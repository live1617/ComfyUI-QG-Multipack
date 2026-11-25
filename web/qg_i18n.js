/**
 * ComfyUI-QG-Multipack —— 下拉控件「显示值」汉化
 *
 * 背景：汉化插件（ComfyUI-Global-Translation）的 Menus 词表只能替换 DOM 文本，
 * 而收起状态下画布 / Vue 节点显示的 COMBO 当前值走的是 canvas 文本绘制或
 * widget 的 displayValue，DOM 替换够不到，所以一直显示英文（如 subtract）。
 *
 * 做法：ComfyUI 官方前端给 COMBO widget 留了 options.getOptionLabel(value) 钩子，
 * 收起时的当前值、展开时的菜单项都会走它，而选中回调写入 widget.value 的仍是
 * 英文原值。因此这里只挂一个「英文值 -> 中文短标签」的显示映射：
 *   - 界面显示中文
 *   - 工作流 JSON、API 提交、后端校验拿到的仍是英文值，行为完全不变
 *   - 映射按「节点类型 + 控件名」区分，避免 left 在混合模式 / 对齐方式里语义串味
 *     （全局词表做不到这一点）
 *
 * 未收录的值（用户自定义服务商、模型名、规则名等）原样显示。
 * 中文值（规则名、百度翻译等）不在映射里，也原样显示。
 */
import { app } from "/scripts/app.js";

const PROVIDER = {
  "Moonshot Kimi": "月之暗面 Kimi",
  "Alibaba Qwen": "阿里通义千问",
  "Zhipu GLM": "智谱 GLM",
  "SiliconFlow": "硅基流动",
  "Ollama (local)": "Ollama（本地）",
  "DeepSeek/deepseek-reasoner": "DeepSeek · 推理版",
  "Moonshot Kimi/kimi-k2-turbo-preview": "月之暗面 Kimi/kimi-k2-turbo-preview",
  "Alibaba Qwen/qwen-max": "阿里通义千问/qwen-max",
  "Alibaba Qwen/qwen-turbo": "阿里通义千问/qwen-turbo",
  "Zhipu GLM/glm-4.5": "智谱 GLM/glm-4.5",
  "SiliconFlow/deepseek-ai/DeepSeek-V3": "硅基流动/DeepSeek-V3",
  "OpenRouter/google/gemini-2.5-flash": "OpenRouter · Gemini 2.5 Flash",
  "OpenRouter/openai/gpt-4o-mini": "OpenRouter · GPT-4o mini",
  "Ollama/qwen2.5vl:7b": "本地 Ollama · Qwen2.5-VL 7B",
  "Ollama/llama3.2-vision:11b": "本地 Ollama · Llama 3.2 Vision",
  "Ollama/llava:7b": "本地 Ollama · LLaVA 7B",
};

const LANG_LOWER = {
  auto: "自动",
  chinese: "中文",
  english: "英文",
  japanese: "日文",
  korean: "韩文",
  french: "法文",
  german: "德文",
  spanish: "西班牙文",
  russian: "俄文",
};

const LANG_CAP = {
  English: "英文",
  Chinese: "中文",
  Japanese: "日文",
  Korean: "韩文",
  French: "法文",
  German: "德文",
  Spanish: "西班牙文",
  Russian: "俄文",
};

// QG_GoogleTranslate 的语言码（BCP-47，存档值是码本身）。只映射常用的，
// 其余码按「未收录的值原样显示」约定直接显示码。
const GOOGLE_LANG = {
  "zh-cn": "中文（简体）",
  "zh-tw": "中文（繁体）",
  en: "英文",
  ja: "日文",
  ko: "韩文",
  fr: "法文",
  de: "德文",
  es: "西班牙文",
  ru: "俄文",
};
const GOOGLE_LANG_FROM = { auto: "自动", ...GOOGLE_LANG };

const IF_FAIL = {
  "output original": "输出原文",
  "stop the run": "终止运行",
};

const BUCKETS = {
  "Qwen-Image 1K": "Qwen-Image 1K 档",
  "Qwen-Image 2K": "Qwen-Image 2K 档",
  "SDXL 1K": "SDXL 1K 档",
  "SD 1.5 512": "SD 1.5 512 档",
  "SD 1.5 768": "SD 1.5 768 档",
  "Flux 1MP": "Flux 1MP 档",
  "Flux 2MP": "Flux 2MP 档",
};

/** 节点类型 -> 控件名 -> 英文值 -> 中文显示名 */
const LABELS = {
  QG_MaskByName: {
    several: {
      "all matches": "全部合并",
      "largest only": "只取最大",
    },
    if_nothing: {
      "stop the run": "终止运行",
      "empty mask": "输出空蒙版",
    },
  },
  QG_Translate: {
    provider: PROVIDER,
    to_lang: LANG_LOWER,
    from_lang: LANG_LOWER,
    if_fail: IF_FAIL,
  },
  QG_PromptTranslate: {
    target_language: LANG_CAP,
    translate_service: PROVIDER,
  },
  QG_PromptOptimize: {
    llm_service: PROVIDER,
  },
  QG_GoogleTranslate: {
    from_translate: GOOGLE_LANG_FROM,
    to_translate: GOOGLE_LANG,
  },
  QG_FaceRectify: {
    enable_fix: {
      True: "开启",
      False: "关闭",
    },
  },
  QG_BiRefNet: {
    // model 是模型权重文件名，按惯例保留英文代号
    background: {
      Alpha: "透明背景",
      Color: "纯色背景",
    },
  },
  QG_IDPhotoCrop: {
    alpha_mode: {
      fill: "填平透明",
      keep: "保留透明",
    },
  },
};

/**
 * 节点帮助浮层用的中文 tooltip（与 locales/zh/nodeDefs.json 同步）。
 * 本包 3 个老节点的 tooltip 原文是英文，后端与 Vue 节点定义各有自己的一份数据，
 * 汉化插件的 Menus 词表只能替换 DOM 文本，够不到这两处，所以在注册阶段直接补齐。
 */
const TOOLTIPS = {
  "QG_MaskByName": {
    "image": "要搜索的图片。",
    "checkpoint": "SAM 3 检查点：sam3.1_multiplex_fp16.safetensors（放 models/checkpoints，或 extra_model_paths.yaml 里配置的 checkpoints 目录）。节点内部加载，无需检查点加载器；文件里的文字读取器负责读名称，无需单独的 CLIP。",
    "name": "要找什么，几个普通词即可，如「那只狗」「红色夹克」。要找多个物体就用逗号隔开。",
    "several": "匹配到多个物体时：全部合并成一个蒙版，或只取面积最大的那个。",
    "grow": "蒙版向外扩多少像素。0 保持精确轮廓。",
    "soften": "蒙版边缘软化多少像素。0 保持硬边。",
    "if_nothing": "没有任何匹配时怎么办。终止运行：工作流在此停止并给出提示，本节点之后一律不跑。空蒙版：继续运行，输出一张全黑蒙版。",
    "preview": "在节点上显示染色+描边的找到区域。关掉可省去写临时预览文件。",
    "drop_small": "剔除搜索偶尔在目标旁边留下的零碎小白斑——蒙版里独立、不属于目标的小岛。面积最大的一块永远保留。",
    "small_size": "多小的一块算零碎噪点：以最大块面积的百分比计。仅在「剔除碎块」开启时生效。",
    "threshold": "SAM 3 判定「匹配」所需的最低确信度。小物体被漏掉就调低；把不是目标的东西框进来了就调高。",
    "fill_holes": "填补完全位于蒙版内部的空隙（分割在头发、布料上常留的洞）。开启后得到实心形状。",
    "free_vram": "搜索结束后立刻把 SAM 3 移出显存。后面还要加载大模型的工作流建议开启；关闭则下一次搜索稍快。",
  },
  "QG_Translate": {
    "text": "要翻译的文字。直接在这里输入，或把上游文本接到这个口上（右键字段可转换为输入口）。",
    "provider": "调用哪一条服务商。列表 = 内置厂商 + 你在 设置 → QG 工具 里添加的条目；只写服务商名就用它的默认模型，写成「服务商/模型」可以指名某个模型。地址、模型、Key 都跟着设置面板那条配置走。",
    "to_lang": "翻译成什么语言。默认英文——SAM 3 这类检测模型只认英文。",
    "from_lang": "原文是什么语言。auto 让模型自己判断；原文很短且有歧义时建议指定。",
    "api_url": "已移到系统设置，一般不用填。老工作流里如果还留着值，会优先生效。",
    "model": "已移到系统设置，一般不用填。老工作流里如果还留着值，会优先生效。",
    "api_key": "已移到系统设置，一般不用填。Key 存在 ComfyUI/user/ComfyUI-QG-Multipack/config.json，插件目录和工作流都不含密钥。这里填的只在本次会话有效，不会写进工作流。",
    "if_fail": "API 连不上或拒绝时怎么办。输出原文：继续运行，文字原样传下去。终止运行：工作流在此停止并给出服务商的报错信息。",
  },
};

/** LiteGraph 注册路径：nodeData.input.<组>.<字段>[1].tooltip */
function patchLiteGraphDef(nodeData, cls) {
  const tips = TOOLTIPS[cls];
  if (!tips || !nodeData?.input) return;
  for (const group of Object.values(nodeData.input)) {
    for (const [name, spec] of Object.entries(group || {})) {
      if (tips[name] && spec?.[1] && typeof spec[1] === "object") {
        spec[1].tooltip = tips[name];
      }
    }
  }
}

/** Vue 节点定义结构随前端版本变化，做防御式递归，只改带 tooltip 的字段对象。 */
function patchVueDef(def, tips, depth, seen) {
  seen = seen || new WeakSet();
  if (!def || typeof def !== "object" || depth > 6 || seen.has(def)) return;
  seen.add(def);
  for (const [key, val] of Object.entries(def)) {
    if (!val || typeof val !== "object") continue;
    if (tips[key]) {
      if (typeof val.tooltip === "string") val.tooltip = tips[key];
      if (val[1] && typeof val[1] === "object" && typeof val[1].tooltip === "string") {
        val[1].tooltip = tips[key];
      }
    }
    patchVueDef(val, tips, depth + 1, seen);
  }
}

const patched = new WeakSet();

function applyToNode(node) {
  if (!node) return;
  const cls = node.comfyClass || node.constructor?.comfyClass || node.type;
  const byField = LABELS[cls];
  if (!byField) return;

  let changed = false;
  for (const w of node.widgets || []) {
    const dict = byField[w.name];
    if (!dict || !w.options || patched.has(w)) continue;

    const prev = typeof w.options.getOptionLabel === "function"
      ? w.options.getOptionLabel
      : null;

    w.options.getOptionLabel = function (value) {
      const key = value == null ? value : String(value);
      if (key != null && Object.prototype.hasOwnProperty.call(dict, key)) {
        return dict[key];
      }
      if (prev) return prev.call(this, key);
      return key ?? "";
    };

    patched.add(w);
    changed = true;
  }
  if (changed && typeof node.setDirtyCanvas === "function") {
    node.setDirtyCanvas(true, true);
  }
}

function scanGraph() {
  const g = app.graph;
  if (!g) return;
  for (const node of g._nodes || g.nodes || []) applyToNode(node);
}

app.registerExtension({
  name: "QG.I18n.ComboLabels",
  beforeRegisterNodeDef(nodeType, nodeData) {
    patchLiteGraphDef(nodeData, nodeType?.comfyClass);
  },
  beforeRegisterVueAppNodeDefs(nodeDefs) {
    for (const def of nodeDefs || []) {
      const cls = def?.comfyClass || def?.name || def?.type;
      const tips = TOOLTIPS[cls];
      if (tips) patchVueDef(def, tips, 0);
    }
  },
  setup() {
    scanGraph();
  },
  nodeCreated(node) {
    applyToNode(node);
    const tips = TOOLTIPS[node.comfyClass || node.type];
    if (tips) {
      for (const input of node.inputs || []) {
        if (tips[input.name]) input.tooltip = tips[input.name];
      }
    }
  },
  loadedGraphNode(node) {
    applyToNode(node);
  },
  afterConfigureGraph() {
    scanGraph();
  },
});
