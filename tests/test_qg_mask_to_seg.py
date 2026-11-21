# -*- coding: utf-8 -*-
"""QG_MaskToSeg 节点级测试：自造类型 / 静态契约 / 连通域 / 五控件 / 批次 / 回退 / 词表。

不依赖真实模型、网络、ComfyUI 运行时，也不依赖 Impact-Pack。
运行：python_embeded\\python.exe tests\\test_qg_mask_to_seg.py
"""
import builtins
import json
import os
import sys
import types

import numpy as np
import torch

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PKG)

# 该模块相对导入 qg_simple_seg_detector，须当包加载（造一个父包指向插件目录）。
_pkg = types.ModuleType("qgmultipack_for_mask_to_seg_test")
_pkg.__path__ = [PKG]
sys.modules[_pkg.__name__] = _pkg
import importlib

M = importlib.import_module(_pkg.__name__ + ".qg_mask_to_seg")
SD = importlib.import_module(_pkg.__name__ + ".qg_simple_seg_detector")

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


def rect(plane, y0, y1, x0, x1, value=1.0):
    plane[y0:y1, x0:x1] = value
    return plane


print("== 一、自造类型与独立边界 ==")
check("SEGS 类型带本包前缀", M.SEGS_TYPE == "QG_SEGS", M.SEGS_TYPE)
check("不与 Impact 类型撞名", M.SEGS_TYPE != "SEGS")
check("复用本包 QGSegs 容器", M.QGSegs is SD.QGSegs)
check("复用本包 QGSeg 段", M.QGSeg is SD.QGSeg)
src = open(os.path.join(PKG, "qg_mask_to_seg.py"), encoding="utf-8").read()
check("源码零 impact 引用",
      "import impact" not in src and "from impact" not in src and "impact.core" not in src)
check("源码零 subprocess/eval",
      "subprocess" not in src and "eval(" not in src and "exec(" not in src)

print("== 二、节点注册契约 ==")
node = M.QGMaskToSeg
check("注册 key", "QG_MaskToSeg" in M.NODE_CLASS_MAPPINGS)
check("显示名中文", "遮罩" in M.NODE_DISPLAY_NAME_MAPPINGS["QG_MaskToSeg"])
check("单输出 QG_SEGS", node.RETURN_TYPES == (M.SEGS_TYPE,), str(node.RETURN_TYPES))
check("RETURN_NAMES", node.RETURN_NAMES == ("segs",), str(node.RETURN_NAMES))
check("CATEGORY 中文", node.CATEGORY == "QG 工具")
check("FUNCTION=convert", node.FUNCTION == "convert")
check("输出提示中文", any("\u4e00" <= c <= "\u9fff" for c in node.OUTPUT_TOOLTIPS[0]))
it = node.INPUT_TYPES()
req = it["required"]
check("六个必填控件", len(req) == 6, list(req))
check("输入口顺序 mask 在前", list(req)[0] == "mask", list(req))
check("mask 类型是 MASK", req["mask"][0] == "MASK")
check("combine 默认 False", req["combine"][1]["default"] is False)
check("crop_factor 默认 3.0", req["crop_factor"][1]["default"] == 3.0)
check("bbox_fill 默认 False", req["bbox_fill"][1]["default"] is False)
check("drop_size 默认 10", req["drop_size"][1]["default"] == 10)
check("is_contour 默认 True", req["is_contour"][1]["default"] is True)
for b in ("combine", "bbox_fill", "is_contour"):
    w = req[b][1]
    check("%s 布尔中文标签" % b,
          all("\u4e00" <= c <= "\u9fff" for c in w["label_on"] + w["label_off"]), str(w))

print("== 三、连通域分段 ==")
plane = rect(rect(np.zeros((50, 60), np.float32), 5, 17, 5, 17), 25, 40, 30, 45)
c = M.mask_to_segs(plane, drop_size=10)
check("两块各出一段", len(c) == 2, len(c))
check("容器尺寸正确", (c.width, c.height) == (60, 50))
check("每段框正确", set(c_seg.bbox for c_seg in c) ==
      {(5.0, 5.0, 17.0, 17.0), (30.0, 25.0, 45.0, 40.0)},
      [s.bbox for s in c])
check("每段是实心轮廓", all(set(np.unique(s.mask)) <= {0.0, 1.0} for s in c))
check("mask_batch 形状 [N,H,W]", c.mask_batch().shape == (2, 50, 60))
check("combined_mask 形状 [H,W]", c.combined_mask().shape == (50, 60))

print("== 四、合并 / 最小尺寸 ==")
c_all = M.mask_to_segs(plane, combine=True, drop_size=10)
check("合并为一段", len(c_all) == 1, len(c_all))
check("合并框包住两块", c_all[0].bbox == (5.0, 5.0, 45.0, 40.0), c_all[0].bbox)
small = rect(np.zeros((30, 30), np.float32), 5, 12, 5, 12)  # 7x7
check("drop_size=10 丢掉小块", len(M.mask_to_segs(small, drop_size=10)) == 0)
check("drop_size=5 保留小块", len(M.mask_to_segs(small, drop_size=5)) == 1)
check("drop_size 下限夹到 1",
      len(M.mask_to_segs(small, drop_size=0)) == 1)

print("== 五、填充轮廓 / 填充 BBox ==")
gray = rect(np.zeros((40, 40), np.float32), 5, 20, 5, 20, 0.5)
c_true = M.mask_to_segs(gray, is_contour=True, drop_size=10)[0]
c_false = M.mask_to_segs(gray, is_contour=False, drop_size=10)[0]
check("填充轮廓：0/1 二值", set(np.unique(c_true.mask)) <= {0.0, 1.0})
check("保留原遮罩：仍是 0.5 灰度", 0.5 in set(np.unique(c_false.mask)))
c_fill = M.mask_to_segs(gray, is_contour=False, bbox_fill=True, drop_size=10)[0]
check("填充 BBox：框内全 1", float(c_fill.mask[5:20, 5:20].mean()) == 1.0)
check("填充 BBox：框外仍 0", float(c_fill.mask[0:5, 0:5].max()) == 0.0)
c_fill2 = M.mask_to_segs(plane, combine=True, bbox_fill=True, drop_size=10)[0]
check("合并模式下 bbox_fill 也能跑", float(c_fill2.mask[5:40, 5:45].min()) == 1.0)

print("== 六、批次 / 空遮罩 / 维度 ==")
batch = np.zeros((2, 50, 60), np.float32)
batch[0] = rect(np.zeros((50, 60), np.float32), 5, 17, 5, 17)
batch[1] = rect(np.zeros((50, 60), np.float32), 25, 40, 30, 45)
c_batch = M.mask_to_segs(batch, drop_size=10)
check("批次取 max 合成后分段数=2", len(c_batch) == 2, len(c_batch))
check("批次与逐像素max的合并等价",
      set(s.bbox for s in c_batch) ==
      set(s.bbox for s in M.mask_to_segs(batch.max(axis=0), drop_size=10)))
empty = M.mask_to_segs(np.zeros((10, 12), np.float32))
check("空遮罩 0 段", len(empty) == 0)
check("空容器 mask_batch=[0,H,W]", empty.mask_batch().shape == (0, 10, 12))
check("空容器 combined_mask 全 0", float(empty.combined_mask().max()) == 0.0)
try:
    M.mask_to_segs(np.zeros((2, 2, 3, 4), np.float32))
    check("4 维输入报错", False)
except ValueError:
    check("4 维输入报错", True)

print("== 七、Tensor / ndarray 输入 ==")
c_t = M.mask_to_segs(torch.from_numpy(plane), drop_size=10)
check("Tensor 输入正常分段", len(c_t) == 2, len(c_t))
c_nan = plane.copy()
c_nan[0, 0] = np.nan
check("NaN 被清零不污染", len(M.mask_to_segs(c_nan, drop_size=10)) == 2)

print("== 八、缺 cv2 的 numpy 回退 ==")
real_import = builtins.__import__


def _no_cv2(name, *a, **k):
    if name == "cv2":
        raise ImportError("blocked for test")
    return real_import(name, *a, **k)


builtins.__import__ = _no_cv2
try:
    c_np = M.mask_to_segs(plane, drop_size=10)
    check("回退分段数=2", len(c_np) == 2, len(c_np))
    check("回退框正确", set(s.bbox for s in c_np) ==
          {(5.0, 5.0, 17.0, 17.0), (30.0, 25.0, 45.0, 40.0)},
          [s.bbox for s in c_np])
    check("回退遮罩实心", all(set(np.unique(s.mask)) <= {0.0, 1.0} for s in c_np))
finally:
    builtins.__import__ = real_import

print("== 九、节点调用 ==")
res = node().convert(torch.from_numpy(plane), False, 3.0, False, 10, True)
check("返回单元素元组", isinstance(res, tuple) and len(res) == 1)
check("输出是 QGSegs", isinstance(res[0], SD.QGSegs))
check("节点输出两段", len(res[0]) == 2)

print("== 十、词表与文档登记 ==")
nd = json.load(open(os.path.join(PKG, "locales/zh/nodeDefs.json"), encoding="utf-8"))
tr = json.load(open(os.path.join(PKG, "translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"),
                    encoding="utf-8"))
check("nodeDefs 38 节点", len(nd) == 38, str(len(nd)))
check("translations 38 节点", len(tr) == 38, str(len(tr)))
check("两套都登记 QG_MaskToSeg", "QG_MaskToSeg" in nd and "QG_MaskToSeg" in tr)
e = nd["QG_MaskToSeg"]
check("nodeDefs 有 display_name", e.get("display_name") == "QG 遮罩到 Seg")
check("nodeDefs 六个输入", set(e["inputs"]) ==
      {"mask", "combine", "crop_factor", "bbox_fill", "drop_size", "is_contour"})
check("nodeDefs 一个输出", set(e["outputs"]) == {"0"})
check("translations 有 title", bool(tr["QG_MaskToSeg"].get("title")))
check("translations 无恒等翻译",
      not any(k == v for f in ("inputs", "widgets", "outputs")
              for k, v in tr["QG_MaskToSeg"].get(f, {}).items()))
readme = open(os.path.join(PKG, "README.md"), encoding="utf-8").read()
check("README 节点表登记", "| `QG_MaskToSeg` | QG 遮罩到 Seg |" in readme)
check("README 专章", "### `QG_MaskToSeg` 遮罩到 Seg" in readme)
check("README 节点数 38", "本节覆盖全部 38 个节点" in readme)
init_src = open(os.path.join(PKG, "__init__.py"), encoding="utf-8").read()
check("__init__ 注册新节点", "from . import qg_mask_to_seg as _mask_to_seg" in init_src)

print()
print("合计 PASS %d / FAIL %d" % (ok, fail))
sys.exit(1 if fail else 0)
