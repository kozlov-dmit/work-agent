"""Skills: reusable, task-specific instructions the agent can read and write.

Each skill is a folder with a ``SKILL.md`` file carrying YAML frontmatter
(``name``, ``description``) and a markdown body. Descriptions are surfaced in the
system prompt; the full body is loaded on demand (progressive disclosure). The
agent can create new skills and append corrections to existing ones, so it
improves from user feedback across sessions.

Skills live under the persistent state directory, so they survive container
recreation when ``/workspace`` is a volume.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_SKILL_FILE = "SKILL.md"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "skill"


@dataclass
class Skill:
    name: str
    description: str
    path: Path

    def body(self) -> str:
        text = self.path.read_text(encoding="utf-8")
        _, body = _split_frontmatter(text)
        return body


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            meta = yaml.safe_load(parts[1]) or {}
            return (meta if isinstance(meta, dict) else {}), parts[2].lstrip("\n")
    return {}, text


def _render(name: str, description: str, body: str) -> str:
    front = yaml.safe_dump({"name": name, "description": description}, sort_keys=False).strip()
    return f"---\n{front}\n---\n\n{body.rstrip()}\n"


class SkillStore:
    def __init__(self, skills_dir: Path) -> None:
        self.dir = Path(skills_dir)

    def list(self) -> list[Skill]:
        if not self.dir.exists():
            return []
        skills: list[Skill] = []
        for child in sorted(self.dir.iterdir()):
            md = child / _SKILL_FILE
            if not md.is_file():
                continue
            meta, _ = _split_frontmatter(md.read_text(encoding="utf-8"))
            skills.append(
                Skill(
                    name=meta.get("name", child.name),
                    description=meta.get("description", ""),
                    path=md,
                )
            )
        return skills

    def get(self, name: str) -> Skill | None:
        md = self.dir / slugify(name) / _SKILL_FILE
        if not md.is_file():
            return None
        meta, _ = _split_frontmatter(md.read_text(encoding="utf-8"))
        return Skill(meta.get("name", name), meta.get("description", ""), md)

    def create(self, name: str, description: str, body: str) -> Skill:
        slug = slugify(name)
        md = self.dir / slug / _SKILL_FILE
        if md.exists():
            raise FileExistsError(f"Skill '{name}' already exists; append or edit it instead.")
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(_render(name, description, body), encoding="utf-8")
        return Skill(name, description, md)

    def append(self, name: str, content: str) -> Skill:
        skill = self.get(name)
        if skill is None:
            raise FileNotFoundError(f"Skill '{name}' does not exist; create it first.")
        text = skill.path.read_text(encoding="utf-8")
        meta, body = _split_frontmatter(text)
        new_body = f"{body.rstrip()}\n\n{content.strip()}\n"
        skill.path.write_text(
            _render(meta.get("name", name), meta.get("description", ""), new_body),
            encoding="utf-8",
        )
        return skill

    def edit(self, name: str, old_string: str, new_string: str) -> Skill:
        skill = self.get(name)
        if skill is None:
            raise FileNotFoundError(f"Skill '{name}' does not exist.")
        text = skill.path.read_text(encoding="utf-8")
        count = text.count(old_string)
        if count == 0:
            raise ValueError("old_string not found")
        if count > 1:
            raise ValueError(f"old_string is not unique ({count} matches)")
        skill.path.write_text(text.replace(old_string, new_string), encoding="utf-8")
        return skill


def skills_system_section(skills_dir: Path) -> str:
    """The '## Skills' block injected into the system prompt each turn."""
    skills = SkillStore(skills_dir).list()
    if skills:
        listing = "Available skills:\n" + "\n".join(
            f"- {s.name}: {s.description}" for s in skills
        )
    else:
        listing = "No skills exist yet."
    return (
        "\n\n## Skills\n"
        "Skills are reusable, task-specific instructions stored across sessions.\n"
        f"{listing}\n"
        "When a task matches a skill, call the `skill` tool (action 'read') to load "
        "its full instructions before acting. When the user corrects you, teaches a "
        "procedure, or you find a reusable approach, persist it with `skill_write` — "
        "create a new skill, or append the correction to an existing one — so you "
        "improve over time."
    )
