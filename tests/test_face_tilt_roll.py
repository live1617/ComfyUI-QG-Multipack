# -*- coding: utf-8 -*-
"""人脸倾斜角稳健化（``Face.roll`` + 脸部对称交叉校验）的回归测试。

历史故障：用户拿一张 1080x1920 的全身照（左眼上半被刘海盖住），打开
「人脸矫正」之后，输出的头比原图还歪 —— 越矫越歪。

根因：mediapipe 把被遮挡的那只眼的整套 landmark 挪到了上眼睑上（偏上
25 px，约 1/3 个眼高）。两眼连线因此从真实的 -5.3°（右眼高）读成
+9.5°（右眼低），方向都反了；矫正按这个角度转，等于把歪斜翻倍。

覆盖：
  · ``Face.roll`` 覆盖 ``tilt``，``scaled`` 一路保留；
  · ``_pair_roll`` / ``_median`` 的边界行为；
  · ``_robust_roll``：与脸部对称一致时用眼线、冲突时改用脸部对称、
    参考点不足时仍用眼线、没有眼线时退回脸部对称；
  · 真实案例的四对硬结构坐标固化成用例（期望 -4.0°，不是 +9.5°）；
  · ``plan_frame`` 的旋转语义：输出眼线 = 源眼线 - tilt，且 tilt 等于源
    眼线时输出必须水平；
  · ``auto_rotate`` 的 label_on / label_off 是中文（前端不翻这两串）。

不依赖 ComfyUI 运行时、模型、网络或 GPL 参考源码。
运行：python_embeded\\python.exe tests\\test_face_tilt_roll.py
"""
import importlib
import importlib.util
import json
import math
import os
import sys

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
    name = "qgmp_tilt_roll_test"
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(PKG, "__init__.py"), submodule_search_locations=[PKG])
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[name] = pkg
    spec.loader.exec_module(pkg)
    return name


def read(path):
    with open(os.path.join(PKG, path), encoding="utf-8") as handle:
        return handle.read()


def make_points(pairs, size=478):
    """478 个点，只有关心的索引有坐标，其余落在原点。"""
    points = [(0.0, 0.0)] * size
    for index, xy in pairs.items():
        points[index] = (float(xy[0]), float(xy[1]))
    return points


def pair_points(left_id, right_id, x0, y0, dx, deg):
    """一对对称点，右点比左点低 ``deg`` 度（正值 = 右低，与 Face.tilt 同向）。"""
    return {left_id: (x0, y0),
            right_id: (x0 + dx, y0 + dx * math.tan(math.radians(deg)))}


# 真实案例（1080x1920 全身照，左眼被刘海遮住）：mediapipe 两眼连线 +9.5°，
# 而鼻翼 / 颧骨 / 下颌 / 太阳穴 四对实测 -5.09 / -3.82 / -4.24 / -3.41，
# 中位 -4.03°；同一张图的瞳孔像素测出来是 -5.3°。
REAL_ANGLES = {"nose": -5.09, "cheek": -3.82, "jaw": -4.24, "temple": -3.41}
REAL_POINTS = {}
REAL_POINTS.update(pair_points(129, 358, 100.0, 400.0, 100.0, -5.09))
REAL_POINTS.update(pair_points(234, 454, 80.0, 380.0, 100.0, -3.82))
REAL_POINTS.update(pair_points(172, 397, 70.0, 500.0, 100.0, -4.24))
REAL_POINTS.update(pair_points(127, 356, 60.0, 340.0, 100.0, -3.41))
REAL_EYE_ROLL = math.radians(9.52)
REAL_REFERENCE = -4.03


def forward(frame):
    """``frame.affine`` 是「输出→源」，这里求反向的「源→输出」。"""
    a, b, c, d, e, f = frame.affine
    det = a * e - b * d
    ia, ib = e / det, -b / det
    id_, ie = -d / det, a / det
    ic = -(ia * c + ib * f)
    if_ = -(id_ * c + ie * f)

    def to_output(point):
        return (ia * point[0] + ib * point[1] + ic,
                id_ * point[0] + ie * point[1] + if_)

    return to_output


def main():
    pkg_name = load_package()
    helpers = importlib.import_module(pkg_name + "._face_helpers")
    idphoto = importlib.import_module(pkg_name + "._id_photo_helpers")

    # ------------------------------------------------------------ Face.roll
    print("\n[1] Face.roll 覆盖 tilt，scaled 保留")
    box = (0.0, 0.0, 200.0, 260.0)
    eye_a, eye_b = (60.0, 100.0), (140.0, 116.0)
    plain = helpers.Face(box, eye_a, eye_b, "mock")
    raw = math.degrees(math.atan2(16.0, 80.0))
    check("不传 roll 时按眼点算", abs(math.degrees(plain.tilt) - raw) < 1e-6,
          "%.3f vs %.3f" % (math.degrees(plain.tilt), raw))
    check("不传 roll 时 roll 为 None", plain.roll is None, str(plain.roll))

    vetted = helpers.Face(box, eye_a, eye_b, "mock", roll=math.radians(-1.76))
    check("传 roll 时 tilt 用它",
          abs(math.degrees(vetted.tilt) + 1.76) < 1e-6,
          "%.3f" % math.degrees(vetted.tilt))
    check("roll 不影响眼睛排序",
          vetted.eye_a == (60.0, 100.0) and vetted.eye_b == (140.0, 116.0),
          str((vetted.eye_a, vetted.eye_b)))

    swapped = helpers.Face(box, eye_b, eye_a, "mock", roll=math.radians(-1.76))
    check("左眼右眼传反了也排好",
          swapped.eye_a[0] < swapped.eye_b[0], str(swapped.eye_a))

    scaled = vetted.scaled(2.0, 2.0)
    check("scaled 保留 roll",
          scaled.roll is not None
          and abs(math.degrees(scaled.tilt) + 1.76) < 1e-6,
          str(scaled.roll))
    check("scaled 缩放眼睛坐标",
          scaled.eye_a == (120.0, 200.0), str(scaled.eye_a))

    # -------------------------------------------------- _pair_roll / _median
    print("\n[2] _pair_roll / _median")
    points = make_points({129: (10.0, 20.0), 358: (110.0, 30.0)})
    left_first = helpers._pair_roll(points, (129,), (358,))
    right_first = helpers._pair_roll(points, (358,), (129,))
    check("同一对点顺序无关",
          abs(left_first - right_first) < 1e-9,
          "%.4f vs %.4f" % (left_first, right_first))
    check("角度方向正确",
          abs(math.degrees(left_first) - 5.7106) < 0.01,
          "%.4f°" % math.degrees(left_first))
    check("点不够时返回 None",
          helpers._pair_roll(points[:100], (129,), (358,)) is None)

    check("_median 奇数", helpers._median([3, 1, 2]) == 2, "")
    check("_median 偶数", helpers._median([4, 1, 3, 2]) == 2.5, "")
    check("_median 空输入", helpers._median([]) is None, "")

    # -------------------------------------------------------- _robust_roll
    print("\n[3] _robust_roll：一致用眼线，冲突用脸部对称")
    agree = {}
    for index, (ids_a, ids_b) in enumerate(helpers._ROLL_PAIRS):
        agree.update(pair_points(ids_a, ids_b, 100.0 + index * 5.0, 400.0,
                                 100.0, 0.4))
    eye_roll = math.radians(0.4)
    roll, note = helpers._robust_roll(eye_roll, make_points(agree))
    check("与参考一致时用眼线", abs(roll - eye_roll) < 1e-9, "%.4f" % roll)
    check("一致时不打日志", note == "", note)

    roll, note = helpers._robust_roll(REAL_EYE_ROLL, make_points(REAL_POINTS))
    got = math.degrees(roll)
    check("真实案例改用脸部对称（不是 +9.5°）", got < 0, "%+.2f°" % got)
    check("真实案例结果约 -4.0°", abs(got - REAL_REFERENCE) < 0.3,
          "%+.2f°" % got)
    check("冲突时给出日志", "eye line reads" in note, note)
    check("日志报出两个角度",
          "+9.5" in note and "-4.0" in note, note)

    roll, note = helpers._robust_roll(REAL_EYE_ROLL, make_points({})[:100])
    check("参考点不足时退回眼线", abs(roll - REAL_EYE_ROLL) < 1e-9,
          "%.4f" % roll)

    roll, note = helpers._robust_roll(None, make_points(REAL_POINTS))
    check("没有眼线时用脸部对称", roll is not None
          and abs(math.degrees(roll) - REAL_REFERENCE) < 0.3,
          "%+.2f" % math.degrees(roll) if roll is not None else "None")

    # 阈值边界：差 5° 不动，差 7° 才换
    just_under = math.radians(REAL_REFERENCE + 5.0)
    roll, note = helpers._robust_roll(just_under, make_points(REAL_POINTS))
    check("差 5° 仍在阈值内", abs(roll - just_under) < 1e-9 and note == "",
          "%.4f %r" % (roll, note))
    just_over = math.radians(REAL_REFERENCE + 7.0)
    roll, note = helpers._robust_roll(just_over, make_points(REAL_POINTS))
    check("差 7° 触发替换", abs(math.degrees(roll) - REAL_REFERENCE) < 0.3,
          "%+.2f°" % math.degrees(roll))

    # 参考点里有一条被拉偏，中位数不该跟着跑
    skewed = dict(REAL_POINTS)
    skewed.update(pair_points(172, 397, 70.0, 500.0, 100.0, 20.0))
    roll, _ = helpers._robust_roll(REAL_EYE_ROLL, make_points(skewed))
    check("单条参考被拉偏不影响中位", math.degrees(roll) < 0,
          "%+.2f°" % math.degrees(roll))

    # 侧脸：四对彼此都对不上，参考本身没有资格否决眼睛
    wild = {}
    for index, (ids_a, ids_b) in enumerate(helpers._ROLL_PAIRS):
        wild.update(pair_points(ids_a, ids_b, 100.0, 400.0 + index * 40.0,
                                100.0, (-15.0, -10.0, 10.0, 15.0)[index]))
    roll, note = helpers._robust_roll(REAL_EYE_ROLL, make_points(wild))
    check("参考自身离散时保留眼线", abs(roll - REAL_EYE_ROLL) < 1e-9
          and note == "", "%.4f %r" % (roll, note))

    # ------------------------------------------------ plan_frame 旋转语义
    print("\n[4] plan_frame：输出眼线 = 源眼线 - tilt")
    box = (40.0, 60.0, 240.0, 360.0)
    eye_a, eye_b = (90.0, 150.0), (190.0, 166.0)
    source_angle = math.degrees(math.atan2(eye_b[1] - eye_a[1],
                                           eye_b[0] - eye_a[0]))
    for deg in (-5.3, -1.76, 0.0, 3.5, 12.0):
        face = helpers.Face(box, eye_a, eye_b, "mock", roll=math.radians(deg))
        frame = idphoto.plan_frame(face, 295, 413, 0.42, 0.38, True)
        to_output = forward(frame)
        a_out, b_out = to_output(face.eye_a), to_output(face.eye_b)
        after = math.degrees(math.atan2(b_out[1] - a_out[1],
                                        b_out[0] - a_out[0]))
        check("tilt=%+.2f° 时输出 %+.2f°" % (deg, source_angle - deg),
              abs(after - (source_angle - deg)) < 0.05, "%.3f°" % after)

    # tilt 与源眼线相等时，输出必须完全水平 —— 这就是「摆平」的定义
    face = helpers.Face(box, eye_a, eye_b, "mock",
                        roll=math.radians(source_angle))
    frame = idphoto.plan_frame(face, 295, 413, 0.42, 0.38, True)
    to_output = forward(frame)
    a_out, b_out = to_output(face.eye_a), to_output(face.eye_b)
    after = math.degrees(math.atan2(b_out[1] - a_out[1],
                                    b_out[0] - a_out[0]))
    check("tilt 等于源眼线时输出水平", abs(after) < 0.05, "%.3f°" % after)

    # 关掉矫正时保持原样，连 roll 也不能偷偷转
    face = helpers.Face(box, eye_a, eye_b, "mock", roll=math.radians(-1.76))
    frame = idphoto.plan_frame(face, 295, 413, 0.42, 0.38, False)
    check("rotate=False 时 frame.tilt 为 0", frame.tilt == 0.0,
          str(frame.tilt))

    # ------------------------------------------------------------ 节点契约
    print("\n[5] auto_rotate 的中文标签与词表")
    crop_module = importlib.import_module(pkg_name + ".id_photo_crop_node")
    spec = crop_module.NODE_CLASS_MAPPINGS["QG_IDPhotoCrop"].INPUT_TYPES()["required"]
    config = spec["auto_rotate"][1]
    check("label_on 是中文", config.get("label_on") == "摆平",
          str(config.get("label_on")))
    check("label_off 是中文", config.get("label_off") == "保持倾斜",
          str(config.get("label_off")))
    check("tooltip 仍是英文（走词表）",
          isinstance(config.get("tooltip"), str)
          and config["tooltip"].isascii(), str(config.get("tooltip"))[:40])

    node_defs = json.loads(read("locales/zh/nodeDefs.json"))
    options = node_defs["QG_IDPhotoCrop"]["inputs"]["auto_rotate"]["options"]
    check("官方词表 options 仍是中文", "摆平" in options.values(), str(options))
    words = json.loads(read("translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"))
    check("汉化词表控件名是人脸矫正",
          words["QG_IDPhotoCrop"]["widgets"]["auto_rotate"] == "人脸矫正",
          str(words["QG_IDPhotoCrop"]["widgets"].get("auto_rotate")))

    readme = read("README.md")
    check("README 说明倾斜角交叉校验", "太阳穴" in readme, "")
    check("README 说明 label_on 不走词表", "label_on" in readme, "")

    print("\n===== 合计 %d 项，FAIL %d =====" % (TOTAL, FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
