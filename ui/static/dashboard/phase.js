/* Phase detail + informational page.
 *
 * URL forms:
 *   /phase?phase=<slug>&experiment_id=<id>   — informational view (even if no run yet)
 *   /phase?id=<phase_run_id>                 — specific phase run
 *
 * Renders static phase docs (description / inputs / outputs / tools /
 * success criteria) on every load, then overlays the live run data
 * (scan table, summary cards, collection progress) if a run exists.
 * A page-aware chat widget is mounted at the bottom so the operator
 * can ask the agent questions with the current page already loaded
 * into the prompt context.
 */
(function () {
    "use strict";

    const PHASE_INFO = {
        beamline_alignment: {
            slug: "beamline_alignment",
            name: "Beamline Alignment",
            description:
                "Brings the beamline optics (M1 vertical, M2 horizontal, mono pitch) " +
                "to a working anchor and measures the usable beam size before any sample " +
                "is loaded. Runs a sequence of short alias scans (vvv, hhh, m1m1) with " +
                "centering / FWHM fits between each step.",
            inputs: [
                "Anchor energy (from experiment config)",
                "Current mono calibration + gap state",
                "Beam status (SPEAR current, shutter)",
            ],
            outputs: [
                "Aligned M1 / M2 positions",
                "Measured beam size (H, V) at sample",
                "Saved anchor position for later phases",
                "align_beamline_ok flag on the experiment",
            ],
            tools: [
                "align_beamline()",
                "fallbacks: vvv, m1m1, hhh alias scans",
                "get_beam_status(), umv",
            ],
            success: [
                "Beam FWHM within target envelope",
                "Anchor saved and reported",
                "No beam-drop or shutter faults left unresolved",
            ],
        },
        xes_alignment: {
            slug: "xes_alignment",
            name: "Spectrometer Alignment",
            description:
                "Per-crystal peak optimization for the emission spectrometer plus a " +
                "mono elastic scan to lock the XES energy offset. Runs pitcha / pitchb " +
                "rocking curves per crystal, fits the peak, and stores the optimal " +
                "position.",
            inputs: [
                "List of active crystals (from experiment config)",
                "Detector Dz and Az positions",
                "Anchor energy from beamline alignment",
            ],
            outputs: [
                "Crystal pitch / roll set per crystal",
                "XES_EN_OFFSET calibration",
                "Anomaly log for any crystal that failed to peak",
            ],
            tools: [
                "align_xes_spectrometer()",
                "peak_mono_pitch()",
                "calibrate_mono()",
            ],
            success: [
                "Every active crystal has a peak within threshold",
                "XES_EN_OFFSET written and non-drifting",
            ],
        },
        spec_align: { alias: "xes_alignment" },
        sample_alignment: {
            slug: "sample_alignment",
            name: "Sample Alignment",
            description:
                "Sz survey across the holder to locate each loaded sample, followed " +
                "by per-sample Sx / Sy centering. Each centered sample has its " +
                "position persisted in the plan so the collection loop can move " +
                "between samples without re-aligning.",
            inputs: [
                "Sample holder layout + nominal positions",
                "Active element list (for knife-edge shape expectations)",
                "Aligned beam from the previous phase",
            ],
            outputs: [
                "Per-sample Sx / Sy / Sz absolute positions",
                "Bounds stored on each plan entry",
                "Count of samples successfully aligned",
            ],
            tools: [
                "run_sample_alignment()",
                "auto_sample_align()",
                "update_sample_position()",
            ],
            success: [
                "Every sample in the plan has a recorded position",
                "No samples flagged missing / collided",
            ],
        },
        collection: {
            slug: "collection",
            name: "Data Collection",
            description:
                "Main science loop: step through the sample queue, run the configured " +
                "techniques (XAS, RIXS, emission) for the requested reps, and analyze " +
                "each scan live. Plan edits (reorder, skip, extend budget) can happen " +
                "mid-collection.",
            inputs: [
                "Sample plan + reps / count-time per mode",
                "Beamtime budget (remaining hours)",
                "Per-sample aligned positions",
            ],
            outputs: [
                "SPEC data files for every completed scan",
                "Per-sample reps_completed, SNR estimate, efficiency verdict",
                "Summary images for long-running samples",
            ],
            tools: [
                "run_collection()",
                "tune_detector_gain()",
                "swap_sample_in_plan()",
                "request_human_intervention()",
            ],
            success: [
                "SNR target reached for every non-skipped sample (or documented reason)",
                "No unresolved anomalies at end of run",
                "Total time within budget",
            ],
        },
    };

    function resolveInfo(slug) {
        const entry = PHASE_INFO[slug];
        if (!entry) return null;
        if (entry.alias) return PHASE_INFO[entry.alias] || null;
        return entry;
    }

    function byId(id) { return document.getElementById(id); }

    function setList(id, items) {
        const el = byId(id);
        if (!el) return;
        if (!items || !items.length) {
            el.innerHTML = '<li class="muted">—</li>';
            return;
        }
        el.innerHTML = items.map(t => `<li>${escapeHtml(t)}</li>`).join("");
    }

    function escapeHtml(s) {
        if (s == null) return "";
        return String(s)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;")
            .replace(/>/g, "&gt;").replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function formatTime(iso) {
        if (!iso) return "--";
        const d = new Date(iso);
        return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    }

    function formatDuration(startIso, endIso) {
        if (!startIso) return "--";
        const start = new Date(startIso);
        const end = endIso ? new Date(endIso) : new Date();
        const ms = end - start;
        const mins = Math.floor(ms / 60000);
        const secs = Math.floor((ms % 60000) / 1000);
        if (mins > 60) return `${Math.floor(mins / 60)}h ${mins % 60}m`;
        return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
    }

    function fmt(v, n) {
        if (v == null) return "--";
        return Number(v).toFixed(n == null ? 2 : n);
    }

    function confClass(c) {
        if (c == null) return "";
        if (c >= 0.7) return "confidence-high";
        if (c >= 0.4) return "confidence-mid";
        return "confidence-low";
    }

    // ---- State passed to the chat widget -------------------------------

    const pageState = {
        info: null,
        slug: null,
        experimentId: null,
        phaseRun: null,
        scanCount: 0,
        latestScan: null,
    };

    // ---- Render --------------------------------------------------------

    function renderInfo(info) {
        const title = info ? info.name : "Phase";
        document.title = "BL15-2 — " + title;
        byId("page-title").textContent = title;
        byId("detail-title").textContent = title;
        if (!info) {
            byId("phase-description").textContent = "Unknown phase.";
            return;
        }
        byId("phase-description").textContent = info.description;
        setList("phase-inputs", info.inputs);
        setList("phase-outputs", info.outputs);
        setList("phase-tools", info.tools);
        setList("phase-success", info.success);
    }

    function renderBadge(status) {
        const badge = byId("detail-badge");
        if (!badge) return;
        badge.className = "tile-status-badge badge-" + (status || "pending");
        badge.textContent = status || "pending";
    }

    function renderRunData(data) {
        // dashboard_api returns {"run": ..., "scans": [...]}, but the older
        // /api/dashboard/status payload nests the same info as phase_runs[]
        // without the scans. Accept either shape.
        const run = data && (data.run || data.phase_run);
        if (!run) {
            byId("phase-data-panel").style.display = "none";
            byId("phase-empty-panel").style.display = "";
            renderBadge("pending");
            return;
        }
        byId("phase-data-panel").style.display = "";
        byId("phase-empty-panel").style.display = "none";
        renderBadge(run.status);

        const scans = data.scans || [];
        pageState.phaseRun = run;
        pageState.scanCount = scans.length;
        pageState.latestScan = scans[scans.length - 1] || null;

        const sub = byId("phase-run-sub");
        if (sub) sub.textContent = `run ${run.id} · ${scans.length} scans`;

        const set = (id, v) => { const el = byId(id); if (el) el.textContent = v == null ? "--" : v; };
        set("sum-started", formatTime(run.started_at));
        set("sum-duration", formatDuration(run.started_at, run.completed_at));
        set("sum-scans", scans.length);
        set("sum-llm", scans.filter(s => s.llm_consulted).length);
        set("sum-anomalies", scans.filter(s => s.anomaly).length);
        set("sum-datafile", run.spec_datafile || "--");

        if (run.notes) {
            byId("assessment-box").style.display = "";
            byId("assessment-text").textContent = run.notes;
        } else {
            byId("assessment-box").style.display = "none";
        }
        if (run.summary_image_path) {
            byId("report-image").src =
                "/api/dashboard/image?path=" + encodeURIComponent(run.summary_image_path);
            byId("report-image-container").style.display = "";
        } else {
            byId("report-image-container").style.display = "none";
        }

        if (run.phase === "collection" && data.collection_progress) {
            const grid = byId("collection-grid");
            byId("collection-progress").style.display = "";
            grid.innerHTML = data.collection_progress.map(s => {
                const pct = s.target > 0 ? Math.min(100, (s.completed / s.target) * 100) : 0;
                const done = pct >= 100 ? "done" : "";
                return `<div class="sample-card">
                    <div class="sample-card-name">${escapeHtml(s.name)}</div>
                    <div class="sample-card-element">${escapeHtml(s.element)} ${escapeHtml(s.technique)}</div>
                    <div class="progress-bar-bg"><div class="progress-bar-fill ${done}" style="width:${pct}%"></div></div>
                    <div class="progress-label">${s.completed} / ${s.target} reps</div>
                </div>`;
            }).join("");
        } else {
            byId("collection-progress").style.display = "none";
        }

        const tbody = byId("scan-tbody");
        if (!scans.length) {
            tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No scans recorded yet.</td></tr>';
            return;
        }
        tbody.innerHTML = scans.map(s => `
            <tr class="${s.anomaly ? "anomaly" : ""}">
                <td>${s.scan_number}</td>
                <td>${escapeHtml(s.motor_name || "")}</td>
                <td>${s.iteration ?? ""}</td>
                <td>${escapeHtml(s.decision_action || "--")}</td>
                <td>${escapeHtml(s.decision_command || "--")}</td>
                <td>${fmt(s.result_position)}</td>
                <td>${fmt(s.fwhm)}</td>
                <td class="${confClass(s.decision_confidence)}">${fmt(s.decision_confidence)}</td>
                <td class="${s.llm_consulted ? "llm-yes" : ""}">${s.llm_consulted ? "yes" : "--"}</td>
            </tr>`).join("");
    }

    // ---- Loading -------------------------------------------------------

    async function loadByRunId(runId) {
        try {
            const r = await fetch("/api/dashboard/phase/" + encodeURIComponent(runId));
            if (!r.ok) { renderRunData(null); return; }
            const data = await r.json();
            const run = data.run || data.phase_run;
            const phaseField = (run && run.phase) || "";
            const slug = phaseField === "spec_align" ? "xes_alignment"
                : phaseField === "bl_align" ? "beamline_alignment"
                : phaseField === "sample_align" ? "sample_alignment"
                : phaseField;
            pageState.slug = slug;
            pageState.info = resolveInfo(slug);
            renderInfo(pageState.info);
            if (run && run.experiment_id) pageState.experimentId = run.experiment_id;
            renderRunData(data);
        } catch (_) {
            renderRunData(null);
        }
    }

    async function loadByPhaseName(slug, experimentId) {
        pageState.slug = slug;
        pageState.info = resolveInfo(slug);
        pageState.experimentId = experimentId || null;
        renderInfo(pageState.info);

        if (!experimentId) {
            renderRunData(null);
            return;
        }
        try {
            const r = await fetch("/api/dashboard/status?experiment_id=" + encodeURIComponent(experimentId));
            if (!r.ok) { renderRunData(null); return; }
            const data = await r.json();
            // Find a phase run that matches this slug. The DB stores some
            // phases under the _align short form; accept both.
            const phaseNames = [slug];
            if (slug === "xes_alignment") phaseNames.push("spec_align", "xes_align");
            if (slug === "beamline_alignment") phaseNames.push("bl_align");
            if (slug === "sample_alignment") phaseNames.push("sample_align");
            const runs = (data.phases || data.phase_runs || []).filter(p => phaseNames.includes(p.phase));
            const run = runs[runs.length - 1];
            if (!run) {
                renderRunData(null);
                return;
            }
            const detail = await fetch("/api/dashboard/phase/" + encodeURIComponent(run.id));
            if (!detail.ok) {
                renderRunData({ phase_run: run, scans: [] });
                return;
            }
            const detailData = await detail.json();
            renderRunData(detailData);
        } catch (_) {
            renderRunData(null);
        }
    }

    // ---- Chat widget mount --------------------------------------------

    function mountChat() {
        const container = byId("phase-chat");
        if (!container || typeof window.mountChatWidget !== "function") return;
        const info = pageState.info;
        const title = info ? `Chat about ${info.name}` : "Chat with the agent";
        window.mountChatWidget(container, {
            header: title,
            placeholder:
                "Ask the agent about this phase — e.g. 'how does the detector Dz scan look?' " +
                "or 'summarize the beamline alignment'.  (Enter sends, Shift+Enter newline)",
            context: () => ({
                experiment_id: pageState.experimentId || undefined,
                page: pageState.slug || "phase",
                page_context: buildPageContext(),
            }),
        });
    }

    function buildPageContext() {
        const info = pageState.info || {};
        const ctx = {
            phase_name: info.name || pageState.slug,
            phase_slug: info.slug || pageState.slug,
            description: info.description,
            inputs: info.inputs,
            outputs: info.outputs,
            tools_available: info.tools,
            success_criteria: info.success,
        };
        const run = pageState.phaseRun;
        if (run) {
            ctx.phase_run_id = run.id;
            ctx.phase_run_status = run.status;
            ctx.phase_run_started_at = run.started_at;
            ctx.phase_run_datafile = run.spec_datafile;
            ctx.phase_run_scan_count = pageState.scanCount;
            if (pageState.latestScan) {
                ctx.latest_scan = {
                    scan_number: pageState.latestScan.scan_number,
                    motor: pageState.latestScan.motor_name,
                    iteration: pageState.latestScan.iteration,
                    result_position: pageState.latestScan.result_position,
                    fwhm: pageState.latestScan.fwhm,
                };
            }
        }
        return ctx;
    }

    // ---- Init ----------------------------------------------------------

    function init() {
        const params = new URLSearchParams(window.location.search);
        const runId = params.get("id");
        const phase = params.get("phase");
        const experimentId = params.get("experiment_id");

        // Simulation pill + server health (if dashboard.js loaded these helpers).
        if (typeof checkServer === "function") checkServer();
        setInterval(() => { if (typeof checkServer === "function") checkServer(); }, 5000);

        // Mount chat first so the container exists even if later fetches fail.
        if (phase) pageState.slug = phase === "spec_align" ? "xes_alignment" : phase;
        pageState.info = resolveInfo(pageState.slug);
        renderInfo(pageState.info);
        mountChat();

        if (runId) {
            loadByRunId(runId);
            setInterval(() => loadByRunId(runId), 10000);
        } else if (phase) {
            loadByPhaseName(pageState.slug, experimentId);
            if (experimentId) {
                setInterval(() => loadByPhaseName(pageState.slug, experimentId), 10000);
            }
        } else {
            byId("phase-description").textContent =
                "Open a phase from the dashboard to see its details.";
            renderRunData(null);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
