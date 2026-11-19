# -*- coding: utf-8 -*-
"""本包抠图模型目录的**统一解析层**。

设计目的
--------
本包四个调用模型的节点（``QG_PortraitMatte`` / ``QG_BiRefNet`` /
``QG_RemoveBackgroundV2`` / ``QG_MaskByName``）过去各自实现「文件夹路径在哪」
这件事：有的只拼 ``models_dir``，有的问 ``folder_paths.get_folder_paths``，
有的还带插件内置兜底。逻辑重复、口径不一，用户想统一管理模型时无处下手。

本模块只收敛**根目录解析**这一件事，不碰加载器、不改权重文件名、不改下载
源。任何节点想知道「某类模型的候选目录有哪些」，都调用 :func:`category_roots`：

* 先问 ``folder_paths.get_folder_paths(category)`` —— 这会带来
  ``extra_model_paths.yaml`` 里挂载的额外根（例如 ``E:/models``）；
* 再拼 ``models_dir/<category>`` 作为兜底（类别未注册时也能工作）；
* 全部去重保序：挂载优先于本地默认，先命中者胜出。

配套原语：:func:`models_root`（ComfyUI models 根）、:func:`bundled_dir`
（插件随包模型目录）、:func:`first_writable`（挑一个可写目录用于下载）。

用户偏好「统一放置位置」的实现口径
------------------------------------
* 随包 modnet 与 SAM3 保持原位：前者在 ``<插件>/models/background_removal``
  随分发走，后者必须留在 ``checkpoints``（ComfyUI 核心 checkpoint loader 只认
  这个类别）。这两类**不通过本模块改位置**。
* 其余抠图模型（BiRefNet 家族、rmbg-1.4、birefnet-v1-lite、ViTMatte）统一收敛
  到 ``background_removal`` 类别。BiRefNet 的历史目录 ``models/RMBG`` 仅作
  **兼容读取**，新下载不再写进去，避免与 ComfyUI-RMBG 插件各自维护副本。
* 加载器、预处理、权重文件名一律不变，本模块不推理、不下载，只回答路径。

测试友好
--------
在无 ComfyUI 的脚本环境（``folder_paths`` 是 stub、甚至缺失）下全部函数可用，
退路是相对本文件推断 ``<插件>/../../models``，保证单文件 spec 加载不炸。
"""

from __future__ import annotations

import os
import tempfile


def models_root():
    """ComfyUI 的 ``models`` 根目录绝对路径；拿不到就按插件位置推断。"""
    try:
        import folder_paths
        root = getattr(folder_paths, "models_dir", None)
        if root:
            return str(root)
    except Exception:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "..", "models"))


def category_roots(category, *extra_categories, root=None):
    """某模型类别的候选根目录，去重保序。

    顺序：``folder_paths.get_folder_paths(category)``（含 ``extra_model_paths``
    挂载，多个类别按参数顺序）→ ``models_root/<category>`` 兜底。返回值都是
    字符串路径，调用方自行拼子目录或文件名。

    ``extra_categories`` 用于「主类别 + 兼容历史类别」合并扫描：例如 BiRefNet
    读 ``background_removal`` 时也读历史 ``RMBG`` 根，但下载落点只认主类别。

    ``root`` 可选：显式指定 models 根（测试用它注入临时目录），默认取
    :func:`models_root`。
    """
    if root is None:
        root = models_root()
    roots = []

    def _add(path):
        if path and path not in roots:
            roots.append(path)

    try:
        import folder_paths
        getter = getattr(folder_paths, "get_folder_paths", None)
        if callable(getter):
            for name in (category,) + tuple(extra_categories):
                try:
                    for path in getter(name):
                        _add(str(path))
                except Exception:
                    # 类别未注册（如 portable 没注册 RMBG）就跳过，不致命
                    continue
    except Exception:
        pass

    _add(os.path.join(str(root), category))
    for name in extra_categories:
        _add(os.path.join(str(root), name))
    return roots


def primary_root(category, root=None):
    """新下载/新放置的唯一落点：``models_root/<category>``（可写优先）。

    与 :func:`category_roots` 的区别：这里**不含挂载路径**。挂载库只读、不写，
    新模型统一落到本机主库，避免同一权重散落多个根、日后难以管理。

    ``root`` 可选：显式指定 models 根（测试注入临时目录用）。
    """
    if root is None:
        root = models_root()
    return os.path.join(str(root), category)


def bundled_dir(category="background_removal"):
    """插件随包模型目录 ``<插件>/models/<category>``，与 folder_paths 无关。

    纯离线、无 ComfyUI 环境也能定位；随包 modnet 用它做最后兜底。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "models", category)


def first_writable(directories):
    """从候选目录里挑第一个能创建探针文件的绝对路径，都不可用返回 None。

    用于下载落点：优先用 primary_root，实在不可写再依次退到挂载/临时目录，
    保证受限环境仍能跑，同时不把模型塞进只读的挂载库。
    """
    for directory in directories:
        if not directory:
            continue
        path = str(directory)
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, ".qg_write_probe")
            with open(probe, "w", encoding="utf-8") as handle:
                handle.write("1")
            os.remove(probe)
            return path
        except Exception:
            continue
    fallback = os.path.join(tempfile.gettempdir(), "qg_model_cache")
    try:
        os.makedirs(fallback, exist_ok=True)
        return fallback
    except Exception:
        return None


# 让单文件加载与本包相对导入两种场景都能用；不改变任何节点行为。
__all__ = ["models_root", "category_roots", "primary_root",
           "bundled_dir", "first_writable"]
