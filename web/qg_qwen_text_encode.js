// Qwen Image 2.1 文本编码 —— 前端扩展。
// 对齐 Goohaitools text_encode_qwen_image_21_gh.js 的交互：
// image_XX 输入口动态增减（有连接就多保留 2 个空位，最少 1 个、最多 10 个），
// 口名显示为「图像 N」，ref_image_size 显示为「参考图尺寸」。
// 有意加固：参考的 labelReferenceSize 只找 input 口，本包同时处理控件
// （widget），保证「参考图尺寸」下拉在任何前端版本下都显示中文。
import { app } from "/scripts/app.js";

const NODE_NAME = "QG_QwenTextEncode";
const RESTORE_NAME = "QG_QwenRestore";
const MAX_IMAGES = 10;
const imageName = (index) => `image_${String(index + 1).padStart(2, "0")}`;

const isImageInput = (slot) => /^image_\d+$/.test(String(slot?.name || ""));
const connected = (slot) => slot?.link != null;

function imageInputs(node) {
    return (node.inputs || [])
        .map((slot, index) => ({ slot, index }))
        .filter(({ slot }) => isImageInput(slot));
}

function syncImageInputs(node) {
    let inputs = imageInputs(node);

    while (inputs.length > MAX_IMAGES) {
        const last = inputs[inputs.length - 1];
        node.removeInput(last.index);
        inputs = imageInputs(node);
    }

    if (!inputs.length) {
        node.addInput(imageName(0), "IMAGE");
        inputs = imageInputs(node);
    }

    let lastConnected = -1;
    inputs.forEach(({ slot }, index) => {
        if (connected(slot)) lastConnected = index;
    });
    const targetCount = Math.min(MAX_IMAGES, Math.max(1, lastConnected + 2));

    while (inputs.length > targetCount) {
        const last = inputs[inputs.length - 1];
        if (connected(last.slot)) break;
        node.removeInput(last.index);
        inputs = imageInputs(node);
    }
    while (inputs.length < targetCount) {
        node.addInput(imageName(inputs.length), "IMAGE");
        inputs = imageInputs(node);
    }

    inputs.forEach(({ slot }, index) => {
        slot.label = `图像 ${index + 1}`;
        slot.type = "IMAGE";
    });
    node.setDirtyCanvas?.(true, true);
}

function labelReferenceSize(node) {
    const slot = (node.inputs || []).find((input) => input?.name === "ref_image_size");
    if (slot) slot.label = "参考图尺寸";
    // 有意加固：ref_image_size 平时是下拉控件（不在 node.inputs 里），
    // 也给它设 label，保证控件名与参考截图一致。
    const widget = (node.widgets || []).find((w) => w?.name === "ref_image_size");
    if (widget) widget.label = "参考图尺寸";
}

function scheduleSync(node) {
    if (node._qgQwen21SyncPending) return;
    node._qgQwen21SyncPending = true;
    requestAnimationFrame(() => {
        node._qgQwen21SyncPending = false;
        syncImageInputs(node);
    });
}

app.registerExtension({
    name: "QG.QwenTextEncode",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_NAME) return;

        const originalCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            originalCreated?.apply(this, arguments);
            labelReferenceSize(this);
            scheduleSync(this);
        };

        const originalConnections = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            originalConnections?.apply(this, arguments);
            labelReferenceSize(this);
            scheduleSync(this);
        };

        const originalConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            originalConfigure?.apply(this, arguments);
            labelReferenceSize(this);
            scheduleSync(this);
        };
    },
});
