/**
 * QG 颜色转换 —— 格式下拉的中文显示。
 *
 * 后端值保持 #HEX / HEX / RGB / HSL 原文（存档、API 不变），中文只是显示名：
 * 走官方 widget.options.getOptionLabel 钩子，实时判语言，切界面语言无需重建节点。
 */
import { app } from "/scripts/app.js";

const FORMAT_LABELS = {
    "#HEX": "带 # 十六进制",
    "HEX": "十六进制",
    "RGB": "RGB 整数",
    "HSL": "HSL 百分比",
};

function wantsChinese() {
    try {
        const loc = app?.i18n?.global?.locale;
        const value = typeof loc === "string" ? loc : loc?.value;
        if (/^zh/i.test(value || "")) return true;
        const setting = app?.ui?.settings?.getSettingValue?.("Comfy.Locale");
        if (/^zh/i.test(setting || "")) return true;
    } catch (err) {
        /* 老前端取不到就退回 HTML lang */
    }
    return /^zh/i.test(document?.documentElement?.lang || "");
}

/** 只挂一次；getOptionLabel 内部实时判语言，切界面语言后无需重建节点。 */
function labelFormat(node) {
    for (const widget of node.widgets || []) {
        if (widget?.name !== "format" || widget.__qgCcLabel) continue;
        widget.__qgCcLabel = true;
        widget.options = widget.options || {};
        const previous = typeof widget.options.getOptionLabel === "function"
            ? widget.options.getOptionLabel
            : null;
        widget.options.getOptionLabel = function (value) {
            const key = value == null ? value : String(value);
            if (wantsChinese() && FORMAT_LABELS[key]) return FORMAT_LABELS[key];
            return previous ? previous.call(this, value) : value;
        };
    }
}

app.registerExtension({
    name: "QG.ColorConvert",

    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== "QG_ColorConvert") return;

        const onCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onCreated?.apply(this, arguments);
            labelFormat(this);
            return r;
        };

        // 从已保存工作流加载时不走 onNodeCreated，补一道
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = onConfigure?.apply(this, arguments);
            labelFormat(this);
            return r;
        };
    },

    nodeCreated(node) {
        if (node?.comfyClass === "QG_ColorConvert" || node?.type === "QG_ColorConvert") {
            labelFormat(node);
        }
    },

    setup() {
        for (const node of app.graph?._nodes || []) labelFormat(node);
    },
});
