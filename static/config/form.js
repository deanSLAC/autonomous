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

const COMMON_ELEMENTS = [
    { symbol: 'Fe', name: 'Iron' },
    { symbol: 'Cu', name: 'Copper' },
    { symbol: 'Zn', name: 'Zinc' },
    { symbol: 'As', name: 'Arsenic' },
    { symbol: 'Se', name: 'Selenium' },
    { symbol: 'Pb', name: 'Lead' },
    { symbol: 'Mn', name: 'Manganese' },
    { symbol: 'Ni', name: 'Nickel' },
    { symbol: 'Co', name: 'Cobalt' },
    { symbol: 'Cr', name: 'Chromium' },
];

const CRYSTAL_CUTS = [
    { hkl: '1 1 1', type: 'Si', common_for: ['Fe', 'Mn', 'Cr', 'Co'] },
    { hkl: '3 1 1', type: 'Si', common_for: ['Zn', 'As', 'Se', 'Pb', 'Cu', 'Ni'] },
    { hkl: '6 4 2', type: 'Si', common_for: ['Zn'] },
    { hkl: '9 1 1', type: 'Si', common_for: ['As', 'Pb'] },
    { hkl: '8 4 4', type: 'Si', common_for: ['Se'] },
];

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
    const edge = data ? data.edge : 'K';
    const incE = data ? data.incident_energy : '';
    const emE = data ? data.emission_energy : '';
    const cType = data ? data.crystal_type : 0;
    const hkl = data ? data.crystal_hkl : '';
    const rowR = data ? data.row_radius : 1000;
    const nC = data ? data.n_crystals : 3;
    const vCh = data ? data.vortex_channel : 1;

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
                <input type="text" id="elem_${idx}_other" maxlength="3" value="${otherSel ? sym : ''}" placeholder="e.g. Ti">
            </div>
            <div class="form-group narrow">
                <label>Edge <span class="required">*</span></label>
                <select id="elem_${idx}_edge" onchange="lookupEnergy(${idx})">
                    <option value="K"${edge === 'K' ? ' selected' : ''}>K</option>
                    <option value="L1"${edge === 'L1' ? ' selected' : ''}>L1</option>
                    <option value="L2"${edge === 'L2' ? ' selected' : ''}>L2</option>
                    <option value="L3"${edge === 'L3' ? ' selected' : ''}>L3</option>
                </select>
            </div>
            <div class="form-group">
                <label>Incident Energy (eV) <span class="required">*</span></label>
                <input type="number" id="elem_${idx}_incident" step="0.1" value="${incE}" placeholder="Auto-filled">
            </div>
            <div class="form-group">
                <label>Emission Energy (eV) <span class="required">*</span></label>
                <input type="number" id="elem_${idx}_emission" step="0.1" value="${emE}" placeholder="Auto-filled">
            </div>
        </div>
        <div class="form-row">
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
    `;

    container.appendChild(card);

    // If we have a symbol and edge but no energies, look them up
    if (sym && !incE) {
        lookupEnergy(idx);
    }

    // Auto-suggest crystal cut
    if (sym && !hkl) {
        suggestCrystalCut(idx, sym);
    }

    updateSampleElementDropdowns();
}

function removeElement(idx) {
    const card = document.getElementById(`element-card-${idx}`);
    if (card) card.remove();
    updateSampleElementDropdowns();
}

function onElementSelect(idx) {
    const sel = document.getElementById(`elem_${idx}_symbol_select`);
    const otherWrap = document.getElementById(`elem_${idx}_other_wrap`);

    if (sel.value === '__other') {
        otherWrap.style.display = '';
        document.getElementById(`elem_${idx}_other`).focus();
    } else {
        otherWrap.style.display = 'none';
    }

    // Lookup energy and suggest crystal
    if (sel.value && sel.value !== '__other') {
        suggestCrystalCut(idx, sel.value);
    }
    lookupEnergy(idx);
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
    if (hklInput.value) return; // Don't overwrite user input

    for (const cut of CRYSTAL_CUTS) {
        if (cut.common_for.includes(symbol)) {
            hklInput.value = cut.hkl;
            break;
        }
    }
}

function lookupEnergy(idx) {
    const symbol = getElementSymbol(idx);
    const edge = document.getElementById(`elem_${idx}_edge`).value;

    if (!symbol || !edge) return;

    fetch('/api/lookup_energy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: symbol, edge: edge }),
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            const incInput = document.getElementById(`elem_${idx}_incident`);
            const emInput = document.getElementById(`elem_${idx}_emission`);
            // Only fill if empty or auto-filled (not user-edited)
            if (!incInput.dataset.userEdited) {
                incInput.value = data.incident_energy || '';
            }
            if (!emInput.dataset.userEdited && data.emission_energy) {
                emInput.value = data.emission_energy;
            }
        }
    })
    .catch(err => {
        console.warn('Energy lookup failed:', err);
    });
}

// ---------------------------------------------------------------------------
// Sample Management
// ---------------------------------------------------------------------------

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

        <!-- Positions (populated after alignment or entered manually) -->
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
        </div>

        <hr class="section-sep">

        <!-- XAS Parameters -->
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
        experimenter: val('experimenter'),
        mono_crystal: val('mono_crystal'),
        beam_size_h: document.getElementById('beam_size_h').value,
        beam_size_v: document.getElementById('beam_size_v').value,
        mirrors_out: document.getElementById('mirrors_out').checked,
        sample_env: val('sample_env'),
        data_directory: val('data_directory'),
        i0_gain: val('i0_gain'),
        i1_gain: val('i1_gain'),
        i0_offset: val('i0_offset'),
        llm_enabled: document.getElementById('llm_enabled').checked,
        llm_decide_enabled: document.getElementById('llm_decide_enabled').checked,
        elements: [],
    };

    document.querySelectorAll('.element-card').forEach(card => {
        const idx = parseInt(card.dataset.idx);
        data.elements.push({
            symbol: getElementSymbol(idx),
            edge: val(`elem_${idx}_edge`),
            incident_energy: val(`elem_${idx}_incident`),
            emission_energy: val(`elem_${idx}_emission`),
            crystal_type: parseInt(val(`elem_${idx}_crystal_type`) || '0'),
            crystal_hkl: val(`elem_${idx}_hkl`),
            row_radius: parseInt(val(`elem_${idx}_row_radius`) || '1000'),
            n_crystals: parseInt(val(`elem_${idx}_n_crystals`) || '3'),
            vortex_channel: parseInt(val(`elem_${idx}_vortex`) || '1'),
        });
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
        data.samples.push({
            name: val(`samp_${idx}_name`),
            element: val(`samp_${idx}_element`),
            enabled: document.getElementById(`samp_${idx}_enabled`).checked,
            sx_lo: numVal(`samp_${idx}_sx_lo`),
            sx_hi: numVal(`samp_${idx}_sx_hi`),
            sy_lo: numVal(`samp_${idx}_sy_lo`),
            sy_hi: numVal(`samp_${idx}_sy_hi`),
            sz_lo: numVal(`samp_${idx}_sz_lo`),
            sz_hi: numVal(`samp_${idx}_sz_hi`),
            sx_del: numVal(`samp_${idx}_sx_del`),
            sy_del: numVal(`samp_${idx}_sy_del`),
            sz_del: numVal(`samp_${idx}_sz_del`),
            do_xas: document.getElementById(`samp_${idx}_do_xas`).checked,
            xas_reps: parseInt(val(`samp_${idx}_xas_reps`) || '10'),
            xas_time: parseFloat(val(`samp_${idx}_xas_time`) || '0.5'),
            xas_filter: parseInt(val(`samp_${idx}_xas_filter`) || '0'),
            xas_emiss_override: numVal(`samp_${idx}_xas_emiss`),
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
                'Switch to the Sample Holder tab to configure samples.'
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
                `${result.summary.holder}: ${result.summary.n_samples} samples`,
                'Ready to hand off to the autonomous agent.'
            );
            document.dispatchEvent(new Event("autonomy-ready"));
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
            const elems = result.elements.map(e => `${e.symbol} ${e.edge}`).join(', ');

            // Cache elements for sample dropdowns
            _cachedElements = result.elements;

            banner.innerHTML = `
                <div class="banner-title">Active Experiment: ${esc(exp.name)}</div>
                <div class="banner-details">
                    <span>Experimenter: ${esc(exp.experimenter)}</span>
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

function loadActiveExperiment() {
    fetch('/api/load_active')
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
    document.getElementById('experimenter').value = exp.experimenter || '';
    document.getElementById('mono_crystal').value = exp.mono_crystal || 'A';
    document.getElementById('beam_size_h').value = exp.beam_size_h || 'big';
    document.getElementById('beam_size_v').value = exp.beam_size_v || 'big';
    document.getElementById('mirrors_out').checked = !!exp.mirrors_out;
    // Update beam size controls state
    _updateMirrorsOutState(!!exp.mirrors_out);
    document.getElementById('sample_env').value = exp.sample_env || 'ambient';
    document.getElementById('data_directory').value = exp.data_directory || '';

    // Advanced
    if (exp.i0_gain) document.getElementById('i0_gain').value = exp.i0_gain;
    if (exp.i1_gain) document.getElementById('i1_gain').value = exp.i1_gain;
    if (exp.i0_offset) document.getElementById('i0_offset').value = exp.i0_offset;
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

function showSuccess(title, detail, specCmd) {
    const area = document.getElementById('message-area');
    area.innerHTML = `
        <div class="success-box">
            <h3>${esc(title)}</h3>
            <p>${esc(detail)}</p>
            <p style="margin-top: 8px;"><code>${esc(specCmd)}</code></p>
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
});
