from pathlib import Path

from work_agent.config import Config
from work_agent.provisioning import Provisioning
from work_agent.tools import build_registry
from work_agent.tools.base import ToolContext
from work_agent.tools.builtin.selfmanage import ConfigureTool, InstallTool


def test_provisioning_records_and_dedupes(tmp_path: Path):
    prov = Provisioning(tmp_path)
    prov.record("pip", ["requests", "rich"])
    prov.record("pip", ["requests", "httpx"])  # requests is a dup
    prov.record("apt", ["jq"])

    manifest = prov.load()
    assert manifest["pip"] == ["requests", "rich", "httpx"]
    assert manifest["apt"] == ["jq"]
    assert manifest["npm"] == []


def test_config_save_load_roundtrip(tmp_path: Path):
    cfg = Config()
    cfg.model = "claude-opus-4-8"
    cfg.enabled_tools = ["read", "bash"]
    cfg.permission_overrides = {"bash": "deny"}
    target = tmp_path / "config.yaml"
    cfg.save(str(target))

    loaded = Config.load(str(target))
    assert loaded.model == "claude-opus-4-8"
    assert loaded.enabled_tools == ["read", "bash"]
    assert loaded.permission_overrides == {"bash": "deny"}


def test_configure_enables_tool_live_and_persists(tmp_path: Path):
    cfg = Config()
    cfg.enabled_tools = ["read"]
    cfg.source_path = str(tmp_path / "config.yaml")
    registry = build_registry(cfg.enabled_tools)
    ctx = ToolContext(workdir=tmp_path, state_dir=tmp_path, config=cfg, registry=registry)

    out = ConfigureTool().run({"action": "enable_tool", "tool": "glob"}, ctx)
    assert not out.is_error
    # Live: registry now has the tool.
    assert registry.get("glob") is not None
    # Persisted: config file and in-memory config updated.
    assert "glob" in cfg.enabled_tools
    assert Config.load(cfg.source_path).enabled_tools == cfg.enabled_tools


def test_configure_disable_tool(tmp_path: Path):
    cfg = Config()
    cfg.enabled_tools = ["read", "glob"]
    cfg.source_path = str(tmp_path / "config.yaml")
    registry = build_registry(cfg.enabled_tools)
    ctx = ToolContext(workdir=tmp_path, state_dir=tmp_path, config=cfg, registry=registry)

    out = ConfigureTool().run({"action": "disable_tool", "tool": "glob"}, ctx)
    assert not out.is_error
    assert registry.get("glob") is None
    assert "glob" not in cfg.enabled_tools


def test_configure_set_rejects_unknown_key(tmp_path: Path):
    cfg = Config()
    cfg.source_path = str(tmp_path / "config.yaml")
    ctx = ToolContext(workdir=tmp_path, state_dir=tmp_path, config=cfg, registry=None)
    out = ConfigureTool().run({"action": "set", "key": "secret", "value": "x"}, ctx)
    assert out.is_error


def test_install_tool_rejects_unknown_manager(tmp_path: Path):
    ctx = ToolContext(workdir=tmp_path, state_dir=tmp_path)
    out = InstallTool().run({"manager": "brew", "packages": ["x"]}, ctx)
    assert out.is_error
