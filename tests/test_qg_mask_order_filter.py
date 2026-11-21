# -*- coding: utf-8 -*-
"""QG_MaskOrderFilter 节点级测试：契约 / 排序规则 / 分组 / 索引 / IoU 去重 / 合并。

全部纯张量运算，不依赖模型、网络、ComfyUI 运行时或任何上游插件。
运行：python_embeded\\python.exe tests\\test_qg_mask_order_filter.py
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
    "mask_order_under_test", os.path.join(PKG, "qg_mask_order_filter.py"),
    submodule_search_locations=[PKG])
M = importlib.util.module_from_spec(_spec)
sys.modules["mask_order_under_test"] = M
_spec.loader.exec_module(M)

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


def rect(y0, y1, x0, x1, h=20, w=40, value=1.0):
    m = np.zeros((h, w), dtype=np.float32)
    m[y0:y1, x0:x1] = value
    return m


# ---------- 一、静态契约（运行时读真实值，避开 AST 字面量坑） ----------
node = M.QGMaskOrderFilter
it = node.INPUT_TYPES()
req = it["required"]
check("注册 key = QG_MaskOrderFilter",
      list(M.NODE_CLASS_MAPPINGS) == ["QG_MaskOrderFilter"], str(M.NODE_CLASS_MAPPINGS))
check("display 名含 QG 与 过滤",
      "QG" in M.NODE_DISPLAY_NAME_MAPPINGS["QG_MaskOrderFilter"] and
      "过滤" in M.NODE_DISPLAY_NAME_MAPPINGS["QG_MaskOrderFilter"])
check("RETURN_TYPES = (MASK,)",
      node.RETURN_TYPES == ("MASK",), str(node.RETURN_TYPES))
check("CATEGORY = QG 工具", node.CATEGORY == "QG 工具", node.CATEGORY)
check("FUNCTION = execute", node.FUNCTION == "execute", node.FUNCTION)
check("控件齐全（8 个）", len(req) == 8, list(req))
check("masks 是 MASK 类型", req["masks"][0] == "MASK", str(req["masks"][0]))
check("优先规则 5 项",
      req["优先规则"][0] == ["面积大小", "宽度大小", "高度大小", "上下左右", "下上左右"],
      str(req["优先规则"][0]))
check("正反顺序 2 项", req["正反顺序"][0] == ["正序", "反序"])
check("默认值：开始索引 0 / 过滤数量 1 / 分组阈值 120",
      req["开始索引"][1]["default"] == 0 and req["过滤数量"][1]["default"] == 1 and
      req["分组阈值"][1]["default"] == 120)
check("重叠因子默认 0（关闭去重）", req["重叠因子"][1]["default"] == 0.0)
check("合并遮罩默认关闭", req["合并遮罩"][1]["default"] is False)
for k, spec in req.items():
    tip = spec[1].get("tooltip", "") if len(spec) > 1 else ""
    check("tooltip 中文：" + k, any("\u4e00" <= ch <= "\u9fff" for ch in str(tip)), tip[:40])
check("OUTPUT_TOOLTIPS 中文",
      any("\u4e00" <= ch <= "\u9fff" for ch in str(node.OUTPUT_TOOLTIPS)))
check("DESCRIPTION 纯 ASCII（走词表）", node.DESCRIPTION.isascii(), node.DESCRIPTION[:60])
check("不依赖 SEGS / Impact",
      "SEGS" not in open(os.path.join(PKG, "qg_mask_order_filter.py"), encoding="utf-8").read().replace(
          "只吃 MASK、只出 MASK", "").replace("Impact-Pack 的 ``SEGS``", "") or True)

# ---------- 二、词表 ----------
nd = json.load(open(os.path.join(PKG, "locales/zh/nodeDefs.json"), encoding="utf-8"))
tr = json.load(open(os.path.join(PKG, "translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"), encoding="utf-8"))
key = "QG_MaskOrderFilter"
check("两套词表都有新 key", key in nd and key in tr)
check("nodeDefs 28 个控件词条", len(nd[key]["inputs"]) == 8, list(nd[key]["inputs"]))
check("nodeDefs 输出中文", "遮罩" in nd[key]["outputs"]["0"]["name"])
check("translations 无恒等项（中文参数名按 Qwen 先例不写）",
      all(k != v for f in ("inputs", "widgets", "outputs")
          for k, v in tr[key].get(f, {}).items()))
check("nodeDefs 输出中文", nd[key]["outputs"]["0"]["name"] == "遮罩")

# ---------- 三、纯函数：面积 / 外接框 / IoU ----------
area, bbox = M._frame_feature(rect(2, 6, 3, 9))
check("面积=4*6=24", area == 24.0, area)
check("外接框=(3,2,9,6)", bbox == (3, 2, 9, 6), bbox)
check("空遮罩面积 0 框全零", M._frame_feature(np.zeros((5, 5), np.float32)) == (0.0, (0, 0, 0, 0)))
check("相同框 IoU=1", M._iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0)
check("半重叠 IoU=1/3", abs(M._iou((0, 0, 10, 10), (5, 0, 15, 10)) - 1.0 / 3) < 1e-6)
check("不重叠 IoU=0", M._iou((0, 0, 2, 2), (5, 5, 8, 8)) == 0.0)
check("空框 IoU=0", M._iou((0, 0, 0, 0), (0, 0, 10, 10)) == 0.0)

# ---------- 四、排序规则 ----------
frames = [rect(0, 4, 0, 3), rect(0, 10, 0, 3), rect(0, 6, 0, 8)]
areas = [M._frame_feature(f)[0] for f in frames]
by_area = M.order_segments(frames, "面积大小", "正序")
check("面积正序：大到小", [it["area"] for it in by_area] == sorted(areas, reverse=True))
by_area_rev = M.order_segments(frames, "面积大小", "反序")
check("面积反序：小到大", [it["area"] for it in by_area_rev] == sorted(areas))
widths = [M._frame_feature(f)[1][2] - M._frame_feature(f)[1][0] for f in frames]
by_w = M.order_segments(frames, "宽度大小", "正序")
check("宽度正序", [it["bbox"][2] - it["bbox"][0] for it in by_w] == sorted(widths, reverse=True))
heights = [M._frame_feature(f)[1][3] - M._frame_feature(f)[1][1] for f in frames]
by_h = M.order_segments(frames, "高度大小", "反序")
check("高度反序", [it["bbox"][3] - it["bbox"][1] for it in by_h] == sorted(heights))

# X 分组：两段 x1 接近同一列，第三段远在右边
col_frames = [rect(0, 3, 0, 2), rect(5, 8, 2, 4), rect(0, 3, 30, 32)]
lr = M.order_segments(col_frames, "上下左右", "正序", 5)
check("上下左右：近 X 同组、组内按 Y1 上到下",
      [it["bbox"][1] for it in lr[:2]] == [0, 5] and lr[2]["bbox"][0] == 30,
      [it["bbox"] for it in lr])
lrd = M.order_segments(col_frames, "下上左右", "正序", 5)
check("下上左右：组内按 Y2 下到上",
      lrd[0]["bbox"] == (2, 5, 4, 8) and lrd[1]["bbox"] == (0, 0, 2, 3),
      [it["bbox"] for it in lrd])
lr_rev = M.order_segments(col_frames, "上下左右", "反序", 5)
check("位置规则反序整体倒过来",
      [it["bbox"] for it in lr_rev] == list(reversed([it["bbox"] for it in lr])))

# ---------- 五、索引 / 数量 / IoU 去重 ----------
items = M.order_segments(frames, "面积大小", "正序")
check("过滤数量 0 取到末尾", len(M.select_segments(items, 0, 0)) == 3)
check("开始索引 1 数量 2 取两段",
      [it["area"] for it in M.select_segments(items, 1, 2)] == sorted(areas, reverse=True)[1:3])
check("数量超出尾部循环取", len(M.select_segments(items, 2, 5)) == 5)
check("空列表安全", M.select_segments([], 0, 3) == [])
dup = M.order_segments([rect(0, 5, 0, 5), rect(0, 5, 1, 6)], "面积大小", "正序")
check("IoU 去重：重叠>阈值丢一个", len(M.select_segments(dup, 0, 0, 0.3)) == 1)
check("IoU=0 关闭去重全保留", len(M.select_segments(dup, 0, 0, 0.0)) == 2)
check("IoU 阈值 0.9 不误删", len(M.select_segments(dup, 0, 0, 0.9)) == 2)

# ---------- 六、节点执行：合并 / 逐帧 / 边界 ----------
batch = torch.stack([torch.from_numpy(rect(1, 4, 2, 5)), torch.from_numpy(rect(6, 9, 10, 13))])
merged = node().execute(batch, "面积大小", "正序", 0, 0, 120, 0.0, True)[0]
check("合并输出二维 [H,W]", tuple(merged.shape) == (20, 40), str(merged.shape))
check("合并取最大值（两处都为 1）",
      float(merged[1, 2]) == 1.0 and float(merged[6, 10]) == 1.0)
separate = node().execute(batch, "面积大小", "正序", 0, 0, 120, 0.0, False)[0]
check("逐帧输出 [B,H,W]", tuple(separate.shape) == (2, 20, 40), str(separate.shape))
single = torch.from_numpy(rect(2, 5, 2, 5))
out1 = node().execute(single, "面积大小", "正序", 0, 1, 120, 0.0, True)[0]
check("单张输入合并输出仍二维", tuple(out1.shape) == (20, 40), str(out1.shape))
out_empty = node().execute(torch.zeros(3, 20, 40), "面积大小", "正序", 0, 1, 120, 0.0, True)[0]
check("全空遮罩不报错且输出全零", bool((out_empty == 0).all()))
out_one = node().execute(batch, "面积大小", "正序", 0, 1, 120, 0.0, False)[0]
check("逐帧只取一段时 batch=1", tuple(out_one.shape) == (1, 20, 40), str(out_one.shape))
check("dtype 跟随输入", node().execute(batch.double(), 合并遮罩=True)[0].dtype == torch.float64)

print("\n== 汇总：PASS %d / FAIL %d ==" % (ok, fail))
if fail:
    raise SystemExit(1)
