// QG Rules: 提示词规则库的管理界面。
//
// 规则正文不写死在 Python 里，存在插件目录的 rules.json。这个文件负责：
//   1. 设置面板里一张卡片（显示几组几条、当前激活哪条），点「规则管理器…」开对话框；
//   2. 对话框按用途分页签：提示词优化 / 图像反推 / 视频反推 / 翻译规则；
//   3. 每组只能激活一条（面板上那列单选圆点），作用是新节点的默认值 +
//      规则被删时的兜底；
//   4. 增删改都在内存里改，点「保存」才落盘——取消就当没动过。
//
// 交互参考 Prompt-Assistant 的规则管理器，代码独立实现。

import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const API_BASE = "/qg_rules";

// 后端返回的全量数据（带正文）
let STATE = {
  order: [],
  labels: {},
  hints: {},
  groups: {},
  tab: "image",
  dirty: false,
};

const C = {
  panel: "var(--comfy-menu-bg,#1e1e24)",
  field: "var(--comfy-input-bg,#1b1b22)",
  text: "var(--fg-color,#ddd)",
  line: "var(--border-color,#45455a)",
  blue: "#3b82f6",
  green: "#5fbf72",
  red: "#e88",
};

const FIELD = [
  "width:100%", "box-sizing:border-box", "padding:5px 8px", "font-size:12px",
  "border-radius:6px", "border:1px solid " + C.line,
  "background:" + C.field, "color:" + C.text,
].join(";");

function button(kind) {
  const parts = [
    "padding:5px 12px", "border-radius:7px", "font-size:12px", "cursor:pointer",
    "border:1px solid " + C.line, "background:" + C.field, "color:" + C.text,
  ];
  if (kind === "primary") parts.push("background:" + C.blue, "border-color:" + C.blue, "color:#fff", "font-weight:600");
  if (kind === "danger") parts.push("color:" + C.red, "border-color:#a55");
  if (kind === "blank") parts.push("background:transparent", "padding:2px 7px");
  return parts.join(";");
}

// ---------- 数据 ----------

async function loadRules() {
  try {
    const res = await api.fetchApi(API_BASE);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    if (data.ok !== false) applyPayload(data);
  } catch (error) {
    console.warn("[QG-Rules] 读取规则失败:", error);
  }
  return STATE;
}

function applyPayload(data) {
  STATE.order = Array.isArray(data.order) && data.order.length
    ? data.order : Object.keys(data.groups || {});
  STATE.labels = data.labels || {};
  STATE.hints = data.hints || {};
  // 深拷贝：对话框里的改动要能整体丢弃
  STATE.groups = JSON.parse(JSON.stringify(data.groups || {}));
  if (!STATE.order.includes(STATE.tab)) STATE.tab = STATE.order[0] || "image";
  STATE.dirty = false;
}

async function postJSON(url, payload) {
  const res = await api.fetchApi(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    throw new Error(data.message || ("HTTP " + res.status));
  }
  return data;
}

/** 保存前自查：空名、同组重名、跨组重名都在这里拦掉，省一次往返。 */
function validate() {
  const seen = new Map();
  for (const key of STATE.order) {
    for (const item of STATE.groups[key] || []) {
      const name = String(item.name || "").trim();
      if (!name) {
        return `「${STATE.labels[key] || key}」里有规则还没起名字`;
      }
      if (seen.has(name)) {
        const where = STATE.labels[seen.get(name)] || seen.get(name);
        const here = STATE.labels[key] || key;
        return seen.get(name) === key
          ? `「${here}」里有两个都叫「${name}」的规则`
          : `「${name}」在「${where}」和「${here}」里重名了，名字不能跨组重复`;
      }
      seen.set(name, key);
    }
  }
  return "";
}

// ---------- 对话框 ----------

/** 当前打开的设置对话框（reka-ui Dialog）。找不到就返回 null，调用方退回 body。
 *
 *  管理器必须挂在这层里面：设置面板带 FocusScope 焦点锁，焦点一旦落到
 *  对话框外就被抢回搜索框，弹层里的输入框和文本框会「点进去打不了字」。
 */
function settingsDialogHost() {
  return document.querySelector('[role="dialog"][data-reka-dialog-content]')
    || document.querySelector('[role="dialog"]');
}

function openManager() {
  const overlay = document.createElement("div");
  overlay.style.cssText = [
    "position:fixed", "inset:0", "z-index:2147483647", "pointer-events:auto",
    "display:flex", "align-items:center", "justify-content:center",
    "background:rgba(0,0,0,.55)", "font-family:inherit",
  ].join(";");

  const card = document.createElement("div");
  // min-height 是给编辑弹层留空间用的：卡片高度默认由行数决定，只有三四条
  // 规则时整卡才 460px，弹层里 84% 分给文本框就只剩五行。给个下限，列表区
  // （body 是 flex:1）自然把卡片撑到这么高，弹层也跟着变大。
  card.style.cssText = [
    "position:relative", "width:min(860px,95vw)", "max-height:86vh",
    "min-height:min(560px,86vh)",
    "display:flex", "flex-direction:column", "border-radius:12px", "overflow:hidden",
    "background:" + C.panel, "color:" + C.text,
    "border:1px solid " + C.line, "box-shadow:0 16px 48px rgba(0,0,0,.5)",
  ].join(";");

  // 头部
  const head = document.createElement("div");
  head.style.cssText = [
    "display:flex", "align-items:center", "gap:10px",
    "padding:12px 16px", "border-bottom:1px solid " + C.line,
  ].join(";");
  head.innerHTML = '<b style="font-size:14px;">规则管理器</b>'
    + '<span style="font-size:11px;opacity:.55;">'
    + '节点下拉读的就是这里 · 改完点保存，不用重启</span>';
  const headSpacer = document.createElement("span");
  headSpacer.style.cssText = "flex:1;";
  const close = document.createElement("button");
  close.textContent = "×";
  close.style.cssText = "border:none;background:transparent;color:inherit;font-size:20px;cursor:pointer;line-height:1;";
  close.onclick = () => overlay.remove();
  head.append(headSpacer, close);

  // 页签条
  const tabBar = document.createElement("div");
  tabBar.style.cssText = [
    "display:flex", "flex-wrap:wrap", "align-items:center", "gap:8px",
    "padding:12px 16px 0",
  ].join(";");

  // 表格区
  const body = document.createElement("div");
  body.style.cssText = "padding:12px 16px; overflow-y:auto; flex:1; min-height:240px;";

  // 底部
  const foot = document.createElement("div");
  foot.style.cssText = [
    "display:flex", "align-items:center", "gap:8px", "padding:10px 16px",
    "border-top:1px solid " + C.line,
  ].join(";");
  const status = document.createElement("span");
  status.style.cssText = "flex:1; font-size:11.5px; opacity:.75;";
  const resetBtn = document.createElement("button");
  resetBtn.textContent = "恢复内置";
  resetBtn.style.cssText = button("danger");
  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = "取消";
  cancelBtn.style.cssText = button();
  const saveBtn = document.createElement("button");
  saveBtn.textContent = "保存";
  saveBtn.style.cssText = button("primary");
  foot.append(status, resetBtn, cancelBtn, saveBtn);

  card.append(head, tabBar, body, foot);
  overlay.appendChild(card);
  // 与 QG 服务商面板同样的处理：让 ComfyUI 的 reka-ui 把这层当成更顶层的
  // 弹层，否则点页签 / 点输入框会被判成「点外部」而关掉身后的设置面板。
  overlay.dataset.dismissableLayer = "";
  for (const type of ["pointerdown", "mousedown", "click", "focusin"]) {
    overlay.addEventListener(type, (e) => e.stopPropagation());
  }
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) overlay.remove(); });
  // 挂进设置对话框里而不是 body，理由见 settingsDialogHost 的注释。
  (settingsDialogHost() || document.body).appendChild(overlay);

  function say(text, tone) {
    status.style.color = tone === "error" ? C.red : (tone === "ok" ? C.green : "inherit");
    status.textContent = text || "";
  }

  function markDirty() {
    STATE.dirty = true;
    saveBtn.textContent = "保存 •";
    say("有未保存的改动");
  }

  // ---- 编辑弹层 ----
  function editRule(group, index, focusName) {
    const items = STATE.groups[group] || [];
    const item = items[index];
    if (!item) return;

    const mask = document.createElement("div");
    mask.style.cssText = [
      "position:absolute", "inset:0", "z-index:5", "display:flex",
      "align-items:center", "justify-content:center",
      "background:rgba(0,0,0,.5)",
    ].join(";");
    const box = document.createElement("div");
    // 必须给确定高度而不是只给 max-height：flex 子项（下面是 flex:1 的文本框）
    // 在容器没有确定高度时不会收缩，min-height 又会把它顶到 300px，
    // 结果整个弹层撑出卡片、底部的「确定」被 card 的 overflow:hidden 裁掉。
    box.style.cssText = [
      "width:min(660px,92%)", "height:min(620px,90%)", "display:flex",
      "flex-direction:column", "gap:10px", "padding:16px", "border-radius:10px",
      "background:" + C.panel, "border:1px solid " + C.line,
      "box-shadow:0 12px 32px rgba(0,0,0,.45)", "overflow:hidden",
    ].join(";");

    const title = document.createElement("div");
    title.style.cssText = "display:flex; align-items:center; gap:8px; flex:0 0 auto;";
    title.innerHTML = '<b style="font-size:13px;">编辑规则</b>'
      + `<span style="font-size:11px;opacity:.55;"> · ${STATE.labels[group] || group}</span>`;
    const titleSpacer = document.createElement("span");
    titleSpacer.style.cssText = "flex:1;";
    const closeX = document.createElement("button");
    closeX.textContent = "×";
    closeX.title = "关闭";
    closeX.style.cssText = "border:none;background:transparent;color:inherit;"
      + "font-size:18px;line-height:1;cursor:pointer;padding:0 2px;opacity:.6;";
    closeX.onclick = () => mask.remove();
    title.append(titleSpacer, closeX);

    const nameLabel = document.createElement("div");
    nameLabel.textContent = "规则名称（节点下拉里显示这串字；改名后旧名会自动记成别名，老工作流仍能命中）";
    nameLabel.style.cssText = "font-size:11px;opacity:.6;flex:0 0 auto;";
    const nameInput = document.createElement("input");
    nameInput.value = item.name || "";
    nameInput.placeholder = "例如 像素级描述";
    nameInput.style.cssText = FIELD + "flex:0 0 auto;";

    const bodyLabel = document.createElement("div");
    bodyLabel.textContent = "规则内容（写给模型看的指令：观察顺序、成文格式、禁止项）";
    bodyLabel.style.cssText = "font-size:11px;opacity:.6;flex:0 0 auto;";
    const area = document.createElement("textarea");
    area.value = item.content || "";
    area.placeholder = "你是一名 AI 生图提示词工程师……";
    // min-height:0 是 flex 收缩的关键：文本域默认 min-height:auto，会被内容
    // 顶到几百像素，把下面的按钮行挤出弹层。resize 也去掉，允许手动拖拽就
    // 又回到了「拖大以后按钮看不见」的老问题。
    area.style.cssText = [
      FIELD, "flex:1 1 auto", "min-height:0", "resize:none", "overflow:auto",
      "font-family:ui-monospace,Consolas,monospace", "line-height:1.6",
    ].join(";");

    const row = document.createElement("div");
    row.style.cssText = "display:flex; justify-content:flex-end; gap:8px; flex:0 0 auto;";
    const cancel = document.createElement("button");
    cancel.textContent = "取消";
    cancel.style.cssText = button();
    cancel.onclick = () => mask.remove();
    const ok = document.createElement("button");
    ok.textContent = "确定";
    ok.style.cssText = button("primary");
    ok.onclick = () => {
      const name = nameInput.value.trim();
      if (!name) { nameInput.focus(); return; }
      item.name = name.slice(0, 60);
      item.content = area.value.slice(0, 20000);
      mask.remove();
      markDirty();
      render();
    };
    row.append(cancel, ok);
    box.append(title, nameLabel, nameInput, bodyLabel, area, row);
    mask.appendChild(box);
    card.appendChild(mask);
    // 编辑已有规则时直接落光标到正文开头（规则动辄几千字，光标落末尾会
    // 直接滚到结尾，看起来像「内容缺了前几段」）；新建时先让用户改名字。
    // 设置面板（reka-ui）的焦点锁会把弹层外的焦点拽回搜索框，同步调
    // focus() 抢不过；先把它 blur 掉，至少用户在弹层里打字不会输进搜索框。
    setTimeout(() => {
      const active = document.activeElement;
      if (active && active !== document.body && !mask.contains(active)) active.blur();
      const target = focusName ? nameInput : area;
      target.focus();
      if (focusName) {
        nameInput.select();
      } else {
        area.setSelectionRange(0, 0);
        area.scrollTop = 0;
      }
    }, 40);
  }

  // ---- 渲染 ----
  function renderTabs() {
    tabBar.innerHTML = "";
    for (const key of STATE.order) {
      const items = STATE.groups[key] || [];
      const active = STATE.tab === key;
      const el = document.createElement("button");
      el.style.cssText = [
        "padding:6px 12px", "border-radius:6px 6px 0 0", "font-size:12px", "cursor:pointer",
        "border:1px solid " + (active ? C.line : "transparent"), "border-bottom:none",
        "background:" + (active ? C.field : "transparent"),
        "color:" + (active ? C.text : "rgba(200,200,200,.55)"),
      ].join(";");
      el.textContent = (STATE.labels[key] || key) + (items.length ? `  ${items.length}` : "");
      el.onclick = () => { STATE.tab = key; render(); };
      tabBar.appendChild(el);
    }
    const addBtn = document.createElement("button");
    addBtn.textContent = "＋ 添加规则";
    addBtn.style.cssText = button();
    addBtn.style.marginLeft = "auto";
    addBtn.onclick = () => {
      const list = STATE.groups[STATE.tab] || (STATE.groups[STATE.tab] = []);
      let n = list.length + 1;
      let name = `新规则 ${n}`;
      while (list.some((r) => r.name === name)) name = `新规则 ${++n}`;
      list.push({ name, content: "", enabled: list.length === 0 });
      markDirty();
      render();
      editRule(STATE.tab, list.length - 1, true);
    };
    tabBar.appendChild(addBtn);
  }

  function renderTable() {
    body.innerHTML = "";
    const group = STATE.tab;
    const items = STATE.groups[group] || [];

    const hint = document.createElement("div");
    hint.style.cssText = "font-size:11.5px; opacity:.6; margin-bottom:10px;";
    hint.textContent = STATE.hints[group] || "";
    body.appendChild(hint);

    if (!items.length) {
      const empty = document.createElement("div");
      empty.style.cssText = "font-size:12px; opacity:.5; padding:24px 0; text-align:center;";
      empty.textContent = "这一组还没有规则，点右上角「＋ 添加规则」新建一条。";
      body.appendChild(empty);
      return;
    }

    const table = document.createElement("div");
    table.style.cssText = "display:flex; flex-direction:column; gap:2px;";

    const headRow = document.createElement("div");
    headRow.style.cssText = [
      "display:grid", "grid-template-columns:52px 1fr 1.4fr 62px", "gap:8px",
      "padding:4px 6px", "font-size:11px", "opacity:.5",
      "border-bottom:1px solid " + C.line,
    ].join(";");
    for (const text of ["状态", "规则名称", "规则内容", "操作"]) {
      const cell = document.createElement("div");
      cell.textContent = text;
      headRow.appendChild(cell);
    }
    table.appendChild(headRow);

    items.forEach((item, index) => {
      const row = document.createElement("div");
      row.style.cssText = [
        "display:grid", "grid-template-columns:52px 1fr 1.4fr 62px", "gap:8px",
        "align-items:center", "padding:6px", "border-radius:6px", "font-size:12px",
      ].join(";");
      row.addEventListener("mouseenter", () => { row.style.background = "rgba(255,255,255,.05)"; });
      row.addEventListener("mouseleave", () => { row.style.background = "transparent"; });

      // 状态：每组单选，点一下把其它条熄灭
      const stateCell = document.createElement("div");
      const dot = document.createElement("button");
      dot.textContent = item.enabled ? "✓" : "○";
      dot.title = "设为该组的激活规则（新节点默认用它；规则被删时也用它兜底）";
      dot.style.cssText = [
        "border:none", "background:transparent", "cursor:pointer",
        "font-size:15px", "line-height:1", "padding:0 0 0 4px",
        "color:" + (item.enabled ? C.green : "rgba(200,200,200,.35)"),
      ].join(";");
      dot.onclick = () => {
        items.forEach((r, i) => { r.enabled = i === index; });
        markDirty();
        render();
      };
      stateCell.appendChild(dot);

      const nameCell = document.createElement("div");
      nameCell.style.cssText = "overflow:hidden; text-overflow:ellipsis; white-space:nowrap;";
      const aliases = Array.isArray(item.aliases) ? item.aliases : [];
      nameCell.textContent = item.name || "（未命名）";
      if (aliases.length) {
        const tag = document.createElement("span");
        tag.textContent = ` +${aliases.length} 个旧名`;
        tag.title = "改过名：这些旧名字仍然能找到这条规则\n" + aliases.join("\n");
        tag.style.cssText = "font-size:10.5px; opacity:.45; margin-left:4px;";
        nameCell.appendChild(tag);
      }
      nameCell.title = item.name || "";

      const preview = String(item.content || "").replace(/\s+/g, " ").trim();
      const contentCell = document.createElement("div");
      contentCell.textContent = preview.slice(0, 46) + (preview.length > 46 ? "…" : "")
        || "（空规则，模型会自由发挥）";
      contentCell.style.cssText = "overflow:hidden; text-overflow:ellipsis; white-space:nowrap; opacity:.7;";
      contentCell.title = preview.slice(0, 400);

      const ops = document.createElement("div");
      ops.style.cssText = "display:flex; gap:4px; justify-content:flex-end;";
      const editBtn = document.createElement("button");
      editBtn.textContent = "✎";
      editBtn.title = "编辑这条规则";
      editBtn.style.cssText = button("blank");
      editBtn.onclick = () => editRule(group, index);
      const delBtn = document.createElement("button");
      delBtn.textContent = "✕";
      delBtn.title = "删除（保存后才真正删掉，点取消可还原）";
      delBtn.style.cssText = button("blank");
      delBtn.onclick = () => {
        items.splice(index, 1);
        if (items.length && !items.some((r) => r.enabled)) items[0].enabled = true;
        markDirty();
        render();
      };
      ops.append(editBtn, delBtn);

      row.append(stateCell, nameCell, contentCell, ops);
      table.appendChild(row);
    });

    body.appendChild(table);
  }

  function render() {
    renderTabs();
    renderTable();
    if (!STATE.dirty) {
      saveBtn.textContent = "保存";
      status.textContent = "";
    }
  }

  // ---- 动作 ----
  saveBtn.onclick = async () => {
    const problem = validate();
    if (problem) { say(problem, "error"); return; }
    saveBtn.disabled = true;
    saveBtn.textContent = "保存中…";
    try {
      const data = await postJSON(API_BASE, { groups: STATE.groups });
      applyPayload(data);
      render();
      say("已保存 ✓ 节点下拉已同步", "ok");
      window.dispatchEvent(new Event("qg-rules-changed"));
    } catch (error) {
      say("保存失败：" + (error.message || error), "error");
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = "保存";
    }
  };

  cancelBtn.onclick = async () => {
    await loadRules();
    render();
    say("已放弃改动");
  };

  resetBtn.onclick = async () => {
    if (!window.confirm("恢复内置规则会覆盖你现在所有改动（包括自己加的规则），确定吗？")) return;
    try {
      const data = await postJSON(API_BASE + "/reset");
      applyPayload(data);
      render();
      say("已恢复内置规则", "ok");
      window.dispatchEvent(new Event("qg-rules-changed"));
    } catch (error) {
      say("恢复失败：" + (error.message || error), "error");
    }
  };

  render();
  loadRules().then(render);
  return overlay;
}

// ---------- 设置面板卡片 ----------

function makeSettingsCard() {
  const row = document.createElement("div");
  row.style.cssText = "display:flex; align-items:center; gap:10px; flex-wrap:wrap;";

  const summary = document.createElement("span");
  summary.style.cssText = "font-size:12px; opacity:.75;";

  const button = document.createElement("button");
  button.textContent = "规则管理器…";
  button.style.cssText = [
    "padding:5px 12px", "border-radius:7px", "cursor:pointer", "font-size:12px",
    "border:1px solid " + C.line, "background:" + C.field, "color:" + C.text,
  ].join(";");
  button.onclick = () => openManager();

  const paint = () => {
    const order = STATE.order.length ? STATE.order : ["optimize", "image", "video", "translate"];
    let total = 0;
    let activeName = "";
    for (const key of order) {
      const items = STATE.groups[key] || [];
      total += items.length;
      if (!activeName && key === "image") {
        const lit = items.find((r) => r.enabled);
        if (lit) activeName = lit.name;
      }
    }
    summary.textContent = total
      ? `${order.length} 组 · ${total} 条规则 · 图像反推默认：${activeName || "（未选）"}`
      : "还没读到规则，点右边打开管理器";
  };

  row.append(summary, button);
  paint();
  loadRules().then(paint);
  window.addEventListener("qg-rules-changed", () => loadRules().then(paint));
  return row;
}

// ---------- 扩展注册 ----------

app.registerExtension({
  name: "QG.Rules",
  settings: [
    {
      id: "QG.Rules.Prompts",
      name: "提示词规则",
      category: ["QG 工具", "规则", "提示词规则"],
      tooltip: "图像反推 / 视频反推 / 翻译规则都在这里改，节点下拉读的就是这份清单",
      type: () => makeSettingsCard(),
      defaultValue: "",
    },
  ],
});
