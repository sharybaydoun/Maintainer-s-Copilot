# Embeddable React widget

Production-facing chat widget (floating bubble) calling `POST /rag/query`.

```bash
npm install
VITE_API_URL=http://localhost:8000 npm run dev
```

Config: `public/widget-config.json` (loaded at runtime for iframe/embed deployments).

Build: `npm run build` · Docker: `docker build -t copilot-widget .`
