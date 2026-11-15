/**
 * QG 取色器 —— 把「字符串型颜色输入」变成图形化色块 + 弹出色板。
 *
 * 触发条件：节点定义里 COLOR_WIDGETS 列出的控件名。后端仍保持 STRING 类型，
 * 好处是：
 *   1. 工作流里存的就是 "#364254" 这样可读的字符串，老工作流完全兼容；
 *   2. 用户想手输十六进制也能输（色板里有输入框），不会被控件锁死；
 *   3. 后端不用改一行代码，PG 校验、API 提交路径都不受影响。
 *
 * 节点上的表现：原本的文本框换成一个色块 + 大写 HEX 文本，点一下弹色板。
 *
 * 弹层是自己画的 DOM 面板而不是原生 <input type="color">：
 *   原生取色器在不同浏览器里长相和交互差异很大，而且没法放常用预设色；
 *   自己画能保证和画布风格一致，也方便后续加「取屏幕颜色」之类的功能。
 */
import { app } from "/scripts/app.js";

const STYLE_ID = "qg-color-picker-style";
const FALLBACK = "#364254";

/** 需要图形化的颜色控件：节点注册 key → 控件名列表。要复用到别的节点，在这里加一行即可。 */
const COLOR_WIDGETS = {
    QG_BiRefNet: ["background_color"],
    QG_DualColorPicker: ["primary_color", "secondary_color"],
    QG_CustomColor: ["color1", "color2"],
    QG_FaceAlign: ["custom_fill_color"],
    QG_IDPhotoParams: ["bg_custom"],
    // 全包普查后补齐的 5 个纯颜色值控件。这些都是单一颜色输入（不像
    // QG_ColorConvert 的 color 还吃 HSL / RGB 整数 / 0-1 浮点，套色板反而是限制）。
    QG_IDPhotoCrop: ["fill_color"],
    QG_PhotoSheetMixed: ["border_color"],
    QG_IDCardSheet: ["bg_color"],
    QG_MarriageCloth: ["pad_color"],
    QG_Watermark: ["color"],
};

/**
 * 证件照底色：与后端 _matte_pipeline.BG_NAMED 一一对应（印刷蓝 #438edb，
 * 不是 CSS 蓝）。改后端色值时要同步这份表，否则「自定义色值」控件初始化出来
 * 的颜色会和真正渲染的底色对不上。
 */
const ID_PHOTO_BG_HEX = {
    white: "#ffffff",
    blue: "#438edb",
    darkblue: "#1b4b8f",
    red: "#d93b3b",
    gray: "#9a9a9a",
    lightblue: "#a8c8e8",
};

/**
 * 取色后要联动的下拉：节点类型 -> { 颜色控件: [下拉控件, 下拉值] }。
 * 证件照参数节点光改「自定义色值」没用 —— 后端 build() 只在「背景颜色」选了
 * custom 时才读它。所以取色时把这个下拉一并切到 custom，取色才真正生效。
 */
const LINKED_COMBO = {
    QG_IDPhotoParams: { bg_custom: ["bg_color", "custom"] },
};

/** 色板标题按控件给，不再一律写死「描边颜色」（那个词只对描边控件才对）。 */
const PANEL_TITLE = {
    background_color: "背景颜色",
    primary_color: "主色",
    secondary_color: "辅色",
    color1: "颜色 1",
    color2: "颜色 2",
    custom_fill_color: "自定义填充色",
    bg_custom: "自定义背景色",
    fill_color: "填充颜色",
    border_color: "边框颜色",
    bg_color: "底色",
    pad_color: "衬底颜色",
    color: "颜色",
};

/**
 * 这些控件改用「整块色块 + 居中文字」绘制（双色取色器的主色/辅色按钮），
 * 其余控件仍是胶囊底板 + 左侧小色块。文案存中英双串，绘制时才按界面语言取，
 * 不在模块顶层定稿（开发规范 §4.2）。
 */
const BANNER_TEXT = {
    primary_color: { en: "Primary", zh: "主色" },
    secondary_color: { en: "Secondary", zh: "辅色" },
    color1: { en: "Color 1", zh: "颜色1" },
    color2: { en: "Color 2", zh: "颜色2" },
};

/** 画布上画的字汉化插件够不到，这里延迟到绘制时判定界面语言。 */
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

function bannerLabel(name) {
    const pair = BANNER_TEXT[name];
    return pair ? (wantsChinese() ? pair.zh : pair.en) : "";
}

/** 预设色：按「中性色 / 暖色 / 冷色」三行排，每行 8 个，跟面板 8 列网格对齐。 */
const PRESETS = [
    "#000000", "#1F2328", "#364254", "#5B6675", "#8A94A6", "#C3CBD6", "#E8EDF3", "#FFFFFF",
    "#E5484D", "#F76808", "#FFB224", "#FFD60A", "#D9A066", "#8B5E3C", "#C2410C", "#7C2D12",
    "#30A46C", "#12A594", "#0090FF", "#3E63DD", "#6E56CF", "#8E4EC6", "#D6409F", "#0F766E",
];

const FONT = 'Inter, "Microsoft YaHei", "PingFang SC", Arial, sans-serif';

/* ------------------------------------------------------------------ *
 * 颜色工具
 * ------------------------------------------------------------------ */

/** 统一成小写 #rrggbb；#rgb / #rrggbbaa / 无 # 前缀都能吃。非法输入回退默认色。 */
function normHex(value, fallback = FALLBACK) {
    const t = String(value ?? "").trim().replace(/^#/, "");
    if (/^[0-9a-fA-F]{3}$/.test(t)) {
        return "#" + t.split("").map((c) => c + c).join("").toLowerCase();
    }
    if (/^[0-9a-fA-F]{6}$/.test(t)) return "#" + t.toLowerCase();
    if (/^[0-9a-fA-F]{8}$/.test(t)) return "#" + t.slice(0, 6).toLowerCase();
    return fallback;
}

/**
 * 这个控件里的值是不是「能安全规范化成 #rrggbb」的写法。
 *
 * 后端这些颜色控件大多还接受颜色名（white / red）、RGB 三元组（128,128,128）
 * 甚至灰度小数（0.5）。normHex 认不出这些写法会回退到默认灰 —— 那不是显示
 * 问题，而是会把工作流里存的值直接改写成另一个颜色。所以挂钩时只规范化这里
 * 认定为 hex 的值，其余一律原样保留，绘制时再用 normHex 降级显示色块即可。
 */
function isHexColor(value) {
    const t = String(value ?? "").trim().replace(/^#/, "");
    return /^[0-9a-fA-F]{3}$|^[0-9a-fA-F]{6}$|^[0-9a-fA-F]{8}$/.test(t);
}

/** 按背景亮度选对比色，保证色块上的勾选标记在任何底色上都看得见。 */
function isLight(hex) {
    const v = normHex(hex);
    const r = parseInt(v.slice(1, 3), 16);
    const g = parseInt(v.slice(3, 5), 16);
    const b = parseInt(v.slice(5, 7), 16);
    return (r * 299 + g * 587 + b * 114) / 1000 > 150;
}

/* ------------------------------------------------------------------ *
 * 主题色（ComfyUI 用 CSS 变量，不同主题下取值不同）
 * ------------------------------------------------------------------ */

let themeCache = { at: 0, value: null };

function getTheme() {
    const now = performance.now();
    if (themeCache.value && now - themeCache.at < 800) return themeCache.value;
    const cs = getComputedStyle(document.body);
    const pick = (name, fb) => (cs.getPropertyValue(name) || "").trim() || fb;
    themeCache = {
        at: now,
        value: {
            inputBg: pick("--comfy-input-bg", "#2a2a33"),
            border: pick("--border-color", "#4a4a55"),
            text: pick("--input-text", "") || pick("--fg-color", "#dddddd"),
            menuBg: pick("--comfy-menu-bg", "#1e1e24"),
            divider: pick("--border-color", "#3a3a44"),
        },
    };
    return themeCache.value;
}

/* ------------------------------------------------------------------ *
 * 节点上的色块控件
 * ------------------------------------------------------------------ */

function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") {
        ctx.roundRect(x, y, w, h, r);
        return;
    }
    // 老浏览器兜底
    const rr = Math.min(r, w / 2, h / 2);
    ctx.moveTo(x + rr, y);
    ctx.arcTo(x + w, y, x + w, y + h, rr);
    ctx.arcTo(x + w, y + h, x, y + h, rr);
    ctx.arcTo(x, y + h, x, y, rr);
    ctx.arcTo(x, y, x + w, y, rr);
    ctx.closePath();
}

/** 接管 widget 的绘制：胶囊底板 + 左侧色块 + HEX + 右侧取色提示。 */
function drawColorWidget(ctx, node, widget, width, y, H) {
    const h = H || 20;
    const theme = getTheme();
    const hex = normHex(widget.value);
    const x = 15;

    /* 不同前端版本传进来的 width 含义不一样：有的给整节点宽（含左右 15px 边距），
     * 有的已经减好了。用「是否接近节点总宽」来判断，避免底板戳出节点右边框。 */
    const nodeW = node.size?.[0] || 320;
    let innerW = Number.isFinite(width) && width > 0 ? width : nodeW - 30;
    if (innerW > nodeW - 24) innerW = nodeW - 30;
    innerW = Math.max(40, innerW);

    const by = y + 1;
    const bh = h - 2;

    ctx.save();

    // 胶囊底板：和其它输入控件同一套观感
    roundRect(ctx, x, by, innerW, bh, bh / 2);
    ctx.fillStyle = theme.inputBg;
    ctx.fill();
    ctx.strokeStyle = theme.border;
    ctx.lineWidth = 1;
    ctx.stroke();

    // 色块：四周留出明显内边距，不要填满整行（那样看不出是可点的控件）
    const chipInset = 3;
    const chipH = bh - chipInset * 2;
    const chipW = Math.max(16, Math.min(chipH * 2.1, innerW * 0.3));
    roundRect(ctx, x + chipInset, by + chipInset, chipW, chipH, Math.min(4, chipH / 3));
    ctx.fillStyle = hex;
    ctx.fill();
    ctx.strokeStyle = isLight(hex) ? "rgba(0,0,0,0.28)" : "rgba(255,255,255,0.28)";
    ctx.stroke();

    // 右侧取色提示：一个调色盘轮廓，暗示这行可以点开色板
    const iconR = Math.max(4, Math.min(6, bh * 0.28));
    const iconX = x + innerW - 12;
    const iconY = by + bh / 2;
    ctx.beginPath();
    ctx.arc(iconX, iconY, iconR, 0, Math.PI * 2);
    ctx.strokeStyle = withAlpha(theme.text, 0.55);
    ctx.lineWidth = 1.2;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(iconX, iconY, iconR * 0.34, 0, Math.PI * 2);
    ctx.fillStyle = hex;
    ctx.fill();

    // HEX 文本：在色块与图标之间
    ctx.fillStyle = theme.text;
    ctx.font = `12px ${FONT}`;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    const tx = x + chipInset + chipW + 9;
    const maxTx = iconX - iconR - 6;
    if (maxTx - tx > 24) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(tx, by, maxTx - tx, bh);
        ctx.clip(); // 节点被拖得很窄时文字自动截断，不压到图标
        ctx.fillText(hex.toUpperCase(), tx, iconY + 0.5);
        ctx.restore();
    }

    ctx.restore();
}

/** 整条背景就是颜色本身，文字居中（双色取色器的主色/辅色按钮）。 */
function drawBannerColorWidget(ctx, node, widget, width, y, H) {
    const h = H || 20;
    const hex = normHex(widget.value);
    const x = 15;

    const nodeW = node.size?.[0] || 320;
    let innerW = Number.isFinite(width) && width > 0 ? width : nodeW - 30;
    if (innerW > nodeW - 24) innerW = nodeW - 30;
    innerW = Math.max(40, innerW);

    const by = y + 1;
    const bh = h - 2;
    const light = isLight(hex);

    ctx.save();

    roundRect(ctx, x, by, innerW, bh, bh / 2);
    ctx.fillStyle = hex;
    ctx.fill();
    ctx.strokeStyle = light ? "rgba(0,0,0,0.32)" : "rgba(255,255,255,0.32)";
    ctx.lineWidth = 1;
    ctx.stroke();

    const text = `${bannerLabel(widget.name)} (${hex.toUpperCase()})`;
    ctx.fillStyle = light ? "#141418" : "#ffffff";
    ctx.font = `600 12px ${FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.save();
    ctx.beginPath();
    ctx.rect(x + 6, by, innerW - 12, bh);
    ctx.clip(); // 节点被拖窄时居中文字自动截断，不会溢出胶囊
    ctx.fillText(text, x + innerW / 2, by + bh / 2 + 0.5);
    ctx.restore();

    ctx.restore();
}

/** 给 '#rrggbb' 加透明度，返回 rgba()。 */
function withAlpha(hex, alpha) {
    const v = normHex(hex);
    const r = parseInt(v.slice(1, 3), 16);
    const g = parseInt(v.slice(3, 5), 16);
    const b = parseInt(v.slice(5, 7), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** 取色后把联动下拉切到指定值（证件照：切到 custom 让自定义色值真正生效）。 */
function applyLinkedCombo(node, widget) {
    const spec = LINKED_COMBO[node?.type]?.[widget?.name]
        || LINKED_COMBO[node?.comfyClass]?.[widget?.name];
    if (!spec) return;
    const [comboName, comboValue] = spec;
    const combo = (node.widgets || []).find((w) => w?.name === comboName);
    if (!combo || combo.value === comboValue) return;
    const prev = combo.value;
    combo.value = comboValue;
    try {
        combo.callback?.(comboValue, app.canvas, node, [0, 0], {});
    } catch (e) {
        console.warn("[QG 取色器] 联动下拉 callback 异常", e);
    }
    node.onWidgetChanged?.(comboName, comboValue, prev, combo);
}

/** 值变化后统一走这条路径：callback → 联动下拉 → 变更通知 → 重绘。 */
function applyColor(node, widget, raw) {
    // raw 来自色板 / HEX 输入框 / 系统取色器，都是合法色值；兜底固定用默认色，
    // 不能拿 widget.value 当 fallback —— 它可能是 white / 0.5 这种非 hex 写法。
    const next = normHex(raw, FALLBACK);
    const prev = widget.value;
    widget.value = next;

    if (prev !== next) {
        try {
            widget.callback?.(next, app.canvas, node, [0, 0], {});
        } catch (e) {
            console.warn("[QG 取色器] widget.callback 异常", e);
        }
        node.onWidgetChanged?.(widget.name, next, prev, widget);
        node.graph?.incrementVersion?.();
        applyLinkedCombo(node, widget);
    }
    node.setDirtyCanvas?.(true, true);
    app.canvas?.setDirty?.(true, true);
}

/**
 * 自定义色值初次挂钩时为空串，normHex("") 会得到默认灰 #364254 —— 画布上看着
 * 像用户填了个灰色，其实没生效。按当前「背景颜色」下拉初始化成对应的证件照底色，
 * 所见即所得；已是合法色值的老工作流不动。
 */
function seedFromCombo(node, widget) {
    if (widget?.name !== "bg_custom") return;
    if (String(widget.value ?? "").trim()) return;
    const combo = (node.widgets || []).find((w) => w?.name === "bg_color");
    const key = String(combo?.value ?? "blue").trim().toLowerCase();
    widget.value = ID_PHOTO_BG_HEX[key] || ID_PHOTO_BG_HEX.blue;
}

/* ------------------------------------------------------------------ *
 * 弹出色板
 * ------------------------------------------------------------------ */

let panel = null;
let panelOwner = null; // { node, widget }
let outsideHandler = null;
let keyHandler = null;

function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
.qgcp-panel {
    position: fixed;
    z-index: 2147483000;
    width: 268px;
    padding: 12px;
    border-radius: 10px;
    border: 1px solid var(--border-color, #3a3a44);
    background: var(--comfy-menu-bg, #1e1e24);
    color: var(--fg-color, #dddddd);
    font: 12px ${FONT};
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
    pointer-events: auto;
    user-select: none;
}
.qgcp-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 10px;
}
.qgcp-title { font-size: 12px; opacity: 0.75; letter-spacing: 0.05em; }
.qgcp-close {
    width: 20px; height: 20px; line-height: 18px;
    border-radius: 5px; border: none; cursor: pointer;
    background: transparent; color: inherit; opacity: 0.6; font-size: 14px;
}
.qgcp-close:hover { opacity: 1; background: var(--comfy-input-bg, #2a2a33); }
.qgcp-row {
    display: flex; align-items: center; gap: 8px; margin-bottom: 10px;
}
.qgcp-chip {
    width: 42px; height: 30px; border-radius: 6px; flex: none;
    border: 1px solid rgba(128, 128, 128, 0.45);
}
.qgcp-hex {
    flex: 1; min-width: 0; height: 30px; padding: 0 8px;
    border-radius: 6px; box-sizing: border-box;
    border: 1px solid var(--border-color, #3a3a44);
    background: var(--comfy-input-bg, #2a2a33);
    color: var(--input-text, #dddddd);
    font: 12px ui-monospace, Menlo, Consolas, monospace;
    outline: none;
}
.qgcp-hex:focus { border-color: #5b9dff; }
.qgcp-grid {
    display: grid;
    grid-template-columns: repeat(8, 1fr);
    gap: 6px;
    margin-bottom: 10px;
}
.qgcp-swatch {
    position: relative;
    aspect-ratio: 1 / 1;
    border-radius: 5px;
    cursor: pointer;
    border: 1px solid rgba(128, 128, 128, 0.35);
    transition: transform 0.08s ease;
}
.qgcp-swatch:hover { transform: scale(1.12); border-color: #5b9dff; }
.qgcp-swatch[data-active="1"]::after {
    content: "";
    position: absolute; inset: 0;
    border-radius: 4px;
    box-shadow: 0 0 0 2px #5b9dff inset;
}
.qgcp-foot {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
}
.qgcp-custom {
    display: inline-flex; align-items: center; gap: 6px;
    cursor: pointer; opacity: 0.85; padding: 4px 6px; border-radius: 6px;
}
.qgcp-custom:hover { opacity: 1; background: var(--comfy-input-bg, #2a2a33); }
.qgcp-custom input[type="color"] {
    width: 22px; height: 22px; padding: 0; border: none;
    border-radius: 5px; background: transparent; cursor: pointer;
}
.qgcp-btn {
    height: 26px; padding: 0 12px; border-radius: 6px; cursor: pointer;
    border: 1px solid var(--border-color, #3a3a44);
    background: var(--comfy-input-bg, #2a2a33);
    color: var(--fg-color, #dddddd);
    font: 12px ${FONT};
}
.qgcp-btn:hover { border-color: #5b9dff; }
`;
    document.head.appendChild(style);
}

function closePanel() {
    if (outsideHandler) {
        window.removeEventListener("pointerdown", outsideHandler, true);
        outsideHandler = null;
    }
    if (keyHandler) {
        window.removeEventListener("keydown", keyHandler, true);
        keyHandler = null;
    }
    panel?.remove();
    panel = null;
    panelOwner = null;
}

/** 面板锚点：优先用 widget 在画布上的最近绘制位置，取不到就退回鼠标位置。 */
function anchorOf(node, widget) {
    const canvas = app.canvas;
    const cv = canvas?.canvas;
    const ds = canvas?.ds;
    if (cv && ds) {
        const rect = cv.getBoundingClientRect();
        const localY = Number.isFinite(widget.last_y) ? widget.last_y : 40;
        const gx = (node.pos?.[0] ?? 0) + (node.size?.[0] ?? 200) + 8;
        const gy = (node.pos?.[1] ?? 0) + localY;
        return {
            x: rect.left + (gx + ds.offset[0]) * ds.scale,
            y: rect.top + (gy + ds.offset[1]) * ds.scale,
        };
    }
    return { x: window.innerWidth / 2 - 134, y: window.innerHeight / 2 - 120 };
}

function openPicker(node, widget) {
    ensureStyle();

    // 同一个控件再点一次 = 收起（当成开关用）
    if (panel && panelOwner?.node === node && panelOwner?.widget === widget) {
        closePanel();
        return;
    }
    closePanel();

    const el = document.createElement("div");
    el.className = "qgcp-panel";
    // reka-ui / Vue 弹层会靠这个属性判断"点外面该不该关"，标上后点击不会被它们吞掉
    el.dataset.dismissableLayer = "";

    const title = PANEL_TITLE[widget?.name] || "选择颜色";
    el.innerHTML = `
        <div class="qgcp-head">
            <span class="qgcp-title">${title}</span>
            <button class="qgcp-close" title="关闭">×</button>
        </div>
        <div class="qgcp-row">
            <div class="qgcp-chip"></div>
            <input class="qgcp-hex" maxlength="7" spellcheck="false" />
        </div>
        <div class="qgcp-grid"></div>
        <div class="qgcp-foot">
            <label class="qgcp-custom" title="打开系统调色器">
                <input type="color" />
                <span>自定义</span>
            </label>
            <button class="qgcp-btn">完成</button>
        </div>
    `;

    const chip = el.querySelector(".qgcp-chip");
    const hexInput = el.querySelector(".qgcp-hex");
    const grid = el.querySelector(".qgcp-grid");
    const colorInput = el.querySelector('input[type="color"]');

    const syncUi = () => {
        const hex = normHex(widget.value);
        chip.style.background = hex;
        colorInput.value = hex;
        if (document.activeElement !== hexInput) hexInput.value = hex.toUpperCase();
        for (const s of grid.children) {
            s.dataset.active = s.dataset.hex === hex ? "1" : "0";
        }
    };

    for (const hex of PRESETS) {
        const sw = document.createElement("div");
        sw.className = "qgcp-swatch";
        sw.dataset.hex = hex;
        sw.style.background = hex;
        sw.title = hex.toUpperCase();
        sw.addEventListener("pointerdown", (e) => {
            e.preventDefault();
            e.stopPropagation();
            applyColor(node, widget, hex);
            syncUi();
            closePanel(); // 选预设色就直接收工，省一次点击
        });
        grid.appendChild(sw);
    }

    // 手动输 HEX：边输边预览，合法才落到节点上（避免半截 "#3" 把颜色打乱）
    hexInput.addEventListener("input", () => {
        let t = hexInput.value.trim().replace(/^#/, "");
        if (/^[0-9a-fA-F]{3}$|^[0-9a-fA-F]{6}$/.test(t)) {
            const hex = normHex(t);
            chip.style.background = hex;
            colorInput.value = hex;
            applyColor(node, widget, hex);
            for (const s of grid.children) s.dataset.active = s.dataset.hex === hex ? "1" : "0";
        }
    });
    hexInput.addEventListener("keydown", (e) => {
        e.stopPropagation(); // 别让画布抢走快捷键
        if (e.key === "Enter" || e.key === "Escape") {
            e.preventDefault();
            closePanel();
        }
    });
    hexInput.addEventListener("blur", syncUi);

    // 系统调色器：适合从别处取到的精确颜色
    colorInput.addEventListener("input", () => {
        applyColor(node, widget, colorInput.value);
        syncUi();
    });

    el.querySelector(".qgcp-close").addEventListener("click", (e) => {
        e.stopPropagation();
        closePanel();
    });
    el.querySelector(".qgcp-btn").addEventListener("click", (e) => {
        e.stopPropagation();
        closePanel();
    });

    // 面板内所有指针事件都不往上冒：否则画布会把点击当成"点到空白处"清空选择
    ["pointerdown", "mousedown", "click", "dblclick"].forEach((type) => {
        el.addEventListener(type, (e) => e.stopPropagation());
    });

    document.body.appendChild(el);

    const at = anchorOf(node, widget);
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    el.style.left = Math.round(Math.max(8, Math.min(at.x, window.innerWidth - w - 8))) + "px";
    el.style.top = Math.round(Math.max(8, Math.min(at.y, window.innerHeight - h - 8))) + "px";

    panel = el;
    panelOwner = { node, widget };
    syncUi();

    // 点面板外面关闭。用捕获阶段，保证即使有别的层拦了冒泡也能收到
    outsideHandler = (e) => {
        if (panel && !panel.contains(e.target)) closePanel();
    };
    window.addEventListener("pointerdown", outsideHandler, true);

    keyHandler = (e) => {
        if (e.key === "Escape") {
            e.preventDefault();
            closePanel();
        }
    };
    window.addEventListener("keydown", keyHandler, true);
}

/* ------------------------------------------------------------------ *
 * 挂钩子
 * ------------------------------------------------------------------ */

function hookNode(node) {
    const names = COLOR_WIDGETS[node?.type] || COLOR_WIDGETS[node?.comfyClass];
    if (!names || !Array.isArray(node.widgets)) return;

    // 浮层是挂在 document.body 上的独立 DOM，不会随节点一起销毁。
    // 删掉节点 / 清空画布 / 扩展热重载时不收起来，就会留一个指向已失效
    // widget 的孤儿面板，越攒越多。onRemoved 是 LiteGraph 的删除钩子，
    // 这里只挂一次并保留原实现的返回值。
    if (!node.__qgColorRemovedHooked) {
        node.__qgColorRemovedHooked = true;
        const originalRemoved = node.onRemoved;
        node.onRemoved = function () {
            const r = originalRemoved?.apply(this, arguments);
            if (panelOwner?.node === this) closePanel();
            return r;
        };
    }

    // 控件还没建出来时（个别版本 nodeCreated 早于 widget 创建）下一轮再补
    if (node.widgets.length === 0) {
        if (!node.__qgColorRetry) {
            node.__qgColorRetry = true;
            setTimeout(() => {
                node.__qgColorRetry = false;
                hookNode(node);
            }, 0);
        }
        return;
    }

    for (const name of names) {
        const widget = node.widgets.find((w) => w?.name === name);
        if (!widget || widget.__qgColor) continue;
        widget.__qgColor = true;

        // 证件照「自定义色值」空串先按当前背景色种一个值，再统一成标准形态
        seedFromCombo(node, widget);
        // 老工作流里可能存着 "#abc" / "364254" 这种写法，统一成标准形态。
        // 但 white / 128,128,128 / 0.5 这类后端支持的非 hex 写法必须原样保留 ——
        // normHex 会把它们回退成默认灰，等于悄悄改了用户存的颜色。
        if (isHexColor(widget.value)) {
            widget.value = normHex(widget.value);
        }

        const painter = BANNER_TEXT[widget.name] ? drawBannerColorWidget : drawColorWidget;
        widget.draw = function (ctx, n, width, y, H) {
            painter(ctx, n, this, width, y, H);
        };

        // 老路径（普通 widget）走 mouse；新路径（具体 widget）走 onClick，两个都挂上
        widget.mouse = function (event, _pos, n) {
            const type = event?.type;
            if (type === "pointerdown" || type === "mousedown") {
                openPicker(n || node, this);
                return true;
            }
            return false;
        };
        widget.onClick = function () {
            openPicker(node, widget);
        };
    }
}

app.registerExtension({
    name: "QG.ColorPicker",

    /**
     * 三路兜底，因为"什么时候挂上"在不同加载顺序下不一样：
     *   1. beforeRegisterNodeDef —— 正常启动时扩展先加载，patch 节点原型；
     *   2. nodeCreated —— 节点创建后的统一回调，覆盖粘贴/复制/子图里的节点；
     *   3. setup —— 扩展比节点定义晚加载时，把画布上已有的节点补上。
     * 三者都用 __qgColor 去重，重复调用无副作用。
     */
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (!COLOR_WIDGETS[nodeData?.name]) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated?.apply(this, arguments);
            hookNode(this);
            return r;
        };

        // 从已保存工作流加载时不会走 onNodeCreated，补一道
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = onConfigure?.apply(this, arguments);
            hookNode(this);
            return r;
        };
    },

    nodeCreated(node) {
        hookNode(node);
    },

    setup() {
        for (const node of app.graph?._nodes || []) hookNode(node);
    },
});
