# -*- coding: utf-8 -*-
"""QG_MultiPhotoSheet 节点级测试：几何 / 渲染 / 契约 / 词表登记。

重点在几何函数 ``plan_multi_sheet``：它是纯整数运算，不依赖 PIL / torch，
把「列数→行数自动」「实际列数不超过人数」「最后一行计数」「放不下缩小」
这几条最容易出错的规则离线断言。

不依赖模型、网络、API Key。
运行：python_embeded\\python.exe tests\\test_multi_photo_sheet.py
"""
import importlib.util
import json
import os
import sys

import numpy as np
import torch

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


def load_node():
    spec = importlib.util.spec_from_file_location(
        "qgmp_multi_sheet_test",
        os.path.join(PKG, "qg_multi_photo_sheet.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read(rel):
    with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
        return fh.read()


m = load_node()

# ---------- 一、纯几何 ----------
print("== 一、几何 plan_multi_sheet ==")
A4 = (21.0, 29.7)
DPI = 300
ASPECT = 0.7  # 宽/高，证件照典型比（如 3.5:5 = 0.7）

p = m.plan_multi_sheet(6, ASPECT, *A4, DPI, 0.5, 0.3, 3)
check("6 人 / 3 列 → 2 行", (p.cols, p.rows) == (3, 2),
      "得 %d×%d" % (p.cols, p.rows))
check("6 人全部计入", p.count == 6 and p.last_row_count == 3)

p1 = m.plan_multi_sheet(1, ASPECT, *A4, DPI, 0.5, 0.3, 3)
check("1 人 / 3 列 → 实际列数收敛为 1", (p1.cols, p1.rows) == (1, 1),
      "得 %d×%d" % (p1.cols, p1.rows))

p7 = m.plan_multi_sheet(7, ASPECT, *A4, DPI, 0.5, 0.3, 3)
check("7 人 / 3 列 → 3 行，末行 1 人", (p7.rows, p7.last_row_count) == (3, 1),
      "得 行%d 末行%d" % (p7.rows, p7.last_row_count))

check("格宽随列数增大而减小",
      m.plan_multi_sheet(6, ASPECT, *A4, DPI, 0.5, 0.3, 2).cell_w
      > m.plan_multi_sheet(6, ASPECT, *A4, DPI, 0.5, 0.3, 4).cell_w)
check("格高按首帧比例算",
      abs(p.cell_h - round(p.cell_w / ASPECT)) <= 1)

# 越界：末格必须在纸内
last_x = p7.origin_x + (p7.cols - 1) * p7.step_x + p7.cell_w
last_y = p7.origin_y + (p7.rows - 1) * p7.step_y + p7.cell_h
check("末格不越出纸张", last_x <= p7.canvas_w and last_y <= p7.canvas_h,
      "末格(%d,%d) 纸(%d,%d)" % (last_x, last_y, p7.canvas_w, p7.canvas_h))

# 放不下：缩小与报错两条路
too_many = 60
ps = m.plan_multi_sheet(too_many, ASPECT, *A4, DPI, 0.5, 0.3, 4, True)
check("放不下时启用缩小：scale < 1", ps.scale < 1.0, "scale=%.4f" % ps.scale)
last_xs = ps.origin_x + (ps.cols - 1) * ps.step_x + ps.cell_w
last_ys = ps.origin_y + (ps.rows - 1) * ps.step_y + ps.cell_h
check("缩小后末格不越界", last_xs <= ps.canvas_w and last_ys <= ps.canvas_h,
      "末格(%d,%d) 纸(%d,%d)" % (last_xs, last_ys, ps.canvas_w, ps.canvas_h))
try:
    m.plan_multi_sheet(too_many, ASPECT, *A4, DPI, 0.5, 0.3, 4, False)
    check("关闭缩小时明确报错", False)
except ValueError as e:
    check("关闭缩小时明确报错", "放不下" in str(e), str(e)[:60])

# 0 帧 / 非法比例
for bad in [(0, ASPECT), (3, 0)]:
    try:
        m.plan_multi_sheet(bad[0], bad[1], *A4, DPI, 0.5, 0.3, 3)
        check("非法输入 %r 报错" % (bad,), False)
    except ValueError:
        check("非法输入 %r 报错" % (bad,), True)

# ---------- 二、渲染 ----------
print("== 二、渲染 render_multi_sheet ==")


def solid_frame(rgb, h=70, w=50):
    a = np.zeros((h, w, 3), dtype=np.float32)
    a[..., 0] = rgb[0] / 255.0
    a[..., 1] = rgb[1] / 255.0
    a[..., 2] = rgb[2] / 255.0
    return torch.from_numpy(a)


frames = [solid_frame(c) for c in [(255, 0, 0), (0, 255, 0),
                                   (0, 0, 255), (255, 255, 0)]]
plan = m.plan_multi_sheet(4, 50 / 70.0, 10.0, 10.0, 300, 0.1, 0.1, 2)
sheet = m.render_multi_sheet(frames, plan)
check("输出尺寸 = 纸张像素", sheet.size == (plan.canvas_w, plan.canvas_h),
      str(sheet.size))
# 每格中心像素应等于对应帧颜色（居中裁切纯色块 → 中心必是该色）
from PIL import Image
px = sheet.load()
colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
ok_color = True
for i, want in enumerate(colors):
    r, c = divmod(i, plan.cols)
    cx = plan.origin_x + c * plan.step_x + plan.cell_w // 2
    cy = plan.origin_y + r * plan.step_y + plan.cell_h // 2
    got = px[cx, cy]
    if max(abs(got[k] - want[k]) for k in range(3)) > 2:
        ok_color = False
check("每格中心=对应人的颜色（未串格）", ok_color)

# 描边画在格内：描边后中心仍是本人颜色
plain = m.render_multi_sheet(frames[:1], m.plan_multi_sheet(
    1, 50 / 70.0, 10.0, 10.0, 300, 0.1, 0.1, 1), border_px=4)
check("描边后图像仍正常生成", plain.size[0] > 0 and plain.size[1] > 0)

# 底色可指定
bg = m.render_multi_sheet(frames[:1], m.plan_multi_sheet(
    1, 50 / 70.0, 10.0, 10.0, 300, 0.1, 0.1, 1), bg_color="#123456")
check("纸张底色可指定", bg.load()[0, 0][:3] == (0x12, 0x34, 0x56),
      str(bg.load()[0, 0][:3]))

# 非法颜色回退白
check("非法底色回退白", m.parse_color("not-a-color") == (255, 255, 255))

# ---------- 三、节点契约 ----------
print("== 三、节点契约 ==")
cls = m.QGMultiPhotoSheet
it = cls.INPUT_TYPES()
check("类名映射", m.NODE_CLASS_MAPPINGS.get("QG_MultiPhotoSheet") is cls)
check("显示名", m.NODE_DISPLAY_NAME_MAPPINGS.get("QG_MultiPhotoSheet")
      == "QG 多人证件照拼版")
check("RETURN_TYPES", cls.RETURN_TYPES == ("IMAGE", "INT", "INT", "INT"),
      str(cls.RETURN_TYPES))
check("RETURN_NAMES", cls.RETURN_NAMES == ("sheet", "rows", "cols", "count"))
check("image 是 IMAGE", it["required"]["image"][0] == "IMAGE")
check("列数默认 3", it["required"]["cols"][1]["default"] == 3)
check("fit_to_paper 默认开",
      it["required"]["fit_to_paper"][1]["default"] is True)

# execute 端到端：4 人 → 2×2，输出单帧 IMAGE
out = cls().execute(torch.stack(frames), 10.0, 10.0, 300, 2, 0.1, 0.1, True)
check("execute 输出 4 项", len(out) == 4)
check("execute 行数=2 列数=2 人数=4", out[1:] == (2, 2, 4), str(out[1:]))
check("execute 输出 IMAGE 单帧 4 维", out[0].dim() == 4 and out[0].shape[0] == 1)

# ---------- 四、词表与文档登记 ----------
print("== 四、词表与文档登记 ==")
nd = json.loads(read("locales/zh/nodeDefs.json"))
tr = json.loads(read("translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"))
check("nodeDefs 收录新节点", "QG_MultiPhotoSheet" in nd)
check("translations 收录新节点", "QG_MultiPhotoSheet" in tr)
check("两份词表节点数一致", len(nd) == len(tr))
check("description 逐字一致",
      nd["QG_MultiPhotoSheet"]["description"]
      == tr["QG_MultiPhotoSheet"]["description"])
check("全部输入有中文", all(k in nd["QG_MultiPhotoSheet"]["inputs"]
                        for k in it["required"]))
check("全部输出有中文", len(nd["QG_MultiPhotoSheet"]["outputs"]) == 4)
rd = read("README.md")
check("README 表格登记", "QG_MultiPhotoSheet" in rd)
check("ISSUES 登记", "多人证件照拼版" in read("ISSUES.md"))

print("\n结果：%d / %d 通过" % (Total - Failed, Total))
if Failed:
    sys.exit(1)
