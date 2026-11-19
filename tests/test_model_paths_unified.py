# -*- coding: utf-8 -*-
"""抠图模型目录统一层 qg_model_paths：契约 + 行为 + 四节点接入。

背景：本包四个调用模型的节点过去各自拼模型根目录，口径不一。v2.19 把
「根目录解析」收敛到 qg_model_paths，本测试固化以下契约：

* category_roots 先挂载后本地、去重保序，支持额外兼容类别；
* primary_root 只给本机主库落点，不含挂载（新模型不写只读挂载库）；
* root 参数可注入，保留各节点的可 mock 点；
* bundled_dir 与 folder_paths 无关，离线可用；
* 四节点确实改用统一层（BiRefNet 下载落点改 background_removal，
  历史 RMBG 仍可读；SAM3 / 随包 modnet 保持原位不受影响）；
* 打包脚本不会漏掉新模块。

不依赖 GPL 参考源码，可单独运行。
"""
import importlib.util
import os
import pathlib
import sys
import tempfile
import types

HERE = pathlib.Path(__file__).resolve().parent
PKG = HERE.parent
FAILED = []


def check(name, cond, extra=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        FAILED.append(name)
        print("  FAIL  %s  %s" % (name, extra))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 用假的 folder_paths 精确控制「挂载 + 本地」两路输入
# ---------------------------------------------------------------------------
def install_fake_folder_paths(mounts, models_dir):
    fake = types.ModuleType("folder_paths")
    fake.models_dir = models_dir
    fake.get_folder_paths = lambda name: list(mounts.get(name, []))
    fake.get_filename_list = lambda name: []
    fake.get_full_path = lambda name, filename: os.path.join(
        mounts.get(name, [models_dir])[0], filename)
    sys.modules["folder_paths"] = fake
    return fake


def main():
    print("=== qg_model_paths 契约 ===")
    real_fp = sys.modules.get("folder_paths")
    # 统一层只读 folder_paths.models_dir / get_folder_paths，造一个最小 stub
    with tempfile.TemporaryDirectory() as td:
        install_fake_folder_paths(
            {"background_removal": ["M:/mount/bg", "N:/other/bg"],
             "RMBG": ["M:/mount/rmbg"]},
            td,
        )
        sys.path.insert(0, str(PKG))
        QP = load_module("qg_model_paths", str(PKG / "qg_model_paths.py"))

        roots = QP.category_roots("background_removal")
        check("挂载路径在前", roots[0] == "M:/mount/bg", str(roots))
        check("第二挂载也在", "N:/other/bg" in roots)
        check("本地 models_dir 兜底在最后",
              roots[-1] == os.path.join(td, "background_removal"), str(roots))
        check("去重（不重复本地根）",
              len(roots) == len(set(roots)), str(roots))

        roots2 = QP.category_roots("background_removal", "RMBG", root=td)
        check("额外兼容类别一并扫描", "M:/mount/rmbg" in roots2, str(roots2))
        check("额外类别的本地兜底也在",
              os.path.join(td, "RMBG") in roots2, str(roots2))

        primary = QP.primary_root("background_removal", root=td)
        check("primary_root 只给本机主库",
              primary == os.path.join(td, "background_removal"), primary)
        check("primary_root 不含挂载",
              not any(p.startswith("M:/") for p in [primary]), primary)

        bundled = QP.bundled_dir("background_removal")
        check("bundled_dir 指向插件内置目录",
              bundled == str(PKG / "models" / "background_removal"), bundled)

        # 注入 root 覆盖 stub 的 models_dir（保留调用方可 mock 性）
        injected = QP.category_roots("background_removal", root="X:/injected")
        check("root 参数覆盖本地兜底",
              injected[-1].replace("\\", "/") ==
              "X:/injected/background_removal", str(injected))

        # first_writable：跳过不可写，选能写的
        good = os.path.join(td, "writable")
        chosen = QP.first_writable(["Z:/no/such/dir", good])
        check("first_writable 挑到可写目录", chosen == good, str(chosen))
        check("first_writable 建了目录", os.path.isdir(good))

    print("\n=== 四节点接入统一层（静态断言）===")
    matte = (PKG / "_matte_models.py").read_text(encoding="utf-8")
    biref = (PKG / "birefnet_node.py").read_text(encoding="utf-8")
    remove = (PKG / "qg_remove_background_v2.py").read_text(encoding="utf-8")
    by_name = (PKG / "mask_by_name_node.py").read_text(encoding="utf-8")

    check("_matte_models 接入统一层", "qg_model_paths" in matte
          and "_QP.category_roots" in matte)
    check("_matte_models 落点用 primary_root", "_QP.primary_root" in matte)
    check("_matte_models 保留可 mock 的 _models_root",
          "root=_models_root()" in matte)
    check("_matte_models 仍扫内置的 modnet", "_bundled_dir" in matte)

    check("BiRefNet 下载落点改 background_removal",
          '_QP.primary_root("background_removal")' in biref)
    check("BiRefNet 兼容读取旧 RMBG",
          '"RMBG"' in biref and "legacy" in biref)
    check("BiRefNet 挂载经统一层",
          '_QP.category_roots("background_removal", "RMBG", "BiRefNet")' in biref)
    check("BiRefNet 新落点不再写 models/RMBG",
          'os.path.join(folder_paths.models_dir, "RMBG")' not in biref)

    check("RemoveBackgroundV2 ViTMatte 经统一层",
          '_QP.category_roots("background_removal")' in remove)

    check("SAM3 仍用 checkpoints（未改）",
          'get_filename_list("checkpoints")' in by_name
          and 'get_full_path("checkpoints"' in by_name)
    check("SAM3 未接入统一层（按用户要求排除）",
          "qg_model_paths" not in by_name)

    print("\n=== 打包脚本不漏新模块 ===")
    # 打包脚本住在工作区、不在插件包里；布局随机器而变（同 test_bundled_matte_models）
    pack = None
    cands = [PKG.parent, pathlib.Path("D:/WorkBuddy/ComfyUI-QG-Multipack")]
    if os.environ.get("QG_WORKSPACE"):
        cands.insert(0, pathlib.Path(os.environ["QG_WORKSPACE"]))
    for base in cands:
        p = base / "打包备份.py"
        if p.is_file():
            pack = p.read_text(encoding="utf-8")
            break
    if pack is None:
        print("  SKIP 找不到打包脚本，跳过该项")
    else:
        check("打包脚本按目录整体打包（新 py 自动入包）",
              "make_zip" in pack or "shutil.make_archive" in pack
              or "os.walk" in pack)

    if real_fp is not None:
        sys.modules["folder_paths"] = real_fp
    else:
        sys.modules.pop("folder_paths", None)

    print("\n== 汇总：失败 %d ==" % len(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
