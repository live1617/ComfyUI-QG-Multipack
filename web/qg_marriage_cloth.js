/**
 * QG 结婚登记照服装 —— 节点内嵌画廊。
 *
 * 界面形态参照 Goohaitools「孤海-结婚登记照服装」：节点体内直接显示
 * 「上方预览框（白框 + 已选绿标，未选时显示「无」）」+「下方缩略图网格」。
 * 点缩略图写回 `image_index`（序号）与隐藏控件 `cloth_name`（精确文件名）；
 * 手改序号时预览与高亮同步跟随。
 *
 * 与参照实现的差别：
 * 1. 列数随节点宽度自适应（上游固定 3 列 200x100），拉宽能一屏看更多；
 * 2. 选中状态存 node.properties，存盘/重开工作流自动还原；
 * 3. 再点已选中的卡片 = 取消选择（回到序号 0 纯色底）。
 *
 * 数据与缩略图来自 /qg-multipack/marriage_cloth/{list,image}。
 */
import { app } from "/scripts/app.js";

const NODE_NAME = "QG_MarriageCloth";
const API_LIST = "/qg-multipack/marriage_cloth/list";
const API_IMAGE = "/qg-multipack/marriage_cloth/image";

/* ---------- 布局常量 ---------- */
const THUMB_W = 200;         // 缩略图设计宽（素材统一 2:1）
const THUMB_RATIO = 0.5;     // 高 = 宽 × 0.5
const GAP = 8;
const PAD = 6;
const RADIUS = 10;
const BORDER_SEL = 3;
const NODE_W = 660;          // 初始尺寸（与参照实现同规格）
const NODE_H = 880;
const PV_MAX_W = 640;
const EMPTY_TEXT = "暂无服装素材。把图片放进 ComfyUI/models/marriage_cloth/"
    + "（jpg / png / webp），或使用插件内置素材，然后刷新页面。";

const COLOR_NODE = "#3a4d64";
const COLOR_NODE_BG = "#2c3849";
const COLOR_SEL = "#00cc00";
const COLOR_FLAT = "#6c1e27";   // 序号 0 的纯色底（与后端一致）

let _listCache = null;

async function loadList() {
    if (_listCache) return _listCache;
    try {
        const resp = await fetch(API_LIST);
        _listCache = await resp.json();
    } catch (e) {
        console.error("[QG-Multipack] 结婚登记照服装列表加载失败:", e);
        _listCache = { count: 0, images: [] };
    }
    return _listCache;
}

function imageUrl(name) {
    return API_IMAGE + "/" + encodeURIComponent(name);
}

function el(tag, css) {
    const node = document.createElement(tag);
    if (css) Object.assign(node.style, css);
    return node;
}

/* ---------- 节点接入 ---------- */

app.registerExtension({
    name: "QG.MarriageCloth",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_NAME) return;

        const origOnCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            origOnCreated?.apply(this, arguments);
            this.color = COLOR_NODE;
            this.bgcolor = COLOR_NODE_BG;
            buildPanel(this);
        };
    },
});

/* ---------- 面板构建 ---------- */

async function buildPanel(node) {
    if (node._qgMarriageBuilt) return;
    node._qgMarriageBuilt = true;

    const data = await loadList();
    const images = data.images || [];

    const idxWidget = node.widgets?.find((w) => w.name === "image_index");
    let nameWidget = node.widgets?.find((w) => w.name === "cloth_name");
    if (!nameWidget) {
        nameWidget = node.addWidget("text", "cloth_name", "", () => {});
        nameWidget.type = "hidden";
        nameWidget.hidden = true;
        nameWidget.computeSize = () => [0, -4];
    }

    let selectedName = "";
    let selectedIndex = 0;

    /* ---- DOM ---- */
    const root = el("div", {
        display: "flex",
        flexDirection: "column",
        boxSizing: "border-box",
        padding: PAD + "px",
        gap: "10px",
        overflow: "hidden",
        width: "100%",
        height: "100%",
        fontFamily: "'Microsoft YaHei','SimHei',Arial,sans-serif",
        fontSize: "12px",
        color: "#ddd",
        userSelect: "none",
    });

    const pvWrap = el("div", {
        position: "relative", width: "100%", flexShrink: "0",
        display: "flex", justifyContent: "center",
    });
    const pvBox = el("div", {
        position: "relative", width: "100%", height: "200px",
        borderRadius: RADIUS + "px", overflow: "hidden",
        border: "2px solid #ffffff", background: COLOR_FLAT,
        boxSizing: "border-box",
    });
    const pvImg = el("img", {
        width: "100%", height: "100%", objectFit: "cover", display: "none",
    });
    pvImg.draggable = false;
    const badge = el("div", {
        position: "absolute", top: "10px", left: "10px",
        background: COLOR_SEL, color: "#fff", padding: "3px 8px",
        borderRadius: "4px", fontSize: "13px", fontWeight: "bold",
        display: "none", zIndex: "10",
    });
    badge.textContent = "已选";
    const noneLabel = el("div", {
        position: "absolute", top: "50%", left: "50%",
        transform: "translate(-50%, -50%)",
        color: "#ffffff", fontSize: "24px", fontWeight: "bold",
        opacity: "0.85",
    });
    noneLabel.textContent = "无";
    pvBox.append(pvImg, badge, noneLabel);
    pvWrap.appendChild(pvBox);
    root.appendChild(pvWrap);

    const scroll = el("div", {
        flex: "1", minHeight: "0", overflowY: "auto", overflowX: "hidden",
    });
    const grid = el("div", {
        display: "grid", gap: GAP + "px", justifyContent: "center",
        gridTemplateColumns: "repeat(3, 1fr)",
    });
    scroll.appendChild(grid);
    root.appendChild(scroll);

    const dw = node.addDOMWidget("marriage_gallery", "marriage_gallery", root, {
        hideOnZoom: false,
        serialize: false,
        getMinHeight: () => 300,
    });
    if (dw) {
        dw.serialize = false;
        // 面板占满「节点高度 - 控件与标题区」，随拖拽实时重算
        dw.computeSize = (width) => {
            const total = node.size?.[1] || NODE_H;
            const chrome = 8 + (node.widgets?.length || 0) * 22 + 46;
            return [width ?? 0, Math.max(300, Math.round(total - chrome))];
        };
        if (dw.visibility?.surfaces) {
            dw.visibility.surfaces.canvas = "shown";
            dw.visibility.surfaces.panel = "never";
            dw.visibility.surfaces.vueNode = "shown";
        }
    }

    /* ---- 状态同步 ---- */

    function saveState() {
        if (!node.properties) node.properties = {};
        node.properties._qg_marriage_sel = {
            name: selectedName, index: selectedIndex,
        };
    }

    function highlight() {
        grid.querySelectorAll("[data-qg-hit]").forEach((card) => {
            const on = card.dataset.qgHit === selectedName;
            card.style.border = on
                ? BORDER_SEL + "px solid " + COLOR_SEL
                : "1px solid #ffffff";
            const ck = card.querySelector("[data-qg-check]");
            if (ck) ck.style.display = on ? "flex" : "none";
        });
    }

    function applySelection(index, name) {
        selectedIndex = Number(index) || 0;
        selectedName = name || "";
        if (idxWidget) idxWidget.value = selectedIndex;
        if (nameWidget) nameWidget.value = selectedName;

        const hit = images.find((it) => it.name === selectedName);
        if (hit) {
            pvImg.src = imageUrl(hit.name);
            pvImg.style.display = "block";
            badge.style.display = "block";
            noneLabel.style.display = "none";
        } else {
            pvImg.removeAttribute("src");
            pvImg.style.display = "none";
            badge.style.display = "none";
            noneLabel.style.display = "block";
        }
        highlight();
        saveState();
        node.setDirtyCanvas?.(true, true);
    }

    /* ---- 网格渲染 ---- */

    function renderGrid() {
        grid.innerHTML = "";
        if (!images.length) {
            const msg = el("div", {
                gridColumn: "1 / -1", textAlign: "center", color: "#888",
                padding: "40px 12px", fontSize: "13px", lineHeight: "1.6",
            });
            msg.textContent = EMPTY_TEXT;
            grid.appendChild(msg);
            return;
        }
        images.forEach((item) => {
            const card = el("div", {
                position: "relative", width: "100%", aspectRatio: "2 / 1",
                borderRadius: RADIUS + "px", overflow: "hidden",
                cursor: "pointer", border: "1px solid #ffffff",
                background: "#111", boxSizing: "border-box",
                transition: "border-color .15s ease",
            });
            card.dataset.qgHit = item.name;

            const im = el("img", {
                width: "100%", height: "100%", objectFit: "cover",
                display: "block", transition: "transform .2s ease",
                pointerEvents: "none",
            });
            im.src = imageUrl(item.name);
            im.loading = "lazy";
            im.draggable = false;

            const ck = el("div", {
                position: "absolute", top: "5px", right: "5px",
                width: "22px", height: "22px", background: COLOR_SEL,
                borderRadius: "50%", display: "none",
                alignItems: "center", justifyContent: "center",
                color: "#fff", fontSize: "13px", fontWeight: "bold",
                pointerEvents: "none", zIndex: "2",
            });
            ck.dataset.qgCheck = "1";
            ck.textContent = "✓";

            const lb = el("div", {
                position: "absolute", top: "5px", left: "5px",
                color: "#fff", fontSize: "12px", fontWeight: "bold",
                pointerEvents: "none", whiteSpace: "nowrap",
                overflow: "hidden", textOverflow: "ellipsis",
                maxWidth: "calc(100% - 40px)",
                textShadow: "0 1px 3px rgba(0,0,0,.9)",
            });
            lb.textContent = item.title;

            card.append(im, ck, lb);
            card.addEventListener("mouseenter", () => {
                im.style.transform = "scale(1.05)";
            });
            card.addEventListener("mouseleave", () => {
                im.style.transform = "scale(1)";
            });
            card.addEventListener("click", (e) => {
                e.stopPropagation();
                if (selectedName === item.name) {
                    applySelection(0, "");            // 再点一次 = 取消
                } else {
                    applySelection(item.index, item.name);
                }
            });

            grid.appendChild(card);
        });
    }

    /* ---- 列数与预览框尺寸随节点宽度自适应 ---- */
    function relayout() {
        const avail = Math.max(200, (node.size?.[0] || NODE_W) - PAD * 2 - 4);
        const cols = Math.max(2, Math.min(5,
            Math.floor((avail + GAP) / (THUMB_W + GAP))));
        grid.style.gridTemplateColumns = "repeat(" + cols + ", 1fr)";

        const pvW = Math.min(avail, PV_MAX_W);
        const maxH = Math.max(110, (node.size?.[1] || NODE_H) * 0.42);
        pvBox.style.width = pvW + "px";
        pvBox.style.height = Math.round(Math.min(pvW * THUMB_RATIO, maxH)) + "px";
    }

    /* ---- 序号控件回调 ---- */
    if (idxWidget) {
        const origCb = idxWidget.callback;
        idxWidget.callback = function (v) {
            origCb?.call(this, v);
            const num = Number(v) || 0;
            if (num <= 0) {
                applySelection(0, "");
                return;
            }
            const item = images.find((it) => it.index === num);
            applySelection(num, item ? item.name : "");
        };
    }

    /* ---- 尺寸变化 ---- */
    const origOnResize = node.onResize;
    node.onResize = function () {
        origOnResize?.apply(this, arguments);
        relayout();
        node.setDirtyCanvas?.(true, true);
    };

    /* ---- 初始化 ---- */
    renderGrid();

    const saved = node.properties?._qg_marriage_sel;
    if (saved && (saved.name || saved.index)) {
        const hit = images.find((it) => it.name === saved.name)
            || images.find((it) => it.index === saved.index);
        applySelection(hit ? hit.index : (saved.index || 0),
                       hit ? hit.name : "");
    } else {
        // 新节点：跟随后端控件默认值（默认 1 = 第一张）
        const cur = idxWidget ? (Number(idxWidget.value) || 0) : 1;
        const item = images.find((it) => it.index === cur);
        applySelection(cur, item ? item.name : "");
    }

    if (!node.size || node.size[0] < 320) {
        node.setSize?.([NODE_W, NODE_H]);
    }
    relayout();
}
