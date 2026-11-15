# -*- coding: utf-8 -*-
"""QG_IDPhotoCrop 越界补边与边缘取色的回归测试。

历史故障：用户用一张 429x600、人脸占宽 52% 的红底人像，按
``face_ratio=0.42`` 裁剪，结果人物变小、四周多出一圈红边。

根因不是裁剪算错，而是取景框被撑到原图之外：
``face_ratio`` 是「人脸轮廓宽度 ÷ 输出宽度」，0.42 要求人脸只占输出 42%，
可素材本身已经是 52% —— 取景框必须放大到脸的 1/0.42 倍，于是算出
533x746，比 429x600 的源图还大，越界部分只能用背景色补，补出来的就是
那圈边框。

曾经的 ``overflow_mode``（收缩到原图 / 允许补边）已按用户要求整块移除，
节点回到「严格按 face_ratio 构图、越界就补边」的单一行为；剩下的改进只有
补边颜色：不再统一用顶部采样色，而是四条边各自取背景色。

覆盖：
  · ``edge_colours``：四条边各自取背景色；底部混进衣服时不会被拖成黑色；
  · ``render(edge_fill=...)``：补边区跟随所在边，而不是统一纯色；
    ``filled`` 掩码把补出来的区域标 1、真实像素标 0；
  · 节点契约：``overflow_mode`` 已彻底移除、``alpha_mode`` 仍在，
    越界时照常补边并标记 ``是否扩图``，不越界时补边为 0；
  · 两套词表、前端两处映射、README 都不再出现 ``overflow_mode``，
    README 仍说明补边按四边取色。

不依赖 ComfyUI 运行时、模型、网络、API Key 或 GPL 参考源码。
运行：python_embeded\\python.exe tests\\test_id_photo_crop_pad.py
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
    name = "qgmp_crop_pad_test"
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

    face = Face((50, 80, 250, 340), (100, 140), (200, 140), "mock")
    frame = H.plan_frame(face, 295, 413, 0.42, 0.38, True)

    # ------------------------------------------------------------ 边缘取色
    print("\n[1] edge_colours：每条边各自取背景色")
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
    print("\n[2] render(edge_fill)：补边区跟随所在边")
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

    inside_face = Face((120, 150, 180, 250), (135, 190), (165, 190), "mock")
    inside = H.plan_frame(inside_face, 295, 413, 0.8, 0.38, True)
    _, mask_in = H.render(src, inside, filled_rgb, 255, edges)
    check("不越界时没有补边", float(mask_in.mean()) < 0.01,
          "%.4f" % float(mask_in.mean()))
    check("不越界时输出尺寸正确", np.asarray(edged).shape == (413, 295, 3))

    # 极端越界不能因为要 pad 就把内存吃光：face_ratio 极小时框比源大十几倍
    huge = H.plan_frame(face, 295, 413, 0.02, 0.38, True)
    extreme, extreme_mask = H.render(src, huge, filled_rgb, 255, edges)
    check("极端越界回退纯色且不崩",
          tuple(int(v) for v in np.asarray(extreme)[0, 0]) == filled_rgb,
          str(np.asarray(extreme)[0, 0]))

    # ---------------------------------------------------------------- 节点
    print("\n[3] 节点契约：overflow_mode 已移除，补边行为不变")
    spec = cls.INPUT_TYPES()
    optional = spec.get("optional", {})
    check("overflow_mode 已从 optional 移除", "overflow_mode" not in optional)
    check("alpha_mode 仍在 optional 里", "alpha_mode" in optional)
    check("alpha_mode 默认仍是 fill",
          optional.get("alpha_mode", ({}, {}))[1].get("default") == "fill")
    check("required 里也没有 overflow_mode",
          "overflow_mode" not in spec.get("required", {}))
    import inspect
    params = inspect.signature(cls.execute).parameters
    check("execute 没有 overflow_mode 参数", "overflow_mode" not in params)
    check("execute 仍有 alpha_mode 默认值",
          params.get("alpha_mode") is not None
          and params["alpha_mode"].default == "fill")
    check("输出槽没变",
          tuple(cls.RETURN_TYPES) == ("IMAGE", "MASK", "BOOLEAN", "INT", "IMAGE"))
    check("fill_mode tooltip 提到按边取色",
          "edge" in spec["required"]["fill_mode"][1]["tooltip"].lower())

    # 打桩检测结果，验证补边行为
    node = cls()
    node._detect_with_shrink = lambda rgb, pick, side: face
    batch = np.asarray(portrait_like()).astype(np.float32) / 255.0
    tensor = torch.from_numpy(batch)[None]

    def run(ratio=0.42):
        return node.execute(tensor, "1inch", 0.0, 0.0, "cm", 300, ratio, 0.38,
                            True, "center", 2000, "border", "#364254", "fill")

    over = run(0.42)
    over_mask = over[1][0].numpy()
    check("越界：输出尺寸正确", tuple(over[0].shape) == (1, 413, 295, 3),
          str(tuple(over[0].shape)))
    check("越界：照常补边", float(over_mask.mean()) > 0.05,
          "%.3f" % float(over_mask.mean()))
    check("越界：是否扩图 为 True", over[2] is True)
    check("越界：补边用的是背景红而不是鲜绿",
          abs(int((over[0][0, 0, 0, 0].item()) * 255) - 220) < 30,
          str(float(over[0][0, 0, 0, 0])))

    tight = run(0.8)
    tight_mask = tight[1][0].numpy()
    check("贴紧：不产生补边", float(tight_mask.mean()) < 0.01,
          "%.4f" % float(tight_mask.mean()))
    check("贴紧：是否扩图 为 False", tight[2] is False)
    check("贴紧：输出尺寸一致", tuple(tight[0].shape) == (1, 413, 295, 3))

    # -------------------------------------------------------------- 登记
    print("\n[4] 词表 / 前端 / README 已清理 overflow_mode")
    node_defs = json.loads(read("locales/zh/nodeDefs.json"))["QG_IDPhotoCrop"]
    check("nodeDefs 没有 overflow_mode",
          "overflow_mode" not in node_defs["inputs"])
    check("nodeDefs 仍登记 alpha_mode",
          "alpha_mode" in node_defs["inputs"])
    check("nodeDefs fill_mode tooltip 说明按边取色",
          "四条边" in node_defs["inputs"]["fill_mode"]["tooltip"])

    words = json.loads(read("translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"))
    block = words["QG_IDPhotoCrop"]
    check("translations inputs 没有 overflow_mode",
          "overflow_mode" not in block["inputs"])
    check("translations widgets 没有 overflow_mode",
          "overflow_mode" not in block["widgets"])

    menus = json.loads(read("translations/zh-CN/Menus/ComfyUI-QG-Multipack.json"))
    check("Menus 没有 shrink 词条", "shrink" not in menus)
    check("Menus 没有 pad 词条", "pad" not in menus)

    photokit_js = read("web/qg_photokit_zh.js")
    check("前端收起态没有 overflow_mode", "overflow_mode" not in photokit_js)
    check("前端不再有「收缩到原图」", "收缩到原图" not in photokit_js)
    i18n_js = read("web/qg_i18n.js")
    check("qg_i18n 没有 overflow_mode", "overflow_mode" not in i18n_js)

    node_src = read("id_photo_crop_node.py")
    check("节点源码没有 overflow_mode", "overflow_mode" not in node_src)
    check("helpers 没有 shrink_into_source",
          "shrink_into_source" not in read("_id_photo_helpers.py"))

    readme = read("README.md")
    check("README 不再出现 overflow_mode", "overflow_mode" not in readme)
    check("README 不再写「收缩到原图」", "收缩到原图" not in readme)
    check("README 说明补边按四边取色", "四条边" in readme)

    print("\n===== 合计 %d 项，FAIL %d =====" % (TOTAL, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
