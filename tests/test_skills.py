from pathlib import Path

from work_agent.skills import SkillStore, skills_system_section, slugify
from work_agent.tools.base import ToolContext
from work_agent.tools.builtin.skills import SkillTool, SkillWriteTool


def test_slugify():
    assert slugify("Deploy to Prod!") == "deploy-to-prod"
    assert slugify("  ") == "skill"


def test_store_create_list_read_append(tmp_path: Path):
    store = SkillStore(tmp_path)
    store.create("Run Tests", "How to run the test suite", "Use pytest -q.")

    skills = store.list()
    assert len(skills) == 1
    assert skills[0].name == "Run Tests"
    assert skills[0].description == "How to run the test suite"

    skill = store.get("run tests")  # lookup is slug-insensitive
    assert skill is not None
    assert "pytest -q" in skill.body()

    store.append("Run Tests", "Correction: also run mypy first.")
    assert "mypy first" in store.get("Run Tests").body()


def test_store_create_duplicate_errors(tmp_path: Path):
    store = SkillStore(tmp_path)
    store.create("a", "d", "b")
    try:
        store.create("a", "d", "b")
        assert False, "expected FileExistsError"
    except FileExistsError:
        pass


def test_system_section_lists_skills(tmp_path: Path):
    assert "No skills exist yet" in skills_system_section(tmp_path)
    SkillStore(tmp_path).create("deploy", "How to deploy", "steps")
    section = skills_system_section(tmp_path)
    assert "deploy: How to deploy" in section
    assert "skill_write" in section


def test_skill_tools_end_to_end(tmp_path: Path):
    ctx = ToolContext(workdir=tmp_path, state_dir=tmp_path)
    write = SkillWriteTool()
    read = SkillTool()

    out = write.run(
        {"action": "create", "name": "lint", "description": "linting", "content": "run ruff"},
        ctx,
    )
    assert not out.is_error

    out = read.run({"action": "list"}, ctx)
    assert "lint" in out.content

    out = read.run({"action": "read", "name": "lint"}, ctx)
    assert "run ruff" in out.content

    out = write.run({"action": "append", "name": "lint", "content": "also run black"}, ctx)
    assert not out.is_error
    assert "also run black" in read.run({"action": "read", "name": "lint"}, ctx).content


def test_skill_read_unknown(tmp_path: Path):
    ctx = ToolContext(workdir=tmp_path, state_dir=tmp_path)
    out = SkillTool().run({"action": "read", "name": "nope"}, ctx)
    assert out.is_error
