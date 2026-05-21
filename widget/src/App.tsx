import { useEffect, useMemo, useState } from "react";
import ChatWidget from "./components/ChatWidget";
import {
  fetchWidgetConfig,
  readLoaderParams,
  type WidgetConfig,
} from "./api";

function sessionIdFromStorage(widgetId: string): string {
  const key = `copilot_session_${widgetId}`;
  let id = localStorage.getItem(key);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(key, id);
  }
  return id;
}

export default function App() {
  const params = useMemo(() => readLoaderParams(), []);
  const [config, setConfig] = useState<WidgetConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!params) {
      setError(
        "Missing widget_id. Embed via <script data-widget-id=...> on a host page."
      );
      return;
    }
    let cancelled = false;
    fetchWidgetConfig(params.apiUrl, params.widgetId, params.parentOrigin)
      .then((cfg) => {
        if (!cancelled) setConfig(cfg);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        if (err.message === "origin_not_allowed") {
          setError(
            "This widget is not allowed on this origin. Check the widget's allowed_origins."
          );
        } else {
          setError(`Could not load widget config: ${err.message}`);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [params]);

  if (error) {
    return <div className="copilot-error">{error}</div>;
  }
  if (!config || !params) {
    return <div className="loading">Loading widget…</div>;
  }

  const sessionId = sessionIdFromStorage(params.widgetId);
  return (
    <ChatWidget
      config={config}
      sessionId={sessionId}
      parentOrigin={params.parentOrigin}
    />
  );
}
