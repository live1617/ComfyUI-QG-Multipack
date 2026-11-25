# -*- coding: utf-8 -*-
"""QG_ImageMaskPreview 节点回归：契约、上色、序号、缩放、颜色/字体、词表登记。

本节点零相对导入，可直接按文件路径加载，不需要父包上下文。
"""
import importlib.util
import json
import os
import re
import sys

import numpy as np
import torch

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, filename):
    path = os.path.join(PKG, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load("qg_image_mask_preview", "qg_image_mask_preview.py")

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


def white(h=40, w=50):
    return torch.ones((1, h, w, 3))


def black(h=40, w=50):
    return torch.zeros((1, h, w, 3))


def rect(h, w, y0, y1, x0, x1):
    p = np.zeros((h, w), np.float32)
    p[y0:y1, x0:x1] = 1.0
    return p


print("== 一、静态契约 ==")
check("注册 key 唯一", list(M.NODE_CLASS_MAPPINGS) == ["QG_ImageMaskPreview"],
      str(list(M.NODE_CLASS_MAPPINGS)))
check("显示名中文", M.NODE_DISPLAY_NAME_MAPPINGS["QG_ImageMaskPreview"] == "QG 图像与遮罩预览")
cls = M.QGImageMaskPreview
check("分类 QG 工具", cls.CATEGORY == "QG 工具")
check("FUNCTION=preview", cls.FUNCTION == "preview")
t = cls.INPUT_TYPES()
req = t["required"]
check("两个原生输入 IMAGE + MASK",
      req["image"][0] == "IMAGE" and req["mask"][0] == "MASK")
check("8 个控件（2 输入 + 8 控件）", len(req) == 10, str(list(req)))
check("颜色控件是 STRING 不是 GHCOLOR",
      req["mask_color"][0] == "STRING" and req["index_color"][0] == "STRING")
check("遮罩不透明默认 0.4", req["mask_opacity"][1]["default"] == 0.4)
check("序号不透明默认 0.8", req["index_opacity"][1]["default"] == 0.8)
check("序号缩放两项", req["index_scale"][0] == ["跟随遮罩缩放", "固定大小"])
check("序号比例默认 0.15", req["index_ratio"][1]["default"] == 0.15)
check("序号比例默认不会压盖半身",
      req["index_ratio"][1]["default"] <= 0.2,
      req["index_ratio"][1]["default"])
check("布尔显示序号有 label_on/label_off",
      req["show_index"][0] == "BOOLEAN"
      and req["show_index"][1].get("label_on") and req["show_index"][1].get("label_off"))
check("控件 tooltip 全中文",
      all(any("\u4e00" <= ch <= "\u9fff" for ch in str(v[1].get("tooltip", "")))
          for v in req.values()))
check("输出单 IMAGE", cls.RETURN_TYPES == ("IMAGE",) and cls.RETURN_NAMES == ("image",))
check("输出 tooltip 中文",
      any("\u4e00" <= ch <= "\u9fff" for ch in str(cls.OUTPUT_TOOLTIPS[0])))
check("DESCRIPTION 全 ASCII（走词表）", all(ord(c) < 128 for c in cls.DESCRIPTION))
check("源码无 impact 引用",
      "import impact" not in open(os.path.join(PKG, "qg_image_mask_preview.py"),
                                  encoding="utf-8").read())

print("\n== 二、遮罩上色 ==")
m = torch.from_numpy(np.stack([rect(40, 50, 5, 15, 5, 15),
                               rect(40, 50, 20, 35, 30, 45)]))
out = M.render_preview(white(), m, mask_opacity=1.0,
                       mask_color="#ff0000", show_index=False)[0]
check("输出形状 [1,H,W,3]", tuple(out.shape) == (1, 40, 50, 3), str(tuple(out.shape)))
a = out[0].numpy()
check("第一块染成红色", np.allclose(a[6, 6], [1, 0, 0]), str(a[6, 6]))
check("第二块染成红色", np.allclose(a[22, 32], [1, 0, 0]), str(a[22, 32]))
check("非遮罩区保持白色", np.allclose(a[0, 0], [1, 1, 1]), str(a[0, 0]))
half = M.render_preview(white(), m, mask_opacity=0.5,
                        mask_color="#ff0000", show_index=False)[0][0].numpy()
check("半透明混色正确", np.allclose(half[6, 6], [1.0, 0.5, 0.5], atol=0.01),
      str(half[6, 6]))
zero = M.render_preview(white(), m, mask_opacity=0.0,
                        mask_color="#ff0000", show_index=False)[0][0].numpy()
check("不透明 0 不叠加", np.allclose(zero, 1.0))

print("\n== 三、序号 ==")
no_num = M.render_preview(black(), m, mask_opacity=0.0, show_index=False)[0][0].numpy()
yes_num = M.render_preview(black(), m, mask_opacity=0.0, show_index=True,
                           index_opacity=1.0, index_color="#ffffff")[0][0].numpy()
check("序号确实画上", int((yes_num.sum(axis=2) > 0).sum()) > 0)
check("关闭序号无像素变化", int((no_num.sum(axis=2) > 0).sum()) == 0)
trans = M.render_preview(black(), m, mask_opacity=0.0, show_index=True,
                         index_opacity=0.0, index_color="#ffffff")[0][0].numpy()
check("序号不透明 0 不可见", int((trans.sum(axis=2) > 0).sum()) == 0)
follow = M.render_preview(black(), m, mask_opacity=0.0, show_index=True,
                          index_opacity=1.0, index_scale="跟随遮罩缩放",
                          index_ratio=0.8)[0][0].numpy()
fixed = M.render_preview(black(), m, mask_opacity=0.0, show_index=True,
                         index_opacity=1.0, index_scale="固定大小",
                         index_ratio=0.8)[0][0].numpy()
check("跟随/固定两模式有差异", int((follow != fixed).any(axis=2).sum()) > 0)
check("序号颜色生效（红）",
      int((M.render_preview(black(), m, mask_opacity=0.0, show_index=True,
                            index_opacity=1.0, index_color="#ff0000")[0][0].numpy()
           [:, :, 0] > 0).sum()) > 0)

print("\n== 四、颜色解析 ==")
check("3 位 hex 展开", M.parse_color("#abc", "#ffffff") == (170, 187, 204))
check("6 位 hex", M.parse_color("#c524ff", "#000000") == (197, 36, 255))
check("非法回退", M.parse_color("zzz", "#123456") == (18, 52, 86))
check("空值回退", M.parse_color(None, "#ffffff") == (255, 255, 255))

print("\n== 五、边界与形状 ==")
# 方形图（H==W）——曾触发 _fit_mask 的 3D 索引 bug
sq = M.render_preview(torch.zeros((1, 10, 10, 3)), torch.zeros((10, 10)),
                      show_index=False)[0]
check("方形图 + 空遮罩不崩", tuple(sq.shape) == (1, 10, 10, 3))
check("空遮罩输出原图（黑）", bool((sq == 0).all()))
# 0 帧图像批次：给中文错误而不是 IndexError（用户要知道是哪个节点、为什么）
try:
    M.render_preview(torch.zeros((0, 10, 10, 3)), torch.zeros((10, 10)),
                     show_index=False)
    check("0 帧图像批次报中文错", False)
except ValueError as exc:
    check("0 帧图像批次报中文错", "空图像批次" in str(exc), str(exc))
# RGBA 透明压黑
rgba = torch.zeros((1, 10, 10, 4))
rgba[..., :3] = 1.0
rgba[..., 3] = 0.5
r = M.render_preview(rgba, torch.zeros((10, 10)), show_index=False)[0][0].numpy()
check("RGBA alpha 压黑", abs(float(r[0, 0, 0]) - 0.5) < 0.01, str(float(r[0, 0, 0])))
# 遮罩尺寸不匹配 -> 最近邻缩放
sc = M.render_preview(white(10, 10), torch.ones((5, 6)),
                      mask_opacity=1.0, mask_color="#00ff00",
                      show_index=False)[0][0].numpy()
check("遮罩缩放到图像尺寸后全绿",
      np.allclose(sc, np.array([0, 1, 0], np.float32)))
# NaN 遮罩
bad = torch.from_numpy(np.array([[np.nan, 0.9], [0.2, np.inf]], np.float32))
bn = M.render_preview(torch.zeros((1, 2, 2, 3)), bad, show_index=False)[0].numpy()
check("NaN 遮罩输出有限值", bool(np.isfinite(bn).all()))
# 单张 2D 遮罩
one = M.render_preview(white(), torch.from_numpy(rect(40, 50, 5, 15, 5, 15)),
                       mask_opacity=1.0, mask_color="#0000ff",
                       show_index=False)[0][0].numpy()
check("2D 单张遮罩可处理", np.allclose(one[6, 6], [0, 0, 1]))
# 8 位色值 #RRGGBBAA：透明度由滑杆控制，这里只取 RGB，不能整串判非法回退
check("8 位色值取 RGB",
      M.parse_color("#c524ff80", "#000000") == (197, 36, 255),
      str(M.parse_color("#c524ff80", "#000000")))
# 三维一律按 [B,H,W]：不能因为最后一维是 1 就猜成 [H,W,1] 单帧
# （那会把 [B,H,1] 批次压成一帧，帧数与尺寸全错）。
check("[B,1,W] 保留批次不被压成一帧",
      tuple(M._mask_frames(torch.zeros(3, 1, 8)).shape) == (3, 1, 8),
      str(tuple(M._mask_frames(torch.zeros(3, 1, 8)).shape)))
check("[B,H,1] 保留批次不被当单帧",
      tuple(M._mask_frames(torch.zeros(4, 6, 1)).shape) == (4, 6, 1),
      str(tuple(M._mask_frames(torch.zeros(4, 6, 1)).shape)))
b1w = M.render_preview(white(10, 10), torch.zeros((3, 1, 8)), show_index=False)[0]
check("[B,1,W] 端到端不崩", tuple(b1w.shape) == (1, 10, 10, 3), str(tuple(b1w.shape)))
# 端到端节点调用
res = cls().preview(white(), m, 1.0, "#ff0000", False, 0.8,
                    "跟随遮罩缩放", 0.5, None, "#ffffff")
check("节点 preview 返回单 IMAGE", isinstance(res, tuple) and len(res) == 1
      and isinstance(res[0], torch.Tensor))

print("\n== 六、字体 ==")
fc = M.font_choices()
check("字体候选含 default", fc and fc[0] == "<default>")
check("默认字体在候选里", M.default_font() in fc)
check("默认字体是随包 OFL", M.default_font() == "NotoSansSC-VF.ttf")
check("load_font 缺字体回退不崩", M.load_font("__nonexistent__.ttf", 20) is not None)

print("\n== 七、词表与前端登记 ==")
with open(os.path.join(PKG, "locales/zh/nodeDefs.json"), encoding="utf-8") as fh:
    nd = json.load(fh)
with open(os.path.join(PKG, "translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"),
          encoding="utf-8") as fh:
    tr = json.load(fh)
check("两套词表 39 节点", len(nd) == len(tr) == 39, "%d/%d" % (len(nd), len(tr)))
key = "QG_ImageMaskPreview"
check("nodeDefs 有新节点", key in nd and nd[key]["display_name"] == "QG 图像与遮罩预览")
check("nodeDefs 10 输入全覆盖",
      set(nd[key]["inputs"]) == {"image", "mask", "mask_opacity", "mask_color",
                                 "show_index", "index_opacity", "index_scale",
                                 "index_ratio", "index_font", "index_color"})
check("nodeDefs 输出中文", nd[key]["outputs"]["0"]["name"] == "图像")
check("translations 有 title 与 description",
      bool(tr[key].get("title")) and bool(tr[key].get("description")))
check("translations 无恒等翻译",
      not [(f, k) for f in ("inputs", "widgets", "outputs")
           for k, v in tr[key].get(f, {}).items() if k == v])
rd = open(os.path.join(PKG, "README.md"), encoding="utf-8").read()
check("README 节点表登记", "`QG_ImageMaskPreview`" in rd)
check("README 专章登记", "### `QG_ImageMaskPreview` 图像与遮罩预览" in rd)
check("README 节点数 39", "本节覆盖全部 39 个节点" in rd)
js = open(os.path.join(PKG, "web/qg_color_picker.js"), encoding="utf-8").read()
check("色块三处登记",
      "QG_ImageMaskPreview: [\"mask_color\", \"index_color\"]" in js
      and "mask_color: \"遮罩颜色\"" in js
      and "mask_color: { en: \"Mask Color\", zh: \"遮罩颜色\" }" in js)

print("\n== 汇总：PASS %d / FAIL %d ==" % (ok, fail))
sys.exit(1 if fail else 0)
