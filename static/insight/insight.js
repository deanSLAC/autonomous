/* Insight page — turn tape + simulation status + verbose toggle. */

const POLL_MS = 5000;
const VERBOSE_KEY = "insight-verbose";

let verbose = localStorage.getItem(VERBOSE_KEY) === "1";
let turns = [];
let ws = null;

document.addEventListener("DOMContentLoaded", () => {
    const tog = document.getElementById("verbose-toggle");
    tog.checked = verbose;
    tog.addEventListener("change", () => {
        verbose = tog.checked;
        localStorage.setItem(VERBOSE_KEY, verbose ? "1" : "0");
        renderTurns();
        toggleSysPrompt();
    });

    refreshAll();
    setInterval(refreshAll, POLL_MS);
    connectWS();

    setInterval(async () => {
        const dot = document.getElementById("server-dot");
        const txt = document.getElementById("server-status");
        try {
            const r = await fetch("/health", { signal: AbortSignal.timeout(3000) });
            if (r.ok) {
                dot.className = "status-dot dot-good";
                txt.textContent = "connected";
                const j = await r.json();
                document.getElementById("sim-pill").style.display =
                    j.simulation ? "inline-block" : "none";
            } else {
                dot.className = "status-dot dot-bad";
                txt.textContent = "error";
            }
        } catch {
            dot.className = "status-dot dot-bad";
            txt.textContent = "offline";
        }
    }, 5000);
});

function connectWS() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    try {
        ws = new WebSocket(`${proto}://${location.host}/ws`);
    } catch (e) {
        console.error("ws connect failed", e);
        return;
    }
    ws.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch { return; }
        if (msg.type === "turn_complete" && msg.turn) {
            turns.unshift(msg.turn);
            if (turns.length > 100) turns.length = 100;
            renderTurns();
        }
    };
    ws.onclose = () => setTimeout(connectWS, 4000);
}

async function refreshAll() {
    await Promise.all([refreshTurns(), refreshSim(), refreshActions(), maybeRefreshSysPrompt()]);
}

async function refreshTurns() {
    try {
        const r = await fetch("/api/insight/turns?limit=50");
        const j = await r.json();
        turns = j.turns || [];
        renderTurns();
    } catch (e) { console.error(e); }
}

async function refreshSim() {
    try {
        const r = await fetch("/api/insight/simulation");
        const j = await r.json();
        renderSim(j);
    } catch (e) { console.error(e); }
}

async function refreshActions() {
    try {
        const r = await fetch("/api/dashboard/action_log?limit=30");
        const j = await r.json();
        renderActions(j.actions || []);
    } catch (e) { console.error(e); }
}

let _sysPromptLoaded = false;
async function maybeRefreshSysPrompt() {
    if (_sysPromptLoaded) return;
    try {
        const r = await fetch("/api/insight/system_prompt");
        if (!r.ok) return;
        const j = await r.json();
        document.getElementById("syspr-path").textContent = j.path || "";
        document.getElementById("system-prompt-text").textContent = j.text || "";
        _sysPromptLoaded = true;
        toggleSysPrompt();
    } catch {}
}

function toggleSysPrompt() {
    const p = document.getElementById("system-prompt-panel");
    p.style.display = verbose && _sysPromptLoaded ? "" : "none";
}

function renderTurns() {
    const el = document.getElementById("turn-tape");
    document.getElementById("turn-summary").textContent =
        `${turns.length} turn${turns.length === 1 ? "" : "s"}`;
    if (!turns.length) {
        el.innerHTML = '<div class="muted" style="padding:24px;">No turns yet. Send a chat message or start the orchestrator.</div>';
        return;
    }
    el.innerHTML = turns.map((t, idx) => renderTurn(t, idx)).join("");
}

function renderTurn(t, idx) {
    const ts = t.ts ? new Date(t.ts * 1000).toLocaleTimeString() : "";
    const tools = (t.tool_calls || []);
    const toolPreview = tools.length
        ? tools.map(c => c.name).join(" → ")
        : "(no tool calls)";
    const txtPreview = (t.text || "").replace(/\s+/g, " ").slice(0, 140);
    const open = idx === 0; // expand the most recent by default
    return `
        <div class="turn" data-id="${esc(t.id || "")}">
            <div class="turn-head" onclick="toggleTurn(this)">
                <span class="turn-source">${esc(t.source || "?")}</span>
                <span class="turn-time">${esc(ts)}</span>
                <span class="turn-tools">${esc(toolPreview)}</span>
                <span class="turn-text-preview">${esc(txtPreview)}</span>
            </div>
            <div class="turn-body" ${open ? "" : "hidden"}>
                ${renderToolCalls(tools)}
                ${renderText("Assistant text", t.text)}
                ${verbose ? renderPrompt(t.prompt) : ""}
                ${verbose ? renderThoughts(t.thoughts) : ""}
            </div>
        </div>
    `;
}

function renderToolCalls(tools) {
    if (!tools.length) {
        return `<div><div class="turn-section-label">Tool calls</div>
                <div class="muted" style="font-size:12px;">No tools called this turn.</div></div>`;
    }
    return `
        <div>
            <div class="turn-section-label">Tool calls (${tools.length})</div>
            <div class="tool-call-list">
                ${tools.map((c, i) => renderToolCall(c, i)).join("")}
            </div>
        </div>
    `;
}

function renderToolCall(c, i) {
    const args = formatArgs(c.input);
    const status = c.status || "ok";
    const errClass = String(status).toLowerCase().includes("err") ? " err" : "";
    let detail = "";
    if (verbose) {
        const rows = [];
        if (c.input != null) rows.push("INPUT:\n" + safeJson(c.input));
        if (c.output) rows.push("OUTPUT:\n" + (typeof c.output === "string" ? c.output : safeJson(c.output)));
        if (rows.length) {
            detail = `<div class="tool-call-detail">${esc(rows.join("\n\n"))}</div>`;
        }
    }
    return `
        <div class="tool-call${errClass}">
            <span class="tc-num">${i + 1}.</span>
            <span class="tc-name">${esc(c.name || "?")}</span>
            <span class="tc-args" title="${esc(args)}">${esc(args)}</span>
            <span class="tc-status">${esc(String(status))}</span>
        </div>
        ${detail}
    `;
}

function renderText(label, text) {
    if (!text) return "";
    return `<div>
        <div class="turn-section-label">${esc(label)}</div>
        <div class="turn-text">${esc(text)}</div>
    </div>`;
}

function renderPrompt(p) {
    if (!p) return "";
    return `<div>
        <div class="turn-section-label">Prompt sent to LLM</div>
        <div class="turn-prompt">${esc(p)}</div>
    </div>`;
}

function renderThoughts(thoughts) {
    if (!thoughts || !thoughts.length) return "";
    return `<div>
        <div class="turn-section-label">Reasoning</div>
        <div class="turn-thoughts">${esc(thoughts.join("\n\n"))}</div>
    </div>`;
}

function toggleTurn(headEl) {
    const body = headEl.nextElementSibling;
    if (!body) return;
    body.hidden = !body.hidden;
}

function renderSim(s) {
    const block = document.getElementById("sim-block");
    document.getElementById("sim-sub").textContent = s.enabled ? "active" : "off";
    if (!s.enabled) {
        block.innerHTML = '<div class="muted">Simulation off. Set <code>SIMULATION_MODE=1</code> in .env and restart to enable.</div>';
        return;
    }
    const positions = s.positions || {};
    const posKeys = Object.keys(positions).slice(0, 14);
    const posHtml = posKeys.map(k => `
        <div class="row"><span class="name">${esc(k)}</span><span>${formatNum(positions[k])}</span></div>
    `).join("");
    const scans = s.scans_per_file || {};
    const scanRows = Object.entries(scans).map(([k, v]) =>
        `<div class="sim-stat"><span class="lbl">${esc(k)}</span><span class="val">${v}</span></div>`
    ).join("");
    block.innerHTML = `
        <div class="sim-stat"><span class="lbl">Active scan dir</span><span class="val">${esc(short(s.scan_dir || "—"))}</span></div>
        <div class="sim-stat"><span class="lbl">Current file</span><span class="val">${esc(s.current_file || s.last_filename || "—")}</span></div>
        ${scanRows || ""}
        <div style="margin-top:10px;">
            <div class="turn-section-label">Mock SPEC positions</div>
            <div class="sim-positions">${posHtml || '<span class="muted">—</span>'}</div>
        </div>
    `;
}

function renderActions(actions) {
    const el = document.getElementById("action-tape");
    if (!actions.length) {
        el.innerHTML = '<div class="muted">No actions yet.</div>';
        return;
    }
    el.innerHTML = actions.map(a => {
        const badge = a.success === 1 ? "ok" : a.success === 0 ? "err" : "pend";
        const txt = a.success === 1 ? "OK" : a.success === 0 ? "FAIL" : "…";
        const ts = a.timestamp ? a.timestamp.slice(11, 19) : "";
        return `<div class="action-row" title="${esc(a.justification || "")}">
            <span class="phase">${esc(ts)}</span>
            <span class="phase">${esc(a.phase || "")}</span>
            <span class="cmd">${esc(a.command)}</span>
            <span class="just">${esc((a.justification || "").slice(0, 140))}</span>
            <span class="badge ${badge}">${txt}</span>
        </div>`;
    }).join("");
}

// ---- helpers ----

function formatArgs(input) {
    if (!input || (typeof input === "object" && !Object.keys(input).length)) return "";
    if (typeof input === "string") return input.length > 80 ? input.slice(0, 80) + "…" : input;
    try {
        const pairs = Object.entries(input).map(([k, v]) => {
            let vs;
            if (v === null || v === undefined) vs = String(v);
            else if (typeof v === "string") vs = `"${v}"`;
            else if (typeof v === "object") vs = JSON.stringify(v);
            else vs = String(v);
            if (vs.length > 40) vs = vs.slice(0, 40) + "…";
            return `${k}=${vs}`;
        });
        const joined = pairs.join(" ");
        return joined.length > 200 ? joined.slice(0, 200) + "…" : joined;
    } catch {
        return "";
    }
}

function safeJson(x) {
    try { return JSON.stringify(x, null, 2); }
    catch { return String(x); }
}

function formatNum(v) {
    if (v == null) return "—";
    if (typeof v !== "number") return String(v);
    return Number.isInteger(v) ? String(v) : v.toFixed(4);
}

function short(p) {
    if (!p) return "—";
    return p.length > 60 ? "…" + p.slice(-58) : p;
}

function esc(s) {
    if (s == null) return "";
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
