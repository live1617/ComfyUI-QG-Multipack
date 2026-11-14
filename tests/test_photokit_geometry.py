# -*- coding: utf-8 -*-
"""PhotoKit 六个节点的几何与像素断言（并入 QG-Multipack 后放在 tests/）。

运行（必须在 python_embeded 环境）：
    python_embeded\\python.exe custom_nodes\\ComfyUI-QG-Multipack\\tests\\test_photokit_geometry.py

与包内其他测试的区别：本文件**不能**用 `import xxx as m` 的扁平写法。
六个节点模块用的是相对导入（`from ._face_helpers import ...`），只有在「包」语境下
才解析得了，所以这里把包根当成一个包加载，再按子模块名导入 —— 与 ComfyUI 实际的
加载方式一致。

断言写的是自洽关系，不是硬编码常量：
  · 裁剪：仿射把「输出画面中线 + eye_line」送回眼睛中心，误差 < 1e-6
  · 拼版：造刚体投影的卡片，拉正后四角颜色必须与原卡片一致
  · 排版：行列数由几何推出，不写死「应该是 3×3」
"""
import importlib
import importlib.util
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

FAILED = 0


def check(label, ok, detail=""):
    global FAILED
    if not ok:
        FAILED += 1
    print(f"  {label:<50}{'PASS' if ok else 'FAIL'}  {detail if not ok else ''}")


def load_package():
    """把插件根目录当成包加载，让相对导入成立。"""
    name = "qgmp_under_test"
    init = os.path.join(PKG, "__init__.py")
    if not os.path.isfile(init):
        raise SystemExit("找不到 %s，路径给错了？" % init)
    spec = importlib.util.spec_from_file_location(
        name, init, submodule_search_locations=[PKG])
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[name] = pkg
    spec.loader.exec_module(pkg)
    return name


def main():
    global FAILED
    pkg_name = load_package()
    H = importlib.import_module(pkg_name + "._id_photo_helpers")
    F = importlib.import_module(pkg_name + "._face_helpers")
    S = importlib.import_module(pkg_name + "._sheet_helpers")
    P = importlib.import_module(pkg_name + "._matte_pipeline")
    IC = importlib.import_module(pkg_name + "._idcard_helpers")

    # ------------------------------------------------------------- 注册
    print("\n[0] 六个节点模块能导入并注册")
    mods = ("id_photo_params_node", "portrait_matte_node", "id_photo_crop_node",
            "photo_sheet_node", "id_card_sheet_node", "watermark_node")
    seen = {}
    for m in mods:
        try:
            mod = importlib.import_module(pkg_name + "." + m)
            cm = getattr(mod, "NODE_CLASS_MAPPINGS", {})
            seen.update(cm)
            check("%-24s 注册 %d 个" % (m, len(cm)), bool(cm))
        except Exception as exc:                       # noqa: BLE001
            check("%-24s 导入失败" % m, False, str(exc))
    check("六个节点 ID 互不重复", len(seen) == 6, str(list(seen)))
    check("CATEGORY 全是「QG 工具」",
          all(getattr(v, "CATEGORY", "") == "QG 工具" for v in seen.values()))

    # ------------------------------------------------------------- 预设表
    print("\n[A] 预设表与像素换算")

    check("预设 20 项（19 个尺寸 + custom）", len(H.PRESETS) == 20,
          "实际 %d" % len(H.PRESETS))
    for key, spec_ in H.PRESETS.items():
        if spec_ is None:                     # custom
            continue
        w, h, unit, _ = spec_
        if unit != "cm":
            continue
        for dpi in (300, 350, 600):
            pw, ph, used = H.output_pixels(key, "cm", 0, 0, dpi)
            check("%-16s @%d 与厘米换算一致" % (key, dpi),
                  abs(pw - round(w / 2.54 * used)) <= 1
                  and abs(ph - round(h / 2.54 * used)) <= 1, "%dx%d" % (pw, ph))

    pw, ph, used = H.output_pixels("id_card_digital", "cm", 0, 0, 300)
    check("像素预设自带 dpi 覆盖入参", (pw, ph, used) == (358, 441, 350),
          "%dx%d @%d" % (pw, ph, used))
    pw, ph, _ = H.output_pixels("custom", "cm", 400, 500, 300)
    check("超大尺寸钳到 MAX_SIDE", max(pw, ph) <= H.MAX_SIDE, "%dx%d" % (pw, ph))
    try:
        H.output_pixels("custom", "px", 3.5, 4.9, 300)
        check("过小尺寸抛 ValueError", False, "没有抛")
    except ValueError:
        check("过小尺寸抛 ValueError", True)

    # --------------------------------------------------------------- 裁剪
    print("\n[B] 裁剪几何（仿射互逆）")
    Face = F.Face
    rng = np.random.default_rng(20261109)
    worst_pos = worst_w = 0.0
    for _ in range(300):
        w = float(rng.uniform(120, 600))
        h = float(rng.uniform(150, 700))
        x0 = float(rng.uniform(0, 800))
        y0 = float(rng.uniform(0, 800))
        eye_a = (x0 + w * 0.30, y0 + h * 0.40 + rng.uniform(-12, 12))
        eye_b = (x0 + w * 0.70, y0 + h * 0.40 + rng.uniform(-12, 12))
        face = Face((x0, y0, x0 + w, y0 + h), eye_a, eye_b, "selftest")
        out_w, out_h = 295, 413
        ratio = float(rng.uniform(0.30, 0.60))
        line = float(rng.uniform(0.30, 0.48))
        frame = H.plan_frame(face, out_w, out_h, ratio, line,
                             bool(rng.integers(0, 2)))
        a, b, c, d, e, f = frame.affine
        ex, ey = face.eye_center
        # PIL 的 AFFINE 是「输出 -> 输入」的逆向映射
        bx = a * (out_w / 2.0) + b * (line * out_h) + c
        by = d * (out_w / 2.0) + e * (line * out_h) + f
        worst_pos = max(worst_pos, abs(bx - ex), abs(by - ey))
        worst_w = max(worst_w, abs(frame.w - face.width / ratio))
    check("300 组：眼中心 <-> (中线, eye_line) 互逆", worst_pos <= 1e-6,
          "最大偏差 %.2e" % worst_pos)
    check("300 组：框宽 = 脸宽 / face_ratio", worst_w <= 1e-6,
          "最大偏差 %.2e" % worst_w)

    # --------------------------------------------------------------- 拼版
    print("\n[C] 身份证拼版（刚体投影）")
    import cv2
    W, HH, CW, CH = 850, 537, 1600, 1400
    RED, GREEN, BLUE, YELLOW = (220, 30, 30), (30, 160, 60), (30, 60, 200), (235, 205, 40)

    def make_card():
        src = np.full((HH, W, 3), 245, np.uint8)
        b = 70
        src[6:6 + b, 6:6 + b] = RED
        src[6:6 + b, W - 6 - b:W - 6] = GREEN
        src[HH - 6 - b:HH - 6, W - 6 - b:W - 6] = BLUE
        src[HH - 6 - b:HH - 6, 6:6 + b] = YELLOW
        cv2.rectangle(src, (4, 4), (W - 5, HH - 5), (60, 60, 60), 3)
        return src

    def project(card, theta, scale, turn=0):
        if turn:
            card = np.rot90(card, turn)
        hh, ww = card.shape[:2]
        q = np.float32([[0, 0], [ww - 1, 0], [ww - 1, hh - 1], [0, hh - 1]])
        a = np.radians(theta)
        R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]]) * scale
        return card, (q - np.array([ww / 2, hh / 2])) @ R.T + np.array([800, 700])

    def shoot(card, quad):
        canvas = np.full((CH, CW, 3), 202, np.uint8)
        M = cv2.getPerspectiveTransform(
            np.float32([[0, 0], [card.shape[1] - 1, 0],
                        [card.shape[1] - 1, card.shape[0] - 1], [0, card.shape[0] - 1]]),
            quad.astype(np.float32))
        shot = cv2.warpPerspective(card, M, (CW, CH), borderValue=(202, 202, 202))
        mask = np.zeros((CH, CW), np.uint8)
        cv2.fillConvexPoly(mask, quad.astype(np.int32), 255)
        return shot, mask

    def corners(img):
        hh, ww = img.shape[:2]
        o, s = 24, 10

        def px(y, x):
            return img[y:y + s, x:x + s].reshape(-1, 3).mean(0)

        return {"TL": px(o, o), "TR": px(o, ww - o - s),
                "BR": px(hh - o - s, ww - o - s), "BL": px(hh - o - s, o)}

    want = {"TL": RED, "TR": GREEN, "BR": BLUE, "BL": YELLOW}
    card0 = make_card()
    for label, theta, scale, turn in (("倾斜 12°", 12, 1.0, 0),
                                      ("大角度 40°", 40, 0.9, 0),
                                      ("竖放", 15, 0.95, 1),
                                      ("倒放 + 180° 修正", -20, 0.9, 3)):
        card, quad = project(card0, theta, scale, turn)
        shot, mask = shoot(card, quad)
        out = IC.warp_card(shot, IC.upright_quad(IC.mask_to_quad(mask)), W, HH)
        if turn == 3:
            out = np.ascontiguousarray(np.rot90(out, 2))
        cols = corners(out)
        bad = [k for k in want
               if max(abs(int(x) - int(y)) for x, y in zip(cols[k], want[k])) > 60]
        mae = float(np.abs(out.astype(float) - card0.astype(float)).mean())
        check("%-18s 四角颜色 + 色差" % label, not bad and mae < 22,
              "%s MAE=%.1f" % (",".join(bad) if bad else "四角对", mae))

    card, quad = project(card0, 10, 1.0, 0)
    shot, mask = shoot(card, quad)
    noisy = mask.copy()
    noisy[100:130, 1350:1400] = 255
    noisy[900:904, 60:64] = 255
    d = float(np.abs(IC.mask_to_quad(mask) - IC.mask_to_quad(noisy)).max())
    check("噪点耐受：四角偏移 <= 3px", d <= 3, "%.1f px" % d)
    check("反相判定：正常不误判 / 反相能认出",
          (not IC.looks_inverted(mask > 127)) and IC.looks_inverted(~(mask > 127)))

    # --------------------------------------------------------------- 排版
    print("\n[D] 排版几何")
    plan = S.plan_sheet(295, 413, 12.7, 8.9, 350, 0.2, 0.2, auto_orient=False)
    check("5 寸纸排一寸照：横版 5x2", (plan.cols, plan.rows) == (5, 2),
          "%dx%d" % (plan.cols, plan.rows))
    check("排布不越界", plan.block_w <= plan.canvas_w and plan.block_h <= plan.canvas_h,
          "block %dx%d / canvas %dx%d"
          % (plan.block_w, plan.block_h, plan.canvas_w, plan.canvas_h))
    turned = S.plan_sheet(413, 579, 12.7, 8.9, 350, 0.2, 0.2, auto_orient=True)
    kept = S.plan_sheet(413, 579, 12.7, 8.9, 350, 0.2, 0.2, auto_orient=False)
    check("原方向放不下时会去试翻转", turned.total > kept.total,
          "转向 %d vs 不转 %d" % (turned.total, kept.total))
    empty = S.plan_sheet(600, 800, 2.0, 2.0, 300, 0.2, 0.2)
    check("放不下时 cols=rows=0", (empty.cols, empty.rows) == (0, 0),
          "%dx%d" % (empty.cols, empty.rows))
    check("cm_to_px：2.54cm @300dpi = 300px", S.cm_to_px(2.54, 300) == 300)

    # --------------------------------------------------------------- 管线
    print("\n[E] 背景与美颜")
    top, bottom = (67, 142, 219), (27, 75, 143)
    for mode in ("pure", "vertical", "radial"):
        bg = np.asarray(P.make_background(400, 600, mode, top, bottom).convert("RGB"))
        hh = bg.shape[0]
        if mode == "pure":
            ok = np.allclose(bg[2, 2], top, atol=2)
        elif mode == "vertical":
            ok = np.allclose(bg[2, 2], top, atol=3) and np.allclose(bg[hh - 3, 2], bottom, atol=3)
        else:
            ok = np.allclose(bg[hh // 2, 200], top, atol=8)
        check("%-9s 端点颜色正确" % mode, ok, str(bg[2, 2].tolist()))

    rgb = np.full((60, 60, 3), 128, np.uint8)
    out = P.beauty(rgb, None, 0, 20, 20, 20, 2)
    check("beauty 输出仍是三通道", np.asarray(out).shape == rgb.shape)
    check("beauty 确实改了像素", not np.array_equal(np.asarray(out), rgb))
    check("全零强度不改图",
          np.array_equal(np.asarray(P.beauty(rgb, None, 0, 0, 0, 0, 0)), rgb))

    # --------------------------------------------------------------- 汇总
    print("\n" + "-" * 66)
    if FAILED:
        print("失败 %d 项" % FAILED)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
