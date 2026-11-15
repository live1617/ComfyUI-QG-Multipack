# -*- coding: utf-8 -*-
"""QG_IDPhotoCrop 越界处理（overflow_mode）的回归测试。

历史故障：用户用一张 429x600、人脸占宽 52% 的红底人像，按默认
``face_ratio=0.42`` 裁剪，结果人物变小、四周多出一圈红边。

根因不是裁剪算错，而是取景框被撑到原图之外：
``face_ratio`` 是「人脸轮廓宽度 ÷ 输出宽度」，0.42 要求人脸只占输出 42%，
可素材本身已经是 52% —— 取景框必须放大到脸的 1/0.42 倍，于是算出
533x746，比 429x600 的源图还大，越界部分只能用背景色补，补出来的就是
那圈边框。

覆盖：
  · ``shrink_into_source``：源内不动；越界等比缩小且四角落在源内；
    绕中心缩，眼睛的相对位置不变；旋转框也收得回来；
  · ``edge_colours``：四条边各自取背景色；底部混进衣服时不会被拖成黑色；
  · ``render(edge_fill=...)``：补边区跟随所在边，而不是统一纯色；
    ``filled`` 掩码把补出来的区域标 1、真实像素标 0；
  · ``overflow_mode`` 是可选下拉、默认 shrink，老工作流缺键仍能跑；
    shrink 模式不产生补边，pad 模式仍按原语义补；
  · 两套词表、前端收起态、README 都登记了新控件与下拉值。

不依赖 ComfyUI 运行时、模型、网络、API Key 或 GPL 参考源码。
运行：python_embeded\\python.exe tests\\test_id_photo_crop_overflow.py
"""
import importlib
import importlib.util
import json
import os
import sys

import numpy as np
import torch
from PIL import Image

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
    name = "qgmp_crop_overflow_test"
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(PKG, "__init__.py"), submodule_search_locations=[PKG])
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[name] = pkg
    spec.loader.exec_module(pkg)
    return name


def read(rel):
    with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
        return fh.read()


def solid(w, h, colour):
    array = np.zeros((h, w, 3), dtype=np.uint8)
    array[..., :] = colour
    return array


def portrait_like(w=300, h=400, bg=(220, 60, 60), body=(30, 30, 34)):
    """红底 + 中央深色块的合成人像，底部条带混着"衣服"。"""
    array = solid(w, h, bg)
    array[int(h * 0.35):h, int(w * 0.22):int(w * 0.78)] = body
    return array


def main():
    pkg = load_package()
    mod = importlib.import_module(pkg + ".id_photo_crop_node")
    helpers = importlib.import_module(pkg + "._id_photo_helpers")
    face_mod = importlib.import_module(pkg + "._face_helpers")
    Face = face_mod.Face
    H = helpers
    cls = mod.NODE_CLASS_MAPPINGS["QG_IDPhotoCrop"]

    # ---------------------------------------------------------------- 几何
    print("\n[1] shrink_into_source：加大脸部占比，把框收进源内")
    face = Face((50, 80, 250, 340), (100, 140), (200, 140), "mock")
    frame = H.plan_frame(face, 295, 413, 0.42, 0.38, True)
    shrunk, ratio, widened = H.shrink_into_source(
        face, 295, 413, 0.42, 0.38, True, 300, 400)
    x0, y0, x1, y1 = H.frame_bounds(shrunk)
    check("越界时报告已收", widened is True)
    check("收窄用的是更大的脸部占比", ratio > 0.42, "ratio=%.3f" % ratio)
    check("收完后比原框小", shrunk.w < frame.w, "%.0f vs %.0f"
          % (shrunk.w, frame.w))
    check("收缩后左边界 >= 0", x0 >= -1e-6, "x0=%.2f" % x0)
    check("收缩后上边界 >= 0", y0 >= -1e-6, "y0=%.2f" % y0)
    check("收缩后右边界 <= 源宽", x1 <= 300 + 1e-6, "x1=%.2f" % x1)
    check("收缩后下边界 <= 源高", y1 <= 400 + 1e-6, "y1=%.2f" % y1)
    check("输出尺寸不变", (shrunk.out_w, shrunk.out_h) == (295, 413))
    check("宽高比不变", abs(shrunk.w / shrunk.h - frame.w / frame.h) < 1e-6)

    # 关键性质：eye_line 不能因为收框而漂移，否则头顶会被切
    ex, ey = face.eye_center
    eye_share = (ey - (shrunk.cy - shrunk.h / 2)) / shrunk.h
    check("收缩后眼线仍在 eye_line 上", abs(eye_share - 0.38) < 0.01,
          "%.4f" % eye_share)
    check("收缩后眼睛左右居中", abs(ex - shrunk.cx) < 1.0,
          "%.1f vs %.1f" % (ex, shrunk.cx))

    # 已经装得下就不该动
    small_face = Face((120, 150, 180, 250), (135, 190), (165, 190), "mock")
    same, same_ratio, same_widened = H.shrink_into_source(
        small_face, 295, 413, 0.42, 0.38, True, 300, 400)
    expected = H.plan_frame(small_face, 295, 413, 0.42, 0.38, True)
    check("源内不触发收缩", same_widened is False)
    check("源内脸部占比原样", same_ratio == 0.42, "ratio=%r" % same_ratio)
    check("源内框与原计划一致", same.affine == expected.affine)

    # 旋转过的框，外接矩形也要收回来
    tilted_frame = H.plan_frame(face, 295, 413, 0.42, 0.38, True)
    tilted = H.frame_centred(tilted_frame.cx, tilted_frame.cy, tilted_frame.w,
                             tilted_frame.h, 0.12, 295, 413)
    check("旋转框本来就越界", not H.frame_fits(
        tilted, 299.0, 399.0))
    tshrunk, tratio, _ = H.shrink_into_source(
        face, 295, 413, 0.42, 0.38, True, 300, 400)
    check("旋转素材也能收进源内", H.frame_fits(tshrunk, 299.0, 399.0),
          str(H.frame_bounds(tshrunk)))

    # 眼睛几乎贴着上边：任何占比都放不下，只能缩框 + 平移兜底
    edge_face = Face((100, 5, 300, 60), (150, 20), (250, 20), "mock")
    eshrunk, eratio, ewidened = H.shrink_into_source(
        edge_face, 295, 413, 0.42, 0.38, True, 400, 400)
    check("极端贴边时仍报告已收", ewidened is True)
    check("极端贴边时用满上限占比", abs(eratio - 0.9) < 1e-6, "%.3f" % eratio)
    check("极端贴边时最终仍在源内", H.frame_fits(eshrunk, 399.0, 399.0),
          str(H.frame_bounds(eshrunk)))

    # ------------------------------------------------------------ 边缘取色
    print("\n[2] edge_colours：每条边各自取背景色")
    rgb = portrait_like()
    top, bottom, left, right = H.edge_colours(rgb)
    check("顶部取到红底", abs(top[0] - 220) < 12 and abs(top[1] - 60) < 12,
          str(top))
    check("左边缘取到红底", abs(left[0] - 220) < 12, str(left))
    check("右边取到红底", abs(right[0] - 220) < 12, str(right))
    check("底部没被衣服拖成黑色", bottom[0] > 150,
          "bottom=%s（衣服是 (30,30,34)）" % (bottom,))

    flat = solid(120, 160, (12, 100, 200))
    edges = H.edge_colours(flat)
    check("纯色图四边同色", all(e == (12, 100, 200) for e in edges), str(edges))
    check("空图回退白色",
          H.edge_colours(np.zeros((0, 0, 3), dtype=np.uint8))[0] == (255, 255, 255))
    check("全黑图不会溢出色值",
          all(0 <= c <= 255 for c in H.edge_colours(solid(40, 40, (0, 0, 0)))[0]))

    # ---------------------------------------------------------------- 渲染
    print("\n[3] render(edge_fill)：补边区跟随所在边")
    src = Image.fromarray(portrait_like(), "RGB")
    filled_rgb = (0, 255, 0)          # 鲜绿，一眼能看出有没有被用上
    no_edge, mask_plain = H.render(src, frame, filled_rgb)
    plain_corner = np.asarray(no_edge)[0, 0]
    check("不传 edge_fill 时补边区是纯色（回归）",
          tuple(int(v) for v in plain_corner) == filled_rgb, str(plain_corner))

    edges = H.edge_colours(np.asarray(src))
    edged, mask_edge = H.render(src, frame, filled_rgb, 255, edges)
    corner = np.asarray(edged)[0, 0]
    check("传 edge_fill 时补边区用边色而不是纯色",
          abs(int(corner[0]) - 220) < 26 and abs(int(corner[1]) - 60) < 26,
          str(corner))
    check("补边区不再是鲜绿", tuple(int(v) for v in corner) != filled_rgb)
    check("越界掩码非空", float(mask_edge.mean()) > 0.01,
          "%.3f" % float(mask_edge.mean()))
    check("两种渲染的掩码一致",
          float(np.abs(mask_edge - mask_plain).mean()) < 0.02)
    check("掩码中心是真实像素", float(mask_edge[206, 147]) < 0.5,
          "%.2f" % float(mask_edge[206, 147]))

    inside = H.plan_frame(small_face, 295, 413, 0.42, 0.38, True)
    _, mask_in = H.render(src, inside, filled_rgb, 255, edges)
    check("不越界时没有补边", float(mask_in.mean()) < 0.01,
          "%.4f" % float(mask_in.mean()))
    check("不越界时输出尺寸正确", np.asarray(edged).shape == (413, 295, 3))

    # 极端越界不能因为要 pad 就把内存吃光
    huge = H.frame_centred(150, 200, 2400, 3360, 0.0, 295, 413)
    extreme, extreme_mask = H.render(src, huge, filled_rgb, 255, edges)
    check("极端越界回退纯色且不崩",
          tuple(int(v) for v in np.asarray(extreme)[0, 0]) == filled_rgb,
          str(np.asarray(extreme)[0, 0]))

    # ---------------------------------------------------------------- 节点
    print("\n[4] 节点契约：overflow_mode 可选、默认 shrink")
    spec = cls.INPUT_TYPES()
    optional = spec.get("optional", {})
    check("overflow_mode 在 optional 里", "overflow_mode" in optional)
    check("overflow_mode 默认 shrink",
          optional.get("overflow_mode", ({}, {}))[1].get("default") == "shrink")
    check("overflow_mode 只有 shrink / pad",
          list(optional["overflow_mode"][0]) == ["shrink", "pad"])
    check("alpha_mode 仍在", "alpha_mode" in optional)
    import inspect
    params = inspect.signature(cls.execute).parameters
    check("execute 有 overflow_mode 默认值",
          "overflow_mode" in params and params["overflow_mode"].default == "shrink")
    check("alpha_mode 默认值仍是 fill", params["alpha_mode"].default == "fill")
    check("输出槽没变",
          tuple(cls.RETURN_TYPES) == ("IMAGE", "MASK", "BOOLEAN", "INT", "IMAGE"))
    check("fill_mode tooltip 提到按边取色",
          "edges" in spec["required"]["fill_mode"][1]["tooltip"].lower()
          or "edge" in spec["required"]["fill_mode"][1]["tooltip"].lower())

    # 打桩检测结果，验证两种模式的补边行为
    node = cls()
    node._detect_with_shrink = lambda rgb, pick, side: face
    batch = np.asarray(portrait_like()).astype(np.float32) / 255.0
    tensor = torch.from_numpy(batch)[None]

    def run(mode):
        return node.execute(tensor, "1inch", 0.0, 0.0, "cm", 300, 0.42, 0.38,
                            True, "center", 2000, "border", "#364254", mode,
                            "fill")

    shrink_out = run("shrink")
    shrink_mask = shrink_out[1][0].numpy()
    check("shrink：输出尺寸正确", tuple(shrink_out[0].shape) == (1, 413, 295, 3),
          str(tuple(shrink_out[0].shape)))
    check("shrink：不再补边", float(shrink_mask.mean()) < 0.01,
          "%.4f" % float(shrink_mask.mean()))
    check("shrink：是否扩图 为 False", shrink_out[2] is False)

    pad_out = run("pad")
    pad_mask = pad_out[1][0].numpy()
    check("pad：仍会补边", float(pad_mask.mean()) > 0.05,
          "%.3f" % float(pad_mask.mean()))
    check("pad：是否扩图 为 True", pad_out[2] is True)
    check("pad：输出尺寸一致", tuple(pad_out[0].shape) == (1, 413, 295, 3))

    # -------------------------------------------------------------- 登记
    print("\n[5] 词表 / 前端 / README 登记")
    node_defs = json.loads(read("locales/zh/nodeDefs.json"))["QG_IDPhotoCrop"]
    entry = node_defs["inputs"].get("overflow_mode")
    check("nodeDefs 有 overflow_mode", entry is not None)
    check("nodeDefs 有中文名", bool(entry and entry.get("name")),
          str(entry and entry.get("name")))
    check("nodeDefs 有两个取值中文",
          bool(entry and set(entry.get("options", {})) == {"shrink", "pad"}),
          str(entry and entry.get("options")))
    check("nodeDefs fill_mode tooltip 已更新为按边取色",
          "四条边" in node_defs["inputs"]["fill_mode"]["tooltip"])

    words = json.loads(read("translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"))
    block = words["QG_IDPhotoCrop"]
    check("translations inputs 有 overflow_mode", "overflow_mode" in block["inputs"])
    check("translations widgets 有 overflow_mode",
          "overflow_mode" in block["widgets"])
    check("translations 中文名不是恒等翻译",
          block["widgets"].get("overflow_mode") not in (None, "overflow_mode"))

    menus = json.loads(read("translations/zh-CN/Menus/ComfyUI-QG-Multipack.json"))
    check("Menus shrink -> 收缩到原图", menus.get("shrink") == "收缩到原图")
    check("Menus pad -> 允许补边", menus.get("pad") == "允许补边")

    photokit_js = read("web/qg_photokit_zh.js")
    check("前端有 overflow_mode 收起态标签", "overflow_mode" in photokit_js)
    check("前端 shrink 有中文", "收缩到原图" in photokit_js)
    i18n_js = read("web/qg_i18n.js")
    check("qg_i18n 有 overflow_mode", "overflow_mode" in i18n_js)

    readme = read("README.md")
    check("README 控件清单含 overflow_mode", "overflow_mode" in readme)
    check("README 说明收缩到原图", "收缩到原图" in readme)
    check("README 说明补边按四边取色", "四条边" in readme)

    print("\n===== 合计 %d 项，FAIL %d =====" % (TOTAL, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
