"""Shell command execution, scoped to the working directory."""

from __future__ import annotations

import subprocess

from ..base import ToolContext, ToolOutput

_MAX_OUTPUT = 30_000


class BashTool:
    name = "bash"
    description = (
        "Run a bash command inside the agent's container. Use for builds, tests, "
        "git, package managers, and any shell action. Output is truncated if large."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The bash command to execute."},
            "timeout": {
                "type": "integer",
                "description": "Max seconds before the command is killed (default 120).",
            },
        },
        "required": ["command"],
    }
    parallel_safe = False

    def run(self, args: dict, ctx: ToolContext) -> ToolOutput:
        command = args["command"]
        timeout = int(args.get("timeout", 120))
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(ctx.workdir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolOutput(f"Command timed out after {timeout}s", is_error=True)

        out = (proc.stdout or "") + (proc.stderr or "")
        if len(out) > _MAX_OUTPUT:
            out = out[:_MAX_OUTPUT] + "\n... [output truncated]"
        body = out or "(no output)"
        return ToolOutput(f"exit={proc.returncode}\n{body}", is_error=proc.returncode != 0)
