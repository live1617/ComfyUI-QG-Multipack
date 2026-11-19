# -*- coding: utf-8 -*-
"""rmbg-1.4 从 ``models/background_removal/RMBG-1.4/`` 子目录读取的契约。

用户 2026-11-19 要求：官方 RMBG-1.4 完整权重（model.pth + rmbg-1.4.onnx）
按仓库结构放在 RMBG-1.4/ 子目录，``QG_PortraitMatte`` 选 rmbg-1.4 时要能读到。
此前 ``discover()`` 只扫根目录，子目录里的 onnx 读不到。本测试固化：

* ``resolve("rmbg-1.4")`` 优先命中子目录里的 rmbg-1.4.onnx；
* 子目录没有时退回根目录旧文件（兼容，不删不搬）；
* 自动下载落点也在子目录，与读取口径一致；
* 挂载路径（extra_model_paths）下的 RMBG-1.4/ 同样可命中；
* 其余模型（modnet / birefnet）的路径逻辑不受影响。

不依赖 GPL 参考源码，不真实下载，可单独运行。
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


def load_matte_models():
    """以包别名加载单文件模块，相对导入 qg_model_paths 不受影响。"""
    pkg_name = "qgpkg_rmbg_test"
    if pkg_name not in sys.modules:
        holder = types.ModuleType(pkg_name)
        holder.__path__ = [str(PKG)]
        sys.modules[pkg_name] = holder
    mod_name = pkg_name + "._matte_models"
    spec = importlib.util.spec_from_file_location(
        mod_name, str(PKG / "_matte_models.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod, pkg_name


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
    real_fp = sys.modules.get("folder_paths")
    M, pkg_name = load_matte_models()
    DL = importlib.import_module(pkg_name + "._model_download") \
        if pkg_name in sys.modules else None

    with tempfile.TemporaryDirectory() as td:
        install_fake_folder_paths({}, td)
        bg = os.path.join(td, "background_removal")
        sub = os.path.join(bg, "RMBG-1.4")
        os.makedirs(sub, exist_ok=True)

        orig_root = M._models_root
        M._models_root = lambda: td
        try:
            print("\n[1] 子目录命中优先")
            sub_onnx = os.path.join(sub, "rmbg-1.4.onnx")
            with open(sub_onnx, "wb") as fh:
                fh.write(b"ONNX-sub")
            got = M.resolve("rmbg-1.4")
            check("resolve 命中 RMBG-1.4/ 子目录", got == sub_onnx,
                  str(got))
            check("family_of 仍按文件名判为 rmbg",
                  M.family_of(got) == "rmbg")

            # 根目录也放一份旧的，确认子目录优先（旧文件不删不搬）
            root_onnx = os.path.join(bg, "rmbg-1.4.onnx")
            with open(root_onnx, "wb") as fh:
                fh.write(b"ONNX-root")
            check("子目录存在时优先于根目录旧文件",
                  M.resolve("rmbg-1.4") == sub_onnx)

            print("\n[2] 子目录缺失时退回根目录兼容读取")
            os.remove(sub_onnx)
            check("子目录无文件则用根目录旧 onnx",
                  M.resolve("rmbg-1.4") == root_onnx,
                  str(M.resolve("rmbg-1.4")))

            print("\n[3] 挂载路径下的 RMBG-1.4/ 同样命中")
            with tempfile.TemporaryDirectory() as mount:
                sub2 = os.path.join(mount, "RMBG-1.4")
                os.makedirs(sub2, exist_ok=True)
                pth = os.path.join(sub2, "rmbg-1.4.onnx")
                with open(pth, "wb") as fh:
                    fh.write(b"ONNX-mount")
                sys.modules["folder_paths"].get_folder_paths = \
                    lambda name: [mount] if name == "background_removal" else []
                check("挂载优先：命中挂载根的子目录",
                      M.resolve("rmbg-1.4") == pth, str(M.resolve("rmbg-1.4")))
                sys.modules["folder_paths"].get_folder_paths = lambda name: []

            print("\n[4] 自动下载落点在子目录（不真下，mock http_download）")
            # 清空所有本地候选，强制走 _resolve_preset
            if os.path.exists(root_onnx):
                os.remove(root_onnx)
            import importlib as _il
            DL = _il.import_module(pkg_name + "._model_download")
            orig_dl = DL.http_download
            orig_url = M.PRESET_MODELS["rmbg-1.4"]["url"]
            orig_hint = M.PRESET_MODELS["rmbg-1.4"]["size_hint"]
            seen = {}

            def fake_dl(url, dest, stall_seconds=120, min_bytes=None):
                seen["dest"] = dest
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as fh:
                    fh.write(b"\x00ONNXfake" * 1000)  # ~9KB 过 1KB 下界
                return dest

            DL.http_download = fake_dl
            M.PRESET_MODELS["rmbg-1.4"]["size_hint"] = "1KB"
            try:
                got4 = M.resolve("rmbg-1.4")
                check("下载落点位于 RMBG-1.4/ 子目录",
                      os.path.normpath(seen.get("dest", "")).endswith(
                          os.path.normpath("RMBG-1.4/rmbg-1.4.onnx")),
                      str(seen.get("dest")))
                check("下载后返回同一路径", got4 == seen.get("dest"))
            finally:
                DL.http_download = orig_dl
                M.PRESET_MODELS["rmbg-1.4"]["url"] = orig_url
                M.PRESET_MODELS["rmbg-1.4"]["size_hint"] = orig_hint

            print("\n[5] 其余模型不受影响")
            check("未知名仍返回 None", M.resolve("不存在的模型_xyz") is None)
            check("modnet 预置仍在下拉",
                  "hivision_modnet" in M.available_choices())
        finally:
            M._models_root = orig_root

    if real_fp is not None:
        sys.modules["folder_paths"] = real_fp
    else:
        sys.modules.pop("folder_paths", None)

    print("\n== 汇总：失败 %d ==" % len(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
