# -*- coding: utf-8 -*-
"""QG_MaskTopExpand 节点级测试：矩形位置 / batch / 合并语义 / 羽化 / 契约 / i18n。

全部纯张量运算，不依赖模型、网络或 ComfyUI 运行时。
运行：python_embeded\\python.exe tests\\test_mask_top_expand.py
"""
import importlib.util
import json
import os
import sys

import numpy as np
import torch

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PKG)

_spec = importlib.util.spec_from_file_location(
    "mask_top_expand_under_test", os.path.join(PKG, "mask_top_expand_node.py"),
    submodule_search_locations=[PKG])
MTE = importlib.util.module_from_spec(_spec)
sys.modules["mask_top_expand_under_test"] = MTE
_spec.loader.exec_module(MTE)

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


def rect_mask(h, w, y0, y1, x0, x1):
    m = np.zeros((h, w), dtype=np.float32)
    m[y0:y1, x0:x1] = 1.0
    return m


# ---------- 1. 契约 ----------
cls = MTE.NODE_CLASS_MAPPINGS.get("QG_MaskTopExpand")
check("契约：注册 key 只有 QG_MaskTopExpand",
      list(MTE.NODE_CLASS_MAPPINGS) == ["QG_MaskTopExpand"],
      list(MTE.NODE_CLASS_MAPPINGS))
check("契约：类存在", cls is not None)
check("契约：RETURN_TYPES 与 RETURN_NAMES 等长",
      len(cls.RETURN_TYPES) == len(cls.RETURN_NAMES))
check("契约：输出 MASK", cls.RETURN_TYPES == ("MASK",), cls.RETURN_TYPES)
check("契约：FUNCTION 存在", callable(getattr(cls, cls.FUNCTION, None)))
check("契约：分类为 QG 工具", cls.CATEGORY == "QG 工具", cls.CATEGORY)

req = cls.INPUT_TYPES()["required"]
check("控件：mask / expand_x / expand_y / center_mode / feather / keep_original",
      {"mask", "expand_x", "expand_y", "center_mode", "feather",
       "keep_original"} <= set(req), list(req))
check("控件：center_mode 值为英文",
      req["center_mode"][0] == ["top_center", "bbox_center", "mask_center"],
      req["center_mode"][0])
check("控件：keep_original 默认 True",
      req["keep_original"][1].get("default") is True, req["keep_original"][1])

node = cls()

# ---------- 2. 基本矩形（top_center） ----------
base = rect_mask(100, 200, 40, 80, 80, 120)      # 头顶 y=40，中心 x=100
out = MTE.expand_frame(base, 30, 20, "top_center", 0, True)
check("矩形：向上扩 20 像素（y 从 40 到 20）",
      out[20:39, 100] .min() > 0.99 and out[19, 100] < 0.01,
      (float(out[20, 100]), float(out[19, 100])))
check("矩形：宽度为中心 ±30（x 70..130）",
      out[25, 70] > 0.99 and out[25, 129] > 0.99
      and out[25, 69] < 0.01 and out[25, 130] < 0.01,
      (float(out[25, 69]), float(out[25, 70]), float(out[25, 129]),
       float(out[25, 130])))
check("矩形：不盖住原遮罩下方（y=39 为原遮罩）",
      out[39, 100] > 0.99 and out[45, 50] < 0.01)
check("矩形：原遮罩仍在（keep_original=True）",
      out[50:80, 80:120].min() > 0.99, float(out[60, 100]))

# ---------- 3. keep_original=False ----------
repl = MTE.expand_frame(base, 30, 20, "top_center", 0, False)
check("合并语义：Replace 时不保留原遮罩",
      repl[60, 100] < 0.01, float(repl[60, 100]))
check("合并语义：Replace 仍有矩形",
      repl[25, 100] > 0.99, float(repl[25, 100]))

# ---------- 4. 三种中心模式 ----------
skew = rect_mask(100, 200, 40, 60, 20, 30)       # 头顶只有左侧一小块
skew[80:90, 150:170] = 1.0                        # 右下角一大块（拉偏质心/外接框）
top_c = MTE.expand_frame(skew, 10, 10, "top_center", 0, True)
check("中心：top_center 跟着顶行（x≈25）",
      top_c[30, 25] > 0.99 and top_c[30, 100] < 0.01,
      (float(top_c[30, 25]), float(top_c[30, 100])))
bbox_c = MTE.expand_frame(skew, 10, 10, "bbox_center", 0, True)
check("中心：bbox_center 用外接框中点（x≈95）",
      bbox_c[30, 95] > 0.99 and bbox_c[30, 25] < 0.01,
      (float(bbox_c[30, 95]), float(bbox_c[30, 25])))
mask_c = MTE.expand_frame(skew, 10, 10, "mask_center", 0, True)
check("中心：mask_center 用质心（两块等面积 → x≈92）",
      mask_c[30, 92] > 0.99 and mask_c[30, 30] < 0.01,
      (float(mask_c[30, 92]), float(mask_c[30, 30])))

# 顶行有游离像素时用中位数，不被单点拽偏
noisy = rect_mask(100, 200, 40, 80, 90, 110)
noisy[40, 5] = 1.0                                # 顶行最左一个噪点
med = MTE.expand_frame(noisy, 10, 10, "top_center", 0, True)
check("中心：顶行噪点不把矩形拽到最左（中位数抗离群）",
      med[30, 100] > 0.99 and med[30, 10] < 0.01,
      (float(med[30, 100]), float(med[30, 10])))

# ---------- 5. 羽化 ----------
blur = MTE.expand_frame(base, 30, 20, "top_center", 5, True)
check("羽化：边缘出现中间值（0 < v < 1）",
      bool(((blur > 0.02) & (blur < 0.98)).any()),
      float(blur.min()))
big_src = rect_mask(200, 300, 100, 160, 100, 200)
big_blur = MTE.expand_frame(big_src, 60, 50, "top_center", 4, True)
check("羽化：大矩形内部仍是实心",
      big_blur[80, 150] > 0.99, float(big_blur[80, 150]))
check("羽化：矩形上边缘被软化（低于 1）",
      big_blur[52, 150] < 0.999 and big_blur[52, 150] > 0.0,
      float(big_blur[52, 150]))
check("羽化 0 不出中间值",
      not ((out > 0.02) & (out < 0.98)).any())

# ---------- 6. 边界与退化 ----------
zero = MTE.expand_frame(base, 0, 0, "top_center", 0, True)
check("退化：expand 全 0 → 与原遮罩一致",
      np.allclose(zero, base), (float(zero.sum()), float(base.sum())))

empty = np.zeros((50, 50), dtype=np.float32)
check("退化：空遮罩原样返回",
      np.allclose(MTE.expand_frame(empty, 20, 20, "top_center", 0, True), empty))

clip = MTE.expand_frame(rect_mask(50, 60, 2, 20, 5, 15), 100, 100,
                        "top_center", 0, True)
check("越界：扩大超出画布不报错、不越界",
      clip.shape == (50, 60) and float(clip.max()) <= 1.0, clip.shape)
check("越界：贴顶时仍填满顶行", clip[0, 10] > 0.99, float(clip[0, 10]))

# ---------- 7. 批次与形状 ----------
batch = torch.zeros((3, 100, 200), dtype=torch.float32)
batch[0, 40:80, 80:120] = 1.0
batch[1, 20:60, 20:40] = 1.0
batch[2, 60:90, 160:190] = 1.0
res_b = node.execute(batch, 15, 10, "top_center", 0, True)[0]
check("批次：形状保持 [3, 100, 200]", tuple(res_b.shape) == (3, 100, 200),
      tuple(res_b.shape))
check("批次：第 1 帧在自己头顶扩展（x≈100）",
      float(res_b[0, 35, 100]) > 0.99 and float(res_b[0, 35, 30]) < 0.01,
      (float(res_b[0, 35, 100]), float(res_b[0, 35, 30])))
check("批次：第 2 帧在自己头顶扩展（x≈30）",
      float(res_b[1, 15, 30]) > 0.99 and float(res_b[1, 15, 100]) < 0.01,
      (float(res_b[1, 15, 30]), float(res_b[1, 15, 100])))
check("批次：第 3 帧在自己头顶扩展（x≈175）",
      float(res_b[2, 55, 175]) > 0.99 and float(res_b[2, 55, 30]) < 0.01,
      (float(res_b[2, 55, 175]), float(res_b[2, 55, 30])))
check("批次：三帧互不影响（无串帧）",
      float(res_b[1, 35, 100]) < 0.02, float(res_b[1, 35, 100]))

single2d = torch.from_numpy(base)
res2d = node.execute(single2d, 30, 20, "top_center", 0, True)[0]
check("形状：二维输入返回二维", tuple(res2d.shape) == (100, 200),
      tuple(res2d.shape))
single3d = single2d.unsqueeze(0)
res3d = node.execute(single3d, 30, 20, "top_center", 0, True)[0]
check("形状：三维输入返回三维", tuple(res3d.shape) == (1, 100, 200),
      tuple(res3d.shape))

# ---------- 8. 不改输入 / 保持 dtype ----------
before = batch.clone()
node.execute(batch, 15, 10, "top_center", 0, True)
check("副作用：不修改输入张量", torch.equal(batch, before))
hb = torch.zeros((1, 40, 60), dtype=torch.float16)
hb[0, 10:30, 20:40] = 1.0
res_h = node.execute(hb, 5, 5, "top_center", 0, True)[0]
check("dtype：float16 输入保持 float16", res_h.dtype == torch.float16,
      res_h.dtype)
check("dtype：float16 结果数值正确", float(res_h[0, 8, 30]) > 0.9,
      float(res_h[0, 8, 30]))

# ---------- 9. i18n 与文档 ----------
def load_json(rel):
    with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
        return json.load(fh)


defs = load_json("locales/zh/nodeDefs.json")
check("i18n：nodeDefs 有该节点",
      defs.get("QG_MaskTopExpand", {}).get("display_name") == "QG 头顶遮罩扩展",
      defs.get("QG_MaskTopExpand"))
nodes_zh = load_json("translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json")
check("i18n：AIGODLIKE 词表有该节点", "QG_MaskTopExpand" in nodes_zh)
menus = load_json("translations/zh-CN/Menus/ComfyUI-QG-Multipack.json")
check("i18n：Menus 有 center_mode 三值中文",
      menus.get("top_center") and menus.get("bbox_center")
      and menus.get("mask_center"),
      (menus.get("top_center"), menus.get("bbox_center"),
       menus.get("mask_center")))
check("规范：布尔标签保持英文（不进存档，仅显示）",
      req["keep_original"][1].get("label_on") == "Merge"
      and req["keep_original"][1].get("label_off") == "Replace",
      req["keep_original"][1])

readme = open(os.path.join(PKG, "README.md"), encoding="utf-8").read()
check("文档：README 登记该节点", "QG_MaskTopExpand" in readme)

print("\nPASS %d / FAIL %d" % (ok, fail))
sys.exit(1 if fail else 0)
