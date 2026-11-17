"""QG_ImageComposite - 图像合成：把源图按坐标贴到目标画布上，可选遮罩混合。

功能规格参照 ComfyUI_essentials 的 ``ImageComposite+``（GPL-3.0），代码为独立
实现，未复制上游源码。它解决的是同一个问题：目标图（底图）尺寸固定，源图
（要贴上去的内容）按 x/y 放到指定位置，遮罩决定哪些像素替换底图。

和上游做法的差别（都是上游实现里会出错或语义不清的地方）：

* **负坐标不再错位。** 上游用 ``d[y:y+h, x:x+w]`` 直接切片，坐标一旦为负，
  Python 走负索引，会从画布另一头取像素——本该裁掉的左侧/上侧反而贴到了
  右边/下边。这里显式求「源图矩形 ∩ 画布矩形」的交集，再取对应区域。
* **四边越界统一按裁切处理。** 上游只处理了右边界、下边界，负坐标那两侧漏了。
* **帧数取两边较大值。** 上游会把目标强行截到源图的帧数，目标帧更多时会
  丢帧；这里取 ``max(目标帧数, 源帧数)``，短的一边重复最后一帧补齐。
* **遮罩当作先验 alpha。** 尺寸与源图不符时双三次缩放到源图尺寸；单帧遮罩
  广播到所有帧；遮罩值先 ``clip(0,1)``，NaN 会被清成 0 而不是静默污染输出。
* **offset 是叠加量。** 最终位置 = ``(x + offset_x, y + offset_y)``。保留这两个
  控件是为了让位置能被上游的动态值（如逐帧坐标）驱动，单独使用时留 0 即可。

坐标原点在画布左上角，x 向右、y 向下，单位是像素；源图完全落在画布外时
原样返回目标帧，并打印一行提示。

注册 key：QG_ImageComposite；输出 IMAGE（帧数见上）。
"""

from __future__ import annotations

import numpy as np
import torch
from PIL import Image

#: 坐标控件范围（ComfyUI 惯例；只是滑块的上下限，不限制实际贴图尺寸）
COORD_LIMIT = 16384


def _as_frames(tensor):
    """把 ``[H,W,C]`` 或 ``[B,H,W,C]`` 统一成 ``[B,H,W,C]``。"""
    if tensor.ndim == 3:
        return tensor.unsqueeze(0)
    return tensor


def _mask_planes(mask):
    """把 MASK 规整成 ``[H,W]`` float32 列表，裁到 0..1，清掉 NaN。"""
    if mask is None:
        return []
    frames = mask.unsqueeze(0) if mask.ndim == 2 else mask
    if frames.ndim == 4:  # 个别来源会给 [B,H,W,1]
        frames = frames[..., 0]
    arr = frames.detach().cpu().numpy().astype(np.float32)
    arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=0.0)
    return [np.clip(arr[i], 0.0, 1.0) for i in range(arr.shape[0])]


def _resize_plane(plane, height, width):
    """遮罩平面双三次缩放到源图尺寸（尺寸已对则原样返回）。"""
    if plane.shape == (height, width):
        return plane
    img = Image.fromarray((np.clip(plane, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8), "L")
    img = img.resize((width, height), Image.BICUBIC)
    return np.asarray(img, dtype=np.float32) / 255.0


def _fit_channels(patch, channels):
    """源图通道数与画布不一致时补齐 / 截断，避免广播失败。"""
    if patch.shape[2] == channels:
        return patch
    if patch.shape[2] == 1:
        return np.repeat(patch, channels, axis=2)
    if patch.shape[2] > channels:
        return patch[:, :, :channels]
    pad = np.repeat(patch[:, :, -1:], channels - patch.shape[2], axis=2)
    return np.concatenate((patch, pad), axis=2)


def compose_frame(canvas, source, alpha, left, top):
    """把 ``source`` 贴到 ``canvas`` 的 ``(left, top)``，返回新帧（不改入参）。

    ``alpha`` 为 ``None`` 时直接覆盖；否则按 ``source*a + canvas*(1-a)`` 混合。
    源图矩形与画布矩形的交集为空时，返回画布副本。
    """
    out = canvas.copy()
    height, width = canvas.shape[:2]
    src_h, src_w = source.shape[:2]

    x0 = max(int(left), 0)
    y0 = max(int(top), 0)
    x1 = min(int(left) + src_w, width)
    y1 = min(int(top) + src_h, height)
    if x1 <= x0 or y1 <= y0:
        return out

    src_x0 = x0 - int(left)
    src_y0 = y0 - int(top)
    patch = source[src_y0:src_y0 + (y1 - y0), src_x0:src_x0 + (x1 - x0), :]
    patch = _fit_channels(patch, canvas.shape[2])

    if alpha is None:
        out[y0:y1, x0:x1, :] = patch
        return out

    a = alpha[src_y0:src_y0 + (y1 - y0), src_x0:src_x0 + (x1 - x0)]
    a = a[:, :, None]
    out[y0:y1, x0:x1, :] = patch * a + out[y0:y1, x0:x1, :] * (1.0 - a)
    return out


def compose_batch(destination, source, mask, x, y, offset_x, offset_y):
    """整批合成，返回 ``(输出帧列表, 是否完全落在画布外)``。"""
    dest = _as_frames(destination)
    src = _as_frames(source)
    if dest.shape[0] == 0 or src.shape[0] == 0:
        raise ValueError("QG_ImageComposite：目标图与源图的批次都不能为空。")

    count = max(int(dest.shape[0]), int(src.shape[0]))
    left = int(x) + int(offset_x)
    top = int(y) + int(offset_y)

    planes = _mask_planes(mask)
    src_h, src_w = int(src.shape[1]), int(src.shape[2])
    canvas_h, canvas_w = int(dest.shape[1]), int(dest.shape[2])
    outside = (left + src_w <= 0 or top + src_h <= 0
               or left >= canvas_w or top >= canvas_h)

    frames = []
    for i in range(count):
        canvas = dest[min(i, dest.shape[0] - 1)].detach().cpu().numpy().astype(np.float32)
        patch = src[min(i, src.shape[0] - 1)].detach().cpu().numpy().astype(np.float32)
        alpha = None
        if planes:
            alpha = _resize_plane(planes[min(i, len(planes) - 1)], src_h, src_w)
        frames.append(compose_frame(canvas, patch, alpha, left, top))
    return frames, outside


class QGImageComposite:
    """图像合成：源图按坐标贴到目标画布，遮罩可选。"""

    CATEGORY = "QG 工具"
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "execute"
    DESCRIPTION = (
        "Pastes the source image onto the destination canvas at "
        "(x + offset_x, y + offset_y), blended through an optional mask. "
        "Parts outside the canvas are cropped (negative coordinates work), "
        "and the shorter batch repeats its last frame."
    )
    SEARCH_ALIASES = ["图像合成", "合成", "贴图", "composite", "paste", "overlay"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "destination": ("IMAGE", {
                    "tooltip": "画布图像。它的尺寸决定输出尺寸。",
                }),
                "source": ("IMAGE", {
                    "tooltip": "贴到画布上的图像。",
                }),
                "x": ("INT", {
                    "default": 0, "min": -COORD_LIMIT, "max": COORD_LIMIT, "step": 1,
                    "tooltip": "源图左上角在画布上的横坐标（像素）。填负数就是裁掉左边。",
                }),
                "y": ("INT", {
                    "default": 0, "min": -COORD_LIMIT, "max": COORD_LIMIT, "step": 1,
                    "tooltip": "源图左上角在画布上的纵坐标（像素）。填负数就是裁掉上边。",
                }),
                "offset_x": ("INT", {
                    "default": 0, "min": -COORD_LIMIT, "max": COORD_LIMIT, "step": 1,
                    "tooltip": "加到 x 上。让上游的值来调位置，不用改 x 本身。",
                }),
                "offset_y": ("INT", {
                    "default": 0, "min": -COORD_LIMIT, "max": COORD_LIMIT, "step": 1,
                    "tooltip": "加到 y 上。让上游的值来调位置，不用改 y 本身。",
                }),
            },
            "optional": {
                "mask": ("MASK", {
                    "tooltip": "与源图尺寸一致的混合遮罩。白色留源图，黑色留画布。尺寸不同会缩放；单帧会应用到所"
                               "有帧。",
                }),
            },
        }

    def execute(self, destination, source, x=0, y=0, offset_x=0, offset_y=0, mask=None):
        frames, outside = compose_batch(destination, source, mask,
                                        x, y, offset_x, offset_y)
        if outside:
            src = _as_frames(source)
            height, width = int(frames[0].shape[0]), int(frames[0].shape[1])
            print("[QG-ImageComposite] 源图 %dx%d 放在 (%d, %d)，完全落在 %dx%d 画布外，"
                  "输出与目标相同。" % (int(src.shape[2]), int(src.shape[1]),
                                       int(x) + int(offset_x),
                                       int(y) + int(offset_y), width, height))
        result = torch.from_numpy(np.stack(frames, axis=0))
        result = result.to(device=destination.device, dtype=destination.dtype)
        return (result,)


NODE_CLASS_MAPPINGS = {"QG_ImageComposite": QGImageComposite}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_ImageComposite": "QG 图像合成"}
