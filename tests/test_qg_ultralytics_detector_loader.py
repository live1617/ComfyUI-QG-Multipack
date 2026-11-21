# -*- coding: utf-8 -*-
"""QG_UltralyticsDetectorLoader 契约 / 扫描 / 软依赖 / 调用链回归测试。

本节点按 Impact-Subpack 的 UltralyticsDetectorProvider 规格独立实现，运行时
依赖它的 modules.subcore。本机测试进程通常没有 Impact-Subpack，所以这里：

1. 静态层：核对注册 key、RETURN_TYPES（必须与 Impact 逐字一致，不加 QG 前缀）、
   CATEGORY、DESCRIPTION 英文、中文 tooltip，确认无复制上游源码的痕迹。
2. 扫描层：用临时目录 + fake folder_paths 验证 bbox/segm 分类、后缀过滤、
   去重排序、三级路径解析、IS_CHANGED 缓存键。
3. 运行时层：stub 注入 subcore，验证 bbox/segm 两条构造分支与参数传递；
   清掉 stub 后验证中文安装提示；模型不存在时验证中文排查提示。
4. 登记层：两套词表 34 节点、README / ISSUES / NOTICES 来源登记（含 AGPL 声明）。

不依赖真实 YOLO 权重、不依赖 Impact-Subpack 安装、不联网。
运行：python_embeded\\python.exe tests\\test_qg_ultralytics_detector_loader.py
"""
import ast
import io
import json
import os
import shutil
import sys
import tempfile
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


SRC = io.open(os.path.join(PKG, "qg_ultralytics_detector_loader.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)
import qg_ultralytics_detector_loader as mod  # noqa: E402

# ---- 一、静态契约 ----
cls = next((n for n in TREE.body
            if isinstance(n, ast.ClassDef) and n.name == "QGUltralyticsDetectorLoader"), None)
check("节点类存在", cls is not None)
methods = {n.name: n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))} if cls else {}
check("INPUT_TYPES / load_detector / IS_CHANGED 齐全",
      {"INPUT_TYPES", "load_detector", "IS_CHANGED"} <= set(methods), str(list(methods)))

check("注册 key = QG_UltralyticsDetectorLoader",
      list(mod.NODE_CLASS_MAPPINGS) == ["QG_UltralyticsDetectorLoader"],
      str(list(mod.NODE_CLASS_MAPPINGS)))
check("display 名含 QG 与 检测加载器",
      "QG" in mod.NODE_DISPLAY_NAME_MAPPINGS.get("QG_UltralyticsDetectorLoader", "") and
      "检测加载器" in mod.NODE_DISPLAY_NAME_MAPPINGS.get("QG_UltralyticsDetectorLoader", ""))

node_cls = mod.NODE_CLASS_MAPPINGS["QG_UltralyticsDetectorLoader"]
check("映射指向节点类", node_cls is mod.QGUltralyticsDetectorLoader)
check("RETURN_TYPES 与 Impact 逐字一致（不加 QG 前缀）",
      node_cls.RETURN_TYPES == ("BBOX_DETECTOR", "SEGM_DETECTOR"),
      str(node_cls.RETURN_TYPES))
check("RETURN_NAMES 两项",
      node_cls.RETURN_NAMES == ("bbox_detector", "segm_detector"), str(node_cls.RETURN_NAMES))
check("CATEGORY = QG 工具", node_cls.CATEGORY == "QG 工具")
check("FUNCTION 指向 load_detector", node_cls.FUNCTION == "load_detector")
check("OUTPUT_TOOLTIPS 中文",
      all(any("\u4e00" <= ch <= "\u9fff" for ch in str(t)) for t in node_cls.OUTPUT_TOOLTIPS))
check("DESCRIPTION 为英文（走词表）", node_cls.DESCRIPTION.isascii(), node_cls.DESCRIPTION[:80])

it = node_cls.INPUT_TYPES()
req = it["required"]
check("只有一个必填控件 model_name", list(req) == ["model_name"], str(list(req)))
check("model_name 是 combo 且有中文提示",
      isinstance(req["model_name"][0], (list, tuple)) and
      any("\u4e00" <= ch <= "\u9fff" for ch in req["model_name"][1]["tooltip"]))
check("无控件时给中文占位而不是空列表",
      len(req["model_name"][0]) >= 1 and
      any("\u4e00" <= ch <= "\u9fff" for ch in req["model_name"][0][0]))

# 合规：没有复制上游源码的运行时安装 / 动态执行
for banned in ("subprocess", "eval(", "exec(", "pip install"):
    check("源码无 %s" % banned, banned not in SRC)

# ---- 二、模型扫描与路径解析（临时目录 + fake folder_paths） ----
tmp = tempfile.mkdtemp(prefix="qg_yolo_test_")
try:
    bbox_root = os.path.join(tmp, "ultralytics", "bbox")
    segm_root = os.path.join(tmp, "ultralytics", "segm")
    os.makedirs(bbox_root)
    os.makedirs(segm_root)
    for name in ("face_yolov8n.pt", "hand.pt", "notes.txt", "dup.pt"):
        io.open(os.path.join(bbox_root, name), "w").close()
    io.open(os.path.join(segm_root, "person-yolov8s-seg.pt"), "w").close()
    # 第二个挂载点，含同名文件，验证去重
    extra_bbox = os.path.join(tmp, "extra", "bbox")
    os.makedirs(extra_bbox)
    io.open(os.path.join(extra_bbox, "dup.pt"), "w").close()

    class FakeFP:
        supported_pt_extensions = {".pt", ".pth", ".safetensors"}

        def __init__(self, roots, models_dir=None):
            self.roots = roots
            self.models_dir = models_dir
            self.folder_names_and_paths = {}

        def get_folder_paths(self, key):
            return list(self.roots.get(key, []))

        def get_full_path(self, key, rel):
            for root in self.roots.get(key, []):
                path = os.path.join(root, rel)
                if os.path.isfile(path):
                    return path
            return None

    fp = FakeFP({
        "ultralytics_bbox": [bbox_root, extra_bbox],
        "ultralytics_segm": [segm_root],
        "ultralytics": [os.path.join(tmp, "ultralytics")],
    })
    boxes = mod._scan_models("bbox", fp)
    segms = mod._scan_models("segm", fp)
    check("bbox 扫描：只收模型后缀、去重、排序",
          boxes == ["dup.pt", "face_yolov8n.pt", "hand.pt"], str(boxes))
    check("segm 扫描：只收本目录模型",
          segms == ["person-yolov8s-seg.pt"], str(segms))
    check("路径解析：ultralytics 根 + 子目录前缀",
          mod._resolve_model_path("bbox/face_yolov8n.pt", fp) ==
          os.path.join(bbox_root, "face_yolov8n.pt"))
    check("路径解析：segm 前缀",
          mod._resolve_model_path("segm/person-yolov8s-seg.pt", fp) ==
          os.path.join(segm_root, "person-yolov8s-seg.pt"))
    check("路径解析：第二个挂载点的同名文件",
          mod._resolve_model_path("bbox/dup.pt", fp) ==
          os.path.join(bbox_root, "dup.pt"))
    check("路径解析：不存在返回 None",
          mod._resolve_model_path("bbox/not-here.pt", fp) is None)

    # 兜底：只有 models_dir，没有 Subpack 注册的 folder key
    fp2 = FakeFP({}, models_dir=tmp)
    check("无 Subpack 时仍从主模型库扫到 bbox",
          "face_yolov8n.pt" in mod._scan_models("bbox", fp2))
    check("无 Subpack 时路径解析走主模型库",
          mod._resolve_model_path("segm/person-yolov8s-seg.pt", fp2) ==
          os.path.join(segm_root, "person-yolov8s-seg.pt"))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ---- 三、运行时调用链（stub subcore） ----
calls = []


class FakeSubcore:
    @staticmethod
    def load_yolo(path):
        calls.append(("load_yolo", path))
        return "MODEL:" + os.path.basename(path)

    @staticmethod
    def UltraBBoxDetector(model):
        calls.append(("bbox", model))
        return "BBOX:" + model

    @staticmethod
    def UltraSegmDetector(model):
        calls.append(("segm", model))
        return "SEGM:" + model

    @staticmethod
    def NO_SEGM_DETECTOR():
        calls.append(("no_segm",))
        return "NO_SEGM"


fake = types.ModuleType("impact_subpack_subcore_stub")
for name in ("load_yolo", "UltraBBoxDetector", "UltraSegmDetector", "NO_SEGM_DETECTOR"):
    setattr(fake, name, getattr(FakeSubcore, name))
sys.modules["impact_subpack_subcore_stub"] = fake
mod._SUBCORE = fake
node = node_cls()

# 绕过真实文件路径：临时替换解析函数
orig_resolve = mod._resolve_model_path
orig_roots = mod._candidate_roots
mod._resolve_model_path = lambda name, fp=None: "/fake/" + name
try:
    calls.clear()
    out = node.load_detector("bbox/face.pt")
    check("bbox 模型：返回两个检测器", out == ("BBOX:MODEL:face.pt", "NO_SEGM"), str(out))
    check("bbox 模型：不构造 UltraSegmDetector",
          [c[0] for c in calls] == ["load_yolo", "bbox", "no_segm"], str(calls))

    calls.clear()
    out = node.load_detector("segm/person.pt")
    check("segm 模型：返回两个真实检测器",
          out == ("BBOX:MODEL:person.pt", "SEGM:MODEL:person.pt"), str(out))
    check("segm 模型：调用顺序 load→bbox→segm",
          [c[0] for c in calls] == ["load_yolo", "bbox", "segm"], str(calls))
    check("load_yolo 收到完整模型名",
          calls[0][1] == "/fake/segm/person.pt", str(calls[0]))
finally:
    mod._resolve_model_path = orig_resolve
    mod._candidate_roots = orig_roots

# IS_CHANGED 用 mtime + size 做键
tmp2 = tempfile.mkdtemp(prefix="qg_yolo_changed_")
try:
    model_path = os.path.join(tmp2, "a.pt")
    io.open(model_path, "w").write("x")
    mod._resolve_model_path = lambda name, fp=None: model_path
    key1 = node_cls.IS_CHANGED("bbox/a.pt")
    io.open(model_path, "w").write("xy")
    key2 = node_cls.IS_CHANGED("bbox/a.pt")
    check("IS_CHANGED：文件内容变化则键变化", key1 != key2, "%s / %s" % (key1, key2))
    check("IS_CHANGED：键是字符串", isinstance(key1, str), str(type(key1)))
finally:
    mod._resolve_model_path = orig_resolve
    shutil.rmtree(tmp2, ignore_errors=True)

# 软依赖：清掉 stub 与缓存后给中文提示
for key in list(sys.modules):
    if key == "impact_subpack_subcore_stub" or key.endswith(".subcore"):
        del sys.modules[key]
mod._SUBCORE = None
mod._resolve_model_path = lambda name, fp=None: "/fake/" + name
try:
    node.load_detector("bbox/face.pt")
    check("缺 Impact-Subpack 时拒绝执行", False, "未抛异常")
except RuntimeError as exc:
    check("缺 Impact-Subpack 给中文安装提示",
          "ComfyUI-Impact-Subpack" in str(exc) and "custom_nodes" in str(exc), str(exc))

# 模型找不到：中文排查提示（这里让解析返回 None，命中路径分支）
mod._resolve_model_path = lambda name, fp=None: None
mod._candidate_roots = lambda kind, fp=None: ["/tmp/models/ultralytics/" + kind]
try:
    node.load_detector("bbox/ghost.pt")
    check("模型不存在时拒绝执行", False, "未抛异常")
except ValueError as exc:
    msg = str(exc)
    check("模型不存在给中文排查提示",
          "找不到模型" in msg and "models/ultralytics/bbox" in msg and "/tmp/models" in msg, msg[:200])
finally:
    mod._resolve_model_path = orig_resolve
    mod._candidate_roots = orig_roots

# ---- 四、登记检查 ----
with io.open(os.path.join(PKG, "locales/zh/nodeDefs.json"), encoding="utf-8") as fh:
    nd = json.load(fh)
with io.open(os.path.join(PKG, "translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"), encoding="utf-8") as fh:
    tr = json.load(fh)
check("两套词表各 34 节点", len(nd) == len(tr) == 34, "%d/%d" % (len(nd), len(tr)))
key = "QG_UltralyticsDetectorLoader"
check("两套词表都有新节点", key in nd and key in tr)
check("nodeDefs inputs 覆盖 model_name", list(nd[key]["inputs"]) == ["model_name"])
check("nodeDefs outputs 用索引 0/1", set(nd[key]["outputs"]) == {"0", "1"})
check("translations outputs 用两种类型字符串",
      set(tr[key]["outputs"]) == {"BBOX_DETECTOR", "SEGM_DETECTOR"})

readme = io.open(os.path.join(PKG, "README.md"), encoding="utf-8").read()
check("README 一览表 / 来源表 / 专章齐全",
      "| `QG_UltralyticsDetectorLoader` |" in readme and
      readme.count("QG_UltralyticsDetectorLoader") >= 3 and
      "## 检测加载器" in readme)
check("README 标明 AGPL-3.0", "AGPL-3.0" in readme)
issues = io.open(os.path.join(PKG, "ISSUES.md"), encoding="utf-8").read()
check("ISSUES #154 登记", "| 154 |" in issues)
notices = io.open(os.path.join(PKG, "THIRD-PARTY-NOTICES.md"), encoding="utf-8").read()
check("NOTICES 记 Impact-Subpack AGPL-3.0 来源",
      "ComfyUI-Impact-Subpack" in notices and "AGPL-3.0" in notices)

print("=== 合计 %d PASS / %d FAIL ===" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
