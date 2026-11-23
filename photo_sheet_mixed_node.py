"""QG Photo Sheet Mixed - A5 ID-photo layouts, including two-size mixes.

The functional spec follows Goohaitools' ``孤海-证件照排版（A5定制）``: thirteen
fixed A5 layouts, six of them single-size grids and seven mixing two sizes
(some with rotated photos, one on portrait A5, two with zero gutter).

This is an independent, declarative implementation. Upstream has one ~700-line
branch per layout, each repeating the same centring / paste arithmetic; here
all thirteen are rows of *bands* containing *regions* described by data, and
one engine places them. Layout geometry is pure integer arithmetic in
``layout_plan`` so it can be asserted without rendering.

Differences that fix real problems upstream:

* **Batches keep every frame.** Upstream reads ``image[0]`` only.
* **The border is drawn *inside* the photo.** Upstream uses
  ``ImageOps.expand``, which makes each photo bigger than the grid cell it
  computed, so a border silently overlaps the neighbour or runs off the sheet.
* **An oversized layout is scaled to fit** (or fails loudly when disabled)
  instead of being clipped by ``paste`` without a word.
* Colour parsing accepts ``#RGB`` / ``#RRGGBB`` / colour names. Upstream
  slices ``#`` strings by fixed offsets, so a short hex raises.
* ``layout`` combo values are stable ASCII keys; Chinese names are display-only.
* Caption font size is in pixels and 0 turns the caption off; a missing font
  falls back with a log line instead of an exception swallowed silently.

Units: paper / sizes / spacing / top offset are centimetres; border and font
size are pixels. DPI turns centimetres into sheet pixels.
"""

from __future__ import annotations

import os

import numpy as np
import torch
from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps

# Physical photo sizes in centimetres (width, height).
SIZES_CM = {
    "小1寸": (2.2, 3.2),
    "标准1寸": (2.5, 3.5),
    "大1寸": (3.3, 4.8),
    "小2寸": (3.5, 4.5),
    "标准2寸": (3.5, 5.0),
    "2寸": (3.5, 5.0),          # 上游「标准2寸」的别名
    "大2寸": (3.5, 5.3),
    "22x32": (2.2, 3.2),
    "31x46": (3.1, 4.6),
    "24x34": (2.4, 3.4),
    "34x49": (3.4, 4.9),
}

# 随包的开放许可字体（SIL OFL 1.1）。与 photo_sheet_node.BUNDLED_FONTS_DIR
# 指向同一目录；tests/test_bundled_fonts.py 会断言两者行为一致。
# 这里不 import 单尺寸排版节点：本模块的对照测试用 spec_from_file_location
# 单文件加载，包内相对导入在那个上下文里会失败。
BUNDLED_FONTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
WINDOWS_FONTS = r"C:\Windows\Fonts"

_A5_LANDSCAPE = (21.0, 14.8)
_A5_PORTRAIT = (14.8, 21.0)


def _font_dirs():
    """内置 OFL 字体 > 用户 models/fonts > 系统字体。"""
    dirs = [BUNDLED_FONTS_DIR]
    try:
        import folder_paths
        dirs.append(os.path.join(folder_paths.models_dir, "fonts"))
    except Exception:                                     # noqa: BLE001
        pass
    dirs.append(WINDOWS_FONTS)
    return dirs


def font_choices():
    """下拉候选：只列各目录里真实存在的字体文件。"""
    names = ["<default>"]
    for directory in _font_dirs():
        if not os.path.isdir(directory):
            continue
        try:
            for entry in sorted(os.listdir(directory)):
                if entry.lower().endswith((".ttf", ".otf", ".ttc")) and entry not in names:
                    names.append(entry)
        except OSError:
            pass
    return names


def load_font(name, size):
    """载入字体；可变字体固定到 Regular 实例，否则中文标注会细到看不见。"""
    if name and name != "<default>":
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
        print("[QG Photo Sheet Mixed] font %r unavailable, using the "
              "built-in default (Chinese captions may show as boxes)" % name)
    return ImageFont.load_default()


def _region(size, cols, rows, rotate=False):
    """One rectangular grid of identical photos inside a band."""
    return {"size": size, "cols": int(cols), "rows": int(rows),
            "rotate": bool(rotate)}


def _layout(key, zh, bands, spacing_cm=0.4, paper=_A5_LANDSCAPE,
            top_cm=None):
    return {"key": key, "zh": zh, "bands": bands,
            "spacing_cm": spacing_cm, "paper": paper, "top_cm": top_cm}


LAYOUTS = [
    # --- six single-size grids, A5 landscape, 0.4 cm gutter ---
    _layout("small1_14", "小1寸 14张", [[_region("小1寸", 7, 2)]]),
    _layout("standard1_12", "标准1寸 12张", [[_region("标准1寸", 6, 2)]]),
    _layout("large1_8", "大1寸 8张", [[_region("大1寸", 4, 2)]]),
    _layout("small2_8", "小2寸 8张", [[_region("小2寸", 4, 2)]]),
    _layout("standard2_8", "标准2寸 8张", [[_region("标准2寸", 4, 2)]]),
    _layout("large2_8", "大2寸 8张", [[_region("大2寸", 4, 2)]]),

    # --- two-size mixes, side by side ---
    _layout("mix_small1_9_small2_4", "小1寸 9张 + 小2寸 4张",
            [[_region("小1寸", 3, 3), _region("小2寸", 2, 2)]]),
    _layout("mix_1_8_small2_4", "1寸 8张 + 小2寸 4张",
            [[_region("标准1寸", 2, 4, rotate=True), _region("小2寸", 2, 2)]]),
    _layout("mix_1_8_2_4", "1寸 8张 + 2寸 4张",
            [[_region("标准1寸", 2, 4, rotate=True), _region("标准2寸", 2, 2)]]),

    # --- portrait A5, four stacked bands, starts 2 cm from the top ---
    _layout("mix_22x32_8_31x46_4", "22x32 8张 + 31x46 4张",
            [[_region("22x32", 4, 1)], [_region("22x32", 4, 1)],
             [_region("31x46", 2, 1, rotate=True)],
             [_region("31x46", 2, 1, rotate=True)]],
            spacing_cm=0.3, paper=_A5_PORTRAIT, top_cm=2.0),

    _layout("mix_1_8_large1_4", "1寸 8张 + 大1寸 4张",
            [[_region("标准1寸", 2, 4, rotate=True), _region("大1寸", 2, 2)]],
            spacing_cm=0.35),
    _layout("mix_24x34_33x48_nogap", "2.4 x 3.4 + 3.3 x 4.8 无间距",
            [[_region("24x34", 2, 4, rotate=True), _region("大1寸", 2, 2)]],
            spacing_cm=0.0),

    # --- single size, no gutter ---
    _layout("plain_34x49_nogap", "3.4 x 4.9 无间距",
            [[_region("34x49", 4, 2)]], spacing_cm=0.0),
]

LAYOUT_BY_KEY = {item["key"]: item for item in LAYOUTS}
LAYOUT_KEYS = [item["key"] for item in LAYOUTS]
LAYOUT_LABELS = {item["key"]: item["zh"] for item in LAYOUTS}


def total_photos(layout):
    """Number of photo copies on one sheet."""
    return sum(reg["cols"] * reg["rows"]
               for band in layout["bands"] for reg in band)


def cm_to_px(cm, dpi):
    """Centimetres to sheet pixels, rounded (upstream truncates and drifts)."""
    return int(round(float(cm) * float(dpi) / 2.54))


def _geometry(layout, dpi, scale=1.0):
    """Compute every photo rectangle. Pure integer arithmetic, no PIL."""
    paper_w, paper_h = layout["paper"]
    canvas_w, canvas_h = cm_to_px(paper_w, dpi), cm_to_px(paper_h, dpi)
    sp = int(round(cm_to_px(layout["spacing_cm"], dpi) * scale)) if layout["spacing_cm"] else 0

    regions = []
    band_sizes = []
    for band in layout["bands"]:
        placed = []
        band_w = 0
        band_h = 0
        for reg in band:
            w_cm, h_cm = SIZES_CM[reg["size"]]
            src_w = max(1, int(round(cm_to_px(w_cm, dpi) * scale)))
            src_h = max(1, int(round(cm_to_px(h_cm, dpi) * scale)))
            pw, ph = (src_h, src_w) if reg["rotate"] else (src_w, src_h)
            rw = reg["cols"] * pw + (reg["cols"] - 1) * sp
            rh = reg["rows"] * ph + (reg["rows"] - 1) * sp
            placed.append({"size": reg["size"], "cols": reg["cols"],
                           "rows": reg["rows"], "rotate": reg["rotate"],
                           "src_w": src_w, "src_h": src_h,
                           "photo_w": pw, "photo_h": ph,
                           "w": rw, "h": rh})
            band_w += rw
            band_h = max(band_h, rh)
        band_w += sp * (len(placed) - 1)
        band_sizes.append((band_w, band_h))
        regions.append(placed)

    total_w = max(w for w, _h in band_sizes)
    total_h = sum(h for _w, h in band_sizes) + sp * (len(band_sizes) - 1)
    return {"canvas_w": canvas_w, "canvas_h": canvas_h, "sp": sp,
            "regions": regions, "band_sizes": band_sizes,
            "total_w": total_w, "total_h": total_h}


def layout_plan(layout_key, dpi, fit_to_paper=True):
    """Place all cells; returns a plain dict (testable without rendering).

    When ``fit_to_paper`` is on and the layout does not fit, every photo and
    gutter is scaled down together (geometry stays proportional). With it off,
    an oversized layout raises instead of being silently clipped.
    """
    layout = LAYOUT_BY_KEY[layout_key]
    dpi = int(dpi)
    if dpi < 1:
        raise ValueError("dpi must be >= 1")

    geo = _geometry(layout, dpi)
    avail_w = geo["canvas_w"]
    avail_h = geo["canvas_h"] - (cm_to_px(layout["top_cm"], dpi)
                                 if layout["top_cm"] is not None else 0)
    overflow_w = geo["total_w"] > avail_w
    overflow_h = geo["total_h"] > avail_h
    scale = 1.0
    if (overflow_w or overflow_h) and fit_to_paper:
        scale = min(avail_w / geo["total_w"], avail_h / geo["total_h"], 1.0)
        # Rounding every photo individually can add back a pixel or two on a
        # long grid, so shrink in small steps until the recomputed geometry
        # really fits rather than trusting the floating-point ratio.
        for _attempt in range(8):
            geo = _geometry(layout, dpi, scale)
            if geo["total_w"] <= avail_w and geo["total_h"] <= avail_h:
                break
            scale *= 0.98
    elif overflow_w or overflow_h:
        raise ValueError(
            "「%s」版式放不进相纸：需要 %dx%d 像素，可用 %dx%d 像素（%d dpi）。"
            "把 dpi 调低，或打开「自动适应相纸」。"
            % (layout_key, geo["total_w"], geo["total_h"],
               avail_w, avail_h, dpi))

    start_x = (geo["canvas_w"] - geo["total_w"]) // 2
    if layout["top_cm"] is not None:
        start_y = cm_to_px(layout["top_cm"], dpi)
    else:
        start_y = (geo["canvas_h"] - geo["total_h"]) // 2

    cells = []
    band_y = start_y
    for band_index, (placed, (band_w, band_h)) in enumerate(
            zip(geo["regions"], geo["band_sizes"])):
        band_x = start_x + (geo["total_w"] - band_w) // 2
        region_x = band_x
        for region_index, reg in enumerate(placed):
            for row in range(reg["rows"]):
                for col in range(reg["cols"]):
                    cells.append({
                        "x": region_x + col * (reg["photo_w"] + geo["sp"]),
                        "y": band_y + row * (reg["photo_h"] + geo["sp"]),
                        "w": reg["photo_w"], "h": reg["photo_h"],
                        "band": band_index, "region": region_index,
                        "size": reg["size"], "rotate": reg["rotate"],
                        "src_w": reg["src_w"], "src_h": reg["src_h"],
                    })
            region_x += reg["w"] + geo["sp"]
        band_y += band_h + geo["sp"]

    # Flat index of each region, so rendering can cache one crop per region.
    offsets, running = [], 0
    for band in geo["regions"]:
        offsets.append(running)
        running += len(band)

    return {"layout": layout_key, "name": layout["zh"], "dpi": dpi,
            "scale": scale, "canvas_w": geo["canvas_w"],
            "canvas_h": geo["canvas_h"], "spacing": geo["sp"],
            "start_x": start_x, "start_y": start_y,
            "total_w": geo["total_w"], "total_h": geo["total_h"],
            "regions": geo["regions"], "cells": cells,
            "region_offsets": offsets}


def parse_color(value):
    """``#RGB`` / ``#RRGGBB`` / a PIL colour name -> (r, g, b)."""
    try:
        rgb = ImageColor.getrgb(str(value or "").strip())
        return tuple(rgb[:3])
    except (ValueError, TypeError):
        return (0, 0, 0)


def _to_pil(frame):
    array = (frame.detach().cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
    if array.ndim == 2:
        return Image.fromarray(array, "L").convert("RGB")
    if array.ndim != 3:
        return Image.fromarray(array).convert("RGB")
    # 4 通道不能直接切前 3 个：透明区域的 RGB 通常是 0，切出来就是黑底。
    # 先按 alpha 合成到白底，与「拼到白纸上」的语义一致。
    if array.shape[2] >= 4:
        rgba = Image.fromarray(array[..., :4], "RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, (0, 0), rgba)
        return flat
    if array.shape[2] == 2:
        return Image.fromarray(array, "LA").convert("RGB")
    return Image.fromarray(array[..., :3], "RGB").copy()


def _to_tensor(image):
    return torch.from_numpy(
        np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0)


def render_sheet(photo, plan, border_px=0, border_color="#000000",
                 caption="", font="<default>", font_size=0):
    """Draw one sheet. ``photo`` is a PIL image; ``plan`` comes from layout_plan.

    One prepared photo per region: every cell in a region is the same crop,
    so a 14-copy sheet only resizes the source once instead of fourteen times.
    """
    canvas = Image.new("RGB", (plan["canvas_w"], plan["canvas_h"]), "white")
    colour = parse_color(border_color)
    border_px = max(0, int(border_px))

    prepared = {}
    offset = 0
    for band in plan["regions"]:
        for local_index, region in enumerate(band):
            crop = ImageOps.fit(photo.convert("RGB"),
                                (region["src_w"], region["src_h"]),
                                method=Image.Resampling.LANCZOS)
            if region["rotate"]:
                crop = crop.rotate(90, expand=True)
            if border_px:
                draw = ImageDraw.Draw(crop)
                draw.rectangle([0, 0, crop.width - 1, crop.height - 1],
                               outline=colour,
                               width=min(border_px, crop.width // 2))
            prepared[offset + local_index] = crop
        offset += len(band)

    for cell in plan["cells"]:
        index = plan["region_offsets"][cell["band"]] + cell["region"]
        canvas.paste(prepared[index], (cell["x"], cell["y"]))

    if int(font_size) > 0:
        face = load_font(font, int(font_size))
        draw = ImageDraw.Draw(canvas)
        text = "%s | %s" % (caption, plan["name"]) if caption else plan["name"]
        box = draw.textbbox((0, 0), text, font=face)
        text_w = box[2] - box[0]
        text_x = max(0, (plan["canvas_w"] - text_w) // 2)
        text_y = min(plan["canvas_h"] - (box[3] - box[1]) - 1,
                     plan["start_y"] + plan["total_h"]
                     + cm_to_px(0.5, plan["dpi"]))
        draw.text((text_x, text_y), text, font=face, fill=(0, 0, 0))
    return canvas


class QGPhotoSheetMixed:

    CATEGORY = "QG 工具"
    DESCRIPTION = (
        "Lay one ID photo out on an A5 sheet using one of thirteen fixed "
        "layouts: six single-size grids, six two-size mixes (some with "
        "rotated photos, one on portrait A5) and one zero-gutter grid. "
        "Paper sizes, photo sizes, gutter and top offset are centimetres; "
        "border and caption font size are pixels. DPI turns centimetres into "
        "sheet pixels. Every frame of a batch gets its own sheet, the border "
        "is drawn inside the photo so it cannot overlap its neighbour, and "
        "an oversized layout is scaled to fit (or fails with the numbers "
        "when fit_to_paper is off). Outputs the sheet, the Chinese layout "
        "name and the number of copies. Layout combo values are stable ASCII "
        "keys; the Chinese name is display-only."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {
                    "tooltip": "一张证件照。批量输入每帧各出一版，照片按每格的比例居中裁切。",
                }),
                "layout": (LAYOUT_KEYS, {
                    "default": "mix_1_8_2_4",
                    "tooltip": "十三种 A5 版式之一。存的是固定的英文键，中文名只用来显示。",
                }),
                "dpi": ("INT", {
                    "default": 300, "min": 72, "max": 3000, "step": 1,
                    "tooltip": "打印分辨率：厘米 × DPI 得到版面像素。照片冲印通用 300 dpi。",
                }),
                "border_px": ("INT", {
                    "default": 1, "min": 0, "max": 50, "step": 1,
                    "tooltip": "每张照片外圈的边框，单位像素，画在照片内侧，不影响格子位置。",
                }),
                "border_color": ("STRING", {
                    "default": "#000000",
                    "tooltip": "边框颜色：支持 #RGB、#RRGGBB 或颜色名。填错按黑色处理。",
                }),
                "caption": ("STRING", {
                    "default": "", "multiline": False,
                    "tooltip": "可选：印在版面下方的文字，后面会自动接上版式名。留空就不印，除非设了字号。",
                }),
                "font": (font_choices(), {
                    "default": "<default>",
                    "tooltip": "文字字体。随包的 OFL 字体 NotoSansSC-VF.ttf 排在最前，能"
                               "显示中文；内置点阵字体不行。",
                }),
                "font_size": ("INT", {
                    "default": 0, "min": 0, "max": 200, "step": 1,
                    "tooltip": "文字大小（像素）。0 关闭文字。",
                }),
                "fit_to_paper": ("BOOLEAN", {
                    "default": True,
                    "label_on": "Shrink to Fit", "label_off": "Error Out",
                    "tooltip": "版面放不下时整体等比缩小。关掉就直接报错并给出像素数字，而不是悄悄裁掉。",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "INT")
    RETURN_NAMES = ("sheet", "layout_name", "total")
    FUNCTION = "execute"
    OUTPUT_TOOLTIPS = (
        "每输入一帧出一张 A5 版，尺寸 = 纸型 × dpi。",
        "所选版式的中文名（只用于显示）。",
        "一版上的照片份数。",
    )

    def execute(self, image, layout, dpi, border_px, border_color,
                caption, font, font_size, fit_to_paper=True):
        plan = layout_plan(layout, dpi, bool(fit_to_paper))
        batch = image if image.dim() == 4 else image.unsqueeze(0)
        if int(batch.shape[0]) == 0:
            # 0 帧时 first_size 一直是 None，日志那行 first_size[0] 直接
            # TypeError；torch.stack([]) 也会抛。按本包约定给中文错误。
            raise ValueError(
                "QG 照片拼版（混合版式）：没有收到任何图像帧（输入 batch 为 0 帧）。"
                "检查上游是否把照片全部过滤掉了。")
        sheets = []
        first_size = None
        for index in range(int(batch.shape[0])):
            photo = _to_pil(batch[index])
            if first_size is None:
                first_size = (photo.width, photo.height)
            sheets.append(_to_tensor(render_sheet(
                photo, plan, int(border_px), border_color,
                caption, font, int(font_size))))
        print("[QG Photo Sheet Mixed] %s: %dx%d photo -> %d copies on a "
              "%dx%d px sheet x%d frame(s) (dpi=%d, gutter=%d px, scale=%.3f)"
              % (plan["name"], first_size[0], first_size[1],
                 total_photos(LAYOUT_BY_KEY[layout]),
                 plan["canvas_w"], plan["canvas_h"], int(batch.shape[0]),
                 plan["dpi"], plan["spacing"], plan["scale"]))
        return (torch.stack(sheets), plan["name"],
                total_photos(LAYOUT_BY_KEY[layout]))


NODE_CLASS_MAPPINGS = {"QG_PhotoSheetMixed": QGPhotoSheetMixed}
NODE_DISPLAY_NAME_MAPPINGS = {
    "QG_PhotoSheetMixed": "QG 证件照混合排版（A5）"
}
