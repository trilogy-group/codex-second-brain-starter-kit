#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_CREDENTIAL_RE = re.compile(r"(https?://)([^/\s@]+)@")
PRIVATE_IP_RE = re.compile(
    r"\b(?:10(?:\.\d{1,3}){3}|172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}|192\.168(?:\.\d{1,3}){2})\b"
)
STANDALONE_NAME_RE = re.compile(r"^(?:\s*(?:- |## ))([A-Z][a-z]+(?: [A-Z][a-z]+){1,2})\s*$")
AUTHOR_CONTEXT_TERMS = {"posted", "comments", "author"}
NAME_STOPLIST = {
    "Full Article Content",
    "Full Wiki Content",
    "Platform Core",
    "Feature Overview",
    "Frequently Asked Questions",
    "How It Works",
    "Welcome Email",
    "Challenge Digest",
    "Best Practices",
    "Notify Product",
    "Community Components",
    "Open Signup",
    "Challenge Notification Email",
    "Inactive Members Email",
    "Authentication Flow",
    "First Name",
    "Last Name",
    "Privacy Policy",
    "Setup Instructions",
    "Click Save",
    "Message Notification Email",
    "Forgot Password Email",
    "Advocacy Insights",
    "Support To Code Map",
}


def detect_likely_person_names(markdown_paths: list[Path]) -> set[str]:
    counts: Counter[str] = Counter()
    for path in markdown_paths:
        lines = path.read_text(errors="ignore").splitlines()
        for index, line in enumerate(lines):
            match = STANDALONE_NAME_RE.match(line)
            if not match:
                continue
            candidate = match.group(1)
            if candidate in NAME_STOPLIST:
                continue
            window = " ".join(lines[max(0, index - 3) : min(len(lines), index + 4)]).lower()
            if not any(term in window for term in AUTHOR_CONTEXT_TERMS):
                continue
            counts[candidate] += 1
    return {name for name, count in counts.items() if count >= 2}


def sanitize_markdown_text(text: str, person_names: set[str]) -> str:
    sanitized = text
    sanitized = URL_CREDENTIAL_RE.sub(r"\1[REDACTED_CREDENTIALS]@", sanitized)
    sanitized = EMAIL_RE.sub("[REDACTED_EMAIL]", sanitized)
    sanitized = PRIVATE_IP_RE.sub("[REDACTED_PRIVATE_IP]", sanitized)
    for name in sorted(person_names, key=len, reverse=True):
        sanitized = re.sub(rf"\b{re.escape(name)}\b", "[REDACTED_PERSON]", sanitized)
    return sanitized


def sanitize_vault_markdown(vault_path: Path) -> dict[str, int]:
    markdown_paths = sorted(vault_path.rglob("*.md"))
    person_names = detect_likely_person_names(markdown_paths)
    changed_files = 0
    for path in markdown_paths:
        original = path.read_text(errors="ignore")
        sanitized = sanitize_markdown_text(original, person_names)
        if sanitized == original:
            continue
        path.write_text(sanitized)
        changed_files += 1
    return {
        "files_scanned": len(markdown_paths),
        "files_changed": changed_files,
        "person_names_redacted": len(person_names),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sanitize PII and credentials from generated Obsidian markdown notes.")
    parser.add_argument("--vault", required=True, type=Path)
    args = parser.parse_args()
    summary = sanitize_vault_markdown(args.vault.expanduser())
    print(summary)


if __name__ == "__main__":
    main()
