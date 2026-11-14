"""QG 双色取色器：输出颜色模式、主色、辅色三个字符串。

本节点是「参照功能规格的独立实现」，未复制任何第三方代码。颜色输入在后端
保持 STRING（值进存档/API 可读、兼容老工作流），图形化色块由前端
web/qg_color_picker.js 接管绘制。

模式值一律英文（进存档、跨插件互通），中文显示由两份 i18n 词表与前端
getOptionLabel 提供。
"""

from __future__ import annotations

# 模块级常量不写类型标注：开发规范 §5（AST 扫描器只收 ast.Assign）
MODE_CHOICES = ["solid", "vertical_gradient", "radial_gradient"]

_HEX_DIGITS = frozenset("0123456789abcdef")
DEFAULT_PRIMARY = "#213d50"
DEFAULT_SECONDARY = "#402633"


def normalize_hex(value, fallback="#000000"):
    """把多种写法统一成小写 #rrggbb。

    接受：#rgb / #rrggbb / #rrggbbaa / 无 # 前缀 / (r, g, b) 元组。
    非法输入回退到 fallback，绝不把脏字符串透传给下游节点。
    """
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        try:
            channels = []
            for raw in value[:3]:
                num = int(raw)
                channels.append(max(0, min(255, num)))
            return "#%02x%02x%02x" % tuple(channels)
        except (TypeError, ValueError):
            return fallback

    text = str(value if value is not None else "").strip().lower()
    if text.startswith("#"):
        text = text[1:]

    if len(text) == 3 and all(c in _HEX_DIGITS for c in text):
        text = "".join(c * 2 for c in text)

    if len(text) >= 6 and all(c in _HEX_DIGITS for c in text[:6]):
        return "#" + text[:6]
    return fallback


class QGDualColorPicker:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (MODE_CHOICES, {"default": "solid"}),
                "primary_color": ("STRING", {"default": DEFAULT_PRIMARY}),
                "secondary_color": ("STRING", {"default": DEFAULT_SECONDARY}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("mode", "primary_color", "secondary_color")
    FUNCTION = "pick"
    CATEGORY = "QG 工具"
    DESCRIPTION = "Pick a colour mode plus two hex colours for downstream nodes."

    def pick(self, mode, primary_color, secondary_color):
        if mode not in MODE_CHOICES:
            mode = MODE_CHOICES[0]
        return (
            mode,
            normalize_hex(primary_color, DEFAULT_PRIMARY),
            normalize_hex(secondary_color, DEFAULT_SECONDARY),
        )


NODE_CLASS_MAPPINGS = {"QG_DualColorPicker": QGDualColorPicker}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_DualColorPicker": "QG 双色取色器"}
