/**
 * QG 面部对齐 —— 填充模式下拉的中文显示。
 *
 * 后端值一律英文（custom_color / border_color），中文只是显示名：
 * 走官方 widget.options.getOptionLabel 钩子，不改存档值、不影响 API。
 * 自定义填充色控件是 STRING 颜色字段，图形化色板由 qg_color_picker.js
 * 统一接管（COLOR_WIDGETS 里登记 custom_fill_color）。
 */
import { app } from "/scripts/app.js";

const MODE_LABELS = {
    custom_color: "自定义颜色",
    border_color: "边框颜色",
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
function labelMode(node) {
    for (const widget of node.widgets || []) {
        if (widget?.name !== "fill_mode" || widget.__qgFaLabel) continue;
        widget.__qgFaLabel = true;
        widget.options = widget.options || {};
        const previous = typeof widget.options.getOptionLabel === "function"
            ? widget.options.getOptionLabel
            : null;
        widget.options.getOptionLabel = function (value) {
            const key = value == null ? value : String(value);
            if (wantsChinese() && MODE_LABELS[key]) return MODE_LABELS[key];
            return previous ? previous.call(this, value) : value;
        };
    }
}

app.registerExtension({
    name: "QG.FaceAlign",

    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== "QG_FaceAlign") return;

        const onCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onCreated?.apply(this, arguments);
            labelMode(this);
            return r;
        };

        // 从已保存工作流加载时不走 onNodeCreated，补一道
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = onConfigure?.apply(this, arguments);
            labelMode(this);
            return r;
        };
    },

    nodeCreated(node) {
        if (node?.comfyClass === "QG_FaceAlign" || node?.type === "QG_FaceAlign") {
            labelMode(node);
        }
    },

    setup() {
        for (const node of app.graph?._nodes || []) labelMode(node);
    },
});
