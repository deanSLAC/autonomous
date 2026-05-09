/* Autonomy dashboard add-on: per-phase tile actions, plan, action log,
   interventions, guidance, chat. The master orchestrator (Start/Pause/
   Resume/Stop/Reset) was retired — every phase tile spawns its own
   Claude-CLI subprocess via /api/phase/run/{slug}. Polls
   /api/orchestrator/status (read-only), /api/dashboard/status, and
   /api/phase/run_status. */

const API = "";
const POLL_MS = 3000;

let autonomyPollTimer = null;
// Cache the spectrometer-aligned flag so the gating check is synchronous
// in renderTileActions(). Refreshed in refreshAutonomy().
let __spectrometerAligned = false;
// Phase-runner snapshot: {slug: {state, ...}}; refreshed each tick.
let __phaseRunStatus = {};

const _PHASE_LABELS_FOR_ALERT = {
    beamline_alignment: "Beamline Alignment",
    sample_alignment: "Sample Alignment",
    sample_survey: "Sample Survey",
    collection: "Data Collection",
    planner: "Planner",
    xes_alignment: "Spectrometer Alignment",
};

function openConfig() {
    window.location.href = "/config";
}

function openSampleHolderConfig() {
    // Land directly on the Sample Holder tab of /config. form.js reads
    // the query param on DOMContentLoaded and switches tabs.
    window.location.href = "/config?tab=samples";
}

function openPhaseDetail(phase) {
    window.location.href = "/phase?phase=" + encodeURIComponent(phase);
}

// ---------------------------------------------------------------------------
// Tile click → expand action buttons
// ---------------------------------------------------------------------------

function onPhaseTileClick(tile, event) {
    if (event && event.target && event.target.closest(".tile-actions")) return;
    if (tile.classList.contains("tile-disabled")) return;
    const column = tile.closest(".phase-column");
    const actions = column && column.querySelector(".tile-actions");
    if (!actions) return;
    const wasOpen = !actions.hidden;
    // Collapse any other open tiles first.
    document.querySelectorAll(".tile-actions").forEach(a => a.hidden = true);
    if (!wasOpen) {
        renderTileActions(tile, actions);
        actions.hidden = false;
    }
}

function renderTileActions(tile, container) {
    const phase = tile.getAttribute("data-phase");
    const runState = (__phaseRunStatus[phase] || {}).state || "idle";
    const isRunning = runState === "running";
    let html = "";

    if (phase === "beamline_alignment" || phase === "sample_alignment" || phase === "sample_survey" || phase === "collection") {
        const slug = phase;
        if (isRunning) {
            html += `<button class="btn-tile btn-tile-danger" onclick="killPhase('${slug}')">Kill</button>`;
        } else {
            html += `<button class="btn-tile btn-tile-primary" onclick="runPhase('${slug}')">Run</button>`;
        }
        // Sample Survey shares the Data Collection detail page (same scope, same panel).
        const infoSlug = phase === "sample_survey" ? "collection" : phase;
        html += `<button class="btn-tile" onclick="openPhaseDetail('${infoSlug}')">More info</button>`;
    } else if (phase === "xes_alignment") {
        if (__spectrometerAligned) {
            html += `<span class="tile-action-status">Marked aligned</span>`;
            html += `<button class="btn-tile btn-tile-warn" onclick="resetSpectrometerAligned()">Reset</button>`;
        } else {
            html += `<button class="btn-tile btn-tile-primary" onclick="markSpectrometerAligned()">Mark Complete</button>`;
        }
        html += `<button class="btn-tile" onclick="openPhaseDetail('${phase}')">More info</button>`;
    }
    container.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Run / Kill phase
// ---------------------------------------------------------------------------

async function runPhase(slug) {
    const labels = {
        beamline_alignment: "Beamline Alignment",
        sample_alignment: "Sample Alignment",
        sample_survey: "Sample Survey",
        collection: "Data Collection",
    };
    const label = labels[slug] || slug;
    if (!confirm(`Spawn the ${label} agent now?\n\nA Claude-CLI subprocess will start; watch its output on the More info page.`)) return;
    try {
        const r = await fetch(API + `/api/phase/run/${slug}`, { method: "POST" });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) {
            alert(`Run failed: ${j.detail || j.error || r.status}`);
            return;
        }
    } catch (e) {
        alert("Run failed: " + e);
        return;
    }
    refreshAutonomy();
}

async function killPhase(slug) {
    if (!confirm(`Send SIGTERM to the ${slug} agent?`)) return;
    try {
        const r = await fetch(API + `/api/phase/kill/${slug}`, { method: "POST" });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) {
            alert(`Kill failed: ${j.detail || j.error || r.status}`);
            return;
        }
    } catch (e) {
        alert("Kill failed: " + e);
        return;
    }
    refreshAutonomy();
}

// ---------------------------------------------------------------------------
// Spectrometer-aligned flag (no agent — operator confirmation only)
// ---------------------------------------------------------------------------

async function markSpectrometerAligned() {
    const expSel = document.getElementById("experiment-select");
    const expId = expSel ? expSel.value : "";
    if (!expId) { alert("Select an experiment first."); return; }
    // Pull the crystal label from the dashboard header so the prompt is precise.
    const crystalRaw = (document.getElementById("exp-crystal")?.textContent || "").trim();
    const crystalLabel = crystalRaw && crystalRaw !== "--"
        ? crystalRaw
        : "the crystal selected for this experiment";
    if (!confirm(`Confirm you have aligned the spectrometer with crystal set ${crystalLabel}.`)) return;
    try {
        const r = await fetch(API + `/api/phase/spectrometer_aligned`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ experiment_id: expId, aligned: true }),
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) { alert(`Mark failed: ${j.detail || j.error || r.status}`); return; }
    } catch (e) {
        alert("Mark failed: " + e); return;
    }
    refreshAutonomy();
}

async function resetSpectrometerAligned() {
    if (!confirm("Clear the spectrometer-aligned flag? Sample Alignment + Data Collection will be re-greyed-out.")) return;
    const expSel = document.getElementById("experiment-select");
    const expId = expSel ? expSel.value : "";
    if (!expId) return;
    try {
        await fetch(API + `/api/phase/spectrometer_aligned`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ experiment_id: expId, aligned: false }),
        });
    } catch (e) { console.error(e); }
    refreshAutonomy();
}

// ---------------------------------------------------------------------------
// Tile rendering
// ---------------------------------------------------------------------------

function setTileStatus(tile, status) {
    if (!tile) return;
    tile.dataset.status = status;
    const column = tile.closest(".phase-column");
    if (column) column.dataset.status = status;
}

function renderConfigTile(exp) {
    const tile = document.querySelector('.phase-tile[data-phase="config"]');
    if (!tile) return;
    const column = tile.closest(".phase-column");
    const folderEl = tile.querySelector('[data-field="folder"]');
    const elementsEl = tile.querySelector('[data-field="elements"]');
    const envEl = tile.querySelector('[data-field="sample_env"]');
    const badge = tile.querySelector(".tile-status-badge");

    if (!exp) {
        setTileStatus(tile, "pending");
        if (column) column.setAttribute("data-required", "true");
        if (badge) {
            badge.className = "tile-status-badge badge-pending";
            badge.textContent = "pending";
        }
        if (folderEl) folderEl.textContent = "--";
        if (elementsEl) elementsEl.innerHTML =
            '<span class="config-empty">Start here — no experiment configured yet</span>';
        if (envEl) envEl.textContent = "--";
        return;
    }

    setTileStatus(tile, "completed");
    if (column) column.removeAttribute("data-required");
    if (badge) {
        badge.className = "tile-status-badge badge-completed";
        badge.textContent = "configured";
    }
    if (folderEl) folderEl.textContent = exp.name || exp.experimenter || "--";
    if (elementsEl) {
        const elements = exp.elements || [];
        if (!elements.length) {
            elementsEl.innerHTML = '<span class="config-empty">No elements selected</span>';
        } else {
            elementsEl.innerHTML = elements
                .map((sym) => `<span class="element-chip">${escapeHtml(sym)}</span>`)
                .join("");
        }
    }
    if (envEl) envEl.textContent = exp.sample_env || "ambient";
}

function renderSampleHolderTile(dash) {
    const tile = document.querySelector('.phase-tile[data-phase="sample_holder_config"]');
    if (!tile) return;
    const badge = tile.querySelector(".tile-status-badge");
    const countEl = tile.querySelector('[data-field="sample_holder_count"]');
    const queue = (dash && dash.plan && dash.plan.plan && dash.plan.plan.sample_queue) || [];
    const nSamples = queue.length;
    if (nSamples > 0) {
        setTileStatus(tile, "completed");
        if (badge) {
            badge.className = "tile-status-badge badge-completed";
            badge.textContent = "configured";
        }
        if (countEl) countEl.textContent = `${nSamples} samples`;
    } else {
        setTileStatus(tile, "pending");
        if (badge) {
            badge.className = "tile-status-badge badge-pending";
            badge.textContent = "pending";
        }
        if (countEl) countEl.textContent = "no samples yet";
    }
}

// ---------------------------------------------------------------------------
// Guidance + chat
// ---------------------------------------------------------------------------

async function submitGuidance() {
    const input = document.getElementById("guidance-input");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    const expSel = document.getElementById("experiment-select");
    await fetch(API + "/api/orchestrator/guidance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            text,
            author: "web-user",
            experiment_id: expSel ? expSel.value : null,
        }),
    });
    refreshAutonomy();
}

// -- chat session id (per-tab, persisted in localStorage) -----------
function _chatUiSessionId() {
    let sid = null;
    try { sid = localStorage.getItem("chat_ui_session_id"); } catch (_) {}
    if (!sid) {
        // RFC4122-ish 12-hex; matches what the server mints.
        sid = (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "").slice(0, 12)
               : Math.random().toString(16).slice(2, 14));
        try { localStorage.setItem("chat_ui_session_id", sid); } catch (_) {}
    }
    return sid;
}

function _setChatUiSessionId(sid) {
    try { localStorage.setItem("chat_ui_session_id", sid); } catch (_) {}
}

// -- WebSocket: receives the agent's chat_reply ----------------------
let _chatWS = null;
function _ensureChatWS() {
    if (_chatWS && _chatWS.readyState <= 1) return _chatWS;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    try {
        _chatWS = new WebSocket(`${proto}://${location.host}/ws`);
    } catch (e) { console.error("chat ws connect failed", e); return null; }
    _chatWS.onmessage = (ev) => {
        let m;
        try { m = JSON.parse(ev.data); } catch { return; }
        if (m.type === "chat_reply" && m.text) {
            showTyping(false);
            appendChat("assistant", m.text);
        }
    };
    _chatWS.onclose = () => { setTimeout(_ensureChatWS, 4000); };
    return _chatWS;
}

async function sendChat() {
    const input = document.getElementById("chat-input");
    const btn = document.querySelector(".chat-compose button.chat-send-btn")
              || document.querySelector(".chat-compose button");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    appendChat("user", text);
    if (btn) { btn.disabled = true; btn.textContent = "…"; }
    showTyping(true);
    _ensureChatWS();
    try {
        const r = await fetch(API + "/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: text,
                ui_session_id: _chatUiSessionId(),
            }),
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) {
            showTyping(false);
            appendChat("assistant", "Error: " + (j.error || `HTTP ${r.status}`));
        }
        // Reply will arrive over the WebSocket as type=chat_reply.
        // Keep the typing indicator visible until then.
    } catch (e) {
        showTyping(false);
        appendChat("assistant", "Error: " + e);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = "Send"; }
    }
}

async function clearChat() {
    const sid = _chatUiSessionId();
    try {
        const r = await fetch(API + "/api/chat/clear", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ui_session_id: sid }),
        });
        const j = await r.json().catch(() => ({}));
        if (j.new_ui_session_id) {
            _setChatUiSessionId(j.new_ui_session_id);
        }
    } catch (e) {
        console.error("chat clear failed", e);
    }
    const log = document.getElementById("chat-log");
    if (log) {
        log.innerHTML = '<div class="muted">No messages yet.</div>';
    }
    showTyping(false);
}

function appendChat(role, text) {
    const log = document.getElementById("chat-log");
    if (!log) return;
    const placeholder = log.querySelector(".muted");
    if (placeholder && log.children.length === 1) placeholder.remove();
    const el = document.createElement("div");
    el.className = "chat-msg " + role;
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
}

function showTyping(on) {
    const log = document.getElementById("chat-log");
    const status = document.getElementById("chat-status");
    if (status) status.textContent = on ? "agent thinking…" : "";
    if (!log) return;
    let t = log.querySelector(".typing-indicator");
    if (on) {
        if (!t) {
            t = document.createElement("div");
            t.className = "typing-indicator";
            t.textContent = "agent is thinking…";
            log.appendChild(t);
            log.scrollTop = log.scrollHeight;
        }
    } else if (t) {
        t.remove();
    }
}

// ---------------------------------------------------------------------------
// Polling loop
// ---------------------------------------------------------------------------

async function refreshAutonomy() {
    let orc = null;
    let dash = null;
    try {
        const r = await fetch(API + "/api/orchestrator/status");
        orc = await r.json();
    } catch {}
    try {
        const r = await fetch(API + "/api/phase/run_status");
        const j = await r.json();
        const next = (j && j.phases) || {};
        _detectPhaseTransitions(__phaseRunStatus, next);
        __phaseRunStatus = next;
    } catch { __phaseRunStatus = {}; }

    const expSel = document.getElementById("experiment-select");
    const expId = expSel ? expSel.value : "";
    if (expId) {
        try {
            const r = await fetch(API + "/api/dashboard/status?experiment_id=" + expId);
            dash = await r.json();
        } catch {}
        try {
            const r = await fetch(API + "/api/phase/spectrometer_aligned?experiment_id=" + expId);
            const j = await r.json();
            __spectrometerAligned = !!(j && j.aligned);
        } catch { __spectrometerAligned = false; }
    } else {
        __spectrometerAligned = false;
    }
    renderAutonomy(orc, dash);
}

function renderAutonomy(orc, dash) {
    // Agent backend pill
    const agentReady = orc
        ? (orc.agent_reachable !== undefined ? !!orc.agent_reachable : !!orc.initialized)
        : false;
    // Agent backend pill — only meaningful for the opencode backend
    // (long-lived loopback server). With AGENT_BACKEND=claude_code
    // each turn spawns a `claude -p` subprocess, so there's no
    // server to be online or offline — hide the pill entirely.
    const agentPill = document.getElementById("orc-agent-pill");
    const agentEl = document.getElementById("orc-agent");
    const isOpencode = orc && orc.agent_backend === "opencode";
    if (agentPill) {
        agentPill.style.display = isOpencode ? "" : "none";
    }
    if (agentEl && isOpencode) {
        agentEl.textContent = agentReady ? "online" : "offline";
        agentEl.className = agentReady ? "dot-good" : "dot-bad";
    }

    const snap = (orc && orc.plan_snapshot) || {};
    const setText = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    };
    setText("orc-total", snap.beamtime_total_hours != null ? snap.beamtime_total_hours.toFixed(1) : "–");
    setText("orc-elapsed", snap.beamtime_elapsed_hours != null ? snap.beamtime_elapsed_hours.toFixed(2) : "–");
    // Samples done/total — exp-info bar on /dashboard, autonomy-bar pill on /sample_planning.
    const sDoneVal = snap.samples_completed != null ? snap.samples_completed : "–";
    const sTotVal = snap.samples_total != null ? snap.samples_total : "–";
    ["exp-samples-done", "orc-samples-done"].forEach(id => setText(id, sDoneVal));
    ["exp-samples-total", "orc-samples-total"].forEach(id => setText(id, sTotVal));
    // /sample_planning still shows a Turn pill; populate it if present.
    if (orc && orc.turn_count != null) setText("orc-turn", orc.turn_count);

    if (orc && orc.phase) {
        setText("cur-phase", orc.phase);
    }


    if (!dash) {
        renderConfigTile(null);
        renderSampleHolderTile(null);
        applyPhaseRunStatusToTiles();
        applyGatingToTiles();
        return;
    }

    // Plan table
    const tbody = document.getElementById("plan-tbody");
    const queue = (dash.plan && dash.plan.plan && dash.plan.plan.sample_queue) || [];
    const expSel = document.getElementById("experiment-select");
    const expId = expSel ? expSel.value : "";
    if (tbody) {
        if (queue.length) {
            tbody.innerHTML = queue.map((s, i) => {
                const reps = s.modes && s.modes[0] && s.modes[0].reps != null
                    ? `${s.reps_completed ?? 0} / ${s.modes[0].reps}`
                    : (s.reps_completed ?? 0);
                return `<tr>
                    <td>${i + 1}</td>
                    <td><span class="sample-name">${escapeHtml(s.sample_name)}</span></td>
                    <td>${escapeHtml(s.element_symbol)}</td>
                    <td><span class="plan-status-pill ${s.status || "queued"}">${s.status || "queued"}</span></td>
                    <td>${reps}</td>
                    <td>${s.snr_estimate != null ? Number(s.snr_estimate).toFixed(1) : "–"}</td>
                    <td>${s.efficiency_verdict || "–"}</td>
                </tr>`;
            }).join("");
        } else {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#888">No samples in plan yet — configure a sample holder under /config, then open Manage plan.</td></tr>';
        }
    }

    // Plan summary header
    const ps = document.getElementById("plan-summary");
    if (ps) {
        const done = queue.filter(s => s.status === "done").length;
        const inprog = queue.filter(s => s.status === "in_progress").length;
        const skip = queue.filter(s => s.status === "skipped").length;
        const budget = dash.plan && dash.plan.beamtime_total_hours;
        ps.textContent =
            `${queue.length} samples · ${done} done · ${inprog} running · ${skip} skipped` +
            (budget != null ? ` · budget ${budget.toFixed(1)}h` : "");
    }

    // Plan edit history
    const edits = dash.plan_edits || [];
    const editsEl = document.getElementById("plan-edits");
    if (editsEl) {
        if (edits.length) {
            editsEl.innerHTML = edits.map(e => {
                const ts = (e.timestamp || "").replace("T", " ").slice(0, 19);
                const target = e.target_id ? ` <span class="muted">${escapeHtml(e.target_id)}</span>` : "";
                const reason = e.reason ? ` — ${escapeHtml(e.reason)}` : "";
                const extra = summarizePayload(e.action, e.payload);
                return `<div class="edit">
                    <span class="when">${escapeHtml(ts)}</span>
                    <span class="who">${escapeHtml(e.author || "?")}</span>
                    <span class="act ${escapeHtml(e.action)}">${escapeHtml(e.action)}</span>${target}${extra ? ` ${extra}` : ""}${reason}
                </div>`;
            }).join("");
        } else {
            editsEl.innerHTML = '<div class="muted">No edits yet.</div>';
        }
    }

    window.__planQueue = queue;
    window.__planExpId = expId;

    // Action tape
    const actionsEl = document.getElementById("action-tape");
    const actions = dash.action_log || [];
    if (actionsEl) {
        if (actions.length) {
            actionsEl.innerHTML = actions.slice(0, 30).map(a => {
                const badge = a.success === 1 ? "ok" : a.success === 0 ? "err" : "pend";
                const badgeText = a.success === 1 ? "OK" : a.success === 0 ? "FAIL" : "…";
                const ts = a.timestamp ? a.timestamp.slice(11, 19) : "";
                return `<div class="action-row" title="${escapeHtml(a.justification || "")}">
                    <span class="phase">${ts}</span>
                    <span class="phase">${escapeHtml(a.phase || "")}</span>
                    <span class="cmd">${escapeHtml(a.command)}</span>
                    <span class="just">${escapeHtml((a.justification || "").slice(0, 160))}</span>
                    <span class="badge ${badge}">${badgeText}</span>
                </div>`;
            }).join("");
        } else {
            actionsEl.innerHTML = '<div class="muted">No actions yet.</div>';
        }
    }

    // Interventions
    const banner = document.getElementById("interventions-banner");
    const interventions = dash.interventions || [];
    if (banner) {
        if (interventions.length) {
            banner.style.display = "block";
            const sig = interventions
                .map(iv => `${iv.id}|${iv.kind}|${iv.detail || ""}`)
                .join("␞");
            if (banner.dataset.sig !== sig) {
                banner.dataset.sig = sig;
                banner.innerHTML = interventions.map(iv => {
                    const p = interventionPresentation(iv.kind);
                    return `
                    <div class="intervention-row intervention-${p.level}">
                        <div class="intervention-body">
                            <div class="intervention-title">
                                <span class="intervention-icon">${p.icon}</span>
                                ${escapeHtml(p.title)}
                            </div>
                            <div class="intervention-instruction">${escapeHtml(p.instruction)}</div>
                            ${iv.detail ? `
                                <details class="intervention-agent">
                                    <summary>Agent message</summary>
                                    <div class="intervention-agent-text">${escapeHtml(iv.detail)}</div>
                                </details>
                            ` : ""}
                        </div>
                        <div class="btns">
                            <button onclick="resolveIntervention('${iv.id}', 'resolved')">Done — continue</button>
                            <button class="secondary" onclick="resolveIntervention('${iv.id}', 'denied')">Abort run</button>
                        </div>
                    </div>`;
                }).join("");
            }
        } else {
            banner.style.display = "none";
            banner.dataset.sig = "";
        }
    }

    // Guidance feed — API returns newest-first; render oldest→newest so the
    // most recent message lands at the bottom (matches the chat panel).
    const feed = document.getElementById("guidance-feed");
    const guidance = dash.guidance || [];
    if (feed) {
        if (guidance.length) {
            const ordered = guidance.slice(0, 30).slice().reverse();
            const sig = ordered.map(g => g.id || `${g.timestamp}|${g.text}`).join("␞");
            if (feed.dataset.sig !== sig) {
                feed.dataset.sig = sig;
                feed.innerHTML = ordered.map(g => `
                    <div class="row">
                        <span class="who">${escapeHtml(g.author || "?")}</span>
                        <span class="when">${escapeHtml((g.timestamp || "").replace("T", " ").slice(0, 19))}</span>
                        <div>${escapeHtml(g.text)}</div>
                    </div>
                `).join("");
                feed.scrollTop = feed.scrollHeight;
            }
        } else {
            if (feed.dataset.sig !== "") {
                feed.dataset.sig = "";
                feed.innerHTML = '<div class="muted">No guidance yet.</div>';
            }
        }
    }

    // Phase tiles (status from DB phase_runs)
    document.querySelectorAll('.phase-tile:not([data-phase="config"]):not([data-phase="sample_holder_config"])').forEach(tile => {
        const key = tile.getAttribute("data-phase");
        const matching = (dash.phase_runs || []).filter(r => r.phase === key || r.phase === key.replace("_alignment","_align"));
        const latest = matching[matching.length - 1];
        if (latest) {
            const status = latest.status || "pending";
            setTileStatus(tile, status);
            const badge = tile.querySelector(".tile-status-badge");
            if (badge) {
                badge.textContent = status;
                badge.className = "tile-status-badge badge-" + status;
            }
        }
    });

    if (orc && orc.phase) {
        document.querySelectorAll('.phase-tile:not([data-phase="config"]):not([data-phase="sample_holder_config"])').forEach(t => {
            t.style.outline = t.getAttribute("data-phase") === orc.phase
                ? "2px solid var(--accent, #9b1b30)" : "";
        });
    }

    // Config tile + exp info
    const expForTile = dash.experiment
        ? { ...dash.experiment, elements: (dash.elements || []).map((e) => e.symbol).filter(Boolean) }
        : null;
    renderConfigTile(expForTile);
    renderSampleHolderTile(dash);

    if (dash.experiment) {
        const expmer = (typeof experimenterFromExperiment === "function")
            ? experimenterFromExperiment(dash.experiment)
            : (dash.experiment.experimenter || "");
        setText("exp-experimenter", expmer || "--");
        setText(
            "exp-crystal",
            (typeof formatCrystal === "function"
                ? formatCrystal(dash.experiment.mono_crystal)
                : (dash.experiment.mono_crystal || "--")),
        );
        setText(
            "exp-beam",
            (typeof formatBeamSize === "function"
                ? formatBeamSize(dash.experiment)
                : `H:${dash.experiment.beam_size_h || "?"} V:${dash.experiment.beam_size_v || "?"}`),
        );
        setText("exp-env", dash.experiment.sample_env || "--");
    }

    applyPhaseRunStatusToTiles();
    applyGatingToTiles();

    // Re-render any open tile-actions block to reflect new state.
    document.querySelectorAll(".tile-actions:not([hidden])").forEach(actions => {
        const column = actions.closest(".phase-column");
        const tile = column && column.querySelector(".phase-tile");
        if (tile) renderTileActions(tile, actions);
    });

    if (typeof window !== "undefined" && typeof window.onAutonomyRendered === "function") {
        try { window.onAutonomyRendered(orc, dash); } catch (e) { console.warn(e); }
    }
}

// ---------------------------------------------------------------------------
// Per-phase live state (running spinner, complete/failed flag) + gating
// ---------------------------------------------------------------------------

function _detectPhaseTransitions(prev, curr) {
    // First tick: prev is {} so every slug's previous state is undefined,
    // and `prevState === "running"` is false — nothing fires. Subsequent
    // ticks fire once when a slug transitions out of running.
    Object.entries(curr || {}).forEach(([slug, info]) => {
        const prevState = (prev[slug] || {}).state;
        const newState = (info || {}).state;
        if (prevState === "running" && newState && newState !== "running") {
            const label = _PHASE_LABELS_FOR_ALERT[slug] || slug;
            const startedAt = info.started_at || info.startedAt;
            const finishedAt = info.finished_at || info.finishedAt;
            _showPhaseCompleteAlert(label, newState, startedAt, finishedAt);
        }
    });
}

function _showPhaseCompleteAlert(name, state, startedAt, finishedAt) {
    let modal = document.getElementById("phase-complete-modal");
    if (!modal) {
        modal = document.createElement("div");
        modal.id = "phase-complete-modal";
        modal.className = "phase-modal-overlay";
        modal.innerHTML = `
            <div class="phase-modal-card" role="alertdialog" aria-modal="true">
                <div class="phase-modal-headline" id="phase-modal-headline"></div>
                <div class="phase-modal-state" id="phase-modal-state"></div>
                <div class="phase-modal-duration muted" id="phase-modal-duration"></div>
                <button class="phase-modal-ok" type="button">OK</button>
            </div>`;
        document.body.appendChild(modal);
        modal.querySelector(".phase-modal-ok").addEventListener("click", _dismissPhaseComplete);
        // Click outside the card to dismiss.
        modal.addEventListener("click", (e) => {
            if (e.target === modal) _dismissPhaseComplete();
        });
    }
    const stateLabel =
        state === "complete" ? "completed successfully" :
        state === "failed"   ? "failed"                  :
        state === "aborted"  ? "was aborted"             :
                               `ended (${state})`;
    document.getElementById("phase-modal-headline").textContent = name + " — finished";
    const stateEl = document.getElementById("phase-modal-state");
    stateEl.textContent = stateLabel;
    stateEl.className = "phase-modal-state state-" + state;

    let durationStr = "";
    if (startedAt) {
        const startMs = Number(startedAt) * 1000;
        const endMs = finishedAt ? Number(finishedAt) * 1000 : Date.now();
        const totalSecs = Math.max(0, Math.round((endMs - startMs) / 1000));
        const m = Math.floor(totalSecs / 60);
        const s = totalSecs % 60;
        durationStr = m > 0 ? `${m}m ${s}s` : `${s}s`;
    }
    document.getElementById("phase-modal-duration").textContent =
        durationStr ? `Took ${durationStr}.` : "";

    modal.classList.add("visible");
    try { document.title = "✓ " + name + " — BL15-2"; } catch (_) {}
}

function _dismissPhaseComplete() {
    const modal = document.getElementById("phase-complete-modal");
    if (modal) modal.classList.remove("visible");
    try { document.title = "BL15-2 Dashboard"; } catch (_) {}
}

function applyPhaseRunStatusToTiles() {
    Object.entries(__phaseRunStatus).forEach(([slug, info]) => {
        const tile = document.querySelector(`.phase-tile[data-phase="${slug}"]`);
        if (!tile) return;
        const badge = tile.querySelector(".tile-status-badge");
        if (info.state === "running") {
            setTileStatus(tile, "running");
            if (badge) { badge.className = "tile-status-badge badge-running"; badge.textContent = "running"; }
        } else if (info.state === "complete") {
            setTileStatus(tile, "completed");
            if (badge) { badge.className = "tile-status-badge badge-completed"; badge.textContent = "complete"; }
        } else if (info.state === "failed") {
            setTileStatus(tile, "failed");
            if (badge) { badge.className = "tile-status-badge badge-failed"; badge.textContent = "failed"; }
        }
    });

    // Spectrometer alignment is a manual phase — no agent process, so it
    // never appears in __phaseRunStatus. Drive its badge from the
    // operator-confirmed `spectrometer_aligned` flag instead.
    const xesTile = document.querySelector('.phase-tile[data-phase="xes_alignment"]');
    if (xesTile) {
        const xesBadge = xesTile.querySelector(".tile-status-badge");
        if (__spectrometerAligned) {
            setTileStatus(xesTile, "completed");
            if (xesBadge) { xesBadge.className = "tile-status-badge badge-completed"; xesBadge.textContent = "complete"; }
        } else {
            setTileStatus(xesTile, "pending");
            if (xesBadge) { xesBadge.className = "tile-status-badge badge-pending"; xesBadge.textContent = "pending"; }
        }
    }
}

function applyGatingToTiles() {
    // Sample Alignment + Data Collection are blocked until the operator
    // marks the spectrometer aligned. Greying out means: no click, no
    // run buttons.
    ["sample_alignment", "sample_survey", "collection"].forEach(slug => {
        const tile = document.querySelector(`.phase-tile[data-phase="${slug}"]`);
        if (!tile) return;
        if (__spectrometerAligned) {
            tile.classList.remove("tile-disabled");
            tile.title = "";
        } else {
            tile.classList.add("tile-disabled");
            tile.title = "Mark the spectrometer aligned first (Spectrometer Alignment tile)";
            // collapse any open actions
            const column = tile.closest(".phase-column");
            const actions = column && column.querySelector(".tile-actions");
            if (actions) actions.hidden = true;
        }
    });
}

// ---------------------------------------------------------------------------
// Plan helpers (unchanged from previous version)
// ---------------------------------------------------------------------------

function currentAuthor() {
    return localStorage.getItem("plan-author") || "web-user";
}

function summarizePayload(action, payload) {
    if (!payload) return "";
    if (action === "set_end_time" && payload.end_time) {
        return `<span class="muted">end → ${escapeHtml(payload.end_time)}</span>`;
    }
    if (action === "add_sample" && payload.sample) {
        return `<span class="muted">${escapeHtml(payload.sample.sample_name || "")} (${escapeHtml(payload.sample.element_symbol || "")})</span>`;
    }
    if (action === "update_params") {
        const keys = ["status", "snr_target", "note"].filter(k => payload[k] != null);
        return `<span class="muted">${escapeHtml(keys.join(", "))}</span>`;
    }
    if (action === "reorder") {
        return `<span class="muted">${(payload.order || []).length} samples</span>`;
    }
    if (action === "skip" && payload.note) {
        return `<span class="muted">${escapeHtml(payload.note)}</span>`;
    }
    return "";
}

async function planPost(path, body) {
    const expId = window.__planExpId || (document.getElementById("experiment-select")?.value || "");
    if (!expId) { alert("Start an experiment first."); return null; }
    const full = { ...body, experiment_id: expId, author: currentAuthor() };
    try {
        const r = await fetch(`/api/plan/${path}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(full),
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) { alert(j.detail || j.error || `error ${r.status}`); return null; }
        return j;
    } catch (e) {
        alert(`Request failed: ${e}`); return null;
    } finally {
        refreshAutonomy();
    }
}

async function skipSample(sampleId) {
    const note = prompt("Skip reason (optional):", "") || undefined;
    await planPost("skip_sample", { sample_id: sampleId, note });
}

async function removeSample(sampleId) {
    if (!confirm("Remove this sample from the plan? This does not delete the record, just takes it out of the queue.")) return;
    const reason = prompt("Why remove it? (optional)", "") || undefined;
    await planPost("remove_sample", { sample_id: sampleId, reason });
}

async function moveSample(sampleId, delta) {
    const queue = window.__planQueue || [];
    const ids = queue.map(s => s.sample_id);
    const idx = ids.indexOf(sampleId);
    if (idx < 0) return;
    const newIdx = Math.max(0, Math.min(ids.length - 1, idx + delta));
    if (newIdx === idx) return;
    ids.splice(idx, 1);
    ids.splice(newIdx, 0, sampleId);
    await planPost("reorder", { order: ids });
}

async function extendEndTime(hours) {
    const reason = hours < 0
        ? prompt(`Pull end-time in by ${Math.abs(hours)}h. Reason? (optional)`, "")
        : prompt(`Push end-time out by ${hours}h. Reason? (optional)`, "");
    if (reason === null) return;
    await planPost("set_end_time", { hours_from_now: hours, reason: reason || undefined });
}

function openAddSample() {
    document.getElementById("add-sample-inline").style.display = "flex";
    document.getElementById("add-sample-name").focus();
}
function closeAddSample() {
    document.getElementById("add-sample-inline").style.display = "none";
}

async function submitAddSample() {
    const name = document.getElementById("add-sample-name").value.trim();
    const elem = document.getElementById("add-sample-element").value.trim();
    if (!name || !elem) { alert("Sample name + element are required."); return; }
    const reps = parseInt(document.getElementById("add-sample-reps").value || "6", 10);
    const ct = parseFloat(document.getElementById("add-sample-time").value || "0.5");
    const posRaw = document.getElementById("add-sample-pos").value.trim();
    const position = posRaw === "" ? null : Math.max(0, parseInt(posRaw, 10) - 1);
    const reason = document.getElementById("add-sample-reason").value.trim();
    const modes = [{ mode: "xas", reps, count_time_s: ct }];
    const ok = await planPost("add_sample", {
        sample_name: name,
        element_symbol: elem,
        modes,
        position,
        reason: reason || undefined,
    });
    if (ok) {
        document.getElementById("add-sample-name").value = "";
        document.getElementById("add-sample-element").value = "";
        document.getElementById("add-sample-pos").value = "";
        document.getElementById("add-sample-reason").value = "";
        closeAddSample();
    }
}

async function resolveIntervention(id, status) {
    await fetch(API + `/api/orchestrator/intervention/${id}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, resolver: "web-user" }),
    });
    refreshAutonomy();
}

async function stopSpec() {
    try {
        const r = await fetch(API + "/api/orchestrator/abort_spec", { method: "POST" });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) {
            alert("Stop SPEC failed: " + (j.detail || j.error || r.status));
        }
    } catch (e) {
        alert("Stop SPEC failed: " + (e && e.message ? e.message : e));
    }
}

// ---------------------------------------------------------------------------
// Log-tail panels (Agent Output + SPEC Output)
// ---------------------------------------------------------------------------

const _tailState = {
    agent: { path: null, offset: 0, cards: new Map() },
    spec:  { path: null, offset: -1, started: false },
};

const _LOG_TAIL_MAX_CHARS = 64 * 1024;
const _AGENT_MAX_CARDS = 200;

function _appendToLogPanel(panelId, content) {
    const el = document.getElementById(panelId);
    if (!el) return;
    if (!_tailState.spec.started) {
        el.textContent = "";  // clear placeholder on first content
        _tailState.spec.started = true;
    }
    el.textContent += content;
    if (el.textContent.length > _LOG_TAIL_MAX_CHARS) {
        el.textContent = el.textContent.slice(-_LOG_TAIL_MAX_CHARS);
    }
    el.scrollTop = el.scrollHeight;
}

// --- Agent Output (structured cards) -----------------------------------

const _TOOL_CHIP = {
    Bash:  "bash",
    Read:  "read",
    Edit:  "edit",
    Write: "write",
    Grep:  "grep",
    Glob:  "glob",
    Task:  "task",
    WebFetch: "web",
    WebSearch: "web",
    NotebookEdit: "edit",
};

function _toolChipClass(tool) {
    return _TOOL_CHIP[tool] || "tool";
}

function _agentResetPanel() {
    const el = document.getElementById("agent-output");
    if (!el) return;
    el.innerHTML = '<div class="muted">Waiting for the agent…</div>';
    _tailState.agent.cards.clear();
}

function _formatDetail(detail) {
    // Try to pretty-print JSON; otherwise leave as-is.
    if (!detail) return "";
    const s = detail.trim();
    if ((s.startsWith("{") && s.endsWith("}")) || (s.startsWith("[") && s.endsWith("]"))) {
        try {
            return JSON.stringify(JSON.parse(s), null, 2);
        } catch (_) {}
    }
    return detail;
}

function _isNearBottom(el, slack = 60) {
    return (el.scrollHeight - el.scrollTop - el.clientHeight) < slack;
}

function _renderAgentEvent(host, ev) {
    const cards = _tailState.agent.cards;

    if (ev.kind === "tool_use") {
        const card = document.createElement("div");
        card.className = "agent-card pending";
        card.dataset.toolUseId = ev.tool_use_id;

        const head = document.createElement("div");
        head.className = "agent-card-head";

        const chip = document.createElement("span");
        chip.className = `agent-chip chip-${_toolChipClass(ev.tool)}`;
        chip.textContent = ev.tool || "tool";
        head.appendChild(chip);

        const summary = document.createElement("span");
        summary.className = "agent-card-summary";
        summary.textContent = ev.summary || "";
        head.appendChild(summary);

        const status = document.createElement("span");
        status.className = "agent-card-status";
        status.textContent = "…";
        head.appendChild(status);

        card.appendChild(head);

        const body = document.createElement("div");
        body.className = "agent-card-body";
        body.style.display = "none";
        const inputPre = document.createElement("pre");
        inputPre.className = "agent-card-detail";
        inputPre.textContent = ev.input ? JSON.stringify(ev.input, null, 2) : "";
        body.appendChild(_labeledBlock("input", inputPre));
        card.appendChild(body);

        head.addEventListener("click", () => {
            const open = body.style.display !== "none";
            body.style.display = open ? "none" : "block";
            card.classList.toggle("open", !open);
        });

        host.appendChild(card);
        cards.set(ev.tool_use_id, card);
        return;
    }

    if (ev.kind === "tool_result") {
        const card = cards.get(ev.tool_use_id);
        if (!card) {
            // Result with no matching call (e.g. result arrived before its
            // tool_use was projected, or chunk-boundary lost the use). Drop
            // a standalone result so nothing is silently swallowed.
            const orphan = document.createElement("div");
            orphan.className = "agent-card " + (ev.is_error ? "err" : "ok");
            const head = document.createElement("div");
            head.className = "agent-card-head";
            const chip = document.createElement("span");
            chip.className = "agent-chip chip-tool";
            chip.textContent = "result";
            head.appendChild(chip);
            const sm = document.createElement("span");
            sm.className = "agent-card-summary";
            sm.textContent = ev.summary || "";
            head.appendChild(sm);
            orphan.appendChild(head);
            host.appendChild(orphan);
            return;
        }
        card.classList.remove("pending");
        card.classList.add(ev.is_error ? "err" : "ok");
        const status = card.querySelector(".agent-card-status");
        if (status) status.textContent = ev.is_error ? "✕" : "✓";
        const summary = card.querySelector(".agent-card-summary");
        if (summary) summary.textContent = ev.summary || summary.textContent;
        const body = card.querySelector(".agent-card-body");
        if (body && ev.detail) {
            const resultPre = document.createElement("pre");
            resultPre.className = "agent-card-detail";
            resultPre.textContent = _formatDetail(ev.detail);
            body.appendChild(_labeledBlock("output", resultPre));
        }
        return;
    }

    if (ev.kind === "assistant_text") {
        const note = document.createElement("div");
        note.className = "agent-note";
        note.textContent = ev.text;
        host.appendChild(note);
        return;
    }

    if (ev.kind === "system") {
        const sys = document.createElement("div");
        sys.className = "agent-system";
        sys.textContent = `[${ev.subtype}] ${ev.text || ""}`.trim();
        host.appendChild(sys);
        return;
    }

    if (ev.kind === "result") {
        const done = document.createElement("div");
        done.className = "agent-system done";
        const cost = (typeof ev.cost === "number") ? `  cost=$${ev.cost.toFixed(4)}` : "";
        const turns = (ev.turns != null) ? `  turns=${ev.turns}` : "";
        done.textContent = `[done] ${ev.subtype || ""}${turns}${cost}`.trim();
        host.appendChild(done);
        return;
    }
}

function _labeledBlock(label, child) {
    const wrap = document.createElement("div");
    wrap.className = "agent-card-section";
    const lbl = document.createElement("div");
    lbl.className = "agent-card-label";
    lbl.textContent = label;
    wrap.appendChild(lbl);
    wrap.appendChild(child);
    return wrap;
}

function _trimAgentCards(host) {
    while (host.children.length > _AGENT_MAX_CARDS) {
        const first = host.firstElementChild;
        if (!first) break;
        if (first.dataset && first.dataset.toolUseId) {
            _tailState.agent.cards.delete(first.dataset.toolUseId);
        }
        host.removeChild(first);
    }
}

async function _fetchAgentEvents(slug, offset) {
    const url = slug
        ? `${API}/api/phase/log_tail?format=structured&slug=${encodeURIComponent(slug)}&offset=${offset}`
        : `${API}/api/phase/log_tail?format=structured&offset=${offset}`;
    const r = await fetch(url);
    if (!r.ok) return null;
    return r.json();
}

async function refreshAgentOutput() {
    const st = _tailState.agent;
    try {
        const j = await _fetchAgentEvents(null, st.offset);
        if (!j) return;
        const sub = document.getElementById("agent-output-sub");
        if (sub) sub.textContent = j.slug ? `${j.slug}` : "idle";
        // Reset on path change (new run started, log rotated).
        if (j.path !== st.path) {
            st.path = j.path;
            st.offset = 0;
            _agentResetPanel();
            if (j.path) {
                const j2 = await _fetchAgentEvents(j.slug, 0);
                if (j2) {
                    _renderAgentEvents(j2.events || []);
                    st.offset = j2.offset;
                }
            }
            return;
        }
        _renderAgentEvents(j.events || []);
        st.offset = j.offset;
    } catch (_) {}
}

function _renderAgentEvents(events) {
    if (!events || !events.length) return;
    const host = document.getElementById("agent-output");
    if (!host) return;
    // First content arrives → drop placeholder.
    const placeholder = host.querySelector(".muted");
    if (placeholder && host.children.length === 1) host.innerHTML = "";
    const stickToBottom = _isNearBottom(host);
    for (const ev of events) _renderAgentEvent(host, ev);
    _trimAgentCards(host);
    if (stickToBottom) host.scrollTop = host.scrollHeight;
}

async function refreshSpecOutput() {
    const st = _tailState.spec;
    try {
        const u = `${API}/api/spec_log/tail?offset=${st.offset}`;
        const r = await fetch(u);
        if (!r.ok) return;
        const j = await r.json();
        const sub = document.getElementById("spec-output-sub");
        if (sub && j.path) {
            const parts = j.path.split("/");
            sub.textContent = parts[parts.length - 1];
        } else if (sub) {
            sub.textContent = "no log";
        }
        // Log rotated (or first poll): reset panel; the offset=-1 fetch
        // already returned the file's tail in j.content.
        if (j.path !== st.path) {
            st.path = j.path;
            st.started = false;
            const el = document.getElementById("spec-output");
            if (el) el.innerHTML = '<span class="muted">Waiting for SPEC log…</span>';
        }
        if (j.content) _appendToLogPanel("spec-output", j.content);
        st.offset = j.offset;
    } catch (_) {}
}

let _lastPlotKey = null;
async function refreshAgentPlot() {
    try {
        const r = await fetch(API + "/api/tool_plots/latest");
        if (!r.ok) return;
        const j = await r.json();
        const sub = document.getElementById("agent-plot-sub");
        const box = document.getElementById("agent-plot");
        if (!box) return;
        if (!j.filename) {
            if (sub) sub.textContent = "no plots yet";
            if (_lastPlotKey !== null) {
                box.innerHTML = '<div class="muted">No plots yet.</div>';
                _lastPlotKey = null;
            }
            return;
        }
        const key = j.filename + "@" + j.mtime;
        if (sub) sub.textContent = j.filename;
        if (key !== _lastPlotKey) {
            // Cache-bust so the browser picks up overwrites of the same name.
            const url = `${API}/api/tool_plots/file/${encodeURIComponent(j.filename)}?t=${j.mtime}`;
            box.innerHTML = `<img src="${url}" alt="latest agent plot">`;
            _lastPlotKey = key;
        }
    } catch (_) {}
}

async function refreshSafetySwitches() {
    try {
        const r = await fetch(API + "/api/safety_switches");
        if (!r.ok) return;
        const j = await r.json();
        const rd = document.getElementById("sw-spec-read");
        const wr = document.getElementById("sw-spec-write");
        if (rd) rd.checked = !!j.spec_read_enabled;
        if (wr) wr.checked = !!j.spec_write_enabled;
    } catch (_) {}
}

async function setSafetySwitch(key, enabled) {
    try {
        const r = await fetch(API + "/api/safety_switches", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ [key]: !!enabled }),
        });
        if (!r.ok) {
            const j = await r.json().catch(() => ({}));
            alert("Toggle failed: " + (j.detail || j.error || r.status));
            refreshSafetySwitches();  // re-sync UI to actual state
            return;
        }
    } catch (e) {
        alert("Toggle failed: " + (e && e.message ? e.message : e));
        refreshSafetySwitches();
    }
}

async function stopAgents() {
    if (!confirm("SIGTERM every running phase agent?")) return;
    try {
        const r = await fetch(API + "/api/phase/kill_all", { method: "POST" });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) {
            alert("Stop agents failed: " + (j.detail || j.error || r.status));
            return;
        }
        if (j.count === 0) alert("No phase agents were running.");
    } catch (e) {
        alert("Stop agents failed: " + (e && e.message ? e.message : e));
    }
    refreshAutonomy();
}


function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

const INTERVENTION_KINDS = {
    crystal_install: {
        level: "success",
        icon: "✓",
        title: "Beamline alignment complete",
        instruction:
            "Install the crystals for this experiment, then click " +
            "“Done — continue” so the agent can start " +
            "spectrometer alignment.",
    },
    sample_mount: {
        level: "action",
        icon: "●",
        title: "Ready for sample mount",
        instruction:
            "Mount the sample(s) in the holder, then click “Done " +
            "— continue”.",
    },
    foil_swap: {
        level: "action",
        icon: "●",
        title: "Reference foil swap needed",
        instruction:
            "Install the correct reference foil, then click “Done " +
            "— continue”.",
    },
    gap_ownership: {
        level: "action",
        icon: "●",
        title: "Gap ownership transfer needed",
        instruction:
            "Take gap ownership for this hutch, then click “Done " +
            "— continue”.",
    },
    backward_transition: {
        level: "warning",
        icon: "↶",
        title: "Agent wants to redo a previous phase",
        instruction:
            "The agent is asking to go back a phase. Approve only if " +
            "you agree with the reason given below.",
    },
    system_issue: {
        level: "warning",
        icon: "⚠",
        title: "Please review",
        instruction:
            "The agent paused because it thinks something is off. Read " +
            "its message below, then either continue (if you’re " +
            "satisfied) or abort the run.",
    },
};

function interventionPresentation(kind) {
    if (kind && INTERVENTION_KINDS[kind]) return INTERVENTION_KINDS[kind];
    return {
        level: "warning",
        icon: "?",
        title: "Action needed",
        instruction:
            "The agent raised an intervention of a kind we don’t " +
            "have hardcoded guidance for. Read its message below and " +
            "decide what to do.",
    };
}

function wirePlanAuthor() {
    const el = document.getElementById("plan-author");
    if (!el) return;
    const label = () => `as ${currentAuthor()}`;
    el.textContent = label();
    el.style.cursor = "pointer";
    el.addEventListener("click", () => {
        const name = prompt("Attribute plan edits to:", currentAuthor());
        if (name) {
            localStorage.setItem("plan-author", name.trim());
            el.textContent = label();
        }
    });
}

document.addEventListener("DOMContentLoaded", () => {
    wirePlanAuthor();
    refreshAutonomy();
    refreshSafetySwitches();
    setInterval(refreshSafetySwitches, 5000);
    refreshAgentOutput();
    refreshSpecOutput();
    refreshAgentPlot();
    setInterval(refreshAgentOutput, 1500);
    setInterval(refreshSpecOutput, 1500);
    setInterval(refreshAgentPlot, 3000);
    autonomyPollTimer = setInterval(refreshAutonomy, POLL_MS);
    // Server health signal
    const srvDot = document.getElementById("server-dot");
    const srvTxt = document.getElementById("server-status");
    setInterval(async () => {
        try {
            const r = await fetch(API + "/health", { signal: AbortSignal.timeout(3000) });
            if (r.ok) {
                srvDot.className = "status-dot dot-good"; srvTxt.textContent = "connected";
                try {
                    const j = await r.json();
                    const pill = document.getElementById("sim-pill");
                    if (pill) pill.style.display = j.simulation ? "inline-block" : "none";
                } catch {}
            }
            else { srvDot.className = "status-dot dot-bad"; srvTxt.textContent = "error"; }
        } catch {
            srvDot.className = "status-dot dot-bad"; srvTxt.textContent = "offline";
        }
    }, 5000);
});
