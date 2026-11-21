# -*- coding: utf-8 -*-
"""QG_UltralyticsDetectorLoader —— QG 检测加载器 (Ultralytics)。

规格参考 ComfyUI-Impact-Subpack 的 UltralyticsDetectorProvider
（ltdrdata/ComfyUI-Impact-Subpack，AGPL-3.0），**按规格独立实现，未逐行复制
其源码**：模型目录扫描、多级路径解析、软依赖探测、中文说明都是为本包写的。
检测器的构造在运行时调用 Impact-Subpack 的公开接口（subcore.load_yolo /
UltraBBoxDetector / UltraSegmDetector / NO_SEGM_DETECTOR）。

为什么必须依赖 Impact-Subpack
----------------------------
输出类型 BBOX_DETECTOR / SEGM_DETECTOR 是 Impact 生态的自定义类型，返回的
检测器对象也必须是它的 UltraBBoxDetector / UltraSegmDetector 实例，否则下游
（Detailer、本包 QG_SimpleSegDetectorSEGS 等）无法调用 detect。因此这些
**类型字符串不能加本包前缀**，必须与 Impact 逐字一致；这是跨包连线契约。
未装 Impact-Subpack 时节点照常注册、模型列表照常显示（本包自己扫描目录），
只在真正执行时给出可照做的中文提示，不拖垮本包其余节点。

模型目录
--------
优先用 Impact-Subpack 注册过的 folder key（ultralytics_bbox /
ultralytics_segm / ultralytics），未注册时回退到 models/ultralytics/{bbox,segm}
及 extra_model_paths 挂载点。下拉项格式与 Impact 一致：bbox/xxx.pt、segm/xxx.pt。
"""
from __future__ import annotations

import os

_SUBCORE = None
_SUBPACK_MISSING = (
    "QG 检测加载器需要本机安装 ComfyUI-Impact-Subpack：输出类型 "
    "BBOX_DETECTOR / SEGM_DETECTOR 与返回的检测器对象都由它定义，模型加载也"
    "调用它的公开接口。请把 ComfyUI-Impact-Subpack 放进 custom_nodes 并完整"
    "重启 ComfyUI，再使用本节点。"
)

# 脱离 ComfyUI 的测试进程用这份后缀兜底；在 ComfyUI 内优先用 folder_paths 的
# supported_pt_extensions，避免漏掉用户额外注册的模型后缀。
_FALLBACK_EXTS = (".pt", ".pth", ".ckpt", ".bin", ".safetensors")


def _folder_paths_module():
    """懒导入 ComfyUI 的 folder_paths；测试进程里没有时返回 None。"""
    try:
        import folder_paths  # noqa: PLC0415 - 故意延迟，便于测试注入
    except Exception:
        return None
    return folder_paths


def _model_extensions(fp):
    exts = getattr(fp, "supported_pt_extensions", None) if fp is not None else None
    if not exts:
        return _FALLBACK_EXTS
    return tuple(str(ext).lower() for ext in exts)


def _candidate_roots(kind, fp):
    """返回 bbox/segm 的候选模型根目录，去重保序。"""
    roots = []
    if fp is not None:
        # 1) Impact-Subpack 自己注册的专用 folder key（含 extra_model_paths）
        key = "ultralytics_bbox" if kind == "bbox" else "ultralytics_segm"
        try:
            roots.extend(fp.get_folder_paths(key))
        except Exception:
            pass
        # 2) Impact-Subpack 注册的 ultralytics 根，下面按 bbox/segm 分子目录
        try:
            roots.extend(os.path.join(r, kind) for r in fp.get_folder_paths("ultralytics"))
        except Exception:
            pass
        # 3) 本机主模型库兜底（Subpack 未安装或未注册时仍能看到模型）
        models_dir = getattr(fp, "models_dir", None)
        if models_dir:
            roots.append(os.path.join(models_dir, "ultralytics", kind))
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


def _scan_models(kind, fp=None):
    """扫描某类模型的相对条目（不含 bbox/ 前缀），排序去重。"""
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
    """把 bbox/xxx.pt、segm/xxx.pt 解析成本机绝对路径，找不到返回 None。"""
    if fp is None:
        fp = _folder_paths_module()
    kind = None
    rel = model_name
    if model_name.startswith("bbox/"):
        kind, rel = "bbox", model_name[5:]
    elif model_name.startswith("segm/"):
        kind, rel = "segm", model_name[5:]

    # 1) Subpack 注册过的 ultralytics 根（它支持带子目录前缀的查找）
    if fp is not None:
        try:
            path = fp.get_full_path("ultralytics", model_name)
            if path and os.path.isfile(path):
                return os.path.normpath(path)
        except Exception:
            pass
        # 2) 按前缀到专用 folder key 里找
        if kind is not None:
            key = "ultralytics_bbox" if kind == "bbox" else "ultralytics_segm"
            try:
                path = fp.get_full_path(key, rel)
                if path and os.path.isfile(path):
                    return os.path.normpath(path)
            except Exception:
                pass
    # 3) 本包自己扫描到的候选根目录
    if kind is not None:
        for root in _candidate_roots(kind, fp):
            path = os.path.join(root, rel)
            if os.path.isfile(path):
                return path
    return None


def _load_subcore():
    """运行时取 Impact-Subpack 的 subcore；缺失只在本节点执行时提示。"""
    global _SUBCORE
    if _SUBCORE is not None:
        return _SUBCORE

    import sys  # noqa: PLC0415

    # Subpack 已被 ComfyUI 加载时子模块必在 sys.modules，直接复用最稳，
    # 也避开带连字符的包名在 importlib 里的路径歧义。
    for module in list(sys.modules.values()):
        if (hasattr(module, "load_yolo") and hasattr(module, "UltraBBoxDetector")
                and hasattr(module, "UltraSegmDetector")):
            _SUBCORE = module
            return module

    err = None
    try:
        import importlib  # noqa: PLC0415
        module = importlib.import_module("custom_nodes.ComfyUI-Impact-Subpack.modules.subcore")
        if hasattr(module, "load_yolo"):
            _SUBCORE = module
            return module
    except Exception as exc:  # noqa: BLE001 - 依赖缺失形态不止一种
        err = exc
    raise RuntimeError(_SUBPACK_MISSING) from err


class QGUltralyticsDetectorLoader:
    """加载 Ultralytics YOLO 模型，输出 Impact 生态的 BBOX/SEGM 检测器。"""

    @classmethod
    def INPUT_TYPES(cls):
        models = ["bbox/" + x for x in _scan_models("bbox")]
        models += ["segm/" + x for x in _scan_models("segm")]
        if not models:
            # 下拉不能是空列表（ComfyUI 前端会渲染成空控件）；给一条中文占位。
            models = ["（未找到 ultralytics 模型，请检查 models/ultralytics/{bbox,segm}）"]
        return {
            "required": {
                "model_name": (models, {
                    "tooltip": "选择本机 ultralytics 权重。bbox/ 开头只给矩形框，segm/ 开头同时给出实例分割遮罩；放在 models/ultralytics/bbox 或 segm 目录下。",
                }),
            },
        }

    RETURN_TYPES = ("BBOX_DETECTOR", "SEGM_DETECTOR")
    RETURN_NAMES = ("bbox_detector", "segm_detector")
    FUNCTION = "load_detector"
    CATEGORY = "QG 工具"
    OUTPUT_TOOLTIPS = (
        "Impact 生态的 BBox 检测器对象，可接 QG 简易 Seg 检测等节点。",
        "Impact 生态的 SEGM 检测器对象；bbox 模型返回空检测器占位。",
    )
    DESCRIPTION = (
        "Load a local Ultralytics YOLO model and return Impact-compatible "
        "BBOX_DETECTOR and SEGM_DETECTOR objects. Requires ComfyUI-Impact-Subpack."
    )

    @classmethod
    def IS_CHANGED(cls, model_name):
        """用权重文件的修改时间与大小做缓存键，换了模型或改了文件才会重跑。"""
        path = _resolve_model_path(model_name)
        if path is None:
            return float("nan")
        try:
            stat = os.stat(path)
            return "%s:%s" % (stat.st_mtime, stat.st_size)
        except OSError:
            return float("nan")

    def load_detector(self, model_name):
        path = _resolve_model_path(model_name)
        if path is None:
            candidates = []
            for kind in ("bbox", "segm"):
                candidates.extend(_candidate_roots(kind, _folder_paths_module()))
            hint = "\n  ".join(candidates) if candidates else "（未找到模型目录）"
            raise ValueError(
                "QG 检测加载器找不到模型 %r。已查找目录：\n  %s\n"
                "请把权重放到 models/ultralytics/bbox 或 models/ultralytics/segm 下，"
                "或在 extra_model_paths.yaml 里挂载对应目录。" % (model_name, hint)
            )
        subcore = _load_subcore()
        model = subcore.load_yolo(path)
        bbox_detector = subcore.UltraBBoxDetector(model)
        if model_name.startswith("bbox/"):
            segm_detector = subcore.NO_SEGM_DETECTOR()
        else:
            segm_detector = subcore.UltraSegmDetector(model)
        return (bbox_detector, segm_detector)


NODE_CLASS_MAPPINGS = {
    "QG_UltralyticsDetectorLoader": QGUltralyticsDetectorLoader,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "QG_UltralyticsDetectorLoader": "QG 检测加载器 (Ultralytics)",
}
