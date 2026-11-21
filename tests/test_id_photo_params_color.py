# -*- coding: utf-8 -*-
"""QG_IDPhotoParams 颜色文本输出槽 + 自定义色值取色的回归测试。

覆盖：
  · 后端第 5 个输出 color_text 是 STRING，值为主背景色的标准 #rrggbb；
  · 预设名 / #RGB / 裸六位 / RGB 三元组 / 自定义空值回退都能解析；
  · 输出追加在末尾，不动既有 0-3 号槽（老工作流连线不错位）；
  · 前端把 bg_custom 注册进取色器、取色联动切 custom、空值按底色初始化；
  · 两份词表与 README 都登记了第 5 个输出。

不依赖 ComfyUI 运行时、模型、网络、API Key 或 GPL 参考源码。
运行：python_embeded\\python.exe tests\\test_id_photo_params_color.py
"""
import importlib
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

FAILED = 0
TOTAL = 0


def check(label, ok, detail=""):
    global FAILED, TOTAL
    TOTAL += 1
    if not ok:
        FAILED += 1
    print("  %-52s %s  %s" % (label, "PASS" if ok else "FAIL",
                              detail if not ok else ""))


def load_package():
    name = "qgmp_color_test"
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(PKG, "__init__.py"), submodule_search_locations=[PKG])
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[name] = pkg
    spec.loader.exec_module(pkg)
    return name


def read(rel):
    with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
        return fh.read()


def main():
    pkg = load_package()
    mod = importlib.import_module(pkg + ".id_photo_params_node")
    cls = mod.NODE_CLASS_MAPPINGS["QG_IDPhotoParams"]

    print("\n[1] 输出槽契约（追加在末尾）")
    check("注册 key 仍为 QG_IDPhotoParams",
          list(mod.NODE_CLASS_MAPPINGS) == ["QG_IDPhotoParams"])
    check("五个返回槽", len(cls.RETURN_TYPES) == 5, str(cls.RETURN_TYPES))
    check("第五槽是 STRING", cls.RETURN_TYPES[4] == "STRING")
    check("输出名 = params/width/height/dpi/color_text",
          cls.RETURN_NAMES == ("params", "width", "height", "dpi", "color_text"),
          str(cls.RETURN_NAMES))
    check("前四槽保持原样（老连线不错位）",
          cls.RETURN_TYPES[:4] == (mod.PARAM_TYPE, "INT", "INT", "INT"))
    check("五条 tooltip 齐备", len(cls.RETURN_TOOLTIPS) == 5)
    check("FUNCTION 指向 build", cls.FUNCTION == "build" and callable(cls.build))

    print("\n[2] 主色文本解析（与下游渲染同源）")
    node = cls()
    base = ["1inch", "blue", "", "darkblue", "pure", 300, 3.5, 4.9]

    def color_of(**kw):
        args = list(base)
        names = ["preset", "bg_color", "bg_custom", "bg_color_2", "render",
                 "dpi", "custom_width", "custom_height"]
        for k, v in kw.items():
            args[names.index(k)] = v
        result = node.build(*args)
        return result[4], result[0]

    text, _ = color_of()
    check("默认蓝 -> #438edb（印刷蓝非 CSS 蓝）", text == "#438edb", text)
    for name, expect in [("white", "#ffffff"), ("darkblue", "#1b4b8f"),
                         ("red", "#d93b3b"), ("gray", "#9a9a9a"),
                         ("lightblue", "#a8c8e8")]:
        text, _ = color_of(bg_color=name)
        check("预设 %s -> %s" % (name, expect), text == expect, text)

    for typed, expect in [("#abc", "#aabbcc"), ("438edb", "#438edb"),
                          ("#1B4B8F", "#1b4b8f"), ("200,30,40", "#c81e28"),
                          ("", "#438edb")]:
        text, _ = color_of(bg_color="custom", bg_custom=typed)
        check("自定义 %r -> %s" % (typed, expect), text == expect, text)

    text, params = color_of(bg_color="custom", bg_custom="#abc")
    check("color_text 与渲染用的色同源",
          params["bg_color"] == "#abc" and text == "#aabbcc")
    check("格式恒为 # + 六位小写",
          all(len(color_of(bg_color=c)[0]) == 7
              and color_of(bg_color=c)[0].startswith("#")
              and color_of(bg_color=c)[0][1:].islower()
              for c in ["white", "blue", "red", "darkblue"]))
    check("渐变也只取第一色",
          color_of(bg_color="blue", bg_color_2="red", render="radial")[0] == "#438edb")

    print("\n[3] 前端取色器登记")
    js = read("web/qg_color_picker.js")
    check("bg_custom 注册进取色器", "QG_IDPhotoParams: [\"bg_custom\"]" in js)
    check("有取色联动下拉表", "LINKED_COMBO" in js)
    check("联动到 bg_color=custom",
          'QG_IDPhotoParams: { bg_custom: ["bg_color", "custom"] }' in js)
    check("空值按背景色初始化", "seedFromCombo" in js and "ID_PHOTO_BG_HEX" in js)
    check("证件照底色表与后端一致（印刷蓝）", 'blue: "#438edb"' in js)
    check("面板标题按控件取而非写死",
          "PANEL_TITLE" in js and "PANEL_TITLE[widget?.name]" in js
          and "<span class=\"qgcp-title\">描边颜色</span>" not in js)
    check("applyColor 调用了联动", "applyLinkedCombo(node, widget)" in js)

    print("\n[3b] 全包取色器覆盖（13 节点 / 17 控件）")
    # 从 COLOR_WIDGETS 字面量里解析出注册项，与预期清单逐一核对。
    block = js.split("const COLOR_WIDGETS = {", 1)[1].split("};", 1)[0]
    import re as _re
    registered = _re.findall(r'(\w+):\s*\[([^\]]+)\]', block)
    got = {k: _re.findall(r'"([^"]+)"', v) for k, v in registered}
    expect = {
        "QG_BiRefNet": ["background_color"],
        "QG_DualColorPicker": ["primary_color", "secondary_color"],
        "QG_CustomColor": ["color1", "color2"],
        "QG_FaceAlign": ["custom_fill_color"],
        "QG_IDPhotoParams": ["bg_custom"],
        "QG_IDPhotoCrop": ["fill_color"],
        "QG_PhotoSheetMixed": ["border_color"],
        "QG_IDCardSheet": ["bg_color"],
        "QG_MarriageCloth": ["pad_color"],
        "QG_Watermark": ["color"],
        "QG_ColorPicker": ["color"],
        "QG_MultiPhotoSheet": ["bg_color", "border_color"],
        "QG_ImageMaskPreview": ["mask_color", "index_color"],
    }
    check("取色器注册 13 个节点", len(got) == 13, str(sorted(got)))
    check("取色器注册清单与预期完全一致", got == expect, str(got))
    check("注册 17 个颜色控件", sum(len(v) for v in got.values()) == 17)
    check("每控件都有面板标题",
          all(c in js.split("const PANEL_TITLE = {", 1)[1].split("};", 1)[0]
              for v in expect.values() for c in v))
    check("颜色转换节点不套色板（多格式输入）", "QG_ColorConvert:" not in block)

    print("\n[3c] 非 hex 写法的数据破坏防护")
    check("有 isHexColor 判定", "function isHexColor" in js)
    check("hook 只规范化 hex、非 hex 原样保留",
          "if (isHexColor(widget.value))" in js
          and "\n            widget.value = normHex(widget.value);" in js)
    check("applyColor 兜底不再依赖 widget.value",
          "normHex(raw, FALLBACK)" in js and "normHex(raw, normHex(widget.value))" not in js)
    # 用 JS 同一套正则在 Python 侧复现，确认 white / RGB 元组 / 灰度不会被误认成 hex。
    def is_hex(v):
        import re
        t = str(v).strip().lstrip("#")
        return bool(re.fullmatch(r"[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8}", t))
    for safe in ["white", "red", "128,128,128", "0.5", "gray", "lightblue"]:
        check("%r 不会被当 hex 改写" % safe, not is_hex(safe))
    for hx in ["#abc", "438edb", "#1B4B8F", "#ffffff80"]:
        check("%r 判为合法 hex" % hx, is_hex(hx))

    print("\n[4] 词表与文档")
    nd = json.loads(read("locales/zh/nodeDefs.json"))
    tr = json.loads(read("translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"))
    check("nodeDefs 第四号后新增 4 号输出",
          sorted(nd["QG_IDPhotoParams"]["outputs"]) == ["0", "1", "2", "3", "4"])
    check("nodeDefs 输出名=主色",
          nd["QG_IDPhotoParams"]["outputs"]["4"]["name"] == "主色")
    check("汉化词表输出含 color_text",
          tr["QG_IDPhotoParams"]["outputs"].get("color_text") == "主色")
    check("两份词表节点数一致", len(nd) == len(tr), "%d/%d" % (len(nd), len(tr)))
    rd = read("README.md")
    check("README 一览表登记主色",
          "`DPI` / `主色`" in rd)
    check("README 专章说明取色自动切自定义",
          "取完会自动把「背景颜色」切到「自定义」" in rd)

    print("\n== 合计 %d 项，FAIL %d ==" % (TOTAL, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
