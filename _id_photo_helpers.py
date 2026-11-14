"""Where the crop goes, and how the picture gets there.

The whole layout is arithmetic in ``plan_frame``: given a face, a target
picture size and two ratios, it says exactly which rectangle of the source
becomes which rectangle of the output, as one affine matrix. Nothing is drawn
there, so the geometry can be asserted on its own - feed a known crop coordinate
back through the matrix and it must land on the eye.

Why one matrix matters: the obvious way to build a rotated ID photo is to
straighten the whole picture onto a bigger canvas, crop, then resize to the
target. Each of those steps resamples, and the last one magnifies whatever the
first one threw away. A single ``transform`` with this matrix reads the source
once and writes the output once.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

CM_PER_INCH = 2.54

# Verified against the sizes the reference implementation offers. The first
# three fields are the printed size; the fourth is the dpi that size carries by
# definition (``None`` means "use whatever the widget says"). A 358x441 ID
# photo is 350 dpi because that is what 358x441 means - letting the widget
# override it would silently produce a picture that is not that size.
PRESETS = {
    "1inch": (2.5, 3.5, "cm", None),
    "1inch_large": (3.3, 4.8, "cm", None),
    "2inch_small": (3.5, 4.5, "cm", None),
    "2inch": (3.5, 4.9, "cm", None),
    "2inch_large": (3.5, 5.3, "cm", None),
    "3inch": (5.5, 8.5, "cm", None),
    "5inch": (8.9, 12.7, "cm", None),
    "6inch": (10.1, 15.2, "cm", None),
    "id_card": (2.6, 3.2, "cm", None),
    "driver_license": (2.2, 3.2, "cm", None),
    "japan_visa": (4.5, 4.5, "cm", None),
    "us_visa": (5.1, 5.1, "cm", None),
    "postgrad_exam": (3.0, 4.0, "cm", None),
    "id_card_digital": (358, 441, "px", 350),
    "mandarin_exam": (390, 567, "px", 300),
    "teacher_exam": (480, 640, "px", 300),
    "nurse_exam": (160, 210, "px", 300),
    "judicial_exam": (413, 626, "px", 300),
    "medical_exam": (354, 472, "px", 300),
    "custom": None,
}

PRESET_ORDER = list(PRESETS)

# Guard rails. The custom size widgets are in centimetres by default, so a
# value that was meant as pixels ("413") is 4880 px at 300 dpi - and the same
# typo with unit=cm can ask for a 47 000 px canvas, which does not raise, it
# just eats all the memory and takes ComfyUI down with it. A value that rounds
# away to nothing is the other half of the same mistake.
MAX_SIDE = 8192
MIN_SIDE = 8


def output_pixels(preset, unit, custom_w, custom_h, dpi):
    """Resolve the target picture size in pixels. Returns ``(w, h, dpi)``.

    ``custom`` falls back to the two size widgets; everything else ignores them,
    which is the point of a preset. A preset given in pixels also fixes the
    dpi, because the pixel count and the paper size together *are* the dpi.
    """
    key = str(preset)
    spec = PRESETS.get(key)
    if spec is None or key == "custom":
        width, height, use_unit, use_dpi = (float(custom_w), float(custom_h),
                                            str(unit), int(dpi))
    else:
        width, height, use_unit, use_dpi = spec
        use_dpi = int(use_dpi) if use_dpi else int(dpi)

    use_dpi = max(72, min(2000, use_dpi))

    if use_unit == "px":
        width_px = int(round(width))
        height_px = int(round(height))
    else:
        width_px = int(round(width / CM_PER_INCH * use_dpi))
        height_px = int(round(height / CM_PER_INCH * use_dpi))

    if width_px < MIN_SIDE or height_px < MIN_SIDE:
        raise ValueError(
            "target size works out to %dx%d px - check the custom width/height "
            "and the unit (unit %s, %d dpi); a size below %d px cannot be a "
            "photo" % (width_px, height_px, use_unit, use_dpi, MIN_SIDE))

    return min(width_px, MAX_SIDE), min(height_px, MAX_SIDE), use_dpi


class Frame(NamedTuple):
    """Where the crop sits on the source, and how the two map onto each other.

    ``cx``/``cy`` are the centre of the crop rectangle in source pixels, and
    ``tilt`` is how far it is turned. ``affine`` is the PIL matrix that takes an
    output pixel and returns the source pixel it reads - the direction PIL wants,
    which is the inverse of the intuitive one.
    """
    cx: float
    cy: float
    w: float
    h: float
    tilt: float
    out_w: int
    out_h: int
    affine: tuple

    def scale(self) -> float:
        """Source pixels per output pixel."""
        return self.w / float(self.out_w)


def plan_frame(face, out_w, out_h, face_ratio, eye_line, rotate):
    """Build the frame for one face. Pure arithmetic, no pixels touched."""
    if face is None:
        raise ValueError("no face")
    if face.width < 8:
        raise ValueError("face box is only %.1f px wide - the picture is too "
                         "small" % face.width)

    width = face.width / float(face_ratio)
    height = width * float(out_h) / float(out_w)
    if width < 16 or height < 16:
        raise ValueError("crop works out to %.0f x %.0f px - check the face "
                         "ratio" % (width, height))

    tilt = float(face.tilt) if rotate else 0.0
    cos, sin = math.cos(tilt), math.sin(tilt)
    ex, ey = face.eye_center

    # The eyes sit ``eye_line`` down the crop, so the crop centre is below them
    # by this much - turned with the face, or a tilted crop would drift.
    offset_y = (0.5 - float(eye_line)) * height
    cx = ex + cos * 0.0 - sin * offset_y
    cy = ey + sin * 0.0 + cos * offset_y

    scale = width / float(out_w)
    a = scale * cos
    b = -scale * sin
    d = scale * sin
    e = scale * cos
    c = ex - a * (out_w / 2.0) - b * (eye_line * out_h)
    f = ey - d * (out_w / 2.0) - e * (eye_line * out_h)

    return Frame(cx, cy, width, height, tilt, int(out_w), int(out_h),
                 (a, b, c, d, e, f))


def frame_corners(frame):
    """The four corners of the crop rectangle, in source pixels."""
    cos, sin = math.cos(frame.tilt), math.sin(frame.tilt)
    half_w, half_h = frame.w / 2.0, frame.h / 2.0
    corners = []
    for dx, dy in ((-half_w, -half_h), (half_w, -half_h),
                   (half_w, half_h), (-half_w, half_h)):
        corners.append((frame.cx + cos * dx - sin * dy,
                        frame.cy + sin * dx + cos * dy))
    return corners


def render(img, frame, fill_rgb):
    """One affine pass. Returns ``(crop_pil, filled_mask)``.

    ``filled_mask`` is float32 HxW with 1.0 where the crop had to invent pixels
    (outside the source) and 0.0 where real pixels came through.

    ``transform`` does not offer LANCZOS - and would not help if it did: it
    samples without a prefilter, so shrinking 3x in one hit aliases. When the
    scale is large the picture is reduced by an integer factor first, which is
    an exact coordinate division and averages properly, and the residual is
    left to BICUBIC. The factor is floored, not rounded: a scale of 2.6 must
    reduce by 2 and then shrink 1.3x, because reducing by 3 would leave the
    remaining 0.87 a *magnification* of an already decimated picture.
    """
    size = (frame.out_w, frame.out_h)
    affine = frame.affine
    work = img

    factor = int(frame.scale())
    if factor >= 2 and img.width // factor >= 8 and img.height // factor >= 8:
        work = img.reduce(factor)
        affine = tuple(v / factor for v in frame.affine)

    crop = work.transform(size, Image.Transform.AFFINE, affine,
                          resample=Image.Resampling.BICUBIC,
                          fillcolor=tuple(int(c) for c in fill_rgb))

    # Which output pixels actually sampled the source. The plate is made at the
    # working resolution, not on a shrunk copy, or the filled/unfilled edge
    # gets eaten by the first resample.
    plate = Image.new("L", work.size, 255)
    keep = plate.transform(size, Image.Transform.AFFINE, affine,
                           resample=Image.Resampling.NEAREST, fillcolor=0)
    filled = 1.0 - np.asarray(keep, dtype=np.float32) / 255.0
    return crop, np.clip(filled, 0.0, 1.0)


def border_color(rgb):
    """Average of the top strip, robust against one odd-coloured patch.

    An ID photo is nearly always shot or generated against a plain background,
    and the top strip is the part least likely to contain a collar or hair. A
    single mean would be dragged by a bright blob, so pixels far from the median
    are dropped first.
    """
    if rgb is None or rgb.size == 0:
        return (255, 255, 255)
    strip = rgb[:max(1, rgb.shape[0] // 10)].reshape(-1, 3).astype(np.float32)
    if strip.size == 0:
        return (255, 255, 255)
    median = np.median(strip, axis=0)
    distance = np.abs(strip - median).max(axis=1)
    keep = strip[distance <= 40]
    if keep.size == 0:
        keep = strip
    return tuple(int(round(float(c))) for c in keep.mean(axis=0))


def _guide_font(size):
    for name in ("msyh.ttc", "simhei.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:                                # noqa: BLE001
            continue
    return ImageFont.load_default()


def draw_guide(img, face, frame, filled=None):
    """Mark the face box, the eye line and the crop rectangle on the source.

    This exists because ``face_ratio`` is a number nobody can judge by eye. With
    the frame drawn over the picture the question becomes "is the head the right
    size", which is answerable at a glance.

    The canvas grows to hold whatever falls outside the source, so a crop that
    had to invent pixels is visible rather than assumed.
    """
    corners = frame_corners(frame)
    xs = [p[0] for p in corners] + [0.0, float(img.width)]
    ys = [p[1] for p in corners] + [0.0, float(img.height)]
    pad = 30
    left = math.floor(min(xs)) - pad
    top = math.floor(min(ys)) - pad
    right = math.ceil(max(xs)) + pad
    bottom = math.ceil(max(ys)) + pad

    canvas = Image.new("RGB", (int(right - left), int(bottom - top)),
                       (28, 28, 30))
    canvas.paste(img, (int(-left), int(-top)))
    draw = ImageDraw.Draw(canvas)

    def shift(point):
        return (point[0] - left, point[1] - top)

    green = (80, 220, 120)
    red = (255, 90, 90)
    amber = (255, 200, 60)

    if face is not None:
        draw.rectangle([shift((face.x0, face.y0)), shift((face.x1, face.y1))],
                       outline=green, width=2)
        draw.line([shift(face.eye_a), shift(face.eye_b)], fill=red, width=2)
        for eye in (face.eye_a, face.eye_b):
            ex, ey = shift(eye)
            draw.ellipse([ex - 4, ey - 4, ex + 4, ey + 4], outline=red, width=2)

    draw.line([shift(corners[0]), shift(corners[1]), shift(corners[2]),
               shift(corners[3]), shift(corners[0])], fill=amber, width=2)

    label = "%dx%d px | face %.0f%% | tilt %.1f deg | %s" % (
        frame.out_w, frame.out_h,
        100.0 * (face.width / frame.w) if face is not None else 0.0,
        math.degrees(frame.tilt),
        ("filled %.0f%%" % (100.0 * float(filled.mean()))) if filled is not None
        else "no fill")
    font = _guide_font(18)
    draw.rectangle([0, 0, canvas.width, 30], fill=(0, 0, 0))
    draw.text((8, 6), label, font=font, fill=(240, 240, 240))

    return canvas
