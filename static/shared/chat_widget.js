/* Reusable "Chat with the agent" widget.
 *
 * Usage:
 *   <div id="my-chat-panel" class="panel"></div>
 *   <script src="/static/shared/chat_widget.js"></script>
 *   <script>
 *     mountChatWidget(document.getElementById("my-chat-panel"), {
 *       header: "Chat with the agent",
 *       context: () => ({
 *         experiment_id: "...",      // optional, else server picks
 *         page: "spectrometer_alignment",   // page slug
 *         page_context: { ...arbitrary JSON... },
 *       }),
 *     });
 *   </script>
 *
 * Styling re-uses the .panel / .chat-log / .chat-compose / .chat-msg /
 * .typing-indicator classes already defined in dashboard.css +
 * autonomy.css, so no extra stylesheet is required as long as both
 * are loaded on the host page.
 */
(function () {
    "use strict";

    function escapeHtml(s) {
        if (s == null) return "";
        return String(s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function appendMessage(log, role, text) {
        const placeholder = log.querySelector(".muted");
        if (placeholder && log.children.length === 1) placeholder.remove();
        const el = document.createElement("div");
        el.className = "chat-msg " + role;
        el.textContent = text;
        log.appendChild(el);
        log.scrollTop = log.scrollHeight;
    }

    function setTyping(log, status, on) {
        if (status) status.textContent = on ? "agent thinking…" : "";
        let t = log.querySelector(".typing-indicator");
        if (on) {
            if (!t) {
                t = document.createElement("div");
                t.className = "typing-indicator";
                t.textContent = "agent is thinking…";
                log.appendChild(t);
                log.scrollTop = log.scrollHeight;
            }
        } else if (t) {
            t.remove();
        }
    }

    function mountChatWidget(container, opts) {
        opts = opts || {};
        const header = opts.header || "Chat with the agent";
        const placeholder = opts.placeholder || "Ask the agent anything…  (Enter sends, Shift+Enter newline)";
        const emptyText = opts.emptyText || "No messages yet.";
        const endpoint = opts.endpoint || "/api/chat";

        container.classList.add("panel");
        container.innerHTML = `
            <div class="panel-header">
                ${escapeHtml(header)}
                <span class="panel-sub chat-status"></span>
            </div>
            <div class="chat-log"><div class="muted">${escapeHtml(emptyText)}</div></div>
            <div class="chat-compose">
                <textarea class="chat-input" rows="3" placeholder="${escapeHtml(placeholder)}"></textarea>
                <button type="button" class="chat-send">Send</button>
            </div>
        `;

        const log = container.querySelector(".chat-log");
        const input = container.querySelector(".chat-input");
        const btn = container.querySelector(".chat-send");
        const status = container.querySelector(".chat-status");

        async function send() {
            const text = input.value.trim();
            if (!text) return;
            input.value = "";
            appendMessage(log, "user", text);
            btn.disabled = true;
            const origLabel = btn.textContent;
            btn.textContent = "…";
            setTyping(log, status, true);
            try {
                let ctx = {};
                if (typeof opts.context === "function") {
                    try { ctx = (await opts.context()) || {}; } catch (_) { ctx = {}; }
                }
                const body = { message: text };
                if (ctx.experiment_id) body.experiment_id = ctx.experiment_id;
                if (ctx.page) body.page = ctx.page;
                if (ctx.page_context) body.page_context = ctx.page_context;
                const r = await fetch(endpoint, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(body),
                });
                const j = await r.json().catch(() => ({}));
                setTyping(log, status, false);
                if (!r.ok) {
                    appendMessage(log, "assistant", "Error: " + (j.error || j.detail || `HTTP ${r.status}`));
                } else {
                    appendMessage(log, "assistant", j.response || j.error || "(no response)");
                }
            } catch (e) {
                setTyping(log, status, false);
                appendMessage(log, "assistant", "Error: " + (e && e.message ? e.message : e));
            } finally {
                btn.disabled = false;
                btn.textContent = origLabel || "Send";
                input.focus();
            }
        }

        btn.addEventListener("click", send);
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
            }
        });

        return {
            send,
            appendUser: (t) => appendMessage(log, "user", t),
            appendAssistant: (t) => appendMessage(log, "assistant", t),
        };
    }

    window.mountChatWidget = mountChatWidget;
})();
