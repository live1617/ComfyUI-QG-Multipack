# -*- coding: utf-8 -*-
"""mask_by_name_helpers.py 的单元测试。

重点是那两个「参数能拉到很大」的步骤：grow 到 512、soften 到 100。它们曾经
用大核池化实现，耗时随半径平方涨（1024² 上 grow=128 要 51 秒、soften=100 要
10 秒），现在换成距离变换 / 积分图，这里把「结果不变 + 时间有上限」钉住。

运行：python_embeded\\python.exe tests\\test_mask_helpers.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402

import mask_by_name_helpers as m  # noqa: E402

FAILED = 0


def check(label, ok, detail=""):
    global FAILED
    if not ok:
        FAILED += 1
    print(f"  {label:<46}{'PASS' if ok else 'FAIL'}  {detail if not ok else ''}")


def reference_grow(binary, px):
    """参照实现：3x3 方形核迭代 px 次。慢，但是定义本身。"""
    plane = binary.float().unsqueeze(0).unsqueeze(0)
    for _ in range(px):
        plane = F.max_pool2d(plane, 3, stride=1, padding=1)
    return plane.squeeze(0).squeeze(0) > 0.5


print("=== A. grow 结果与定义一致 ===")
base = torch.zeros(1, 64, 64)
base[0, 20:30, 20:30] = 1.0
base[0, 40:44, 44:51] = 1.0
for px in (1, 2, 5, 9):
    got = m.grow_mask(base, px) > 0.5
    ref = reference_grow(base[0] > 0.5, px).unsqueeze(0)
    check(f"grow={px} 逐像素一致", bool((got == ref).all()),
          f"差异 {int((got != ref).sum())} 像素")

print("\n=== B. grow 边界 ===")
check("grow=0 原样返回", bool(torch.equal(m.grow_mask(base, 0), base)))
check("grow 负值原样返回", bool(torch.equal(m.grow_mask(base, -3), base)))
empty = torch.zeros(1, 32, 32)
check("空遮罩不炸", float(m.grow_mask(empty, 5).sum()) == 0.0)
full = torch.ones(1, 16, 16)
check("全满遮罩仍全满", float(m.grow_mask(full, 3).sum()) == 256.0)

print("\n=== C. grow 性能（1024x1024，半径拉到最大的量级）===")
big = torch.zeros(1, 1024, 1024)
big[0, 400:600, 400:600] = 1.0
t0 = time.time()
grown = m.grow_mask(big, 128)
cost = time.time() - t0
check("grow=128 在 3 秒内", cost < 3.0, f"用了 {cost:.2f}s")
check("grow=128 面积正确", int(grown.sum()) == 456 * 456, int(grown.sum()))
t0 = time.time()
m.grow_mask(big, 512)
cost = time.time() - t0
check("grow=512 在 3 秒内", cost < 3.0, f"用了 {cost:.2f}s")

print("\n=== D. soften 与 avg_pool2d 一致 ===")
for px in (1, 3, 7):
    x = torch.rand(1, 48, 61)
    ref = F.avg_pool2d(x.unsqueeze(1), 2 * px + 1, stride=1, padding=px).squeeze(1)
    got = m.soften_mask(x, px)
    diff = (ref - got).abs().max().item()
    check(f"soften={px} 最大误差 < 1e-4", diff < 1e-4, f"{diff:.2e}")

print("\n=== E. soften 性能 ===")
t0 = time.time()
m.soften_mask(big, 100)
cost = time.time() - t0
check("soften=100 在 3 秒内", cost < 3.0, f"用了 {cost:.2f}s")
check("soften 不改全空遮罩", float(m.soften_mask(empty, 8).sum()) == 0.0)

print("\n=== F. refine 顺序 ===")
shape = torch.zeros(1, 64, 64)
shape[0, 20:40, 20:40] = 1.0
shape[0, 22:26, 22:26] = 0.0   # 内部洞
shape[0, 2:4, 2:4] = 1.0       # 小碎块
out = m.refine_mask(shape, 0, 0, True, True, 0.05)
# 400 的前景块 + 内部洞 16 被填 - 2x2 碎块 4 被删 = 400（洞本来就不算前景）
check("先删碎块再填洞", int(out.sum()) == 400, int(out.sum()))
check("输出范围 0..1", float(out.min()) >= 0.0 and float(out.max()) <= 1.0)

print("\n=== G. pick / split ===")
stack = torch.zeros(3, 4, 4)
stack[0, 0, 0] = 1.0
stack[1, 0, 1] = 1.0
stack[1, 1, 1] = 1.0
frames = m.split_by_frame(stack, [1, 2, 0])
check("按帧切分数量", [int(f.shape[0]) for f in frames] == [1, 2, 0])
check("空帧 pick 出全零", float(m.pick(frames[2], "all matches").sum()) == 0.0)
check("largest 选面积大的", int(m.pick(frames[1], "largest only").sum()) == 2)
try:
    m.split_by_frame(stack, [1, 1])
    check("数量对不上要报错", False)
except ValueError:
    check("数量对不上要报错", True)

print("\n=== H. search_text ===")
check("补默认数量", m.search_text("the dog") == "the dog:16")
check("已有的数量保留", m.search_text("cat:3") == "cat:3")
check("逗号拆成两条", m.search_text("cat,dog:2") == "cat:16, dog:2")
check("去括号引号", m.search_text('(the "cat")') == "the cat:16")
check("空白串返回空", m.search_text("   ") == "")

print("\n---")
print("失败 %d 项" % FAILED)
print("全部通过" if FAILED == 0 else "有失败")
sys.exit(1 if FAILED else 0)
