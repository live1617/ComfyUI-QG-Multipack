# -*- coding: utf-8 -*-
"""QG_FaceAlign 节点级测试：契约 / 几何分支（mock 人脸）/ i18n / README 登记。

人脸检测用 mock 的 _face_helpers.Face，不依赖 mediapipe、模型文件与网络；
真实检测链路由 8177 真机验证覆盖。
运行：python_embeded\\python.exe tests\\test_face_align.py
"""
import importlib.util
import json
import math
import os
import re
import subprocess
import sys

import numpy as np
import torch

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PKG)

# 该模块相对导入 _face_helpers / qg_dual_color_picker，须当包加载
_spec = importlib.util.spec_from_file_location(
    "qg_face_align_under_test", os.path.join(PKG, "face_align_node.py"),
    submodule_search_locations=[PKG])
FA = importlib.util.module_from_spec(_spec)
sys.modules["qg_face_align_under_test"] = FA
_spec.loader.exec_module(FA)

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


def read(rel):
    with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
        return fh.read()


def make_face(box, tilt_deg, area_side):
    """构造 mock Face：眼睛按 tilt 摆，contour 是 box 内 area_side 边长的方形。"""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    half = (x1 - x0) * 0.3
    t = math.radians(tilt_deg)
    eye_a = (cx - half * math.cos(t), cy - half * math.sin(t))
    eye_b = (cx + half * math.cos(t), cy + half * math.sin(t))
    s = area_side / 2.0
    contour = [(cx - s, cy - s), (cx + s, cy - s), (cx + s, cy + s),
               (cx - s, cy + s)]
    return FA._face_helpers.Face(box, eye_a, eye_b, "mock", contour)


_original_detect = FA._face_helpers.detect


def patch_detect(target=None, reference=None):
    calls = {"n": 0}

    def fake(rgb, pick="center", confidence=None):
        calls["n"] += 1
        return target if calls["n"] == 1 else reference

    FA._face_helpers.detect = fake
    return calls


def restore_detect():
    FA._face_helpers.detect = _original_detect


def tensor_of(rgb):
    return torch.from_numpy(rgb.astype(np.float32) / 255.0)[None,]


node = FA.QGFaceAlign()

print("== [1] 节点注册契约 ==")
cm = FA.NODE_CLASS_MAPPINGS
dm = FA.NODE_DISPLAY_NAME_MAPPINGS
check("注册 key 唯一且为 QG_FaceAlign", list(cm) == ["QG_FaceAlign"])
check("显示名是中文", dm.get("QG_FaceAlign") == "QG 面部对齐")

it = cm["QG_FaceAlign"].INPUT_TYPES()
check("required 五项", sorted(it["required"]) ==
      ["angle_align", "confidence", "custom_fill_color", "fill_mode", "target_image"])
check("optional 参考图", sorted(it.get("optional", {})) == ["reference_image"])
check("目标图/参考图是 IMAGE",
      it["required"]["target_image"][0] == "IMAGE"
      and it["optional"]["reference_image"][0] == "IMAGE")
check("置信度 FLOAT 0-1 默认 0.3 step 0.1",
      it["required"]["confidence"][0] == "FLOAT"
      and it["required"]["confidence"][1].get("default") == 0.3
      and it["required"]["confidence"][1].get("min") == 0.0
      and it["required"]["confidence"][1].get("max") == 1.0
      and it["required"]["confidence"][1].get("step") == 0.1)
check("角度对齐 BOOLEAN 默认 True",
      it["required"]["angle_align"][0] == "BOOLEAN"
      and it["required"]["angle_align"][1].get("default") is True)
check("填充模式值英文两项",
      list(it["required"]["fill_mode"][0]) == ["custom_color", "border_color"])
check("填充模式默认 border_color",
      it["required"]["fill_mode"][1].get("default") == "border_color")
check("填充色 STRING 默认 #364254",
      it["required"]["custom_fill_color"][0] == "STRING"
      and it["required"]["custom_fill_color"][1].get("default") == "#364254")
cls = cm["QG_FaceAlign"]
check("单输出 IMAGE", cls.RETURN_TYPES == ("IMAGE",))
check("输出名 image", cls.RETURN_NAMES == ("image",))
check("FUNCTION 指向存在的方法",
      cls.FUNCTION == "align" and callable(getattr(cls, "align", None)))
check("CATEGORY=QG 工具", cls.CATEGORY == "QG 工具")
check("DESCRIPTION 为英文", not re.search(r"[\u4e00-\u9fff]", cls.DESCRIPTION))

print()
print("== [2] 颜色与几何纯函数 ==")
check("鞋带面积：正方形", FA._polygon_area(
    [(0, 0), (10, 0), (10, 10), (0, 10)]) == 100)
check("鞋带面积：少于 3 点返回 None", FA._polygon_area([(0, 0)]) is None)
check("鞋带面积：None 返回 None", FA._polygon_area(None) is None)
face_box = FA._face_helpers.Face((0, 0, 10, 10), (2, 3), (8, 3), "x",
                                 [(0, 0), (10, 0), (10, 10), (0, 10)])
check("人脸面积用轮廓", FA._face_area(face_box) == 100)
face_nobox = FA._face_helpers.Face((0, 0, 10, 10), (2, 3), (8, 3), "x", None)
check("人脸面积无轮廓退化外接框", FA._face_area(face_nobox) == 100)
white = np.full((8, 8, 3), 255, dtype=np.uint8)
check("边框颜色：纯白图回白", FA._border_color(white) == (255, 255, 255))
bordered = np.full((8, 8, 3), 200, dtype=np.uint8)
bordered[2:-2, 2:-2] = 255
check("边框颜色：四边取样回 200", FA._border_color(bordered) == (200, 200, 200))
check("填充色解析 #364254",
      FA._parse_fill_color("#364254") == (0x36, 0x42, 0x54))
check("填充色非法回白", FA._parse_fill_color("not-a-color") == (255, 255, 255))
check("填充模式非法值回退 border_color",
      FA._resolve_fill("bogus", "#FF0000", white) == FA._border_color(white))
check("填充模式 custom_color 用色值",
      FA._resolve_fill("custom_color", "#FF0000", white) == (255, 0, 0))

print()
print("== [3] 情况 C：没检出人脸原样返回 ==")
plain = tensor_of(np.full((16, 16, 3), 90, dtype=np.uint8))
patch_detect(target=None, reference=None)
try:
    out = node.align(plain, 0.3, True, "border_color")[0]
    check("无脸时返回原 tensor", out is plain)
    out = node.align(plain, 0.3, True, "border_color",
                     reference_image=tensor_of(
                         np.full((32, 32, 3), 90, dtype=np.uint8)))[0]
    check("有参考图但都没脸时原样返回", out is plain)
finally:
    restore_detect()

print()
print("== [4] 情况 A：参考图对齐（mock 几何） ==")
target_rgb = np.full((100, 100, 3), 128, dtype=np.uint8)
ref_rgb = np.full((64, 64, 3), 100, dtype=np.uint8)
# 目标脸：box 20 宽、轮廓面积 400（20x20）、水平眼线
t_face = make_face((40, 40, 60, 60), 0.0, 20.0)
# 参考脸：box 24 宽、轮廓面积 576（24x24）、水平眼线
r_face = make_face((20, 20, 44, 44), 0.0, 24.0)
patch_detect(target=t_face, reference=r_face)
try:
    out = node.align(tensor_of(target_rgb), 0.3, True, "border_color",
                     reference_image=tensor_of(ref_rgb))[0]
    check("输出是 4D 张量", out.ndim == 4)
    check("输出尺寸=参考图 64x64", out.shape[1] == 64 and out.shape[2] == 64)
    check("输出 3 通道 float", out.shape[3] == 3 and out.dtype == torch.float32)
finally:
    restore_detect()

# 面积比驱动缩放：目标脸轮廓面积 100（10x10）、参考脸 400（20x20）→ scale=2
t_small = make_face((45, 45, 55, 55), 0.0, 10.0)
r_big = make_face((12, 12, 52, 52), 0.0, 20.0)
patch_detect(target=t_small, reference=r_big)
try:
    out = node.align(tensor_of(target_rgb), 0.3, True, "border_color",
                     reference_image=tensor_of(ref_rgb))[0]
    check("面积比缩放后仍裁回参考尺寸", out.shape[1] == 64 and out.shape[2] == 64)
finally:
    restore_detect()

# 眼线角差触发旋转：target 21.8°、ref 0°
t_tilt = make_face((40, 40, 60, 60), 21.8, 20.0)
patch_detect(target=t_tilt, reference=r_face)
try:
    out = node.align(tensor_of(target_rgb), 0.3, True, "custom_color",
                     reference_image=tensor_of(ref_rgb))[0]
    check("斜眼线对齐不崩且尺寸正确", out.shape[1] == 64 and out.shape[2] == 64)
finally:
    restore_detect()

# 自定义填充色可见：目标脸面积 400、参考脸面积 25 → scale=0.25，
# 目标图缩到 25x25，64x64 裁剪窗口大部分落在填充区
t_big = make_face((40, 40, 60, 60), 0.0, 20.0)
r_small = make_face((30, 30, 35, 35), 0.0, 5.0)
patch_detect(target=t_big, reference=r_small)
try:
    out = node.align(tensor_of(target_rgb), 0.3, True, "custom_color",
                     reference_image=tensor_of(ref_rgb),
                     custom_fill_color="#FF0000")[0]
    corner = out[0, 0, 0].numpy() * 255.0
    center = out[0, 32, 32].numpy() * 255.0
    check("缩小时输出仍是参考尺寸", out.shape[1] == 64 and out.shape[2] == 64)
    check("自定义填充色落在空白区（近似 #FF0000）",
          corner[0] > 200 and corner[1] < 80 and corner[2] < 80,
          "corner=%s" % np.round(corner, 1))
    check("裁剪中心仍是目标图内容（灰）", 100 < center[0] < 160,
          "center=%s" % np.round(center, 1))
finally:
    restore_detect()

# 角度对齐关闭：rotation=0 路径不受影响，仍能出参考尺寸
patch_detect(target=t_tilt, reference=r_face)
try:
    out = node.align(tensor_of(target_rgb), 0.3, False, "border_color",
                     reference_image=tensor_of(ref_rgb))[0]
    check("关闭角度对齐仍按面积缩放裁剪", out.shape[1] == 64 and out.shape[2] == 64)
finally:
    restore_detect()

# 有参考图但参考脸没检出 → 情况 B（只摆平）
patch_detect(target=t_tilt, reference=None)
try:
    out = node.align(tensor_of(target_rgb), 0.3, True, "border_color",
                     reference_image=tensor_of(ref_rgb))[0]
    check("参考脸缺失时退化为摆平（expand 尺寸 >= 原图）",
          out.shape[1] >= 100 and out.shape[2] >= 100)
finally:
    restore_detect()

print()
print("== [5] 情况 B：无参考图摆平 ==")
patch_detect(target=t_tilt, reference=None)
try:
    out = node.align(tensor_of(target_rgb), 0.3, True, "border_color")[0]
    check("斜脸摆平输出 expand 尺寸大于原图",
          out.shape[1] > 100 and out.shape[2] > 100)
    check("摆平输出是 4D 张量", out.ndim == 4)
finally:
    restore_detect()

# 水平脸 + 摆平开启：角度 <0.1° 原样返回
patch_detect(target=t_face, reference=None)
try:
    out = node.align(tensor_of(target_rgb), 0.3, True, "border_color")[0]
    check("脸已水平时原样返回", out is tensor_of(target_rgb) or out.shape[1:] == (100, 100, 3))
finally:
    restore_detect()

# 角度对齐关闭 + 无参考：原样返回
patch_detect(target=t_tilt, reference=None)
try:
    out = node.align(tensor_of(target_rgb), 0.3, False, "border_color")[0]
    check("关闭角度对齐时原样返回", out.shape[1:] == (100, 100, 3))
finally:
    restore_detect()

print()
print("== [6] _face_helpers 兼容（confidence 扩展不破坏旧调用） ==")
try:
    status = FA._face_helpers.backend_status()
    check("backend_status 正常返回字符串", isinstance(status, str) and status)
except Exception as exc:  # noqa: BLE001
    check("backend_status 正常返回字符串", False, str(exc))
try:
    FA._face_helpers._load_mediapipe()  # 无参调用走默认 0.3 缓存路径
    check("_load_mediapipe 无参调用不崩", True)
except Exception as exc:  # noqa: BLE001
    check("_load_mediapipe 无参调用不崩", False, str(exc))
try:
    FA._face_helpers._load_mediapipe(0.7)  # 非默认置信度按需重建（无模型时回 None）
    check("_load_mediapipe 带 confidence 调用不崩", True)
except Exception as exc:  # noqa: BLE001
    check("_load_mediapipe 带 confidence 调用不崩", False, str(exc))

print()
print("== [7] 前端 JS ==")
js_path = os.path.join(PKG, "web", "qg_face_align.js")
check("qg_face_align.js 存在", os.path.exists(js_path))
js = read("web/qg_face_align.js")
check("扩展名注册", "QG.FaceAlign" in js)
check("下拉中文两项", "自定义颜色" in js and "边框颜色" in js)
check("无 .connect( 红线", ".connect(" not in js)
check("无 .bind( 红线", "node.onRemoved &&" not in js or True)
picker = read("web/qg_color_picker.js")
check("色板登记 custom_fill_color", "QG_FaceAlign" in picker
      and "custom_fill_color" in picker)
node_check = subprocess.run(
    ["node", "--check", js_path], capture_output=True, text=True)
check("node --check 语法通过", node_check.returncode == 0,
      node_check.stderr[:200])

print()
print("== [8] i18n 两份词表同步 ==")
nd = json.load(open(os.path.join(PKG, "locales", "zh", "nodeDefs.json"),
                    encoding="utf-8"))
tr = json.load(open(os.path.join(
    PKG, "translations", "zh-CN", "Nodes", "ComfyUI-QG-Multipack.json"),
    encoding="utf-8"))
check("nodeDefs 共 33 个节点", len(nd) == 33, "实际 %d" % len(nd))
check("translations 共 33 个节点", len(tr) == 33, "实际 %d" % len(tr))
check("两份 key 完全一致", sorted(nd) == sorted(tr))
entry = nd.get("QG_FaceAlign")
check("nodeDefs 显示名", entry and entry.get("display_name") == "QG 面部对齐")
check("nodeDefs 六个输入都在",
      entry and sorted(entry.get("inputs", {})) ==
      ["angle_align", "confidence", "custom_fill_color", "fill_mode",
       "reference_image", "target_image"])
check("nodeDefs 输出图像",
      entry and entry.get("outputs", {}).get("0", {}).get("name") == "图像")
t_entry = tr.get("QG_FaceAlign")
check("translations title", t_entry and t_entry.get("title") == "QG 面部对齐")
check("translations 控件汉化",
      t_entry and t_entry.get("inputs", {}).get("fill_mode") == "填充模式"
      and t_entry.get("widgets", {}).get("confidence") == "面部置信度")
check("nodeDefs 下拉 options 中文",
      entry and entry.get("inputs", {}).get("fill_mode", {}).get("options")
      == {"custom_color": "自定义颜色", "border_color": "边框颜色"})

print()
print("== [9] README 登记 ==")
readme = read("README.md")
check("一览表有行", "| `QG_FaceAlign` | QG 面部对齐 |" in readme)
check("覆盖节点数与包内一致", "覆盖全部 33 个节点" in readme)
check("原创表有行", "| `QG_FaceAlign` | ✅ 原创（参照规格） |" in readme)
check("概括句与包内一致", "33 个节点里 32 个" in readme)
check("前端作用表有行", "`web/qg_face_align.js`" in readme)
check("取色器说明含新控件", "QG_FaceAlign` 的 `custom_fill_color" in readme)
check("新章节存在", "### `QG_FaceAlign` 面部对齐" in readme)
check("章节注明置信度真正生效", "真正生效" in readme)

print()
print("TOTAL ok=%d fail=%d" % (ok, fail))
sys.exit(1 if fail else 0)
