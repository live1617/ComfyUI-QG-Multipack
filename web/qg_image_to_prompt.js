// QG 图像反推提示词 —— 多图输入口动态增减。
// 对齐 MUJUN-2025/ComfyUI-Prompt-Assistant fork 的交互：主口 image 恒在；
// image2 ~ image9 随连接自动增减（接入后自动出现下一个空口，断开后其后
// 的口级联回收），口名显示为「图像 N」。未接额外口时与原单图行为一致。
//
// 后端在 INPUT_TYPES 的 optional 里一次性声明全部 image2~image9，前端按
// 连接状态做显隐增减（removeInput/addInput），与 qg_qwen_text_encode.js
// 同一套规格：生命周期钩子包装必须把原实现返回值传下去。
import { app } from "/scripts/app.js";

const NODE_NAME = "QG_ImageToPrompt";
const EXTRA_MAX = 8;                       // image2 ~ image9

const isExtraInput = (slot) => /^image[2-9]$/.test(String(slot?.name || ""));
const connected = (slot) => slot?.link != null;

function extraInputs(node) {
    return (node.inputs || [])
        .map((slot, index) => ({ slot, index }))
        .filter(({ slot }) => isExtraInput(slot));
}

function syncExtraInputs(node) {
    let inputs = extraInputs(node);

    // 主口 name 是 "image"，不会被正则误伤；但保险起见按序号裁剪，多余的
    // （理论上不该出现）从未连接的尾部删起。
    while (inputs.length > EXTRA_MAX) {
        const last = inputs[inputs.length - 1];
        if (connected(last.slot)) break;
        node.removeInput(last.index);
        inputs = extraInputs(node);
    }

    // 已连接的最深口（extras 相对序号，0 对应 image2）
    let lastConnected = -1;
    inputs.forEach(({ slot }, index) => {
        if (connected(slot)) lastConnected = index;
    });
    // 至少留 1 个空口（接入 image2 后自动出现 image3，以此类推）
    const targetCount = Math.min(EXTRA_MAX, Math.max(1, lastConnected + 2));

    while (inputs.length > targetCount) {
        const last = inputs[inputs.length - 1];
        if (connected(last.slot)) break;      // 已连接的口不能删
        node.removeInput(last.index);
        inputs = extraInputs(node);
    }
    while (inputs.length < targetCount) {
        node.addInput(`image${inputs.length + 2}`, "IMAGE");
        inputs = extraInputs(node);
    }

    // 口名标签：主口「图像」，额外口「图像 2..N」
    const main = (node.inputs || []).find((slot) => slot?.name === "image");
    if (main) main.label = "图像";
    inputs.forEach(({ slot }) => {
        const serial = parseInt(String(slot.name).slice(5), 10) || "";
        slot.label = serial ? `图像 ${serial}` : "图像";
        slot.type = "IMAGE";
    });
    node.setDirtyCanvas?.(true, true);
}

function scheduleSync(node) {
    if (node._qgItpSyncPending) return;
    node._qgItpSyncPending = true;
    requestAnimationFrame(() => {
        node._qgItpSyncPending = false;
        syncExtraInputs(node);
    });
}

app.registerExtension({
    name: "QG.ImageToPrompt",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_NAME) return;

        const originalCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalCreated?.apply(this, arguments);
            scheduleSync(this);
            return result;
        };

        const originalConnections = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = originalConnections?.apply(this, arguments);
            scheduleSync(this);
            return result;
        };

        const originalConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalConfigure?.apply(this, arguments);
            scheduleSync(this);
            return result;
        };
    },
});
