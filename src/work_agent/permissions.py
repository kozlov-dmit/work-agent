"""Permission policy gating tool execution."""

from __future__ import annotations

from typing import Callable

ALLOW = "allow"
ASK = "ask"
DENY = "deny"


class PermissionPolicy:
    """Decides whether a tool may run: allow / ask / deny.

    ``ask`` defers to ``confirm``, an injected callback (interactive prompt in
    the CLI, auto-allow in ``--yolo`` / autonomous mode).
    """

    def __init__(
        self,
        default: str,
        overrides: dict[str, str],
        confirm: Callable[[str, dict], bool],
    ) -> None:
        self._default = default
        self._overrides = overrides
        self._confirm = confirm

    def allowed(self, tool_name: str, args: dict) -> bool:
        decision = self._overrides.get(tool_name, self._default)
        if decision == ALLOW:
            return True
        if decision == DENY:
            return False
        return self._confirm(tool_name, args)


def auto_allow(_name: str, _args: dict) -> bool:
    return True
