# -*- coding: utf-8 -*-
"""QG 模型扫描与路径解析公共层 —— 两个加载器共用，避免各写一遍。

背景
----
``QG_YoloDetectorLoader`` 与 ``QG_SamModelLoader`` 原先各自实现了同一套东西：
候选根推导、递归扫描、下拉值的路径安全解析、设备解析、文件签名。两份代码逐行
几乎相同，改一处必须记得改另一处（``_scan_models`` 加子目录支持时就差点漏掉
SAM 那份）。本模块把这几件事收敛成一份。

职责边界
--------
只回答「有哪些权重」「这个下拉值对应哪个文件」「该用哪个设备」「文件变了没」，
**不加载任何权重、不 import ultralytics / segment_anything**；缺库提示仍由各
加载器自己给。两个加载器保留同名薄封装（``_scan_models`` 等），测试与旧调用
点的符号不变。

约定
----
* 候选根：先问 ``folder_paths.get_folder_paths(category)``（含
  ``extra_model_paths`` 挂载），再拼 ``models_dir/<category>`` 与各挂载 models
  根下的同名子目录，最后追加调用方给的额外根（环境变量目录）。全部去重保序。
* 扫描递归但限深（默认 3 层），跳过隐藏目录与 ``__pycache__``——与 ComfyUI
  自身 ``get_filename_list`` 的口径一致，用户按型号建子目录整理权重时不会整批
  消失。
* 解析下拉值拒绝绝对路径、盘符与 ``..`` 上跳，并用 ``commonpath`` 校验结果仍
  留在候选根内。

导入方式
--------
包上下文走相对导入，单文件/顶层加载走绝对导入，两种场景都要能用：

    try:
        from . import qg_model_scan as _scan
    except ImportError:
        import qg_model_scan as _scan
"""
from __future__ import annotations

import os

#: folder_paths 拿不到时用的权重后缀兜底。
FALLBACK_EXTS = (".pth", ".pt", ".ckpt", ".bin", ".safetensors")

#: 递归扫描默认深度上限（不含根目录本身）。
DEFAULT_MAX_DEPTH = 3


def folder_paths_module():
    """拿 ComfyUI 的 folder_paths 模块；无 ComfyUI 环境返回 None。"""
    try:
        import folder_paths  # noqa: PLC0415 - 延迟导入，便于测试注入
    except Exception:
        return None
    return folder_paths


def model_extensions(fp=None):
    """该环境认可的权重后缀（小写元组）；拿不到用 FALLBACK_EXTS。"""
    if fp is None:
        fp = folder_paths_module()
    exts = getattr(fp, "supported_pt_extensions", None) if fp is not None else None
    return tuple(str(e).lower() for e in exts) if exts else FALLBACK_EXTS


def dedupe(paths):
    """规范化并去重保序（保留第一个出现的写法与顺序）。"""
    seen = set()
    out = []
    for path in paths:
        if not path:
            continue
        norm = os.path.normpath(str(path))
        key = os.path.normcase(norm)
        if key not in seen:
            seen.add(key)
            out.append(norm)
    return out


def models_roots(fp=None):
    """所有 models 根目录，去重保序。

    来源：``folder_paths.models_dir``（本机主库）+ 从 ``folder_names_and_paths``
    各已注册类别路径向上反推的 models 根（``extra_model_paths`` 挂载的库）。
    反推是为了让挂载库下的 ``<root>/ultralytics``、``<root>/sams`` 也能被看见。
    """
    if fp is None:
        fp = folder_paths_module()
    roots = []
    if fp is not None:
        models_dir = getattr(fp, "models_dir", None)
        if models_dir:
            roots.append(models_dir)
        try:
            for value in getattr(fp, "folder_names_and_paths", {}).values():
                if not isinstance(value, (tuple, list)) or not value:
                    continue
                first = value[0]
                paths = first if isinstance(first, (tuple, list)) else [first]
                for path in paths:
                    if path:
                        roots.append(os.path.dirname(str(path)))
        except Exception:
            pass
    return dedupe(roots)


def category_roots(category, fp=None, extra=()):
    """某模型类别的候选根目录，去重保序。

    顺序：``get_folder_paths(category)``（含挂载）→ ``models_roots/<category>``
    → ``extra``（环境变量目录等调用方额外指定的根）。

    ``category`` 可以是单个名字，也可以是多个名字的序列：加载器用两个历史 key
    登记同一类权重时（SAM 的 ``sams`` / ``sam``）一次传入即可。
    """
    if fp is None:
        fp = folder_paths_module()
    names = (category,) if isinstance(category, str) else tuple(category)
    roots = []
    if fp is not None:
        getter = getattr(fp, "get_folder_paths", None)
        if callable(getter):
            for name in names:
                try:
                    roots.extend(getter(name))
                except Exception:
                    continue          # 类别未注册（portable 常见）不算错
    for base in models_roots(fp):
        for name in names:
            roots.append(os.path.join(base, name))
    roots.extend(extra)
    return dedupe(roots)


def walk_relative(root, exts, max_depth=DEFAULT_MAX_DEPTH):
    """递归产出 ``(相对名, 绝对路径)``，相对名用 ``/`` 分隔。

    限深、跳过隐藏目录与 ``__pycache__``；非文件条目（断链符号链接等）跳过。
    """
    if not root or not os.path.isdir(root):
        return
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        depth = 0 if rel_dir in (".", "") else rel_dir.count(os.sep) + 1
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d != "__pycache__"]
        if depth >= max_depth:
            dirnames[:] = []
        for name in filenames:
            if not name.lower().endswith(exts):
                continue
            full = os.path.join(dirpath, name)
            if not os.path.isfile(full):
                continue
            rel = name if depth == 0 else os.path.relpath(full, root).replace(os.sep, "/")
            yield rel, full


def scan_category(category, fp=None, extra=(), max_depth=DEFAULT_MAX_DEPTH):
    """扫一个类别下的权重，返回排序后的相对名列表（子目录用 ``/`` 分隔）。"""
    if fp is None:
        fp = folder_paths_module()
    exts = model_extensions(fp)
    found = set()
    for root in category_roots(category, fp, extra):
        for rel, _full in walk_relative(root, exts, max_depth):
            found.add(rel)
    return sorted(found)


def split_relative(name):
    """把下拉值拆成安全的分段列表；疑似越界返回 None。

    拒绝：空值、绝对路径（``/`` ``\\`` 开头）、含盘符或冒号、``..`` 上跳。
    """
    text = str(name or "").strip().replace("\\", "/")
    if not text or text.startswith("/") or ":" in text:
        return None
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return parts


def resolve_in_roots(parts, roots):
    """在候选根里逐个拼 ``parts``，返回第一个存在的文件绝对路径，否则 None。

    额外做 ``commonpath`` 校验：符号链接或盘符差异导致解析结果跳出候选根时跳过。
    """
    if not parts:
        return None
    for root in roots:
        path = os.path.normpath(os.path.join(root, *parts))
        try:
            base = os.path.normcase(os.path.abspath(root))
            target = os.path.normcase(os.path.abspath(path))
            if os.path.commonpath([base, target]) != base:
                continue
        except ValueError:
            continue
        if os.path.isfile(path):
            return path
    return None


def resolve_device(device):
    """把下拉的 auto/cpu/cuda 落成实际设备字符串；CUDA 不可用时回退 CPU。"""
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


def file_signature(path):
    """``IS_CHANGED`` 用：返回 ``mtime:size``；文件不存在返回 nan（每次重跑）。"""
    if not path:
        return float("nan")
    try:
        stat = os.stat(path)
        return "%s:%s" % (stat.st_mtime, stat.st_size)
    except OSError:
        return float("nan")


__all__ = [
    "FALLBACK_EXTS", "DEFAULT_MAX_DEPTH",
    "dedupe", "folder_paths_module", "model_extensions", "models_roots", "category_roots",
    "walk_relative", "scan_category", "split_relative", "resolve_in_roots",
    "resolve_device", "file_signature",
]
