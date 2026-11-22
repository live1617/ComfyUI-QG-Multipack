# -*- coding: utf-8 -*-
"""QG SAM 模型加载器 —— 自造 QG_SAM_MODEL 类型，不依赖 Impact-Pack。

扫描本机 SAM 权重（models/sams，含 extra_model_paths 挂载），运行时用
segment_anything 的公开接口 sam_model_registry + SamPredictor 构建预测器，
包装成自造的 ``QGSamModel`` 对象输出。遮罩推理由该对象自己的 predict 方法
提供，全程不引用 impact / impact_subpack 的任何代码或类型。

两套后端按文件名自动分流（两者是不兼容的权重格式与包）：
    * 文件名含 sam_hq / hq-sam → HQ-SAM，导入 ``segment_anything_hq``
      （pip 包 segment-anything-hq）。HQ 权重多出 HQ 输出 token，
      官方 segment_anything 直接加载会 key 不匹配。
    * 其余 → Meta 官方 SAM，导入 ``segment_anything``。

类型字符串 ``QG_SAM_MODEL`` 带本包前缀，与 Impact 生态的 SAM_MODEL 隔离。
未装对应库时节点照常注册、下拉照常列出权重，只在执行加载时给出中文提示。
"""
from __future__ import annotations

import os

# 候选根推导 / 递归扫描 / 路径安全解析 / 设备解析 全部走公共层，
# 与 YOLO 检测器加载器共用一份实现；本模块只保留 SAM 特有的后端分流与加载。
try:
    from . import qg_model_scan as _scan
except ImportError:                     # 单文件/顶层加载（测试脚本）
    import qg_model_scan as _scan

SAM_TYPE = "QG_SAM_MODEL"

_SAM_MISSING = (
    "QG SAM 模型加载器需要本机安装 segment_anything（Meta 官方 SAM）：本节点用它"
    "加载 SAM 权重并生成遮罩。请在 ComfyUI 的 Python 环境执行 "
    "python -m pip install git+https://github.com/facebookresearch/segment-anything.git "
    "后完整重启 ComfyUI。本节点不依赖 ComfyUI-Impact-Pack。"
)

_SAM_HQ_MISSING = (
    "这个权重是 HQ-SAM（文件名含 sam_hq），需要单独安装 HQ-SAM 包：官方 "
    "segment_anything 读不了 HQ 权重（结构多了 HQ 输出 token，会 key 不匹配）。"
    "请在 ComfyUI 的 Python 环境执行 python -m pip install segment-anything-hq "
    "后完整重启 ComfyUI。"
)

#: SAM 权重登记的类别名（含历史别名 sam，兼容早期把权重放 models/sam 的用法）。
_CATEGORIES = ("sams", "sam")

#: 文件名里的骨干规格标记，直接就是 sam_model_registry 的键。
_MODEL_TYPE_HINTS = ("vit_h", "vit_l", "vit_b")

# HQ-SAM 权重常见的文件名标记。
_HQ_MARKERS = ("sam_hq", "samhq", "hq_sam", "hq-sam")


def _folder_paths_module():
    return _scan.folder_paths_module()


def _sam_roots(fp=None):
    """返回 SAM 权重目录候选（含挂载与环境变量），去重保序。"""
    if fp is None:
        fp = _folder_paths_module()
    env_dir = os.environ.get("QG_SAMS_DIR")
    return _scan.category_roots(_CATEGORIES, fp, extra=[env_dir] if env_dir else [])


def _scan_models(fp=None):
    """递归扫描 SAM 权重，返回相对文件名的排序列表（子目录用 / 分隔）。

    与 ComfyUI 自身的 ``folder_paths.get_filename_list`` 口径一致：该接口是
    递归的，Impact 等加载器因此能看到 ``sams/hq/xxx.pth`` 这类按型号分目录的
    权重。本节点原先只列根目录一层，用户整理成子目录后就整批消失。
    """
    if fp is None:
        fp = _folder_paths_module()
    env_dir = os.environ.get("QG_SAMS_DIR")
    return _scan.scan_category(
        _CATEGORIES, fp, extra=[env_dir] if env_dir else [])


def _resolve_model_path(model_name, fp=None):
    """把下拉值（可能含子目录，如 hq/sam_hq_vit_h.pth）解析为绝对路径。

    拒绝绝对路径与 ``..`` 上跳，并校验解析结果仍在该候选根之内，避免借下拉
    值读到模型目录以外的文件。
    """
    if fp is None:
        fp = _folder_paths_module()
    parts = _scan.split_relative(model_name)
    if parts is None:
        return None
    return _scan.resolve_in_roots(parts, _sam_roots(fp))


def _is_hq_model(model_name):
    """文件名是否属于 HQ-SAM 权重（需 segment_anything_hq 后端）。

    只看文件名部分：递归扫描后下拉值可能带子目录（``hq/sam_hq_vit_h.pth``），
    若目录名里恰好含 hq_sam 之类字样会造成误判。
    """
    low = os.path.basename(str(model_name).replace("\\", "/")).lower()
    return any(marker in low for marker in _HQ_MARKERS)


def _guess_model_type(model_name):
    """从文件名推断 sam_model_registry 的键，认不出返回 None。

    同样只看文件名：子目录名可能含 vit_b / vit_h 字样（例如用户按骨干分目录
    ``vit_b/sam_hq_vit_h.pth``），用整条相对路径匹配会取到目录的规格而不是
    权重本身的规格。

    先按 vit_b/l/h 片段匹配；只写了 sam_hq 而没写骨干尺寸时，按 HQ-SAM
    官方默认发布规格回落 vit_h（三个官方权重里 vit_h 最常见）。
    """
    low = os.path.basename(str(model_name).replace("\\", "/")).lower()
    for key in _MODEL_TYPE_HINTS:
        if key in low:
            return key
    if _is_hq_model(low):
        return "vit_h"
    return None


def _resolve_device(device):
    return _scan.resolve_device(device)


class QGSamModel:
    """自造 SAM 对象：持有 SamPredictor，predict 返回单张遮罩。"""

    def __init__(self, predictor, path, device, model_type, backend="sam"):
        self.predictor = predictor
        self.path = path
        self.device = device
        self.model_type = model_type
        self.backend = backend      # "sam" 或 "sam_hq"

    def set_image(self, image_rgb):
        """设置 RGB uint8 [H,W,3] 图，SAM 会缓存图像嵌入。"""
        self.predictor.set_image(image_rgb)

    def predict_box(self, box, threshold):
        """用矩形框 [x0,y0,x1,y1] 作提示，返回 (**原图尺寸** [H,W] 遮罩, 打分)。

        返回值契约（官方 SamPredictor.predict 文档与前缀两个实现一致）：
            masks        —— C×H×W，H/W 是 **原图尺寸**；return_logits=True 时是未
                            二值化的 logits。
            iou          —— 每个候选遮罩的质量打分。
            low_res_masks—— C×256×256，模型内部低分辨率 logits，只能当下一次
                            mask_input 用，**不能**当输出遮罩。

        这里必须用第一个返回值：曾误取第三个，256×256 的方形低分辨率遮罩被
        主节点按「尺寸不符」拉伸到 432×768，结果遮罩被压成半幅、位置整体错乱
        （预览图上只覆盖左边一条）。第三个返回值的 padding 只有 predictor 内部
        postprocess 才裁得对，外部直接缩放必然比例错误。

        threshold 作用在 **sigmoid 后的概率** 上（0.5 等同 SAM 默认的 logits > 0）：
        logits 值域约 -20~20，直接拿它和 0~1 的阈值比较会让语义整体偏移。打分
        来自 SAM 自身对该遮罩的置信度，供主节点做低质量段过滤。
        """
        import numpy as np  # noqa: PLC0415
        masks, scores, _low_res_masks = self.predictor.predict(
            box=np.asarray(box, dtype=np.float32),
            multimask_output=False,
            return_logits=True,
        )
        arr = np.asarray(masks)
        if arr.ndim == 3:
            arr = arr[0]
        if arr.ndim != 2:
            raise ValueError(
                "QG SAM 模型加载器：SAM 返回的遮罩维度异常（%d 维），无法当作单张遮罩。"
                % arr.ndim)
        original = getattr(self.predictor, "original_size", None)
        if original is not None and tuple(arr.shape[:2]) != tuple(original):
            raise RuntimeError(
                "QG SAM 模型加载器：SAM 返回的遮罩尺寸 %s 与输入图像尺寸 %s 不一致。"
                "这说明当前后端返回的是低分辨率 logits（256x256），直接缩放会让"
                "遮罩比例与位置全错。请确认 segment_anything / segment_anything_hq "
                "为标准版本。" % (tuple(arr.shape[:2]), tuple(original)))
        if arr.dtype == np.bool_:
            # 少数实现忽略 return_logits，直接回二值遮罩：此时阈值已由它内部
            # 施加，这里不再过 sigmoid。
            mask = arr.astype(np.float32)
        else:
            logits = np.nan_to_num(arr.astype(np.float32),
                                   nan=-60.0, posinf=60.0, neginf=-60.0)
            prob = 1.0 / (1.0 + np.exp(-np.clip(logits, -60.0, 60.0)))
            mask = (prob > float(threshold)).astype(np.float32)
        try:
            # SAM 的 iou 预测偶尔略超 1（实测 1.007），夹回 [0,1] 再给下游，
            # 否则 seg.score 会突破控件上限、下游按分数做的判断会失真。
            score = float(np.clip(float(scores[0]), 0.0, 1.0))
        except (TypeError, IndexError, ValueError):
            score = 1.0
        return mask, score


class QGSamModelLoader:
    """加载本机 SAM 权重，输出自造 QG_SAM_MODEL。"""

    CATEGORY = "QG 工具"
    FUNCTION = "load_model"

    @classmethod
    def INPUT_TYPES(cls):
        models = _scan_models()
        if not models:
            models = ["（未找到 SAM 模型，请检查 models/sams 或设置 QG_SAMS_DIR）"]
        return {
            "required": {
                "model_name": (models, {
                    "tooltip": "本机 SAM 权重（models/sams，含子目录，最多 3 层）。按文件名自动识别 vit_b/vit_l/vit_h；文件名含 sam_hq 的按 HQ-SAM 后端加载（需另装 segment-anything-hq）。",
                }),
                "device": (["auto", "cpu", "cuda"], {
                    "default": "auto",
                    "tooltip": "推理设备。auto 自动选 CUDA（可用时），cpu 强制 CPU，cuda 不可用时自动回退 CPU。",
                }),
            },
        }

    RETURN_TYPES = (SAM_TYPE,)
    RETURN_NAMES = ("sam_model",)
    OUTPUT_TOOLTIPS = ("自造 SAM 对象 QG_SAM_MODEL，只能接本包的 QG 简易 Seg 检测节点。",)
    DESCRIPTION = (
        "Load a local SAM weight and return a self-contained QG_SAM_MODEL object. "
        "Independent of Impact-Pack. Uses segment_anything for Meta SAM weights and "
        "segment_anything_hq for HQ-SAM weights (sam_hq in the file name)."
    )
    SEARCH_ALIASES = ["SAM 加载器", "SAM 模型", "分割模型", "HQ-SAM"]

    @classmethod
    def IS_CHANGED(cls, model_name, device="auto"):
        return _scan.file_signature(_resolve_model_path(model_name))

    def load_model(self, model_name, device="auto"):
        path = _resolve_model_path(model_name)
        if path is None:
            roots = _sam_roots(_folder_paths_module())
            hint = "\n  ".join(roots) if roots else "（未找到任何候选目录）"
            raise ValueError(
                "QG SAM 模型加载器找不到模型 %r。已查找目录：\n  %s\n"
                "请把权重放到 models/sams 下，或设置 QG_SAMS_DIR 指向 SAM 目录。"
                % (model_name, hint))
        model_type = _guess_model_type(model_name)
        if model_type is None:
            raise ValueError(
                "QG SAM 模型加载器无法从文件名 %r 判断模型类型（vit_b/vit_l/vit_h）。"
                "请把权重改名为包含 vit_b / vit_l / vit_h 的标准名称。" % model_name)
        backend = "sam_hq" if _is_hq_model(model_name) else "sam"
        try:
            if backend == "sam_hq":
                from segment_anything_hq import SamPredictor, sam_model_registry  # noqa: PLC0415
            else:
                from segment_anything import SamPredictor, sam_model_registry  # noqa: PLC0415
        except Exception as exc:
            raise RuntimeError(
                _SAM_HQ_MISSING if backend == "sam_hq" else _SAM_MISSING) from exc
        try:
            sam = sam_model_registry[model_type](checkpoint=path)
            dev = _resolve_device(device)
            sam.to(device=dev)
            predictor = SamPredictor(sam)
        except Exception as exc:
            raise RuntimeError(
                "QG SAM 模型加载器加载 %r 失败：%s。请确认权重与 %s 版本兼容。"
                % (path, exc, "segment_anything_hq" if backend == "sam_hq"
                   else "segment_anything")) from exc
        return (QGSamModel(predictor, path, dev, model_type, backend),)


NODE_CLASS_MAPPINGS = {"QG_SamModelLoader": QGSamModelLoader}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_SamModelLoader": "QG SAM 模型加载器"}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "SAM_TYPE"]
