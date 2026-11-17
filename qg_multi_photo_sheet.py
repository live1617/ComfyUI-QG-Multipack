"""多人证件照拼版：把 batch 里每个人的照片各占一格，拼到同一张纸上。

与 ``photo_sheet_node`` / ``photo_sheet_mixed_node`` 的区别：那两个是「一张
照片复制 N 份铺满相纸」，本节点是「N 张不同的照片（batch 每帧一人）各占
一格」。所以那边的 ``plan_sheet`` 用 cols×rows 乘算张数，这里的人数就是
batch 帧数，几何函数按帧数排布。

设计要点：
- 统一格：所有格子同尺寸，宽高比取**首帧照片**的比例。证件照是同一规格
  裁出来的，比例一致；居中裁切只处理个别比例不同的帧，不拉伸人脸。
- 列数由用户给定，行数 = ceil(人数 / 列数) 自动；实际列数 = min(列数, 人数)，
  避免一个人也铺出三个空格。最后一行不满时居中，不留一侧大空档。
- 放不下时可选等比缩小（fit_to_paper），关闭则明确报错「需要多少 / 可用多少」，
  不复刻上游那种 paste 静默裁切。
- 几何计算 ``plan_multi_sheet`` 是纯整数运算，不依赖 PIL / torch，便于断言。

本模块保持零相对导入：对照测试用 spec_from_file_location 单文件加载。
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
import torch
from PIL import Image, ImageColor, ImageDraw, ImageOps

CM_PER_INCH = 2.54


def cm_to_px(cm: float, dpi: int) -> int:
    """厘米换算像素，四舍五入。与 _sheet_helpers.cm_to_px 同口径。"""
    return int(round(float(cm) * float(dpi) / CM_PER_INCH))


class MultiSheetPlan(NamedTuple):
    canvas_w: int
    canvas_h: int
    count: int            # 实际拼进去的人数（帧数）
    cols: int             # 实际列数 = min(给定列数, 人数)
    rows: int
    cell_w: int
    cell_h: int
    origin_x: int
    origin_y: int
    step_x: int
    step_y: int
    spacing: int
    scale: float          # 放不下时的等比缩小系数，1.0 表示原尺寸放得下
    last_row_count: int   # 最后一行的实际人数（用于居中最后一行）


def plan_multi_sheet(count: int, aspect: float, paper_w_cm: float,
                     paper_h_cm: float, dpi: int, margin_cm: float,
                     spacing_cm: float, cols: int,
                     fit_to_paper: bool = True) -> MultiSheetPlan:
    """把 count 个人排进网格。aspect 是单格宽高比（宽 / 高）。

    纯整数几何：给定可用区域与列数，先定格宽，再按 aspect 定格高；行数随
    人数增长。放不下时按可用高度等比缩小格子，间距保持不变。
    """
    count = int(count)
    if count <= 0:
        raise ValueError("没有可拼版的图像：输入 batch 至少要有 1 帧")
    if aspect <= 0:
        raise ValueError("照片宽高比非法（宽或高为 0）")

    dpi = int(dpi)
    cols = max(1, min(int(cols), count))
    canvas_w = cm_to_px(paper_w_cm, dpi)
    canvas_h = cm_to_px(paper_h_cm, dpi)
    margin = cm_to_px(margin_cm, dpi)
    spacing = cm_to_px(spacing_cm, dpi)
    usable_w = canvas_w - 2 * margin
    usable_h = canvas_h - 2 * margin
    if usable_w <= 0 or usable_h <= 0:
        raise ValueError("页边距过大或纸张过小：可用区域为 %dx%d px"
                         % (usable_w, usable_h))

    rows = (count + cols - 1) // cols
    cell_w = max(1, (usable_w - (cols - 1) * spacing) // cols)
    cell_h = max(1, int(round(cell_w / aspect)))
    scale = 1.0

    total_h = rows * cell_h + (rows - 1) * spacing
    if total_h > usable_h:
        if not fit_to_paper:
            raise ValueError(
                "放不下：%d 行需要 %d px 高，页内只有 %d px（%d dpi）。"
                "可增大纸张、减小列数或开启等比缩小。"
                % (rows, total_h, usable_h, dpi))
        scale = usable_h / float(total_h)
        cell_w = max(1, int(cell_w * scale))
        cell_h = max(1, int(cell_h * scale))
        # 间距必须一起等比缩小：行数多时，n-1 条未缩的间距会把末行
        # 重新顶出页面（60 人 / 4 列实测末行 3804 px > 纸高 3508 px）。
        spacing = max(0, int(spacing * scale))
        total_h = rows * cell_h + (rows - 1) * spacing

    block_w = cols * cell_w + (cols - 1) * spacing
    block_h = total_h
    origin_x = margin + max(0, (usable_w - block_w) // 2)
    origin_y = margin + max(0, (usable_h - block_h) // 2)
    last_row_count = count - (rows - 1) * cols

    return MultiSheetPlan(
        canvas_w=canvas_w, canvas_h=canvas_h,
        count=count, cols=cols, rows=rows,
        cell_w=cell_w, cell_h=cell_h,
        origin_x=origin_x, origin_y=origin_y,
        step_x=cell_w + spacing, step_y=cell_h + spacing,
        spacing=spacing, scale=scale,
        last_row_count=last_row_count,
    )


def parse_color(value):
    """``#RGB`` / ``#RRGGBB`` / 颜色名 → (r, g, b)，非法回退白。"""
    try:
        rgb = ImageColor.getrgb(str(value or "").strip())
        return tuple(rgb[:3])
    except (ValueError, TypeError):
        return (255, 255, 255)


def _to_pil(frame):
    array = (frame.detach().cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
    return Image.fromarray(array[..., :3], "RGB").copy()


def _to_tensor(image):
    return torch.from_numpy(
        np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0)


def render_multi_sheet(frames, plan: MultiSheetPlan, bg_color="#FFFFFF",
                       border_px=0, border_color="#000000"):
    """按 plan 把每帧居中裁切进格子，拼成一张纸（PIL 图像）。"""
    canvas = Image.new("RGB", (plan.canvas_w, plan.canvas_h),
                       parse_color(bg_color))
    stroke = parse_color(border_color)
    border_px = max(0, int(border_px))
    size = (plan.cell_w, plan.cell_h)

    for index, frame in enumerate(frames[:plan.count]):
        row, col = divmod(index, plan.cols)
        if row == plan.rows - 1:
            col += (plan.cols - plan.last_row_count) // 2  # 最后一行居中
        x = plan.origin_x + col * plan.step_x
        y = plan.origin_y + row * plan.step_y
        # 兼容 PIL 与 tensor 两种帧（execute 传 PIL，测试/复用可传 tensor）
        pil = frame if isinstance(frame, Image.Image) else _to_pil(frame)
        crop = ImageOps.fit(pil.convert("RGB"), size,
                            method=Image.Resampling.LANCZOS)
        if border_px:
            draw = ImageDraw.Draw(crop)
            draw.rectangle([0, 0, size[0] - 1, size[1] - 1],
                           outline=stroke, width=min(border_px, size[0] // 2))
        canvas.paste(crop, (x, y))
    return canvas


class QGMultiPhotoSheet:
    CATEGORY = "QG 工具"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {
                    "tooltip": "多人证件照，每人一帧（batch）。同一人要多张就多放几帧，按帧顺序逐格排。",
                }),
                "paper_w": ("FLOAT", {
                    "default": 21.0, "min": 1.0, "max": 100.0, "step": 0.1,
                    "tooltip": "纸张宽度，厘米。A4 为 21.0。",
                }),
                "paper_h": ("FLOAT", {
                    "default": 29.7, "min": 1.0, "max": 100.0, "step": 0.1,
                    "tooltip": "纸张高度，厘米。A4 为 29.7。",
                }),
                "dpi": ("INT", {
                    "default": 300, "min": 72, "max": 3000, "step": 1,
                    "tooltip": "打印分辨率，纸张厘米 × dpi 决定出图像素。",
                }),
                "cols": ("INT", {
                    "default": 3, "min": 1, "max": 20, "step": 1,
                    "tooltip": "每行几人；行数按人数自动算。实际列数不超过人数。",
                }),
                "margin_cm": ("FLOAT", {
                    "default": 0.5, "min": 0.0, "max": 10.0, "step": 0.05,
                    "tooltip": "四周安全边距，厘米。",
                }),
                "spacing_cm": ("FLOAT", {
                    "default": 0.3, "min": 0.0, "max": 5.0, "step": 0.05,
                    "tooltip": "人与人之间的间距，厘米。",
                }),
                "fit_to_paper": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "人太多放不下时整体等比缩小格子；关闭则直接报错。",
                }),
            },
            "optional": {
                "bg_color": ("STRING", {
                    "default": "#FFFFFF",
                    "tooltip": "纸张底色，#RGB / #RRGGBB / 颜色名。默认白。",
                }),
                "border_px": ("INT", {
                    "default": 0, "min": 0, "max": 50, "step": 1,
                    "tooltip": "每格描边宽度，像素，画在格子内部。0 为不画。",
                }),
                "border_color": ("STRING", {
                    "default": "#000000",
                    "tooltip": "描边颜色，#RGB / #RRGGBB / 颜色名。",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "INT", "INT")
    RETURN_NAMES = ("sheet", "rows", "cols", "count")
    FUNCTION = "execute"

    def execute(self, image, paper_w, paper_h, dpi, cols, margin_cm,
                spacing_cm, fit_to_paper, bg_color="#FFFFFF",
                border_px=0, border_color="#000000"):
        batch = image if image.dim() == 4 else image.unsqueeze(0)
        frames = [_to_pil(batch[i]) for i in range(int(batch.shape[0]))]
        aspect = frames[0].width / float(frames[0].height)
        plan = plan_multi_sheet(len(frames), aspect, paper_w, paper_h, dpi,
                                margin_cm, spacing_cm, cols,
                                bool(fit_to_paper))
        sheet = render_multi_sheet(frames, plan, bg_color, border_px,
                                   border_color)
        print("[QG Multi Photo Sheet] %d 人 → %dx%d 格，单格 %dx%d px，"
              "纸张 %dx%d px（%d dpi，缩小 %.3f）"
              % (plan.count, plan.cols, plan.rows, plan.cell_w, plan.cell_h,
                 plan.canvas_w, plan.canvas_h, dpi, plan.scale))
        return (_to_tensor(sheet).unsqueeze(0), plan.rows, plan.cols,
                plan.count)


NODE_CLASS_MAPPINGS = {"QG_MultiPhotoSheet": QGMultiPhotoSheet}
NODE_DISPLAY_NAME_MAPPINGS = {
    "QG_MultiPhotoSheet": "QG 多人证件照拼版"
}
