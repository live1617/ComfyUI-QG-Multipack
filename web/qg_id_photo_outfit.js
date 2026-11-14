/**
 * QG 证件照服装发型 —— 模板网格选择面板。
 *
 * 节点上点「选择模板」弹出浮动面板：顶部风格下拉（与节点 style 控件
 * 双向同步）、提示词展示区、搜索框（多关键词任意符号隔开，全部命中
 * 才保留）、缩略图网格；点选模板把其提示词写回 prompt_output 控件。
 * 数据与缩略图来自后端路由 /qg-multipack/id_photo/{templates,image}，
 * 素材目录 ComfyUI/models/id_photo/ 全部自备（格式见 README）。
 *
 * 独立实现，未复制上游源码。
 */
import { app } from "/scripts/app.js";

const API_TEMPLATES = "/qg-multipack/id_photo/templates";
const API_IMAGE = "/qg-multipack/id_photo/image";

/* ---------- 单例面板（多节点共用，打开时绑定当前节点） ---------- */

const panelState = {
    root: null,
    select: null,
    promptBox: null,
    searchInput: null,
    grid: null,
    hint: null,
    node: null,
    data: null,        // { categories, templates }
    selected: null,    // 当前选中的模板对象
};

function ensurePanel() {
    if (panelState.root) return panelState.root;

    const root = document.createElement("div");
    root.className = "qg-ipo-panel";
    root.innerHTML = [
        "<style>",
        ".qg-ipo-panel{position:fixed;z-index:99999;width:560px;max-width:92vw;",
        "  max-height:72vh;display:none;flex-direction:column;background:#1e2126;",
        "  border:1px solid #3a3f47;border-radius:8px;box-shadow:0 8px 30px rgba(0,0,0,.5);",
        "  color:#d6d9de;font:12px/1.5 sans-serif;}",
        ".qg-ipo-head{display:flex;align-items:center;gap:8px;padding:8px 10px;",
        "  border-bottom:1px solid #3a3f47;}",
        ".qg-ipo-title{font-weight:600;color:#e8eaee;white-space:nowrap;}",
        ".qg-ipo-close{margin-left:auto;background:transparent;border:0;color:#9aa0a8;",
        "  font-size:16px;cursor:pointer;padding:2px 8px;}",
        ".qg-ipo-close:hover{color:#fff;}",
        ".qg-ipo-select{flex:1;background:#15171b;color:#d6d9de;border:1px solid #444a52;",
        "  border-radius:4px;padding:4px 6px;}",
        ".qg-ipo-prompt{margin:8px 10px 0;padding:7px 9px;min-height:52px;max-height:96px;",
        "  overflow:auto;background:#15171b;border:1px solid #444a52;border-radius:4px;",
        "  color:#cdd2d9;white-space:pre-wrap;}",
        ".qg-ipo-prompt:focus{outline:none;border-color:#4CAF50;}",
        ".qg-ipo-searchrow{display:flex;gap:6px;margin:8px 10px 0;}",
        ".qg-ipo-search{flex:1;background:#15171b;color:#d6d9de;border:1px solid #444a52;",
        "  border-radius:4px;padding:5px 9px;}",
        ".qg-ipo-search:focus{outline:none;border-color:#4CAF50;}",
        ".qg-ipo-grid{flex:1;overflow:auto;display:grid;",
        "  grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:8px;",
        "  padding:10px;align-content:start;}",
        ".qg-ipo-item{position:relative;cursor:pointer;border-radius:6px;overflow:hidden;",
        "  border:2px solid transparent;background:#15171b;aspect-ratio:3/4;",
        "  display:flex;align-items:center;justify-content:center;}",
        ".qg-ipo-item:hover{border-color:#5a81ff;}",
        ".qg-ipo-item.qg-ipo-active{border-color:#4CAF50;}",
        ".qg-ipo-item img{width:100%;height:100%;object-fit:cover;display:block;}",
        ".qg-ipo-item .qg-ipo-fallback{color:#7d838c;font-size:11px;text-align:center;padding:6px;word-break:break-all;}",
        ".qg-ipo-item .qg-ipo-cap{position:absolute;left:0;right:0;bottom:0;padding:2px 5px;",
        "  background:rgba(0,0,0,.55);color:#e8eaee;font-size:10px;white-space:nowrap;",
        "  overflow:hidden;text-overflow:ellipsis;}",
        ".qg-ipo-hint{padding:16px 12px;color:#9aa0a8;text-align:center;line-height:1.8;}",
        "</style>",
        '<div class="qg-ipo-head">',
        '  <span class="qg-ipo-title">选择模板</span>',
        '  <select class="qg-ipo-select"></select>',
        '  <button class="qg-ipo-close" title="关闭">✕</button>',
        "</div>",
        '<div class="qg-ipo-prompt" contenteditable="true"></div>',
        '<div class="qg-ipo-searchrow">',
        '  <input class="qg-ipo-search" type="text" spellcheck="false"',
        '         placeholder="搜索模板（多关键词用任意符号隔开，如：西装 领带 男）">',
        "</div>",
        '<div class="qg-ipo-grid"></div>',
        '<div class="qg-ipo-hint" style="display:none"></div>',
    ].join("");
    document.body.appendChild(root);

    panelState.root = root;
    panelState.select = root.querySelector(".qg-ipo-select");
    panelState.promptBox = root.querySelector(".qg-ipo-prompt");
    panelState.searchInput = root.querySelector(".qg-ipo-search");
    panelState.grid = root.querySelector(".qg-ipo-grid");
    panelState.hint = root.querySelector(".qg-ipo-hint");

    root.querySelector(".qg-ipo-close").addEventListener("click", hidePanel);
    panelState.select.addEventListener("change", () => {
        const node = panelState.node;
        const value = panelState.select.value;
        const styleWidget = node && findWidget(node, "style");
        if (styleWidget && styleWidget.value !== value) {
            styleWidget.value = value;
            styleWidget.callback?.(value);
        }
        panelState.selected = null;
        renderGrid();
    });
    panelState.searchInput.addEventListener("input", renderGrid);
    // 提示词区手动编辑：失焦时写回控件（自定义提示词）
    panelState.promptBox.addEventListener("blur", () => {
        const node = panelState.node;
        if (!node || !panelState.selected) return;
        const widget = findWidget(node, "prompt_output");
        const text = panelState.promptBox.innerText.trim();
        if (widget && text && text !== widget.value) {
            widget.value = text;
            widget.callback?.(text);
        }
    });
    return root;
}

function hidePanel() {
    if (panelState.root) panelState.root.style.display = "none";
    panelState.node = null;
}

function findWidget(node, name) {
    return (node.widgets || []).find((w) => w.name === name) || null;
}

/* ---------- 数据加载与渲染 ---------- */

async function ensureData() {
    if (panelState.data) return panelState.data;
    const res = await fetch(API_TEMPLATES);
    if (!res.ok) throw new Error("HTTP " + res.status);
    panelState.data = await res.json();
    return panelState.data;
}

function imageUrl(category, filename) {
    return API_IMAGE + "/" + encodeURIComponent(category)
        + "/" + encodeURIComponent(filename);
}

function currentTemplates() {
    const data = panelState.data;
    if (!data) return [];
    const category = panelState.select.value;
    return (data.templates && data.templates[category]) || [];
}

function parseKeywords(text) {
    // 多关键词用任意非文字符号隔开：空格/逗号/顿号/斜杠/竖线等
    return (text || "").split(/[^\p{L}\p{N}]+/u).filter(Boolean);
}

function renderGrid() {
    const grid = panelState.grid;
    const hint = panelState.hint;
    grid.innerHTML = "";
    const items = currentTemplates();
    const words = parseKeywords(panelState.searchInput.value);

    if (!items.length) {
        hint.style.display = "block";
        hint.innerHTML = "该分类下没有素材。<br>把模板图放进 "
            + "<b>ComfyUI/models/id_photo/&lt;分类&gt;/</b>（jpg/png/webp，"
            + "提示词见 README），刷新页面或重开面板即可。";
        return;
    }
    hint.style.display = "none";

    const filtered = words.length
        ? items.filter((t) => words.every((w) => t.title.includes(w)))
        : items;
    if (!filtered.length) {
        hint.style.display = "block";
        hint.textContent = "没有匹配「" + panelState.searchInput.value + "」的模板";
        return;
    }

    const fragment = document.createDocumentFragment();
    for (const tpl of filtered) {
        const cell = document.createElement("div");
        cell.className = "qg-ipo-item";
        if (panelState.selected
            && panelState.selected.category === tpl.category
            && panelState.selected.filename === tpl.filename) {
            cell.classList.add("qg-ipo-active");
        }
        const img = document.createElement("img");
        img.src = imageUrl(tpl.category, tpl.filename);
        img.loading = "lazy";
        img.alt = tpl.title;
        img.addEventListener("error", () => {
            img.remove();
            const fb = document.createElement("div");
            fb.className = "qg-ipo-fallback";
            fb.textContent = tpl.title;
            cell.prepend(fb);
        });
        const cap = document.createElement("div");
        cap.className = "qg-ipo-cap";
        cap.textContent = tpl.title;
        cap.title = tpl.prompt || tpl.title;
        cell.append(img, cap);
        cell.addEventListener("click", () => chooseTemplate(tpl, cell));
        fragment.appendChild(cell);
    }
    grid.appendChild(fragment);
}

function chooseTemplate(tpl, cell) {
    panelState.selected = tpl;
    panelState.promptBox.innerText = tpl.prompt || "";
    for (const el of panelState.grid.querySelectorAll(".qg-ipo-active")) {
        el.classList.remove("qg-ipo-active");
    }
    cell.classList.add("qg-ipo-active");
    const node = panelState.node;
    const widget = node && findWidget(node, "prompt_output");
    if (widget) {
        widget.value = tpl.prompt || "";
        widget.callback?.(tpl.prompt || "");
    }
}

async function openPanel(node) {
    const root = ensurePanel();
    panelState.node = node;
    root.style.display = "flex";

    let data;
    try {
        data = await ensureData();
    } catch (err) {
        panelState.grid.innerHTML = "";
        panelState.hint.style.display = "block";
        panelState.hint.textContent = "加载模板列表失败：" + err.message
            + "（请确认后端已重启且版本 ≥ v2.8.0）";
        return;
    }

    // 风格下拉与节点 style 控件同步
    const styleWidget = findWidget(node, "style");
    const current = styleWidget ? String(styleWidget.value) : data.categories[0];
    const select = panelState.select;
    select.innerHTML = "";
    for (const cat of data.categories) {
        const opt = document.createElement("option");
        opt.value = cat;
        opt.textContent = cat;
        select.appendChild(opt);
    }
    if (data.categories.includes(current)) select.value = current;

    // 提示词区回显控件当前值
    const promptWidget = findWidget(node, "prompt_output");
    panelState.promptBox.innerText = promptWidget ? String(promptWidget.value || "") : "";
    panelState.selected = null;
    renderGrid();

    // 面板贴着节点右上弹出，越界自动收
    const rect = node.getBoundingClientRect ? node.getBoundingClientRect() : null;
    if (rect && rect.width) {
        const canvasRect = document.querySelector("canvas")?.getBoundingClientRect?.();
        if (canvasRect && (rect.right < canvasRect.left || rect.top > canvasRect.bottom)) {
            // 节点不在视口内（画布移动过）就走居中
            root.style.left = "50px";
            root.style.top = "60px";
            return;
        }
        const left = Math.min(rect.right + 8, window.innerWidth - root.offsetWidth - 12);
        const top = Math.max(12, Math.min(rect.top, window.innerHeight - root.offsetHeight - 12));
        root.style.left = Math.max(12, left) + "px";
        root.style.top = top + "px";
    } else {
        root.style.left = "50px";
        root.style.top = "60px";
    }
}

/* ---------- 节点接入 ---------- */

function enhance(node) {
    if (node.__qgIpoReady) return;
    if (!findWidget(node, "style") || !findWidget(node, "prompt_output")) return;
    node.__qgIpoReady = true;

    node.addWidget("button", "👔 选择模板", null, () => openPanel(node));
    // 按钮行加高，避免窄节点压扁
    const btn = (node.widgets || []).at(-1);
    if (btn && "y" in btn) {
        const last = btn;
        const origCompute = last.computeSize;
        last.computeSize = function (width) {
            const size = origCompute ? origCompute.apply(this, arguments) : [width, 26];
            return [size[0], 26];
        };
    }
}

app.registerExtension({
    name: "QG.IDPhotoOutfit",

    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== "QG_IDPhotoOutfit") return;

        const onCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onCreated?.apply(this, arguments);
            enhance(this);
            return r;
        };

        // 从已保存工作流加载时不走 onNodeCreated，补一道
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = onConfigure?.apply(this, arguments);
            enhance(this);
            return r;
        };
    },

    nodeCreated(node) {
        if (node?.comfyClass === "QG_IDPhotoOutfit" || node?.type === "QG_IDPhotoOutfit") {
            enhance(node);
        }
    },

    setup() {
        for (const node of app.graph?._nodes || []) enhance(node);
    },
});
