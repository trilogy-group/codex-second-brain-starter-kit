#!/usr/bin/env python3
from __future__ import annotations

import os
import ssl
import urllib.request
from pathlib import Path
from typing import Any, Callable

try:
    import certifi
except ImportError:  # pragma: no cover - certifi is bundled in normal Codex runtimes.
    certifi = None  # type: ignore[assignment]


def _existing_file(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return str(path) if path.exists() else None


def ca_bundle_path() -> str | None:
    explicit = _existing_file(os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE"))
    if explicit:
        return explicit
    paths = ssl.get_default_verify_paths()
    default_cafile = _existing_file(getattr(paths, "cafile", None)) or _existing_file(getattr(paths, "openssl_cafile", None))
    if default_cafile:
        return default_cafile
    if certifi is None:
        return None
    try:
        return _existing_file(certifi.where())
    except Exception:
        return None


def ssl_context() -> ssl.SSLContext:
    cafile = ca_bundle_path()
    return ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()


def urlopen(
    request: urllib.request.Request,
    *,
    timeout: float,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> Any:
    context = ssl_context()
    try:
        return opener(request, timeout=timeout, context=context)
    except TypeError:
        # Tests and some custom opener callables intentionally accept only the
        # urllib-compatible subset used before CA fallback support existed.
        return opener(request, timeout=timeout)
