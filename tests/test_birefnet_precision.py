# -*- coding: utf-8 -*-
"""QG_BiRefNet 推理精度回归测试。

背景（v2.15.11）：节点曾在 CUDA 上无条件 ``model.half()``，BiRefNet 的中间
特征在 fp16 下溢出 65504，整张 1024x1024 输出 100% NaN；``(nan*255).astype
(uint8)`` 把 NaN 变成 0，遮罩全空 → 前景透明度全 0 → 用户只看到一块纯色
背景（截图里那块纯红）。同一张图 fp32 下前景占比 48%，完全正常。

本测试固化四件事：

A. 默认不开 fp16，只有显式 ``QG_BIRefNET_FP16=1`` 才尝试
B. NaN 在 cast 之前必须被清掉（不能静默变 0）
C. fp16 出 NaN 要有自动降级回 fp32 的路径
D. 遮罩几乎全空时要留一条能看懂的日志

运行：python_embeded\\python.exe tests\\test_birefnet_precision.py
"""
import os
import sys
import types

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)
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

import birefnet_node as bn  # noqa: E402

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


ENV = bn._FP16_ENV
src = open(os.path.join(PKG, "birefnet_node.py"), encoding="utf-8").read()

# ---------------------------------------------------------------- A. 精度开关
print("=== A. 精度默认 fp32 ===")
_saved = os.environ.pop(ENV, None)
check("A1 未设环境变量时 _want_half() 为 False", bn._want_half() is False)

for value, expect, label in (("1", True, "1"), ("true", True, "true"),
                             ("YES", True, "YES"), ("on", True, "on"),
                             ("0", False, "0"), ("", False, "空串"),
                             ("no", False, "no")):
    os.environ[ENV] = value
    check("A2 %s %r → %s" % (label, value, expect),
          bn._want_half() is expect)

if _saved is not None:
    os.environ[ENV] = _saved
else:
    os.environ.pop(ENV, None)

check("A3 _Runner 默认 half=False",
      bn._Runner().half is False)
check("A4 降级记录表初始为空", bn._Runner().fp16_broken == set())

# ------------------------------------------------------- B. half 必须在条件内
print("=== B. fp16 只在显式开启时启用 ===")
check("B1 model.half() 受 device+half 双条件保护",
      'if device.type == "cuda" and half:' in src)
check("B2 已无「CUDA 就 half」的旧写法",
      'if device.type == "cuda":\n            # CUDA 上 fp16' not in src)
check("B3 推理张量按 self.half 决定 dtype",
      'if device.type == "cuda" and self.half:' in src)
check("B4 _load 传入 half 参数", "def _load_birefnet(self, files, half)" in src)
check("B5 精度写进加载日志",
      "'fp16' if half else 'fp32'" in src)

# ------------------------------------------------------------ C. NaN 必须清掉
print("=== C. NaN 在 cast 之前被清掉 ===")
check("C1 统计 NaN 占比", "np.isnan(prob).mean()" in src)
check("C2 用 nan_to_num 兜底", "np.nan_to_num(prob" in src)
check("C3 先清 NaN 再 clip", src.index("np.nan_to_num(prob")
      < src.index("prob = np.clip(prob, 0.0, 1.0)"))
check("C4 返回 (遮罩, NaN 占比)",
      "return prob_img.resize((w, h), Image.BICUBIC), nan_ratio" in src)

# --------------------------------------------------- D. 自动降级与空遮罩提示
print("=== D. 自动降级 / 空遮罩提示 ===")
check("D1 predict 检测 NaN", "if nan_ratio > 0.01 and self.half:" in src)
check("D2 降级前记录该模型", "self.fp16_broken.add(model_name)" in src)
check("D3 降级后重载重跑", src.count("self._predict_birefnet(image_pil, process_res)") >= 2)
check("D4 fp32 下仍有 NaN 要出声",
      "fp32 下仍有" in src)
check("D5 遮罩几乎全空有提示", "遮罩几乎全空" in src)
check("D6 提示里给出可操作建议",
      "换 general / portrait 模型" in src)


# ---------------------------------------------- E. 行为：NaN 不再静默变全黑
print("=== E. 行为验证（假模型打桩） ===")


class _FakeModel:
    """只负责产出可控的 logits，绕过权重与设备。"""

    def __init__(self, mode):
        self.mode = mode

    def __call__(self, tensor):
        n = 32
        if self.mode == "nan":
            out = torch.full((1, 1, n, n), float("nan"))
        elif self.mode == "left":
            out = torch.full((1, 1, n, n), -10.0)
            out[..., : n // 2] = 10.0          # 左半判前景
        else:                                   # empty：全判背景
            out = torch.full((1, 1, n, n), -10.0)
        return [out]


_orig_device = getattr(bn.mm, "get_torch_device", None)
if _orig_device is None:                    # 工作区镜像里 comfy 只是空 stub
    bn.mm.get_torch_device = lambda: torch.device("cpu")
    _orig_device = bn.mm.get_torch_device
bn.mm.get_torch_device = lambda: torch.device("cpu")

runner = bn._Runner()
runner.half = False
from PIL import Image  # noqa: E402

img = Image.new("RGB", (24, 16), (128, 128, 128))

runner.model = _FakeModel("nan")
mask, nan_ratio = runner._predict_birefnet(img, 32)
check("E1 全 NaN 输出被识别", abs(nan_ratio - 1.0) < 1e-6, "nan_ratio=%s" % nan_ratio)
check("E2 NaN 清理后不抛异常且尺寸正确", mask.size == (24, 16), str(mask.size))
check("E3 NaN 像素按背景（0）处理，遮罩可读",
      int(np.asarray(mask).max()) == 0)

runner.model = _FakeModel("left")
mask, nan_ratio = runner._predict_birefnet(img, 32)
fg = float((np.asarray(mask) > 127).mean())
check("E4 正常输出无 NaN", nan_ratio == 0.0)
check("E5 左半前景 → 占比约 0.5", 0.4 < fg < 0.6, "fg=%.3f" % fg)
check("E6 遮罩尺寸回到原图", mask.size == (24, 16))

runner.model = _FakeModel("empty")
mask, nan_ratio = runner._predict_birefnet(img, 32)
check("E7 全背景时 nan_ratio=0", nan_ratio == 0.0)
check("E8 全背景遮罩全 0（供 E 节日志判定）",
      float((np.asarray(mask) > 127).mean()) == 0.0)

# 灵敏度对全 0 遮罩不能炸
zeroed = bn._adjust_sensitivity(mask, 0.5)
check("E9 灵敏度处理全 0 遮罩不炸", int(np.asarray(zeroed).max()) == 0)

# fp16 降级路径：假模型 + half=True 时应当自动改 fp32 并重跑
calls = []


def _fake_predict(image_pil, process_res):
    calls.append(1)
    if len(calls) == 1:
        return Image.new("L", image_pil.size, 0), 1.0
    return Image.new("L", image_pil.size, 255), 0.0


runner2 = bn._Runner()
runner2.half = True
runner2.loaded_name = "BiRefNet_lite"
runner2.model = _FakeModel("left")
_orig_load = runner2._load
runner2._load = lambda name: None            # 跳过真实权重解析
_orig_unload = runner2.unload
runner2.unload = lambda: None
runner2._predict_birefnet = _fake_predict
mask2 = runner2.predict(img, "BiRefNet_lite", 32)
check("E10 fp16 出 NaN 会自动重跑一次", len(calls) == 2, "calls=%d" % len(calls))
check("E11 重跑后返回正常遮罩", int(np.asarray(mask2).max()) == 255)
check("E12 该模型被标记为 fp16 不可用",
      "BiRefNet_lite" in runner2.fp16_broken)

runner2._load = _orig_load
runner2.unload = _orig_unload
bn.mm.get_torch_device = _orig_device

print()
print("=== 合计：PASS %d / FAIL %d ===" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
