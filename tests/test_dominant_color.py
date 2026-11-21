# -*- coding: utf-8 -*-
"""QG_DominantColor 节点级测试：契约 / 颜色统计语义 / i18n 同步 / README 登记。

不依赖 ComfyUI 运行时、真实模型、网络、API Key，也不依赖 GPL 参考源码。
运行：python_embeded\\python.exe tests\\test_dominant_color.py
"""
import json
import os
import re
import sys

import numpy as np
import torch

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PKG)

# 该模块是包根平铺文件，用相对导入的兄弟模块时须当包加载；这里它不 import
# 兄弟模块，直接按文件加载即可（与其它颜色节点测试同一套路）。
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "qg_dominant_color_under_test", os.path.join(PKG, "qg_dominant_color.py"))
C = importlib.util.module_from_spec(_spec)
sys.modules["qg_dominant_color_under_test"] = C
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
check("注册 key 唯一且为 QG_DominantColor", list(cm) == ["QG_DominantColor"])
check("显示名是中文", dm.get("QG_DominantColor") == "QG 主色提取")

cls = cm["QG_DominantColor"]
it = cls.INPUT_TYPES()["required"]
check("必填项：image + 两个控件",
      sorted(it) == ["downsample", "image", "tolerance"])
check("image 是 IMAGE 类型", it["image"][0] == "IMAGE")
check("降采样 1-16 默认 8 滑块",
      it["downsample"][1].get("default") == 8
      and it["downsample"][1].get("min") == 1
      and it["downsample"][1].get("max") == 16
      and it["downsample"][1].get("display") == "slider")
check("容差 0-100 默认 15 滑块",
      it["tolerance"][1].get("default") == 15
      and it["tolerance"][1].get("min") == 0
      and it["tolerance"][1].get("max") == 100
      and it["tolerance"][1].get("display") == "slider")
check("单输出 STRING", cls.RETURN_TYPES == ("STRING",))
check("输出名 hex", cls.RETURN_NAMES == ("hex",))
check("FUNCTION 指向存在的方法",
      cls.FUNCTION == "extract" and callable(getattr(cls, "extract", None)))
check("CATEGORY=QG 工具", cls.CATEGORY == "QG 工具")
check("DESCRIPTION 为英文", not re.search(r"[\u4e00-\u9fff]", cls.DESCRIPTION))

print()
print("== [2] 单帧颜色处理 ==")
rgb = C._frame_to_rgb_uint8
f = rgb(np.full((2, 2, 3), 0.5, dtype=np.float32))
check("float 0-1 放大为 uint8", f.dtype == np.uint8 and f[0, 0, 0] == 127)
check("uint8 输入直通不放大",
      rgb(np.full((2, 2, 3), 128, dtype=np.uint8))[0, 0, 0] == 128)
rgba = np.zeros((1, 1, 4), dtype=np.float32)
rgba[0, 0] = [1.0, 0.0, 0.0, 0.5]
check("4 通道按 alpha 预乘", rgb(rgba)[0, 0, 0] == 127
      and rgb(rgba)[0, 0, 1] == 0)
gray = rgb(np.full((2, 2, 1), 0.5, dtype=np.float32))
check("1 通道复制成 3 通道",
      gray.shape == (2, 2, 3) and gray[0, 0, 2] == 127)
bad = np.zeros((2, 2, 5), dtype=np.float32)
try:
    rgb(bad)
    five_ch = False
except ValueError:
    five_ch = True
check("5 通道报 ValueError", five_ch)
try:
    rgb(np.zeros((2, 2), dtype=np.float32))
    bad_shape = False
except ValueError:
    bad_shape = True
check("非 3 维输入报 ValueError", bad_shape)

print()
print("== [3] 降采样 ==")
ds = C._downsample
check("系数 1 不缩放", ds(np.zeros((20, 30, 3), np.uint8), 1).shape == (20, 30, 3))
check("系数 4 尺寸为 //4", ds(np.zeros((20, 30, 3), np.uint8), 4).shape == (5, 7, 3))
check("宽高下限 4", ds(np.zeros((2, 2, 3), np.uint8), 8).shape == (4, 4, 3))
solid = np.full((100, 100, 3), 40, dtype=np.uint8)
check("纯色缩小后仍是纯色",
      ds(solid, 8).shape == (12, 12, 3) and int(ds(solid, 8).max()) == 40)

print()
print("== [4] 极端色过滤 ==")
drop = C._drop_extreme_colors
px = np.array([[10, 10, 10], [100, 100, 100], [250, 250, 250]], dtype=np.uint8)
kept = drop(px)
check("黑边白边剔除", kept.shape == (1, 3) and int(kept[0, 0]) == 100)
all_extreme = np.array([[5, 5, 5], [250, 250, 250]], dtype=np.uint8)
check("全被剔时回退全部像素", drop(all_extreme).shape == (2, 3))
edge = np.array([[15, 15, 15], [240, 240, 240]], dtype=np.uint8)
check("边界值 15/240 保留", drop(edge).shape == (2, 3))

print()
print("== [5] 分桶统计 ==")
q = C._quantized_dominant
color, count = q(np.array([[200, 10, 10], [196, 14, 8]], dtype=np.uint8), 15)
check("容差量化归同一桶", color == (195, 0, 0) and count == 2)
check("容差 0 逐原色统计",
      q(np.array([[1, 2, 3]], dtype=np.uint8), 0)[0] == (1, 2, 3))
tie = np.array([[10, 200, 10], [100, 10, 10]], dtype=np.uint8)
check("频次并列取亮度更高的桶", q(tie, 0)[0] == (10, 200, 10))
major = np.array([[10, 200, 10]] * 3 + [[100, 10, 10]], dtype=np.uint8)
check("频次优先于亮度", q(major, 0)[0] == (10, 200, 10) and q(major, 0)[1] == 3)
color255, _ = q(np.full((5, 3), 255, dtype=np.uint8), 100)
check("255 // 100 * 100 不溢出", color255 == (200, 200, 200))

print()
print("== [6] 节点整链路 ==")
node = cls()


def extract_arr(arr, **kwargs):
    kwargs.setdefault("downsample", 8)
    kwargs.setdefault("tolerance", 15)
    tensor = torch.from_numpy(arr.astype(np.float32) / 255.0)[None,]
    return node.extract(tensor, **kwargs)[0]


check("纯红图出 #FF0000",
      extract_arr(np.full((16, 16, 3), [255, 0, 0], dtype=np.uint8)) == "#FF0000")
check("纯色 200 量化到 #C30000",
      extract_arr(np.full((16, 16, 3), [200, 0, 0], dtype=np.uint8),
                  tolerance=15) == "#C30000")
check("容差 0 精确原色",
      extract_arr(np.full((16, 16, 3), [200, 0, 0], dtype=np.uint8),
                  tolerance=0) == "#C80000")
# 黑边白边被滤掉：主色由中间区域决定（64 格图：16 黑 / 32 主体 / 16 白，
# 降采样 8 后每行恰好整行黑或整行主体，LANCZOS 不跨区混合）
bordered = np.zeros((64, 64, 3), dtype=np.uint8)
bordered[:16] = 0            # 黑边
bordered[-16:] = 255         # 白边
bordered[16:-16] = [180, 60, 30]
check("黑边白边被滤掉取主体色", extract_arr(bordered) == "#B43C1E")
# batch 只取第一帧
batch = np.stack([
    np.full((8, 8, 3), [255, 0, 0], dtype=np.uint8),
    np.full((8, 8, 3), [0, 255, 0], dtype=np.uint8)])
check("batch 只统计第一帧",
      node.extract(torch.from_numpy(batch.astype(np.float32) / 255.0),
                   downsample=8, tolerance=15)[0] == "#FF0000")
check("downsample 越界钳制不崩且全黑图回退统计",
      node.extract(torch.zeros(1, 8, 8, 3), downsample=999, tolerance=15)[0]
      == "#000000")
check("容差越界钳制不崩",
      node.extract(torch.full((1, 8, 8, 3), 0.5), downsample=8, tolerance=-5)[0]
      == "#7F7F7F")
check("输出格式为 #RRGGBB",
      re.fullmatch(r"#[0-9A-F]{6}",
                   extract_arr(np.full((4, 4, 3), 120, dtype=np.uint8))) is not None)

print()
print("== [7] i18n 两份词表同步 ==")
nd_path = os.path.join(PKG, "locales", "zh", "nodeDefs.json")
tr_path = os.path.join(PKG, "translations", "zh-CN", "Nodes",
                       "ComfyUI-QG-Multipack.json")
nd = json.load(open(nd_path, encoding="utf-8"))
tr = json.load(open(tr_path, encoding="utf-8"))
check("nodeDefs 共 33 个节点", len(nd) == 33, "实际 %d" % len(nd))
check("translations 共 33 个节点", len(tr) == 33, "实际 %d" % len(tr))
check("两份 key 完全一致", sorted(nd) == sorted(tr))
entry = nd.get("QG_DominantColor")
check("nodeDefs 条目存在且显示名正确",
      entry and entry.get("display_name") == "QG 主色提取")
check("nodeDefs 三个输入都在",
      entry and sorted(entry.get("inputs", {})) == ["downsample", "image", "tolerance"])
check("nodeDefs 输出主色 HEX",
      entry and entry.get("outputs", {}).get("0", {}).get("name") == "主色 HEX")
t_entry = tr.get("QG_DominantColor")
check("translations 条目 title 一致",
      t_entry and t_entry.get("title") == "QG 主色提取")
check("translations 控件汉化",
      t_entry and t_entry.get("inputs", {}).get("downsample") == "降采样系数"
      and t_entry.get("widgets", {}).get("tolerance") == "颜色容差")
check("translations 输出汉化",
      t_entry and t_entry.get("outputs", {}).get("hex") == "主色 HEX")
check("控件英文名保持英文（存档稳定）",
      "downsample" in entry.get("inputs", {})
      and "tolerance" in entry.get("inputs", {}))

print()
print("== [8] README 登记 ==")
readme = read("README.md")
check("一览表有行", "| `QG_DominantColor` | QG 主色提取 |" in readme)
check("覆盖节点数与包内一致", "覆盖全部 33 个节点" in readme)
check("原创表有行", "| `QG_DominantColor` | ✅ 原创（参照规格） |" in readme)
check("概括句与包内一致", "33 个节点里 32 个" in readme)
check("新章节存在", "### `QG_DominantColor` 主色提取" in readme)
check("章节注明参照来源", "孤海-主色提取" in readme)
check("章节说明多版本兼容未照搬", "未照搬" in readme)

print()
print("TOTAL ok=%d fail=%d" % (ok, fail))
sys.exit(1 if fail else 0)
