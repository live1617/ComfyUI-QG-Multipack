/**
 * QG 证件照简易提示词 —— 13 个下拉的中文显示。
 *
 * 后端下拉值一律英文编号（composition_01 ...），中文只是显示名：走官方
 * widget.options.getOptionLabel 钩子，不改存档值、不影响 API。映射表由
 * qg_id_photo_prompt.py 的 value_label_map() 生成，两边不会漂移。
 */
import { app } from "/scripts/app.js";

const LABELS = {
    "none": "无",
    "random": "随机",
    "composition_01": "人像面部特写",
    "composition_02": "上半身近景特写",
    "composition_03": "中近景构图",
    "composition_04": "半身构图",
    "composition_05": "七分身构图",
    "nationality_01": "中国",
    "nationality_02": "日本",
    "nationality_03": "韩国",
    "nationality_04": "东南亚",
    "nationality_05": "印度",
    "nationality_06": "中东",
    "nationality_07": "俄罗斯",
    "nationality_08": "北欧",
    "nationality_09": "西欧",
    "nationality_10": "南欧",
    "nationality_11": "北美",
    "nationality_12": "南美",
    "nationality_13": "非洲",
    "nationality_14": "原住民",
    "nationality_15": "混血",
    "gender_01": "女孩",
    "gender_02": "男孩",
    "gender_03": "女人",
    "gender_04": "男人",
    "gender_05": "老人",
    "gender_06": "老奶奶",
    "gender_07": "老爷爷",
    "gender_08": "小女孩",
    "gender_09": "小男孩",
    "gender_10": "女婴儿",
    "gender_11": "男婴儿",
    "body_shape_01": "纤细的",
    "body_shape_02": "苗条的",
    "body_shape_03": "丰满的",
    "body_shape_04": "肌肉发达的",
    "body_shape_05": "娇小的",
    "body_shape_06": "高挑的",
    "body_shape_07": "肥胖的",
    "hair_color_01": "黑色",
    "hair_color_02": "蓝黑色",
    "hair_color_03": "茶黑色",
    "hair_color_04": "深棕色",
    "hair_color_05": "巧克力棕",
    "hair_color_06": "亚麻棕",
    "hair_color_07": "青木棕",
    "hair_color_08": "香槟金",
    "hair_color_09": "酒红色",
    "hair_color_10": "莓果红",
    "hair_color_11": "橘红色",
    "hair_color_12": "奶奶灰",
    "hair_color_13": "雾霾灰",
    "hair_color_14": "灰紫色",
    "hair_color_15": "蓝灰色",
    "hair_color_16": "孔雀蓝",
    "hair_color_17": "樱花粉",
    "hair_color_18": "玫瑰粉",
    "hair_color_19": "粉紫色",
    "hair_color_20": "奶茶色",
    "hair_color_21": "薰衣草紫",
    "hair_color_22": "珊瑚橙",
    "hair_color_23": "渐变色",
    "hairstyle_01": "飘逸长发",
    "hairstyle_02": "波波头",
    "hairstyle_03": "精灵短发",
    "hairstyle_04": "露耳短发",
    "hairstyle_05": "空气刘海",
    "hairstyle_06": "中长发",
    "hairstyle_07": "锁骨发",
    "hairstyle_08": "波浪卷",
    "hairstyle_09": "法式刘海",
    "hairstyle_10": "齐刘海",
    "hairstyle_11": "长发",
    "hairstyle_12": "大波浪",
    "hairstyle_13": "黑长直",
    "hairstyle_14": "公主切",
    "hairstyle_15": "高马尾",
    "hairstyle_16": "复古背头",
    "hairstyle_17": "复古卷发",
    "hairstyle_18": "单马尾辫",
    "hairstyle_19": "双马尾辫",
    "hairstyle_20": "脏辫（Dreadlocks）",
    "hairstyle_21": "丸子头发",
    "hairstyle_22": "头包脸发型",
    "clothing_color_01": "中性色",
    "clothing_color_02": "黑色",
    "clothing_color_03": "白色",
    "clothing_color_04": "灰色",
    "clothing_color_05": "米色",
    "clothing_color_06": "卡其色",
    "clothing_color_07": "驼色",
    "clothing_color_08": "冷色",
    "clothing_color_09": "藏青色",
    "clothing_color_10": "天蓝色",
    "clothing_color_11": "宝蓝色",
    "clothing_color_12": "浅蓝色",
    "clothing_color_13": "墨绿色",
    "clothing_color_14": "军绿色",
    "clothing_color_15": "浅绿色",
    "clothing_color_16": "暖色",
    "clothing_color_17": "红色",
    "clothing_color_18": "酒红色",
    "clothing_color_19": "浅红色",
    "clothing_color_20": "粉色",
    "clothing_color_21": "玫粉色",
    "clothing_color_22": "浅粉色",
    "clothing_color_23": "橙色",
    "clothing_color_24": "黄色",
    "clothing_color_25": "浅黄色",
    "clothing_color_26": "紫色",
    "clothing_color_27": "浅紫色",
    "clothing_color_28": "深紫色",
    "clothing_color_29": "棕色",
    "clothing_color_30": "咖啡色",
    "clothing_color_31": "牛仔蓝",
    "clothing_color_32": "荧光色",
    "clothing_color_33": "荧光黄",
    "clothing_color_34": "荧光绿",
    "clothing_color_35": "金色",
    "clothing_color_36": "银色",
    "clothing_style_01": "V领T恤",
    "clothing_style_02": "圆领T恤",
    "clothing_style_03": "衬衫",
    "clothing_style_04": "V领衬衫",
    "clothing_style_05": "POLO衫",
    "clothing_style_06": "泡泡袖",
    "clothing_style_07": "毛衣",
    "clothing_style_08": "卫衣",
    "clothing_style_09": "夹克",
    "clothing_style_10": "西装外套",
    "clothing_style_11": "V领正装",
    "clothing_style_12": "风衣",
    "clothing_style_13": "皮衣",
    "clothing_style_14": "羽绒服",
    "clothing_style_15": "高档婚纱",
    "clothing_style_16": "高档礼服",
    "clothing_style_17": "马甲",
    "clothing_style_18": "连衣裙",
    "clothing_style_19": "牛仔衣",
    "clothing_style_20": "军装",
    "clothing_style_21": "警服",
    "clothing_style_22": "护士服",
    "clothing_style_23": "厨师服",
    "clothing_style_24": "校服",
    "clothing_style_25": "白大褂",
    "clothing_style_26": "睡衣",
    "clothing_style_27": "旗袍",
    "clothing_style_28": "包臀裙",
    "clothing_style_29": "背带裤",
    "clothing_style_30": "春装",
    "clothing_style_31": "夏装",
    "clothing_style_32": "秋装",
    "clothing_style_33": "冬装",
    "accessory_01": "领带",
    "accessory_02": "格子领带",
    "accessory_03": "斜纹领带",
    "accessory_04": "领结",
    "accessory_05": "蝴蝶结",
    "accessory_06": "腰带",
    "accessory_07": "围巾",
    "makeup_01": "素颜",
    "makeup_02": "淡妆",
    "makeup_03": "日常妆",
    "makeup_04": "清新妆",
    "makeup_05": "素颜妆",
    "makeup_06": "职场妆",
    "makeup_07": "烟熏妆",
    "makeup_08": "晚晏妆",
    "makeup_09": "新娘妆",
    "makeup_10": "舞台妆",
    "makeup_11": "韩系妆",
    "makeup_12": "日系妆",
    "makeup_13": "中式古典妆",
    "makeup_14": "复古妆",
    "makeup_15": "欧美妆",
    "makeup_16": "纯欲妆",
    "expression_01": "微笑",
    "expression_02": "大笑",
    "expression_03": "抿嘴笑",
    "expression_04": "甜甜的笑容和洁白的牙齿",
    "expression_05": "冷漠的表情",
    "expression_06": "冷笑",
    "background_color_01": "简单背景",
    "background_color_02": "中性色",
    "background_color_03": "黑色",
    "background_color_04": "白色",
    "background_color_05": "灰色",
    "background_color_06": "米色",
    "background_color_07": "卡其色",
    "background_color_08": "驼色",
    "background_color_09": "冷色",
    "background_color_10": "藏青色",
    "background_color_11": "天蓝色",
    "background_color_12": "宝蓝色",
    "background_color_13": "浅蓝色",
    "background_color_14": "墨绿色",
    "background_color_15": "军绿色",
    "background_color_16": "浅绿色",
    "background_color_17": "暖色",
    "background_color_18": "红色",
    "background_color_19": "酒红色",
    "background_color_20": "浅红色",
    "background_color_21": "粉色",
    "background_color_22": "玫粉色",
    "background_color_23": "浅粉色",
    "background_color_24": "橙色",
    "background_color_25": "黄色",
    "background_color_26": "浅黄色",
    "background_color_27": "紫色",
    "background_color_28": "浅紫色",
    "background_color_29": "深紫色",
    "background_color_30": "棕色",
    "background_color_31": "咖啡色",
    "background_color_32": "牛仔蓝",
    "background_color_33": "荧光色",
    "background_color_34": "荧光黄",
    "background_color_35": "荧光绿",
    "background_color_36": "金色",
    "background_color_37": "银色",
    "extra_accessory_01": "帽子",
    "extra_accessory_02": "眼镜",
    "extra_accessory_03": "细框眼镜",
    "extra_accessory_04": "粗框眼镜",
    "extra_accessory_05": "耳环",
    "extra_accessory_06": "耳钉",
    "extra_accessory_07": "项链",
    "extra_accessory_08": "头花",
    "extra_accessory_09": "发箍"
};

const DIM_KEYS = new Set(["composition", "nationality", "gender", "body_shape", "hair_color", "hairstyle", "clothing_color", "clothing_style", "accessory", "makeup", "expression", "background_color", "extra_accessory"]);

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

/** 只挂一次；getOptionLabel 内部实时判语言，切界面语言后无需重建节点。 */
function labelCombos(node) {
    for (const widget of node.widgets || []) {
        if (!widget || !DIM_KEYS.has(widget.name) || widget.__qgIppLabel) continue;
        widget.__qgIppLabel = true;
        widget.options = widget.options || {};
        const previous = typeof widget.options.getOptionLabel === "function"
            ? widget.options.getOptionLabel
            : null;
        widget.options.getOptionLabel = function (value) {
            const key = value == null ? value : String(value);
            if (wantsChinese() && LABELS[key]) return LABELS[key];
            return previous ? previous.call(this, value) : value;
        };
    }
}

app.registerExtension({
    name: "QG.IDPhotoPrompt",

    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== "QG_IDPhotoPrompt") return;

        const onCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onCreated?.apply(this, arguments);
            labelCombos(this);
            return r;
        };

        // 从已保存工作流加载时不走 onNodeCreated，补一道
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = onConfigure?.apply(this, arguments);
            labelCombos(this);
            return r;
        };
    },

    nodeCreated(node) {
        if (node?.comfyClass === "QG_IDPhotoPrompt" || node?.type === "QG_IDPhotoPrompt") {
            labelCombos(node);
        }
    },

    setup() {
        for (const node of app.graph?._nodes || []) labelCombos(node);
    },
});
