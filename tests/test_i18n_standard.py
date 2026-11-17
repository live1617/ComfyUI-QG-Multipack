# -*- coding: utf-8 -*-
"""汉化词表「两套标准」结构校验（2026-11-14 整理后固化）。

本包的中文词表有两套，各自对应一个生态标准，职责不同：

1. `locales/zh/nodeDefs.json` —— ComfyUI 官方前端 i18n 标准（ComfyUI_frontend
   的 locales 体系，前端自动加载）：
   - 顶层 key = 节点注册类名；
   - 节点条目字段：`display_name`（官方字段名，**不是** AIGODLIKE 的 `title`）、
     `description`、`inputs`（value 为 {name, tooltip}）、`outputs`（key 为
     **输出索引字符串** "0"/"1"/...，官方口径；v2.7.1 之前 QG_QwenPromptOptimizer
     用槽名、QG_QwenTextEncode 缺整个 outputs，已修正）；
   - 不存在 `widgets` 字段（官方把控件并入 inputs；Qwen 三节点的遗留 widgets
     字段官方会忽略）。

2. `translations/zh-CN/{Nodes,Menus}/ComfyUI-QG-Multipack.json` ——
   AIGODLIKE 系汉化插件（ComfyUI-Chinese-Translation / Global-Translation）
   标准，`Nodes/插件名.json` 每节点 {title, description, inputs, widgets,
   outputs}，key 全部为原始英文输入/控件名（Qwen 提示词优化器的输入名
   上游本来就是中文，如实保留）。把这两个文件拷进汉化插件的
   `zh-CN/Nodes`、`zh-CN/Menus` 即可被其聚合识别。

3. 分类无需 Categories 词表：本包全部节点 category="QG 工具"，已是中文。

ComfyUI-Global-Translation v3.0.1 规范补充（2026-11-15 整理）：
- 禁止恒等翻译：键==值的条目没有翻译意义，且会污染汉化插件的
  "已翻译文本判定集合"（虽 v3.0.1 已跳过恒等，仍按规范不写）。
  因此 nodeDefs 里 name==key 的端口（如 Qwen 的 clip/vae/mask、
  上游本就是中文的 QwenPromptOptimizer 参数名）在 translations 中缺失
  是正确行为，"需覆盖"只针对 nodeDefs 里 name!=key 的真需要汉化项。
- ui 字段（翻译节点内嵌 DOM 面板的英文原文）本包用不上：本包面板文案
  全部是中文硬编码，无英文原文可映射；若将来某节点面板出现英文才补。

历史背景：v2.7.1 之前 translations 的 10 个节点 inputs/widgets 大量缺词条、
nodeDefs 的 3 个 Qwen 节点用非官方字段（官方前端显示英文），本测试固化
修正后的口径，防止回归。
"""
import json
import os
import sys

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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


with open(os.path.join(PKG, "locales/zh/nodeDefs.json"), encoding="utf-8") as fh:
    nd = json.load(fh)
with open(os.path.join(PKG,
           "translations/zh-CN/Nodes/ComfyUI-QG-Multipack.json"), encoding="utf-8") as fh:
    tr = json.load(fh)
with open(os.path.join(PKG,
           "translations/zh-CN/Menus/ComfyUI-QG-Multipack.json"), encoding="utf-8") as fh:
    menu = json.load(fh)

# ---- 一、nodeDefs（官方前端标准） ----
check("nodeDefs 31 个节点", len(nd) == 31, str(len(nd)))
bad_field = [k for k, v in nd.items() if "display_name" not in v or "title" in v]
check("全部用官方字段 display_name（无 title）", not bad_field, str(bad_field))
no_desc = [k for k, v in nd.items() if not v.get("description")]
check("全部有 description", not no_desc, str(no_desc))
bad_out = []
for k, v in nd.items():
    outs = v.get("outputs", {})
    if outs and not all(kk.isdigit() for kk in outs):
        bad_out.append((k, list(outs)))
check("outputs key 全部为索引字符串", not bad_out, str(bad_out))
bad_in = []
for k, v in nd.items():
    for ik, iv in v.get("inputs", {}).items():
        if not isinstance(iv, dict) or "name" not in iv:
            bad_in.append((k, ik))
check("inputs value 均为 {name, ...} 对象", not bad_in, str(bad_in))

# ---- 二、translations（AIGODLIKE 汉化插件标准） ----
check("translations 31 个节点", len(tr) == 31, str(len(tr)))
check("两套词表 key 完全一致", set(nd) == set(tr),
      str(set(nd) ^ set(tr)))
miss_title = [k for k, v in tr.items() if not v.get("title")]
check("translations 全部有 title", not miss_title, str(miss_title))
miss_in = []
miss_w = []
for k, v in nd.items():
    t = tr[k]
    # 只需覆盖 name!=key 的项：name==key 是恒等端口（技术术语/本就中文），
    # 按汉化插件规范不写恒等条目，缺失是正确的。
    for ik, iv in v.get("inputs", {}).items():
        disp = iv.get("name", ik) if isinstance(iv, dict) else ik
        if disp != ik and ik not in t.get("inputs", {}):
            miss_in.append((k, ik))
    for wk, wv in v.get("widgets", {}).items():
        disp = wv.get("name", wk) if isinstance(wv, dict) else wk
        if disp != wk and wk not in t.get("widgets", {}):
            miss_w.append((k, wk))
check("translations 覆盖所有需汉化 inputs（name!=key）", not miss_in, str(miss_in))
check("translations 覆盖所有需汉化 widgets（name!=key）", not miss_w, str(miss_w))

# 规范：禁止恒等翻译（键==值）
ident = [(k, f, kk) for k, v in tr.items() for f in ("inputs", "widgets", "outputs")
         for kk, vv in v.get(f, {}).items() if kk == vv]
check("无恒等翻译（键==值）", not ident, str(ident))

# 规范：每节点有 description（缺失的 Qwen 三节点已从 nodeDefs 补齐）
no_desc = [k for k, v in tr.items() if not v.get("description")]
check("translations 全部有 description", not no_desc, str(no_desc))

# ---- 三、Menus（汉化插件全局下拉替换） ----
for key, zh in (("solid", "纯色"), ("vertical_gradient", "上下渐变"),
                ("radial_gradient", "中心渐变"), ("custom_color", "自定义颜色"),
                ("border_color", "边框颜色"),
                ("Moonshot Kimi", "月之暗面 Kimi"), ("SiliconFlow", "硅基流动")):
    check("Menus[%r]" % key, menu.get(key) == zh,
          "got %r" % menu.get(key))

print("TOTAL ok=%d fail=%d" % (ok, fail))
sys.exit(1 if fail else 0)
