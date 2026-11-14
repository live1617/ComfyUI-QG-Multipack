# -*- coding: utf-8 -*-
"""v0.1.3 P2 回归：把「旧日志里挂着的未验证项」能本机验证的部分做成可复现测试。

严格区分「已做」与「没做」，不许把没跑的写成已验证：

* 已做：百度两条翻译通道 + QG_PromptTranslate.execute 的**本地端到端**
  （起一个 127.0.0.1 假服务，走完整的签名 / 分块 / 请求 / 解析 / 回落 /
  错误码 / 缓存链路，不发一个真实请求、不花一分额度）；BiRefNet 模型定义
  补丁副本的生成与语法；Qwen GGUF 的依赖状态与模型清单分流。
* 没做、也不伪称做了：连真实百度 API 的成功路径、Qwen GGUF 真推理一次、
  SAM3 在 GPU 下重新推理、#56 换模型后的输出质量主观复测。这四项需要真实
  外部服务 / 权重 / 用户判断，在 ISSUES.md 里逐条登记为待验证。

运行：python_embeded\\python.exe tests\\test_p2_live_paths.py
"""
import hashlib
import importlib
import io
import json
import os
import sys
import tempfile
import threading
import types
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)
_comfy_root = os.environ.get("QG_COMFY_ROOT") or os.path.abspath(
    os.path.join(PKG, "..", ".."))
if os.path.isdir(_comfy_root):
    sys.path.insert(0, _comfy_root)

_TMP = tempfile.mkdtemp(prefix="qg_p2_live_")


def _stub(name, **attrs):
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    if name == "comfy":
        mod.__path__ = []
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


# folder_paths 在真实 ComfyUI 里 models_dir 是「字符串路径」，不是函数；
# 优先用真模块，只有拿不到时才造 stub，且 stub 形状必须与真模块一致。
try:
    import folder_paths as _fp  # noqa: F401
except ImportError:
    _fp = _stub("folder_paths",
                get_temp_directory=lambda: _TMP,
                get_filename_list=lambda _name: [],
                models_dir=_TMP,
                folder_names_and_paths={},
                get_folder_paths=lambda _name: [])
_stub("comfy")
_stub("comfy.model_management")
_stub("comfy.utils")
_stub("node_helpers")
if "server" not in sys.modules:
    class _Routes:
        def post(self, _path):
            return lambda fn: fn

        def get(self, _path):
            return lambda fn: fn

    class _ServerInstance:
        def __init__(self):
            self.routes = _Routes()

        def __call__(self):
            return self

    class _PromptServer:
        instance = _ServerInstance()

    _stub("server", PromptServer=_PromptServer)

shell = types.ModuleType("qg_pack_p2_live")
shell.__path__ = [PKG]
sys.modules["qg_pack_p2_live"] = shell
pt = importlib.import_module("qg_pack_p2_live.prompt_translate_node")
bn = importlib.import_module("qg_pack_p2_live.birefnet_node")
qo = importlib.import_module("qg_pack_p2_live.qwen_prompt_optimizer_node")

ok = 0
fail = 0
RECORDS = []
LLM_REPLY = {"mode": "ok"}


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS", name)
    else:
        fail += 1
        print("FAIL", name, extra)


def safe(name, fn, *args, **kwargs):
    try:
        check(name, bool(fn(*args, **kwargs)))
    except Exception as exc:  # noqa: BLE001
        global fail
        fail += 1
        print("FAIL", name, "%s: %s" % (type(exc).__name__, exc))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):  # noqa: N802 - http.server 的约定
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        RECORDS.append((self.path, self.headers.get("Content-Type", ""), raw))
        llm = self.path.endswith("/llm")
        if llm and LLM_REPLY["mode"] == "fallback":
            payload = {"error_code": "52003", "error_msg": "not authorized"}
        elif not llm and LLM_REPLY["mode"] == "sign_error":
            payload = {"error_code": "54001", "error_msg": "invalid sign"}
        else:
            if llm:
                q = json.loads(raw.decode("utf-8"))["q"]
                payload = {"data": {"trans_result": [{"dst": "LLM:" + q}]}}
            else:
                q = urllib.parse.parse_qs(raw.decode("utf-8"))["q"][0]
                payload = {"trans_result": [{"dst": "EN:" + q}]}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
base = "http://127.0.0.1:%d" % server.server_port

# 把所有对外地址换成本地假服务；限速关掉，避免测试平白睡 3 秒。
pt.BAIDU_URL = base + "/general"
pt.BAIDU_LLM_URL = base + "/llm"
pt.baidu_credentials = lambda: ("fake_appid", "fake_key")
pt.QPS_GAP = 0.0
pt._last_call = 0.0
pt.TIMEOUT = 5
pt._CACHE.clear()

print("== 一、百度翻译两条通道（本地端到端） ==")
RECORDS.clear()
safe("通用通道：成功返回译文",
     lambda: pt.translate_baidu("一只猫", "chinese", "english") == "EN:一只猫")
safe("通用通道：请求打到假服务且是表单",
     lambda: len(RECORDS) == 1 and RECORDS[0][0] == "/general"
     and "x-www-form-urlencoded" in RECORDS[0][1])
fields = urllib.parse.parse_qs(RECORDS[0][2].decode("utf-8")) if RECORDS else {}
safe("通用通道：语言码按百度口径映射",
     lambda: fields.get("from") == ["zh"] and fields.get("to") == ["en"])
safe("通用通道：salt 是字符串（与大模型通道相反）",
     lambda: fields.get("salt") and fields["salt"][0].isdigit())
safe("通用通道：MD5 签名正确",
     lambda: fields.get("sign") == [hashlib.md5(
         ("fake_appid" + "一只猫" + fields["salt"][0] + "fake_key")
         .encode("utf-8")).hexdigest()])

RECORDS.clear()
safe("大模型通道：成功返回译文",
     lambda: pt.translate_baidu_llm("一只猫", "chinese", "english") == "LLM:一只猫")
llm_body = json.loads(RECORDS[0][2].decode("utf-8")) if RECORDS else {}
safe("大模型通道：salt 是数字不是字符串（历史真 bug 回归）",
     lambda: isinstance(llm_body.get("salt"), int))
safe("大模型通道：带提示词风格指令",
     lambda: "(word:1.2)" in str(llm_body.get("reference", "")))
safe("大模型通道：JSON 请求头", lambda: "application/json" in RECORDS[0][1])

print()
print("== 二、回落 / 错误码 / 分段 / 节点 execute ==")
LLM_REPLY["mode"] = "fallback"
RECORDS.clear()
safe("大模型没开通时自动回落通用翻译",
     lambda: pt.translate_baidu_llm("一只猫", "chinese", "english") == "EN:一只猫")
safe("回落确实打了两个不同接口",
     lambda: [r[0] for r in RECORDS] == ["/llm", "/general"])
LLM_REPLY["mode"] = "sign_error"
try:
    pt.translate_baidu("一只猫", "chinese", "english")
    sign_err = ""
except pt.BaiduError as exc:
    sign_err = str(exc)
safe("签名错误翻成中文提示", lambda: "签名错误" in sign_err)
LLM_REPLY["mode"] = "ok"

RECORDS.clear()
long_text = "a" * 2500
chunked = pt.translate_baidu(long_text, "english", "chinese")
safe("2500 字符分 3 段请求", lambda: len(RECORDS) == 3)
safe("分段译文拼回不丢字、不硬塞换行",
     lambda: chunked.count("EN:") == 3
     and chunked.replace("EN:", "") == long_text
     and "\n" not in chunked)

pt._CACHE.clear()
node = pt.QGPromptTranslate()
safe("节点 execute：中文→英文走通整条链路",
     lambda: node.execute("一只猫", "English", pt.BAIDU) == ("EN:一只猫",))
safe("节点 execute：空文本直通",
     lambda: node.execute("", "English", pt.BAIDU) == ("",))
safe("节点 execute：原文已是目标语言则跳过请求",
     lambda: node.execute("a cat", "English", pt.BAIDU) == ("a cat",))
LLM_REPLY["mode"] = "sign_error"
pt._CACHE.clear()
safe("节点 execute：翻译失败不挡工作流、原文原样输出",
     lambda: node.execute("另一只猫", "English", pt.BAIDU) == ("另一只猫",))
LLM_REPLY["mode"] = "ok"
pt._CACHE.clear()
node.execute("缓存猫", "English", pt.BAIDU)
before = len(RECORDS)
node.execute("缓存猫", "English", pt.BAIDU)
safe("节点 execute：命中缓存不重复请求", lambda: len(RECORDS) == before)

print()
print("== 三、BiRefNet 模型定义补丁（只读原文件、写副本） ==")
orig = os.path.join(_TMP, "birefnet_probe.py")
original_src = (
    "from .BiRefNet_config import Config\n"
    "class X:\n"
    "    def f(self, attn, mask, B_, nW, N):\n"
    "        attn = attn.view(B_ // nW, nW, self.num_heads, N, N) "
    "+ mask.unsqueeze(1).unsqueeze(0)\n"
    "        return attn\n"
)
with io.open(orig, "w", encoding="utf-8") as handle:
    handle.write(original_src)
bn._writable_patch_dir = lambda: _TMP
dest = bn._patched_script(orig)
patched_src = io.open(dest, encoding="utf-8").read()
check("补丁写到副本而不是就地改原文件", dest != orig)
check("原文件一字未动",
      io.open(orig, encoding="utf-8").read() == original_src)
check("副本修掉相对导入", "from BiRefNet_config import Config" in patched_src)
check("副本修掉 fp16 dtype 不一致", "mask.to(attn.dtype)" in patched_src)
safe("补丁副本语法可编译", lambda: bool(compile(patched_src, dest, "exec")))
safe("已修好的原文件直接返回原路径",
     lambda: bn._patched_script(dest) == dest)

print()
print("== 四、Qwen GGUF 依赖状态与模型清单 ==")
status = qo._llama_dependency_status()
check("依赖状态含 needs_install / reason",
      isinstance(status, dict) and isinstance(status.get("needs_install"), bool)
      and isinstance(status.get("reason"), str))
print("INFO 本机 llama-cpp-python 状态：needs_install=%s reason=%s"
      % (status.get("needs_install"), status.get("reason")))
old_list = qo.folder_paths.get_filename_list
qo.folder_paths.get_filename_list = lambda _n: [
    "Qwen-Image-2.1-PE-T2I.Q5_K_S.gguf", "mmproj-BF16.gguf"]
llms, mmprojs = qo._all_choices()
check("模型清单把 mmproj 分到第二列",
      llms == ["Qwen-Image-2.1-PE-T2I.Q5_K_S.gguf"]
      and mmprojs == ["mmproj-BF16.gguf"])
qo.folder_paths.get_filename_list = old_list
target = qo._llama_install_target()
check("安装目标含平台标记与 wheel 后缀",
      isinstance(target, dict) and "tag_marker" in target and "wheel_suffix" in target)

server.shutdown()
server.server_close()

print()
print("== 本文件明确不覆盖（如实登记到 ISSUES.md） ==")
for item in (
    "连真实百度 API 的成功路径（需真实 appid/密钥与额度）",
    "Qwen GGUF 真推理一次（本机无 llama-cpp-python，需安装并加载权重）",
    "SAM3 补丁在 GPU 下重新推理（需加载 sam3.1 权重与显存）",
    "#56 换模型后的输出质量复测（需真实 LLM 调用 + 用户主观确认）",
):
    print("NOT_COVERED", item)

print()
print("TOTAL ok=%d fail=%d" % (ok, fail))
sys.exit(1 if fail else 0)
