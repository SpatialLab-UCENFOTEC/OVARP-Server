/**
 * OVARP: Overview panel.
 *
 * The landing tab. It answers "what is this and where do I start" with a set
 * of launchers, and "is it working" with the live state the other tabs each
 * hold a fragment of.
 */

const REFRESH_INTERVAL_MS = 10000;

let refreshTimer = null;

function setMetric(id, text, color = null) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.style.color = color || 'var(--text)';
}

async function fetchJson(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`${url} → ${resp.status}`);
    return resp.json();
}

async function refreshSession() {
    try {
        const status = await fetchJson('/api/session/status');
        if (status.active) {
            setMetric('ov-session-status',
                `${status.participant_id} · ${status.marker_count} markers`,
                status.status === 'paused' ? 'var(--amber)' : 'var(--emerald)');
        } else {
            setMetric('ov-session-status', 'No Session', 'var(--text-muted)');
        }
    } catch {
        setMetric('ov-session-status', 'Unavailable', 'var(--text-muted)');
    }
}

async function refreshProviders() {
    try {
        const config = await fetchJson('/api/llm/config');
        setMetric('ov-llm-provider', (config.active_provider || '—').toUpperCase());

        const overriding = config.agents_overriding_global || [];
        if (overriding.length) {
            const names = overriding.map(a => a.profile_id || a.agent_id);
            setMetric('ov-profile', names.join(', '), 'var(--text)');
        } else {
            setMetric('ov-profile', 'Global prompt', 'var(--text-muted)');
        }
    } catch {
        setMetric('ov-llm-provider', 'Unavailable', 'var(--text-muted)');
    }
}

async function refreshClients() {
    try {
        const { count } = await fetchJson('/api/clients');
        setMetric('ov-client-count', String(count),
            count > 0 ? 'var(--emerald)' : 'var(--text-muted)');
    } catch {
        setMetric('ov-client-count', '—', 'var(--text-muted)');
    }
}

/** Repaint every card. Also bound to the panel's Refresh button. */
export async function refreshOverview() {
    await Promise.all([refreshSession(), refreshProviders(), refreshClients()]);
}

/** Reflect the WebSocket state the SDK reports, which polling cannot see. */
export function setOverviewConnection(connected) {
    setMetric('ov-server-status',
        connected ? 'Connected (WS)' : 'Reconnecting…',
        connected ? 'var(--emerald)' : 'var(--amber)');
}

export function initOverview() {
    // Launchers and the Refresh button are inline onclick=, not module scope.
    window.switchTab = (tabId) => document.getElementById(tabId)?.click();
    window.refreshOverview = refreshOverview;

    refreshOverview();
    refreshTimer = setInterval(refreshOverview, REFRESH_INTERVAL_MS);

    document.addEventListener('ovarp:keys-changed', refreshProviders);
    window.addEventListener('beforeunload', () => clearInterval(refreshTimer));
}
