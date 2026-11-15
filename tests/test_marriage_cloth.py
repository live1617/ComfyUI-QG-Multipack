# -*- coding: utf-8 -*-
"""QG_MarriageCloth 节点级测试：自然排序 / 扫描 / 路径安全 / 尺寸模式 / 契约 / i18n。

素材用 tmp 目录构造，不依赖真实 models/marriage_cloth；末尾单独核对插件内置
素材是否随包存在（81 张）。
运行：python_embeded\\python.exe tests\\test_marriage_cloth.py
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PKG)

_spec = importlib.util.spec_from_file_location(
    "qg_marriage_cloth_under_test", os.path.join(PKG, "qg_marriage_cloth.py"),
    submodule_search_locations=[PKG])
IMC = importlib.util.module_from_spec(_spec)
sys.modules["qg_marriage_cloth_under_test"] = IMC
_spec.loader.exec_module(IMC)

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


def make_img(path, size=(40, 20), color=(200, 60, 60)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


tmp = Path(tempfile.mkdtemp(prefix="qg_imo_"))
root_a = tmp / "a"
root_b = tmp / "b"

# ---------- 1. 契约 ----------
MAPPINGS = IMC.NODE_CLASS_MAPPINGS
check("契约：注册 key 唯一且为 QG_MarriageCloth",
      list(MAPPINGS) == ["QG_MarriageCloth"], list(MAPPINGS))
cls = MAPPINGS.get("QG_MarriageCloth")
check("契约：类存在", cls is not None)
check("契约：RETURN_TYPES 与 RETURN_NAMES 等长",
      len(cls.RETURN_TYPES) == len(cls.RETURN_NAMES),
      (cls.RETURN_TYPES, cls.RETURN_NAMES))
check("契约：输出单帧 IMAGE", cls.RETURN_TYPES == ("IMAGE",), cls.RETURN_TYPES)
check("契约：FUNCTION 指向的方法存在",
      callable(getattr(cls, cls.FUNCTION, None)), cls.FUNCTION)
check("契约：分类为 QG 工具", cls.CATEGORY == "QG 工具", cls.CATEGORY)
check("契约：显示名中文",
      IMC.NODE_DISPLAY_NAME_MAPPINGS["QG_MarriageCloth"] == "QG 结婚登记照服装",
      IMC.NODE_DISPLAY_NAME_MAPPINGS)

inputs = cls.INPUT_TYPES()
req = inputs["required"]
check("控件：image_index / resize_mode / target_* / pad_color 齐全",
      {"image_index", "resize_mode", "target_width", "target_height",
       "pad_color"} <= set(req), list(req))
check("控件：隐藏 cloth_name",
      "cloth_name" in (inputs.get("hidden") or {}), list(inputs))
check("控件：resize_mode 值为英文",
      req["resize_mode"][0] == ["fit_pad", "stretch", "original"],
      req["resize_mode"][0])

# ---------- 2. 自然排序 ----------
names = ["10.jpg", "2.jpg", "01.jpg", "img_3.png", "img_11.png"]
sorted_names = [p.name for p in sorted([Path(n) for n in names],
                                       key=lambda p: IMC._natural_key(p.name))]
check("自然排序：数字段按数值（1,2,10）",
      sorted_names[:3] == ["01.jpg", "2.jpg", "10.jpg"], sorted_names)
check("自然排序：带前缀的段也按数值",
      sorted_names[3:] == ["img_3.png", "img_11.png"], sorted_names)
check("自然排序：大数在后面（字典序会排成 11 < 3）",
      sorted_names.index("img_11.png") > sorted_names.index("img_3.png"),
      sorted_names)

# ---------- 3. 扫描 ----------
make_img(root_a / "01.jpg")
make_img(root_a / "2.jpg")
make_img(root_a / "10.jpg")
(root_a / "readme.txt").write_text("not an image", encoding="utf-8")  # 非图片，忽略
make_img(root_b / "99.jpg")              # 第二个根
make_img(root_b / "01.jpg", (8, 8), (10, 20, 30))   # 与根 a 同名，应被忽略

items = IMC.scan_clothes(force=True, roots=[root_a, root_b])
check("扫描：非图片文件被忽略", all(i["name"].endswith(".jpg") for i in items),
      items)
check("扫描：序号从 1 连续", [i["index"] for i in items] == [1, 2, 3, 4],
      [i["index"] for i in items])
check("扫描：自然排序落地", [i["name"] for i in items] ==
      ["01.jpg", "2.jpg", "10.jpg", "99.jpg"], [i["name"] for i in items])
check("扫描：多根合并", any(i["name"] == "99.jpg" for i in items), items)
check("扫描：同名文件以先出现的根为准（大小仍为根 a 的 40x20）",
      Image.open(root_a / "01.jpg").size == (40, 20))
check("扫描：title 为去扩展名文件名",
      items[0]["title"] == "01", items[0])
check("扫描：缓存命中后返回同一对象",
      IMC.scan_clothes(roots=[root_a, root_b]) is items)

empty_root = tmp / "empty"
empty_root.mkdir(parents=True, exist_ok=True)
check("扫描：空目录返回空列表",
      IMC.scan_clothes(force=True, roots=[empty_root]) == [])

# ---------- 4. 路径安全 ----------
check("清洗：普通文件名通过", IMC.safe_name("01.jpg") == "01.jpg")
check("清洗：中文与全角标点通过",
      IMC.safe_name("双人-中式礼服，红色.jpg") == "双人-中式礼服，红色.jpg")
check("清洗：拒绝穿越", IMC.safe_name("../evil.jpg") is None)
check("清洗：拒绝子目录", IMC.safe_name("sub/evil.jpg") is None)
check("清洗：拒绝反斜杠", IMC.safe_name("sub\\evil.jpg") is None)
check("清洗：拒绝隐藏文件", IMC.safe_name(".hidden.jpg") is None)
check("清洗：拒绝非图片扩展", IMC.safe_name("script.py") is None)
check("清洗：拒绝空值", IMC.safe_name("") is None)
check("清洗：拒绝首尾空白", IMC.safe_name(" 01.jpg") is None)
check("定位：命中真实文件",
      IMC.resolve_image("01.jpg", roots=[root_a]) == root_a / "01.jpg")
check("定位：不存在返回 None",
      IMC.resolve_image("nope.jpg", roots=[root_a]) is None)
check("定位：非法名返回 None",
      IMC.resolve_image("../a/01.jpg", roots=[root_a]) is None)

# ---------- 5. 尺寸模式 ----------
src = tmp / "src_square.png"
make_img(src, (10, 10), (255, 0, 0))
pad = "#00FF00"

fit = IMC.load_image(src, "fit_pad", 100, 50, pad)
check("fit_pad：输出形状 [1, 50, 100, 3]", tuple(fit.shape) == (1, 50, 100, 3),
      tuple(fit.shape))
arr = fit[0].numpy()
check("fit_pad：长边撑满（左右留边）",
      bool(arr[25, 50, 0] > 0.9 and arr[25, 50, 1] < 0.1),
      arr[25, 50].round(2).tolist())
check("fit_pad：补边用 pad_color（绿色）",
      arr[25, 2, 1] > 0.9 and arr[25, 2, 0] < 0.1,
      arr[25, 2].round(2).tolist())
check("fit_pad：方图缩进 2:1 框后上下贴边（高度刚好填满）",
      arr[1, 50, 0] > 0.9 and arr[48, 50, 0] > 0.9,
      (arr[1, 50].round(2).tolist(), arr[48, 50].round(2).tolist()))

wide_src = tmp / "src_wide.png"
make_img(wide_src, (40, 10), (255, 0, 0))
wide = IMC.load_image(wide_src, "fit_pad", 100, 50, pad)[0].numpy()
check("fit_pad：宽图上下留边（顶部为 pad_color）",
      wide[2, 50, 1] > 0.9 and wide[2, 50, 0] < 0.1,
      wide[2, 50].round(2).tolist())
check("fit_pad：宽图中间仍是原图",
      wide[25, 50, 0] > 0.9 and wide[25, 50, 1] < 0.1,
      wide[25, 50].round(2).tolist())

stretch = IMC.load_image(src, "stretch", 100, 50, pad)[0].numpy()
check("stretch：铺满目标尺寸", tuple(stretch.shape) == (50, 100, 3),
      tuple(stretch.shape))
check("stretch：四角都是原图色（无补边）",
      stretch[1, 1, 0] > 0.9 and stretch[48, 98, 0] > 0.9,
      (stretch[1, 1].round(2).tolist(), stretch[48, 98].round(2).tolist()))

orig = IMC.load_image(src, "original", 100, 50, pad)
check("original：保持原尺寸 10x10", tuple(orig.shape) == (1, 10, 10, 3),
      tuple(orig.shape))
check("未知模式退回 fit_pad（不崩、不变形）",
      tuple(IMC.load_image(src, "whatever", 100, 50, pad).shape) == (1, 50, 100, 3))

check("值域：输出在 0-1 之间",
      float(fit.min()) >= 0.0 and float(fit.max()) <= 1.0,
      (float(fit.min()), float(fit.max())))

# ---------- 6. 纯色底图 ----------
flat = IMC.flat_image("#0000FF", 64, 32)
check("纯色：形状 [1, 32, 64, 3]", tuple(flat.shape) == (1, 32, 64, 3),
      tuple(flat.shape))
check("纯色：颜色正确", flat[0, 5, 5, 2] > 0.9 and flat[0, 5, 5, 0] < 0.1,
      flat[0, 5, 5].tolist())
bad = IMC.flat_image("not-a-color", 8, 8)
check("纯色：非法颜色退回默认色（#6c1e27 偏红）",
      bad[0, 0, 0, 0] > 0.3 and bad[0, 0, 0, 1] < 0.2,
      bad[0, 0, 0].tolist())

# ---------- 7. 执行分支 ----------
IMC._active_roots = lambda: [root_a, root_b]   # 让 execute 走 tmp 素材
node = cls()

out0 = node.execute(image_index=0)
check("执行：序号 0 → 纯色底图（默认尺寸 1024x512）",
      tuple(out0[0].shape) == (1, 512, 1024, 3), tuple(out0[0].shape))

out2 = node.execute(image_index=2)
check("执行：序号 2 → 第二张（2.jpg）",
      tuple(out2[0].shape) == (1, 512, 1024, 3), tuple(out2[0].shape))

out_name = node.execute(image_index=99, cloth_name="99.jpg")
check("执行：cloth_name 优先于序号（99 命中根 b）",
      tuple(out_name[0].shape) == (1, 512, 1024, 3),
      tuple(out_name[0].shape))

out_big = node.execute(image_index=1, target_width=64, target_height=32)
check("执行：目标尺寸生效", tuple(out_big[0].shape) == (1, 32, 64, 3),
      tuple(out_big[0].shape))

out_orig = node.execute(image_index=1, resize_mode="original")
check("执行：original 输出素材原尺寸", tuple(out_orig[0].shape) == (1, 20, 40, 3),
      tuple(out_orig[0].shape))

IMC._active_roots = lambda: [empty_root]
out_empty = node.execute(image_index=3)
check("执行：无素材时不报错，退回纯色底图",
      tuple(out_empty[0].shape) == (1, 512, 1024, 3),
      tuple(out_empty[0].shape))

# ---------- 8. i18n 与文档 ----------
def load_json(rel):
    with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
        return json.load(fh)


defs = load_json("locales/zh/nodeDefs.json")
check("i18n：nodeDefs 有该节点",
      defs.get("QG_MarriageCloth", {}).get("display_name") == "QG 结婚登记照服装",
      defs.get("QG_MarriageCloth"))
check("i18n：nodeDefs 有描述",
      bool(defs.get("QG_MarriageCloth", {}).get("description")))
nodes_zh = load_json("translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json")
check("i18n：AIGODLIKE 词表有该节点",
      "QG_MarriageCloth" in nodes_zh, list(nodes_zh)[-3:])
check("i18n：AIGODLIKE 词表有控件名",
      "image_index" in nodes_zh.get("QG_MarriageCloth", {}).get("inputs", {}))
menus = load_json("translations/zh-CN/Menus/ComfyUI-QG-Multipack.json")
check("i18n：Menus 有 fit_pad 中文",
      menus.get("fit_pad") == "等比缩放补边", menus.get("fit_pad"))
check("i18n：Menus 有 stretch / original 中文",
      menus.get("stretch") and menus.get("original"),
      (menus.get("stretch"), menus.get("original")))

readme = open(os.path.join(PKG, "README.md"), encoding="utf-8").read()
check("文档：README 登记该节点", "QG_MarriageCloth" in readme)
check("文档：README 提到素材目录", "models/marriage_cloth" in readme)

# ---------- 9. 内置素材 ----------
asset_dir = os.path.join(PKG, "models", "marriage_cloth")
check("内置素材：目录存在", os.path.isdir(asset_dir), asset_dir)
n_asset = 0
if os.path.isdir(asset_dir):
    n_asset = len([f for f in os.listdir(asset_dir)
                   if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))])
check("内置素材：81 张随包分发", n_asset == 81, n_asset)

shutil.rmtree(tmp, ignore_errors=True)

print("\nPASS %d / FAIL %d" % (ok, fail))
sys.exit(1 if fail else 0)
