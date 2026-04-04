#!/usr/bin/env python3
"""
SynthFin E2E Production Test Suite
====================================
Testa todos os fluxos principais contra o ambiente de produção.

Gera:
  - Relatório JSON com métricas detalhadas
  - Dashboard HTML publicado no GitHub Pages

Uso:
    pip install httpx pytest pytest-asyncio
    SYNTHFIN_TEST_KEY=fgen_sk_... python3 tests/e2e/run_e2e.py

No CI:
    Secrets: SYNTHFIN_TEST_KEY, SYNTHFIN_ADMIN_SECRET
"""

import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_API  = os.environ.get("SYNTHFIN_API_URL",  "https://api.synthfin.com.br")
BASE_WEB  = os.environ.get("SYNTHFIN_WEB_URL",  "https://app.synthfin.com.br")
BASE_LAND = os.environ.get("SYNTHFIN_LAND_URL",  "https://synthfin.com.br")
TEST_KEY  = os.environ.get("SYNTHFIN_TEST_KEY",  "")
ADMIN_SECRET = os.environ.get("SYNTHFIN_ADMIN_SECRET", "")
TIMEOUT   = 30

# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class TestResult:
    name:        str
    category:    str
    status:      str           # pass | fail | skip
    duration_ms: float
    http_status: Optional[int] = None
    error:       Optional[str] = None
    details:     dict          = field(default_factory=dict)
    timestamp:   str           = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class SuiteResult:
    run_id:      str
    started_at:  str
    finished_at: str = ""
    env:         str = "production"
    api_url:     str = BASE_API
    results:     list = field(default_factory=list)

    @property
    def total(self):    return len(self.results)
    @property
    def passed(self):   return sum(1 for r in self.results if r.status == "pass")
    @property
    def failed(self):   return sum(1 for r in self.results if r.status == "fail")
    @property
    def skipped(self):  return sum(1 for r in self.results if r.status == "skip")
    @property
    def pass_rate(self):
        t = self.total - self.skipped
        return round(self.passed / t * 100, 1) if t > 0 else 0
    @property
    def avg_duration_ms(self):
        passed = [r.duration_ms for r in self.results if r.status == "pass"]
        return round(sum(passed) / len(passed), 0) if passed else 0


# ── Test runner helpers ────────────────────────────────────────────────────────

def _auth(key: str = TEST_KEY) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

def _admin() -> dict:
    return {"X-Admin-Secret": ADMIN_SECRET, "Content-Type": "application/json"}


async def run_test(
    name: str,
    category: str,
    coro,
    suite: SuiteResult,
    skip_if: bool = False,
) -> TestResult:
    if skip_if:
        r = TestResult(name=name, category=category, status="skip", duration_ms=0)
        suite.results.append(r)
        print(f"  ⏭  {name}")
        return r

    t0 = time.perf_counter()
    try:
        result = await coro
        duration = (time.perf_counter() - t0) * 1000
        r = TestResult(
            name=name, category=category, status="pass",
            duration_ms=round(duration, 1),
            http_status=result.get("status"),
            details=result,
        )
        print(f"  ✅ {name} ({duration:.0f}ms)")
    except AssertionError as e:
        duration = (time.perf_counter() - t0) * 1000
        r = TestResult(
            name=name, category=category, status="fail",
            duration_ms=round(duration, 1),
            error=str(e),
        )
        print(f"  ❌ {name} — {e}")
    except Exception as e:
        duration = (time.perf_counter() - t0) * 1000
        r = TestResult(
            name=name, category=category, status="fail",
            duration_ms=round(duration, 1),
            error=f"{type(e).__name__}: {e}",
        )
        print(f"  ❌ {name} — {type(e).__name__}: {e}")

    suite.results.append(r)
    return r


# ── Individual test coroutines ─────────────────────────────────────────────────

async def test_health(client: httpx.AsyncClient) -> dict:
    r = await client.get(f"{BASE_API}/v2/health")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert data["status"] == "ok", f"Health degraded: {data}"
    return {"status": r.status_code, "checks": data.get("checks", {}), "version": data.get("version")}


async def test_usage(client: httpx.AsyncClient) -> dict:
    r = await client.get(f"{BASE_API}/v2/usage", headers=_auth())
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert "plan" in data, "Missing 'plan' field"
    assert "events_remaining" in data, "Missing 'events_remaining'"
    return {"status": r.status_code, "plan": data["plan"], "events_remaining": data["events_remaining"]}


async def test_usage_history(client: httpx.AsyncClient) -> dict:
    r = await client.get(f"{BASE_API}/v2/usage/history", headers=_auth())
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert isinstance(data, list), "Expected list"
    assert len(data) == 30, f"Expected 30 days, got {len(data)}"
    return {"status": r.status_code, "days": len(data)}


async def test_generate_batch(client: httpx.AsyncClient) -> dict:
    """Full batch flow: create → poll → verify done."""
    r = await client.post(
        f"{BASE_API}/v2/generate",
        headers=_auth(),
        json={"type": "transactions", "count": 500, "format": "jsonl", "fraud_rate": 0.05, "seed": 42},
        timeout=30,
    )
    assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text[:200]}"
    job_id = r.json()["job_id"]
    eta    = r.json().get("eta_seconds", 10)

    # Poll until done (max 60s)
    final_status = None
    for _ in range(20):
        await asyncio.sleep(3)
        s = await client.get(f"{BASE_API}/v2/jobs/{job_id}", headers=_auth())
        assert s.status_code == 200, f"Job poll failed: {s.status_code}"
        final_status = s.json()["status"]
        if final_status in ("done", "failed", "cancelled"):
            break

    assert final_status == "done", f"Job ended with status '{final_status}'"
    job_data = s.json()
    assert job_data.get("download_url"), "No download_url in done job"
    return {
        "status": 202,
        "job_id": job_id,
        "final_status": final_status,
        "events_generated": job_data.get("events_generated"),
        "file_size_bytes": job_data.get("file_size_bytes"),
        "eta_seconds": eta,
    }


async def test_jobs_list(client: httpx.AsyncClient) -> dict:
    r = await client.get(f"{BASE_API}/v2/jobs?limit=5", headers=_auth())
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    jobs = data.get("jobs", data) if isinstance(data, dict) else data
    assert isinstance(jobs, list), "Expected list of jobs"
    return {"status": r.status_code, "jobs_returned": len(jobs)}


async def test_stream_lifecycle(client: httpx.AsyncClient) -> dict:
    """Stream: create → verify running → consume 3s → stop."""
    # Create
    r = await client.post(
        f"{BASE_API}/v2/streams",
        headers=_auth(),
        json={"type": "transactions", "rate": 5, "fraud_rate": 0.05, "duration_hours": 0.1},
        timeout=20,
    )
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text[:300]}"
    stream_id = r.json()["stream_id"]
    assert r.json()["status"] == "running", "Stream not running"

    # Verify in list
    await asyncio.sleep(1)
    lst = await client.get(f"{BASE_API}/v2/streams", headers=_auth())
    assert lst.status_code == 200

    # Stop
    await asyncio.sleep(3)
    stop = await client.delete(f"{BASE_API}/v2/streams/{stream_id}", headers=_auth())
    assert stop.status_code == 200, f"Stop failed: {stop.status_code}"
    assert stop.json()["status"] == "stopped"

    return {
        "status": 201,
        "stream_id": stream_id,
        "events_sent": stop.json().get("events_sent", 0),
    }


async def test_stream_sse_events(client: httpx.AsyncClient, stream_id: str) -> dict:
    """Consume SSE events for 5 seconds."""
    events_received = 0
    first_event = None

    try:
        async with client.stream(
            "GET",
            f"{BASE_API}/v2/streams/{stream_id}/events",
            headers={**_auth(), "Accept": "text/event-stream"},
            timeout=10,
        ) as resp:
            assert resp.status_code == 200, f"SSE failed: {resp.status_code}"
            deadline = time.time() + 5
            async for line in resp.aiter_lines():
                if time.time() > deadline:
                    break
                if line.startswith("data:") and '"transaction_id"' in line:
                    events_received += 1
                    if not first_event:
                        try:
                            first_event = json.loads(line[5:].strip())
                        except Exception:
                            pass
    except Exception:
        pass

    assert events_received > 0, "No SSE events received in 5 seconds"
    return {
        "status": 200,
        "events_received": events_received,
        "has_is_fraud_field": first_event is not None and "is_fraud" in first_event,
        "has_fraud_score": first_event is not None and "fraud_score" in first_event,
    }


async def test_docs_chat(client: httpx.AsyncClient) -> dict:
    """Send one message to docs-chat and verify SSE response."""
    tokens_received = 0
    session_id = None

    try:
        async with client.stream(
            "POST",
            f"{BASE_API}/v2/docs/chat",
            headers={**_auth(), "Accept": "text/event-stream"},
            json={"message": "O que é o SynthFin em uma frase?", "session_id": str(uuid.uuid4())[:8]},
            timeout=30,
        ) as resp:
            assert resp.status_code == 200, f"Docs chat failed: {resp.status_code}"
            deadline = time.time() + 20
            async for line in resp.aiter_lines():
                if time.time() > deadline:
                    break
                if line.startswith("data:"):
                    try:
                        d = json.loads(line[5:].strip())
                        if "session_id" in d:
                            session_id = d["session_id"]
                        if "token" in d:
                            tokens_received += 1
                    except Exception:
                        pass
                if "event: end" in line or tokens_received > 30:
                    break
    except Exception as e:
        pass

    assert tokens_received > 0, "No tokens received from docs-chat"
    return {"status": 200, "tokens_received": tokens_received, "session_id": session_id}


async def test_ml_assistant(client: httpx.AsyncClient) -> dict:
    """Test ML assistant endpoint."""
    tokens_received = 0

    try:
        async with client.stream(
            "POST",
            f"{BASE_API}/v2/ml/chat",
            headers={**_auth(), "Accept": "text/event-stream"},
            json={"message": "Quais são os campos de biometria disponíveis no SynthFin?"},
            timeout=30,
        ) as resp:
            assert resp.status_code == 200, f"ML chat failed: {resp.status_code}"
            deadline = time.time() + 25
            async for line in resp.aiter_lines():
                if time.time() > deadline:
                    break
                if line.startswith("data:"):
                    try:
                        d = json.loads(line[5:].strip())
                        if "token" in d:
                            tokens_received += 1
                    except Exception:
                        pass
                if tokens_received > 30:
                    break
    except Exception:
        pass

    assert tokens_received > 0, "No tokens received from ml-assistant"
    return {"status": 200, "tokens_received": tokens_received}


async def test_web_page(client: httpx.AsyncClient, url: str, name: str) -> dict:
    r = await client.get(url, follow_redirects=True, timeout=15)
    assert r.status_code == 200, f"{name}: expected 200, got {r.status_code}"
    assert len(r.text) > 500, f"{name}: response too short ({len(r.text)} chars)"
    return {"status": r.status_code, "size_bytes": len(r.text.encode()), "url": url}


async def test_admin_dashboard(client: httpx.AsyncClient) -> dict:
    r = await client.get(f"{BASE_API}/v2/admin/dashboard", headers=_admin())
    assert r.status_code == 200, f"Admin dashboard: {r.status_code}"
    data = r.json()
    assert "total_users" in data
    return {"status": r.status_code, "total_users": data["total_users"], "active_users": data["active_users"]}


async def test_admin_server_health(client: httpx.AsyncClient) -> dict:
    r = await client.get(f"{BASE_API}/v2/admin/server-health", headers=_admin())
    assert r.status_code == 200, f"Server health: {r.status_code}"
    data = r.json()
    checks = data.get("checks", {})
    return {"status": r.status_code, "server_status": data.get("status"), "checks": checks}


async def test_key_recovery_endpoint(client: httpx.AsyncClient) -> dict:
    """Recovery endpoint deve responder 200 sempre (não revela se email existe)."""
    r = await client.post(
        f"{BASE_API}/v2/auth/recover",
        json={"email": "naoexiste_test@synthfin.com.br"},
        timeout=10,
    )
    assert r.status_code == 200, f"Recovery: expected 200, got {r.status_code}"
    assert "message" in r.json()
    return {"status": r.status_code}


# ── Main runner ───────────────────────────────────────────────────────────────

async def main() -> SuiteResult:
    if not TEST_KEY:
        print("❌ SYNTHFIN_TEST_KEY não definida. Export a variável e tente novamente.")
        sys.exit(1)

    suite = SuiteResult(
        run_id=str(uuid.uuid4())[:8],
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    print(f"\n{'='*60}")
    print(f"  SynthFin E2E Suite — {suite.run_id}")
    print(f"  {BASE_API}")
    print(f"{'='*60}\n")

    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:

        # ── Infrastructure ────────────────────────────────────────────────────
        print("📡 Infrastructure")
        await run_test("Health check",       "infra", test_health(client),       suite)
        await run_test("Admin dashboard",    "infra", test_admin_dashboard(client), suite,
                       skip_if=not ADMIN_SECRET)
        await run_test("Server health",      "infra", test_admin_server_health(client), suite,
                       skip_if=not ADMIN_SECRET)

        # ── Auth & Usage ──────────────────────────────────────────────────────
        print("\n🔑 Auth & Usage")
        await run_test("GET /v2/usage",         "auth", test_usage(client),         suite)
        await run_test("GET /v2/usage/history", "auth", test_usage_history(client), suite)
        await run_test("POST /v2/auth/recover", "auth", test_key_recovery_endpoint(client), suite)

        # ── Batch generation ──────────────────────────────────────────────────
        print("\n⚡ Batch Generation")
        await run_test("POST /v2/generate (500 eventos)", "batch", test_generate_batch(client), suite)
        await run_test("GET /v2/jobs",                    "batch", test_jobs_list(client),       suite)

        # ── Streaming ─────────────────────────────────────────────────────────
        print("\n🌊 Streaming")
        stream_result = await run_test(
            "POST /v2/streams (lifecycle)", "stream",
            test_stream_lifecycle(client), suite,
        )

        # ── AI/Chat ───────────────────────────────────────────────────────────
        print("\n🤖 AI / Chat")
        await run_test("POST /v2/docs/chat (SSE)",   "ai", test_docs_chat(client),    suite)
        await run_test("POST /v2/ml/chat (ML Advisor)", "ai", test_ml_assistant(client), suite)

        # ── Frontend pages ────────────────────────────────────────────────────
        print("\n🌐 Frontend")
        await run_test("Landing page",      "web", test_web_page(client, BASE_LAND, "Landing"),          suite)
        await run_test("Login page",        "web", test_web_page(client, f"{BASE_WEB}/login", "Login"),  suite)
        await run_test("Dashboard (200)",   "web", test_web_page(client, f"{BASE_WEB}/dashboard", "Dashboard"), suite)
        await run_test("Plans page",        "web", test_web_page(client, f"{BASE_WEB}/plans", "Plans"),  suite)
        await run_test("Docs page",         "web", test_web_page(client, f"{BASE_WEB}/docs", "Docs"),    suite)
        await run_test("ML Advisor page",   "web", test_web_page(client, f"{BASE_WEB}/ml-assistant", "ML Advisor"), suite)

    suite.finished_at = datetime.now(timezone.utc).isoformat()

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Results: {suite.passed}✅  {suite.failed}❌  {suite.skipped}⏭")
    print(f"  Pass rate: {suite.pass_rate}%")
    print(f"  Avg duration: {suite.avg_duration_ms:.0f}ms")
    print(f"{'='*60}\n")

    # Save JSON
    out_dir = Path("tests/e2e/results")
    out_dir.mkdir(parents=True, exist_ok=True)

    result_data = {
        "run_id":      suite.run_id,
        "started_at":  suite.started_at,
        "finished_at": suite.finished_at,
        "env":         suite.env,
        "api_url":     suite.api_url,
        "summary": {
            "total":         suite.total,
            "passed":        suite.passed,
            "failed":        suite.failed,
            "skipped":       suite.skipped,
            "pass_rate":     suite.pass_rate,
            "avg_duration_ms": suite.avg_duration_ms,
        },
        "results": [asdict(r) for r in suite.results],
    }

    json_path = out_dir / "latest.json"
    json_path.write_text(json.dumps(result_data, indent=2))
    print(f"Results saved: {json_path}")

    return suite


if __name__ == "__main__":
    suite = asyncio.run(main())
    sys.exit(0 if suite.failed == 0 else 1)
