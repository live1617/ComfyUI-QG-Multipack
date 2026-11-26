"""Photo Sheet - tile one photo across a print-sized sheet.

The reference implementation is ``孤海-单尺寸排版`` from Goohaitools. It lays
out the grid correctly; the problems are around the edges:

* **When nothing fits it prints a blank sheet.** Its column count is
  ``max(1, floor(...))``, so an oversized photo becomes a 1x1 grid, then the
  per-photo bounds check silently rejects it. The result is a white sheet and
  a green run - the reason is invisible.
* **Units are mixed.** Paper, margin and spacing are centimetres; border and
  font size are pixels; nothing in the UI says which is which.
* **A batch loses all but the first frame** (``tensor[0]``).
* **A missing font falls back silently** to PIL's bitmap default, which has no
  Chinese glyphs, so the caption turns into boxes.
* **A caption wider than the sheet is dropped**, again with no word.

Here: ``_cm`` and ``_px`` are spelled out in the parameter names, a photo too
large for the sheet is scaled down to fit instead of killing the run (and the
log says by how much), every frame of a batch gets its own sheet, and both font
and caption fallbacks say what they did.

Layout is pure integer arithmetic in ``_sheet_helpers`` so it can be asserted
offline; this module only draws.
"""

from __future__ import annotations

import os
from functools import lru_cache

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont, ImageOps

from ._sheet_helpers import cm_to_px, plan_sheet, shrink_to_fit, usable_area

DEFAULT_FONT = "<default>"

# 随包的开放许可字体（SIL OFL 1.1，许可全文见 assets/fonts/OFL.txt）。
# 优先级高于用户字体与系统字体：中文标注因此开箱即用，不依赖本机装了什么字体。
BUNDLED_FONTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")

# Named files rather than a directory walk: Windows/Fonts holds several hundred
# entries, most of them unusable for a caption, and the dropdown would be a
# wall of noise. These are the ones that actually have Chinese glyphs.
KNOWN_FONTS = (
    "msyh.ttc",        # Microsoft YaHei
    "msyhbd.ttc",
    "simhei.ttf",      # SimHei
    "simsun.ttc",      # SimSun
    "simkai.ttf",      # KaiTi
    "simfang.ttf",     # FangSong
    "Deng.ttf",        # DengXian
)

WINDOWS_FONTS = r"C:\Windows\Fonts"


def _font_dirs():
    """Where to look for a font file, most specific first."""
    dirs = [BUNDLED_FONTS_DIR]
    try:
        import folder_paths
        dirs.append(os.path.join(folder_paths.models_dir, "fonts"))
    except Exception:                                     # noqa: BLE001
        pass
    dirs.append(WINDOWS_FONTS)
    return dirs


def font_choices():
    """What the dropdown offers: whatever is actually readable on this box."""
    names = [DEFAULT_FONT]
    for directory in _font_dirs():
        if not os.path.isdir(directory):
            continue
        for name in KNOWN_FONTS:
            if os.path.exists(os.path.join(directory, name)) and name not in names:
                names.append(name)
        # Anything the user dropped into models/fonts is fair game too.
        try:
            for entry in sorted(os.listdir(directory)):
                if entry.lower().endswith((".ttf", ".otf", ".ttc")) and entry not in names:
                    names.append(entry)
        except OSError:
            pass
    return names


def resolve_font(name: str):
    """Full path for a font name, or None when it is the built-in default."""
    if not name or name == DEFAULT_FONT:
        return None
    if os.path.isabs(name) and os.path.exists(name):
        return name
    for directory in _font_dirs():
        candidate = os.path.join(directory, name)
        if os.path.exists(candidate):
            return candidate
    return None


def _truetype(path: str, size: int):
    """加载 TTF，并把可变字体固定到 Regular 实例。

    随包的 Noto Sans SC 是官方可变字体，默认实例为 Thin，20~40 px 的标注
    会细到几乎看不见。静态字体没有这个轴，调用会被静默忽略。
    """
    face = ImageFont.truetype(path, max(1, int(size)))
    if hasattr(face, "set_variation_by_name"):
        try:
            face.set_variation_by_name("Regular")
        except (OSError, ValueError, AttributeError, TypeError):
            pass
    return face


def load_font(name: str, size: int):
    """Load a font, saying so when the requested one is not there."""
    path = resolve_font(name)
    if path is None:
        return ImageFont.load_default(), "default"
    try:
        return _truetype(path, size), name
    except Exception as exc:                              # noqa: BLE001
        print("[Photo Sheet] could not load font %r (%s); falling back to the "
              "built-in bitmap font, which has no Chinese glyphs" % (name, exc))
        return ImageFont.load_default(), "default"


@lru_cache(maxsize=128)
def font_for(name: str, size: int):
    """Cached loader. The caption-fitting loop asks for the same font at many
    sizes; without this every step re-reads the file and every failure would
    print its warning again."""
    return load_font(name, int(size))


def _text_width(font, text: str) -> int:
    box = font.getbbox(text)
    return box[2] - box[0]


def _to_pil(frame: torch.Tensor) -> Image.Image:
    array = (frame.clamp(0.0, 1.0).cpu().numpy() * 255.0).round().astype(np.uint8)
    if array.ndim == 3 and array.shape[2] == 1:
        array = array[..., 0]
    if array.ndim == 2:
        # 灰度：先转 RGB。后面 ImageOps.expand(fill=(0,0,0)) 对 L 模式会抛
        # TypeError，转成 RGB 之后边框才画得上去。
        return Image.fromarray(array, "L").convert("RGB")
    if array.ndim != 3:
        return Image.fromarray(array).convert("RGB")
    channels = array.shape[2]
    if channels == 2:
        return Image.fromarray(array, "LA").convert("RGB")
    if channels >= 4:
        # RGBA：先按 alpha 合成到白底。直接 paste 到 RGB 画布会丢掉 alpha，
        # 透明区域（RGB 通常是 0）会被印成黑块 —— 抠图节点的输出接进来就中招。
        rgba = Image.fromarray(array[..., :4], "RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, (0, 0), rgba)
        return flat
    return Image.fromarray(array[..., :3], "RGB")


def _to_tensor(image: Image.Image) -> torch.Tensor:
    array = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(array)


def _fit_caption(text, name, size, max_width):
    """Shrink the caption until it fits, then cut it. Always says which."""
    if not text or size <= 0:
        return None, size
    chosen = int(size)
    while chosen > 8:
        font, _ = font_for(name, chosen)
        if _text_width(font, text) <= max_width:
            return text, chosen
        chosen = int(chosen * 0.9)
    font, _ = font_for(name, chosen)
    width = _text_width(font, text)
    if width <= max_width:
        return text, chosen
    # Still too wide at the floor size: cut characters until it fits.
    trimmed = text
    while trimmed and width > max_width:
        trimmed = trimmed[:-1]
        width = _text_width(font, trimmed)
    print("[Photo Sheet] caption did not fit at the smallest size; trimmed to "
          "%r" % trimmed)
    return trimmed, chosen


def _draw_cut_marks(draw, plan, spacing_px, colour=(0, 0, 0)):
    """Short L marks just outside each corner, in the gutter.

    The marks point away from the photo, not into it: a cut line is a guide
    for where to cut, so it belongs in the space that gets trimmed off. The
    reach is capped at the spacing so two neighbouring marks never meet, and
    a sheet with no spacing draws none - there is nowhere to put them.
    """
    gutter = max(0, int(spacing_px))
    reach = min(gutter // 2, 10)
    if reach <= 0:
        return
    for row in range(plan.rows):
        for col in range(plan.cols):
            x = plan.origin_x + col * plan.step_x
            y = plan.origin_y + row * plan.step_y
            right = x + plan.photo_w
            bottom = y + plan.photo_h
            for cx, cy, dx, dy in (
                (x, y, -1, -1), (right, y, 1, -1),
                (x, bottom, -1, 1), (right, bottom, 1, 1),
            ):
                draw.line([(cx, cy), (cx + dx * reach, cy)], fill=colour, width=1)
                draw.line([(cx, cy), (cx, cy + dy * reach)], fill=colour, width=1)


def rescale_for_dpi(photo: Image.Image, photo_dpi: int, sheet_dpi: int):
    """Reinterpret the photo's pixels as ``photo_dpi`` and re-sample for the
    sheet's dpi, so that one inch of the photo stays one inch on the paper.

    A 1 inch portrait at 600 dpi is 591x827 px. Dropped onto a 350 dpi sheet as
    is, those same pixels are read as 350 dpi worth of image and print at
    4.3x6.0 cm - a "1 inch" photo that no office will accept. Measured in
    centimetres the two only agree after dividing by the dpi that produced
    them and multiplying by the one that will consume them.

    Returns ``(image, note)``, ``note`` being ``None`` when nothing moved.
    """
    if photo_dpi <= 0 or sheet_dpi <= 0 or photo_dpi == sheet_dpi:
        return photo, None
    scale = float(sheet_dpi) / float(photo_dpi)
    width = max(1, int(round(photo.width * scale)))
    height = max(1, int(round(photo.height * scale)))
    if (width, height) == (photo.width, photo.height):
        return photo, None
    note = (photo.width, photo.height, width, height, photo_dpi, sheet_dpi)
    return photo.resize((width, height), Image.Resampling.LANCZOS), note


def build_sheet(photo: Image.Image, caption, font_name, font_size,
                paper_w_cm, paper_h_cm, dpi, margin_cm, spacing_cm,
                border_px, cut_marks, auto_orient, auto_fit=True,
                photo_dpi=0):
    """Render one sheet.

    Returns ``(image, plan, caption_used, fit, dpi_note)``. ``fit`` is ``None``
    when the photo went on as it came in, otherwise ``(src_w, src_h, new_w,
    new_h)`` for the copy auto-fit had to scale - the caller logs it, because a
    silent downscale is a lost print nobody notices until the paper comes out
    of the tray. ``dpi_note`` is the same shape for the dpi conversion.
    """
    photo, dpi_note = rescale_for_dpi(photo, int(photo_dpi), int(dpi))

    gap_px = cm_to_px(0.1, dpi)
    caption_h = (font_size + gap_px) if (caption and font_size > 0) else 0
    frame = max(0, int(border_px))
    pad = 2 * frame

    def plan_for(w, h):
        return plan_sheet(w, h, paper_w_cm, paper_h_cm, dpi, margin_cm,
                          spacing_cm, caption_h=caption_h,
                          auto_orient=auto_orient)

    plan = plan_for(photo.width + pad, photo.height + pad)
    fit = None

    if plan.total == 0:
        usable_w, usable_h = usable_area(paper_w_cm, paper_h_cm, dpi,
                                         margin_cm, caption_h)
        if not auto_fit:
            raise ValueError(
                "这张照片 %dx%d 像素放不进 %.1fx%.1f 厘米、%d dpi 的相纸："
                "扣掉 %.2f 厘米边距、%.2f 厘米间距后只剩 %dx%d 像素可用，"
                "而「自动缩小」是关的。把相纸调大、dpi 调低、边距/间距调小，"
                "或打开「自动缩小」。"
                % (photo.width + pad, photo.height + pad, paper_w_cm,
                   paper_h_cm, dpi, margin_cm, spacing_cm,
                   usable_w, usable_h))

        fitted = shrink_to_fit(photo.width + pad, photo.height + pad,
                               paper_w_cm, paper_h_cm, dpi, margin_cm,
                               spacing_cm, caption_h=caption_h,
                               auto_orient=auto_orient)
        if fitted is None:
            raise ValueError(
                "缩小到最小尺寸后仍放不进 %.1fx%.1f 厘米、%d dpi 的相纸："
                "%.2f 厘米边距%s只剩 %dx%d 像素可用。把边距调小或把相纸调大。"
                % (paper_w_cm, paper_h_cm, dpi, margin_cm,
                   "加文字说明" if caption_h else "",
                   usable_w, usable_h))

        inner_w = max(1, fitted.width - pad)
        inner_h = max(1, fitted.height - pad)
        if (inner_w, inner_h) != (photo.width, photo.height):
            fit = (photo.width, photo.height, inner_w, inner_h)
            photo = photo.resize((inner_w, inner_h), Image.Resampling.LANCZOS)
        plan = plan_for(photo.width + pad, photo.height + pad)
        if plan.total == 0:
            # 纸太小、边距/边框太大时能走到这里（都是控件的合法值）。原来的
            # 「please report these numbers」把可调参数的后果说成了内部 bug。
            raise ValueError(
                "这张照片 %dx%d 像素连一张都放不进 %.1fx%.1f 厘米、%d dpi 的相纸"
                "（边距 %.2f 厘米）。把相纸调大、dpi 调低，或把边距/边框调小。"
                % (photo.width + pad, photo.height + pad, paper_w_cm,
                   paper_h_cm, dpi, margin_cm))

    if frame:
        photo = ImageOps.expand(photo, border=frame, fill=(0, 0, 0))

    canvas = Image.new("RGB", (plan.canvas_w, plan.canvas_h), (255, 255, 255))
    for row in range(plan.rows):
        for col in range(plan.cols):
            canvas.paste(photo, (plan.origin_x + col * plan.step_x,
                                 plan.origin_y + row * plan.step_y))

    spacing_px = cm_to_px(spacing_cm, dpi)
    if cut_marks:
        _draw_cut_marks(ImageDraw.Draw(canvas), plan, spacing_px)

    caption_used = None
    if caption_h:
        usable = canvas.width - 2 * cm_to_px(margin_cm, dpi)
        text, size = _fit_caption(caption, font_name, font_size, usable)
        if text:
            caption_used = (text, size)
            font, _ = font_for(font_name, size)
            draw = ImageDraw.Draw(canvas)
            box = font.getbbox(text)
            text_w = box[2] - box[0]
            draw.text((plan.origin_x + (plan.block_w - text_w) // 2,
                       plan.caption_y + gap_px),
                      text, font=font, fill=(0, 0, 0))

    return canvas, plan, caption_used, fit, dpi_note


class QGPhotoSheet:

    CATEGORY = "QG 工具"
    DESCRIPTION = (
        "Tile one photo across a print-sized sheet: pick paper in centimetres, "
        "a dpi, the margin and the gap, and every photo that fits is repeated "
        "in a centred grid. Paper, margin and spacing are centimetres; border "
        "and font size are pixels - the names say which. Set photo_dpi to the "
        "dpi the photo came out of and its pixels read as real centimetres, so "
        "a 1 inch portrait prints at 1 inch instead of whatever the sheet's "
        "dpi makes of those pixels. A photo larger than the sheet is scaled "
        "down to fit (auto-fit, on by default) and the log reports the "
        "percentage, rather than failing the run or returning a blank sheet. "
        "Every frame of a batch gets its own sheet. Optionally draws corner "
        "cut marks in the gutter and a caption under the grid."
    )
    SEARCH_ALIASES = ["photo sheet", "photosheet", "print layout", "id photo sheet",
                      "tile", "repeat image", "grid print", "排版", "照片排版",
                      "相纸", "冲印", "排版打印", "一寸排版", "证件照排版",
                      "单尺寸排版", "拼版"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {
                    "tooltip": "要复制的照片。批量输入每帧各出一版；照片只重复、绝不缩放。",
                }),
                "paper_w": ("FLOAT", {
                    "default": 12.7, "min": 1.0, "max": 100.0, "step": 0.1,
                    "tooltip": "相纸宽度（厘米）。12.7 × 8.9 是 5 寸，10.1 × 15.2 是 "
                               "6 寸。",
                }),
                "paper_h": ("FLOAT", {
                    "default": 8.9, "min": 1.0, "max": 100.0, "step": 0.1,
                    "tooltip": "相纸高度（厘米）。",
                }),
                "dpi": ("INT", {
                    "default": 350, "min": 72, "max": 1200, "step": 1,
                    "tooltip": "打印分辨率，决定版面有多少像素：12.7 厘米 @350 dpi 就是 1750"
                               " 像素。",
                }),
                "margin": ("FLOAT", {
                    "default": 0.2, "min": 0.0, "max": 10.0, "step": 0.05,
                    "tooltip": "四边留白（厘米）。打印机一般够不到最后几毫米。",
                }),
                "spacing": ("FLOAT", {
                    "default": 0.2, "min": 0.0, "max": 5.0, "step": 0.05,
                    "tooltip": "照片之间的间距（厘米）。裁切标记也画在这条缝里。",
                }),
                "border": ("INT", {
                    "default": 0, "min": 0, "max": 40, "step": 1,
                    "tooltip": "每张照片外圈的黑色边框（像素）。它会让照片变大，所以要算进「能放几张」。",
                }),
                "cut_marks": ("BOOLEAN", {
                    "default": False,
                    "label_on": "Cut Marks", "label_off": "No Marks",
                    "tooltip": "每个照片角上的短 L 形裁切标记，画在缝里。间距要大于 0 才画。",
                }),
                "auto_orient": ("BOOLEAN", {
                    "default": True,
                    "label_on": "Auto", "label_off": "As Set",
                    "tooltip": "纸横过来能多放时自动转。选「保持」就按设的纸向。",
                }),
                "caption": ("STRING", {
                    "default": "", "multiline": False,
                    "tooltip": "印在版面下方的文字，只画在版面上、不写进文件。留空就不印。",
                }),
                "font": (font_choices(), {
                    "default": DEFAULT_FONT,
                    "tooltip": "文字字体。随包的 OFL 字体 NotoSansSC-VF.ttf 排在最前，能"
                               "显示中文；内置点阵字体不行，中文会变成方块。",
                }),
                "font_size": ("INT", {
                    "default": 0, "min": 0, "max": 200, "step": 1,
                    "tooltip": "文字大小（像素）。0 完全关闭文字，并把它占的高度让出来。",
                }),
                "auto_fit": ("BOOLEAN", {
                    "default": True,
                    "label_on": "Shrink to Fit", "label_off": "Error Out",
                    "tooltip": "照片比相纸大时按比例缩小，而不是中止运行。2560×3413 的渲染就是这样装进"
                               " 5 寸纸的，日志会写缩到百分之多少。关掉就直接报错并给出数字。",
                }),
                "photo_dpi": ("INT", {
                    "default": 0, "min": 0, "max": 2400, "step": 1,
                    "tooltip": "照片渲染时的 DPI，用来把它的像素换算成真实厘米。填 0 就按像素摆。1 寸人"
                               "像 @600 dpi 是 591×827 像素；在 350 dpi 的纸上不填 "
                               "600，这些像素只会印成 4.3×6.0 厘米。把证件照节点的 DPI 输出接进"
                               "来最稳。",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "INT", "INT")
    RETURN_NAMES = ("sheet", "columns", "rows", "total")
    FUNCTION = "execute"
    OUTPUT_TOOLTIPS = (
        "每输入一帧出一版，尺寸 = 相纸尺寸 × dpi。",
        "一行能放几张。",
        "能放几行。",
        "列 × 行 —— 一版上的份数。",
    )

    def execute(self, image, paper_w, paper_h, dpi, margin, spacing, border,
                cut_marks, auto_orient, caption, font, font_size,
                auto_fit=True, photo_dpi=0):
        batch = image if image.dim() == 4 else image.unsqueeze(0)
        if int(batch.shape[0]) == 0:
            # 图像空批次按本包约定报中文错误：torch.stack([]) 与 last_plan.cols
            # 都会抛裸异常，用户看不出是哪个节点、为什么空。
            raise ValueError(
                "QG 照片拼版：没有收到任何图像帧（输入 batch 为 0 帧）。"
                "检查上游是否把照片全部过滤掉了。")

        sheets = []
        last_plan = None
        for index in range(int(batch.shape[0])):
            photo = _to_pil(batch[index])
            canvas, plan, used, fitted, dpi_note = build_sheet(
                photo, caption, font, int(font_size),
                float(paper_w), float(paper_h), int(dpi),
                float(margin), float(spacing),
                int(border), bool(cut_marks), bool(auto_orient),
                bool(auto_fit), int(photo_dpi))
            sheets.append(_to_tensor(canvas))
            last_plan = plan
            if index == 0:
                note = ""
                if auto_orient and (plan.canvas_w, plan.canvas_h) != (
                        cm_to_px(paper_w, dpi), cm_to_px(paper_h, dpi)):
                    note = " (paper turned around: it fits more that way)"
                if used:
                    note += " caption=%r at %dpx" % used
                print("[Photo Sheet] %dx%d photo -> %d x %d = %d per sheet "
                      "on a %dx%d px sheet%s"
                      % (photo.width, photo.height, plan.cols, plan.rows,
                         plan.total, plan.canvas_w, plan.canvas_h, note))
                if dpi_note:
                    src_w, src_h, new_w, new_h, from_dpi, to_dpi = dpi_note
                    detail = ""
                    if new_w > src_w:
                        detail = (" The photo has fewer pixels than %d dpi "
                                  "needs here, so this is an upscale and the "
                                  "print will be soft." % to_dpi)
                    print("[Photo Sheet] photo_dpi=%d vs sheet %d dpi: %dx%d px "
                          "-> %dx%d px, so one inch stays one inch.%s"
                          % (from_dpi, to_dpi, src_w, src_h, new_w, new_h,
                             detail))
                if fitted:
                    src_w, src_h, new_w, new_h = fitted
                    percent = int(round(100.0 * new_w / src_w))
                    print("[Photo Sheet] photo was %dx%d px, too big for this "
                          "sheet - scaled to %d%% (%dx%d px, about %d dpi in "
                          "print). Bigger paper or a higher dpi keeps more "
                          "detail."
                          % (src_w, src_h, percent, new_w, new_h,
                             int(round(float(dpi) * percent / 100.0))))

        return (torch.stack(sheets), last_plan.cols, last_plan.rows,
                last_plan.total)


NODE_CLASS_MAPPINGS = {"QG_PhotoSheet": QGPhotoSheet}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_PhotoSheet": "QG 照片排版"}
