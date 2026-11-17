"""QG_IDPhotoSizePicker - 证件照尺寸选择：只挑尺寸，输出给别的节点用。

同一套预设原本锁在两个节点各自的控件里（裁剪节点的 ``preset``、参数节点的
``preset``），想统一改一处尺寸就得两边各改一次。这个节点把"要多大"单独拎出来：
选一次，``preset`` 一路喂给下游的预设下拉，像素宽高与 dpi 单独引出来给排版、
生成、合成节点用。

⚠️ 第 1 槽的输出类型必须是 ``PRESET_ORDER`` 列表本身，不能写 "STRING"，
也不能写 "COMBO" —— 后端 ``comfy_execution.validation.validate_node_input``
拿到的 ``input_type`` 是下拉的**原始选项列表**（``graph.py`` 里 list→COMBO 的
转换被注释掉了），实测只有"与下游逐项相同的数组"才放行。前端再把槽类型对齐成
``"COMBO"``，由 ``web/qg_id_photo_size_picker.js`` 负责。

尺寸换算与裁剪节点共用 ``_id_photo_helpers.output_pixels``，所以同一个预设在这
两个节点里算出的像素一定相同；按像素给的预设（358x441 这类）自带 dpi，会把
控件里的 dpi 覆盖掉。
"""

from __future__ import annotations

from ._id_photo_helpers import PRESET_ORDER, output_pixels


class QGIDPhotoSizePicker:

    CATEGORY = "QG 工具"
    DESCRIPTION = (
        "证件照尺寸选择：一处选定预设，preset 输出可直接连证件照裁剪、证件照参数"
        "等节点的预设输入，同时输出换算好的像素宽高与实际 dpi。"
    )
    SEARCH_ALIASES = ["id photo size", "photo size", "尺寸选择", "证件照尺寸",
                      "一寸", "二寸", "证件照预设", "preset", "size picker"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # 下拉与下游裁剪节点同源：同一个 PRESET_ORDER，值一律英文 slug
                # （进存档、跨插件互通），中文显示由词表与前端 getOptionLabel 给。
                "preset": (list(PRESET_ORDER), {
                    "default": "1inch",
                    "tooltip": "成品尺寸。按像素给的预设（358x441 这类）自带 DPI，"
                               "会覆盖下面的 dpi。选 custom 才用自定义宽高。",
                }),
                "dpi": ("INT", {
                    "default": 300, "min": 72, "max": 2000, "step": 1,
                    "tooltip": "打印分辨率。300 是冲印标准；像素预设自带 dpi，不受这里影响。",
                }),
                "custom_width": ("FLOAT", {
                    "default": 3.5, "min": 0.0, "max": 4096.0, "step": 0.01,
                    "tooltip": "只有预设选 custom 时才用。单位由下面的 unit 决定。",
                }),
                "custom_height": ("FLOAT", {
                    "default": 4.9, "min": 0.0, "max": 4096.0, "step": 0.01,
                    "tooltip": "只有预设选 custom 时才用。",
                }),
                "unit": (["cm", "px"], {
                    "default": "cm",
                    "tooltip": "只有 custom 才用：厘米按 dpi 换算成像素，像素则填多少是多少。"
                               "标准预设自带的单位不受这里影响。",
                }),
            },
        }

    # 第 1 槽 = 选项列表（与下游 combo 输入逐项相等，后端才放行），前端再标 COMBO。
    RETURN_TYPES = (list(PRESET_ORDER), "INT", "INT", "INT")
    RETURN_NAMES = ("preset", "width", "height", "dpi")
    RETURN_TOOLTIPS = (
        "预设值，连给证件照裁剪 / 证件照参数等节点的预设下拉。",
        "换算好的成品像素宽。",
        "换算好的成品像素高。",
        "实际用到的 dpi —— 按像素给的预设会覆盖控件里的值。",
    )
    FUNCTION = "pick"

    def pick(self, preset, dpi, custom_width, custom_height, unit):
        out_w, out_h, dpi_used = output_pixels(preset, unit, custom_width,
                                               custom_height, dpi)
        return (str(preset), int(out_w), int(out_h), int(dpi_used))


NODE_CLASS_MAPPINGS = {"QG_IDPhotoSizePicker": QGIDPhotoSizePicker}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_IDPhotoSizePicker": "ID Photo Size Picker"}
