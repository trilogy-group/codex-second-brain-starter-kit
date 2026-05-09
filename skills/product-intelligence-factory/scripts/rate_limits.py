#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import threading
import time
from email.utils import parsedate_to_datetime
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback for local tests.
    fcntl = None  # type: ignore[assignment]


class RateLimitExceeded(RuntimeError):
    pass


class ProviderRateLimitError(RateLimitExceeded):
    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.headers = headers or {}


class RateLimitRecorder:
    def __init__(self, initial_events: list[dict[str, Any]] | None = None) -> None:
        self._events = list(initial_events or [])
        self._lock = threading.Lock()

    def record(self, **event: Any) -> None:
        with self._lock:
            self._events.append(
                {
                    "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    **event,
                }
            )

    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    if not value:
        return None
    trimmed = value.strip()
    try:
        seconds = float(trimmed)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(trimmed)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        seconds = (parsed - current).total_seconds()
    return max(0.0, round(seconds, 4))


def provider_rate_limit_from_http_error(exc: HTTPError) -> ProviderRateLimitError | None:
    if exc.code not in {429, 500, 502, 503, 504}:
        return None
    headers = {str(key): str(value) for key, value in exc.headers.items()}
    retry_after = parse_retry_after(headers.get("Retry-After") or headers.get("retry-after"))
    return ProviderRateLimitError(
        f"Provider returned HTTP {exc.code}; retry_after_seconds={retry_after if retry_after is not None else 'unavailable'}",
        retry_after_seconds=retry_after,
        headers=headers,
    )


class SharedBudget:
    def __init__(self, path: Path, config: dict[str, Any], *, recorder: RateLimitRecorder | None = None) -> None:
        self.path = path
        self.config = config
        self.recorder = recorder or RateLimitRecorder()
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"requests": 0, "tokens": 0, "estimated_cost_usd": 0.0}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RateLimitExceeded(f"Shared OpenAI budget file is invalid JSON: {self.path}") from exc
        return data if isinstance(data, dict) else {"requests": 0, "tokens": 0, "estimated_cost_usd": 0.0}

    def acquire(
        self,
        *,
        stage: str,
        worker_count: int,
        requests: int = 1,
        tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        recommended_knob: str = "openai_requests_per_minute",
    ) -> None:
        max_requests = int(self.config.get("max_openai_requests_per_budget_window", 0) or 0)
        max_tokens = int(self.config.get("max_openai_tokens_per_budget_window", 0) or 0)
        max_cost = float(self.config.get("max_openai_cost_usd_per_budget_window", 0) or 0)
        if max_requests <= 0 and max_tokens <= 0 and max_cost <= 0:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with self._lock, lock_path.open("a+", encoding="utf-8") as lock_handle:
            if fcntl is not None:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                state = self._load()
                next_requests = int(state.get("requests", 0) or 0) + max(0, requests)
                next_tokens = int(state.get("tokens", 0) or 0) + max(0, tokens)
                next_cost = float(state.get("estimated_cost_usd", 0) or 0) + max(0.0, estimated_cost_usd)
                exceeded = []
                if max_requests > 0 and next_requests > max_requests:
                    exceeded.append(f"requests {next_requests}/{max_requests}")
                if max_tokens > 0 and next_tokens > max_tokens:
                    exceeded.append(f"tokens {next_tokens}/{max_tokens}")
                if max_cost > 0 and next_cost > max_cost:
                    exceeded.append(f"estimated_cost_usd {next_cost:.6f}/{max_cost:.6f}")
                if exceeded:
                    self.recorder.record(
                        stage=stage,
                        event="budget_exceeded",
                        worker_count=worker_count,
                        recommended_knob=recommended_knob,
                        budget_path=str(self.path),
                        exceeded=", ".join(exceeded),
                    )
                    raise RateLimitExceeded(
                        f"{stage} exceeded shared OpenAI budget ({', '.join(exceeded)}). "
                        f"Lower {recommended_knob} or raise the configured budget."
                    )
                self.path.write_text(
                    json.dumps(
                        {
                            **state,
                            "requests": next_requests,
                            "tokens": next_tokens,
                            "estimated_cost_usd": round(next_cost, 8),
                            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def shared_budget_from_config(config: dict[str, Any], *, recorder: RateLimitRecorder | None = None) -> SharedBudget | None:
    configured = str(config.get("openai_budget_path") or os.environ.get("PRODUCT_BASB_OPENAI_BUDGET_PATH") or "").strip()
    if not configured:
        return None
    return SharedBudget(Path(configured).expanduser(), config, recorder=recorder)


class WindowRateLimiter:
    def __init__(
        self,
        config: dict[str, Any],
        *,
        recorder: RateLimitRecorder | None = None,
        window_seconds: float = 60.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.recorder = recorder or RateLimitRecorder()
        self.window_seconds = window_seconds
        self.sleeper = sleeper
        self._request_windows: dict[str, deque[float]] = defaultdict(deque)
        self._token_windows: dict[str, deque[tuple[float, int]]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, now: float, budget_key: str) -> None:
        request_window = self._request_windows[budget_key]
        while request_window and now - request_window[0] >= self.window_seconds:
            request_window.popleft()
        token_window = self._token_windows[budget_key]
        while token_window and now - token_window[0][0] >= self.window_seconds:
            token_window.popleft()

    def acquire(
        self,
        *,
        budget_key: str,
        request_limit: int,
        token_limit: int | None = None,
        tokens: int = 0,
        stage: str,
        worker_count: int,
        recommended_knob: str,
    ) -> float:
        if request_limit <= 0:
            raise RateLimitExceeded(f"{budget_key} request limit must be positive.")
        waited = 0.0
        start = time.monotonic()
        while True:
            with self._lock:
                now = time.monotonic()
                self._prune(now, budget_key)
                request_window = self._request_windows[budget_key]
                token_window = self._token_windows[budget_key]
                token_total = sum(value for _, value in token_window)
                request_allowed = len(request_window) < request_limit
                token_allowed = token_limit is None or token_total + tokens <= token_limit
                if request_allowed and token_allowed:
                    request_window.append(now)
                    if token_limit is not None:
                        token_window.append((now, tokens))
                    return waited
                request_wait = self.window_seconds - (now - request_window[0]) if request_window else 0.0
                token_wait = self.window_seconds - (now - token_window[0][0]) if token_window else 0.0
                wait_seconds = max(0.001, request_wait if not request_allowed else 0.0, token_wait if not token_allowed else 0.0)

            fail_fast_seconds = float(self.config.get("fail_fast_seconds", 120.0))
            if time.monotonic() - start + wait_seconds > fail_fast_seconds:
                raise RateLimitExceeded(
                    f"{stage} saturated {budget_key}; worker_count={worker_count}. Lower {recommended_knob} or raise fail_fast_seconds."
                )
            self.recorder.record(
                stage=stage,
                budget_key=budget_key,
                event="wait",
                wait_seconds=round(wait_seconds, 4),
                worker_count=worker_count,
                recommended_knob=recommended_knob,
            )
            self.sleeper(wait_seconds)
            waited += wait_seconds

    def acquire_openai(self, *, stage: str, worker_count: int, tokens: int = 0, recommended_knob: str) -> float:
        return self.acquire(
            budget_key="openai",
            request_limit=int(self.config.get("openai_requests_per_minute", 300)),
            token_limit=int(self.config.get("openai_tokens_per_minute", 200000)),
            tokens=max(1, tokens),
            stage=stage,
            worker_count=worker_count,
            recommended_knob=recommended_knob,
        )

    def acquire_source_fetch(self, *, host: str, stage: str, worker_count: int) -> float:
        return self.acquire(
            budget_key=f"source:{host or 'unknown'}",
            request_limit=int(self.config.get("source_fetch_requests_per_host_per_minute", 120)),
            token_limit=None,
            stage=stage,
            worker_count=worker_count,
            recommended_knob="source_fetch_workers",
        )


def with_retries(
    *,
    action: Callable[[], Any],
    config: dict[str, Any],
    recorder: RateLimitRecorder,
    stage: str,
    worker_count: int,
    recommended_knob: str,
) -> tuple[Any, int, float]:
    retry_attempts = int(config.get("retry_attempts", 3))
    retry_base = float(config.get("retry_base_seconds", 1.0))
    retry_max = float(config.get("retry_max_seconds", 30.0))
    total_wait = 0.0
    last_error: Exception | None = None
    for attempt in range(1, retry_attempts + 1):
        try:
            return action(), attempt - 1, total_wait
        except ProviderRateLimitError as exc:
            last_error = exc
            if attempt >= retry_attempts:
                break
            wait_seconds = min(retry_max, exc.retry_after_seconds if exc.retry_after_seconds is not None else retry_base * (2 ** (attempt - 1)))
            recorder.record(
                stage=stage,
                event="provider_retry_after",
                retry_attempt=attempt,
                wait_seconds=round(wait_seconds, 4),
                worker_count=worker_count,
                recommended_knob=recommended_knob,
                retry_after_seconds=exc.retry_after_seconds,
                provider_headers={
                    key: value
                    for key, value in exc.headers.items()
                    if key.lower().startswith(("retry-after", "x-ratelimit", "openai-"))
                },
            )
            time.sleep(wait_seconds)
            total_wait += wait_seconds
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= retry_attempts:
                break
            wait_seconds = min(retry_max, retry_base * (2 ** (attempt - 1)))
            recorder.record(
                stage=stage,
                event="retry",
                retry_attempt=attempt,
                wait_seconds=round(wait_seconds, 4),
                worker_count=worker_count,
                recommended_knob=recommended_knob,
                error_type=type(exc).__name__,
            )
            time.sleep(wait_seconds)
            total_wait += wait_seconds
    assert last_error is not None
    raise last_error


def load_rate_limit_inventory(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"events": [], "summary": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"events": [], "summary": {"load_error": "invalid-json"}}
    return data if isinstance(data, dict) else {"events": [], "summary": {"load_error": "invalid-shape"}}


def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    waits = [
        float(event.get("wait_seconds", 0) or 0)
        for event in events
        if event.get("event") in {"wait", "retry", "provider_retry_after"}
    ]
    return {
        "event_count": len(events),
        "wait_event_count": sum(1 for event in events if event.get("event") == "wait"),
        "retry_event_count": sum(1 for event in events if event.get("event") == "retry"),
        "provider_retry_after_count": sum(1 for event in events if event.get("event") == "provider_retry_after"),
        "budget_exceeded_count": sum(1 for event in events if event.get("event") == "budget_exceeded"),
        "total_wait_seconds": round(sum(waits), 4),
        "stages": sorted({str(event.get("stage")) for event in events if event.get("stage")}),
    }


def write_rate_limit_inventory(path: Path, *, config: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    inventory = {
        "schema_version": 1,
        "config": config,
        "summary": summarize_events(events),
        "events": events,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return inventory
