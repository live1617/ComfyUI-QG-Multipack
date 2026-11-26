"""QG_IDPhotoParams - 证件照参数：尺寸、底色、渲染、dpi 打成一路，连给下游。

一个节点只干一件事：把"这张照片要什么样"集中说清楚。抠图换背景节点因此
只剩"怎么抠、怎么修"的参数，两边的职责不再混在一起。

底色是下拉不是文本框：写成 ``blue`` 那种 slug 要用户背单词，还容易打错一个
字母就得到中灰。下拉里的 slug 只在这里出现，界面上显示的是中文（见
``web/photokit_zh.js``）；真要别的颜色就选"自定义"，在旁边填色值。

顺带把算出来的像素宽高和 dpi 单独引出来 —— 排版节点的 ``photo_dpi`` 直接
接这根线就行，不用手抄数字（抄错就是印出来尺寸不对）。
"""

from __future__ import annotations

from ._id_photo_helpers import PRESET_ORDER, output_pixels
from ._matte_pipeline import BG_MODES, BG_NAMED, resolve_color
from .id_photo_crop_node import parse_color

PARAM_TYPE = "QG_IDPHOTO_PARAMS"

# 下拉里的 slug。最后一项是"自己填"，其余对应 _matte_pipeline.BG_NAMED。
BG_COLORS = ["white", "blue", "darkblue", "red", "lightblue", "gray", "custom"]
BG_COLORS_2 = [c for c in BG_COLORS if c != "custom"]


class QGIDPhotoParams:

    CATEGORY = "QG 工具"
    DESCRIPTION = (
        "证件照的「要什么」：尺寸预设、背景底色、渐变方式、打印 dpi。"
        "输出一路参数给抠图换背景节点，另外把算好的像素宽高与 dpi 单独引出来，"
        "排版节点的 photo_dpi 可以直接接。"
    )
    SEARCH_ALIASES = ["params", "尺寸", "证件照参数", "id photo params",
                      "背景颜色", "底色"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "preset": (PRESET_ORDER, {
                    "default": "1inch",
                    "tooltip": "成品尺寸。按像素给的预设（358x441 这类）自带 DPI，"
                               "会覆盖下面的 dpi。",
                }),
                "bg_color": (BG_COLORS, {
                    "default": "blue",
                    "tooltip": "背景主色。想要别的颜色选 custom，在旁边填 #RRGGBB。",
                }),
                "bg_custom": ("STRING", {
                    "default": "",
                    "tooltip": "只有背景颜色选 custom 时才用。填 #438edb 这种色值，"
                               "留空则退回蓝色。",
                }),
                "bg_color_2": (BG_COLORS_2, {
                    "default": "darkblue",
                    "tooltip": "渐变背景的第二色，纯色渲染时忽略。",
                }),
                "render": (BG_MODES, {
                    "default": "pure",
                    "tooltip": "pure 纯色 / vertical 上下渐变（主色在上）/ radial 中心渐变"
                               "（中心主色，四角第二色）。",
                }),
                "dpi": ("INT", {
                    "default": 300, "min": 72, "max": 2000, "step": 1,
                    "tooltip": "打印分辨率。300 是冲印标准，600 给的是双倍像素。",
                }),
                "custom_width": ("FLOAT", {
                    "default": 3.5, "min": 0.0, "max": 4096.0, "step": 0.01,
                    "tooltip": "只有大小选 custom 时才用，单位厘米 —— 要按像素出图就挑"
                               "对应像素的预设，别在这里填像素数。",
                }),
                "custom_height": ("FLOAT", {
                    "default": 4.9, "min": 0.0, "max": 4096.0, "step": 0.01,
                    "tooltip": "只有大小选 custom 时才用，单位厘米。",
                }),
            },
        }

    # 末尾追加 color_text：不影响既有 0-3 号槽，老工作流的连线不会错位。
    RETURN_TYPES = (PARAM_TYPE, "INT", "INT", "INT", "STRING")
    RETURN_NAMES = ("params", "width", "height", "dpi", "color_text")
    RETURN_TOOLTIPS = (
        "连给抠图换背景节点的 params 输入。",
        "算好的成品像素宽 —— custom 尺寸也按 dpi 换算过了。",
        "算好的成品像素高。",
        "实际用到的 dpi，像素预设会覆盖控件里的值。",
        "主背景色的 #RRGGBB 文本（渐变时取第一色），可直接连给取色/颜色节点。",
    )
    FUNCTION = "build"

    def build(self, preset, bg_color, bg_custom, bg_color_2, render, dpi,
              custom_width, custom_height):
        out_w, out_h, dpi_used = output_pixels(preset, "cm", custom_width,
                                               custom_height, dpi)

        color = str(bg_color)
        if color == "custom":
            typed = str(bg_custom or "").strip()
            # 选了自定义却什么都没填：退回蓝色，而不是让下游去解析字符串
            # "custom" 然后得到一个中灰。
            color = typed or "blue"

        params = {
            "preset": str(preset),
            "out_w": int(out_w),
            "out_h": int(out_h),
            "dpi": int(dpi_used),
            "bg_mode": str(render),
            "bg_color": color,
            "bg_color_2": str(bg_color_2) if bg_color_2 in BG_NAMED else "darkblue",
        }

        # 颜色文本：预设名（blue）先换成 #438edb，自定义的 #abc / 裸六位 / RGB
        # 三元组都交给 parse_color 统一成 RGB，再拼回标准 #rrggbb。和下游
        # 抠图节点拿到的是同一个色，不会出现「输出说蓝、渲染出来是灰」。
        rgb = parse_color(resolve_color(color), "ID Photo Params color_text")
        color_text = "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in rgb[:3])

        return (params, int(out_w), int(out_h), int(dpi_used), color_text)


NODE_CLASS_MAPPINGS = {"QG_IDPhotoParams": QGIDPhotoParams}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_IDPhotoParams": "QG 证件照参数"}
