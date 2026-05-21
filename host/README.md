# Host demo

Minimal static page that embeds the React widget via iframe.

```bash
# After widget is running on :5173
open "http://localhost:8080?widget=http://localhost:5173&api=http://localhost:8000"
```

Docker: built as `host` service in `docker compose`.
