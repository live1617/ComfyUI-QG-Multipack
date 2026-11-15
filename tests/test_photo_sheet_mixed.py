# -*- coding: utf-8 -*-
"""QG_PhotoSheetMixed：规格对照 + 13 版式几何 + 渲染 + 词表一致性。

规格对照走 tests/ref_helper.py（GPL 参考源码只读）。运行前需设置
``QG_GOOHAI_REF_ROOT``；参考缺失时按项目纪律 exit=2，绝不静默 SKIP。
"""
import ast
import importlib.util
import json
import pathlib
import sys

import numpy as np
import torch
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ref_helper import require_ref  # noqa: E402

PKG = HERE.parent
spec = importlib.util.spec_from_file_location(
    "qg_psm_test", str(PKG / "photo_sheet_mixed_node.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

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


# ---------- 1. 规格对照（GPL 参考源码，只读） ----------
REF_FILE = pathlib.Path(require_ref("nodes", "证件照排版（A5定制）.py"))
tree = ast.parse(REF_FILE.read_text(encoding="utf-8"))
ref_layouts, ref_sizes = None, None
for node in ast.walk(tree):
    if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
        for key, val in zip(node.value.keys, node.value.values):
            if isinstance(key, ast.Constant) and key.value == "required":
                for opt_key, opt_val in zip(val.keys, val.values):
                    # 上游 required 里有条件表达式（字体下拉），整表不能
                    # literal_eval；这里只取「尺寸选择」那一项。
                    if (isinstance(opt_key, ast.Constant)
                            and opt_key.value == "尺寸选择"):
                        ref_layouts = ast.literal_eval(opt_val)[0]
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "sizes":
                ref_sizes = ast.literal_eval(node.value)
check("参考源码可解析出 13 个版式名与尺寸表",
      bool(ref_layouts) and bool(ref_sizes))
check("规格：13 个版式中文名与参考逐项、同序一致",
      [v["zh"] for v in M.LAYOUTS] == list(ref_layouts),
      ([v["zh"] for v in M.LAYOUTS], list(ref_layouts)))
check("规格：9 个命名尺寸与参考一致",
      all(M.SIZES_CM.get(k) == tuple(v) for k, v in ref_sizes.items()),
      [(k, v, M.SIZES_CM.get(k)) for k, v in ref_sizes.items()
       if M.SIZES_CM.get(k) != tuple(v)])

# ---------- 2. 13 版式几何（纯整数运算，不渲染） ----------
EXPECTED_COUNTS = [14, 12, 8, 8, 8, 8, 13, 12, 12, 12, 12, 12, 8]
check("13 个版式", len(M.LAYOUTS) == 13)
check("版式 key 全部 ASCII 且唯一",
      all(k.isascii() for k in M.LAYOUT_KEYS)
      and len(set(M.LAYOUT_KEYS)) == 13)

for dpi in (72, 150, 300, 600, 1200):
    for layout, expected in zip(M.LAYOUTS, EXPECTED_COUNTS):
        plan = M.layout_plan(layout["key"], dpi)
        cells = plan["cells"]
        inside = all(c["x"] >= 0 and c["y"] >= 0
                     and c["x"] + c["w"] <= plan["canvas_w"]
                     and c["y"] + c["h"] <= plan["canvas_h"] for c in cells)
        overlap = any(
            not (a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"]
                 or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"])
            for i, a in enumerate(cells) for b in cells[i + 1:])
        good = (len(cells) == expected and inside and not overlap
                and plan["scale"] == 1.0)
        check("几何 dpi=%d %s：%d 格 / 不越界 / 不重叠" % (dpi, layout["key"], expected),
              good,
              "cells=%d inside=%s overlap=%s scale=%s" % (
                  len(cells), inside, overlap, plan["scale"]))
        if dpi == 300:
            continue

p = M.layout_plan("mix_22x32_8_31x46_4", 300)
check("竖版 A5 画布为 14.8x21cm",
      p["canvas_w"] == M.cm_to_px(14.8, 300)
      and p["canvas_h"] == M.cm_to_px(21.0, 300))
check("竖版版式起点距顶 2cm", p["start_y"] == M.cm_to_px(2.0, 300))
check("竖版有 4 条横带、12 张", len(p["regions"]) == 4 and len(p["cells"]) == 12)
check("横版版式整体居中",
      M.layout_plan("small1_14", 300)["start_x"]
      == (M.cm_to_px(21, 300) - M.layout_plan("small1_14", 300)["total_w"]) // 2)
check("无间距版式 spacing=0",
      M.layout_plan("plain_34x49_nogap", 300)["spacing"] == 0
      and M.layout_plan("mix_24x34_33x48_nogap", 300)["spacing"] == 0)
rot = M.layout_plan("mix_1_8_2_4", 300)
rot_cell = rot["cells"][0]
check("旋转区：裁剪源尺寸未交换、单元格已交换",
      rot_cell["rotate"] and rot_cell["src_w"] < rot_cell["src_h"]
      and rot_cell["w"] > rot_cell["h"]
      and rot_cell["w"] == rot_cell["src_h"]
      and rot_cell["h"] == rot_cell["src_w"],
      (rot_cell["src_w"], rot_cell["src_h"], rot_cell["w"], rot_cell["h"]))

# 人为注入一个超界版式，验证 fit 缩小与关闭时报数
M.LAYOUT_BY_KEY["_test_oversize"] = M._layout(
    "_test_oversize", "测试超界", [[M._region("大2寸", 20, 20)]],
    spacing_cm=0.4)
big = M.layout_plan("_test_oversize", 300, True)
check("改进：超界版式自动等比缩小且仍不越界",
      big["scale"] < 1.0
      and all(c["x"] + c["w"] <= big["canvas_w"]
              and c["y"] + c["h"] <= big["canvas_h"] for c in big["cells"]),
      big["scale"])
try:
    M.layout_plan("_test_oversize", 300, False)
    check("改进：关闭 fit 时明确报错", False, "未抛异常")
except ValueError as err:
    check("改进：关闭 fit 时明确报错且带像素数", "px needed" in str(err), str(err))
del M.LAYOUT_BY_KEY["_test_oversize"]

# ---------- 3. 颜色 / 渲染 ----------
check("颜色：#RRGGBB", M.parse_color("#6c1e27") == (108, 30, 39))
check("颜色：#RGB 短写", M.parse_color("#f00") == (255, 0, 0))
check("颜色：颜色名", M.parse_color("white") == (255, 255, 255))
check("颜色：非法值回退黑色", M.parse_color("??not-a-colour") == (0, 0, 0))

red = Image.new("RGB", (600, 900), (220, 20, 30))
plan = M.layout_plan("mix_1_8_2_4", 300)
plain = M.render_sheet(red, plan, 0, "#000000", "", "<default>", 0)
check("渲染：画布尺寸等于相纸像素",
      plain.size == (plan["canvas_w"], plan["canvas_h"]))
cell = plan["cells"][0]
check("渲染：照片落在网格中心且为原色",
      plain.getpixel((cell["x"] + cell["w"] // 2,
                      cell["y"] + cell["h"] // 2)) == (220, 20, 30))
bordered = M.render_sheet(red, plan, 6, "#00ff00", "", "<default>", 0)
check("改进：描边画在照片内部、不放大单元格",
      bordered.size == plain.size
      and bordered.getpixel((cell["x"] + 2, cell["y"] + 2)) == (0, 255, 0),
      bordered.getpixel((cell["x"] + 2, cell["y"] + 2)))
check("描边 0 时无边框像素",
      plain.getpixel((cell["x"] + 2, cell["y"] + 2)) == (220, 20, 30))
captioned = M.render_sheet(red, plan, 0, "#000000", "测试", "<default>", 24)
check("渲染：带文字不抛错且尺寸不变", captioned.size == plain.size)

# ---------- 4. 节点执行（批量逐帧） ----------
def frame(colour):
    arr = np.array(Image.new("RGB", (64, 96), colour), dtype=np.float32) / 255.0
    return torch.from_numpy(arr)

batch = torch.stack([frame((220, 20, 30)), frame((20, 220, 30)),
                     frame((20, 30, 220))])
node = M.QGPhotoSheetMixed()
sheet, name, total = node.execute(batch, "mix_1_8_2_4", 300, 0, "#000000",
                                  "", "<default>", 0, True)
check("执行：批量 3 帧 → 3 张相纸", sheet.shape[0] == 3, tuple(sheet.shape))
check("执行：返回版式中文名与张数",
      name == "1寸 8张 + 2寸 4张" and total == 12, (name, total))
check("执行：输出形状与相纸一致且值域 0-1",
      sheet.shape[1:3] == (plan["canvas_h"], plan["canvas_w"])
      and float(sheet.min()) >= 0 and float(sheet.max()) <= 1,
      tuple(sheet.shape))
colours = []
for i in range(3):
    arr = (sheet[i].numpy() * 255).astype(np.uint8)
    colours.append(tuple(int(v) for v in arr[
        cell["y"] + cell["h"] // 2, cell["x"] + cell["w"] // 2]))
check("改进：三帧颜色各不相同（上游只取第一帧）",
      len(set(colours)) == 3, colours)
single = node.execute(frame((220, 20, 30)), "small1_14", 300, 0, "#000000",
                      "", "<default>", 0, True)
check("执行：3D 单帧输入也能出图", single[0].shape[0] == 1 and single[2] == 14)

# ---------- 5. 契约 / 词表 ----------
it = M.QGPhotoSheetMixed.INPUT_TYPES()["required"]
check("契约：9 个控件", len(it) == 9, list(it))
check("契约：layout 下拉 13 项且默认在列表中",
      len(it["layout"][0]) == 13 and it["layout"][1]["default"] in it["layout"][0])
check("契约：RETURN_TYPES / FUNCTION / CATEGORY",
      M.QGPhotoSheetMixed.RETURN_TYPES == ("IMAGE", "STRING", "INT")
      and M.QGPhotoSheetMixed.FUNCTION == "execute"
      and M.QGPhotoSheetMixed.CATEGORY == "QG 工具")
check("契约：注册 key 唯一", list(M.NODE_CLASS_MAPPINGS) == ["QG_PhotoSheetMixed"])
check("契约：后端 DESCRIPTION 为英文",
      M.QGPhotoSheetMixed.DESCRIPTION.isascii())
check("契约：字体下拉全部为系统字体文件名",
      it["font"][0][0] == "<default>" and all(f.endswith((".ttf", ".ttc"))
                                              for f in it["font"][0][1:]))

js = (PKG / "web/qg_photo_sheet_mixed.js").read_text(encoding="utf-8")
js_labels = json.loads(js.split("const LABELS = ", 1)[1].split(";\n\nfunction", 1)[0])
check("前端 LABELS 与版式表一致", js_labels == M.LAYOUT_LABELS)
check("前端无 .connect( / .bind( 字面量",
      ".connect(" not in js and ".bind(" not in js)
menu = json.loads((PKG / "translations/zh-CN/Menus/ComfyUI-QG-Multipack.json")
                  .read_text(encoding="utf-8"))
check("Menus 词表覆盖 13 个版式值且中文一致",
      all(menu.get(k) == v for k, v in M.LAYOUT_LABELS.items()))
nd = json.loads((PKG / "locales/zh/nodeDefs.json").read_text(encoding="utf-8"))
tr = json.loads((PKG / "translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json")
                .read_text(encoding="utf-8"))
check("nodeDefs 有该节点且 outputs 为索引 0/1/2",
      list(nd["QG_PhotoSheetMixed"]["outputs"]) == ["0", "1", "2"])
check("translations inputs/widgets 覆盖 9 控件",
      set(tr["QG_PhotoSheetMixed"]["inputs"]) == set(it)
      == set(nd["QG_PhotoSheetMixed"]["inputs"]))

print("TOTAL ok=%d fail=%d" % (ok, fail))
sys.exit(1 if fail else 0)
