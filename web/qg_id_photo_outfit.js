/**
 * QG 证件照服装发型 —— 节点内嵌模板选择面板（v2.9.0 重做）。
 *
 * 界面形态与 Goohaitools「孤海-证件照服装发型」一致（用户要求界面一样）：
 * 节点内嵌 DOM 面板，顶部横排「当前选中预览框(左) + 提示词文本框/搜索框(右)」，
 * 下方 4 列缩略图网格；选中模板绿框高亮 + ✓ 徽章，点预览框或再点选中卡取消；
 * 搜索支持多关键词（任意符号隔开，全部命中才保留），搜索时跨全部分类并
 * 显示分类角标；原生「提示词输出」控件隐藏，由面板内文本框替代并双向同步；
 * 画廊高度随节点缩放自适应，选择状态存 node.properties 刷新/存档不丢。
 *
 * 数据与缩略图来自后端路由 /qg-multipack/id_photo/{templates,image}，
 * 素材目录 ComfyUI/models/id_photo/ 全部自备（格式见 README）。
 * 布局尺寸、交互逻辑参照孤海公开行为对齐；代码为本包独立实现，未复制上游源码。
 */
import { app } from "/scripts/app.js";

const NODE_NAME = "QG_IDPhotoOutfit";
const API_TEMPLATES = "/qg-multipack/id_photo/templates";
const API_IMAGE = "/qg-multipack/id_photo/image";

/* ---------- 布局常量（与孤海界面同规格） ---------- */
const THUMB_W = 128;            // 缩略图宽
const THUMB_H = 180;            // 缩略图高
const GAP = 5;                  // 网格间距
const BORDER_RADIUS = 10;       // 卡片圆角
const COLS = 4;                 // 设计列数
const SCROLLBAR_EXTRA = 10;     // 滚动条预留
const GALLERY_WIDTH = COLS * THUMB_W + (COLS - 1) * GAP + SCROLLBAR_EXTRA;
const BORDER_HIGHLIGHT = 3;     // 选中绿框宽度
const SEARCH_AREA_H = 34;       // 搜索框区域高
const INNER_GAP = 6;            // 提示词框与搜索框间距
const PROMPT_TEXTAREA_H = THUMB_H - INNER_GAP - SEARCH_AREA_H;
const TOP_ROW_GAP = 15;         // 预览框与右列间距
const BOTTOM_PAD = 20;          // 底部留白
// 空分类（未放素材）时网格里的指引文案
const EMPTY_GUIDE = "未找到素材。把模板图放进 ComfyUI/models/id_photo/<分类>/"
    + "（jpg/png/webp，命名与提示词格式见 README），然后刷新页面。";

let _dataCache = null;

async function loadTemplateData() {
    if (_dataCache) return _dataCache;
    try {
        const resp = await fetch(API_TEMPLATES);
        _dataCache = await resp.json();
    } catch (e) {
        console.error("[QG-Multipack] 加载模板数据失败:", e);
        _dataCache = { categories: [], templates: {} };
    }
    return _dataCache;
}

/* ---------- UI 辅助元素 ---------- */

function createCheckmark() {
    const el = document.createElement("div");
    el.textContent = "✓";
    Object.assign(el.style, {
        position: "absolute", top: "2px", right: "2px",
        width: "18px", height: "18px",
        background: "#4CAF50", borderRadius: "50%",
        display: "flex", alignItems: "center", justifyContent: "center",
        color: "#fff", fontSize: "13px", fontWeight: "bold",
        zIndex: "10", pointerEvents: "none",
        boxShadow: "0 1px 4px rgba(0,0,0,0.4)",
    });
    return el;
}

function createSelectedBadge() {
    const el = document.createElement("div");
    el.textContent = "已选";
    Object.assign(el.style, {
        position: "absolute", top: "4px", left: "4px",
        padding: "2px 6px",
        background: "#4CAF50",
        borderRadius: "4px",
        display: "flex", alignItems: "center", justifyContent: "center",
        color: "#fff", fontSize: "10px", fontWeight: "bold",
        zIndex: "10", pointerEvents: "none",
        boxShadow: "0 1px 4px rgba(0,0,0,0.4)",
        whiteSpace: "nowrap",
    });
    return el;
}

function createImageFallback(parent, title, width, height, borderRadius) {
    const fb = document.createElement("div");
    Object.assign(fb.style, {
        width, height,
        display: "flex", alignItems: "center", justifyContent: "center",
        background: "#333", color: "#999", fontSize: "11px",
        padding: "4px", textAlign: "center", borderRadius,
    });
    fb.textContent = title;
    parent.appendChild(fb);
}

/* ---------- 关键词切分：任意非文字符号隔开 ---------- */

function parseKeywords(text) {
    return (text || "").split(/[^\p{L}\p{N}]+/u).filter(Boolean);
}

/* ---------- 节点接入 ---------- */

app.registerExtension({
    name: "QG.IDPhotoOutfit",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_NAME) return;

        const origOnCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            origOnCreated?.apply(this, arguments);
            this.color = "#3a4d64";
            this.bgcolor = "#2c3849";
            this._initOutfitUI();
        };

        nodeType.prototype._initOutfitUI = async function () {
            const node = this;
            const data = await loadTemplateData();

            const allTemplates = data.templates || {};
            const allCategories = data.categories || [];

            // ========== 状态变量 ==========
            const defaultCat = allCategories[0] || "";
            let currentCategory = defaultCat;
            let searchQuery = "";
            let isSearching = false;
            let selectedCategory = "";
            let selectedFilename = "";
            let selectedPrompt = "";
            let _lastSyncedValue = "";
            let _lastAppliedMaxH = 0;

            // ========== 提示词输出控件（原生控件隐藏，由面板文本框替代） ==========
            const promptWidget = node.widgets?.find((w) => w.name === "prompt_output");
            if (promptWidget) {
                _lastSyncedValue = promptWidget.value || "";
            }

            // ========== 挂接「style」下拉回调：切分类重渲染 ==========
            const catWidget = node.widgets?.find((w) => w.name === "style");
            if (catWidget) {
                const origCb = catWidget.callback;
                catWidget.callback = function (v) {
                    origCb?.call(this, v);
                    currentCategory = v;
                    searchQuery = "";
                    isSearching = false;
                    searchInput.value = "";
                    clearBtn.style.display = "none";
                    renderGallery();
                };
            }

            // ========== 辅助函数 ==========

            function syncPrompt() {
                if (promptWidget) {
                    promptWidget.value = selectedPrompt;
                    const el = promptWidget.element;
                    if (el) {
                        const ta = el.tagName === "TEXTAREA" ? el : el.querySelector?.("textarea");
                        if (ta) ta.value = selectedPrompt;
                    }
                }
                promptArea.value = selectedPrompt;
                _lastSyncedValue = selectedPrompt;
            }

            function findTemplate(cat, fname) {
                return (allTemplates[cat] || []).find((t) => t.filename === fname);
            }

            function saveSelectionState() {
                if (!node.properties) node.properties = {};
                const actualPrompt = promptWidget ? (promptWidget.value || "") : selectedPrompt;
                if (selectedFilename && selectedCategory) {
                    node.properties._qg_outfit_sel = {
                        cat: selectedCategory,
                        file: selectedFilename,
                        curCat: currentCategory,
                        prompt: actualPrompt,
                    };
                } else {
                    node.properties._qg_outfit_sel = {
                        _none: true,
                        curCat: currentCategory,
                        prompt: actualPrompt,
                    };
                }
            }

            function deselectAll() {
                selectedCategory = "";
                selectedFilename = "";
                selectedPrompt = "";
                syncPrompt();
                saveSelectionState();
                renderGallery();
            }

            function selectTemplate(tpl) {
                selectedCategory = tpl.category;
                selectedFilename = tpl.filename;
                selectedPrompt = tpl.prompt || "";
                syncPrompt();
                saveSelectionState();
                renderGallery();
            }

            function buildDisplayList() {
                let pool = [];
                if (isSearching) {
                    // 搜索时跨全部分类，关键词须同时命中（分类/标题/提示词任一含即可）
                    const keywords = parseKeywords(searchQuery);
                    for (const cat of allCategories) {
                        for (const tpl of (allTemplates[cat] || [])) {
                            const catLower = cat.toLowerCase();
                            const titleLower = tpl.title.toLowerCase();
                            const promptLower = (tpl.prompt || "").toLowerCase();
                            const allMatch = keywords.every((kw) =>
                                catLower.includes(kw)
                                || titleLower.includes(kw)
                                || promptLower.includes(kw)
                            );
                            if (allMatch) pool.push(tpl);
                        }
                    }
                } else {
                    pool = (allTemplates[currentCategory] || []).slice();
                }

                const list = [];
                const sel = selectedFilename && selectedCategory
                    ? findTemplate(selectedCategory, selectedFilename)
                    : null;

                // 首格固定为「当前选中」预览（无选中则「无」占位）
                list.push(sel
                    ? { _kind: "first_preview", ...sel, _isSel: false, _isFirst: true }
                    : { _kind: "none", title: "无", prompt: "", _isSel: false, _isFirst: true }
                );

                for (const tpl of pool) {
                    const isSelected = !!sel
                        && tpl.category === selectedCategory
                        && tpl.filename === selectedFilename;
                    list.push({ _kind: "item", ...tpl, _isSel: isSelected, _isFirst: false });
                }

                return { items: list, poolCount: pool.length };
            }

            // ==================== DOM 构建 ====================

            const container = document.createElement("div");
            Object.assign(container.style, {
                width: "100%",
                boxSizing: "border-box",
                fontFamily: "'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif",
                padding: "0px 4px 4px 4px",
            });

            // ---- 顶部横排：预览框(左) + 提示词/搜索(右) ----

            const topRow = document.createElement("div");
            Object.assign(topRow.style, {
                display: "flex",
                flexDirection: "row",
                alignItems: "flex-start",
                width: "100%",
                gap: `${TOP_ROW_GAP}px`,
                marginBottom: "6px",
            });

            // ---- 左侧预览框（点击=取消选择） ----
            const previewBox = document.createElement("div");
            Object.assign(previewBox.style, {
                width: `${THUMB_W}px`,
                height: `${THUMB_H}px`,
                minWidth: `${THUMB_W}px`,
                boxSizing: "border-box",
                border: `${BORDER_HIGHLIGHT}px solid #4CAF50`,
                borderRadius: `${BORDER_RADIUS}px`,
                overflow: "hidden",
                position: "relative",
                cursor: "pointer",
                flexShrink: "0",
                transition: "transform .1s",
                background: "#1e1e1e",
            });
            previewBox.addEventListener("mouseenter", () => {
                previewBox.style.transform = "scale(1.03)";
            });
            previewBox.addEventListener("mouseleave", () => {
                previewBox.style.transform = "scale(1)";
            });
            previewBox.addEventListener("click", () => deselectAll());
            topRow.appendChild(previewBox);

            // ---- 右侧列：提示词框 + 搜索框 ----
            const rightCol = document.createElement("div");
            Object.assign(rightCol.style, {
                display: "flex",
                flexDirection: "column",
                flex: "1",
                minWidth: "0",
                height: `${THUMB_H}px`,
                boxSizing: "border-box",
                overflow: "hidden",
            });

            // ---- 提示词文本框 ----
            const promptArea = document.createElement("textarea");
            promptArea.placeholder = "服装/发型提示词：选择模板后自动填入，也可随时手动编辑...";
            Object.assign(promptArea.style, {
                width: "100%",
                height: `${PROMPT_TEXTAREA_H}px`,
                minHeight: `${PROMPT_TEXTAREA_H}px`,
                maxHeight: `${PROMPT_TEXTAREA_H}px`,
                resize: "none",
                background: "#222",
                color: "#ddd",
                border: "1px solid #444",
                borderRadius: "6px",
                padding: "6px 8px",
                fontSize: "14px",
                fontFamily: "'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif",
                outline: "none",
                boxSizing: "border-box",
                overflow: "auto",
                display: "block",
                lineHeight: "1.5",
                transition: "border-color .2s",
                marginBottom: `${INNER_GAP}px`,
                flexShrink: "0",
            });
            promptArea.addEventListener("focus", () => {
                promptArea.style.borderColor = "#4CAF50";
            });
            promptArea.addEventListener("blur", () => {
                promptArea.style.borderColor = "#444";
            });
            // 阻止按键冒泡到画布快捷键
            promptArea.addEventListener("keydown", (e) => e.stopPropagation());
            promptArea.addEventListener("input", () => {
                if (promptWidget) {
                    promptWidget.value = promptArea.value;
                    const el = promptWidget.element;
                    if (el) {
                        const ta = el.tagName === "TEXTAREA" ? el : el.querySelector?.("textarea");
                        if (ta) ta.value = promptArea.value;
                    }
                }
                _lastSyncedValue = promptArea.value;
                saveSelectionState();
            });
            rightCol.appendChild(promptArea);

            // ---- 搜索框 ----
            const searchWrapper = document.createElement("div");
            Object.assign(searchWrapper.style, {
                position: "relative",
                width: "100%",
                marginBottom: "0px",
                marginTop: "0px",
                flexShrink: "0",
            });

            const magnifier = document.createElement("div");
            magnifier.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#888" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="10.5" cy="10.5" r="7"/><line x1="15.5" y1="15.5" x2="21" y2="21"/></svg>`;
            Object.assign(magnifier.style, {
                position: "absolute", left: "8px", top: "50%",
                transform: "translateY(-50%)",
                display: "flex", alignItems: "center", justifyContent: "center",
                pointerEvents: "none", zIndex: "2",
            });
            searchWrapper.appendChild(magnifier);

            const searchInput = document.createElement("input");
            searchInput.type = "text";
            searchInput.placeholder = "搜索模板（多个关键词用任意符号隔开，如：西装 领带 男...）";
            Object.assign(searchInput.style, {
                width: "100%",
                padding: "5px 26px 5px 28px",
                border: "1px solid #555", borderRadius: "4px",
                background: "#2a2a2a", color: "#e0e0e0",
                fontSize: "12px", outline: "none",
                boxSizing: "border-box",
                transition: "border-color .2s",
            });
            searchInput.addEventListener("focus", () => {
                searchInput.style.borderColor = "#4CAF50";
            });
            searchInput.addEventListener("blur", () => {
                searchInput.style.borderColor = "#555";
            });
            searchInput.addEventListener("keydown", (e) => {
                e.stopPropagation();
                if (e.key === "Escape") searchInput.blur();
            });
            searchInput.addEventListener("input", () => {
                searchQuery = searchInput.value.trim();
                isSearching = searchQuery.length > 0;
                clearBtn.style.display = isSearching ? "flex" : "none";
                renderGallery();
            });
            searchWrapper.appendChild(searchInput);

            const clearBtn = document.createElement("div");
            clearBtn.textContent = "✕";
            Object.assign(clearBtn.style, {
                position: "absolute", right: "8px", top: "50%",
                transform: "translateY(-50%)",
                width: "16px", height: "16px",
                display: "none", alignItems: "center", justifyContent: "center",
                color: "#888", fontSize: "12px", fontWeight: "bold",
                cursor: "pointer", zIndex: "2",
                borderRadius: "50%",
                transition: "color .15s, background .15s",
            });
            clearBtn.addEventListener("mouseenter", () => {
                clearBtn.style.color = "#e0e0e0";
                clearBtn.style.background = "rgba(255,255,255,0.1)";
            });
            clearBtn.addEventListener("mouseleave", () => {
                clearBtn.style.color = "#888";
                clearBtn.style.background = "transparent";
            });
            clearBtn.addEventListener("click", () => {
                searchInput.value = "";
                searchQuery = "";
                isSearching = false;
                clearBtn.style.display = "none";
                searchInput.focus();
                renderGallery();
            });
            searchWrapper.appendChild(clearBtn);
            rightCol.appendChild(searchWrapper);

            topRow.appendChild(rightCol);
            container.appendChild(topRow);

            // ---- 画廊网格 ----
            const gallery = document.createElement("div");
            gallery.className = "qg-outfit-gallery";
            Object.assign(gallery.style, {
                display: "grid",
                gridTemplateColumns: `repeat(auto-fill, ${THUMB_W}px)`,
                justifyContent: "start",
                gap: `${GAP}px`,
                width: "100%",
                maxHeight: `${3 * THUMB_H + 2 * GAP}px`,
                overflowY: "auto",
                paddingRight: "2px",
                scrollbarWidth: "thin",
                scrollbarColor: "#555 transparent",
            });
            gallery.addEventListener("wheel", (e) => e.stopPropagation());
            container.appendChild(gallery);

            const scrollStyle = document.createElement("style");
            scrollStyle.textContent = `
                .qg-outfit-gallery::-webkit-scrollbar { width: 6px; }
                .qg-outfit-gallery::-webkit-scrollbar-thumb { background: #555; border-radius: 3px; }
                .qg-outfit-gallery::-webkit-scrollbar-track { background: transparent; }
            `;
            container.appendChild(scrollStyle);

            // ==================== 渲染左侧预览框 ====================

            function renderPreviewBox(firstItem) {
                previewBox.innerHTML = "";
                const innerRadius = `${BORDER_RADIUS - BORDER_HIGHLIGHT}px`;

                if (firstItem._kind === "none") {
                    const placeholder = document.createElement("div");
                    Object.assign(placeholder.style, {
                        width: "100%", height: "100%",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        background: "#2d2d2d", color: "#888", fontSize: "16px",
                        borderRadius: innerRadius,
                    });
                    placeholder.textContent = "无";
                    previewBox.appendChild(placeholder);
                    previewBox.appendChild(createSelectedBadge());
                } else {
                    const img = document.createElement("img");
                    img.src = `${API_IMAGE}/${encodeURIComponent(firstItem.category)}/${encodeURIComponent(firstItem.filename)}`;
                    Object.assign(img.style, {
                        width: "100%", height: "100%",
                        objectFit: "cover", display: "block",
                        borderRadius: innerRadius,
                    });
                    img.onerror = function () {
                        this.style.display = "none";
                        createImageFallback(previewBox, firstItem.title, "100%", "100%", innerRadius);
                    };
                    previewBox.appendChild(img);
                    previewBox.appendChild(createSelectedBadge());
                }

                previewBox.title = firstItem.prompt || firstItem.title || "";
            }

            // ==================== 渲染画廊 ====================

            function renderGallery() {
                gallery.innerHTML = "";
                const { items, poolCount } = buildDisplayList();

                renderPreviewBox(items[0]);

                for (let i = 1; i < items.length; i++) {
                    const item = items[i];
                    const showBorder = item._isSel;
                    const cardRadius = showBorder
                        ? `${BORDER_RADIUS - BORDER_HIGHLIGHT}px`
                        : `${BORDER_RADIUS}px`;

                    const card = document.createElement("div");
                    Object.assign(card.style, {
                        position: "relative", cursor: "pointer",
                        width: `${THUMB_W}px`,
                        height: `${THUMB_H}px`,
                        border: showBorder
                            ? `${BORDER_HIGHLIGHT}px solid #4CAF50`
                            : "1px solid transparent",
                        borderRadius: `${BORDER_RADIUS}px`,
                        overflow: "hidden",
                        transition: "border-color .15s, transform .1s",
                        background: "#1e1e1e",
                        flexShrink: "0",
                    });
                    card.addEventListener("mouseenter", () => {
                        card.style.transform = "scale(1.03)";
                    });
                    card.addEventListener("mouseleave", () => {
                        card.style.transform = "scale(1)";
                    });

                    const img = document.createElement("img");
                    img.src = `${API_IMAGE}/${encodeURIComponent(item.category)}/${encodeURIComponent(item.filename)}`;
                    Object.assign(img.style, {
                        width: `${THUMB_W}px`,
                        height: `${THUMB_H}px`,
                        objectFit: "cover",
                        display: "block",
                        borderRadius: cardRadius,
                    });
                    img.loading = "lazy";
                    img.onerror = function () {
                        this.style.display = "none";
                        createImageFallback(card, item.title, `${THUMB_W}px`, `${THUMB_H}px`, cardRadius);
                    };
                    card.appendChild(img);

                    // 底部渐变标题条
                    const label = document.createElement("div");
                    Object.assign(label.style, {
                        position: "absolute", bottom: "0", left: "0", right: "0",
                        background: "linear-gradient(transparent, rgba(0,0,0,0.8))",
                        color: "#e0e0e0", fontSize: "10px",
                        padding: "8px 4px 3px", textAlign: "center",
                        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                        borderRadius: `0 0 ${BORDER_RADIUS}px ${BORDER_RADIUS}px`,
                    });
                    label.textContent = item.title;
                    card.appendChild(label);

                    // 搜索结果带分类角标（结果可能来自其它分类）
                    if (isSearching && item._kind === "item") {
                        const badge = document.createElement("div");
                        Object.assign(badge.style, {
                            position: "absolute", top: "2px", left: "2px",
                            background: "rgba(0,0,0,0.7)", color: "#aaa",
                            fontSize: "9px", padding: "1px 4px", borderRadius: "2px",
                        });
                        badge.textContent = item.category;
                        card.appendChild(badge);
                    }

                    card.title = item.prompt || item.title;

                    if (item._isSel) {
                        card.appendChild(createCheckmark());
                        card.addEventListener("click", deselectAll);
                    } else {
                        card.addEventListener("click", () => selectTemplate(item));
                    }

                    gallery.appendChild(card);
                }

                // 未放素材：给一行自备素材指引（首格之外的空态提示）
                if (!isSearching && poolCount === 0 && currentCategory === "无数据") {
                    const guide = document.createElement("div");
                    Object.assign(guide.style, {
                        gridColumn: "1 / -1", textAlign: "center",
                        color: "#666", padding: "16px", fontSize: "12px",
                        lineHeight: "1.8",
                    });
                    guide.textContent = EMPTY_GUIDE;
                    gallery.appendChild(guide);
                }

                if (isSearching && poolCount === 0) {
                    const noResult = document.createElement("div");
                    Object.assign(noResult.style, {
                        gridColumn: "1 / -1", textAlign: "center",
                        color: "#666", padding: "16px", fontSize: "12px",
                    });
                    noResult.textContent = "未找到匹配的模板";
                    gallery.appendChild(noResult);
                }
            }

            // ==================== 添加 DOM Widget ====================

            const galleryWidget = node.addDOMWidget("outfit_gallery", "div", container, {
                serialize: false,
                hideOnZoom: false,
            });
            if (galleryWidget?.visibility?.surfaces) {
                galleryWidget.visibility.surfaces.canvas = "shown";
                galleryWidget.visibility.surfaces.panel = "never";
                galleryWidget.visibility.surfaces.vueNode = "shown";
            }
            galleryWidget.computeSize = () => [0, 0];

            // 原生提示词控件隐藏（面板内文本框替代）
            if (promptWidget) {
                promptWidget.computeSize = () => [0, 0];
                if (promptWidget.element) {
                    promptWidget.element.style.display = "none";
                }
            }

            // ==================== 画廊高度自适应 ====================

            function getLayoutMetrics() {
                const TITLE_H = (typeof LiteGraph !== "undefined" && LiteGraph.NODE_TITLE_HEIGHT) || 30;
                const SLOT_H = (typeof LiteGraph !== "undefined" && LiteGraph.NODE_SLOT_HEIGHT) || 20;
                return { TITLE_H, SLOT_H };
            }

            function getContainerFixedOverhead() {
                return 8 + THUMB_H + 6;
            }

            function updateGalleryHeight() {
                const { TITLE_H, SLOT_H } = getLayoutMetrics();
                const nodeH = node.size ? node.size[1] : 0;
                if (!nodeH || nodeH <= 0) return;

                const catH = SLOT_H;
                const avail = nodeH - TITLE_H - catH - getContainerFixedOverhead() - BOTTOM_PAD;
                const minH = THUMB_H + GAP;
                const maxH = Math.max(minH, avail);

                if (Math.abs(maxH - _lastAppliedMaxH) < 1) return;
                _lastAppliedMaxH = maxH;

                gallery.style.maxHeight = maxH + "px";
            }

            const origOnResize = node.onResize;
            node.onResize = function (size) {
                if (origOnResize) origOnResize.call(node, size);
                requestAnimationFrame(updateGalleryHeight);
            };

            const _pollId = setInterval(() => {
                if (!node.graph) { clearInterval(_pollId); return; }
                updateGalleryHeight();
            }, 200);

            // ==================== 同步外部值变化（连线/其它来源改写提示词） ====================

            const _syncPollId = setInterval(() => {
                if (!node.graph) { clearInterval(_syncPollId); return; }
                const current = promptWidget?.value || "";
                if (current !== _lastSyncedValue) {
                    _lastSyncedValue = current;
                    promptArea.value = current;
                    selectedPrompt = current;
                    saveSelectionState();
                }
            }, 300);

            // ==================== 节点移除时清理定时器 ====================

            const origOnRemoved = node.onRemoved;
            node.onRemoved = function () {
                clearInterval(_pollId);
                clearInterval(_syncPollId);
                origOnRemoved?.apply(this, arguments);
            };

            // ==================== 状态恢复 ====================

            function tryLegacyRestore() {
                // 旧档兼容：工作流里只存了提示词文本，按提示词反查模板
                const saved = promptWidget?.value || "";
                if (!saved) return false;

                for (const cat of allCategories) {
                    const tpl = (allTemplates[cat] || []).find((t) => t.prompt === saved);
                    if (tpl) {
                        selectedCategory = cat;
                        selectedFilename = tpl.filename;
                        selectedPrompt = tpl.prompt;
                        currentCategory = cat;
                        if (catWidget) catWidget.value = cat;
                        promptArea.value = selectedPrompt;
                        _lastSyncedValue = selectedPrompt;
                        saveSelectionState();
                        renderGallery();
                        return true;
                    }
                }
                return false;
            }

            function restoreState() {
                const state = node.properties?._qg_outfit_sel;
                if (!state) return tryLegacyRestore();

                // 恢复当前浏览分类
                if (state.curCat && allCategories.includes(state.curCat)) {
                    currentCategory = state.curCat;
                    if (catWidget) catWidget.value = currentCategory;
                }

                // 无选择状态（提示词可能被手动编辑过，保留）
                if (state._none) {
                    selectedCategory = "";
                    selectedFilename = "";
                    selectedPrompt = state.prompt ?? "";
                    syncPrompt();
                    renderGallery();
                    return true;
                }

                // 恢复模板选择
                if (state.cat && state.file) {
                    const tpl = findTemplate(state.cat, state.file);
                    if (tpl) {
                        selectedCategory = tpl.category;
                        selectedFilename = tpl.filename;
                        selectedPrompt = state.prompt ?? (tpl.prompt || "");
                        syncPrompt();
                        renderGallery();
                        return true;
                    }
                }

                return tryLegacyRestore();
            }

            // ==================== 初始渲染 ====================

            if (!restoreState()) {
                // 全新节点：默认选中第一个分类的第 5 个模板（与孤海一致）
                const defaultList = allTemplates[defaultCat] || [];
                if (defaultList.length > 0) {
                    selectedCategory = defaultCat;
                    const idx = Math.min(4, defaultList.length - 1);
                    selectedFilename = defaultList[idx].filename;
                    selectedPrompt = defaultList[idx].prompt;
                }
                syncPrompt();
                saveSelectionState();
            }

            renderGallery();

            // 首次打开时固定节点大小（宽度容下 4 列网格，高度容下 3 行）
            setTimeout(() => {
                const { TITLE_H, SLOT_H } = getLayoutMetrics();
                const defaultGalleryH = 3 * THUMB_H + 2 * GAP;
                const nodeSize = node.computeSize ? node.computeSize() : [0, 0];
                const targetW = Math.max(nodeSize[0] || 0, GALLERY_WIDTH + 40);
                const targetH = TITLE_H + SLOT_H + getContainerFixedOverhead() + defaultGalleryH + BOTTOM_PAD;

                gallery.style.maxHeight = defaultGalleryH + "px";
                node.setSize([targetW, targetH]);
                updateGalleryHeight();
            }, 100);
        };
    },
});
