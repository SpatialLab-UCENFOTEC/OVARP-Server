/**
 * OVARP — Event markers.
 *
 * One code path for every marker, whether it comes from a preset button or the
 * free-text box: the two used to be separate copies and had already drifted —
 * the custom one ignored the server's error response and reported success when
 * no session was active.
 *
 * Markers can be corrected afterwards. The timestamp is never touched and the
 * server appends the amendment to the session log, so the record still shows
 * what was captured live.
 */

const esc = (s) => { const d = document.createElement('div'); d.textContent = s ?? ''; return d.innerHTML; };

/** Ask the console to re-read session state after markers change. */
function requestSessionRefresh() {
    document.dispatchEvent(new CustomEvent('ovarp:session-refresh'));
}

function flash(button, text) {
    if (!button) return;
    const original = { text: button.textContent, background: button.style.background, color: button.style.color };
    button.textContent = text;
    setTimeout(() => {
        button.textContent = original.text;
        button.style.background = original.background;
        button.style.color = original.color;
    }, 700);
}

function notify(message, type = 'info') {
    if (typeof window.showToast === 'function') window.showToast(message, type);
}

/**
 * Fire a marker. Presets pass their id as the label plus `{preset: true}`.
 * Returns the created marker, or null when the server refused it.
 */
export async function addMarker(label, { metadata = null, button = null, display = null } = {}) {
    if (!label) return null;
    try {
        const resp = await fetch('/api/session/marker', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ label, metadata }),
        });
        const data = await resp.json();

        // The server answers 200 with an error body when no session is active
        if (data.error) {
            notify(data.error, 'warning');
            return null;
        }

        notify(`Marker: "${display || label}"`, 'info');
        flash(button, '✅');
        requestSessionRefresh();
        return data.marker;
    } catch (e) {
        notify(`Marker failed: ${e}`, 'error');
        return null;
    }
}

export async function amendMarker(markerId, changes) {
    const resp = await fetch(`/api/session/marker/${encodeURIComponent(markerId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(changes),
    });
    const data = await resp.json();
    if (data.error) { notify(data.error, 'warning'); return null; }
    requestSessionRefresh();
    return data.marker;
}

export async function deleteMarker(markerId) {
    const resp = await fetch(`/api/session/marker/${encodeURIComponent(markerId)}`, { method: 'DELETE' });
    const data = await resp.json();
    if (data.error) { notify(data.error, 'warning'); return false; }
    notify('Marker removed', 'info');
    requestSessionRefresh();
    return true;
}

function markerRow(marker) {
    const time = new Date(marker.timestamp * 1000).toLocaleTimeString();
    const amended = marker.amended
        ? '<span class="badge bg-secondary ms-1" title="Edited after it was recorded">edited</span>'
        : '';
    const notes = marker.notes
        ? `<div class="text-muted ps-3" style="font-size:.8em">↳ ${esc(marker.notes)}</div>`
        : '';

    return `
        <div class="py-1 border-bottom border-secondary" data-marker="${esc(marker.id)}" style="font-size:.85em">
            <div class="d-flex justify-content-between align-items-center gap-2">
                <span class="text-warning flex-grow-1">📌 ${esc(marker.label)}${amended}</span>
                <small class="text-muted">${time}</small>
                <button class="btn btn-link btn-sm p-0 text-info" data-action="edit"
                    title="Edit label or add notes" aria-label="Edit marker">✎</button>
                <button class="btn btn-link btn-sm p-0 text-danger" data-action="delete"
                    title="Remove this marker" aria-label="Delete marker">🗑</button>
            </div>
            ${notes}
        </div>`;
}

function editorRow(marker) {
    return `
        <div class="py-2 border-bottom border-secondary" data-marker="${esc(marker.id)}">
            <input class="form-control form-control-sm mb-1" data-field="label"
                value="${esc(marker.label)}" aria-label="Marker label">
            <textarea class="form-control form-control-sm mb-1" data-field="notes" rows="2"
                placeholder="Notes — what happened, what you observed"
                aria-label="Marker notes">${esc(marker.notes || '')}</textarea>
            <div class="d-flex gap-2">
                <button class="btn btn-success btn-sm flex-fill" data-action="save">Save</button>
                <button class="btn btn-outline-secondary btn-sm flex-fill" data-action="cancel">Cancel</button>
            </div>
            <small class="text-muted d-block mt-1">The timestamp stays as recorded; the change is logged.</small>
        </div>`;
}

let currentMarkers = [];
let editingId = null;

export function renderMarkerHistory(markers) {
    const container = document.getElementById('marker-history');
    if (!container) return;
    currentMarkers = markers || [];

    if (!currentMarkers.length) {
        container.innerHTML = '';
        return;
    }
    container.innerHTML = currentMarkers
        .map(m => (m.id === editingId ? editorRow(m) : markerRow(m)))
        .join('');
}

function handleHistoryClick(event) {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const row = button.closest('[data-marker]');
    const markerId = row?.dataset.marker;
    if (!markerId) return;

    const action = button.dataset.action;
    if (action === 'edit') {
        editingId = markerId;
        renderMarkerHistory(currentMarkers);
    } else if (action === 'cancel') {
        editingId = null;
        renderMarkerHistory(currentMarkers);
    } else if (action === 'save') {
        const label = row.querySelector('[data-field="label"]').value.trim();
        const notes = row.querySelector('[data-field="notes"]').value.trim();
        editingId = null;
        amendMarker(markerId, { label, notes });
    } else if (action === 'delete') {
        if (window.confirm('Remove this marker from the session?')) deleteMarker(markerId);
    }
}

export function initMarkers() {
    // Preset buttons and the free-text box both land on addMarker
    window.addMarker = async () => {
        const input = document.getElementById('marker-label');
        const label = input.value.trim();
        const created = await addMarker(label, {
            button: document.querySelector('#marker-row .btn-warning'),
        });
        if (created) input.value = '';
    };
    window.addPresetMarker = (id, label, color, button) =>
        addMarker(id, { metadata: { preset: true }, button, display: label });

    document.getElementById('marker-history')?.addEventListener('click', handleHistoryClick);
}
