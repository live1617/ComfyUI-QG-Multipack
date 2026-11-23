# -*- coding: utf-8 -*-
"""翻译核心 —— 服务商预设、config.json 读写、HTTP 调用与缓存。

这个模块只做「怎么把一段文字翻过去」，不定义任何节点。两个节点共用它：

* ``QG_Translate``（translate_node.py）—— 通用翻译器，源语言 / 目标语言 /
  地址 / 模型 / Key 全摊在节点上；
* ``QG_PromptTranslate``（prompt_translate_node.py）—— 提示词翻译，
  四个控件，中文进英文出。

**节点层是外壳**。删掉 translate_node.py 不会影响这里的配置读写、缓存、
设置面板（``/qg_translate/*`` 直接绑在本模块上），也不会影响提示词翻译。

为什么存在
----------
开放词表检测（SAM 3 这类）只读英文，而免费 Google 翻译端点一拥就 HTTP 429。
几乎每家模型厂商都提供 OpenAI 兼容的 ``/chat/completions``，所以一个客户端
就能覆盖 DeepSeek、Kimi、通义千问、智谱 GLM、SiliconFlow、OpenRouter 和
本地 Ollama —— 用户选一家，地址与模型自动填好，配置文件里一行 Key。

设计取舍
--------
* **零依赖**：只用标准库 urllib，任何环境都能导入、脱离 ComfyUI 也能测。
* **Key 不必进工作流，也不进插件目录**：``config.json`` 存在
  ``ComfyUI/user/ComfyUI-QG-Multipack/``（首次运行自动从插件目录旧位置
  迁移过去），插件目录整个打包分享也不带密钥，workflow JSON 同样不含。
* **同样的原文只翻一次**：进程内缓存，重跑工作流不重复扣费。
* **本地地址不走代理**：Ollama 在 127.0.0.1 时绕过系统代理，否则请求会被
  代理应答成 502。
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

# 设置面板可能被两个标签页同时打开，两次保存撞在一起时共用一个固定名字的
# 临时文件会写成交错的半份 JSON（然后把整份配置读成 {}，Key 全丢）。
# 锁 + 唯一临时文件两头都堵上。用 RLock 是因为 config_api_key() 会在锁内
# 再调 save_config()，普通 Lock 会把同一线程自己锁死。
_CONFIG_LOCK = threading.RLock()

# --- vendor presets -------------------------------------------------------
# Every entry speaks the OpenAI chat-completions dialect; "custom" means the
# user fills api_url and model themselves.
#
# ``model`` 是默认模型，``models`` 是这家厂商常用的一组（节点下拉会全部列
# 出来）。两者都要有：``model`` 供老代码与「没选具体模型」时兜底，``models``
# 决定下拉里能看到几个选项。
PRESETS = {
    "custom": {"api_url": "", "model": "", "models": []},
    "DeepSeek": {
        "api_url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "Moonshot Kimi": {
        "api_url": "https://api.moonshot.cn/v1/chat/completions",
        "model": "kimi-k2-0905-preview",
        "models": ["kimi-k2-0905-preview", "kimi-k2-turbo-preview"],
    },
    "Alibaba Qwen": {
        "api_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen-plus",
        "models": ["qwen-plus", "qwen-max", "qwen-turbo", "qwen3-vl-plus"],
    },
    "Zhipu GLM": {
        "api_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-4-flash",
        "models": ["glm-4-flash", "glm-4.5", "glm-4.5v", "glm-4.6v-flash"],
    },
    "SiliconFlow": {
        "api_url": "https://api.siliconflow.cn/v1/chat/completions",
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "models": ["Qwen/Qwen2.5-7B-Instruct", "deepseek-ai/DeepSeek-V3"],
    },
    "OpenRouter": {
        "api_url": "https://openrouter.ai/api/v1/chat/completions",
        "model": "openai/gpt-4o-mini",
        "models": [
            "openai/gpt-4o-mini",
            "google/gemini-2.5-flash",
            "qwen/qwen2.5-vl-72b-instruct",
        ],
    },
    "Ollama (local)": {
        "api_url": "http://127.0.0.1:11434/v1/chat/completions",
        "model": "qwen2.5:7b",
        "models": ["qwen2.5:7b", "llama3.2-vision:11b"],
    },
}
PROVIDERS = list(PRESETS)

# --- 用户自己的服务商条目 ------------------------------------------------
# 内置预设只覆盖几个常见厂商；用户真正在用的往往是自建代理、中转站、
# 或者同一个厂商的两个 key。这些存在 config.json 的 "providers" 里，
# 由设置面板增删改，节点上的 provider 下拉直接列出它们的名字。
# 每条：{"id": "...", "name": "...", "api_url": "...", "model": "...", "api_key": "..."}
CONFIG_NAME = "config.json"
# 掩码里的固定后缀：前端原样提交回来时，后端据此判断「没改过，保留原 key」
KEY_MASK = "****"

_config_cache = {"stamp": None, "data": {}}

LANGUAGES = (
    "auto",
    "chinese",
    "english",
    "japanese",
    "korean",
    "french",
    "german",
    "spanish",
    "russian",
)
LANG_NAMES = {
    "auto": "",
    "chinese": "Chinese",
    "english": "English",
    "japanese": "Japanese",
    "korean": "Korean",
    "french": "French",
    "german": "German",
    "spanish": "Spanish",
    "russian": "Russian",
}

IF_FAIL = ("output original", "stop the run")

TIMEOUT = 60
# How many translations to remember. The entries are small; a plain clear at
# the cap keeps this honest without an LRU dependency.
CACHE_MAX = 256
_CACHE: dict = {}

MISSING_TEXT = (
    "QG 翻译：没有可翻译的文字。在文本框里输入内容，或接一个文字输出进来。"
)
BAD_REPLY = (
    "QG 翻译：接口有响应，但不是 OpenAI 对话格式（找不到 "
    "choices[0].message.content）。检查接口地址是不是 chat/completions，"
    "以及这个模型在服务上是否存在。"
)


_PACK_DIR = os.path.dirname(os.path.abspath(__file__))


def _legacy_config_path() -> str:
    """旧版位置：插件目录里的 config.json（1.0 之前一直放这里）。"""
    return os.path.join(_PACK_DIR, CONFIG_NAME)


def _config_dir() -> str:
    """config.json 的目录：优先 ComfyUI user 目录下的 ``ComfyUI-QG-Multipack/``。

    放 user 目录是为了让插件目录可以整个打包分享 —— Key 这类敏感信息
    不再混在插件文件里（与 QG-tools 的 ``user/QG-tools/`` 惯例一致）。
    拿不到 user 目录（裸进程跑单测、极端精简环境）时退回插件目录。
    """
    try:
        from folder_paths import get_user_directory

        base = os.path.join(get_user_directory(), "ComfyUI-QG-Multipack")
    except Exception:  # noqa: BLE001 - 任何导入/查找失败都走降级
        return _PACK_DIR
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        return _PACK_DIR
    return base


def _config_path() -> str:
    path = os.path.join(_config_dir(), CONFIG_NAME)
    if os.path.exists(path):
        return path
    # 首次升级：把插件目录里的旧 config.json 搬进 user 目录。
    # os.replace 同盘是原子移动，成功后旧文件自然消失；搬不动就继续用旧位置。
    legacy = _legacy_config_path()
    if os.path.exists(legacy):
        try:
            os.replace(legacy, path)
        except OSError:
            return legacy
    return path


def load_config() -> dict:
    """config.json as a dict; a missing or broken file reads as {}.

    Cached on (mtime, size) so the node can call this per run without
    touching the disk twice - the file only changes when the settings panel
    saves it.
    """
    path = _config_path()
    try:
        stat = os.stat(path)
    except OSError:
        return {}
    stamp = (stat.st_mtime_ns, stat.st_size)
    if _config_cache["stamp"] == stamp:
        return dict(_config_cache["data"] or {})
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:  # noqa: BLE001 - a broken file must not break the node
        return {}
    if not isinstance(data, dict):
        data = {}
    _config_cache["stamp"] = stamp
    _config_cache["data"] = data
    return dict(data)


def save_config(data: dict) -> dict:
    """Write config.json atomically and drop the read cache.

    临时文件名由 NamedTemporaryFile 生成（不是固定的 ``config.json.tmp``），
    再配一把进程内的锁：两个标签页同时点保存时，各自写各自的临时文件，
    最后一次 ``os.replace`` 生效，磁盘上不会出现两份内容交错的 JSON。
    """
    data = dict(data or {})
    path = _config_path()
    with _CONFIG_LOCK:
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=os.path.dirname(path),
            prefix=".config-", suffix=".json", delete=False)
        try:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, path)
    _config_cache["stamp"] = None
    _config_cache["data"] = {}
    return data


MAX_MODELS = 30
MAX_MODEL_LEN = 200


def _clean_models(raw, fallback: str = "") -> list:
    """模型列表：去空、去重、限长。

    ``fallback`` 是旧的单模型字段。老配置只有 ``model`` 没有 ``models``，
    直接把它当成只有一项的列表，不需要额外的迁移步骤。
    """
    out = []
    values = raw if isinstance(raw, (list, tuple)) else []
    for item in values:
        model = str(item or "").strip()[:MAX_MODEL_LEN]
        if model and model not in out:
            out.append(model)
    fallback = str(fallback or "").strip()[:MAX_MODEL_LEN]
    if fallback and fallback not in out:
        out.insert(0, fallback)
    return out[:MAX_MODELS]


def _clean_provider(raw, index: int = 0) -> dict:
    """One provider entry, trimmed and type-safe.

    一个服务商可以挂多个模型：``models`` 是全部，``default_model`` 是没选
    具体模型时用的那个。``model`` 仍然保留为默认模型的镜像——老的节点代码
    和老的配置文件都只认这一个字段。
    """
    raw = raw if isinstance(raw, dict) else {}
    pid = str(raw.get("id") or "").strip()[:40] or "p%d" % (index + 1)
    legacy_model = str(raw.get("model") or "").strip()[:MAX_MODEL_LEN]
    models = _clean_models(raw.get("models"), legacy_model)
    default_model = str(raw.get("default_model") or "").strip()[:MAX_MODEL_LEN]
    if default_model not in models:
        if models:
            default_model = models[0]
        else:
            default_model = ""
    return {
        "id": pid,
        "name": str(raw.get("name") or "").strip()[:60],
        "api_url": str(raw.get("api_url") or "").strip()[:500],
        "model": default_model,
        "models": models,
        "default_model": default_model,
        "api_key": str(raw.get("api_key") or "").strip()[:400],
    }


def list_providers(with_key: bool = False) -> list:
    """The user's own providers, in the order the settings panel saved them."""
    raw = load_config().get("providers")
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for i, item in enumerate(raw):
        entry = _clean_provider(item, i)
        if not entry["name"]:
            continue          # 没有名字的条目在节点下拉里无法选择，直接忽略
        if not with_key:
            entry = dict(entry)
            entry.pop("api_key", None)
        out.append(entry)
    return out


def mask_key(key: str) -> str:
    """`sk-abcd****` - enough to recognise which key it is, not enough to use."""
    key = str(key or "")
    if not key:
        return ""
    if len(key) <= 8:
        return KEY_MASK
    return key[:4] + KEY_MASK


def provider_choices() -> list:
    """服务商名列表（不含模型），内置预设在前。

    这是「选哪一家」的下拉；要选具体模型用 ``service_choices()``。
    """
    names = [k for k in PRESETS]
    for entry in list_providers():
        if entry["name"] not in names:
            names.append(entry["name"])
    return names


def _split_service(value) -> tuple:
    """把 ``服务商/模型`` 拆开；整串只是服务商名时模型为空。

    用最长前缀匹配：OpenRouter 的模型名本身带斜杠
    （``OpenRouter/openai/gpt-4o-mini``），先匹配短名字会把模型切错。
    认不出服务商就原样返回，交给调用方报「没有地址 / 没有模型」。
    """
    raw = str(value or "").strip()
    if not raw:
        return "", ""
    for entry in list_providers():
        if raw in (entry["name"], entry["id"]):
            return entry["name"], ""
    if raw in PRESETS:
        return raw, ""
    candidates = []
    for entry in list_providers():
        candidates.append((entry["name"], entry["name"]))
        if entry["id"]:
            candidates.append((entry["id"], entry["name"]))
    for name in PRESETS:
        candidates.append((name, name))
    for prefix, provider in sorted(candidates, key=lambda item: len(item[0]), reverse=True):
        head = prefix + "/"
        if prefix and raw.startswith(head):
            model = raw[len(head):].strip()
            if model:
                return provider, model
    return raw, ""


def _provider_default(name: str) -> str:
    """某服务商的默认模型（自定义条目优先于同名预设）。"""
    for entry in list_providers():
        if name in (entry["name"], entry["id"]):
            return entry["default_model"]
    preset = PRESETS.get(name) or {}
    return str(preset.get("model") or "")


def provider_models(name) -> list:
    """某服务商下可选的模型列表。"""
    provider, _model = _split_service(name)
    for entry in list_providers():
        if provider in (entry["name"], entry["id"]):
            return list(entry["models"])
    preset = PRESETS.get(provider) or {}
    models = [str(m).strip() for m in (preset.get("models") or []) if str(m).strip()]
    default = str(preset.get("model") or "").strip()
    if default and default not in models:
        models.insert(0, default)
    return models


# 视觉专用模型的识别特征，按厂商的两套命名各来一条：
#   * 名字里带整段的 ``vl`` / ``vision``：qwen3-vl-plus、qwen2.5-vl-72b、
#     llama3.2-vision:11b；
#   * 智谱的「版本号 + v」写法：glm-4v-flash、glm-4.5v、glm-4.6v-flash。
# ``gpt-4o`` 这类通用多模态不算 —— 文本任务一样能打，从翻译下拉里剔掉反而
# 少了可用选项；``deepseek-v3`` 这种「v + 数字」也不会误判。
_VISION_ONLY = re.compile(
    r"(?:^|[-/_.])vl(?:$|[-/_.:])"          # -vl- / /vl/
    r"|vision"                               # vision
    r"|(?:^|[-_.])\d+(?:\.\d+)?v(?:$|[-_.:])",  # -4v / -4.5v / -4.6v-
    re.I,
)


def is_vision_only(model) -> bool:
    """这个模型是否只对「看图」有意义（纯文本节点不必列出来）。"""
    return bool(_VISION_ONLY.search(str(model or "")))


def service_choices(include_vision: bool = False) -> list:
    """节点下拉用：「服务商」代表它的默认模型，其余模型展开成 ``服务商/模型``。

    默认模型不再单独列一遍组合串，否则下拉里会出现
    ``DeepSeek`` 和 ``DeepSeek/deepseek-chat`` 两个看起来一样的选项。

    ``include_vision=False``（默认）把视觉专用模型从下拉里去掉。翻译、润色、
    扩写都是纯文本任务，``Zhipu GLM/glm-4.5v`` 混在里面只会让用户以为要换
    模型才能跑；看图反推的节点走自己的 ``vision_choices()``，不受影响。
    这些值仍然能执行（``execute`` 不查列表），老工作流里存着也不会崩 ——
    配套的 ``VALIDATE_INPUTS`` 在提交阶段接住了「不在列表里」的旧值。
    """
    out = []
    for name in provider_choices():
        if name == "custom":
            continue           # 空地址占位，选它只会得到「没有地址」的报错
        out.append(name)
        default = _provider_default(name)
        for model in provider_models(name):
            if model == default:
                continue
            if not include_vision and is_vision_only(model):
                continue
            item = "%s/%s" % (name, model)
            if item not in out:
                out.append(item)
    return out or ["custom"]


def default_provider() -> str:
    """The provider a fresh node starts on: the one picked in settings."""
    want = str(load_config().get("default_provider") or "").strip()
    return want if want in provider_choices() else "custom"


def default_service_choice() -> str:
    """节点下拉的默认值：保证返回值一定落在 ``service_choices()`` 里。

    ``default_provider()`` 在没有有效默认时返回 ``"custom"``，那是「空地址
    占位」，而节点下拉给的是 ``service_choices()``（故意不含 custom）。两者
    混用会让新拖出来的节点带着一个非法值：前端显示空白，提交时被判
    ``Value not in list``，用户看到的就是「这节点拖出来就不能跑」。

    优先级：设置里指定的默认 → 第一个填了 Key 的服务商 → 第一个选项。
    最后一档是「刚装好什么都没配」，选中的服务会在执行时给出「没有配置
    地址 / Key」的明确报错，比一个非法值好。
    """
    choices = service_choices()
    want = default_provider()
    if want in choices:
        return want
    for name in provider_choices():
        if name == "custom" or name not in choices:
            continue
        if str(resolve_provider(name).get("api_key") or "").strip():
            return name
    for name in choices:
        if name != "custom":
            return name
    return choices[0] if choices else "custom"


def preset_key(name) -> str:
    """The key saved for a built-in preset, or ''.

    Built-in presets ship without a key - the settings panel stores one per
    preset under config.json's ``preset_api_keys``, keyed by preset name.
    """
    keys = load_config().get("preset_api_keys")
    if not isinstance(keys, dict):
        return ""
    return str(keys.get(str(name)) or "")


def resolve_provider(name) -> dict:
    """`{"api_url", "model", "api_key"}` for a provider name.

    ``name`` 既可以是服务商名（用它的默认模型），也可以是
    ``服务商/模型``（用指名模型）。后者是「一个服务商挂多个模型」的入口，
    老工作流里存的服务商名照样能用。

    A name from the user's own list wins over a built-in preset of the same
    name - that is the only way to override a preset's address without
    editing code.
    """
    provider, model = _split_service(name)
    for entry in list_providers(with_key=True):
        if provider and provider in (entry["name"], entry["id"]):
            return {
                "api_url": entry["api_url"],
                "model": model or entry["default_model"],
                "api_key": entry["api_key"],
                "provider": entry["name"],
            }
    preset = PRESETS.get(provider, PRESETS["custom"])
    return {
        "api_url": preset["api_url"],
        "model": model or preset["model"],
        "api_key": preset_key(provider),
        "provider": provider,
    }


def config_api_key() -> str:
    """The legacy single key from config.json, or ''.

    Still honoured so an existing config keeps working after the upgrade to
    a provider list - a provider entry's own key wins when it has one.

    文件不存在时补一份空模板，但不再用 ``open(path, "w")`` 直接写：那会和
    设置面板的 ``save_config()`` 撞车，写到一半被另一处读成半份 JSON，
    整份配置（含所有 Key）就会被静默读空。现在走同一把锁 + 唯一临时文件 +
    ``os.replace``，并在锁内复查一次，避免覆盖别的标签页刚写好的 Key。
    """
    path = _config_path()
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return str(data.get("api_key") or "")
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001 - a broken config is treated as no key
        return ""

    with _CONFIG_LOCK:
        # 双检：读失败到拿锁之间，另一个标签页可能已经把带 Key 的配置写好了
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    existing = json.load(handle)
            except Exception:  # noqa: BLE001
                return ""
            return str((existing or {}).get("api_key") or "")
        try:
            save_config({
                "api_key": "",
                "_comment": (
                    "Fill api_key here - it stays on this machine and "
                    "out of workflow files. Ollama needs no key."
                ),
            })
        except OSError:  # 只读介质：和旧行为一致，静默跳过建文件
            pass
    return ""


# --------------------------------------------------------------------------
# 错误正文脱敏
# --------------------------------------------------------------------------

_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{4,}")
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}")
# 字段名后面可能紧跟引号（JSON 里的 "api_key":"..."），所以引号要算进
# 前缀；authorization 故意不列——它由 _BEARER_RE 处理，列进来会把
# "Authorization: Bearer ***" 里的协议字也一起吃掉，反倒破坏错误文案。
_KV_RE = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|sign)\b"
    r"[\"']?\s*[:=]\s*[\"']?)([^\s\"',}\]]{4,})"
)


def redact_secrets(text, secrets=()) -> str:
    """把 HTTP 错误正文里可能回显的密钥打码后再往画布 / 日志推。

    少数服务商 401/400 的响应体会把请求头或请求参数原样回显（例如
    ``Bearer sk-...``、``"api_key": "..."``）。这些正文以前直接进
    RuntimeError 的消息，既上节点气泡也进控制台日志，等于把 Key 明文
    写进日志。这里只打码明显的密钥形态，其余错误描述一字不动，排障信息
    仍然可用；``secrets`` 可额外传入本次请求用的真实 Key。
    """
    out = str(text or "")
    for value in secrets or ():
        value = str(value or "").strip()
        if len(value) >= 6:
            out = out.replace(value, "***")
    out = _BEARER_RE.sub(lambda m: m.group(1) + "***", out)
    out = _SK_RE.sub("sk-***", out)
    out = _KV_RE.sub(lambda m: m.group(1) + "***", out)
    return out


NOTICE_EVENT = "qg-node-notice"


def push_notice(text: str, kind: str = "error", title: str = "") -> None:
    """把一条提示推给前端，画在正在执行的那个节点下方。

    翻译失败时节点只能「原样输出」，用户在画布上完全看不出发生了什么——
    界面上一模一样，区别只在控制台里一行 print。这条事件让失败原因直接
    出现在节点下面，跟反推节点的流式气泡是同一套前端绘制。

    ``title`` 是气泡标题。不给就按 ``kind`` 用默认文案（出错时是「⚠ 出错
    （已原样输出）」）——这句只对「失败后照样往下走」的节点成立，别的节点
    要用得自己给一个。

    任何环节不可用（没有 PromptServer、没有 last_node_id）都静默跳过：
    提示只是锦上添花，绝不能因为它把翻译本身搞挂。
    """
    try:
        # 用 sys.modules 取已加载的 server，不主动 import：脱离 ComfyUI 的环境
        # （单测、脚本）里 import server 会连带拉起整个 ComfyUI，代价太大。
        server_module = sys.modules.get("server")
        server = getattr(getattr(server_module, "PromptServer", None), "instance", None)
        if server is None:
            return
        node_id = getattr(server, "last_node_id", None)
        if node_id is None:
            return
        server.send_sync(NOTICE_EVENT, {
            "node": str(node_id),
            "text": str(text or "")[:600],
            "kind": str(kind or "error"),
            "title": str(title or ""),
        })
    except Exception:  # noqa: BLE001 - 推不出去就算了
        pass


def strip_quotes(text: str) -> str:
    """One layer of wrapping quotes gone - models like to add them.

    Only a matched pair is removed, and only when something is left: a
    quoted title that is really part of the text keeps its quotes.

    **Must run after** ``clean_answer``: a ``` fence is three backticks, and
    this function would peel exactly one of them, leaving ``text`` behind -
    which the fence regex can no longer recognise.
    """
    out = text.strip()
    pairs = ('"', '"', "'", "'", "`", "\u201c\u201d", "\u300c\u300d")
    for pair in pairs:
        if len(out) >= 2 and out[0] == pair[0] and out[-1] == pair[-1]:
            inner = out[1:-1].strip()
            if inner:
                return inner
            break
    return out


_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.S | re.I)
_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_+-]*\s*\n?(.*?)\n?\s*```\s*$", re.S | re.I)
# DeepSeek 系的思考段用这个标记收尾，而且经常不带 <think> 开标签
_THINK_END = "<｜end▁of▁thinking｜>"


def clean_answer(text: str) -> str:
    """剥掉思考段、Markdown 围栏和一层包裹引号，返回可以直接用的正文。

    各家模型（尤其是免费档和走中转站的）很爱把答案包成三反引号代码块，
    或者在前面加一段思考。这些字符一旦流进提示词或 CLIP 文本编码，
    就是肉眼可见的脏数据，所以输出端统一兜一层。

    顺序不能调换：必须先剥围栏再剥引号，因为围栏本身是三个反引号，
    ``strip_quotes`` 只会剥掉其中一个。
    """
    out = str(text or "")
    marker = _THINK_END
    if marker in out.lower():
        out = out[out.lower().rfind(marker) + len(marker):]
    out = _THINK_BLOCK.sub("", out)
    match = _FENCE.match(out)
    if match:
        out = match.group(1)
    return strip_quotes(out.strip())


def build_messages(text: str, from_lang: str, to_lang: str, rule_text: str = "") -> list:
    """The chat messages: a strict translator instruction plus the text.

    ``rule_text`` is the optional style constraint from the rules manager
    (设置 → QG 工具 → 提示词规则 → 翻译规则). It is appended to the same
    system message instead of adding a second one: several vendors reject
    requests that carry more than one system turn.
    """
    source = LANG_NAMES.get(str(from_lang), "")
    target = LANG_NAMES.get(str(to_lang), "English")
    where = f" from {source}" if source else ""
    system = (
        f"You are a professional translator. Translate the user's text{where} "
        f"into {target}. Output ONLY the translated text - no quotes around it, "
        "no pinyin, no explanations, no alternatives. Keep proper nouns, brand "
        "names and code identifiers unchanged."
    )
    extra = str(rule_text or "").strip()
    if extra:
        system = system + "\n\n" + extra
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]


def call_api(url: str, key: str, model: str, messages: list, meta=None) -> str:
    """One chat-completions call, the answer's text back.

    Errors carry the vendor's own message where there is one - a 401 from a
    wrong key or a 404 from a wrong url should be named, not disguised.

    ``meta`` 是可选出参：塞入 ``{"truncated": bool, "finish_reason": str}``，
    调用方据此决定要不要缓存（被截断的译文不能进缓存，否则重跑拿到同一份
    坏结果）。之前这里既不传 ``max_tokens`` 也不看 ``finish_reason``，长段落
    译文后半句消失且被当成功缓存。
    """
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    # System proxies stay on for real vendors (some need them to be reached
    # at all), but a local endpoint behind a proxy gets answered by the
    # proxy instead of Ollama - so localhost never proxies.
    opener = urllib.request.build_opener()
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host in ("127.0.0.1", "localhost", "::1"):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            detail = redact_secrets(
                error.read().decode("utf-8", "replace")[:300], (key,))
        except Exception:  # noqa: BLE001 - the body is best effort
            pass
        raise RuntimeError(
            f"QG 翻译：接口返回 HTTP {error.code}。{detail}"
        ) from error
    try:
        choice = payload["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError(BAD_REPLY) from error
    finish = str(choice.get("finish_reason") or "")
    if isinstance(meta, dict):
        meta["finish_reason"] = finish
        meta["truncated"] = finish == "length"
    if finish == "length":
        print("[QG Translate] 译文被服务端按长度上限截断了（model=%s）—— 后半段可能"
              "缺失，长段落建议拆成几次翻；这份结果不会进缓存。" % model)
    # 原样返回：清洗交给 clean_answer 统一做（它要先剥围栏再剥引号，
    # 这里先剥一层反引号会让围栏正则永远匹配不上）。
    return str(content)


def translate(
    text: str,
    provider: str,
    api_url: str,
    model: str,
    api_key: str,
    from_lang: str,
    to_lang: str,
    rule_text: str = "",
) -> str:
    """The whole path: resolve settings, cache, call, answer.

    Raises with a plain message on any failure; the caller decides whether
    that stops the run.
    """
    text = str(text or "")
    if not text.strip():
        raise ValueError(MISSING_TEXT)

    # 设置面板里配好的条目优先；节点上的三个输入框只是临时覆盖
    # （搬进设置之后它们默认是空的）。
    entry = resolve_provider(provider)
    url = str(api_url or "").strip() or entry["api_url"]
    if not url:
        raise ValueError(
            "QG 翻译：没有接口地址。在设置面板（或节点上）选一个服务商，"
            "或填一个兼容 OpenAI 的 chat/completions 地址。"
        )
    used_model = str(model or "").strip() or entry["model"]

    key = (str(api_key or "").strip()
           or entry.get("api_key", "")
           or config_api_key())

    cache_key = (url, used_model, bool(key), from_lang, to_lang, text, rule_text)
    hit = _CACHE.get(cache_key)
    if hit is not None:
        return hit

    meta = {}
    answer = clean_answer(call_api(
        url, key, used_model,
        build_messages(text, from_lang, to_lang, rule_text), meta=meta))
    if meta.get("truncated"):
        # 截断的译文可能是半句，缓存它等于把坏结果钉死。
        return answer
    if len(_CACHE) >= CACHE_MAX:
        _CACHE.clear()
    _CACHE[cache_key] = answer
    return answer


def test_provider(entry: dict) -> dict:
    """Send one tiny message so the settings panel can say "works" or why not.

    Deliberately not ``translate()``: that one caches, and a cached answer
    would report success for an address that has since gone dead.
    """
    entry = entry if isinstance(entry, dict) else {}
    url = str(entry.get("api_url") or "").strip()
    model = str(entry.get("model") or "").strip()
    key = str(entry.get("api_key") or "").strip() or config_api_key()
    if not url:
        return {"ok": False, "message": "API 地址是空的"}
    if not model:
        return {"ok": False, "message": "模型名是空的"}
    try:
        answer = call_api(
            url, key, model,
            [{"role": "user", "content": "Reply with the single word: pong"}],
        )
    except Exception as error:  # noqa: BLE001 - the message is the point
        return {"ok": False, "message": str(error)[:500]}
    return {"ok": True, "message": "连接正常", "sample": clean_answer(answer)[:120]}



__all__ = [
    "PRESETS", "PROVIDERS", "LANGUAGES", "LANG_NAMES", "IF_FAIL", "KEY_MASK",
    "CONFIG_NAME", "load_config", "save_config", "list_providers",
    "mask_key", "provider_choices", "service_choices", "provider_models",
    "is_vision_only",
    "default_provider", "preset_key", "resolve_provider", "config_api_key",
    "strip_quotes", "clean_answer", "build_messages", "call_api",
    "translate", "test_provider",
    "_clean_provider", "_split_service", "MAX_MODELS",
]
