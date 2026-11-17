/**
 * QG 排版节点 —— 常用纸型尺寸预设（纯前端辅助控件）。
 *
 * 作用于两个节点：
 *   · QG_PhotoSheet（单张照片铺满相纸）：5/6/7/8 寸冲印纸 + A4/A5；
 *   · QG_MultiPhotoSheet（多人证件照拼版）：A4/A5/B5/信纸 + A4 横向。
 *
 * 关键设计：预设下拉是「注入的辅助控件」，设 serialize:false，因此
 *   1. 不进工作流存档的 widgets_values —— 后端契约一个字都不用改，老工作流
 *      完全兼容，API 提交路径不受影响；
 *   2. 选预设只是把 纸宽 / 纸高 / DPI 三个真实控件填好，真正决定出图的仍是
 *      那三个控件里的值（它们照常序列化）。
 *
 * 手动改了纸宽 / 纸高 / DPI 后下拉自动回到「自定义」，避免显示与实际不符。
 * 预设色值与本包 qg_color_picker.js 无关，两个扩展互不干扰。
 */
import { app } from "/scripts/app.js";

const CUSTOM = "custom";

/**
 * 每个节点一份预设表。w/h 单位厘米，dpi 为该纸型冲印常用值。
 * label 用中英双串：英文界面读 en，中文界面读 zh；值存英文 slug。
 */
const PRESETS = {
    QG_PhotoSheet: {
        "photo_5r": { w: 12.7, h: 8.9, dpi: 350, en: "5R 5x3.5in", zh: "5寸（12.7 x 8.9 厘米）" },
        "photo_6r": { w: 15.2, h: 10.1, dpi: 350, en: "6R 6x4in", zh: "6寸（15.2 x 10.1 厘米）" },
        "photo_7r": { w: 17.8, h: 12.7, dpi: 350, en: "7R 7x5in", zh: "7寸（17.8 x 12.7 厘米）" },
        "photo_8r": { w: 20.3, h: 15.2, dpi: 350, en: "8R 8x6in", zh: "8寸（20.3 x 15.2 厘米）" },
        "a5": { w: 14.8, h: 21.0, dpi: 300, en: "A5 14.8x21cm", zh: "A5（14.8 x 21 厘米）" },
        "a4": { w: 21.0, h: 29.7, dpi: 300, en: "A4 21x29.7cm", zh: "A4（21 x 29.7 厘米）" },
    },
    QG_MultiPhotoSheet: {
        "a4": { w: 21.0, h: 29.7, dpi: 300, en: "A4 21x29.7cm", zh: "A4（21 x 29.7 厘米）" },
        "a5": { w: 14.8, h: 21.0, dpi: 300, en: "A5 14.8x21cm", zh: "A5（14.8 x 21 厘米）" },
        "b5": { w: 17.6, h: 25.0, dpi: 300, en: "ISO B5 17.6x25cm", zh: "B5（17.6 x 25 厘米）" },
        "letter": { w: 21.59, h: 27.94, dpi: 300, en: "Letter 8.5x11in", zh: "信纸（21.6 x 27.9 厘米）" },
        "a4_landscape": { w: 29.7, h: 21.0, dpi: 300, en: "A4 landscape", zh: "A4 横向（29.7 x 21 厘米）" },
    },
};

/** 三个被预设改写的真实控件，按节点实际字段名（两者都是这套名字）。 */
const SIZE_WIDGETS = ["paper_w", "paper_h", "dpi"];

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

function presetLabel(key, spec) {
    if (key === CUSTOM) return wantsChinese() ? "自定义尺寸" : "Custom";
    return wantsChinese() ? spec?.zh || key : spec?.en || key;
}

function findWidget(node, name) {
    return (node?.widgets || []).find((w) => w?.name === name);
}

/** 把值写进真实控件并触发 ComfyUI 的标准变更路径（存档/重绘/执行都走它）。 */
function setSizeValue(node, name, value) {
    const widget = findWidget(node, name);
    if (!widget) return;
    const prev = widget.value;
    widget.value = value;
    try {
        widget.callback?.(value, app.canvas, node, [0, 0], {});
    } catch (err) {
        console.warn("[QG 纸型预设] 控件 callback 异常", err);
    }
    node.onWidgetChanged?.(name, value, prev, widget);
    node.graph?.incrementVersion?.();
}

/** 选中预设：填纸宽 / 纸高 / DPI；custom 不动任何控件。 */
function applyPreset(node, key) {
    if (key === CUSTOM) return;
    const nodeKey = node?.type || node?.comfyClass;
    const spec = PRESETS[nodeKey]?.[key];
    if (!spec) return;
    // 防止下面写控件时触发的 onWidgetChanged 把下拉自己复位成 custom。
    node._qgSheetPresetApplying = true;
    try {
        setSizeValue(node, "paper_w", spec.w);
        setSizeValue(node, "paper_h", spec.h);
        setSizeValue(node, "dpi", spec.dpi);
    } finally {
        node._qgSheetPresetApplying = false;
    }
    node.setDirtyCanvas?.(true, true);
}

/** 用户手动改了尺寸 → 下拉回「自定义」，避免显示和实际尺寸对不上。 */
function watchManualEdit(node) {
    if (node.__qgSheetPresetWatching) return;
    node.__qgSheetPresetWatching = true;
    const prior = node.onWidgetChanged;
    node.onWidgetChanged = function (name, value, oldValue, widget) {
        const result = prior?.apply(this, arguments);
        if (!this._qgSheetPresetApplying && SIZE_WIDGETS.includes(name)) {
            const combo = this._qgSheetPresetWidget;
            if (combo && combo.value !== CUSTOM) {
                combo.value = CUSTOM;
                this.setDirtyCanvas?.(true, true);
            }
        }
        return result;
    };
}

/** 把注入的辅助控件挪到 widgets 数组最前，令其显示在节点顶部。
 *  serialize:false 的控件不占 widgets_values 位次，挪动不影响存档/执行映射。 */
function moveWidgetToTop(node, widget) {
    const widgets = node?.widgets;
    if (!Array.isArray(widgets)) return;
    const idx = widgets.indexOf(widget);
    if (idx <= 0) return;
    widgets.splice(idx, 1);
    widgets.unshift(widget);
}

function hookNode(node) {
    const nodeKey = node?.type || node?.comfyClass;
    const table = PRESETS[nodeKey];
    if (!table || !Array.isArray(node?.widgets)) return;
    if (node.__qgmpSheetPreset) return;

    // 控件可能晚于 onNodeCreated 才建好，下一轮再补（与色板扩展同样的兜底）。
    if (SIZE_WIDGETS.some((name) => !findWidget(node, name))) {
        if (!node.__qgSheetPresetRetry) {
            node.__qgSheetPresetRetry = true;
            setTimeout(() => {
                node.__qgSheetPresetRetry = false;
                hookNode(node);
            }, 0);
        }
        return;
    }

    node.__qgmpSheetPreset = true;
    const keys = [CUSTOM, ...Object.keys(table)];
    const combo = node.addWidget(
        "combo", "常用尺寸", CUSTOM,
        (value) => applyPreset(node, value),
        { values: keys, serialize: false });
    if (!combo) return;
    // 双重保险：不同前端版本一个看 options、一个看 widget 本身。
    combo.serialize = false;
    combo.options = { ...(combo.options || {}), serialize: false };
    combo.options.getOptionLabel = (value) => presetLabel(value, table[value]);
    node._qgSheetPresetWidget = combo;
    // 挪到 widgets 最前 → 节点顶部显示（serialize:false 不占存档位次，映射不变）。
    moveWidgetToTop(node, combo);
    watchManualEdit(node);
    node.setDirtyCanvas?.(true, true);
}

app.registerExtension({
    name: "QG.Multipack.SheetSizePreset",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!PRESETS[nodeData?.name]) return;

        const priorCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = priorCreated?.apply(this, arguments);
            hookNode(this);
            return r;
        };
        const priorConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = priorConfigure?.apply(this, arguments);
            hookNode(this);
            return r;
        };
    },
    nodeCreated(node) {
        hookNode(node);
    },
    setup() {
        // 扩展比节点定义晚加载时，把画布上已有的节点补上。
        for (const node of app.graph?.nodes || []) hookNode(node);
    },
});
