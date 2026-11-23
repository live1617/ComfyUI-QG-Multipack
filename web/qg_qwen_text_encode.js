// Qwen Image 2.1 文本编码 —— 前端扩展。
// 对齐 Goohaitools text_encode_qwen_image_21_gh.js 的交互：
// image_XX 输入口动态增减（有连接就多保留 2 个空位，最少 1 个、最多 10 个），
// 口名显示为「图像 N」，ref_image_size 显示为「参考图尺寸」。
// 有意加固：参考的 labelReferenceSize 只找 input 口，本包同时处理控件
// （widget），保证「参考图尺寸」下拉在任何前端版本下都显示中文。
//
// 尺寸持久化：节点尺寸由工作流的 size 字段承载，正常前端会原样恢复。但不同
// 前端版本（1.59.x 起改走 state store + canonical 字段筛选）与「image_XX 动态
// 口」的交互存在边界情况，实测有用户的尺寸在重开后被还原成默认值。这里额外
// 把用户拖出来的尺寸记进 properties（随工作流一起序列化），配置完成后再校验
// 一次：若当前尺寸与记录不符，就按记录恢复（并保证不小于内容所需尺寸）。
// 记录只在用户 resize 时更新，configure 期间不记录，避免把被重置的值写回。
import { app } from "/scripts/app.js";

const NODE_NAME = "QG_QwenTextEncode";
const MAX_IMAGES = 10;
const SIZE_PROPERTY = "qg_qwen_text_size";
const SIZE_TOLERANCE = 2;
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

// ---------- 尺寸记忆与恢复 ----------

function asSizePair(value) {
    // 不能只认 Array：新版前端把节点 size 存成 Float32Array 之类的类型化数组，
    // Array.isArray 会返回 false，导致「尺寸已有值」被误判成「没有值」而跳过恢复。
    if (!value || typeof value.length !== "number" || value.length !== 2) return null;
    const width = Number(value[0]);
    const height = Number(value[1]);
    if (!Number.isFinite(width) || !Number.isFinite(height)) return null;
    if (width <= 0 || height <= 0) return null;
    return [width, height];
}

function rememberSize(node, data) {
    // 记录时机是「保存工作流」：此刻 node.size 就是用户最终看到的尺寸，不受
    // 配置期 expandToFitContent（addInput 只增不减）与恢复过程的中间值影响。
    const current = asSizePair(node?.size);
    if (!current || !data || typeof data !== "object") return;
    data.properties = data.properties || {};
    data.properties[SIZE_PROPERTY] = [Math.round(current[0]), Math.round(current[1])];
}

function hookSerialize(node) {
    // 实例级包装：ComfyNode 会在构造时给实例挂 onResize / onSerialize，
    // 只包原型会被实例属性屏蔽。
    if (!node || node._qgSerializeHooked) return;
    node._qgSerializeHooked = true;
    const own = node.onSerialize;
    node.onSerialize = function (data) {
        const result = own?.apply(this, arguments);
        rememberSize(this, data);
        return result;
    };
}

function restoreSize(node) {
    if (!node) return;
    const saved = asSizePair(node.properties?.[SIZE_PROPERTY]);
    if (!saved) return;
    const current = asSizePair(node.size);
    if (!current) return;
    if (Math.abs(current[0] - saved[0]) <= SIZE_TOLERANCE
        && Math.abs(current[1] - saved[1]) <= SIZE_TOLERANCE) {
        return;          // 存档已正确恢复，不需要干预
    }
    // 恢复时不能小于内容所需尺寸，否则前端会立刻再撑一次，造成可见抖动。
    let targetW = saved[0];
    let targetH = saved[1];
    try {
        const need = node.computeSize?.([saved[0], saved[1]]);
        const pair = asSizePair(need);
        if (pair) {
            targetW = Math.max(targetW, pair[0]);
            targetH = Math.max(targetH, pair[1]);
        }
    } catch (error) {
        // 老前端没有 computeSize 就按记录值恢复，不强求内容适配。
    }
    node._qgRestoringSize = true;
    node.setSize?.([targetW, targetH]);
    node._qgRestoringSize = false;
    node.setDirtyCanvas?.(true, true);
}

function scheduleRestore(node) {
    hookSerialize(node);
    if (node._qgQwen21RestorePending) return;
    node._qgQwen21RestorePending = true;
    // 注册在 scheduleSync 之后：同一帧内先同步 image 口（可能触发 addInput 的
    // 只增不减扩展），再校验尺寸，避免中途尺寸把记录覆盖掉。
    requestAnimationFrame(() => {
        node._qgQwen21RestorePending = false;
        restoreSize(node);
    });
}

app.registerExtension({
    name: "QG.QwenTextEncode",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_NAME) return;

        // 包装生命周期钩子必须把原实现的返回值传下去：ComfyUI 的其它扩展会
        // 把链式 hook 的返回值当成「是否继续 / 已处理」的依据，丢掉会让它们
        // 静默失效（本包开发规范已把这条列为硬约定）。
        const originalCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalCreated?.apply(this, arguments);
            labelReferenceSize(this);
            hookSerialize(this);
            scheduleSync(this);
            return result;
        };

        const originalConnections = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = originalConnections?.apply(this, arguments);
            labelReferenceSize(this);
            scheduleSync(this);
            return result;
        };

        const originalConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalConfigure?.apply(this, arguments);
            labelReferenceSize(this);
            scheduleSync(this);
            scheduleRestore(this);
            return result;
        };
    },
});
