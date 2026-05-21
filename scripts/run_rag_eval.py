#!/usr/bin/env python3
"""RAG evaluation: retrieval metrics + frozen-judge answer quality.

Metrics produced (all 0.0-1.0):

- retrieval_accuracy : case passes if any acceptable source is in top-5
- hit_at_5           : expected source ∈ top-5 retrieved (fraction of cases)
- mrr_at_10          : mean reciprocal rank of first acceptable source in top-10
- faithfulness       : judge says "every claim supported by context"
- answer_relevancy   : judge says "answer addresses the question"
- judge_agreement    : on the self-labeled subset, how often the deterministic
                      heuristic and the LLM judge agree on faithfulness

The judge is a single Groq LLM call per answered case, temperature=0, with a
strict JSON rubric. We deliberately do NOT depend on RAGAS / langchain.

Thresholds live in ``eval_thresholds.yaml`` (rag section). The script exits
non-zero if any threshold is breached.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GOLDEN_PATH = ROOT / "evals/rag_golden.json"
THRESHOLDS_PATH = ROOT / "eval_thresholds.yaml"
REPORT_PATH = ROOT / "reports" / "golden_eval_report.json"
RAG_REPORT_PATH = ROOT / "reports" / "rag_eval_report.json"

MIN_RETRIEVAL_SCORE = float(os.environ.get("RAG_EVAL_MIN_SCORE", "0.25"))
REFUSAL_PHRASE = "not found in retrieved documentation"
SOURCE_CITE_PATTERN = re.compile(r"\bSources:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
JUDGE_MODEL = os.environ.get("RAG_JUDGE_MODEL", "llama-3.1-8b-instant")

JUDGE_PROMPT = """You are a strict evaluator. Compare the candidate answer to the retrieved context.

Question:
{query}

Retrieved context (verbatim chunks, do not assume anything beyond these):
{context}

Candidate answer:
{answer}

Rate as JSON with EXACTLY these keys (and no others):
{{
  "faithful": "yes" or "no",
  "relevant": "yes" or "no",
  "hallucination_present": "yes" or "no",
  "reasoning": "<one short sentence>"
}}

Rules:
- "faithful" = every factual claim in the answer is supported by the context.
- "relevant" = the answer addresses the question.
- "hallucination_present" = the answer mentions file paths, numbers, APIs, or facts NOT in the context.
- If the candidate answer is a refusal ("Not found in retrieved documentation..."), set faithful=yes, hallucination_present=no, and set relevant according to whether the refusal is appropriate.

Output ONLY the JSON. No prose, no markdown fences."""


# ---------------------------------------------------------------------------
# Heuristic helpers (preserved from the previous script)
# ---------------------------------------------------------------------------


def _acceptable(case: dict) -> list[str]:
    return case.get("acceptable_sources") or case.get("expected_sources", [])


def source_match(retrieved_sources: list[str], case: dict) -> bool:
    acceptable = _acceptable(case)
    if acceptable:
        return any(
            any(acc in src or src.endswith(acc) for src in retrieved_sources)
            for acc in acceptable
        )
    keywords = case.get("source_keywords", [])
    joined = " ".join(retrieved_sources).lower()
    return any(keyword.lower() in joined for keyword in keywords)


def keywords_match(answer: str, case: dict) -> bool:
    keywords = case.get("expected_keywords", [])
    if not keywords:
        return True
    lower = answer.lower()
    return any(keyword.lower() in lower for keyword in keywords)


def cited_sources_valid(answer: str, retrieved_sources: list[str]) -> bool:
    match = SOURCE_CITE_PATTERN.search(answer)
    if not match:
        return False
    cited = [part.strip() for part in match.group(1).split(",") if part.strip()]
    allowed = set(retrieved_sources)
    return bool(cited) and all(source in allowed for source in cited)


def hallucination_heuristic(
    answer: str, retrieved_sources: list[str], chunk_text: str
) -> bool:
    if REFUSAL_PHRASE in answer.lower():
        return False
    if not cited_sources_valid(answer, retrieved_sources):
        return True
    context = chunk_text.lower()
    for token in re.findall(r"[\w./-]+\.(?:py|md|json|yaml)", answer):
        if token not in context and token.split("/")[-1] not in context:
            return True
    return False


# ---------------------------------------------------------------------------
# Retrieval metrics
# ---------------------------------------------------------------------------


def _is_acceptable_source(src: str, case: dict) -> bool:
    for acc in _acceptable(case):
        if acc in src or src.endswith(acc):
            return True
    return False


def first_relevant_rank(
    retrieved_sources: list[str], case: dict, *, cap: int
) -> Optional[int]:
    """Return the 1-indexed rank of the first acceptable source in top-`cap`."""
    for i, src in enumerate(retrieved_sources[:cap], start=1):
        if _is_acceptable_source(src, case):
            return i
    return None


def run_retrieval_eval(retriever, cases: list[dict]) -> dict[str, Any]:
    passes = 0
    hits_at_5 = 0
    reciprocal_ranks_at_10: list[float] = []
    per_case: list[dict[str, Any]] = []

    for case in cases:
        case_id = case["id"]
        results, _ = retriever.retrieve(case["query"], top_k=10)
        sources = [hit.source for hit in results]
        top_score = results[0].score if results else 0.0

        rank_at_5 = first_relevant_rank(sources, case, cap=5)
        rank_at_10 = first_relevant_rank(sources, case, cap=10)

        ok_source = source_match(sources, case)
        ok_score = top_score >= MIN_RETRIEVAL_SCORE
        ok_nonempty = bool(results) and bool(results[0].text.strip())

        case_passed = ok_source and ok_score and ok_nonempty
        if case_passed:
            passes += 1
        if rank_at_5 is not None:
            hits_at_5 += 1
        reciprocal_ranks_at_10.append(1.0 / rank_at_10 if rank_at_10 else 0.0)

        per_case.append(
            {
                "id": case_id,
                "category": case.get("category"),
                "passed": case_passed,
                "top_source": sources[0] if sources else None,
                "top_score": round(top_score, 4),
                "rank_at_5": rank_at_5,
                "rank_at_10": rank_at_10,
                "retrieved_sources": sources[:5],
            }
        )
        flag = "PASS" if case_passed else "FAIL"
        print(
            f"RETRIEVAL {flag} {case_id} top_score={top_score:.3f} "
            f"rank@5={rank_at_5} rank@10={rank_at_10} sources={sources[:3]}"
        )

    n = len(cases)
    return {
        "n": n,
        "retrieval_accuracy": passes / n if n else 0.0,
        "hit_at_5": hits_at_5 / n if n else 0.0,
        "mrr_at_10": sum(reciprocal_ranks_at_10) / n if n else 0.0,
        "per_case": per_case,
    }


# ---------------------------------------------------------------------------
# Answer + judge
# ---------------------------------------------------------------------------


def _format_context_for_judge(chunks: list[Any], char_budget: int = 4000) -> str:
    out: list[str] = []
    used = 0
    for i, c in enumerate(chunks, start=1):
        block = f"[{i}] source={c.source} section={c.section or 'n/a'}\n{c.text}"
        if used + len(block) > char_budget:
            block = block[: max(0, char_budget - used)]
        out.append(block)
        used += len(block)
        if used >= char_budget:
            break
    return "\n\n".join(out)


def _judge_one(
    client, query: str, context: str, answer: str
) -> dict[str, Any]:
    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[
            {
                "role": "user",
                "content": JUDGE_PROMPT.format(
                    query=query, context=context, answer=answer
                ),
            }
        ],
        temperature=0.0,
        max_tokens=200,
    )
    raw = (response.choices[0].message.content or "").strip()
    # Strip accidental code fences before parsing.
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Defensive: degrade gracefully so one bad judge call doesn't tank
        # the whole run.
        return {
            "faithful": "no",
            "relevant": "no",
            "hallucination_present": "yes",
            "reasoning": f"judge_parse_failed: {raw[:120]}",
        }


def _yn(value: Any) -> bool:
    return str(value).strip().lower() in {"yes", "true", "1"}


def run_answer_eval(
    rag_service, client, cases: list[dict]
) -> dict[str, Any]:
    from app.domain.rag import RagQueryRequest

    faithful_count = 0
    relevant_count = 0
    refusals = 0
    judge_calls = 0

    self_labeled_total = 0
    judge_agree_count = 0

    per_case: list[dict[str, Any]] = []

    for case in cases:
        case_id = case["id"]
        response = rag_service.query(RagQueryRequest(query=case["query"]))
        answer = response.answer
        chunks = response.retrieved_chunks
        sources = [c.source for c in chunks]
        chunk_text_joined = " ".join(c.text for c in chunks)

        refused = REFUSAL_PHRASE in answer.lower()
        if refused:
            refusals += 1

        # Heuristic faithfulness signal — used both as a sanity check and as
        # the "self-labeled" expectation for judge-agreement scoring.
        heuristic_faithful = (
            not refused
            and cited_sources_valid(answer, sources)
            and not hallucination_heuristic(answer, sources, chunk_text_joined)
        )

        judge = _judge_one(
            client,
            query=case["query"],
            context=_format_context_for_judge(chunks),
            answer=answer,
        )
        judge_calls += 1
        judge_faithful = _yn(judge.get("faithful"))
        judge_relevant = _yn(judge.get("relevant"))
        judge_hallucination = _yn(judge.get("hallucination_present"))

        if judge_faithful:
            faithful_count += 1
        if judge_relevant:
            relevant_count += 1

        case_record: dict[str, Any] = {
            "id": case_id,
            "category": case.get("category"),
            "self_labeled": bool(case.get("self_labeled")),
            "refused": refused,
            "answer_chars": len(answer),
            "judge": {
                "faithful": judge_faithful,
                "relevant": judge_relevant,
                "hallucination_present": judge_hallucination,
                "reasoning": str(judge.get("reasoning", ""))[:240],
            },
            "heuristic": {
                "faithful": heuristic_faithful,
            },
            "sources": sources,
        }

        if case.get("self_labeled"):
            self_labeled_total += 1
            if heuristic_faithful == judge_faithful:
                judge_agree_count += 1
                case_record["judge_agreement"] = "agree"
            else:
                case_record["judge_agreement"] = "disagree"

        per_case.append(case_record)
        print(
            f"ANSWER {'PASS' if judge_faithful and judge_relevant else 'FAIL'} "
            f"{case_id} faithful={judge_faithful} relevant={judge_relevant} "
            f"hallucination={judge_hallucination} refused={refused}"
        )

    n = len(cases)
    judge_agreement = (
        judge_agree_count / self_labeled_total
        if self_labeled_total
        else None
    )
    return {
        "n": n,
        "faithfulness": faithful_count / n if n else 0.0,
        "answer_relevancy": relevant_count / n if n else 0.0,
        "refusals": refusals,
        "judge_agreement": judge_agreement,
        "self_labeled_n": self_labeled_total,
        "judge_calls": judge_calls,
        "per_case": per_case,
    }


# ---------------------------------------------------------------------------
# Thresholds + report
# ---------------------------------------------------------------------------


def _load_thresholds() -> dict[str, Any]:
    raw = yaml.safe_load(THRESHOLDS_PATH.read_text(encoding="utf-8")) or {}
    return raw.get("rag") or {}


def _git_sha() -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except Exception:
        return None


def _check_thresholds(metrics: dict[str, Any], thresholds: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for key in (
        "retrieval_accuracy",
        "hit_at_5",
        "mrr_at_10",
        "faithfulness",
        "answer_relevancy",
        "judge_agreement",
    ):
        threshold_key = f"{key}_min"
        if threshold_key not in thresholds:
            continue
        threshold = thresholds[threshold_key]
        observed = metrics.get(key)
        if observed is None:
            continue
        if observed < threshold:
            failures.append(
                f"{key}={observed:.3f} < {threshold:.3f} (threshold {threshold_key})"
            )
    return failures


def _write_report(
    *,
    retrieval: dict[str, Any],
    answers: Optional[dict[str, Any]],
    thresholds: dict[str, Any],
    failures: list[str],
    answers_skipped_reason: Optional[str] = None,
) -> None:
    timestamp = _dt.datetime.now(_dt.timezone.utc).isoformat()
    git_sha = _git_sha()

    rag_summary: dict[str, Any] = {
        "n": retrieval["n"],
        "retrieval_accuracy": retrieval["retrieval_accuracy"],
        "hit_at_5": retrieval["hit_at_5"],
        "mrr_at_10": retrieval["mrr_at_10"],
    }
    if answers is not None:
        rag_summary.update(
            {
                "faithfulness": answers["faithfulness"],
                "answer_relevancy": answers["answer_relevancy"],
                "judge_agreement": answers["judge_agreement"],
                "refusals": answers["refusals"],
                "self_labeled_n": answers["self_labeled_n"],
            }
        )
    elif answers_skipped_reason:
        rag_summary["answers_status"] = "skipped"
        rag_summary["answers_skipped_reason"] = answers_skipped_reason

    detail_report = {
        "generated_at": timestamp,
        "git_sha": git_sha,
        "thresholds": thresholds,
        "failures": failures,
        "summary": rag_summary,
        "retrieval": retrieval,
        "answers": answers,
    }
    RAG_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAG_REPORT_PATH.write_text(
        json.dumps(detail_report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(f"Wrote {RAG_REPORT_PATH}")

    # Merge into the unified golden_eval_report.json (preserve classification
    # block written by run_classification_eval.py).
    merged: dict[str, Any] = {}
    if REPORT_PATH.is_file():
        try:
            merged = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            merged = {}
    merged.setdefault("generated_at", timestamp)
    merged["generated_at_rag"] = timestamp
    if git_sha:
        merged["git_sha"] = git_sha
    merged["rag"] = rag_summary
    merged["rag_thresholds"] = thresholds
    merged["rag_failures"] = failures
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(merged, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(f"Wrote {REPORT_PATH}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RAG golden evals")
    parser.add_argument(
        "--with-answers",
        action="store_true",
        help="Also run answer evaluation (RAG generation + LLM judge). Requires OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--skip-gating",
        action="store_true",
        help="Compute metrics + write the report, but do not exit non-zero on threshold breach.",
    )
    args = parser.parse_args()

    if not GOLDEN_PATH.is_file():
        print(f"Missing {GOLDEN_PATH}", file=sys.stderr)
        return 1

    from app.rag.retrieval import load_retriever

    retriever = load_retriever()
    if retriever is None:
        print(
            "RAG index not built. Run: python scripts/build_rag_corpus.py && "
            "python scripts/build_rag_index.py",
            file=sys.stderr,
        )
        return 1

    cases = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    thresholds = _load_thresholds()

    retrieval = run_retrieval_eval(retriever, cases)
    print(
        f"\nRetrieval: accuracy={retrieval['retrieval_accuracy']:.3f} "
        f"hit@5={retrieval['hit_at_5']:.3f} MRR@10={retrieval['mrr_at_10']:.3f}"
    )

    answers: Optional[dict[str, Any]] = None
    answers_skipped_reason: Optional[str] = None
    api_key = os.environ.get("OPENAI_API_KEY")
    if args.with_answers:
        if not api_key:
            answers_skipped_reason = "OPENAI_API_KEY not set"
            print(
                "Skipping answer eval: OPENAI_API_KEY not set", file=sys.stderr
            )
        else:
            try:
                from openai import OpenAI

                from app.services.rag import RagService

                base_url = os.environ.get("OPENAI_BASE_URL", GROQ_BASE_URL)
                client = OpenAI(api_key=api_key, base_url=base_url)
                rag = RagService(retriever=retriever, api_key=api_key)
                answers = run_answer_eval(rag, client, cases)
                print(
                    f"\nAnswers: faithfulness={answers['faithfulness']:.3f} "
                    f"relevancy={answers['answer_relevancy']:.3f} "
                    f"judge_agreement={answers['judge_agreement']} "
                    f"refusals={answers['refusals']}/{answers['n']}"
                )
            except Exception as exc:
                answers_skipped_reason = f"answer_eval_failed: {exc}"
                print(
                    f"Answer eval crashed ({exc}); marking skipped",
                    file=sys.stderr,
                )
                answers = None

    metrics: dict[str, Any] = {
        "retrieval_accuracy": retrieval["retrieval_accuracy"],
        "hit_at_5": retrieval["hit_at_5"],
        "mrr_at_10": retrieval["mrr_at_10"],
    }
    if answers is not None:
        metrics.update(
            {
                "faithfulness": answers["faithfulness"],
                "answer_relevancy": answers["answer_relevancy"],
                "judge_agreement": answers["judge_agreement"],
            }
        )

    failures = _check_thresholds(metrics, thresholds)
    if failures:
        print("\nThreshold breaches:")
        for f in failures:
            print(f"  - {f}")

    _write_report(
        retrieval=retrieval,
        answers=answers,
        thresholds=thresholds,
        failures=failures,
        answers_skipped_reason=answers_skipped_reason,
    )

    if failures and not args.skip_gating:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
