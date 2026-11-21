# -*- coding: utf-8 -*-
"""QG SAM 模型加载器 —— 自造 QG_SAM_MODEL 类型，不依赖 Impact-Pack。

扫描本机 SAM 权重（models/sams，含 extra_model_paths 挂载），运行时用
segment_anything 的公开接口 sam_model_registry + SamPredictor 构建预测器，
包装成自造的 ``QGSamModel`` 对象输出。遮罩推理由该对象自己的 predict 方法
提供，全程不引用 impact / impact_subpack 的任何代码或类型。

类型字符串 ``QG_SAM_MODEL`` 带本包前缀，与 Impact 生态的 SAM_MODEL 隔离。
未装 segment_anything 时节点照常注册、下拉照常列出权重，只在执行加载时
给出中文提示。
"""
from __future__ import annotations

import os

SAM_TYPE = "QG_SAM_MODEL"

_SAM_MISSING = (
    "QG SAM 模型加载器需要本机安装 segment_anything：本节点用它加载 SAM 权重"
    "并生成遮罩。请在 ComfyUI 的 Python 环境执行 "
    "python -m pip install git+https://github.com/facebookresearch/segment-anything.git "
    "后完整重启 ComfyUI。本节点不依赖 ComfyUI-Impact-Pack。"
)

_FALLBACK_EXTS = (".pth", ".pt", ".ckpt", ".bin", ".safetensors")

# 文件名片段 -> sam_model_registry 的键。顺序重要：先长后短。
_MODEL_TYPE_HINTS = (
    ("vit_h", "vit_h"), ("vit_l", "vit_l"), ("vit_b", "vit_b"),
    ("sam_hq", "vit_h"),  # HQ 权重结构与 vit_h 一致，共用 vit_h 注册表
)


def _folder_paths_module():
    try:
        import folder_paths  # noqa: PLC0415
    except Exception:
        return None
    return folder_paths


def _model_extensions(fp):
    exts = getattr(fp, "supported_pt_extensions", None) if fp is not None else None
    return tuple(str(e).lower() for e in exts) if exts else _FALLBACK_EXTS


def _sam_roots(fp):
    """返回 SAM 权重目录候选，去重保序。"""
    roots = []
    if fp is not None:
        for key in ("sams", "sam"):
            try:
                roots.extend(fp.get_folder_paths(key))
            except Exception:
                pass
        models_dir = getattr(fp, "models_dir", None)
        if models_dir:
            roots.append(os.path.join(models_dir, "sams"))
        try:
            for value in getattr(fp, "folder_names_and_paths", {}).values():
                if isinstance(value, (tuple, list)) and value:
                    for path in (value[0] if isinstance(value[0], (tuple, list)) else [value[0]]):
                        if path:
                            roots.append(os.path.join(os.path.dirname(path), "sams"))
        except Exception:
            pass
    env_dir = os.environ.get("QG_SAMS_DIR")
    if env_dir:
        roots.append(env_dir)
    seen = set()
    out = []
    for root in roots:
        if not root:
            continue
        norm = os.path.normpath(root)
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _scan_models(fp=None):
    if fp is None:
        fp = _folder_paths_module()
    exts = _model_extensions(fp)
    found = set()
    for root in _sam_roots(fp):
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in names:
            if name.lower().endswith(exts) and os.path.isfile(os.path.join(root, name)):
                found.add(name)
    return sorted(found)


def _resolve_model_path(model_name, fp=None):
    if fp is None:
        fp = _folder_paths_module()
    if "/" in model_name or "\\" in model_name:
        return None
    for root in _sam_roots(fp):
        path = os.path.join(root, model_name)
        if os.path.isfile(path):
            return os.path.normpath(path)
    return None


def _guess_model_type(model_name):
    """从文件名推断 sam_model_registry 的键，认不出返回 None。"""
    low = model_name.lower()
    for needle, key in _MODEL_TYPE_HINTS:
        if needle in low:
            return key
    return None


def _resolve_device(device):
    if device == "cpu":
        return "cpu"
    try:
        import torch  # noqa: PLC0415
        if device == "cuda" and not torch.cuda.is_available():
            return "cpu"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


class QGSamModel:
    """自造 SAM 对象：持有 SamPredictor，predict 返回单张遮罩。"""

    def __init__(self, predictor, path, device, model_type):
        self.predictor = predictor
        self.path = path
        self.device = device
        self.model_type = model_type

    def set_image(self, image_rgb):
        """设置 RGB uint8 [H,W,3] 图，SAM 会缓存图像嵌入。"""
        self.predictor.set_image(image_rgb)

    def predict_box(self, box, threshold):
        """用矩形框 [x0,y0,x1,y1] 作提示，返回 ([H,W] float32 遮罩, 打分)。

        只调用 SamPredictor.predict 的公开接口；threshold 用于把 logits
        二值化（0.5 为 SAM 默认阈值）。打分来自 SAM 自身对该遮罩的置信度，
        供主节点做低质量段过滤。
        """
        import numpy as np  # noqa: PLC0415
        masks, scores, logits = self.predictor.predict(
            box=np.asarray(box, dtype=np.float32),
            multimask_output=False,
            return_logits=True,
        )
        if logits is None:
            logits = masks[0]
        logits = logits[0] if getattr(logits, "ndim", 2) == 3 else logits
        mask = (logits > float(threshold)).astype(np.float32)
        try:
            score = float(scores[0])
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
                    "tooltip": "本机 SAM 权重（models/sams）。按文件名自动识别 vit_b/vit_l/vit_h；HQ 权重按 vit_h 加载。",
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
        "Load a local SAM weight with segment_anything and return a self-contained "
        "QG_SAM_MODEL object. Independent of Impact-Pack; requires segment_anything "
        "at runtime. Model type is inferred from the file name."
    )

    @classmethod
    def IS_CHANGED(cls, model_name, device="auto"):
        path = _resolve_model_path(model_name)
        if path is None:
            return float("nan")
        try:
            stat = os.stat(path)
            return "%s:%s" % (stat.st_mtime, stat.st_size)
        except OSError:
            return float("nan")

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
        try:
            from segment_anything import SamPredictor, sam_model_registry  # noqa: PLC0415
        except Exception as exc:
            raise RuntimeError(_SAM_MISSING) from exc
        try:
            sam = sam_model_registry[model_type](checkpoint=path)
            dev = _resolve_device(device)
            sam.to(device=dev)
            predictor = SamPredictor(sam)
        except Exception as exc:
            raise RuntimeError(
                "QG SAM 模型加载器加载 %r 失败：%s。请确认权重与 "
                "segment_anything 版本兼容。" % (path, exc)) from exc
        return (QGSamModel(predictor, path, dev, model_type),)


NODE_CLASS_MAPPINGS = {"QG_SamModelLoader": QGSamModelLoader}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_SamModelLoader": "QG SAM 模型加载器"}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "SAM_TYPE"]
