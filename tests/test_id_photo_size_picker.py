# -*- coding: utf-8 -*-
"""QG_IDPhotoSizePicker 节点级测试：契约 / 预设同源 / 尺寸换算 / 前端与词表登记。

最要紧的一条是 [4]：用 ComfyUI 自己的 validate_node_input 实测第 1 槽的输出类型
能不能连上下游的预设下拉。这不是推理 —— 之前双色取色器就是在"以为写 COMBO 就行"
上栽过，实测才发现后端只认与下游逐项相同的数组。

不依赖模型、网络、API Key。
运行：python_embeded\\python.exe tests\\test_id_photo_size_picker.py
"""
import importlib
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
COMFY = os.path.dirname(os.path.dirname(PKG))

Total = 0
Failed = 0


def check(label, ok, detail=""):
    global Total, Failed
    Total += 1
    if not ok:
        Failed += 1
    print("  %-54s %s  %s" % (label, "PASS" if ok else "FAIL",
                              detail if not ok else ""))


def load_package():
    name = "qgmp_size_test"
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(PKG, "__init__.py"), submodule_search_locations=[PKG])
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[name] = pkg
    spec.loader.exec_module(pkg)
    return name


def read(rel):
    with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
        return fh.read()


pkg_name = load_package()
mod = importlib.import_module(pkg_name + ".qg_id_photo_size_picker")
crop = importlib.import_module(pkg_name + ".id_photo_crop_node")
params = importlib.import_module(pkg_name + ".id_photo_params_node")
helpers = importlib.import_module(pkg_name + "._id_photo_helpers")

cls = mod.QGIDPhotoSizePicker

print("== [1] 节点注册契约 ==")
check("注册 key 唯一且为 QG_IDPhotoSizePicker",
      list(mod.NODE_CLASS_MAPPINGS) == ["QG_IDPhotoSizePicker"],
      str(list(mod.NODE_CLASS_MAPPINGS)))
check("显示名已登记",
      bool(mod.NODE_DISPLAY_NAME_MAPPINGS.get("QG_IDPhotoSizePicker")))
check("类名与注册一致", cls.__name__ == "QGIDPhotoSizePicker")
check("分类是 QG 工具", cls.CATEGORY == "QG 工具")
check("FUNCTION 指向 pick 且方法存在",
      cls.FUNCTION == "pick" and callable(getattr(cls, "pick", None)))

print("== [2] 预设与裁剪 / 参数节点同源（接得上才叫能连） ==")
it = cls.INPUT_TYPES()["required"]
own = list(it["preset"][0])
crop_opts = list(crop.QGIDPhotoCrop.INPUT_TYPES()["required"]["preset"][0])
param_opts = list(params.QGIDPhotoParams.INPUT_TYPES()["required"]["preset"][0])
check("自己的 preset 下拉 == PRESET_ORDER", own == list(helpers.PRESET_ORDER))
check("与裁剪节点预设逐项相同", own == crop_opts,
      "本节点 %d 项 / 裁剪 %d 项" % (len(own), len(crop_opts)))
check("与参数节点预设逐项相同", own == param_opts)
check("预设共 20 项", len(own) == 20, str(len(own)))
check("含 custom 且排最后", own[-1] == "custom")
check("默认值是 1inch", it["preset"][1].get("default") == "1inch")
check("其余四个控件齐全",
      sorted(it) == ["custom_height", "custom_width", "dpi", "preset", "unit"],
      str(sorted(it)))

print("== [3] 输出槽契约 ==")
check("四路输出", len(cls.RETURN_TYPES) == 4, str(len(cls.RETURN_TYPES)))
check("第 1 槽是列表而不是字符串", isinstance(cls.RETURN_TYPES[0], list),
      type(cls.RETURN_TYPES[0]).__name__)
check("第 1 槽内容 == PRESET_ORDER", cls.RETURN_TYPES[0] == list(helpers.PRESET_ORDER))
check("后三槽都是 INT", tuple(cls.RETURN_TYPES[1:]) == ("INT", "INT", "INT"))
check("输出名是 preset/width/height/dpi",
      tuple(cls.RETURN_NAMES) == ("preset", "width", "height", "dpi"))
check("四路都有 tooltip", len(cls.RETURN_TOOLTIPS) == 4)

print("== [4] 后端类型校验实测（本节点的核心契约） ==")
sys.path.insert(0, COMFY)
try:
    from comfy_execution.validation import validate_node_input
except Exception as exc:  # 环境缺 ComfyUI 运行时才算失败，不静默跳过
    validate_node_input = None
    print("     导入失败：%r" % (exc,))
check("能导入 ComfyUI 的 validate_node_input", validate_node_input is not None)

if validate_node_input is not None:
    out_type = cls.RETURN_TYPES[0]
    check("本节点输出 × 裁剪预设输入 → 放行",
          validate_node_input(out_type, crop_opts) is True)
    check("本节点输出 × 参数预设输入 → 放行",
          validate_node_input(out_type, param_opts) is True)
    check("写 \"STRING\" 会被拒（旧写法为什么不行）",
          validate_node_input("STRING", crop_opts) is False)
    check("写 \"COMBO\" 照样被拒（想当然的改法）",
          validate_node_input("COMBO", crop_opts) is False)
    check("内容不同的列表被拒",
          validate_node_input(["a", "b"], crop_opts) is False)

print("== [5] 尺寸换算 ==")
node = cls()


def pick(preset, dpi=300, cw=3.5, ch=4.9, unit="cm"):
    return node.pick(preset, dpi, cw, ch, unit)


check("1寸 @300 → 295x413",
      pick("1inch") == ("1inch", 295, 413, 300), str(pick("1inch")))
check("1寸 @600 → 591x827",
      pick("1inch", 600) == ("1inch", 591, 827, 600), str(pick("1inch", 600)))
check("美签 5.1x5.1 @300 → 602x602",
      pick("us_visa") == ("us_visa", 602, 602, 300), str(pick("us_visa")))
check("身份证电子自带 350dpi，覆盖控件的 300",
      pick("id_card_digital", 300) == ("id_card_digital", 358, 441, 350),
      str(pick("id_card_digital", 300)))
check("司法考试照是像素预设 413x626",
      pick("judicial_exam") == ("judicial_exam", 413, 626, 300))
check("custom 厘米 3.5x4.9 @300 → 413x579",
      pick("custom", 300, 3.5, 4.9, "cm") == ("custom", 413, 579, 300),
      str(pick("custom", 300, 3.5, 4.9, "cm")))
check("custom 像素 400x500 原样",
      pick("custom", 300, 400, 500, "px") == ("custom", 400, 500, 300),
      str(pick("custom", 300, 400, 500, "px")))

try:
    pick("custom", 300, 0.0, 0.0, "cm")
    zero_raised = False
except ValueError:
    zero_raised = True
check("custom 宽高为 0 时报错而不是出 0 像素图", zero_raised)

# 与裁剪节点同一个换算函数，结果必须完全一致
same = all(
    pick(k)[1:] == tuple(
        int(v) for v in helpers.output_pixels(k, "cm", 3.5, 4.9, 300)
    )
    for k in helpers.PRESET_ORDER if k != "custom"
)
check("19 个标准预设与裁剪节点换算结果逐一相同", same)

print("== [6] 前端静态契约 ==")
js_path = os.path.join("web", "qg_id_photo_size_picker.js")
check("前端脚本存在", os.path.exists(os.path.join(PKG, js_path)))
js = read(js_path)
check("扩展名带本包前缀", 'name: "QG.IDPhotoSizePicker"' in js)
check("在 addOutputs 之前改 nodeData.output[0]",
      "nodeData.output[0] = \"COMBO\"" in js)
check("改了 nodeData 有 try/catch 兜住",
      "try {" in js and "} catch (err)" in js)
check("有槽位兜底函数 markPresetOutput", "function markPresetOutput" in js)
check("onNodeCreated 兜底", "onCreated?.apply(this, arguments)" in js)
check("onConfigure 兜底（存档加载也会过一遍）",
      "onConfigure?.apply(this, arguments)" in js)
check("nodeCreated 钩子兜底", "nodeCreated(node)" in js)
check("setup 扫一遍已有节点", "app.graph?._nodes" in js)
check("不在延迟回调里改尺寸（不受尺寸还原问题牵连）", "setSize" not in js)

print("== [7] 词表与文档登记 ==")
nd = json.loads(read(os.path.join("locales", "zh", "nodeDefs.json")))
tr = json.loads(read(os.path.join("translations", "zh-CN", "Nodes",
                                 "ComfyUI-QG-Multipack.json")))
check("nodeDefs 登记了该节点", "QG_IDPhotoSizePicker" in nd)
check("nodeDefs 显示名是中文",
      nd.get("QG_IDPhotoSizePicker", {}).get("display_name") == "QG 证件照尺寸选择")
check("nodeDefs 四个输出都有中文名",
      sorted(nd["QG_IDPhotoSizePicker"]["outputs"]) == ["0", "1", "2", "3"])
check("translations 登记了该节点", "QG_IDPhotoSizePicker" in tr)
check("translations 标题与 nodeDefs 一致",
      tr["QG_IDPhotoSizePicker"]["title"] == nd["QG_IDPhotoSizePicker"]["display_name"])
check("translations 四个输出都有中文名",
      sorted(tr["QG_IDPhotoSizePicker"]["outputs"]) == ["dpi", "height", "preset", "width"])

photo_kit = read(os.path.join("web", "qg_photokit_zh.js"))
check("下拉中文复用裁剪节点的同一份文案",
      "QG_IDPhotoSizePicker: {" in photo_kit and "ID_PHOTO_PRESETS" in photo_kit)
check("尺寸选择器登记了厘米/像素标签",
      photo_kit.count('unit: { cm: "厘米", px: "像素" }') >= 2)

readme = read("README.md")
check("README 提到该节点", "QG 证件照尺寸选择" in readme or "QG_IDPhotoSizePicker" in readme)

print("")
if Failed:
    print("存在失败项！合计 %d 项" % Total)
    sys.exit(1)
print("全部通过，合计 %d 项" % Total)
