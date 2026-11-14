"""斜向平铺水印 —— 纯函数，不碰 torch。

参考实现（孤海那条链里）用的是同一套思路：文字装进一个单元 → 旋转 →
平铺 → 裁到画布 → 合成。这里补了两处：

* 文字按真实包围盒贴到单元的左上角。PIL 的 ``textbbox`` 会带左边距/上边距，
  直接画在 (0, 0) 的话字在单元里偏右下，平铺出来是一张歪歪扭扭的网。
* 奇数行错开半格。不错开的话斜着看是一排排方阵，错开才像水印。
"""

from __future__ import annotations

from PIL import Image, ImageDraw

__all__ = ["build_unit", "tiled_watermark"]


def build_unit(text, font, color_rgb, opacity, spacing):
    """把一个词做成带透明边距的水印单元（未旋转）。"""
    alpha = int(round(max(0, min(100, opacity)) * 2.55))
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = probe.textbbox((0, 0), text, font=font)
    text_w = max(1, bbox[2] - bbox[0])
    text_h = max(1, bbox[3] - bbox[1])

    unit = Image.new("RGBA", (text_w + int(spacing), text_h + int(spacing)), (0, 0, 0, 0))
    ImageDraw.Draw(unit).text(
        (-bbox[0], -bbox[1]), text, font=font, fill=tuple(color_rgb[:3]) + (alpha,))
    return unit


def tiled_watermark(canvas_rgb, text, font, color_rgb, opacity, spacing, angle):
    """在整张图上铺斜向水印，返回 RGB。

    ``opacity`` 是 0~100，``angle`` 是度数（正数逆时针，PIL 的规矩）。
    """
    if not text or opacity <= 0:
        return canvas_rgb

    unit = build_unit(text, font, color_rgb, opacity, spacing)
    if angle:
        unit = unit.rotate(angle, expand=True, resample=Image.BICUBIC)
    step_x, step_y = unit.size
    if step_x <= 0 or step_y <= 0:
        return canvas_rgb

    cols = canvas_rgb.width // step_x + 2
    rows = canvas_rgb.height // step_y + 2
    tile = Image.new("RGBA", (cols * step_x, rows * step_y), (0, 0, 0, 0))
    for row in range(rows):
        shift = (step_x // 2) if row % 2 else 0
        for col in range(cols):
            tile.paste(unit, (col * step_x + shift, row * step_y), unit)

    tile = tile.crop((0, 0, canvas_rgb.width, canvas_rgb.height))
    merged = Image.alpha_composite(canvas_rgb.convert("RGBA"), tile)
    return merged.convert("RGB")
