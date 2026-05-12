from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ---------- shell execution in skill body ----------
# 支持两种语法（与 claude-code 一致）：
#   代码块：  ```!\n<cmd>\n```
#   内联：    !`<cmd>`
_SHELL_BLOCK_RE = re.compile(r"```!\s*\n([\s\S]*?)\n?```", re.MULTILINE)
_SHELL_INLINE_RE = re.compile(r"(?:^|\s)!`([^`]+)`")


def _run_shell(command: str, cwd: Path | None = None) -> str:
    """在 skill 加载时执行内嵌 shell 命令并返回 stdout。"""
    if sys.platform == "win32":
        import shutil
        ps = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
        argv = [ps, "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        import shutil
        sh = shutil.which("bash") or shutil.which("sh") or "sh"
        argv = [sh, "-c", command]
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            timeout=15,
            check=False,
        )
        stdout = proc.stdout.decode("utf-8", errors="replace").strip()
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0 and stderr:
            return f"[shell error: {stderr}]"
        return stdout
    except Exception as exc:
        return f"[shell error: {exc}]"


def execute_shell_in_skill(body: str, skill_dir: Path | None = None) -> str:
    """替换 skill body 中所有内嵌 shell 命令为其输出。"""
    # 代码块：```!\ncmd\n```
    def _replace_block(m: re.Match[str]) -> str:
        cmd = m.group(1).strip()
        return _run_shell(cmd, skill_dir) if cmd else ""

    body = _SHELL_BLOCK_RE.sub(_replace_block, body)

    # 内联：!`cmd`
    def _replace_inline(m: re.Match[str]) -> str:
        cmd = m.group(1).strip()
        prefix = m.group(0)[0] if m.group(0)[0] != "!" else ""
        return prefix + (_run_shell(cmd, skill_dir) if cmd else "")

    body = _SHELL_INLINE_RE.sub(_replace_inline, body)
    return body


@dataclass(slots=True)
class SkillMeta:
    """Parsed YAML frontmatter of a SKILL.md file."""
    name: str
    description: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    disable_model_invocation: bool = False
    user_invocable: bool = True
    context: str = ""  # "fork" for subagent execution
    model: str = ""
    argument_hint: str = ""


@dataclass(slots=True)
class SkillSummary:
    name: str
    path: Path
    preview: str
    meta: SkillMeta | None = None


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_ARG_N_RE = re.compile(r"\$ARGUMENTS\[(\d+)]|\$(\d+)")


def parse_frontmatter(text: str) -> tuple[SkillMeta | None, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None, text

    raw_yaml = m.group(1)
    body = text[m.end():]

    try:
        data = yaml.safe_load(raw_yaml) or {}
    except yaml.YAMLError:
        return None, text

    if not isinstance(data, dict):
        return None, text

    allowed_raw = data.get("allowed-tools") or data.get("allowed_tools") or ""
    if isinstance(allowed_raw, str):
        allowed = [t.strip() for t in allowed_raw.split(",") if t.strip()]
    elif isinstance(allowed_raw, list):
        allowed = [str(t).strip() for t in allowed_raw]
    else:
        allowed = []

    meta = SkillMeta(
        name=str(data.get("name", "")),
        description=str(data.get("description", "")),
        allowed_tools=allowed,
        disable_model_invocation=bool(data.get("disable-model-invocation", False)),
        user_invocable=bool(data.get("user-invocable", True)),
        context=str(data.get("context", "")),
        model=str(data.get("model", "")),
        argument_hint=str(data.get("argument-hint", "")),
    )
    return meta, body


def render_skill_content(body: str, arguments: str) -> str:
    arg_list = arguments.split() if arguments else []
    has_indexed = bool(_ARG_N_RE.search(body))
    has_full = "$ARGUMENTS" in body

    def _replace_indexed(m: re.Match[str]) -> str:
        idx_str = m.group(1) or m.group(2)
        idx = int(idx_str)
        return arg_list[idx] if idx < len(arg_list) else ""

    result = _ARG_N_RE.sub(_replace_indexed, body)

    if has_full:
        result = result.replace("$ARGUMENTS", arguments)
    elif arguments and not has_indexed:
        result += f"\n\nARGUMENTS: {arguments}"

    return result


class SkillLoader:
    def __init__(self, *skill_dirs: Path) -> None:
        self.skill_dirs = list(skill_dirs)

    def list_skills(self, include_bundled: bool = True) -> list[SkillSummary]:
        """列出skills

        Args:
            include_bundled: 是否包含bundled skills（默认True）
        """
        seen: set[str] = set()
        items: list[SkillSummary] = []

        # 如果不包含bundled，只遍历前面的目录（排除最后一个bundled目录）
        dirs_to_check = self.skill_dirs if include_bundled else self.skill_dirs[:-1]

        for d in dirs_to_check:
            if not d.exists():
                continue
            for child in sorted(d.iterdir()):
                skill_file = child / "SKILL.md"
                if not (child.is_dir() and skill_file.exists()):
                    continue
                text = skill_file.read_text(encoding="utf-8-sig")
                meta, body = parse_frontmatter(text)
                skill_name = (meta.name if meta and meta.name else child.name)
                if skill_name in seen:
                    continue
                seen.add(skill_name)
                preview = meta.description if meta and meta.description else _first_line(body)
                items.append(SkillSummary(
                    name=skill_name,
                    path=skill_file,
                    preview=preview[:80],
                    meta=meta,
                ))
        return items

    def read_skill(self, name: str) -> str:
        for d in self.skill_dirs:
            path = d / name / "SKILL.md"
            if path.exists():
                return path.read_text(encoding="utf-8-sig")
        raise FileNotFoundError(f"skill not found: {name}")

    def read_skill_parsed(
        self, name: str, execute_shell: bool = True
    ) -> tuple[SkillMeta | None, str]:
        """读取并解析 skill。
        execute_shell=True 时自动执行 body 中的 !`cmd` 内嵌命令（与 claude-code 一致）。
        """
        for d in self.skill_dirs:
            skill_dir = d / name
            path = skill_dir / "SKILL.md"
            if path.exists():
                text = path.read_text(encoding="utf-8-sig")
                meta, body = parse_frontmatter(text)
                if execute_shell and ("!`" in body or "```!" in body):
                    body = execute_shell_in_skill(body, skill_dir)
                return meta, body
        raise FileNotFoundError(f"skill not found: {name}")

    def find_by_dir_name(self, dir_name: str) -> SkillSummary | None:
        for d in self.skill_dirs:
            path = d / dir_name / "SKILL.md"
            if path.exists():
                text = path.read_text(encoding="utf-8-sig")
                meta, body = parse_frontmatter(text)
                skill_name = meta.name if meta and meta.name else dir_name
                preview = meta.description if meta and meta.description else _first_line(body)
                return SkillSummary(name=skill_name, path=path, preview=preview[:80], meta=meta)
        return None


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return ""
