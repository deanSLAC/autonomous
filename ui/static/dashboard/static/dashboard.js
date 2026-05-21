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

// Beam-size display: prefer measured FWHM (in µm) once beamline_alignment
// has run, fall back to the operator-configured big/focused mode pair.
function formatBeamSize(exp) {
    if (!exp) return "--";
    if (exp.mirrors_out) return "Mirrors out";
    const h = exp.beam_h_fwhm_um;
    const v = exp.beam_v_fwhm_um;
    if (h != null || v != null) {
        const fmt = (x) => (x != null ? Number(x).toFixed(1) + " µm" : "?");
        return `H:${fmt(h)} V:${fmt(v)}`;
    }
    return "H:" + (exp.beam_size_h || "?") + " V:" + (exp.beam_size_v || "?");
}
window.formatBeamSize = formatBeamSize;

function formatCrystal(code) {
    if (!code) return "--";
    if (code === "A") return "A Si(111)";
    if (code === "B") return "B Si(311)";
    return code;
}
window.formatCrystal = formatCrystal;

// The form persists `experimenter` as a separate field but operators
// rarely fill it in; the experiment name (format YYYY-MM_<name>) is
// the reliable source. Fall back to parsing the name when the explicit
// field is empty.
function experimenterFromExperiment(exp) {
    if (!exp) return "";
    if (exp.experimenter && String(exp.experimenter).trim()) {
        return String(exp.experimenter).trim();
    }
    const name = (exp.name || "").trim();
    const m = name.match(/^\d{4}-\d{2}[_\-\s]+(.+)$/);
    return m ? m[1].replace(/_/g, " ").trim() : "";
}
window.experimenterFromExperiment = experimenterFromExperiment;

function renderExperimentInfo(exp) {
    if (!exp) return;
    const set = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val || "--";
    };
    set("exp-experimenter", experimenterFromExperiment(exp));
    set("exp-crystal", formatCrystal(exp.mono_crystal));
    set("exp-beam", formatBeamSize(exp));
    set("exp-env", exp.sample_env || "ambient");
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
