# -*- coding: utf-8 -*-
"""QG_CustomColor 节点级测试：契约 / 三种模式渲染语义 / 前端与文档登记。

不依赖 ComfyUI 运行时、真实模型、网络、API Key，也不依赖 GPL 参考源码。
运行：python_embeded\\python.exe tests\\test_custom_color.py
"""
import json
import os
import re
import sys

import numpy as np

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PKG)

# 该模块用相对导入（from .qg_dual_color_picker import ...），须当包加载
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "qg_custom_color_under_test", os.path.join(PKG, "qg_custom_color.py"),
    submodule_search_locations=[PKG])
C = importlib.util.module_from_spec(_spec)
sys.modules["qg_custom_color_under_test"] = C
_spec.loader.exec_module(C)

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
check("注册 key 唯一且为 QG_CustomColor", list(cm) == ["QG_CustomColor"])
check("显示名是中文", dm.get("QG_CustomColor") == "QG 自定义颜色")

cls = cm["QG_CustomColor"]
it = cls.INPUT_TYPES()["required"]
check("七个必填控件",
      sorted(it) == ["color1", "color2", "grain", "height", "mode", "scale", "width"])
check("mode 值英文三项",
      list(it["mode"][0]) == ["solid", "vertical_gradient", "radial_gradient"])
check("mode 默认 solid", it["mode"][1].get("default") == "solid")
check("宽高默认 512 且范围 1-8192",
      it["width"][1].get("default") == 512 and it["width"][1].get("min") == 1
      and it["width"][1].get("max") == 8192
      and it["height"][1].get("max") == 8192)
check("颜色默认值",
      it["color1"][1].get("default") == "#364254"
      and it["color2"][1].get("default") == "#4C3843")
check("颜色控件是 STRING",
      it["color1"][0] == "STRING" and it["color2"][0] == "STRING")
check("缩放 0-300 默认 100",
      it["scale"][1].get("default") == 100 and it["scale"][1].get("min") == 0
      and it["scale"][1].get("max") == 300)
check("颗粒 0-100 默认 0",
      it["grain"][1].get("default") == 0 and it["grain"][1].get("min") == 0
      and it["grain"][1].get("max") == 100)
check("单输出 IMAGE", cls.RETURN_TYPES == ("IMAGE",))
check("输出名英文", cls.RETURN_NAMES == ("image",))
check("FUNCTION 指向存在的方法",
      cls.FUNCTION == "render" and callable(getattr(cls, "render", None)))
check("CATEGORY=QG 工具", cls.CATEGORY == "QG 工具")
check("DESCRIPTION 为英文", not re.search(r"[\u4e00-\u9fff]", cls.DESCRIPTION))

print()
print("== [2] 三种模式渲染语义 ==")
node = cls()
C1 = np.array([0x36, 0x42, 0x54], dtype=np.float32) / 255.0
C2 = np.array([0x4C, 0x38, 0x43], dtype=np.float32) / 255.0

img = node.render(4, 3, "solid", "#364254", "#4C3843", 100, 0)[0]
check("输出形状 [1,3,4,3]", tuple(img.shape) == (1, 3, 4, 3), str(tuple(img.shape)))
check("纯色整图=颜色1",
      np.allclose(img[0].numpy(), np.ones((3, 4, 3), np.float32) * C1, atol=1e-6))

img = node.render(2, 11, "vertical_gradient", "#000000", "#ffffff", 100, 0)[0]
arr = img[0].numpy()
check("渐变顶部=颜色1(黑)", abs(arr[0, 0, 0]) < 0.02, str(arr[0, 0, 0]))
check("渐变底部=颜色2(白)", abs(arr[-1, 0, 0] - 1.0) < 0.02, str(arr[-1, 0, 0]))
check("逐行常量（宽度方向相同）", bool((arr[:, 0, :] == arr[:, 1, :]).all()))
check("单调递增", bool((np.diff(arr[:, 0, 0]) >= 0).all()))

# 缩放语义：>100 提前完成（钳制在颜色区间内）
img = node.render(1, 10, "vertical_gradient", "#000000", "#ffffff", 200, 0)[0]
arr = img[0].numpy()
check("缩放 200 时 y=0.6 已到颜色2", arr[6, 0, 0] == 1.0, str(arr[6, 0, 0]))
# 缩放 <100 推进更慢（底部只完成一半）
img = node.render(1, 10, "vertical_gradient", "#000000", "#ffffff", 50, 0)[0]
check("缩放 50 底部只推进一半", abs(img[0, -1, 0, 0].item() - 0.5) < 0.02,
      str(img[0, -1, 0, 0].item()))
# 缩放 0 退化为正常渐变
img = node.render(1, 10, "vertical_gradient", "#000000", "#ffffff", 0, 0)[0]
check("缩放 0 退化正常渐变（底部=颜色2）",
      abs(img[0, -1, 0, 0].item() - 1.0) < 0.02, str(img[0, -1, 0, 0].item()))

# 中心渐变（与上游公式一致）：中心=颜色2，边缘=颜色1
img = node.render(11, 11, "radial_gradient", "#000000", "#ffffff", 100, 0)[0]
arr = img[0].numpy()
check("中心渐变中心=颜色2(白)", arr[5, 5, 0] > 0.95, str(arr[5, 5, 0]))
# 11x11 的角点距离(7.07) < 渐变最大半径(对角线一半 7.78)，到不了纯颜色1
check("中心渐变角落趋近颜色1(黑)",
      abs(arr[0, 0, 0] - (1.0 - 7.0710678 / 7.7772073)) < 0.01, str(arr[0, 0, 0]))
# 缩放 0 → 半径 0 → 全图颜色1
img = node.render(5, 5, "radial_gradient", "#000000", "#ffffff", 0, 0)[0]
check("中心渐变缩放 0 全图=颜色1(黑)",
      float(img[0].numpy().max()) < 0.05, "%.4f" % float(img[0].numpy().max()))

print()
print("== [3] 颗粒与兜底 ==")
img = node.render(200, 200, "solid", "#808080", "#808080", 100, 50)[0]
arr = img[0].numpy()
check("颗粒输出范围 0-1", arr.min() >= 0.0 and arr.max() <= 1.0)
check("颗粒均值仍接近原色", abs(arr.mean() - 128 / 255) < 0.05, "%.4f" % arr.mean())
check("颗粒非恒定（有噪声）", float(arr.std()) > 0.01, "%.4f" % arr.std())
img = node.render(4, 4, "solid", "#808080", "#808080", 100, 0)[0]
check("颗粒 0 输出恒定", float(img[0].numpy().std()) == 0.0)

img = node.render(2, 2, "solid", "xyz", "#4C3843", 100, 0)[0]
check("非法颜色1回退默认 #364254",
      np.allclose(img[0, 0, 0].numpy(), C1, atol=1e-6))
img = node.render(2, 2, "bogus", "#364254", "#4C3843", 100, 0)[0]
check("非法 mode 回退 solid", bool((img[0, 0, 0] == img[0, 1, 1]).all()))
img = node.render(99999, 0, "solid", "#364254", "#4C3843", 100, 0)[0]
check("尺寸钳制到 [1, 8192]", tuple(img.shape) == (1, 1, 8192, 3), str(tuple(img.shape)))
img = node.render(3, 2, "solid", "#364254", None, 100, 0)[0]
check("None 颜色2 不崩（回退默认）", tuple(img.shape) == (1, 2, 3, 3))

print()
print("== [4] 两份 i18n 词表 ==")
a = json.loads(read("locales/zh/nodeDefs.json"))
b = json.loads(read("translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"))
ea = a.get("QG_CustomColor", {})
eb = b.get("QG_CustomColor", {})
check("nodeDefs 有新词条", bool(ea))
check("汉化主档有新词条", bool(eb))
check("两份标题一致", ea.get("display_name") == eb.get("title") == "QG 自定义颜色")
check("两份描述一致", ea.get("description") == eb.get("description"))
check("nodeDefs outputs 用索引键", sorted(ea.get("outputs", {})) == ["0"])
check("汉化主档 outputs 用槽名", sorted(eb.get("outputs", {})) == ["image"])
check("nodeDefs mode.options 覆盖三个英文值",
      sorted(ea.get("inputs", {}).get("mode", {}).get("options", {}))
      == ["radial_gradient", "solid", "vertical_gradient"])
check("两份词表节点数一致（随包 34 节点）", len(a) == len(b) == 34, "%d/%d" % (len(a), len(b)))

print()
print("== [5] 前端登记与规范红线 ==")
js_new = read("web/qg_custom_color.js")
js_pick = read("web/qg_color_picker.js")
check("新前端文件存在且注册扩展名正确", 'name: "QG.CustomColor"' in js_new)
check("锁定节点 QG_CustomColor", "QG_CustomColor" in js_new)
check("模式中文标签三项齐全",
      all(k in js_new for k in ("solid:", "vertical_gradient:", "radial_gradient:")))
check("用绝对脚本路径 /scripts/app.js", 'from "/scripts/app.js"' in js_new)
check("COLOR_WIDGETS 登记新节点两控件",
      "QG_CustomColor: [\"color1\", \"color2\"]" in js_pick)
check("BANNER_TEXT 登记颜色1/颜色2",
      "color1:" in js_pick and "color2:" in js_pick)
for label, text in (("新前端", js_new), ("取色器", js_pick)):
    check("%s 无 .connect(/.bind( 字面量" % label,
          not re.search(r"\.connect\(|\.bind\(", text))

print()
print("== [6] README 登记 ==")
rd = read("README.md")
check("一览表有条目", "| `QG_CustomColor` | QG 自定义颜色 |" in rd)
check("原创表有条目且标注参照规格", "| `QG_CustomColor` | ✅ 原创（参照规格）" in rd)
check("有独立章节", "### `QG_CustomColor` 自定义颜色" in rd)
check("前端作用表登记新 JS", "`web/qg_custom_color.js`" in rd)
check("节点总数已更新为 28", "本节覆盖全部 34 个节点" in rd)

print()
print("合计 PASS %d / FAIL %d" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
