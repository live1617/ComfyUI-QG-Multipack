# -*- coding: utf-8 -*-
"""QG_ColorPicker 节点级测试：契约 / 与孤海源码逐字节对照 / 词表与前端登记。

对照源码走 ref_helper.require_ref，缺参考即 exit=2，不允许静默 SKIP。
运行：python_embeded\\python.exe tests\\test_color_picker.py
"""
import importlib.util
import json
import os
import re
import sys

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PKG)
sys.path.insert(0, os.path.join(PKG, "tests"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(PKG))))

import qg_color_picker as C  # noqa: E402
from ref_helper import require_ref  # noqa: E402

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
check("注册 key 唯一且为 QG_ColorPicker", list(cm) == ["QG_ColorPicker"])
check("显示名是中文", dm.get("QG_ColorPicker") == "QG 取色器")
cls = cm["QG_ColorPicker"]
it = cls.INPUT_TYPES()["required"]
check("两个必填控件", sorted(it) == ["color", "mode"])
check("color 是 STRING 且默认 #213d50",
      it["color"][0] == "STRING" and it["color"][1].get("default") == "#213d50")
check("mode 三项且默认 HEX",
      list(it["mode"][0]) == ["HEX", "RGB", "HSL"] and it["mode"][1].get("default") == "HEX")
check("两路输出均为 STRING", cls.RETURN_TYPES == ("STRING", "STRING"))
check("输出名对齐", cls.RETURN_NAMES == ("color_control", "string"))
check("FUNCTION 指向存在的方法",
      cls.FUNCTION == "pick" and callable(getattr(cls, "pick", None)))
check("CATEGORY=QG 工具", cls.CATEGORY == "QG 工具")
check("DESCRIPTION 为英文", not re.search(r"[\u4e00-\u9fff]", cls.DESCRIPTION))

print()
print("== [2] 规范化与三项格式输出 ==")
node = cls()
check("合法 6 位小写化", node.pick("#FF0080", "HEX") == ("#ff0080", "#FF0080"))
check("3 位保持 3 位、大写输出", node.pick("#aBc", "HEX") == ("#abc", "#ABC"))
check("RGB 逗号后带空格", node.pick("#FF0080", "RGB")[1] == "255, 0, 128")
check("HSL 逗号后带空格", node.pick("#0000FF", "HSL")[1] == "240, 100%, 50%")
check("非法回退默认色", node.pick("garbage", "HEX") == ("#213d50", "#213D50"))
check("无 # 前缀回退", node.pick("213d50", "HEX")[0] == "#213d50")
check("None 回退", node.pick(None, "RGB") == ("#213d50", "33, 61, 80"))
check("未知模式回退 HEX", node.pick("#FF0080", "BOGUS")[1] == "#FF0080")
check("两路都是 str", all(isinstance(v, str) for v in node.pick("#fff", "HSL")))
check("normalize_color 接受 3/6 位",
      C.normalize_color("#ABC") == "#abc" and C.normalize_color("#aabbcc") == "#aabbcc")
check("normalize_color 拒绝 8 位透明写法", C.normalize_color("#aabbccdd") == "#213d50")

print()
print("== [3] 与孤海源码逐字节对照 ==")
ref_path = require_ref("nodes", "颜色处理.py")
spec = importlib.util.spec_from_file_location("gh_color_picker_ref", ref_path)
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)
gh = ref.取色器_孤海()

# None 不在孤海规格内（其源码直接 .strip() 会抛异常），仅本包做健壮性回退，
# 已在 [2] 单独断言，不纳入逐字节对照。
colors = ["#213d50", "#abc", "#ABC", "#FF0080", "#0000FF", "#ffffff", "#000000",
          "garbage", "", "#12345", "#1234567", "ff0080", "  #F00  "]
modes = ["HEX", "RGB", "HSL"]
diff = 0
for color in colors:
    for mode in modes:
        want = gh.获取颜色(color, mode)
        got = node.pick(color, mode)
        same = got == want
        if not same:
            diff += 1
            print("  差异 color=%r mode=%s 本包=%s 孤海=%s" % (color, mode, got, want))
check("39 组颜色/模式输出与孤海完全一致", diff == 0, "差异 %d 组" % diff)
check("孤海参考类可正常实例化", gh.RETURN_TYPES == ("GHCOLOR", "STRING"))

print()
print("== [4] 两份 i18n 词表 ==")
a = json.loads(read("locales/zh/nodeDefs.json"))
b = json.loads(read("translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"))
ea = a.get("QG_ColorPicker", {})
eb = b.get("QG_ColorPicker", {})
check("nodeDefs 有新词条", bool(ea))
check("汉化主档有新词条", bool(eb))
check("两份标题一致", ea.get("display_name") == eb.get("title") == "QG 取色器")
check("两份描述一致", ea.get("description") == eb.get("description"))
check("nodeDefs outputs 用索引键", sorted(ea.get("outputs", {})) == ["0", "1"])
check("汉化主档 outputs 用槽名",
      sorted(eb.get("outputs", {})) == ["color_control", "string"])
check("两份 widgets 键是源码真实参数名",
      sorted(eb.get("widgets", {})) == ["color", "mode"])
check("模式值未做恒等翻译", "options" not in ea.get("inputs", {}).get("mode", {}))
check("两份词表节点数一致（随包 33 节点）", len(a) == len(b) == 33, "%d/%d" % (len(a), len(b)))

print()
print("== [5] 前端登记与文档 ==")
js = read("web/qg_color_picker.js")
check("取色控件登记了 QG_ColorPicker", "QG_ColorPicker: [\"color\"]" in js)
check("整块色条按节点精确限定", "BANNER_WIDGETS" in js and "QG_ColorPicker" in js.split("const BANNER_WIDGETS")[1][:120])
check("色条文案按节点判定", "bannerLabel(node, widget.name)" in js)
check("扩展名保持本包前缀", 'name: "QG.Multipack.ColorPicker"' in js)
init = read("__init__.py")
check("__init__ 注册了新模块", "import qg_color_picker as _color_picker" in init)
rd = read("README.md")
check("README 覆盖节点数已更新", "覆盖全部 33 个节点" in rd)
check("README 有新节点行", "QG_ColorPicker" in rd)
iss = read("ISSUES.md")
check("ISSUES 记录了本项", "| 139 |" in iss and "QG 取色器" in iss)

print()
print("== 结果 ==")
print("PASS %d / FAIL %d" % (ok, fail))
sys.exit(1 if fail else 0)
