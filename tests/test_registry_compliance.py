# -*- coding: utf-8 -*-
"""Comfy Registry 发布合规静态回归测试。

依据官方文档 docs.comfy.org/registry/standards 的三条安全红线：
  1. 禁止 eval / exec 调用（RCE 风险）
  2. 禁止 subprocess 运行时 pip install（供应链攻击风险）
  3. 禁止代码混淆

本测试用 AST 精确识别「内置 eval/exec 的直接调用」与「subprocess 调 pip」，
避免把 PyTorch 的 ``model.eval()``、测试里的 ``exec(code, mod.__dict__)``
（对照加载器，非节点本体）误判成违规。节点本体指包根目录下所有 .py，
不含 tests/ 与 reference/。
"""
from __future__ import annotations

import ast
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
PKG_ROOT = HERE.parent

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} {detail}")


def node_sources():
    """包根目录下的节点本体 .py（排除 tests / reference / 前端 / 缓存）。"""
    for path in sorted(PKG_ROOT.glob("*.py")):
        yield path


def builtin_call_violations(tree: ast.AST, banned: set[str]) -> list[str]:
    """找出直接调用内置 eval/exec 的位置（排除 obj.eval() 这类方法调用）。"""
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in banned:
            hits.append(f"{banned & {func.id}}@{node.lineno}")
    return hits


def subprocess_pip_violations(tree: ast.AST) -> list[str]:
    """找出 subprocess 调用中把 pip / -m pip 作为命令参数的写法。"""
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # subprocess.run / Popen / check_output / call 等
        is_subprocess = (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
        )
        if not is_subprocess:
            continue
        flat = []
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            if isinstance(arg, (ast.List, ast.Tuple)):
                flat.extend(
                    elt.value for elt in arg.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                )
            elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                flat.append(arg.value)
        joined = " ".join(flat).lower()
        if "pip" in joined and "install" in joined:
            hits.append(f"subprocess-pip@{node.lineno}")
    return hits


def imported_modules(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
    return names


def main() -> int:
    print("=== Comfy Registry 发布合规静态回归 ===\n")

    total_eval = []
    total_pip = []
    obfuscation_hits = []
    files = list(node_sources())
    check("节点本体文件可枚举", bool(files), f"找到 {len(files)} 个")

    for path in files:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
        for hit in builtin_call_violations(tree, {"eval", "exec"}):
            total_eval.append(f"{path.name}:{hit}")
        for hit in subprocess_pip_violations(tree):
            total_pip.append(f"{path.name}:{hit}")
        mods = imported_modules(tree)
        if "subprocess" in mods and "pip" in src.lower():
            obfuscation_hits.append(f"{path.name}: 同时 import subprocess 且出现 pip 字样")

    check("节点本体无内置 eval/exec 调用", not total_eval, str(total_eval))
    check("节点本体无 subprocess pip install", not total_pip, str(total_pip))
    check("无 subprocess+pip 组合残留", not obfuscation_hits, str(obfuscation_hits))

    # 特化：Qwen 优化节点必须给出手动安装指引，且不再带自动安装实现。
    qwen = (PKG_ROOT / "qwen_prompt_optimizer_node.py").read_text(encoding="utf-8")
    qwen_tree = ast.parse(qwen)
    func_names = {
        node.name for node in ast.walk(qwen_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    check("保留 _llama_manual_hint 手动指引函数", "_llama_manual_hint" in func_names)
    check("已移除 _install_llama_cpp 自动安装", "_install_llama_cpp" not in func_names)
    check("已移除 _find_llama_wheel 联网查 wheel", "_find_llama_wheel" not in func_names)
    check("保留安装路由名（对照测试依赖）", "qg_qwen_install_llama" in qwen)

    # 前端不得再向安装路由发起 POST。
    web_js = (PKG_ROOT / "web" / "qg_qwen_prompt_optimizer.js").read_text(encoding="utf-8")
    check("前端已移除 LLAMA_INSTALL_ROUTE", "LLAMA_INSTALL_ROUTE" not in web_js)
    check("前端不再 POST install_llama", "install_llama" not in web_js)

    # 元数据：description 节点数与实际一致。
    import re as _re
    pyproject = (PKG_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = _re.search(r"^description\s*=\s*\"([^\"]+)\"", pyproject, _re.M)
    desc = m.group(1) if m else ""
    check("description 声明 32 个节点（与实际一致）", "32 个节点" in desc, desc[:120])

    # [tool.comfy].PublisherId 必填且非空（Registry 发布硬要求，创建后不可改）。
    pm = _re.search(r'^PublisherId\s*=\s*"([^"]*)"', pyproject, _re.M)
    publisher = pm.group(1).strip() if pm else ""
    check("PublisherId 已填写且非空", bool(publisher), repr(publisher))
    check("PublisherId 与预期账号一致", publisher == "live1617", repr(publisher))
    check("version 符合语义化版本", bool(_re.search(
        r'^version\s*=\s*"\d+\.\d+\.\d+"', pyproject, _re.M)))

    # Icon（可选但已启用）：官方要求公开 URL、SVG/PNG/JPG/GIF、≤400×400、正方形。
    im = _re.search(r'^Icon\s*=\s*"([^"]*)"', pyproject, _re.M)
    icon = im.group(1).strip() if im else ""
    check("Icon 已填写且非空", bool(icon), repr(icon))
    check("Icon 是 https 公开 URL", icon.startswith("https://"), repr(icon))
    check("Icon 指向本仓库 raw 文件",
          icon.startswith("https://raw.githubusercontent.com/live1617/ComfyUI-QG-Multipack/"), repr(icon))
    icon_path = PKG_ROOT / "icon.svg"
    check("仓库根目录存在 icon.svg", icon_path.exists())
    if icon_path.exists():
        svg = icon_path.read_text(encoding="utf-8")
        wm = _re.search(r'\bwidth="(\d+)"', svg)
        hm = _re.search(r'\bheight="(\d+)"', svg)
        w = int(wm.group(1)) if wm else 0
        h = int(hm.group(1)) if hm else 0
        check("icon.svg 为 400×400 正方形（符合 Registry 上限）", w == 400 and h == 400, f"{w}x{h}")
        check("icon.svg 是合法 SVG（含 viewBox）", "<svg" in svg and "viewBox" in svg)

    # .comfyignore 存在且排除 tests/，避免开发文件进入 Registry 包。
    ci = PKG_ROOT / ".comfyignore"
    check("存在 .comfyignore", ci.exists())
    if ci.exists():
        ci_text = ci.read_text(encoding="utf-8")
        check(".comfyignore 排除 tests/", "tests/" in ci_text)

    print(f"\n===== 合计 {PASS + FAIL} 项，FAIL {FAIL} =====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
