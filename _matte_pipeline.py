"""人像抠图换背景的纯函数：换底、调色、裁剪几何。

这里的每个函数都只吃数字和 PIL 图，不碰 ComfyUI、不碰 onnx —— 所以能离线
断言。注意两个容易搞错的地方：

* **裁剪比例用的是面积**，不是宽度。``head_measure_ratio`` 的含义是"人脸框
  面积 / 裁剪框面积"，0.2 表示人脸框占画面 20% 的面积。这样同一个数字在
  竖版和方版证件照上都能用，换成宽度比就得每换一种纸型重调一次。
* **头顶用抠图后的 alpha 顶行**，不是人脸框顶。人脸框止于发际线附近，而
  证件照要求的是头发顶到画面上沿的距离，差那一截头发会明显偏下。
"""

from __future__ import annotations

import math
import os

import numpy as np
from PIL import Image, ImageFilter

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

BG_MODES = ["pure", "vertical", "radial"]

# 证件照常用底色。CSS 的 "blue" 是 #0000ff，印出来是荧光蓝，不是证件照那种
# 藏青 —— 所以这几个名字得自己定，不能让 PIL 去查。
BG_NAMED = {
    "white": "#ffffff",
    "blue": "#438edb",
    "darkblue": "#1b4b8f",
    "red": "#d93b3b",
    "gray": "#9a9a9a",
    "lightblue": "#a8c8e8",
}


def resolve_color(text):
    """把 ``blue`` 这类别名换成色值；认不出的原样返回，交给 parse_color。"""
    key = str("" if text is None else text).strip().lower()
    return BG_NAMED.get(key, text)

_LUT = {"tried": False, "table": None}


# ---------------------------------------------------------------- 背景
def make_background(width, height, mode, top_rgb, bottom_rgb=None):
    """造一张背景。``mode`` = pure / vertical / radial。"""
    width = max(1, int(width))
    height = max(1, int(height))
    top = tuple(int(v) for v in top_rgb[:3])
    bottom = tuple(int(v) for v in (bottom_rgb or top_rgb)[:3])

    if mode == "pure" or top == bottom:
        return Image.new("RGB", (width, height), top)

    if mode == "vertical":
        # 逐行插值：一行一个色，够快也不会有 banding 之外的伪影
        ramp = np.empty((height, 1, 3), dtype=np.float32)
        t = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
        for c in range(3):
            ramp[:, 0, c] = top[c] * (1.0 - t[:, 0]) + bottom[c] * t[:, 0]
        arr = np.repeat(ramp, width, axis=1).astype(np.uint8)
        return Image.fromarray(arr, "RGB")

    # radial：中心是 top，四角是 bottom
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
    # 归一化到"到四角的距离"，中心 0、角 1，这样渐变在边角刚好用完
    half_diag = math.hypot(cx, cy) or 1.0
    t = np.clip(np.hypot(xx - cx, yy - cy) / half_diag, 0.0, 1.0)[:, :, None]
    arr = np.array(top, dtype=np.float32) * (1.0 - t) + \
        np.array(bottom, dtype=np.float32) * t
    return Image.fromarray(np.rint(arr).astype(np.uint8), "RGB")


def composite(rgb, alpha, background):
    """把 ``rgb`` 按 ``alpha`` 贴到 ``background`` 上。"""
    fg = Image.fromarray(rgb, "RGB")
    bg = background.convert("RGB")
    if bg.size != fg.size:
        bg = bg.resize(fg.size, Image.BILINEAR)
    out = bg.copy()
    out.paste(fg, (0, 0), Image.fromarray(alpha, "L"))
    return out


def alpha_rows(alpha, threshold=32, min_share=0.01):
    """alpha 顶行/底行 —— 证件照要的是头发顶，不是人脸框顶。

    只认"这一行有足够多不透明像素"的行，否则一根飞起来的发丝就能把头顶
    拉到画面最上沿。找不到就返回 ``None``，调用方退回人脸框。
    """
    solid = np.asarray(alpha) >= threshold
    width = solid.shape[1]
    need = max(1, int(round(width * min_share)))
    count = solid.sum(axis=1)
    rows = np.nonzero(count >= need)[0]
    if rows.size == 0:
        return None
    return int(rows[0]), int(rows[-1])


# ---------------------------------------------------------------- 裁剪
class CropPlan:
    """裁剪框，全部用源图坐标。``head_top`` 用于核对顶部距离。"""

    __slots__ = ("x0", "y0", "w", "h", "head_top", "out_w", "out_h")

    def __init__(self, x0, y0, w, h, head_top, out_w, out_h):
        self.x0 = float(x0)
        self.y0 = float(y0)
        self.w = float(w)
        self.h = float(h)
        self.head_top = float(head_top)
        self.out_w = int(out_w)
        self.out_h = int(out_h)

    @property
    def top_gap(self):
        """头顶到裁剪框上沿的距离，占框高的比例 —— 就是 top_distance 该得的数。"""
        return (self.head_top - self.y0) / self.h if self.h else 0.0


def plan_crop(face_box, head_top, out_w, out_h, head_height, top_distance):
    """算裁剪框。face_box 是 ``(x0, y0, x1, y1)``，源图坐标。

    **按头高定框，不按人脸面积。** 国标说的是"头部约占照片高度 2/3"，那是个
    高度比；换成面积比之后，同一个数在竖版和方版上会给出完全不同的头高 ——
    实测面积比 0.20 在 295×413 上是 62%、在 602×602 上是 74%。高度比则与
    纸型宽度无关：裁剪框高 = 头高 / head_height，任何纸型都是同一个比例。

    ``head_top`` 是头发顶（不是人脸框顶），``face_box[3]`` 当下巴。
    """
    x0, y0, x1, y1 = (float(v) for v in face_box)
    out_w, out_h = max(1, int(out_w)), max(1, int(out_h))
    aspect = out_w / float(out_h)

    ratio = min(max(float(head_height), 0.20), 0.95)
    # head_top -> 下巴 就是"头部高度"（含头发），国标量的是这一段
    head_h = max(1.0, y1 - float(head_top))
    crop_h = head_h / ratio
    crop_w = crop_h * aspect

    cx = (x0 + x1) / 2.0
    left = cx - crop_w / 2.0
    top = float(head_top) - float(top_distance) * crop_h
    return CropPlan(left, top, crop_w, crop_h, head_top, out_w, out_h)


def crop_fill(img, box, fill_rgb=(255, 255, 255)):
    """按浮点框裁剪，越界的地方补 ``fill_rgb``，返回与框等大的图。

    保留原图模式：传进来的蒙版是 ``L``，补的就不是三个通道了。
    """
    box = (int(round(box[0])), int(round(box[1])),
           int(round(box[2])), int(round(box[3])))
    w, h = max(1, box[2] - box[0]), max(1, box[3] - box[1])
    mode = img.mode if img.mode in ("L", "RGB", "RGBA") else "RGB"
    fill = tuple(int(v) for v in fill_rgb[:3])
    if mode == "L":
        patch = fill[0] if isinstance(fill, tuple) else fill
        canvas = Image.new("L", (w, h), min(255, max(0, patch)))
        src = img.convert("L")
    else:
        canvas = Image.new(mode, (w, h), fill if mode == "RGB" else fill + (255,))
        src = img.convert(mode)
    left, top = max(0, box[0]), max(0, box[1])
    right, bottom = min(src.width, box[2]), min(src.height, box[3])
    if right > left and bottom > top:
        piece = src.crop((left, top, right, bottom))
        canvas.paste(piece, (left - box[0], top - box[1]))
    return canvas


def render_crop(img, plan, fill_rgb=(255, 255, 255)):
    """裁剪 + 缩放到目标尺寸，一次 LANCZOS。"""
    box = (plan.x0, plan.y0, plan.x0 + plan.w, plan.y0 + plan.h)
    piece = crop_fill(img, box, fill_rgb)
    return piece.resize((plan.out_w, plan.out_h), Image.LANCZOS)


# ---------------------------------------------------------------- 调色
def load_lut(path):
    """读美白用的 64³ 立方体 LUT（8x8 网格拼成的 512x512 图）。"""
    if _LUT["tried"]:
        return _LUT["table"]
    _LUT["tried"] = True
    if not os.path.exists(path):
        print("[Portrait Matte] 美白 LUT 没找到（%s），美白参数会被忽略" % path)
        return None
    grid = np.asarray(Image.open(path).convert("RGB"))
    size, rows, cube = 64, 8, 256
    table = np.zeros((cube, cube, cube, 3), dtype=np.uint8)
    for i in range(size):
        gx, gy = (i % rows) * size, (i // rows) * size
        piece = grid[gy:gy + size, gx:gx + size]
        if piece.size == 0:
            continue
        piece = np.asarray(Image.fromarray(piece).resize((cube, cube), Image.BILINEAR))
        scale = cube // size
        table[i * scale:(i + 1) * scale] = piece
    _LUT["table"] = table
    return table


def _whiten(rgb, table, strength):
    """美白。口径照 Hivision：0..15，10 是满强度，15 等于叠满一次再加 5。"""
    if table is None or strength <= 0:
        return rgb
    out = rgb
    for _ in range(int(strength) // 10):
        out = _mix_lut(out, table, 1.0)
    rest = (int(strength) % 10) / 10.0
    if rest > 0:
        out = _mix_lut(out, table, rest)
    return out


def _mix_lut(rgb, table, share):
    if share <= 0:
        return rgb
    lookup = table[rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]]
    return (rgb.astype(np.float32) * (1.0 - share)
            + lookup.astype(np.float32) * share).astype(np.uint8)


def _saturate(rgb, factor):
    scale = 1.0 + float(factor) / 100.0
    if cv2 is not None:
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * scale, 0, 255)
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)
    hsv = np.asarray(Image.fromarray(rgb).convert("HSV")).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * scale, 0, 255)
    return np.asarray(Image.fromarray(hsv.astype(np.uint8), "HSV").convert("RGB"))


def _bright_contrast(rgb, brightness, contrast):
    alpha = 1.0 + float(contrast) / 100.0
    arr = rgb.astype(np.float32) * alpha + float(brightness)
    return np.clip(arr, 0, 255).astype(np.uint8)


def _sharpen(rgb, strength):
    """反锐化掩模。strength 0..5，5 大约相当于半径 1 像素、强度 0.6 的锐化。"""
    if strength <= 0:
        return rgb
    amount = float(strength) * 0.6
    if cv2 is not None:
        blur = cv2.GaussianBlur(rgb, (0, 0), 1.0)
        return np.clip(rgb.astype(np.float32) * (1.0 + amount)
                       - blur.astype(np.float32) * amount, 0, 255).astype(np.uint8)
    blur = np.asarray(Image.fromarray(rgb).filter(ImageFilter.GaussianBlur(1.0)),
                      dtype=np.float32)
    return np.clip(rgb.astype(np.float32) * (1.0 + amount) - blur * amount,
                   0, 255).astype(np.uint8)


def beauty(rgb, lut_table, whitening=0, brightness=0, contrast=0,
           saturation=0, sharpen=0):
    """美白 → 饱和度 → 亮度对比 → 锐化。全 0 时原样返回，不做无用拷贝。"""
    if not any((whitening, brightness, contrast, saturation, sharpen)):
        return rgb
    out = _whiten(np.asarray(rgb, dtype=np.uint8), lut_table, whitening)
    if saturation:
        out = _saturate(out, saturation)
    if brightness or contrast:
        out = _bright_contrast(out, brightness, contrast)
    if sharpen:
        out = _sharpen(out, sharpen)
    return out
