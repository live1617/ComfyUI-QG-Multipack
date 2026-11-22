# -*- coding: utf-8 -*-
"""QG 检测模型加载器 —— 自造 QG_YOLO_DETECTOR 类型，不依赖 Impact-Pack。

本节点只做两件事：扫描本机 ultralytics 权重（含 extra_model_paths 挂载）、
在运行时用 ultralytics 的公开接口 ``YOLO(path)`` 加载模型，包装成自造的
``QGYoloDetector`` 对象输出。检测能力由该对象自己的 ``detect`` 方法提供，
全流程不引用 impact / impact_subpack 的任何代码或类型。

类型字符串用 ``QG_YOLO_DETECTOR``（带本包前缀），与 Impact 生态的
BBOX_DETECTOR / SEGM_DETECTOR 完全隔离，既不会撞名，也不需要用户装 Impact。
未装 ultralytics 时节点照常注册、下拉照常列出本机权重，只在真正执行加载时
给出可照做的中文提示。

模型目录（按优先级去重）：
    1. folder_paths 注册的 ultralytics 根（含 extra_model_paths 挂载）
    2. models_dir/ultralytics（本机主库）
    3. 由 folder_names_and_paths 里所有挂载路径反推的 models 根/ultralytics
    4. 环境变量 QG_ULTRALYTICS_DIR（可直接指向 ultralytics 根）
下拉项格式沿用 Impact 生态习惯：bbox/xxx.pt、segm/xxx.pt。
"""
from __future__ import annotations

import os

DETECTOR_TYPE = "QG_YOLO_DETECTOR"

_YOLO_MISSING = (
    "QG 检测模型加载器需要本机安装 ultralytics（YOLO 推理库）：本节点用它加载"
    "检测权重并出框。请在 ComfyUI 的 Python 环境执行 "
    "python -m pip install ultralytics 后完整重启 ComfyUI。本节点不依赖 "
    "ComfyUI-Impact-Pack 或 Impact-Subpack。"
)

_FALLBACK_EXTS = (".pt", ".pth", ".onnx", ".safetensors")


def _folder_paths_module():
    try:
        import folder_paths  # noqa: PLC0415 - 延迟导入，便于测试进程注入
    except Exception:
        return None
    return folder_paths


def _model_extensions(fp):
    exts = getattr(fp, "supported_pt_extensions", None) if fp is not None else None
    return tuple(str(e).lower() for e in exts) if exts else _FALLBACK_EXTS


def _model_roots(fp):
    """返回 ultralytics 根的候选目录，去重保序。"""
    roots = []
    if fp is not None:
        try:
            roots.extend(fp.get_folder_paths("ultralytics"))
        except Exception:
            pass
        models_dir = getattr(fp, "models_dir", None)
        if models_dir:
            roots.append(os.path.join(models_dir, "ultralytics"))
        # extra_model_paths 挂进来的 models 根：从所有已注册路径向上反推。
        try:
            for value in getattr(fp, "folder_names_and_paths", {}).values():
                if isinstance(value, (tuple, list)) and value:
                    for path in (value[0] if isinstance(value[0], (tuple, list)) else [value[0]]):
                        if path:
                            roots.append(os.path.join(os.path.dirname(path), "ultralytics"))
        except Exception:
            pass
    env_dir = os.environ.get("QG_ULTRALYTICS_DIR")
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


def _candidate_roots(kind, fp=None):
    """某类（bbox/segm）模型目录候选，去重保序。"""
    if fp is None:
        fp = _folder_paths_module()
    roots = []
    for base in _model_roots(fp):
        sub = os.path.join(base, kind)
        # 目录本身已以 bbox/segm 结尾时不再重复拼一层。
        roots.append(sub if os.path.basename(os.path.normpath(base)) != kind else base)
    seen = set()
    out = []
    for root in roots:
        norm = os.path.normpath(root)
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _scan_models(kind, fp=None):
    """扫描某类模型的相对文件名，排序去重。"""
    if fp is None:
        fp = _folder_paths_module()
    exts = _model_extensions(fp)
    found = set()
    for root in _candidate_roots(kind, fp):
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in names:
            if name.lower().endswith(exts) and os.path.isfile(os.path.join(root, name)):
                found.add(name)
    return sorted(found)


def _resolve_model_path(model_name, fp=None):
    """把 bbox/xxx.pt、segm/xxx.pt 解析为绝对路径，找不到返回 None。"""
    if fp is None:
        fp = _folder_paths_module()
    if model_name.startswith("bbox/"):
        kind, rel = "bbox", model_name[5:]
    elif model_name.startswith("segm/"):
        kind, rel = "segm", model_name[5:]
    else:
        return None
    if "/" in rel or "\\" in rel:
        return None  # 不接受子目录跳转，避免路径穿越
    for root in _candidate_roots(kind, fp):
        path = os.path.join(root, rel)
        if os.path.isfile(path):
            return os.path.normpath(path)
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


class QGYoloDetector:
    """自造检测器对象：持有 ultralytics 模型，detect 方法返回框列表。"""

    def __init__(self, model, path, device, kind):
        self.model = model
        self.path = path
        self.device = device
        self.kind = kind

    def detect(self, image_bgr, conf):
        """在单张 **BGR** uint8 [H,W,3] 图上检测，返回框 dict 列表。

        调用方必须传 BGR：ultralytics 对 numpy 输入按 OpenCV 约定处理（内部会
        再做 BGR→RGB），传 RGB 会导致红蓝通道互换。

        每项：{"bbox": (x0,y0,x1,y1), "conf": float, "label": str, "cls": int}。
        只调用 ultralytics 模型的公开 predict 接口。
        """
        results = self.model.predict(
            source=image_bgr, conf=float(conf), device=self.device, verbose=False)
        if not results:
            return []
        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return []
        xyxy = getattr(boxes, "xyxy", None)
        if xyxy is None:
            return []
        try:
            xyxy = xyxy.detach().cpu().numpy()
        except AttributeError:
            pass
        confs = getattr(boxes, "conf", None)
        clss = getattr(boxes, "cls", None)
        if confs is None:
            confs = [1.0] * len(xyxy)
        else:
            try:
                confs = confs.detach().cpu().numpy()
            except AttributeError:
                pass
        if clss is None:
            clss = [0] * len(xyxy)
        else:
            try:
                clss = clss.detach().cpu().numpy()
            except AttributeError:
                pass
        names = getattr(self.model, "names", None) or {}
        out = []
        for i in range(len(xyxy)):
            score = float(confs[i])
            if score < float(conf):
                continue
            x0, y0, x1, y1 = (float(v) for v in xyxy[i])
            cls = int(clss[i])
            label = names.get(cls, str(cls)) if isinstance(names, dict) else str(cls)
            out.append({"bbox": (x0, y0, x1, y1), "conf": score,
                        "label": label, "cls": cls})
        return out


class QGYoloDetectorLoader:
    """加载本机 ultralytics 权重，输出自造 QG_YOLO_DETECTOR。"""

    CATEGORY = "QG 工具"
    FUNCTION = "load_detector"

    @classmethod
    def INPUT_TYPES(cls):
        models = ["bbox/" + x for x in _scan_models("bbox")]
        models += ["segm/" + x for x in _scan_models("segm")]
        if not models:
            models = ["（未找到 ultralytics 模型，请检查 models/ultralytics/{bbox,segm}）"]
        return {
            "required": {
                "model_name": (models, {
                    "tooltip": "本机 ultralytics 权重。bbox/ 只出矩形框，segm/ 为实例分割权重；放在 models/ultralytics/bbox 或 segm 下，或用 QG_ULTRALYTICS_DIR 指定目录。",
                }),
                "device": (["auto", "cpu", "cuda"], {
                    "default": "auto",
                    "tooltip": "推理设备。auto 自动选 CUDA（可用时），cpu 强制 CPU，cuda 不可用时自动回退 CPU。",
                }),
            },
        }

    RETURN_TYPES = (DETECTOR_TYPE,)
    RETURN_NAMES = ("detector",)
    OUTPUT_TOOLTIPS = ("自造检测对象 QG_YOLO_DETECTOR，只能接本包的 QG 简易 Seg 检测节点。",)
    DESCRIPTION = (
        "Load a local Ultralytics YOLO weight and return a self-contained QG_YOLO_DETECTOR "
        "object. Independent of Impact-Pack; requires the ultralytics package at runtime."
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

    def load_detector(self, model_name, device="auto"):
        path = _resolve_model_path(model_name)
        if path is None:
            roots = _candidate_roots("bbox") + _candidate_roots("segm")
            hint = "\n  ".join(roots) if roots else "（未找到任何候选目录）"
            raise ValueError(
                "QG 检测模型加载器找不到模型 %r。已查找目录：\n  %s\n"
                "请把权重放到 models/ultralytics/bbox 或 segm 下，或设置 "
                "QG_ULTRALYTICS_DIR 指向 ultralytics 目录。" % (model_name, hint))
        try:
            from ultralytics import YOLO  # noqa: PLC0415 - 延迟到运行时
        except Exception as exc:
            raise RuntimeError(_YOLO_MISSING) from exc
        try:
            model = YOLO(path)
        except Exception as exc:
            raise RuntimeError(
                "QG 检测模型加载器加载 %r 失败：%s。请确认该权重与本机 "
                "ultralytics 版本兼容。" % (path, exc)) from exc
        kind = model_name.split("/", 1)[0] if "/" in model_name else "bbox"
        detector = QGYoloDetector(model, path, _resolve_device(device), kind)
        return (detector,)


NODE_CLASS_MAPPINGS = {"QG_YoloDetectorLoader": QGYoloDetectorLoader}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_YoloDetectorLoader": "QG 检测模型加载器"}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "DETECTOR_TYPE"]
