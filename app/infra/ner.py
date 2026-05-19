from __future__ import annotations

import re

FILENAME_PATTERN = re.compile(
    r"\b[\w./-]+\.(?:py|pyi|ipynb|md|rst|txt|json|ya?ml|toml|csv|ini|cfg)\b",
    re.IGNORECASE,
)
URL_PATTERN = re.compile(r"https?://[^\s\)\]>\"']+")
STACK_FILE_PATTERN = re.compile(
    r'File "([^"]+)", line (\d+)(?:, in ([A-Za-z_][\w]*)?)?'
)
STACK_ERROR_PATTERN = re.compile(
    r"^([A-Za-z_][\w.]*(?:Error|Exception)):\s*(.+)$", re.MULTILINE
)
DEF_FUNCTION_PATTERN = re.compile(r"\bdef\s+([A-Za-z_][\w]*)\s*\(")
CALL_PATTERN = re.compile(r"\b([A-Za-z_][\w]*)\s*\(\)")
BACKTICK_CODE_PATTERN = re.compile(r"`([^`\n]+)`")


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def extract_entities(text: str) -> dict[str, list[str]]:
    filenames = _unique(FILENAME_PATTERN.findall(text))
    urls = _unique(URL_PATTERN.findall(text))

    functions: list[str] = []
    functions.extend(DEF_FUNCTION_PATTERN.findall(text))
    functions.extend(CALL_PATTERN.findall(text))
    functions = _unique(functions)

    stack_trace: list[str] = []
    for match in STACK_FILE_PATTERN.finditer(text):
        location = match.group(3) or "unknown"
        stack_trace.append(
            f'File "{match.group(1)}", line {match.group(2)}, in {location}'
        )
    stack_trace.extend(
        _unique(f"{error}: {message}" for error, message in STACK_ERROR_PATTERN.findall(text))
    )
    stack_trace = _unique(stack_trace)

    code_tokens: list[str] = []
    for token in BACKTICK_CODE_PATTERN.findall(text):
        cleaned = token.strip()
        if cleaned and len(cleaned) <= 120:
            code_tokens.append(cleaned)
    code_tokens = _unique(code_tokens)

    return {
        "filenames": filenames,
        "functions": functions,
        "urls": urls,
        "stack_trace": stack_trace,
        "code_tokens": code_tokens,
    }
