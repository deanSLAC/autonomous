// Tools catalog — renders the /api/tools payload into a long-form
// reference page. One source of truth = server/tools/lineage.py.

const SOURCE_LABEL = {
    spec_session: "SPEC session",
    spec_datafile: "SPEC datafile",
    spec_logfile: "SPEC log",
    spec_config: "SPEC config",
    autonomy_db: "Autonomy DB",
    filesystem: "Scan dir",
    tool_chain: "Other tool",
    slack: "Slack",
};

const escapeHtml = BL.escapeHtml;

function sourceBadge(source) {
    if (!source) return "";
    const label = SOURCE_LABEL[source] || source;
    return `<span class="badge badge-source src-${escapeHtml(source)}">${escapeHtml(label)}</span>`;
}

function renderInputs(inputs) {
    if (!inputs || inputs.length === 0) {
        return '<div class="muted">No arguments.</div>';
    }
    const rows = inputs.map(arg => {
        const req = arg.required
            ? '<span class="arg-required">required</span>'
            : "";
        const def = (arg.default !== undefined)
            ? `<span class="arg-enum">default = ${escapeHtml(JSON.stringify(arg.default))}</span>`
            : "";
        const enm = (arg.enum)
            ? `<span class="arg-enum">one of ${arg.enum.map(v => escapeHtml(JSON.stringify(v))).join(" | ")}</span>`
            : "";
        const desc = arg.description
            ? `<span class="arg-description">${escapeHtml(arg.description)}</span>`
            : "";
        return `<li>
            <span class="arg-name">${escapeHtml(arg.name)}</span>
            <span class="arg-type">${escapeHtml(arg.type || "")}</span>
            ${req}${enm}${def}${desc}
        </li>`;
    }).join("");
    return `<ul class="inputs-list">${rows}</ul>`;
}

function renderDeps(deps) {
    if (!deps || deps.length === 0) {
        return '<span class="muted">None.</span>';
    }
    return `<div class="deps-list">${deps.map(d =>
        `<a class="dep-chip" href="#tool-${escapeHtml(d)}">${escapeHtml(d)}</a>`
    ).join("")}</div>`;
}

function renderTool(tool) {
    const specBadge = tool.sends_spec_command
        ? '<span class="badge badge-spec">SPEC</span>'
        : "";
    const srcBadge = sourceBadge(tool.source);
    const specRow = tool.sends_spec_command ? `
        <div class="row">
            <div class="key">SPEC command</div>
            <div class="val"><code class="block">${escapeHtml(tool.spec_command)}</code></div>
        </div>` : "";
    return `<article class="tool-card" id="tool-${escapeHtml(tool.name)}" data-name="${escapeHtml(tool.name)}">
        <div class="tool-left">
            <div class="tool-name">${escapeHtml(tool.name)}</div>
            <div class="tool-description">${escapeHtml(tool.long_description || tool.description)}</div>
            <div class="tool-badges">${specBadge}${srcBadge}</div>
        </div>
        <div class="tool-detail">
            <div class="row">
                <div class="key">Python function</div>
                <div class="val"><code class="block">${escapeHtml(tool.python_func || "—")}</code></div>
            </div>
            ${specRow}
            <div class="row">
                <div class="key">Source</div>
                <div class="val">${escapeHtml(tool.source_detail || "—")}</div>
            </div>
            <div class="row compact-hide">
                <div class="key">Inputs</div>
                <div class="val">${renderInputs(tool.inputs)}</div>
            </div>
            <div class="row">
                <div class="key">Output</div>
                <div class="val">${escapeHtml(tool.output || "—")}</div>
            </div>
            <div class="row">
                <div class="key">Depends on</div>
                <div class="val">${renderDeps(tool.depends_on)}</div>
            </div>
        </div>
    </article>`;
}

function renderCategories(categories) {
    return categories.map(cat => `
        <section class="category-block" data-category="${escapeHtml(cat.category)}">
            <button type="button" class="category-header" aria-expanded="true">
                <span class="cat-title">
                    <span class="chevron" aria-hidden="true">&#9662;</span>
                    <span>${escapeHtml(cat.category)}</span>
                </span>
                <span class="category-count">${cat.tools.length} tool${cat.tools.length === 1 ? "" : "s"}</span>
            </button>
            <div class="category-body">
                ${cat.tools.map(renderTool).join("")}
            </div>
        </section>
    `).join("");
}

// ---- Collapse / expand ---------------------------------------------------

const COLLAPSED_KEY = "bl15-tools-collapsed";

function loadCollapsedSet() {
    try {
        const raw = localStorage.getItem(COLLAPSED_KEY);
        return new Set(raw ? JSON.parse(raw) : []);
    } catch { return new Set(); }
}

function saveCollapsedSet(set) {
    try { localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...set])); }
    catch { /* ignore quota errors */ }
}

function applyCollapsedState() {
    const collapsed = loadCollapsedSet();
    document.querySelectorAll(".category-block").forEach(block => {
        const name = block.dataset.category;
        const isCollapsed = collapsed.has(name);
        block.classList.toggle("collapsed", isCollapsed);
        const btn = block.querySelector(".category-header");
        if (btn) btn.setAttribute("aria-expanded", String(!isCollapsed));
    });
}

function toggleCategory(block, forceCollapsed) {
    const name = block.dataset.category;
    const collapsed = loadCollapsedSet();
    const nextCollapsed = (typeof forceCollapsed === "boolean")
        ? forceCollapsed
        : !collapsed.has(name);
    if (nextCollapsed) collapsed.add(name); else collapsed.delete(name);
    saveCollapsedSet(collapsed);
    block.classList.toggle("collapsed", nextCollapsed);
    const btn = block.querySelector(".category-header");
    if (btn) btn.setAttribute("aria-expanded", String(!nextCollapsed));
}

function setAllCollapsed(collapsedState) {
    const names = [...document.querySelectorAll(".category-block")]
        .map(b => b.dataset.category);
    const set = collapsedState ? new Set(names) : new Set();
    saveCollapsedSet(set);
    applyCollapsedState();
}

function wireCollapse() {
    document.getElementById("categories").addEventListener("click", e => {
        const btn = e.target.closest(".category-header");
        if (!btn) return;
        const block = btn.closest(".category-block");
        if (block) toggleCategory(block);
    });
    document.getElementById("expand-all")
        ?.addEventListener("click", () => setAllCollapsed(false));
    document.getElementById("collapse-all")
        ?.addEventListener("click", () => setAllCollapsed(true));
}

function renderSpecSummary(categories) {
    const specTools = [];
    for (const cat of categories) {
        for (const t of cat.tools) {
            if (t.sends_spec_command) {
                specTools.push({ ...t, category: cat.category });
            }
        }
    }
    document.getElementById("spec-count").textContent =
        `${specTools.length} tool${specTools.length === 1 ? "" : "s"}`;

    if (specTools.length === 0) {
        document.getElementById("spec-table-host").innerHTML =
            '<div class="muted" style="padding:16px;">No SPEC-bound tools registered.</div>';
        return;
    }

    const rows = specTools.map(t => `
        <tr>
            <td><a href="#tool-${escapeHtml(t.name)}"><code>${escapeHtml(t.name)}</code></a></td>
            <td><code>${escapeHtml(t.spec_command)}</code></td>
            <td class="spec-category">${escapeHtml(t.category)}</td>
        </tr>
    `).join("");

    document.getElementById("spec-table-host").innerHTML = `
        <table>
            <thead>
                <tr>
                    <th>Tool</th>
                    <th>SPEC command</th>
                    <th>Category</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    `;
}

function renderReferences(refs) {
    const host = document.getElementById("refs-host");
    if (!refs || refs.length === 0) {
        host.innerHTML = '<div class="muted" style="padding:16px;">No reference docs.</div>';
        return;
    }
    host.innerHTML = `<ul class="refs-list">${refs.map(r => `
        <li>
            <code>${escapeHtml(r.name)}</code>
            <span>${escapeHtml(r.description || "")}</span>
        </li>
    `).join("")}</ul>`;
}

function applyFilter() {
    const q = (document.getElementById("tool-search").value || "")
        .trim().toLowerCase();
    const cards = document.querySelectorAll(".tool-card");
    cards.forEach(card => {
        if (!q) {
            card.classList.remove("hidden");
            return;
        }
        const hay = card.textContent.toLowerCase();
        card.classList.toggle("hidden", !hay.includes(q));
    });
    // hide categories with zero visible cards
    document.querySelectorAll(".category-block").forEach(block => {
        const any = block.querySelector(".tool-card:not(.hidden)");
        block.style.display = any ? "" : "none";
    });
    // While search is active, force every category open so matches are
    // never hidden behind a collapsed header. The persisted collapsed
    // state in localStorage is untouched; we just visually override.
    // When the query clears, restore the user's chosen collapsed state.
    const searching = q.length > 0;
    document.querySelector(".tools-page")
        .classList.toggle("searching", searching);
    if (!searching) applyCollapsedState();
}

async function load() {
    let payload;
    try {
        const r = await fetch("/api/tools");
        payload = await r.json();
    } catch (e) {
        document.getElementById("categories").innerHTML =
            '<div class="muted" style="padding:32px;text-align:center;">Failed to load /api/tools.</div>';
        return;
    }
    const cats = payload.categories || [];
    document.getElementById("categories").innerHTML = renderCategories(cats);
    renderSpecSummary(cats);
    renderReferences(payload.references || []);
    applyCollapsedState();
    wireCollapse();

    // Scroll to anchor (e.g. /tools#tool-align_beamline) after render.
    // If the target is inside a collapsed category, expand it first.
    if (location.hash) {
        const target = document.querySelector(location.hash);
        if (target) {
            const block = target.closest(".category-block");
            if (block && block.classList.contains("collapsed")) {
                toggleCategory(block, false);
            }
            target.scrollIntoView({ behavior: "instant", block: "start" });
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("tool-search")
        .addEventListener("input", applyFilter);
    const compact = document.getElementById("compact-toggle");
    compact.addEventListener("change", () => {
        document.querySelector(".tools-page")
            .classList.toggle("compact", compact.checked);
    });
    load();
});
