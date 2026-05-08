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
    const vCh = data ? data.vortex_channel : 1;
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
                    <label>Vortex Ch</label>
                    <select id="elem_${idx}_vortex">
                        <option value="1"${vCh === 1 ? ' selected' : ''}>1 (vortDT)</option>
                        <option value="3"${vCh === 3 ? ' selected' : ''}>3 (vortDT2)</option>
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
    const isLiquidJet = (getSampleEnv() === 'liquid_jet');

    const card = document.createElement('div');
    card.className = 'sample-card';
    card.id = `sample-card-${idx}`;
    card.dataset.idx = idx;

    const sName = data ? data.name : '';
    const sElem = data ? data.element : '';
    const sEnabled = data ? data.enabled : true;
    const doXas = data ? data.do_xas : true;
    const xasReps = data ? data.xas_reps : 10;
    const xasTime = data ? data.xas_time : 0.5;
    const xasFilter = data ? data.xas_filter : 0;
    const xasEmissOvr = data ? (data.xas_emiss_override || '') : '';
    const doRixs = data ? data.do_rixs : false;
    const rixsTime = data ? data.rixs_time : 1.0;
    const rixsStart = data ? (data.rixs_start || '') : '';
    const rixsEnd = data ? (data.rixs_end || '') : '';
    const rixsStep = data ? data.rixs_step : -0.2;
    const rixsFilter = data ? data.rixs_filter : 0;

    // Gain settings (per-sample)
    const i0Gain = data ? (data.i0_gain || '') : '';
    const i0Offset = data ? (data.i0_offset || '') : '';
    const i1Gain = data ? (data.i1_gain || '') : '';

    // Position fields (may be blank pre-alignment)
    const sxLo = data ? (data.sx_lo || '') : '';
    const sxHi = data ? (data.sx_hi || '') : '';
    const syLo = data ? (data.sy_lo || '') : '';
    const syHi = data ? (data.sy_hi || '') : '';
    const szLo = data ? (data.sz_lo || '') : '';
    const szHi = data ? (data.sz_hi || '') : '';
    const sxDel = data ? (data.sx_del || '') : '';
    const syDel = data ? (data.sy_del || '') : '';
    const szDel = data ? (data.sz_del || '') : '';

    // Build element dropdown from current elements
    const elemOptions = buildElementOptions(sElem);

    // Position fields HTML depends on sample environment
    let positionHtml;
    if (isLiquidJet) {
        // Liquid jet: single Sx, Sy, Sz (fixed point, sample replenishes)
        const sx = sxLo || '';
        const sy = syLo || '';
        const sz = szLo || '';
        positionHtml = `
            <div class="form-row">
                <div class="form-group narrow">
                    <label>Sx</label>
                    <input type="number" id="samp_${idx}_sx" step="0.1" value="${sx}" placeholder="">
                </div>
                <div class="form-group narrow">
                    <label>Sy</label>
                    <input type="number" id="samp_${idx}_sy" step="0.1" value="${sy}" placeholder="">
                </div>
                <div class="form-group narrow">
                    <label>Sz</label>
                    <input type="number" id="samp_${idx}_sz" step="0.1" value="${sz}" placeholder="">
                </div>
            </div>`;
    } else {
        positionHtml = `
            <div class="form-row">
                <div class="form-group narrow">
                    <label>Sx Lo</label>
                    <input type="number" id="samp_${idx}_sx_lo" step="0.1" value="${sxLo}" placeholder="">
                </div>
                <div class="form-group narrow">
                    <label>Sx Hi</label>
                    <input type="number" id="samp_${idx}_sx_hi" step="0.1" value="${sxHi}" placeholder="">
                </div>
                <div class="form-group narrow">
                    <label>Sy Lo</label>
                    <input type="number" id="samp_${idx}_sy_lo" step="0.1" value="${syLo}" placeholder="">
                </div>
                <div class="form-group narrow">
                    <label>Sy Hi</label>
                    <input type="number" id="samp_${idx}_sy_hi" step="0.1" value="${syHi}" placeholder="">
                </div>
                <div class="form-group narrow">
                    <label>Sz Lo</label>
                    <input type="number" id="samp_${idx}_sz_lo" step="0.1" value="${szLo}" placeholder="">
                </div>
                <div class="form-group narrow">
                    <label>Sz Hi</label>
                    <input type="number" id="samp_${idx}_sz_hi" step="0.1" value="${szHi}" placeholder="">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group narrow">
                    <label>Sx Step</label>
                    <input type="number" id="samp_${idx}_sx_del" step="0.01" value="${sxDel}" placeholder="">
                </div>
                <div class="form-group narrow">
                    <label>Sy Step</label>
                    <input type="number" id="samp_${idx}_sy_del" step="0.01" value="${syDel}" placeholder="">
                </div>
                <div class="form-group narrow">
                    <label>Sz Step</label>
                    <input type="number" id="samp_${idx}_sz_del" step="0.01" value="${szDel}" placeholder="">
                </div>
            </div>`;
    }

    // Build gain dropdown HTML with selected values
    function selectOpt(html, val) {
        if (!val) return html;
        return html.replace(`value="${val}"`, `value="${val}" selected`);
    }

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
                <label>Enabled</label>
                <input type="checkbox" id="samp_${idx}_enabled" ${sEnabled ? 'checked' : ''}>
            </div>
        </div>

        <!-- Positions -->
        ${positionHtml}

        <hr class="section-sep">

        <!-- XAS Parameters + Gains -->
        <div class="form-row">
            <div class="form-group narrow">
                <label>Do XAS</label>
                <input type="checkbox" id="samp_${idx}_do_xas" ${doXas ? 'checked' : ''}>
            </div>
            <div class="form-group narrow">
                <label>XAS Reps</label>
                <input type="number" id="samp_${idx}_xas_reps" value="${xasReps}" min="1">
            </div>
            <div class="form-group narrow">
                <label>Count (s)</label>
                <input type="number" id="samp_${idx}_xas_time" step="0.1" value="${xasTime}" min="0.1">
            </div>
            <div class="form-group narrow">
                <label>Filter</label>
                <input type="number" id="samp_${idx}_xas_filter" value="${xasFilter}" min="0" max="255">
            </div>
            <div class="form-group">
                <label>Emiss Override (eV)</label>
                <input type="number" id="samp_${idx}_xas_emiss" step="0.1" value="${xasEmissOvr}" placeholder="Use element default">
            </div>
        </div>

        <!-- Gain Settings (per-sample) -->
        <div class="form-row">
            <div class="form-group medium">
                <label>I0 Gain</label>
                <select id="samp_${idx}_i0_gain">${selectOpt(I0_GAIN_OPTIONS, i0Gain)}</select>
            </div>
            <div class="form-group medium">
                <label>I0 Offset</label>
                <select id="samp_${idx}_i0_offset">${selectOpt(I0_OFFSET_OPTIONS, i0Offset)}</select>
            </div>
            <div class="form-group medium">
                <label>I1 Gain</label>
                <select id="samp_${idx}_i1_gain">${selectOpt(I1_GAIN_OPTIONS, i1Gain)}</select>
            </div>
        </div>

        <!-- RIXS Section (collapsible) -->
        <div class="rixs-section ${doRixs ? '' : 'hidden'}" id="samp_${idx}_rixs_section">
            <div class="form-row">
                <div class="form-group narrow">
                    <label>RIXS Time (s)</label>
                    <input type="number" id="samp_${idx}_rixs_time" step="0.1" value="${rixsTime}" min="0.1">
                </div>
                <div class="form-group">
                    <label>Emiss Start (eV)</label>
                    <input type="number" id="samp_${idx}_rixs_start" step="0.1" value="${rixsStart}" placeholder="Higher energy">
                </div>
                <div class="form-group">
                    <label>Emiss End (eV)</label>
                    <input type="number" id="samp_${idx}_rixs_end" step="0.1" value="${rixsEnd}" placeholder="Lower energy">
                </div>
                <div class="form-group narrow">
                    <label>Emiss Step</label>
                    <input type="number" id="samp_${idx}_rixs_step" step="0.01" value="${rixsStep}">
                </div>
                <div class="form-group narrow">
                    <label>RIXS Filter</label>
                    <input type="number" id="samp_${idx}_rixs_filter" value="${rixsFilter}" min="0" max="255">
                </div>
            </div>
        </div>

        <div class="checkbox-row" style="margin-top: 6px;">
            <input type="checkbox" id="samp_${idx}_do_rixs" ${doRixs ? 'checked' : ''}
                   onchange="toggleRixs(${idx})">
            <label for="samp_${idx}_do_rixs">Enable RIXS for this sample</label>
        </div>
    `;

    container.appendChild(card);
}

function removeSample(idx) {
    const card = document.getElementById(`sample-card-${idx}`);
    if (card) card.remove();
}

function toggleRixs(idx) {
    const checked = document.getElementById(`samp_${idx}_do_rixs`).checked;
    const section = document.getElementById(`samp_${idx}_rixs_section`);
    if (checked) {
        section.classList.remove('hidden');
    } else {
        section.classList.add('hidden');
    }
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
            vortex_channel: parseInt(val(`elem_${idx}_vortex`) || '1'),
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

    const isLiquidJet = (getSampleEnv() === 'liquid_jet');

    document.querySelectorAll('.sample-card').forEach(card => {
        const idx = parseInt(card.dataset.idx);

        let sxLo, sxHi, syLo, syHi, szLo, szHi, sxDel, syDel, szDel;
        if (isLiquidJet) {
            // Single point: lo = hi = value, no steps
            const sx = numVal(`samp_${idx}_sx`);
            const sy = numVal(`samp_${idx}_sy`);
            const sz = numVal(`samp_${idx}_sz`);
            sxLo = sx; sxHi = sx;
            syLo = sy; syHi = sy;
            szLo = sz; szHi = sz;
            sxDel = 0; syDel = 0; szDel = 0;
        } else {
            sxLo = numVal(`samp_${idx}_sx_lo`);
            sxHi = numVal(`samp_${idx}_sx_hi`);
            syLo = numVal(`samp_${idx}_sy_lo`);
            syHi = numVal(`samp_${idx}_sy_hi`);
            szLo = numVal(`samp_${idx}_sz_lo`);
            szHi = numVal(`samp_${idx}_sz_hi`);
            sxDel = numVal(`samp_${idx}_sx_del`);
            syDel = numVal(`samp_${idx}_sy_del`);
            szDel = numVal(`samp_${idx}_sz_del`);
        }

        data.samples.push({
            name: val(`samp_${idx}_name`),
            element: val(`samp_${idx}_element`),
            enabled: document.getElementById(`samp_${idx}_enabled`).checked,
            sx_lo: sxLo,
            sx_hi: sxHi,
            sy_lo: syLo,
            sy_hi: syHi,
            sz_lo: szLo,
            sz_hi: szHi,
            sx_del: sxDel,
            sy_del: syDel,
            sz_del: szDel,
            do_xas: document.getElementById(`samp_${idx}_do_xas`).checked,
            xas_reps: parseInt(val(`samp_${idx}_xas_reps`) || '10'),
            xas_time: parseFloat(val(`samp_${idx}_xas_time`) || '0.5'),
            xas_filter: parseInt(val(`samp_${idx}_xas_filter`) || '0'),
            xas_emiss_override: numVal(`samp_${idx}_xas_emiss`),
            i0_gain: val(`samp_${idx}_i0_gain`),
            i0_offset: val(`samp_${idx}_i0_offset`),
            i1_gain: val(`samp_${idx}_i1_gain`),
            do_rixs: document.getElementById(`samp_${idx}_do_rixs`).checked,
            rixs_time: parseFloat(val(`samp_${idx}_rixs_time`) || '1.0'),
            rixs_start: numVal(`samp_${idx}_rixs_start`),
            rixs_end: numVal(`samp_${idx}_rixs_end`),
            rixs_step: parseFloat(val(`samp_${idx}_rixs_step`) || '-0.2'),
            rixs_filter: parseInt(val(`samp_${idx}_rixs_filter`) || '0'),
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
