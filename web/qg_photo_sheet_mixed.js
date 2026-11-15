/**
 * QG 证件照混合排版（A5）—— 版式下拉的中文显示。
 *
 * 后端值一律英文（small1_14 / mix_1_8_2_4 ...），中文只是显示名：走官方
 * widget.options.getOptionLabel 钩子，不改存档值、不影响 API。映射表由
 * photo_sheet_mixed_node.py 的 LAYOUT_LABELS 生成，两边不会漂移。
 */
import { app } from "/scripts/app.js";

const LABELS = {
    "small1_14": "小1寸 14张",
    "standard1_12": "标准1寸 12张",
    "large1_8": "大1寸 8张",
    "small2_8": "小2寸 8张",
    "standard2_8": "标准2寸 8张",
    "large2_8": "大2寸 8张",
    "mix_small1_9_small2_4": "小1寸 9张 + 小2寸 4张",
    "mix_1_8_small2_4": "1寸 8张 + 小2寸 4张",
    "mix_1_8_2_4": "1寸 8张 + 2寸 4张",
    "mix_22x32_8_31x46_4": "22x32 8张 + 31x46 4张",
    "mix_1_8_large1_4": "1寸 8张 + 大1寸 4张",
    "mix_24x34_33x48_nogap": "2.4 x 3.4 + 3.3 x 4.8 无间距",
    "plain_34x49_nogap": "3.4 x 4.9 无间距"
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
function labelLayout(node) {
    for (const widget of node.widgets || []) {
        if (widget?.name !== "layout" || widget.__qgPsmLabel) continue;
        widget.__qgPsmLabel = true;
        widget.options = widget.options || {};
        const previous = typeof widget.options.getOptionLabel === "function"
            ? widget.options.getOptionLabel
            : null;
        widget.options.getOptionLabel = function (value) {
            const key = value == null ? value : String(value);
            if (wantsChinese() && LABELS[key]) return LABELS[key];
            return previous ? previous.call(this, value) : value;
        };
    }
}

app.registerExtension({
    name: "QG.PhotoSheetMixed",

    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== "QG_PhotoSheetMixed") return;

        const onCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onCreated?.apply(this, arguments);
            labelLayout(this);
            return r;
        };

        // 从已保存工作流加载时不走 onNodeCreated，补一道
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = onConfigure?.apply(this, arguments);
            labelLayout(this);
            return r;
        };
    },

    nodeCreated(node) {
        if (node?.comfyClass === "QG_PhotoSheetMixed" || node?.type === "QG_PhotoSheetMixed") {
            labelLayout(node);
        }
    },

    setup() {
        for (const node of app.graph?._nodes || []) labelLayout(node);
    },
});
