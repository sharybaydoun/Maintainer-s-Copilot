#!/usr/bin/env python3
"""Build RAG corpus copies and semantic chunks from project documentation."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "rag_corpus"
CHUNKS_DIR = ROOT / "rag_chunks"
CHUNKS_PATH = CHUNKS_DIR / "chunks.json"

MAX_CHUNK_CHARS = 800
CHUNK_OVERLAP = 120

SOURCE_FILES = [
    ROOT / "README.md",
    ROOT / "DECISIONS.md",
    ROOT / "models/bert_tiny_classifier/MODEL_CARD.md",
]

REPORT_PATTERNS = ("*.md", "*.json")


def chunk_id(source: str, section: str, index: int, text: str) -> str:
    digest = hashlib.sha256(f"{source}:{section}:{index}:{text[:80]}".encode()).hexdigest()
    return digest[:16]


def split_long_text(text: str, max_chars: int, overlap: int) -> list[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []

    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        parts.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, 0)
    return [part for part in parts if part]


def chunk_markdown(source_name: str, content: str) -> list[dict]:
    chunks: list[dict] = []
    sections = re.split(r"^(#{1,3})\s+(.+)$", content, flags=re.MULTILINE)

    if len(sections) <= 1:
        for index, part in enumerate(split_long_text(content, MAX_CHUNK_CHARS, CHUNK_OVERLAP)):
            chunks.append(
                {
                    "chunk_id": chunk_id(source_name, "document", index, part),
                    "source": source_name,
                    "text": part,
                    "section": "document",
                }
            )
        return chunks

    prefix = sections[0].strip()
    if prefix:
        for index, part in enumerate(split_long_text(prefix, MAX_CHUNK_CHARS, CHUNK_OVERLAP)):
            chunks.append(
                {
                    "chunk_id": chunk_id(source_name, "introduction", index, part),
                    "source": source_name,
                    "text": part,
                    "section": "introduction",
                }
            )

    index = 1
    while index < len(sections):
        _hashes, title, body = sections[index], sections[index + 1], sections[index + 2]
        section_name = title.strip()
        body_text = body.strip()
        for part_index, part in enumerate(
            split_long_text(body_text, MAX_CHUNK_CHARS, CHUNK_OVERLAP)
        ):
            chunks.append(
                {
                    "chunk_id": chunk_id(source_name, section_name, part_index, part),
                    "source": source_name,
                    "text": part,
                    "section": section_name,
                }
            )
        index += 3

    return chunks


def chunk_json_report(source_name: str, content: str) -> list[dict]:
    """Flatten JSON reports into short text chunks for retrieval."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return chunk_markdown(source_name, content)

    lines = [f"Report: {source_name}"]
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict) and "macro_f1" in value:
                lines.append(
                    f"{key}: accuracy={value.get('accuracy')}, macro_f1={value.get('macro_f1')}"
                )
            elif key == "test" and isinstance(value, dict):
                lines.append(
                    f"test accuracy={value.get('accuracy')}, macro_f1={value.get('macro_f1')}"
                )
            else:
                lines.append(f"{key}: {json.dumps(value)[:400]}")
    text = "\n".join(lines)
    return chunk_markdown(source_name, text)


def copy_sources() -> list[Path]:
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    reports_dir = CORPUS_DIR / "reports"
    reports_dir.mkdir(exist_ok=True)

    copied: list[Path] = []
    for path in SOURCE_FILES:
        if not path.is_file():
            continue
        dest = CORPUS_DIR / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        copied.append(dest)

    reports_src = ROOT / "reports"
    if reports_src.is_dir():
        for pattern in REPORT_PATTERNS:
            for path in sorted(reports_src.glob(pattern)):
                dest = reports_dir / path.name
                shutil.copy2(path, dest)
                copied.append(dest)

    return copied


def build_chunks(corpus_files: list[Path]) -> list[dict]:
    all_chunks: list[dict] = []
    for path in corpus_files:
        content = path.read_text(encoding="utf-8")
        source_name = str(path.relative_to(CORPUS_DIR))
        if path.suffix == ".json":
            all_chunks.extend(chunk_json_report(source_name, content))
        else:
            all_chunks.extend(chunk_markdown(source_name, content))
    return all_chunks


def main() -> None:
    corpus_files = copy_sources()
    if not corpus_files:
        raise SystemExit("No corpus files found to ingest.")

    chunks = build_chunks(corpus_files)
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    CHUNKS_PATH.write_text(json.dumps(chunks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Copied {len(corpus_files)} files to {CORPUS_DIR}")
    print(f"Wrote {len(chunks)} chunks to {CHUNKS_PATH}")


if __name__ == "__main__":
    main()
