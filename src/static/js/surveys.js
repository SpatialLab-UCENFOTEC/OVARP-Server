/**
 * OVARP — Feedback panel.
 *
 * Builds the participant-facing questionnaire link and shows the scores as they
 * come in. The questionnaire itself is a standalone page so the participant can
 * answer on their own phone without the console.
 */

const esc = (s) => { const d = document.createElement('div'); d.textContent = s ?? ''; return d.innerHTML; };

let surveys = [];

async function activeParticipantId() {
    try {
        const status = await (await fetch('/api/session/status')).json();
        return status.active ? status.participant_id : '';
    } catch {
        return '';
    }
}

async function buildLink() {
    const id = document.getElementById('survey-select').value;
    const lang = document.getElementById('survey-lang').value;
    if (!id) return '';

    const participant = await activeParticipantId();
    const url = new URL('/survey.html', window.location.origin);
    url.searchParams.set('id', id);
    url.searchParams.set('lang', lang);
    if (participant) url.searchParams.set('participant', participant);
    return url.toString();
}

async function refreshLink() {
    const link = await buildLink();
    document.getElementById('survey-link').value = link;

    const chosen = surveys.find(s => s.id === document.getElementById('survey-select').value);
    document.getElementById('survey-desc').textContent = chosen
        ? `${chosen.item_count} items · ${chosen.scoring && chosen.scoring !== 'none' ? chosen.scoring.toUpperCase() + ' scoring' : 'open answers'}`
        : '';
}

function renderScore(entry) {
    const score = entry.score || {};
    if (typeof score.score === 'number') {
        const band = score.score >= 68 ? 'text-success' : 'text-warning';
        return `<span class="${band} fw-bold fs-5">${score.score}</span><small class="text-muted"> / 100</small>`;
    }
    if (score.scales) {
        return Object.entries(score.scales).map(([scale, value]) => {
            const band = value >= 0.8 ? 'text-success' : value <= -0.8 ? 'text-danger' : 'text-muted';
            return `<div class="d-flex justify-content-between" style="font-size:.85em">
                <span class="text-capitalize">${esc(scale)}</span>
                <span class="${band} fw-bold">${value > 0 ? '+' : ''}${value}</span></div>`;
        }).join('');
    }
    return '<small class="text-muted">Open answers</small>';
}

function renderAnswers(entry) {
    const open = Object.entries(entry.answers).filter(([, v]) => typeof v === 'string');
    if (!open.length) return '';
    return `<div class="mt-2 ps-2 border-start border-secondary">
        ${open.map(([k, v]) => `<div style="font-size:.85em">
            <span class="text-muted">${esc(k)}:</span> ${esc(v)}</div>`).join('')}
    </div>`;
}

export async function refreshResults() {
    const container = document.getElementById('survey-results');
    if (!container) return;
    try {
        const { responses } = await (await fetch('/api/surveys/responses')).json();
        if (!responses.length) {
            container.innerHTML = '<small class="text-muted">No responses yet. Scores appear here as participants submit.</small>';
            return;
        }
        container.innerHTML = responses.map(entry => `
            <div class="mb-3 pb-2 border-bottom border-secondary">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <strong>${esc(entry.survey_name)}</strong>
                        <small class="text-muted d-block">${esc(entry.participant_id || 'unknown participant')}</small>
                    </div>
                    <div class="text-end">${renderScore(entry)}</div>
                </div>
                ${renderAnswers(entry)}
            </div>`).join('');
    } catch (e) {
        container.innerHTML = `<small class="text-danger">Could not load responses: ${esc(String(e))}</small>`;
    }
}

export async function initSurveysPanel() {
    const select = document.getElementById('survey-select');
    if (!select) return;

    try {
        surveys = (await (await fetch('/api/surveys')).json()).surveys || [];
    } catch {
        select.innerHTML = '<option>Could not load questionnaires</option>';
        return;
    }

    select.innerHTML = surveys
        .map(s => `<option value="${esc(s.id)}">${esc(s.name)}</option>`)
        .join('');

    select.addEventListener('change', refreshLink);
    document.getElementById('survey-lang').addEventListener('change', refreshLink);

    document.getElementById('survey-copy-btn').addEventListener('click', async (e) => {
        const input = document.getElementById('survey-link');
        try {
            await navigator.clipboard.writeText(input.value);
        } catch {
            input.select();
        }
        const btn = e.currentTarget;
        const original = btn.textContent;
        btn.textContent = '✅';
        setTimeout(() => { btn.textContent = original; }, 1000);
    });

    document.getElementById('survey-open-btn').addEventListener('click', async () => {
        const link = await buildLink();
        if (link) window.open(link, '_blank', 'noopener');
    });

    document.getElementById('survey-refresh-btn').addEventListener('click', refreshResults);

    // The link embeds the participant ID, so it has to be rebuilt when a session starts
    document.getElementById('surveys-tab')?.addEventListener('shown.bs.tab', () => {
        refreshLink();
        refreshResults();
    });

    await refreshLink();
    await refreshResults();
}
