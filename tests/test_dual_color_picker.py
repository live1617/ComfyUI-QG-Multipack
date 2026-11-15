# -*- coding: utf-8 -*-
"""QG_DualColorPicker 节点级测试：契约 / 颜色标准化 / 前端与文档登记。

不依赖 ComfyUI 运行时、真实模型、网络、API Key，也不依赖 GPL 参考源码。
运行：python_embeded\\python.exe tests\\test_dual_color_picker.py
"""
import json
import os
import re
import sys

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PKG)

# 该模块没有包内相对导入，普通导入与 ComfyUI 实际加载语义一致
import qg_dual_color_picker as D  # noqa: E402

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


print("== [1] 节点注册契约 ==")
cm = D.NODE_CLASS_MAPPINGS
dm = D.NODE_DISPLAY_NAME_MAPPINGS
check("注册 key 唯一且为 QG_DualColorPicker", list(cm) == ["QG_DualColorPicker"])
check("显示名是中文", dm.get("QG_DualColorPicker") == "QG 双色取色器")

cls = cm["QG_DualColorPicker"]
it = cls.INPUT_TYPES()["required"]
check("三个必填控件", sorted(it) == ["mode", "primary_color", "secondary_color"])
check("mode 值全英文且三项",
      list(it["mode"][0]) == ["solid", "vertical_gradient", "radial_gradient"])
check("mode 默认 solid", it["mode"][1].get("default") == "solid")
check("主色默认 #213d50", it["primary_color"][1].get("default") == "#213d50")
check("辅色默认 #402633", it["secondary_color"][1].get("default") == "#402633")
check("颜色控件是 STRING", it["primary_color"][0] == "STRING" and it["secondary_color"][0] == "STRING")
check("三个输出", cls.RETURN_TYPES == ("STRING", "STRING", "STRING"))
check("输出名对齐且英文",
      cls.RETURN_NAMES == ("mode", "primary_color", "secondary_color"))
check("FUNCTION 指向存在的方法",
      cls.FUNCTION == "pick" and callable(getattr(cls, "pick", None)))
check("CATEGORY=QG 工具", cls.CATEGORY == "QG 工具")
check("DESCRIPTION 为英文", not re.search(r"[\u4e00-\u9fff]", cls.DESCRIPTION))

print()
print("== [2] normalize_hex ==")
cases = [
    ("#abc", "#aabbcc"), ("abc", "#aabbcc"), ("#AABBCC", "#aabbcc"),
    ("112233", "#112233"), ("#11223344", "#112233"),
    ((255, 0, 128), "#ff0080"), ((0, 300, -5), "#00ff00"),
    ([17, 34, 51], "#112233"), ("  #AbC ", "#aabbcc"),
    ("#GGGGGG", "#000000"), ("", "#000000"), (None, "#000000"),
    ((1, 2), "#000000"),
]
for raw, want in cases:
    got = D.normalize_hex(raw)
    check("normalize_hex(%r) -> %s" % (raw, want), got == want, "实际 %s" % got)
check("自定义 fallback 生效", D.normalize_hex("xyz", "#123456") == "#123456")
check("三位合法 hex 不当成非法值", D.normalize_hex("bad") == "#bbaadd")
check("元组含非数字回退 fallback",
      D.normalize_hex(("x", 2, 3), "#abcdef") == "#abcdef")

print()
print("== [3] pick 输出 ==")
node = cls()
out = node.pick("solid", "#213d50", "#402633")
check("默认三路输出", out == ("solid", "#213d50", "#402633"), str(out))
check("输出全为 str", all(isinstance(v, str) for v in out))
out2 = node.pick("radial_gradient", "#ABC", "#ff000080")
check("缩写与 8 位被规范化", out2 == ("radial_gradient", "#aabbcc", "#ff0000"), str(out2))
out3 = node.pick("bogus", "not-a-color", None)
check("非法 mode 回退 solid", out3[0] == "solid", str(out3))
check("非法色值回退默认色",
      out3[1] == "#213d50" and out3[2] == "#402633", str(out3))
for mode in D.MODE_CHOICES:
    got = node.pick(mode, "#abc", "#402633")
    check("模式 %s 输出格式合法" % mode,
          got[0] == mode and all(re.fullmatch(r"#[0-9a-f]{6}", v) for v in got[1:]),
          str(got))

print()
print("== [4] 两份 i18n 词表 ==")
a = json.loads(read("locales/zh/nodeDefs.json"))
b = json.loads(read("translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"))
ea = a.get("QG_DualColorPicker", {})
eb = b.get("QG_DualColorPicker", {})
check("nodeDefs 有新词条", bool(ea))
check("汉化主档有新词条", bool(eb))
check("两份标题一致", ea.get("display_name") == eb.get("title") == "QG 双色取色器")
check("两份描述一致", ea.get("description") == eb.get("description"))
check("nodeDefs outputs 用索引键",
      sorted(ea.get("outputs", {})) == ["0", "1", "2"])
check("汉化主档 outputs 用槽名",
      sorted(eb.get("outputs", {})) == ["mode", "primary_color", "secondary_color"])
check("nodeDefs mode.options 覆盖三个英文值",
      sorted(ea.get("inputs", {}).get("mode", {}).get("options", {}))
      == ["radial_gradient", "solid", "vertical_gradient"])
check("两份词表节点数一致", len(a) == len(b) == 27, "%d/%d" % (len(a), len(b)))

print()
print("== [5] 前端登记与规范红线 ==")
js_new = read("web/qg_dual_color_picker.js")
js_pick = read("web/qg_color_picker.js")
check("新前端文件存在且注册扩展名正确",
      'name: "QG.DualColorPicker"' in js_new)
check("模式中文标签三项齐全",
      all(k in js_new for k in ("solid:", "vertical_gradient:", "radial_gradient:")))
check("用绝对脚本路径 /scripts/app.js", 'from "/scripts/app.js"' in js_new)
check("COLOR_WIDGETS 登记了新节点", "QG_DualColorPicker:" in js_pick)
check("BANNER_TEXT 登记两个颜色控件",
      "primary_color:" in js_pick and "secondary_color:" in js_pick)
check("hookNode 按 BANNER_TEXT 选绘制函数", "BANNER_TEXT[widget.name]" in js_pick)
for label, text in (("新前端", js_new), ("取色器", js_pick)):
    check("%s 无 .connect(/.bind( 字面量" % label,
          not re.search(r"\.connect\(|\.bind\(", text))

print()
print("== [6] README 登记 ==")
rd = read("README.md")
check("一览表有条目", "| `QG_DualColorPicker` | QG 双色取色器 |" in rd)
check("原创表有条目且标注参照规格",
      "| `QG_DualColorPicker` | ✅ 原创（参照规格）" in rd)
check("有独立章节", "### `QG_DualColorPicker` 双色取色器" in rd)
check("前端作用表登记新 JS", "`web/qg_dual_color_picker.js`" in rd)
check("节点总数已更新为 27", "本节覆盖全部 27 个节点" in rd)

print()
print("合计 PASS %d / FAIL %d" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
