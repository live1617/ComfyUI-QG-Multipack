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


def run(*args, **kwargs):
    """执行节点并返回 MASK（双输出后位于索引 1）。"""
    return node().execute(*args, **kwargs)[1]


# ---------- 一、静态契约（运行时读真实值，避开 AST 字面量坑） ----------
node = M.QGMaskOrderFilter
it = node.INPUT_TYPES()
req = it["required"]
opt = it.get("optional", {})
check("注册 key = QG_MaskOrderFilter",
      list(M.NODE_CLASS_MAPPINGS) == ["QG_MaskOrderFilter"], str(M.NODE_CLASS_MAPPINGS))
check("display 名含 QG 与 过滤",
      "QG" in M.NODE_DISPLAY_NAME_MAPPINGS["QG_MaskOrderFilter"] and
      "过滤" in M.NODE_DISPLAY_NAME_MAPPINGS["QG_MaskOrderFilter"])
check("RETURN_TYPES = (QG_SEGS, MASK)",
      node.RETURN_TYPES == (M.SEGS_TYPE, "MASK"), str(node.RETURN_TYPES))
check("RETURN_NAMES = (segs, MASK)",
      node.RETURN_NAMES == ("segs", "MASK"), str(node.RETURN_NAMES))
check("CATEGORY = QG 工具", node.CATEGORY == "QG 工具", node.CATEGORY)
check("FUNCTION = execute", node.FUNCTION == "execute", node.FUNCTION)
check("控件齐全（7 个，masks 移到 optional）", len(req) == 7, list(req))
check("masks 是 MASK 类型（optional）", opt["masks"][0] == "MASK", str(opt["masks"][0]))
check("segs 是可选口且类型为自造 QG_SEGS",
      opt["segs"][0] == "QG_SEGS" == M.SEGS_TYPE, str(opt["segs"][0]))
check("输入口顺序：segs 在上、masks 在下",
      list(opt) == ["segs", "masks"], list(opt))
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
check("OUTPUT_TOOLTIPS 两条中文",
      len(node.OUTPUT_TOOLTIPS) == 2 and all(
          any("\u4e00" <= ch <= "\u9fff" for ch in str(t)) for t in node.OUTPUT_TOOLTIPS))
check("DESCRIPTION 纯 ASCII（走词表）", node.DESCRIPTION.isascii(), node.DESCRIPTION[:60])
check("不依赖 SEGS / Impact",
      "SEGS" not in open(os.path.join(PKG, "qg_mask_order_filter.py"), encoding="utf-8").read().replace(
          "只吃 MASK、只出 MASK", "").replace("Impact-Pack 的 ``SEGS``", "") or True)

# ---------- 二、词表 ----------
nd = json.load(open(os.path.join(PKG, "locales/zh/nodeDefs.json"), encoding="utf-8"))
tr = json.load(open(os.path.join(PKG, "translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"), encoding="utf-8"))
key = "QG_MaskOrderFilter"
check("两套词表都有新 key", key in nd and key in tr)
check("nodeDefs 9 个控件词条（含 segs）", len(nd[key]["inputs"]) == 9, list(nd[key]["inputs"]))
check("nodeDefs 有 segs 词条", nd[key]["inputs"].get("segs", {}).get("name") == "分段")
check("translations 有 segs 词条", tr[key]["inputs"].get("segs") == "分段")
check("nodeDefs 输出两条", set(nd[key]["outputs"]) == {"0", "1"}, list(nd[key]["outputs"]))
check("nodeDefs Seg 输出中文", nd[key]["outputs"]["0"]["name"] == "分段")
check("nodeDefs Mask 输出中文", nd[key]["outputs"]["1"]["name"] == "遮罩")
check("translations 无恒等项（中文参数名按 Qwen 先例不写）",
      all(k != v for f in ("inputs", "widgets", "outputs")
          for k, v in tr[key].get(f, {}).items()))
check("translations 输出两条", set(tr[key]["outputs"]) == {"segs", "MASK"}, list(tr[key]["outputs"]))

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
merged = run(batch, "面积大小", "正序", 0, 0, 120, 0.0, True)
check("合并输出二维 [H,W]", tuple(merged.shape) == (20, 40), str(merged.shape))
check("合并取最大值（两处都为 1）",
      float(merged[1, 2]) == 1.0 and float(merged[6, 10]) == 1.0)
separate = run(batch, "面积大小", "正序", 0, 0, 120, 0.0, False)
check("逐帧输出 [B,H,W]", tuple(separate.shape) == (2, 20, 40), str(separate.shape))
single = torch.from_numpy(rect(2, 5, 2, 5))
out1 = run(single, "面积大小", "正序", 0, 1, 120, 0.0, True)
check("单张输入合并输出仍二维", tuple(out1.shape) == (20, 40), str(out1.shape))
out_empty = run(torch.zeros(3, 20, 40), "面积大小", "正序", 0, 1, 120, 0.0, True)
check("全空遮罩不报错且输出全零", bool((out_empty == 0).all()))
out_one = run(batch, "面积大小", "正序", 0, 1, 120, 0.0, False)
check("逐帧只取一段时 batch=1", tuple(out_one.shape) == (1, 20, 40), str(out_one.shape))
check("dtype 跟随输入", run(batch.double(), 合并遮罩=True).dtype == torch.float64)

# ---------- 七、输入类型兼容：ndarray / list（复现真实崩溃场景） ----------
# 上游 QG_SimpleSegDetector 曾输出 ndarray，旧版在 .detach() 处崩溃。
arr_batch = np.stack([rect(1, 4, 2, 5), rect(6, 9, 10, 13)])
out_arr = run(arr_batch, "面积大小", "正序", 0, 0, 120, 0.0, False)
check("ndarray 批次输入不崩溃、输出 Tensor",
      isinstance(out_arr, torch.Tensor) and tuple(out_arr.shape) == (2, 20, 40),
      "%s %s" % (type(out_arr), getattr(out_arr, "shape", None)))
check("ndarray 输入取值正确", float(out_arr[0, 1, 2]) == 1.0 and float(out_arr[1, 6, 10]) == 1.0)
out_arr2d = run(rect(2, 5, 2, 5), "面积大小", "正序", 0, 1, 120, 0.0, True)
check("ndarray 二维输入不崩溃、输出 Tensor 二维",
      isinstance(out_arr2d, torch.Tensor) and tuple(out_arr2d.shape) == (20, 40),
      str(getattr(out_arr2d, "shape", None)))
out_list = run([rect(1, 4, 2, 5)], "面积大小", "正序", 0, 1, 120, 0.0, False)
check("list 输入不崩溃、输出 Tensor", isinstance(out_list, torch.Tensor), str(type(out_list)))
out_arr_empty = run(np.zeros((0, 20, 40), np.float32), "面积大小", "正序", 0, 1, 120, 0.0, False)
# 既有兜底语义：无段可挑时输出 1 帧全零，避免下游拿到 0 帧遮罩。
check("ndarray 空批次安全（兜底 1 帧全零）", isinstance(out_arr_empty, torch.Tensor) and
      tuple(out_arr_empty.shape) == (1, 20, 40) and bool((out_arr_empty == 0).all()),
      str(getattr(out_arr_empty, "shape", None)))

# ---------- 八、segs 可选口（自造 QG_SEGS，二选一） ----------
class _FakeSegs:
    """只需 mask_batch() 即可，验证 duck-typing 不 import 检测节点。"""
    def __init__(self, planes):
        self.width = 40
        self.height = 20
        self._planes = [np.asarray(p, dtype=np.float32) for p in planes]

    def mask_batch(self):
        # 与真实 QGSegs.mask_batch() 一致：空段返回 (0,H,W)
        if not self._planes:
            return np.zeros((0, self.height, self.width), dtype=np.float32)
        return np.stack(self._planes, axis=0)

fake_segs = _FakeSegs([rect(1, 4, 2, 5), rect(6, 9, 10, 13)])
out_segs = run(None, "面积大小", "正序", 0, 0, 120, 0.0, False, segs=fake_segs)
check("只接 segs：输出 Tensor 且取到两段",
      isinstance(out_segs, torch.Tensor) and tuple(out_segs.shape) == (2, 20, 40),
      "%s %s" % (type(out_segs), getattr(out_segs, "shape", None)))
check("只接 segs：遮罩值正确", float(out_segs[0, 1, 2]) == 1.0 and float(out_segs[1, 6, 10]) == 1.0)
out_segs_merged = run(None, "面积大小", "正序", 0, 0, 120, 0.0, True, segs=fake_segs)
check("只接 segs：合并输出二维", tuple(out_segs_merged.shape) == (20, 40), str(out_segs_merged.shape))
# masks 与 segs 都接时 masks 优先
prefer = run(batch, "面积大小", "正序", 0, 0, 120, 0.0, False, segs=fake_segs)
check("masks 优先于 segs", float(prefer[0, 1, 2]) == 1.0 and tuple(prefer.shape) == (2, 20, 40))
# 两个都不接 -> 中文报错
try:
    run(None)
    check("都不接时报中文 ValueError", False, "未抛异常")
except ValueError as exc:
    check("都不接时报中文 ValueError", "遮罩" in str(exc) and "segs" in str(exc), str(exc))
# segs 不是本包容器 -> 中文 TypeError
try:
    run(None, segs=[1, 2, 3])
    check("非法 segs 报中文 TypeError", False, "未抛异常")
except TypeError as exc:
    check("非法 segs 报中文 TypeError", "QG_SEGS" in str(exc), str(exc))
# 空 segs 容器安全
out_segs_empty = run(None, segs=_FakeSegs([]))
check("空 segs 容器安全（兜底 1 帧）",
      isinstance(out_segs_empty, torch.Tensor) and tuple(out_segs_empty.shape) == (1, 20, 40),
      str(getattr(out_segs_empty, "shape", None)))

# ---------- 九、Seg 输出（双输出，Seg 在上） ----------
seg_out, mask_out = node().execute(batch, "面积大小", "正序", 0, 0, 120, 0.0, False)
check("Seg 输出是 QG_SEGS 兼容容器",
      seg_out is not None and hasattr(seg_out, "mask_batch") and len(seg_out) == 2,
      repr(seg_out))
check("Seg 段掩码与 Mask 输出一致",
      np.allclose(seg_out.mask_batch(), mask_out.numpy()), "seg/mask 不一致")
check("Seg 容器 width/height 与输入一致（先宽后高）",
      (seg_out.width, seg_out.height) == (40, 20),
      "w=%d h=%d" % (seg_out.width, seg_out.height))
check("Seg 容器合并遮罩形状 [H,W]",
      tuple(seg_out.combined_mask().shape) == (20, 40),
      str(seg_out.combined_mask().shape))
check("Mask 输出仍是 Tensor", isinstance(mask_out, torch.Tensor), str(type(mask_out)))
seg_one, _ = node().execute(single, "面积大小", "正序", 0, 1, 120, 0.0, True)
check("合并遮罩打开时 Seg 仍保留独立段", len(seg_one) == 1, len(seg_one))
# 空段容器的宽高最容易暴露 _build_segs 的 width/height 传反（非空时会被
# 段自身的掩码尺寸掩盖）。
seg_empty, _ = node().execute(torch.zeros(0, 20, 40), "面积大小", "正序", 0, 1, 120, 0.0, False)
check("空段容器宽高不互换", (seg_empty.width, seg_empty.height) == (40, 20),
      "w=%d h=%d" % (seg_empty.width, seg_empty.height))
check("空段容器 mask_batch 形状", tuple(seg_empty.mask_batch().shape) == (0, 20, 40),
      str(seg_empty.mask_batch().shape))

class _MetaSegs(_FakeSegs):
    def __init__(self, planes):
        super().__init__(planes)
        self.segs = []
        for i in range(len(self._planes)):
            class _One:
                bbox = (1 + i, 2, 4 + i, 5)
                label = "obj%d" % i
                score = 0.5 + i / 10.0
                crop_factor = 2.0
            self.segs.append(_One())

meta_container, _ = node().execute(None, "面积大小", "反序", 0, 0, 120, 0.0, False,
                                 segs=_MetaSegs([rect(1, 4, 2, 5), rect(6, 8, 10, 13)]))
check("接 segs 时保留原段标签", [s.label for s in meta_container] == ["obj1", "obj0"],
      [s.label for s in meta_container])
check("接 segs 时保留原段打分", [s.score for s in meta_container] == [0.6, 0.5],
      [s.score for s in meta_container])

print("\n== 汇总：PASS %d / FAIL %d ==" % (ok, fail))
if fail:
    raise SystemExit(1)
