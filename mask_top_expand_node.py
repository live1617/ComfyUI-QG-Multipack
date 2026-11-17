"""QG_MaskTopExpand - 头顶遮罩扩展：从遮罩最高点向上补一块矩形。

功能规格参考 Goohaitools「孤海-头顶遮罩」（GPL-3.0），代码为独立实现，未复制
上游源码。用途是外补画板 / 扩图节点之前的准备：证件照头顶发量不够时，先给
生成阶段圈出一块"往上补"的区域。

和上游做法的差别：

* **原遮罩不再被丢掉。** 上游 ``new_mask = zeros_like(...)`` 之后只填矩形，
  名字叫 expand 实际是 replace —— 原遮罩（比如人物轮廓）整块消失。这里默认
  ``keep_original=True``，矩形与原遮罩取并集；想要上游那种"只要矩形"就关掉它。
* **批量遮罩逐帧处理。** 上游 ``mask.squeeze(0)`` 假定只有一帧，批次进来后
  维度错位、结果全错。这里按 ``[B, H, W]`` 逐帧算，单帧 ``[H, W]`` 也照常。
* **中心点用中位数。** 顶行偶尔有一个游离像素就把矩形整体拽偏，所以取顶行
  横坐标的中位数而不是平均值。
* **可选羽化。** 硬边矩形直接接外补画板会在接缝处留一条亮线，``feather``
  给矩形边缘做高斯过渡。

中心点三种取法（``center_mode``）：

``top_center``  遮罩最高点那一行的水平中位数（默认，贴头顶）
``bbox_center`` 整个遮罩外接框的水平中心（人物居中时更稳）
``mask_center`` 遮罩质心（头发左右不对称时偏向发量多的一侧）

注册 key：QG_MaskTopExpand；输出 MASK（形状与输入一致）。
"""

from __future__ import annotations

import numpy as np
import torch
from PIL import Image, ImageFilter

CENTER_MODES = ["top_center", "bbox_center", "mask_center"]
DEFAULT_EXPAND_X = 50
DEFAULT_EXPAND_Y = 100
_VALID_CUT = 0.5


def _as_bhw(mask):
    """把 MASK 规整成 ``[B, H, W]``；返回 (batch, 是否原本是二维)。"""
    if mask.ndim == 2:
        return mask.unsqueeze(0), True
    if mask.ndim == 3:
        return mask, False
    # 4 通道之类：压掉多余的维度，取第一层
    squeezed = mask.reshape(-1, mask.shape[-2], mask.shape[-1])
    return squeezed, False


def _center_x(binary, mode):
    """按 mode 求水平中心；遮罩为空返回 None。"""
    ys, xs = np.nonzero(binary)
    if ys.size == 0:
        return None
    if mode == "bbox_center":
        return int(round((xs.min() + xs.max()) / 2.0))
    if mode == "mask_center":
        return int(round(float(xs.mean())))
    # top_center：最高一行（含 1 像素容差）的横坐标中位数
    top = ys.min()
    row = xs[ys <= top]
    return int(round(float(np.median(row))))


def _feather(plane, radius):
    """对 float 平面做高斯羽化（radius<=0 原样返回）。"""
    if radius <= 0:
        return plane
    img = Image.fromarray((np.clip(plane, 0.0, 1.0) * 255.0).astype(np.uint8), "L")
    img = img.filter(ImageFilter.GaussianBlur(float(radius)))
    return np.asarray(img, dtype=np.float32) / 255.0


def expand_frame(plane, expand_x, expand_y, mode="top_center",
                 feather=0, keep_original=True):
    """单帧 ``[H, W]`` 头顶扩展，返回同形状 float32 numpy。"""
    height, width = plane.shape
    binary = np.asarray(plane, dtype=np.float32) >= _VALID_CUT
    center = _center_x(binary, mode)
    if center is None:
        return np.asarray(plane, dtype=np.float32)

    ys = np.nonzero(binary)[0]
    top = int(ys.min())

    x0 = max(0, center - max(0, int(expand_x)))
    x1 = min(width, center + max(0, int(expand_x)))
    y0 = max(0, top - max(0, int(expand_y)))
    y1 = min(height, top)          # 矩形到头顶那一行为止，不盖住脸

    rect = np.zeros((height, width), dtype=np.float32)
    if x1 > x0 and y1 > y0:
        rect[y0:y1, x0:x1] = 1.0
    rect = _feather(rect, feather)

    if keep_original:
        return np.maximum(np.asarray(plane, dtype=np.float32), rect)
    return rect


class QGMaskTopExpand:
    """头顶遮罩扩展：向上补矩形，可与原遮罩合并。"""

    CATEGORY = "QG 工具"
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "execute"
    DESCRIPTION = (
        "Adds a rectangular cap above the highest point of a mask, so an "
        "outpaint node has room to grow hair upwards. Every frame of a batch is "
        "handled, the rectangle can be feathered, and by default it is merged "
        "with the original mask instead of replacing it."
    )
    SEARCH_ALIASES = ["头顶", "遮罩扩展", "top mask", "outpaint", "扩图"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mask": ("MASK", {
                    "tooltip": "以这张遮罩的顶边为基准，往外扩出新矩形。",
                }),
                "expand_x": ("INT", {
                    "default": DEFAULT_EXPAND_X, "min": 0, "max": 4096, "step": 1,
                    "tooltip": "半宽（像素）：矩形横向范围是中心点 ± 这个值。",
                }),
                "expand_y": ("INT", {
                    "default": DEFAULT_EXPAND_Y, "min": 0, "max": 4096, "step": 1,
                    "tooltip": "矩形在遮罩最高像素之上再往上走多少。",
                }),
                "center_mode": (list(CENTER_MODES), {
                    "default": "top_center",
                    "tooltip": "top_center：顶边那一行的中位横坐标。bbox_center：遮罩外框的"
                               "中心。mask_center：质心。",
                }),
                "feather": ("INT", {
                    "default": 0, "min": 0, "max": 256, "step": 1,
                    "tooltip": "矩形边缘的高斯模糊半径。0 是硬边。",
                }),
                "keep_original": ("BOOLEAN", {
                    "default": True,
                    "label_on": "Merge", "label_off": "Replace",
                    "tooltip": "合并：与输入遮罩取并集。替换：只输出新矩形。",
                }),
            },
        }

    def execute(self, mask, expand_x=DEFAULT_EXPAND_X, expand_y=DEFAULT_EXPAND_Y,
                center_mode="top_center", feather=0, keep_original=True):
        batch, was_2d = _as_bhw(mask)
        device = mask.device
        frames = []
        for i in range(batch.shape[0]):
            plane = batch[i].detach().cpu().numpy().astype(np.float32, copy=False)
            frames.append(expand_frame(plane, expand_x, expand_y, center_mode,
                                       feather, keep_original))
        out = np.stack(frames, axis=0)
        result = torch.from_numpy(out).to(device=device, dtype=mask.dtype)
        if was_2d:
            result = result[0]
        return (result,)


NODE_CLASS_MAPPINGS = {"QG_MaskTopExpand": QGMaskTopExpand}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_MaskTopExpand": "QG 头顶遮罩扩展"}
