/* Autonomy dashboard add-on: orchestrator control, plan, actions,
   interventions, guidance, chat. Polls /api/orchestrator/status +
   /api/dashboard/status. */

const API = "";
const POLL_MS = 3000;

let pollTimer = null;

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
            await r.json();
        } else {
            await fetch(API + `/api/orchestrator/${kind}`, { method: "POST" });
        }
    } catch (e) {
        console.error(e);
    }
    refreshAutonomy();
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

async function sendChat() {
    const input = document.getElementById("chat-input");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    appendChat("user", text);
    try {
        const r = await fetch(API + "/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: text }),
        });
        const j = await r.json();
        appendChat("assistant", j.response || j.error || "(no response)");
    } catch (e) {
        appendChat("assistant", "Error: " + e);
    }
}

function appendChat(role, text) {
    const log = document.getElementById("chat-log");
    const el = document.createElement("div");
    el.className = "chat-msg " + role;
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
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
    document.getElementById("btn-start").disabled = running;
    document.getElementById("btn-pause").disabled = !running || paused;
    document.getElementById("btn-resume").disabled = !running || !paused;
    document.getElementById("btn-stop").disabled = !running;

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

    // Agent summary
    const summary = document.getElementById("latest-summary");
    if (orc && orc.last_summary) {
        summary.textContent = orc.last_summary;
    }

    if (!dash) return;

    // Plan table
    const tbody = document.getElementById("plan-tbody");
    const queue = (dash.plan && dash.plan.plan && dash.plan.plan.sample_queue) || [];
    const expId = expSel ? expSel.value : "";
    if (queue.length) {
        tbody.innerHTML = queue.map((s, i) => {
            const sid = s.sample_id;
            const disableMove = "";
            const first = i === 0 ? "disabled" : "";
            const last = i === queue.length - 1 ? "disabled" : "";
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
                <td class="row-actions">
                    <button ${first} title="Move up" onclick="moveSample('${sid}', -1)">↑</button>
                    <button ${last} title="Move down" onclick="moveSample('${sid}', 1)">↓</button>
                    <button title="Skip this sample" onclick="skipSample('${sid}')">Skip</button>
                    <button class="danger" title="Remove from plan" onclick="removeSample('${sid}')">✕</button>
                </td>
            </tr>`;
        }).join("");
    } else {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#888">No samples in plan yet — either start an experiment or add one below.</td></tr>';
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

    // Interventions
    const banner = document.getElementById("interventions-banner");
    const interventions = dash.interventions || [];
    if (interventions.length) {
        banner.style.display = "block";
        banner.innerHTML = interventions.map(iv => `
            <div class="intervention-row">
                <div>
                    <div class="kind">${escapeHtml(iv.kind)}</div>
                    <div>${escapeHtml(iv.detail)}</div>
                </div>
                <div class="btns">
                    <button onclick="resolveIntervention('${iv.id}', 'resolved')">Mark complete</button>
                    <button class="secondary" onclick="resolveIntervention('${iv.id}', 'denied')">Cancel</button>
                </div>
            </div>
        `).join("");
    } else {
        banner.style.display = "none";
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

    // Phase tiles
    const phaseKeys = {
        "beamline_alignment": "beamline_alignment",
        "xes_alignment": "xes_alignment",
        "sample_alignment": "sample_alignment",
        "collection": "collection",
    };
    document.querySelectorAll(".phase-tile").forEach(tile => {
        const key = tile.getAttribute("data-phase");
        const matching = (dash.phase_runs || []).filter(r => r.phase === key || r.phase === key.replace("_alignment","_align"));
        const latest = matching[matching.length - 1];
        if (latest) {
            tile.setAttribute("data-status", latest.status || "pending");
            const badge = tile.querySelector(".tile-status-badge");
            badge.textContent = latest.status || "pending";
            badge.className = "tile-status-badge badge-" + (latest.status || "pending");
        }
    });
    // Current phase highlighting
    if (orc && orc.phase) {
        document.querySelectorAll(".phase-tile").forEach(t => {
            t.style.outline = t.getAttribute("data-phase") === orc.phase
                ? "2px solid var(--accent, #9b1b30)" : "";
        });
    }

    // Exp info
    if (dash.experiment) {
        document.getElementById("exp-experimenter").textContent = dash.experiment.experimenter || "--";
        document.getElementById("exp-crystal").textContent = dash.experiment.mono_crystal || "--";
        document.getElementById("exp-beam").textContent =
            `H:${dash.experiment.beam_size_h || "?"} V:${dash.experiment.beam_size_v || "?"}`;
        document.getElementById("exp-env").textContent = dash.experiment.sample_env || "--";
        document.getElementById("exp-status").textContent = dash.experiment.status || "--";
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

function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
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

async function loadCapabilities() {
    const toolsEl = document.getElementById("caps-tools");
    const refsEl = document.getElementById("caps-refs");
    if (!toolsEl || !refsEl) return;
    try {
        const r = await fetch(API + "/api/tools");
        const j = await r.json();
        const cats = j.categories || [];
        toolsEl.innerHTML = cats.map(cat => `
            <li class="caps-cat">
                <div class="caps-cat-name">${escapeHtml(cat.category)}</div>
                <ul class="caps-sublist">
                    ${(cat.tools || []).map(t => `
                        <li title="${escapeHtml(t.description || "")}">
                            <code>${escapeHtml(t.name)}</code>
                            <span class="caps-desc">${escapeHtml((t.description || "").split("\n")[0].slice(0, 110))}</span>
                        </li>`).join("")}
                </ul>
            </li>
        `).join("") || '<li class="muted">No tools registered.</li>';
        refsEl.innerHTML = (j.references || []).map(r => `
            <li title="${escapeHtml(r.description || "")}">
                <code>${escapeHtml(r.name)}</code>
                <span class="caps-desc">${escapeHtml((r.description || "").slice(0, 140))}</span>
            </li>
        `).join("") || '<li class="muted">No reference docs.</li>';
    } catch (e) {
        toolsEl.innerHTML = '<li class="muted">Failed to load tools.</li>';
        refsEl.innerHTML = '';
    }
}

function wireCapabilitiesToggle() {
    const btn = document.getElementById("caps-toggle");
    const body = document.getElementById("caps-body");
    const arrow = document.getElementById("caps-arrow");
    if (!btn || !body) return;
    let loaded = false;
    btn.addEventListener("click", () => {
        const open = body.hasAttribute("hidden");
        if (open) {
            body.removeAttribute("hidden");
            btn.setAttribute("aria-expanded", "true");
            if (arrow) arrow.style.transform = "rotate(90deg)";
            if (!loaded) { loadCapabilities(); loaded = true; }
        } else {
            body.setAttribute("hidden", "");
            btn.setAttribute("aria-expanded", "false");
            if (arrow) arrow.style.transform = "";
        }
    });
}

// Start polling
document.addEventListener("DOMContentLoaded", () => {
    wirePlanAuthor();
    wireCapabilitiesToggle();
    refreshAutonomy();
    pollTimer = setInterval(refreshAutonomy, POLL_MS);
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
