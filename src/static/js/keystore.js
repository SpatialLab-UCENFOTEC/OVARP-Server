/**
 * OVARP: API Key Store panel.
 *
 * Provider credentials a researcher can set without editing .env and
 * restarting. The server applies them to the running providers immediately and,
 * when asked, writes them to an encrypted store.
 *
 * A key is never carried in a status response: Show fetches it on demand.
 */

const PROVIDERS = ['openai', 'gemini', 'elevenlabs'];

const ENV_NAMES = {
    openai: 'OPENAI_API_KEY',
    gemini: 'GEMINI_API_KEY',
    elevenlabs: 'ELEVENLABS_API_KEY',
};

const BADGE_CLASSES = {
    encrypted: 'badge badge-emerald mono-font',
    plaintext: 'badge badge-amber mono-font',
    memory_only: 'badge badge-indigo mono-font',
    unconfigured: 'badge badge-slate mono-font',
};

let notify = () => {};
let lastStatus = {};

function statusFor(provider) {
    return lastStatus[ENV_NAMES[provider]] || {};
}

function renderProvider(provider) {
    const status = statusFor(provider);
    const badge = document.getElementById(`status-key-${provider}`);
    if (badge) {
        badge.textContent = status.badge || '[NOT CONFIGURED]';
        badge.className = BADGE_CLASSES[status.storage_state] || BADGE_CLASSES.unconfigured;
    }

    const input = document.getElementById(`key-${provider}`);
    if (input && !input.dataset.dirty) {
        input.value = '';
        input.placeholder = status.masked_key || input.dataset.emptyPlaceholder || '';
    }

    const toggle = document.getElementById(`toggle-key-${provider}`);
    if (toggle) {
        toggle.disabled = !status.is_set;
        toggle.textContent = 'Show';
    }
}

/** One line for the header and the Overview card: the weakest state wins. */
function summarise() {
    const states = PROVIDERS.map(p => statusFor(p).storage_state);
    if (states.includes('encrypted')) return '[SAVED, ENCRYPTED]';
    if (states.includes('plaintext')) return '[SAVED, PLAIN TEXT]';
    if (states.includes('memory_only')) return '[IN MEMORY ONLY]';
    return '[NOT CONFIGURED]';
}

function renderAll() {
    PROVIDERS.forEach(renderProvider);

    const summary = summarise();
    const headerBadge = document.getElementById('keystore-summary-badge');
    if (headerBadge) {
        headerBadge.textContent = summary;
        headerBadge.className = summary === '[NOT CONFIGURED]'
            ? 'badge badge-slate mono-font'
            : 'badge badge-emerald mono-font';
    }

    const overview = document.getElementById('ov-key-status');
    if (overview) {
        overview.textContent = summary;
        overview.style.color = summary === '[NOT CONFIGURED]'
            ? 'var(--text-muted)' : 'var(--emerald)';
    }

    const encrypted = PROVIDERS.some(p => statusFor(p).encrypted);
    const saved = PROVIDERS.some(p => statusFor(p).persisted);
    const encValue = document.getElementById('keystore-encryption-value');
    if (encValue) {
        if (encrypted) {
            encValue.textContent = 'Enabled (OVARP_SECRET_KEY set)';
            encValue.style.color = 'var(--emerald)';
        } else if (saved) {
            encValue.textContent = 'Off, keys stored in plain text';
            encValue.style.color = 'var(--amber)';
        } else {
            encValue.textContent = 'Nothing saved yet';
            encValue.style.color = 'var(--text-muted)';
        }
    }
}

export async function refreshKeyStatus() {
    try {
        const data = await (await fetch('/api/keys/status')).json();
        lastStatus = data.keys || {};
        renderAll();
    } catch {
        notify('Could not read the API key status', 'error');
    }
}

/** Collect the fields the researcher actually typed into. */
function editedKeys() {
    const updates = {};
    for (const provider of PROVIDERS) {
        const input = document.getElementById(`key-${provider}`);
        if (input && input.dataset.dirty) updates[provider] = input.value.trim();
    }
    return updates;
}

function markClean() {
    for (const provider of PROVIDERS) {
        const input = document.getElementById(`key-${provider}`);
        if (input) delete input.dataset.dirty;
    }
}

async function applyKeys(persist) {
    const keys = editedKeys();
    if (!Object.keys(keys).length) {
        notify('Type a key first, or use Clear to remove one', 'warning');
        return;
    }

    try {
        const resp = await fetch('/api/keys/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keys, persist }),
        });
        if (!resp.ok) throw new Error(await resp.text());

        lastStatus = (await resp.json()).keys || {};
        markClean();
        renderAll();
        notify(persist ? 'Keys saved to the key store' : 'Keys applied for this run', 'success');
        document.dispatchEvent(new CustomEvent('ovarp:keys-changed'));
    } catch {
        notify('Could not update the API keys', 'error');
    }
}

async function clearKey(provider) {
    if (!window.confirm(`Remove the ${provider} key from memory and from the key store?`)) return;

    try {
        const resp = await fetch('/api/keys/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider, api_key: '', persist: true }),
        });
        if (!resp.ok) throw new Error(await resp.text());

        lastStatus = (await resp.json()).keys || {};
        const input = document.getElementById(`key-${provider}`);
        if (input) {
            input.value = '';
            delete input.dataset.dirty;
        }
        renderAll();
        notify(`${provider} key cleared`, 'info');
        document.dispatchEvent(new CustomEvent('ovarp:keys-changed'));
    } catch {
        notify(`Could not clear the ${provider} key`, 'error');
    }
}

async function toggleKeyVisibility(provider) {
    const input = document.getElementById(`key-${provider}`);
    const button = document.getElementById(`toggle-key-${provider}`);
    if (!input || !button) return;

    if (input.type === 'text') {
        input.type = 'password';
        button.textContent = 'Show';
        if (!input.dataset.dirty) input.value = '';
        return;
    }

    if (!input.dataset.dirty) {
        try {
            const resp = await fetch('/api/keys/reveal', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key_name: provider }),
            });
            if (!resp.ok) throw new Error(await resp.text());
            input.value = (await resp.json()).api_key || '';
        } catch {
            notify(`Could not read the ${provider} key`, 'error');
            return;
        }
    }
    input.type = 'text';
    button.textContent = 'Hide';
}

export function initKeyStore({ showToast } = {}) {
    if (showToast) notify = showToast;

    for (const provider of PROVIDERS) {
        const input = document.getElementById(`key-${provider}`);
        if (!input) continue;
        input.dataset.emptyPlaceholder = input.placeholder;
        input.addEventListener('input', () => { input.dataset.dirty = '1'; });
    }

    // The panel is driven from inline onclick=, which is not module scope.
    window.applyKeys = applyKeys;
    window.clearKey = clearKey;
    window.toggleKeyVisibility = toggleKeyVisibility;

    refreshKeyStatus();
}
