# -*- coding: utf-8 -*-
"""边界与空批次回归（第四轮排查）。

覆盖范围：
A. 空 batch：QG_Watermark / QG_PortraitMatte 返回空张量而不是裸异常
B. 拼版通道：RGBA 按 alpha 合成白底，不再印成黑块；0 帧给中文错误
C. 取色写法：`0.5` 按 0~1 归一化，不再是纯黑
D. 取景参数：face_ratio/out_w 为 0 时给中文提示，不是 ZeroDivisionError
E. 超限尺寸：等比缩放保住宽高比，不再各自独立钳
F. 译文截断：finish_reason=length 时回报 truncated 且不进缓存
G. 前端静态回归：返回值传递、配置缓存、尺寸守卫、模板丢失时保留提示词

运行：python_embeded\\python.exe tests\\test_edge_cases.py
"""
import importlib
import os
import sys
import types

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

# ComfyUI 根：优先环境变量，其次按 custom_nodes/<插件> 相对推导；推不出来用 stub。
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

# 插件目录名带连字符，不是合法包名：造一个包壳让相对导入生效。
shell = types.ModuleType("qg_pack_edge")
shell.__path__ = [PKG]
sys.modules["qg_pack_edge"] = shell


def load(name):
    return importlib.import_module("qg_pack_edge." + name)


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
    with open(os.path.join(PKG, "web", name), "r", encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------------------
print("=== A. 空 batch 不崩 ===")

wm = load("watermark_node")
empty3 = torch.zeros((0, 64, 64, 3), dtype=torch.float32)
try:
    out = wm.QGWatermark().execute(empty3, "x", "<default>", 20, "#FFFFFF", 50, 40, 0)
    check("Watermark 空 batch 返回 [0,H,W,3]",
          tuple(out[0].shape) == (0, 64, 64, 3), str(out[0].shape))
except Exception as exc:  # noqa: BLE001
    check("Watermark 空 batch 返回 [0,H,W,3]", False, repr(exc))

check("Watermark 不再在循环外取 outs[0] 的死变量",
      "first = outs[0]" not in open(os.path.join(PKG, "watermark_node.py"),
                                    encoding="utf-8").read())

pm = load("portrait_matte_node")
try:
    # crop_only=True 跳过模型解析，专测空 batch 路径
    got = pm.QGPortraitMatte().execute(
        empty3, "rmbg-1.4", True, False, True, 0.62, 0.10, 0, 0, 0, 0, 0)
    check("PortraitMatte 空 batch 三个输出都是 0 帧",
          all(int(got[i].shape[0]) == 0 for i in range(3)),
          "%s %s %s" % (got[0].shape, got[1].shape, got[2].shape))
    check("PortraitMatte 空 batch 遮罩是 3 维 [0,H,W]",
          got[1].dim() == 3, str(got[1].shape))
except Exception as exc:  # noqa: BLE001
    check("PortraitMatte 空 batch 三个输出都是 0 帧", False, repr(exc))

# --------------------------------------------------------------------------
print("\n=== B. 拼版通道与空批次 ===")

ps = load("photo_sheet_node")
rgba = torch.zeros((1, 8, 8, 4), dtype=torch.float32)
rgba[0, :, :, 0] = 1.0        # 红通道，alpha 全 0（全透明）
pil = ps._to_pil(rgba[0])
check("photo_sheet RGBA 全透明 -> 白底",
      pil.mode == "RGB" and pil.getpixel((4, 4)) == (255, 255, 255),
      "%s %s" % (pil.mode, pil.getpixel((4, 4))))
opaque = torch.zeros((1, 8, 8, 4), dtype=torch.float32)
opaque[0, :, :, 1] = 1.0      # 绿，alpha=0 -> 仍应白
opaque[0, :, :, 3] = 0.0
pil_b = ps._to_pil(opaque[0])
check("photo_sheet 透明像素的 RGB 不被采用",
      pil_b.getpixel((4, 4)) == (255, 255, 255), str(pil_b.getpixel((4, 4))))
semi = torch.zeros((1, 8, 8, 4), dtype=torch.float32)
semi[0, :, :, 0] = 1.0
semi[0, :, :, 3] = 1.0        # 不透明红
check("photo_sheet 不透明像素保持原色",
      ps._to_pil(semi[0]).getpixel((4, 4)) == (255, 0, 0),
      str(ps._to_pil(semi[0]).getpixel((4, 4))))
gray = torch.zeros((1, 8, 8, 1), dtype=torch.float32)
check("photo_sheet 单通道转 RGB（否则 expand 会 TypeError）",
      ps._to_pil(gray[0]).mode == "RGB")

pmx = load("photo_sheet_mixed_node")
check("photo_sheet_mixed RGBA 全透明 -> 白底",
      pmx._to_pil(rgba[0]).getpixel((4, 4)) == (255, 255, 255),
      str(pmx._to_pil(rgba[0]).getpixel((4, 4))))
try:
    pmx.QGPhotoSheetMixed().execute(
        empty3, list(pmx.LAYOUT_BY_KEY.keys())[0], 300, 0, "#000000", "", "<default>", 0)
    check("photo_sheet_mixed 0 帧给中文错误", False, "没抛异常")
except ValueError as exc:
    check("photo_sheet_mixed 0 帧给中文错误", "没有收到任何图像帧" in str(exc), str(exc))
except Exception as exc:  # noqa: BLE001
    check("photo_sheet_mixed 0 帧给中文错误", False, repr(exc))

# --------------------------------------------------------------------------
print("\n=== C. 取色支持 0~1 写法 ===")

crop = load("id_photo_crop_node")
check('parse_color("0.5") -> (128,128,128)',
      crop.parse_color("0.5", "t") == (128, 128, 128),
      str(crop.parse_color("0.5", "t")))
check('parse_color("1") 仍是灰度 1（不误判为归一化）',
      crop.parse_color("1", "t") == (1, 1, 1), str(crop.parse_color("1", "t")))
check('parse_color("128,128,128") 不受影响',
      crop.parse_color("128,128,128", "t") == (128, 128, 128))
check('parse_color("#808080") 不受影响',
      crop.parse_color("#808080", "t") == (128, 128, 128))

# --------------------------------------------------------------------------
print("\n=== D. 取景参数除零防御 ===")

h = load("_id_photo_helpers")


class _Face:
    width = 200.0
    height = 240.0
    tilt = 0.0
    eye_center = (100.0, 90.0)
    contour = None


try:
    h.plan_frame(_Face(), 295, 413, 0.0, 0.40, True)
    check("face_ratio=0 抛中文 ValueError", False, "没抛")
except ValueError as exc:
    check("face_ratio=0 抛中文 ValueError", "取景比例" in str(exc), str(exc))

try:
    h.plan_frame(_Face(), 0, 413, 0.5, 0.40, True)
    check("out_w=0 抛中文 ValueError", False, "没抛")
except ValueError as exc:
    check("out_w=0 抛中文 ValueError", "输出尺寸" in str(exc), str(exc))

try:
    h.plan_frame(_Face(), 295, 413, 0.5, 0.40, True)
    check("正常参数仍然得出取景框", True)
except Exception as exc:  # noqa: BLE001
    check("正常参数仍然得出取景框", False, repr(exc))

# --------------------------------------------------------------------------
print("\n=== E. 超限尺寸等比缩放 ===")

w, hh, dpi = h.output_pixels("custom", "cm", 100, 50, 300)
ratio = w / float(hh)
check("100x50cm@300dpi 等比缩到长边 8192", max(w, hh) == h.MAX_SIDE,
      "%dx%d" % (w, hh))
check("缩放后宽高比保持 2.0", abs(ratio - 2.0) < 0.01, "%.3f" % ratio)
w2, h2, _ = h.output_pixels("custom", "cm", 5, 7, 300)
check("未超限的尺寸原样返回", (w2, h2) == (591, 827), "%dx%d" % (w2, h2))

# --------------------------------------------------------------------------
print("\n=== F. 译文截断回报 truncated ===")

tc = load("translate_core")


class _Resp:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Opener:
    def __init__(self, body):
        self._body = body

    def open(self, request, timeout=None):
        return _Resp(self._body)


def _fake(body):
    tc.urllib.request.build_opener = lambda *a, **k: _Opener(body)


_fake(b'{"choices":[{"message":{"content":"half"},"finish_reason":"length"}]}')
meta = {}
text = tc.call_api("https://example.invalid/v1/chat/completions", "k", "m",
                   [{"role": "user", "content": "hi"}], meta=meta)
check("finish_reason=length -> meta.truncated 为 True",
      meta.get("truncated") is True, str(meta))
check("截断时仍返回已有文本", text == "half", repr(text))

_fake(b'{"choices":[{"message":{"content":"full"},"finish_reason":"stop"}]}')
meta2 = {}
tc.call_api("https://example.invalid/v1/chat/completions", "k", "m",
            [{"role": "user", "content": "hi"}], meta=meta2)
check("finish_reason=stop -> meta.truncated 为 False",
      meta2.get("truncated") is False, str(meta2))

src_tc = open(os.path.join(PKG, "translate_core.py"), encoding="utf-8").read()
check("截断结果不进缓存",
      'if meta.get("truncated"):' in src_tc
      and src_tc.find('if meta.get("truncated"):') < src_tc.find("_CACHE[cache_key] = answer"))

# --------------------------------------------------------------------------
print("\n=== G. 前端静态回归 ===")

tr = js("qg_translate.js")
check("qg_translate 配置读取失败不记住「已加载」",
      "if (!ok) return CONFIG;" in tr
      and tr.find("if (!ok) return CONFIG;") < tr.find("loaded = true;"))

qwen = js("qg_qwen_text_encode.js")
check("qg_qwen_text_encode 三个钩子都传回原返回值",
      qwen.count("const result = originalCreated?.apply") == 1
      and qwen.count("const result = originalConnections?.apply") == 1
      and qwen.count("const result = originalConfigure?.apply") == 1
      # 3 个生命周期钩子 + hookSerialize 里的实例包装，共 4 处
      and qwen.count("return result;") == 4,
      "return result; = %d" % qwen.count("return result;"))

mc = js("qg_marriage_cloth.js")
check("qg_marriage_cloth 标记尺寸来自工作流",
      "_qgSizeFromWorkflow = true" in mc)
check("qg_marriage_cloth 窄节点只补宽度、不动高度",
      "keepH" in mc and "node._qgSizeFromWorkflow ? (node.size[1] || NODE_H)" in mc)

outfit = js("qg_id_photo_outfit.js")
check("qg_id_photo_outfit 模板丢失时保留已有提示词",
      "const existing = String(promptWidget?.value || \"\").trim();" in outfit
      and "selectedPrompt = existing;" in outfit)

ebb = js("qg_image_batch_builder.js")
check("qg_image_batch_builder 上限裁剪前判连接",
      "if (connected(last.slot)) break;" in
      ebb[ebb.find("while (inputs.length > MAX_IMAGES)"):
          ebb.find("while (inputs.length > MAX_IMAGES)") + 400])

# --------------------------------------------------------------------------
print("=== H. 第五轮真机 fuzz 补出的空批次 ===")
_empty_img = torch.zeros(0, 48, 48, 3)
_empty_mask = torch.zeros(0, 48, 48)

def _rejects_0frame(fn, label):
    try:
        fn()
    except ValueError as error:
        check(label + " 空批次报中文错误",
              "0 帧" in str(error), str(error)[:80])
    except Exception as error:
        check(label + " 空批次报中文错误", False,
              type(error).__name__ + ": " + str(error)[:80])
    else:
        check(label + " 空批次报中文错误", False, "未抛异常")

_rejects_0frame(
    lambda: load("qg_dominant_color").QGDominantColor().extract(
        _empty_img, 8, 15),
    "QG_DominantColor")

_rejects_0frame(
    lambda: load("qg_multi_photo_sheet").QGMultiPhotoSheet().execute(
        _empty_img, 10, 15, 300, 3, 0.3, 0.2, True),
    "QG_MultiPhotoSheet")

_rejects_0frame(
    lambda: load("id_card_sheet_node").QGIDCardSheet().execute(
        _empty_img, _empty_mask, 10, 15, 300, 0.2, 8.5, 5.4, 3,
        False, 0, 0, 0, False, False, False, "#FFFFFF"),
    "QG_IDCardSheet")

# --------------------------------------------------------------------------
print("\n===== 合计 PASS %d / FAIL %d =====" % (ok, fail))
sys.exit(1 if fail else 0)
