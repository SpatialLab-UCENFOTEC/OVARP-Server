/**
 * OVARP — Profile authoring.
 *
 * Create, edit and delete agent personas from the console instead of hand-writing
 * YAML. The same editor is reachable from the Profiles tab and from the
 * Playground, because both are places a researcher realises the persona needs a
 * change — it is one dialog, not two implementations.
 *
 * Profiles are written to profiles/*.yaml server-side, so one authored here
 * survives a restart.
 */

const esc = (s) => { const d = document.createElement('div'); d.textContent = s ?? ''; return d.innerHTML; };

let voicesByProvider = { openai: [], gemini: [] };
let editingId = null;

function notify(message, type = 'info') {
    if (typeof window.showToast === 'function') window.showToast(message, type);
}

const MODAL_HTML = `
<div class="modal fade" id="profile-editor-modal" tabindex="-1" aria-labelledby="profile-editor-title" aria-hidden="true">
  <div class="modal-dialog modal-lg modal-dialog-scrollable">
    <div class="modal-content bg-dark text-light border-secondary">
      <div class="modal-header border-secondary">
        <h5 class="modal-title" id="profile-editor-title">New profile</h5>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
      </div>
      <div class="modal-body">
        <div id="profile-editor-error" class="alert alert-danger py-2 d-none" role="alert"></div>
        <div class="row g-3">
          <div class="col-md-6">
            <label class="form-label" for="pe-id">ID</label>
            <input id="pe-id" class="form-control" placeholder="therapist_female">
            <small class="text-muted">Lowercase, no spaces. Cannot change after creation.</small>
          </div>
          <div class="col-md-6">
            <label class="form-label" for="pe-name">Display name</label>
            <input id="pe-name" class="form-control" placeholder="Dr. Ana">
          </div>
          <div class="col-12">
            <label class="form-label" for="pe-prompt">System prompt</label>
            <textarea id="pe-prompt" class="form-control font-monospace" rows="6"
              placeholder="You are an embodied virtual agent..."></textarea>
          </div>
          <div class="col-md-4">
            <label class="form-label" for="pe-voice-provider">Voice provider</label>
            <select id="pe-voice-provider" class="form-select">
              <option value="auto">Auto (follow console)</option>
              <option value="openai">OpenAI</option>
              <option value="gemini">Gemini</option>
            </select>
          </div>
          <div class="col-md-4">
            <label class="form-label" for="pe-voice">Voice</label>
            <select id="pe-voice" class="form-select"></select>
          </div>
          <div class="col-md-4">
            <label class="form-label" for="pe-avatar">Avatar</label>
            <select id="pe-avatar" class="form-select"></select>
          </div>
          <div class="col-md-4">
            <label class="form-label" for="pe-role">Role</label>
            <input id="pe-role" class="form-control" placeholder="Virtual therapist">
          </div>
          <div class="col-md-4">
            <label class="form-label" for="pe-gender">Gender</label>
            <select id="pe-gender" class="form-select">
              <option value="">—</option>
              <option value="feminine">Feminine</option>
              <option value="masculine">Masculine</option>
              <option value="neutral">Neutral</option>
            </select>
          </div>
          <div class="col-md-4">
            <label class="form-label" for="pe-age">Age</label>
            <input id="pe-age" type="number" min="0" class="form-control" placeholder="42">
          </div>
          <div class="col-12">
            <label class="form-label" for="pe-backstory">Backstory</label>
            <textarea id="pe-backstory" class="form-control" rows="2"></textarea>
          </div>
          <div class="col-md-8">
            <label class="form-label" for="pe-rules">Guardrails (one per line)</label>
            <textarea id="pe-rules" class="form-control" rows="3"
              placeholder="Never give medical advice"></textarea>
          </div>
          <div class="col-md-4">
            <label class="form-label" for="pe-max-words">Max response words</label>
            <input id="pe-max-words" type="number" min="1" class="form-control" placeholder="60">
          </div>
        </div>
      </div>
      <div class="modal-footer border-secondary">
        <button id="pe-delete" class="btn btn-outline-danger me-auto d-none">Delete</button>
        <button class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
        <button id="pe-save" class="btn btn-success">Save profile</button>
      </div>
    </div>
  </div>
</div>`;

function field(id) { return document.getElementById(id); }

function populateVoiceOptions() {
    const provider = field('pe-voice-provider').value;
    const select = field('pe-voice');
    const options = provider === 'auto'
        ? [...voicesByProvider.openai, ...voicesByProvider.gemini]
        : (voicesByProvider[provider] || []);
    select.innerHTML = options
        .map(v => `<option value="${esc(v.id)}">${esc(v.label || v.id)}</option>`)
        .join('') || '<option value="">(no voices configured)</option>';
}

function fillForm(profile) {
    field('pe-id').value = profile?.id || '';
    field('pe-id').disabled = Boolean(profile);
    field('pe-name').value = profile?.name || '';
    field('pe-prompt').value = profile?.personality?.system_prompt || '';
    field('pe-voice-provider').value = profile?.voice?.provider || 'auto';
    populateVoiceOptions();
    if (profile?.voice?.voice_id) field('pe-voice').value = profile.voice.voice_id;
    field('pe-avatar').value = profile?.avatar || '';
    field('pe-role').value = profile?.identity?.role || '';
    field('pe-gender').value = profile?.identity?.gender || '';
    field('pe-age').value = profile?.identity?.age ?? '';
    field('pe-backstory').value = profile?.identity?.backstory || '';
    field('pe-rules').value = (profile?.guardrails?.rules || []).join('\n');
    field('pe-max-words').value = profile?.guardrails?.max_response_words ?? '';

    field('profile-editor-title').textContent = profile ? `Edit ${profile.name}` : 'New profile';
    field('pe-delete').classList.toggle('d-none', !profile);
    field('profile-editor-error').classList.add('d-none');
}

function readForm() {
    const rules = field('pe-rules').value.split('\n').map(r => r.trim()).filter(Boolean);
    const payload = {
        id: field('pe-id').value.trim(),
        name: field('pe-name').value.trim(),
        personality: { system_prompt: field('pe-prompt').value.trim() },
    };

    const voiceId = field('pe-voice').value;
    if (voiceId) {
        payload.voice = { provider: field('pe-voice-provider').value, voice_id: voiceId };
    }
    if (field('pe-avatar').value) payload.avatar = field('pe-avatar').value;

    const identity = {
        role: field('pe-role').value.trim() || null,
        gender: field('pe-gender').value || null,
        age: field('pe-age').value ? Number(field('pe-age').value) : null,
        backstory: field('pe-backstory').value.trim() || null,
    };
    if (Object.values(identity).some(Boolean)) payload.identity = identity;

    const maxWords = field('pe-max-words').value;
    if (rules.length || maxWords) {
        payload.guardrails = { rules, max_response_words: maxWords ? Number(maxWords) : null };
    }
    return payload;
}

function showError(message) {
    const box = field('profile-editor-error');
    box.textContent = message;
    box.classList.remove('d-none');
}

async function save() {
    const payload = readForm();
    if (!payload.id || !payload.name) { showError('ID and display name are required.'); return; }
    if (!payload.personality.system_prompt) { showError('A system prompt is required.'); return; }

    const url = editingId ? `/api/profiles/${encodeURIComponent(editingId)}` : '/api/profiles/create';
    const resp = await fetch(url, {
        method: editingId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (data.error) { showError(data.error); return; }

    notify(editingId ? 'Profile updated' : 'Profile created', 'success');
    bootstrap.Modal.getInstance(field('profile-editor-modal')).hide();
    await reloadProfileList();
}

async function remove() {
    if (!editingId) return;
    if (!window.confirm(`Delete the profile "${editingId}"? The YAML file is removed too.`)) return;

    const data = await (await fetch(`/api/profiles/${encodeURIComponent(editingId)}`, { method: 'DELETE' })).json();
    if (data.error) { showError(data.error); return; }

    notify('Profile deleted', 'info');
    bootstrap.Modal.getInstance(field('profile-editor-modal')).hide();
    await reloadProfileList();
}

/** Refresh whatever profile lists the console is showing. */
export async function reloadProfileList() {
    if (typeof window.loadProfiles === 'function') await window.loadProfiles();
    document.dispatchEvent(new CustomEvent('ovarp:profiles-changed'));
}

export function openProfileEditor(profile = null) {
    editingId = profile?.id || null;
    fillForm(profile);
    new bootstrap.Modal(field('profile-editor-modal')).show();
}

/** Load an existing profile by id and open it for editing. */
export async function editProfileById(profileId) {
    const profile = await (await fetch(`/api/profiles/${encodeURIComponent(profileId)}`)).json();
    if (profile.error) { notify(profile.error, 'warning'); return; }
    openProfileEditor(profile);
}

export async function initProfileEditor() {
    document.body.insertAdjacentHTML('beforeend', MODAL_HTML);

    field('pe-voice-provider').addEventListener('change', populateVoiceOptions);
    field('pe-save').addEventListener('click', save);
    field('pe-delete').addEventListener('click', remove);

    // Voice and avatar vocabularies come from config.yaml, same as everywhere else
    try {
        const config = await (await fetch('/api/config')).json();
        voicesByProvider = config.tts || voicesByProvider;
        const avatars = config.custom_commands?.avatar?.values || [];
        field('pe-avatar').innerHTML = '<option value="">—</option>' +
            avatars.map(a => `<option value="${esc(a)}">${esc(a)}</option>`).join('');
        populateVoiceOptions();
    } catch { /* the console reports connection problems on its own */ }

    window.openProfileEditor = openProfileEditor;
    window.editProfileById = editProfileById;
}
