from work_agent.context import (
    Compactor,
    SUMMARY_PREFIX,
    estimate_tokens,
    find_cut_index,
)
from work_agent.providers.base import LLMResponse, Message, ToolCall, ToolResult, Usage


def _turn(text: str) -> list[Message]:
    return [
        Message(role="user", text=text),
        Message(role="assistant", text="ok " + text),
    ]


def test_estimate_tokens_grows_with_content():
    small = [Message(role="user", text="hi")]
    big = [Message(role="user", text="x" * 4000)]
    assert estimate_tokens(big) > estimate_tokens(small)


def test_find_cut_index_snaps_to_user_boundary():
    history = [
        Message(role="user", text="a"),
        Message(role="assistant", text="", tool_calls=[ToolCall("t1", "bash", {})]),
        Message(role="tool", tool_results=[ToolResult("t1", "out")]),
        Message(role="assistant", text="done"),
        Message(role="user", text="b"),
        Message(role="assistant", text="done b"),
    ]
    # keep_recent=3 targets index 3 (assistant); must snap forward to the user at 4
    cut = find_cut_index(history, keep_recent=3)
    assert history[cut].role == "user"
    assert cut == 4


class _FakeProvider:
    def __init__(self):
        self.calls = 0

    def complete(self, system, messages, tools, stream=True):
        self.calls += 1
        return LLMResponse(text="SUMMARY", tool_calls=[], stop_reason="end_turn", usage=Usage())


def test_below_threshold_is_unchanged():
    provider = _FakeProvider()
    comp = Compactor(provider, threshold_tokens=10_000, keep_recent=4)
    history = _turn("hello")
    out, changed = comp.maybe_compact(history)
    assert changed is False
    assert out == history
    assert provider.calls == 0


def test_compacts_when_over_threshold():
    provider = _FakeProvider()
    comp = Compactor(provider, threshold_tokens=1, keep_recent=2)
    history: list[Message] = []
    for i in range(6):
        history += _turn(f"task {i}")

    out, changed = comp.maybe_compact(history)
    assert changed is True
    assert provider.calls == 1
    # First message is the summary; the rest is a verbatim tail starting at a user turn.
    assert out[0].role == "user"
    assert out[0].text.startswith(SUMMARY_PREFIX)
    assert "SUMMARY" in out[0].text
    assert out[1].role == "user"
    assert len(out) < len(history)
