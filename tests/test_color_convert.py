# -*- coding: utf-8 -*-
"""QG_ColorConvert 节点级测试：契约 / 解析转换 / 前端与文档登记。

不依赖 ComfyUI 运行时、真实模型、网络、API Key，也不依赖 GPL 参考源码。
运行：python_embeded\\python.exe tests\\test_color_convert.py
"""
import json
import os
import re
import sys

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PKG)

# 该模块没有包内相对导入，普通导入与 ComfyUI 实际加载语义一致
import qg_color_convert as C  # noqa: E402

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
cm = C.NODE_CLASS_MAPPINGS
dm = C.NODE_DISPLAY_NAME_MAPPINGS
check("注册 key 唯一且为 QG_ColorConvert", list(cm) == ["QG_ColorConvert"])
check("显示名是中文", dm.get("QG_ColorConvert") == "QG 颜色转换")

cls = cm["QG_ColorConvert"]
it = cls.INPUT_TYPES()["required"]
check("两个必填控件", sorted(it) == ["color", "format"])
check("format 值四项且含 #HEX",
      list(it["format"][0]) == ["#HEX", "HEX", "RGB", "HSL"])
check("format 默认 #HEX", it["format"][1].get("default") == "#HEX")
check("color 默认 #FFFFFF 且是 STRING",
      it["color"][0] == "STRING" and it["color"][1].get("default") == "#FFFFFF")
check("两个输出且为 STRING", cls.RETURN_TYPES == ("STRING", "STRING"))
check("输出名对齐且英文",
      cls.RETURN_NAMES == ("string", "color_control"))
check("FUNCTION 指向存在的方法",
      cls.FUNCTION == "convert" and callable(getattr(cls, "convert", None)))
check("CATEGORY=QG 工具", cls.CATEGORY == "QG 工具")
check("DESCRIPTION 为英文", not re.search(r"[\u4e00-\u9fff]", cls.DESCRIPTION))

print()
print("== [2] parse_color 多格式解析 ==")
cases = [
    ("#ffffff", (1.0, 1.0, 1.0)),
    ("#000000", (0.0, 0.0, 0.0)),
    ("#abc", (170.0 / 255.0, 187.0 / 255.0, 204.0 / 255.0)),
    ("364254", (54.0 / 255.0, 66.0 / 255.0, 84.0 / 255.0)),
    ("（255，0，128）", (1.0, 0.0, 128.0 / 255.0)),
    ("(255,0,128)", (1.0, 0.0, 128.0 / 255.0)),
    ("255, 0 , 128", (1.0, 0.0, 128.0 / 255.0)),
    ("hsl(240,100%,50%)", (1.0, 1.0, 1.0)),   # 函数式前缀不解析（与上游规格一致）
    ("240,100%,50%", (0.0, 0.0, 1.0)),
    ("0.5, 0.25, 0.75", (0.5, 0.25, 0.75)),
    ("1,0,0", (1.0 / 255.0, 0.0, 0.0)),   # RGB 整数正则先命中，与上游先序一致
    ("0,0,0", (0.0, 0.0, 0.0)),
    # 非法与越界一律回退白色
    ("red", (1.0, 1.0, 1.0)),
    ("", (1.0, 1.0, 1.0)),
    (None, (1.0, 1.0, 1.0)),
    ("256,0,0", (1.0, 1.0, 1.0)),
    ("0.5,0.5", (1.0, 1.0, 1.0)),
    ("rgb(255,0,128)", (1.0, 1.0, 1.0)),   # 函数式前缀不解析（与上游规格一致）
    ("hsl(240,100%,50%) ", (1.0, 1.0, 1.0)),
]
for raw, want in cases:
    got = C.parse_color(raw)
    check("parse_color(%r)" % raw,
          all(abs(a - b) < 1e-9 for a, b in zip(got, want)),
          "实际 %s 期望 %s" % (got, want))

print()
print("== [3] convert 四种格式输出 ==")
node = cls()
out = node.convert("#FFFFFF", "#HEX")
check("默认 #HEX 输出", out == ("#ffffff", "#ffffff"), str(out))
check("HEX 不带 #", node.convert("#FF0080", "HEX")[0] == "ff0080")
check("RGB 整数", node.convert("#FF0080", "RGB")[0] == "255,0,128")
check("HSL 百分比", node.convert("#0000FF", "HSL")[0] == "240,100%,50%")
check("颜色控件槽恒为规范化 hex",
      node.convert("(54,66,84)", "RGB")[1] == "#364254")
check("非法 format 回退 #HEX",
      node.convert("#FF0080", "bogus")[0] == "#ff0080")
check("输出全为 str", all(isinstance(v, str) for v in node.convert("x", "HSL")))
check("非法输入字符串槽回退白色",
      node.convert("not-a-color", "RGB") == ("255,255,255", "#ffffff"))
for fmt in C.FORMAT_CHOICES:
    got = node.convert("#ff0080", fmt)
    check("格式 %s 输出非空字符串" % fmt, bool(got[0]) and got[1] == "#ff0080", str(got))

print()
print("== [4] 两份 i18n 词表 ==")
a = json.loads(read("locales/zh/nodeDefs.json"))
b = json.loads(read("translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"))
ea = a.get("QG_ColorConvert", {})
eb = b.get("QG_ColorConvert", {})
check("nodeDefs 有新词条", bool(ea))
check("汉化主档有新词条", bool(eb))
check("两份标题一致", ea.get("display_name") == eb.get("title") == "QG 颜色转换")
check("两份描述一致", ea.get("description") == eb.get("description"))
check("nodeDefs outputs 用索引键", sorted(ea.get("outputs", {})) == ["0", "1"])
check("汉化主档 outputs 用槽名",
      sorted(eb.get("outputs", {})) == ["color_control", "string"])
check("nodeDefs format.options 覆盖四个值",
      sorted(ea.get("inputs", {}).get("format", {}).get("options", {}))
      == ["#HEX", "HEX", "HSL", "RGB"])
check("两份词表节点数一致（随包 31 节点）", len(a) == len(b) == 31, "%d/%d" % (len(a), len(b)))

print()
print("== [5] 前端登记与规范红线 ==")
js_new = read("web/qg_color_convert.js")
check("新前端文件存在且注册扩展名正确", 'name: "QG.ColorConvert"' in js_new)
check("锁定节点 QG_ColorConvert", "QG_ColorConvert" in js_new)
check("format 中文标签四项齐全",
      all(k in js_new for k in ('"#HEX":', '"HEX":', '"RGB":', '"HSL":')))
check("用绝对脚本路径 /scripts/app.js", 'from "/scripts/app.js"' in js_new)
check("无 .connect(/.bind( 字面量",
      not re.search(r"\.connect\(|\.bind\(", js_new))

print()
print("== [6] README 登记 ==")
rd = read("README.md")
check("一览表有条目", "| `QG_ColorConvert` | QG 颜色转换 |" in rd)
check("原创表有条目且标注参照规格", "| `QG_ColorConvert` | ✅ 原创（参照规格）" in rd)
check("有独立章节", "### `QG_ColorConvert` 颜色转换" in rd)
check("前端作用表登记新 JS", "`web/qg_color_convert.js`" in rd)
check("节点总数已更新为 28", "本节覆盖全部 31 个节点" in rd)

print()
print("合计 PASS %d / FAIL %d" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
