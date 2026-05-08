/* Autonomy dashboard add-on: orchestrator control, plan, actions,
   interventions, guidance, chat. Polls /api/orchestrator/status +
   /api/dashboard/status. */

const API = "";
const POLL_MS = 3000;

let autonomyPollTimer = null;

async function autonomyAction(kind) {
    const expSel = document.getElementById("experiment-select");
    const expId = expSel ? expSel.value : "";
    try {
        if (kind === "start") {
            if (!expId) { alert("Select an experiment first."); return; }
            const r = await fetch(API + "/api/orchestrator/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ experiment_id: expId, beamtime_hours: 48 }),
            });
            const j = await r.json().catch(() => ({}));
            if (!r.ok || j.success === false) {
                const msg = j.error || j.detail || `HTTP ${r.status}`;
                if (r.status === 503) {
                    alert(
                        "Cannot start run — agent backend is offline.\n\n" +
                        msg + "\n\n" +
                        "The orchestrator needs the local opencode server. " +
                        "Start it with: scripts/start_opencode.sh\n" +
                        "(or run scripts/start.sh to launch everything together)."
                    );
                } else {
                    alert("Start failed: " + msg);
                }
                return;
            }
        } else {
            const r = await fetch(API + `/api/orchestrator/${kind}`, { method: "POST" });
            if (!r.ok) {
                const j = await r.json().catch(() => ({}));
                alert(`${kind} failed: ${j.detail || j.error || r.status}`);
                return;
            }
        }
    } catch (e) {
        alert("Request failed: " + (e && e.message ? e.message : e));
        console.error(e);
    }
    refreshAutonomy();
}

function openConfig() {
    window.location.href = "/config";
}

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
    // Drop the empty-state placeholder on first real message.
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

async function refreshAutonomy() {
    let orc = null;
    let dash = null;
    try {
        const r = await fetch(API + "/api/orchestrator/status");
        orc = await r.json();
    } catch {}
    const expSel = document.getElementById("experiment-select");
    const expId = expSel ? expSel.value : "";
    if (expId) {
        try {
            const r = await fetch(API + "/api/dashboard/status?experiment_id=" + expId);
            dash = await r.json();
        } catch {}
    }
    renderAutonomy(orc, dash);
}

function renderAutonomy(orc, dash) {
    // Buttons
    const running = !!(orc && orc.running);
    const paused = !!(orc && orc.paused);
    // `agent_reachable` is a live probe; `initialized` only flips at
    // FastAPI startup. Prefer the live value when it's present so the
    // pill + button react if opencode dies mid-run.
    const agentReady = orc
        ? (orc.agent_reachable !== undefined ? !!orc.agent_reachable : !!orc.initialized)
        : false;
    const startBtn = document.getElementById("btn-start");
    startBtn.disabled = running || !agentReady;
    startBtn.title = agentReady
        ? "Start the autonomous run"
        : "Agent backend offline — start it with scripts/start.sh";
    document.getElementById("btn-pause").disabled = !running || paused;
    document.getElementById("btn-resume").disabled = !running || !paused;
    document.getElementById("btn-stop").disabled = !running;

    // Agent backend pill
    const agentEl = document.getElementById("orc-agent");
    if (agentEl) {
        if (agentReady) {
            agentEl.textContent = "online";
            agentEl.className = "dot-good";
        } else {
            agentEl.textContent = "offline";
            agentEl.className = "dot-bad";
        }
    }

    // Status pills
    const runEl = document.getElementById("orc-running");
    runEl.textContent = running ? (paused ? "paused" : "yes") : "no";
    runEl.className = running && !paused ? "dot-good" : "dot-bad";

    document.getElementById("orc-turn").textContent = orc && orc.turn_count != null ? orc.turn_count : "–";

    const snap = (orc && orc.plan_snapshot) || {};
    document.getElementById("orc-total").textContent =
        snap.beamtime_total_hours != null ? snap.beamtime_total_hours.toFixed(1) : "–";
    document.getElementById("orc-elapsed").textContent =
        snap.beamtime_elapsed_hours != null ? snap.beamtime_elapsed_hours.toFixed(2) : "–";
    document.getElementById("orc-samples-done").textContent =
        snap.samples_completed != null ? snap.samples_completed : "–";
    document.getElementById("orc-samples-total").textContent =
        snap.samples_total != null ? snap.samples_total : "–";

    // Current phase
    const curPhaseEl = document.getElementById("cur-phase");
    if (orc && orc.phase) curPhaseEl.textContent = orc.phase;

    // Agent summary — show a pending placeholder while the first
    // turn is in flight so Start doesn't look silent. Each LLM round
    // can take 10–30s depending on context size.
    const summary = document.getElementById("latest-summary");
    if (orc && orc.last_summary) {
        summary.textContent = orc.last_summary;
    } else if (running && !paused) {
        summary.innerHTML =
            '<div class="muted">Agent is preparing the first turn — ' +
            'this can take up to ~30s while the LLM loads phase context…</div>';
    }

    if (!dash) {
        // No experiment selected — still render the config tile's empty state
        renderConfigTile(null);
        return;
    }

    // Per-phase enable switches — let the operator skip whole phases
    // (e.g. "already aligned this morning, skip beamline_alignment").
    // Disabled phases auto-pass their preconditions.
    const skipped = new Set(
        (dash.plan && dash.plan.plan && dash.plan.plan.phases_skipped) || [],
    );
    ["beamline_alignment", "xes_alignment", "sample_alignment", "collection"].forEach(p => {
        renderPhaseEnableToggle(p, !skipped.has(p));
    });

    // Plan table (dashboard has a compact read-only table; planning page
    // renders its own richer version via the onAutonomyRendered hook).
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

    // Remember current queue order for moveSample
    window.__planQueue = queue;
    window.__planExpId = expId;

    // Action tape
    const actionsEl = document.getElementById("action-tape");
    const actions = dash.action_log || [];
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

    // Interventions — structured, kind-driven copy.
    // The *title* and *instruction* come from INTERVENTION_KINDS,
    // NOT from the LLM. The agent's free-form detail is shown in a
    // clearly-labelled subordinate section so the user can see what
    // the model said without having to trust it for the action.
    const banner = document.getElementById("interventions-banner");
    const interventions = dash.interventions || [];
    if (interventions.length) {
        banner.style.display = "block";
        // Skip the DOM rewrite if the set of interventions hasn't
        // changed. Otherwise every 3s poll would collapse any <details>
        // the operator just expanded.
        const sig = interventions
            .map(iv => `${iv.id}|${iv.kind}|${iv.detail || ""}`)
            .join("\u241E");
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

    // Guidance feed
    const feed = document.getElementById("guidance-feed");
    const guidance = dash.guidance || [];
    if (guidance.length) {
        feed.innerHTML = guidance.slice(0, 30).map(g => `
            <div class="row">
                <span class="who">${escapeHtml(g.author || "?")}</span>
                <span class="when">${escapeHtml((g.timestamp || "").replace("T", " ").slice(0, 19))}</span>
                <div>${escapeHtml(g.text)}</div>
            </div>
        `).join("");
    } else {
        feed.innerHTML = '<div class="muted">No guidance yet.</div>';
    }

    // Phase tiles (skip the config tile — it's handled by renderConfigTile)
    document.querySelectorAll('.phase-tile:not([data-phase="config"])').forEach(tile => {
        const key = tile.getAttribute("data-phase");
        const matching = (dash.phase_runs || []).filter(r => r.phase === key || r.phase === key.replace("_alignment","_align"));
        const latest = matching[matching.length - 1];
        if (latest) {
            const status = latest.status || "pending";
            setTileStatus(tile, status);
            const badge = tile.querySelector(".tile-status-badge");
            badge.textContent = status;
            badge.className = "tile-status-badge badge-" + status;
        }
    });
    // Current phase highlighting
    if (orc && orc.phase) {
        document.querySelectorAll('.phase-tile:not([data-phase="config"])').forEach(t => {
            t.style.outline = t.getAttribute("data-phase") === orc.phase
                ? "2px solid var(--accent, #9b1b30)" : "";
        });
    }

    // Config tile + exp info. `elements` arrives at the top level of the
    // dashboard payload, not nested under `experiment`, so fold it in.
    const expForTile = dash.experiment
        ? { ...dash.experiment, elements: (dash.elements || []).map((e) => e.symbol).filter(Boolean) }
        : null;
    renderConfigTile(expForTile);
    if (dash.experiment) {
        const setText = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = val;
        };
        setText("exp-experimenter", dash.experiment.experimenter || "--");
        setText(
            "exp-crystal",
            (typeof formatCrystal === "function"
                ? formatCrystal(dash.experiment.mono_crystal)
                : (dash.experiment.mono_crystal || "--")),
        );
        setText(
            "exp-beam",
            `H:${dash.experiment.beam_size_h || "?"} V:${dash.experiment.beam_size_v || "?"}`,
        );
        setText("exp-env", dash.experiment.sample_env || "--");
        setText("exp-status", dash.experiment.status || "--");
    }

    // Allow pages that embed this script (e.g. /sample_planning) to render
    // their own richer views of the same orc+dash payloads.
    if (typeof window !== "undefined" && typeof window.onAutonomyRendered === "function") {
        try { window.onAutonomyRendered(orc, dash); } catch (e) { console.warn(e); }
    }
}

function currentAuthor() {
    return localStorage.getItem("plan-author") || "web-user";
}

function summarizePayload(action, payload) {
    if (!payload) return "";
    if (action === "extend_budget") {
        const d = payload.hours_delta, n = payload.new_total_hours;
        return `<span class="muted">${d != null ? (d >= 0 ? "+" : "") + d + "h" : ""}${n != null ? ` → total ${n}h` : ""}</span>`;
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

async function extendBudget(hours) {
    const reason = hours < 0
        ? prompt(`Trim ${Math.abs(hours)}h from budget. Reason? (optional)`, "")
        : prompt(`Extend budget by ${hours}h. Reason? (optional)`, "");
    if (reason === null) return;
    await planPost("extend_budget", { hours, reason: reason || undefined });
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

async function postStatusUpdate() {
    const text = prompt("Status text to post to Chat channel:");
    if (!text) return;
    try {
        const r = await fetch(API + "/api/slack/status", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text }),
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) {
            alert("Error: " + (j.detail || j.error || r.status));
            return;
        }
        alert("Posted!");
    } catch (e) {
        alert("Post failed: " + (e && e.message ? e.message : e));
    }
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

async function resetRun() {
    if (!confirm(
        "Reset this run?\n\n" +
        "• Agent stops immediately\n" +
        "• Action history cleared (prior rows kept as audit, hidden from re-run guards)\n" +
        "• Pending interventions resolved\n" +
        "• Phase → setup\n\n" +
        "Experiment config and sample plan are kept."
    )) return;
    const expSel = document.getElementById("experiment-select");
    const expId = expSel ? expSel.value : "";
    try {
        const r = await fetch(API + "/api/orchestrator/reset", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ experiment_id: expId }),
        });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) {
            alert("Reset failed: " + (j.detail || j.error || r.status));
            return;
        }
    } catch (e) {
        alert("Reset failed: " + (e && e.message ? e.message : e));
        return;
    }
    refreshAutonomy();
}

function renderPhaseEnableToggle(phase, enabled) {
    const column = document.querySelector(`.phase-column[data-phase-col="${phase}"]`)
        || document.querySelector(`.phase-tile[data-phase="${phase}"]`)?.parentElement;
    if (!column) return;
    let toggle = column.querySelector(".phase-enable-toggle");
    if (!toggle) {
        toggle = document.createElement("label");
        toggle.className = "phase-enable-toggle";
        toggle.innerHTML = `
            <input type="checkbox" />
            <span class="phase-enable-label">run this phase</span>
        `;
        const tile = column.querySelector(".phase-tile");
        if (tile) column.insertBefore(toggle, tile);
        else column.appendChild(toggle);
        toggle.querySelector("input").addEventListener("change", (e) => {
            e.stopPropagation();
            togglePhaseEnabled(phase, e.target.checked);
        });
        // Don't let clicks on the toggle bubble to the tile onclick.
        toggle.addEventListener("click", e => e.stopPropagation());
    }
    const cb = toggle.querySelector("input");
    cb.checked = enabled;
    toggle.classList.toggle("phase-disabled", !enabled);
    const tile = column.querySelector(".phase-tile");
    if (tile) tile.classList.toggle("phase-tile-skipped", !enabled);
}

async function togglePhaseEnabled(phase, enabled) {
    const expSel = document.getElementById("experiment-select");
    const expId = expSel ? expSel.value : "";
    if (!expId) return;
    try {
        await fetch(API + "/api/plan/set_phase_enabled", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                experiment_id: expId, phase, enabled, author: "web-user",
            }),
        });
    } catch (e) {
        console.error("toggle phase failed", e);
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

// Structural content for each intervention kind the agent may raise.
// The TITLE + INSTRUCTION come from *here*, not from the agent — so
// the user never has to trust the LLM's prose for "what do I do
// next." The agent's own `detail` string is shown separately,
// clearly labelled, so the user can see what it said but doesn't
// need it to act. If the agent invents a kind we don't know, we
// fall back to the generic "Please review" framing and surface the
// agent text prominently.
const INTERVENTION_KINDS = {
    crystal_install: {
        level: "success",
        icon: "✓",
        title: "Beamline alignment complete",
        instruction:
            "Install the crystals for this experiment, then click " +
            "\u201CDone \u2014 continue\u201D so the agent can start " +
            "spectrometer alignment.",
    },
    sample_mount: {
        level: "action",
        icon: "●",
        title: "Ready for sample mount",
        instruction:
            "Mount the sample(s) in the holder, then click \u201CDone " +
            "\u2014 continue\u201D.",
    },
    foil_swap: {
        level: "action",
        icon: "●",
        title: "Reference foil swap needed",
        instruction:
            "Install the correct reference foil, then click \u201CDone " +
            "\u2014 continue\u201D.",
    },
    gap_ownership: {
        level: "action",
        icon: "●",
        title: "Gap ownership transfer needed",
        instruction:
            "Take gap ownership for this hutch, then click \u201CDone " +
            "\u2014 continue\u201D.",
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
            "its message below, then either continue (if you\u2019re " +
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
            "The agent raised an intervention of a kind we don\u2019t " +
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

// Start polling
document.addEventListener("DOMContentLoaded", () => {
    wirePlanAuthor();
    refreshAutonomy();
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
