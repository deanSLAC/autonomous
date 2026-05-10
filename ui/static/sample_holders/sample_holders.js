/* /sample_holders — list, edit, reorder, delete, and link to viewer.
 *
 * Reuses form.js helpers (addSample, buildElementOptions,
 * gatherSampleHolderData). We keep the per-sample container id equal to
 * form.js's convention (`samples-container`) so those helpers find it. */

let _shCurrentHolderId = null;
let _shHolders = [];
let _shElements = [];

function shEsc(s) {
    if (s == null) return "";
    return String(s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function shGetExpId() {
    const sel = document.getElementById("experiment-select");
    return sel ? sel.value : "";
}

function shMessage(html) {
    const el = document.getElementById("message-area");
    if (el) el.innerHTML = html;
}

async function shFetchJson(url, opts) {
    try {
        const r = await fetch(url, opts);
        const j = await r.json().catch(() => ({}));
        if (!r.ok) {
            alert(j.detail || (j.errors && j.errors.join(", ")) || j.error || `HTTP ${r.status}`);
            return null;
        }
        return j;
    } catch (e) { alert(`Request failed: ${e}`); return null; }
}

async function shLoadHolders() {
    const expId = shGetExpId();
    if (!expId) {
        document.getElementById("holder-tbody").innerHTML =
            '<tr><td colspan="7" style="text-align:center;color:#888">Select an experiment.</td></tr>';
        return;
    }
    const j = await shFetchJson(`/api/sample_holders/list?experiment_id=${encodeURIComponent(expId)}`);
    if (!j) return;
    _shHolders = j.holders || [];
    shRenderHolderList();
}

function shRenderHolderList() {
    const tbody = document.getElementById("holder-tbody");
    const summary = document.getElementById("holder-summary");
    if (!tbody) return;
    if (!_shHolders.length) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#888">No sample holders yet — create one below.</td></tr>';
        summary.textContent = "0 holders";
        return;
    }
    const activeHolder = _shHolders.find(h => h.status !== "done");
    tbody.innerHTML = _shHolders.map((h, i) => {
        const isActive = activeHolder && activeHolder.id === h.id;
        const first = i === 0 ? "disabled" : "";
        const last = i === _shHolders.length - 1 ? "disabled" : "";
        const isDone = h.status === "done";
        const viewLink = `/viewer?holder_id=${encodeURIComponent(h.id)}&experiment_id=${encodeURIComponent(h.experiment_id)}`;
        return `<tr class="${isActive ? "active-row" : ""}">
            <td>${i + 1}${isActive ? " <span class='muted'>(active)</span>" : ""}</td>
            <td><strong>${shEsc(h.name)}</strong></td>
            <td>${shEsc(h.holder_type)}</td>
            <td><span class="holder-status-pill ${shEsc(h.status)}">${shEsc(h.status)}</span></td>
            <td>${h.n_samples ?? 0}</td>
            <td>${h.beamtime_hours != null ? h.beamtime_hours + " h" : "<span class='muted'>—</span>"}</td>
            <td class="row-actions">
                <button ${first} title="Move up" onclick="shMoveHolder('${shEsc(h.id)}', -1)">↑</button>
                <button ${last} title="Move down" onclick="shMoveHolder('${shEsc(h.id)}', 1)">↓</button>
                <button onclick="shEditHolder('${shEsc(h.id)}')">Edit</button>
                <a href="${viewLink}" title="View alignment scans and spectra from this holder">View data</a>
                <button class="danger" onclick="shConfirmDelete('${shEsc(h.id)}')">✕</button>
            </td>
        </tr>`;
    }).join("");
    summary.textContent = `${_shHolders.length} holder(s)` + (activeHolder ? ` · active: ${activeHolder.name}` : "");
}

async function shMoveHolder(holderId, delta) {
    const ids = _shHolders.map(h => h.id);
    const idx = ids.indexOf(holderId);
    if (idx < 0) return;
    const newIdx = Math.max(0, Math.min(ids.length - 1, idx + delta));
    if (newIdx === idx) return;
    ids.splice(idx, 1);
    ids.splice(newIdx, 0, holderId);
    const j = await shFetchJson("/api/sample_holders/reorder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ experiment_id: shGetExpId(), order: ids }),
    });
    if (j) shLoadHolders();
}

async function shConfirmDelete(holderId) {
    const h = _shHolders.find(x => x.id === holderId);
    if (!h) return;
    if (!confirm(`Delete holder "${h.name}" and all ${h.n_samples} samples inside it? This cannot be undone.`)) return;
    const j = await shFetchJson("/api/sample_holders/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ holder_id: holderId }),
    });
    if (j) {
        if (_shCurrentHolderId === holderId) shCloseEditor();
        shLoadHolders();
    }
}

// ---- Editor --------------------------------------------------------------

async function shLoadElements() {
    const expId = shGetExpId();
    if (!expId) return;
    try {
        const r = await fetch(`/api/experiment_summary/${encodeURIComponent(expId)}`);
        const j = await r.json();
        if (j && j.success) {
            _shElements = j.elements || [];
            if (typeof window !== "undefined") window._cachedElements = _shElements;
        }
    } catch {}
}

function shClearSamplesContainer() {
    const c = document.getElementById("samples-container");
    if (c) c.innerHTML = "";
    // form.js's `sampleCount` is a script-scope counter used to mint
    // unique IDs. Clearing the container is enough — the counter may
    // keep climbing, but the generated IDs stay unique.
}

function shNewHolder() {
    _shCurrentHolderId = null;
    document.getElementById("holder-editor-title").textContent = "New holder";
    document.getElementById("holder-editor-sub").textContent = "Appended to end of queue";
    document.getElementById("sh-holder-name").value = "";
    document.getElementById("sh-holder-type").value = "flat";
    document.getElementById("sh-holder-status").value = "configured";
    document.getElementById("sh-holder-notes").value = "";
    document.getElementById("sh-beamtime-hours").value = "";
    shClearSamplesContainer();
    if (typeof addSample === "function") addSample();
    document.getElementById("sh-delete-btn").style.display = "none";
    document.getElementById("holder-editor-panel").style.display = "";
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}

async function shEditHolder(holderId) {
    _shCurrentHolderId = holderId;
    const j = await shFetchJson(`/api/sample_holders/${encodeURIComponent(holderId)}`);
    if (!j) return;
    document.getElementById("holder-editor-title").textContent = "Edit holder";
    document.getElementById("holder-editor-sub").textContent = `ID ${holderId}`;
    document.getElementById("sh-holder-name").value = j.name || "";
    document.getElementById("sh-holder-type").value = j.holder_type || "flat";
    document.getElementById("sh-holder-status").value = j.status || "configured";
    document.getElementById("sh-holder-notes").value = j.notes || "";
    document.getElementById("sh-beamtime-hours").value = (j.beamtime_hours != null) ? j.beamtime_hours : "";
    shClearSamplesContainer();
    (j.samples || []).forEach(s => {
        if (typeof addSample === "function") addSample(s);
    });
    document.getElementById("sh-delete-btn").style.display = "";
    document.getElementById("holder-editor-panel").style.display = "";
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}

function shCloseEditor() {
    _shCurrentHolderId = null;
    document.getElementById("holder-editor-panel").style.display = "none";
}

async function shSaveHolder() {
    const expId = shGetExpId();
    if (!expId) { alert("Select an experiment first."); return; }
    const name = document.getElementById("sh-holder-name").value.trim();
    if (!name) { alert("Holder name is required."); return; }
    const holderType = document.getElementById("sh-holder-type").value;
    const status = document.getElementById("sh-holder-status").value;
    const notes = document.getElementById("sh-holder-notes").value;
    const btRaw = document.getElementById("sh-beamtime-hours").value.trim();
    const beamtimeHours = btRaw === "" ? null : parseFloat(btRaw);

    const gathered = (typeof gatherSampleHolderData === "function") ? gatherSampleHolderData() : { samples: [] };
    const samples = gathered.samples || [];

    const body = {
        experiment_id: expId,
        name,
        holder_type: holderType,
        status,
        notes,
        beamtime_hours: beamtimeHours,
        samples,
    };
    let j;
    if (_shCurrentHolderId) {
        body.holder_id = _shCurrentHolderId;
        j = await shFetchJson("/api/sample_holders/update", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
    } else {
        j = await shFetchJson("/api/sample_holders/create", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
    }
    if (j && j.success) {
        shMessage(`<div class="success-box"><h3>Saved</h3><p>Holder saved. Plan regenerated to match.</p></div>`);
        _shCurrentHolderId = (j.holder && j.holder.id) || _shCurrentHolderId;
        shLoadHolders();
    }
}

async function shDeleteHolder() {
    if (!_shCurrentHolderId) return;
    await shConfirmDelete(_shCurrentHolderId);
}

// ---- Initialization ------------------------------------------------------

function shOnExperimentChange() {
    shLoadElements().then(() => shLoadHolders());
}

document.addEventListener("DOMContentLoaded", () => {
    if (typeof loadFormDefaults === "function") loadFormDefaults();
    const sel = document.getElementById("experiment-select");
    if (sel) sel.addEventListener("change", shOnExperimentChange);
    setTimeout(shOnExperimentChange, 400);
});
