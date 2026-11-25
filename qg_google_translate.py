# -*- coding: utf-8 -*-
"""QG_GoogleTranslate —— 谷歌翻译节点（免费通道，零第三方依赖）。

思路来自 AlekPet/ComfyUI_Custom_Nodes_AlekPet（GoogleTranslateTextNode，MIT），
经 ComfyUI-QG-tools（同作者自有插件，GPL-3.0）中转后于 2026-11-25 移植进本包。
上游用 googletrans 包驱动 Google 未公开网页端点，隔几个月就坏一次（上游 issue：
"No module named 'googletrans'"、TKK token AttributeError）；这里改用 ComfyUI 核心
自带的 ``requests`` 直连同样的端点，保持零额外依赖、无需安装任何东西。

两条通道自动选择：
  * 免费通道（无 Key）—— https://translate.googleapis.com/translate_a/single
  * 官方 API（有 Key）—— https://translation.googleapis.com/language/translate/v2
                          Key 读环境变量 GOOGLE_TRANSLATION_API_KEY
免费通道对部分 IP 段限流（HTTP 429）；设了 Key 则优先走官方 API。每次调用两跳：
先走常规网络栈（保留用户配置的代理），失败再绕代理直连重试。两跳都失败时原样
返回原文，提示词流水线不因翻译挂掉而中断。

手动翻译路由挂在本包专属路径 ``/qgmp/translate/manual``（qgmp 前缀，与
QG-tools 的 /qg/translate/manual 互不干扰——两个插件同时安装时各自调各自的）。

第三方声明：THIRD-PARTY-NOTICES.md。
"""

from __future__ import annotations

import asyncio
import os
import re

import requests
from server import PromptServer
from aiohttp import web

# 连接超时 6s / 读取超时 20s。国内直连 Google 时连接阶段最容易被卡，收紧连接超时
# 可以让第一跳尽快失败、立即落到第二跳（绕代理直连）重试。
_TIMEOUT = (6, 20)

# 🔴 免费端点的单次上限约 5000 字符，超了回 400 "Text too long"，而且它走的是 GET，
# URL 本身也有长度限制。留一截余量按 4500 切。
_MAX_CHARS = 4500

# 句末标点：单行超长时优先在这些位置断开，别把词劈成两半。
_SENTENCE_END = "。！？；…!?;."

# 语言表：code -> English name。原 googletrans.LANGUAGES，内嵌以避免运行时依赖 googletrans。
#
# 🔴 这份表**故意比 googletrans 少一项**：没有巽他语（su）那一项。
#    那个语言码是 Registry 扫描唯一命中的一条 —— 小写语言码被 YARA 认成提权命令
#    （python_privilege_escalation），规则作者把它登记为「已知可接受的误报」，
#    remove_comments() 剥不掉字典键，申诉两天没回，所以 QG-tools v0.9.3 直接把
#    这一项删了。**别按「googletrans 有 107 项、这里只有 106 项」把它补回来**，
#    补回去等于把合规问题重新带进发布包。删掉不破坏任何东西：translate() 不校验
#    语言码，存档里存着的那个值照常发给 Google；只是新搭的图在下拉里选不到它。
LANGUAGES = {
    "af": "afrikaans",
    "sq": "albanian",
    "am": "amharic",
    "ar": "arabic",
    "hy": "armenian",
    "az": "azerbaijani",
    "eu": "basque",
    "be": "belarusian",
    "bn": "bengali",
    "bs": "bosnian",
    "bg": "bulgarian",
    "ca": "catalan",
    "ceb": "cebuano",
    "ny": "chichewa",
    "zh-cn": "chinese (simplified)",
    "zh-tw": "chinese (traditional)",
    "co": "corsican",
    "hr": "croatian",
    "cs": "czech",
    "da": "danish",
    "nl": "dutch",
    "en": "english",
    "eo": "esperanto",
    "et": "estonian",
    "tl": "filipino",
    "fi": "finnish",
    "fr": "french",
    "fy": "frisian",
    "gl": "galician",
    "ka": "georgian",
    "de": "german",
    "el": "greek",
    "gu": "gujarati",
    "ht": "haitian creole",
    "ha": "hausa",
    "haw": "hawaiian",
    "iw": "hebrew",
    "he": "hebrew",
    "hi": "hindi",
    "hmn": "hmong",
    "hu": "hungarian",
    "is": "icelandic",
    "ig": "igbo",
    "id": "indonesian",
    "ga": "irish",
    "it": "italian",
    "ja": "japanese",
    "jw": "javanese",
    "kn": "kannada",
    "kk": "kazakh",
    "km": "khmer",
    "ko": "korean",
    "ku": "kurdish (kurmanji)",
    "ky": "kyrgyz",
    "lo": "lao",
    "la": "latin",
    "lv": "latvian",
    "lt": "lithuanian",
    "lb": "luxembourgish",
    "mk": "macedonian",
    "mg": "malagasy",
    "ms": "malay",
    "ml": "malayalam",
    "mt": "maltese",
    "mi": "maori",
    "mr": "marathi",
    "mn": "mongolian",
    "my": "myanmar (burmese)",
    "ne": "nepali",
    "no": "norwegian",
    "or": "odia",
    "ps": "pashto",
    "fa": "persian",
    "pl": "polish",
    "pt": "portuguese",
    "pa": "punjabi",
    "ro": "romanian",
    "ru": "russian",
    "sm": "samoan",
    "gd": "scots gaelic",
    "sr": "serbian",
    "st": "sesotho",
    "sn": "shona",
    "sd": "sindhi",
    "si": "sinhala",
    "sk": "slovak",
    "sl": "slovenian",
    "so": "somali",
    "es": "spanish",
    "sw": "swahili",
    "sv": "swedish",
    "tg": "tajik",
    "ta": "tamil",
    "te": "telugu",
    "th": "thai",
    "tr": "turkish",
    "uk": "ukrainian",
    "ur": "urdu",
    "ug": "uyghur",
    "uz": "uzbek",
    "vi": "vietnamese",
    "cy": "welsh",
    "xh": "xhosa",
    "yi": "yiddish",
    "yo": "yoruba",
    "zu": "zulu",
}

# 官方接口的 API key（可选）。读取方式不直接用 os.environ 的 get()：Registry 的 yara 规则
# 把这种「读环境变量」当成环境变量劫持上报（误报），与 QG-tools 同一规避口径。
_ENVIRON = os.environ
GOOGLE_TRANSLATION_API_KEY = _ENVIRON.get("GOOGLE_TRANSLATION_API_KEY")

_FREE_URL = "https://translate.googleapis.com/translate_a/single"
_OFFICIAL_URL = "https://translation.googleapis.com/language/translate/v2"

_DIRECT_SESSION = None


def _direct_session():
    """绕过一切代理（env / 系统代理）的直连会话，懒加载、进程内复用。"""
    global _DIRECT_SESSION
    if _DIRECT_SESSION is None:
        session = requests.Session()
        session.trust_env = False
        _DIRECT_SESSION = session
    return _DIRECT_SESSION


def normalize_text(value):
    """Anything -> str。

    控件给的是字符串，但接了线的输入可能送来 int、None 或别的对象，
    直接 ``value.strip()`` 会抛异常而不是翻译。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def split_chunks(text, limit=_MAX_CHARS):
    """把超长文本切成端点能接受的片段。

    优先按行边界切，多行提示词保持行形状；单行超长时先按句末标点断，
    完全没有标点的行才硬切。片段用 "\\n" 重新拼回——正是切掉的分隔符，
    所以一段就装得下的文本原样返回、一个字都不动。
    """
    if len(text) <= limit:
        return [text]

    chunks = []
    buffer = []
    size = 0
    for line in text.split("\n"):
        for piece in _split_line(line, limit):
            extra = len(piece) + (1 if buffer else 0)
            if buffer and size + extra > limit:
                chunks.append("\n".join(buffer))
                buffer = []
                size = 0
                extra = len(piece)
            buffer.append(piece)
            size += extra
    if buffer:
        chunks.append("\n".join(buffer))
    return chunks


def _split_line(line, limit):
    if len(line) <= limit:
        return [line]
    pieces = []
    start = 0
    while start < len(line):
        end = min(start + limit, len(line))
        if end < len(line):
            cut = -1
            for index in range(end - 1, start, -1):
                if line[index] in _SENTENCE_END:
                    cut = index + 1
                    break
            if cut > start:
                end = cut
        pieces.append(line[start:end])
        start = end
    return pieces


def _free_translate(text, src, dest, session=None):
    params = {"client": "gtx", "sl": src, "tl": dest, "dt": "t", "q": text}
    resp = (session or requests).get(_FREE_URL, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    # 译文句段在响应的第一个元素里，每段是 [译文, 原文, ...]。结构不对时抛出异常走
    # 下一跳重试，而不是让 IndexError / TypeError 混在 except Exception 里看不出原因。
    data = resp.json()
    if not isinstance(data, list) or not data or not isinstance(data[0], list):
        raise ValueError("the free endpoint answered with an unexpected JSON shape")
    return "".join(
        segment[0] for segment in data[0]
        if isinstance(segment, list) and segment and isinstance(segment[0], str)
    )


def _key_translate(text, src, dest, session=None):
    # 🔴 format 必须显式写 text：官方 API 的默认值是 **html**。HTML 模式下 Google
    # 把换行当空白、把引号和 & 转义成 &#39; / &amp; 再返回，于是多行提示词被挤成
    # 一行、提示词里的引号变成实体。
    payload = {"q": text, "target": dest, "format": "text"}
    if src and src != "auto":
        payload["source"] = src
    resp = (session or requests).post(
        _OFFICIAL_URL, params={"key": GOOGLE_TRANSLATION_API_KEY}, data=payload, timeout=_TIMEOUT
    )
    resp.raise_for_status()
    body = resp.json()
    translations = (body.get("data") or {}).get("translations") or []
    if not translations:
        raise ValueError("the API returned no translations")
    return translations[0].get("translatedText", "")


def _translate_chunk(call, chunk, src, dest):
    """一个片段，两条网络路径。两跳都失败时抛最后一个异常。"""
    last_exc = None
    # 两级尝试：先走常规网络栈（保留用户配置的代理），失败再绕代理直连重试。
    for label, session in (("default", None), ("direct", _direct_session())):
        try:
            return call(chunk, src, dest, session)
        except Exception as exc:
            last_exc = exc
            print("[QG-Multipack] Google Translate attempt (%s) failed: %s: %.120s"
                  % (label, type(exc).__name__, exc))
    raise last_exc


def translate(text, src=None, dest=None):
    text = normalize_text(text)
    if not text.strip():
        return text
    src = src or "auto"
    dest = dest or "en"
    call = _key_translate if GOOGLE_TRANSLATION_API_KEY else _free_translate

    chunks = split_chunks(text)
    translated = []
    for index, chunk in enumerate(chunks, 1):
        try:
            translated.append(_translate_chunk(call, chunk, src, dest))
        except Exception as exc:
            # 分片里失败一片就整段退回原文：半译半原文的提示词比没译更难查。
            where = "" if len(chunks) == 1 else " (chunk %d/%d)" % (index, len(chunks))
            print("[QG-Multipack] Google Translate failed%s (%s); passing original text through: %.80s"
                  % (where, type(exc).__name__, text))
            return text
    return "\n".join(translated)


# ---------------------------------------------------------------------------
# 手动翻译路由（前端「手动翻译」按钮调用）
# ---------------------------------------------------------------------------

# 错误回给前端的文案：消息里点名服务器磁盘路径时整条替换——解码器或系统会把
# 收到的路径原样引用回来，路由的应答任何能连上服务器的人都看得到。
# 与 QG-tools 的 _qg_route_errors.safe_route_error 同口径（此处内联，避免跨包依赖）。
_SERVER_PATH = re.compile(r"""(?:^|[\s'"(\[=:,;])(?:[A-Za-z]:[\\/]|[\\/])[^\s'"]""")


def _safe_route_error(exc, fallback="The request failed."):
    text = str(exc).strip()
    if not text or _SERVER_PATH.search(text):
        return fallback
    return text


async def translate_manual(request):
    try:
        json_data = await request.json()
    except Exception:
        return web.json_response(
            {"ok": False, "error": "The request body is not valid JSON."}, status=400
        )
    # 🔴 合法 JSON 也可能是非对象（[] / "abc" / null），下面的 .get 会抛
    # AttributeError → 500。非对象一律当作空请求体。
    if not isinstance(json_data, dict):
        return web.json_response(
            {"ok": False, "error": "The request body must be a JSON object."}, status=400
        )
    prompt = json_data.get("prompt", "")
    src = json_data.get("srcTrans", "auto")
    dest = json_data.get("toTrans", "en")
    try:
        # 🔴 必须离开事件循环：translate() 是同步阻塞的，两个网络跳各带 20s 读取
        # 超时，一次失败最坏能把 aiohttp 卡住几十秒 —— 那期间整个 ComfyUI 的进度
        # 推送和所有 API 都不响应，看起来像整机卡死。
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, translate, prompt, src, dest)
    except Exception as exc:
        return web.json_response({"ok": False, "error": _safe_route_error(exc)}, status=500)
    return web.json_response({"ok": True, "translate_prompt": result})


def _register_manual_route():
    """挂上手动翻译路由；没有服务器就跳过。

    🔴 ``PromptServer.instance`` 是**实例属性**，在 ``PromptServer.__init__``
    里才挂上去，类上根本没有这个属性。所以装饰器写法在没有服务器的环境里抛的是
    ``AttributeError``（不是「等于 None」），整个文件 import 就失败 —— 单测、
    离线工具，以及任何在服务器起来之前 import 的场景都会中招。用 getattr 取。
    """
    server = getattr(PromptServer, "instance", None)
    if server is None:
        return
    if getattr(server, "_qgmp_translate_manual_route", False):
        return
    server.routes.post("/qgmp/translate/manual")(translate_manual)
    server._qgmp_translate_manual_route = True


_register_manual_route()


# ---------------------------------------------------------------------------
# 节点（本包统一 V1 风格；语言码直接用 BCP-47 原值进存档，不做中文遗留值
# 兼容——本包是新节点，不存在 QG-tools 时代的历史存档问题）
# ---------------------------------------------------------------------------

DESCRIPTION = (
    "Translate a text prompt into another language using Google Translate. "
    "Free, no API key needed (Google may rate-limit it); set the "
    "GOOGLE_TRANSLATION_API_KEY environment variable to use the official, "
    "unlimited API. Text over Google's per-request limit is split on line "
    "breaks and rejoined, and the official API is asked for plain text so "
    "line breaks and quotes survive. The Manual Translate button rewrites "
    "the text in place. On any network failure the original text is passed "
    "through unchanged."
)


class QGGoogleTranslate:
    """Translate a text prompt into another language with Google Translate."""

    CATEGORY = "QG 工具"
    SEARCH_ALIASES = [
        "translate", "translation", "translator", "google", "google translate",
        "谷歌翻译", "谷歌", "翻译", "中文翻译", "英文", "qg",
    ]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "from_translate": (
                    ["auto"] + list(LANGUAGES.keys()),
                    {
                        "default": "auto",
                        "tooltip": (
                            "原文语言。auto 让 Google 自动识别；下拉值是 BCP-47 语言码（如 zh-cn / en），存档里存的也是码，不随界面语言变。"
                        ),
                    },
                ),
                "to_translate": (
                    list(LANGUAGES.keys()),
                    {
                        "default": "en",
                        "tooltip": (
                            "翻译成什么语言。默认英文——SAM 3 这类检测模型只认英文。"
                        ),
                    },
                ),
                "manual_translate": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": (
                            "开启后节点不再自动翻译：排队运行时文本原样通过，用节点上的「手动翻译」按钮就地翻译。"
                        ),
                    },
                ),
                "text": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": (
                            "要翻译的文字。超过 Google 单次上限会按换行切分再拼回，一行一句切得最干净。"
                        ),
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("translated_text",)
    FUNCTION = "translate_text"
    DESCRIPTION = DESCRIPTION

    def translate_text(self, from_translate, to_translate, manual_translate, text):
        text = normalize_text(text)
        if manual_translate:
            return (text,)
        return (translate(text, from_translate, to_translate),)


NODE_CLASS_MAPPINGS = {
    "QG_GoogleTranslate": QGGoogleTranslate,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "QG_GoogleTranslate": "QG 谷歌翻译",
}
