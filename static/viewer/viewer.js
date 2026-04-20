/* /viewer — browse SPEC files and plot scans. Plain canvas, no deps. */

const V = {
    holderId: null,
    experimentId: null,
    files: [],
    activeFile: null,
    scans: {},           // scan_number -> scan data
    scanList: [],        // meta from /api/viewer/scans
    selected: new Set(), // scan_numbers checked for the overlay
    detailScan: null,
    colors: [
        "#9b1b30", "#2563eb", "#1b7a1b", "#8a6d00", "#c0392b",
        "#6b46c1", "#0d9488", "#dc2626", "#2a9d8f", "#f59e0b",
    ],
};

function vEsc(s) {
    if (s == null) return "";
    return String(s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function vGetExpId() {
    const sel = document.getElementById("experiment-select");
    return sel ? sel.value : "";
}

function vParseQuery() {
    const p = new URLSearchParams(window.location.search);
    return { holder_id: p.get("holder_id"), experiment_id: p.get("experiment_id") };
}

async function vFetchJson(url) {
    const r = await fetch(url);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { console.warn("viewer fetch failed:", url, j); return null; }
    return j;
}

// ---- File list ------------------------------------------------------------

async function vLoadFiles() {
    const expId = V.experimentId || vGetExpId();
    if (!expId && !V.holderId) {
        document.getElementById("viewer-file-list").innerHTML =
            '<div class="muted">Select an experiment or open the viewer from a holder.</div>';
        return;
    }
    const qs = new URLSearchParams();
    if (expId) qs.set("experiment_id", expId);
    if (V.holderId) qs.set("holder_id", V.holderId);
    const j = await vFetchJson("/api/viewer/files?" + qs.toString());
    if (!j) return;
    V.files = j.files || [];
    V.experimentId = j.experiment_id || expId;
    const sub = document.getElementById("viewer-holder-sub");
    if (sub) {
        if (j.holder_name) {
            sub.textContent = `holder: ${j.holder_name}`;
        } else if (j.directories && j.directories.length) {
            sub.textContent = j.directories.join(" · ");
        } else {
            sub.textContent = "—";
        }
    }
    vRenderFileList();
}

function vRenderFileList() {
    const el = document.getElementById("viewer-file-list");
    if (!V.files.length) {
        el.innerHTML = '<div class="muted">No SPEC files found in the experiment directories.</div>';
        return;
    }
    el.innerHTML = V.files.map(f => {
        const date = new Date(f.mtime * 1000);
        const dateStr = date.toLocaleString();
        const badge = f.holder_match
            ? `<span class="badge">${vEsc(f.holder_match)}</span>` : "";
        const active = V.activeFile === f.path ? "active" : "";
        return `<div class="file-item ${active}" data-path="${vEsc(f.path)}" onclick="vLoadFile('${vEsc(f.path)}')">
            <div style="flex:1; min-width:0">
                <div style="font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap">${vEsc(f.name)}</div>
                <div class="muted" style="font-size:0.82em">${vEsc(dateStr)}</div>
            </div>
            ${badge}
        </div>`;
    }).join("");
}

// ---- Scan list ------------------------------------------------------------

async function vLoadFile(path) {
    V.activeFile = path;
    V.scans = {};
    V.selected = new Set();
    V.detailScan = null;
    document.getElementById("viewer-file-name").textContent = path.split("/").pop();
    vRenderFileList();
    const j = await vFetchJson("/api/viewer/scans?path=" + encodeURIComponent(path));
    if (!j) return;
    V.scanList = j.scans || [];
    vRenderScanList();
    // Pre-load detail dropdown; don't auto-plot until user selects.
    const detailSel = document.getElementById("detail-scan");
    detailSel.innerHTML = '<option value="">—</option>' +
        V.scanList.map(s => `<option value="${s.scan_number}">S${s.scan_number}: ${vEsc((s.command || "").slice(0, 40))}</option>`).join("");
    detailSel.onchange = () => vShowDetail(parseInt(detailSel.value, 10));
    vRenderOverlay(); // clears canvas
}

function vRenderScanList() {
    const el = document.getElementById("viewer-scan-list");
    if (!V.scanList.length) {
        el.innerHTML = '<div class="muted">No scans in this file.</div>';
        return;
    }
    el.innerHTML = V.scanList.map(s => {
        const checked = V.selected.has(s.scan_number) ? "checked" : "";
        const label = `S${s.scan_number}: ${(s.command || "").slice(0, 50)}`;
        return `<label class="scan-item">
            <input type="checkbox" ${checked} onchange="vToggleScan(${s.scan_number}, this.checked)">
            <span>${vEsc(label)}</span>
        </label>`;
    }).join("");
}

async function vToggleScan(scanNum, checked) {
    if (checked) {
        V.selected.add(scanNum);
        if (!V.scans[scanNum]) {
            const d = await vFetchJson(`/api/viewer/scan_data?path=${encodeURIComponent(V.activeFile)}&scan=${scanNum}`);
            if (d) V.scans[scanNum] = d;
        }
    } else {
        V.selected.delete(scanNum);
    }
    vRefreshAxes();
    vRenderOverlay();
}

function vSelectAllScans(all) {
    V.scanList.forEach(s => {
        if (all) V.selected.add(s.scan_number);
        else V.selected.delete(s.scan_number);
    });
    // Load any newly-selected data
    const pending = [...V.selected].filter(n => !V.scans[n]);
    Promise.all(pending.map(async n => {
        const d = await vFetchJson(`/api/viewer/scan_data?path=${encodeURIComponent(V.activeFile)}&scan=${n}`);
        if (d) V.scans[n] = d;
    })).then(() => {
        vRenderScanList();
        vRefreshAxes();
        vRenderOverlay();
    });
    vRenderScanList();
}

function vSelectByKeyword(kw) {
    V.scanList.forEach(s => {
        if ((s.command || "").toLowerCase().includes(kw)) V.selected.add(s.scan_number);
    });
    const pending = [...V.selected].filter(n => !V.scans[n]);
    Promise.all(pending.map(async n => {
        const d = await vFetchJson(`/api/viewer/scan_data?path=${encodeURIComponent(V.activeFile)}&scan=${n}`);
        if (d) V.scans[n] = d;
    })).then(() => {
        vRenderScanList();
        vRefreshAxes();
        vRenderOverlay();
    });
    vRenderScanList();
}

// Expose globals for inline onclick
window.viewerSelectAllScans = vSelectAllScans;
window.viewerSelectByKeyword = vSelectByKeyword;

// ---- Axis dropdowns -------------------------------------------------------

function vAllColumns() {
    const cols = new Set();
    Object.values(V.scans).forEach(s => {
        (s.columns || []).forEach(c => cols.add(c));
    });
    return [...cols].sort();
}

function vRefreshAxes() {
    const cols = vAllColumns();
    const motor = vFirstMotor();
    const setOpts = (id, withNone) => {
        const sel = document.getElementById(id);
        if (!sel) return;
        const cur = sel.value;
        const opts = withNone ? '<option value="">None</option>' : "";
        const sorted = [...cols];
        if (motor && sorted.includes(motor)) {
            sorted.splice(sorted.indexOf(motor), 1);
            sorted.unshift(motor);
        }
        sel.innerHTML = opts + sorted.map(c => `<option value="${vEsc(c)}">${vEsc(c)}</option>`).join("");
        if (cur && sorted.includes(cur)) sel.value = cur;
    };
    setOpts("multi-x", false);
    setOpts("multi-y", false);
    setOpts("multi-y2", true);
    setOpts("detail-x", false);
    setOpts("detail-y", false);
    setOpts("detail-y2", true);
    // Default Y to vortDT/I0 if present
    const preferY = cols.includes("vortDT") ? "vortDT" : (cols.includes("I0") ? "I0" : cols[0]);
    if (preferY) {
        const my = document.getElementById("multi-y");
        if (my && !my.value) my.value = preferY;
        const dy = document.getElementById("detail-y");
        if (dy && !dy.value) dy.value = preferY;
    }
    if (cols.includes("I0")) {
        const my2 = document.getElementById("multi-y2");
        if (my2 && !my2.value) my2.value = "I0";
        const dy2 = document.getElementById("detail-y2");
        if (dy2 && !dy2.value) dy2.value = "I0";
    }
}

function vFirstMotor() {
    for (const n of V.selected) {
        const s = V.scans[n];
        if (s && s.scanned_motor) return s.scanned_motor;
    }
    for (const s of Object.values(V.scans)) {
        if (s && s.scanned_motor) return s.scanned_motor;
    }
    return null;
}

// ---- Plotting -------------------------------------------------------------

function vSeriesFor(scanNum, xKey, yKey, y2Key, normalize) {
    const s = V.scans[scanNum];
    if (!s || !s.data) return null;
    const x = s.data[xKey];
    let y = s.data[yKey];
    if (!x || !y || x.length === 0 || y.length === 0) return null;
    y = y.slice();
    if (y2Key && s.data[y2Key]) {
        const denom = s.data[y2Key];
        for (let i = 0; i < y.length; i++) {
            const d = denom[i];
            if (d && d !== 0) y[i] = y[i] / d;
        }
    }
    if (normalize) {
        let ymin = Infinity, ymax = -Infinity;
        for (const v of y) { if (v < ymin) ymin = v; if (v > ymax) ymax = v; }
        const range = ymax - ymin;
        if (range > 0) {
            for (let i = 0; i < y.length; i++) y[i] = (y[i] - ymin) / range;
        }
    }
    return { x, y, label: `S${scanNum}: ${(s.command || "").slice(0, 36)}` };
}

function vPlot(canvas, series, opts) {
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    // Scale canvas for crisp lines on HiDPI
    const cssW = canvas.clientWidth || canvas.width;
    const cssH = canvas.clientHeight || canvas.height;
    canvas.width = cssW * dpr;
    canvas.height = cssH * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const padL = 56, padR = 16, padT = 18, padB = 38;
    const plotW = cssW - padL - padR;
    const plotH = cssH - padT - padB;
    if (!series.length) {
        ctx.fillStyle = "#888";
        ctx.font = "13px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Select a scan to plot.", cssW / 2, cssH / 2);
        return;
    }

    // Domain
    let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
    for (const s of series) {
        for (let i = 0; i < s.x.length; i++) {
            const xv = s.x[i], yv = s.y[i];
            if (!isFinite(xv) || !isFinite(yv)) continue;
            if (xv < xmin) xmin = xv;
            if (xv > xmax) xmax = xv;
            if (yv < ymin) ymin = yv;
            if (yv > ymax) ymax = yv;
        }
    }
    if (!isFinite(xmin)) { xmin = 0; xmax = 1; }
    if (!isFinite(ymin)) { ymin = 0; ymax = 1; }
    if (xmin === xmax) { xmax = xmin + 1; }
    if (ymin === ymax) { ymax = ymin + 1; }
    const xRange = xmax - xmin;
    const yRange = ymax - ymin;

    const toX = (v) => padL + ((v - xmin) / xRange) * plotW;
    const toY = (v) => padT + plotH - ((v - ymin) / yRange) * plotH;

    // Axes
    const style = getComputedStyle(document.documentElement);
    const gridColor = style.getPropertyValue("--border").trim() || "#ddd";
    const textColor = style.getPropertyValue("--text-muted").trim() || "#666";
    const mainColor = style.getPropertyValue("--text").trim() || "#222";

    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padL, padT);
    ctx.lineTo(padL, padT + plotH);
    ctx.lineTo(padL + plotW, padT + plotH);
    ctx.stroke();

    ctx.fillStyle = textColor;
    ctx.font = "11px sans-serif";

    // Tick marks (5 x, 5 y)
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let i = 0; i <= 4; i++) {
        const y = ymin + (yRange * i) / 4;
        const yPx = toY(y);
        ctx.fillText(y.toPrecision(4), padL - 6, yPx);
        ctx.strokeStyle = "rgba(0,0,0,0.07)";
        ctx.beginPath();
        ctx.moveTo(padL, yPx);
        ctx.lineTo(padL + plotW, yPx);
        ctx.stroke();
    }
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (let i = 0; i <= 4; i++) {
        const x = xmin + (xRange * i) / 4;
        const xPx = toX(x);
        ctx.fillText(x.toPrecision(4), xPx, padT + plotH + 6);
    }

    // Axis labels
    ctx.fillStyle = mainColor;
    ctx.textAlign = "center";
    ctx.font = "12px sans-serif";
    ctx.fillText(opts.xLabel || "", padL + plotW / 2, cssH - 6);
    ctx.save();
    ctx.translate(14, padT + plotH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(opts.yLabel || "", 0, 0);
    ctx.restore();

    // Series
    for (let si = 0; si < series.length; si++) {
        const s = series[si];
        ctx.strokeStyle = s.color || V.colors[si % V.colors.length];
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        let started = false;
        for (let i = 0; i < s.x.length; i++) {
            const xv = s.x[i], yv = s.y[i];
            if (!isFinite(xv) || !isFinite(yv)) continue;
            const px = toX(xv), py = toY(yv);
            if (!started) { ctx.moveTo(px, py); started = true; }
            else { ctx.lineTo(px, py); }
        }
        ctx.stroke();
    }
}

function vRenderOverlay() {
    const canvas = document.getElementById("multi-canvas");
    const legend = document.getElementById("multi-legend");
    const status = document.getElementById("multi-status");
    const xKey = document.getElementById("multi-x").value;
    const yKey = document.getElementById("multi-y").value;
    const y2Key = document.getElementById("multi-y2").value;
    const norm = document.getElementById("multi-norm").checked;
    if (!V.selected.size) {
        status.textContent = "Select scans in the sidebar to plot.";
    } else if (!xKey || !yKey) {
        status.textContent = "Pick X and Y axes.";
    } else {
        status.textContent = `${V.selected.size} scan(s) plotted`;
    }
    const sel = [...V.selected].sort((a, b) => a - b);
    const series = sel
        .map((n, i) => {
            const s = vSeriesFor(n, xKey, yKey, y2Key, norm);
            if (s) s.color = V.colors[i % V.colors.length];
            return s;
        })
        .filter(Boolean);
    vPlot(canvas, series, {
        xLabel: xKey,
        yLabel: y2Key ? `${yKey}/${y2Key}${norm ? " (0–1)" : ""}` : (norm ? `${yKey} (0–1)` : yKey),
    });
    legend.innerHTML = series.map(s => `<span class="legend-item"><span class="swatch" style="background:${s.color}"></span>${vEsc(s.label)}</span>`).join("");
}

// ---- Detail view ----------------------------------------------------------

async function vShowDetail(scanNum) {
    V.detailScan = scanNum;
    if (!scanNum || !V.activeFile) {
        const canvas = document.getElementById("detail-canvas");
        canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
        document.getElementById("detail-meta").textContent = "—";
        return;
    }
    if (!V.scans[scanNum]) {
        const d = await vFetchJson(`/api/viewer/scan_data?path=${encodeURIComponent(V.activeFile)}&scan=${scanNum}`);
        if (d) V.scans[scanNum] = d;
    }
    const s = V.scans[scanNum];
    if (!s) return;
    vRefreshAxes();
    vRenderDetail();
    const meta = {
        command: s.command,
        scanned_motor: s.scanned_motor,
        n_points: s.n_points,
        columns: s.columns,
        motor_positions: s.motor_positions,
    };
    document.getElementById("detail-meta").textContent = JSON.stringify(meta, null, 2);
    document.getElementById("detail-sub").textContent = `S${scanNum}`;
}

function vRenderDetail() {
    const canvas = document.getElementById("detail-canvas");
    const xKey = document.getElementById("detail-x").value;
    const yKey = document.getElementById("detail-y").value;
    const y2Key = document.getElementById("detail-y2").value;
    const norm = document.getElementById("detail-norm").checked;
    if (!V.detailScan || !xKey || !yKey) {
        canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
        return;
    }
    const s = vSeriesFor(V.detailScan, xKey, yKey, y2Key, norm);
    if (!s) return;
    s.color = "#9b1b30";
    vPlot(canvas, [s], {
        xLabel: xKey,
        yLabel: y2Key ? `${yKey}/${y2Key}${norm ? " (0–1)" : ""}` : (norm ? `${yKey} (0–1)` : yKey),
    });
}

// ---- Wiring ---------------------------------------------------------------

function vWireControls() {
    for (const id of ["multi-x", "multi-y", "multi-y2", "multi-norm"]) {
        const el = document.getElementById(id);
        if (el) el.addEventListener("change", vRenderOverlay);
    }
    for (const id of ["detail-x", "detail-y", "detail-y2", "detail-norm"]) {
        const el = document.getElementById(id);
        if (el) el.addEventListener("change", vRenderDetail);
    }
    const expSel = document.getElementById("experiment-select");
    if (expSel) {
        expSel.addEventListener("change", () => {
            V.experimentId = expSel.value;
            V.holderId = null;  // experiment picker trumps holder link
            const sub = document.getElementById("viewer-holder-sub");
            if (sub) sub.textContent = "—";
            V.activeFile = null;
            V.scans = {};
            V.selected = new Set();
            V.scanList = [];
            vRenderFileList();
            vRenderScanList();
            vLoadFiles();
        });
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const q = vParseQuery();
    if (q.holder_id) V.holderId = q.holder_id;
    if (q.experiment_id) V.experimentId = q.experiment_id;
    vWireControls();
    // Let dashboard.js populate the experiment selector first
    setTimeout(vLoadFiles, 400);
});
