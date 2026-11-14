# -*- coding: utf-8 -*-
"""定位 Goohaitools-comfyui（GPL 参考源码，只读对照用）。

历史问题（v0.1.1 修 P0-3）：6 个对照测试把参考源码路径硬编码成某一台
机器的绝对路径；其中 image_scale / mask_detect 在参考缺失时只打印 SKIP
却仍然 ``sys.exit(0)``，导致「零差异」结论在换机器或分发备份包后假通过；
另外 4 个则是直接抛 FileNotFoundError，报错信息不含任何指引。

解析顺序：
  1. 环境变量 ``QG_GOOHAI_REF_ROOT``（显式指定时**只认这一个**，不允许
     悄悄回退到别的副本，避免对照错版本）
  2. ComfyUI 的 ``custom_nodes/Goohaitools-comfyui``（当前部署位置）
  3. 插件包内 ``reference/Goohaitools-comfyui``（便于随包携带）
  4. 环境变量 ``QG_WORKSPACE_REF``（工作区 reference 根目录，可选）

找不到参考目录或文件时打印明确指引并 ``sys.exit(2)``：对照测试绝不允许
静默跳过，缺失必须让测试以非零码失败。
"""
from __future__ import annotations

import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
PKG_ROOT = HERE.parent
CUSTOM_NODES = PKG_ROOT.parent


def _candidates():
    env = os.environ.get("QG_GOOHAI_REF_ROOT")
    if env:
        yield pathlib.Path(env)
        return
    yield CUSTOM_NODES / "Goohaitools-comfyui"
    yield PKG_ROOT / "reference" / "Goohaitools-comfyui"
    ws = os.environ.get("QG_WORKSPACE_REF")
    if ws:
        yield pathlib.Path(ws)


def _fail(what, extra=""):
    print(f"FAIL 找不到 Goohaitools-comfyui GPL 参考源码：{what}")
    print("     对照测试不允许 SKIP 通过，缺参考即判定失败。")
    print("     已尝试的候选位置：")
    for path in _candidates():
        print(f"       - {path}")
    print("     请设置环境变量 QG_GOOHAI_REF_ROOT 指向参考源码根目录后重跑；")
    print("     或把 Goohaitools-comfyui 放回 ComfyUI 的 custom_nodes 目录。")
    if extra:
        print(f"     附加信息：{extra}")
    sys.exit(2)


def ref_root() -> pathlib.Path:
    """返回参考源码根目录；目录缺失或内容不完整则退出码 2。"""
    for root in _candidates():
        if root.is_dir() and ((root / "nodes").is_dir() or (root / "resources").is_dir()):
            return root
    _fail("参考根目录")


def require_ref(*parts: str) -> str:
    """返回参考源码文件的绝对路径（字符串）；文件不存在则退出码 2。"""
    path = ref_root().joinpath(*parts)
    if not path.is_file():
        _fail(str(path))
    return str(path)
