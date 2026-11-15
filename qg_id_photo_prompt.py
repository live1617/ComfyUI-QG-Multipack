"""QG ID Photo Prompt - build an ID-photo portrait prompt from 13 dropdowns.

The functional spec follows Goohaitools' ``孤海-证件照简易提示词``: thirteen
dimensions (composition / nationality / gender / body shape / hair colour /
hairstyle / clothing colour / clothing style / accessory / makeup /
expression / background / extra accessory), each with "none" and "random",
plus a seed. The parts are joined into one comma-separated Chinese sentence
that can be wired straight into a text encoder.

This module is an independent implementation, not a copy of upstream source.
Differences that matter in daily use:

* **Combo values are stable ASCII keys** (``composition_01`` and so on), not
  Chinese literals. The Chinese label is display-only (front-end hook plus
  the two translation dictionaries), so renaming a label never breaks a saved
  workflow and the values are safe to store in a workflow / API payload.
* **Randomness is per dimension and local.** Upstream calls ``random.seed``
  on the process-global generator, which silently changes every other random
  consumer in the ComfyUI process. Here each dimension derives its own
  ``random.Random`` from the seed, so flipping one dropdown to ``random`` does
  not reshuffle all the other dimensions.
* **Background suffix is deduplicated.** Upstream appends ``简单背景`` to
  whatever the background value is, so picking the option ``简单背景`` yields
  ``简单背景简单背景``.
* ``seed`` accepts the full ComfyUI INT range and is clamped deterministically.

The option *labels* come from the public spec (they are data, not code); the
value generation, prompt assembly and front-end hook are written here.
"""

from __future__ import annotations

import random

# (control key, Chinese label, default label, concrete options)
# The first two options of every combo are always "none" and "random".
_COLOR_OPTIONS = [
    "中性色", "黑色", "白色", "灰色", "米色", "卡其色", "驼色", "冷色",
    "藏青色", "天蓝色", "宝蓝色", "浅蓝色", "墨绿色", "军绿色", "浅绿色",
    "暖色", "红色", "酒红色", "浅红色", "粉色", "玫粉色", "浅粉色",
    "橙色", "黄色", "浅黄色", "紫色", "浅紫色", "深紫色", "棕色",
    "咖啡色", "牛仔蓝", "荧光色", "荧光黄", "荧光绿", "金色", "银色",
]

_BACKGROUND_OPTIONS = ["简单背景"] + _COLOR_OPTIONS

DIMENSIONS = [
    ("composition", "构图", "人像面部特写", [
        "人像面部特写", "上半身近景特写", "中近景构图", "半身构图", "七分身构图",
    ]),
    ("nationality", "国籍", "中国", [
        "中国", "日本", "韩国", "东南亚", "印度", "中东", "俄罗斯", "北欧",
        "西欧", "南欧", "北美", "南美", "非洲", "原住民", "混血",
    ]),
    ("gender", "性别", "女孩", [
        "女孩", "男孩", "女人", "男人", "老人", "老奶奶", "老爷爷",
        "小女孩", "小男孩", "女婴儿", "男婴儿",
    ]),
    ("body_shape", "体型", "丰满的", [
        "纤细的", "苗条的", "丰满的", "肌肉发达的", "娇小的", "高挑的", "肥胖的",
    ]),
    ("hair_color", "发色", "亚麻棕", [
        "黑色", "蓝黑色", "茶黑色", "深棕色", "巧克力棕", "亚麻棕", "青木棕",
        "香槟金", "酒红色", "莓果红", "橘红色", "奶奶灰", "雾霾灰", "灰紫色",
        "蓝灰色", "孔雀蓝", "樱花粉", "玫瑰粉", "粉紫色", "奶茶色",
        "薰衣草紫", "珊瑚橙", "渐变色",
    ]),
    ("hairstyle", "发型", "random", [
        "飘逸长发", "波波头", "精灵短发", "露耳短发", "空气刘海", "中长发",
        "锁骨发", "波浪卷", "法式刘海", "齐刘海", "长发", "大波浪", "黑长直",
        "公主切", "高马尾", "复古背头", "复古卷发", "单马尾辫", "双马尾辫",
        "脏辫（Dreadlocks）", "丸子头发", "头包脸发型",
    ]),
    ("clothing_color", "服装颜色", "none", _COLOR_OPTIONS),
    ("clothing_style", "服装款式", "random", [
        "V领T恤", "圆领T恤", "衬衫", "V领衬衫", "POLO衫", "泡泡袖", "毛衣",
        "卫衣", "夹克", "西装外套", "V领正装", "风衣", "皮衣", "羽绒服",
        "高档婚纱", "高档礼服", "马甲", "连衣裙", "牛仔衣", "军装", "警服",
        "护士服", "厨师服", "校服", "白大褂", "睡衣", "旗袍", "包臀裙",
        "背带裤", "春装", "夏装", "秋装", "冬装",
    ]),
    ("accessory", "服饰佩饰", "random", [
        "领带", "格子领带", "斜纹领带", "领结", "蝴蝶结", "腰带", "围巾",
    ]),
    ("makeup", "妆容", "random", [
        "素颜", "淡妆", "日常妆", "清新妆", "素颜妆", "职场妆", "烟熏妆",
        "晚晏妆", "新娘妆", "舞台妆", "韩系妆", "日系妆", "中式古典妆",
        "复古妆", "欧美妆", "纯欲妆",
    ]),
    ("expression", "表情", "random", [
        "微笑", "大笑", "抿嘴笑", "甜甜的笑容和洁白的牙齿", "冷漠的表情", "冷笑",
    ]),
    ("background_color", "背景色", "简单背景", _BACKGROUND_OPTIONS),
    ("extra_accessory", "其他佩饰", "none", [
        "帽子", "眼镜", "细框眼镜", "粗框眼镜", "耳环", "耳钉", "项链",
        "头花", "发箍",
    ]),
]

# Prompt assembly order. Two-item groups share one segment with a space.
_BASE_ORDER = ("body_shape", "nationality", "gender")
_GROUPS = (
    ("composition",),
    ("hair_color", "hairstyle"),
    ("clothing_color", "clothing_style"),
    ("accessory",),
    ("expression",),
    ("makeup",),
    ("extra_accessory",),
)

NONE = "none"
RANDOM = "random"

_SEED_MASK = 0xFFFFFFFFFFFFFFFF


def option_values(dim):
    """ASCII values for one dimension: none, random, then ``<key>_NN``."""
    key = dim[0]
    return [NONE, RANDOM] + ["%s_%02d" % (key, i + 1) for i in range(len(dim[3]))]


def value_label_map():
    """``{ascii value: Chinese label}`` for every combo, plus none / random.

    This is the single source for the front-end label hook and the Menus
    translation dictionary; both are generated from it, so they cannot drift.
    """
    out = {NONE: "无", RANDOM: "随机"}
    for dim in DIMENSIONS:
        values = option_values(dim)[2:]
        for value, label in zip(values, dim[3]):
            out[value] = label
    return out


def value_for(dim, label):
    """Look up an ASCII value by its Chinese label (``none``/``random`` pass)."""
    if label == "无":
        return NONE
    if label == "随机":
        return RANDOM
    for value, item in zip(option_values(dim)[2:], dim[3]):
        if item == label:
            return value
    raise KeyError("unknown label %r for %s" % (label, dim[0]))


def label_for(dim, value):
    """Chinese label for a stored ASCII value; unknown values degrade safely."""
    if value == NONE:
        return ""
    if value == RANDOM:
        return "随机"
    for candidate, item in zip(option_values(dim)[2:], dim[3]):
        if candidate == value:
            return item
    return ""


def _dim_rng(seed, index):
    """A private generator per dimension, so dimensions cannot affect each other."""
    return random.Random((seed & _SEED_MASK) * 131071 + index * 104729 + 17)


def resolve(dim, value, seed, index):
    """Resolve one control to the Chinese fragment that goes into the prompt."""
    if value == NONE:
        return ""
    values = option_values(dim)[2:]
    if value == RANDOM:
        if not values:
            return ""
        return label_for(dim, _dim_rng(seed, index).choice(values))
    return label_for(dim, value)


def build_prompt(values, seed=0):
    """Pure function used by the node and by tests.

    ``values`` maps a dimension key to its stored ASCII value. Missing keys
    fall back to the dimension default, which keeps old workflows working when
    a dimension is added later.
    """
    seed = int(seed) & _SEED_MASK
    dims = {dim[0]: (dim, i) for i, dim in enumerate(DIMENSIONS)}
    defaults = {
        dim[0]: (dim[2] if dim[2] in (NONE, RANDOM, "无", "随机")
                 else value_for(dim, dim[2]))
        for dim in DIMENSIONS
    }
    resolved = {}
    for key, (dim, index) in dims.items():
        raw = values.get(key, defaults[key])
        if raw in ("无", "随机"):
            raw = NONE if raw == "无" else RANDOM
        resolved[key] = resolve(dim, raw, seed, index)

    parts = []
    base = [resolved[k] for k in _BASE_ORDER if resolved.get(k)]
    if base:
        parts.append("一个" + " ".join(base))
    for group in _GROUPS:
        segment = " ".join(x for x in (resolved.get(k) for k in group) if x)
        if segment:
            parts.append(segment)
    background = resolved.get("background_color", "")
    if background:
        parts.append(background if "背景" in background else background + "简单背景")
    return ", ".join(parts)


class QGIDPhotoPrompt:

    CATEGORY = "QG 工具"
    DESCRIPTION = (
        "Build one Chinese ID-photo portrait prompt from thirteen dropdowns "
        "(composition, nationality, gender, body shape, hair colour, "
        "hairstyle, clothing colour, clothing style, accessory, makeup, "
        "expression, background, extra accessory). Each dropdown can be "
        "turned off ('none') or set to 'random'; the seed makes the random "
        "pick reproducible. Combo values are stable ASCII keys and the "
        "Chinese labels are display-only, so renaming a label never breaks a "
        "saved workflow. Randomness is private to this node and derived per "
        "dimension, so it cannot disturb other nodes' random state. Wire the "
        "STRING output into a text encoder or into an ID-photo parameter node."
    )

    @classmethod
    def INPUT_TYPES(cls):
        required = {}
        for dim in DIMENSIONS:
            key, label, default, _items = dim
            values = option_values(dim)
            default_value = (default if default in (NONE, RANDOM, "无", "随机")
                             else value_for(dim, default))
            if default_value in ("无", "随机"):
                default_value = NONE if default_value == "无" else RANDOM
            required[key] = (values, {
                "default": default_value,
                "tooltip": "%s. 'none' omits it, 'random' picks one with the "
                           "seed. Values are stable ASCII keys; the Chinese "
                           "labels are display-only." % key,
            })
        required["seed"] = ("INT", {
            "default": 0, "min": 0, "max": _SEED_MASK, "step": 1,
            "tooltip": "Seed for the 'random' options. Same seed and same "
                       "dropdowns always produce the same prompt.",
        })
        return {"required": required}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "generate"
    OUTPUT_TOOLTIPS = ("The assembled Chinese portrait prompt.",)

    def generate(self, seed=0, **kwargs):
        text = build_prompt(kwargs, seed)
        print("[QG ID Photo Prompt] %s" % text)
        return (text,)


NODE_CLASS_MAPPINGS = {"QG_IDPhotoPrompt": QGIDPhotoPrompt}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_IDPhotoPrompt": "QG 证件照简易提示词"}
