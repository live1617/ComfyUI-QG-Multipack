# -*- coding: utf-8 -*-
"""随包 modnet 权重：授权合规 + 离线发现 + 打包规则 + 文档口径。

用户 2026-11-15 问「两个 25MB 抠图权重能不能随包」。先核查授权：
HivisionIDPhotos 官方 README 写 `licensed under the Apache-2.0 License`，
MODNet 官方仓库 LICENSE 也是标准 Apache-2.0，两边都没有模型专属的
商用 / 非商业限制 → 可再分发。这里把结论固化成断言：

* 文件在、体积够、SHA-256 与 NOTICE / THIRD-PARTY-NOTICES 记录一致；
* 附 Apache-2.0 全文，且另外两个授权不同的大模型没有混进来；
* 模型发现顺序「用户根 → 插件内置 → Hivision 兼容」，离线时不联网；
* 用户自己放的同名权重不被内置副本遮蔽；
* 打包必带清单、.gitignore / .gitattributes、README 口径全部同步。

不依赖 GPL 参考源码，可单独运行。
"""
import hashlib
import importlib.util
import pathlib
import re
import sys
import tempfile
import types

HERE = pathlib.Path(__file__).resolve().parent
PKG = HERE.parent
WORKSPACE = PKG.parent
BUNDLED = PKG / "models" / "background_removal"

NAMES = (
    "modnet_photographic_portrait_matting.onnx",
    "hivision_modnet.onnx",
)

ok = 0
fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS", name)
    else:
        fail += 1
        print("FAIL", name, detail)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_matte_models():
    """以包别名加载单文件模块，相对导入不受影响。"""
    pkg_name = "qgpkg_bundled_test"
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
    return mod


def main():
    print("=== 随包 modnet 权重 ===")
    check("内置目录存在", BUNDLED.is_dir())
    for name in NAMES:
        check(f"{name} 存在", (BUNDLED / name).is_file())

    for name in NAMES:
        path = BUNDLED / name
        if not path.is_file():
            continue
        size = path.stat().st_size
        check(f"{name} 体积在 12~30 MB", 12_000_000 <= size < 30_000_000,
              f"实际 {size}")
        head = path.open("rb").read(512).lower()
        check(f"{name} 不是错误页 / 文本", b"<html" not in head
              and b"<!doctype" not in head and b"404" not in head)

    hashes = {name: sha256(BUNDLED / name) for name in NAMES
              if (BUNDLED / name).is_file()}
    notice = (BUNDLED / "NOTICE.md").read_text(encoding="utf-8")
    notices = (PKG / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
    readme = (PKG / "README.md").read_text(encoding="utf-8")

    for name, digest in hashes.items():
        check(f"{name} 哈希写入 NOTICE", digest in notice, digest)
        check(f"{name} 哈希写入 THIRD-PARTY-NOTICES", digest in notices, digest)
    check("NOTICE 里的 64 位哈希恰好两个",
          len(set(re.findall(r"\b[0-9a-f]{64}\b", notice))) == len(NAMES))

    lic = BUNDLED / "LICENSE-APACHE-2.0.txt"
    check("Apache-2.0 全文随包", lic.is_file())
    if lic.is_file():
        text = lic.read_text(encoding="utf-8")
        check("许可全文含 Apache License / Version 2.0",
              "Apache License" in text and "Version 2.0" in text)
        check("许可全文含 TERMS AND CONDITIONS",
              "TERMS AND CONDITIONS FOR USE, REPRODUCTION" in text)
        check("许可全文行数正常", len(text.splitlines()) >= 190)

    for kw in ("Apache-2.0", "未修改", "releases/download/pretrained-model",
               "SHA-256"):
        check(f"NOTICE 含 {kw}", kw in notice)
    for name in NAMES:
        check(f"NOTICE 列出 {name}", name in notice)

    check("THIRD-PARTY-NOTICES 有随包权重专章",
          "MODNet / HivisionIDPhotos ONNX weights (bundled, Apache-2.0)" in notices)
    check("THIRD-PARTY-NOTICES 旧句已修正",
          "no HivisionIDPhotos source or model file is bundled"
          not in notices.replace("\n", " "))
    check("THIRD-PARTY-NOTICES 声明另外两个不随包",
          re.search(r"are \*\*not\*\*\s+bundled", notices) is not None)

    check("README 标题改为 2 个随包", "2 个随包，2 个按需下载" in readme)
    check("README 旧句已改", "**不随包分发**的模型权重" not in readme)
    check("README 写明发现顺序", "插件内置副本" in readme)
    check("README 写明用户同名优先", "用户自己放的同名权重优先" in readme)

    gitignore = (PKG / ".gitignore").read_text(encoding="utf-8")
    check(".gitignore 没有 *.onnx 排除行",
          not any(line.strip().startswith("*.onnx")
                  for line in gitignore.splitlines()))
    check(".gitignore 说明 onnx 是随包资产", "*.onnx 不在此列" in gitignore)
    check(".gitattributes 标 onnx 为 binary",
          "*.onnx binary" in (PKG / ".gitattributes").read_text(encoding="utf-8"))

    packer = (WORKSPACE / "打包备份.py").read_text(encoding="utf-8")
    for rel in ("models/background_removal/" + NAMES[0],
                "models/background_removal/" + NAMES[1],
                "models/background_removal/LICENSE-APACHE-2.0.txt",
                "models/background_removal/NOTICE.md"):
        check(f"打包 REQUIRED 含 {rel.split('/')[-1]}", f'"{rel}"' in packer)

    check("授权不同的两个大模型没有混进包",
          not (BUNDLED / "rmbg-1.4.onnx").exists()
          and not (BUNDLED / "birefnet-v1-lite.onnx").exists())

    print("\n=== 模型发现 / 离线行为 ===")
    M = load_matte_models()
    with tempfile.TemporaryDirectory() as td:
        M._models_root = lambda: td
        folders = M._source_folders()
        user_dir = str(pathlib.Path(td) / "background_removal")
        bundled_dir = str(M._bundled_dir())
        check("内置目录就是插件 models/background_removal",
              bundled_dir == str(BUNDLED))
        check("搜索顺序含用户根", user_dir in folders)
        check("搜索顺序含插件内置", bundled_dir in folders)
        check("内置排在用户根之后",
              folders.index(user_dir) < folders.index(bundled_dir))
        hiv_idx = next((i for i, f in enumerate(folders)
                        if "HivisionIDPhotos-ComfyUI" in f), -1)
        check("Hivision 兼容路径排在最后",
              hiv_idx == len(folders) - 1 and hiv_idx > folders.index(bundled_dir))
        check("预置下拉仍含 4 个模型", len(M.available_choices()) >= 4)

        # 模拟纯离线：只保留插件内置目录
        M._source_folders = lambda: [bundled_dir]
        found = M.discover()
        check("离线 discover 找到 2 个模型", len(found) == 2,
              str(sorted(found)))
        for name in NAMES:
            key = name[:-5]
            check(f"离线 discover 命中 {key}",
                  found.get(key) == str(BUNDLED / name))

        def must_not_download(_name):
            raise AssertionError("离线时不应触发下载")

        M._resolve_preset = must_not_download
        check("离线 resolve 直接给本地路径",
              M.resolve("hivision_modnet") == str(BUNDLED / NAMES[1]))

        # 用户自己放的同名权重不能被内置副本遮蔽
        (pathlib.Path(td) / "hivision_modnet.onnx").write_bytes(b"user")
        M._source_folders = lambda: [td, bundled_dir]
        check("用户目录同名权重优先",
              M.discover()["hivision_modnet"].startswith(td))

    print("\n=== onnxruntime 实加载（可选） ===")
    try:
        import onnxruntime as ort
        for name in NAMES:
            try:
                sess = ort.InferenceSession(
                    str(BUNDLED / name), providers=["CPUExecutionProvider"])
                shape = sess.get_inputs()[0].shape
                check(f"{name} 可被 onnxruntime 加载", True)
                print("     输入形状", shape)
            except Exception as exc:
                check(f"{name} 可被 onnxruntime 加载", False, str(exc)[:120])
    except ImportError:
        print("SKIP 本机没有 onnxruntime，跳过实加载（不算失败）")

    print(f"\n合计 {ok + fail} 项，PASS {ok}，FAIL {fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
