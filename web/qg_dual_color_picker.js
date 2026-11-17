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

/**
 * 把 mode 输出槽的类型标成 COMBO。后端 RETURN_TYPES 第 1 槽写的是 options
 * 列表（后端类型校验只认这个），前端 addOutputs 会原样把它当类型，导致连线
 * 校验拿数组去比下游的 "COMBO" 字符串而不匹配。这里统一改正，使 mode 能驱动
 * 任何 combo 输入（含 QG 自定义颜色的模式）。
 */
function markModeOutput(node) {
    const outputs = node?.outputs || [];
    const slot = outputs.find((s) => s?.name === "mode") || outputs[0];
    if (!slot || slot.type === "COMBO") return;
    slot.type = "COMBO";
    slot.__qgDcpCombo = true;
}

app.registerExtension({
    name: "QG.DualColorPicker",

    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== "QG_DualColorPicker") return;

        // 后端 RETURN_TYPES 第 1 槽是 options 列表（后端 combo 校验只认数组），
        // 但前端 addOutputs 会把这个数组原样当类型用。这里优先在生成槽位之前
        // 换成 "COMBO"，与下游 combo 输入槽的类型字符串一致，连线校验才能通过。
        // nodeData 可能是被冻结的对象（ES module 严格模式下赋值会抛错并中断
        // 节点注册），所以必须兜住：失败就交给下面的 markModeOutput 覆盖槽位。
        try {
            if (Array.isArray(nodeData.output?.[0])) {
                nodeData.output[0] = "COMBO";
            }
        } catch (err) {
            /* nodeData 冻结，退回槽位覆盖 */
        }

        const onCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onCreated?.apply(this, arguments);
            labelMode(this);
            markModeOutput(this);
            return r;
        };

        // 从已保存工作流加载时不走 onNodeCreated，补一道
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = onConfigure?.apply(this, arguments);
            labelMode(this);
            markModeOutput(this);
            return r;
        };
    },

    nodeCreated(node) {
        if (node?.comfyClass === "QG_DualColorPicker" || node?.type === "QG_DualColorPicker") {
            labelMode(node);
            markModeOutput(node);
        }
    },

    setup() {
        for (const node of app.graph?._nodes || []) {
            labelMode(node);
            markModeOutput(node);
        }
    },
});
