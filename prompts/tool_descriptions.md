# Tool catalog

Human-readable reference for the tools exposed to the Maintainer's Copilot LLM via
OpenAI-compatible function calling. The canonical machine-readable schema lives
in `app/services/chatbot.py::TOOLS`.

## `classify_issue(text)`

- **Returns:** `{ label, confidence }` where `label ∈ {bug, feature, docs, question}`.
- **Backed by:** `app/infra/classifier.py::IssueClassifier` (BERT-tiny, in-process).
- **When to use:** the user asks to triage an issue, pastes an issue body, or
  asks "what kind of issue is this?".

## `extract_entities(text)`

- **Returns:** `{ entities: { filenames, functions, urls, stack_trace, code_tokens } }`.
- **Backed by:** `app/infra/ner.py` regex extractor.
- **When to use:** the user wants code-shaped entities pulled out of pasted text.

## `summarize_thread(text)`

- **Returns:** `{ summary }` — a 3–5 bullet maintainer-facing summary.
- **Backed by:** `app/infra/summarizer.py::IssueSummarizer` (Groq LLM).
- **When to use:** the user pastes a multi-paragraph issue thread and asks for
  a summary.

## `search_docs(query)`

- **Returns:** `{ results: [{ source, section, score, text }], sources: [...] }`.
- **Backed by:** `app/infra/retrieval.py::Retriever` (hybrid dense + BM25 + rerank).
- **When to use:** any factual question about the project — what files exist,
  what was decided, what the metrics are, how startup validation works, etc.

## `write_memory(note)`

- **Returns:** `{ status, stored_chars }`.
- **Backed by:** `app/infra/chat_memory.py::ChatMemory` (Redis short-term).
- **When to use:** the user explicitly asks the bot to remember something. Never
  call this on the model's own initiative.
- **Scope (Phase 1):** notes go to short-term Redis memory only. Long-term
  pgvector memory is a future phase.
