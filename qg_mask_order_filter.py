"""QG_MaskOrderFilter - 遮罩次序过滤：把 MASK 批次按面积/宽高/位置排序、分组、
索引筛选，再合并或逐帧输出。

功能规格参考 Goohaitools「孤海-Seg次序过滤」（GPL-3.0）的控件与行为，代码
为独立实现，未复制上游源码。与上游的关键差别：

* **只吃 MASK、只出 MASK。** 上游的输入/输出是 Impact-Pack 的 ``SEGS``，必须
  装 Impact-Pack 才能连线；本节点把输入 MASK 的**每一帧当成一个独立段**，
  任何环境都能用，输出仍是 ComfyUI 原生 MASK。
* **不依赖 cv2。** 每帧的外接框直接由非零像素的行列下标取 min/max，面积用
  ``sum(mask > 阈值)``；连通域分析不是本节点语义的一部分。
* **新增「重叠因子」。** 截图里有该控件但本机 Goohaitools 源码没有；这里把它
  实现为 bbox IoU 去重阈值：排序后逐段保留，与已保留段的 IoU 超过阈值的段
  跳过（保留面积大的在前）。0 关闭去重。
* **合并/逐帧两种输出。** 合并时取逐像素最大值（遮罩是 0~1，不是相加）；
  关闭时按筛选顺序堆叠成批次，每帧仍是独立遮罩。

注册 key：QG_MaskOrderFilter；输出 MASK。
"""

from __future__ import annotations

import numpy as np
import torch

PRIORITY_RULES = ["面积大小", "宽度大小", "高度大小", "上下左右", "下上左右"]
DIRECTIONS = ["正序", "反序"]
_VALID_CUT = 0.1


def _as_bhw(mask):
    """把 MASK 规整成 ``[B, H, W]``；返回 (batch, 是否原本二维)。"""
    if mask.ndim == 2:
        return mask.unsqueeze(0), True
    if mask.ndim == 3:
        return mask, False
    return mask.reshape(-1, mask.shape[-2], mask.shape[-1]), False


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


def order_segments(frames, rule="上下左右", direction="正序", group_threshold=120):
    """对 ``[np.ndarray, ...]`` 单帧列表排序，返回带面积/框的新列表（不改入参）。"""
    items = []
    for plane in frames:
        area, bbox = _frame_feature(plane)
        items.append({"plane": plane, "area": area, "bbox": bbox})

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


class QGMaskOrderFilter:
    """按面积/宽高/位置给遮罩排序、分组、筛选并输出。"""

    CATEGORY = "QG 工具"
    FUNCTION = "execute"
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("MASK",)
    OUTPUT_TOOLTIPS = ("按次序筛选后的遮罩：合并开关打开时是单张 [H,W]，关闭时是按顺序堆叠的批次。",)
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
                "masks": ("MASK", {
                    "tooltip": "遮罩批次，每一帧当成一个独立段；单张 [H,W] 视为一段。",
                }),
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
        }

    def execute(self, masks, 优先规则="上下左右", 正反顺序="正序", 开始索引=0,
                过滤数量=1, 分组阈值=120, 重叠因子=0.0, 合并遮罩=False):
        batch, was_2d = _as_bhw(masks)
        device, dtype = masks.device, masks.dtype
        frames = [batch[i].detach().cpu().numpy().astype(np.float32, copy=False)
                  for i in range(batch.shape[0])]
        items = order_segments(frames, 优先规则, 正反顺序, 分组阈值)
        selected = select_segments(items, 开始索引, 过滤数量, 重叠因子)
        _, height, width = batch.shape
        out = merge_segments(selected, height, width, 合并遮罩)
        result = torch.from_numpy(out).to(device=device, dtype=dtype)
        # 单帧输入 + 合并输出：保持二维，和 ComfyUI MASK 习惯一致
        if was_2d and 合并遮罩 and result.ndim == 3 and result.shape[0] == 1:
            result = result[0]
        return (result,)


NODE_CLASS_MAPPINGS = {"QG_MaskOrderFilter": QGMaskOrderFilter}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_MaskOrderFilter": "QG 遮罩次序过滤"}
