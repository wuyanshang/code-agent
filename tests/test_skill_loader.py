from pathlib import Path

from code_agent.skills.loader import SkillLoader, parse_frontmatter, render_skill_content


def test_skill_loader_lists_and_reads(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# demo\n\ncontent", encoding="utf-8")

    loader = SkillLoader(tmp_path / "skills")
    items = loader.list_skills()
    assert len(items) == 1
    assert items[0].name == "demo"
    assert "content" in loader.read_skill("demo")


def test_frontmatter_parsing() -> None:
    text = (
        "---\n"
        "name: code-review\n"
        "description: Review code for issues\n"
        "allowed-tools: Read, Grep, Glob\n"
        "disable-model-invocation: true\n"
        "argument-hint: <file>\n"
        "---\n"
        "\n"
        "Review the code in $ARGUMENTS for bugs.\n"
    )
    meta, body = parse_frontmatter(text)
    assert meta is not None
    assert meta.name == "code-review"
    assert meta.description == "Review code for issues"
    assert meta.allowed_tools == ["Read", "Grep", "Glob"]
    assert meta.disable_model_invocation is True
    assert meta.argument_hint == "<file>"
    assert "$ARGUMENTS" in body


def test_frontmatter_list_skills_uses_meta(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: custom-name\ndescription: A custom skill\n---\nBody here.",
        encoding="utf-8",
    )

    loader = SkillLoader(tmp_path / "skills")
    items = loader.list_skills()
    assert len(items) == 1
    assert items[0].name == "custom-name"
    assert items[0].preview == "A custom skill"
    assert items[0].meta is not None
    assert items[0].meta.name == "custom-name"


def test_render_skill_content_arguments() -> None:
    body = "Fix issue $ARGUMENTS following standards."
    result = render_skill_content(body, "123")
    assert "Fix issue 123 following standards." == result


def test_render_skill_content_indexed() -> None:
    body = "Migrate $0 from $1 to $2."
    result = render_skill_content(body, "SearchBar React Vue")
    assert result == "Migrate SearchBar from React to Vue."


def test_render_skill_content_appends_if_no_placeholder() -> None:
    body = "Do the thing."
    result = render_skill_content(body, "extra args")
    assert "ARGUMENTS: extra args" in result


def test_render_skill_content_empty_args() -> None:
    body = "Do the thing with $ARGUMENTS."
    result = render_skill_content(body, "")
    assert "Do the thing with ." == result


def test_multi_dir_skill_loader(tmp_path: Path) -> None:
    personal = tmp_path / "personal"
    project = tmp_path / "project"

    (personal / "shared").mkdir(parents=True)
    (personal / "shared" / "SKILL.md").write_text("personal version", encoding="utf-8")

    (personal / "personal-only").mkdir(parents=True)
    (personal / "personal-only" / "SKILL.md").write_text("personal skill", encoding="utf-8")

    (project / "shared").mkdir(parents=True)
    (project / "shared" / "SKILL.md").write_text("project version", encoding="utf-8")

    (project / "project-only").mkdir(parents=True)
    (project / "project-only" / "SKILL.md").write_text("project skill", encoding="utf-8")

    loader = SkillLoader(personal, project)
    items = loader.list_skills()
    names = {s.name for s in items}
    assert names == {"shared", "personal-only", "project-only"}

    content = loader.read_skill("shared")
    assert "personal version" in content
