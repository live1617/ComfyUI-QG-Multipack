// -*- coding: utf-8 -*-
// QG_GoogleTranslate 前端：加一枚「手动翻译」按钮，点一下把文本框里的文字就地
// 翻成目标语言（不影响连线的自动翻译）。后端逻辑在 qg_google_translate.py。
// 思路来自 AlekPet/ComfyUI_Custom_Nodes_AlekPet（google_translate_node.js，MIT），
// 经 ComfyUI-QG-tools 中转后移植进本包；路由用本包专属的 /qgmp/translate/manual，
// 与 QG-tools 的 /qg/translate/manual 互不干扰（两个插件同时安装时各调各的）。

import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const NODE_CLASS = "QG_GoogleTranslate";

// 控件的 name 永远是英文键（汉化只改显示名），所以按 name 找是稳的。
const BUTTON_NAME = "Manual Translate";

const findWidget = (node, name) => node.widgets?.find((w) => w?.name === name);

function toast(severity, summary, detail, life) {
  console[severity === "error" ? "error" : "info"]("[QG-Multipack]", summary, detail);
  try {
    app.extensionManager?.toast?.add?.({ severity, summary, detail, life });
  } catch (err) {
    /* 老前端没有 toast，控制台那条就是全部提示 */
  }
}

async function manualTranslate(node) {
  const manual = findWidget(node, "manual_translate");
  const textWidget = findWidget(node, "text");
  if (!textWidget) return;

  if (!manual?.value) {
    toast(
      "info",
      "QG 工具：谷歌翻译",
      "「手动翻译」没开。文本会在排队运行节点时自动翻译（点「运行」）。",
      8000,
    );
    return;
  }

  try {
    const responseData = await api.fetchApi("/qgmp/translate/manual", {
      method: "POST",
      body: JSON.stringify({
        prompt: textWidget.value,
        srcTrans: findWidget(node, "from_translate")?.value ?? "auto",
        toTrans: findWidget(node, "to_translate")?.value ?? "en",
      }),
    });

    if (responseData.status !== 200) {
      // 后端失败时回 {"ok": false, "error": "..."}，把这句话转给用户，别只写控制台。
      let detail = responseData.statusText;
      try {
        const body = await responseData.json();
        if (body?.error) detail = body.error;
      } catch (error) {
        // 响应不是 JSON：保持 statusText
      }
      toast("error", "QG 工具：谷歌翻译", String(detail), 10000);
      return;
    }

    const json = await responseData.json();
    if (typeof json?.translate_prompt !== "string") return;

    textWidget.value = json.translate_prompt;
    // 面板是 DOM 还是 canvas 画的都成立：通知画布重画，别让旧文字留在屏幕上。
    node.setDirtyCanvas?.(true, true);
    app.graph.setDirtyCanvas?.(true, true);
  } catch (error) {
    console.error("[QG-Multipack] manual translate error", error);
  }
}

app.registerExtension({
  name: "QG.Multipack.GoogleTranslate",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_CLASS) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onNodeCreated?.apply?.(this, arguments);
      const node = this;

      // 🔴 按钮的文字必须放 label，不能放 addWidget 的第二个参数。
      //   litegraph 的 button 控件是 `label ?? name` 决定显示什么，而第二个参数同时
      //   就是控件的 name —— 把中文塞进去，name 就变成「手动翻译」，按 name 查找
      //   （还有存档里的控件名）全部落空。这里 name 永远是英文常量，显示文字单独
      //   写进 label。
      const button = node.addWidget(
        "button",
        BUTTON_NAME,
        BUTTON_NAME,
        () => manualTranslate(node)
      );
      if (button) button.label = "手动翻译";

      // 把按钮挪到「文本」控件之前（视觉顺序与上游一致）。按 name 找位置，
      // 别写死下标 —— 控件增减时按钮才不会插错地方。
      const widgets = node.widgets;
      const here = widgets.indexOf(button);
      const textIndex = widgets.findIndex((w) => w?.name === "text");
      if (here >= 0 && textIndex >= 0) {
        widgets.splice(here, 1);
        widgets.splice(widgets.findIndex((w) => w?.name === "text"), 0, button);
      }
    };
  },
});
