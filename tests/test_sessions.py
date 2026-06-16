from pathlib import Path

from work_agent.providers.base import Message, ToolCall, ToolResult
from work_agent.sessions import SessionStore, from_jsonable, to_jsonable


def _sample_history() -> list[Message]:
    return [
        Message(role="user", text="build a script"),
        Message(
            role="assistant",
            text="Working on it",
            tool_calls=[ToolCall(id="t1", name="bash", arguments={"command": "ls"})],
        ),
        Message(
            role="tool",
            tool_results=[ToolResult(tool_call_id="t1", content="file.py", is_error=False)],
        ),
        Message(role="assistant", text="Done."),
    ]


def test_serialization_roundtrip():
    history = _sample_history()
    restored = from_jsonable(to_jsonable(history))
    assert restored == history


def test_store_save_load_clear(tmp_path: Path):
    store = SessionStore(tmp_path)
    sid = "telegram-42"

    assert store.load(sid) == []  # nothing yet

    store.save(sid, _sample_history())
    loaded = store.load(sid)
    assert len(loaded) == 4
    assert loaded[1].tool_calls[0].name == "bash"
    assert loaded[2].tool_results[0].content == "file.py"

    store.clear(sid)
    assert store.load(sid) == []


def test_session_id_cannot_escape_dir(tmp_path: Path):
    store = SessionStore(tmp_path)
    store.save("../../evil", [Message(role="user", text="x")])
    # The file stays inside the sessions directory.
    written = list((tmp_path / "sessions").glob("*.json"))
    assert len(written) == 1
    assert written[0].parent == tmp_path / "sessions"
