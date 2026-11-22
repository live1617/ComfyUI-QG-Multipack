# -*- coding: utf-8 -*-
"""QG 遮罩到 Seg —— 把 ComfyUI 原生 MASK 转成自造 QG_SEGS，不依赖 Impact-Pack。

参考 Impact-Pack「MaskToSeg」的控件语义独立实现（未复制上游源码）：遮罩里每个
独立连通区域出一段 SEG，段里带框、标签、打分、遮罩与裁剪系数。输出类型沿用本包
自造 QG_SEGS，可直接接 QG_MaskOrderFilter 等本包下游；不认识 Impact 的 SEGS，
也不依赖它的运行时模块。

控件语义（对齐参考节点，逐项自写）：
    * combine（是否合并）：开 → 整张遮罩的非零像素当一个连通体，只出一段；
      关 → 按连通域逐个分段（默认）。
    * crop_factor（裁剪系数）：记录进段的元数据；裁剪框相对外接框的放大倍数。
      本节点不裁图，仅记元数据，供下游按同一口径使用。
    * bbox_fill（填充BBox）：把段内 [x0,y0,x1,y1] 外接矩形填成实心 1.0。
    * drop_size（最小尺寸）：外接框宽或高 <= 该值的段丢弃。
    * is_contour（填充轮廓）：开 → 用连通域填充后的轮廓当遮罩；关 → 用原遮罩
      与该轮廓相乘（保留原遮罩灰度/镂空）。

批次约定：与参考节点一致——先把整批 MASK 逐像素取最大值合成一张 [H,W]，
再对这张合成图分段；输出一段集合，尺寸取合成图尺寸。
"""
from __future__ import annotations

import numpy as np
import torch

# 复用本包自造容器，保证与 QG_SimpleSegDetector / QG_MaskOrderFilter 同一类型。
from .qg_simple_seg_detector import QGSeg, QGSegs, SEGS_TYPE  # noqa: F401

_MAX_RESOLUTION = 16384


def _to_numpy(mask):
    """MASK 输入（Tensor / ndarray / list）统一成 float32 numpy，形状 [...,H,W]。"""
    if isinstance(mask, torch.Tensor):
        arr = mask.detach().cpu().numpy()
    else:
        arr = np.asarray(mask)
    arr = np.nan_to_num(np.asarray(arr, dtype=np.float32),
                        nan=0.0, posinf=1.0, neginf=0.0)
    return np.clip(arr, 0.0, 1.0)


def _combine_frames(mask):
    """批次 [N,H,W] 取逐像素最大值合成一张 [H,W]；2D 原样返回。"""
    arr = _to_numpy(mask)
    if arr.ndim == 2:
        return arr
    if arr.ndim == 3:
        return arr.max(axis=0)
    raise ValueError(
        "QG 遮罩到 Seg 只接受 [H,W] 或 [N,H,W] 的遮罩，收到 %d 维。" % arr.ndim)


def _contours(mask_u8):
    """从 uint8 遮罩取每个前景连通区域的外轮廓，返回 (轮廓列表, 填充掩膜)。

    cv2 可用时走 cv2.findContours(RETR_TREE)，按 hierarchy 深度区分前景外轮廓
    与孔洞：深度为偶数的是前景区域外边界，奇数的是它内部被挖掉的孔。只取
    parent == -1 会漏掉「环形中间那块独立实心」（深度 4），而它本身是一个独立
    连通区域，语义上必须单独成段。

    缺 cv2 时用纯 numpy 的 4 邻域洪泛标记，逐连通域生成掩膜（天然不会漏）。
    """
    try:
        import cv2  # noqa: PLC0415

        contours, tree = cv2.findContours(mask_u8, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        items = []
        if tree is None or len(contours) == 0:
            return items
        hierarchy = tree[0]
        # 每个轮廓到根的距离（深度）。奇偶决定它是不是孔。
        depths = []
        for j in range(len(contours)):
            depth, parent = 0, int(hierarchy[j][3])
            while parent != -1 and depth <= len(contours):
                depth += 1
                parent = int(hierarchy[parent][3])
            depths.append(depth)
        # 直接子轮廓索引：偶数深度（前景外轮廓）的奇数深度子轮廓就是它的孔。
        children = [[] for _ in range(len(contours))]
        for j in range(len(contours)):
            parent = int(hierarchy[j][3])
            if parent != -1:
                children[parent].append(j)
        for j, contour in enumerate(contours):
            if depths[j] % 2:          # 奇数深度 = 孔洞内边界，跳过
                continue
            filled = np.zeros_like(mask_u8)
            cv2.drawContours(filled, [contour], 0, 255, -1)
            for child in children[j]:
                # 填外轮廓会把孔一起填满，这里按颜色 0 把孔挖回去；
                # 孔里的独立实体是另一个偶数深度轮廓，各自成段，不受影响。
                cv2.drawContours(filled, [contours[child]], 0, 0, -1)
            items.append((contour, (filled / 255.0).astype(np.float32)))
        return items
    except ImportError:
        return _contours_numpy(mask_u8)


def _contours_numpy(mask_u8):
    """cv2 缺失时的连通域回退：4 邻域洪泛标记，逐域生成 [H,W] 掩膜。"""
    binary = mask_u8 > 0
    height, width = binary.shape
    seen = np.zeros((height, width), dtype=bool)
    items = []
    ys, xs = np.nonzero(binary)
    for sy, sx in zip(ys.tolist(), xs.tolist()):
        if seen[sy, sx]:
            continue
        stack = [(sy, sx)]
        seen[sy, sx] = True
        pts = []
        while stack:
            y, x = stack.pop()
            pts.append((x, y))
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < height and 0 <= nx < width and binary[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        xs_i = [p[0] for p in pts]
        ys_i = [p[1] for p in pts]
        contour = np.array([[[min(xs_i), min(ys_i)], [max(xs_i), max(ys_i)]]], dtype=np.int32)
        filled = np.zeros((height, width), dtype=np.uint8)
        for px, py in pts:
            filled[py, px] = 255
        items.append((contour, (filled / 255.0).astype(np.float32)))
    return items


def mask_to_segs(mask, combine=False, crop_factor=3.0, bbox_fill=False,
                 drop_size=10, is_contour=True, label="A"):
    """核心：把合成后的单张 [H,W] 遮罩分成 (QGSegs)。

    独立实现，供节点调用与测试直接验证。
    """
    plane = _combine_frames(mask)
    height, width = plane.shape[:2]
    drop_size = max(int(drop_size), 1)

    segs = []
    if combine:
        ys, xs = np.nonzero(plane > 0)
        if len(xs) and len(ys):
            x0, y0 = int(xs.min()), int(ys.min())
            x1, y1 = int(xs.max()) + 1, int(ys.max()) + 1
            bbox = (float(x0), float(y0), float(x1), float(y1))
            # 合并模式同样遵守最小尺寸：整块太小就一段都不出，而不是绕过过滤。
            if (x1 - x0) <= drop_size or (y1 - y0) <= drop_size:
                return QGSegs([], width, height)
            seg_mask = plane.copy()
            if bbox_fill:
                seg_mask[y0:y1, x0:x1] = 1.0
            segs.append(QGSeg(bbox, label, 1.0, seg_mask.astype(np.float32),
                              crop_factor))
    else:
        mask_u8 = (np.clip(plane, 0, 1) * 255.0).astype(np.uint8)
        for contour, filled in _contours(mask_u8):
            try:
                import cv2  # noqa: PLC0415
                x, y, w, h = cv2.boundingRect(contour)
            except ImportError:
                pts = contour.reshape(-1, 2)
                x, y = int(pts[:, 0].min()), int(pts[:, 1].min())
                w = int(pts[:, 0].max()) - x + 1
                h = int(pts[:, 1].max()) - y + 1
            if w <= drop_size or h <= drop_size:
                continue
            bbox = (float(x), float(y), float(x + w), float(y + h))
            # 填充轮廓开：用连通域实心掩膜；关：与原遮罩相乘，保留灰度/镂空。
            seg_mask = filled if is_contour else plane * filled
            if bbox_fill:
                seg_mask = seg_mask.copy()
                x0, y0, x1, y1 = (int(v) for v in bbox)
                seg_mask[y0:y1, x0:x1] = 1.0
            segs.append(QGSeg(bbox, label, 1.0,
                              np.clip(seg_mask, 0.0, 1.0).astype(np.float32),
                              crop_factor))

    return QGSegs(segs, width, height)


class QGMaskToSeg:
    """遮罩 → 自造 QG_SEGS：每个连通区域一段，控件语义对齐参考节点。"""

    CATEGORY = "QG 工具"
    FUNCTION = "convert"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mask": ("MASK", {
                    "tooltip": "输入遮罩，支持 [H,W] 单张或 [N,H,W] 批次；批次先逐像素取最大值合成一张再分段。",
                }),
                "combine": ("BOOLEAN", {
                    "default": False, "label_on": "合并为一段", "label_off": "逐区域分段",
                    "tooltip": "合并为一段：整张遮罩只出一个段。逐区域分段：每个独立连通区域各出一段。",
                }),
                "crop_factor": ("FLOAT", {
                    "default": 3.0, "min": 1.0, "max": 100.0, "step": 0.1,
                    "tooltip": "裁剪系数：记入段的元数据，表示裁剪框相对外接框的放大倍数；本节点不裁图。",
                }),
                "bbox_fill": ("BOOLEAN", {
                    "default": False, "label_on": "填充", "label_off": "不填充",
                    "tooltip": "填充 BBox：把每段外接矩形范围填成实心遮罩，适合做整块区域处理。",
                }),
                "drop_size": ("INT", {
                    "default": 10, "min": 1, "max": _MAX_RESOLUTION, "step": 1,
                    "tooltip": "最小尺寸：外接框宽或高不超过该像素数的段丢弃，过滤掉噪点小块。",
                }),
                "is_contour": ("BOOLEAN", {
                    "default": True, "label_on": "填充轮廓", "label_off": "保留原遮罩",
                    "tooltip": "填充轮廓：用连通域实心轮廓当段遮罩；关闭则与原遮罩相乘，保留原始灰度与镂空。",
                }),
            },
        }

    RETURN_TYPES = (SEGS_TYPE,)
    RETURN_NAMES = ("segs",)
    OUTPUT_TOOLTIPS = (
        "自造 QG_SEGS 容器：每个连通区域一段，带框、标签、打分与遮罩；可接 QG 遮罩次序过滤等本包下游。",
    )
    DESCRIPTION = (
        "Converts a ComfyUI MASK into the pack's own QG_SEGS: each connected "
        "region becomes one segment with bbox, label, score and mask. "
        "Independent of Impact-Pack; batch masks are combined by pixel maximum first."
    )
    SEARCH_ALIASES = ["遮罩到Seg", "MaskToSeg", "遮罩转分段", "Mask 到 Segs"]

    def convert(self, mask, combine=False, crop_factor=3.0, bbox_fill=False,
                drop_size=10, is_contour=True):
        return (mask_to_segs(mask, combine, crop_factor, bbox_fill,
                             drop_size, is_contour),)


NODE_CLASS_MAPPINGS = {"QG_MaskToSeg": QGMaskToSeg}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_MaskToSeg": "QG 遮罩到 Seg"}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "SEGS_TYPE",
           "QGSeg", "QGSegs", "mask_to_segs"]
