// QG Translate: 服务商配置放在 ComfyUI 的系统设置里，节点上只留下拉框。
//
// 管理界面（参照 Prompt Assistant 的交互重做，代码独立实现）：
//   1. 设置面板里一张卡片：显示「有几个服务商 / 默认是哪个」，点「管理」开对话框；
//   2. 对话框是标签页式：内置厂商一排灰 tab（地址/模型只读防改错，Key 可填），
//      自定义服务商白色 tab（可增删改、拖动「设为默认」），「＋」新建；
//   3. 每个字段失焦即保存 —— 不需要「保存」按钮，改完点别处就写盘；
//   4. 节点上的 provider 下拉自动同步，api_url / model / api_key 三个
//      widget 收起 —— 这些值由设置里的条目提供，不用每个节点填。

import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const API_BASE = "/qg_translate";
const HIDDEN_WIDGETS = ["api_url", "model", "api_key"];
const MASK = "****";

// 当前配置（服务商列表与内置 Key 都是后端打码后的版本）
let CONFIG = {
  providers: [],
  default_provider: "custom",
  choices: ["custom"],
  presets: {},
  preset_keys: {},
  // 图像反推节点的「服务商/模型」下拉，由后端拼好
  vision_services: [],
  // 百度翻译：appid 明文，密钥只拿得到掩码
  baidu: { appid: "", has_key: false, key_masked: "" },
  // 规则摘要：节点 rule 下拉用，正文在规则管理器里
  rules: { order: [], groups: {}, node_rules: [] },
};
let loaded = false;

async function loadConfig(force) {
  if (loaded && !force) return CONFIG;
  try {
    const res = await api.fetchApi(API_BASE + "/config");
    if (res.ok) {
      const data = await res.json();
      CONFIG = {
        providers: Array.isArray(data.providers) ? data.providers : [],
        default_provider: data.default_provider || "custom",
        choices: Array.isArray(data.choices) && data.choices.length ? data.choices : ["custom"],
        presets: data.presets || {},
        preset_keys: data.preset_api_keys || {},
        baidu: data.baidu || { appid: "", has_key: false, key_masked: "" },
        vision_services: Array.isArray(data.vision_services) ? data.vision_services : [],
        // 规则摘要（只有名字），图像反推节点的 rule 下拉照它同步
        rules: data.rules || { order: [], groups: {}, node_rules: [] },
      };
    }
  } catch (error) {
    console.warn("[QG-Translate] 读取服务商配置失败:", error);
  }
  loaded = true;
  syncAllNodes();
  return CONFIG;
}

async function saveConfig(payload) {
  const res = await api.fetchApi(API_BASE + "/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    throw new Error(data.message || ("HTTP " + res.status));
  }
  loaded = false;
  await loadConfig(true);
  return data;
}

async function testProvider(entry) {
  const res = await api.fetchApi(API_BASE + "/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider: entry }),
  });
  return res.json().catch(() => ({ ok: false, message: "HTTP " + res.status }));
}

// ---------- 节点 ----------

function hideWidget(node, name) {
  const widget = node.widgets?.find((w) => w.name === name);
  if (!widget) return;
  widget.computeSize = () => [0, -4];
  widget.type = "hidden";
  widget.hidden = true;
}

/** 已选服务不在下拉列表里时的统一处理：保留原值，只提示一次。
 *
 *  早先的写法是 ``if (!choices.includes(value)) value = choices[0]``。后果是：
 *  用户在设置面板删掉（或改名）某个服务后，节点在刷新下拉时**静默切换**到
 *  另一个服务——跑出来的结果不是他要的，而且界面上没有任何痕迹。现在保留
 *  原值，让后端在运行时报「这个服务没有 API 地址」（那条报错会指名道姓），
 *  前端只补一条一次性提示，避免用户完全不知道发生了什么。
 */
const warnedMissingService = new Set();

function keepUnlistedService(widget, kind) {
  const value = String(widget.value || "");
  if (!value) return;
  const key = kind + "|" + value;
  if (warnedMissingService.has(key)) return;
  warnedMissingService.add(key);
  const msg = `服务「${value}」已不在可用列表里（可能在设置面板里被删掉或改了名）。`
    + "节点保留了这个选择；运行时若提示没有 API 地址，去设置面板重新选一个即可。";
  console.warn("[QG-Multipack]", msg);
  try {
    app.extensionManager?.toast?.add?.({
      severity: "warn",
      summary: "QG 工具：服务已失效",
      detail: msg,
      life: 8000,
    });
  } catch (err) {
    /* 老前端没有 toast，控制台那条就是全部提示 */
  }
}

/** 把最新的服务商列表塞进节点的下拉框，并保持当前选中值。 */
function syncNode(node) {
  const widget = node.widgets?.find((w) => w.name === "provider");
  if (!widget) return;
  const choices = CONFIG.choices?.length ? CONFIG.choices : ["custom"];
  widget.options = widget.options || {};
  widget.options.values = choices;
  if (!choices.includes(widget.value)) {
    if (widget.value) {
      keepUnlistedService(widget, "translate");
    } else {
      const fallback = choices.includes(CONFIG.default_provider)
        ? CONFIG.default_provider : choices[0];
      widget.value = fallback;
    }
  }
  node.setDirtyCanvas?.(true, false);
}

/** 提示词翻译的服务下拉：两条百度通道打头，其余与 QG_Translate 同源。
 *  这两项必须与后端 prompt_translate_node.service_choices() 一致——少一项
 *  的话，用户面板里改完配置，节点上已选的「百度翻译（大模型）」会被刷掉。 */
const BAIDU_SERVICES = ["百度翻译", "百度翻译（大模型）"];

function promptServiceChoices() {
  const base = CONFIG.choices?.length ? CONFIG.choices : ["custom"];
  return [...BAIDU_SERVICES, ...base.filter((n) => !BAIDU_SERVICES.includes(n))];
}

/** 刷新提示词翻译节点的服务下拉（该节点所有控件都可见，不隐藏任何东西）。 */
function syncPromptNode(node) {
  const widget = node.widgets?.find((w) => w.name === "translate_service");
  if (!widget) return;
  const choices = promptServiceChoices();
  widget.options = widget.options || {};
  widget.options.values = choices;
  if (!choices.includes(widget.value)) {
    if (widget.value) {
      keepUnlistedService(widget, "prompt_translate");
    } else {
      // custom 是空地址占位，别把默认值落在它身上
      const want = CONFIG.default_provider;
      widget.value = (want && want !== "custom" && choices.includes(want))
        ? want
        : (choices.find((n) => n !== "custom") || choices[0]);
    }
  }
  node.setDirtyCanvas?.(true, false);
}

/** 图像反推节点的规则下拉：名字来自设置里的规则管理器（rules.json）。
 *  规则改名/删除之后，旧值不在列表里了，回退到该组的激活规则——
 *  后端 run() 里也有一层同样的回退，两边都做才不会被老工作流卡住。 */
function syncRuleWidget(node) {
  const widget = node.widgets?.find((w) => w.name === "rule");
  if (!widget) return;
  const names = CONFIG.rules?.node_rules || [];
  if (!names.length) return;            // 后端没给就保持原样，别把下拉清空
  widget.options = widget.options || {};
  widget.options.values = names;
  // 值不在列表里时不要急着换成激活规则：这多半是「改名前的旧名」，后端
  // 按 aliases 还能命中（老工作流正是靠这个继续跑）。前端一改，用户就再也
  // 看不到自己原来选的是哪条，而且会静默换成另一套规则。只有值为空时才补默认。
  if (!widget.value) {
    const active = CONFIG.rules?.groups?.image?.active;
    widget.value = (active && names.includes(active)) ? active : names[0];
  }
  node.setDirtyCanvas?.(true, false);
}

/** 刷新图像反推节点的视觉服务下拉。
 *  这份列表由后端给（内置视觉模型 + 自定义服务商的模型），前端拼不出来。
 *  后端返回空数组时保持原样，不能把下拉清空。 */
function syncVisionNode(node) {
  const widget = node.widgets?.find((w) => w.name === "vlm_service");
  const choices = CONFIG.vision_services || [];
  if (widget && choices.length) {
    widget.options = widget.options || {};
    widget.options.values = choices;
    // 同样是「保留原值 + 提示」，不把用户选的视觉服务悄悄换成第一个
    if (!choices.includes(widget.value)) {
      if (widget.value) keepUnlistedService(widget, "vision");
      else widget.value = choices[0];
    }
  }
  syncRuleWidget(node);
  node.setDirtyCanvas?.(true, false);
}

/** 提示词优化节点的两个下拉。
 *
 *  rule 只列「提示词优化」这一组——后端 INPUT_TYPES 用的是
 *  ``node_rule_choices(("optimize",))``，前端要是把三组名字全塞进去，
 *  用户就能选到图像反推的规则，提交时被判 Value not in list。
 *  llm_service 与 QG_Translate 的服务商列表同源。
 */
function syncOptimizeNode(node) {
  const optimize = CONFIG.rules?.groups?.optimize || {};
  const names = Array.isArray(optimize.names) ? optimize.names : [];
  const ruleWidget = node.widgets?.find((w) => w.name === "rule");
  if (ruleWidget && names.length) {
    ruleWidget.options = ruleWidget.options || {};
    ruleWidget.options.values = names;
    // 值不在列表里多半是「改名前的旧名」，后端按 aliases 还能命中，
    // 这里不动它；只有空值才补默认（与 syncRuleWidget 同一套判断）。
    if (!ruleWidget.value) {
      const active = optimize.active;
      ruleWidget.value = (active && names.includes(active)) ? active : names[0];
    }
  }

  const svc = node.widgets?.find((w) => w.name === "llm_service");
  if (svc) {
    const choices = CONFIG.choices?.length ? CONFIG.choices : ["custom"];
    svc.options = svc.options || {};
    svc.options.values = choices;
    if (!choices.includes(svc.value)) {
      if (svc.value) {
        keepUnlistedService(svc, "optimize");
      } else {
        const want = CONFIG.default_provider;
        svc.value = (want && want !== "custom" && choices.includes(want))
          ? want
          : (choices.find((n) => n !== "custom") || choices[0]);
      }
    }
  }
  node.setDirtyCanvas?.(true, false);
}

function syncAllNodes() {
  const nodes = app.graph?._nodes || [];
  for (const node of nodes) {
    if (node.type === "QG_Translate") syncNode(node);
    else if (node.type === "QG_PromptTranslate") syncPromptNode(node);
    else if (node.type === "QG_ImageToPrompt") syncVisionNode(node);
    else if (node.type === "QG_PromptOptimize") syncOptimizeNode(node);
  }
}

// ---------- 设置面板里的卡片 ----------

function makeSettingsCard() {
  const row = document.createElement("div");
  row.style.cssText = "display:flex; align-items:center; gap:10px; flex-wrap:wrap;";

  const summary = document.createElement("span");
  summary.style.cssText = "font-size:12px; opacity:.75;";
  const button = document.createElement("button");
  button.textContent = "管理服务商…";
  button.style.cssText = [
    "padding:5px 12px", "border-radius:7px", "cursor:pointer", "font-size:12px",
    "border:1px solid var(--border-color,#4a4a55)",
    "background:var(--comfy-input-bg,#2a2a33)",
    "color:var(--fg-color,#ddd)",
  ].join(";");

  const paint = () => {
    const count = CONFIG.providers.length;
    const def = CONFIG.default_provider || "custom";
    summary.textContent = count
      ? `${count} 个自定义服务商 · 默认：${def}`
      : "使用内置厂商即可，点右边可添加自己的服务商";
  };

  button.onclick = () => openManager();
  row.append(summary, button);
  paint();
  loadConfig().then(paint);
  // 对话框保存后刷新摘要
  window.addEventListener("qg-providers-changed", paint);
  return row;
}

// ---------- 管理对话框（标签页式，失焦即存） ----------

const fieldStyle = [
  "width:100%", "box-sizing:border-box", "padding:5px 8px", "font-size:12px",
  "border-radius:6px", "border:1px solid var(--border-color,#4a4a55)",
  "background:var(--comfy-input-bg,#1b1b22)", "color:var(--fg-color,#ddd)",
].join(";");

const readonlyStyle = fieldStyle + ";opacity:.55;cursor:not-allowed;";

/** 当前打开的设置对话框（reka-ui Dialog）。找不到就返回 null，调用方退回 body。
 *
 *  面板必须挂在这层里面，否则焦点锁（FocusScope）会把焦点从输入框抢回设置
 *  的搜索框，用户看到的现象就是「输入框点不进去 / 打字没反应」。
 */
function settingsDialogHost() {
  return document.querySelector('[role="dialog"][data-reka-dialog-content]')
    || document.querySelector('[role="dialog"]');
}

function label(text) {
  const el = document.createElement("div");
  el.textContent = text;
  el.style.cssText = "font-size:11px; opacity:.6; margin-bottom:3px;";
  return el;
}

function input(value, placeholder, type) {
  const el = document.createElement("input");
  el.type = type || "text";
  el.value = value || "";
  el.placeholder = placeholder || "";
  el.style.cssText = fieldStyle;
  return el;
}

function buttonStyle(primary, danger) {
  const parts = [
    "padding:6px 12px", "border-radius:7px", "font-size:12px", "cursor:pointer",
    "border:1px solid var(--border-color,#4a4a55)",
    "background:var(--comfy-input-bg,#2a2a33)",
    "color:var(--fg-color,#ddd)",
  ];
  if (primary) {
    parts.push("background:#3a6ea5", "border-color:#3a6ea5", "color:#fff", "font-weight:600");
  }
  if (danger) {
    parts.push("color:#e88", "border-color:#a55");
  }
  return parts.join(";");
}

function openManager() {
  const overlay = document.createElement("div");
  overlay.style.cssText = [
    // 32 位 int 上限：必须压过 ComfyUI 新版 Vue 设置面板的弹层（其 z-index
    // 高于普通 99999，叠在一起时我们的对话框会被截走点击，表现为“点不动”）
    // pointer-events:auto 必须显式声明：设置面板打开时 Vue 会把 body 设为
    // pointer-events:none，不写就会被连坐成 none——点击全部穿透，z-index 再高也没用
    "position:fixed", "inset:0", "z-index:2147483647", "pointer-events:auto", "display:flex",
    "align-items:center", "justify-content:center",
    "background:rgba(0,0,0,.55)", "font-family:inherit",
  ].join(";");

  const card = document.createElement("div");
  card.style.cssText = [
    "width:min(720px,94vw)", "max-height:84vh", "display:flex", "flex-direction:column",
    "border-radius:12px", "overflow:hidden",
    "background:var(--comfy-menu-bg,#1e1e24)",
    "color:var(--fg-color,#ddd)",
    "border:1px solid var(--border-color,#45455a)",
    "box-shadow:0 16px 48px rgba(0,0,0,.5)",
  ].join(";");

  const head = document.createElement("div");
  head.style.cssText = [
    "display:flex", "align-items:center", "gap:10px",
    "padding:12px 16px", "border-bottom:1px solid var(--border-color,#33333d)",
  ].join(";");
  head.innerHTML = '<b style="font-size:14px;">API 服务商</b>'
    + '<span style="font-size:11px;opacity:.55;">Key 存在本机 ComfyUI/user 目录，插件目录和工作流都不含密钥</span>';
  const spacer = document.createElement("span");
  spacer.style.cssText = "flex:1;";
  const closeBtn = document.createElement("button");
  closeBtn.textContent = "×";
  closeBtn.style.cssText = "border:none;background:transparent;color:inherit;font-size:20px;cursor:pointer;line-height:1;";
  closeBtn.onclick = () => overlay.remove();
  head.append(spacer, closeBtn);

  // tab 条 + 详情区 + 状态栏
  const tabBar = document.createElement("div");
  tabBar.style.cssText = [
    "display:flex", "flex-wrap:wrap", "gap:6px", "align-items:center",
    "padding:10px 16px 0",
  ].join(";");
  const detail = document.createElement("div");
  detail.style.cssText = "padding:14px 16px; overflow-y:auto; flex:1;";
  const foot = document.createElement("div");
  foot.style.cssText = [
    "display:flex", "align-items:center", "gap:8px", "padding:10px 16px",
    "border-top:1px solid var(--border-color,#33333d)",
  ].join(";");
  const status = document.createElement("span");
  status.style.cssText = "flex:1; font-size:11.5px; opacity:.75;";
  foot.append(status);

  card.append(head, tabBar, detail, foot);
  overlay.appendChild(card);
  // 向 ComfyUI 前端(reka-ui)声明：本对话框是一个"更顶层"的弹层。
  // 设置面板在 document 上监听 pointerdown/focusin，凡是不在
  // data-dismissable-layer 层内的点击/聚焦都被判定为"点击外部"而 dismiss——
  // 之前每次点 tab 或点输入框都会把身后的设置面板关掉。本对话框 append 到
  // body 末尾、DOM 顺序在设置面板之后，加上此标记后 reka-ui 会视为嵌套顶层，不再关闭。
  overlay.dataset.dismissableLayer = "";
  // 双保险：拦截向 document 冒泡的指针/焦点/点击事件，
  // 任何"点击外部就关闭"的逻辑（reka-ui 或其他扩展）都看不到来自本对话框的点击。
  // 同元素上的其他监听器不受影响（stopPropagation 只挡向上冒泡），
  // 所以下面"点背景关闭"依然正常工作。
  for (const type of ["pointerdown", "mousedown", "click", "focusin"]) {
    overlay.addEventListener(type, (e) => e.stopPropagation());
  }
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) overlay.remove(); });
  // 必须挂进设置对话框内部，不能挂 body：设置面板是 reka-ui 的 Dialog，
  // 带 FocusScope 焦点锁——焦点一旦落到对话框外的元素上就会被立刻抢回搜索框，
  // 表现就是「点 API Key 输入框打不了字，字全跑进搜索框」。挂进去以后焦点
  // 始终在 scope 内，锁不会介入。
  (settingsDialogHost() || document.body).appendChild(overlay);

  // ---- 工作态（失焦即存，没有草稿/保存按钮） ----
  // 自定义条目：masked 是后端打码的 key；输入框留空 = 沿用。
  // models 是一个服务商下的多个模型，default_model 是没选具体模型时用的那个
  // ——老配置只有单个 model 字段，读进来时就地展开成一元素列表。
  const custom = CONFIG.providers.map((p) => {
    const models = Array.isArray(p.models) && p.models.length
      ? p.models.slice()
      : (p.model ? [p.model] : []);
    return {
      id: p.id, name: p.name, api_url: p.api_url,
      models,
      default_model: p.default_model || p.model || models[0] || "",
      has_key: p.has_key, masked: p.api_key_masked || "",
    };
  });
  // 内置预设的 key 草稿：name -> 掩码或新值
  const presetKeys = { ...(CONFIG.preset_keys || {}) };
  // 百度翻译那对凭证：appid 明文可回填，密钥同样「留空 = 沿用」
  const baidu = {
    appid: (CONFIG.baidu && CONFIG.baidu.appid) || "",
    has_key: !!(CONFIG.baidu && CONFIG.baidu.has_key),
    masked: (CONFIG.baidu && CONFIG.baidu.key_masked) || "",
    newKey: "",
  };
  let chosenDefault = CONFIG.default_provider || "custom";
  // 当前选中 tab：{type:'preset', name} 或 {type:'custom', index}
  let active = null;

  const statusOK = (text) => {
    status.style.color = "#7ccf8a";
    status.textContent = text;
    setTimeout(() => { if (status.textContent === text) status.textContent = ""; }, 2500);
  };
  const statusErr = (text) => {
    status.style.color = "#e88";
    status.textContent = text;
  };

  function dupName(excludeIndex) {
    const seen = new Set();
    for (let i = 0; i < custom.length; i++) {
      const n = custom[i].name.trim();
      if (!n || i === excludeIndex) continue;
      if (seen.has(n)) return n;
      seen.add(n);
    }
    return null;
  }

  // 保存串行化。点「★ 设为默认」这类按钮时，当前输入框会先 blur 触发一次
  // 保存，按钮自己又触发一次——两个请求并发，先发的可能后回，把新状态覆盖
  // 回旧值（实测表现：刚设成默认，界面又跳回上一条）。排成一条链，后一次
  // 永远基于前一次的结果写盘。
  let saveChain = Promise.resolve();

  function persist() {
    const run = () => doPersist();
    saveChain = saveChain.then(run, run);
    return saveChain;
  }

  async function doPersist() {
    const bad = dupName(-1);
    if (bad) {
      statusErr(`自定义服务商名称「${bad}」重复了，先改掉再离开这个输入框`);
      return false;
    }
    try {
      const data = await saveConfig({
        providers: custom.map((c) => ({
          id: c.id,
          name: c.name.trim(),
          api_url: c.api_url.trim(),
          // 空行是「刚点了添加还没填」，过滤掉；default_model 交给后端校正
          models: (c.models || []).map((m) => m.trim()).filter(Boolean),
          default_model: c.default_model || "",
          api_key: c.newKey || (c.has_key ? c.masked : ""),
        })),
        preset_api_keys: presetKeys,
        default_provider: chosenDefault,
        baidu: {
          appid: baidu.appid.trim(),
          key: baidu.newKey || (baidu.has_key ? baidu.masked : ""),
        },
      });
      // 只同步后端才知道的字段（掩码、服务端生成的 id）。models / default_model
      // 不回灌：这两个是用户刚在界面上改的，旧请求的响应晚到会把它们覆盖回
      // 上一次的值——「设完默认又跳回上一条」就是这么来的。后端对空默认的
      // 校正前端已经自己做过一遍，下次打开面板时 loadConfig 会再对齐。
      (data.providers || []).forEach((p, i) => {
        if (custom[i]) {
          custom[i].has_key = p.has_key;
          custom[i].masked = p.api_key_masked || "";
          custom[i].id = p.id || custom[i].id;
        }
      });
      Object.assign(presetKeys, data.preset_api_keys || {});
      if (data.baidu) {
        baidu.appid = data.baidu.appid || "";
        baidu.has_key = !!data.baidu.has_key;
        baidu.masked = data.baidu.key_masked || "";
        baidu.newKey = "";
      }
      window.dispatchEvent(new Event("qg-providers-changed"));
      statusOK("已保存 ✓");
      return true;
    } catch (error) {
      statusErr("保存失败：" + (error.message || error));
      return false;
    }
  }

  function renderTabs() {
    tabBar.innerHTML = "";
    // 百度翻译单独一页：它不是 OpenAI 兼容接口，凭证只有一对 appid/密钥
    tabBar.appendChild(tabEl({
      type: "baidu",
      title: "百度翻译",
      sub: baidu.has_key && baidu.appid ? "✓ key" : "",
      muted: true,
    }));
    const presetNames = Object.keys(CONFIG.presets).filter((n) => n !== "custom");
    for (const name of presetNames) {
      tabBar.appendChild(tabEl({
        type: "preset", name,
        title: name,
        sub: presetKeys[name] ? "✓ key" : "",
        muted: true,
      }));
    }
    custom.forEach((c, i) => {
      tabBar.appendChild(tabEl({
        type: "custom", index: i,
        title: (chosenDefault === c.name.trim() ? "★ " : "") + (c.name.trim() || "未命名"),
        sub: c.has_key ? "✓ key" : "",
        muted: false,
      }));
    });
    const addBtn = document.createElement("button");
    addBtn.textContent = "＋";
    addBtn.title = "添加自定义服务商";
    addBtn.style.cssText = [
      "padding:4px 10px", "border-radius:7px", "cursor:pointer", "font-size:13px",
      "border:1px dashed var(--border-color,#4a4a55)", "background:transparent",
      "color:var(--fg-color,#ddd)",
    ].join(";");
    addBtn.onclick = () => {
      let n = custom.length + 1;
      let name = `服务商 ${n}`;
      while (custom.some((c) => c.name.trim() === name)) name = `服务商 ${++n}`;
      custom.push({
        id: "", name, api_url: "", models: [], default_model: "",
        has_key: false, masked: "",
      });
      active = { type: "custom", index: custom.length - 1 };
      render();
    };
    tabBar.appendChild(addBtn);
  }

  function tabEl({ type, name, index, title, sub, muted }) {
    let isActive;
    if (type === "preset") isActive = active && active.type === "preset" && active.name === name;
    else if (type === "baidu") isActive = active && active.type === "baidu";
    else isActive = active && active.type === "custom" && active.index === index;
    const b = document.createElement("button");
    b.textContent = title + (sub ? `  ${sub}` : "");
    b.style.cssText = [
      "padding:5px 12px", "border-radius:8px 8px 0 0", "cursor:pointer", "font-size:12px",
      "border:1px solid " + (isActive ? "var(--border-color,#4a4a55)" : "transparent"),
      "border-bottom:none",
      "background:" + (isActive ? "var(--comfy-input-bg,#2a2a33)" : "transparent"),
      "color:" + (muted ? "var(--fg-color,#ddd)" : "var(--fg-color,#fff)"),
      "opacity:" + (muted ? (isActive ? "1" : ".55") : (isActive ? "1" : ".8")),
    ].join(";");
    b.onclick = () => {
      if (type === "preset") active = { type: "preset", name };
      else if (type === "baidu") active = { type: "baidu" };
      else active = { type: "custom", index };
      render();
    };
    return b;
  }

  function rowOfInput(labelText, value, placeholder, opts = {}) {
    const wrap = document.createElement("div");
    wrap.append(label(labelText));
    const el = input(value, placeholder, opts.type);
    el.style.cssText = opts.readonly ? readonlyStyle : fieldStyle;
    if (opts.readonly) { el.readOnly = true; el.tabIndex = -1; }
    if (opts.onblur) el.addEventListener("blur", opts.onblur);
    wrap.append(el);
    return { wrap, el };
  }

  function renderDetail() {
    detail.innerHTML = "";
    if (!active) {
      // 初始选中：优先第一个自定义条目，否则第一个真正的内置厂商
      // （"custom" 只是兜底占位，不在 tab 条里，绝不能被选中）
      if (custom.length) {
        active = { type: "custom", index: 0 };
      } else {
        const first = Object.keys(CONFIG.presets).filter((n) => n !== "custom")[0];
        if (first) active = { type: "preset", name: first };
        else return;
      }
    }
    if (active.type === "preset") renderPresetDetail();
    else if (active.type === "baidu") renderBaiduDetail();
    else renderCustomDetail();
  }

  // 百度翻译：通用文本翻译接口，不需要模型，只需要一对 appid / 密钥
  function renderBaiduDetail() {
    const box = document.createElement("div");
    box.style.cssText = "display:flex; flex-direction:column; gap:10px; max-width:560px;";

    const title = document.createElement("div");
    title.innerHTML = '<b>百度翻译</b> <span style="font-size:11px;opacity:.55;">'
      + '不是 OpenAI 兼容接口 · 按字符计费，标准版每月有免费额度</span>';
    box.append(title);

    const appidRow = rowOfInput("APP ID", baidu.appid, "开放平台应用的 APP ID");
    appidRow.el.addEventListener("blur", () => {
      const val = appidRow.el.value.trim();
      if (val === baidu.appid) return;      // 没动就不写盘
      baidu.appid = val;
      persist();
    });
    box.append(appidRow.wrap);

    const keyRow = rowOfInput(
      baidu.has_key ? `密钥（已保存 ${baidu.masked}，留空不改）` : "密钥",
      "", baidu.has_key ? "留空则沿用已保存的密钥" : "开放平台里那串密钥",
      { type: "password" },
    );
    keyRow.el.addEventListener("blur", () => {
      const val = keyRow.el.value.trim();
      if (!val) return;                     // 留空 = 不改，静默
      if (val.includes(MASK)) return;       // 掩码原样，不改
      baidu.newKey = val;
      keyRow.el.value = "";
      keyRow.el.placeholder = "已保存，重新打开对话框可见掩码";
      persist();
    });
    box.append(keyRow.wrap);

    const tip = document.createElement("div");
    tip.style.cssText = "font-size:11px; opacity:.6; line-height:1.7;";
    tip.innerHTML = '申请地址：<a href="https://fanyi-api.baidu.com/" target="_blank" '
      + 'style="color:inherit;">fanyi-api.baidu.com</a> → 管理控制台 → 开发者信息，'
      + '复制 APP ID 与密钥。<br>提示词翻译节点选「百度翻译」时用的就是这一对凭证。';
    box.append(tip);

    // 这一行之前漏了：元素都建好了却没挂进 detail，表现为点「百度翻译」页签后
    // 详情区全白，像是“没法设置”。其它两个 render*Detail 都在末尾做了这件事。
    detail.append(box);
  }

  // 内置预设：地址/模型只读（防改错导致请求失败），Key 可填
  function renderPresetDetail() {
    const preset = CONFIG.presets[active.name] || {};
    const box = document.createElement("div");
    box.style.cssText = "display:flex; flex-direction:column; gap:10px; max-width:560px;";

    const title = document.createElement("div");
    title.innerHTML = `<b>${active.name}</b> <span style="font-size:11px;opacity:.55;">内置厂商 · 地址与模型不可改（要改就新建自定义服务商）</span>`;
    box.append(title);

    box.append(rowOfInput("API 地址", preset.api_url || "（未预设，建议新建自定义服务商填写）", "", { readonly: true }).wrap);
    const presetModels = Array.isArray(preset.models) && preset.models.length
      ? preset.models : (preset.model ? [preset.model] : []);
    const presetModelText = presetModels.length
      ? presetModels.map((m) => (m === preset.model ? m + "（默认）" : m)).join(" · ")
      : "—";
    box.append(rowOfInput("可选模型", presetModelText, "", { readonly: true }).wrap);

    const keyRow = rowOfInput(
      presetKeys[active.name] ? `API Key（已保存 ${presetKeys[active.name]}，留空不改）` : "API Key",
      "", presetKeys[active.name] ? "留空则沿用已保存的 Key" : "sk-...", { type: "password" },
    );
    keyRow.el.addEventListener("blur", () => {
      const val = keyRow.el.value.trim();
      if (!val) return;                 // 留空 = 不改，静默
      if (val.includes(MASK)) return;   // 掩码原样，不改
      presetKeys[active.name] = val;
      keyRow.el.value = "";
      keyRow.el.placeholder = `已保存，重新打开对话框可见掩码`;
      persist();
    });
    box.append(keyRow.wrap);

    const testBtn = document.createElement("button");
    testBtn.textContent = "测试连通";
    testBtn.style.cssText = buttonStyle(false);
    const hint = document.createElement("div");
    hint.style.cssText = "font-size:11px; min-height:14px;";
    testBtn.onclick = async () => {
      testBtn.disabled = true;
      testBtn.textContent = "测试中…";
      hint.style.color = "inherit";
      hint.textContent = "";
      try {
        const result = await testProvider({
          name: active.name,
          api_url: preset.api_url || "",
          model: preset.model || "",
          api_key: (keyRow.el.value.trim() || presetKeys[active.name] || ""),
        });
        hint.style.color = result.ok ? "#7ccf8a" : "#e88";
        hint.textContent = result.ok
          ? `✓ ${result.message}：${result.sample || ""}`
          : `✗ ${String(result.message || "").slice(0, 240)}`;
      } catch (error) {
        hint.style.color = "#e88";
        hint.textContent = "✗ " + (error.message || error);
      } finally {
        testBtn.disabled = false;
        testBtn.textContent = "测试连通";
      }
    };
    box.append(testBtn, hint);
    detail.append(box);
  }

  function renderCustomDetail() {
    const c = custom[active.index];
    if (!c) { active = null; renderDetail(); return; }
    const box = document.createElement("div");
    box.style.cssText = "display:flex; flex-direction:column; gap:10px; max-width:560px;";

    const top = document.createElement("div");
    top.style.cssText = "display:flex; gap:8px; align-items:flex-end;";
    const nameRow = rowOfInput("名称（节点下拉里显示的名字）", c.name, "例如 中转站 / 自建代理");
    nameRow.el.addEventListener("blur", () => {
      const val = nameRow.el.value.trim();
      if (!val || val === c.name) { nameRow.el.value = c.name; return; }
      const old = c.name;
      c.name = val;
      if (chosenDefault === old) chosenDefault = val;
      persist().then((saved) => {
        if (!saved) { c.name = old; if (chosenDefault === val) chosenDefault = old; }
        nameRow.el.value = c.name;
        render();
      });
    });
    nameRow.wrap.style.cssText = "flex:1; min-width:0;";
    top.append(nameRow.wrap);

    const isDefault = chosenDefault === c.name.trim();
    const defBtn = document.createElement("button");
    defBtn.textContent = isDefault ? "★ 默认" : "☆ 设为默认";
    defBtn.title = "新拖出来的节点默认停在这个服务商上";
    defBtn.style.cssText = buttonStyle(false);
    defBtn.disabled = isDefault;
    defBtn.onclick = () => { chosenDefault = c.name.trim(); persist().then(render); };
    top.append(defBtn);

    const delBtn = document.createElement("button");
    delBtn.textContent = "删除";
    delBtn.style.cssText = buttonStyle(false, true);
    delBtn.onclick = async () => {
      const gone = c.name.trim();
      custom.splice(active.index, 1);
      if (chosenDefault === gone) chosenDefault = "";
      active = custom.length ? { type: "custom", index: Math.min(active.index, custom.length - 1) } : null;
      await persist();
      render();
    };
    top.append(delBtn);
    box.append(top);

    const urlRow = rowOfInput("API 地址（chat/completions 完整地址）", c.api_url, "https://example.com/v1/chat/completions");
    urlRow.el.addEventListener("blur", () => {
      const val = urlRow.el.value.trim();
      if (val === c.api_url) return;
      c.api_url = val;
      persist();
    });
    box.append(urlRow.wrap);

    const mid = document.createElement("div");
    mid.style.cssText = "display:flex; flex-direction:column; gap:6px;";

    // 标题行 + 添加按钮
    const modelHead = document.createElement("div");
    modelHead.style.cssText = "display:flex; align-items:center; gap:8px; margin-top:2px;";
    const modelLabel = document.createElement("div");
    modelLabel.textContent = "模型（可以配多个，节点下拉会逐个列出来；★ 是默认）";
    modelLabel.style.cssText = "font-size:11px; opacity:.6; flex:1;";
    const addModel = document.createElement("button");
    addModel.textContent = "＋ 添加模型";
    addModel.style.cssText = buttonStyle(false);
    addModel.onclick = () => {
      (c.models = c.models || []).push("");
      if (!c.default_model) c.default_model = "";
      render();
      const inputs = [...detail.querySelectorAll('input[data-qg-model]')];
      const last = inputs[inputs.length - 1];
      if (last) last.focus();
    };
    modelHead.append(modelLabel, addModel);
    mid.append(modelHead);

    const modelList = document.createElement("div");
    modelList.style.cssText = "display:flex; flex-direction:column; gap:4px;";
    const models = c.models || [];
    if (!models.length) {
      const empty = document.createElement("div");
      empty.textContent = "还没有模型，点右上角添加。至少填一个，视觉节点才能用这家。";
      empty.style.cssText = "font-size:11px; opacity:.45; padding:4px 2px;";
      modelList.appendChild(empty);
    }
    models.forEach((model, mi) => {
      const row = document.createElement("div");
      row.style.cssText = "display:flex; align-items:center; gap:6px;";
      const nameEl = document.createElement("input");
      nameEl.value = model;
      nameEl.placeholder = "glm-4-flash / deepseek-chat";
      nameEl.dataset.qgModel = "1";
      nameEl.style.cssText = fieldStyle + "flex:1; min-width:0;";
      nameEl.addEventListener("blur", () => {
        const val = nameEl.value.trim();
        if (val === (c.models[mi] || "")) return;
        c.models[mi] = val;
        // 原本的默认模型被清空/改名时，默认跟着落到第一项，不能留个悬空的
        if (!c.default_model || !c.models.filter(Boolean).includes(c.default_model)) {
          c.default_model = c.models.filter(Boolean)[0] || "";
        }
        persist();
      });
      const star = document.createElement("button");
      const isDefault = c.default_model === model && !!model;
      star.textContent = isDefault ? "★" : "☆";
      star.title = "设为默认模型（节点上只写服务商名时用它）";
      // 这里刻意不用 disabled：按钮的 disabled 是渲染那一刻算出来的，而
      // 「刚敲完模型名还没 blur / 还没重渲染」时它还是 disabled，click 会被
      // 浏览器直接吞掉——表现就是「点了 ☆ 没反应，默认还留在上一条」。
      // 改成点击时读输入框的实时值，空值再忽略。
      star.style.cssText = [
        "border:none", "background:transparent", "cursor:pointer", "font-size:15px",
        "padding:0 2px", "line-height:1",
        "color:" + (isDefault ? "#e8c35a" : "rgba(200,200,200,.45)"),
      ].join(";");
      star.onclick = () => {
        const val = nameEl.value.trim();
        if (!val) return;
        c.models[mi] = val;      // 顺手把可能还没 blur 的编辑落进数组
        c.default_model = val;
        persist().then(render);
      };
      const del = document.createElement("button");
      del.textContent = "✕";
      del.title = "删除这个模型";
      del.style.cssText = buttonStyle(false, true);
      del.onclick = () => {
        c.models.splice(mi, 1);
        // 删掉的正好是默认模型（或者默认值改过名不在了）就落到第一项，别留悬空值
        if (!c.default_model || !c.models.filter(Boolean).includes(c.default_model)) {
          c.default_model = c.models.filter(Boolean)[0] || "";
        }
        persist().then(render);
      };
      row.append(nameEl, star, del);
      modelList.appendChild(row);
    });
    mid.append(modelList);
    box.append(mid);

    const keyRow = rowOfInput(
      c.has_key ? `API Key（已保存 ${c.masked}，留空不改）` : "API Key",
      "", c.has_key ? "留空则沿用已保存的 Key" : "sk-...", { type: "password" },
    );
    keyRow.el.addEventListener("blur", () => {
      const val = keyRow.el.value.trim();
      if (!val || val.includes(MASK)) return;
      c.newKey = val;
      keyRow.el.value = "";
      persist();
    });
    box.append(keyRow.wrap);

    const testBtn = document.createElement("button");
    testBtn.textContent = "测试连通";
    testBtn.style.cssText = buttonStyle(false);
    const hint = document.createElement("div");
    hint.style.cssText = "font-size:11px; min-height:14px;";
    testBtn.onclick = async () => {
      testBtn.disabled = true;
      testBtn.textContent = "测试中…";
      hint.style.color = "inherit";
      hint.textContent = "";
      try {
        const result = await testProvider({
          id: c.id, name: c.name,
          api_url: c.api_url,
          model: c.default_model || (c.models || []).filter(Boolean)[0] || "",
          api_key: keyRow.el.value.trim() || c.newKey || (c.has_key ? c.masked : ""),
        });
        hint.style.color = result.ok ? "#7ccf8a" : "#e88";
        hint.textContent = result.ok
          ? `✓ ${result.message}：${result.sample || ""}`
          : `✗ ${String(result.message || "").slice(0, 240)}`;
      } catch (error) {
        hint.style.color = "#e88";
        hint.textContent = "✗ " + (error.message || error);
      } finally {
        testBtn.disabled = false;
        testBtn.textContent = "测试连通";
      }
    };
    box.append(testBtn, hint);
    detail.append(box);
  }

  function render() {
    renderTabs();
    renderDetail();
  }

  render();
}

// ---------- 扩展注册 ----------

app.registerExtension({
  name: "QG.Translate",
  async setup() {
    await loadConfig(true);
    // 规则管理器保存后，重新拉一次摘要并把已存在节点的 rule 下拉刷新
    window.addEventListener("qg-rules-changed", () => loadConfig(true));
  },
  settings: [
    {
      id: "QG.Translate.Providers",
      name: "API 服务商",
      category: ["QG 工具", "服务商", "服务商列表"],
      tooltip: "在这里统一配置多个 API（地址 / 模型 / Key），节点上只选服务商",
      type: () => makeSettingsCard(),
      defaultValue: "",
    },
  ],
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name === "QG_PromptTranslate") {
      const created = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function () {
        const result = created ? created.apply(this, arguments) : undefined;
        // 服务列表来自 config.json；这个节点的控件全都保留，不隐藏任何东西
        loadConfig().then(() => syncPromptNode(this));
        return result;
      };
      return;
    }
    if (nodeData.name === "QG_ImageToPrompt") {
      const created = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function () {
        const result = created ? created.apply(this, arguments) : undefined;
        // 视觉列表随设置面板走；控件全保留，不隐藏
        loadConfig().then(() => syncVisionNode(this));
        return result;
      };
      return;
    }
    if (nodeData.name === "QG_PromptOptimize") {
      const created = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function () {
        const result = created ? created.apply(this, arguments) : undefined;
        loadConfig().then(() => syncOptimizeNode(this));
        return result;
      };
      return;
    }
    if (nodeData.name !== "QG_Translate") return;
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = created ? created.apply(this, arguments) : undefined;
      hideWidget(this, "api_url");
      hideWidget(this, "model");
      hideWidget(this, "api_key");
      // api_key 和另外两个不一样：hideWidget 只是不画，widgets_values 里照样
      // 存值 —— 工作流一发给别人，Key 就跟着出去了（2026-11-06 之前的行为）。
      // serialize=false 让它完全跳过序列化：节点上填的 Key 只在本次会话有效，
      // 长期用的那把写到设置面板（config.json），节点执行时自动回退去读。
      const keyWidget = this.widgets?.find((w) => w.name === "api_key");
      if (keyWidget) keyWidget.serialize = false;
      if (this.computeSize) {
        const size = this.computeSize();
        if (size && size[1]) this.setSize?.([this.size[0], size[1]]);
      }
      loadConfig().then(() => syncNode(this));
      return result;
    };
  },
});
