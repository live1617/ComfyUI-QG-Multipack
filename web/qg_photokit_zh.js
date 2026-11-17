// PhotoKit 六个节点的下拉中文 + 宽度贴合（并入 QG-Multipack）
// 扩展名 QG.photokit.zh；内置脚本用绝对路径 /scripts/app.js，
// 与包内其余前端文件一致（web/ 是按原目录树挂载的，相对路径换个层级就错）。
//
// Both nodes keep English slugs as the widget *values* - that is what the
// backend compares against and what a saved workflow holds. Only the label is
// swapped, through getOptionLabel, so an English UI keeps the raw values and a
// Chinese one reads "1寸（2.5 x 3.5 厘米）" instead of "1inch".
//
// Two nodes in one extension because they ship in one pack; the table below is
// the only thing that differs between them.

import { app } from "/scripts/app.js";

const ID_PHOTO_PRESETS = {
    "1inch": "1寸（2.5 x 3.5 厘米）",
    "1inch_large": "大1寸（3.3 x 4.8 厘米）",
    "2inch_small": "小2寸（3.5 x 4.5 厘米）",
    "2inch": "2寸（3.5 x 4.9 厘米）",
    "2inch_large": "大2寸（3.5 x 5.3 厘米）",
    "3inch": "3寸（5.5 x 8.5 厘米）",
    "5inch": "5寸（8.9 x 12.7 厘米）",
    "6inch": "6寸（10.1 x 15.2 厘米）",
    "id_card": "身份证社保（2.6 x 3.2 厘米）",
    "driver_license": "驾驶证（2.2 x 3.2 厘米）",
    "japan_visa": "日签（4.5 x 4.5 厘米）",
    "us_visa": "美签（5.1 x 5.1 厘米）",
    "postgrad_exam": "研究生考试（3.0 x 4.0 厘米）",
    "id_card_digital": "身份证电子（358 x 441 像素 350dpi）",
    "mandarin_exam": "普通话考试（390 x 567 像素 300dpi）",
    "teacher_exam": "教师资格证（480 x 640 像素 300dpi）",
    "nurse_exam": "护士资格证（160 x 210 像素 300dpi）",
    "judicial_exam": "司法考试照（413 x 626 像素 300dpi）",
    "medical_exam": "执业医考照（354 x 472 像素 300dpi）",
    "custom": "自定义尺寸",
};

const FONT_LABELS = {
    "<default>": "内置默认（无中文字形）",
    "msyh.ttc": "微软雅黑",
    "msyhbd.ttc": "微软雅黑 粗体",
    "simhei.ttf": "黑体",
    "simsun.ttc": "宋体",
    "simkai.ttf": "楷体",
    "simfang.ttf": "仿宋",
    "Deng.ttf": "等线",
};

// 证件照底色。值仍是 slug（后端与已保存的工作流都按它认），只换显示。
const BG_LABELS = {
    white: "白",
    blue: "蓝",
    darkblue: "深蓝",
    red: "红",
    lightblue: "浅蓝",
    gray: "灰",
    custom: "自定义（填色值）",
};

// widget name -> {value: label}. A widget not listed here is left alone.
//
// `width` only. Height is deliberately left to ComfyUI's own computeSize():
// hardcoding it means the next time a widget is added or removed the node
// carries a slab of empty space, which is exactly what [330, 470] did after
// the matting node shed its size widgets.
const NODES = {
    QG_IDPhotoParams: {
        // Eight widgets, short labels except the preset list.
        width: 300,
        widgets: {
            preset: ID_PHOTO_PRESETS,
            bg_color: BG_LABELS,
            bg_color_2: BG_LABELS,
            render: { pure: "纯色", vertical: "上下渐变", radial: "中心渐变" },
        },
    },
    QG_PortraitMatte: {
        // Twelve widgets plus the params socket. Nothing to translate here: the
        // only dropdown is the model filename, which is the thing being picked.
        width: 330,
        widgets: {},
    },
    QG_IDPhotoCrop: {
        // Thirteen widgets collapse to about 300 px on their own, which clips
        // the long preset names.
        width: 330,
        widgets: {
            preset: ID_PHOTO_PRESETS,
            unit: { cm: "厘米", px: "像素" },
            face_pick: { center: "取居中", largest: "取最大" },
            fill_mode: { border: "边框颜色", custom: "自定义颜色" },
        },
    },
    QG_PhotoSheet: {
        // Twelve widgets collapse to about 300 px, which clips "12.7" against
        // its label.
        width: 340,
        widgets: {
            font: FONT_LABELS,
        },
    },
    QG_IDCardSheet: {
        // "阴影不透明度" plus a four digit value needs the room.
        width: 340,
        widgets: {},
    },
    QG_Watermark: {
        width: 320,
        widgets: {
            font: FONT_LABELS,
        },
    },
};

function currentLocale() {
    try {
        const loc = globalThis.app?.i18n?.global?.locale;
        const value = typeof loc === "string" ? loc : loc?.value;
        if (typeof value === "string" && value) return value;
    } catch (err) {
        /* older frontend, fall through */
    }
    try {
        const value = globalThis.app?.ui?.settings?.getSettingValue?.("Comfy.Locale");
        if (typeof value === "string" && value) return value;
    } catch (err) {
        /* same */
    }
    try {
        return document?.documentElement?.lang || "";
    } catch (err) {
        return "";
    }
}

function wantsChinese() {
    return /^zh/i.test(currentLocale() || "");
}

function labelWidgets(node, table) {
    if (!wantsChinese()) return;
    for (const widget of node.widgets || []) {
        const names = table[widget?.name];
        if (!names) continue;
        widget.options = widget.options || {};
        widget.options.getOptionLabel = (value) => names[value] ?? value;
    }
}

app.registerExtension({
    name: "QG.photokit.zh",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const spec = NODES[nodeData?.name];
        if (!spec) return;

        // 打一个「尺寸来自工作流」的标记。加载顺序是
        // createNode()（此刻跑 onNodeCreated）→ node.configure(info)（把存档的 size 写回），
        // 而下面的 fit() 走 setTimeout，一定排在 configure 之后。
        // 不打标记的话，fit 会拿 computeSize() 的自然高度覆盖用户拉过的尺寸，
        // 表现就是「调好大小 → 存盘 → 重新打开又变回默认」。
        const priorConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (...args) {
            const result = priorConfigure?.apply(this, args);
            this._qgSizeFromWorkflow = true;
            return result;
        };

        const prior = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function (...args) {
            const result = prior?.apply(this, args);
            const label = `[${nodeData.name}]`;
            try {
                labelWidgets(this, spec.widgets);
            } catch (err) {
                console.warn(`${label} dropdown labels failed`, err);
            }
            // Resize a tick later: the creation pass recomputes the width after
            // this runs and would undo a synchronous setSize.
            //
            // Width: only ever grows. Narrower than spec clips the long option
            // names, wider is a choice the user made and is left alone.
            // Height: taken from computeSize(), so the node ends exactly where
            // the last widget ends.
            //
            // 两处都只对**新建节点**生效：尺寸来自工作流（或粘贴）的节点
            // 直接跳过，用户拉成什么样就是什么样。
            const self = this;
            const fit = () => {
                try {
                    if (self._qgSizeFromWorkflow) return;
                    let natural = null;
                    try {
                        // Pass the width we are about to use: a widget may lay
                        // itself out differently when it is wider.
                        const computed = self.computeSize?.([spec.width, 0]);
                        if (computed && Number.isFinite(computed[1]) && computed[1] > 40) {
                            natural = computed[1];
                        }
                    } catch (err) {
                        /* older frontend: fall back to whatever it already has */
                    }
                    const width = Math.max(self.size[0], spec.width);
                    const height = natural ?? self.size[1];
                    const tooNarrow = width !== self.size[0];
                    const tooTall = Math.abs(height - self.size[1]) > 8;
                    if (tooNarrow || tooTall) {
                        self.setSize([width, height]);
                        self.setDirtyCanvas?.(true, true);
                    }
                } catch (err) {
                    console.warn(`${label} resize failed`, err);
                }
            };
            setTimeout(fit, 0);
            // 有些控件的尺寸创建之后才定下来，一帧后再核一次。尺寸已经对了
            // 的话这一趟什么都不做。
            setTimeout(fit, 300);
            return result;
        };
    },
});
