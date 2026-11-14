/**
 * QG 双色取色器 —— 模式下拉的中文显示。
 *
 * 后端值一律英文（solid / vertical_gradient / radial_gradient），中文只是
 * 显示名：走官方 widget.options.getOptionLabel 钩子，不改存档值、不影响 API。
 * 两个颜色控件的图形化绘制与弹出色板由 qg_color_picker.js 统一接管。
 */
import { app } from "/scripts/app.js";

const MODE_LABELS = {
    solid: "纯色",
    vertical_gradient: "上下渐变",
    radial_gradient: "中心渐变",
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
        if (widget?.name !== "mode" || widget.__qgDcpLabel) continue;
        widget.__qgDcpLabel = true;
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
    name: "QG.DualColorPicker",

    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== "QG_DualColorPicker") return;

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
        if (node?.comfyClass === "QG_DualColorPicker" || node?.type === "QG_DualColorPicker") {
            labelMode(node);
        }
    },

    setup() {
        for (const node of app.graph?._nodes || []) labelMode(node);
    },
});
