"""QG_MaskOrderFilter - 遮罩次序过滤：把 MASK 批次按面积/宽高/位置排序、分组、
索引筛选，再输出 Seg 与 Mask 两路。

功能规格参考 Goohaitools「孤海-Seg次序过滤」（GPL-3.0）的控件与行为，代码
为独立实现，未复制上游源码。与上游的关键差别：

* **双输出。** 与上游一样 Seg 在上、Mask 在下；上游是 Impact-Pack 的 ``SEGS``，
  本包输出自造 ``QG_SEGS`` 兼容容器（duck-typing），不导入检测节点、不碰第三方
  SEGS，也不要求安装 Impact-Pack。
* **可选 segs 口。** 既可吃 ComfyUI 原生 MASK（每帧当一段），也可直接接本包
  QG_SimpleSegDetector 输出的自造 ``QG_SEGS``；与 masks 二选一，masks 优先。
  接 segs 时尽量保留原段的框/标签/打分等元数据到输出 Seg。
* **不依赖 cv2。** 每帧的外接框直接由非零像素的行列下标取 min/max，面积用
  ``sum(mask > 阈值)``；连通域分析不是本节点语义的一部分。
* **新增「重叠因子」。** 截图里有该控件但本机 Goohaitools 源码没有；这里把它
  实现为 bbox IoU 去重阈值：排序后逐段保留，与已保留段的 IoU 超过阈值的段
  跳过（保留面积大的在前）。0 关闭去重。
* **合并/逐帧两种输出。** 合并时取逐像素最大值（遮罩是 0~1，不是相加）；
  关闭时按筛选顺序堆叠成批次，每帧仍是独立遮罩。

注册 key：QG_MaskOrderFilter；输出 QG_SEGS + MASK。
"""

from __future__ import annotations

import numpy as np
import torch

PRIORITY_RULES = ["面积大小", "宽度大小", "高度大小", "上下左右", "下上左右"]
DIRECTIONS = ["正序", "反序"]
_VALID_CUT = 0.1
# 自造 SEGS 类型，与 qg_simple_seg_detector.SEGS_TYPE 保持一致；
# 只接本包 QG_SimpleSegDetector 的输出，不碰 Impact/LitSegs 的第三方结构。
SEGS_TYPE = "QG_SEGS"


class _SegItem:
    """筛选后的一段：字段与检测节点的 QGSeg 一致，便于下游按属性读取。"""

    __slots__ = ("bbox", "label", "score", "mask", "crop_factor")

    def __init__(self, bbox, label, score, mask, crop_factor):
        self.bbox = tuple(float(v) for v in bbox)
        self.label = str(label)
        self.score = float(score)
        self.mask = mask
        self.crop_factor = float(crop_factor)

    def __repr__(self):
        return "_SegItem(label=%r, score=%.3f, bbox=%s)" % (
            self.label, self.score, self.bbox)


class _SegsContainer:
    """输出用 QG_SEGS 兼容容器， duck-typing 对齐 QGSegs，不导入检测节点。"""

    def __init__(self, segs, width, height):
        self.segs = list(segs)
        self.width = int(width)
        self.height = int(height)

    def __len__(self):
        return len(self.segs)

    def __iter__(self):
        return iter(self.segs)

    def __getitem__(self, index):
        return self.segs[index]

    def __repr__(self):
        return "_SegsContainer(%d segs, %dx%d)" % (len(self.segs), self.width, self.height)

    def combined_mask(self):
        """逐像素取最大，合成一张 [H,W]；无段时返回全 0。"""
        if not self.segs:
            return np.zeros((self.height, self.width), dtype=np.float32)
        out = self.segs[0].mask.copy()
        for seg in self.segs[1:]:
            np.maximum(out, seg.mask, out=out)
        return out

    def mask_batch(self):
        """每段一帧，堆叠成 [N,H,W]；无段时返回 [0,H,W]。"""
        if not self.segs:
            return np.zeros((0, self.height, self.width), dtype=np.float32)
        return np.stack([s.mask for s in self.segs], axis=0)


def _to_numpy(mask):
    """把 MASK 转成 numpy float32。

    ComfyUI 原生 MASK 是 torch.Tensor，但本包自造检测节点以及其他第三方插件
    可能直接给 numpy.ndarray；这里统一规整，避免在上游给 ndarray 时调用
    ``.detach()`` 报 AttributeError。
    """
    if isinstance(mask, torch.Tensor):
        return mask.detach().cpu().numpy().astype(np.float32, copy=False)
    return np.asarray(mask, dtype=np.float32)


def _as_bhw(mask):
    """把 MASK 规整成 ``[B, H, W]`` 的 numpy 数组；返回 (batch, 是否原本二维)。"""
    arr = _to_numpy(mask)
    if arr.ndim == 2:
        return arr[None, ...], True
    if arr.ndim == 3:
        return arr, False
    return arr.reshape(-1, arr.shape[-2], arr.shape[-1]), False


def _frame_feature(plane):
    """单帧 ``[H, W]`` 的面积与外接框；空遮罩返回 0 与全零框。"""
    active = np.asarray(plane, dtype=np.float32) > _VALID_CUT
    ys, xs = np.nonzero(active)
    if ys.size == 0:
        return 0.0, (0, 0, 0, 0)
    x1, x2 = int(xs.min()), int(xs.max()) + 1
    y1, y2 = int(ys.min()), int(ys.max()) + 1
    return float(ys.size), (x1, y1, x2, y2)


def _iou(a, b):
    """两个 ``(x1, y1, x2, y2)`` 框的交并比；空框视为 0。"""
    if a[2] <= a[0] or a[3] <= a[1] or b[2] <= b[0] or b[3] <= b[1]:
        return 0.0
    inter_w = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    inter_h = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = inter_w * inter_h
    if inter == 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / float(area_a + area_b - inter)


def _group_by_x(items, threshold):
    """按外接框左边界 x1 分组：相邻 x1 差不超过阈值的归为同一组。"""
    ordered = sorted(items, key=lambda it: it["bbox"][0])
    groups, current, current_x = [], [], None
    for item in ordered:
        x1 = item["bbox"][0]
        if current_x is None or abs(x1 - current_x) <= threshold:
            current.append(item)
            current_x = x1
        else:
            groups.append(current)
            current, current_x = [item], x1
    if current:
        groups.append(current)
    return groups


def order_segments(frames, rule="上下左右", direction="正序", group_threshold=120,
                   metas=None):
    """对 ``[np.ndarray, ...]`` 单帧列表排序，返回带面积/框的新列表（不改入参）。

    metas 可选：与 frames 等长的原段对象，透传到 ``meta`` 字段供 Seg 输出复用。
    """
    items = []
    for index, plane in enumerate(frames):
        area, bbox = _frame_feature(plane)
        item = {"plane": plane, "area": area, "bbox": bbox}
        if metas is not None and index < len(metas):
            item["meta"] = metas[index]
        items.append(item)

    reverse = direction == "正序"
    if rule == "面积大小":
        items.sort(key=lambda it: it["area"], reverse=reverse)
    elif rule == "宽度大小":
        items.sort(key=lambda it: it["bbox"][2] - it["bbox"][0], reverse=reverse)
    elif rule == "高度大小":
        items.sort(key=lambda it: it["bbox"][3] - it["bbox"][1], reverse=reverse)
    elif rule in ("上下左右", "下上左右"):
        groups = _group_by_x(items, max(0, int(group_threshold)))
        groups.sort(key=lambda g: float(np.mean([it["bbox"][0] for it in g])))
        flat = []
        for group in groups:
            if rule == "上下左右":
                group.sort(key=lambda it: it["bbox"][1])       # y1 小在上
            else:
                group.sort(key=lambda it: it["bbox"][3], reverse=True)  # y2 大在下
            flat.extend(group)
        items = list(reversed(flat)) if not reverse else flat
    return items


def select_segments(items, start=0, count=1, overlap=0.0):
    """按开始索引/数量截取，并按重叠因子做 bbox IoU 去重。"""
    if not items:
        return []
    start = max(0, int(start))
    count = max(0, int(count))
    if count == 0:
        chosen = list(items[start:])
    else:
        # 超出尾部时从头循环取，保证「过滤数量」总能取满（对齐上游行为）
        chosen = [items[(start + i) % len(items)] for i in range(count)]
    if overlap <= 0:
        return chosen
    kept = []
    for item in chosen:
        if any(_iou(item["bbox"], other["bbox"]) > overlap for other in kept):
            continue
        kept.append(item)
    return kept


def merge_segments(items, height, width, merge=True):
    """合并输出：merge=True 取逐像素最大值输出 [H,W]；否则堆叠成 [B,H,W]。"""
    if not items:
        empty = np.zeros((height, width), dtype=np.float32)
        return empty if merge else empty[None, ...]
    planes = [np.asarray(it["plane"], dtype=np.float32) for it in items]
    if merge:
        out = np.zeros((height, width), dtype=np.float32)
        for plane in planes:
            np.maximum(out, plane, out=out)
        return out
    return np.stack(planes, axis=0)


def _build_segs(items, height, width):
    """把筛选后的段打包成 QG_SEGS 兼容容器；有原段元数据时尽量保留。"""
    parts = []
    for item in items:
        meta = item.get("meta")
        plane = np.asarray(item["plane"], dtype=np.float32)
        if meta is not None:
            bbox = getattr(meta, "bbox", item["bbox"])
            label = getattr(meta, "label", "")
            score = getattr(meta, "score", 1.0)
            crop_factor = getattr(meta, "crop_factor", 3.0)
        else:
            bbox, label, score, crop_factor = item["bbox"], "", 1.0, 3.0
        parts.append(_SegItem(bbox, label, score, plane, crop_factor))
    return _SegsContainer(parts, width, height)


class QGMaskOrderFilter:
    """按面积/宽高/位置给遮罩排序、分组、筛选并输出 Seg + Mask。"""

    CATEGORY = "QG 工具"
    FUNCTION = "execute"
    RETURN_TYPES = (SEGS_TYPE, "MASK")
    RETURN_NAMES = ("segs", "MASK")
    OUTPUT_TOOLTIPS = (
        "筛选后的自造 QG_SEGS 容器：每段的框、标签、打分与遮罩，可继续接本包 seg 下游。",
        "按次序筛选后的遮罩：合并开关打开时是单张 [H,W]，关闭时是按顺序堆叠的批次。",
    )
    DESCRIPTION = (
        "Sort, group, filter and merge a mask batch. Each mask frame is treated as "
        "one segment. Order by area, width, height or left-to-right groups; pick by "
        "start index and count; remove overlapping boxes by IoU; merge by pixel-wise "
        "maximum or keep frames separate. Independent of Impact-Pack."
    )
    SEARCH_ALIASES = ["次序过滤", "遮罩排序", "Mask filter", "Seg 过滤"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "优先规则": (list(PRIORITY_RULES), {
                    "default": "上下左右",
                    "tooltip": "面积大小：正序从大到小。宽度/高度大小：同理。上下左右：按 X 坐标分组，组从左到右、组内从上到下。下上左右：组内从下到上。",
                }),
                "正反顺序": (list(DIRECTIONS), {
                    "default": "正序",
                    "tooltip": "正序按规则的自然方向，反序把结果整体倒过来。",
                }),
                "开始索引": ("INT", {
                    "default": 0, "min": 0, "max": 4096, "step": 1,
                    "tooltip": "从排序结果的第几个开始取，从 0 数起。",
                }),
                "过滤数量": ("INT", {
                    "default": 1, "min": 0, "max": 4096, "step": 1,
                    "tooltip": "取多少段；0 表示从开始索引一直取到末尾，超出尾部会从头循环。",
                }),
                "分组阈值": ("INT", {
                    "default": 120, "min": 0, "max": 4096, "step": 1,
                    "tooltip": "上下左右/下上左右规则下，X 坐标相差不超过该像素数的段算同一列。",
                }),
                "重叠因子": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "按外接框 IoU 去重：与前面已保留段的重叠超过该比例就跳过；0 关闭。",
                }),
                "合并遮罩": ("BOOLEAN", {
                    "default": False,
                    "label_on": "合并", "label_off": "逐帧",
                    "tooltip": "合并：所有筛选段取逐像素最大值，输出单张遮罩。逐帧：按次序堆成批次，每段独立。",
                }),
            },
            "optional": {
                # 与上游「Segs 在上、遮罩在下」的输出顺序对齐，避免连线交叉
                "segs": (SEGS_TYPE, {
                    "tooltip": "自造分段容器（QG 简易 Seg 检测的输出），每段取其中遮罩当一段；与 masks 二选一，优先用 masks。",
                }),
                "masks": ("MASK", {
                    "tooltip": "遮罩批次，每一帧当成一个独立段；单张 [H,W] 视为一段。与 segs 二选一，都不接则报错。",
                }),
            },
        }

    def execute(self, masks=None, 优先规则="上下左右", 正反顺序="正序", 开始索引=0,
                过滤数量=1, 分组阈值=120, 重叠因子=0.0, 合并遮罩=False, segs=None):
        # masks 与 segs 二选一：masks 优先；只接 segs 时取每段的遮罩当一段。
        # 全程 duck-typing，不 import 检测节点，也不解析任何第三方 SEGS 结构。
        source_segs = None
        if masks is None:
            if segs is None:
                raise ValueError(
                    "QG 遮罩次序过滤：请接上「遮罩」或「segs 分段」其中一个输入口。")
            if not hasattr(segs, "mask_batch"):
                raise TypeError(
                    "QG 遮罩次序过滤：segs 必须是本包「QG 简易 Seg 检测」输出的 "
                    "QG_SEGS 容器，收到的是 %s。" % type(segs).__name__)
            source_segs = segs
            masks = segs.mask_batch()
        batch, was_2d = _as_bhw(masks)
        # 输入是 Tensor 时跟随其设备/精度；输入是 ndarray 时按 CPU fp32 处理。
        if isinstance(masks, torch.Tensor):
            device, dtype = masks.device, masks.dtype
        else:
            device, dtype = torch.device("cpu"), torch.float32
        frames = [batch[i] for i in range(batch.shape[0])]
        # 接 segs 时保留原段元数据（框/标签/打分），输出 Seg 才有意义
        metas = None
        if source_segs is not None and hasattr(source_segs, "segs"):
            metas = list(source_segs.segs)[:len(frames)]
        items = order_segments(frames, 优先规则, 正反顺序, 分组阈值, metas)
        selected = select_segments(items, 开始索引, 过滤数量, 重叠因子)
        _, height, width = batch.shape
        out = merge_segments(selected, height, width, 合并遮罩)
        result = torch.from_numpy(np.ascontiguousarray(out)).to(device=device, dtype=dtype)
        # 单帧输入 + 合并输出：保持二维，和 ComfyUI MASK 习惯一致
        if was_2d and 合并遮罩 and result.ndim == 3 and result.shape[0] == 1:
            result = result[0]
        # Seg 口与上游对齐：排在最上面；每段始终保留独立遮罩，不受「合并遮罩」影响
        filtered = _build_segs(selected, width, height)
        return (filtered, result)


NODE_CLASS_MAPPINGS = {"QG_MaskOrderFilter": QGMaskOrderFilter}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_MaskOrderFilter": "QG 遮罩次序过滤"}
