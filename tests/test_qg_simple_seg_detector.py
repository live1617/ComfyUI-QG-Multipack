# -*- coding: utf-8 -*-
"""简易 Seg 检测三件套节点级测试：自造类型 / 契约 / 路径扫描 / 检测 / SAM / 双输出 / 词表。

全部用假检测器与假 SAM 对象，不依赖真实模型、网络、ComfyUI 运行时，也不依赖
Impact-Pack / ultralytics / segment_anything 是否安装（只在加载时才 import）。
运行：python_embeded\\python.exe tests\\test_qg_simple_seg_detector.py
"""
import importlib.util
import json
import os
import sys
import types

import numpy as np
import torch

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PKG)


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(PKG, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


YL = _load("yolo_loader_under_test", "qg_yolo_detector_loader.py")
SL = _load("sam_loader_under_test", "qg_sam_model_loader.py")
SD = _load("simple_seg_under_test", "qg_simple_seg_detector.py")

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


# ---------- 一、自造类型与独立边界 ----------
print("== 一、自造类型与独立边界 ==")
check("检测器类型带本包前缀", YL.DETECTOR_TYPE == "QG_YOLO_DETECTOR", YL.DETECTOR_TYPE)
check("SAM 类型带本包前缀", SL.SAM_TYPE == "QG_SAM_MODEL", SL.SAM_TYPE)
check("SEGS 类型带本包前缀", SD.SEGS_TYPE == "QG_SEGS", SD.SEGS_TYPE)
check("三类型互不相同", len({YL.DETECTOR_TYPE, SL.SAM_TYPE, SD.SEGS_TYPE}) == 3)
check("不与 Impact 类型撞名",
      not any(t in ("BBOX_DETECTOR", "SAM_MODEL", "SEGS", "SEGM_DETECTOR")
              for t in (YL.DETECTOR_TYPE, SL.SAM_TYPE, SD.SEGS_TYPE)))

for mod, fname in ((YL, "qg_yolo_detector_loader.py"),
                   (SL, "qg_sam_model_loader.py"),
                   (SD, "qg_simple_seg_detector.py")):
    src = open(os.path.join(PKG, fname), encoding="utf-8").read()
    check("%s 源码零 impact 引用" % fname,
          "import impact" not in src and "from impact" not in src
          and "subcore" not in src)
    check("%s 源码零 subprocess/eval" % fname,
          "subprocess" not in src and "eval(" not in src and "exec(" not in src)


# ---------- 二、节点注册契约 ----------
print("== 二、节点注册契约 ==")
for name, mapping in (
    ("QG_YoloDetectorLoader", YL.NODE_CLASS_MAPPINGS),
    ("QG_SamModelLoader", SL.NODE_CLASS_MAPPINGS),
    ("QG_SimpleSegDetector", SD.NODE_CLASS_MAPPINGS),
):
    check("%s 已注册" % name, name in mapping)
    cls = mapping[name]
    check("%s 有 INPUT_TYPES" % name, callable(getattr(cls, "INPUT_TYPES", None)))
    check("%s CATEGORY=QG 工具" % name, cls.CATEGORY == "QG 工具", cls.CATEGORY)
    check("%s FUNCTION 指向存在方法" % name, hasattr(cls, cls.FUNCTION))

loader_it = YL.QGYoloDetectorLoader.INPUT_TYPES()
sam_it = SL.QGSamModelLoader.INPUT_TYPES()
seg_it = SD.QGSimpleSegDetector.INPUT_TYPES()
check("加载器有 model_name 与 device",
      "model_name" in loader_it["required"] and "device" in loader_it["required"])
check("SAM 加载器有 model_name 与 device",
      "model_name" in sam_it["required"] and "device" in sam_it["required"])
check("主节点有 detector/image",
      "detector" in seg_it["required"] and "image" in seg_it["required"])
check("主节点 detector 类型是自造",
      seg_it["required"]["detector"][0] == YL.DETECTOR_TYPE)
check("主节点可选 SAM 类型是自造",
      seg_it["optional"]["sam_model"][0] == SL.SAM_TYPE)
check("主节点双输出 QG_SEGS + MASK",
      SD.QGSimpleSegDetector.RETURN_TYPES == (SD.SEGS_TYPE, "MASK"))
check("RETURN_NAMES 对齐",
      len(SD.QGSimpleSegDetector.RETURN_NAMES) == len(SD.QGSimpleSegDetector.RETURN_TYPES))

params = ["bbox_threshold", "bbox_dilation", "crop_factor", "drop_size",
          "sub_threshold", "sub_dilation", "sub_bbox_expansion",
          "sam_mask_hint_threshold", "post_dilation"]
check("截图九个控件齐全", all(p in seg_it["required"] for p in params))
defaults = {p: seg_it["required"][p][1].get("default") for p in params}
check("截图默认值一致",
      defaults == {"bbox_threshold": 0.6, "bbox_dilation": 0, "crop_factor": 3.0,
                   "drop_size": 10, "sub_threshold": 0.7, "sub_dilation": 0,
                   "sub_bbox_expansion": 0, "sam_mask_hint_threshold": 0.7,
                   "post_dilation": 0}, str(defaults))
for p in params:
    meta = seg_it["required"][p][1]
    check("%s tooltip 是中文" % p, any("\u4e00" <= c <= "\u9fff" for c in meta["tooltip"]))


# ---------- 三、模型目录扫描与路径解析 ----------
print("== 三、模型目录扫描与路径解析 ==")
import shutil
import tempfile

tmp = tempfile.mkdtemp(prefix="qg_simseg_models_")
for kind in ("bbox", "segm"):
    os.makedirs(os.path.join(tmp, "ultralytics", kind), exist_ok=True)
os.makedirs(os.path.join(tmp, "sams"), exist_ok=True)
for rel in ("ultralytics/bbox/a.pt", "ultralytics/bbox/b.onnx",
            "ultralytics/segm/c.pt", "sams/sam_vit_b_01ec64.pth",
            "sams/sam_vit_h_4b8939.pth", "sams/sam_hq_vit_l.pth"):
    path = os.path.join(tmp, *rel.split("/"))
    if not os.path.exists(path):
        open(path, "wb").write(b"x")

fp = types.ModuleType("fp")
fp.get_folder_paths = lambda n: []
fp.models_dir = tmp
fp.folder_names_and_paths = {}
fp.supported_pt_extensions = [".pt", ".pth", ".onnx", ".safetensors"]

bbox_models = YL._scan_models("bbox", fp)
segm_models = YL._scan_models("segm", fp)
check("扫到 bbox 权重", bbox_models == ["a.pt", "b.onnx"], str(bbox_models))
check("扫到 segm 权重", segm_models == ["c.pt"], str(segm_models))
check("解析 bbox 路径", YL._resolve_model_path("bbox/a.pt", fp).replace("\\", "/").endswith("ultralytics/bbox/a.pt"))
check("拒绝目录穿越", YL._resolve_model_path("bbox/../evil.pt", fp) is None)
check("未知前缀返回 None", YL._resolve_model_path("foo/a.pt", fp) is None)
sam_models = SL._scan_models(fp)
check("扫到 SAM 权重", len(sam_models) == 3, str(sam_models))
check("推断 vit_b", SL._guess_model_type("sam_vit_b_01ec64.pth") == "vit_b")
check("推断 vit_h", SL._guess_model_type("sam_vit_h_4b8939.pth") == "vit_h")
check("HQ 权重按 vit_h", SL._guess_model_type("sam_hq_vit_h.pth") == "vit_h")
check("认不出的类型返回 None", SL._guess_model_type("mystery.pth") is None)


# ---------- 四、检测对象与 SAM 对象 ----------
print("== 四、检测对象与 SAM 对象 ==")
class FakeYOLO:
    names = {0: "person", 1: "cat"}
    def predict(self, source, conf, device, verbose):
        assert source.shape == (20, 30, 3) and source.dtype == np.uint8
        assert device in ("cpu", "cuda", "auto")
        class Boxes:
            xyxy = np.array([[2, 2, 12, 12], [15, 15, 17, 17]], dtype=np.float32)
            conf = np.array([0.9, 0.3], dtype=np.float32)
            cls = np.array([0, 1], dtype=np.int64)
        class R:
            boxes = Boxes()
        return [R()]

det = YL.QGYoloDetector(FakeYOLO(), "/fake.pt", "cpu", "bbox")
found = det.detect(np.zeros((20, 30, 3), np.uint8), 0.6)
check("检测出框并按阈值过滤", len(found) == 1, str(found))
check("框元数据正确", found[0]["bbox"] == (2.0, 2.0, 12.0, 12.0)
      and found[0]["label"] == "person" and found[0]["cls"] == 0, str(found[0]))

class FakePredictor:
    def __init__(self):
        self.img_set = False
    def set_image(self, rgb):
        self.img_set = True
        self.h, self.w = rgb.shape[:2]
    def predict(self, box, multimask_output, return_logits):
        assert self.img_set and multimask_output is False and return_logits is True
        logits = np.full((1, self.h, self.w), -5.0, np.float32)
        x0, y0, x1, y1 = [int(v) for v in box]
        logits[0, y0:y1, x0:x1] = 5.0
        return None, np.array([0.95]), logits

sam = SL.QGSamModel(FakePredictor(), "/fake.pth", "cpu", "vit_b")
sam.set_image(np.zeros((20, 30, 3), np.uint8))
mask, score = sam.predict_box([2, 2, 12, 12], 0.0)
check("SAM 返回全图尺寸遮罩", mask.shape == (20, 30), str(mask.shape))
check("SAM 遮罩核心为 1", mask[5, 5] == 1.0 and mask[0, 0] == 0.0)
check("SAM 打分返回", score == 0.95)


# ---------- 五、主节点双输出与参数行为 ----------
print("== 五、主节点双输出与参数行为 ==")
class TwoBoxDet:
    def detect(self, rgb, conf):
        return [
            {"bbox": (10, 10, 40, 40), "conf": 0.9, "label": "person", "cls": 0},
            {"bbox": (60, 60, 64, 62), "conf": 0.8, "label": "small", "cls": 1},
        ]

img = np.zeros((1, 100, 120, 3), np.float32)
node = SD.QGSimpleSegDetector()

def run(sam_model=None, drop_size=10, hint_threshold=0.0, dilation=0):
    return node.detect(TwoBoxDet(), img, 0.6, 0, 3.0, drop_size, 0.0,
                       0, 0, hint_threshold, dilation, sam_model)

segs, mask = run()
check("无 SAM：小框被最小尺寸过滤", len(segs) == 1, str(len(segs)))
check("无 SAM：矩形遮罩", segs[0].mask.sum() == 900, str(segs[0].mask.sum()))
check("MASK 批次形状且为 torch.Tensor（ComfyUI 标准）",
      mask.shape == (1, 100, 120) and isinstance(mask, torch.Tensor) and
      mask.dtype == torch.float32,
      "%s %s" % (type(mask), getattr(mask, "dtype", None)))
check("SEGS 容器类型", isinstance(segs, SD.QGSegs))
check("SEGS 元素类型", isinstance(segs[0], SD.QGSeg))
check("SEGS 可迭代/索引", len(list(iter(segs))) == 1 and segs[0].label == "person")
check("合并遮罩", segs.combined_mask().shape == (100, 120))

segs_all, _ = run(drop_size=1)
check("放宽最小尺寸后两段", len(segs_all) == 2)
check("MASK 批次两帧", segs_all.mask_batch().shape == (2, 100, 120))

segs_sam, mask_sam = run(sam_model=sam)
check("带 SAM：仍过滤小框", len(segs_sam) == 1, str(len(segs_sam)))
check("带 SAM：遮罩来自 SAM", segs_sam[0].mask.sum() > 0)

segs_q, mask_q = run(sam_model=sam, hint_threshold=0.96)
check("SAM 打分过滤全丢", len(segs_q) == 0 and mask_q.shape == (0, 100, 120))

segs_d, _ = run(dilation=2)
check("后处理膨胀放大遮罩", segs_d[0].mask.sum() > 900)

# 批量输入直接拒绝
try:
    node.detect(TwoBoxDet(), np.zeros((2, 100, 120, 3), np.float32),
                0.6, 0, 3.0, 10, 0.0, 0, 0, 0.0, 0, None)
    check("批量输入被拒绝", False)
except RuntimeError as e:
    check("批量输入被拒绝", "单张图片" in str(e))

# 空结果
class EmptyDet:
    def detect(self, rgb, conf):
        return []
s4, m4 = node.detect(EmptyDet(), img, 0.6, 0, 3.0, 10, 0.0, 0, 0, 0.0, 0, None)
check("空结果 MASK 形状", len(s4) == 0 and m4.shape == (0, 100, 120))
check("空结果合并遮罩全 0", s4.combined_mask().sum() == 0)

# 框扩展
box = SD._expand_box((20, 20, 40, 40), 5, 3, 100, 100)
check("框扩展与夹取", box == (12.0, 12.0, 48.0, 48.0), str(box))
box2 = SD._expand_box((1, 1, 3, 3), 10, 0, 100, 100)
check("框扩展夹到图像边界", box2 == (0.0, 0.0, 13.0, 13.0), str(box2))

# nan 兜底
dirty = np.zeros((1, 20, 20, 3), np.float32)
dirty[0, 0, 0] = np.nan
rgb = SD._to_uint8_rgb(dirty)
check("图像 nan 兜底", np.isfinite(rgb).all() and rgb.dtype == np.uint8)


# ---------- 六、词表覆盖 ----------
print("== 六、词表覆盖 ==")
nd = json.load(open(os.path.join(PKG, "locales/zh/nodeDefs.json"), encoding="utf-8"))
tr = json.load(open(os.path.join(PKG, "translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"),
                    encoding="utf-8"))
new_keys = ("QG_YoloDetectorLoader", "QG_SamModelLoader", "QG_SimpleSegDetector")
check("两份词表均 38 节点", len(nd) == len(tr) == 38, "%d/%d" % (len(nd), len(tr)))
check("新三节点进 nodeDefs", all(k in nd for k in new_keys))
check("新三节点进 translations", all(k in tr for k in new_keys))
for k in new_keys:
    check("%s nodeDefs display_name" % k, bool(nd[k].get("display_name")))
    check("%s translations title" % k, bool(tr[k].get("title")))
    check("%s 两份都有 description" % k,
          bool(nd[k].get("description")) and bool(tr[k].get("description")))

shutil.rmtree(tmp, ignore_errors=True)

print("TOTAL ok=%d fail=%d" % (ok, fail))
sys.exit(1 if fail else 0)
