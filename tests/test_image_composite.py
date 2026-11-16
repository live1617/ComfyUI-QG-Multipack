# -*- coding: utf-8 -*-
"""QG_ImageComposite 图像合成节点测试。

规格对齐 ComfyUI_essentials 的 ``ImageComposite+``，本包是独立实现。测试重点
放在**上游实现会出错的地方**，避免只测「能跑通」：

* 负坐标：上游直接切片 ``d[y:y+h, x:x+w]``，负索引会从画布另一头取像素，
  本该裁掉的左边反而贴到右边。这里逐像素核对「源图第 2 列落在画布第 0 列」，
  并反向断言画布最右侧未被污染。
* 四边越界：右/下越界裁切，左/上（负坐标）同样裁切。
* 批次：帧数取两边较大值，短的一边重复最后一帧（上游会把目标截短丢帧）。
* 遮罩：尺寸不符自动缩放、单帧广播、NaN 清成 0、按源图坐标对齐而不是画布坐标。

运行：python_embeded\\python.exe tests\\test_image_composite.py
"""
import os
import sys

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

import qg_image_composite as qc  # noqa: E402

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


def canvas(height=8, width=10, color=(0.0, 0.0, 0.0), frames=1):
    """底色画布 [B,H,W,3]。"""
    plane = np.tile(np.array(color, dtype=np.float32), (height, width, 1))
    return torch.from_numpy(np.stack([plane] * frames, axis=0))


def marked(height=4, width=6):
    """源图 [1,H,W,3]：R 通道存列号，G 通道存行号，便于定位像素来自哪。"""
    arr = np.zeros((1, height, width, 3), dtype=np.float32)
    arr[0, ..., 0] = np.arange(width, dtype=np.float32)[None, :]
    arr[0, ..., 1] = np.arange(height, dtype=np.float32)[:, None]
    return torch.from_numpy(arr)


node = qc.QGImageComposite()
spec = node.INPUT_TYPES()

# ---------------------------------------------------------------------------
# 一、节点契约
# ---------------------------------------------------------------------------
print("== 一、节点契约 ==")
check("注册 key 为 QG_ImageComposite",
      "QG_ImageComposite" in qc.NODE_CLASS_MAPPINGS)
check("显示名叫 QG 图像合成",
      qc.NODE_DISPLAY_NAME_MAPPINGS.get("QG_ImageComposite") == "QG 图像合成")
check("CATEGORY = QG 工具", node.CATEGORY == "QG 工具")
check("RETURN_TYPES = (IMAGE,)", node.RETURN_TYPES == ("IMAGE",))
check("RETURN_NAMES 与 RETURN_TYPES 对齐",
      len(node.RETURN_NAMES) == len(node.RETURN_TYPES))
check("FUNCTION 指向 execute", node.FUNCTION == "execute" and hasattr(node, "execute"))

required = spec["required"]
check("required 含 destination / source",
      "destination" in required and "source" in required)
check("遮罩在 optional（可不接）", "mask" in spec.get("optional", {}))
for name in ("x", "y", "offset_x", "offset_y"):
    entry = required.get(name)
    check("%s 是 INT 且默认 0" % name,
          entry is not None and entry[0] == "INT" and entry[1]["default"] == 0,
          str(entry)[:60])
check("坐标范围对称到 ±COORD_LIMIT",
      required["x"][1]["min"] == -qc.COORD_LIMIT
      and required["x"][1]["max"] == qc.COORD_LIMIT)

# ---------------------------------------------------------------------------
# 二、基本贴图
# ---------------------------------------------------------------------------
print()
print("== 二、基本贴图 ==")
dest = canvas(8, 10, (0.2, 0.2, 0.2))
src = marked(4, 6)
out = node.execute(dest, src)[0]
check("输出形状 = 目标形状", tuple(out.shape) == (1, 8, 10, 3), str(out.shape))
check("(0,0) 贴左上：左上角像素来自源图 (0,0)",
      abs(float(out[0, 0, 0, 0]) - 0.0) < 1e-6 and abs(float(out[0, 0, 0, 1]) - 0.0) < 1e-6)
check("(0,0) 贴左上：右下边界像素来自源图 (3,5)",
      abs(float(out[0, 3, 5, 0]) - 5.0) < 1e-6 and abs(float(out[0, 3, 5, 1]) - 3.0) < 1e-6)
check("(0,0) 源图范围之外保持底色",
      abs(float(out[0, 7, 9, 0]) - 0.2) < 1e-6)

out = node.execute(dest, src, x=2, y=3)[0]
check("(2,3) 贴图：画布 (3,2) 来自源图 (0,0)",
      abs(float(out[0, 3, 2, 0]) - 0.0) < 1e-6 and abs(float(out[0, 3, 2, 1]) - 0.0) < 1e-6)
check("(2,3) 贴图：画布 (6,7) 来自源图 (3,5)",
      abs(float(out[0, 6, 7, 0]) - 5.0) < 1e-6 and abs(float(out[0, 6, 7, 1]) - 3.0) < 1e-6)
check("(2,3) 贴图：画布 (2,2) 仍是底色",
      abs(float(out[0, 2, 2, 0]) - 0.2) < 1e-6)

out_off = node.execute(dest, src, x=2, y=3, offset_x=5, offset_y=7)[0]
base = node.execute(dest, src, x=7, y=10)[0]
check("offset 与 x/y 相加后等价（2+5, 3+7）",
      torch.allclose(out_off, base, atol=1e-6))

# ---------------------------------------------------------------------------
# 三、负坐标（上游实现会贴错位置）
# ---------------------------------------------------------------------------
print()
print("== 三、负坐标 ==")
out = node.execute(dest, src, x=-2, y=0)[0]
check("x=-2：画布第 0 列来自源图第 2 列",
      abs(float(out[0, 0, 0, 0]) - 2.0) < 1e-6)
check("x=-2：画布第 3 列来自源图第 5 列（源图右端）",
      abs(float(out[0, 0, 3, 0]) - 5.0) < 1e-6)
check("x=-2：画布第 4 列已出源图范围，回到底色",
      abs(float(out[0, 0, 4, 0]) - 0.2) < 1e-6)
check("x=-2 不会贴到画布右侧（回归负索引 bug）",
      abs(float(out[0, 0, 9, 0]) - 0.2) < 1e-6)

out = node.execute(dest, src, x=0, y=-1)[0]
check("y=-1：画布第 0 行来自源图第 1 行",
      abs(float(out[0, 0, 0, 1]) - 1.0) < 1e-6)
check("y=-1：画布第 2 行来自源图第 3 行",
      abs(float(out[0, 2, 0, 1]) - 3.0) < 1e-6)
check("y=-1 不会贴到画布底部（回归负索引 bug）",
      abs(float(out[0, 7, 0, 0]) - 0.2) < 1e-6)

out = node.execute(dest, src, x=-2, y=-1)[0]
check("双负坐标：画布 (0,0) 来自源图 (1,2)",
      abs(float(out[0, 0, 0, 0]) - 2.0) < 1e-6
      and abs(float(out[0, 0, 0, 1]) - 1.0) < 1e-6)
check("双负坐标：画布尺寸不变",
      tuple(out.shape) == (1, 8, 10, 3))

# ---------------------------------------------------------------------------
# 四、越界裁切
# ---------------------------------------------------------------------------
print()
print("== 四、越界裁切 ==")
out = node.execute(dest, src, x=7, y=0)[0]
check("右越界：画布第 9 列来自源图第 2 列（10-7-1=2）",
      abs(float(out[0, 0, 9, 0]) - 2.0) < 1e-6)
check("右越界：画布第 6 列仍未覆盖",
      abs(float(out[0, 0, 6, 0]) - 0.2) < 1e-6)

out = node.execute(dest, src, x=0, y=6)[0]
check("下越界：画布第 7 行来自源图第 1 行（8-6-1=1）",
      abs(float(out[0, 7, 0, 1]) - 1.0) < 1e-6)

for label, kw in (("右侧外", {"x": 10}), ("左侧外", {"x": -7}),
                  ("下方外", {"y": 8}), ("上方外", {"y": -5})):
    out = node.execute(dest, src, **kw)[0]
    check("完全在画布%s：输出等于目标" % label,
          torch.allclose(out, dest, atol=1e-6))

# ---------------------------------------------------------------------------
# 五、遮罩
# ---------------------------------------------------------------------------
print()
print("== 五、遮罩 ==")
white = canvas(4, 6, (1.0, 1.0, 1.0))[:, :, :, 0]
black = canvas(4, 6, (0.0, 0.0, 0.0))[:, :, :, 0]

out = node.execute(dest, src, mask=black)[0]
check("遮罩全 0：输出等于目标", torch.allclose(out, dest, atol=1e-6))

out = node.execute(dest, src, mask=white)[0]
check("遮罩全 1：贴图区域等于源图",
      torch.allclose(out[0, :4, :6], src[0], atol=1e-6))
check("遮罩全 1：源图外仍保持底色",
      abs(float(out[0, 7, 9, 0]) - 0.2) < 1e-6)

half = torch.full((4, 6), 0.5)
out = node.execute(dest, src, mask=half)[0]
expect = src * 0.5 + 0.2 * 0.5
check("遮罩 0.5：源图与底色各半",
      abs(float(out[0, 0, 0, 0]) - float(expect[0, 0, 0, 0])) < 1e-5)

# 遮罩尺寸与源图不符 → 自动缩放
small_mask = torch.zeros((2, 3))
out = node.execute(dest, src, mask=small_mask)[0]
check("遮罩尺寸不符时自动缩放（不崩且形状正确）",
      tuple(out.shape) == (1, 8, 10, 3))
check("缩放后的全 0 遮罩仍保持目标",
      torch.allclose(out, dest, atol=0.02))

# 单帧遮罩 + 多帧源 → 广播
src3 = torch.cat([marked(4, 6), marked(4, 6) * 0 + 0.5, marked(4, 6) * 0 + 0.9])
out = node.execute(canvas(8, 10, (0.2, 0.2, 0.2), frames=3), src3, mask=white)[0]
check("单帧遮罩广播到 3 帧", tuple(out.shape) == (3, 8, 10, 3))

# NaN 遮罩不能污染输出
nan_mask = torch.full((4, 6), float("nan"))
out = node.execute(dest, src, mask=nan_mask)[0]
check("NaN 遮罩清成 0（输出等于目标、无 NaN）",
      torch.isfinite(out).all() and torch.allclose(out, dest, atol=1e-6))

# 遮罩按源图坐标对齐，不是画布坐标
left_black = torch.ones((4, 6))
left_black[:, :3] = 0.0
out = node.execute(dest, src, mask=left_black, x=3)[0]
check("遮罩按源图坐标对齐：画布第 3 列（源图第 0 列）保持底色",
      abs(float(out[0, 0, 3, 0]) - 0.2) < 1e-6)
check("遮罩按源图坐标对齐：画布第 6 列（源图第 3 列）已混合",
      abs(float(out[0, 0, 6, 0]) - 3.0) < 1e-6)

# ---------------------------------------------------------------------------
# 六、批次
# ---------------------------------------------------------------------------
print()
print("== 六、批次 ==")
dest1 = canvas(8, 10, (0.2, 0.2, 0.2), frames=1)
src3 = torch.stack([marked(4, 6)[0] + i * 0.1 for i in range(3)])
out = node.execute(dest1, src3)[0]
check("目标 1 帧 + 源 3 帧 → 输出 3 帧", tuple(out.shape)[0] == 3, str(out.shape))
check("每帧贴的都是自己的源帧",
      abs(float(out[0, 0, 0, 0]) - 0.0) < 1e-6
      and abs(float(out[1, 0, 0, 0]) - 0.1) < 1e-6
      and abs(float(out[2, 0, 0, 0]) - 0.2) < 1e-6)

dest3 = canvas(8, 10, (0.2, 0.2, 0.2), frames=3)
src1 = marked(4, 6)
out = node.execute(dest3, src1)[0]
check("目标 3 帧 + 源 1 帧 → 输出 3 帧", tuple(out.shape)[0] == 3, str(out.shape))
check("目标 3 帧 + 源 1 帧：每帧都贴上同一源图",
      all(abs(float(out[i, 0, 0, 0]) - 0.0) < 1e-6 for i in range(3)))

try:
    node.execute(torch.zeros((0, 8, 10, 3)), src1)
    check("空批次抛 ValueError", False)
except ValueError:
    check("空批次抛 ValueError", True)

out = node.execute(dest, src)[0]
check("输出 dtype 与目标一致", out.dtype == dest.dtype)
check("输出 device 与目标一致", out.device == dest.device)

# ---------------------------------------------------------------------------
# 七、源码约定
# ---------------------------------------------------------------------------
print()
print("== 七、源码约定 ==")
source_text = open(os.path.join(PKG, "qg_image_composite.py"), encoding="utf-8").read()
check("声明了独立实现（GPL 合规）", "独立" in source_text and "未复制上游源码" in source_text)
check("遮罩先清 NaN 再使用", "nan_to_num" in source_text)
check("没有把坐标直接塞进切片（先求交集）", "x1 <= x0" in source_text)
check("__init__.py 已注册该模块",
      "qg_image_composite" in open(os.path.join(PKG, "__init__.py"), encoding="utf-8").read())

print()
print("合计：%d 通过 / %d 失败" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
