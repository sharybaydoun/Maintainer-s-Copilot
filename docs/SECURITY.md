# Security — Maintainer's Copilot

## Threat model in one paragraph

A maintainer pastes raw issue text into the chatbot. That text frequently
contains tracebacks copied from production logs and, occasionally, secrets the
user did not realise were in their clipboard (GitHub tokens left in a curl
command, AWS keys in a screenshot transcript). The system must (a) never
persist those secrets verbatim into logs, traces, memory, audit rows, or eval
artifacts; (b) only serve answers grounded in indexed documentation, never make
up file paths; and (c) be embeddable in third-party host pages without giving
those hosts a way to bypass the allowlist.

## Redaction layer

Implementation: `app/infra/redaction.py`. Two entry points:

- `redact(text)` — string-in, string-out, pattern substitution.
- `redact_value(value)` — recursive walk of `dict`/`list`/`tuple` with
  key-based redaction for sensitive keys + pattern-based redaction for string
  values.

Redaction runs **before** any of these leave the service boundary:

| Sink | Where redaction is applied |
|------|----------------------------|
| Structured logs | `app/infra/logging_config.JsonFormatter.format` calls `redact_value(payload)` |
| OTel trace span attributes | tool-input / tool-output set via the same `redact_value` in `app/services/chatbot._dispatch_and_record` |
| Short-term memory (Redis) | chatbot's `_tool_write_memory` redacts the note string before `ChatMemory.append` |
| Long-term memory (pgvector) | `redact(raw_note)` + `redact_value(metadata)` before `insert_long_term_memory` |
| Audit-log metadata | same call chain — audit row and memory row share the redacted payload |

The LLM still receives the **raw** user message for reasoning. Redaction is a
side-effect on persisted / observed copies only. This is deliberate: we want
the model to give a useful answer to a maintainer who pasted a real traceback,
without that traceback ending up in the database.

### Patterns we redact, and why

| Pattern | Replacement | Real-world source it appears in |
|---------|-------------|---------------------------------|
| `sk-[A-Za-z0-9_\-]{20,}` | `sk-[REDACTED]` | OpenAI / Groq API keys leaked from curl examples and code blocks pasted into issue bodies |
| `ghp_[A-Za-z0-9]{20,}` | `ghp_[REDACTED]` | GitHub personal access tokens — extremely common in `gh` command pastes |
| `github_pat_[A-Za-z0-9_]{20,}` | `github_pat_[REDACTED]` | Newer GitHub fine-grained PAT format |
| `glpat-[A-Za-z0-9_\-]{20,}` | `glpat-[REDACTED]` | GitLab project / personal access tokens (we don't fetch GitLab today but `pandas` users do) |
| `AKIA[0-9A-Z]{16}` | `AKIA[REDACTED]` | AWS access key IDs — show up when users paste `aws s3 cp` reproductions |
| `(?i)\bbearer\s+[A-Za-z0-9._\-]+` | `Bearer [REDACTED]` | HTTP authorization headers in copy-pasted requests; covers JWTs we don't recognise by shape |
| `\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b` | `[EMAIL_REDACTED]` | Reporter / maintainer emails copied from `git log` output or `@mention`-adjacent text |

Order matters: the broad `Bearer …` regex is intentionally listed after the
specific token patterns so it doesn't eat shorter, more specific tokens.

### Sensitive keys (key-based redaction)

For dict-shaped values, any key whose lowercase name is in the set below has
its value replaced with `[[REDACTED]]` regardless of pattern match. This catches
opaque tokens (especially JWTs) that don't fit a regex shape:

```
password, hashed_password, secret, api_key, openai_api_key, groq_api_key,
github_token, authorization, jwt, token
```

This is the defence against the failure mode "the model returned a dict
whose 'token' key contains an unrecognised opaque string".

### What the test asserts

`tests/test_redaction.py` runs in CI on every push (the `unit-tests` job,
before any eval). It asserts:

- A fake `sk-…` key, a fake `ghp_…` PAT, a fake `Bearer …`, a fake email, a
  fake AWS key ID, and a fake `glpat-…` are all replaced when passed through
  `redact()` and through `JsonFormatter.format` on a log record.
- A short-term Redis memory write of a sensitive payload stores the
  **redacted** version, never the raw one.
- A long-term pgvector memory write of a sensitive payload stores the
  **redacted** version in both the memory row and the audit log row.

If any of those assertions ever flips, CI fails before evals even run.

## Secrets — Vault is the source of truth

- **Vault** (dev-mode in compose, `hashicorp/vault:1.18`) holds every
  application secret at KV path `secret/copilot`:
  - `openai_api_key` → `OPENAI_API_KEY`
  - `database_url` → `DATABASE_URL`
  - `jwt_secret` → `JWT_SECRET`
  - `minio_access_key` → `MINIO_ACCESS_KEY`
  - `minio_secret_key` → `MINIO_SECRET_KEY`
  - `minio_bucket` → `MINIO_BUCKET`
  - `minio_endpoint` → `MINIO_ENDPOINT`
- `app/infra/vault.load_secrets` resolves these at startup and
  `apply_secrets` maps them into the process environment **before**
  anything else looks at `os.environ`.
- `VAULT_REQUIRED=true` makes the API **refuse to boot** if Vault is
  unreachable (`vault.load_secrets` raises `RuntimeError`). Use this in
  production. The compose file leaves `VAULT_REQUIRED=false` for the
  developer-on-a-flight scenario.
- `.env.example` (production-shaped) carries only the Vault root token and
  ports. `.env.dev.example` carries dev-mode fallbacks with `# DEV ONLY`
  markers on every secret.
- `grep -ri 'sk-' app/` and `grep -ri 'password' app/` return only the Vault-
  read paths in `app/infra/vault.py` and `app/infra/auth.py` (no committed
  secret values).

If Vault becomes unreachable **after** the API is already running, the
existing secrets stay in process memory and the API keeps serving — the
in-process state is the cache. The next restart will fail closed (with
`VAULT_REQUIRED=true`) or fall back to env (with `VAULT_REQUIRED=false`).

## Authentication and admin protection

- `fastapi-users` with a JWT bearer strategy
  (`app/infra/auth.AuthenticationBackend`).
- Two roles: `user` and `admin`. `admin` is enforced via the
  `current_admin_user` FastAPI dependency.
- All routes under `/admin/*` (including `/admin/widgets/*`) carry
  `dependencies=[Depends(current_admin_user)]` when `AUTH_REQUIRED=true`.
- `AUTH_REQUIRED=false` (local dev only — `.env.dev.example` default) lifts
  the dependency so an unauthenticated developer can curl admin endpoints
  while iterating. The dev-mode-warning is logged on boot.
- JWT secret loading is fail-closed when auth is required: missing /
  short `JWT_SECRET` aborts startup with `StartupValidationError`
  (`app/infra/startup_validation._check_jwt_secret`).
- An ephemeral dev JWT is generated and warned about when `AUTH_REQUIRED=false`
  and no secret is configured — so developer-curls still work but the warning
  makes it impossible to ship that posture by accident.

The compose API healthcheck is `GET /health/ready` (unauthenticated) so
flipping `AUTH_REQUIRED=true` does not make the API container go unhealthy.

## Widget — origin allowlist and CSP

The embeddable widget has two independent gates against a malicious host
embedding it:

1. **Backend origin allowlist (`/widgets/{id}/config`)** —
   `app/services/widget_security.origin_allowed`. The parent's origin is
   extracted from (in order) the `parent_origin` query parameter, the
   `Origin` header, or the `Referer` header. If the resulting origin is not
   in the widget row's `allowed_origins`, the API returns HTTP 403 with a
   structured envelope. Wildcards (`*`) are supported but only on widgets
   that explicitly opt in.

2. **Browser CSP** — the same endpoint emits
   `Content-Security-Policy: frame-ancestors <allowed_origins>` (built by
   `widget_security.frame_ancestors_csp`). So even if the JSON config is
   leaked, an unauthorized parent **cannot** iframe the widget — the browser
   blocks the embed.

Friday demo: visit `http://localhost:8080` (allowed) → widget loads. Edit
`/etc/hosts` to make `evil.local` resolve to `127.0.0.1`, visit
`http://evil.local:8080` → backend returns 403 *and* the iframe is blocked by
the parent CSP. The script `scripts/seed_demo_widget.py` writes the demo
widget row whose `allowed_origins` is exactly `http://localhost:8080`.

## Prompt-injection defense

`app/infra/safety.py`:

- A blocklist of common patterns blocks adversarial user queries before they
  reach the LLM: instruction-override (`"ignore previous instructions"`),
  secret extraction (`"reveal API key"`, `"vault token"`), system-prompt
  exfiltration attempts.
- Retrieved chunks are **sanitized** before they're shown to the LLM —
  instruction-like lines (`"system:"`, `"---"`, `"<|"`, etc.) are stripped
  via `sanitize_chunk_text`.
- Violations log a `safety_violation` JSON event with the redacted query and
  the blocked pattern name.
- Extra patterns can be added without a deploy via
  `SAFETY_BLOCKLIST_EXTRA=pattern1|pattern2`.

The chatbot returns the canonical refusal `"I cannot process that request.
Please ask a documentation question about this project."` on a blocked query
— no information about which pattern triggered.

## Grounded refusal — RAG side

`app/services/rag.RagService` returns the literal phrase
`"Not found in retrieved documentation"` (configurable via prompt) when:

- Safety check failed (input)
- Retrieval top score below `RAG_MIN_RETRIEVAL_SCORE` (default 0.35)
- Hallucination heuristic triggers post-generation (answer cites a source not
  in the retrieved set, or references file paths absent from context)

Refusals include a "reformulation hint" so the user understands what to try
next. No fabricated citations.

## Logging and PII

- All logs are JSON on stdout (`JsonFormatter`).
- Every line carries `trace_id`, `span_id`, `request_id`, and (when known)
  `user_id`, `session_id` — so logs and traces are joinable in Jaeger.
- Payload values pass through `redact_value` (see above) so a sensitive
  string never makes it to disk / stdout.
- `prediction_logs` (Postgres) stores `/predict` inputs when `DATABASE_URL`
  is set; the text is **redacted on the way in** (see `app/services/predict.py`).
- Chat memory in Redis: redacted query, redacted answer, redacted sources.
  TTL via `CHAT_MEMORY_TTL_SECONDS` (default 3600 s).

## Production checklist

- [ ] `VAULT_REQUIRED=true` against a production Vault (not dev-mode).
- [ ] `AUTH_REQUIRED=true` so `/admin/*` carries the JWT dependency.
- [ ] `JWT_SECRET` set in Vault (32+ chars).
- [ ] TLS termination at the ingress.
- [ ] CORS allowlist matches the production widget hosts, not `localhost:*`.
- [ ] Non-root container user — `Dockerfile` already runs as UID 10001
      (`copilot`).
- [ ] Secret scanning in CI — repo-level (e.g. `trufflehog`); not yet wired
      into `.github/workflows/`.
- [ ] Rate limiting at the edge for `/chat` and `/rag/query`.

What we already enforce:

- API refuses to boot when classifier weights don't match `MODEL_CARD.md`
  SHA-256.
- API refuses to boot when eval thresholds are missing / zero.
- API refuses to boot when `AUTH_REQUIRED=true` without `JWT_SECRET`.
- Widget config endpoint refuses unallowed origins (HTTP 403 + CSP).
- Redaction layer + redaction test on every CI run.
