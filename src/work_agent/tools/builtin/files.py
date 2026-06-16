"""File tools: read, write, edit, glob, grep — scoped to the working directory."""

from __future__ import annotations

import re
from pathlib import Path

from ..base import ToolContext, ToolOutput

_MAX_READ = 30_000


def _resolve(ctx: ToolContext, rel: str) -> Path:
    """Resolve a path and confine it to the workdir (no traversal escapes)."""
    workdir = ctx.workdir.resolve()
    target = (workdir / rel).resolve()
    if target != workdir and workdir not in target.parents:
        raise ValueError(f"Path escapes the working directory: {rel}")
    return target


class ReadTool:
    name = "read"
    description = "Read a UTF-8 text file from the working directory."
    input_schema = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Path relative to workdir."}},
        "required": ["path"],
    }
    parallel_safe = True

    def run(self, args: dict, ctx: ToolContext) -> ToolOutput:
        try:
            target = _resolve(ctx, args["path"])
            text = target.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError) as e:
            return ToolOutput(str(e), is_error=True)
        if len(text) > _MAX_READ:
            text = text[:_MAX_READ] + "\n... [truncated]"
        return ToolOutput(text)


class WriteTool:
    name = "write"
    description = "Create or overwrite a text file in the working directory."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to workdir."},
            "content": {"type": "string", "description": "Full file content to write."},
        },
        "required": ["path", "content"],
    }
    parallel_safe = False

    def run(self, args: dict, ctx: ToolContext) -> ToolOutput:
        try:
            target = _resolve(ctx, args["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args["content"], encoding="utf-8")
        except (OSError, ValueError) as e:
            return ToolOutput(str(e), is_error=True)
        return ToolOutput(f"Wrote {len(args['content'])} bytes to {args['path']}")


class EditTool:
    name = "edit"
    description = "Replace an exact string in a file (old_string must be unique)."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
        },
        "required": ["path", "old_string", "new_string"],
    }
    parallel_safe = False

    def run(self, args: dict, ctx: ToolContext) -> ToolOutput:
        try:
            target = _resolve(ctx, args["path"])
            text = target.read_text(encoding="utf-8")
        except (OSError, ValueError) as e:
            return ToolOutput(str(e), is_error=True)
        count = text.count(args["old_string"])
        if count == 0:
            return ToolOutput("old_string not found", is_error=True)
        if count > 1:
            return ToolOutput(f"old_string is not unique ({count} matches)", is_error=True)
        target.write_text(text.replace(args["old_string"], args["new_string"]), encoding="utf-8")
        return ToolOutput(f"Edited {args['path']}")


class GlobTool:
    name = "glob"
    description = "Find files matching a glob pattern (e.g. '**/*.py')."
    input_schema = {
        "type": "object",
        "properties": {"pattern": {"type": "string"}},
        "required": ["pattern"],
    }
    parallel_safe = True

    def run(self, args: dict, ctx: ToolContext) -> ToolOutput:
        matches = sorted(str(p.relative_to(ctx.workdir)) for p in ctx.workdir.glob(args["pattern"]))
        return ToolOutput("\n".join(matches) if matches else "(no matches)")


class GrepTool:
    name = "grep"
    description = "Search file contents by regex across the working directory."
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regular expression."},
            "glob": {"type": "string", "description": "File glob to limit search (default '**/*')."},
        },
        "required": ["pattern"],
    }
    parallel_safe = True

    def run(self, args: dict, ctx: ToolContext) -> ToolOutput:
        try:
            regex = re.compile(args["pattern"])
        except re.error as e:
            return ToolOutput(f"Invalid regex: {e}", is_error=True)
        glob = args.get("glob", "**/*")
        hits: list[str] = []
        for path in ctx.workdir.glob(glob):
            if not path.is_file():
                continue
            try:
                for i, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if regex.search(line):
                        hits.append(f"{path.relative_to(ctx.workdir)}:{i}:{line}")
                        if len(hits) >= 200:
                            break
            except OSError:
                continue
            if len(hits) >= 200:
                break
        return ToolOutput("\n".join(hits) if hits else "(no matches)")
