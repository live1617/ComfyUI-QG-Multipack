"""QG 自定义颜色：按宽度/高度/模式生成纯色或渐变底图。

本节点是「参照功能规格的独立实现」（功能形态参考 Goohaitools「孤海 自定义
颜色」，GPL-3.0），渲染逻辑自行编写：上游逐像素画点，本实现用 numpy 向量化
并分块计算以控制内存，结果语义一致。颜色解析复用 qg_dual_color_picker
的 normalize_hex，非法色值回退各自默认色。

与上游规格保持一致的语义：
- 缩放控制渐变推进（上下渐变）或渐变半径（中心渐变），100 为标准；
- 缩放 0 时上下渐变退化为正常渐变、中心渐变全图为颜色1；
- 颗粒是三通道相同的灰度噪声，强度 = 颗粒/100 * 0.15。
差异（刻意改进）：插值系数钳制在 [0, 1]，缩放 >100 时不会溢出颜色区间。
"""

from __future__ import annotations

import numpy as np
import torch

from .qg_dual_color_picker import normalize_hex

# 模块级常量不写类型标注：开发规范 §5（AST 扫描器只收 ast.Assign）
MODE_CHOICES = ["solid", "vertical_gradient", "radial_gradient"]
DEFAULT_COLOR1 = "#364254"
DEFAULT_COLOR2 = "#4C3843"
_MAX_SIDE = 8192
_CHUNK_ROWS = 256  # 分块行数：限制 8192 宽大图的中间数组内存


def _hex_to_rgb01(hex_color):
    """#rrggbb 转 0-1 浮点三元组（输入已经过 normalize_hex）。"""
    text = hex_color.lstrip("#")
    return (
        int(text[0:2], 16) / 255.0,
        int(text[2:4], 16) / 255.0,
        int(text[4:6], 16) / 255.0,
    )


def _ratio_column(height, scale):
    """上下渐变的行插值系数：缩放乘进推进速度，缩放 0 退化为正常渐变。"""
    ratio = np.linspace(0.0, 1.0, height, dtype=np.float32)
    factor = scale / 100.0
    if factor != 0.0:
        ratio = ratio * factor
    return np.clip(ratio, 0.0, 1.0)[:, None]


def _gradient_rows(height, width, c1, c2, scale):
    """上下渐变：顶部颜色1 → 底部颜色2，按行插值（每行常量，广播成图）。"""
    ratio = _ratio_column(height, scale)
    rows = c1 + (c2 - c1) * ratio  # (H, 3)，每行一个颜色
    return np.broadcast_to(rows[:, None, :], (height, width, 3))


def _radial_ratio_block(ys, width, center_x, center_y, radius):
    """中心渐变一块行区域的插值系数（中心颜色1 → 边缘颜色2）。"""
    xs = np.arange(width, dtype=np.float32)
    dist = np.sqrt(
        (ys[:, None] - center_y) ** 2 + (xs[None, :] - center_x) ** 2)
    if radius <= 0.0:
        return np.ones(dist.shape, dtype=np.float32)
    return np.clip(dist / radius, 0.0, 1.0)


def _apply_grain(image, grain):
    """灰度颗粒噪声：三通道同值，强度 = grain/100 * 0.15，钳制 0-1。"""
    strength = grain / 100.0 * 0.15
    noise = np.random.normal(
        scale=strength, size=(image.shape[0], image.shape[1], 1)
    ).astype(np.float32)
    return np.clip(image + np.repeat(noise, 3, axis=2), 0.0, 1.0)


class QGCustomColor:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "width": ("INT", {"default": 512, "min": 1, "max": _MAX_SIDE}),
                "height": ("INT", {"default": 512, "min": 1, "max": _MAX_SIDE}),
                "mode": (MODE_CHOICES, {"default": "solid"}),
                "color1": ("STRING", {"default": DEFAULT_COLOR1}),
                "color2": ("STRING", {"default": DEFAULT_COLOR2}),
                "scale": ("INT", {"default": 100, "min": 0, "max": 300, "step": 1}),
                "grain": ("INT", {"default": 0, "min": 0, "max": 100, "step": 1}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "render"
    CATEGORY = "QG 工具"
    DESCRIPTION = (
        "Render a solid or gradient background image from two hex colours, "
        "with scale controlling gradient progress/radius and grain adding "
        "monochrome noise."
    )

    def render(self, width, height, mode, color1, color2, scale, grain):
        if mode not in MODE_CHOICES:
            mode = MODE_CHOICES[0]
        width = max(1, min(int(width), _MAX_SIDE))
        height = max(1, min(int(height), _MAX_SIDE))
        c1 = np.array(_hex_to_rgb01(
            normalize_hex(color1, DEFAULT_COLOR1)), dtype=np.float32)
        c2 = np.array(_hex_to_rgb01(
            normalize_hex(color2, DEFAULT_COLOR2)), dtype=np.float32)

        if mode == "solid":
            image = np.ones((height, width, 3), dtype=np.float32) * c1
        elif mode == "vertical_gradient":
            image = _gradient_rows(height, width, c1, c2, scale)
        else:  # radial_gradient：中心颜色1 → 边缘颜色2
            max_radius = ((width ** 2 + height ** 2) ** 0.5) / 2.0
            radius = max_radius * (scale / 100.0)
            center_x, center_y = width // 2, height // 2
            image = np.empty((height, width, 3), dtype=np.float32)
            for start in range(0, height, _CHUNK_ROWS):
                end = min(start + _CHUNK_ROWS, height)
                ys = np.arange(start, end, dtype=np.float32)
                ratio = _radial_ratio_block(
                    ys, width, center_x, center_y, radius)[:, :, None]
                image[start:end] = \
                    c2[None, None, :] + (c1 - c2)[None, None, :] * ratio

        if grain > 0:
            image = _apply_grain(image, grain)

        tensor = torch.from_numpy(np.clip(image, 0.0, 1.0))[None,]
        return (tensor,)


NODE_CLASS_MAPPINGS = {"QG_CustomColor": QGCustomColor}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_CustomColor": "QG 自定义颜色"}
