#!/usr/bin/env python3
from __future__ import annotations

import os
import ssl
import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable
from hashlib import sha256

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
    certifi_cafile = None
    if certifi is not None:
        try:
            certifi_cafile = _existing_file(certifi.where())
        except Exception:
            certifi_cafile = None
    if certifi_cafile:
        return certifi_cafile
    paths = ssl.get_default_verify_paths()
    default_cafile = _existing_file(getattr(paths, "cafile", None)) or _existing_file(getattr(paths, "openssl_cafile", None))
    if default_cafile:
        return default_cafile
    try:
        return _existing_file(certifi.where()) if certifi is not None else None
    except Exception:
        return None


def ssl_context() -> ssl.SSLContext:
    cafile = ca_bundle_path()
    return ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()


class _GatewayResponse:
    def __init__(self, payload: bytes, headers: dict[str, str] | None = None):
        self._payload = payload
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_GatewayResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _request_url(request: urllib.request.Request) -> str:
    return str(getattr(request, "full_url", "") or request.get_full_url())


def _is_openai_provider_request(request: urllib.request.Request) -> bool:
    return _request_url(request) in {
        "https://api.openai.com/v1/responses",
        "https://api.openai.com/v1/embeddings",
    }


def _request_json_payload(request: urllib.request.Request) -> dict[str, Any]:
    data = getattr(request, "data", None)
    if not data:
        return {}
    if isinstance(data, str):
        raw = data
    else:
        raw = bytes(data).decode("utf-8", errors="replace")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("OpenAI provider request body must be a JSON object.")
    return parsed


def _gateway_env() -> tuple[str, str] | None:
    base_url = os.environ.get("TYLER_PROVIDER_GATEWAY_BASE_URL", "").strip().rstrip("/")
    token = os.environ.get("TYLER_PROVIDER_GATEWAY_TOKEN", "").strip()
    if not base_url or not token:
        return None
    return base_url, token


def _gateway_api_json(
    *,
    path: str,
    token: str,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    base_url = os.environ.get("TYLER_PROVIDER_GATEWAY_BASE_URL", "").strip().rstrip("/")
    payload = json.dumps(body or {}).encode("utf-8")
    provider_request = urllib.request.Request(
        f"{base_url}{path}",
        data=payload if body is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(provider_request, timeout=timeout, context=ssl_context()) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not isinstance(parsed, dict):
        raise RuntimeError("Tyler provider gateway returned a non-object response.")
    return parsed


def _provider_gateway_urlopen(request: urllib.request.Request, *, timeout: float) -> _GatewayResponse | None:
    gateway = _gateway_env()
    if gateway is None or not _is_openai_provider_request(request):
        return None
    _base_url, token = gateway
    request_payload = _request_json_payload(request)
    product_id = os.environ.get("TYLER_PROVIDER_GATEWAY_PRODUCT_ID")
    product_slug = os.environ.get("TYLER_PROVIDER_GATEWAY_PRODUCT_SLUG")
    job_run_id = os.environ.get("TYLER_PROVIDER_GATEWAY_JOB_RUN_ID")
    digest_payload = {
        "url": _request_url(request),
        "payload": request_payload,
        "product_id": product_id,
        "product_slug": product_slug,
        "job_run_id": job_run_id,
    }
    idempotency_key = "starter_kit_openai_http:" + sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    created = _gateway_api_json(
        path="/api/internal/provider-tasks",
        token=token,
        body={
            "product_id": int(product_id) if product_id and product_id.isdigit() else None,
            "product_slug": product_slug or None,
            "job_run_id": int(job_run_id) if job_run_id and job_run_id.isdigit() else None,
            "operation": "openai_http",
            "provider": "openai",
            "idempotency_key": idempotency_key,
            "payload": {
                "url": _request_url(request),
                "json": request_payload,
                "timeout_seconds": timeout,
            },
        },
    )
    task = created.get("task") if isinstance(created.get("task"), dict) else {}
    task_id = int(task.get("id") or 0)
    if task_id <= 0:
        raise RuntimeError("Tyler provider gateway did not return a task id.")
    poll_seconds = max(0.25, float(os.environ.get("TYLER_PROVIDER_GATEWAY_POLL_SECONDS") or "2"))
    wait_timeout = max(timeout, float(os.environ.get("TYLER_PROVIDER_GATEWAY_WAIT_TIMEOUT_SECONDS") or "3600"))
    started_at = time.monotonic()
    while True:
        current = _gateway_api_json(path=f"/api/internal/provider-tasks/{task_id}", token=token)
        current_task = current.get("task") if isinstance(current.get("task"), dict) else {}
        status = str(current_task.get("status") or "")
        if status == "succeeded":
            result = current.get("result") if isinstance(current.get("result"), dict) else {}
            body_json = result.get("body_json")
            if isinstance(body_json, dict):
                return _GatewayResponse(
                    json.dumps(body_json).encode("utf-8"),
                    headers={str(key): str(value) for key, value in (result.get("provider_headers") or {}).items()},
                )
            body_text = result.get("body_text")
            if isinstance(body_text, str):
                return _GatewayResponse(body_text.encode("utf-8"))
            raise RuntimeError("Tyler provider gateway task succeeded without a response body.")
        if status == "failed":
            raise RuntimeError(str(current_task.get("error_message") or "Tyler provider gateway task failed."))
        if time.monotonic() - started_at > wait_timeout:
            raise TimeoutError(f"Timed out waiting for Tyler provider gateway task {task_id}.")
        time.sleep(poll_seconds)


def urlopen(
    request: urllib.request.Request,
    *,
    timeout: float,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> Any:
    gateway_response = _provider_gateway_urlopen(request, timeout=timeout)
    if gateway_response is not None:
        return gateway_response
    context = ssl_context()
    try:
        return opener(request, timeout=timeout, context=context)
    except TypeError:
        # Tests and some custom opener callables intentionally accept only the
        # urllib-compatible subset used before CA fallback support existed.
        return opener(request, timeout=timeout)
