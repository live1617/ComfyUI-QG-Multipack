"""QG 取色器：点色块选一个颜色，按指定格式输出颜色控件值与字符串。

本节点是「参照功能规格的独立实现」（功能形态参考 Goohaitools「孤海 取色器」，
GPL-3.0），未复制任何第三方代码。与包内 QG_ColorConvert 的分工：

* QG_ColorConvert 是中间转换节点 —— 吃任意写法的色值字符串，转成目标格式；
* 本节点是颜色源节点 —— 直接拖出来点色块选色，按模式输出，作为工作流起点。

差异化的实现约定：
* 本包无 GHCOLOR 自定义 socket，两路输出都用 STRING，可接本包任意颜色/文本输入；
* 「颜色控件」输出与孤海一致保留输入的 3/6 位形态（小写），下游解析器都吃 3 位；
* 「字符串」输出严格对齐孤海：HEX 大写、RGB/HSL 逗号后带一个空格；
* 非法色值回退 #213d50，不把脏字符串透传给下游。
"""

from __future__ import annotations

import colorsys
import re

MODE_CHOICES = ["HEX", "RGB", "HSL"]
DEFAULT_COLOR = "#213d50"

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def normalize_color(value):
    """校验并规范化颜色：仅接受带 # 的 3/6 位十六进制，非法回退默认色。"""
    text = str(value if value is not None else "").strip().lower()
    return text if _HEX_RE.match(text) else DEFAULT_COLOR


def _hex_to_rgb01(value):
    """3/6 位 #hex 转 0-1 浮点三元组。"""
    code = value[1:]
    if len(code) == 3:
        code = "".join(c * 2 for c in code)
    return tuple(int(code[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def to_rgb_string(value):
    """#rrggbb → 'r, g, b'（逗号后带空格，与孤海取色器一致）。"""
    r, g, b = _hex_to_rgb01(value)
    return "%d, %d, %d" % (
        int(min(max(r * 255.0, 0.0), 255.0)),
        int(min(max(g * 255.0, 0.0), 255.0)),
        int(min(max(b * 255.0, 0.0), 255.0)),
    )


def to_hsl_string(value):
    """#rrggbb → 'h, s%, l%'（整数 H/S/L，逗号后带空格）。"""
    r, g, b = _hex_to_rgb01(value)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return "%d, %d%%, %d%%" % (
        int(round((h * 360.0) % 360.0)),
        int(round(s * 100.0)),
        int(round(l * 100.0)),
    )


class QGColorPicker:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "color": ("STRING", {"default": DEFAULT_COLOR}),
                "mode": (MODE_CHOICES, {"default": "HEX"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("color_control", "string")
    FUNCTION = "pick"
    CATEGORY = "QG 工具"
    DESCRIPTION = (
        "Pick a colour from the swatch widget and emit it as a normalized "
        "control value plus a formatted string (HEX / RGB / HSL)."
    )

    def pick(self, color, mode):
        value = normalize_color(color)
        if mode == "RGB":
            text = to_rgb_string(value)
        elif mode == "HSL":
            text = to_hsl_string(value)
        else:  # HEX，含未知模式兜底
            text = value.upper()
        return (value, text)


NODE_CLASS_MAPPINGS = {"QG_ColorPicker": QGColorPicker}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_ColorPicker": "QG 取色器"}
