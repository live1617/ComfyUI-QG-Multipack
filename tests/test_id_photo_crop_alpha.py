# -*- coding: utf-8 -*-
"""QG_IDPhotoCrop 透明通道（RGBA）支持的回归测试。

历史故障：``_to_pil`` 用 ``Image.fromarray(..., "RGB")`` 强制三通道，上游
抠图节点（本包 BiRefNet 的 ``background=Alpha`` / QG_PortraitMatte）输出的
四通道 IMAGE 接进来直接抛 ``ValueError: Invalid mode for data type``。

覆盖：
  · 1 / 2 / 3 / 4 / 5 通道输入的归一化规则（不崩、通道选对）；
  · ``alpha_mode`` 是 optional 下拉，默认 fill，老工作流缺键也能跑；
  · fill：RGBA 输出 RGB，透明区落成 fill_color 的实心像素；
  · keep：RGBA 输出 RGBA，补边区与透明区 alpha = 0，主体 alpha 原样保留
    （``_fit_center`` 曾用图像自身当 mask paste，半透明 0.5 被乘成 0.25）；
  · 普通 RGB 图两种模式都仍输出三通道；
  · 整批模式按批决定，avoid torch.stack 通道数不一致；
  · 输出槽契约不变（IMAGE/MASK/BOOLEAN/INT/IMAGE）；
  · 两套词表、前端收起态标签、README 都登记了新控件与下拉值。

不依赖 ComfyUI 运行时、模型、网络、API Key 或 GPL 参考源码。
运行：python_embeded\\python.exe tests\\test_id_photo_crop_alpha.py
"""
import importlib
import importlib.util
import json
import os
import sys

import numpy as np
import torch

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
    name = "qgmp_crop_alpha_test"
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(PKG, "__init__.py"), submodule_search_locations=[PKG])
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[name] = pkg
    spec.loader.exec_module(pkg)
    return name


def read(rel):
    with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
        return fh.read()


def rgba_tensor(alpha, colour=(0.9, 0.9, 0.9), h=48, w=64):
    array = np.zeros((h, w, 4), dtype=np.float32)
    array[..., :3] = colour
    array[..., 3] = alpha
    return torch.from_numpy(array).unsqueeze(0)


def rgb_tensor(h=48, w=64):
    return torch.rand(1, h, w, 3, dtype=torch.float32)


def cutout_tensor(subject_alpha=1.0, h=48, w=64):
    """Cut-out shape: transparent margin, subject in the middle."""
    array = np.zeros((h, w, 4), dtype=np.float32)
    array[..., :3] = 0.9
    array[8:h - 8, 8:w - 8, 3] = subject_alpha
    return torch.from_numpy(array).unsqueeze(0)


def main():
    pkg = load_package()
    mod = importlib.import_module(pkg + ".id_photo_crop_node")
    cls = mod.NODE_CLASS_MAPPINGS["QG_IDPhotoCrop"]
    node = cls()

    def run(img, **kw):
        params = dict(image=img, preset="1inch", custom_width=0.0,
                      custom_height=0.0, unit="cm", dpi=300, face_ratio=0.42,
                      eye_line=0.38, auto_rotate=True, face_pick="center",
                      max_side=2000, fill_mode="custom", fill_color="#ff0000")
        params.update(kw)
        return node.execute(**params)

    print("\n[0] 空批次（0 帧）不崩")
    empty = torch.empty((0, 32, 32, 3), dtype=torch.float32)
    out = run(empty)
    check("空批次返回 5 个输出", len(out) == 5, str(len(out)))
    check("空批次图像是 0 帧", tuple(out[0].shape)[0] == 0,
          str(tuple(out[0].shape)))
    check("空批次遮罩是 0 帧", tuple(out[1].shape)[0] == 0,
          str(tuple(out[1].shape)))
    check("空批次 filled=False", out[2] is False, str(out[2]))
    check("空批次 dpi 仍按预设给出", int(out[3]) > 0, str(out[3]))
    check("空批次示意图仍是 [1,H,W,3]",
          len(tuple(out[4].shape)) == 4 and tuple(out[4].shape)[0] == 1
          and tuple(out[4].shape)[-1] == 3, str(tuple(out[4].shape)))
    empty_rgba = torch.empty((0, 32, 32, 4), dtype=torch.float32)
    out_rgba = run(empty_rgba, alpha_mode="keep")
    check("空批次 keep 保留四通道", tuple(out_rgba[0].shape)[-1] == 4,
          str(tuple(out_rgba[0].shape)))

    print("\n[1] 通道归一化（_to_pil）")
    to_pil = mod._to_pil
    for channels, mode, label in [(1, "RGB", "单通道"),
                                  (2, "RGB", "两通道"),
                                  (3, "RGB", "三通道"),
                                  (4, "RGBA", "四通道"),
                                  (5, "RGB", "五通道")]:
        arr = np.random.rand(16, 12, channels).astype(np.float32)
        got = to_pil(arr)
        check("%s -> %s" % (label, mode), got.mode == mode, got.mode)
    check("二维灰度 -> RGB", to_pil(np.random.rand(16, 12).astype(np.float32)).mode == "RGB")
    check("两通道取第一路（不被 alpha 染绿）",
          np.allclose(np.asarray(to_pil(
              np.stack([np.full((8, 8), 0.5), np.zeros((8, 8))], axis=-1)
              .astype(np.float32)))[..., 0], 128, atol=1))
    four = np.zeros((8, 8, 4), np.float32)
    four[..., :3] = 1.0
    four[..., 3] = 0.25
    as_rgba = np.asarray(to_pil(four))
    check("四通道保住 alpha", as_rgba.shape[-1] == 4 and 60 <= as_rgba[0, 0, 3] <= 67,
          "%d / %d" % (as_rgba.shape[-1], as_rgba[0, 0, 3]))

    print("\n[2] alpha_mode 是 optional 下拉，默认 fill")
    required, optional = cls.INPUT_TYPES()["required"], cls.INPUT_TYPES()["optional"]
    check("alpha_mode 不在 required（老工作流不报缺参）", "alpha_mode" not in required)
    check("alpha_mode 在 optional", "alpha_mode" in optional)
    spec = optional["alpha_mode"]
    check("值域 = fill / keep", list(spec[0]) == ["fill", "keep"], str(spec[0]))
    check("默认 fill", spec[1].get("default") == "fill")
    check("tooltip 讲清 transparent / alpha（源码注释用语为英文）",
          "transparent" in spec[1].get("tooltip", "").lower()
          and "alpha" in spec[1].get("tooltip", "").lower())
    import inspect
    sig = inspect.signature(cls.execute)
    check("execute 形参 alpha_mode 带默认值",
          sig.parameters["alpha_mode"].default == "fill")

    print("\n[3] 输出槽契约不变")
    check("五槽仍是 IMAGE/MASK/BOOLEAN/INT/IMAGE",
          cls.RETURN_TYPES == ("IMAGE", "MASK", "BOOLEAN", "INT", "IMAGE"),
          str(cls.RETURN_TYPES))
    check("输出名不变",
          cls.RETURN_NAMES == ("image", "mask", "filled", "dpi", "guide"),
          str(cls.RETURN_NAMES))
    check("image tooltip 提到 RGBA", "RGBA" in cls.OUTPUT_TOOLTIPS[0])

    print("\n[4] fill 模式（默认）：RGBA -> RGB，透明区填底色")
    out = run(rgba_tensor(0.0))
    img = np.asarray(out[0][0])
    check("不崩且输出三通道", img.shape[-1] == 3, str(img.shape))
    check("输出尺寸仍是 1 寸 295x413", img.shape[:2] == (413, 295), str(img.shape))
    corner = img[0, 0]
    check("透明补边区落成 fill_color 红",
          corner[0] > 0.9 and corner[1] < 0.1 and corner[2] < 0.1, str(corner))
    check("返回五元组", len(out) == 5)

    plain = run(rgba_tensor(1.0))
    check("不透明 RGBA 在 fill 下也输出 RGB",
          np.asarray(plain[0][0]).shape[-1] == 3)

    print("\n[5] keep 模式：RGBA -> RGBA，透明区保持透明")
    out = run(rgba_tensor(0.0), alpha_mode="keep")
    img = np.asarray(out[0][0])
    check("输出四通道", img.shape[-1] == 4, str(img.shape))
    check("补边区 alpha=0", img[0, 0, 3] < 0.01, "%.3f" % img[0, 0, 3])

    out = run(cutout_tensor(), alpha_mode="keep")
    img = np.asarray(out[0][0])
    mid = img[img.shape[0] // 2, img.shape[1] // 2, 3]
    check("补边区仍透明", img[0, 0, 3] < 0.01, "%.3f" % img[0, 0, 3])
    check("主体 alpha 保持不透明", mid > 0.99, "%.3f" % mid)

    out = run(cutout_tensor(subject_alpha=0.5), alpha_mode="keep")
    img = np.asarray(out[0][0])
    mid = img[img.shape[0] // 2, img.shape[1] // 2, 3]
    check("半透明主体 0.5 不被二次相乘（曾变 0.25）", 0.45 < mid < 0.55, "%.3f" % mid)

    print("\n[5b] 没有透明区的四通道 = 整体不透明度，不是抠图遮罩")
    # 整幅 alpha 均匀 0.5 的素材：保留它会把成品整体压成半透明，叠在深色
    # 画布上就是「裁剪后变色」——红底照看起来成了暗橙。
    for mode in ("fill", "keep"):
        out = run(rgba_tensor(0.5), alpha_mode=mode)
        img = np.asarray(out[0][0])
        mid = img[img.shape[0] // 2, img.shape[1] // 2]
        check("整幅 alpha=0.5 + %s -> 三通道" % mode, img.shape[-1] == 3, str(img.shape))
        check("整幅 alpha=0.5 + %s -> 不压暗（中心仍 0.9）" % mode,
              mid[0] > 0.85, "%.3f" % mid[0])
    out = run(rgba_tensor(1.0), alpha_mode="keep")
    check("alpha 全 1 + keep -> 三通道",
          np.asarray(out[0][0]).shape[-1] == 3)
    # 真抠图必须仍然保留透明：只有存在实际透明像素时才认这个通道。
    out = run(cutout_tensor(), alpha_mode="keep")
    img = np.asarray(out[0][0])
    check("有透明区的抠图 + keep -> 仍是四通道", img.shape[-1] == 4, str(img.shape))
    check("抠图补边区透明", img[0, 0, 3] < 0.05, "%.3f" % img[0, 0, 3])

    print("\n[6] RGB 输入两种模式都输出三通道")
    rgb = rgb_tensor()
    for mode in ("fill", "keep"):
        got = np.asarray(run(rgb, alpha_mode=mode)[0][0])
        check("RGB + %s -> 3 通道" % mode, got.shape[-1] == 3, str(got.shape))

    print("\n[7] 整批模式按批决定（torch.stack 不吃混合通道）")
    out = run(torch.cat([rgba_tensor(0.0), rgba_tensor(0.0)], dim=0),
              alpha_mode="keep")
    check("batch2 RGBA keep -> 四通道", np.asarray(out[0][0]).shape[-1] == 4)
    check("batch2 遮罩两帧", tuple(out[1].shape)[0] == 2, str(tuple(out[1].shape)))
    out = run(torch.cat([rgba_tensor(0.0), rgba_tensor(0.0)], dim=0))
    check("batch2 RGBA 默认 fill -> 三通道", np.asarray(out[0][0]).shape[-1] == 3)
    out = run(torch.cat([rgb, rgb], dim=0), alpha_mode="keep")
    check("batch2 RGB keep -> 三通道", np.asarray(out[0][0]).shape[-1] == 3)

    print("\n[8] 两套词表 / 前端 / README 已登记")
    nd = json.loads(read("locales/zh/nodeDefs.json"))["QG_IDPhotoCrop"]
    check("nodeDefs 有 alpha_mode", "alpha_mode" in nd["inputs"])
    check("nodeDefs 中文名 = 透明区域",
          nd["inputs"]["alpha_mode"]["name"] == "透明区域",
          nd["inputs"]["alpha_mode"].get("name", ""))
    check("nodeDefs 下拉值中文齐备",
          nd["inputs"]["alpha_mode"].get("options") ==
          {"fill": "填平透明", "keep": "保留透明"},
          str(nd["inputs"]["alpha_mode"].get("options")))

    tr = json.loads(read("translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"))["QG_IDPhotoCrop"]
    check("translations inputs 有 alpha_mode",
          tr["inputs"].get("alpha_mode") == "透明区域", str(tr["inputs"].get("alpha_mode")))
    check("translations widgets 有 alpha_mode",
          tr["widgets"].get("alpha_mode") == "透明区域", str(tr["widgets"].get("alpha_mode")))

    menus = json.loads(read("translations/zh-CN/Menus/ComfyUI-QG-Multipack.json"))
    check("Menus fill -> 填平透明", menus.get("fill") == "填平透明", str(menus.get("fill")))
    check("Menus keep -> 保留透明", menus.get("keep") == "保留透明", str(menus.get("keep")))

    js = read("web/qg_i18n.js")
    check("前端补了 QG_IDPhotoCrop 收起态标签", "QG_IDPhotoCrop" in js)
    block = js.split("QG_IDPhotoCrop", 1)[1][:400] if "QG_IDPhotoCrop" in js else ""
    check("前端 alpha_mode 有 fill/keep 中文",
          "alpha_mode" in block and "填平透明" in block and "保留透明" in block)

    readme = read("README.md")
    crop_doc = readme.split("### `QG_IDPhotoCrop` 证件照裁剪", 1)[-1][:2000]
    check("README 控件清单含 alpha_mode", "alpha_mode" in crop_doc)
    check("README 说明保留透明", "保留透明" in crop_doc)
    check("README 说明 RGBA 输入不再报错", "RGBA" in crop_doc)

    print("\n===== 合计 %d 项，FAIL %d =====" % (TOTAL, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
