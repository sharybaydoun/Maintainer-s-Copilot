export type WidgetTheme = {
  primary_color?: string;
  bubble_color?: string;
  title?: string;
};

export type WidgetConfig = {
  widget_id: string;
  name: string;
  allowed_origins: string[];
  theme: WidgetTheme | null;
  greeting: string | null;
  enabled_tools: string[];
  api_url: string;
};

export type ToolCallTrace = {
  name: string;
  arguments: Record<string, unknown>;
  result_summary: string;
  error?: string | null;
};

export type ChatResponse = {
  reply: string;
  tool_trace: ToolCallTrace[];
  sources: string[];
  refused?: boolean;
  refusal_reason?: string | null;
};

type LoaderParams = {
  widgetId: string;
  parentOrigin: string;
  apiUrl: string;
};

export function readLoaderParams(): LoaderParams | null {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  const widgetId = params.get("widget_id");
  const parentOrigin = params.get("parent_origin") || window.location.origin;
  const apiUrl =
    params.get("api_url") ||
    import.meta.env.VITE_API_URL ||
    "http://localhost:8000";
  if (!widgetId) return null;
  return { widgetId, parentOrigin, apiUrl: apiUrl.replace(/\/$/, "") };
}

export async function fetchWidgetConfig(
  apiUrl: string,
  widgetId: string,
  parentOrigin: string
): Promise<WidgetConfig> {
  const url = new URL(`${apiUrl}/widgets/${widgetId}/config`);
  url.searchParams.set("parent_origin", parentOrigin);
  const response = await fetch(url.toString(), {
    method: "GET",
    headers: { Accept: "application/json" },
    credentials: "omit",
  });
  if (response.status === 403) {
    throw new Error("origin_not_allowed");
  }
  if (!response.ok) {
    throw new Error(`config_fetch_failed: HTTP ${response.status}`);
  }
  return response.json();
}

/**
 * Sentinel thrown when the chat request exceeds the client-side timeout
 * (default 20s). The UI catches this and shows the friendly slow-response
 * message instead of an opaque "Error: AbortError".
 */
export class ChatTimeoutError extends Error {
  constructor(message = "chat_timeout") {
    super(message);
    this.name = "ChatTimeoutError";
  }
}

export async function askChat(
  apiUrl: string,
  message: string,
  sessionId: string,
  options: { signal?: AbortSignal; timeoutMs?: number } = {}
): Promise<ChatResponse> {
  const timeoutMs = options.timeoutMs ?? 20_000;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort("timeout"), timeoutMs);

  // If the caller passed their own signal, forward its aborts to ours so
  // both component-unmount cleanup AND the timeout can cancel the request.
  if (options.signal) {
    if (options.signal.aborted) controller.abort("external");
    else
      options.signal.addEventListener("abort", () => controller.abort("external"));
  }

  try {
    const response = await fetch(`${apiUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `HTTP ${response.status}`);
    }
    return (await response.json()) as ChatResponse;
  } catch (err) {
    // Distinguish "we timed out" from "the user navigated away".
    if (controller.signal.aborted) {
      const reason = String(controller.signal.reason ?? "");
      if (reason === "timeout" || (err instanceof DOMException && err.name === "AbortError")) {
        throw new ChatTimeoutError();
      }
    }
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

/**
 * Cheap readiness probe used by the widget header status pill.
 * Returns true iff the API answers /health/ready within ``timeoutMs``.
 */
export async function probeApi(
  apiUrl: string,
  timeoutMs = 4_000
): Promise<boolean> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort("timeout"), timeoutMs);
  try {
    const r = await fetch(`${apiUrl}/health/ready`, {
      method: "GET",
      cache: "no-store",
      signal: controller.signal,
    });
    return r.ok;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timer);
  }
}
