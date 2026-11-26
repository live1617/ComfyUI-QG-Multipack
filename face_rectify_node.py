# -*- coding: utf-8 -*-
"""QG_FaceRectify - straighten a picture so its face stands upright.

Written for the QG 工具 multi-pack (ComfyUI-QG-Multipack) on 2026-11-04.
Same job as the "auto face rectify" idea (Goohaitools' node), implemented
from scratch for this pack after reading how that node works.

Pipeline (per frame, best-effort - any failure returns the frame as-is)
-----------------------------------------------------------------------
1. **Quarter-turn scan.** HOG face detection runs on 0/90/180/270 degree
   full rotations; the first orientation that finds a face wins. This
   fixes sideways/upside-down photos before any fine work.
2. **Tilt from the eyes.** The 5-point landmark model gives two points per
   eye; their per-eye mean centers define the eye line. ``atan2`` of that
   line is the roll angle; angles beyond +-45 degrees are treated as the
   head lying sideways and folded back by 90.
3. **Rotate about the center** with Lanczos4 and replicated borders (no
   black corners), then center-crop back to the original size (swapped for
   quarter turns) so the rotated padding is gone.
4. **Edge trim.** Rotating smears a soft band along all four edges, so the
   node shaves ``side * fold(angle)^0.8 / 100 / edge_trim`` pixels off each
   edge - larger ``edge_trim`` values trim less. fold() maps the angle to
   0..45 so a sideways head does not nuke the whole picture.

Differences from the node this was modeled on: the dlib detector and
predictor are created once and reused (not per execution), and batches
whose frames end up different sizes are padded/cropped to the first
frame's size instead of crashing ``torch.stack``.

Needs ``dlib`` plus ``shape_predictor_5_face_landmarks.dat`` in the pack
root (bundled). Without them every frame passes through unchanged.
"""

from __future__ import annotations

import math
import os
from threading import Lock

_LANDMARK_FILE = "shape_predictor_5_face_landmarks.dat"
_QUARTERS = (0, 90, 180, 270)

_lock = Lock()
_detector = None
_predictor = None


def _landmark_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), _LANDMARK_FILE)


def _get_dlib():
    """Lazily build the shared detector + predictor (None = unavailable)."""
    global _detector, _predictor
    if _predictor is not None:
        return _detector, _predictor
    with _lock:
        if _predictor is None:
            path = _landmark_path()
            if not os.path.exists(path):
                return None, None
            import dlib  # noqa: PLC0415 - heavy, imported on first use only

            _detector = dlib.get_frontal_face_detector()
            _predictor = dlib.shape_predictor(path)
    return _detector, _predictor


def _rotate_quarter(img, quarter: int):
    """Rotate by an exact quarter turn without changing the pixel data."""
    import cv2  # noqa: PLC0415

    if quarter == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if quarter == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if quarter == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    return img


def _analyze(img, predictor, detector):
    """Analyze one orientation: (roll angle, upright?) or None if no face.

    ``upright`` is judged by the nose point sitting below the eye line
    (image y grows downward) - a 180-degree face still has a level eye
    line, so the roll angle alone cannot tell upside down.
    """
    import cv2  # noqa: PLC0415

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = detector(gray, 0)
    if not faces:
        return None
    face = max(faces, key=lambda rect: rect.width() * rect.height())
    marks = predictor(img, face)
    # dlib 5-point layout: points 0-1 are one eye, 2-3 the other, 4 the nose.
    left = ((marks.part(2).x + marks.part(3).x) / 2.0,
            (marks.part(2).y + marks.part(3).y) / 2.0)
    right = ((marks.part(0).x + marks.part(1).x) / 2.0,
             (marks.part(0).y + marks.part(1).y) / 2.0)
    eye_y = (left[1] + right[1]) / 2.0
    nose_y = float(marks.part(4).y)
    angle = math.degrees(math.atan2(right[1] - left[1], right[0] - left[0]))
    if angle > 45.0:
        angle -= 90.0
    elif angle < -45.0:
        angle += 90.0
    return angle, nose_y > eye_y


def _find_upright(img, predictor, detector):
    """Score all four quarter turns; return (image, quarter, roll angle).

    HOG happily fires on upside-down faces, so "first detection wins"
    (as in the node this was modeled on) can return a 180-degree result.
    Ranking instead: upright orientations first, then the smallest |roll|.
    """
    best = None  # (upright, -|roll|, quarter, turned, roll)
    for quarter in _QUARTERS:
        turned = _rotate_quarter(img, quarter)
        result = _analyze(turned, predictor, detector)
        if result is None:
            continue
        roll, upright = result
        key = (upright, -abs(roll), -quarter)
        if best is None or key > best[0]:
            best = (key, quarter, turned, roll)
    if best is None:
        return img, 0, None
    _, quarter, turned, roll = best
    return turned, quarter, roll


def _rotate_about_center(img, angle: float):
    import cv2  # noqa: PLC0415

    h, w = img.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    return cv2.warpAffine(img, matrix, (w, h),
                          flags=cv2.INTER_LANCZOS4,
                          borderMode=cv2.BORDER_REPLICATE)


def _center_crop(img, target_w: int, target_h: int):
    h, w = img.shape[:2]
    y0 = max(0, (h - target_h) // 2)
    x0 = max(0, (w - target_w) // 2)
    return img[y0:y0 + target_h, x0:x0 + target_w]


def _trim_edges(img, angle: float, edge_trim: int):
    """Shave the rotation-smeared band off all four edges.

    Vertical and horizontal bands are sized from their own side length.
    """
    folded = abs(angle) % 90.0
    if folded > 45.0:
        folded = 90.0 - folded
    if folded <= 0.0:
        return img
    h, w = img.shape[:2]
    factor = (folded ** 0.8) / 100.0 / max(edge_trim, 1)
    band_y = int(h * factor)
    band_x = int(w * factor)
    if band_y <= 0 and band_x <= 0:
        return img
    ny, nw = h - 2 * band_y, w - 2 * band_x
    if ny <= 0 or nw <= 0:
        return img
    return img[band_y:band_y + ny, band_x:band_x + nw]


def _fit_to(first, img):
    """Center-crop then pad (replicated border) so ``img`` matches ``first``."""
    import cv2  # noqa: PLC0415

    fh, fw = first.shape[:2]
    h, w = img.shape[:2]
    if (h, w) == (fh, fw):
        return img
    if h > fh or w > fw:
        img = _center_crop(img, min(w, fw), min(h, fh))
        h, w = img.shape[:2]
        if (h, w) == (fh, fw):
            return img
    top, bottom = max(0, (fh - h) // 2), max(0, (fh - h + 1) // 2)
    left, right = max(0, (fw - w) // 2), max(0, (fw - w + 1) // 2)
    return cv2.copyMakeBorder(img, top, bottom, left, right,
                              cv2.BORDER_REPLICATE)


class QGFaceRectify:
    """Straighten sideways / tilted faces; best-effort, pass-through on miss."""

    CATEGORY = "QG 工具"
    DESCRIPTION = (
        "把横躺、倒置、歪头的照片转正：dlib 找 5 个人脸关键点判断朝向，"
        "转正后按 edge_trim 裁掉旋转带出来的黑边。输出尺寸以批次第一帧为准，"
        "其余帧居中裁切或复制边缘补到同一尺寸；90° / 270° 转正时宽高互换，"
        "轻微倾斜时会因裁掉黑边而略小于原图。找不到脸就原样输出，不报错。"
    )
    SEARCH_ALIASES = [
        "face", "face rectify", "straighten", "rotate", "orientation",
        "exif", "人脸", "矫正", "转正", "旋转", "照片方向", "qg",
    ]
    OUTPUT_NODE = False

    @classmethod
    def INPUT_TYPES(cls):  # noqa: N802 - ComfyUI convention
        return {
            "required": {
                "image": ("IMAGE", {"tooltip":
                    "要矫正的图像。批次里每帧独立判断朝向（正面 / 横躺 / 倒置）。"}),
                "enable_fix": ("BOOLEAN", {"default": True,
                    "tooltip": "关掉则原图直通，用来对比矫正前后的效果。"}),
                "edge_trim": ("INT", {"default": 2, "min": 1, "max": 5, "step": 1,
                    "tooltip": "旋转后额外裁掉的边缘像素（1~5）。转正会带进黑边，"
                               "值越大裁得越多，构图也越靠近中心。"}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "rectify"

    def rectify(self, image, enable_fix, edge_trim):
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        if not enable_fix:
            return (image,)

        # 单帧 3 维输入补齐一维；空批次直接原样返回，别在下面 results[0] 上
        # 抛 "list index out of range"（那更像是代码坏了，用户看不懂）。
        if image.dim() == 3:
            image = image.unsqueeze(0)
        if int(image.shape[0]) == 0:
            return (image,)

        detector, predictor = _get_dlib()
        if detector is None:
            print("[QG 工具] 人脸自动矫正：缺少 dlib 或 landmark 模型，"
                  "原图直通。")
            return (image,)

        results = []
        for i in range(image.shape[0]):
            tensor = image[i]
            try:
                frame = cv2.cvtColor(
                    (tensor.detach().cpu().numpy() * 255.0)
                    .round().clip(0, 255).astype("uint8"),
                    cv2.COLOR_RGB2BGR)
                src_h, src_w = frame.shape[:2]

                turned, quarter, angle = _find_upright(frame, predictor, detector)

                # quarter turns swap the output footprint
                tgt_w, tgt_h = (src_h, src_w) if quarter in (90, 270) else (src_w, src_h)

                out = turned
                if angle is not None:
                    out = _rotate_about_center(out, angle)
                    out = _center_crop(out, tgt_w, tgt_h)
                    out = _trim_edges(out, angle, edge_trim)
                elif quarter:
                    out = _center_crop(out, tgt_w, tgt_h)

                out = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
                results.append(out.astype("float32") / 255.0)
            except Exception:  # noqa: BLE001 - one bad frame must not kill the batch
                results.append(tensor.detach().cpu().numpy().astype("float32"))

        first = results[0]
        fitted = [_fit_to(first, r) for r in results]
        return (image.new_tensor(np.stack(fitted, axis=0)),)


NODE_CLASS_MAPPINGS = {"QG_FaceRectify": QGFaceRectify}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_FaceRectify": "QG 人脸自动矫正"}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
