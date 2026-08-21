/**
 * OVARP — API access layer.
 *
 * Wraps window.fetch so every same-origin /api/ call carries the console token
 * when the server asks for one. Wrapping rather than routing each call site
 * through a helper means existing code and anything added later are covered
 * without being rewritten.
 */

const TOKEN_STORAGE_KEY = 'OVARP_console_token';
const TOKEN_HEADER = 'X-OVARP-Token';

let tokenRequired = false;

export function getToken() {
    return sessionStorage.getItem(TOKEN_STORAGE_KEY) || '';
}

export function setToken(token) {
    sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearToken() {
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
}

export function isTokenRequired() {
    return tokenRequired;
}

function isConsoleApiCall(url) {
    try {
        return new URL(url, window.location.origin).origin === window.location.origin
            && new URL(url, window.location.origin).pathname.startsWith('/api/');
    } catch {
        return false;
    }
}

/** Inject the token header into console API calls, leaving everything else alone. */
function installFetchInterceptor() {
    const originalFetch = window.fetch.bind(window);

    window.fetch = (input, init = {}) => {
        const url = typeof input === 'string' ? input : input.url;
        if (!isConsoleApiCall(url)) return originalFetch(input, init);

        const token = getToken();
        if (!token) return originalFetch(input, init);

        const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
        headers.set(TOKEN_HEADER, token);
        return originalFetch(input, { ...init, headers });
    };
}

async function verifyToken(token) {
    const resp = await fetch('/api/auth/verify', {
        method: 'POST',
        headers: { [TOKEN_HEADER]: token },
    });
    return resp.ok;
}

/**
 * Ask for the token until one is accepted. Runs before any other API call so
 * the console never renders a half-loaded state built from 401 responses.
 */
async function promptUntilValid() {
    for (;;) {
        const entered = window.prompt(
            'This OVARP server requires an access token.\n' +
            'It is the OVARP_ACCESS_TOKEN value from the server\'s .env file.'
        );
        if (entered === null) {
            document.body.innerHTML =
                '<div style="padding:3rem;font-family:system-ui;color:#ddd;background:#1a1a1a;height:100vh">' +
                '<h2>Access token required</h2><p>Reload the page to try again.</p></div>';
            throw new Error('Console access cancelled');
        }
        if (await verifyToken(entered.trim())) {
            setToken(entered.trim());
            return;
        }
        window.alert('That token was not accepted.');
    }
}

/** Resolve once the console is allowed to talk to the API. */
export async function initApiAccess() {
    installFetchInterceptor();

    let status;
    try {
        status = await (await fetch('/api/auth/status')).json();
    } catch {
        return;  // Server unreachable — the console surfaces that on its own
    }

    tokenRequired = Boolean(status.required);
    if (!tokenRequired) return;

    if (getToken() && await verifyToken(getToken())) return;

    clearToken();
    await promptUntilValid();
}
