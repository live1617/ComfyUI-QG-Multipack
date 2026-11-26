# -*- coding: utf-8 -*-
"""QG_ImageToPrompt —— 图像反推提示词：一张图进去，一段提示词出来。

和 ``QG_PromptTranslate`` 是同一套思路的两头：翻译是「文字 → 文字」，
反推是「图片 → 提示词」，两者都靠 ``translate_core`` 里那份服务商配置
（地址 / 模型 / Key 全在 user 目录的 ``config.json``，插件目录与工作流文件里都不落密钥）。

为什么不是简单调一次 vision 接口
--------------------------------
反推的效果八成取决于「怎么问」，所以规则预设是节点的一等公民：像素级描述、
Tag 标签流、自然语言短描述、图像编辑指令、视频动态提示词各有一套观察顺序和
成文格式。自定义规则开关打开时用用户自己的规则整段替换预设——不是追加，
追加会让两套互相矛盾的格式指令打架。

几个必须照做、否则一定踩坑的细节
--------------------------------
* **system 必须单独占一个 role**。智谱 GLM-4V 这类服务对 role 有硬要求，
  把规则塞进 user 的 content 数组里会直接 400；user 里只放一句
  "Please analyze this image." 和图片。
* **图片先压再发**。ComfyUI 的 IMAGE 是 0~1 浮点，边长动辄两千多，原样
  base64 出去单张就上 MB，请求会超时或被拒。长边压到 1024、JPEG 质量 75
  是实测甜点；批量帧数越多越要压，否则一次请求几十张直接顶满配额。
* **400 要降级重试**。各家对 ``thinking`` / ``enable_thinking`` /
  ``max_tokens`` 的支持参差不齐，严格的服务商见到不认识的字段就 400。
  依次去掉思考参数、只留 model+messages 重试，比让用户去猜哪家支持什么强。
* **思考链要关掉**。GLM-4.6V 这类模型默认会先输出 ``<think>`` 段，不关的话
  提示词里会混进一大段推理文字。请求里带 ``thinking: disabled``，输出端再
  兜一层剥离，两个都做才稳。
* **种子不是随机的**。它只进 ``IS_CHANGED``：固定种子时同一张图不会重复
  请求（省钱），切成 randomize 就每跑一次重新反推（换措辞）。与原版一致。

批量：IMAGE 是 batch 时逐帧独立调用，合并文本用 ``\\n---\\n`` 分隔，第二个
输出口给出逐帧结果列表；单张时列表就是单元素列表。

多图合并（对齐 MUJUN-2025/ComfyUI-Prompt-Assistant fork，GPL-3.0）
--------------------------------
除主口 ``image`` 外还有 ``image2``~``image9`` 八个 optional 口（前端动态增减）。
任一额外口接入时进入合并模式：全部帧（主图 batch 也会展开）压进**一次**请求，
由模型综合描述输出一条结果；只接主口时行为与原来完全一致。帧数超过模型多图
上限时保留前 N 张并在控制台提示，不中断任务。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np

from . import prompt_rules as _rules
from . import translate_core as _translate

TIMEOUT = 120
MAX_TOKENS = 1024
TEMPERATURE = 0.7
TOP_P = 0.9

# 额外图像输入口数量：image2 ~ image9（与上游 fork 一致）
MAX_EXTRA_IMAGES = 8
EXTRA_IMAGE_KEYS = tuple(f"image{n}" for n in range(2, MAX_EXTRA_IMAGES + 2))

# --------------------------------------------------------------------------
# 规则
# --------------------------------------------------------------------------
# 规则正文不在这里：设置面板 → QG 工具 → 提示词规则（规则管理器）维护
# rules.json，节点下拉读的就是那份数据，改完不用重启。见 prompt_rules.py。
# 下面这个名字只在规则库整组被删空时兜底，保证下拉永远有得选。
FALLBACK_RULE = "像素级描述"
DEFAULT_RULE = FALLBACK_RULE

# 规则内容被清空时的兜底指令，避免 system 只剩一句「不要思考」
EMPTY_RULE_HINT = "详细描述这张图片的画面内容，输出可直接用于 AI 生图的提示词。"

# 反推任务通用附加指令：模型不主动输出推理过程，输出才干净。
NO_THINKING_HINT = "只输出最终提示词，不要输出思考过程、推理步骤或 <think> 标记。"

# --------------------------------------------------------------------------
# 视觉模型清单
# --------------------------------------------------------------------------
# 键必须是 translate_core.PRESETS 里的服务商名（地址与 Key 从那里取），
# 值是这家服务上真能看图的模型。只写确认存在的名字——写错了要到运行时
# 才报 404，不如不写。
VISUAL_MODELS = {
    "Zhipu GLM": ["glm-4.6v-flash", "glm-4.5v", "glm-4v-flash", "glm-4v-plus"],
    "Alibaba Qwen": [
        "qwen3-vl-plus",
        "qwen-vl-max-latest",
        "qwen-vl-plus-latest",
        "qwen2.5-vl-72b-instruct",
    ],
    "SiliconFlow": ["Qwen/Qwen2.5-VL-7B-Instruct"],
    "OpenRouter": [
        "openai/gpt-4o-mini",
        "google/gemini-2.5-flash",
        "qwen/qwen2.5-vl-72b-instruct",
    ],
    "Ollama (local)": ["qwen2.5vl:7b", "llama3.2-vision:11b", "llava:7b"],
}

# 下拉里的显示名。用中文短名是为了横向放得下——节点宽度有限，一个
# 「Zhipu GLM/glm-4.6v-flash」会把右边的箭头挤到看不见。值本身（保存在
# 工作流里的字符串）就是这串显示名，解析时再换回服务商全名。
PROVIDER_LABELS = {
    "Zhipu GLM": "智谱",
    "Alibaba Qwen": "通义",
    "SiliconFlow": "硅基",
    "Ollama (local)": "Ollama",
}
LABEL_TO_PROVIDER = {label: name for name, label in PROVIDER_LABELS.items()}


def _provider_label(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider)


DEFAULT_SERVICE = "智谱/glm-4.6v-flash"


# --------------------------------------------------------------------------
# 服务商与模型
# --------------------------------------------------------------------------

def vision_choices() -> list:
    """视觉服务下拉：内置视觉模型在前，用户自定义服务商在后。

    格式是「服务商/模型」，与 Prompt-Assistant 一致——一眼能看出用哪家的
    哪个模型，而不是只给一个服务商名、模型藏在配置文件里。
    """
    names = []
    seen = set()

    def add(provider: str, model: str) -> None:
        provider = str(provider or "").strip()
        model = str(model or "").strip()
        if not provider or not model:
            return
        item = f"{_provider_label(provider)}/{model}"
        if item not in seen:
            seen.add(item)
            names.append(item)

    for provider, models in VISUAL_MODELS.items():
        for model in models:
            add(provider, model)

    # 自定义服务商：一个服务商可以配多个模型，全部展开成独立选项。没配
    # 模型的跳过——视觉调用必须指名模型。custom 是空地址占位，同样跳过。
    for entry in _translate.list_providers():
        if entry["name"] == "custom":
            continue
        for model in (entry.get("models") or [entry.get("model")]):
            add(entry["name"], model)

    return names or [DEFAULT_SERVICE]


def _known_providers() -> list:
    """所有可能出现在下拉里的服务商名（含中文显示名），长的排前面。

    排序是为了「最长前缀匹配」：OpenRouter 的模型名自带斜杠
    （``openai/gpt-4o-mini``），先匹配短名字会把模型切错。
    """
    names = (set(VISUAL_MODELS) | set(_translate.provider_choices())
             | set(LABEL_TO_PROVIDER))
    return sorted((n for n in names if n), key=len, reverse=True)


def parse_vision_choice(choice: str) -> tuple:
    """把 ``服务商/模型`` 拆开，中文显示名换回服务商全名。

    认不出服务商就原样返回 (名字, "")——调用方会给出「没有模型名」的提示，
    比在这里抛错更容易定位。
    """
    choice = str(choice or "").strip()
    for name in _known_providers():
        prefix = name + "/"
        if choice.startswith(prefix):
            model = choice[len(prefix):].strip()
            return LABEL_TO_PROVIDER.get(name, name), model
    return choice, ""


def resolve_vision_target(choice: str) -> dict:
    """选项 → 实际请求要用的地址、模型、Key。

    Key 的优先级与翻译节点一致：服务商条目自带的 > config.json 里那条
    遗留的单 key。这样老配置不用迁移。
    """
    provider, model = parse_vision_choice(choice)
    if not provider:
        raise ValueError("没有选择视觉服务")
    if not model:
        raise ValueError(
            f"视觉服务「{choice}」没有解析出模型名。下拉里应该是"
            "「服务商/模型」的形式；自定义服务商请在设置面板里填上模型。"
        )
    entry = _translate.resolve_provider(provider)
    url = str(entry.get("api_url") or "").strip()
    if not url:
        raise ValueError(
            f"服务商「{provider}」没有配置 API 地址。打开 设置 → QG 工具 → "
            "API 服务商补上，或者把节点上的视觉服务换成别的。"
        )
    key = str(entry.get("api_key") or "").strip() or _translate.config_api_key()
    return {"provider": provider, "model": model, "api_url": url, "api_key": key}


# --------------------------------------------------------------------------
# 图片 → data URL
# --------------------------------------------------------------------------

def _batch_params(frames: int) -> tuple:
    """按帧数决定压缩档位，照抄原版的分级。

    一帧 1024/75 足够看清发丝和布料纹理；帧数多了再保持这个尺寸，单次请求
    的 base64 体积会线性膨胀，只能牺牲分辨率换不超时。
    """
    if frames <= 1:
        return 1024, 75
    if frames <= 3:
        return 1024, 70
    if frames <= 6:
        return 768, 70
    if frames <= 10:
        return 640, 65
    if frames <= 16:
        return 512, 60
    return 480, 55


def model_max_images(model: str) -> int:
    """按模型名推断一次请求能合并几张图；未知模型给保守默认 10。

    映射口径照搬 MUJUN-2025/ComfyUI-Prompt-Assistant 的
    ``get_model_max_images``（GPL-3.0）：已知系列给宽松上限，末段含视觉
    关键词的兜底放宽，其它一律 10——乐观默认比误杀强，反正真正发请求前
    每帧还要压缩，超限的代价是 413 而不是崩溃。
    """
    name = str(model or "").lower()
    if "gemini" in name or "google" in name:
        return 3000
    if "qwen" in name:
        return 100
    if "glm" in name:
        return 100 if "4.6v" in name else 5
    if "gpt-4" in name or "gpt-5" in name:
        return 100
    if "claude" in name or "grok" in name:
        return 20
    if any(keyword in name for keyword in ("vision", "visual", "vl", "multimodal")):
        return 100
    return 10


def flatten_frames(tensors) -> list:
    """把若干 IMAGE 张量展开成单帧列表。

    每个输入口本身可能是 batch ``[N,H,W,C]``：4 维就逐帧切，3 维整帧收。
    形状认不出的跳过——下游 len(frames)==0 自然会走「没有可反推的图像」。
    """
    frames = []
    for tensor in tensors:
        if tensor is None:
            continue
        shape = tuple(getattr(tensor, "shape", ()) or ())
        if len(shape) == 4:
            for index in range(int(shape[0])):
                frames.append(tensor[index:index + 1])
        elif len(shape) == 3:
            frames.append(tensor)
    return frames


def tensor_to_data_url(image, max_side: int = 1024, quality: int = 75) -> str:
    """一帧 IMAGE（0~1 浮点，HWC）→ ``data:image/jpeg;base64,...``。"""
    from PIL import Image

    array = image
    if hasattr(array, "detach"):
        array = array.detach().cpu().float().numpy()
    array = np.asarray(array, dtype=np.float32)
    if array.ndim == 4:            # 兜底：传进来还是 batch
        array = array[0]
    if array.ndim == 2:            # 灰度
        array = np.stack([array] * 3, axis=-1)
    if array.shape[-1] == 4:       # 带 alpha 的，压到白底
        rgb = array[..., :3]
        alpha = array[..., 3:4]
        array = rgb * alpha + (1.0 - alpha)
    elif array.shape[-1] > 4:
        array = array[..., :3]

    pixels = (np.clip(array, 0.0, 1.0) * 255.0).round().astype(np.uint8)
    pil = Image.fromarray(pixels, mode="RGB")
    if max(pil.size) > max_side:
        pil.thumbnail((max_side, max_side), Image.LANCZOS)
    buffer = io.BytesIO()
    pil.save(buffer, format="JPEG", quality=quality, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return "data:image/jpeg;base64," + encoded


def image_fingerprint(image) -> str:
    """给 ComfyUI 判缓存用：只看缩略图的像素，不看完整张量。

    原版只哈希第一帧的中心区域，batch 里后面的帧改了也判不出变化。这里
    逐帧各取一张 32×32 的采样图，任一帧变化都会换指纹，代价是几十微秒。

    切片放在**搬回 CPU 之前**：GPU 上一个 50 帧的 1080p batch 是 1.2 GB，
    整批 ``.cpu()`` 会把这些字节全拷一遍，而指纹只用得到每帧 32×32 的
    采样点。先 ``frame[::step, ::step]`` 再转，拷贝量降到千分之一。

    形状认不出来时返回一个每次都不同的值（时间戳），让节点重跑——这一步
    失败说明上游给了意外的东西，复用一个可能对不上的旧结果更糟。
    """
    if image is None:
        return "0"
    try:
        frames = image.detach() if hasattr(image, "detach") else image
        ndim = len(tuple(getattr(frames, "shape", ()) or ()))
        if ndim == 3:
            frames = frames[None]
        elif ndim != 4:
            return "x%.6f" % time.time()
        digest = []
        for frame in frames:
            height, width = int(frame.shape[0]), int(frame.shape[1])
            step = max(1, min(height, width) // 32)
            small = frame[::step, ::step]
            if hasattr(small, "detach"):
                small = small.detach().cpu().float().numpy()
            small = np.asarray(small, dtype=np.float32)
            if small.ndim == 3:
                small = small.mean(axis=2)
            digest.append(hashlib.md5(
                np.ascontiguousarray(small, dtype=np.float32).tobytes()
            ).hexdigest())
        if not digest:
            return "x%.6f" % time.time()
        return hashlib.md5("|".join(digest).encode("ascii")).hexdigest()
    except Exception:  # noqa: BLE001 - 指纹算不出来就当作每次都变
        return "x%.6f" % time.time()


# --------------------------------------------------------------------------
# 请求
# --------------------------------------------------------------------------

class _HTTPFailure(RuntimeError):
    """带状态码的 HTTP 失败，用来判断值不值得降级重试。"""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = int(code)


def _thinking_payload(model: str) -> dict:
    """各家关思考的参数不一样，只对已知支持的发。

    多发的代价是一次 400 加一轮降级——能用，但白等十几秒。所以宁可窄一点：
    没把握就不发，靠 system 里的「不要输出思考过程」兜着。
    """
    name = str(model or "").lower()
    if re.search(r"glm[-_/.]?(4\.5|4\.6|4\.7|5)", name):
        return {"thinking": {"type": "disabled"}}
    if re.search(r"qwen.*vl|qwen[-_/.]?3", name):
        return {"enable_thinking": False}
    if re.search(r"deepseek[-_/.]?(chat|v3)", name):
        return {"thinking": {"type": "disabled"}}
    if re.search(r"gemini[-_/.]?2\.(0|5)[-_/.]?(flash|lite)", name):
        return {"reasoning_effort": "none"}
    return {}


def _build_messages(system_text: str, image_data: str) -> list:
    """system 独立一条，user 里只放一句话和图片。

    这不是风格问题：智谱 GLM-4V 要求 system 与 user 严格分离，把规则塞进
    user 的 content 数组会 400。
    """
    return [
        {"role": "system", "content": system_text},
        {
            "role": "user",
            "content": [
                # 这句只是「触发分析」的引子，具体要什么全在 system 里。
                # 用中文而不是英文：默认输出语言是中文，一句英文的
                # "Please analyze this image." 会把模型往英文上带。
                {"type": "text", "text": "请分析这张图片。"},
                {"type": "image_url", "image_url": {"url": image_data}},
            ],
        },
    ]


def _build_multi_messages(system_text: str, image_data_list: list) -> list:
    """多图合并版消息体：所有图放进同一条 user 消息做综合描述。

    与单图版同样的约束：system 单独一条（GLM-4V 硬要求），user 里只放一句
    引子加图片数组。图与图之间没有分隔文字——有些模型会把分隔符当成正文
    一起描述，交给模型自己判断更稳。
    """
    content = [{"type": "text", "text": "请分析这些图片。"}]
    for image_data in image_data_list:
        content.append({"type": "image_url", "image_url": {"url": image_data}})
    return [
        {"role": "system", "content": system_text},
        {"role": "user", "content": content},
    ]


def _opener(url: str):
    """本地地址绕过系统代理。

    Ollama 在 127.0.0.1 时走系统代理会被代理应答成 502，这个坑在设置面板
    和两个节点上都出现过。
    """
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host in ("127.0.0.1", "localhost", "::1"):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def _headers(key: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    return headers


def _post(url: str, key: str, payload: dict) -> dict:
    """一次 POST，返回解析后的 JSON。"""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=_headers(key),
        method="POST",
    )
    try:
        with _opener(url).open(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            detail = _translate.redact_secrets(
                error.read().decode("utf-8", "replace")[:400], (key,))
        except Exception:  # noqa: BLE001 - 错误正文是尽力而为
            pass
        raise _HTTPFailure(error.code, detail or str(error)) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"连不上模型服务：{error.reason}。检查网络、代理和 API 地址。"
        ) from error
    except OSError as error:  # 含超时
        raise RuntimeError(
            f"模型服务请求失败（{TIMEOUT} 秒超时或连接中断）：{error}"
        ) from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"模型服务返回的不是 JSON：{error}") from error


# --------------------------------------------------------------------------
# 流式输出
# --------------------------------------------------------------------------

# 前端监听的事件名（web/qg_stream.js 里同名）
STREAM_EVENT = "qg-vlm-stream"


def _content_of(part) -> str:
    """OpenAI 的 content 有时是字符串，有时是 [{type, text}] 数组。"""
    if isinstance(part, list):
        return "".join(
            str(item.get("text") or "") if isinstance(item, dict) else str(item)
            for item in part)
    return str(part or "")


def _delta_text(chunk: dict) -> str:
    """一条流式 chunk 里新增的那段文本。"""
    try:
        choice = chunk["choices"][0]
    except (KeyError, IndexError, TypeError):
        return ""
    delta = choice.get("delta")
    if isinstance(delta, dict):
        return _content_of(delta.get("content"))
    return ""


def _message_text(chunk: dict) -> str:
    """有些服务在 SSE 里只发完整 message（不发 delta），用它兜底。"""
    try:
        choice = chunk["choices"][0]
    except (KeyError, IndexError, TypeError):
        return ""
    message = choice.get("message")
    if isinstance(message, dict):
        return _content_of(message.get("content"))
    return ""


def _post_stream(url: str, key: str, payload: dict, on_delta=None) -> str:
    """流式调用，边收边回调；返回拼好的完整文本。

    服务端不认 ``stream`` 时（返回 application/json 整包）也能工作：按
    Content-Type 判断一次，直接把它当普通响应读。判断放在响应头而不是
    首行，是因为有些中转站把 SSE 也标成 text/plain。
    """
    body = dict(payload)
    body["stream"] = True
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=_headers(key),
        method="POST",
    )
    try:
        with _opener(url).open(request, timeout=TIMEOUT) as response:
            ctype = str(response.headers.get("Content-Type") or "").lower()
            if "event-stream" not in ctype and "json" in ctype:
                # 整包 JSON：不支持流式的服务
                text = _extract_text(json.loads(response.read().decode("utf-8")))
                if on_delta:
                    on_delta(text)
                return text

            text = ""
            fallback = ""
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    obj = json.loads(chunk)
                except ValueError:
                    continue
                piece = _delta_text(obj)
                if piece:
                    text += piece
                    # 回调抛异常不能打断取流：预览只是锦上添花
                    if on_delta:
                        try:
                            on_delta(text)
                        except Exception:  # noqa: BLE001
                            pass
                elif not fallback:
                    fallback = _message_text(obj)
            if not text:
                text = fallback
            if not text:
                raise RuntimeError(
                    "流式响应里没有取到任何文本，这条服务可能不支持 stream。")
            return text
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            detail = _translate.redact_secrets(
                error.read().decode("utf-8", "replace")[:400], (key,))
        except Exception:  # noqa: BLE001
            pass
        raise _HTTPFailure(error.code, detail or str(error)) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"连不上模型服务：{error.reason}。检查网络、代理和 API 地址。"
        ) from error
    except OSError as error:  # 含超时
        raise RuntimeError(
            f"模型服务请求失败（{TIMEOUT} 秒超时或连接中断）：{error}"
        ) from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"模型服务返回的不是 JSON：{error}") from error


def stream_pusher(label: str = "反推"):
    """把中间结果推给前端画布上的节点预览。

    返回 ``push(text, done=False)``；脱离 ComfyUI（单测）或拿不到当前节点
    时返回 ``None``，调用方自动退回「只出最终结果」。

    ``label`` 决定气泡标题（「反推中…」/「优化中…」），前端读事件里的
    同名字段；不给就用「反推」，保持老行为。
    """
    # 只在 server 已经被 ComfyUI 加载过时才用，不主动 import：在单测或别的
    # 宿主进程里 import server 会连带拉起整个 ComfyUI（torch 之类），既慢又
    # 可能直接段错误——推个进度远不值得付这个代价。
    try:
        server_module = sys.modules.get("server")
        instance = getattr(
            getattr(server_module, "PromptServer", None), "instance", None)
        node_id = getattr(instance, "last_node_id", None) if instance else None
        if instance is None or node_id is None:
            return None
    except Exception:  # noqa: BLE001 - 没有 ComfyUI 的 server 模块
        return None

    state = {"at": 0.0, "sent": 0}

    def push(text: str, done: bool = False) -> None:
        now = time.monotonic()
        # 限流：模型吐字很快，每字推一次会把 websocket 和画布塞满。
        # 要么过了 80ms，要么新增了 24 个字，才推一次。
        if not done:
            if now - state["at"] < 0.08 and len(text) - state["sent"] < 24:
                return
        state["at"] = now
        state["sent"] = len(text)
        try:
            instance.send_sync(STREAM_EVENT, {
                "node": str(node_id),
                "text": text,
                "done": bool(done),
                "label": label,
            })
        except Exception:  # noqa: BLE001 - 推流失败不该让节点执行失败
            pass

    return push


def _explain(failure: _HTTPFailure, model: str, vision: bool = True) -> str:
    """把状态码翻成人话，附上各家自己的错误正文。"""
    code = failure.code
    # detail 在 _post / _post_stream 里已脱敏，这里再兜一层：异常也可能由
    # 别处构造，直接把原始消息推到画布 / 日志同样有漏 Key 的风险。
    raw = _translate.redact_secrets(str(failure).strip())
    what = "看图" if vision else "处理这段文本"
    hints = {
        400: f"请求被拒绝：该服务可能不支持模型「{model}」{what}，或某个参数不被接受。",
        401: "鉴权失败：API Key 不对或没填。到 设置 → QG 工具 → API 服务商 里补上。",
        403: "没有权限：这个 Key 可能没开通该模型，或额度已用尽。",
        404: "地址或模型不存在：检查服务商地址是否为 chat/completions 接口。",
        413: "内容太大被拒：把输入缩短后再试。",
        429: "该模型当前排队/限流（智谱常见 1305「访问量过大」），"
             "稍等一会儿再试，或换同家的另一个模型。",
    }
    hint = hints.get(code, f"模型服务返回 HTTP {code}。")
    return f"{hint}（接口原文：{raw}）" if raw else hint


def _extract_text(payload: dict) -> str:
    """取 ``choices[0].message.content``，兼容 content 是数组的写法。"""
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError(
            "模型服务返回了响应，但不是 OpenAI chat 格式（没有 "
            "choices[0].message.content）。确认地址指向 chat/completions。"
        ) from error
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(item))
        content = "".join(parts)
    return str(content or "")


def clean_answer(text: str) -> str:
    """剥掉思考段、Markdown 围栏和一层包裹引号。

    实现在 ``translate_core.clean_answer``。两个翻译节点和这里必须用同一套
    清洗：早先这里有一份、那边没有，结果反推/优化的输出是干净的，翻译节点
    却会把 ``` 和思考段原样吐给用户。同一个包内不要再留两份实现。
    """
    return _translate.clean_answer(text)


def ask_vision(system_text: str, image_data: str, target: dict, on_delta=None) -> str:
    """一次反推：构造身体 → 逐级降级 → 取文本。

    ``on_delta`` 给了就走流式，边收边回调（前端节点上的实时预览）；没给
    就等整段返回。两条路的后备与降级逻辑完全一样。
    """
    return _ask(_build_messages(system_text, image_data), target, on_delta,
                vision=True)


def _text_messages(system_text: str, user_text: str) -> list:
    """纯文本任务的消息体：system 放规则，user 放待处理的正文。

    不在这里加「请优化下面这段」之类的引导句——那会把「待处理的内容」和
    「对模型的指令」混成一条，模型有时会开始回答正文里的问题（比如正文是
    「一个女孩在问 what is this」）。规则里已经交代清楚 user 消息是什么。
    """
    return [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_text},
    ]


def ask_text(system_text: str, user_text: str, target: dict, on_delta=None) -> str:
    """纯文本调用，复用反推那套流式与 400 降级。

    ``QG_PromptOptimize`` 用它。两个节点共用同一份重试逻辑，省得两边各自
    演化——之前翻译节点和反推节点就吃过这种苦：一处修好了，另一处还是老
    行为。
    """
    return _ask(_text_messages(system_text, user_text), target, on_delta,
                vision=False)


def _ask(messages: list, target: dict, on_delta=None, vision: bool = True) -> str:
    """公共调用：逐级降级重试，返回模型原文。"""
    base = {
        "model": target["model"],
        "messages": messages,
        "temperature": TEMPERATURE,
        "top_p": TOP_P,
        "max_tokens": MAX_TOKENS,
        "stream": False,
    }
    thinking = _thinking_payload(target["model"])

    def call(payload: dict) -> str:
        if on_delta:
            return _post_stream(
                target["api_url"], target["api_key"], payload, on_delta)
        return _extract_text(_post(target["api_url"], target["api_key"], payload))

    # Level 0 完整；Level 1 去思考参数；Level 2 只留 model + messages。
    # 只对 400 降级——401/429 这些降级也没用，早点把原因告诉用户。
    levels = []
    if thinking:
        levels.append({**base, **thinking})
    levels.append(dict(base))
    levels.append({"model": base["model"], "messages": messages})

    last = None
    for index, payload in enumerate(levels):
        try:
            return call(payload)
        except _HTTPFailure as failure:
            last = failure
            can_retry = failure.code == 400 and index + 1 < len(levels)
            if not can_retry:
                if failure.code == 429 and index == 0:
                    # 限流等 3 秒再来一次，不值得继续降级
                    time.sleep(3)
                    try:
                        return call(payload)
                    except _HTTPFailure as again:
                        raise RuntimeError(
                            _explain(again, target["model"], vision)) from again
                raise RuntimeError(
                    _explain(failure, target["model"], vision)) from failure
            print(f"[QG-LLM] HTTP 400，去掉可选参数重试（第 {index + 1} 级）")
    raise RuntimeError(_explain(last, target["model"], vision)) from last


# --------------------------------------------------------------------------
# 本地 Ollama 释放显存
# --------------------------------------------------------------------------

def release_local_model(provider: str, model: str) -> None:
    """反推完把本地 Ollama 的模型请出显存；云端服务安静跳过。"""
    if not provider or not model:
        return
    entry = _translate.resolve_provider(provider)
    parsed = urllib.parse.urlparse(str(entry.get("api_url") or ""))
    host = (parsed.hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        return
    base = f"{parsed.scheme or 'http'}://{parsed.hostname}:{parsed.port or 11434}"
    body = json.dumps({"model": model, "keep_alive": 0}).encode("utf-8")
    request = urllib.request.Request(
        base + "/api/generate", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=15):
            pass
    except Exception as error:  # noqa: BLE001 - 卸载失败不影响结果
        print(f"[QG-ImageToPrompt] 释放 Ollama 模型失败（不影响结果）：{error}")


# --------------------------------------------------------------------------
# 节点
# --------------------------------------------------------------------------

class QGImageToPrompt:
    """图像 → 提示词。单张出文本，batch 出合并文本 + 逐帧列表。"""

    CATEGORY = "QG 工具"
    SEARCH_ALIASES = [
        "image to prompt", "图像反推", "反推提示词", "图片反推", "识图",
        "caption", "vlm", "vision", "describe image", "glm-4v", "qwen-vl",
        "prompt from image", "qg",
    ]

    @classmethod
    def INPUT_TYPES(cls):
        # 规则来自 rules.json（设置面板的规则管理器），这里只负责把名字列出来。
        # 列表里额外带上改名前的旧名：ComfyUI 提交工作流时会按这个列表校验，
        # 少了旧名，存量工作流会在校验阶段就被拒（Value not in list），走不到
        # 执行里的别名匹配。前端下拉只用纯名字，所以界面上看不到旧名。
        rules = _rules.node_rule_choices() or [FALLBACK_RULE]
        current = _rules.active("image")
        default_rule = current["name"] if current and current["name"] in rules else rules[0]
        services = vision_choices()
        default = DEFAULT_SERVICE if DEFAULT_SERVICE in services else services[0]
        return {
            "required": {
                "image": (
                    "IMAGE",
                    {
                        "tooltip": (
                            "要反推的图片。接 batch 时逐帧独立反推，合成文本用 "
                            "--- 分隔，第二个输出口给出逐帧结果。"
                        ),
                    },
                ),
                "rule": (
                    rules,
                    {
                        "default": default_rule,
                        "tooltip": (
                            "反推规则，来自 设置 → QG 工具 → 提示词规则。不同规则"
                            "观察的重点和成文格式完全不同：像素级描述出长段落，"
                            "Tag 标签流出逗号标签，图像编辑指令配合 user prompt "
                            "出改动指令。想改措辞或加一条新规则，去设置面板里改，"
                            "这里会自动跟着变。"
                        ),
                    },
                ),
                "custom_rule": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "label_on": "Enable",
                        "label_off": "Disable",
                        "tooltip": (
                            "打开后用下面的「自定义规则」整段替换上面的预设规则"
                            "（不是追加）。适合固定一种输出格式反复使用。"
                        ),
                    },
                ),
                "custom_rule_content": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": (
                            "自定义规则内容，只在「自定义规则」打开时生效。"
                            "写清观察顺序和输出格式，比如「只输出英文标签，"
                            "逗号分隔，不要句子」。"
                        ),
                    },
                ),
                "user_prompt": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": (
                            "附加要求，会拼在规则后面一起发给模型。比如"
                            "「重点描述服装材质」「这是要换成夜景」。"
                            "「图像编辑指令」规则靠它说明要改什么。"
                        ),
                    },
                ),
                "vlm_service": (
                    services,
                    {
                        "default": default,
                        "tooltip": (
                            "用哪家的视觉模型。列表是「服务商/模型」：地址与 Key "
                            "取自 设置 → QG 工具 → API 服务商，节点上只选名字。"
                            "想用清单外的模型，就在设置面板里加一个服务商条目，"
                            "填上模型名，它会出现在这里。"
                        ),
                    },
                ),
                "auto_unload": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "label_on": "Enable",
                        "label_off": "Disable",
                        "tooltip": (
                            "反推完立刻把本地 Ollama 的视觉模型请出显存，给后面"
                            "的采样器腾地方。云端服务忽略这个开关。"
                        ),
                    },
                ),
                "seed": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 0xffffffffffffffff,
                        "control_after_generate": True,
                        "tooltip": (
                            "不影响确定性，只控制节点要不要重跑。固定时同一张图"
                            "复用上次结果、不重复扣费；切成 randomize 就每跑一次"
                            "重新反推，用来换一种措辞。"
                        ),
                    },
                ),
            },
            "optional": {
                **{
                    key: (
                        "IMAGE",
                        {
                            "tooltip": (
                                "可选的额外图片。接入任意一个后，所有已连接的图"
                                "（含主口 batch 的全部帧）会合并进一次请求，由"
                                "模型综合描述输出一条结果；只接主口时保持原有"
                                "行为。前端会随连接自动增减这些口。"
                            ),
                        },
                    )
                    for key in EXTRA_IMAGE_KEYS
                },
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("提示词输出", "提示词列表")
    OUTPUT_TOOLTIPS = (
        "反推得到的提示词；batch 时是各帧结果用 --- 连接。",
        "逐帧结果列表；单张时只有一个元素。",
    )
    OUTPUT_IS_LIST = (False, True)
    FUNCTION = "execute"

    @classmethod
    def IS_CHANGED(cls, image=None, rule="", custom_rule=False,
                   custom_rule_content="", user_prompt="", vlm_service="",
                   auto_unload=True, seed=0, **kwargs):
        """图、规则、服务或种子变了才重跑。

        用 md5 拼而不是内置 ``hash()``：字符串 hash 每个进程带随机盐，重启
        ComfyUI 后同一个值算出来不一样，节点会被判成「变了」白跑一次。

        ``rule`` 是规则**名字**，正文在 rules.json 里。只拼名字的话，用户在
        规则管理器里改措辞（名字不变）时 ComfyUI 会认为输入没变、直接复用
        上次输出，规则改了等于没改。再拼一个规则库指纹兜住这种情况。

        ``image2``~``image9`` 逐个算指纹拼进去（未连接是 None，指纹为固定
        值）：换哪一张额外图、或接上/断开某个口，都会正确触发重新反推。
        """
        blob = "\x1f".join([
            image_fingerprint(image),
            *[image_fingerprint(kwargs.get(key)) for key in EXTRA_IMAGE_KEYS],
            str(rule), str(bool(custom_rule)),
            hashlib.md5(str(custom_rule_content or "").encode("utf-8")).hexdigest(),
            hashlib.md5(str(user_prompt or "").encode("utf-8")).hexdigest(),
            str(vlm_service), str(bool(auto_unload)), str(seed),
            _rules.fingerprint(),
        ])
        return hashlib.md5(blob.encode("utf-8")).hexdigest()

    def execute(self, image, rule, custom_rule, custom_rule_content,
                user_prompt, vlm_service, auto_unload=True, seed=0, **kwargs):
        extras = [kwargs.get(key) for key in EXTRA_IMAGE_KEYS]
        if image is None and not any(e is not None for e in extras):
            raise RuntimeError(
                "QG 图像反推：没有图片输入。把 Load Image 之类的输出接到 image 上，"
                "或多图场景把图接进 image2~image9。")

        # 全部输入展开成单帧列表（主口 batch 也展开）。全空才报空——主口空
        # 批次但额外口有图时，合并模式照常能跑。
        frames = flatten_frames([image, *extras])
        if not frames:
            print("[QG-ImageToPrompt] 图像批次为空（0 帧），没有可反推的图像。")
            push = stream_pusher()
            if push:
                push("没有可反推的图像（0 帧）", done=True)
            return ("", [])

        target = resolve_vision_target(vlm_service)

        # 规则：自定义开着就用用户的整段规则，否则按名字去规则库里取。
        # 名字找不到（用户改过名、删过规则、工作流来自别人）时不报错，
        # 退回该组激活的那条并打一行提示——存量的工作流不该因为改名就跑不动。
        if custom_rule and str(custom_rule_content or "").strip():
            system_text = str(custom_rule_content).strip()
            rule_name = "自定义规则"
        else:
            picked, fell_back = _rules.resolve(rule, ("optimize", "image", "video"))
            system_text = (picked or {}).get("content") or EMPTY_RULE_HINT
            rule_name = (picked or {}).get("name") or str(rule)
            if fell_back and str(rule or "").strip() and str(rule) != rule_name:
                print(f"[QG-ImageToPrompt] 规则「{rule}」不在规则库里，"
                      f"改用「{rule_name}」。可在 设置 → QG 工具 → 提示词规则 里核对。")
        extra = str(user_prompt or "").strip()
        if extra:
            system_text = system_text + "\n\n" + extra
        system_text = system_text + "\n\n" + NO_THINKING_HINT

        # 多图模式：任一额外口接入 → 全部帧合并进一次请求，输出一条综合描述。
        # 只接主口时保持原行为（单张直接反推，batch 逐帧独立反推）。
        multi = any(e is not None for e in extras)
        push = stream_pusher()

        if multi:
            limit = model_max_images(target["model"])
            if len(frames) > limit:
                print(f"[QG-ImageToPrompt] 多图反推 | 共 {len(frames)} 帧超过"
                      f"模型「{target['model']}」的多图上限 {limit}，已截断，"
                      f"忽略后 {len(frames) - limit} 张。")
                frames = frames[:limit]
            max_side, quality = _batch_params(len(frames))
            print(f"[QG-ImageToPrompt] {rule_name} · {vlm_service} · "
                  f"多图合并 {len(frames)} 张 · 长边 {max_side}px")
            try:
                data_urls = [
                    tensor_to_data_url(frame, max_side=max_side, quality=quality)
                    for frame in frames
                ]
                on_delta = None
                if push:
                    on_delta = lambda text: push(clean_answer(text))  # noqa: E731
                answer = clean_answer(_ask(
                    _build_multi_messages(system_text, data_urls),
                    target, on_delta, vision=True))
                if not answer:
                    raise RuntimeError(
                        f"视觉模型「{target['model']}」返回了空结果。"
                        "可能是模型只输出了思考过程，或该模型不支持图像输入。")
                if push:
                    push(answer, done=True)
            except Exception as error:
                if push:
                    push("反推失败：%s" % error, done=True)
                raise
            if auto_unload:
                release_local_model(target["provider"], target["model"])
            return (answer, [answer])

        # 原行为：单张 / 主口 batch 逐帧独立反推
        batch = getattr(image, "shape", ()) and len(image.shape) == 4 and image.shape[0] > 1
        frame_count = int(image.shape[0]) if batch else 1
        max_side, quality = _batch_params(frame_count)

        print(f"[QG-ImageToPrompt] {rule_name} · {vlm_service} · "
              f"{frame_count} 帧 · 长边 {max_side}px")

        results = []
        # 边收边推给画布上的节点预览；拿不到前端（单测 / 无 server）就是 None
        try:
            for index in range(frame_count):
                frame = image[index:index + 1] if batch else image
                data_url = tensor_to_data_url(frame, max_side=max_side, quality=quality)
                prefix = f"第 {index + 1}/{frame_count} 帧\n" if frame_count > 1 else ""
                if frame_count > 1:
                    print(f"[QG-ImageToPrompt] 第 {index + 1}/{frame_count} 帧…")

                on_delta = None
                if push:
                    def on_delta(text, _prefix=prefix):
                        push(_prefix + clean_answer(text))

                answer = clean_answer(ask_vision(system_text, data_url, target, on_delta))
                if not answer:
                    raise RuntimeError(
                        f"视觉模型「{target['model']}」返回了空结果。"
                        "可能是模型只输出了思考过程，或该模型不支持图像输入。")
                results.append(answer)
                if push:
                    push(prefix + answer, done=(index == frame_count - 1))
        except Exception as error:
            # 失败也发一次 done，否则前端那条「反推中…」会一直挂着
            if push:
                push("反推失败：%s" % error, done=True)
            raise

        if auto_unload:
            release_local_model(target["provider"], target["model"])

        if len(results) == 1:
            return (results[0], results)
        return ("\n---\n".join(results), results)


NODE_CLASS_MAPPINGS = {"QG_ImageToPrompt": QGImageToPrompt}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_ImageToPrompt": "QG 图像反推提示词"}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
