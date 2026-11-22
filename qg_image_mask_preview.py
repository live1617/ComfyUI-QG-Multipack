# -*- coding: utf-8 -*-
"""QG 图像与遮罩预览 —— 在图像上叠加遮罩颜色与序号，输出预览图。

参考 Goohaitools「图像与遮罩预览」（GPL-3.0）的控件语义独立实现，未复制上游
源码。与上游的关键差别：

* **不依赖上游的 GHCOLOR socket**：两个颜色输入是本包惯用的 ``STRING``（十
  六进制色值），前端接 ``qg_color_picker.js`` 的色块 + 色板；工作流存的是可读
  字符串，上游的 ``GHCOLOR`` 无法与别的插件互通。
* **字体走本包发现逻辑**：内置 OFL 中文字体 > ``models/fonts`` > 系统字体，
  下拉只列真实存在的字体文件；上游只读它自己插件目录下的专有字体。
* **零相对导入**：字体/颜色工具内联，单文件可被测试直接加载，也可被 ComfyUI
  作为包模块导入。

控件语义（对齐上游，逐项自写）：
    * mask_opacity（遮罩不透明）：遮罩区域叠加颜色的强度，0~1。
    * mask_color（遮罩颜色）：叠加到遮罩区域的十六进制色值。
    * show_index（显示序号）：是否在每帧遮罩中心画序号（从 1 数起）。
    * index_opacity（序号不透明）：序号文字的 alpha，0~1。
    * index_scale（序号缩放）：跟随遮罩缩放=字号按各自遮罩高度×比例；
      固定大小=所有遮罩取最大高度×比例，序号一样大。
    * index_ratio（序号比例）：字号相对遮罩高度的倍数。
    * index_font（序号字体）：字体下拉，缺省用随包 OFL 中文字体。
    * index_color（序号颜色）：序号文字的十六进制色值。

遮罩批次约定：``[B,H,W]`` 每帧当一个独立对象，各自上色、各自编号；2D 单张
按一帧处理。尺寸与图像不一致时最近邻缩放到图像尺寸。
"""
from __future__ import annotations

import os

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

_MAX_RESOLUTION = 16384
_BANNED_FONT = "<default>"
DEFAULT_MASK_COLOR = "#c524ff"
DEFAULT_INDEX_COLOR = "#ffffff"

_BUNDLED_FONTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
_WINDOWS_FONTS = r"C:\Windows\Fonts"


def _font_dirs():
    """内置 OFL 字体 > 用户 models/fonts > 系统字体。"""
    dirs = [_BUNDLED_FONTS_DIR]
    try:
        import folder_paths

        dirs.append(os.path.join(folder_paths.models_dir, "fonts"))
    except Exception:                                     # noqa: BLE001
        pass
    dirs.append(_WINDOWS_FONTS)
    return dirs


def font_choices():
    """字体下拉候选：随包 OFL 字体优先，其后是用户与系统字体。"""
    names = [_BANNED_FONT]
    for directory in _font_dirs():
        if not os.path.isdir(directory):
            continue
        try:
            for entry in sorted(os.listdir(directory)):
                if (entry.lower().endswith((".ttf", ".otf", ".ttc"))
                        and entry not in names):
                    names.append(entry)
        except OSError:
            pass
    return names


def default_font():
    """默认字体：优先随包 OFL 中文字体，否则 PIL 内置字体。"""
    bundled = os.path.join(_BUNDLED_FONTS_DIR, "NotoSansSC-VF.ttf")
    if os.path.isfile(bundled):
        return "NotoSansSC-VF.ttf"
    return _BANNED_FONT


def load_font(name, size):
    """加载字体；可变字体固定 Regular 实例，失败回退 PIL 默认字体。"""
    if name and name != _BANNED_FONT:
        for directory in _font_dirs():
            path = os.path.join(directory, os.path.basename(name))
            if not os.path.isfile(path):
                continue
            try:
                face = ImageFont.truetype(path, max(1, int(size)))
                if hasattr(face, "set_variation_by_name"):
                    try:
                        face.set_variation_by_name("Regular")
                    except (OSError, ValueError, AttributeError, TypeError):
                        pass
                return face
            except OSError:
                pass
    return ImageFont.load_default()


def parse_color(value, fallback):
    """把 #rgb / #rrggbb / #rrggbbaa 解析成 0-255 三元组，非法回退 fallback。"""
    text = str(value if value is not None else "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    elif len(text) == 8:
        # 8 位是 #RRGGBBAA：本控件的透明度由单独的滑杆控制，这里只取 RGB。
        text = text[:6]
    if len(text) == 6:
        try:
            return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    text2 = str(fallback).strip().lstrip("#")
    return tuple(int(text2[i:i + 2], 16) for i in (0, 2, 4))


def _to_numpy(value):
    """任意输入转 float32 numpy，先 nan_to_num 再 clip（NaN 不能漏到 uint8）。"""
    if isinstance(value, torch.Tensor):
        arr = value.detach().cpu().numpy()
    else:
        arr = np.asarray(value)
    arr = np.asarray(arr, dtype=np.float32)
    arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=0.0)
    return np.clip(arr, 0.0, 1.0)


def _image_frame(image):
    """取图像第一帧转成 [H,W,3] uint8；RGBA 透明部分压黑。"""
    arr = _to_numpy(image)
    if arr.ndim == 4:
        arr = arr[0]
    if arr.ndim != 3:
        raise ValueError(
            "QG 图像与遮罩预览：图像需为 [H,W,C] 或 [B,H,W,C]，收到 %d 维。" % arr.ndim)
    if arr.shape[2] == 4:
        alpha = arr[:, :, 3:4]
        arr = arr[:, :, :3] * alpha
    elif arr.shape[2] == 1:
        arr = np.repeat(arr, 3, axis=2)
    elif arr.shape[2] < 3:
        raise ValueError("QG 图像与遮罩预览：图像通道数不足。")
    return (np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)


def _mask_frames(mask):
    """遮罩规整成 [B,H,W] 的二值浮点数组。

    ComfyUI 的 MASK 契约就是 [B,H,W]，三维输入一律按批次处理。不再猜测
    「最后一维为 1 就当单帧 [H,W,1]」：那个判断与 [B,H,1] 在数据上不可区分，
    会把一个批次压成一帧（[B,H,1] → [1,B,H]），帧数与尺寸全错。非规范的
    [H,W,1] 单帧会被当成 B=H 的批次，属于上游格式问题，不在这里猜。
    """
    arr = _to_numpy(mask)
    if arr.ndim == 2:
        arr = arr[None, :, :]
    elif arr.ndim != 3:
        raise ValueError(
            "QG 图像与遮罩预览：遮罩需为 [H,W] 或 [B,H,W]，收到 %d 维。" % arr.ndim)
    return (arr > 0.5).astype(np.float32)


def _fit_mask(plane, width, height):
    """把单帧 [H,W] 遮罩最近邻缩放到图像尺寸。"""
    if plane.ndim != 2:
        raise ValueError(
            "QG 图像与遮罩预览：单帧遮罩应为 [H,W]，收到 %d 维。" % plane.ndim)
    if plane.shape[0] == height and plane.shape[1] == width:
        return plane
    img = Image.fromarray((plane * 255.0).astype(np.uint8), mode="L")
    img = img.resize((width, height), Image.NEAREST)
    return np.asarray(img, dtype=np.float32) / 255.0


def _bbox_center(plane):
    """二值遮罩的外接框中心与高度；空遮罩返回 None。"""
    rows = np.any(plane > 0.5, axis=1)
    cols = np.any(plane > 0.5, axis=0)
    if not np.any(rows) or not np.any(cols):
        return None
    r0, r1 = np.where(rows)[0][[0, -1]]
    c0, c1 = np.where(cols)[0][[0, -1]]
    return ((int(c0) + int(c1)) // 2, (int(r0) + int(r1)) // 2,
            int(r1) - int(r0))


def render_preview(image, mask, mask_opacity=0.4, mask_color=DEFAULT_MASK_COLOR,
                   show_index=True, index_opacity=0.8, index_scale="跟随遮罩缩放",
                   index_ratio=0.15, index_font=None, index_color=DEFAULT_INDEX_COLOR):
    """把遮罩颜色与序号叠加到图像，返回 [1,H,W,3] float tensor。"""
    rgb = _image_frame(image)
    height, width = rgb.shape[:2]
    frames = _mask_frames(mask)

    # 画布用 RGBA，便于逐帧 alpha 合成。
    canvas = Image.fromarray(rgb, mode="RGB").convert("RGBA")
    mask_rgb = parse_color(mask_color, DEFAULT_MASK_COLOR)
    opacity = float(np.clip(mask_opacity, 0.0, 1.0))

    fitted = []
    for i in range(frames.shape[0]):
        plane = _fit_mask(frames[i], width, height)
        fitted.append(plane)
        alpha = (plane * opacity * 255.0).astype(np.uint8)
        layer = Image.new("RGBA", (width, height), (*mask_rgb, 0))
        layer.putalpha(Image.fromarray(alpha, mode="L"))
        canvas = Image.alpha_composite(canvas, layer)

    if show_index:
        number_rgb = parse_color(index_color, DEFAULT_INDEX_COLOR)
        number_alpha = int(round(float(np.clip(index_opacity, 0.0, 1.0)) * 255.0))
        infos = [(i + 1, _bbox_center(plane)) for i, plane in enumerate(fitted)]
        infos = [(idx, info) for idx, info in infos if info is not None]
        fixed_mode = str(index_scale).strip() == "固定大小"
        max_height = max((info[2] for _, info in infos), default=0)
        font_name = index_font if index_font else default_font()

        for idx, (cx, cy, mask_height) in infos:
            base = max_height if fixed_mode else mask_height
            size = max(1, int(round(base * float(index_ratio))))
            font = load_font(font_name, size)
            text = str(idx)
            text_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(text_layer)
            try:
                box = draw.textbbox((0, 0), text, font=font)
                tw, th = box[2] - box[0], box[3] - box[1]
            except AttributeError:                        # 旧版 PIL
                tw, th = draw.textsize(text, font=font)
            draw.text((cx - tw // 2, cy - th // 2), text,
                      fill=(*number_rgb, number_alpha), font=font)
            canvas = Image.alpha_composite(canvas, text_layer)

    out = np.asarray(canvas.convert("RGB"), dtype=np.float32) / 255.0
    return (torch.from_numpy(np.ascontiguousarray(out)).unsqueeze(0),)


class QGImageMaskPreview:
    """图像 + 遮罩预览：遮罩区域上色，可选按帧绘制序号。"""

    CATEGORY = "QG 工具"
    FUNCTION = "preview"

    @classmethod
    def INPUT_TYPES(cls):
        fonts = font_choices()
        return {
            "required": {
                "image": ("IMAGE", {
                    "tooltip": "输入图像，取第一帧；支持 RGB/RGBA。",
                }),
                "mask": ("MASK", {
                    "tooltip": "输入遮罩，[H,W] 单张或 [B,H,W] 批次；每帧当一个对象分别上色与编号。",
                }),
                "mask_opacity": ("FLOAT", {
                    "default": 0.4, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "遮罩不透明：遮罩区域叠加颜色的强度，0 不叠加、1 完全盖住。",
                }),
                "mask_color": ("STRING", {
                    "default": DEFAULT_MASK_COLOR,
                    "tooltip": "遮罩颜色：叠加到遮罩区域的色值，点色块取色或手填 #RRGGBB。",
                }),
                "show_index": ("BOOLEAN", {
                    "default": True, "label_on": "显示", "label_off": "隐藏",
                    "tooltip": "显示序号：在每个遮罩中心画序号，从 1 数起。",
                }),
                "index_opacity": ("FLOAT", {
                    "default": 0.8, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "序号不透明：序号文字的透明度，0 全透明、1 完全不透明。",
                }),
                "index_scale": (["跟随遮罩缩放", "固定大小"], {
                    "default": "跟随遮罩缩放",
                    "tooltip": "序号缩放：跟随遮罩缩放按各自遮罩高度定字号；固定大小按最大遮罩高度统一定字号。",
                }),
                "index_ratio": ("FLOAT", {
                    "default": 0.15, "min": 0.05, "max": 3.0, "step": 0.05,
                    "tooltip": "序号比例：字号 = 遮罩高度 × 该比例。0.5 时字号约半身高，"
                               "多人密集场景会互相压盖，建议 0.1~0.2。",
                }),
                "index_font": (fonts, {
                    "default": default_font() if default_font() in fonts else _BANNED_FONT,
                    "tooltip": "序号字体：随包 OFL 中文字体优先，其后是 models/fonts 与系统字体。",
                }),
                "index_color": ("STRING", {
                    "default": DEFAULT_INDEX_COLOR,
                    "tooltip": "序号颜色：序号文字的色值，点色块取色或手填 #RRGGBB。",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    OUTPUT_TOOLTIPS = ("叠加了遮罩颜色与序号的预览图，可直接接预览节点查看。",)
    DESCRIPTION = (
        "Overlays mask regions with a chosen color and optional sequence numbers "
        "on an image. Mask batch frames are treated as separate objects. "
        "Independent implementation; colors are plain hex strings, not GHCOLOR."
    )
    SEARCH_ALIASES = ["遮罩预览", "图像遮罩预览", "Mask 预览", "遮罩可视化"]

    def preview(self, image, mask, mask_opacity, mask_color, show_index,
                index_opacity, index_scale, index_ratio, index_font, index_color):
        return render_preview(
            image, mask,
            mask_opacity=mask_opacity, mask_color=mask_color,
            show_index=show_index, index_opacity=index_opacity,
            index_scale=index_scale, index_ratio=index_ratio,
            index_font=index_font, index_color=index_color,
        )


NODE_CLASS_MAPPINGS = {"QG_ImageMaskPreview": QGImageMaskPreview}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_ImageMaskPreview": "QG 图像与遮罩预览"}
