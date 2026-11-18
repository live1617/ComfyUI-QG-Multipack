# -*- coding: utf-8 -*-
"""P1 修复回归测试（不依赖任何第三方 GPL 参考源码）。

覆盖上一轮审查里 6 组 P1 缺陷：

A. HTTP 错误正文脱敏（translate_core.redact_secrets）
B. config_api_key 不再用非原子 open(..., "w") 覆盖已有配置
C. rules.json 优先写 user 目录、旧文件复制保留、目录不存在时自动建
D. QG_BiRefNet 通道归一（4/2/1/>4 通道）与空 batch 不再抛裸异常
E. QG_ImageToPrompt 空 batch 返回空结果而不是 IndexError
F. 前端生命周期修复的静态回归（取色器浮层清理）

注：原 QG_AddWatermark 图像水印 size_percent=0 修复（旧 D 节）随该节点
移除已删除；原计时器 / 比例分辨率前端定时器清理检查（旧 G 节）随
web/timer.js、web/qg_ratio_resolution.js 移除已删除。

运行：python_embeded\\python.exe tests\\test_p1_robustness.py
"""
import importlib
import json
import os
import sys
import tempfile
import types

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)
# ComfyUI 根：优先环境变量，其次按 custom_nodes/<插件>/tests 相对推导。
# 工作区镜像里推不出来时用最小 stub 顶上，绝不硬编码某台机器的绝对路径
# （P0-3 刚修过测试里硬编码路径的坑）。
_comfy_root = os.environ.get("QG_COMFY_ROOT") or os.path.abspath(
    os.path.join(PKG, "..", ".."))
if os.path.isdir(_comfy_root):
    sys.path.insert(0, _comfy_root)
try:
    import folder_paths  # noqa: F401
except ImportError:
    sys.modules["folder_paths"] = types.ModuleType("folder_paths")
if "comfy" not in sys.modules:
    _comfy_stub = types.ModuleType("comfy")
    _comfy_stub.__path__ = []
    sys.modules["comfy"] = _comfy_stub
if "comfy.model_management" not in sys.modules:
    sys.modules["comfy.model_management"] = types.ModuleType(
        "comfy.model_management")

import translate_core as t  # noqa: E402
import prompt_rules as rules  # noqa: E402
import birefnet_node as bn  # noqa: E402

# 反推节点用相对导入，目录名带连字符不是合法包名，照既有测试造一个包壳
shell = types.ModuleType("qg_pack_p1")
shell.__path__ = [PKG]
sys.modules["qg_pack_p1"] = shell
ip = importlib.import_module("qg_pack_p1.image_to_prompt_node")

ok = 0
fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS", name)
    else:
        fail += 1
        print("FAIL", name, extra)


def js(name):
    with open(os.path.join(PKG, "web", name), "r", encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------------------
print("=== A. 错误正文脱敏 ===")
red = t.redact_secrets
check("Bearer 令牌被打码",
      "sk-abcdef123456" not in red("Authorization: Bearer sk-abcdef123456")
      and "Bearer ***" in red("Authorization: Bearer sk-abcdef123456"))
check("裸 sk- 令牌被打码",
      "sk-abcdef123456" not in red("invalid key sk-abcdef123456"))
check("JSON 里的 api_key 值被打码",
      "secretvalue123" not in red('{"error":{"api_key":"secretvalue123"}}'))
check("传入的真实 Key 被精确打码",
      "my-real-key-9999" not in red("echo my-real-key-9999", ("my-real-key-9999",)))
check("普通错误文案一字不动",
      red("unknown field thinking") == "unknown field thinking")
check("状态码与提示文字保留",
      "HTTP 401" in red("HTTP 401 Bearer sk-abcdef123456"))
check("幂等：脱敏两次结果一致", red(red("Bearer sk-abcdef123456")) == red("Bearer sk-abcdef123456"))

# --------------------------------------------------------------------------
print("=== B. config_api_key 原子写 ===")
tmp = tempfile.mkdtemp(prefix="_qg_p1_cfg_")
cfg = os.path.join(tmp, "config.json")
old_path = t._config_path
t._config_path = lambda: cfg
t._config_cache["stamp"] = None
t._config_cache["data"] = {}
try:
    check("文件不存在时返回空串", t.config_api_key() == "")
    check("缺文件时补出的模板是合法 JSON",
          isinstance(json.load(open(cfg, encoding="utf-8")), dict))
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump({"api_key": "sk-user-real-key", "providers": [{"name": "X"}]}, f)
    t._config_cache["stamp"] = None
    t._config_cache["data"] = {}
    check("已有配置时读出真实 Key", t.config_api_key() == "sk-user-real-key")
    saved = json.load(open(cfg, encoding="utf-8"))
    check("已有配置不被模板覆盖", saved.get("providers") == [{"name": "X"}])
    check("锁可重入（config_api_key 内会再调 save_config）",
          type(t._CONFIG_LOCK).__name__ == "RLock")
    with t._CONFIG_LOCK:
        check("持锁时调用不死锁", t.config_api_key() == "sk-user-real-key")
finally:
    t._config_path = old_path
    t._config_cache["stamp"] = None
    t._config_cache["data"] = {}

# --------------------------------------------------------------------------
print("=== C. rules.json 路径 ===")
old_dir = rules.RULES_DIR
old_cache = rules._auto_rules_dir_cache
old_pack = rules._PACK_DIR
old_auto = rules._auto_rules_dir
try:
    tmp_rules = tempfile.mkdtemp(prefix="_qg_p1_rules_")
    rules.RULES_DIR = tmp_rules
    check("显式指定目录时路径不变且不迁移",
          rules.rules_path() == os.path.join(tmp_rules, "rules.json"))
    nested = os.path.join(tmp_rules, "deep", "user")
    rules.RULES_DIR = nested
    rules.save_rules({"optimize": [{"name": "测试规则", "content": "正文"}]})
    check("目录不存在时 save_rules 自动创建",
          os.path.exists(os.path.join(nested, "rules.json")))
    check("写进去的规则读得回来",
          any(x["name"] == "测试规则" for x in rules.load_rules()["optimize"]))
    check("fingerprint 用 mtime:size", ":" in rules.fingerprint())

    # 旧版把 rules.json 放在插件目录：应复制到 user 目录、原文件保留
    legacy_dir = os.path.join(tmp_rules, "legacy_pack")
    user_dir = os.path.join(tmp_rules, "user")
    os.makedirs(legacy_dir)
    os.makedirs(user_dir)
    legacy_file = os.path.join(legacy_dir, "rules.json")
    with open(legacy_file, "w", encoding="utf-8") as f:
        json.dump({"version": 3, "groups": {}}, f)
    rules._PACK_DIR = legacy_dir
    rules.RULES_DIR = None
    rules._auto_rules_dir = lambda: user_dir
    path = rules.rules_path()
    check("自动定位到 user 目录", path == os.path.join(user_dir, "rules.json"))
    check("旧规则被复制过去", os.path.exists(path))
    check("插件目录原文件保留（不搬走）", os.path.exists(legacy_file))
    check("复制内容一致",
          json.load(open(path, encoding="utf-8"))["version"] == 3)
finally:
    rules.RULES_DIR = old_dir
    rules._auto_rules_dir_cache = old_cache
    rules._PACK_DIR = old_pack
    rules._auto_rules_dir = old_auto

# --------------------------------------------------------------------------
print("=== D. BiRefNet 通道归一 / 空 batch ===")
f = bn._frame_to_rgb_uint8
rgb = np.full((4, 5, 3), 0.5, dtype=np.float32)
check("3 通道形状与取值", f(rgb).shape == (4, 5, 3)
      and int(f(rgb)[0, 0, 0]) == 128)
rgba0 = np.zeros((4, 5, 4), dtype=np.float32)
check("4 通道 alpha=0 压成白底", bool(np.all(f(rgba0) == 255)))
rgba1 = rgba0.copy()
rgba1[..., :3] = 0.5
rgba1[..., 3] = 1.0
check("4 通道 alpha=1 保留原色", bool(np.all(f(rgba1) == 128)))
gray = np.full((4, 5, 1), 0.25, dtype=np.float32)
check("1 通道复制成三通道且相等",
      f(gray).shape == (4, 5, 3) and bool(np.all(f(gray)[..., 0] == f(gray)[..., 1])))
la = np.zeros((4, 5, 2), dtype=np.float32)
la[..., 0] = 0.5
la[..., 1] = 0.9
check("2 通道不把 alpha 当绿通道",
      bool(np.all(f(la)[..., 0] == f(la)[..., 1]))
      and bool(np.all(f(la)[..., 1] == f(la)[..., 2])))
five = np.zeros((4, 5, 5), dtype=np.float32)
five[..., 0] = 0.5
check(">4 通道切前三", f(five).shape == (4, 5, 3)
      and int(f(five)[0, 0, 0]) == 128)
check("2D 灰度也补成三通道", f(np.full((4, 5), 0.5, dtype=np.float32)).shape == (4, 5, 3))

model = next(iter(bn.MODEL_CONFIG))
try:
    out = bn.QGBiRefNet().run(torch.empty(0, 12, 16, 3), model)
    check("空 batch 三个输出形状正确",
          tuple(out[0].shape) == (0, 12, 16, 3)
          and tuple(out[1].shape) == (0, 12, 16)
          and tuple(out[2].shape) == (0, 12, 16, 3),
          tuple(x.shape for x in out))
except Exception as exc:  # noqa: BLE001
    check("空 batch 三个输出形状正确", False, repr(exc))

# --------------------------------------------------------------------------
print("=== E. 反推节点空 batch ===")
try:
    node = ip.QGImageToPrompt()
    res = node.execute(torch.empty(0, 8, 8, 3), "", False, "", "", "")
    check("空 batch 返回空文本与空列表", res == ("", []), res)
except Exception as exc:  # noqa: BLE001
    check("空 batch 返回空文本与空列表", False, repr(exc))

# --------------------------------------------------------------------------
print("=== F. 前端修复静态回归 ===")
qwen_js = js("qg_qwen_prompt_optimizer.js")
# 6 个 hook = configure / onNodeCreated / onResize / onConnectionsChange /
# onConfigure / onExecuted。configure 是为「自定义skill」槽对齐上游新增的，
# 载入工作流时按存档槽名还原顺序，同样必须接住并传回原实现返回值。
check("6 个生命周期 hook 都接收原返回值",
      qwen_js.count("const result = original") == 6,
      qwen_js.count("const result = original"))
check("6 个 hook 都把返回值传下去", qwen_js.count("return result;") == 6,
      qwen_js.count("return result;"))
check("skill 槽排在图像槽之后并修正连线归属",
      "syncSkillInput(node)" in qwen_js
      and 'const SKILL_INPUT_NAME = "自定义skill"' in qwen_js
      and "link.target_slot = target" in qwen_js)
picker_js = js("qg_color_picker.js")
check("取色器浮层在节点删除时收起",
      "onRemoved" in picker_js and "panelOwner?.node === this" in picker_js)

print(f"\n=== 合计：PASS {ok} / FAIL {fail} ===")
sys.exit(1 if fail else 0)
