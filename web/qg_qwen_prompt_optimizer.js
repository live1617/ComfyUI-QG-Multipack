// QG Qwen image 2.1 提示词优化 —— 前端增强。
// 本文件是 Goohaitools-comfyui（GPL-3.0）web/js/qwen_image_prompt_optimizer.js
// 的逐行移植：动态图像口（最后连接位置 index+2、最多 10 个）、llama-cpp 依赖
// 检测按钮、随机种子队列 hook、提示词高度可拖拽布局。
// 两项目同为 GPL-3.0；移植写入本包并在 THIRD-PARTY-NOTICES.md 署名。
// 有意差异：注册 key、HTTP 路由前缀（/qg_qwen_prompt_optimizer/*）与节点内部
// 状态标识改用 qg 前缀，避免与参考插件同画布时互相干扰。
// Comfy Registry 合规：上游「点击自动安装」会在节点进程内 subprocess pip
// install，违反 Registry 安全标准；本包改为「查看手动安装说明」，只展示环境
// 匹配结果与发布页地址，不发起任何安装请求。
import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const MAX_IMAGES = 10;
const NODE_NAME = "QG_QwenPromptOptimizer";
const SKILL_INPUT_NAME = "自定义skill";
const PROMPT_HEIGHT_PROPERTY = "qg_qwen_prompt_height";
const MIN_PROMPT_HEIGHT = 64;
const SEED_WIDGET_NAMES = new Set(["种子值", "seed"]);
const SEED_MODE_WIDGET_NAMES = new Set(["种子模式", "seed_mode"]);
const LAST_SEED_MODE_PROPERTY = "qg_last_executed_seed_mode";
const LLAMA_STATUS_ROUTE = "/qg_qwen_prompt_optimizer/llama_status";
const imageName = (index) => `图像_${String(index + 1).padStart(2, "0")}`;
const isImageInput = (slot) => {
    const name = String(slot?.name || "");
    return name.startsWith("图像_") || name.startsWith("image_");
};

function connected(slot) {
    return slot?.link != null;
}

// 自定义 skill 槽：后端声明在 optional 里，前端把它排到所有图像槽之后，
// 并始终保持在最后一个位置。新前端按槽位下标解析连线，重排前先记下每条
// 连线属于哪个槽、重排后写回 target_slot，否则连线会错位到别的输入。
function syncSkillInput(node) {
    if (!node.inputs?.some((input) => input.name === SKILL_INPUT_NAME)) {
        node.addInput(SKILL_INPUT_NAME, "STRING", { shape: 7 });
    }
    const inputs = node.inputs;
    const links = node.graph?.links;
    const inputLinks = inputs.map((input) => {
        const id = input.link;
        return id == null ? null : (links?.get ? links.get(id) : links?.[id]);
    });
    const originalInputs = [...inputs];
    const skillIndex = inputs.findIndex((input) => input.name === SKILL_INPUT_NAME);
    const [skill] = inputs.splice(skillIndex, 1);
    skill.label = "skill";
    skill.localized_name = "skill";
    const targetIndex = inputs.findLastIndex((input) => isImageInput(input)) + 1;
    inputs.splice(targetIndex, 0, skill);
    const movedLinks = originalInputs.flatMap((input, index) => {
        const link = inputLinks[index];
        const target = inputs.indexOf(input);
        return link && link.target_slot !== target ? [{ link, target }] : [];
    });
    // 先整体腾空旧槽位，再写回新下标：直接覆盖会让两条占用同一 target 的
    // 连线被拓扑存储拒绝。
    movedLinks.forEach(({ link }, index) => { link.target_slot = inputs.length + index; });
    movedLinks.forEach(({ link, target }) => { link.target_slot = target; });
}

function promptWidget(node) {
    return node.widgets?.find((item) => item.name === "用户提示词" || item.name === "user_prompt");
}

function updateSeedWidget(node, seed) {
    const widget = node.widgets?.find((item) => SEED_WIDGET_NAMES.has(item.name));
    if (!widget || !Number.isFinite(Number(seed))) return;
    widget.value = Number(seed);
    widget.callback?.(widget.value);
}

function widgetValue(node, names) {
    return node.widgets?.find((item) => names.has(item.name))?.value;
}

function dependencyMessage(message, success = false) {
    const text = String(message || "未知错误");
    const escaped = text
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;")
        .replaceAll("\n", "<br>");
    const content = success
        ? `<div style="display:flex;align-items:flex-start;gap:12px;color:#48c774;line-height:1.7;">`
            + `<span style="display:inline-flex;align-items:center;justify-content:center;flex:0 0 28px;width:28px;height:28px;border-radius:50%;background:#48c774;color:#fff;font-size:20px;font-weight:700;line-height:1;">✓</span>`
            + `<div>${escaped}</div></div>`
        : escaped;
    if (app.ui?.dialog?.show) app.ui.dialog.show(content);
    else window.alert(text);
}

async function installLlamaDependencyButton(node) {
    if (node._qgLlamaDependencyChecked) return;
    node._qgLlamaDependencyChecked = true;
    let status;
    try {
        const response = await api.fetchApi(LLAMA_STATUS_ROUTE, { cache: "no-store" });
        if (!response.ok) return;
        status = await response.json();
    } catch {
        return;
    }
    if (!status?.needs_install || node._qgLlamaInstallWidget) return;
    const label = "llama-cpp需0.3.48以上，点击查看安装说明";
    const widget = node.addWidget("button", label, null, () => {
        const current = status.installed_version
            ? `当前 llama-cpp-python 版本：${status.installed_version}\n`
            : "当前未安装 llama-cpp-python\n";
        const detail = status.supported === true
            ? `${current}\n本包遵循 Comfy Registry 安全规范，不自动安装依赖。\n`
              + `请到发布页下载文件名以 ${status.wheel_suffix || "匹配当前环境"} 结尾的 `
              + `${status.backend || ""} wheel，用 ComfyUI 自带 Python 执行：\n`
              + `  python -m pip install <wheel文件> diskcache\n安装后完全重启 ComfyUI。`
            : `${current}\n${status.reason || "当前环境无法自动匹配 wheel。"}\n`
              + `请到发布页按系统与 Python 版本手动选择对应 wheel。`;
        dependencyMessage(`${detail}\n\n发布页：${status.release_url}`);
        window.open(status.release_url, "_blank", "noopener,noreferrer");
    });
    widget.serialize = false;
    widget.options = { ...(widget.options || {}), serialize: false };
    node._qgLlamaInstallWidget = widget;
    requestAnimationFrame(() => applyPromptLayout(node, true));
}

function nextRandomSeed() {
    if (globalThis.crypto?.getRandomValues) {
        const value = new Uint32Array(1);
        globalThis.crypto.getRandomValues(value);
        return Number(value[0]) || 1;
    }
    return (Math.floor(Math.random() * 0xFFFFFFFF) + 1) >>> 0;
}

function prepareRuntimeSeeds() {
    const nodes = app.graph?._nodes || app.graph?._nodes_by_id && Object.values(app.graph._nodes_by_id) || [];
    for (const node of nodes) {
        if (node?.comfyClass !== NODE_NAME && node?.type !== NODE_NAME) continue;
        const mode = widgetValue(node, SEED_MODE_WIDGET_NAMES);
        if (mode === "随机") updateSeedWidget(node, nextRandomSeed());
    }
}

function prepareRuntimeSeedModes() {
    const nodes = app.graph?._nodes || app.graph?._nodes_by_id && Object.values(app.graph._nodes_by_id) || [];
    const restores = [];
    for (const node of nodes) {
        if (node?.comfyClass !== NODE_NAME && node?.type !== NODE_NAME) continue;
        const widget = node.widgets?.find((item) => SEED_MODE_WIDGET_NAMES.has(item.name));
        if (!widget) continue;
        const selectedMode = widget.value;
        const lastExecutedMode = node._qgLastExecutedSeedMode
            || node.properties?.[LAST_SEED_MODE_PROPERTY];
        const queuedMode = selectedMode === "固定"
            && lastExecutedMode === "随机"
            ? "随机"
            : selectedMode;
        node._qgQueuedSeedMode = selectedMode;
        if (queuedMode !== selectedMode) {
            widget.value = queuedMode;
            restores.push(() => { widget.value = selectedMode; });
        }
    }
    return restores;
}

function installQueueSeedHook() {
    if (app._qgQwenPromptRuntimeSeedHook) return;
    if (typeof app.queuePrompt !== "function") {
        setTimeout(installQueueSeedHook, 250);
        return;
    }
    const originalQueuePrompt = app.queuePrompt;
    app.queuePrompt = async function () {
        prepareRuntimeSeeds();
        const restores = prepareRuntimeSeedModes();
        try {
            return await originalQueuePrompt.apply(this, arguments);
        } finally {
            for (const restore of restores.reverse()) restore();
        }
    };
    app._qgQwenPromptRuntimeSeedHook = true;
}

function asPromptHeight(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(MIN_PROMPT_HEIGHT, Math.round(number)) : fallback;
}

// 新版前端把 node.size 存成 Float64Array，Array.isArray() 对它返回 false。
// 用 length 判断才同时兼容普通数组与类型化数组。
function sizePair(value) {
    if (!value || typeof value.length !== "number" || value.length < 2) return null;
    const width = Number(value[0]);
    const height = Number(value[1]);
    if (!Number.isFinite(width) || !Number.isFinite(height)) return null;
    return [width, height];
}

function measurePromptLayout(node, widget) {
    const originalWidgetComputeSize = node._qgOriginalWidgetComputeSize || widget.computeSize;
    const originalNodeComputeSize = node._qgOriginalNodeComputeSize || node.computeSize;
    if (typeof originalWidgetComputeSize !== "function" || typeof originalNodeComputeSize !== "function") {
        return null;
    }

    const currentComputeSize = widget.computeSize;
    widget.computeSize = originalWidgetComputeSize;
    const naturalWidgetSize = originalWidgetComputeSize.call(widget, node.size?.[0]) || [0, 160];
    const naturalNodeSize = originalNodeComputeSize.call(node) || [0, 0];
    widget.computeSize = currentComputeSize;

    const naturalPromptHeight = Math.max(MIN_PROMPT_HEIGHT, Math.round(Number(naturalWidgetSize[1] || 160)));
    const fixedNodeHeight = Math.max(0, Math.round(Number(naturalNodeSize[1] || 0) - naturalPromptHeight));
    return { originalWidgetComputeSize, originalNodeComputeSize, naturalPromptHeight, fixedNodeHeight };
}

function applyPromptLayout(node, forceSize = false) {
    const widget = promptWidget(node);
    if (!widget) return;

    if (!node._qgOriginalWidgetComputeSize) node._qgOriginalWidgetComputeSize = widget.computeSize;
    if (!node._qgOriginalNodeComputeSize) node._qgOriginalNodeComputeSize = node.computeSize;
    const layout = measurePromptLayout(node, widget);
    if (!layout) return;

    const currentSize = sizePair(node.size);
    const hadSavedHeight = node.properties && Object.prototype.hasOwnProperty.call(node.properties, PROMPT_HEIGHT_PROPERTY);
    const initialHeight = Math.max(MIN_PROMPT_HEIGHT, Math.round(layout.naturalPromptHeight * 0.5));
    // 没有记录时（旧工作流、或首次加载）先按当前节点高度反推提示词区高度，
    // 保住用户已经拉过的尺寸；连尺寸都读不到才退回「自然高度的一半」。
    const derivedHeight = currentSize
        ? Math.max(MIN_PROMPT_HEIGHT, Math.round(currentSize[1] - layout.fixedNodeHeight))
        : initialHeight;
    const savedHeight = hadSavedHeight
        ? asPromptHeight(node.properties[PROMPT_HEIGHT_PROPERTY], derivedHeight)
        : derivedHeight;

    node.properties = node.properties || {};
    node.properties[PROMPT_HEIGHT_PROPERTY] = savedHeight;
    node._qgPromptFixedNodeHeight = layout.fixedNodeHeight;
    node._qgPromptHeight = savedHeight;
    node._qgPromptReady = false;
    widget.computeSize = () => [0, node._qgPromptHeight];

    const expectedHeight = layout.fixedNodeHeight + savedHeight;
    const needsResize = forceSize || !currentSize
        || Math.abs(currentSize[1] - expectedHeight) > 1;
    if (needsResize) {
        node._qgPromptInternalResize = true;
        node.setSize?.([currentSize ? Math.max(1, currentSize[0]) : 1, expectedHeight]);
        node._qgPromptInternalResize = false;
    }
    node._qgPromptReady = true;
    node.setDirtyCanvas?.(true, true);
}

function updatePromptHeightFromNodeSize(node, size) {
    if (!node._qgPromptReady || node._qgPromptInternalResize) return;
    const totalHeight = Number(size?.[1] ?? node.size?.[1]);
    const fixedHeight = Number(node._qgPromptFixedNodeHeight);
    if (!Number.isFinite(totalHeight) || !Number.isFinite(fixedHeight)) return;
    const nextHeight = asPromptHeight(totalHeight - fixedHeight, node._qgPromptHeight || MIN_PROMPT_HEIGHT);
    if (Math.abs(nextHeight - node._qgPromptHeight) <= 1) return;
    node._qgPromptHeight = nextHeight;
    node.properties = node.properties || {};
    node.properties[PROMPT_HEIGHT_PROPERTY] = nextHeight;
    node.setDirtyCanvas?.(true, true);
}

function hookResize(node) {
    // ComfyUI 前端在 addDOMWidget 里会给**实例**挂一个组合好的 onResize
    // （实测 Object.hasOwnProperty(node, "onResize") === true）。只包
    // nodeType.prototype 会被实例属性整段屏蔽，updatePromptHeightFromNodeSize
    // 就永远不执行，properties 里记的高度停在初值，重开节点时按旧值还原。
    if (!node || node._qgPromptResizeHooked) return;
    node._qgPromptResizeHooked = true;
    const own = node.onResize;
    node.onResize = function (size) {
        const result = own?.apply(this, arguments);
        updatePromptHeightFromNodeSize(this, size ?? this.size);
        return result;
    };
}

function hookSerialize(node) {
    // 保存时再以当前高度算一次并写进 properties：某些扩展会整体替换 onResize，
    // 只靠拖拽回调会漏记。this.properties 与 data.properties 都写，覆盖
    // 「核心先写 properties 再调 onSerialize」和反过来的两种顺序。
    if (!node || node._qgPromptSerializeHooked) return;
    node._qgPromptSerializeHooked = true;
    const own = node.onSerialize;
    node.onSerialize = function (data) {
        const result = own?.apply(this, arguments);
        const pair = sizePair(this.size);
        const fixed = Number(this._qgPromptFixedNodeHeight);
        if (pair && Number.isFinite(fixed) && fixed > 0) {
            const height = asPromptHeight(pair[1] - fixed, this._qgPromptHeight || MIN_PROMPT_HEIGHT);
            this.properties = this.properties || {};
            this.properties[PROMPT_HEIGHT_PROPERTY] = height;
            if (data && data.properties && typeof data.properties === "object") {
                data.properties[PROMPT_HEIGHT_PROPERTY] = height;
            }
        }
        return result;
    };
}

function sync(node) {
    let inputs = node.inputs || [];
    let imageIndexes = inputs
        .map((slot, index) => ({ slot, index }))
        .filter(({ slot }) => isImageInput(slot));
    if (!imageIndexes.length) {
        node.addInput(imageName(0), "IMAGE");
        imageIndexes = [{ slot: node.inputs[node.inputs.length - 1], index: node.inputs.length - 1 }];
    }
    let lastConnected = -1;
    imageIndexes.forEach(({ slot }, imageIndex) => {
        if (connected(slot)) lastConnected = Math.max(lastConnected, imageIndex);
    });
    const target = Math.min(MAX_IMAGES, Math.max(1, lastConnected + 2));
    while (imageIndexes.length > target) {
        const last = imageIndexes[imageIndexes.length - 1];
        if (connected(last.slot)) break;
        node.removeInput(last.index);
        imageIndexes = (node.inputs || [])
            .map((slot, index) => ({ slot, index }))
            .filter(({ slot }) => isImageInput(slot));
    }
    while (imageIndexes.length < target) {
        node.addInput(imageName(imageIndexes.length), "IMAGE");
        imageIndexes = (node.inputs || [])
            .map((slot, index) => ({ slot, index }))
            .filter(({ slot }) => isImageInput(slot));
    }
    const slots = node.inputs || [];
    let number = 0;
    for (const slot of slots) {
        if (!isImageInput(slot)) continue;
        slot.name = imageName(number);
        slot.label = `图像 ${number + 1}`;
        number += 1;
    }
    syncSkillInput(node);
    node.setDirtyCanvas?.(true, true);
}

app.registerExtension({
    name: "QG.QwenPromptOptimizer",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_NAME) return;
        installQueueSeedHook();
        // 载入工作流时核心会恢复声明里的所有图像槽、并重排 widget 输入。
        // 按存档记录的槽名顺序还原，避免 skill 槽插队导致连线按旧下标接错。
        const originalConfigureNode = nodeType.prototype.configure;
        nodeType.prototype.configure = function (config) {
            const inputNames = config?.inputs?.map((input) => input.name);
            const result = originalConfigureNode?.apply(this, arguments);
            if (inputNames && this.inputs) {
                const inputs = new Map(this.inputs.map((input) => [input.name, input]));
                this.inputs = [
                    ...inputNames.map((name) => inputs.get(name)).filter(Boolean),
                    ...this.inputs.filter((input) => !inputNames.includes(input.name) && !isImageInput(input)),
                ];
            }
            this._qgImageScheduleSync?.();
            return result;
        };
        /* 包装生命周期钩子时必须把原实现的返回值传下去。ComfyUI 的其它
         * 扩展（以及节点自己）会把链式 hook 的返回值当成「是否继续 / 已处理」
         * 的依据，丢掉返回值会让后面的扩展静默失效。全包其余扩展都保留，
         * 这里此前 5 处全丢了，逐个补齐。 */
        const originalCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalCreated?.apply(this, arguments);
            installLlamaDependencyButton(this);
            this._qgImageSyncQueued = false;
            this._qgImageScheduleSync = () => {
                if (this._qgImageSyncQueued) return;
                this._qgImageSyncQueued = true;
                requestAnimationFrame(() => {
                    this._qgImageSyncQueued = false;
                    sync(this);
                });
            };
            this._qgImageScheduleSync();
            hookResize(this);
            hookSerialize(this);
            requestAnimationFrame(() => applyPromptLayout(this, false));
            return result;
        };
        const originalResize = nodeType.prototype.onResize;
        nodeType.prototype.onResize = function () {
            const result = originalResize?.apply(this, arguments);
            updatePromptHeightFromNodeSize(this, arguments[0]);
            return result;
        };
        const originalConnections = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = originalConnections?.apply(this, arguments);
            this._qgImageScheduleSync?.();
            requestAnimationFrame(() => applyPromptLayout(this, false));
            return result;
        };
        const originalConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalConfigure?.apply(this, arguments);
            this._qgImageScheduleSync?.();
            requestAnimationFrame(() => applyPromptLayout(this, true));
            return result;
        };
        const originalExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            const result = originalExecuted?.apply(this, arguments);
            const seed = Array.isArray(message?.seed) ? message.seed[0] : message?.seed;
            updateSeedWidget(this, seed);
            if (this._qgQueuedSeedMode) {
                this._qgLastExecutedSeedMode = this._qgQueuedSeedMode;
                this.properties = this.properties || {};
                this.properties[LAST_SEED_MODE_PROPERTY] = this._qgQueuedSeedMode;
            }
            return result;
        };
    },
});
