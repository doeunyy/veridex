"use strict";

// Veridex chat client: POST /api/chat/stream and read Server-Sent Events with fetch().
// Events: route, trace, token, citations, done, error.

const $ = (selector, root = document) => root.querySelector(selector);
const messages = $("#messages");
const form = $("#composer");
const input = $("#query");
const sendButton = $("#send");
const SESSION_KEY = "veridex.session";
const CHUNK_ID = /\b([a-z0-9_]+_\d{4}):p(\d+):c(\d+)\b/g;
const PAGE_REF = /\[([a-z0-9_]+_\d{4}) p\.(\d+)\]/g;

function newSessionId() {
  return (crypto.randomUUID && crypto.randomUUID()) || `s-${Date.now()}-${Math.random()}`;
}

function sessionId() {
  let id = null;
  try { id = localStorage.getItem(SESSION_KEY); } catch (_) { /* storage unavailable */ }
  if (!id) {
    id = newSessionId();
    try { localStorage.setItem(SESSION_KEY, id); } catch (_) { /* ignore */ }
  }
  return id;
}

function showSession() {
  $("#session-label").textContent = `session ${sessionId().slice(0, 8)}`;
}

// ---------- Minimal, escaping Markdown renderer ----------

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function inline(text) {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return html;
}

function renderMarkdown(source) {
  const lines = source.replace(/\r/g, "").split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      const code = [];
      i += 1;
      while (i < lines.length && !lines[i].startsWith("```")) code.push(lines[i++]);
      i += 1;
      out.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      out.push(`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`);
      i += 1;
      continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { out.push("<hr>"); i += 1; continue; }
    if (line.trim().startsWith("|") && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1])) {
      const cells = (row) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(cells(lines[i++]));
      out.push(
        `<table><thead><tr>${head.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>` +
          rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("") +
          "</tbody></table>",
      );
      continue;
    }
    const listItem = /^\s*([-*]|\d+\.)\s+(.*)$/;
    if (listItem.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      while (i < lines.length && listItem.test(lines[i])) {
        items.push(`<li>${inline(lines[i].match(listItem)[2])}</li>`);
        i += 1;
      }
      out.push(ordered ? `<ol>${items.join("")}</ol>` : `<ul>${items.join("")}</ul>`);
      continue;
    }
    if (!line.trim()) { i += 1; continue; }
    const paragraph = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*([-*]|\d+\.)\s|\s*\|)/.test(lines[i])) {
      paragraph.push(lines[i++]);
    }
    if (!paragraph.length) paragraph.push(lines[i++]);
    out.push(`<p>${inline(paragraph.join(" "))}</p>`);
  }
  return out.join("\n");
}

// Replace chunk / page references with chips linking to the turn's source list.
function linkCitations(html, citations, turnId) {
  const index = new Map(citations.map((c, n) => [c.id, n + 1]));
  const chip = (id, label) => {
    const n = index.get(id);
    return n
      ? `<a class="cite" href="#${turnId}-src-${n}" title="${escapeHtml(id)}">${n} · ${escapeHtml(label)}</a>`
      : `<span class="cite unverified" title="Not retrieved by a tool in this turn">${escapeHtml(label)}</span>`;
  };
  return html
    .replace(CHUNK_ID, (id, doc, page) => chip(id, `${doc} p.${page}`))
    .replace(PAGE_REF, (_, doc, page) => chip(`${doc} p.${page}`, `${doc} p.${page}`));
}

// ---------- Rendering a turn ----------

let turnCounter = 0;

function addTurn(question) {
  $("#empty")?.remove();
  const node = $("#turn-template").content.firstElementChild.cloneNode(true);
  node.id = `turn-${++turnCounter}`;
  $(".bubble.user", node).textContent = question;
  messages.appendChild(node);
  node.scrollIntoView({ block: "end" });
  return node;
}

function renderRoute(turn, decision) {
  const chip = document.createElement("span");
  chip.className = `route ${decision.provider}`;
  chip.title = `${decision.reason}\nsignals: ${JSON.stringify(decision.signals)}`;
  chip.innerHTML =
    `<span class="agent">${escapeHtml(decision.agent)}</span>→` +
    `<span class="provider">${escapeHtml(decision.model)}</span>` +
    `<span class="muted">${escapeHtml(decision.dimension)}:${escapeHtml(decision.rule)}</span>` +
    (decision.fallback_from ? `<span class="fallback">fallback from ${escapeHtml(decision.fallback_from)}</span>` : "");
  $(".routes", turn).appendChild(chip);
}

function describeEvent(event) {
  if (event.node === "supervisor") {
    const target = event.next === "finish" ? "finish" : `→ ${event.next}`;
    return `${target}<span class="reason"> — ${escapeHtml(event.reason || "")}</span>`;
  }
  if (event.node === "finalize") return `answer assembled (${escapeHtml(event.mode)}, ${event.citations} citations)`;
  const status = event.status === "ok" ? "" : `<span class="tag error">${escapeHtml(event.error || event.status)}</span>`;
  const tools = (event.tools || []).map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("");
  return `${status}${tools}<span class="reason"> ${event.sources || 0} sources</span>`;
}

function renderTrace(turn, event) {
  const item = document.createElement("li");
  const ms = event.duration_ms != null ? ` <span class="muted">${event.duration_ms} ms</span>` : "";
  item.innerHTML = `<span class="node">${escapeHtml(event.node)}</span> ${describeEvent(event)}${ms}`;
  $(".trace", turn).appendChild(item);
  const status = event.node === "supervisor" && event.next !== "finish"
    ? `${event.next} agent working…`
    : event.node === "finalize" ? "Finishing…" : "Supervisor deciding…";
  $(".status-text", turn).textContent = status;
}

function renderSources(turn, citations) {
  const list = $(".sources", turn);
  list.innerHTML = "";
  citations.forEach((c, n) => {
    const item = document.createElement("li");
    item.id = `${turn.id}-src-${n + 1}`;
    const where = c.kind === "web" ? "web" : `${c.document_id} · p.${c.page}`;
    const url = c.kind === "web" ? c.url : `${c.url}`;
    item.innerHTML =
      `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(c.title)}</a> ` +
      `<span class="muted">${escapeHtml(where)}${c.kind === "corpus" ? ` · ${escapeHtml(c.id)}` : ""}</span>` +
      (c.snippet ? `<span class="snippet">${escapeHtml(c.snippet)}…</span>` : "");
    list.appendChild(item);
  });
  $(".sources-box", turn).hidden = citations.length === 0;
  $(".sources-box", turn).open = citations.length > 0;
}

// ---------- SSE over fetch ----------

async function* readEvents(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      let event = "message";
      const data = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (data.length) yield { event, data: JSON.parse(data.join("\n")) };
    }
  }
}

async function ask(question) {
  const turn = addTurn(question);
  const answer = $(".answer", turn);
  let draft = "";
  let draftNode = null;
  let frame = 0;
  const render = () => {
    frame = 0;
    answer.innerHTML = renderMarkdown(draft);
    turn.scrollIntoView({ block: "end" });
  };

  sendButton.disabled = true;
  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ query: question, session_id: sessionId() }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `Request failed (${response.status}).`);
    }
    for await (const { event, data } of readEvents(response)) {
      if (event === "route") renderRoute(turn, data);
      else if (event === "trace") renderTrace(turn, data);
      else if (event === "token") {
        // A new answering node restarts the draft; the final text arrives with `done`.
        if (draftNode !== data.node) { draft = ""; draftNode = data.node; }
        draft += data.text;
        answer.classList.add("streaming");
        $(".status", turn).hidden = true;
        if (!frame) frame = requestAnimationFrame(render);
      } else if (event === "citations") renderSources(turn, data.citations);
      else if (event === "done") {
        if (frame) cancelAnimationFrame(frame); // a queued draft render must not replace the final text
        frame = 0;
        answer.classList.remove("streaming");
        answer.innerHTML = linkCitations(renderMarkdown(data.response), data.citations, turn.id);
        const ttft = data.ttft_ms != null ? `first token ${(data.ttft_ms / 1000).toFixed(1)} s · ` : "";
        $(".meta", turn).textContent =
          `${ttft}total ${(data.total_ms / 1000).toFixed(1)} s · ${data.history_turns} earlier turns in context`;
      } else if (event === "error") throw new Error(data.message);
    }
  } catch (error) {
    answer.classList.remove("streaming");
    answer.classList.add("error");
    answer.textContent = error.message || "Request failed.";
  } finally {
    $(".status", turn).hidden = true;
    sendButton.disabled = false;
    input.focus();
  }
}

// ---------- Side panel ----------

async function loadInfo() {
  try {
    const info = await (await fetch("/api/info")).json();
    const shared = new Set(Object.keys(info.shared_tools || {}));
    $("#agents").innerHTML =
      Object.entries(info.agents || {})
        .map(([agent, tools]) =>
          `<div class="agent-card"><b>${escapeHtml(agent)}</b><div>` +
          tools.map((t) => `<span class="tool${shared.has(t) ? " shared" : ""}" title="${shared.has(t) ? "Shared MCP tool" : ""}">${escapeHtml(t)}</span>`).join("") +
          "</div></div>")
        .join("") +
      `<p class="small muted">Outlined tools are MCP tools shared between agents. ` +
      `Models: ${escapeHtml(info.models?.openai || "")} · ${escapeHtml(info.models?.gemini || "")}. ` +
      `Conversation state: ${escapeHtml(info.state_backend || "")}.</p>`;
  } catch (_) {
    $("#agents").textContent = "Agent information is unavailable.";
  }
}

// ---------- Wiring ----------

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (!question || sendButton.disabled) return;
  input.value = "";
  ask(question);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});

document.querySelectorAll(".suggestion").forEach((button) =>
  button.addEventListener("click", () => {
    input.value = button.textContent;
    form.requestSubmit();
  }),
);

$("#new-chat").addEventListener("click", () => {
  try { localStorage.setItem(SESSION_KEY, newSessionId()); } catch (_) { /* ignore */ }
  window.location.reload();
});

showSession();
loadInfo();
