/**
 * OVARP: Marker preset and scenario builders.
 *
 * Both let a researcher extend the experiment vocabulary from the console.
 * They differ in how long the result lives: a marker preset is held in config
 * memory for this run, while a scenario is written to scenarios/<id>.yaml.
 */

const DEFAULT_PRESET_COLOR = '#f59e0b';

let notify = () => {};
let onPresetsChanged = () => {};
let stepCount = 0;

function value(id) {
    return (document.getElementById(id)?.value || '').trim();
}

function closeModal(id) {
    const el = document.getElementById(id);
    if (el) window.bootstrap?.Modal.getInstance(el)?.hide();
}

async function saveMarkerPreset() {
    const label = value('new-preset-label');
    if (!label) {
        notify('A display label is required', 'warning');
        return;
    }

    const preset = {
        id: value('new-preset-id') || `marker_${Date.now()}`,
        label,
        description: value('new-preset-desc') || null,
        color: value('new-preset-color') || DEFAULT_PRESET_COLOR,
    };

    try {
        const resp = await fetch('/api/session/markers/presets', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(preset),
        });
        const data = await resp.json();
        if (data.error) throw new Error(data.error);

        notify(`Preset "${label}" added`, 'success');
        closeModal('createMarkerPresetModal');
        ['new-preset-id', 'new-preset-label', 'new-preset-desc']
            .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
        await onPresetsChanged();
    } catch (e) {
        notify(`Could not save the preset: ${e.message}`, 'error');
    }
}

function addScenarioStepInput(data = {}) {
    const container = document.getElementById('scenario-steps-input-list');
    if (!container) return;

    stepCount += 1;
    const row = document.createElement('div');
    row.className = 'scenario-step-row card p-2';
    row.innerHTML = `
        <div class="d-flex justify-content-between align-items-center mb-2">
            <span class="badge badge-amber mono-font">Step ${stepCount}</span>
            <button type="button" class="btn btn-ghost btn-xs"
                onclick="this.closest('.scenario-step-row').remove()">Remove</button>
        </div>
        <div class="row g-2">
            <div class="col-md-3">
                <input type="text" class="form-control form-control-sm step-id-input"
                    placeholder="Step ID" value="${data.id || 'step_' + stepCount}"
                    aria-label="Step ID">
            </div>
            <div class="col-md-9">
                <input type="text" class="form-control form-control-sm step-inst-input"
                    placeholder="What the researcher or participant does here"
                    value="${data.instruction || ''}" aria-label="Step instruction">
            </div>
            <div class="col-md-4">
                <input type="text" class="form-control form-control-sm step-marker-input"
                    placeholder="Auto marker (optional)" value="${data.auto_marker || ''}"
                    aria-label="Auto marker">
            </div>
            <div class="col-md-4">
                <input type="text" class="form-control form-control-sm step-cond-input"
                    placeholder="Condition / profile id (optional)" value="${data.condition || ''}"
                    aria-label="Condition">
            </div>
            <div class="col-md-4">
                <input type="number" class="form-control form-control-sm step-dur-input"
                    placeholder="Duration (s)" value="${data.duration_seconds || ''}"
                    aria-label="Step duration in seconds">
            </div>
        </div>`;
    container.appendChild(row);
}

function collectSteps() {
    return Array.from(document.querySelectorAll('.scenario-step-row')).map((row, i) => {
        const duration = row.querySelector('.step-dur-input').value;
        return {
            id: row.querySelector('.step-id-input').value.trim() || `step_${i + 1}`,
            instruction: row.querySelector('.step-inst-input').value.trim() || `Step ${i + 1}`,
            condition: row.querySelector('.step-cond-input').value.trim() || null,
            auto_marker: row.querySelector('.step-marker-input').value.trim() || null,
            duration_seconds: duration ? parseInt(duration, 10) : null,
        };
    });
}

async function saveNewScenario() {
    const id = value('new-scenario-id');
    const name = value('new-scenario-name');
    if (!id || !name) {
        notify('Scenario ID and name are required', 'warning');
        return;
    }

    const steps = collectSteps();
    if (!steps.length) {
        notify('Add at least one step', 'warning');
        return;
    }

    try {
        const resp = await fetch('/api/scenarios', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id, name, description: value('new-scenario-desc'), steps }),
        });
        const data = await resp.json();
        if (data.error) throw new Error(data.error);

        notify(`Scenario "${name}" saved`, 'success');
        closeModal('createScenarioModal');
        document.dispatchEvent(new CustomEvent('ovarp:scenarios-changed', {
            detail: { scenarios: data.scenarios || [] },
        }));
    } catch (e) {
        notify(`Could not save the scenario: ${e.message}`, 'error');
    }
}

export function initBuilders({ showToast, reloadPresets } = {}) {
    if (showToast) notify = showToast;
    if (reloadPresets) onPresetsChanged = reloadPresets;

    window.saveMarkerPreset = saveMarkerPreset;
    window.addScenarioStepInput = addScenarioStepInput;
    window.saveNewScenario = saveNewScenario;

    // A builder opened with nothing in it reads as broken, so seed one row.
    document.getElementById('createScenarioModal')?.addEventListener('show.bs.modal', () => {
        if (!document.querySelector('.scenario-step-row')) addScenarioStepInput();
    });
}
