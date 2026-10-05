#!/usr/bin/env python3
"""One-shot verification service.

Runs after the API reports healthy and then, in order:

1. waits for ``GET /health`` (compose also gates this service on health)
2. build sanity check: byte-compilation plus importing the application stack
3. the repository's pytest suite
4. HTTP smoke tests for a consistent chain (exact coefficients/results),
   a contradictory chain (``conflict`` naming instruments, no usable values),
   and an unreachable pair (``unreachable``)

Exits 0 only when every step succeeds; any failure yields a non-zero exit code
so Docker Compose can report it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000")
HEALTH_URL = f"{API_BASE_URL}/health"
TRANSLATE_URL = f"{API_BASE_URL}/api/calibrations/translate"


def report(name: str, ok: bool, detail: str = "") -> bool:
    marker = "PASS" if ok else "FAIL"
    print(f"[{marker}] {name}" + (f" -- {detail}" if detail and not ok else ""))
    if detail and ok:
        print(f"       {detail}")
    return ok


def wait_for_health(timeout_seconds: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    last_error = "not started"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=2) as response:
                body = json.load(response)
            if response.status == 200 and body.get("status") == "ok":
                return True
            last_error = f"unexpected body: {body!r}"
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        time.sleep(1)
    print(f"[FAIL] health check did not become ready: {last_error}")
    return False


def build_check() -> bool:
    print("== build sanity: compileall + import ==")
    compile_proc = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "app", "scripts", "tests"]
    )
    if compile_proc.returncode != 0:
        return False
    import_proc = subprocess.run(
        [sys.executable, "-c", "import fastapi, uvicorn, app.main; print('imports ok')"],
    )
    return import_proc.returncode == 0


def run_tests() -> bool:
    print("== pytest suite ==")
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q"])
    return proc.returncode == 0


def post_json(payload: dict) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        TRANSLATE_URL, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def smoke_consistent_chain() -> bool:
    print("== smoke: consistent chain A -> B -> C ==")
    payload = {
        "instruments": ["A", "B", "C"],
        "relations": [
            {"source": "A", "target": "B", "a": "2", "b": "1"},
            {"source": "B", "target": "C", "a": "3", "b": "4"},
            # redundant but consistent path; the answer must not depend on it
            {"source": "A", "target": "C", "a": "6", "b": "7"},
        ],
        "source": "A",
        "target": "C",
        "readings": ["0", "1", "1/3"],
    }
    status, body = post_json(payload)
    ok = status == 200
    ok = report("consistent chain returns 200", ok, f"status={status} body={body}") and ok
    expected_coefficients = {"a": "6", "b": "7"}  # 3*(2x+1)+4 = 6x+7
    ok = (
        report(
            "exact reduced-fraction coefficients",
            body.get("coefficients") == expected_coefficients,
            str(body.get("coefficients")),
        )
        and ok
    )
    # 6*(1/3)+7 = 9 exactly; no floating point appears
    ok = report(
        "exact conversion results",
        body.get("results") == ["7", "13", "9"],
        str(body.get("results")),
    ) and ok
    return ok


def smoke_conflicting_chain() -> bool:
    print("== smoke: contradictory cycle A-B-C-A ==")
    payload = {
        "instruments": ["A", "B", "C"],
        "relations": [
            {"source": "A", "target": "B", "a": "2", "b": "1"},
            {"source": "B", "target": "C", "a": "3", "b": "4"},
            {"source": "A", "target": "C", "a": "6", "b": "8"},  # must be 6x+7
        ],
        "source": "A",
        "target": "C",
        "readings": ["1"],
    }
    status, body = post_json(payload)
    ok = status == 409
    ok = report("contradiction returns 409", ok, f"status={status} body={body}") and ok
    ok = (
        report("error code is 'conflict'", body.get("error") == "conflict", str(body.get("error")))
        and ok
    )
    instruments = set(body.get("instruments") or [])
    ok = (
        report(
            "conflict names involved instruments",
            {"A", "B", "C"}.issubset(instruments),
            str(sorted(instruments)),
        )
        and ok
    )
    ok = (
        report("no usable coefficients or results returned", "results" not in body and "coefficients" not in body)
        and ok
    )
    return ok


def smoke_unreachable() -> bool:
    print("== smoke: disconnected source/target ==")
    payload = {
        "instruments": ["A", "B", "X"],
        "relations": [{"source": "A", "target": "B", "a": "2", "b": "0"}],
        "source": "A",
        "target": "X",
        "readings": ["1"],
    }
    status, body = post_json(payload)
    ok = status == 404 and body.get("error") == "unreachable"
    return report("disconnected pair returns identifiable unreachable error", ok, f"status={status} body={body}")


def main() -> int:
    steps = [
        ("wait for API health", wait_for_health),
        ("build sanity check", build_check),
        ("code tests", run_tests),
        ("smoke: consistent chain", smoke_consistent_chain),
        ("smoke: contradictory chain", smoke_conflicting_chain),
        ("smoke: unreachable pair", smoke_unreachable),
    ]
    failures: list[str] = []
    for name, step in steps:
        if not step():
            failures.append(name)

    print()
    if failures:
        print(f"VERIFY FAILED ({len(failures)} step(s)): {', '.join(failures)}")
        return 1
    print("VERIFY OK: tests, build, and all API smoke checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
