// QG Stream: 图像反推的实时预览 + 翻译失败的节点提示。
//
// 反推一条 300 字的提示词要等十几秒，中途什么都看不到。后端用 stream=true
// 逐块取 SSE，通过 websocket 事件把已经收到的文本推过来，这个文件负责把它
// 画在节点下方——不用点开任何面板，眼睛盯着节点就能看到模型在吐字。
//
// 第二种事件是「提示」（qg-node-notice）：翻译节点失败时会静默把原文传给
// 下游，画布上跟成功一模一样，区别只在控制台一行 print。这类失败必须摆到
// 节点脸上，否则用户只会看到「怎么都是输出原文」。
//
// 为什么用 canvas 画而不是塞一个 DOM 覆盖层：
//   DOM 要跟着节点拖动、缩放、折叠、切子图一次次改坐标，这些状态每个
//   ComfyUI 版本都在变。onDrawForeground 是节点绘制生命周期里稳定的一环，
//   画在节点的局部坐标系里，节点怎么动都自动跟着。
//
// 气泡只在执行期间存在：反推气泡 done 之后保留 6 秒，提示气泡保留 15 秒
// （报错要留够时间看清）。
//
// 标题不写死：后端在事件里带 label（「反推」/「优化」），拼成「优化中…」
// 「优化完成」。没有 label 时按「反推」处理，兼容老版本的事件。

import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const EVENT = "qg-vlm-stream";
const NOTICE_EVENT = "qg-node-notice";
const KEEP_MS = 6000;
const NOTICE_KEEP_MS = 15000;
const MAX_LINES = 10;
const MAX_CHARS = 800;

/** nodeId -> {text, done, lines, cachedText, timer} */
const STREAMS = new Map();
/** nodeId -> {text, kind, lines, cachedText, timer} */
const NOTICES = new Map();

function wrapLines(ctx, text, maxWidth) {
  const out = [];
  for (const para of String(text).split("\n")) {
    if (!para) { out.push(""); continue; }
    let line = "";
    for (const ch of para) {
      const test = line + ch;
      if (line && ctx.measureText(test).width > maxWidth) {
        out.push(line);
        line = ch;
      } else {
        line = test;
      }
    }
    out.push(line);
  }
  return out;
}

/**
 * 在 top 处画一个气泡，返回它占掉的高度。
 * 样式由 stroke / titleColor 决定，正文统一等宽字体好读代码味的报错。
 */
function drawBubble(ctx, top, width, title, titleColor, stroke, lines) {
  const pad = 9;
  const lineHeight = 15;
  const height = 26 + lines.length * lineHeight + pad;

  ctx.save();
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(0, top, width, height, 8);
  else ctx.rect(0, top, width, height);
  ctx.fillStyle = "rgba(12,16,26,.88)";
  ctx.fill();
  ctx.lineWidth = 1;
  ctx.strokeStyle = stroke;
  ctx.stroke();

  ctx.font = "11px sans-serif";
  ctx.fillStyle = titleColor;
  ctx.fillText(title, pad, top + 15);

  ctx.font = "12px ui-monospace, Consolas, monospace";
  ctx.fillStyle = "#dfe7f5";
  lines.forEach((line, i) => {
    ctx.fillText(line, pad, top + 32 + i * lineHeight);
  });
  ctx.restore();
  return height + 6;
}

function paint(node, ctx) {
  const key = String(node.id);
  const stream = STREAMS.get(key);
  const notice = NOTICES.get(key);
  if (!stream && !notice) return;

  const width = Math.max(200, node.size[0]);
  const pad = 9;
  let top = node.size[1] + 6;

  if (stream && stream.text) {
    ctx.save();
    ctx.font = "12px ui-monospace, Consolas, monospace";
    if (stream.cachedText !== stream.text) {
      const tail = stream.text.length > MAX_CHARS
        ? "…" + stream.text.slice(-MAX_CHARS) : stream.text;
      stream.lines = wrapLines(ctx, tail, width - pad * 2);
      stream.cachedText = stream.text;
    }
    ctx.restore();
    const shown = (stream.lines || []).slice(-MAX_LINES);
    const label = stream.label || "反推";
    top += drawBubble(
      ctx, top, width,
      stream.done ? `${label}完成` : `${label}中…`,
      stream.done ? "#9fe0b5" : "#9dc4ff",
      stream.done ? "rgba(120,200,150,.75)" : "rgba(110,170,255,.85)",
      shown,
    );
  }

  if (notice && notice.text) {
    ctx.save();
    ctx.font = "12px ui-monospace, Consolas, monospace";
    if (notice.cachedText !== notice.text) {
      notice.lines = wrapLines(ctx, notice.text, width - pad * 2);
      notice.cachedText = notice.text;
    }
    ctx.restore();
    const shown = (notice.lines || []).slice(-MAX_LINES);
    drawBubble(
      ctx, top, width,
      notice.title || (notice.kind === "error" ? "⚠ 出错（已原样输出）" : "提示"),
      notice.kind === "error" ? "#ffb3b3" : "#ffe1a3",
      notice.kind === "error"
        ? "rgba(235,120,120,.9)" : "rgba(232,195,90,.85)",
      shown,
    );
  }
}

function hookNode(node) {
  if (node.__qgStreamHooked) return;
  node.__qgStreamHooked = true;
  const previous = node.onDrawForeground;
  node.onDrawForeground = function (ctx) {
    if (previous) previous.call(this, ctx);
    try {
      paint(this, ctx);
    } catch (error) {
      console.warn("[QG-Stream] 预览绘制失败:", error);
    }
  };
}

function nodeById(key) {
  return app.graph?.getNodeById?.(Number(key))
    || app.graph?.getNodeById?.(key);
}

/* Vue 节点渲染（Nodes 2.0）下 onDrawForeground 不再被调用，气泡整片消失。
 * timer.js 在画布最上层开了一张读数层，这里把气泡也挂上去：painter 收到的
 * ctx 已经套好画布的平移与缩放，只需要自己 translate 到节点原点。 */
function paintAllBubbles(ctx) {
  if (!STREAMS.size && !NOTICES.size) return;
  const keys = new Set([...STREAMS.keys(), ...NOTICES.keys()]);
  for (const key of keys) {
    const node = nodeById(key);
    if (!node || node.flags?.collapsed) continue;
    ctx.save();
    ctx.translate(node.pos[0], node.pos[1]);
    try {
      paint(node, ctx);
    } catch (error) {
      console.warn("[QG-Stream] Vue 气泡绘制失败:", error);
    }
    ctx.restore();
  }
}

app.registerExtension({
  name: "QG.Stream",
  setup() {
    // timer.js 的 Vue 读数层（加载顺序不保证，所以放在 setup 里注册）
    window.__QG_VUE_LAYER__?.add(paintAllBubbles);

    api.addEventListener(EVENT, (event) => {
      const detail = event.detail || {};
      const key = String(detail.node || "");
      if (!key) return;
      const node = nodeById(key);
      if (!node) return;

      let st = STREAMS.get(key);
      if (!st) {
        st = { text: "", done: false, label: "", lines: null, cachedText: "", timer: null };
        STREAMS.set(key, st);
      }
      st.text = String(detail.text || "");
      st.done = !!detail.done;
      st.label = String(detail.label || "反推");
      hookNode(node);
      node.setDirtyCanvas?.(true, false);

      if (st.done) {
        clearTimeout(st.timer);
        st.timer = setTimeout(() => {
          // 同一个节点可能已经开始了新一次运行（跑完紧接着再跑很常见，
          // node id 不变）。只有「还停在这份状态」才清，否则会把新一轮
          // 正在吐字的气泡一起抹掉。下面 NOTICES 一直是这么做的，这里
          // 早先漏了同一个判断。
          if (STREAMS.get(key) === st) {
            STREAMS.delete(key);
            node.setDirtyCanvas?.(true, false);
          }
        }, KEEP_MS);
      }
    });

    api.addEventListener(NOTICE_EVENT, (event) => {
      const detail = event.detail || {};
      const key = String(detail.node || "");
      if (!key) return;
      const node = nodeById(key);
      if (!node) return;

      const st = {
        text: String(detail.text || ""),
        kind: String(detail.kind || "error"),
        title: String(detail.title || ""),
        lines: null,
        cachedText: "",
        timer: null,
      };
      const old = NOTICES.get(key);
      if (old) clearTimeout(old.timer);
      NOTICES.set(key, st);
      hookNode(node);
      node.setDirtyCanvas?.(true, false);

      st.timer = setTimeout(() => {
        if (NOTICES.get(key) === st) {
          NOTICES.delete(key);
          node.setDirtyCanvas?.(true, false);
        }
      }, NOTICE_KEEP_MS);
    });
  },
});
