# -*- coding: utf-8 -*-
"""QG_PromptTranslate —— 提示词翻译：原文从左边进来，译好的提示词从右边出去。

这个包里的 ``QG_Translate`` 是一个「通用翻译器」：源语言、目标语言、服务商、
地址、模型、Key 全都摊在节点上。真正用起来时，工作流里的形状是固定的——
中文提示词进、英文提示词出——于是有了这个只有四个控件的快捷版。

设计取舍
--------
* **原文只做成输入口（forceInput）**。提示词几乎总是由别的节点产生
  （文本编辑、字符串拼接、注释），留个空文本框只会让人误填。
* **翻译服务 = 两条百度通道 + 所有 OpenAI 兼容服务商**。百度不需要模型，
  填一对 appid / 密钥就能用，额度免费；其中「百度翻译（大模型）」会带上
  提示词专用的翻译指令（保持短语结构、保留括号权重），代价是要在控制台
  单独开通，没开通时自动回落到通用翻译。其余条目的地址、模型、Key 都跟着
  ``config.json`` 走，节点上只选名字。
* **百度通道的坑都埋在地基里**：分块按「字符」不按字节（官方口径是字符，
  标准版 1000、认证后 6000）、块间强制隔 1 秒（未认证 QPS 只有 1）、
  限流类错误指数退避重试 3 次、错误码翻成中文并给处理建议。
* **源语言自动判断**：含中文字符算中文，全 ASCII 可打印算英文，其余交给
  服务端 auto。目标语言与源语言相同时直接跳过，不花一次请求的钱。
* **自动释放显存只对本地 Ollama 有意义**：翻译完立刻 ``keep_alive: 0``
  把模型请出显存，给后面的采样器腾地方；云端服务忽略这个开关。
* **种子不改变翻译结果**。翻译本身是确定性的，种子进 ``IS_CHANGED`` 与
  缓存键，作用只是「换个数就重新走一次请求」，方便对措辞不满意时重翻。
* **失败不挡工作流**：控制台打一行醒目警告，原文原样传下去。与
  ``QG_Translate`` 的默认行为一致——一次网络抖动不该让几十分钟的采样白跑。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import prompt_rules as _rules
from . import translate_core as _translate

BAIDU = "百度翻译"
BAIDU_LLM = "百度翻译（大模型）"
BAIDU_URL = "https://fanyi-api.baidu.com/api/trans/vip/translate"
BAIDU_LLM_URL = "https://fanyi-api.baidu.com/ait/api/aiTextTranslate"
# 百度通用文本翻译的语言码与 ISO 不同（日文 jp、韩文 kor、法文 fra...）
BAIDU_LANG = {
    "chinese": "zh",
    "english": "en",
    "japanese": "jp",
    "korean": "kor",
    "french": "fra",
    "german": "de",
    "spanish": "spa",
    "russian": "ru",
}
# 节点下拉显示英文名（与截图一致），内部用 QG_Translate 的小写键
TARGETS = {
    "English": "english",
    "Chinese": "chinese",
    "Japanese": "japanese",
    "Korean": "korean",
    "French": "french",
    "German": "german",
    "Spanish": "spanish",
    "Russian": "russian",
}

# 单次请求上限按「字符」算，不是字节——官方文档的 1000 / 6000 都是字符数，
# 而中文一个字符占 3 字节，按字节切会把额度白白用掉三分之二。
#   通用接口：未认证标准版 1000 字符，实名认证后 6000，官方建议 2000 以内
#   大模型接口：6000 字符，官方同样建议 2000 以内
# 取最保守的 1000 作默认，任何账号都不会越界；真被拒也有自适应降半兜底。
BAIDU_CHUNK = 1000
BAIDU_LLM_CHUNK = 2000
# 极少数网关按字节判长度，加一条字节上限兜底
BAIDU_MAX_BYTES = 4800
TIMEOUT = 25
# 未认证账号 QPS 只有 1，两段之间必须留间隔，否则第二段必撞 54003
QPS_GAP = 1.05
MAX_ATTEMPTS = 3

# 错误码 → 人话。百度只回英文/代码，直接透出去用户看不懂。
BAIDU_ERRORS = {
    "52001": "请求超时",
    "52002": "百度服务端系统错误",
    "52003": "未授权：APPID 不对，或该服务没开通",
    "54000": "必填参数为空",
    "54001": "签名错误：APPID 与密钥不配对",
    "54003": "访问频率受限：未认证账号 QPS 只有 1，请放慢或完成实名认证",
    "54004": "账户余额不足，请到管理控制台充值",
    "54005": "长文本请求过于频繁，请 3 秒后再试",
    "58000": "客户端 IP 非法：开发者信息里填的服务器 IP 与实际不符，建议留空",
    "58001": "译文语言方向不支持",
    "58002": "服务当前已关闭：请到管理控制台开启对应 API",
    "58003": "此 IP 已被封禁：同日用多个 APPID 请求所致，次日解封",
    "90107": "开发者认证未通过或未生效",
    "20003": "内容被判定为安全风险：提示词里有敏感词，换个服务商或改写",
}
# 重试有用的码：限流、系统错误、超时
RETRY_CODES = {"52001", "52002", "54003", "54005"}
# 大模型通道不可用时值得回落到通用翻译的码（没开通 / 没认证 / 签名不支持）
LLM_FALLBACK_CODES = {"52003", "54001", "58002", "90107", "10006"}

# 大模型通道的翻译指令。百度文档里这个字段叫 reference，
# 可以把「我要什么风格」直接塞给模型 —— 提示词最怕被意译成散文。
BAIDU_PROMPT_REFERENCE = (
    "这是 AI 图像生成提示词。只做语言转换：保持逗号分隔的短语结构，"
    "不要合并成完整句子，不要添加原文没有的描述；保留括号权重语法"
    "（如 (word:1.2)、[word]）、LoRA 标签（如 <lora:name:0.8>）、"
    "数字参数与符号；不要输出任何解释。"
)


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------

def baidu_credentials() -> tuple:
    """config.json 里的百度 appid 与密钥，没配就是两个空串。"""
    section = _translate.load_config().get("baidu")
    section = section if isinstance(section, dict) else {}
    return (str(section.get("appid") or "").strip(),
            str(section.get("key") or "").strip())


def service_choices() -> list:
    """下拉选项：两条百度通道打头，其后是全部 OpenAI 兼容服务商。

    用户自定义的服务商如果也叫「百度翻译」，只留一个（自定义那条在下拉里
    无法与内置区分，所以这里让内置的优先，避免同名两条互相干扰）。

    服务商配了多个模型时，``服务商`` 代表默认模型，其余展开成
    ``服务商/模型``，与 QG_Translate 保持一致。
    """
    names = [BAIDU, BAIDU_LLM]
    for name in _translate.service_choices():
        if name not in names:
            names.append(name)
    return names


def default_service() -> str:
    """开箱默认：百度配好了就用百度，否则挑一条真能用的。

    ``custom`` 是空地址的占位条目，选它必然报错，所以跳过它；内置厂商里
    优先挑已经存过 Key 的那家（用户配过就说明在用），都没有才退回百度，
    让用户去设置面板补一对凭证。
    """
    appid, key = baidu_credentials()
    if appid and key:
        return BAIDU
    fallback = _translate.default_provider()
    if fallback and fallback != "custom":
        return fallback
    for name in _translate.PRESETS:
        if name != "custom" and _translate.preset_key(name):
            return name
    return BAIDU


# --------------------------------------------------------------------------
# 结果缓存
# --------------------------------------------------------------------------

# ComfyUI 的节点级缓存看 IS_CHANGED，而种子是「生成后随机」时每次都得重跑
# ——没有这层缓存，每点一次生图就真的再请求一次、再扣一次额度。
# 只缓存百度两条通道；OpenAI 兼容那条在 translate_core 里已有自己的缓存。
_CACHE_MAX = 64
_CACHE: dict = {}


def _rule_fingerprint() -> str:
    """当前翻译规则的短指纹，用于缓存键；规则为空时给空串。"""
    text = _rules.translate_rule_text()
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:8] if text else ""


def _cached(service: str, text: str, source: str, target: str) -> str:
    """查缓存；不打中的地方照常请求，不抛异常。

    规则指纹要进 key：用户在规则管理器里改了「翻译规则」的措辞，缓存里
    那份旧结果就不该再被拿出来了。
    """
    key = (service, source, target, text, _rule_fingerprint())
    hit = _CACHE.get(key)
    if hit is not None:
        print("[QG-PromptTranslate] 命中缓存，不重复请求")
        return hit

    if service == BAIDU_LLM:
        answer = translate_baidu_llm(text, source, target)
    else:
        answer = translate_baidu(text, source, target)

    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = answer
    return answer


# --------------------------------------------------------------------------
# 语言判断
# --------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """粗判源语言：中文 / 英文 / 交给服务端（auto）。"""
    if not text:
        return "auto"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "chinese"
    if re.fullmatch(r"[ -~]+", text):
        return "english"
    return "auto"


# --------------------------------------------------------------------------
# 百度翻译
# --------------------------------------------------------------------------

class BaiduError(RuntimeError):
    """带错误码的百度异常，用来判断值不值得回落或重试。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = str(code)


def _describe(code: str, message) -> str:
    """错误码翻成人话，并把接口原文附在后面备查。"""
    hint = BAIDU_ERRORS.get(str(code))
    raw = str(message or "").strip()
    if hint and raw:
        return f"{hint}（接口原文：{raw}）"
    return hint or raw or f"百度翻译返回错误 {code}"


def _error_code(payload: dict):
    """取错误码，成功返回 None。

    两个接口给的码类型不一样：通用接口是字符串 ``"52003"``，大模型接口是
    数字 ``54001``。而且数字 0 是 falsy、字符串 ``"52000"`` 又代表成功，
    所以不能简单 ``if payload.get("error_code")``，统一转字符串再比白名单。
    """
    code = payload.get("error_code")
    if code is None:
        return None
    code = str(code).strip()
    if code in ("", "0", "52000"):
        return None
    return code


def _split_text(text: str, limit_chars: int) -> list:
    """按行切成不超过 limit_chars 字符的块，单行超长再按字符硬切。

    百度按「字符」限长（标准版 1000、认证后 6000），超了报 54005 / 54003，
    白丢一次额度。先按换行对齐切，一整行都塞不下才硬切。
    """
    def fits(piece: str) -> bool:
        return (len(piece) <= limit_chars
                and len(piece.encode("utf-8")) <= BAIDU_MAX_BYTES)

    chunks = []
    buffer = ""
    for line in text.splitlines(keepends=True):
        if fits(buffer + line):
            buffer += line
            continue
        if buffer:
            chunks.append(buffer)
            buffer = ""
        while not fits(line):
            cut = min(limit_chars, len(line))
            while cut > 1 and len(line[:cut].encode("utf-8")) > BAIDU_MAX_BYTES:
                cut -= 1
            chunks.append(line[:cut])
            line = line[cut:]
        buffer = line
    if buffer:
        chunks.append(buffer)
    return chunks or [""]


_last_call = 0.0


def _throttle() -> None:
    """按 QPS=1 限速。未认证账号两段连着发，第二段必被 54003 挡回来。"""
    global _last_call
    wait = QPS_GAP - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()


def _baidu_request(url: str, body: bytes, headers: dict, label: str) -> dict:
    """发一次请求并解析 JSON；限流与系统错误自动退避重试。

    重试只对「再来一次可能成功」的码做（限流、超时、服务端错误）。
    签名错、余额不足、内容风险这些重试多少次都一样，直接抛。
    """
    last = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        _throttle()
        try:
            request = urllib.request.Request(
                url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = ""
            try:
                detail = _translate.redact_secrets(
                    error.read().decode("utf-8", "replace")[:200])
            except Exception:  # noqa: BLE001 - 错误正文是尽力而为
                pass
            last = f"HTTP {error.code} {detail}".strip()
            if 500 <= error.code < 600 and attempt < MAX_ATTEMPTS:
                time.sleep(attempt)
                continue
            raise BaiduError(str(error.code), f"{label}返回 {last}") from error
        except OSError as error:  # 含 URLError / TimeoutError
            last = str(error)
            if attempt < MAX_ATTEMPTS:
                time.sleep(attempt)
                continue
            raise BaiduError("network", f"{label}网络请求失败：{error}") from error
        except json.JSONDecodeError as error:
            raise BaiduError("json", f"{label}返回的不是 JSON：{error}") from error

        code = _error_code(payload)
        if code is None:
            return payload
        last = code
        if code in RETRY_CODES and attempt < MAX_ATTEMPTS:
            # 54005 官方建议等 3 秒，其余按次数递增
            time.sleep(3 if code == "54005" else attempt)
            continue
        raise BaiduError(code, _describe(code, payload.get("error_msg")))
    raise BaiduError("retry", f"{label}重试 {MAX_ATTEMPTS} 次仍失败：{last}")


def _rows_to_text(payload: dict) -> str:
    """把 trans_result 数组拼回文本。

    百度按换行切段返回，所以这里用换行拼；大模型接口个别返回会把结果
    包在 data 里，一并兼容。
    """
    rows = payload.get("trans_result")
    if not rows and isinstance(payload.get("data"), dict):
        rows = payload["data"].get("trans_result")
    return "\n".join(str(row.get("dst") or "") for row in (rows or []))


def _baidu_call(text: str, source: str, target: str,
                appid: str, key: str) -> str:
    """通用文本翻译接口，一次请求。"""
    salt = str(int(time.time() * 1000))
    sign = hashlib.md5(
        (appid + text + salt + key).encode("utf-8")).hexdigest()
    body = urllib.parse.urlencode({
        "q": text,
        "from": BAIDU_LANG.get(source, "auto"),
        "to": BAIDU_LANG[target],
        "appid": appid,
        "salt": salt,
        "sign": sign,
    }).encode("utf-8")
    payload = _baidu_request(
        BAIDU_URL, body,
        {"Content-Type": "application/x-www-form-urlencoded"}, "百度翻译")
    return _rows_to_text(payload)


def _baidu_llm_call(text: str, source: str, target: str,
                    appid: str, key: str, reference: str = "") -> str:
    """大模型文本翻译接口，一次请求。

    ``reference`` 是给模型的风格指令，取自规则管理器的「翻译规则」；
    规则被清空时用内置那段兜底。

    注意 ``salt`` 必须是**数字**：这个接口按 protobuf 解包，字段类型是
    uint64，传字符串会直接报
    ``aitext.AITextRequest.Salt: readUint64: unexpected character``。
    通用接口（form 表单）那边恰恰相反，salt 只能传字符串——两个接口不通用。
    """
    salt = str(int(time.time() * 1000))
    sign = hashlib.md5(
        (appid + text + salt + key).encode("utf-8")).hexdigest()
    body = json.dumps({
        "appid": appid,
        "q": text,
        "from": BAIDU_LANG.get(source, "auto"),
        "to": BAIDU_LANG[target],
        "model_type": "llm",
        "reference": str(reference or "").strip() or BAIDU_PROMPT_REFERENCE,
        "salt": int(salt),
        "sign": sign,
    }, ensure_ascii=False).encode("utf-8")
    payload = _baidu_request(
        BAIDU_LLM_URL, body,
        {"Content-Type": "application/json"}, "百度大模型翻译")
    return _rows_to_text(payload)


def _run_chunked(text: str, limit_chars: int, call) -> str:
    """分段翻译再拼回来。

    拼的时候要判断块边界是不是行边界：上一块以换行结尾就补回一个换行
    （百度按行返回、会吃掉分隔符）；不以换行结尾说明是一整行被硬切开，
    直接接上，不能凭空塞换行把一句话拆成两行。
    """
    pieces, breaks = [], []
    for chunk in _split_text(text, limit_chars):
        if not chunk:
            continue
        pieces.append(call(chunk))
        breaks.append(chunk.endswith(("\n", "\r")))
    out = ""
    for index, piece in enumerate(pieces):
        if index and breaks[index - 1]:
            out += "\n"
        out += piece
    return out.strip()


def _require_credentials() -> tuple:
    appid, key = baidu_credentials()
    if not appid or not key:
        raise RuntimeError(
            "百度翻译还没配 appid 与密钥。打开 设置 → QG 工具 → API 服务商，"
            "切到「百度翻译」页签填进去（fanyi-api.baidu.com 免费申请），"
            "或者把节点上的翻译服务换成别的服务商。"
        )
    return appid, key


def translate_baidu(text: str, source: str, target: str) -> str:
    """整段走通用翻译接口，超长自动分段。"""
    appid, key = _require_credentials()
    if target not in BAIDU_LANG:
        raise ValueError(f"百度翻译不支持目标语言 {target}")
    return _run_chunked(
        text, BAIDU_CHUNK,
        lambda chunk: _baidu_call(chunk, source, target, appid, key))


def translate_baidu_llm(text: str, source: str, target: str) -> str:
    """整段走大模型翻译接口，带提示词专用的翻译指令。

    这个接口要在控制台单独开通。没开通时自动回落到通用翻译——不能让
    一句「服务未开通」把整条工作流卡住。
    """
    appid, key = _require_credentials()
    if target not in BAIDU_LANG:
        raise ValueError(f"百度翻译不支持目标语言 {target}")
    try:
        reference = _rules.translate_rule_text()
        return _run_chunked(
            text, BAIDU_LLM_CHUNK,
            lambda chunk: _baidu_llm_call(chunk, source, target, appid, key, reference))
    except BaiduError as error:
        if error.code not in LLM_FALLBACK_CODES:
            raise
        print(f"[QG-PromptTranslate] 大模型翻译不可用（{error}），"
              "自动回落到通用翻译")
        return translate_baidu(text, source, target)


# --------------------------------------------------------------------------
# Ollama 显存
# --------------------------------------------------------------------------

def release_ollama_model(service: str) -> None:
    """把本地 Ollama 上跑完的模型请出显存；云端服务或不支持时安静跳过。"""
    entry = _translate.resolve_provider(service)
    parsed = urllib.parse.urlparse(entry.get("api_url") or "")
    host = (parsed.hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        return
    model = str(entry.get("model") or "")
    if not model:
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
    except Exception as error:  # noqa: BLE001 - 卸载失败不该影响翻译结果
        print(f"[QG-PromptTranslate] 释放 Ollama 模型失败（不影响结果）：{error}")


# --------------------------------------------------------------------------
# 节点
# --------------------------------------------------------------------------

class QGPromptTranslate:
    """原文 → 目标语言的提示词。"""

    CATEGORY = "QG 工具"
    SEARCH_ALIASES = [
        "prompt translate", "提示词翻译", "翻译提示词", "百度翻译",
        "translate", "translation", "英文提示词", "chinese to english",
        "prompt", "qg",
    ]

    @classmethod
    def INPUT_TYPES(cls):
        services = service_choices()
        return {
            "required": {
                "source_text": (
                    "STRING",
                    {
                        "forceInput": True,
                        "tooltip": (
                            "要翻译的原文，从左边接进来，节点上不显示输入框。"
                            "内容为空时原样输出空串，不会发起请求。"
                        ),
                    },
                ),
                "target_language": (
                    list(TARGETS),
                    {
                        "default": "English",
                        "tooltip": (
                            "翻译成什么语言。默认 English——SAM 3、CLIP 这类"
                            "检测与编码模型只认英文。原文已经是目标语言时"
                            "直接跳过，不花一次请求。"
                        ),
                    },
                ),
                "translate_service": (
                    services,
                    {
                        "default": default_service(),
                        "tooltip": (
                            "用哪条通道翻译。「百度翻译」填一对 appid 与密钥"
                            "就能用（未认证账号 5 万字符/月）；「百度翻译"
                            "（大模型）」翻提示词更准，会按逗号短语结构输出、"
                            "保留括号权重与 LoRA 标签，但要在控制台单独开通，"
                            "没开通时自动回落到普通百度翻译。其余条目是设置"
                            "面板里配好的 OpenAI 兼容服务商。"
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
                            "翻译完立刻把本地 Ollama 的模型请出显存，给后面的"
                            "采样器腾地方。云端服务商忽略这个开关。"
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
                            "不影响翻译结果。作用只是让节点重新执行一次"
                            "（对措辞不满意时换个种子重翻），已有缓存仍会复用，"
                            "不会重复扣费。"
                        ),
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("translated_text",)
    OUTPUT_TOOLTIPS = ("译好的提示词；失败时是原文。",)
    FUNCTION = "execute"

    @classmethod
    def VALIDATE_INPUTS(cls, translate_service=""):
        """只接管 ``translate_service`` 一项，其余输入照常走默认校验。

        下拉里现在不列视觉专用模型（``glm-4.5v`` 这类），而老工作流、或者
        设置面板里被删掉的自定义服务商，都可能存着「不在列表里」的值。
        默认校验会在**提交阶段**判 ``Value not in list``，报错里只有一串
        字符串，用户根本不知道要改哪里；放行它，让 execute 去报
        「这个服务没有配置地址」——那句话才指明下一步。
        """
        return True

    @classmethod
    def IS_CHANGED(cls, source_text="", target_language="", translate_service="",
                   auto_unload=True, seed=0, **_kwargs):
        """输入或种子变了才重跑；不然 ComfyUI 直接复用上次结果。

        用 md5 而不是内置 ``hash()``：字符串 hash 每次进程启动都带随机盐，
        换进程后同一个值算出不同的数，节点会被判成「变了」白跑一次。

        翻译规则不在节点输入里（它在 rules.json），而 ``_cached`` 的缓存键
        恰恰把规则正文算进去了。规则指纹不进 ``IS_CHANGED`` 的话，节点在
        这一步就被判成「没变」、连 execute 都进不去，那层缓存键形同虚设。
        """
        blob = "\x1f".join([
            hashlib.md5(str(source_text or "").encode("utf-8")).hexdigest(),
            str(target_language), str(translate_service),
            str(bool(auto_unload)), str(seed),
            _rules.fingerprint(),
        ])
        return hashlib.md5(blob.encode("utf-8")).hexdigest()

    def execute(self, source_text, target_language, translate_service,
                auto_unload=True, seed=0):
        text = str(source_text or "")
        if not text.strip():
            return ("",)

        target = TARGETS.get(str(target_language), "english")
        source = detect_language(text)
        if source == target:
            print(f"[QG-PromptTranslate] 原文已经是目标语言（{target}），跳过翻译")
            return (text,)

        try:
            if translate_service in (BAIDU, BAIDU_LLM):
                answer = _cached(translate_service, text, source, target)
            else:
                # api_url / model / api_key 留空 = 全部取 config.json 里那条配置
                answer = _translate.translate(
                    text, translate_service, "", "", "", source, target,
                    _rules.translate_rule_text())
                if auto_unload:
                    release_ollama_model(translate_service)
        except Exception as error:  # noqa: BLE001 - 失败不挡工作流
            print(f"[QG-PromptTranslate] 翻译失败，原文直通：{error}")
            _translate.push_notice(f"翻译失败，已原样输出：{error}")
            return (text,)

        answer = str(answer or "").strip()
        if not answer:
            print("[QG-PromptTranslate] 服务返回了空结果，原文直通")
            _translate.push_notice("翻译服务返回了空结果，已原样输出")
            return (text,)
        return (answer,)



NODE_CLASS_MAPPINGS = {"QG_PromptTranslate": QGPromptTranslate}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_PromptTranslate": "提示词翻译"}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
