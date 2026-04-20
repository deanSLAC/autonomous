/**
 * BL15-2 Dashboard — polling, rendering, navigation
 */

// ---- Theme toggle ----

(function initTheme() {
    const saved = localStorage.getItem("bl15-dashboard-theme");
    if (saved === "dark") {
        document.documentElement.setAttribute("data-theme", "dark");
    }
})();

function toggleTheme() {
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "dark" ? "light" : "dark";
    if (next === "dark") {
        document.documentElement.setAttribute("data-theme", "dark");
    } else {
        document.documentElement.removeAttribute("data-theme");
    }
    localStorage.setItem("bl15-dashboard-theme", next);
    // Update toggle button icon
    const btn = document.getElementById("theme-toggle");
    if (btn) btn.textContent = next === "dark" ? "\u2600" : "\u263E";
}

document.addEventListener("DOMContentLoaded", function() {
    const btn = document.getElementById("theme-toggle");
    if (btn) {
        btn.addEventListener("click", toggleTheme);
        // Set initial icon
        const isDark = document.documentElement.getAttribute("data-theme") === "dark";
        btn.textContent = isDark ? "\u2600" : "\u263E";
    }
});

const API_BASE = "";  // same origin
const POLL_INTERVAL = 5000;
let currentExperimentId = null;
let pollTimer = null;

// ---- Phase display names ----

const PHASE_NAMES = {
    bl_align: "Beamline Alignment",
    xes_align: "Spectrometer Alignment",
    spec_align: "Spectrometer Alignment",
    sample_align: "Sample Alignment",
    collection: "Data Collection",
};

const PHASE_ORDER = ["bl_align", "xes_align", "sample_align", "collection"];

// ---- Utility ----

function formatTime(isoStr) {
    if (!isoStr) return "--";
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDate(isoStr) {
    if (!isoStr) return "--";
    const d = new Date(isoStr);
    return d.toLocaleDateString([], { month: "short", day: "numeric" }) +
        " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDuration(startIso, endIso) {
    if (!startIso) return "--";
    const start = new Date(startIso);
    const end = endIso ? new Date(endIso) : new Date();
    const diffMs = end - start;
    const mins = Math.floor(diffMs / 60000);
    const secs = Math.floor((diffMs % 60000) / 1000);
    if (mins > 60) {
        const hrs = Math.floor(mins / 60);
        return `${hrs}h ${mins % 60}m`;
    }
    return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

function confidenceClass(conf) {
    if (conf === null || conf === undefined) return "";
    if (conf >= 0.7) return "confidence-high";
    if (conf >= 0.4) return "confidence-mid";
    return "confidence-low";
}

function fmt(val, decimals) {
    if (val === null || val === undefined) return "--";
    return Number(val).toFixed(decimals !== undefined ? decimals : 2);
}

// ---- Server health check ----

async function checkServer() {
    const dot = document.getElementById("server-dot");
    const label = document.getElementById("server-status");
    if (!dot || !label) return;
    try {
        const resp = await fetch(API_BASE + "/health", { signal: AbortSignal.timeout(3000) });
        if (resp.ok) {
            dot.className = "status-dot";
            label.textContent = "connected";
            try {
                const j = await resp.json();
                const pill = document.getElementById("sim-pill");
                if (pill) pill.style.display = j.simulation ? "inline-block" : "none";
            } catch { /* non-JSON ok */ }
        } else {
            dot.className = "status-dot offline";
            label.textContent = "error";
        }
    } catch {
        dot.className = "status-dot offline";
        label.textContent = "offline";
    }
}

// ---- Experiments dropdown ----

async function loadExperiments() {
    try {
        const resp = await fetch(API_BASE + "/api/dashboard/experiments");
        if (!resp.ok) return;
        const data = await resp.json();
        const sel = document.getElementById("experiment-select");
        if (!sel) return;
        sel.innerHTML = "";
        if (data.length === 0) {
            sel.innerHTML = '<option value="">No experiments</option>';
            return;
        }
        data.forEach((exp) => {
            const opt = document.createElement("option");
            opt.value = exp.id;
            opt.textContent = exp.name;
            sel.appendChild(opt);
        });
        // Default to first (most recent)
        if (!currentExperimentId && data.length > 0) {
            currentExperimentId = data[0].id;
        }
        sel.value = currentExperimentId;
    } catch { /* ignore */ }
}

function onExperimentChange(e) {
    currentExperimentId = e.target.value;
    refreshDashboard();
}

// ---- Main dashboard refresh ----

async function refreshDashboard() {
    if (!currentExperimentId) return;
    try {
        const resp = await fetch(
            API_BASE + "/api/dashboard/status?experiment_id=" + currentExperimentId
        );
        if (!resp.ok) return;
        const data = await resp.json();
        renderExperimentInfo(data.experiment);
        renderPhases(data.phases);
    } catch { /* ignore */ }
}

function formatCrystal(code) {
    if (!code) return "--";
    if (code === "A") return "A Si(111)";
    if (code === "B") return "B Si(311)";
    return code;
}
window.formatCrystal = formatCrystal;

function renderExperimentInfo(exp) {
    if (!exp) return;
    const set = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val || "--";
    };
    set("exp-experimenter", exp.experimenter);
    set("exp-crystal", formatCrystal(exp.mono_crystal));
    set("exp-beam", exp.mirrors_out ? "Mirrors out" : ("H:" + (exp.beam_size_h || "?") + " V:" + (exp.beam_size_v || "?")));
    set("exp-env", exp.sample_env || "ambient");
    set("exp-status", exp.status);
}

function renderPhases(phases) {
    // Build a map of phase -> latest run
    const phaseMap = {};
    (phases || []).forEach((p) => {
        const key = p.phase === "spec_align" ? "xes_align" : p.phase;
        // Keep the latest run per phase
        if (!phaseMap[key] || new Date(p.started_at) > new Date(phaseMap[key].started_at)) {
            phaseMap[key] = p;
        }
    });

    PHASE_ORDER.forEach((phaseKey) => {
        const tile = document.querySelector(`.phase-tile[data-phase="${phaseKey}"]`);
        if (!tile) return;

        const run = phaseMap[phaseKey];
        const status = run ? run.status : "pending";

        // Update status
        tile.dataset.status = status;
        tile.dataset.phaseRunId = run ? run.id : "";

        // Badge
        const badge = tile.querySelector(".tile-status-badge");
        badge.className = "tile-status-badge badge-" + status;
        badge.textContent = status;

        // Metrics
        const setField = (field, val) => {
            const el = tile.querySelector(`[data-field="${field}"]`);
            if (el) el.textContent = val !== undefined && val !== null ? val : "--";
        };

        if (run) {
            setField("scan_count", run.scan_count || 0);
            setField("iterations", run.max_iteration || "--");
            setField("llm_count", run.llm_count || 0);
            setField("anomaly_count", run.anomaly_count || 0);
            setField("crystal_count", run.crystal_count || "--");
            setField("sample_count", run.sample_count || "--");
            setField("technique_count", run.technique_count || "--");

            // Time
            if (status === "running") {
                setField("time", "started " + formatTime(run.started_at));
            } else if (status === "completed") {
                setField("time", formatDuration(run.started_at, run.completed_at));
            } else {
                setField("time", formatTime(run.started_at));
            }
        } else {
            setField("scan_count", "--");
            setField("time", "--");
        }
    });
}

// ---- Navigate to phase detail ----

function openPhase(tile) {
    const phaseRunId = tile.dataset.phaseRunId;
    const phase = tile.dataset.phase;
    if (phaseRunId) {
        window.location.href = "/phase?id=" + phaseRunId;
    } else {
        window.location.href = "/phase?phase=" + phase +
            "&experiment_id=" + currentExperimentId;
    }
}

// ---- Phase detail page ----

async function loadPhaseDetail(phaseRunId) {
    try {
        const resp = await fetch(API_BASE + "/api/dashboard/phase/" + phaseRunId);
        if (!resp.ok) return;
        const data = await resp.json();
        renderPhaseDetail(data);
    } catch { /* ignore */ }
}

async function loadPhaseByName(phase) {
    // Get experiment_id from URL params
    const params = new URLSearchParams(window.location.search);
    const expId = params.get("experiment_id");
    if (!expId) return;

    try {
        const resp = await fetch(
            API_BASE + "/api/dashboard/status?experiment_id=" + expId
        );
        if (!resp.ok) return;
        const data = await resp.json();
        const normalPhase = phase === "spec_align" ? "xes_align" : phase;
        const run = (data.phases || []).find(
            (p) => p.phase === phase || p.phase === normalPhase
        );
        if (run) {
            loadPhaseDetail(run.id);
        } else {
            renderEmptyPhase(phase);
        }
    } catch { /* ignore */ }
}

function renderEmptyPhase(phase) {
    const title = document.getElementById("detail-title");
    if (title) title.textContent = PHASE_NAMES[phase] || phase;
    const badge = document.getElementById("detail-badge");
    if (badge) {
        badge.className = "tile-status-badge badge-pending";
        badge.textContent = "pending";
    }
    const tbody = document.getElementById("scan-tbody");
    if (tbody) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No data yet for this phase.</td></tr>';
    }
}

function renderPhaseDetail(data) {
    const run = data.phase_run;
    const scans = data.scans || [];
    const phase = run.phase;

    // Title
    const titleEl = document.getElementById("detail-title");
    const pageTitle = document.getElementById("page-title");
    const name = PHASE_NAMES[phase] || phase;
    if (titleEl) titleEl.textContent = name;
    if (pageTitle) pageTitle.textContent = name;
    document.title = "BL15-2 — " + name;

    // Badge
    const badge = document.getElementById("detail-badge");
    if (badge) {
        badge.className = "tile-status-badge badge-" + run.status;
        badge.textContent = run.status;
    }

    // Summary
    const set = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val || "--";
    };
    set("sum-started", formatDate(run.started_at));
    set("sum-duration", formatDuration(run.started_at, run.completed_at));
    set("sum-scans", scans.length);
    set("sum-llm", scans.filter((s) => s.llm_consulted).length);
    set("sum-anomalies", scans.filter((s) => s.anomaly).length);
    set("sum-datafile", run.spec_datafile);

    // LLM assessment
    if (run.notes) {
        const box = document.getElementById("assessment-box");
        const text = document.getElementById("assessment-text");
        if (box && text) {
            text.textContent = run.notes;
            box.style.display = "";
        }
    }

    // Report image
    if (run.summary_image_path) {
        const container = document.getElementById("report-image-container");
        const img = document.getElementById("report-image");
        if (container && img) {
            img.src = "/api/dashboard/image?path=" + encodeURIComponent(run.summary_image_path);
            container.style.display = "";
        }
    }

    // Collection progress (for collection phase)
    if (phase === "collection" && data.collection_progress) {
        renderCollectionProgress(data.collection_progress);
    }

    // Scan table
    renderScanTable(scans);
}

function renderScanTable(scans) {
    const tbody = document.getElementById("scan-tbody");
    if (!tbody) return;

    if (scans.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No scans recorded.</td></tr>';
        return;
    }

    tbody.innerHTML = scans.map((s) => {
        const confClass = confidenceClass(s.decision_confidence);
        const llmClass = s.llm_consulted ? "llm-yes" : "";
        const anomalyClass = s.anomaly ? "anomaly" : "";
        return `<tr class="${anomalyClass}">
            <td>${s.scan_number}</td>
            <td>${s.motor_name}</td>
            <td>${s.iteration}</td>
            <td>${s.decision_action || "--"}</td>
            <td>${s.decision_command || "--"}</td>
            <td>${fmt(s.result_position)}</td>
            <td>${fmt(s.fwhm)}</td>
            <td class="${confClass}">${fmt(s.decision_confidence)}</td>
            <td class="${llmClass}">${s.llm_consulted ? "yes" : "--"}</td>
        </tr>`;
    }).join("");
}

function renderCollectionProgress(progress) {
    const container = document.getElementById("collection-progress");
    const grid = document.getElementById("collection-grid");
    if (!container || !grid) return;

    container.style.display = "";
    grid.innerHTML = progress.map((sample) => {
        const pct = sample.target > 0 ? Math.min(100, (sample.completed / sample.target) * 100) : 0;
        const doneClass = pct >= 100 ? "done" : "";
        return `<div class="sample-card">
            <div class="sample-card-name">${sample.name}</div>
            <div class="sample-card-element">${sample.element} ${sample.technique}</div>
            <div class="progress-bar-bg">
                <div class="progress-bar-fill ${doneClass}" style="width: ${pct}%"></div>
            </div>
            <div class="progress-label">${sample.completed} / ${sample.target} reps</div>
        </div>`;
    }).join("");
}

// ---- Initialization ----

function isMainDashboard() {
    return !window.location.pathname.includes("/phase");
}

async function init() {
    checkServer();

    if (isMainDashboard()) {
        await loadExperiments();
        refreshDashboard();

        const sel = document.getElementById("experiment-select");
        if (sel) sel.addEventListener("change", onExperimentChange);

        // Start polling
        pollTimer = setInterval(() => {
            checkServer();
            refreshDashboard();
        }, POLL_INTERVAL);
    } else {
        // Phase detail page — phase.js owns rendering + polling. Only
        // bother with the health dot here.
        setInterval(checkServer, POLL_INTERVAL);
    }
}

init();
