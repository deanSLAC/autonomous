/* /sample_planning — rich plan editor layered on top of autonomy.js.
 * Uses the `window.onAutonomyRendered` hook to render our own table,
 * and adds per-sample + per-holder + budget + regenerate endpoints. */

let _spActiveSampleId = null;
let _spPlanEntries = [];
let _spHolders = [];

function spEsc(s) {
    if (s == null) return "";
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function spAuthor() {
    return localStorage.getItem("plan-author") || "web-user";
}

function spGetExpId() {
    const sel = document.getElementById("experiment-select");
    return sel ? sel.value : "";
}

async function spFetchJson(url, opts) {
    try {
        const r = await fetch(url, opts);
        const j = await r.json().catch(() => ({}));
        if (!r.ok) {
            alert(j.detail || j.error || `HTTP ${r.status}`);
            return null;
        }
        return j;
    } catch (e) {
        alert(`Request failed: ${e}`);
        return null;
    }
}

async function spPost(path, body) {
    const expId = spGetExpId();
    if (!expId) { alert("Select an experiment first."); return null; }
    const result = await spFetchJson(`/api/plan/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, experiment_id: expId, author: spAuthor() }),
    });
    if (result && typeof refreshAutonomy === "function") refreshAutonomy();
    return result;
}

// --- Budget panel -----------------------------------------------------------

async function spSetBudget() {
    const hrs = parseFloat(document.getElementById("budget-hours").value);
    if (isNaN(hrs) || hrs < 0) { alert("Enter a non-negative number of hours."); return; }
    await spPost("set_budget", { hours_total: hrs });
}

async function spExtendBudget(delta) {
    const note = delta < 0
        ? prompt(`Trim ${Math.abs(delta)}h. Reason? (optional)`, "")
        : prompt(`Add ${delta}h. Reason? (optional)`, "");
    if (note === null) return;
    await spPost("extend_budget", { hours: delta, reason: note || undefined });
}

async function spUpdateThresholds() {
    const snr = parseFloat(document.getElementById("snr-target").value);
    const reps = parseInt(document.getElementById("min-reps").value, 10);
    const body = {};
    if (!isNaN(snr)) body.snr_target = snr;
    if (!isNaN(reps)) body.min_reps_per_sample = reps;
    if (!Object.keys(body).length) { alert("Nothing to apply."); return; }
    await spPost("update_thresholds", body);
}

// --- Holder budget ----------------------------------------------------------

async function spSetHolderBudget() {
    const holder = document.getElementById("holder-budget-select").value || null;
    const mode = document.getElementById("holder-budget-mode").value || null;
    const ct = parseFloat(document.getElementById("holder-budget-ct").value);
    const reps = parseInt(document.getElementById("holder-budget-reps").value, 10);
    const apply = document.getElementById("holder-budget-apply").checked;
    const body = { holder_id: holder, mode, apply_to_existing: apply };
    if (!isNaN(ct)) body.count_time_s = ct;
    if (!isNaN(reps)) body.reps = reps;
    if (body.count_time_s == null && body.reps == null) {
        alert("Set at least a count time or reps."); return;
    }
    const reason = prompt("Optional reason to log:", "") || undefined;
    if (reason !== undefined) body.reason = reason;
    await spPost("set_holder_time_budget", body);
}

// --- Per-sample editor ------------------------------------------------------

function spOpenSampleEditor(sampleId) {
    _spActiveSampleId = sampleId;
    const entry = _spPlanEntries.find(s => s.sample_id === sampleId);
    const panel = document.getElementById("sample-editor-panel");
    if (!panel) return;
    panel.style.display = "";
    document.getElementById("sample-editor-sub").textContent =
        entry ? `${entry.sample_name} (${entry.element_symbol})` : sampleId;
    // Pre-fill current values from first mode
    const firstMode = (entry && entry.modes && entry.modes[0]) || {};
    document.getElementById("sample-budget-mode").value = firstMode.mode || "";
    document.getElementById("sample-budget-ct").value = firstMode.count_time_s ?? "";
    document.getElementById("sample-budget-reps").value = firstMode.reps ?? "";
    document.getElementById("sample-budget-reason").value = "";
    document.querySelectorAll("#plan-tbody-sp tr").forEach(tr => {
        tr.classList.toggle("active-sample", tr.dataset.sampleId === sampleId);
    });
}

function spCloseSampleEditor() {
    _spActiveSampleId = null;
    const panel = document.getElementById("sample-editor-panel");
    if (panel) panel.style.display = "none";
    document.querySelectorAll("#plan-tbody-sp tr.active-sample")
        .forEach(tr => tr.classList.remove("active-sample"));
}

async function spApplySampleBudget() {
    if (!_spActiveSampleId) { alert("Click a sample row first."); return; }
    const ct = parseFloat(document.getElementById("sample-budget-ct").value);
    const reps = parseInt(document.getElementById("sample-budget-reps").value, 10);
    const mode = document.getElementById("sample-budget-mode").value || null;
    const reason = document.getElementById("sample-budget-reason").value.trim();
    const body = { sample_id: _spActiveSampleId, mode };
    if (!isNaN(ct)) body.count_time_s = ct;
    if (!isNaN(reps)) body.reps = reps;
    if (body.count_time_s == null && body.reps == null) {
        alert("Set at least a count time or reps."); return;
    }
    if (reason) body.reason = reason;
    await spPost("set_sample_time_budget", body);
}

// --- Add sample + regenerate ------------------------------------------------

function spOpenAddSample() {
    document.getElementById("add-sample-inline-sp").style.display = "flex";
    document.getElementById("sp-add-sample-name").focus();
}
function spCloseAddSample() {
    document.getElementById("add-sample-inline-sp").style.display = "none";
}

async function spSubmitAddSample() {
    const name = document.getElementById("sp-add-sample-name").value.trim();
    const elem = document.getElementById("sp-add-sample-element").value.trim();
    if (!name || !elem) { alert("Sample name and element are required."); return; }
    const reps = parseInt(document.getElementById("sp-add-sample-reps").value || "6", 10);
    const ct = parseFloat(document.getElementById("sp-add-sample-time").value || "0.5");
    const posRaw = document.getElementById("sp-add-sample-pos").value.trim();
    const position = posRaw === "" ? null : Math.max(0, parseInt(posRaw, 10) - 1);
    const reason = document.getElementById("sp-add-sample-reason").value.trim();
    const modes = [{ mode: "xas", reps, count_time_s: ct }];
    const ok = await spPost("add_sample", {
        sample_name: name,
        element_symbol: elem,
        modes,
        position,
        reason: reason || undefined,
    });
    if (ok) {
        document.getElementById("sp-add-sample-name").value = "";
        document.getElementById("sp-add-sample-element").value = "";
        document.getElementById("sp-add-sample-pos").value = "";
        document.getElementById("sp-add-sample-reason").value = "";
        spCloseAddSample();
    }
}

async function spRegeneratePlan() {
    if (!confirm("Rebuild the plan from the DB? Sample-level progress is preserved, but samples not in any holder will be removed.")) return;
    const reason = prompt("Why regenerate? (optional)", "") || undefined;
    await spPost("regenerate", { reason });
}

// --- Plan table rendering (hooks into autonomy.js) --------------------------

function spRenderPlan(orc, dash) {
    const tbody = document.getElementById("plan-tbody-sp");
    if (!tbody) return;
    const plan = dash && dash.plan && dash.plan.plan;
    const queue = (plan && plan.sample_queue) || [];
    _spPlanEntries = queue;
    _spHolders = (plan && plan.holders) || [];

    // Update holder select + add-sample position limit
    const holderSel = document.getElementById("holder-budget-select");
    if (holderSel) {
        const current = holderSel.value;
        holderSel.innerHTML = '<option value="">All holders</option>' +
            _spHolders.map(h => `<option value="${spEsc(h.id)}">${spEsc(h.name || h.id)}</option>`).join("");
        holderSel.value = current;
    }

    // Budget field (only overwrite if the user isn't editing it)
    const budgetInput = document.getElementById("budget-hours");
    if (budgetInput && document.activeElement !== budgetInput) {
        const total = dash && dash.plan && dash.plan.beamtime_total_hours;
        if (total != null) budgetInput.value = total;
    }

    // Thresholds
    if (plan && plan.thresholds) {
        const snrEl = document.getElementById("snr-target");
        const repsEl = document.getElementById("min-reps");
        if (snrEl && document.activeElement !== snrEl && plan.thresholds.snr_target != null) {
            snrEl.value = plan.thresholds.snr_target;
        }
        if (repsEl && document.activeElement !== repsEl && plan.thresholds.min_reps_per_sample != null) {
            repsEl.value = plan.thresholds.min_reps_per_sample;
        }
    }

    if (queue.length) {
        tbody.innerHTML = queue.map((s, i) => {
            const sid = s.sample_id;
            const first = i === 0 ? "disabled" : "";
            const last = i === queue.length - 1 ? "disabled" : "";
            const modes = s.modes || [];
            const modeLabel = modes.map(m => m.mode).join(", ") || "—";
            const ctLabel = modes.length
                ? modes.map(m => m.count_time_s != null ? Number(m.count_time_s).toFixed(2) : "–").join(" / ")
                : "–";
            const repsLabel = modes.length
                ? modes.map(m => m.reps != null ? m.reps : "–").join(" / ")
                : "–";
            const holderName = (_spHolders.find(h => h.id === s.holder_id) || {}).name || (s.holder_id || "—");
            const isActive = sid === _spActiveSampleId ? " active-sample" : "";
            return `<tr class="plan-row${isActive}" data-sample-id="${spEsc(sid)}">
                <td>${i + 1}</td>
                <td class="editable-cell" onclick="spOpenSampleEditor('${spEsc(sid)}')">
                    <span class="sample-name">${spEsc(s.sample_name)}</span>
                </td>
                <td>${spEsc(s.element_symbol)}</td>
                <td>${spEsc(holderName)}</td>
                <td>${spEsc(modeLabel)}</td>
                <td class="editable-cell" onclick="spOpenSampleEditor('${spEsc(sid)}')">${ctLabel}</td>
                <td class="editable-cell" onclick="spOpenSampleEditor('${spEsc(sid)}')">${repsLabel}</td>
                <td><span class="plan-status-pill ${s.status || "queued"}">${s.status || "queued"}</span></td>
                <td>${s.snr_estimate != null ? Number(s.snr_estimate).toFixed(1) : "–"}</td>
                <td>${s.efficiency_verdict || "–"}</td>
                <td class="row-actions">
                    <button ${first} title="Move up" onclick="moveSample('${spEsc(sid)}', -1)">↑</button>
                    <button ${last} title="Move down" onclick="moveSample('${spEsc(sid)}', 1)">↓</button>
                    <button title="Skip this sample" onclick="skipSample('${spEsc(sid)}')">Skip</button>
                    <button class="danger" title="Remove from plan" onclick="removeSample('${spEsc(sid)}')">✕</button>
                </td>
            </tr>`;
        }).join("");
    } else {
        tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;color:#888">No samples in plan yet — configure a sample holder under /config, then start the run.</td></tr>';
    }
}

window.onAutonomyRendered = spRenderPlan;

// Wire the plan-author click in the sample-planning panel-sub
document.addEventListener("DOMContentLoaded", () => {
    const el = document.getElementById("plan-author-sp");
    if (el) {
        const label = () => `as ${spAuthor()}`;
        el.textContent = label();
        el.style.cursor = "pointer";
        el.addEventListener("click", () => {
            const name = prompt("Attribute plan edits to:", spAuthor());
            if (name) {
                localStorage.setItem("plan-author", name.trim());
                el.textContent = label();
            }
        });
    }
});
