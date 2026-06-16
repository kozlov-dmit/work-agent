"""Tools for using and authoring skills (reusable task instructions)."""

from __future__ import annotations

from pathlib import Path

from ..base import ToolContext, ToolOutput


def _skills_dir(ctx: ToolContext) -> Path:
    base = ctx.state_dir or (ctx.workdir / ".work-agent")
    return base / "skills"


class SkillTool:
    name = "skill"
    description = (
        "Use skills (reusable task instructions). Actions: 'list' shows available "
        "skills with descriptions; 'read' returns the full instructions of one "
        "skill. Read a skill before doing a task it covers."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "read"]},
            "name": {"type": "string", "description": "Skill name for 'read'."},
        },
        "required": ["action"],
    }
    parallel_safe = True

    def run(self, args: dict, ctx: ToolContext) -> ToolOutput:
        from ...skills import SkillStore

        store = SkillStore(_skills_dir(ctx))
        action = args["action"]

        if action == "list":
            skills = store.list()
            if not skills:
                return ToolOutput("(no skills yet)")
            return ToolOutput("\n".join(f"{s.name}: {s.description}" for s in skills))

        if action == "read":
            name = args.get("name")
            if not name:
                return ToolOutput("'name' is required for read", is_error=True)
            skill = store.get(name)
            if skill is None:
                return ToolOutput(f"Unknown skill: {name}", is_error=True)
            return ToolOutput(f"# {skill.name}\n{skill.description}\n\n{skill.body()}")

        return ToolOutput(f"Unknown action: {action}", is_error=True)


class SkillWriteTool:
    name = "skill_write"
    description = (
        "Author skills. Actions: 'create' a new skill (name, description, content); "
        "'append' a correction or note to an existing skill (name, content); 'edit' "
        "replaces an exact string in a skill (name, old_string, new_string). Use this "
        "to capture user corrections and reusable procedures so you improve over time."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "append", "edit"]},
            "name": {"type": "string"},
            "description": {"type": "string", "description": "Short summary, for 'create'."},
            "content": {"type": "string", "description": "Body for 'create' / 'append'."},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
        },
        "required": ["action", "name"],
    }
    parallel_safe = False

    def run(self, args: dict, ctx: ToolContext) -> ToolOutput:
        from ...skills import SkillStore

        store = SkillStore(_skills_dir(ctx))
        action = args["action"]
        name = args["name"]

        try:
            if action == "create":
                store.create(name, args.get("description", ""), args.get("content", ""))
                return ToolOutput(f"Created skill '{name}'.")
            if action == "append":
                content = args.get("content", "").strip()
                if not content:
                    return ToolOutput("'content' is required for append", is_error=True)
                store.append(name, content)
                return ToolOutput(f"Appended to skill '{name}'.")
            if action == "edit":
                store.edit(name, args.get("old_string", ""), args.get("new_string", ""))
                return ToolOutput(f"Edited skill '{name}'.")
        except (FileExistsError, FileNotFoundError, ValueError) as e:
            return ToolOutput(str(e), is_error=True)

        return ToolOutput(f"Unknown action: {action}", is_error=True)
