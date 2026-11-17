# -*- coding: utf-8 -*-
"""纸型尺寸预设 + 调色盘接入的静态测试（纯前端改动，零后端契约变更）。

- web/qg_sheet_size_preset.js：给 QG_PhotoSheet / QG_MultiPhotoSheet 注入
  serialize:false 的「常用尺寸」下拉，选中填 paper_w/paper_h/dpi。
- web/qg_color_picker.js：COLOR_WIDGETS 增加 QG_MultiPhotoSheet 两色控件。

运行：python_embeded\\python.exe tests\\test_sheet_size_preset.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

Total = 0
Failed = 0


def check(label, ok, detail=""):
    global Total, Failed
    Total += 1
    if not ok:
        Failed += 1
    print("  %-54s %s  %s" % (label, "PASS" if ok else "FAIL",
                              detail if not ok else ""))


def read(rel):
    with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
        return fh.read()


print("== 一、纸型预设 JS ==")
js = read("web/qg_sheet_size_preset.js")
check("JS 文件存在且非空", len(js) > 500)
check("注册扩展带本包前缀",
      'name: "QG.Multipack.SheetSizePreset"' in js)
check("作用于 QG_PhotoSheet", "QG_PhotoSheet:" in js)
check("作用于 QG_MultiPhotoSheet", "QG_MultiPhotoSheet:" in js)
check("custom 哨兵值存在", 'const CUSTOM = "custom"' in js)

# 逐项核对预设表：照片排版 = 冲印纸型，多人拼版 = 办公纸型，均带 dpi。
photo_items = ["photo_5r", "photo_6r", "photo_7r", "photo_8r", "a5", "a4"]
sheet_items = ["a4", "a5", "b5", "letter", "a4_landscape"]
for key in photo_items:
    check("照片排版预设 %s" % key,
          re.search(r'"%s"\s*:\s*\{\s*w:\s*[\d.]+,\s*h:\s*[\d.]+,\s*dpi:\s*\d+' % key, js))
for key in sheet_items:
    check("多人拼版预设 %s" % key,
          re.search(r'"%s"\s*:\s*\{\s*w:\s*[\d.]+,\s*h:\s*[\d.]+,\s*dpi:\s*\d+' % key, js))

# 关键尺寸数值（防止改错纸型换算）
for frag in ['"photo_5r": { w: 12.7, h: 8.9, dpi: 350',
             '"photo_6r": { w: 15.2, h: 10.1, dpi: 350',
             '"a4": { w: 21.0, h: 29.7, dpi: 300',
             '"a4_landscape": { w: 29.7, h: 21.0, dpi: 300']:
    check("尺寸数值 %s" % frag[:22], frag in js)

check("改写三个真实控件",
      'const SIZE_WIDGETS = ["paper_w", "paper_h", "dpi"]' in js)
check("serialize:false 双重保险",
      "{ values: keys, serialize: false }" in js
      and "combo.serialize = false" in js
      and "serialize: false" in js)
check("三处生命周期 hook",
      all(k in js for k in ("onNodeCreated", "onConfigure", "nodeCreated", "setup"))
      and js.count("hookNode(this)") >= 2)
check("去重标记", "node.__qgmpSheetPreset" in js)
check("预设控件置顶显示",
      "function moveWidgetToTop" in js
      and "widgets.unshift(widget)" in js
      and "moveWidgetToTop(node, combo)" in js)
check("getOptionLabel 中英双语",
      "getOptionLabel" in js and "wantsChinese" in js
      and '"自定义尺寸"' in js and '"Custom"' in js)
check("选预设写值走标准变更路径",
      "widget.callback?." in js and "node.onWidgetChanged?.(" in js
      and "incrementVersion" in js)
check("手动改尺寸复位 custom",
      "this._qgSheetPresetApplying" in js
      and "combo.value = CUSTOM" in js
      and "SIZE_WIDGETS.includes(name)" in js)
check("防循环标记", "_qgSheetPresetApplying = true" in js
      and "_qgSheetPresetApplying = false" in js)
check("控件晚建兜底", "__qgSheetPresetRetry" in js and "setTimeout" in js)

print("== 二、色板接入 ==")
cp = read("web/qg_color_picker.js")
check("COLOR_WIDGETS 含 QG_MultiPhotoSheet",
      "QG_MultiPhotoSheet: [\"bg_color\", \"border_color\"]" in cp)
check("bg_color 面板标题存在", "bg_color: \"底色\"" in cp)
check("border_color 面板标题存在", "border_color: \"边框颜色\"" in cp)

print("== 三、文档登记 ==")
rd = read("README.md")
check("README 专章提到预设", "常用尺寸" in rd)
check("README 提到调色盘", "调色盘" in rd)
check("ISSUES 登记", "纸型" in read("ISSUES.md") or "常用尺寸" in read("ISSUES.md"))

print("\n结果：%d / %d 通过" % (Total - Failed, Total))
if Failed:
    sys.exit(1)
