# -*- coding: utf-8 -*-
"""qg_model_scan 公共层测试：去重 / 递归扫描 / 路径安全 / 设备 / 文件签名。

这一层被 QG_YoloDetectorLoader 与 QG_SamModelLoader 共用，两边的扫描与解析
行为都靠它落地，因此单独立测，避免只在加载器测试里被间接覆盖。

不依赖真实模型、网络、ComfyUI 运行时。
运行：python_embeded\\python.exe tests\\test_qg_model_scan.py
"""
import os
import sys
import types

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PKG)

import qg_model_scan as S  # noqa: E402

ok = 0
fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS", name)
    else:
        fail += 1
        print("FAIL", name, extra)


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x")


print("== 一、dedupe ==")
np = os.path.normpath
check("去空值", S.dedupe(["", None, "a"]) == ["a"])
check("去重保序（Windows 上 normpath 会把 / 归一成 \\）",
      S.dedupe(["/x/a", "/x/b", "/x/a", "/x/c"])
      == [np("/x/a"), np("/x/b"), np("/x/c")],
      str(S.dedupe(["/x/a", "/x/b", "/x/a", "/x/c"])))
check("规范化路径", S.dedupe(["a/./b", "a/b"]) == [np("a/b")],
      str(S.dedupe(["a/./b", "a/b"])))
check("大小写不同视为同一条（Windows 不区分）",
      os.name != "nt" or S.dedupe(["/x/A", "/x/a"]) == [np("/x/A")],
      str(S.dedupe(["/x/A", "/x/a"])))
check("空列表安全", S.dedupe([]) == [])

print("\n== 二、split_relative 路径安全 ==")
check("正常拆分", S.split_relative("hq/sam_hq_vit_h.pth") == ["hq", "sam_hq_vit_h.pth"])
check("反斜杠归一", S.split_relative("hq\\x.pth") == ["hq", "x.pth"])
check("丢弃空段与 .", S.split_relative("./a//b.pth") == ["a", "b.pth"])
check("拒绝空值", S.split_relative("") is None and S.split_relative(None) is None)
check("拒绝绝对路径（/）", S.split_relative("/etc/passwd") is None)
check("拒绝盘符", S.split_relative("C:/Windows/win.ini") is None)
check("拒绝上跳", S.split_relative("../evil.pth") is None)
check("拒绝中段上跳", S.split_relative("a/../../evil.pth") is None)
check("纯空白拒绝", S.split_relative("   ") is None)

print("\n== 三、resolve_in_roots 边界校验 ==")
import shutil
import tempfile

tmp = tempfile.mkdtemp(prefix="qg_modelscan_")
try:
    root_a = os.path.join(tmp, "sams")
    root_b = os.path.join(tmp, "sam")
    touch(os.path.join(root_a, "vit_b.pth"))
    touch(os.path.join(root_a, "hq", "vit_h.pth"))
    touch(os.path.join(root_b, "vit_l.pth"))
    # 候选根之外的文件：解析结果不得跨出去
    outside = os.path.join(tmp, "outside.pth")
    touch(outside)

    roots = [root_a, root_b]
    check("根目录内可解析",
          S.resolve_in_roots(["vit_b.pth"], roots) == os.path.join(root_a, "vit_b.pth"))
    check("子目录可解析",
          S.resolve_in_roots(["hq", "vit_h.pth"], roots)
          == os.path.join(root_a, "hq", "vit_h.pth"))
    check("第二个根命中",
          S.resolve_in_roots(["vit_l.pth"], roots) == os.path.join(root_b, "vit_l.pth"))
    check("不存在的文件返回 None", S.resolve_in_roots(["nope.pth"], roots) is None)
    check("空 parts 返回 None", S.resolve_in_roots([], roots) is None)
    check("上跳串到根外被拒",
          S.resolve_in_roots(["..", "outside.pth"], roots) is None)

    print("\n== 四、walk_relative 递归与限深 ==")
    os.makedirs(os.path.join(root_a, ".hidden"), exist_ok=True)
    touch(os.path.join(root_a, ".hidden", "secret.pth"))
    os.makedirs(os.path.join(root_a, "__pycache__"), exist_ok=True)
    touch(os.path.join(root_a, "__pycache__", "junk.pth"))
    touch(os.path.join(root_a, "a", "b", "deep.pth"))
    touch(os.path.join(root_a, "a", "b", "c", "level3.pth"))
    touch(os.path.join(root_a, "a", "b", "c", "d", "level4.pth"))
    os.makedirs(os.path.join(root_a, "empty_dir"), exist_ok=True)
    touch(os.path.join(root_a, "notes.txt"))

    names = [rel for rel, _full in S.walk_relative(root_a, (".pth",))]
    check("递归收两层子目录", "a/b/deep.pth" in names, str(names))
    check("深度上限 3 层收第 3 层", "a/b/c/level3.pth" in names, str(names))
    check("深度上限 3 层拦住第 4 层", "a/b/c/d/level4.pth" not in names, str(names))
    check("跳过隐藏目录", all(".hidden" not in n for n in names), str(names))
    check("跳过 __pycache__", all("__pycache__" not in n for n in names), str(names))
    check("后缀过滤", all(n.endswith(".pth") for n in names), str(names))
    check("根目录文件不带前缀", "vit_b.pth" in names, str(names))
    check("不存在的根安全", list(S.walk_relative(os.path.join(tmp, "nope"), (".pth",))) == [])

    print("\n== 五、category_roots / scan_category ==")
    fp = types.ModuleType("fp")
    fp.get_folder_paths = lambda n: [os.path.join(tmp, n)] if n in ("sams", "sam") else []
    fp.models_dir = tmp
    fp.folder_names_and_paths = {}
    fp.supported_pt_extensions = [".pt", ".pth", ".onnx", ".safetensors"]

    cats = S.category_roots(("sams", "sam"), fp)
    check("两个历史 key 都进候选根",
          os.path.normpath(os.path.join(tmp, "sams")) in cats
          and os.path.normpath(os.path.join(tmp, "sam")) in cats, str(cats))
    check("候选根去重",
          len(cats) == len({os.path.normcase(os.path.normpath(c)) for c in cats}), str(cats))

    scanned = S.scan_category(("sams", "sam"), fp)
    check("合并扫描两个类别", {"vit_b.pth", "hq/vit_h.pth", "vit_l.pth"} <= set(scanned),
          str(scanned))
    check("扫描结果不含隐藏与缓存",
          all(".hidden" not in n and "__pycache__" not in n for n in scanned), str(scanned))
    check("扫描结果排序", scanned == sorted(scanned), str(scanned))

    extra = os.path.join(tmp, "extra_sams")
    touch(os.path.join(extra, "env_only.pth"))
    check("extra 根被采纳", "env_only.pth" in S.scan_category("sams", fp, extra=(extra,)))

    print("\n== 六、models_roots 反推挂载库 ==")
    fp2 = types.ModuleType("fp2")
    fp2.models_dir = os.path.join(tmp, "local_models")
    fp2.folder_names_and_paths = {
        "checkpoints": ([os.path.join(tmp, "mounted", "checkpoints")], set()),
    }
    fp2.supported_pt_extensions = [".pth"]
    roots2 = S.models_roots(fp2)
    check("含本机 models_dir",
          os.path.normpath(fp2.models_dir) in roots2, str(roots2))
    check("从挂载类别反推出挂载 models 根",
          os.path.normpath(os.path.join(tmp, "mounted")) in roots2, str(roots2))

    print("\n== 七、resolve_device / file_signature ==")
    check("cpu 原样", S.resolve_device("cpu") == "cpu")
    check("auto 落成具体设备", S.resolve_device("auto") in ("cpu", "cuda"))
    check("cuda 不可用时回退 cpu（本机若可用则跳过判断）",
          S.resolve_device("cuda") in ("cpu", "cuda"))
    target = os.path.join(root_a, "vit_b.pth")
    sig = S.file_signature(target)
    check("签名是 mtime:size 形式", isinstance(sig, str) and ":" in sig, str(sig))
    check("不存在的文件返回 nan",
          isinstance(S.file_signature(os.path.join(tmp, "nope.pth")), float)
          and S.file_signature(os.path.join(tmp, "nope.pth")) != S.file_signature(os.path.join(tmp, "nope.pth")))
    check("空路径返回 nan", S.file_signature(None) != S.file_signature(None))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nTOTAL ok=%d fail=%d" % (ok, fail))
sys.exit(1 if fail else 0)
