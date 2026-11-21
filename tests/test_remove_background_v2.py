# -*- coding: utf-8 -*-
"""QG_RemoveBackgroundV2 独立契约 + 数值回归测试。

不下载 ViTMatte 权重：ViTMatte 分支用 stub 替换推理函数，其余五种方法里的
GuidedFilter / PyMatting / trimap 生成都跑真实现（本机有 opencv / pymatting / pyamg）。

运行：
    cd D:/ComfyUI_windows_portable/ComfyUI
    ../python_embeded/python.exe custom_nodes/ComfyUI-QG-Multipack/tests/test_remove_background_v2.py
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
COMFY_ROOT = PKG.parent.parent
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(COMFY_ROOT))

_np = 0
_fail = 0


def check(name, cond, info=""):
    global _np, _fail
    _np += 1
    if not cond:
        _fail += 1
        print("FAIL %s %s" % (name, info))


spec = importlib.util.spec_from_file_location(
    "qg_remove_background_v2", str(PKG / "qg_remove_background_v2.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["qg_remove_background_v2"] = mod
spec.loader.exec_module(mod)

# ---- 1. 后端契约 ----
cls = mod.QGRemoveBackgroundV2
it = cls.INPUT_TYPES()
req, opt = it["required"], it["optional"]
check("9 个必填控件", len(req) == 9, str(len(req)))
check("1 个可选控件（粗分割模型）", len(opt) == 1, str(list(opt)))
expected = ["image", "detail_method", "detail_erode", "detail_dilate",
            "black_point", "white_point", "process_detail", "device",
            "max_megapixels"]
check("必填控件顺序与截图一致", list(req) == expected, str(list(req)))
check("五种细节方法齐全", list(req["detail_method"][0]) == [
    "VITMatte", "VITMatte(local)", "vitmatte-base-composition-1k",
    "PyMatting", "GuidedFilter"])
check("设备三项", list(req["device"][0]) == ["auto", "cuda", "cpu"])
check("detail_erode 默认 6", req["detail_erode"][1]["default"] == 6)
check("detail_dilate 默认 6", req["detail_dilate"][1]["default"] == 6)
check("black_point 默认 0.01", req["black_point"][1]["default"] == 0.01)
check("white_point 默认 0.99", req["white_point"][1]["default"] == 0.99)
check("process_detail 默认 True", req["process_detail"][1]["default"] is True)
check("max_megapixels 默认 2.0", req["max_megapixels"][1]["default"] == 2.0)
check("输出两路 IMAGE/MASK", cls.RETURN_TYPES == ("IMAGE", "MASK"))
check("分类 QG 工具", cls.CATEGORY == "QG 工具")
check("输出说明是中文", all(any("\u4e00" <= c <= "\u9fff" for c in t)
                         for t in cls.OUTPUT_TOOLTIPS))
def _tooltip(cfg):
    return (cfg[1] if isinstance(cfg, tuple) else cfg).get("tooltip", "")


check("全部输入说明是中文", all(
    any("\u4e00" <= c <= "\u9fff" for c in _tooltip(cfg))
    for cfg in list(req.values()) + list(opt.values())))

# ---- 2. 数值函数 ----
arr = np.array([0.0, 0.1, 0.5, 0.9, 1.0], dtype=np.float32)
r = mod.remap_histogram(arr, 0.0, 1.0)
check("remap 恒等区间", np.allclose(r, arr, atol=1e-6), str(r))
r2 = mod.remap_histogram(np.array([0.0, 0.5, 1.0]), 0.25, 0.75)
check("remap 拉伸区间", np.allclose(r2, [0, 0.5, 1], atol=1e-6), str(r2))
r3 = mod.remap_histogram(np.array([0.0, 1.0]), 0.9, 0.1)
check("remap 黑白点倒置不除零", np.all(np.isfinite(r3)))

mask = Image.fromarray(np.zeros((41, 41), np.uint8), "L")
mask.paste(255, (10, 10, 31, 31))
tri = np.asarray(mod.build_trimap(mask, 2, 2))
check("trimap 三值", set(np.unique(tri)) <= {0, 128, 255}, str(np.unique(tri)))
check("trimap 中心是确定前景", tri[20, 20] == 255)
check("trimap 远处是背景", tri[2, 2] == 0)
check("trimap 边缘有待处理区", 128 in tri)

rgb = Image.fromarray(np.full((32, 32, 3), 128, np.uint8), "RGB")
_soft_arr = np.full((32, 32), 180, np.uint8)
_soft_arr[:, :10] = 255
_soft_arr[:, -10:] = 0
soft = Image.fromarray(_soft_arr, "L")
ga = mod.guided_alpha(rgb, soft, 12)
check("引导滤波形状", ga.shape == (32, 32), str(ga.shape))
check("引导滤波值域", float(ga.min()) >= 0 and float(ga.max()) <= 1)

pm_rgb = Image.fromarray(np.full((128, 128, 3), 128, np.uint8), "RGB")
pm_arr = np.zeros((128, 128), np.uint8)
pm_arr[:, :48] = 255
pm_arr[:, 48:80] = np.tile(
    np.linspace(255, 0, 32, dtype=np.uint8)[None, :], (128, 1))
pm_mask = Image.fromarray(pm_arr, "L")
pa = mod.pymatting_alpha(pm_rgb, pm_mask, 1, 0.01, 0.99)
check("PyMatting 形状", pa.shape == (128, 128), str(pa.shape))
check("PyMatting 值域", bool(np.all(np.isfinite(pa))) and float(pa.min()) >= 0)

# 模型库发现：造一个临时 background_removal 根，验证命中本地目录时只读、
# 不再联网；缺失时才回退仓库名。环境变量优先级最高。
import tempfile
with tempfile.TemporaryDirectory() as tmp:
    fake_root = Path(tmp) / "background_removal"
    small_dir = fake_root / "vitmatte-small-composition-1k"
    small_dir.mkdir(parents=True)
    (small_dir / "model.safetensors").write_bytes(b"stub")
    (small_dir / "config.json").write_text("{}", encoding="utf-8")
    (small_dir / "preprocessor_config.json").write_text("{}", encoding="utf-8")

    # 把临时根插到发现列表最前面，模拟用户模型库命中
    orig_roots = mod._vitmatte_model_roots
    mod._vitmatte_model_roots = lambda: [str(fake_root)] + orig_roots()
    try:
        src, only = mod._vitmatte_source("VITMatte")
        check("模型库命中返回本地路径", src == str(small_dir), src)
        check("模型库命中只读本地", only is True)
        check("目录完整性判定", mod._is_vitmatte_dir(str(small_dir)))
        check("缺配置不算命中", not mod._is_vitmatte_dir(str(fake_root)))

        base_src, _ = mod._vitmatte_source("vitmatte-base-composition-1k")
        check("base 未命中回退仓库名",
              base_src.endswith("vitmatte-base-composition-1k"), base_src)

        # local 严格语义：即便没命中也只读本地
        check("local 模式只读本地",
              mod._vitmatte_source("VITMatte(local)")[1] is True)
    finally:
        mod._vitmatte_model_roots = orig_roots

check("小模型目录名映射", mod._VIT_MODEL_DIRS["VITMatte"] ==
      "vitmatte-small-composition-1k")

# ---- 3. run 流程（stub 粗分割与 ViTMatte）----
orig_predict = mod._BR._runner.predict
orig_vit = mod.vitmatte_alpha
try:
    calls = []

    def fake_predict(image_pil, model_name, process_res):
        calls.append(("coarse", model_name, process_res, image_pil.size))
        return Image.fromarray(
            np.full((image_pil.height, image_pil.width), 200, np.uint8), "L")

    def fake_vit(image_pil, trimap_pil, method, device, max_megapixels):
        calls.append(("vit", method, device, max_megapixels))
        return np.full((image_pil.height, image_pil.width), 0.8, np.float32)

    mod._BR._runner.predict = fake_predict
    mod.vitmatte_alpha = fake_vit
    frames = np.zeros((2, 16, 16, 3), np.float32)
    frames[..., 0] = 1.0
    out_img, out_mask = cls().run(
        frames, "VITMatte", 2, 2, 0.01, 0.99, True, "cpu", 2.0)
    check("IMAGE batch 帧数", tuple(out_img.shape) == (2, 16, 16, 4),
          str(tuple(out_img.shape)))
    check("MASK batch 帧数", tuple(out_mask.shape) == (2, 16, 16),
          str(tuple(out_mask.shape)))
    check("RGBA alpha 通道接近精修值", abs(float(out_img[0, 0, 0, 3]) -
          float(mod.remap_histogram(np.array([0.8]), 0.01, 0.99)[0])) < 0.02)
    check("粗分割逐帧调用", len([c for c in calls if c[0] == "coarse"]) == 2,
          str(calls))
    check("模型名走环境变量", calls[0][1] == mod._coarse_model_name("BiRefNet-general"))

    calls.clear()
    _, _ = cls().run(frames[:1], "GuidedFilter", 2, 2, 0.01, 0.99,
                     True, "cpu", 2.0)
    check("GuidedFilter 分支不调 ViTMatte",
          not any(c[0] == "vit" for c in calls), str(calls))

    calls.clear()
    out_img2, out_mask2 = cls().run(
        frames[:1], "VITMatte", 2, 2, 0.01, 0.99, False, "cpu", 2.0)
    check("关闭细节仍出 RGBA", tuple(out_img2.shape) == (1, 16, 16, 4))
    check("关闭细节不调 ViTMatte", not any(c[0] == "vit" for c in calls))
    check("关闭细节遮罩取粗分割", float(out_mask2[0, 0, 0]) > 0.7)

    try:
        cls().run(np.zeros((0, 16, 16, 3), np.float32), "VITMatte",
                  2, 2, 0.01, 0.99, True, "cpu", 2.0)
        check("空输入报错", False)
    except RuntimeError:
        check("空输入报错", True)
finally:
    mod._BR._runner.predict = orig_predict
    mod.vitmatte_alpha = orig_vit

# ---- 4. 词表与文档 ----
nd = json.loads((PKG / "locales" / "zh" / "nodeDefs.json").read_text(encoding="utf-8"))
tr = json.loads((PKG / "translations" / "zh-CN" / "Nodes" /
                 "ComfyUI-QG-Multipack.json").read_text(encoding="utf-8"))
key = "QG_RemoveBackgroundV2"
check("nodeDefs 34 节点", len(nd) == 34, str(len(nd)))
check("translations 34 节点", len(tr) == 34, str(len(tr)))
check("两份词表描述逐字一致", nd[key]["description"] == tr[key]["description"])
check("词表覆盖全部控件", set(nd[key]["inputs"]) == set(list(req) + list(opt)))
check("细节方法选项有中文说明", len(nd[key]["inputs"]["detail_method"]["options"]) == 5)
check("输出名两路", set(tr[key]["outputs"]) == {"IMAGE", "MASK"})
rd = (PKG / "README.md").read_text(encoding="utf-8")
check("README 覆盖节点数 34", "覆盖全部 34 个节点" in rd)
check("README 概括句 34/33", "34 个节点里 33 个" in rd)
check("README 登记新节点", key in rd)

print("== 汇总：%d 项，失败 %d ==" % (_np, _fail))
sys.exit(1 if _fail else 0)
