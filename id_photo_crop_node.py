"""ID Photo Crop - one affine pass from portrait to exact ID photo size.

The reference behaviour is 孤海-证件照裁剪 from Goohaitools. Keeping its
parameter meanings matters - a workflow moved over should not need retuning -
so ``face_ratio`` is the outline width share, ``eye_line`` is how far down the
crop the eyes sit, and the preset list is the same. What changed:

* **One resample, not four.** Shrink for detection, straighten onto a padded
  canvas, crop, then scale up to the target - the last step magnifies what the
  first discarded. Here the frame is planned in source coordinates and PIL
  produces the finished picture in one pass.
* **Every frame is cropped, not just the first.** A batch of ten portraits used
  to come back as one picture; the rest vanished without a word.
* **A missing face does not hand back the wrong size.** The picture is fitted
  and centred into the target, so downstream nodes still get what they were
  promised instead of an image at some other size.
* **A guide image alongside.** ``face_ratio`` means nothing until you see where
  the frame lands, so one output draws the face box, the eye line and the crop
  rectangle on the source.

Detection is mediapipe when available, OpenCV's cascade otherwise; neither is
required for the pack to load.
"""

from __future__ import annotations

import string

import numpy as np
import torch
from PIL import Image, ImageColor

from ._face_helpers import backend_status, detect
from ._id_photo_helpers import (PRESET_ORDER, draw_guide, output_pixels,
                                plan_frame, render, border_color)

GUIDE_MAX_SIDE = 1400


def _to_pil(frame_rgb):
    """float32 HWC in 0..1 -> PIL RGB."""
    array = np.clip(np.asarray(frame_rgb, dtype=np.float32) * 255.0, 0.0, 255.0)
    return Image.fromarray(array.astype(np.uint8), "RGB")


def _to_tensor(image):
    array = np.asarray(image, dtype=np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


def _fit_center(img, out_w, out_h, fill_rgb):
    """Detection failed: put the whole picture inside the target, centred.

    Handing back the original would produce a picture whose size disagrees with
    the one the node promised, and whatever is downstream built its latent on
    that promise.
    """
    scale = min(out_w / float(img.width), out_h / float(img.height))
    width = max(1, int(round(img.width * scale)))
    height = max(1, int(round(img.height * scale)))
    resized = img.resize((width, height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (out_w, out_h), tuple(int(c) for c in fill_rgb))
    left = (out_w - width) // 2
    top = (out_h - height) // 2
    canvas.paste(resized, (left, top))
    mask = np.ones((out_h, out_w), dtype=np.float32)
    mask[top:top + height, left:left + width] = 0.0
    return canvas, mask


def parse_color(value, source="fill_color"):
    """Read a colour leniently; never raises.

    Accepts ``#RRGGBB``, ``#ABC``, ``0-255`` triples, a single grey level, or
    anything PIL knows by name. An unreadable value falls back to mid-grey and
    says so, so a typo is findable rather than silently producing a black frame.
    """
    text = str("" if value is None else value).strip()
    if not text:
        return (0, 0, 0)

    digits = text.lstrip("#")
    # string.hexdigits 而不是手写那串 —— 手写时漏掉 1/4/5 也没人看得出来，
    # 后果是 "123456" 这种裸六位被当成灰度 123456 钳成纯白。
    if len(digits) in (3, 6) and all(c in string.hexdigits for c in digits) \
            and (text.startswith("#") or len(digits) == 6
                 or any(c.isalpha() for c in digits)):
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))

    parts = [p for p in text.replace(",", " ").split() if p]
    if len(parts) in (1, 3):
        try:
            numbers = [float(p) for p in parts]
        except ValueError:
            numbers = []
        if numbers:
            if len(numbers) == 1:
                numbers = numbers * 3
            return tuple(max(0, min(255, int(round(n)))) for n in numbers)

    try:
        return tuple(int(c) for c in ImageColor.getrgb(text)[:3])
    except Exception:                                    # noqa: BLE001
        print("[ID Photo Crop] %s: could not parse %r, using mid-grey"
              % (source, text))
        return (128, 128, 128)


class QGIDPhotoCrop:

    CATEGORY = "QG 工具"
    DESCRIPTION = (
        "Crop a portrait to an exact ID photo size (1 inch, US visa, the "
        "358x441 digital ID card and more), keeping the eyes level and the "
        "face at a chosen share of the width. The picture is resampled once: "
        "the crop frame is planned on the source and one affine pass produces "
        "the result, filling anything outside the source with the background "
        "colour or a colour sampled from the top of the picture. Outputs a "
        "mask of the invented area, a flag saying whether anything had to be "
        "invented, the dpi actually used, and a guide image that draws the "
        "face box, the eye line and the crop frame on the source so the "
        "settings can be judged by eye. Every frame of a batch is processed; "
        "a frame with no detectable face is fitted and centred rather than "
        "passed through at the wrong size."
    )
    SEARCH_ALIASES = ["id photo", "idphoto", "id card photo", "passport photo",
                      "passport", "visa photo", "visa", "portrait crop",
                      "portraitcrop", "face crop", "facecrop", "headshot",
                      "avatar", "photo crop", "证件照", "证件照裁剪", "证件照排版",
                      "一寸照", "二寸照", "头像", "签证照", "护照照片", "考试照",
                      "电子证件照"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {
                    "tooltip": "The portrait to crop. Every frame of a batch "
                               "is processed separately.",
                }),
                "preset": (list(PRESET_ORDER), {
                    "default": "1inch",
                    "tooltip": "Standard sizes. Picking one overrides the four "
                               "size widgets below; 'custom' uses them. Sizes "
                               "given in pixels carry their own dpi, because a "
                               "358x441 ID photo is 350 dpi by definition.",
                }),
                "custom_width": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 4096.0, "step": 0.01,
                    "tooltip": "Only used when preset is 'custom'. Centimetres "
                               "by default; switch the unit for pixels.",
                }),
                "custom_height": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 4096.0, "step": 0.01,
                    "tooltip": "Only used when preset is 'custom'.",
                }),
                "unit": (["cm", "px"], {
                    "default": "cm",
                    "tooltip": "cm: pixels = cm / 2.54 * dpi. px: the numbers "
                               "are pixels already.",
                }),
                "dpi": ("INT", {
                    "default": 300, "min": 72, "max": 2000, "step": 1,
                    "tooltip": "How many pixels make an inch. 300 is the print "
                               "standard; 600 gives a sharper file at twice "
                               "the size.",
                }),
                "face_ratio": ("FLOAT", {
                    "default": 0.42, "min": 0.15, "max": 0.9, "step": 0.01,
                    "tooltip": "How much of the crop's width the face outline "
                               "takes. 0.42 is a standard ID photo; larger is "
                               "a tighter head. The outline runs ear to ear, "
                               "so it is wider than the cheeks - which is why "
                               "the number looks low.",
                }),
                "eye_line": ("FLOAT", {
                    "default": 0.38, "min": 0.2, "max": 0.6, "step": 0.01,
                    "tooltip": "Where the eye line sits, measured from the top "
                               "of the crop. 0.38 leaves the usual headroom "
                               "above the hair.",
                }),
                "auto_rotate": ("BOOLEAN", {
                    "default": True,
                    "label_on": "Level", "label_off": "Keep Tilt",
                    "tooltip": "Turn the picture so the eyes are level. Off "
                               "keeps the original tilt while still cropping "
                               "to the eye midpoint.",
                }),
                "face_pick": (["center", "largest"], {
                    "default": "center",
                    "tooltip": "Which face when there are several: the one "
                               "nearest the middle of the frame, or the "
                               "largest one.",
                }),
                "max_side": ("INT", {
                    "default": 2000, "min": 0, "max": 8192, "step": 64,
                    "tooltip": "Shrink only for detection, so a big picture is "
                               "quick and a small face is still found. The "
                               "crop itself always comes from the full-"
                               "resolution source. 0 disables the preview "
                               "shrink.",
                }),
                "fill_mode": (["border", "custom"], {
                    "default": "border",
                    "tooltip": "Where the invented pixels take their colour "
                               "from: 'border' samples the top of the picture "
                               "(outliers dropped), 'custom' uses the colour "
                               "below.",
                }),
                "fill_color": ("STRING", {
                    "default": "#364254",
                    "tooltip": "Only used when fill_mode is 'custom'. Takes "
                               "#RRGGBB, #ABC, a colour name such as white, "
                               "128,128,128, or 0.5.",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "BOOLEAN", "INT", "IMAGE")
    RETURN_NAMES = ("image", "mask", "filled", "dpi", "guide")
    FUNCTION = "execute"
    OUTPUT_TOOLTIPS = (
        "The cropped portrait at the target size.",
        "1 where pixels had to be invented outside the source, 0 where the "
        "source was sampled.",
        "True when any frame needed those invented pixels.",
        "The dpi actually used - a pixel preset overrides the widget.",
        "The source with the face box, eye line and crop frame drawn on it.",
    )

    def execute(self, image, preset, custom_width, custom_height, unit, dpi,
                face_ratio, eye_line, auto_rotate, face_pick, max_side,
                fill_mode, fill_color):
        batch = image if image.dim() == 4 else image.unsqueeze(0)

        out_w, out_h, dpi_used = output_pixels(preset, unit, custom_width,
                                               custom_height, dpi)

        custom_rgb = parse_color(fill_color, "ID Photo Crop fill_color")
        crops = []
        masks = []
        guides = []
        any_filled = False
        misses = 0
        notes = []

        for index in range(int(batch.shape[0])):
            pil = _to_pil(batch[index].cpu().numpy())
            source_rgb = np.asarray(pil)

            if str(fill_mode) == "custom":
                fill_rgb = custom_rgb
            else:
                fill_rgb = border_color(source_rgb)

            face = self._detect_with_shrink(source_rgb, face_pick, max_side)
            filled = None
            frame = None
            if face is None:
                misses += 1
                crop, filled = _fit_center(pil, out_w, out_h, fill_rgb)
            else:
                try:
                    frame = plan_frame(face, out_w, out_h, face_ratio,
                                       eye_line, auto_rotate)
                except ValueError as exc:
                    misses += 1
                    notes.append(str(exc))
                    crop, filled = _fit_center(pil, out_w, out_h, fill_rgb)
                else:
                    crop, filled = render(pil, frame, fill_rgb)
                    if not guides:
                        guides.append(self._shrink_guide(
                            draw_guide(pil, face, frame, filled)))

            has_fill = bool((filled > 0.5).any())
            any_filled = any_filled or has_fill
            crops.append(np.asarray(crop, dtype=np.float32) / 255.0)
            masks.append(filled)
            if index == 0:
                notes.append(
                    "face=%s, face %.1f%% of crop, tilt %.1f deg, filled %.1f%%"
                    % (face.source if face else "none",
                       (100.0 * face.width / frame.w) if frame else 0.0,
                       0.0 if (face is None or not auto_rotate)
                       else np.degrees(face.tilt),
                       float(filled.mean()) * 100.0))

        if not guides:
            guides.append(self._shrink_guide(
                Image.new("RGB", (max(1, out_w), max(1, out_h)), custom_rgb)))

        crop_stack = torch.from_numpy(np.stack(crops, axis=0))
        mask_stack = torch.from_numpy(np.stack(masks, axis=0))
        guide_tensor = _to_tensor(guides[0])

        if misses:
            print("[ID Photo Crop] %d/%d frame(s) had no usable face - fitted "
                  "and centred instead (backend: %s)"
                  % (misses, batch.shape[0], backend_status()))
        if notes:
            print("[ID Photo Crop] %dx%d -> %dx%d @%d dpi, preset %s, %s"
                  % (source_rgb.shape[1], source_rgb.shape[0], out_w, out_h,
                     dpi_used, preset, notes[0]))

        return (crop_stack, mask_stack, any_filled, dpi_used, guide_tensor)

    def _detect_with_shrink(self, source_rgb, face_pick, max_side):
        """Detect on a smaller copy when the picture is huge, then scale back.

        Only detection is done on the small copy: the crop itself always reads
        the full-resolution source, so the result is sharp regardless.
        """
        height, width = source_rgb.shape[:2]
        limit = int(max_side)
        long_side = max(width, height)
        if limit <= 0 or long_side <= limit:
            return detect(source_rgb, face_pick)

        scale = limit / float(long_side)
        small_w = max(1, int(round(width * scale)))
        small_h = max(1, int(round(height * scale)))
        small = np.asarray(
            Image.fromarray(source_rgb).resize((small_w, small_h),
                                               Image.Resampling.BILINEAR))
        face = detect(small, face_pick)
        if face is None:
            # A smaller copy can lose a face the full-size one would have found.
            return detect(source_rgb, face_pick)
        return face.scaled(width / float(small_w), height / float(small_h))

    @staticmethod
    def _shrink_guide(guide):
        long_side = max(guide.width, guide.height)
        if long_side <= GUIDE_MAX_SIDE:
            return guide
        ratio = GUIDE_MAX_SIDE / float(long_side)
        return guide.resize((max(1, int(round(guide.width * ratio))),
                             max(1, int(round(guide.height * ratio)))),
                            Image.Resampling.LANCZOS)



NODE_CLASS_MAPPINGS = {"QG_IDPhotoCrop": QGIDPhotoCrop}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_IDPhotoCrop": "ID Photo Crop"}
