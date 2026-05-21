/*
 * Maintainer's Copilot — embeddable widget loader.
 *
 * Usage on a host page:
 *
 *   <script src="https://api.example.com/widget.js"
 *           data-widget-id="00000000-0000-0000-0000-000000000000"></script>
 *
 * The loader:
 *   1. Reads `data-widget-id` from its own <script> tag.
 *   2. Injects a small floating iframe pointing at the React widget,
 *      passing widget_id, parent_origin, and api_url as query params.
 *   3. Listens for `copilot:resize` postMessage events from the iframe and
 *      resizes the iframe to match (validated against the widget origin).
 *
 * The backend stamps WIDGET_BASE_URL and API_BASE_URL into this file at
 * request time.
 */
(function () {
  "use strict";

  function findScriptTag() {
    var scripts = document.querySelectorAll("script[data-widget-id]");
    for (var i = scripts.length - 1; i >= 0; i--) {
      var s = scripts[i];
      var src = s.getAttribute("src") || "";
      if (src.indexOf("/widget.js") !== -1) return s;
    }
    return scripts[scripts.length - 1] || null;
  }

  var script = findScriptTag();
  if (!script) {
    console.error("[copilot-widget] <script data-widget-id> not found");
    return;
  }
  var widgetId = script.getAttribute("data-widget-id");
  if (!widgetId) {
    console.error("[copilot-widget] data-widget-id attribute is required");
    return;
  }

  var widgetBaseUrl = "__WIDGET_BASE_URL__".replace(/\/$/, "");
  var apiUrl = "__API_BASE_URL__".replace(/\/$/, "");
  var parentOrigin = window.location.origin;

  function buildIframeUrl() {
    var params =
      "?widget_id=" +
      encodeURIComponent(widgetId) +
      "&parent_origin=" +
      encodeURIComponent(parentOrigin) +
      "&api_url=" +
      encodeURIComponent(apiUrl);
    return widgetBaseUrl + "/" + params;
  }

  function createIframe() {
    var iframe = document.createElement("iframe");
    iframe.src = buildIframeUrl();
    iframe.title = "Maintainer's Copilot";
    iframe.setAttribute("allow", "");
    iframe.setAttribute("aria-label", "Maintainer's Copilot chat widget");
    // Starts collapsed — the React widget posts a resize message when it
    // wants to expand (e.g. when the user opens the chat panel).
    iframe.style.cssText = [
      "position:fixed",
      "bottom:1rem",
      "right:1rem",
      "border:0",
      "background:transparent",
      "z-index:2147483647",
      "width:4rem",
      "height:4rem",
      "transition:width .15s, height .15s",
    ].join(";");
    return iframe;
  }

  function widgetOrigin() {
    try {
      return new URL(widgetBaseUrl).origin;
    } catch (err) {
      return null;
    }
  }

  function clampPx(value, min, max) {
    var n = Number(value);
    if (!isFinite(n)) return min;
    return Math.max(min, Math.min(max, Math.round(n)));
  }

  function mount() {
    if (!document.body) {
      document.addEventListener("DOMContentLoaded", mount);
      return;
    }
    var iframe = createIframe();
    document.body.appendChild(iframe);

    var allowedOrigin = widgetOrigin();
    window.addEventListener("message", function (event) {
      if (allowedOrigin && event.origin !== allowedOrigin) return;
      if (event.source !== iframe.contentWindow) return;
      var data = event.data || {};
      if (!data || typeof data !== "object") return;
      if (data.type !== "copilot:resize") return;
      var w = clampPx(data.width, 60, Math.min(window.innerWidth - 16, 720));
      var h = clampPx(data.height, 60, Math.min(window.innerHeight - 16, 800));
      iframe.style.width = w + "px";
      iframe.style.height = h + "px";
    });
  }

  mount();
})();
