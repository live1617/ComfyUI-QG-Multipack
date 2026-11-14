"""QG_IDCardSheet - 身份证自动扶正拼版。

链路：卡片照片 + 卡片蒙版 → 找四角 → 透视拉正 → 圆角 + 投影 → 按厘米铺到纸上。

和参考实现（孤海-身份证自动扶正拼版）的关系：参数一一对应，三处改了做法：

| 项 | 参考 | 这里 |
|---|---|---|
| 找四角 | ``approxPolyDP`` + 按角度排序，点数多了直接截前四个 | 按 ``x+y`` / ``x−y`` 的极值取角，与顶点数无关，起点固定是左上 |
| 竖放判断 | 整张图 ``height > width`` 就 ``rot90`` | 比较四边形自己的左边与上边 |
| 调色时机 | 整张原图上调 | 拉正之后只调卡片 —— 背景不参与统计，白平衡才不会被白纸带偏 |

水印拆成了独立节点（``QG_Watermark``），这里只管拼版。二十个控件混在一起
是看不完的，水印又是"可加可不加"的一道工序。
"""

from __future__ import annotations

import numpy as np
import torch
from PIL import Image

from ._idcard_helpers import (
    as_bool_mask,
    auto_contrast as _auto_contrast,
    auto_tone as _auto_tone,
    cm_to_px,
    compose_sheet,
    looks_inverted,
    mask_to_quad,
    quad_sides,
    rounded_alpha,
    upright_quad,
    warp_card,
)
from .id_photo_crop_node import parse_color

MM_PER_INCH = 25.4


def _to_pil(frame_rgb):
    arr = np.clip(frame_rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    elif arr.shape[2] == 1:
        arr = np.repeat(arr, 3, axis=2)
    elif arr.shape[2] > 3:
        arr = arr[:, :, :3]
    return Image.fromarray(arr, "RGB")


def _mask_frame(mask, index):
    """ComfyUI 的 MASK 是 ``[B,H,W]``，也见过 ``[H,W]`` 的。"""
    arr = mask
    if arr.dim() == 3:
        arr = arr[min(index, int(arr.shape[0]) - 1)]
    return arr.cpu().numpy()


def _flatten_corners(quad):
    return ", ".join("(%.0f,%.0f)" % (p[0], p[1]) for p in quad)


class QGIDCardSheet:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "front_image": ("IMAGE",),
                "front_mask": ("MASK",),
                "paper_w": ("FLOAT", {
                    "default": 21.0, "min": 1.0, "max": 100.0, "step": 0.1,
                    "tooltip": "纸张宽度，厘米。A4 是 21.0。",
                }),
                "paper_h": ("FLOAT", {
                    "default": 29.7, "min": 1.0, "max": 100.0, "step": 0.1,
                    "tooltip": "纸张高度，厘米。A4 是 29.7。",
                }),
                "dpi": ("INT", {
                    "default": 450, "min": 72, "max": 1200, "step": 1,
                    "tooltip": "打印分辨率。印件建议 300 以上，450 是参考实现的口径。",
                }),
                "gap": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 50.0, "step": 0.1,
                    "tooltip": "正反面之间的间距，厘米。只放一面时忽略。",
                }),
                "card_w": ("FLOAT", {
                    "default": 8.56, "min": 1.0, "max": 30.0, "step": 0.01,
                    "tooltip": "卡片宽度，厘米。二代身份证 8.56（85.6mm）。",
                }),
                "card_h": ("FLOAT", {
                    "default": 5.4, "min": 1.0, "max": 30.0, "step": 0.01,
                    "tooltip": "卡片高度，厘米。二代身份证 5.4（54mm）。",
                }),
                "corner_pct": ("INT", {
                    "default": 7, "min": 0, "max": 30, "step": 1,
                    "tooltip": "圆角半径占短边的百分比。身份证的实际圆角约 6%。0 是直角。",
                }),
                "rotate_180": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "出来是倒的就连这个。四边形只能看出长边朝哪，"
                               "分不出正立还是倒立 —— 卡片倒着拍时得人来补这一下。",
                }),
                "shadow_offset": ("FLOAT", {
                    "default": 0.6, "min": 0.0, "max": 10.0, "step": 0.1,
                    "tooltip": "投影偏移，毫米。0 是不偏移（只留糊边）。",
                }),
                "shadow_blur": ("FLOAT", {
                    "default": 1.2, "min": 0.0, "max": 10.0, "step": 0.1,
                    "tooltip": "投影模糊半径，毫米。0 是硬边。",
                }),
                "shadow_opacity": ("INT", {
                    "default": 128, "min": 0, "max": 255, "step": 1,
                    "tooltip": "投影不透明度。0 关掉。",
                }),
                "auto_contrast": ("INT", {
                    "default": 0, "min": 0, "max": 100, "step": 1,
                    "tooltip": "自动对比度强度，0 关。只在卡片上算，白纸不影响。",
                }),
                "auto_tone": ("INT", {
                    "default": 0, "min": 0, "max": 100, "step": 1,
                    "tooltip": "灰度世界白平衡强度，0 关。偏黄的扫描件用它。",
                }),
                "grayscale": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "整张纸转黑白（复印件效果）。",
                }),
                "bg_color": ("STRING", {
                    "default": "#ffffff",
                    "tooltip": "纸张底色。支持 #RRGGBB、white、255,255,255。",
                }),
            },
            "optional": {
                "back_image": ("IMAGE",),
                "back_mask": ("MASK",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "execute"
    CATEGORY = "QG 工具"

    def execute(self, front_image, front_mask, paper_w, paper_h, dpi, gap,
                card_w, card_h, corner_pct, rotate_180, shadow_offset, shadow_blur,
                shadow_opacity, auto_contrast, auto_tone, grayscale, bg_color,
                back_image=None, back_mask=None):

        dpi = max(72, int(dpi))
        card_w_px = cm_to_px(card_w, dpi)
        card_h_px = cm_to_px(card_h, dpi)
        paper_w_px = cm_to_px(paper_w, dpi)
        paper_h_px = cm_to_px(paper_h, dpi)
        gap_px = cm_to_px(gap, dpi)
        radius_px = int(round(min(card_w_px, card_h_px) * max(0, corner_pct) / 100.0))
        offset_px = int(round(shadow_offset / MM_PER_INCH * dpi))
        blur_px = max(0.0, shadow_blur / MM_PER_INCH * dpi)

        bg_rgb = parse_color(bg_color, "ID Card Sheet bg_color")

        batch = front_image if front_image.dim() == 4 else front_image.unsqueeze(0)
        if int(batch.shape[0]) > 1:
            print("[ID Card Sheet] 输入有 %d 帧，只拼第一帧 —— 一张纸只放一组卡片；"
                  "要批量请用「重复」类节点分别排" % int(batch.shape[0]))

        masks = [(_mask_frame(front_mask, 0), "正面")]
        images = [batch[0]]
        has_back = back_image is not None and back_mask is not None
        if has_back:
            back_batch = back_image if back_image.dim() == 4 else back_image.unsqueeze(0)
            images.append(back_batch[0])
            masks.append((_mask_frame(back_mask, 0), "背面"))
        elif (back_image is None) != (back_mask is None):
            raise ValueError(
                "背面图与背面蒙版要一起给：只接一根线的话分不清哪张是哪张。"
                "只印一面就把两根线都拔掉。")

        cards = []
        for frame, (mask, label) in zip(images, masks):
            pil = _to_pil(frame.cpu().numpy())
            if mask.shape[:2] != (pil.height, pil.width):
                raise ValueError(
                    "%s：蒙版是 %dx%d，图像是 %dx%d，对不上。蒙版要跟图像同尺寸 "
                    "（用抠图节点出蒙版时别中途缩放）。"
                    % (label, mask.shape[1], mask.shape[0], pil.width, pil.height))

            # LoadImage 给带 alpha 的 PNG 时，MASK 是 1−alpha（透明处为白），
            # 直接接过来卡片就变成了整张图。
            binary = as_bool_mask(mask)
            if looks_inverted(binary):
                binary = ~binary
                print("[ID Card Sheet] %s蒙版四边几乎都是前景，判定为反相"
                      "（LoadImage 的 MASK 输出 1−alpha），已自动取反" % label)

            quad = mask_to_quad(binary)
            if quad is None:
                raise ValueError(
                    "%s蒙版里没有前景像素 —— 检查蒙版是不是接反了、或者抠图那步"
                    "什么都没抠出来。注意 ComfyUI 的 LoadImage 直接读带透明通道的 "
                    "PNG 时，MASK 输出的是 1−alpha（透明处为白），接过来正好是反的；"
                    "用抠图节点的蒙版输出就不会有这个问题。" % label)

            top_len, left_len = quad_sides(quad)
            portrait = left_len > top_len
            quad = upright_quad(quad)
            warped = warp_card(np.asarray(pil), quad, card_w_px, card_h_px)
            if rotate_180:
                warped = np.ascontiguousarray(np.rot90(warped, 2))

            card = Image.fromarray(warped, "RGB")
            if auto_contrast > 0:
                card = _auto_contrast(card, auto_contrast)
            if auto_tone > 0:
                card = _auto_tone(card, auto_tone)

            card = card.convert("RGBA")
            card.putalpha(rounded_alpha(card_w_px, card_h_px, radius_px))
            cards.append(card)

            print("[ID Card Sheet] %s %dx%d -> 卡片 %dx%d px | 四角 %s | %s"
                  % (label, pil.width, pil.height, card_w_px, card_h_px,
                     _flatten_corners(quad),
                     ("竖放，已转正" if portrait else "横放")
                     + ("，再转 180°" if rotate_180 else "")))

        sheet = compose_sheet(cards, paper_w_px, paper_h_px, gap_px, bg_rgb,
                              radius_px, offset_px, blur_px, shadow_opacity)
        if grayscale:
            sheet = sheet.convert("L").convert("RGB")

        print("[ID Card Sheet] %d 张卡片 -> %dx%d px 纸 (%.1fx%.1f cm @ %d dpi)%s"
              % (len(cards), paper_w_px, paper_h_px, paper_w, paper_h, dpi,
                 "，黑白" if grayscale else ""))

        out = np.asarray(sheet).astype(np.float32) / 255.0
        return (torch.from_numpy(out).unsqueeze(0),)


NODE_CLASS_MAPPINGS = {"QG_IDCardSheet": QGIDCardSheet}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_IDCardSheet": "ID Card Sheet"}
