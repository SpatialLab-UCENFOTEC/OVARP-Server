/**
 * OVARP — Playground persona controls.
 *
 * The prompt box and the Profiles tab write to the same place: applying a
 * profile parks a composed prompt on the agent that wins over the global one.
 * Editing the global prompt then appears to do nothing, with no explanation.
 *
 * This surfaces that relationship — which agents are following a profile, and a
 * way to apply or release one without leaving the Playground.
 */

const esc = (s) => { const d = document.createElement('div'); d.textContent = s ?? ''; return d.innerHTML; };

function notify(message, type = 'info') {
    if (typeof window.showToast === 'function') window.showToast(message, type);
}

function targetAgent() {
    return document.getElementById('target-agent')?.value || 'all';
}

async function populateProfiles() {
    const select = document.getElementById('pg-profile-select');
    if (!select) return;
    try {
        const { profiles } = await (await fetch('/api/profiles')).json();
        const current = select.value;
        select.innerHTML = '<option value="">No profile (global prompt)</option>' +
            profiles.map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
        if (current) select.value = current;
    } catch {
        // The console reports connection problems on its own
    }
}

/**
 * Show which agents ignore the global prompt, so a save that will not reach
 * them does not look like it succeeded everywhere.
 */
export async function refreshOverrideWarning() {
    const box = document.getElementById('prompt-override-warning');
    if (!box) return;
    try {
        const config = await (await fetch('/api/llm/config')).json();
        const overriding = config.agents_overriding_global || [];

        if (!overriding.length) {
            box.classList.add('d-none');
            return;
        }
        const names = overriding
            .map(a => `<strong>${esc(a.name || a.agent_id)}</strong>${a.profile_id ? ` (${esc(a.profile_id)})` : ''}`)
            .join(', ');
        box.innerHTML = `⚠️ ${names} ${overriding.length === 1 ? 'has' : 'have'} a profile applied and ` +
            'will use its prompt, not this one. Release the profile below to change that.';
        box.classList.remove('d-none');
    } catch {
        box.classList.add('d-none');
    }
}

async function applySelectedProfile() {
    const select = document.getElementById('pg-profile-select');
    const agentId = targetAgent();

    // The empty option means "stop following a profile"
    if (!select.value) {
        await releaseAgent(agentId);
        return;
    }

    const resp = await fetch('/api/profiles/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile_id: select.value, agent_id: agentId }),
    });
    const data = await resp.json();
    if (data.error) { notify(data.error, 'warning'); return; }

    notify(`${data.profile_name} applied to ${agentId}`, 'success');
    await refreshOverrideWarning();
    await refreshHint();
}

async function releaseAgent(agentId) {
    if (agentId === 'all') {
        const config = await (await fetch('/api/config')).json();
        await Promise.all(config.agents.map(a =>
            fetch(`/api/agents/${encodeURIComponent(a.id)}/reset`, { method: 'POST' })));
    } else {
        await fetch(`/api/agents/${encodeURIComponent(agentId)}/reset`, { method: 'POST' });
    }
    notify(`${agentId} follows the global prompt again`, 'info');
    await refreshOverrideWarning();
    await refreshHint();
}

async function refreshHint() {
    const hint = document.getElementById('pg-profile-hint');
    const select = document.getElementById('pg-profile-select');
    if (!hint) return;

    const agentId = targetAgent();
    if (agentId === 'all') {
        hint.textContent = 'Applies to every agent. Change the target in Live Control.';
        return;
    }
    try {
        const info = await (await fetch(`/api/agents/${encodeURIComponent(agentId)}`)).json();
        hint.textContent = info.profile_id
            ? `${agentId} is following "${info.profile_id}".`
            : `${agentId} is on the global prompt.`;
        if (info.profile_id && select) select.value = info.profile_id;
    } catch {
        hint.textContent = '';
    }
}

export async function initPlaygroundPersona() {
    const applyBtn = document.getElementById('pg-apply-profile-btn');
    if (!applyBtn) return;

    applyBtn.addEventListener('click', applySelectedProfile);
    document.getElementById('target-agent')?.addEventListener('change', refreshHint);
    document.addEventListener('ovarp:profiles-changed', populateProfiles);

    await populateProfiles();
    await refreshOverrideWarning();
    await refreshHint();
}
