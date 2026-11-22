# -*- coding: utf-8 -*-
"""QG 简易 Seg 检测 —— 自造 QG_SEGS 类型 + MASK 双输出，不依赖 Impact-Pack。

数据流：自造检测器 QG_YOLO_DETECTOR 出框 → （可选）自造 SAM 对象 QG_SAM_MODEL
逐框生成遮罩 → 后处理 → 输出自造 QG_SEGS 容器与普通 MASK 批次。

本节点是本包自己写的壳与运算：只调用检测器/SAM 对象暴露的公开方法，参数校验、
膨胀/收缩、容器结构、中文说明都是为本包写的。类型字符串 QG_SEGS 带本包前缀，
与 Impact 生态的 SEGS 完全隔离，输出不能喂给 Impact 下游（这是自造类型的取舍）。
MASK 输出是 ComfyUI 原生格式，可直接接本包 QG_MaskOrderFilter 等节点。

参数语义（对齐参考节点的控件，独立实现）：
    * bbox_threshold：检测置信度，低于此值的框丢弃。
    * bbox_dilation：框四边膨胀像素（正扩负缩），影响裁剪与 SAM 提示框。
    * crop_factor：每段裁剪区域相对检测框的放大倍数（记入 SEG 元数据）。
    * drop_size：宽或高小于该像素数的段丢弃。
    * sub_threshold：给 SAM 的二值化阈值（越大遮罩越保守）。
    * sub_dilation：SAM 提示框在 bbox_dilation 之上再膨胀的像素。
    * sub_bbox_expansion：SAM 提示框四边扩展的额外像素。
    * sam_mask_hint_threshold：SAM 打分低于该值的段丢弃（质量过滤）。
    * post_dilation：对最终每段遮罩做膨胀（负值收缩），0 不处理。
"""
from __future__ import annotations

import numpy as np
import torch

_MAX_RESOLUTION = 16384

SEGS_TYPE = "QG_SEGS"


class QGSeg:
    """一段检测结果：矩形框、标签、打分、遮罩与各段元数据。"""

    __slots__ = ("bbox", "label", "score", "mask", "crop_factor")

    def __init__(self, bbox, label, score, mask, crop_factor):
        self.bbox = tuple(float(v) for v in bbox)   # (x0,y0,x1,y1)
        self.label = str(label)
        self.score = float(score)
        self.mask = mask                             # [H,W] float32 0..1
        self.crop_factor = float(crop_factor)

    def __repr__(self):
        return "QGSeg(label=%r, score=%.3f, bbox=%s)" % (
            self.label, self.score, self.bbox)


class QGSegs:
    """自造 SEGS 容器：一组 QGSeg，带尺寸与合并遮罩的便捷方法。"""

    def __init__(self, segs, width, height):
        self.segs = list(segs)
        self.width = int(width)
        self.height = int(height)

    def __len__(self):
        return len(self.segs)

    def __iter__(self):
        return iter(self.segs)

    def __getitem__(self, index):
        return self.segs[index]

    def __repr__(self):
        return "QGSegs(%d segs, %dx%d)" % (len(self.segs), self.width, self.height)

    def combined_mask(self):
        """逐像素取最大，合成一张 [H,W] 遮罩；无段时返回全 0。"""
        if not self.segs:
            return np.zeros((self.height, self.width), dtype=np.float32)
        out = self.segs[0].mask.copy()
        for seg in self.segs[1:]:
            np.maximum(out, seg.mask, out=out)
        return out

    def mask_batch(self):
        """每段一帧，堆叠成 [N,H,W]；无段时返回 [0,H,W]。"""
        if not self.segs:
            return np.zeros((0, self.height, self.width), dtype=np.float32)
        return np.stack([s.mask for s in self.segs], axis=0)


def _dilate_mask(mask, amount):
    """对 [H,W] 遮罩做方形结构元的膨胀（正）或收缩（负），0 原样返回。"""
    amount = int(amount)
    if amount == 0:
        return mask
    try:
        import cv2  # noqa: PLC0415
        kernel = np.ones((amount * 2 + 1, amount * 2 + 1), np.uint8)
        if amount > 0:
            out = cv2.dilate(mask, kernel, iterations=1)
        else:
            out = cv2.erode(mask, kernel, iterations=1)
        return np.asarray(out, dtype=np.float32)
    except Exception:
        # cv2 缺失时的纯 numpy 回退。必须与 cv2 同口径：方形结构元
        # （切比雪夫半径 n），不是「十字邻域迭代 n 次」——后者得到的是曼哈顿
        # 半径 n 的菱形，同样参数下面积只有方形的约 3/4，两条路径结果不一致。
        # 方形核可分离：先水平 1×k，再垂直 k×1，k = 2n+1。
        n = abs(amount)
        k = 2 * n + 1
        arr = np.asarray(mask, dtype=np.float32)
        if amount > 0:
            # 膨胀：取窗口最大值，边界外按 0（不额外扩大）。
            pad_value = 0.0
            reduce = np.max
        else:
            # 收缩：取窗口最小值，边界外按 +inf（不侵蚀边界），
            # 与 cv2 morphologyDefaultBorderValue 对齐。
            # 这里必须用 min + inf：上一版误用了 max，收缩实际变成膨胀。
            pad_value = np.inf
            reduce = np.min
        padded = np.pad(arr, n, mode="constant", constant_values=pad_value)
        horiz = reduce(np.lib.stride_tricks.sliding_window_view(padded, k, axis=1),
                       axis=-1)
        out = reduce(np.lib.stride_tricks.sliding_window_view(horiz, k, axis=0),
                     axis=-1)
        # inf 只可能出现在整幅图为空（或全 inf）的极端情况，回落到 0 更安全。
        return np.nan_to_num(out.astype(np.float32), nan=0.0,
                             posinf=0.0, neginf=0.0)


def _to_uint8_rgb(image):
    """ComfyUI IMAGE [B,H,W,3] float 0..1 -> 首帧 RGB uint8 [H,W,3]。

    空批次（0 帧）没有首帧可转，直接给中文错误——否则会抛 IndexError，
    用户看不懂是哪个节点、为什么。
    """
    frame = image[0] if len(image) else None
    if frame is None:
        raise ValueError("QG 简易 Seg 检测收到空图像批次（0 帧），无法检测。")
    arr = frame.detach().cpu().numpy() if hasattr(frame, "detach") else np.asarray(frame)
    arr = np.nan_to_num(np.asarray(arr, dtype=np.float32), nan=0.0, posinf=1.0, neginf=0.0)
    arr = np.clip(arr, 0.0, 1.0)
    return (arr * 255.0 + 0.5).astype(np.uint8)


def _expand_box(box, dilation, extra, width, height):
    """框四边按 dilation+extra 扩展并夹到图像范围。"""
    x0, y0, x1, y1 = box
    pad = int(dilation) + int(extra)
    x0 = max(0.0, x0 - pad)
    y0 = max(0.0, y0 - pad)
    x1 = min(float(width), x1 + pad)
    y1 = min(float(height), y1 + pad)
    return (x0, y0, x1, y1)


class QGSimpleSegDetector:
    """把自造检测结果与可选 SAM 精修打包成 QG_SEGS 与 MASK。"""

    CATEGORY = "QG 工具"
    FUNCTION = "detect"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "detector": ("QG_YOLO_DETECTOR", {
                    "tooltip": "自造检测器对象，由 QG 检测模型加载器输出。",
                }),
                "image": ("IMAGE", {
                    "tooltip": "单张图片。批次大于 1 会直接报错，请先用批次拆分节点逐帧处理。",
                }),
                "bbox_threshold": ("FLOAT", {
                    "default": 0.6, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "检测置信度阈值：低于此分数的框丢弃。",
                }),
                "bbox_dilation": ("INT", {
                    "default": 0, "min": -512, "max": 512, "step": 1,
                    "tooltip": "框四边膨胀像素：正值外扩、负值收缩，影响裁剪与 SAM 提示框。",
                }),
                "crop_factor": ("FLOAT", {
                    "default": 3.0, "min": 1.0, "max": 100.0, "step": 0.1,
                    "tooltip": "裁剪系数：每段裁剪区域相对检测框放大的倍数，记入 SEG 元数据。",
                }),
                "drop_size": ("INT", {
                    "default": 10, "min": 1, "max": _MAX_RESOLUTION, "step": 1,
                    "tooltip": "最小尺寸：宽或高小于该像素数的段丢弃。",
                }),
                "sub_threshold": ("FLOAT", {
                    "default": 0.7, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "SAM 二值化阈值：越高遮罩越保守，只保留 SAM 更有把握的核心区域。",
                }),
                "sub_dilation": ("INT", {
                    "default": 0, "min": -512, "max": 512, "step": 1,
                    "tooltip": "SAM 提示框在框膨胀之上再膨胀的像素，正值外扩。",
                }),
                "sub_bbox_expansion": ("INT", {
                    "default": 0, "min": 0, "max": 1000, "step": 1,
                    "tooltip": "SAM 提示框四边额外扩展的像素，给 SAM 更多上下文。",
                }),
                "sam_mask_hint_threshold": ("FLOAT", {
                    "default": 0.7, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "SAM 打分低于该值的段直接丢弃（质量过滤），0 表示不过滤。",
                }),
                "post_dilation": ("INT", {
                    "default": 0, "min": -512, "max": 512, "step": 1,
                    "tooltip": "对最终每段遮罩做膨胀（负值收缩）的像素数，0 不处理。",
                }),
            },
            "optional": {
                "sam_model": ("QG_SAM_MODEL", {
                    "tooltip": "可选 SAM 模型（QG SAM 模型加载器输出）。给了就把检测框细化成轮廓；不给则直接用矩形框作遮罩。",
                }),
            },
        }

    RETURN_TYPES = (SEGS_TYPE, "MASK")
    RETURN_NAMES = ("segs", "MASK")
    OUTPUT_TOOLTIPS = (
        "自造 QG_SEGS 容器：每段的框、标签、打分与遮罩；只能接本包下游。",
        "遮罩批次 [N,H,W]，每段一帧，可直接接本包的遮罩类节点。",
    )
    DESCRIPTION = (
        "Runs a self-contained QG detector on a single image, optionally refines each "
        "box into a silhouette with a self-contained SAM model, and returns native "
        "QG_SEGS plus a MASK batch. Independent of Impact-Pack."
    )
    SEARCH_ALIASES = ["Seg检测", "简易Seg", "目标分割", "SAM 检测"]

    def detect(self, detector, image, bbox_threshold, bbox_dilation, crop_factor,
               drop_size, sub_threshold, sub_dilation, sub_bbox_expansion,
               sam_mask_hint_threshold, post_dilation, sam_model=None):
        if len(image) > 1:
            raise RuntimeError(
                "QG 简易 Seg 检测只接受单张图片，收到 %d 帧。请先用批次拆分节点逐帧处理。" % len(image))
        if detector is None:
            raise ValueError("QG 简易 Seg 检测缺少检测器：请接上 QG 检测模型加载器的输出。")

        rgb = _to_uint8_rgb(image)
        height, width = rgb.shape[:2]

        # ultralytics 的 numpy 输入按 OpenCV 约定解释为 BGR：predict() 内部会把
        # numpy 数组当成 BGR 再翻成 RGB，直接喂 RGB 会让红蓝通道互换，检出的
        # 颜色/类别语义整体偏移。检测走 BGR，SAM 仍走 RGB（它的 set_image 要 RGB）。
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])
        raw = detector.detect(bgr, bbox_threshold)
        segs = []
        # 没检出任何框时不必跑 SAM 的图像编码：vit_h 在 CPU 上一次 set_image
        # 要几十秒，白等一轮没有意义。
        if sam_model is not None and raw:
            sam_model.set_image(rgb)

        for item in raw:
            box = _expand_box(item["bbox"], bbox_dilation, 0, width, height)
            x0, y0, x1, y1 = box
            if (x1 - x0) < int(drop_size) or (y1 - y0) < int(drop_size):
                continue

            if sam_model is not None:
                hint = _expand_box(box, sub_dilation, sub_bbox_expansion, width, height)
                if (hint[2] - hint[0]) <= 0 or (hint[3] - hint[1]) <= 0:
                    continue
                mask, score = sam_model.predict_box(hint, sub_threshold)
                if float(sam_mask_hint_threshold) > 0 and score < float(sam_mask_hint_threshold):
                    continue
                # SAM 遮罩按外接框对齐回原图坐标（predict 返回全图尺寸，通常已对齐）。
                if mask.shape[:2] != (height, width):
                    mask = _resize_mask(mask, width, height)
            else:
                mask = np.zeros((height, width), dtype=np.float32)
                ix0, iy0 = max(0, int(x0)), max(0, int(y0))
                ix1, iy1 = min(width, int(x1)), min(height, int(y1))
                if ix1 > ix0 and iy1 > iy0:
                    mask[iy0:iy1, ix0:ix1] = 1.0
                score = float(item.get("conf", 1.0))

            mask = np.nan_to_num(mask, nan=0.0, posinf=1.0, neginf=0.0)
            mask = np.clip(mask, 0.0, 1.0).astype(np.float32)
            if post_dilation:
                mask = _dilate_mask(mask, post_dilation)
            segs.append(QGSeg(box, item.get("label", ""), score, mask, crop_factor))

        container = QGSegs(segs, width, height)
        # ComfyUI 的 MASK 类型是 torch.Tensor；输出 ndarray 会让 Preview 等下游
        # 节点报 "input is not a Tensor"。内部仍用 numpy，出口统一转 Tensor。
        mask_batch = container.mask_batch()
        if not isinstance(mask_batch, torch.Tensor):
            mask_batch = torch.from_numpy(
                np.ascontiguousarray(mask_batch, dtype=np.float32))
        return (container, mask_batch)


def _resize_mask(mask, width, height):
    """尺寸不符时把遮罩缩放到目标 [H,W]（双线性，带 nan 兜底）。"""
    try:
        import cv2  # noqa: PLC0415
        out = cv2.resize(mask, (width, height), interpolation=cv2.INTER_LINEAR)
        return np.asarray(out, dtype=np.float32)
    except Exception:
        src_h, src_w = mask.shape[:2]
        ys = np.linspace(0, src_h - 1, height).astype(np.float32)
        xs = np.linspace(0, src_w - 1, width).astype(np.float32)
        y0 = np.floor(ys).astype(int)
        x0 = np.floor(xs).astype(int)
        y1 = np.clip(y0 + 1, 0, src_h - 1)
        x1 = np.clip(x0 + 1, 0, src_w - 1)
        wy = (ys - y0)[:, None]
        wx = (xs - x0)[None, :]
        top = mask[np.ix_(y0, x0)] * (1 - wx) + mask[np.ix_(y0, x1)] * wx
        bot = mask[np.ix_(y1, x0)] * (1 - wx) + mask[np.ix_(y1, x1)] * wx
        return (top * (1 - wy) + bot * wy).astype(np.float32)


NODE_CLASS_MAPPINGS = {"QG_SimpleSegDetector": QGSimpleSegDetector}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_SimpleSegDetector": "QG 简易 Seg 检测"}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "SEGS_TYPE",
           "QGSeg", "QGSegs"]
