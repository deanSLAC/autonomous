/* Tool Tester — client-side logic */

const CATEGORY_ORDER = ["tool", "spec-read", "spec-write", "ref"];
const CATEGORY_LABELS = {
    "tool": "Tool (non-SPEC)",
    "spec-read": "SPEC Read",
    "spec-write": "SPEC Write",
    "ref": "Reference Docs",
};

let allTools = [];

// ---- Theme ----

function initTheme() {
    const saved = localStorage.getItem("tool-tester-theme");
    if (saved === "dark") document.documentElement.setAttribute("data-theme", "dark");
    updateThemeBtn();
}

function toggleTheme() {
    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
    if (isDark) {
        document.documentElement.removeAttribute("data-theme");
        localStorage.setItem("tool-tester-theme", "light");
    } else {
        document.documentElement.setAttribute("data-theme", "dark");
        localStorage.setItem("tool-tester-theme", "dark");
    }
    updateThemeBtn();
}

function updateThemeBtn() {
    const btn = document.getElementById("theme-toggle");
    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
    btn.textContent = isDark ? "☀️" : "🌙";
}

// ---- API helpers ----

async function fetchConfig() {
    const res = await fetch("/api/config");
    return res.json();
}

async function updateTool(name, fields) {
    return fetch(`/api/config/${name}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
    }).then(r => r.json());
}

async function testTool(name, args) {
    return fetch(`/api/test/${name}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ args }),
    }).then(r => r.json());
}

// ---- Render ----

function groupByCategory(tools) {
    const groups = {};
    for (const cat of CATEGORY_ORDER) groups[cat] = [];
    for (const t of tools) {
        if (!groups[t.cli_path]) groups[t.cli_path] = [];
        groups[t.cli_path].push(t);
    }
    return groups;
}

function renderSummary(tools) {
    const bar = document.getElementById("summary-bar");
    const total = tools.length;
    const working = tools.filter(t => t.working).length;
    const untested = tools.filter(t => !t.working && t.enabled).length;
    const disabled = tools.filter(t => !t.enabled).length;
    bar.innerHTML = `
        <div class="summary-stat"><span class="count blue">${total}</span> Total</div>
        <div class="summary-stat"><span class="count green">${working}</span> Working</div>
        <div class="summary-stat"><span class="count yellow">${untested}</span> Untested</div>
        <div class="summary-stat"><span class="count red">${disabled}</span> Disabled</div>
    `;
}

function renderToolCard(tool) {
    const statusClass = !tool.enabled ? "disabled" : tool.working ? "working" : "untested";
    const inputJson = JSON.stringify(tool.sample_input || {}, null, 2);
    const shortDesc = tool.when_to_use || tool.description || "";

    return `
    <div class="tool-card" data-tool="${tool.name}" data-working="${tool.working}" data-enabled="${tool.enabled}">
        <div class="tool-card-header collapsed" onclick="toggleCard(this)">
            <span class="chevron">▼</span>
            <span class="status-dot ${statusClass}"></span>
            <span class="tool-name">${tool.name}</span>
            <span class="tool-short-desc">${escHtml(shortDesc)}</span>
        </div>
        <div class="tool-card-body">
            <div class="field-group">
                <div class="field-label">Description</div>
                <div class="field-value">${escHtml(tool.description)}</div>
            </div>
            <div class="field-group">
                <div class="field-label">When to Use</div>
                <div class="field-value">${escHtml(tool.when_to_use)}</div>
            </div>

            <div class="checkbox-row">
                <label class="checkbox-item">
                    <input type="checkbox" ${tool.enabled ? "checked" : ""}
                           onchange="onToggleEnabled('${tool.name}', this.checked)">
                    Enabled
                </label>
                <label class="checkbox-item">
                    <input type="checkbox" ${tool.working ? "checked" : ""}
                           onchange="onToggleWorking('${tool.name}', this.checked)">
                    Working
                </label>
            </div>

            ${tool.sample_output ? `
            <div class="field-group sample-output">
                <div class="field-label">Expected Output</div>
                <pre>${escHtml(tool.sample_output)}</pre>
            </div>` : ""}

            <div class="test-area">
                <div class="test-input-label">Sample Input (JSON)</div>
                <textarea class="test-input" id="input-${tool.name}">${escHtml(inputJson)}</textarea>
                <div class="test-actions">
                    <button class="btn btn-test" onclick="onTest('${tool.name}')">Test</button>
                    <span class="spinner" id="spinner-${tool.name}" style="display:none"></span>
                    <span class="test-meta" id="meta-${tool.name}"></span>
                </div>
                <div class="test-result" id="result-${tool.name}"></div>
            </div>

            <div class="comments-area">
                <div class="field-label">Comments</div>
                <textarea class="comments-input" id="comments-${tool.name}"
                          placeholder="Test notes, issues, status...">${escHtml(tool.comments || "")}</textarea>
                <div class="comments-actions">
                    <button class="btn btn-secondary" onclick="onSaveComments('${tool.name}')">Save Comments</button>
                    <span class="save-indicator" id="saved-${tool.name}">Saved ✓</span>
                </div>
            </div>
        </div>
    </div>`;
}

function renderCategories(tools) {
    const content = document.getElementById("content");
    const groups = groupByCategory(tools);
    let html = "";

    for (const cat of CATEGORY_ORDER) {
        const catTools = groups[cat] || [];
        if (catTools.length === 0) continue;

        const working = catTools.filter(t => t.working);
        const untested = catTools.filter(t => !t.working);
        const disabledCount = catTools.filter(t => !t.enabled).length;

        html += `<div class="category" data-category="${cat}">`;
        html += `
            <div class="category-header" onclick="toggleCategory(this)">
                <span class="chevron">▼</span>
                <h2>${CATEGORY_LABELS[cat] || cat}</h2>
                <span class="cat-badge">${cat}</span>
                <div class="category-counts">
                    <span class="cc-working">${working.length} working</span>
                    <span class="cc-untested">${untested.length} untested</span>
                    ${disabledCount ? `<span class="cc-disabled">${disabledCount} disabled</span>` : ""}
                </div>
            </div>
            <div class="category-body">`;

        if (working.length > 0) {
            html += `<div class="sub-section-label working">Working (${working.length})</div>`;
            for (const t of working) html += renderToolCard(t);
        }
        if (untested.length > 0) {
            html += `<div class="sub-section-label untested">Untested (${untested.length})</div>`;
            for (const t of untested) html += renderToolCard(t);
        }

        html += `</div></div>`;
    }

    content.innerHTML = html;
}

// ---- Interactions ----

function toggleCategory(header) {
    header.classList.toggle("collapsed");
}

function toggleCard(header) {
    header.classList.toggle("collapsed");
}

async function onToggleEnabled(name, checked) {
    await updateTool(name, { enabled: checked });
    refreshToolState(name, { enabled: checked });
}

async function onToggleWorking(name, checked) {
    await updateTool(name, { working: checked });
    refreshToolState(name, { working: checked });
}

function refreshToolState(name, updates) {
    const tool = allTools.find(t => t.name === name);
    if (tool) Object.assign(tool, updates);
    renderSummary(allTools);
    // Update status dot and card position
    const card = document.querySelector(`.tool-card[data-tool="${name}"]`);
    if (card) {
        const dot = card.querySelector(".status-dot");
        const statusClass = !tool.enabled ? "disabled" : tool.working ? "working" : "untested";
        dot.className = `status-dot ${statusClass}`;
        card.dataset.working = tool.working;
        card.dataset.enabled = tool.enabled;
    }
    // Update category counts
    const groups = groupByCategory(allTools);
    for (const cat of CATEGORY_ORDER) {
        const catEl = document.querySelector(`.category[data-category="${cat}"]`);
        if (!catEl) continue;
        const catTools = groups[cat] || [];
        const w = catTools.filter(t => t.working).length;
        const u = catTools.filter(t => !t.working).length;
        const d = catTools.filter(t => !t.enabled).length;
        const counts = catEl.querySelector(".category-counts");
        counts.innerHTML = `
            <span class="cc-working">${w} working</span>
            <span class="cc-untested">${u} untested</span>
            ${d ? `<span class="cc-disabled">${d} disabled</span>` : ""}
        `;
    }
}

async function onTest(name) {
    const textarea = document.getElementById(`input-${name}`);
    const spinner = document.getElementById(`spinner-${name}`);
    const meta = document.getElementById(`meta-${name}`);
    const resultDiv = document.getElementById(`result-${name}`);

    let args;
    try {
        args = JSON.parse(textarea.value);
    } catch (e) {
        resultDiv.innerHTML = `<div class="result-header" style="color:var(--red)">Invalid JSON</div>`;
        return;
    }

    spinner.style.display = "inline-block";
    meta.textContent = "Running...";
    resultDiv.innerHTML = "";

    // Save the input back to config
    await updateTool(name, { sample_input: args });

    const result = await testTool(name, args);
    spinner.style.display = "none";
    meta.textContent = `${result.duration_ms}ms · exit ${result.exit_code}`;

    const cls = result.ok ? "success" : "error";
    const label = result.ok ? "Success" : "Error";
    const output = result.stdout || result.stderr || "(no output)";
    resultDiv.className = `test-result ${cls}`;
    resultDiv.innerHTML = `
        <div class="result-header">${label}</div>
        <pre>${escHtml(output)}</pre>
        ${result.stderr && result.stdout ? `<pre style="margin-top:8px;border-color:var(--yellow)">${escHtml(result.stderr)}</pre>` : ""}
        <div class="cmd-display">${escHtml(result.command || "")}</div>
    `;
}

async function onSaveComments(name) {
    const textarea = document.getElementById(`comments-${name}`);
    const indicator = document.getElementById(`saved-${name}`);
    await updateTool(name, { comments: textarea.value });
    const tool = allTools.find(t => t.name === name);
    if (tool) tool.comments = textarea.value;
    indicator.classList.add("visible");
    setTimeout(() => indicator.classList.remove("visible"), 2000);
}

// ---- Search ----

function onSearch(query) {
    const q = query.toLowerCase().trim();
    const cards = document.querySelectorAll(".tool-card");
    const categories = document.querySelectorAll(".category");

    if (!q) {
        cards.forEach(c => c.style.display = "");
        categories.forEach(c => c.style.display = "");
        return;
    }

    cards.forEach(card => {
        const text = card.textContent.toLowerCase();
        card.style.display = text.includes(q) ? "" : "none";
    });

    // Hide empty categories
    categories.forEach(cat => {
        const visible = cat.querySelectorAll(".tool-card:not([style*='display: none'])");
        cat.style.display = visible.length > 0 ? "" : "none";
        // Expand categories during search
        const header = cat.querySelector(".category-header");
        if (visible.length > 0 && header.classList.contains("collapsed")) {
            header.classList.remove("collapsed");
        }
    });
}

// ---- Utils ----

function escHtml(str) {
    if (!str) return "";
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ---- Init ----

async function init() {
    initTheme();
    document.getElementById("theme-toggle").addEventListener("click", toggleTheme);
    document.getElementById("search").addEventListener("input", e => onSearch(e.target.value));

    const data = await fetchConfig();
    allTools = data.tools || [];
    renderSummary(allTools);
    renderCategories(allTools);
}

init();
