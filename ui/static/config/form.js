/**
 * BL15-2 Experiment Configuration Form
 * Two-tab layout: Experiment Setup (staff) and Sample Holder (user).
 * Handles dynamic element/sample rows, energy lookups, validation, and submission.
 */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let elementCount = 0;
let sampleCount = 0;
let activeTab = 'experiment';

// Populated from /api/defaults on page load; used to build the element dropdown
// and (implicitly via the server) to filter edges/lines by accessible energy.
let COMMON_ELEMENTS = [];
let ACCESSIBLE_ENERGY_RANGE_eV = [4000, 25000];  // overwritten by defaults

// Per-element-card cache: { [idx]: { edges, lines_by_edge } } from /api/element_info
const _elementInfoCache = {};

const CRYSTAL_CUTS = [
    { hkl: '1 1 1', type: 'Si', common_for: ['Fe', 'Mn', 'Cr', 'Co'] },
    { hkl: '3 1 1', type: 'Si', common_for: ['Zn', 'As', 'Se', 'Pb', 'Cu', 'Ni'] },
    { hkl: '6 4 2', type: 'Si', common_for: ['Zn'] },
    { hkl: '9 1 1', type: 'Si', common_for: ['As', 'Pb'] },
    { hkl: '8 4 4', type: 'Si', common_for: ['Se'] },
];

// Gain dropdown option HTML (reused in every sample card)
const I0_GAIN_OPTIONS = `
    <option value="">Default (auto)</option>
    <option value="1 nA/V">1 nA/V</option>
    <option value="2 nA/V">2 nA/V</option>
    <option value="5 nA/V">5 nA/V</option>
    <option value="10 nA/V">10 nA/V</option>
    <option value="20 nA/V">20 nA/V</option>
    <option value="50 nA/V">50 nA/V</option>
    <option value="100 nA/V">100 nA/V</option>
    <option value="200 nA/V">200 nA/V</option>
    <option value="500 nA/V">500 nA/V</option>`;

const I0_OFFSET_OPTIONS = `
    <option value="">Default (auto)</option>
    <option value="1 pA">1 pA</option>
    <option value="2 pA">2 pA</option>
    <option value="5 pA">5 pA</option>
    <option value="10 pA">10 pA</option>
    <option value="20 pA">20 pA</option>
    <option value="50 pA">50 pA</option>
    <option value="100 pA">100 pA</option>`;

const I1_GAIN_OPTIONS = `
    <option value="">Default (auto)</option>
    <option value="100 uA/V">100 uA/V</option>
    <option value="200 uA/V">200 uA/V</option>
    <option value="500 uA/V">500 uA/V</option>
    <option value="1 mA/V">1 mA/V</option>
    <option value="2 mA/V">2 mA/V</option>
    <option value="5 mA/V">5 mA/V</option>`;

// ---------------------------------------------------------------------------
// Tab Switching
// ---------------------------------------------------------------------------

function switchTab(tabName) {
    activeTab = tabName;
    clearMessages();

    // Update tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(btn => {
        if ((tabName === 'experiment' && btn.textContent.includes('Experiment')) ||
            (tabName === 'samples' && btn.textContent.includes('Sample'))) {
            btn.classList.add('active');
        }
    });

    // Show/hide tab content
    document.getElementById('tab-experiment').classList.toggle('hidden', tabName !== 'experiment');
    document.getElementById('tab-samples').classList.toggle('hidden', tabName !== 'samples');

    // When switching to samples tab, refresh the experiment summary banner
    if (tabName === 'samples') {
        loadExperimentSummary();
    }
}

// ---------------------------------------------------------------------------
// Element Management
// ---------------------------------------------------------------------------

function addElement(data) {
    elementCount++;
    const idx = elementCount;
    const container = document.getElementById('elements-container');

    const card = document.createElement('div');
    card.className = 'element-card';
    card.id = `element-card-${idx}`;
    card.dataset.idx = idx;

    const sym = data ? data.symbol : '';
    const edge = data ? data.edge : '';
    const emLine = data ? (data.emission_line || '') : '';
    const mode = data ? (data.measurement_mode || 'XES') : 'XES';
    const incE = data ? data.incident_energy : '';
    const emE = data ? data.emission_energy : '';
    const cType = data ? data.crystal_type : 0;
    const hkl = data ? data.crystal_hkl : '';
    const rowR = data ? data.row_radius : 1000;
    const nC = data ? data.n_crystals : 3;
    const vCounter = data ? (data.vortex_counter || 'vortDT') : 'vortDT';
    const isTFY = mode === 'TFY';

    // Build element options
    let elemOpts = '<option value="">-- Select --</option>';
    COMMON_ELEMENTS.forEach(e => {
        const sel = (e.symbol === sym) ? ' selected' : '';
        elemOpts += `<option value="${e.symbol}"${sel}>${e.symbol} - ${e.name}</option>`;
    });
    const otherSel = (sym && !COMMON_ELEMENTS.find(e => e.symbol === sym)) ? ' selected' : '';
    elemOpts += `<option value="__other"${otherSel}>Other...</option>`;

    card.innerHTML = `
        <div class="card-header">
            <span class="card-title">Element ${idx}</span>
            <button type="button" class="btn btn-remove" onclick="removeElement(${idx})">Remove</button>
        </div>
        <div class="form-row">
            <div class="form-group medium">
                <label>Element <span class="required">*</span></label>
                <select id="elem_${idx}_symbol_select" onchange="onElementSelect(${idx})">
                    ${elemOpts}
                </select>
            </div>
            <div class="form-group narrow" id="elem_${idx}_other_wrap" style="${otherSel ? '' : 'display:none'}">
                <label>Symbol</label>
                <input type="text" id="elem_${idx}_other" maxlength="3" value="${otherSel ? sym : ''}"
                       placeholder="e.g. Ti" onblur="onOtherSymbolBlur(${idx})">
            </div>
            <div class="form-group narrow">
                <label>Edge <span class="required">*</span></label>
                <select id="elem_${idx}_edge" onchange="onEdgeChange(${idx})" data-pending="${esc(edge)}">
                    <option value="">--</option>
                </select>
            </div>
            <div class="form-group narrow">
                <label>Measurement</label>
                <select id="elem_${idx}_mode" onchange="toggleTFY(${idx})">
                    <option value="XES"${!isTFY ? ' selected' : ''}>XES</option>
                    <option value="TFY"${isTFY ? ' selected' : ''}>TFY</option>
                </select>
            </div>
            <div class="form-group">
                <label>Incident Energy (eV) <span class="required">*</span></label>
                <input type="number" id="elem_${idx}_incident" step="0.1" value="${incE}"
                       placeholder="Auto-filled from edge" oninput="this.dataset.userEdited=1">
            </div>
        </div>
        <div id="elem_${idx}_xes_fields" ${isTFY ? 'style="display:none"' : ''}>
            <div class="form-row">
                <div class="form-group medium">
                    <label>Emission Line <span class="required">*</span></label>
                    <select id="elem_${idx}_emission_line" onchange="onEmissionLineChange(${idx})" data-pending="${esc(emLine)}">
                        <option value="">-- Select element first --</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Emission Energy (eV) <span class="required">*</span></label>
                    <input type="number" id="elem_${idx}_emission" step="0.1" value="${emE}"
                           placeholder="Auto-filled from line" oninput="this.dataset.userEdited=1">
                </div>
                <div class="form-group narrow">
                    <label>Crystal <span class="required">*</span></label>
                    <select id="elem_${idx}_crystal_type">
                        <option value="0"${cType === 0 ? ' selected' : ''}>Si</option>
                        <option value="1"${cType === 1 ? ' selected' : ''}>Ge</option>
                    </select>
                </div>
                <div class="form-group medium">
                    <label>Crystal hkl <span class="required">*</span></label>
                    <input type="text" id="elem_${idx}_hkl" value="${hkl}" placeholder="e.g. 6 4 2">
                </div>
                <div class="form-group narrow">
                    <label>Row Radius</label>
                    <input type="number" id="elem_${idx}_row_radius" value="${rowR}">
                </div>
                <div class="form-group narrow">
                    <label>Crystals (1-7)</label>
                    <input type="number" id="elem_${idx}_n_crystals" value="${nC}" min="1" max="7">
                </div>
                <div class="form-group narrow">
                    <label>Vortex Counter</label>
                    <select id="elem_${idx}_vortex">
                        <option value="vortDT"${vCounter === 'vortDT' ? ' selected' : ''}>vortDT</option>
                        <option value="vortDT2"${vCounter === 'vortDT2' ? ' selected' : ''}>vortDT2</option>
                        <option value="vortDT3"${vCounter === 'vortDT3' ? ' selected' : ''}>vortDT3</option>
                        <option value="vortDT4"${vCounter === 'vortDT4' ? ' selected' : ''}>vortDT4</option>
                    </select>
                </div>
            </div>
        </div>
    `;

    container.appendChild(card);

    // Kick off element info lookup (populates edge + emission line dropdowns).
    // If data was passed in, the pending attribute on each <select> gets picked
    // up once the API response arrives.
    if (sym) {
        loadElementInfo(idx, sym);
    }

    // Auto-suggest crystal cut
    if (sym && !hkl && !isTFY) {
        suggestCrystalCut(idx, sym);
    }

    updateSampleElementDropdowns();
}

function removeElement(idx) {
    const card = document.getElementById(`element-card-${idx}`);
    if (card) card.remove();
    delete _elementInfoCache[idx];
    updateSampleElementDropdowns();
}

function toggleTFY(idx) {
    const mode = document.getElementById(`elem_${idx}_mode`).value;
    const xesFields = document.getElementById(`elem_${idx}_xes_fields`);
    if (mode === 'TFY') {
        xesFields.style.display = 'none';
    } else {
        xesFields.style.display = '';
        // Make sure the emission line dropdown is populated for current edge
        const edgeSel = document.getElementById(`elem_${idx}_edge`);
        if (edgeSel && edgeSel.value) {
            populateEmissionLineDropdown(idx, edgeSel.value);
        }
    }
}

function onElementSelect(idx) {
    const sel = document.getElementById(`elem_${idx}_symbol_select`);
    const otherWrap = document.getElementById(`elem_${idx}_other_wrap`);

    if (sel.value === '__other') {
        otherWrap.style.display = '';
        document.getElementById(`elem_${idx}_other`).focus();
        return; // wait for blur to trigger lookup
    }
    otherWrap.style.display = 'none';

    const symbol = sel.value;
    if (!symbol) {
        // Cleared — reset edge and emission line dropdowns
        setDropdown(`elem_${idx}_edge`, [], '');
        setDropdown(`elem_${idx}_emission_line`, [], '');
        return;
    }

    suggestCrystalCut(idx, symbol);
    // User changed element explicitly — clear any user-edited flags so auto-fill works
    const incInput = document.getElementById(`elem_${idx}_incident`);
    const emInput = document.getElementById(`elem_${idx}_emission`);
    if (incInput) delete incInput.dataset.userEdited;
    if (emInput) delete emInput.dataset.userEdited;

    loadElementInfo(idx, symbol);
    updateSampleElementDropdowns();
}

function onOtherSymbolBlur(idx) {
    const sym = (document.getElementById(`elem_${idx}_other`).value || '').trim();
    if (sym) {
        loadElementInfo(idx, sym);
    }
    // Refresh sample dropdowns + foil-element placeholder so the
    // user sees the default they'll get if they leave that input
    // blank.
    updateSampleElementDropdowns();
}

function getElementSymbol(idx) {
    const sel = document.getElementById(`elem_${idx}_symbol_select`);
    if (!sel) return '';
    if (sel.value === '__other') {
        return (document.getElementById(`elem_${idx}_other`).value || '').trim();
    }
    return sel.value;
}

function suggestCrystalCut(idx, symbol) {
    const hklInput = document.getElementById(`elem_${idx}_hkl`);
    if (!hklInput || hklInput.value) return; // Don't overwrite user input

    for (const cut of CRYSTAL_CUTS) {
        if (cut.common_for.includes(symbol)) {
            hklInput.value = cut.hkl;
            break;
        }
    }
}

// ---------------------------------------------------------------------------
// Dynamic edge + emission line population (xraydb-backed)
// ---------------------------------------------------------------------------

/** Populate a <select> with [{value, label}] options and set its value. */
function setDropdown(selectId, options, selectedValue) {
    const sel = document.getElementById(selectId);
    if (!sel) return;
    sel.innerHTML = '';
    if (options.length === 0) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = '-- none in range --';
        sel.appendChild(opt);
        sel.value = '';
        return;
    }
    options.forEach(o => {
        const opt = document.createElement('option');
        opt.value = o.value;
        opt.textContent = o.label;
        sel.appendChild(opt);
    });
    // Prefer the explicit selectedValue, then any data-pending attribute (set
    // at card-creation time when loading from DB), then default to first option.
    const pending = sel.dataset.pending || '';
    let target = selectedValue;
    if (!target && pending && options.some(o => o.value === pending)) {
        target = pending;
    }
    if (!target) target = options[0].value;
    sel.value = target;
    // Clear pending so subsequent updates don't reuse a stale value
    sel.dataset.pending = '';
}

/** Fetch edges + emission lines for this element, populate both dropdowns. */
function loadElementInfo(idx, symbol) {
    fetch('/api/element_info', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: symbol }),
    })
    .then(r => r.json())
    .then(data => {
        if (!data.success) {
            console.warn('element_info failed:', data.error);
            return;
        }
        _elementInfoCache[idx] = data;

        const edgeOpts = (data.edges || []).map(e => ({
            value: e.edge,
            label: `${e.edge} (${e.energy} eV)`,
        }));
        setDropdown(`elem_${idx}_edge`, edgeOpts, '');

        // Trigger edge change handler to cascade into emission line dropdown and
        // energy fields, now that the edge value is set.
        onEdgeChange(idx);
    })
    .catch(err => {
        console.warn('element_info fetch failed:', err);
    });
}

/** When the edge dropdown changes: fill incident energy, update line dropdown. */
function onEdgeChange(idx) {
    const edgeSel = document.getElementById(`elem_${idx}_edge`);
    const info = _elementInfoCache[idx];
    if (!edgeSel || !info) return;

    const edge = edgeSel.value;
    if (!edge) return;

    // Fill incident energy from edge (unless user edited)
    const edgeInfo = (info.edges || []).find(e => e.edge === edge);
    const incInput = document.getElementById(`elem_${idx}_incident`);
    if (incInput && !incInput.dataset.userEdited && edgeInfo) {
        incInput.value = edgeInfo.energy;
    }

    populateEmissionLineDropdown(idx, edge);
}

function populateEmissionLineDropdown(idx, edge) {
    const info = _elementInfoCache[idx];
    if (!info) return;

    const lines = (info.lines_by_edge || {})[edge] || [];
    const lineOpts = lines.map(l => ({
        value: l.line,
        label: `${l.line} (${l.energy} eV)`,
    }));
    setDropdown(`elem_${idx}_emission_line`, lineOpts, '');

    // Cascade to fill emission energy
    onEmissionLineChange(idx);
}

function onEmissionLineChange(idx) {
    const info = _elementInfoCache[idx];
    const lineSel = document.getElementById(`elem_${idx}_emission_line`);
    const emInput = document.getElementById(`elem_${idx}_emission`);
    if (!info || !lineSel || !emInput) return;

    const lineName = lineSel.value;
    if (!lineName) return;

    // Find this line's energy in the cache
    let energy = null;
    for (const [, lines] of Object.entries(info.lines_by_edge || {})) {
        const found = lines.find(l => l.line === lineName);
        if (found) { energy = found.energy; break; }
    }

    if (energy !== null && !emInput.dataset.userEdited) {
        emInput.value = energy;
    }
}

// ---------------------------------------------------------------------------
// Sample Management
// ---------------------------------------------------------------------------

function getSampleEnv() {
    const envSel = document.getElementById('sample_env');
    return envSel ? envSel.value : 'ambient';
}

function addSample(data) {
    sampleCount++;
    const idx = sampleCount;
    const container = document.getElementById('samples-container');

    const card = document.createElement('div');
    card.className = 'sample-card';
    card.id = `sample-card-${idx}`;
    card.dataset.idx = idx;

    const sName = data ? data.name : '';
    const sElem = data ? data.element : '';
    // Filter is an optional starting suggestion. Sample alignment + survey
    // refine it; everything else (positions, reps, count time, gains,
    // emiss override) is determined by the alignment / survey phases, not
    // configured here.
    const xasFilter = (data && data.xas_filter != null) ? data.xas_filter : '';
    const minScans = (data && data.min_scans != null) ? data.min_scans : '';

    const elemOptions = buildElementOptions(sElem);

    card.innerHTML = `
        <div class="card-header">
            <span class="card-title">Sample ${idx}</span>
            <button type="button" class="btn btn-remove" onclick="removeSample(${idx})">Remove</button>
        </div>

        <div class="form-row">
            <div class="form-group wide">
                <label>Sample Name <span class="required">*</span></label>
                <input type="text" id="samp_${idx}_name" value="${esc(sName)}" placeholder="Used as SPEC filename">
            </div>
            <div class="form-group medium">
                <label>Element <span class="required">*</span></label>
                <select id="samp_${idx}_element" class="sample-element-select">
                    ${elemOptions}
                </select>
            </div>
            <div class="form-group narrow">
                <label>Filter</label>
                <input type="number" id="samp_${idx}_xas_filter" value="${xasFilter}" min="0" max="255" placeholder="optional">
            </div>
            <div class="form-group narrow">
                <label>Min scans</label>
                <input type="number" id="samp_${idx}_min_scans" value="${minScans}" min="1" placeholder="optional">
            </div>
        </div>
    `;

    container.appendChild(card);
}

function removeSample(idx) {
    const card = document.getElementById(`sample-card-${idx}`);
    if (card) card.remove();
}

function buildElementOptions(selected) {
    // Try to build from element cards on Tab 1
    const cards = document.querySelectorAll('.element-card');
    let opts = '<option value="">-- Select --</option>';

    if (cards.length > 0) {
        cards.forEach(card => {
            const idx = card.dataset.idx;
            const sym = getElementSymbol(parseInt(idx));
            if (sym) {
                const sel = (sym === selected) ? ' selected' : '';
                opts += `<option value="${sym}"${sel}>${sym}</option>`;
            }
        });
    } else if (_cachedElements && _cachedElements.length > 0) {
        // Fall back to cached elements from experiment summary
        _cachedElements.forEach(el => {
            const sel = (el.symbol === selected) ? ' selected' : '';
            opts += `<option value="${el.symbol}"${sel}>${el.symbol}</option>`;
        });
    }
    return opts;
}

// Cache of elements from the active experiment (for Tab 2 when Tab 1 elements aren't in DOM)
let _cachedElements = [];

function updateSampleElementDropdowns() {
    const selects = document.querySelectorAll('.sample-element-select');
    selects.forEach(sel => {
        const current = sel.value;
        const opts = buildElementOptions(current);
        sel.innerHTML = opts;
    });
    // Whenever the science elements change, refresh the foil-element
    // placeholder so users see the default that the server will apply
    // if they leave the field blank.
    _updateFoilElementPlaceholder();
}

/**
 * Reflect the first configured science-target element as the
 * placeholder on the calibration foil element input. Mirrors the
 * server-side default in submit_experiment so users can see what the
 * system will pick if they leave the foil element blank.
 */
function _updateFoilElementPlaceholder() {
    const foilInput = document.getElementById('calibration_foil_element');
    if (!foilInput) return;
    let firstSym = '';
    const cards = document.querySelectorAll('.element-card');
    for (const card of cards) {
        const idx = parseInt(card.dataset.idx);
        const sym = getElementSymbol(idx);
        if (sym) { firstSym = sym; break; }
    }
    if (!firstSym && _cachedElements && _cachedElements.length > 0) {
        firstSym = _cachedElements[0].symbol || '';
    }
    foilInput.placeholder = firstSym
        ? `Defaults to ${firstSym} (first element)`
        : 'Defaults to the science-target element';
}

// ---------------------------------------------------------------------------
// Advanced Section Toggle
// ---------------------------------------------------------------------------

function toggleAdvanced() {
    const header = document.querySelector('.collapsible-header');
    const content = document.getElementById('advanced-content');
    header.classList.toggle('collapsed');
    content.classList.toggle('collapsed');
}

// ---------------------------------------------------------------------------
// Data Gathering (split by tab)
// ---------------------------------------------------------------------------

function gatherExperimentData() {
    const endTimeRaw = val('end_time');
    const data = {
        experiment_id: document.getElementById('experiment_id').value || undefined,
        experiment_name: val('experiment_name'),
        mono_crystal: val('mono_crystal'),
        beam_size_h: document.getElementById('beam_size_h').value,
        beam_size_v: document.getElementById('beam_size_v').value,
        mirrors_out: document.getElementById('mirrors_out').checked,
        sample_env: val('sample_env'),
        calibration_foil_element: val('calibration_foil_element'),
        calibration_foil_detector: val('calibration_foil_detector') || 'I2',
        data_directory: val('data_directory'),
        end_time: endTimeRaw || null,
        llm_enabled: document.getElementById('llm_enabled').checked,
        llm_decide_enabled: document.getElementById('llm_decide_enabled').checked,
        elements: [],
    };

    document.querySelectorAll('.element-card').forEach(card => {
        const idx = parseInt(card.dataset.idx);
        const mode = val(`elem_${idx}_mode`) || 'XES';
        const el = {
            symbol: getElementSymbol(idx),
            edge: val(`elem_${idx}_edge`),
            measurement_mode: mode,
            incident_energy: val(`elem_${idx}_incident`),
            vortex_counter: val(`elem_${idx}_vortex`) || 'vortDT',
        };

        if (mode === 'XES') {
            el.emission_line = val(`elem_${idx}_emission_line`) || '';
            el.emission_energy = val(`elem_${idx}_emission`);
            el.crystal_type = parseInt(val(`elem_${idx}_crystal_type`) || '0');
            el.crystal_hkl = val(`elem_${idx}_hkl`);
            el.row_radius = parseInt(val(`elem_${idx}_row_radius`) || '1000');
            el.n_crystals = parseInt(val(`elem_${idx}_n_crystals`) || '3');
        } else {
            el.emission_line = '';
            el.emission_energy = 0;
            el.crystal_type = 0;
            el.crystal_hkl = '0 0 0';
            el.row_radius = 0;
            el.n_crystals = 0;
        }

        data.elements.push(el);
    });

    return data;
}

function gatherSampleHolderData() {
    const data = {
        experiment_id: document.getElementById('experiment_id').value || undefined,
        sample_holder_name: val('sample_holder_name'),
        samples: [],
    };

    document.querySelectorAll('.sample-card').forEach(card => {
        const idx = parseInt(card.dataset.idx);
        const filterRaw = val(`samp_${idx}_xas_filter`);
        const minScansRaw = val(`samp_${idx}_min_scans`);

        // Form only collects name/element/filter/min_scans. Everything
        // else (positions, reps, count time, emiss override, gains) is
        // determined by alignment + survey phases; we send harmless
        // defaults here so the server validator passes.
        data.samples.push({
            name: val(`samp_${idx}_name`),
            element: val(`samp_${idx}_element`),
            enabled: true,
            sx_lo: 0, sx_hi: 0, sx_del: 0,
            sy_lo: 0, sy_hi: 0, sy_del: 0,
            sz_lo: 0, sz_hi: 0, sz_del: 0,
            do_xas: true,
            xas_reps: 10,
            xas_time: 0.5,
            xas_filter: filterRaw === '' ? 0 : parseInt(filterRaw, 10) || 0,
            xas_emiss_override: null,
            i0_gain: '',
            i0_offset: '',
            i1_gain: '',
            do_rixs: false,
            rixs_time: 1.0,
            rixs_start: null,
            rixs_end: null,
            rixs_step: -0.2,
            rixs_filter: 0,
            min_scans: minScansRaw === '' ? null : parseInt(minScansRaw, 10) || null,
        });
    });

    return data;
}

// Backwards-compatible combined gather
function gatherFormData() {
    const expData = gatherExperimentData();
    const sampleData = gatherSampleHolderData();
    return { ...expData, ...sampleData };
}

// ---------------------------------------------------------------------------
// Form Submission
// ---------------------------------------------------------------------------

function submitExperiment() {
    clearMessages();
    clearFieldErrors();

    const btn = document.getElementById('submit-experiment-btn');
    btn.disabled = true;
    btn.textContent = 'Saving...';

    const data = gatherExperimentData();

    fetch('/api/submit_experiment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    })
    .then(r => r.json())
    .then(result => {
        btn.disabled = false;
        btn.textContent = 'Save Experiment';

        if (result.success) {
            document.getElementById('experiment_id').value = result.experiment_id;

            showSuccess(
                `Experiment "${result.summary.experiment}" saved.`,
                `Elements: ${result.summary.elements} | Crystal: ${result.summary.mono_crystal} | Beam: ${result.summary.beam_size}`,
                'Next: open the dashboard and let the agent run beamline + spectrometer alignment. You can configure the sample holder later, before sample alignment starts.',
                {
                    text: 'Open Dashboard →',
                    href: '/',
                }
            );
        } else {
            showErrors(result.errors || ['Unknown error']);
        }
    })
    .catch(err => {
        btn.disabled = false;
        btn.textContent = 'Save Experiment';
        showErrors([`Network error: ${err.message}`]);
    });
}

function submitSampleHolder() {
    clearMessages();
    clearFieldErrors();

    const btn = document.getElementById('submit-samples-btn');
    btn.disabled = true;
    btn.textContent = 'Saving...';

    const data = gatherSampleHolderData();

    fetch('/api/submit_sample_holder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    })
    .then(r => r.json())
    .then(result => {
        btn.disabled = false;
        btn.textContent = 'Save Sample Holder';

        if (result.success) {
            showSuccess(
                `Sample holder saved.`,
                `${result.summary.holder}: ${result.summary.n_samples} samples. Configuration complete.`,
                'The experiment is ready. Open the dashboard and click Run on each phase tile to drive the run.',
                {
                    text: 'Open Dashboard →',
                    href: '/',
                }
            );
        } else {
            showErrors(result.errors || ['Unknown error']);
        }
    })
    .catch(err => {
        btn.disabled = false;
        btn.textContent = 'Save Sample Holder';
        showErrors([`Network error: ${err.message}`]);
    });
}

// Backwards-compatible combined submit
function submitForm() {
    clearMessages();
    clearFieldErrors();

    const data = gatherFormData();

    fetch('/api/submit_collection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    })
    .then(r => r.json())
    .then(result => {
        if (result.success) {
            document.getElementById('experiment_id').value = result.experiment_id;
            showSuccess(
                `Configuration saved for "${result.summary.experiment}".`,
                `Sample holder: ${result.summary.holder} (${result.summary.n_samples} samples, ${result.summary.elements})`,
                'In SPEC, run: reload_experiment_config'
            );
        } else {
            showErrors(result.errors || ['Unknown error']);
        }
    })
    .catch(err => {
        showErrors([`Network error: ${err.message}`]);
    });
}

// ---------------------------------------------------------------------------
// Experiment Summary Banner (Tab 2)
// ---------------------------------------------------------------------------

function loadExperimentSummary() {
    const expId = document.getElementById('experiment_id').value;
    const banner = document.getElementById('experiment-summary-banner');
    const holderSection = document.getElementById('sample-holder-section');
    const samplesSection = document.getElementById('samples-section');
    const submitArea = document.getElementById('submit-samples-area');

    if (!expId) {
        banner.innerHTML = '<p class="banner-placeholder">No experiment configured yet. Save an experiment in the Experiment Setup tab first.</p>';
        holderSection.style.display = 'none';
        samplesSection.style.display = 'none';
        submitArea.style.display = 'none';
        return;
    }

    fetch(`/api/experiment_summary/${expId}`)
    .then(r => r.json())
    .then(result => {
        if (result.success) {
            const exp = result.experiment;
            const elems = result.elements.map(e => {
                const mode = e.measurement_mode || 'XES';
                return mode === 'TFY' ? `${e.symbol} ${e.edge} (TFY)` : `${e.symbol} ${e.edge}`;
            }).join(', ');

            // Cache elements for sample dropdowns
            _cachedElements = result.elements;

            banner.innerHTML = `
                <div class="banner-title">Active Experiment: ${esc(exp.name)}</div>
                <div class="banner-details">
                    <span>Crystal: ${esc(exp.mono_crystal)}</span>
                    <span>Beam: ${exp.mirrors_out ? 'Mirrors out' : esc('H:' + (exp.beam_size_h || '?') + ' V:' + (exp.beam_size_v || '?'))}</span>
                    <span>Env: ${esc(exp.sample_env)}</span>
                    <span>Elements: ${esc(elems)}</span>
                </div>
            `;

            // Show the sample holder form sections
            holderSection.style.display = '';
            samplesSection.style.display = '';
            submitArea.style.display = '';

            // Refresh element dropdowns in existing sample cards
            updateSampleElementDropdowns();

            // Add a default sample if none exist
            if (document.querySelectorAll('.sample-card').length === 0) {
                addSample();
            }
        } else {
            banner.innerHTML = '<p class="banner-placeholder">Could not load experiment info.</p>';
            holderSection.style.display = 'none';
            samplesSection.style.display = 'none';
            submitArea.style.display = 'none';
        }
    })
    .catch(() => {
        banner.innerHTML = '<p class="banner-placeholder">Could not load experiment info.</p>';
        holderSection.style.display = 'none';
        samplesSection.style.display = 'none';
        submitArea.style.display = 'none';
    });
}

// ---------------------------------------------------------------------------
// Load Experiment
// ---------------------------------------------------------------------------

/** Fetch /api/defaults once on init: populates COMMON_ELEMENTS and energy range. */
function loadFormDefaults() {
    return fetch('/api/defaults')
        .then(r => r.json())
        .then(defaults => {
            if (defaults && Array.isArray(defaults.common_elements)) {
                COMMON_ELEMENTS = defaults.common_elements;
            }
            if (defaults && Array.isArray(defaults.accessible_energy_range_eV)) {
                ACCESSIBLE_ENERGY_RANGE_eV = defaults.accessible_energy_range_eV;
            }
        })
        .catch(err => {
            console.warn('Failed to load /api/defaults, using hard-coded fallback:', err);
        });
}

// Promise tracking the in-flight active-experiment load. Used so deep-links
// like ?tab=samples can wait for experiment_id to be populated before
// rendering the sample-holder banner (otherwise the banner reads an empty
// experiment_id and shows "No experiment configured yet" even when one is).
let _activeExperimentLoad = null;

function loadActiveExperiment() {
    // Wait for defaults before building any element cards so the element dropdown
    // is populated from the server list rather than the empty fallback.
    // Returns a promise (also cached on _activeExperimentLoad) that resolves
    // once the active experiment (if any) has been fetched and populated.
    if (_activeExperimentLoad) return _activeExperimentLoad;
    _activeExperimentLoad = loadFormDefaults().then(() => {
        return fetch('/api/load_active')
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    populateForm(data);
                } else {
                    // No active experiment -- start fresh with defaults
                    addElement();
                }
            })
            .catch(() => {
                // Server not available or no active experiment
                addElement();
            });
    });
    return _activeExperimentLoad;
}

function loadExperiment(experimentId) {
    fetch(`/api/load_experiment/${experimentId}`)
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            populateForm(data);
        } else {
            showErrors([data.error || 'Failed to load experiment']);
        }
    })
    .catch(err => {
        showErrors([`Failed to load experiment: ${err.message}`]);
    });
}

function populateForm(data) {
    const exp = data.experiment;

    // Populate Tab 1 fields
    document.getElementById('experiment_id').value = exp.id || '';
    document.getElementById('experiment_name').value = exp.name || '';
    document.getElementById('mono_crystal').value = exp.mono_crystal || 'A';
    document.getElementById('beam_size_h').value = exp.beam_size_h || 'big';
    document.getElementById('beam_size_v').value = exp.beam_size_v || 'big';
    document.getElementById('mirrors_out').checked = !!exp.mirrors_out;
    // Update beam size controls state
    _updateMirrorsOutState(!!exp.mirrors_out);
    document.getElementById('sample_env').value = exp.sample_env || 'ambient';
    document.getElementById('calibration_foil_element').value =
        exp.calibration_foil_element || '';
    document.getElementById('calibration_foil_detector').value =
        exp.calibration_foil_detector || 'I2';
    document.getElementById('data_directory').value = exp.data_directory || '';

    // End time (datetime-local input expects "YYYY-MM-DDTHH:MM" format)
    const etInput = document.getElementById('end_time');
    if (etInput && exp.end_time) {
        const et = exp.end_time.slice(0, 16);
        etInput.value = et;
    } else if (etInput) {
        etInput.value = '';
    }

    // Created at (read-only display)
    const caGroup = document.getElementById('created_at_group');
    const caDisplay = document.getElementById('created_at_display');
    if (caGroup && caDisplay && exp.created_at) {
        caDisplay.value = new Date(exp.created_at).toLocaleString();
        caGroup.style.display = '';
    } else if (caGroup) {
        caGroup.style.display = 'none';
    }

    // Advanced
    document.getElementById('llm_enabled').checked = exp.llm_enabled !== false;
    document.getElementById('llm_decide_enabled').checked = exp.llm_decide_enabled !== false;

    // Clear and re-add elements
    document.getElementById('elements-container').innerHTML = '';
    elementCount = 0;
    (data.elements || []).forEach(el => addElement(el));
    if (!data.elements || data.elements.length === 0) addElement();

    // Cache elements for Tab 2
    _cachedElements = (data.elements || []).map(el => ({
        symbol: el.symbol,
        edge: el.edge,
        measurement_mode: el.measurement_mode || 'XES',
    }));

    // Populate Tab 2 fields
    document.getElementById('sample_holder_name').value = exp.sample_holder_name || '';

    // Clear and re-add samples
    document.getElementById('samples-container').innerHTML = '';
    sampleCount = 0;
    (data.samples || []).forEach(s => addSample(s));
}

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------

function showErrors(errors) {
    const area = document.getElementById('message-area');
    let html = '<div class="error-list"><h3>Validation Errors</h3><ul>';
    errors.forEach(e => {
        html += `<li>${esc(e)}</li>`;
    });
    html += '</ul></div>';
    area.innerHTML = html;
    area.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function showSuccess(title, detail, nextStep, cta) {
    const area = document.getElementById('message-area');
    const nextHtml = nextStep
        ? `<p class="success-next">${esc(nextStep)}</p>`
        : "";
    const ctaHtml = cta
        ? `<div class="success-cta">
               <a href="${esc(cta.href)}" class="btn btn-cta-primary">${esc(cta.text)}</a>
               ${cta.secondary ? `<a href="${esc(cta.secondary.href)}" class="btn btn-cta-secondary">${esc(cta.secondary.text)}</a>` : ""}
           </div>`
        : "";
    area.innerHTML = `
        <div class="success-box">
            <h3>${esc(title)}</h3>
            <p>${esc(detail)}</p>
            ${nextHtml}
            ${ctaHtml}
        </div>
    `;
    area.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function clearMessages() {
    document.getElementById('message-area').innerHTML = '';
}

function clearFieldErrors() {
    document.querySelectorAll('.error').forEach(el => el.classList.remove('error'));
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function val(id) {
    const el = document.getElementById(id);
    return el ? el.value : '';
}

function numVal(id) {
    const v = val(id);
    if (v === '' || v === null || v === undefined) return '';
    const n = parseFloat(v);
    return isNaN(n) ? '' : n;
}

function esc(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Setup New Experiment
// ---------------------------------------------------------------------------

async function setupNewExperiment() {
    try {
        const r = await fetch('/api/phase/run_status');
        const j = await r.json();
        const phases = (j && j.phases) || {};
        const running = Object.entries(phases)
            .filter(([, info]) => info.state === 'running')
            .map(([slug]) => slug);
        if (running.length > 0) {
            alert(
                'Cannot create a new experiment while agents are running.\n\n' +
                'Running: ' + running.join(', ') + '\n\n' +
                'Stop all agents from the dashboard first.'
            );
            return;
        }
    } catch (e) {
        alert('Could not check agent status: ' + e.message + '\n\nStop all agents before creating a new experiment.');
        return;
    }

    if (!confirm(
        'Start a new experiment?\n\n' +
        'This will clear the form and create a fresh experiment on next Save. ' +
        'The current experiment is not deleted — you can reload it from the dashboard.'
    )) return;

    document.getElementById('experiment_id').value = '';
    document.getElementById('experiment_name').value = '';
    document.getElementById('end_time').value = '';
    document.getElementById('mono_crystal').value = 'A';
    document.getElementById('beam_size_h').value = 'big';
    document.getElementById('beam_size_v').value = 'big';
    document.getElementById('mirrors_out').checked = false;
    _updateMirrorsOutState(false);
    document.getElementById('sample_env').value = 'ambient';
    document.getElementById('calibration_foil_element').value = '';
    document.getElementById('calibration_foil_detector').value = 'I2';
    document.getElementById('data_directory').value = '';
    document.getElementById('llm_enabled').checked = true;
    document.getElementById('llm_decide_enabled').checked = true;

    const caGroup = document.getElementById('created_at_group');
    if (caGroup) caGroup.style.display = 'none';

    document.getElementById('elements-container').innerHTML = '';
    elementCount = 0;
    addElement();

    const samplesContainer = document.getElementById('samples-container');
    if (samplesContainer) samplesContainer.innerHTML = '';
    sampleCount = 0;

    const holderName = document.getElementById('sample_holder_name');
    if (holderName) holderName.value = '';

    clearMessages();
}

// ---------------------------------------------------------------------------
// Mirrors Out Toggle
// ---------------------------------------------------------------------------

function _updateMirrorsOutState(disabled) {
    const bsh = document.getElementById('beam_size_h');
    const bsv = document.getElementById('beam_size_v');
    if (bsh) bsh.disabled = disabled;
    if (bsv) bsv.disabled = disabled;
    // Grey out the parent form-groups if they exist
    const hGroup = bsh ? bsh.closest('.form-group') : null;
    const vGroup = bsv ? bsv.closest('.form-group') : null;
    if (hGroup) hGroup.style.opacity = disabled ? '0.4' : '1';
    if (vGroup) vGroup.style.opacity = disabled ? '0.4' : '1';
}

document.addEventListener('DOMContentLoaded', function () {
    const mirrorsOut = document.getElementById('mirrors_out');
    if (mirrorsOut) {
        mirrorsOut.addEventListener('change', function () {
            _updateMirrorsOutState(this.checked);
        });
    }
    // Honor ?tab=samples (used by the dashboard's Sample Holder
    // Configuration tile) so the page lands directly on the samples tab.
    // We must wait for loadActiveExperiment() to populate experiment_id
    // before switching, otherwise loadExperimentSummary() reads an empty
    // experiment_id and renders "No experiment configured yet" even when
    // an active experiment exists. loadActiveExperiment() is idempotent
    // and returns the same promise the inline init handler kicked off.
    try {
        const params = new URLSearchParams(window.location.search);
        const tab = params.get('tab');
        if (tab === 'samples' || tab === 'experiment') {
            loadActiveExperiment().then(() => switchTab(tab));
        }
    } catch { /* ignore */ }
});
