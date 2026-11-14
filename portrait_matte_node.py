"""QG_PortraitMatte - 人像抠图换背景，出成品证件照。

链路：抠图（onnx）→ 美颜调色 → 人脸检测 → 摆平 → 按"脸占多少面积 / 头顶留
多少"裁 → 合成背景。和同包的证件照裁剪节点是上下游关系：这个出成品，那个
只负责把已有照片裁准。

三件事和参考实现不一样：

* **美颜只作用在 RGB 上，alpha 不参与。** 反过来做的话，抠图边缘那圈半透明
  像素会被调色拉到背景色，合成后头像描了一圈黑边。
* **头顶取 alpha 最上面那行"有肉"的行**，不是人脸框顶。人脸框止于发际线，
  证件照要看的是头发顶，两者能差出一大截。
* **背景直接在目标尺寸上生成**，不是先画一张大的再缩 —— 渐变缩放后边缘会
  出现一条色带。
"""

from __future__ import annotations

import math
import os

import numpy as np
import torch
from PIL import Image

from . import _matte_models as M
from ._face_helpers import backend_status, detect
from ._id_photo_helpers import output_pixels
from ._matte_pipeline import (
    BG_MODES, alpha_rows, beauty, composite, crop_fill, load_lut,
    make_background, plan_crop, resolve_color,
)
from .id_photo_params_node import PARAM_TYPE
from .id_photo_crop_node import parse_color

# 平铺进包根后 __file__ 就在包根，assets/ 是同级目录
_LUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "assets", "lut_origin.png")

# 下拉常驻显示预置模型名（即使本地还没下载），本地 discover 命中的额外合并进来。
# 注意：下拉选项必须在 INPUT_TYPES() 内现取（见下方），不能在 import 时冻结——
# 否则用户事后手动丢进 background_removal/ 的 .onnx 要重启才出现（开发规范 §8）。
DEFAULT_MODEL = "modnet_photographic_portrait_matting"


def _to_pil(frame_rgb):
    arr = np.clip(frame_rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    elif arr.shape[2] == 1:
        arr = np.repeat(arr, 3, axis=2)
    elif arr.shape[2] > 3:
        arr = arr[:, :, :3]
    return Image.fromarray(arr, "RGB")


def _fit_center(pil, alpha, out_w, out_h, bg):
    """没有脸时的兜底：整图等比装进目标尺寸并居中。

    交回原尺寸会打乱下游所有按这个尺寸算好的节点，所以宁可装进去。
    """
    scale = min(out_w / float(pil.width), out_h / float(pil.height))
    new_w = max(1, int(round(pil.width * scale)))
    new_h = max(1, int(round(pil.height * scale)))
    fg = pil.resize((new_w, new_h), Image.LANCZOS)
    a = Image.fromarray(alpha, "L").resize((new_w, new_h), Image.LANCZOS)
    canvas = bg.copy()
    left, top = (out_w - new_w) // 2, (out_h - new_h) // 2
    canvas.paste(fg, (left, top), a)
    mask = np.zeros((out_h, out_w), dtype=np.float32)
    mask[top:top + new_h, left:left + new_w] = np.asarray(a, dtype=np.float32) / 255.0
    return canvas, mask


class QGPortraitMatte:

    CATEGORY = "QG 工具"
    DESCRIPTION = (
        "把人像从背景里抠出来，换纯色或渐变底，再按证件照的构图裁好。"
        "抠图模型从 models/background_removal 里找（找不到会退到 HivisionIDPhotos "
        "插件自带的 weights）。裁剪口径按国标：head_height 是头部（头发顶到下巴）占"
        "画面高度的比例，top_distance 是头发顶到画面上沿占框高的比例。"
        "输出成品图、目标尺寸的蒙版，以及一张长边不小于 600 像素的高清版。"
    )
    SEARCH_ALIASES = ["matting", "background", "抠图", "人像抠图", "换底",
                      "换背景", "证件照", "id photo", "portrait matte", "bg"]

    @classmethod
    def VALIDATE_INPUTS(cls, preset=None, unit=None, bg_mode=None,
                        matting_model=None):
        return True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "matting_model": (M.available_choices(), {
                    "default": DEFAULT_MODEL,
                    "tooltip": "抠图模型。modnet 系快（512 输入），rmbg / birefnet 慢但"
                               "边缘更准。把 .onnx 放进 ComfyUI/models/background_removal "
                               "就会出现在这个列表里。",
                }),
                "face_alignment": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "把画面转到双眼水平，超过 2 度才动。关掉则保持原始倾斜。",
                }),
                "change_bg_only": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "只换背景，不裁剪不缩放。适合先看看抠图干不干净。",
                }),
                "crop_only": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "只裁剪，不抠图。此时蒙版全 1，背景保持原样。",
                }),
                "head_height": ("FLOAT", {
                    "default": 0.667, "min": 0.40, "max": 0.95, "step": 0.005,
                    "tooltip": "头部（头发顶到下巴）占画面的高度比例。国标要求大约 2/3，"
                               "护照是 58%~69%。这个口径与纸型无关 —— 方版和竖版算出来"
                               "是同一个头高比；原来那个面积比会随宽高比漂。",
                }),
                "top_distance": ("FLOAT", {
                    "default": 0.06, "min": 0.0, "max": 0.5, "step": 0.01,
                    "tooltip": "头顶（头发顶，不是人脸框顶）到画面上沿的距离，占裁剪框高度的"
                               "比例。0.06 与参考实现的实测构图一致；想要更多留白就往大调，"
                               "0.12 是国标上限那一档。",
                }),
                "whitening_strength": ("INT", {
                    "default": 2, "min": 0, "max": 15, "step": 1,
                    "tooltip": "美白强度。0 关，10 是满强度，15 等于再叠一次。",
                }),
                "brightness_strength": ("INT", {
                    "default": 0, "min": -50, "max": 50, "step": 1,
                    "tooltip": "亮度，直接加在像素值上。",
                }),
                "contrast_strength": ("INT", {
                    "default": 0, "min": -50, "max": 50, "step": 1,
                    "tooltip": "对比度，百分比增益。",
                }),
                "saturation_strength": ("INT", {
                    "default": 0, "min": -50, "max": 50, "step": 1,
                    "tooltip": "饱和度，百分比。",
                }),
                "sharpen_strength": ("INT", {
                    "default": 0, "min": 0, "max": 5, "step": 1,
                    "tooltip": "锐化强度。证件照建议 1~2，5 已经很硬。",
                }),
            },
            "optional": {
                "params": (PARAM_TYPE, {
                    "tooltip": "接「证件照参数」节点的输出 —— 尺寸、底色、渲染、dpi 都在"
                               "那一头。不接就用一寸、蓝底、300 dpi。",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "IMAGE")
    RETURN_NAMES = ("image", "mask", "hd")
    RETURN_TOOLTIPS = (
        "成品图：目标尺寸，背景已换。",
        "成品尺寸的蒙版：1 是人像，0 是背景。",
        "同样构图的高清版，长边不小于 600 像素 —— 拿去排版或再放大用这张。",
    )
    FUNCTION = "execute"

    def execute(self, image, matting_model, face_alignment, change_bg_only,
                crop_only, head_height, top_distance,
                whitening_strength, brightness_strength, contrast_strength,
                saturation_strength, sharpen_strength, params=None):

        if change_bg_only and crop_only:
            raise ValueError(
                "「仅换背景」和「仅裁剪」不能同时打开：前者跳过裁剪，后者跳过抠图，"
                "同时开会得到一张原图。")

        # 本地有就用本地；没有就按需下载（预置清单里的模型）。crop_only 不碰模型。
        model_path = None if crop_only else M.resolve(matting_model)
        if model_path is None and not crop_only:
            raise ValueError(
                "找不到抠图模型 %r，自动下载也失败了。把 .onnx 放进 "
                "ComfyUI/models/background_removal/ 就会出现在列表里；"
                "只想裁剪就把 crop_only 打开。" % (matting_model,))

        spec = self._resolve_params(params)
        out_w, out_h, dpi_used = spec["out_w"], spec["out_h"], spec["dpi"]
        top_rgb = parse_color(resolve_color(spec["bg_color"]),
                              "Portrait Matte bg_color")
        bottom_rgb = parse_color(resolve_color(spec["bg_color_2"]),
                                 "Portrait Matte bg_color_2")
        lut = load_lut(_LUT_PATH)
        mode = spec["bg_mode"]
        model_name = os.path.basename(model_path) if model_path else "无（只裁剪）"

        batch = image if image.dim() == 4 else image.unsqueeze(0)
        outs, masks, hds = [], [], []
        misses = 0
        first_note = ""

        for index in range(int(batch.shape[0])):
            pil = _to_pil(batch[index].cpu().numpy())
            src = np.asarray(pil)

            # 1. 抠图（用原图，别用调色后的图 —— 调色会改变边缘对比度）
            if crop_only:
                alpha = np.full(src.shape[:2], 255, dtype=np.uint8)
            else:
                alpha = M.matte_alpha(src, model_path)

            # 2. 美颜只动 RGB，alpha 原样留着
            rgb = beauty(src, lut, whitening_strength, brightness_strength,
                         contrast_strength, saturation_strength, sharpen_strength)
            fg_img = Image.fromarray(rgb, "RGB")

            # 3. 只换背景：不裁不缩，输出原尺寸
            if change_bg_only:
                bg = make_background(fg_img.width, fg_img.height, mode,
                                     top_rgb, bottom_rgb)
                out = composite(rgb, alpha, bg)
                arr = np.asarray(out, dtype=np.float32) / 255.0
                outs.append(arr)
                masks.append(np.asarray(alpha, dtype=np.float32) / 255.0)
                hds.append(arr)
                continue

            # 4. 检测 + 摆平
            face = detect(np.asarray(fg_img), "center")
            if face is not None and face_alignment and \
                    abs(math.degrees(face.tilt)) > 2.0:
                fg_img, alpha = self._rotate(fg_img, alpha,
                                             math.degrees(face.tilt), top_rgb)
                face = detect(np.asarray(fg_img), "center")

            # 5. 没脸：等比装入，尺寸承诺不破
            if face is None:
                misses += 1
                bg = make_background(out_w, out_h, mode, top_rgb, bottom_rgb)
                out, mask = _fit_center(fg_img, alpha, out_w, out_h, bg)
                arr = np.asarray(out, dtype=np.float32) / 255.0
                outs.append(arr)
                masks.append(mask)
                hds.append(arr)
                continue

            # 6. 裁剪框：头顶优先用 alpha 顶行
            rows = alpha_rows(alpha)
            head_top = rows[0] if rows else face.y0
            plan = plan_crop((face.x0, face.y0, face.x1, face.y1), head_top,
                             out_w, out_h, head_height, top_distance)
            box = (plan.x0, plan.y0, plan.x0 + plan.w, plan.y0 + plan.h)

            fg_cut = crop_fill(fg_img, box, top_rgb)
            a_cut = crop_fill(Image.fromarray(alpha, "L"), box, (0, 0, 0))

            # 7. 成品：背景按目标尺寸直接生成
            bg = make_background(out_w, out_h, mode, top_rgb, bottom_rgb)
            out = bg.copy()
            fg_small = fg_cut.resize((out_w, out_h), Image.LANCZOS)
            a_small = a_cut.resize((out_w, out_h), Image.LANCZOS)
            out.paste(fg_small, (0, 0), a_small)

            # 8. 高清版：同构图，长边不小于 600
            long_side = max(600, out_w, out_h)
            scale = long_side / float(max(out_w, out_h))
            hd_w = max(1, int(round(out_w * scale)))
            hd_h = max(1, int(round(out_h * scale)))
            hd = make_background(hd_w, hd_h, mode, top_rgb, bottom_rgb)
            hd.paste(fg_cut.resize((hd_w, hd_h), Image.LANCZOS), (0, 0),
                     a_cut.resize((hd_w, hd_h), Image.LANCZOS))

            outs.append(np.asarray(out, dtype=np.float32) / 255.0)
            masks.append(np.asarray(a_small, dtype=np.float32) / 255.0)
            hds.append(np.asarray(hd, dtype=np.float32) / 255.0)

            if index == 0:
                head_share = (face.y1 - head_top) / plan.h
                first_note = (" | 头高 %.1f%% (目标 %.1f%%) | 头顶留白 %.1f%% (目标 %.1f%%)"
                              % (100.0 * head_share, 100.0 * head_height,
                                 100.0 * plan.top_gap, 100.0 * top_distance))

        if misses:
            print("[Portrait Matte] %d/%d 帧没找到可用人脸，已等比装入目标尺寸"
                  "（检测后端：%s）" % (misses, batch.shape[0], backend_status()))
        print("[Portrait Matte] %dx%d -> %dx%d @%d dpi | 模型 %s | 背景 %s%s"
              % (pil.width, pil.height, out_w, out_h, dpi_used, model_name,
                 mode, first_note))

        return (torch.from_numpy(np.stack(outs, axis=0)),
                torch.from_numpy(np.stack(masks, axis=0)),
                torch.from_numpy(np.stack(hds, axis=0)))

    @staticmethod
    def _resolve_params(params):
        """把「证件照参数」节点的输出读成几个数。

        没接参数节点、或者接到的是旧版本存的 dict（字段不全）时，退回一寸
        蓝底 300 dpi —— 拆成两个节点不该让没接线的工作流跑不起来。
        """
        if isinstance(params, dict):
            out_w = int(params.get("out_w") or 0)
            out_h = int(params.get("out_h") or 0)
            if out_w >= 8 and out_h >= 8:
                mode = str(params.get("bg_mode") or "pure")
                return {
                    "out_w": out_w,
                    "out_h": out_h,
                    "dpi": int(params.get("dpi") or 300),
                    "bg_mode": mode if mode in BG_MODES else "pure",
                    "bg_color": params.get("bg_color") or "blue",
                    "bg_color_2": params.get("bg_color_2") or "darkblue",
                }
        default_w, default_h, default_dpi = output_pixels("1inch", "cm",
                                                          0.0, 0.0, 300)
        return {"out_w": default_w, "out_h": default_h, "dpi": default_dpi,
                "bg_mode": "pure", "bg_color": "blue",
                "bg_color_2": "darkblue"}

    @staticmethod
    def _rotate(pil_fg, alpha, angle, fill_rgb):
        """RGB 与 alpha 一起转。alpha 的空白处补 0，不是补白 —— 补白等于把人
        抠出来又贴回去一块白影子。"""
        fg = pil_fg.rotate(angle, resample=Image.BICUBIC, expand=True,
                           fillcolor=tuple(int(v) for v in fill_rgb[:3]))
        a = Image.fromarray(alpha, "L").rotate(angle, resample=Image.BICUBIC,
                                               expand=True, fillcolor=0)
        return fg, np.asarray(a)


NODE_CLASS_MAPPINGS = {"QG_PortraitMatte": QGPortraitMatte}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_PortraitMatte": "Portrait Matte"}
