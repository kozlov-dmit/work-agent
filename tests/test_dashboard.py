from pathlib import Path

from work_agent.config import Config
from work_agent.frontends.web import _DASHBOARD_HTML, create_app
from work_agent.metrics import MetricsStore
from work_agent.providers.base import Usage


def test_metrics_counters_and_snapshot(tmp_path):
    m = MetricsStore()
    m.configure(tmp_path)
    m.record_llm(Usage(input_tokens=100, output_tokens=20), ok=True)
    m.record_llm(None, ok=False)
    m.record_llm(Usage(input_tokens=5, output_tokens=5), ok=True, refusal=True)
    m.record_tool(ok=True)
    m.record_tool(ok=False)

    snap = m.snapshot()
    assert snap["tokens"]["input"] == 105
    assert snap["tokens"]["total"] == 130
    assert snap["llm"]["requests"] == 3
    assert snap["llm"]["failures"] == 1
    assert snap["llm"]["refusals"] == 1
    assert snap["llm"]["reliability"] == round(2 / 3, 4)
    assert snap["tools"] == {"calls": 2, "errors": 1}
    assert "available" in snap["system"]


def test_metrics_aggregate_across_stores(tmp_path):
    # Two MetricsStore instances on the same state dir stand in for two processes
    # (web / telegram / scheduler) sharing the volume.
    a = MetricsStore(); a.configure(tmp_path)
    b = MetricsStore(); b.configure(tmp_path)

    a.record_llm(Usage(input_tokens=10, output_tokens=5), ok=True)
    b.record_llm(Usage(input_tokens=20, output_tokens=10), ok=False)
    b.record_tool(ok=False)

    snap = a.snapshot()  # reading from either sees the combined totals
    assert snap["tokens"]["total"] == 45
    assert snap["llm"]["requests"] == 2
    assert snap["llm"]["failures"] == 1
    assert snap["tools"] == {"calls": 1, "errors": 1}


def test_config_update_from_allowlist():
    cfg = Config()
    cfg.update_from(
        {
            "default_profile": "development",
            "system_prompt_extra": "Always answer in Russian.",
            "effort": "xhigh",
            "max_iterations": 99,
            "permission_default": "allow",
            "profiles": {"search": {"provider": "deepseek", "model": "deepseek-chat"}},
            "compaction": {"enabled": False, "threshold_tokens": 12345},
            "workdir": "/etc",  # not in allowlist — must be ignored
        }
    )
    assert cfg.default_profile == "development"
    assert cfg.system_prompt_extra == "Always answer in Russian."
    assert cfg.effort == "xhigh"
    assert cfg.max_iterations == 99
    assert cfg.permission_default == "allow"
    assert cfg.profiles["search"]["model"] == "deepseek-chat"
    assert cfg.compaction_enabled is False
    assert cfg.compaction_threshold_tokens == 12345
    assert cfg.workdir == "/workspace"  # unchanged


def test_system_prompt_includes_extra(tmp_path: Path):
    from work_agent.agent import Agent
    from work_agent.permissions import PermissionPolicy, auto_allow
    from work_agent.tools import build_registry

    cfg = Config()
    cfg.system_prompt_extra = "ALWAYS_BE_TERSE"
    agent = Agent(
        provider=None,
        registry=build_registry([]),
        policy=PermissionPolicy("ask", {}, auto_allow),
        workdir=tmp_path,
        config=cfg,
        state_dir=tmp_path,
    )
    assert "ALWAYS_BE_TERSE" in agent.system_prompt()


def test_dashboard_routes_registered():
    app = create_app(Config())
    paths = {getattr(r, "path", None) for r in app.routes}
    assert {"/dashboard", "/api/metrics", "/api/config", "/api/schedules"} <= paths
    assert "work-agent" in _DASHBOARD_HTML


def test_dashboard_api_endpoints(tmp_path: Path):
    from fastapi.testclient import TestClient

    cfg = Config()
    cfg.workdir = str(tmp_path)
    cfg.source_path = str(tmp_path / "config.yaml")
    client = TestClient(create_app(cfg))

    assert client.get("/dashboard").status_code == 200
    assert set(client.get("/api/metrics").json()) >= {"tokens", "llm", "tools", "system"}

    # POST body must be accepted (regression: forward-ref annotations broke this).
    r = client.post("/api/config", json={"system_prompt_extra": "be terse", "effort": "low"})
    assert r.json()["status"] == "ok"
    assert cfg.system_prompt_extra == "be terse"

    r = client.post("/api/schedules", json={"cron": "0 9 * * *", "task": "news"})
    assert r.json()["status"] == "ok"
    tid = r.json()["id"]
    assert client.post(f"/api/schedules/{tid}/disable").json()["status"] == "ok"
    assert client.delete(f"/api/schedules/{tid}").json()["status"] == "ok"
    assert client.get("/api/schedules").json()["tasks"] == []
