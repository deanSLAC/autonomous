/* Shared browser utilities for all BL15-2 pages.
 *
 * Load this BEFORE any page script:
 *   <script src="/static/shared/util.js?v=1"></script>
 *
 * Everything hangs off the `BL` namespace so page scripts can keep
 * their local names as thin aliases (e.g. `const escapeHtml = BL.escapeHtml;`).
 */

window.BL = window.BL || {};

/**
 * HTML-escape a value for interpolation into markup, attribute-safe
 * (escapes & < > " '). null/undefined -> "", numbers stringify (0 -> "0").
 */
BL.escapeHtml = function (s) {
    if (s == null) return "";
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
};

/**
 * fetch() that times out (15 s default), throws on a non-2xx response
 * (Error with a `.status` property), and returns parsed JSON.
 *
 * @param {string} url
 * @param {RequestInit} [opts] — pass `signal` to override the timeout.
 */
BL.fetchJson = async function (url, opts) {
    opts = opts || {};
    if (!opts.signal) {
        opts = { ...opts, signal: AbortSignal.timeout(15000) };
    }
    const r = await fetch(url, opts);
    if (!r.ok) {
        const err = new Error(`HTTP ${r.status} for ${url}`);
        err.status = r.status;
        throw err;
    }
    return r.json();
};

/**
 * Wrap a polling function so each tick is skipped when the tab is
 * hidden or while the previous tick is still in flight. Cadence of the
 * surrounding setInterval is unchanged.
 */
BL.pollWrap = function (fn) {
    let inFlight = false;
    return async function (...args) {
        if (document.hidden || inFlight) return;
        inFlight = true;
        try {
            return await fn.apply(this, args);
        } finally {
            inFlight = false;
        }
    };
};
