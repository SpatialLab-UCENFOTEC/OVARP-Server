/**
 * OVARP: Console theme toggle.
 *
 * The design system defines both palettes as CSS custom properties keyed off
 * `data-bs-theme`, so switching is one attribute write. The choice is per
 * browser, not per server, so it lives in localStorage.
 */

const STORAGE_KEY = 'OVARP_theme';
const DEFAULT_THEME = 'dark';

function applyTheme(theme) {
    document.documentElement.setAttribute('data-bs-theme', theme);
    const label = document.getElementById('theme-toggle-label');
    if (label) label.textContent = `THEME: ${theme.toUpperCase()}`;
}

function storedTheme() {
    try {
        return localStorage.getItem(STORAGE_KEY) || DEFAULT_THEME;
    } catch {
        return DEFAULT_THEME;
    }
}

export function initTheme() {
    applyTheme(storedTheme());

    const btn = document.getElementById('theme-toggle-btn');
    if (!btn) return;

    btn.addEventListener('click', () => {
        const next = document.documentElement.getAttribute('data-bs-theme') === 'dark'
            ? 'light' : 'dark';
        applyTheme(next);
        try {
            localStorage.setItem(STORAGE_KEY, next);
        } catch {
            // Private browsing: the toggle still works for this page view.
        }
    });
}
