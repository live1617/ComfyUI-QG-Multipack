# -*- coding: utf-8 -*-
"""QG_SimpleSegDetectorSEGS 契约 / 软依赖 / 调用链回归测试。

本节点按 Impact-Pack 的 ImpactSimpleDetectorSEGS 规格独立实现，运行时依赖
impact.core 与其自定义类型。本机测试进程通常没有 Impact-Pack，所以这里：

1. 静态层：AST 核对注册 key、控件默认值/范围、RETURN_TYPES、CATEGORY、
   DESCRIPTION 英文；确认没有复制上游源码（无 subprocess / eval / exec、
   无硬编码品牌字符串照搬）。
2. 运行时层：用 stub 注入 impact.core，验证三条调用路径（纯 BBox、BBox+SAM、
   BBox+SEGM）的参数传递与先后顺序，以及「SEGM 与 BBOX 同一对象省一次检测」、
   batch 拒绝、软依赖中文提示。
3. 登记层：两套词表都有该节点、README/ISSUES/NOTICES 有来源登记。

不依赖真实模型、不依赖 Impact-Pack 安装、不联网。
运行：python_embeded\\python.exe tests\\test_qg_simple_seg_detector.py
"""
import ast
import io
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("PASS", name)
    else:
        FAIL += 1
        print("FAIL", name, detail)


SRC = io.open(os.path.join(PKG, "qg_simple_seg_detector.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)
import qg_simple_seg_detector as mod  # noqa: E402

# ---- 一、静态契约 ----
cls = next((n for n in TREE.body
            if isinstance(n, ast.ClassDef) and n.name == "QGSimpleSegDetectorSEGS"), None)
check("节点类存在", cls is not None)
methods = {n.name: n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))} if cls else {}
check("INPUT_TYPES / detect 两个方法齐全",
      {"INPUT_TYPES", "detect"} <= set(methods), str(list(methods)))

mapping = mod.NODE_CLASS_MAPPINGS
nodemap = mod.NODE_DISPLAY_NAME_MAPPINGS
check("注册 key = QG_SimpleSegDetectorSEGS",
      list(mapping) == ["QG_SimpleSegDetectorSEGS"], str(mapping))
check("display 名含 QG 与 SEGS",
      "QG" in nodemap.get("QG_SimpleSegDetectorSEGS", "") and
      "SEGS" in nodemap.get("QG_SimpleSegDetectorSEGS", ""), str(nodemap))

node_cls = mapping.get("QG_SimpleSegDetectorSEGS")
check("映射指向节点类", node_cls is mod.QGSimpleSegDetectorSEGS)
check("RETURN_TYPES = (SEGS,)", getattr(node_cls, "RETURN_TYPES", None) == ("SEGS",),
      str(getattr(node_cls, "RETURN_TYPES", None)))
check("CATEGORY = QG 工具", getattr(node_cls, "CATEGORY", None) == "QG 工具")
check("FUNCTION 指向 detect 方法", getattr(node_cls, "FUNCTION", None) == "detect")
check("有 OUTPUT_TOOLTIPS 且中文", bool(getattr(node_cls, "OUTPUT_TOOLTIPS", ())) and
      any("\u4e00" <= ch <= "\u9fff" for ch in str(node_cls.OUTPUT_TOOLTIPS)))
desc = getattr(node_cls, "DESCRIPTION", "")
check("DESCRIPTION 为英文（走词表）", desc.isascii(), desc[:80])

# 运行时取真实 INPUT_TYPES（含模块常量展开），比 AST 字面求值可靠
input_types = node_cls.INPUT_TYPES()
check("INPUT_TYPES 结构完整", isinstance(input_types, dict) and
      "required" in input_types and "optional" in input_types)
req = input_types.get("required", {})
opt = input_types.get("optional", {})
expected_required = ["bbox_detector", "image", "bbox_threshold", "bbox_dilation",
                     "crop_factor", "drop_size", "sub_threshold", "sub_dilation",
                     "sub_bbox_expansion", "sam_mask_hint_threshold", "post_dilation"]
check("11 个必填项与截图一致", list(req) == expected_required, str(list(req)))
check("可选 SAM_MODEL / SEGM_DETECTOR",
      opt.get("sam_model_opt", [None])[0] == "SAM_MODEL" and
      opt.get("segm_detector_opt", [None])[0] == "SEGM_DETECTOR", str(list(opt)))
check("输出自定义类型不加 QG 前缀（跨包连线契约）",
      req.get("bbox_detector", [None])[0] == "BBOX_DETECTOR" and
      node_cls.RETURN_TYPES == ("SEGS",))
check("所有控件 tooltip 均为中文",
      all(any("\u4e00" <= ch <= "\u9fff" for ch in str(v[1].get("tooltip", "")))
          for v in list(req.values()) + list(opt.values())))

# 默认值逐项核对（与 Impact-Pack SimpleDetectorForEach 源码一致）
def dval(name):
    return req[name][1].get("default")

check("bbox_threshold 默认 0.5", dval("bbox_threshold") == 0.5)
check("bbox_dilation 默认 0", dval("bbox_dilation") == 0)
check("crop_factor 默认 3.0", dval("crop_factor") == 3.0)
check("drop_size 默认 10", dval("drop_size") == 10)
check("sub_threshold 默认 0.5", dval("sub_threshold") == 0.5)
check("sub_bbox_expansion 默认 0", dval("sub_bbox_expansion") == 0)
check("sam_mask_hint_threshold 默认 0.7", dval("sam_mask_hint_threshold") == 0.7)
check("post_dilation 默认 0", dval("post_dilation") == 0)

# 合规：无 subprocess / eval / exec / 自动下载
func_calls = [n.func.id for n in ast.walk(TREE)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
check("无 subprocess/eval/exec 调用",
      not set(func_calls) & {"eval", "exec"})
check("无 subprocess import",
      all("subprocess" not in ast.dump(n) for n in ast.walk(TREE)
          if isinstance(n, (ast.Import, ast.ImportFrom))))

# ---- 二、运行时调用链（stub impact.core） ----
calls = []
fake_seg = ("raw", ["seg1"])

impact_pkg = types.ModuleType("impact")
impact_pkg.__path__ = []
sys.modules["impact"] = impact_pkg
fake_core = types.ModuleType("impact.core")
fake_core.make_sam_mask = lambda *a: (calls.append(("make_sam_mask", a)) or "sam_mask")
fake_core.segs_bitwise_and_mask = lambda s, m: (calls.append(("and", (s, m))) or ("and", s, m))
fake_core.segs_to_combined_mask = lambda s: (calls.append(("combined", s)) or "segm_mask")
fake_core.dilate_segs = lambda s, f: (calls.append(("dilate", (s, f))) or ("dilated", s, f))
sys.modules["impact.core"] = fake_core
mod._IMPACT_CORE = None

class FakeDetector:
    def __init__(self, tag="bbox"):
        self.tag = tag
        self.calls = []
    def detect(self, image, t, d, c, s):
        self.calls.append((t, d, c, s))
        return ("segs", self.tag)

image = [[[0.0]]]  # len(image)==1
bbox = FakeDetector()
node = mod.QGSimpleSegDetectorSEGS()

# 路径 A：纯 bbox
calls.clear()
out = node.detect(bbox, image, 0.6, 1, 3.0, 10, 0.5, 0, 0, 0.7, 0)
check("纯 bbox：调用 detector.detect 参数正确",
      bbox.calls[-1] == (0.6, 1, 3.0, 10), str(bbox.calls[-1]))
check("纯 bbox：只调 dilate_segs，无 SAM/SEGM",
      [c[0] for c in calls] == ["dilate"] and calls[0][1][1] == 0, str(calls))
check("纯 bbox：返回 SEGS 一元组", isinstance(out, tuple) and len(out) == 1)

# 路径 B：bbox + SAM（SAM 优先于 SEGM）
calls.clear()
sam = object()
segm = FakeDetector("segm")
out = node.detect(bbox, image, 0.5, 0, 3.0, 10, 0.3, 2, 4, 0.8, 5,
                  sam_model_opt=sam, segm_detector_opt=segm)
check("SAM 路径：make_sam_mask 收到 center-1 与次要参数",
      any(c[0] == "make_sam_mask" and c[1][3] == "center-1" and
          c[1][4] == 2 and c[1][5] == 0.3 and c[1][6] == 4 and c[1][7] == 0.8
          for c in calls), str(calls))
check("SAM 优先：SEGM 未跑", len(segm.calls) == 0, str(segm.calls))
check("SAM 路径：先 mask 再取交再膨胀",
      [c[0] for c in calls] == ["make_sam_mask", "and", "dilate"], str(calls))
check("SAM 路径：膨胀量透传 5",
      calls[-1][1][1] == 5, str(calls[-1]))

# 路径 C：bbox + SEGM（无 SAM）
calls.clear()
segm2 = FakeDetector("segm2")
node.detect(bbox, image, 0.5, 0, 3.0, 10, 0.4, 3, 0, 0.7, 0,
            segm_detector_opt=segm2)
check("SEGM 路径：segm.detect 收到次要参数",
      segm2.calls[-1] == (0.4, 3, 3.0, 10), str(segm2.calls[-1]))
check("SEGM 路径：combined → and → dilate",
      [c[0] for c in calls] == ["combined", "and", "dilate"], str(calls))

# 路径 D：SEGM 与 BBOX 同一对象，省一次 bbox 检测
calls.clear()
shared = FakeDetector("shared")
shared.bbox_detector = shared
node.detect(shared, image, 0.9, 9, 9.0, 9, 0.2, 8, 7, 0.6, 0,
            segm_detector_opt=shared)
check("同一检测器：只跑 SEGM 一次，未跑 bbox 参数",
      len(shared.calls) == 1 and shared.calls[0] == (0.2, 8, 9.0, 9), str(shared.calls))
check("同一检测器：只有 dilate",
      [c[0] for c in calls] == ["dilate"], str(calls))

# batch 拒绝
try:
    node.detect(bbox, [[1], [2]], 0.5, 0, 3.0, 10, 0.5, 0, 0, 0.7, 0)
    check("batch>1 拒绝", False, "未抛异常")
except RuntimeError as exc:
    check("batch>1 拒绝且中文提示", "单张" in str(exc) and "批次" in str(exc), str(exc))

# 软依赖：删掉 impact.core 后给中文提示（不抛 ImportError 原文）
del sys.modules["impact.core"]
mod._IMPACT_CORE = None
try:
    node.detect(bbox, image, 0.5, 0, 3.0, 10, 0.5, 0, 0, 0.7, 0)
    check("缺 Impact-Pack 时拒绝执行", False, "未抛异常")
except RuntimeError as exc:
    check("缺 Impact-Pack 给中文安装提示",
          "ComfyUI-Impact-Pack" in str(exc) and "custom_nodes" in str(exc), str(exc))

# ---- 三、登记检查 ----
with io.open(os.path.join(PKG, "locales/zh/nodeDefs.json"), encoding="utf-8") as fh:
    nd = json.load(fh)
with io.open(os.path.join(PKG, "translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"), encoding="utf-8") as fh:
    tr = json.load(fh)
check("两套词表各 34 节点", len(nd) == len(tr) == 34, "%d/%d" % (len(nd), len(tr)))
key = "QG_SimpleSegDetectorSEGS"
check("两套词表都有新节点", key in nd and key in tr)
check("nodeDefs inputs 覆盖 13 项", len(nd[key]["inputs"]) == 13, str(len(nd[key]["inputs"])))
check("nodeDefs outputs 用索引 0", "0" in nd[key]["outputs"])

readme = io.open(os.path.join(PKG, "README.md"), encoding="utf-8").read()
check("README 一览表 / 来源表 / 专章齐全",
      "| `QG_SimpleSegDetectorSEGS` |" in readme and
      readme.count("QG_SimpleSegDetectorSEGS") >= 3 and
      "## 简易 Seg 检测" in readme)
issues = io.open(os.path.join(PKG, "ISSUES.md"), encoding="utf-8").read()
check("ISSUES #153 登记", "| 153 |" in issues)
notices = io.open(os.path.join(PKG, "THIRD-PARTY-NOTICES.md"), encoding="utf-8").read()
check("NOTICES 记 Impact-Pack GPL-3.0 来源",
      "ComfyUI-Impact-Pack" in notices and "GPL-3.0" in notices)

print("=== 合计 %d PASS / %d FAIL ===" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
