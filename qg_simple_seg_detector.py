# -*- coding: utf-8 -*-
"""QG_SimpleSegDetectorSEGS —— 简易 Seg 检测（SEGS）。

规格参考 ComfyUI-Impact-Pack 的 ImpactSimpleDetectorSEGS（节点类
SimpleDetectorForEach，ltdrdata/ComfyUI-Impact-Pack，GPL-3.0），**按规格独立
实现，未逐行复制其源码**：节点壳、参数校验、软依赖探测、中文 tooltip 都是
为本包写的。检测与遮罩运算在运行时调用 Impact-Pack 的公开接口完成
（impact.core 的 make_sam_mask / segs_bitwise_and_mask / dilate_segs /
segs_to_combined_mask，以及传入 detector 对象自身的 detect 方法）。

为什么必须依赖 Impact-Pack
--------------------------
本节点三个输入与一个输出全是 Impact-Pack 的自定义类型：
BBOX_DETECTOR / SAM_MODEL / SEGM_DETECTOR → SEGS。SEGS 的内部结构是其
namedtuple SEG，任何要接 Impact 下游（DetailerForEach 等）的节点都必须
产出同样的对象。因此这些**类型字符串不能加本包前缀**，必须与 Impact-Pack
逐字一致才能连线；这是跨包连线契约，不是标识命名问题。
未装 Impact-Pack 时节点照常注册、参数照常显示，只在真正运行时给出可照做的
中文提示，不拖垮本包其余节点。

行为规格（与参考节点一致的部分）
--------------------------------
* 单张 IMAGE：batch>1 直接拒绝（Impact 的 detector 本身也不支持批量）。
* 先走 bbox 检测；若 SEGM 检测器与 bbox 检测器是同一个对象（YOLO-World 的
  常见接法），直接用 SEGM 的结果，省一次重复检测。
* 给了 SAM 模型：用「中心点 + 框」提示把矩形区域细化成轮廓，再与 bbox 区域
  取交；否则给了 SEGM 检测器：用它的合并遮罩与 bbox 区域取交。SAM 优先。
* 最后按 post_dilation 对每段遮罩做膨胀（负值收缩），0 则原样返回。
"""
from __future__ import annotations

# ComfyUI 全局 MAX_RESOLUTION 的当前值；写死是为了让本模块在脱离 ComfyUI 的
# 测试进程里也能被导入，不需要先 import nodes。
_MAX_RESOLUTION = 16384

_IMPACT_CORE = None
_IMPACT_MISSING = (
    "QG 简易 Seg 检测需要本机安装 ComfyUI-Impact-Pack：本节点的输入/输出类型"
    "（BBOX_DETECTOR / SAM_MODEL / SEGM_DETECTOR / SEGS）和输出结构都由它定义，"
    "检测与遮罩运算也调用它的公开接口。请先把 ComfyUI-Impact-Pack 放进 "
    "custom_nodes 并完整重启 ComfyUI，再使用本节点。"
)


def _load_impact_core():
    """运行时取 impact.core；缺失只在本节点执行时报中文提示，不影响本包导入。"""
    global _IMPACT_CORE
    if _IMPACT_CORE is not None:
        return _IMPACT_CORE
    try:
        import impact.core as core  # noqa: PLC0415 - 故意延迟到运行时
    except Exception as exc:  # noqa: BLE001 - 可能是依赖缺失而非单纯 ModuleNotFound
        raise RuntimeError(_IMPACT_MISSING) from exc
    _IMPACT_CORE = core
    return core


class QGSimpleSegDetectorSEGS:
    """把 BBOX 检测结果（可选 SAM / SEGM 精修）打包成 Impact 的 SEGS。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "bbox_detector": ("BBOX_DETECTOR", {
                    "tooltip": "BBox 检测器（Impact-Pack 的检测器加载节点输出）。先找出画面里目标的矩形框。",
                }),
                "image": ("IMAGE", {
                    "tooltip": "单张图片。本节点不接受图像批次（batch 大于 1 会直接报错）。",
                }),
                "bbox_threshold": ("FLOAT", {
                    "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "BBox 置信度阈值：低于此分数的检测框丢弃。调低可找出更多目标，但也更容易误检。",
                }),
                "bbox_dilation": ("INT", {
                    "default": 0, "min": -512, "max": 512, "step": 1,
                    "tooltip": "BBox 膨胀像素：正值把检测框向外扩，负值收缩。0 保持原样。",
                }),
                "crop_factor": ("FLOAT", {
                    "default": 3.0, "min": 1.0, "max": 100.0, "step": 0.1,
                    "tooltip": "裁剪系数：每段 SEG 的裁剪区域相对检测框放大多少倍，给后续局部重绘留出上下文。",
                }),
                "drop_size": ("INT", {
                    "default": 10, "min": 1, "max": _MAX_RESOLUTION, "step": 1,
                    "tooltip": "最小尺寸：宽或高小于该像素数的检测框直接丢弃。",
                }),
                "sub_threshold": ("FLOAT", {
                    "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "次要阈值：SAM 遮罩提示与 SEGM 检测器使用的置信度阈值。",
                }),
                "sub_dilation": ("INT", {
                    "default": 0, "min": -512, "max": 512, "step": 1,
                    "tooltip": "次要膨胀：传给 SAM 的提示区域膨胀量，或 SEGM 检测器使用的膨胀量。",
                }),
                "sub_bbox_expansion": ("INT", {
                    "default": 0, "min": 0, "max": 1000, "step": 1,
                    "tooltip": "次要 BBox 扩展：SAM 检测提示时把框再扩多少像素，0 为不扩。",
                }),
                "sam_mask_hint_threshold": ("FLOAT", {
                    "default": 0.7, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "SAM 遮罩提示阈值：只有遮罩值高于该比例的区域才作为 SAM 的提示点。",
                }),
                "post_dilation": ("INT", {
                    "default": 0, "min": -512, "max": 512, "step": 1,
                    "tooltip": "扩张后：对最终每段遮罩做膨胀（负值收缩）的像素数，0 不处理。",
                }),
            },
            "optional": {
                "sam_model_opt": ("SAM_MODEL", {
                    "tooltip": "可选 SAM 模型（Impact-Pack 的 SAMLoader 输出）。给了就把 BBox 矩形细化成轮廓；与 SEGM 同时给时 SAM 优先。",
                }),
                "segm_detector_opt": ("SEGM_DETECTOR", {
                    "tooltip": "可选 SEGM 检测器。没给 SAM 时，用它的遮罩与 BBox 区域取交；若它与 BBox 检测器是同一对象，直接复用检测结果。",
                }),
            },
        }

    RETURN_TYPES = ("SEGS",)
    RETURN_NAMES = ("segs",)
    FUNCTION = "detect"
    CATEGORY = "QG 工具"
    OUTPUT_TOOLTIPS = ("检测到的区域集合（Impact-Pack 的 SEGS），可直接接 Detailer 等 Impact 下游节点。",)
    DESCRIPTION = (
        "Runs a BBOX detector on a single image and returns Impact-Pack SEGS. "
        "Optionally refines boxes into silhouettes with a SAM model or intersects "
        "them with a SEGM detector mask, then applies a final mask dilation. "
        "Requires ComfyUI-Impact-Pack to be installed."
    )

    @staticmethod
    def _needs_segm_only(bbox_detector, segm_detector_opt):
        """SEGM 与 BBOX 是同一检测器时不必再跑一次 bbox，直接用 SEGM 结果。"""
        if segm_detector_opt is None:
            return False
        if not hasattr(segm_detector_opt, "bbox_detector"):
            return False
        return getattr(segm_detector_opt, "bbox_detector") == bbox_detector

    def detect(self, bbox_detector, image, bbox_threshold, bbox_dilation,
               crop_factor, drop_size, sub_threshold, sub_dilation,
               sub_bbox_expansion, sam_mask_hint_threshold, post_dilation,
               sam_model_opt=None, segm_detector_opt=None):
        if len(image) > 1:
            raise RuntimeError(
                "QG 简易 Seg 检测只接受单张图片，收到 %d 帧。请先用批次拆分节点"
                "逐帧处理。" % len(image))

        core = _load_impact_core()
        use_segm_only = self._needs_segm_only(bbox_detector, segm_detector_opt)

        if use_segm_only:
            segs = segm_detector_opt.detect(
                image, sub_threshold, sub_dilation, crop_factor, drop_size)
        else:
            segs = bbox_detector.detect(
                image, bbox_threshold, bbox_dilation, crop_factor, drop_size)

            if sam_model_opt is not None:
                # center-1：每个框取中心点 + 框本身作提示；最后两个参数是
                # mask_hint_threshold 与 use_negative，center-1 用不到负提示。
                sam_mask = core.make_sam_mask(
                    sam_model_opt, segs, image, "center-1", sub_dilation,
                    sub_threshold, sub_bbox_expansion,
                    sam_mask_hint_threshold, False)
                segs = core.segs_bitwise_and_mask(segs, sam_mask)
            elif segm_detector_opt is not None:
                segm_segs = segm_detector_opt.detect(
                    image, sub_threshold, sub_dilation, crop_factor, drop_size)
                segm_mask = core.segs_to_combined_mask(segm_segs)
                segs = core.segs_bitwise_and_mask(segs, segm_mask)

        segs = core.dilate_segs(segs, post_dilation)
        return (segs,)


NODE_CLASS_MAPPINGS = {"QG_SimpleSegDetectorSEGS": QGSimpleSegDetectorSEGS}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_SimpleSegDetectorSEGS": "QG 简易 Seg 检测 (SEGS)"}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
