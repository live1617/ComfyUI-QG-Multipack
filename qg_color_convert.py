"""QG 颜色转换：把多种写法的颜色字符串转成目标格式输出。

本节点是「参照功能规格的独立实现」（功能形态参考 Goohaitools「孤海 颜色
转换」，GPL-3.0），未复制任何第三方代码。输入接受 #hex / hex / RGB 整数 /
HSL 百分比 / 0-1 浮点等常见写法，统一解析后再按目标格式输出；解析失败回退
白色，绝不把脏字符串透传给下游。
"""

from __future__ import annotations

import colorsys
import re

# 模块级常量不写类型标注：开发规范 §5（AST 扫描器只收 ast.Assign）
FORMAT_CHOICES = ["#HEX", "HEX", "RGB", "HSL"]
DEFAULT_COLOR = "#FFFFFF"

_FULLWIDTH_MAP = {
    "，": ",",
    "（": "(",
    "）": ")",
    "　": " ",
}

_HEX_RE = re.compile(r"^#?([0-9a-f]{3}|[0-9a-f]{6})$")
_RGB_RE = re.compile(r"^\(?([0-9]{1,3}),([0-9]{1,3}),([0-9]{1,3})\)?$")
_HSL_RE = re.compile(r"^\(?([0-9]{1,3}),([0-9]{1,3})%,([0-9]{1,3})%\)?$")
_FLOAT_RE = re.compile(
    r"^(?:0(?:\.[0-9]+)?|1(?:\.0+)?),(?:0(?:\.[0-9]+)?|1(?:\.0+)?),"
    r"(?:0(?:\.[0-9]+)?|1(?:\.0+)?)$"
)


def _clean(text):
    """归一化输入：转小写、全角转半角、去掉所有空白。"""
    text = str(text if text is not None else "").strip().lower()
    for full, half in _FULLWIDTH_MAP.items():
        text = text.replace(full, half)
    return re.sub(r"\s+", "", text)


def _hex_to_rgb01(hex_code):
    """6 位 hex 转 0-1 浮点三元组（3 位在正则后已展开）。"""
    r = int(hex_code[0:2], 16) / 255.0
    g = int(hex_code[2:4], 16) / 255.0
    b = int(hex_code[4:6], 16) / 255.0
    return (r, g, b)


def parse_color(text):
    """把多种颜色写法解析成 0-1 浮点三元组，失败回退白色。"""
    text = _clean(text)

    m = _HEX_RE.match(text)
    if m:
        code = m.group(1)
        if len(code) == 3:
            code = "".join(c * 2 for c in code)
        return _hex_to_rgb01(code)

    m = _RGB_RE.match(text)
    if m:
        channels = [int(v) for v in m.groups()]
        if all(0 <= v <= 255 for v in channels):
            return tuple(v / 255.0 for v in channels)

    m = _HSL_RE.match(text)
    if m:
        h = int(m.group(1)) / 360.0
        s = int(m.group(2)) / 100.0
        l = int(m.group(3)) / 100.0
        return colorsys.hls_to_rgb(h, l, s)

    m = _FLOAT_RE.match(text)
    if m:
        parts = [float(v) for v in text.split(",")]
        if all(0.0 <= v <= 1.0 for v in parts):
            return tuple(parts)

    return (1.0, 1.0, 1.0)


def rgb_to_hsl360(r, g, b):
    """0-1 浮点 RGB 转 (0-360, 0-100, 0-100) 整数 HSL。"""
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return (
        int(round((h * 360.0) % 360.0)),
        int(round(s * 100.0)),
        int(round(l * 100.0)),
    )


def to_hex(r, g, b, with_hash=True):
    """0-1 浮点 RGB 转小写十六进制，with_hash 控制是否带 # 前缀。"""
    channels = [int(min(max(v * 255.0, 0.0), 255.0)) for v in (r, g, b)]
    code = "%02x%02x%02x" % tuple(channels)
    return ("#" + code) if with_hash else code


def normalize_hex(value, fallback="#000000"):
    """把任意可解析输入统一成小写 #rrggbb（颜色控件输出槽专用）。"""
    rgb = parse_color(value)
    return to_hex(*rgb, with_hash=True) if _clean(value) else fallback


class QGColorConvert:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "color": ("STRING", {"default": DEFAULT_COLOR}),
                "format": (FORMAT_CHOICES, {"default": "#HEX"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("string", "color_control")
    FUNCTION = "convert"
    CATEGORY = "QG 工具"
    DESCRIPTION = (
        "Parse a colour string in hex / RGB / HSL / 0-1 float notation and "
        "re-emit it in the chosen format, plus a normalized hex for colour "
        "widgets."
    )

    def convert(self, color, format):
        if format not in FORMAT_CHOICES:
            format = FORMAT_CHOICES[0]
        r, g, b = parse_color(color)

        if format == "#HEX":
            result = to_hex(r, g, b, with_hash=True)
        elif format == "HEX":
            result = to_hex(r, g, b, with_hash=False)
        elif format == "RGB":
            result = "%d,%d,%d" % (
                int(min(max(r * 255.0, 0.0), 255.0)),
                int(min(max(g * 255.0, 0.0), 255.0)),
                int(min(max(b * 255.0, 0.0), 255.0)),
            )
        else:  # HSL
            h, s, l = rgb_to_hsl360(r, g, b)
            result = "%d,%d%%,%d%%" % (h, s, l)

        control = to_hex(r, g, b, with_hash=True)
        return (result, control)


NODE_CLASS_MAPPINGS = {"QG_ColorConvert": QGColorConvert}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_ColorConvert": "QG 颜色转换"}
