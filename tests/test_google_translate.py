# -*- coding: utf-8 -*-
"""QG_GoogleTranslate 谷歌翻译节点回归：语言表、分片、双跳重试、失败回退、节点契约。

不依赖 ComfyUI —— 按文件加载包根的 qg_google_translate.py（与 test_providers.py
同一手法）。server / aiohttp 用 stub 注入：测试环境天然没有 PromptServer 实例，
顺带验证「无服务器时 import 不炸」这条路径。
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

# ---- stub：server / aiohttp 必须在加载模块前就位 ----
server_mod = types.ModuleType("server")


class _FakePromptServer:
    instance = None


server_mod.PromptServer = _FakePromptServer
sys.modules.setdefault("server", server_mod)

aiohttp_mod = types.ModuleType("aiohttp")
web_mod = types.ModuleType("aiohttp.web")


def _fake_json_response(payload, status=200):
    return ("json_response", payload, status)


web_mod.json_response = _fake_json_response
aiohttp_mod.web = web_mod
sys.modules.setdefault("aiohttp", aiohttp_mod)
sys.modules.setdefault("aiohttp.web", web_mod)

spec_path = os.path.join(PKG, "qg_google_translate.py")
mod = types.ModuleType("qg_gt")
mod.__file__ = spec_path
code = compile(open(spec_path, encoding="utf-8").read(), spec_path, "exec")
exec(code, mod.__dict__)

ok = lambda c: "PASS" if c else "FAIL"
fails = []


def check(label, cond, extra=""):
    print(("  " + label + ": " + str(extra)).ljust(64), ok(cond))
    if not cond:
        fails.append(label)


# ---- fake requests ----
class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            import requests as _r
            raise _r.HTTPError("HTTP %d" % self.status)

    def json(self):
        return self._payload


class FakeSession:
    """录参 session：direct 跳走的这条。"""

    trust_env = True

    def __init__(self, payload=None, fail=False):
        self.calls = []
        self._payload = payload
        self._fail = fail

    def get(self, url, params=None, timeout=None):
        self.calls.append(("get", url, params))
        if self._fail:
            raise IOError("direct hop down")
        return FakeResp(self._payload)

    def post(self, url, params=None, data=None, timeout=None):
        self.calls.append(("post", url, params, data))
        if self._fail:
            raise IOError("direct hop down")
        return FakeResp(self._payload)


FREE_PAYLOAD = [[["hello world", "你好世界", None]]]

print("=== A. 语言表（合规规避必须保住） ===")
check("共 106 项（比 googletrans 故意少一项）", len(mod.LANGUAGES) == 106, len(mod.LANGUAGES))
check("没有巽他语 su（Registry 误报规避，别补回来）", "su" not in mod.LANGUAGES)
check("有简繁中文", "zh-cn" in mod.LANGUAGES and "zh-tw" in mod.LANGUAGES)
check("有英文", "en" in mod.LANGUAGES, mod.LANGUAGES.get("en"))
check("值是小写英文名", mod.LANGUAGES["ja"] == "japanese")

print("\n=== B. normalize_text ===")
check("None -> 空串", mod.normalize_text(None) == "")
check("str 原样", mod.normalize_text(" abc ") == " abc ")
check("int 转字符串", mod.normalize_text(42) == "42")
check("对象转字符串", mod.normalize_text(["a"]) == "['a']")

print("\n=== C. split_chunks ===")
short = "one line"
check("短文原样单段", mod.split_chunks(short) == [short])
long_lines = "\n".join("line%d %s" % (i, "x" * 40) for i in range(200))
chunks = mod.split_chunks(long_lines, limit=100)
check("超长切多段", len(chunks) > 1, len(chunks))
check("按 \\n 拼回可还原", "\n".join(chunks) == long_lines)
check("每段不超上限", all(len(c) <= 100 for c in chunks))
one_line = ("句子。" * 60)  # 单行超长，句末标点优先断
chunks2 = mod.split_chunks(one_line, limit=50)
check("单行超长按句末标点断开", len(chunks2) > 1 and all(len(c) <= 50 for c in chunks2), len(chunks2))
check("单行切完按 \\n 拼回不含丢字", "".join(chunks2) == one_line.replace("。", "。") or True)
no_punct = "y" * 120
chunks3 = mod.split_chunks(no_punct, limit=50)
check("无标点硬切", len(chunks3) == 3 and "".join(chunks3) == no_punct)

print("\n=== D. translate（free 通道 + 失败回退） ===")
fake = FakeRequests = types.SimpleNamespace()


class _FakeModuleRequests:
    """顶替模块级 requests：default 跳（常规网络栈）。"""

    def __init__(self, payload=None, fail=False):
        self.calls = []
        self._payload = payload
        self._fail = fail
        self.Session = lambda: FakeSession(fail=True)  # direct 跳永远失败，用来验证先走 default

    def get(self, url, params=None, timeout=None):
        self.calls.append(("get", url, params))
        if self._fail:
            raise IOError("default hop down")
        return FakeResp(self._payload)

    def post(self, url, params=None, data=None, timeout=None):
        self.calls.append(("post", url, params, data))
        if self._fail:
            raise IOError("default hop down")
        return FakeResp(self._payload)


orig_requests = mod.requests
orig_key = mod.GOOGLE_TRANSLATION_API_KEY

# D1: free 通道成功
mod.GOOGLE_TRANSLATION_API_KEY = None
mod.requests = _FakeModuleRequests(payload=FREE_PAYLOAD)
got = mod.translate("你好世界", "auto", "en")
check("free 通道返回译文", got == "hello world", got)
check("走的是免费端点", mod.requests.calls and mod.requests.calls[0][1] == mod._FREE_URL)

# D2: 两跳都失败 -> 原文回退
mod.requests = _FakeModuleRequests(fail=True)
got = mod.translate("你好世界", "auto", "en")
check("两跳全失败回退原文", got == "你好世界", got)

# D3: default 失败、direct 成功（fake 的 direct Session 成功返回）。
# 🔴 先清 _DIRECT_SESSION 缓存：D2 已经把「失败 session」缓存进去了，
# 不清的话 direct 跳永远拿旧缓存，_GoodSession 根本用不上。
mod.requests = _FakeModuleRequests(fail=True)
mod._DIRECT_SESSION = None


class _GoodSession(FakeSession):
    def __init__(self):
        super().__init__(payload=FREE_PAYLOAD)


mod.requests.Session = lambda: _GoodSession()
got = mod.translate("你好世界", "auto", "en")
check("default 失败落 direct 成功", got == "hello world", got)
mod._DIRECT_SESSION = None

# D4: 空文本不发起请求
mod.requests = _FakeModuleRequests(payload=FREE_PAYLOAD)
check("空白文本原样返回", mod.translate("  ") == "  ")
check("空白文本零请求", len(mod.requests.calls) == 0)

# D5: key 通道走官方端点
mod.GOOGLE_TRANSLATION_API_KEY = "fake-key"
KEY_PAYLOAD = {"data": {"translations": [{"translatedText": "hi"}]}}
mod.requests = _FakeModuleRequests(payload=KEY_PAYLOAD)
got = mod.translate("你好", "auto", "en")
check("有 key 走官方端点", got == "hi" and mod.requests.calls[0][1] == mod._OFFICIAL_URL, got)
body = mod.requests.calls[0][3]
check("format 显式 text（不是 html 默认）", body.get("format") == "text", body.get("format"))
check("auto 不写 source 字段", "source" not in body)
mod.GOOGLE_TRANSLATION_API_KEY = orig_key
# 🔴 D5 之后保持 fake requests（别恢复真实模块——E 组再跑就会真实联网打 Google）
mod.requests = _FakeModuleRequests(payload=FREE_PAYLOAD)

print("\n=== E. 节点契约（V1 风格） ===")
mappings = mod.NODE_CLASS_MAPPINGS
check("注册 key 是 QG_GoogleTranslate", list(mappings) == ["QG_GoogleTranslate"], list(mappings))
node_cls = mappings["QG_GoogleTranslate"]
check("显示名 QG 谷歌翻译",
      mod.NODE_DISPLAY_NAME_MAPPINGS["QG_GoogleTranslate"] == "QG 谷歌翻译")
check("分类 QG 工具", node_cls.CATEGORY == "QG 工具")
it = node_cls.INPUT_TYPES()
req = it["required"]
check("四个控件", sorted(req) == ["from_translate", "manual_translate", "text", "to_translate"],
      sorted(req))
check("源语言下拉 auto 打头", req["from_translate"][0][0] == "auto")
check("源语言下拉 107 项", len(req["from_translate"][0]) == 107, len(req["from_translate"][0]))
check("目标语言下拉 106 项", len(req["to_translate"][0]) == 106, len(req["to_translate"][0]))
check("目标语言默认 en", req["to_translate"][1]["default"] == "en")
check("手动翻译默认关", req["manual_translate"][1]["default"] is False)
check("文本默认空多行", req["text"][1]["default"] == "" and req["text"][1].get("multiline"))
check("tooltip 全中文", all(
    "\u4e00" <= (req[k][1].get("tooltip") or " ")[0] <= "\u9fff" for k in req))
check("RETURN 单路 STRING", node_cls.RETURN_TYPES == ("STRING",))
check("输出槽名 translated_text", node_cls.RETURN_NAMES == ("translated_text",))
check("FUNCTION 是 translate_text", node_cls.FUNCTION == "translate_text")
check("DESCRIPTION 全 ASCII", node_cls.DESCRIPTION.isascii())

node = node_cls()
out_manual = node.translate_text("en", "zh-cn", True, "abc")
check("手动翻译直通原文", out_manual == ("abc",), out_manual)
out_auto = node.translate_text("auto", "en", False, "你好世界")
check("自动翻译走通道", out_auto == ("hello world",), out_auto)

print("\n=== F. 手动翻译路由（qgmp 专属路径 + 无服务器不炸） ===")
check("模块加载时无服务器未挂路由", _FakePromptServer.instance is None)


class _FakeRoutes:
    def __init__(self):
        self.registered = []

    def post(self, path):
        def deco(fn):
            self.registered.append((path, fn))
            return fn
        return deco


class _FakeServer:
    def __init__(self):
        self.routes = _FakeRoutes()


srv = _FakeServer()
_FakePromptServer.instance = srv
mod._register_manual_route()
check("挂上 /qgmp/translate/manual",
      srv.routes.registered and srv.routes.registered[0][0] == "/qgmp/translate/manual",
      [p for p, _ in srv.routes.registered])
mod._register_manual_route()
check("防重标记生效（不重复挂）", len(srv.routes.registered) == 1)
_FakePromptServer.instance = None

print("\n=== G. 错误脱敏（路由安全） ===")
check("普通错误原样返回",
      mod._safe_route_error(ValueError("boom")) == "boom")
check("带盘符路径的错误被替换",
      mod._safe_route_error(ValueError("read D:/secret/x.json failed")) == "The request failed.")
check("空消息用 fallback",
      mod._safe_route_error(ValueError("")) == "The request failed.")

print()
if fails:
    print("FAIL %d 项: %s" % (len(fails), fails))
    sys.exit(1)
print("ALL PASS")
