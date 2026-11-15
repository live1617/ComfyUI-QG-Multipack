# -*- coding: utf-8 -*-
"""QG_IDPhotoPrompt 证件照简易提示词：规格对照 + 行为 + 词表一致性。

规格对照走 tests/ref_helper.py（GPL 参考源码只读）。运行前需设置
``QG_GOOHAI_REF_ROOT`` 指向 Goohaitools-comfyui 根目录；参考缺失时
按项目纪律 exit=2，绝不静默 SKIP。
"""
import ast
import importlib.util
import json
import os
import pathlib
import random
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ref_helper import require_ref  # noqa: E402

PKG = HERE.parent
spec = importlib.util.spec_from_file_location(
    "qg_ipp_test", str(PKG / "qg_id_photo_prompt.py"))
IPP = importlib.util.module_from_spec(spec)
spec.loader.exec_module(IPP)

ok = 0
fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS", name)
    else:
        fail += 1
        print("FAIL", name, detail)


# ---------- 1. 规格对照（GPL 参考源码，只读） ----------
REF_FILE = pathlib.Path(require_ref("nodes", "证件照简易提示词.py"))
tree = ast.parse(REF_FILE.read_text(encoding="utf-8"))
ref_required = None
for node in ast.walk(tree):
    if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
        for key, val in zip(node.value.keys, node.value.values):
            if isinstance(key, ast.Constant) and key.value == "required":
                ref_required = ast.literal_eval(val)
check("参考源码 INPUT_TYPES.required 可解析", isinstance(ref_required, dict))
ref_required = ref_required or {}

REF_DIMS = [
    ("构图", "composition"), ("国籍", "nationality"), ("性别", "gender"),
    ("体型", "body_shape"), ("发色", "hair_color"), ("发型", "hairstyle"),
    ("服装颜色", "clothing_color"), ("服装款式", "clothing_style"),
    ("服饰佩饰", "accessory"), ("妆容", "makeup"), ("表情", "expression"),
    ("背景色", "background_color"), ("其他佩饰", "extra_accessory"),
]
check("13 个维度", len(IPP.DIMENSIONS) == 13, len(IPP.DIMENSIONS))
check("维度顺序与参考一致",
      [d[0] for d in IPP.DIMENSIONS] == [k for _, k in REF_DIMS])

for zh, key in REF_DIMS:
    ref_opts = ref_required.get(zh)
    dim = next(d for d in IPP.DIMENSIONS if d[0] == key)
    concrete = list(ref_opts[0][2:]) if ref_opts else []
    check("规格：%s 选项与参考逐项一致" % zh,
          dim[3] == concrete,
          "%d vs %d；差异 %s" % (len(dim[3]), len(concrete),
                              [x for x in concrete if x not in dim[3]][:3]))
    if ref_opts and len(ref_opts) > 1:
        default_zh = ref_opts[1].get("default")
        expect = {"无": "none", "随机": "random"}.get(default_zh, default_zh)
        check("规格：%s 默认值与参考一致" % zh,
              IPP.QGIDPhotoPrompt.INPUT_TYPES()["required"][key][1]["default"]
              == (expect if expect in ("none", "random")
                  else IPP.value_for(dim, expect)))

# ---------- 2. 值域与词表 ----------
labels = IPP.value_label_map()
check("映射表条目数 = 选项总数 + none/random",
      len(labels) == 2 + sum(len(d[3]) for d in IPP.DIMENSIONS),
      len(labels))
check("所有下拉值均为 ASCII 英文键",
      all(v.isascii() and re.fullmatch(r"[a-z_0-9]+", v) for v in labels),
      [v for v in labels if not v.isascii()][:3])
for dim in IPP.DIMENSIONS:
    values = IPP.option_values(dim)
    check("值：%s 数量/前缀正确" % dim[0],
          len(values) == len(dim[3]) + 2
          and all(v.startswith(dim[0] + "_") for v in values[2:]))
    check("值：%s label_for 往返" % dim[0],
          all(IPP.value_for(dim, IPP.label_for(dim, v)) == v for v in values[2:]))

js = (PKG / "web/qg_id_photo_prompt.js").read_text(encoding="utf-8")
block = js.split("const LABELS = ", 1)[1].split(";\n\nconst DIM_KEYS", 1)[0]
check("前端 LABELS 与后端映射逐条一致", json.loads(block) == labels)
check("前端无 .connect( / .bind( 字面量",
      ".connect(" not in js and ".bind(" not in js)

menu = json.loads((PKG / "translations/zh-CN/Menus/ComfyUI-QG-Multipack.json")
                  .read_text(encoding="utf-8"))
check("Menus 词表覆盖全部选项值且中文一致",
      all(menu.get(k) == v for k, v in labels.items()),
      [k for k in labels if menu.get(k) != labels[k]][:5])

nd = json.loads((PKG / "locales/zh/nodeDefs.json").read_text(encoding="utf-8"))
tr = json.loads((PKG / "translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json")
                .read_text(encoding="utf-8"))
check("nodeDefs 有该节点且用官方 display_name",
      "display_name" in nd.get("QG_IDPhotoPrompt", {})
      and "title" not in nd.get("QG_IDPhotoPrompt", {}))
check("nodeDefs outputs 用索引字符串",
      list(nd["QG_IDPhotoPrompt"]["outputs"]) == ["0"])
check("translations 有该节点且 inputs/widgets 覆盖 14 控件",
      set(tr["QG_IDPhotoPrompt"]["inputs"]) == set(
          nd["QG_IDPhotoPrompt"]["inputs"])
      == set(IPP.QGIDPhotoPrompt.INPUT_TYPES()["required"]),
      (len(tr["QG_IDPhotoPrompt"]["inputs"]),
       len(IPP.QGIDPhotoPrompt.INPUT_TYPES()["required"])))

# ---------- 3. 提示词组装 ----------
fixed = {}
for dim in IPP.DIMENSIONS:
    fixed[dim[0]] = "none"
fixed["composition"] = IPP.value_for(IPP.DIMENSIONS[0], "人像面部特写")
fixed["nationality"] = IPP.value_for(IPP.DIMENSIONS[1], "中国")
fixed["gender"] = IPP.value_for(IPP.DIMENSIONS[2], "女孩")
fixed["body_shape"] = IPP.value_for(IPP.DIMENSIONS[3], "苗条的")
fixed["hair_color"] = IPP.value_for(IPP.DIMENSIONS[4], "黑色")
fixed["hairstyle"] = IPP.value_for(IPP.DIMENSIONS[5], "波波头")
fixed["clothing_style"] = IPP.value_for(IPP.DIMENSIONS[7], "衬衫")
fixed["background_color"] = IPP.value_for(IPP.DIMENSIONS[11], "白色")
text = IPP.build_prompt(fixed, 0)
check("固定值：基础描述顺序（体型 国籍 性别，空格连接）",
      text.startswith("一个苗条的 中国 女孩, "), text)
check("固定值：发色+发型同段空格连接", "黑色 波波头" in text, text)
check("固定值：背景色补「简单背景」后缀", "白色简单背景" in text, text)
check("固定值：整句与规格顺序完全一致",
      text == "一个苗条的 中国 女孩, 人像面部特写, 黑色 波波头, 衬衫, 白色简单背景",
      text)
check("固定值：none 的维度不出现", "淡妆" not in text and text.count(",") == 4, text)

plain_bg = dict(fixed)
plain_bg["background_color"] = IPP.value_for(IPP.DIMENSIONS[11], "简单背景")
check("改进：背景选「简单背景」不重复叠加",
      "简单背景简单背景" not in IPP.build_prompt(plain_bg, 0)
      and IPP.build_prompt(plain_bg, 0).endswith("简单背景"))

# ---------- 4. 随机行为 ----------
all_random = {d[0]: "random" for d in IPP.DIMENSIONS}
r1 = IPP.build_prompt(all_random, 42)
r2 = IPP.build_prompt(all_random, 42)
r3 = IPP.build_prompt(all_random, 43)
check("random：同 seed 完全可复现", r1 == r2)
check("random：不同 seed 结果不同", r1 != r3)
check("random：候选来自规格选项",
      all(any(x in r1 for x in d[3]) for d in IPP.DIMENSIONS), r1)

state_before = random.getstate()
IPP.build_prompt(all_random, 99)
check("改进：不污染进程全局 random", random.getstate() == state_before)

changed = dict(all_random)
changed["composition"] = "none"
segments = lambda s: [p for p in s.split(", ") if p and not p.startswith("一个")]
check("改进：各维度独立派生，改一个不牵动其它",
      segments(IPP.build_prompt(changed, 7)) == segments(IPP.build_prompt(all_random, 7))[1:],
      (IPP.build_prompt(changed, 7), IPP.build_prompt(all_random, 7)))

check("随机：极大 seed 不报错且可复现",
      IPP.build_prompt(all_random, 0xFFFFFFFFFFFFFFFF)
      == IPP.build_prompt(all_random, 0xFFFFFFFFFFFFFFFF))

# ---------- 5. 节点契约与兜底 ----------
it = IPP.QGIDPhotoPrompt.INPUT_TYPES()
check("契约：required 共 14 控件（13 维 + seed）", len(it["required"]) == 14)
check("契约：13 维均为 combo 且首两项 none/random",
      all(it["required"][d[0]][0][:2] == ["none", "random"] for d in IPP.DIMENSIONS))
check("契约：seed 为 INT 且范围完整",
      it["required"]["seed"][0] == "INT"
      and it["required"]["seed"][1]["max"] == 0xFFFFFFFFFFFFFFFF)
check("契约：RETURN_TYPES / FUNCTION / CATEGORY",
      IPP.QGIDPhotoPrompt.RETURN_TYPES == ("STRING",)
      and IPP.QGIDPhotoPrompt.FUNCTION == "generate"
      and IPP.QGIDPhotoPrompt.CATEGORY == "QG 工具")
check("契约：注册 key 唯一", list(IPP.NODE_CLASS_MAPPINGS) == ["QG_IDPhotoPrompt"])
check("契约：后端 DESCRIPTION 为英文",
      IPP.QGIDPhotoPrompt.DESCRIPTION.isascii(),
      IPP.QGIDPhotoPrompt.DESCRIPTION[:40])
check("兜底：缺 key 自动用维度默认值",
      IPP.build_prompt({}, 0) == IPP.build_prompt(
          {d[0]: it["required"][d[0]][1]["default"] for d in IPP.DIMENSIONS}, 0))
check("兜底：未知值退化为省略而非抛错",
      "_UNKNOWN_" not in IPP.build_prompt({"composition": "composition_999"}, 0))
check("节点调用：generate 返回单元素 tuple",
      IPP.QGIDPhotoPrompt().generate(seed=0, **fixed)[0] == text)

print("TOTAL ok=%d fail=%d" % (ok, fail))
sys.exit(1 if fail else 0)
