from pathlib import Path

from work_agent.tools import build_registry
from work_agent.tools.base import ToolContext


def test_registry_only_enables_requested_tools():
    registry = build_registry(["read", "glob"])
    assert registry.names() == ["glob", "read"]
    assert registry.get("bash") is None


def test_specs_are_provider_agnostic():
    registry = build_registry(["read"])
    specs = registry.specs()
    assert specs[0].name == "read"
    assert specs[0].input_schema["type"] == "object"


def test_read_write_roundtrip(tmp_path: Path):
    registry = build_registry(["read", "write"])
    ctx = ToolContext(workdir=tmp_path)

    write = registry.get("write")
    out = write.run({"path": "hello.txt", "content": "hi"}, ctx)
    assert not out.is_error

    read = registry.get("read")
    out = read.run({"path": "hello.txt"}, ctx)
    assert out.content == "hi"


def test_path_traversal_is_blocked(tmp_path: Path):
    registry = build_registry(["read"])
    ctx = ToolContext(workdir=tmp_path)
    out = registry.get("read").run({"path": "../escape.txt"}, ctx)
    assert out.is_error
