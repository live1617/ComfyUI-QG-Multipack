# -*- coding: utf-8 -*-
"""QG_ImageBatchBuilder 节点级测试：收集 / 对齐 / 契约 / 词表登记。

纯逻辑用 importlib 单文件加载，不依赖 ComfyUI 运行时、模型、网络或 API Key。
运行：python_embeded\\python.exe tests\\test_image_batch_builder.py
"""
import importlib.util
import json
import os
import sys

import torch

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

Total = 0
Failed = 0


def check(label, ok, detail=""):
    global Total, Failed
    Total += 1
    if not ok:
        Failed += 1
    print("  %-54s %s  %s" % (label, "PASS" if ok else "FAIL",
                              detail if not ok else ""))


def load_node():
    spec = importlib.util.spec_from_file_location(
        "qgmp_batch_builder_test",
        os.path.join(PKG, "qg_image_batch_builder.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read(rel):
    with open(os.path.join(PKG, rel), encoding="utf-8") as fh:
        return fh.read()


def solid(h, w, c=3, value=0.5):
    return torch.full((h, w, c), value)


m = load_node()

# ---------- 一、槽位常量与收集 ----------
print("== 一、槽位与收集 collect_frames ==")
check("槽位数量 24", m.SLOT_COUNT == 24, str(m.SLOT_COUNT))
check("槽位名 image_01 .. image_24",
      m.SLOT_NAMES[0] == "image_01" and m.SLOT_NAMES[-1] == "image_24"
      and len(m.SLOT_NAMES) == 24)

f1, f2, f3 = solid(4, 4, value=0.1), solid(4, 4, value=0.2), solid(4, 4, value=0.3)
frames = m.collect_frames({"image_01": f1, "image_03": f3})
check("空槽自动跳过", len(frames) == 2, "得 %d" % len(frames))
check("按槽位编号顺序（非字典序插入）",
      torch.allclose(frames[0], f1) and torch.allclose(frames[1], f3))

batch2 = torch.stack([solid(4, 4, value=0.6), solid(4, 4, value=0.7)])
frames = m.collect_frames({"image_02": batch2})
check("单槽接整 batch 会展开", len(frames) == 2, "得 %d" % len(frames))

frames = m.collect_frames({"image_01": f1, "image_02": batch2, "image_24": f3})
check("单帧 + 整批混合展开", len(frames) == 4, "得 %d" % len(frames))

try:
    m.collect_frames({})
    check("全空抛错", False)
except ValueError as e:
    check("全空抛错", "没有可组合" in str(e))

try:
    m.collect_frames({"image_01": torch.zeros(2, 3, 4, 5, 6)})
    check("非法维度抛错", False)
except ValueError as e:
    check("非法维度抛错", "维度非法" in str(e))

# ---------- 二、对齐 align_frames ----------
print("== 二、对齐 align_frames ==")
out = m.align_frames([f1, f2, f3], "first")
check("对齐后堆成 batch", tuple(out.shape) == (3, 4, 4, 3), str(tuple(out.shape)))

big = torch.ones(8, 8, 3)
out = m.align_frames([f1, big], "first")
check("first 模式把大图缩到首帧尺寸",
      tuple(out.shape) == (2, 4, 4, 3), str(tuple(out.shape)))

try:
    m.align_frames([f1, big], "error")
    check("error 模式尺寸不一直接抛错", False)
except ValueError as e:
    check("error 模式尺寸不一直接抛错", "尺寸不一致" in str(e))

out = m.align_frames([f1, f2], "error")
check("error 模式尺寸一致时正常", tuple(out.shape) == (2, 4, 4, 3))

rgba = torch.ones(4, 4, 4)
out = m.align_frames([f1, rgba], "first")
check("RGB 首帧 + RGBA 输入 → 丢 alpha", tuple(out.shape) == (2, 4, 4, 3),
      str(tuple(out.shape)))
out = m.align_frames([rgba, f1], "first")
check("RGBA 首帧 + RGB 输入 → 补不透明 alpha",
      tuple(out.shape) == (2, 4, 4, 4) and float(out[1, ..., 3].min()) == 1.0,
      str(tuple(out.shape)))

try:
    m.align_frames([], "first")
    check("空帧列表抛错", False)
except ValueError:
    check("空帧列表抛错", True)

# ---------- 三、节点契约 ----------
print("== 三、节点契约 ==")
node = m.QGImageBatchBuilder
it = node.INPUT_TYPES()
req, opt = it["required"], it["optional"]
# 动态槽：前端默认只显示 1 槽、接一个加一个，所以后端不能强制任何槽必填，
# 否则只接 1 张时 ComfyUI 会以「必填未接」拦截执行。至少 1 张由 collect_frames
# 在运行时保证（见第一节「全空抛错」）。
check("required 为空（动态槽全可选）", req == {}, str(list(req)))
check("24 槽全部可选",
      all("image_%02d" % i in opt for i in range(1, 25)))
# 帮助卡按「登记的输入清单」逐条渲染，所以清单里只能有一条图像槽；
# 其余 image_NN 由清单容器兜住（能查到、能取到 IMAGE 规格），后端照旧接收。
check("图像槽只对外登记 1 条（帮助卡不再刷 24 行）",
      [k for k in opt if k.startswith("image_")] == ["image_01"],
      str([k for k in opt if k.startswith("image_")]))
check("清单序列化后只有图像槽 + 尺寸模式两条",
      len(json.loads(json.dumps(opt))) == 2)
check("未登记槽仍能取到 IMAGE 规格",
      opt["image_24"][0] == "IMAGE" and opt["image_09"][0] == "IMAGE")
check("图像槽说明写清 1～24 范围",
      "1～24" in opt["image_01"][1]["tooltip"],
      opt["image_01"][1]["tooltip"][:24])
check("resize_mode 在可选里且默认 first",
      "resize_mode" in opt and opt["resize_mode"][1]["default"] == "first")
check("resize_mode 选项 first/error", list(opt["resize_mode"][0]) == ["first", "error"])
check("RETURN_TYPES 两个输出", tuple(node.RETURN_TYPES) == ("IMAGE", "INT"))
check("RETURN_NAMES 对齐", tuple(node.RETURN_NAMES) == ("image", "count"))
check("FUNCTION=build 存在", node.FUNCTION == "build" and hasattr(node, "build"))
check("CATEGORY=QG 工具", node.CATEGORY == "QG 工具")
check("注册 key 正确", list(m.NODE_CLASS_MAPPINGS) == ["QG_ImageBatchBuilder"])
check("中文显示名", m.NODE_DISPLAY_NAME_MAPPINGS["QG_ImageBatchBuilder"] == "QG 图像批次组合")

batch, count = node().build(
    image_01=f1, image_03=f3, resize_mode="first")
check("build 实跑：3 槽接 2 张 → count=2", count == 2, str(count))
check("build 实跑：batch 帧数=2", tuple(batch.shape) == (2, 4, 4, 3))

batch, count = node().build(
    image_01=f1, image_02=torch.stack([f2, f3]), resize_mode="first")
check("build 实跑：单帧+整批 → count=3", count == 3, str(count))

# ---------- 四、词表与文档登记 ----------
print("== 四、词表与文档 ==")
nd = json.loads(read("locales/zh/nodeDefs.json"))
tr = json.loads(read("translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"))
check("nodeDefs 32 个节点", len(nd) == 32, str(len(nd)))
check("translations 32 个节点", len(tr) == 32, str(len(tr)))
check("两份词表都有新节点",
      "QG_ImageBatchBuilder" in nd and "QG_ImageBatchBuilder" in tr)
check("中文标题一致",
      nd["QG_ImageBatchBuilder"]["display_name"]
      == tr["QG_ImageBatchBuilder"]["title"] == "QG 图像批次组合")
check("全部 24 槽有中文",
      all("image_%02d" % i in nd["QG_ImageBatchBuilder"]["inputs"]
          for i in range(1, 25)))
# 回归：24 个同功能槽在词表里共用同一条说明，帮助卡只列一行（后端只登记 image_01）
_slot_tips = [nd["QG_ImageBatchBuilder"]["inputs"]["image_%02d" % i].get("tooltip", "")
              for i in range(1, 25)]
check("24 槽共用同一条说明", len(set(_slot_tips)) == 1 and bool(_slot_tips[0]),
      "不同说明 %d 种" % len(set(_slot_tips)))
check("说明里写清范围与公共规则",
      all(k in _slot_tips[0] for k in ("第 1～24 张", "空槽自动跳过", "batch")))
check("首槽显示名写成范围",
      nd["QG_ImageBatchBuilder"]["inputs"]["image_01"]["name"] == "第 1～24 张")
check("公共规则写在节点描述里",
      all(k in nd["QG_ImageBatchBuilder"]["description"]
          for k in ("接单张或一个 batch", "空槽自动跳过", "按槽位顺序拼")))
check("输出两个中文名", len(nd["QG_ImageBatchBuilder"]["outputs"]) == 2)
rd = read("README.md")
check("README 表格登记", "`QG_ImageBatchBuilder`" in rd)
check("README 专章登记", "### `QG_ImageBatchBuilder` 图像批次组合" in rd)
check("README 节点数 31", "覆盖全部 32 个节点" in rd)
check("ISSUES 登记", "QG 图像批次组合" in read("ISSUES.md"))
check("__init__.py 注册", "qg_image_batch_builder" in read("__init__.py"))

# ---------- 五、前端动态槽 JS ----------
print("== 五、前端动态槽 JS ==")
js = read("web/qg_image_batch_builder.js")
check("JS 文件存在且非空", len(js) > 200)
check("注册扩展带本包前缀",
      'name: "QG.Multipack.ImageBatchBuilder"' in js)
check("只作用于本节点", 'nodeData?.name !== NODE_NAME' in js)
check("NODE_NAME 对齐后端", 'const NODE_NAME = "QG_ImageBatchBuilder"' in js)
check("槽上限 24 与后端一致", 'MAX_IMAGES = 24' in js)
check("默认 1 槽 / 接一个加一槽（lastConnected + 2）",
      'Math.max(1, lastConnected + 2)' in js)
check("槽名 label 第 N 张", 'slot.label = `第 ${index + 1} 张`' in js)
check("三处生命周期都触发 sync",
      all(k in js for k in ("onNodeCreated", "onConnectionsChange", "onConfigure"))
      and js.count("scheduleSync(this)") >= 2
      and "scheduleSync(this, true)" in js)
check("requestAnimationFrame 防抖", "requestAnimationFrame" in js)

# ---------- 六、节点高度贴合实际槽数 ----------
print("== 六、节点高度贴合 ==")
check("存在 fitNodeHeight", "function fitNodeHeight" in js)
check("新建节点按 computeSize 自然高度收紧",
      "computeSize?.([width, 0])" in js and "initial ? natural[1]" in js)
check("接线时只增高不减高",
      "Math.max(currentH, natural[1])" in js)
check("工作流尺寸守卫 _qgSizeFromWorkflow",
      "if (node._qgSizeFromWorkflow) return;" in js)
check("onConfigure 打工作流尺寸标记",
      "this._qgSizeFromWorkflow = true" in js)
check("fitNodeHeight 在 sync 之后调用",
      js.find("syncImageInputs(node)") < js.find("fitNodeHeight(node, initial)"))
check("示例工作流 builder 尺寸已紧凑（非 720）",
      '"size": [\n        330,\n        230\n      ]' in read("examples/多人证件照拼版示例.json")
      or "[330, 230]" in read("examples/多人证件照拼版示例.json"))
check("上限保护：超过 MAX 收起",
      "inputs.length > MAX_IMAGES" in js and "removeInput" in js)
check("已连接槽绝不删", "if (connected(last.slot)) break" in js)
check("只认 image_XX 槽不碰 resize_mode",
      r"/^image_\d+$/" in js and "resize_mode" in js)

print("\n结果：%d / %d 通过" % (Total - Failed, Total))
if Failed:
    sys.exit(1)
