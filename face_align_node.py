"""QG 面部对齐：把目标图的人脸缩放/旋转到与参考图的人脸对齐。

本节点是「参照功能规格的独立实现」（功能形态参考 Goohaitools
「孤海-面部对齐」，GPL-3.0），几何与统计逻辑自行编写：人脸检测复用
本包 _face_helpers（mediapipe 优先 + OpenCV Haar 回退 + .task 按需
下载，上游只支持 mediapipe），变换主流程按上游语义逐步实现。

与上游规格保持一致的语义：
- 多张脸取离图中心最近的一张；
- 有参考图且两边都检出人脸：按人脸面积比缩放整图
  （scale = sqrt(参考脸面积 / 目标脸面积)，面积取轮廓多边形鞋带
  面积，Haar 回退时退化为外接框面积），目标脸中心对齐参考脸中心，
  输出尺寸 = 参考图尺寸；
- 角度对齐：按眼线角差旋转（>90° 归一到 ±90° 内），旋转中心是
  缩放后的目标脸中心；无参考图时只把目标图绕图中心摆平；
- 扩展画布边长 = max(参考宽, 参考高, 缩放后对角线) × 2，旋转后按
  人脸对齐裁回参考尺寸，裁剪位置钳制在画布内；
- 填充色：自定义颜色（hex 解析）或边框颜色（四边像素 /10 取整统计
  前 5 名按频次加权平均），旋转空白区与裁剪底色同色。

刻意改进（均已注明）：上游的「面部置信度」控件实际没接进检测器，
本实现真正传给 FaceLandmarkerOptions；上游只支持 mediapipe，本实现
缺模型时自动按需下载、缺 mediapipe 时回退 OpenCV Haar（Haar 无轮廓
数据，面积退化为外接框近似）；下拉值英文存档（custom_color /
border_color），中文显示走前端 getOptionLabel。
"""

from __future__ import annotations

import math

import numpy as np
import torch
from PIL import Image

from . import _face_helpers
from .qg_dual_color_picker import normalize_hex

# 模块级常量不写类型标注：开发规范 §5（AST 扫描器只收 ast.Assign）
MODE_CHOICES = ["custom_color", "border_color"]
DEFAULT_FILL_COLOR = "#364254"
DEFAULT_CONFIDENCE = 0.3
_MAX_SCALE = 16.0   # 面积比异常时的缩放上限，防极端数值把内存打爆
_MIN_SCALE = 0.05
_MAX_CANVAS = 8192  # 旋转画布边长上限；再大就是 RGB 几 GB，必 MemoryError


def _tensor_to_rgb(image):
    """ComfyUI IMAGE [B, H, W, C] 取第一帧转 RGB uint8（0-1 浮点 → 0-255）。"""
    frame = image.detach().cpu().numpy()[0]
    return np.clip(frame * 255.0, 0, 255).astype(np.uint8)[:, :, :3]


def _polygon_area(points):
    """轮廓多边形鞋带面积；无轮廓（Haar 回退）返回 None。"""
    if points is None or len(points) < 3:
        return None
    arr = np.asarray(points, dtype=np.float64)
    x, y = arr[:, 0], arr[:, 1]
    return abs(float(np.dot(x, np.roll(y, -1)) -
                     np.dot(np.roll(x, -1), y))) / 2.0


def _face_area(face):
    area = _polygon_area(face.contour)
    if area is not None and area > 0:
        return area
    return max(face.width * face.height, 1.0)


def _border_color(rgb):
    """边框颜色：四边像素按 /10 取整统计，频次前 5 加权平均。"""
    h, w = rgb.shape[:2]
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    # 255/10 取整会得 260，clip 回 0-255 防止 PIL 颜色越界
    rounded = np.clip(np.round(border.astype(np.float32) / 10.0) * 10.0,
                      0, 255).astype(np.int64)
    packed = rounded[:, 0] * 1000000 + rounded[:, 1] * 1000 + rounded[:, 2]
    values, counts = np.unique(packed, return_counts=True)
    if len(values) == 0:
        return (255, 255, 255)
    top = np.argsort(-counts)[:5]
    weight = counts[top].astype(np.float64)
    r = (values[top] // 1000000 * counts[top]).sum() / weight.sum()
    g = (values[top] // 1000 % 1000 * counts[top]).sum() / weight.sum()
    b = (values[top] % 1000 * counts[top]).sum() / weight.sum()
    return (int(r), int(g), int(b))


def _parse_fill_color(text):
    """自定义填充色 hex → (r, g, b)；非法回退白色（与上游一致）。"""
    rgb = normalize_hex(text, "#FFFFFF")
    return (int(rgb[1:3], 16), int(rgb[3:5], 16), int(rgb[5:7], 16))


def _resolve_fill(fill_mode, custom_hex, rgb):
    if fill_mode == MODE_CHOICES[0]:
        return _parse_fill_color(custom_hex)
    return _border_color(rgb)


def _to_tensor(pil_image):
    arr = np.asarray(pil_image.convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(arr)[None,]


class QGFaceAlign:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "target_image": ("IMAGE",),
                "confidence": ("FLOAT", {
                    "default": DEFAULT_CONFIDENCE,
                    "min": 0.0, "max": 1.0, "step": 0.1,
                }),
                "angle_align": ("BOOLEAN", {"default": True}),
                "fill_mode": (MODE_CHOICES, {"default": "border_color"}),
                "custom_fill_color": ("STRING", {"default": DEFAULT_FILL_COLOR}),
            },
            "optional": {
                "reference_image": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "align"
    CATEGORY = "QG 工具"
    DESCRIPTION = (
        "Align the face of the target image to the reference face: scale by "
        "face-area ratio, rotate by eye-line angle difference and crop to the "
        "reference size; without a reference it only levels the target face."
    )

    def align(self, target_image, confidence, angle_align, fill_mode,
              reference_image=None, custom_fill_color=DEFAULT_FILL_COLOR):
        if fill_mode not in MODE_CHOICES:
            fill_mode = MODE_CHOICES[1]
        if target_image is None or len(target_image) == 0:
            # _tensor_to_rgb 里是 numpy()[0]，0 帧直接 IndexError；
            # reference 那边本来就有 len() 判断，target 漏了。
            raise ValueError(
                "QG 人脸对齐：目标图像是空的（batch 为 0 帧），"
                "检查上游是否把帧全部过滤掉了。")
        target_rgb = _tensor_to_rgb(target_image)
        target_pil = Image.fromarray(target_rgb)

        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = DEFAULT_CONFIDENCE
        target_face = _face_helpers.detect(target_rgb, "center", confidence)

        has_reference = reference_image is not None and len(reference_image) > 0
        reference_face = None
        reference_rgb = None
        if has_reference:
            reference_rgb = _tensor_to_rgb(reference_image)
            reference_face = _face_helpers.detect(
                reference_rgb, "center", confidence)

        # 情况 A：参考图 + 两边都检出人脸 → 缩放 + 旋转 + 对齐裁剪
        if has_reference and reference_face is not None and target_face is not None:
            ref_h, ref_w = reference_rgb.shape[:2]
            target_area = _face_area(target_face)
            scale = math.sqrt(_face_area(reference_face) / target_area) \
                if target_area > 0 else 1.0
            scale = max(_MIN_SCALE, min(scale, _MAX_SCALE))

            orig_w, orig_h = target_pil.size
            new_w, new_h = int(orig_w * scale), int(orig_h * scale)
            if new_w > 0 and new_h > 0:
                scaled = target_pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
            else:
                scaled, new_w, new_h = target_pil, orig_w, orig_h

            rotation = math.degrees(target_face.tilt - reference_face.tilt)
            if rotation > 90.0:
                rotation -= 180.0
            elif rotation < -90.0:
                rotation += 180.0

            fill = _resolve_fill(fill_mode, custom_fill_color, target_rgb)
            diagonal = int(math.hypot(new_w, new_h))
            # 参考脸很小、目标脸很大时 scale 顶到 16 倍，diagonal 能到十万像素级，
            # expanded 再乘 2 就是几十万平方的画布（RGB 几十 GB）→ 直接 OOM。
            # 裁到 _MAX_CANVAS 后极端情况会略微裁偏，但不会中断工作流。
            expanded = max(ref_w, ref_h, diagonal) * 2
            if expanded > _MAX_CANVAS:
                expanded = max(_MAX_CANVAS, ref_w, ref_h)
                print("[Face Align] 旋转画布超过 %d px，已收缩到 %d px（目标图被放大了 "
                      "%.1f 倍，输出会以参考图中心为准）" % (_MAX_CANVAS, expanded, scale))
            canvas = Image.new("RGB", (expanded, expanded), fill)
            paste_x = (expanded - new_w) // 2
            paste_y = (expanded - new_h) // 2
            canvas.paste(scaled, (paste_x, paste_y))

            center_x = target_face.center[0] * scale + paste_x
            center_y = target_face.center[1] * scale + paste_y

            if abs(rotation) > 0.1:
                rotated = canvas.rotate(
                    rotation, center=(center_x, center_y), expand=True,
                    resample=Image.BICUBIC, fillcolor=fill)
                rot_w, rot_h = rotated.size
                center_x += (rot_w - expanded) // 2
                center_y += (rot_h - expanded) // 2
            else:
                rotated, rot_w, rot_h = canvas, expanded, expanded

            crop_x = max(0, min(rot_w - ref_w, int(center_x - reference_face.center[0])))
            crop_y = max(0, min(rot_h - ref_h, int(center_y - reference_face.center[1])))
            result = rotated.crop((crop_x, crop_y,
                                   crop_x + ref_w, crop_y + ref_h))
            return (_to_tensor(result),)

        # 情况 B：无参考图（或没检出参考脸），只把目标图摆平
        if target_face is not None and angle_align:
            tilt_deg = math.degrees(target_face.tilt)
            if abs(tilt_deg) > 0.1:
                fill = _resolve_fill(fill_mode, custom_fill_color, target_rgb)
                orig_w, orig_h = target_pil.size
                result = target_pil.rotate(
                    tilt_deg, center=(orig_w / 2.0, orig_h / 2.0),
                    expand=True, resample=Image.BICUBIC, fillcolor=fill)
                return (_to_tensor(result),)
            return (target_image,)

        # 情况 C：没检出人脸 → 原样返回
        return (target_image,)


NODE_CLASS_MAPPINGS = {"QG_FaceAlign": QGFaceAlign}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_FaceAlign": "QG 面部对齐"}
