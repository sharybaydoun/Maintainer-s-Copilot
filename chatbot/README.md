# Streamlit chatbot

Week 7 admin/chat UI — **API client only**, no RAG logic.

```
chatbot/
  app.py           # login placeholder (home)
  auth.py          # placeholder auth
  api_client.py    # httpx → FastAPI
  pages/
    Chat.py        # POST /rag/query
    Admin.py       # GET /admin/*
    Memory.py      # memory inspector placeholder
```

```bash
pip install -r chatbot/requirements.txt
PYTHONPATH=. API_URL=http://127.0.0.1:8000 streamlit run chatbot/app.py
```

Default login: `admin` / `copilot` (`CHATBOT_USER`, `CHATBOT_PASSWORD`).
