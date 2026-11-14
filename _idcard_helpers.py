"""身份证拼版的几何与绘制 —— 纯函数，不碰 torch。

节点层只管张量进出，这里管"把一张拍歪的卡片摆正，铺到纸上"。

两处和参考实现不一样，都是为了别把卡片转歪：

* **四角不按 ``arctan2`` 的角度排序。** 角度排序只保证"绕一圈"，起点是
  随机给的，起点错一位整张就转 90°；而转完它还是个四边形，不跑起来看不出
  来。这里按极值取角：``x+y`` 最小的是左上、最大的是右下，``x−y`` 最大的是
  右上、最小的是左下。对矩形卡片，这四个极值点就是四个角，跟顶点数是几个
  无关，也就不需要 ``approxPolyDP`` 猜。

* **竖放判断看卡片，不看照片。** 参考实现比较整张图的高宽再 ``rot90``，
  但那是照片的方向。这里比较四边形自己的两条边：左边比上边长，说明卡片
  躺横了，从"左下"起绕圈，让长边落到输出的水平方向上。
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from ._sheet_helpers import cm_to_px

try:                       # 只用它找最大连通域，缺了也能跑，只是抗噪弱一点
    from scipy import ndimage as _ndimage
except Exception:          # noqa: BLE001
    _ndimage = None

__all__ = [
    "cm_to_px", "as_bool_mask", "looks_inverted", "mask_to_quad", "quad_sides",
    "upright_quad", "warp_card", "rounded_alpha", "auto_contrast", "auto_tone",
    "compose_sheet",
]


# --------------------------------------------------------------- 找四个角 ---

def as_bool_mask(mask):
    """把蒙版规整成 bool：bool / 0-255 / 0.0-1.0 都吃。"""
    arr = np.asarray(mask)
    if arr.ndim == 3:
        arr = arr[..., 0]
    if arr.dtype == bool:
        return arr
    if arr.dtype.kind == "f":
        return arr > 0.5
    return arr > 127


def looks_inverted(binary):
    """蒙版是不是"反的"。

    ComfyUI 的 ``LoadImage`` 对带透明通道的 PNG 输出 ``1 − alpha``：背景透明
    的地方反而成了前景，接过来卡片就变成整张照片。判据用边框而不是总面积 ——
    卡片照片总有背景托着，四条边不该被前景占满；而反相之后边框恰恰全是"前景"。
    面积超过一半这个前提是为了避开"整张图都是卡片"的极端情况，那种图不该翻。
    """
    h, w = binary.shape[:2]
    band = max(1, min(h, w) // 100)
    edges = np.concatenate([
        binary[:band].ravel(), binary[-band:].ravel(),
        binary[:, :band].ravel(), binary[:, -band:].ravel()])
    return float(edges.mean()) > 0.5 and float(binary.mean()) > 0.5


def _largest_blob(binary):
    """只留最大的一块连通区域。

    抠图模型偶尔会在画面角落留下一小撮误判前景，那撮点一样会参与取极值，
    四角就被拉过去了。这里先按连通域把杂块丢掉，后面的腐蚀只要收拾边缘
    毛刺就行。
    """
    if _ndimage is None:
        return binary
    labels, count = _ndimage.label(binary)
    if count <= 1:
        return binary
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    return labels == int(sizes.argmax())


def mask_to_quad(mask, shrink=3):
    """蒙版 -> ``[[左上], [右上], [右下], [左下]]``，取不到返回 None。

    参数是 HxW 的数组，bool / 0-255 / 0.0-1.0 都吃。

    三步：丢掉零散小块 → 腐蚀 ``shrink`` 像素 → 取极值。腐蚀是为了毛刺，
    一根 1px 的尖刺就能让角点偏出去十几像素，整张卡片跟着歪。

    取的是**真正的极值点**，不是极端区域的质心 —— 后者在卡片斜着放的时候会
    往角的内侧偏（角附近那块是个三角形，质心在中间），四边形整体缩一圈，
    拉正出来的图边缘就被切掉了。
    """
    arr = np.asarray(mask)
    binary = as_bool_mask(arr)
    if not binary.any():
        return None

    binary = _largest_blob(binary)

    if shrink > 0:
        eroded = Image.fromarray((binary.astype(np.uint8) * 255)).filter(
            ImageFilter.MinFilter(shrink * 2 + 1))
        kept = np.asarray(eroded) > 127
        if kept.sum() >= 16:                     # 腐蚀完还有东西才用
            binary = kept

    ys, xs = np.nonzero(binary)
    if xs.size < 16:
        return None
    xs = xs.astype(np.float64)
    ys = ys.astype(np.float64)
    s = xs + ys
    d = xs - ys
    return np.array([
        (xs[np.argmin(s)], ys[np.argmin(s)]),     # 左上：x+y 最小
        (xs[np.argmax(d)], ys[np.argmax(d)]),     # 右上：x−y 最大
        (xs[np.argmax(s)], ys[np.argmax(s)]),     # 右下：x+y 最大
        (xs[np.argmin(d)], ys[np.argmin(d)]),     # 左下：x−y 最小
    ], dtype=np.float64)


# ----------------------------------------------------------------- 摆正 ---

def quad_sides(quad):
    """``(上边长度, 左边长度)``。"""
    top = float(np.linalg.norm(quad[1] - quad[0]))
    left = float(np.linalg.norm(quad[3] - quad[0]))
    return top, left


def upright_quad(quad):
    """把竖着放的卡片转到横放，返回新的四点。

    竖放时图像左边其实是卡片的长边，于是从"左下"起绕圈：
    ``[左上, 右上, 右下, 左下] -> [左下, 左上, 右上, 右下]``。绕完长边就落在
    输出的水平方向上了，输出尺寸不用变。
    """
    top, left = quad_sides(quad)
    if left > top:
        return np.roll(quad, 1, axis=0)
    return quad


def warp_card(rgb, quad, out_w, out_h, pad=2):
    """四边形 → ``out_w × out_h`` 的正射图（RGB uint8）。

    PIL 的 QUAD 变换要的是源图四点按「左上、左下、右下、右上」给 —— 和这台
    机器的行走顺序不一样，写反了会出镜像。边上补 ``pad`` 像素再算，免得顶点
    正好压在图像边界时采样到外面去。
    """
    padded = np.pad(np.asarray(rgb), ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    tl, tr, br, bl = (np.asarray(quad, dtype=np.float64) + pad)
    data = [tl[0], tl[1], bl[0], bl[1], br[0], br[1], tr[0], tr[1]]
    out = Image.fromarray(padded).transform(
        (max(1, int(out_w)), max(1, int(out_h))), Image.QUAD, data, Image.BICUBIC)
    return np.asarray(out.convert("RGB"))


def rounded_alpha(w, h, radius):
    """圆角矩形蒙版。半径钳到短边的一半，超过的话 PIL 画出来是个歪的。"""
    radius = max(0, min(int(radius), min(w, h) // 2))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    return mask


# ----------------------------------------------------------------- 调色 ---

def auto_contrast(img, strength):
    """自动对比度，按强度和原图混合。0 不动。"""
    level = min(1.0, max(0.0, float(strength) / 100.0))
    if level <= 0:
        return img
    return Image.blend(img, ImageOps.autocontrast(img), level)


def auto_tone(img, strength):
    """灰度世界白平衡，按强度混合。0 不动。

    增益钳在 0.7~1.3：扫描件偏色通常没多严重，放开了会把纯白背景染成彩色。
    """
    level = min(1.0, max(0.0, float(strength) / 100.0))
    if level <= 0:
        return img
    arr = np.asarray(img).astype(np.float32)
    means = arr.reshape(-1, 3).mean(axis=0)
    gains = np.clip(float(means.mean()) / np.maximum(means, 1e-6), 0.7, 1.3)
    adj = np.clip(arr * gains, 0, 255).astype(np.uint8)
    return Image.blend(img, Image.fromarray(adj), level)


# ----------------------------------------------------------------- 排版 ---

def compose_sheet(cards, paper_w, paper_h, gap, bg_rgb, radius,
                  shadow_offset, shadow_blur, shadow_alpha):
    """把若干张卡片竖排居中贴到纸上，带一层投影。

    ``cards`` 是 RGBA，宽度必须一致。阴影先铺满整层再模糊 —— 逐张只糊自己
    那一小块的话，两卡相邻处会出现一道硬缝。
    """
    canvas = Image.new("RGBA", (max(1, paper_w), max(1, paper_h)),
                       tuple(int(v) for v in bg_rgb[:3]) + (255,))
    if not cards:
        return canvas.convert("RGB")

    cw, ch = cards[0].size
    total = len(cards) * ch + (len(cards) - 1) * gap
    left = (paper_w - cw) // 2
    top = (paper_h - total) // 2
    if left < 0 or top < 0 or cw > paper_w or ch > paper_h:
        raise ValueError(
            "卡片 %d×%d px 放不进 %d×%d px 的纸（间距 %d px）—— 检查画布尺寸、"
            "卡片尺寸和 dpi" % (cw, ch, paper_w, paper_h, gap))

    boxes = [(left, top + i * (ch + gap)) for i in range(len(cards))]

    if shadow_alpha > 0 and (shadow_offset or shadow_blur):
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for x, y in boxes:
            draw.rounded_rectangle(
                [x + shadow_offset, y + shadow_offset,
                 x + shadow_offset + cw, y + shadow_offset + ch],
                radius=max(0, min(int(radius), min(cw, ch) // 2)),
                fill=(0, 0, 0, int(shadow_alpha)))
        if shadow_blur > 0:
            layer = layer.filter(ImageFilter.GaussianBlur(float(shadow_blur)))
        canvas = Image.alpha_composite(canvas, layer)

    for card, (x, y) in zip(cards, boxes):
        canvas.alpha_composite(card, (x, y))
    return canvas.convert("RGB")
