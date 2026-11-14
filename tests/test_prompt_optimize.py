# -*- coding: utf-8 -*-
"""提示词优化节点回归：下拉内容、两路合并、规则拼装、指纹、错误文案。

不联网：``ask_text`` 被替换成假的，只看节点自己负责的那部分——把原文、
规则、服务拼成一次正确的调用，并把返回整理干净。
"""
import importlib
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

# 目录名带连字符，不是合法包名，造个包壳给相对导入用
shell = types.ModuleType("qg_pack")
shell.__path__ = [PKG]
sys.modules["qg_pack"] = shell
mod = importlib.import_module("qg_pack.prompt_optimize_node")
rules = importlib.import_module("qg_pack.prompt_rules")

fails = []


def check(label, cond, extra=""):
    print(("  " + label + ": " + str(extra)).ljust(70),
          "PASS" if cond else "FAIL")
    if not cond:
        fails.append(label)


print("=== A. 节点定义 ===")
node = mod.QGPromptOptimize()
spec = node.INPUT_TYPES()
required = list(spec["required"])
optional = list(spec.get("optional", {}))
check("控件顺序", required == [
    "text", "rule", "custom_rule", "custom_rule_content",
    "llm_service", "auto_unload", "seed"], required)
check("只有一路可选输入", optional == ["extra_text"], optional)
check("可选口是强制输入", spec["optional"]["extra_text"][1].get("forceInput") is True)

rule_choices = spec["required"]["rule"][0]
optimize_names = [i["name"] for i in rules.load_rules()["optimize"]]
check("规则下拉只含优化组", rule_choices == optimize_names, rule_choices)
check("默认规则是激活项", spec["required"]["rule"][1]["default"]
      == rules.active("optimize")["name"], spec["required"]["rule"][1]["default"])
check("下拉里没有反推规则", "像素级描述" not in rule_choices)

services = spec["required"]["llm_service"][0]
default_service = spec["required"]["llm_service"][1]["default"]
check("服务下拉非空", len(services) >= 1, len(services))
check("默认服务在列表里", default_service in services, default_service)
check("默认服务不是空地址占位", default_service != "custom" or services == ["custom"],
      default_service)
check("种子接生成后控制",
      spec["required"]["seed"][1].get("control_after_generate") is True)
check("输出是单个字符串", node.RETURN_TYPES == ("STRING",) and node.RETURN_NAMES == ("提示词输出",))

print("=== B. 两路文本合并 ===")
check("两路都空", mod.merge_texts("", "") == "")
check("只有本框", mod.merge_texts("a", "") == "a")
check("只有上游", mod.merge_texts("", "b") == "b")
check("两路空一行分隔", mod.merge_texts("a", "b") == "a\n\nb")
check("两端空白被去掉", mod.merge_texts("  a  ", "\n b \n") == "a\n\nb")
check("None 当空处理", mod.merge_texts(None, "b") == "b")

print("=== C. 指纹 ===")
base = dict(text="a", rule="扩写-通用", custom_rule=False,
            custom_rule_content="", llm_service="DeepSeek",
            auto_unload=True, seed=0, extra_text="")
fp = node.IS_CHANGED(**base)
check("是 md5 长度", isinstance(fp, str) and len(fp) == 32, fp)
check("同参数同指纹", node.IS_CHANGED(**base) == fp)
check("换原文换指纹", node.IS_CHANGED(**{**base, "text": "b"}) != fp)
check("换上游文本换指纹", node.IS_CHANGED(**{**base, "extra_text": "z"}) != fp)
check("换规则换指纹", node.IS_CHANGED(**{**base, "rule": "润色-精炼"}) != fp)
check("换种子换指纹", node.IS_CHANGED(**{**base, "seed": 7}) != fp)
check("换服务换指纹", node.IS_CHANGED(**{**base, "llm_service": "Zhipu GLM"}) != fp)

# 规则正文在 rules.json 里，节点输入只有规则「名字」。名字不变而正文改了
# 时，IS_CHANGED 必须变，否则 ComfyUI 会认为输入没动、直接复用上次输出，
# 用户在规则管理器里改措辞就等于没改。这里把 RULES_DIR 指到临时目录验证。
print("=== C2. 规则文件改动会顶掉节点缓存 ===")
import tempfile
import time as _time

_tmp = tempfile.mkdtemp(prefix="qg-rules-")
_old_dir = rules.RULES_DIR
try:
    rules.RULES_DIR = _tmp
    _fp_missing = rules.fingerprint()
    with open(os.path.join(_tmp, "rules.json"), "w", encoding="utf-8") as fh:
        fh.write('{"version": 3, "groups": {}}')
    _fp_first = rules.fingerprint()
    check("从「没有规则文件」到「有文件」指纹会变", _fp_first != _fp_missing,
          (_fp_missing, _fp_first))

    _node_before = node.IS_CHANGED(**base)
    _time.sleep(0.02)          # 保证 mtime 一定变（NTFS 精度 100ns，这行只为稳）
    with open(os.path.join(_tmp, "rules.json"), "w", encoding="utf-8") as fh:
        fh.write('{"version": 3, "groups": {"optimize": [{"name": "x", '
                 '"content": "改过的正文"}]}}')
    _fp_second = rules.fingerprint()
    check("内容改了指纹跟着变", _fp_second != _fp_first, (_fp_first, _fp_second))
    check("规则改名不动、正文改了，节点也判成「变了」",
          node.IS_CHANGED(**base) != _node_before)
finally:
    rules.RULES_DIR = _old_dir
    import shutil
    shutil.rmtree(_tmp, ignore_errors=True)

print("=== D. 服务解析 ===")
try:
    mod.resolve_service("")
    check("空服务报错", False)
except ValueError as error:
    check("空服务报错", "没有选择 LLM 服务" in str(error), str(error)[:40])

try:
    mod.resolve_service("不存在的服务商")
    check("空地址报错", False)
except ValueError as error:
    check("空地址报错", "没有配置 API 地址" in str(error), str(error)[:40])

target = mod.resolve_service("DeepSeek")
check("预设解析出地址", target["api_url"].startswith("https://api.deepseek.com"), target["api_url"])
check("默认模型", target["model"] == "deepseek-chat", target["model"])

target = mod.resolve_service("DeepSeek/deepseek-reasoner")
check("指名模型", target["model"] == "deepseek-reasoner", target["model"])

print("=== E. 规则拼装与执行 ===")
seen = {}


def fake_ask(system_text, user_text, target, on_delta=None):
    seen["system"] = system_text
    seen["user"] = user_text
    seen["target"] = target
    return "  一段 优化后的提示词  "


mod.ask_text = fake_ask
out = node.execute(text="一个女孩", rule="扩写-通用", custom_rule=False,
                   custom_rule_content="", llm_service="DeepSeek",
                   auto_unload=False, seed=0, extra_text="逆光")
check("返回整理后的文本", out == ("一段 优化后的提示词",), out)
check("两路都进了 user", seen["user"] == "一个女孩\n\n逆光", seen.get("user"))
check("system 带规则正文", "AI 生图提示词编辑" in seen["system"],
      seen.get("system", "")[:30])
check("system 带禁思考", "不要输出思考过程" in seen["system"])

node.execute(text="x", rule="扩写-通用", custom_rule=True,
             custom_rule_content="我的规则：只输出英文", llm_service="DeepSeek",
             auto_unload=False, seed=0)
check("自定义规则整段替换", seen["system"].startswith("我的规则：只输出英文"),
      seen["system"][:20])
check("自定义规则也带禁思考", "不要输出思考过程" in seen["system"])

node.execute(text="x", rule="像素级描述", custom_rule=False,
             custom_rule_content="", llm_service="DeepSeek",
             auto_unload=False, seed=0)
check("反推规则名回退到优化组", "AI 生图提示词编辑" in seen["system"],
      seen["system"][:30])

try:
    node.execute(text="", rule="扩写-通用", custom_rule=False,
                 custom_rule_content="", llm_service="DeepSeek",
                 auto_unload=False, seed=0, extra_text="")
    check("空输入报错", False)
except RuntimeError as error:
    check("空输入报错", "没有输入" in str(error), str(error)[:30])

print("\n---")
print("失败 %d 项" % len(fails))
if not fails:
    print("全部通过")
sys.exit(1 if fails else 0)
