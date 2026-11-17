/**
 * QG 证件照尺寸选择 —— 把预设输出槽对齐成 COMBO。
 *
 * 后端 RETURN_TYPES 第 1 槽写的是 PRESET_ORDER 列表本身：后端
 * validate_node_input 拿到的 input_type 是下拉的原始选项列表，只有"与下游
 * 逐项相同的数组"才放行（写 "STRING" 或 "COMBO" 都会被判不匹配）。
 *
 * 但前端 addOutputs 会把这个数组原样当槽类型用，而下游 combo 输入槽的类型是
 * 字符串 "COMBO"，于是连线校验拿数组比字符串，必然不匹配。这里在生成槽位之前
 * 就把类型换成 "COMBO"，让 preset 能直接驱动证件照裁剪 / 证件照参数的下拉。
 *
 * 中文显示（1寸、大1寸……）由 qg_photokit_zh.js 的 NODES 表统一负责，
 * 与裁剪节点共用同一份文案，不在这里重复维护。
 */
import { app } from "/scripts/app.js";

const NODE_NAME = "QG_IDPhotoSizePicker";

function markPresetOutput(node) {
    const outputs = node?.outputs || [];
    const slot = outputs.find((s) => s?.name === "preset") || outputs[0];
    if (!slot || slot.type === "COMBO") return;
    slot.type = "COMBO";
    slot.__qgSpCombo = true;
}

app.registerExtension({
    name: "QG.IDPhotoSizePicker",

    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_NAME) return;

        // nodeData 可能是被冻结的对象：ES module 严格模式下赋值会抛 TypeError，
        // 并中断该节点的注册（现象是节点在工作流里整个消失、只剩悬空连线）。
        // 必须兜住，失败就交给下面的 markPresetOutput 覆盖槽位。
        try {
            if (Array.isArray(nodeData.output?.[0])) {
                nodeData.output[0] = "COMBO";
            }
        } catch (err) {
            /* nodeData 冻结，退回槽位覆盖 */
        }

        const onCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onCreated?.apply(this, arguments);
            markPresetOutput(this);
            return r;
        };

        // 从已保存工作流加载时不走 onNodeCreated，补一道。
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = onConfigure?.apply(this, arguments);
            markPresetOutput(this);
            return r;
        };
    },

    nodeCreated(node) {
        if (node?.comfyClass === NODE_NAME || node?.type === NODE_NAME) {
            markPresetOutput(node);
        }
    },

    setup() {
        for (const node of app.graph?._nodes || []) markPresetOutput(node);
    },
});
