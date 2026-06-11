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

// ---- Initialization ----

function isMainDashboard() {
    return !window.location.pathname.includes("/phase");
}

async function init() {
    checkServer();

    if (isMainDashboard()) {
        // Expose the load promise so page scripts that depend on
        // #experiment-select being populated (viewer.js,
        // sample_holders.js) can await it instead of sleeping.
        window.experimentsLoaded = loadExperiments();
        await window.experimentsLoaded;
        refreshDashboard();

        const sel = document.getElementById("experiment-select");
        if (sel) sel.addEventListener("change", onExperimentChange);

        // Start polling. BL.pollWrap skips a tick while the tab is
        // hidden or while the previous tick is still in flight.
        pollTimer = setInterval(BL.pollWrap(async () => {
            await Promise.all([checkServer(), refreshDashboard()]);
        }), POLL_INTERVAL);
    } else {
        // Phase detail page — phase.js owns rendering + polling. Only
        // bother with the health dot here.
        setInterval(BL.pollWrap(checkServer), POLL_INTERVAL);
    }
}

init();
