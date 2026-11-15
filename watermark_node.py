"""QG_Watermark - 斜向平铺水印，任何图都能盖。

从参考实现里拆出来的：那边"身份证自动扶正拼版"一个节点带 20 个控件，其中
7 个是水印，多数场景根本不打开。拆开之后拼版节点能一眼看完，水印还能单独
盖到别的图上。

字体走的是和照片排版节点同一套发现逻辑（``models/fonts`` 优先，然后系统
字体），下拉里只列真的能读到的。
"""

from __future__ import annotations

import numpy as np
import torch
from PIL import Image

from ._watermark_helpers import tiled_watermark
from .photo_sheet_node import DEFAULT_FONT, font_choices, load_font
from .id_photo_crop_node import parse_color


def _default_font():
    """默认挑第一个真字体：PIL 的内置位图字体没有中文字形，而水印十有八九
    写的是中文。字体下拉把随包的 OFL 字体（Noto Sans SC）排在最前，所以这里
    会优先命中它，不依赖本机装没装中文字体；挑不到就退回内置位图字体。"""
    for name in font_choices():
        if name != DEFAULT_FONT:
            return name
    return DEFAULT_FONT


def _has_wide_chars(text):
    return any(ord(ch) > 127 for ch in text)


def _to_pil(frame_rgb):
    arr = np.clip(frame_rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    elif arr.shape[2] == 1:
        arr = np.repeat(arr, 3, axis=2)
    elif arr.shape[2] > 3:
        arr = arr[:, :, :3]
    return Image.fromarray(arr, "RGB")


class QGWatermark:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "text": ("STRING", {
                    "default": "仅供办理业务使用",
                    "multiline": True,
                    "tooltip": "水印文字。多行也行，会当成一段文本整体旋转。",
                }),
                "font": (font_choices(), {
                    "default": _default_font(),
                    "tooltip": "默认已指向随包的 Noto Sans SC（SIL OFL 1.1，"
                               "含中文字形）；内置位图字体只有英文字形。",
                }),
                "size": ("INT", {
                    "default": 48, "min": 6, "max": 600, "step": 1,
                    "tooltip": "字号，像素。450 dpi 的 A4 上 48 大约 2.7 mm 高。",
                }),
                "color": ("STRING", {
                    "default": "#808080",
                    "tooltip": "水印颜色。支持 #RRGGBB、gray、128,128,128。",
                }),
                "opacity": ("INT", {
                    "default": 50, "min": 1, "max": 100, "step": 1,
                    "tooltip": "不透明度，百分比。50 是常见的浅灰效果。",
                }),
                "spacing": ("INT", {
                    "default": 150, "min": 0, "max": 2000, "step": 10,
                    "tooltip": "水印单元之间的空白，像素。调小会更密。",
                }),
                "angle": ("INT", {
                    "default": 45, "min": -90, "max": 90, "step": 1,
                    "tooltip": "旋转角度。45 是斜向铺开，0 是横平竖直。",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "QG 工具"

    def execute(self, image, text, font, size, color, opacity, spacing, angle):
        color_rgb = parse_color(color, "Watermark color")

        wanted = font
        if wanted == DEFAULT_FONT and _has_wide_chars(text):
            for candidate in font_choices():
                if candidate != DEFAULT_FONT:
                    wanted = candidate
                    print("[Watermark] 内置默认字体没有中文字形，自动换成 %s" % candidate)
                    break

        face, used = load_font(wanted, int(size))
        if used == "default" and _has_wide_chars(text):
            print("[Watermark] 没找到可用的中文字体，水印里的汉字会缺字形 —— "
                  "把 ttf/ttc 丢进 ComfyUI/models/fonts/ 再选一次")

        batch = image if image.dim() == 4 else image.unsqueeze(0)
        outs = []
        for index in range(int(batch.shape[0])):
            pil = _to_pil(batch[index].cpu().numpy())
            marked = tiled_watermark(pil, str(text), face, color_rgb,
                                     int(opacity), int(spacing), int(angle))
            outs.append(np.asarray(marked).astype(np.float32) / 255.0)

        first = outs[0]
        print("[Watermark] %d 帧 | 文字 %r | 字体 %s | %d px | 角度 %d° | 不透明度 %d%%"
              % (len(outs), str(text).splitlines()[:1][0] if str(text) else "",
                 used, int(size), int(angle), int(opacity)))
        return (torch.from_numpy(np.stack(outs, axis=0)),)


NODE_CLASS_MAPPINGS = {"QG_Watermark": QGWatermark}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_Watermark": "Watermark"}
