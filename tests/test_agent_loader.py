from __future__ import annotations

import textwrap
from pathlib import Path

from code_agent.agents.loader import AgentDef, AgentLoader, parse_agent_file


class TestParseAgentFile:
    def test_basic(self) -> None:
        text = textwrap.dedent("""\
        ---
        name: explore
        description: 快速搜索代码
        tools: list_files, read_file, search_text
        maxTurns: 5
        ---

        你是代码搜索专家。
        """)
        agent = parse_agent_file(text)
        assert agent is not None
        assert agent.name == "explore"
        assert agent.description == "快速搜索代码"
        assert agent.tools == ["list_files", "read_file", "search_text"]
        assert agent.max_turns == 5
        assert "代码搜索专家" in agent.system_prompt

    def test_list_tools(self) -> None:
        text = textwrap.dedent("""\
        ---
        name: reviewer
        description: 审查代码
        tools:
          - read_file
          - search_text
        disallowed_tools:
          - run_command
        ---

        审查。
        """)
        agent = parse_agent_file(text)
        assert agent is not None
        assert agent.tools == ["read_file", "search_text"]
        assert agent.disallowed_tools == ["run_command"]

    def test_no_frontmatter(self) -> None:
        assert parse_agent_file("just plain text") is None

    def test_no_name(self) -> None:
        text = textwrap.dedent("""\
        ---
        description: missing name
        ---

        body
        """)
        assert parse_agent_file(text) is None

    def test_defaults(self) -> None:
        text = textwrap.dedent("""\
        ---
        name: minimal
        ---

        minimal agent
        """)
        agent = parse_agent_file(text)
        assert agent is not None
        assert agent.max_turns == 8
        assert agent.tools == []
        assert agent.model == ""

    def test_skills_field(self) -> None:
        text = textwrap.dedent("""\
        ---
        name: skillful
        description: uses skills
        skills: brainstorming, refactoring
        ---

        body
        """)
        agent = parse_agent_file(text)
        assert agent is not None
        assert agent.skills == ["brainstorming", "refactoring"]


class TestAgentLoader:
    def test_list_from_directory(self, tmp_path: Path) -> None:
        agent_md = tmp_path / "explore.md"
        agent_md.write_text(textwrap.dedent("""\
        ---
        name: explore
        description: 搜索代码
        ---

        搜索。
        """), encoding="utf-8")

        loader = AgentLoader(tmp_path)
        agents = loader.list_agents()
        assert len(agents) == 1
        assert agents[0].name == "explore"

    def test_multi_dir_priority(self, tmp_path: Path) -> None:
        d1 = tmp_path / "personal"
        d1.mkdir()
        d2 = tmp_path / "project"
        d2.mkdir()

        (d1 / "explore.md").write_text(textwrap.dedent("""\
        ---
        name: explore
        description: 个人版本
        ---

        个人。
        """), encoding="utf-8")

        (d2 / "explore.md").write_text(textwrap.dedent("""\
        ---
        name: explore
        description: 项目版本
        ---

        项目。
        """), encoding="utf-8")

        loader = AgentLoader(d1, d2)
        agents = loader.list_agents()
        assert len(agents) == 1
        assert agents[0].description == "个人版本"

    def test_get_agent(self, tmp_path: Path) -> None:
        (tmp_path / "reviewer.md").write_text(textwrap.dedent("""\
        ---
        name: reviewer
        description: 代码审查
        ---

        审查。
        """), encoding="utf-8")

        loader = AgentLoader(tmp_path)
        assert loader.get_agent("reviewer") is not None
        assert loader.get_agent("nonexist") is None

    def test_empty_dir(self, tmp_path: Path) -> None:
        loader = AgentLoader(tmp_path)
        assert loader.list_agents() == []

    def test_nonexistent_dir(self) -> None:
        loader = AgentLoader(Path("/nonexistent/path"))
        assert loader.list_agents() == []

    def test_bundled_agents_exist(self) -> None:
        from code_agent.agents.loader import BUNDLED_AGENTS_DIR
        assert BUNDLED_AGENTS_DIR.exists()
        loader = AgentLoader(BUNDLED_AGENTS_DIR)
        agents = loader.list_agents()
        names = {a.name for a in agents}
        assert "explore" in names
        assert "reviewer" in names
        assert "planner" in names
