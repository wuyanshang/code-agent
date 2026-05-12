"""测试自动补全功能"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from code_agent.repl import commands as cmd_mod
from code_agent.skills.loader import SkillLoader
from code_agent.skills import BUNDLED_SKILLS_DIR
from prompt_toolkit.completion import WordCompleter

# 模拟session的补全逻辑
project_root = Path.cwd()
project_skills = project_root / "skills"
personal_skills = Path.home() / ".code-agent" / "skills"
skill_loader = SkillLoader(personal_skills, project_skills, BUNDLED_SKILLS_DIR)

slash_names = sorted(cmd_mod.all_commands().keys())

# 构建skills列表和描述字典（不包含bundled）
skill_names = []
skill_meta = {}
for s in skill_loader.list_skills(include_bundled=False):
    if s.meta and not s.meta.user_invocable:
        continue
    skill_name = f"/{s.name}"
    skill_names.append(skill_name)
    skill_meta[skill_name] = s.preview

# 构建命令描述字典
command_meta = cmd_mod.all_commands()

# 合并所有补全项和描述
all_words = slash_names + skill_names
all_meta = {**command_meta, **skill_meta}

print("=" * 60)
print("自动补全列表（输入 / 后会显示，不含bundled skills）")
print("=" * 60)

for word in sorted(all_words):
    desc = all_meta.get(word, "")
    print(f"{word:<20} {desc}")

print("\n" + "=" * 60)
print(f"总计: {len(all_words)} 个命令/技能")
print("=" * 60)

# 显示所有skills（包括bundled）
print("\n" + "=" * 60)
print("/skill list 会显示的所有技能（包括bundled）")
print("=" * 60)

all_skills = skill_loader.list_skills(include_bundled=True)
for s in all_skills:
    print(f"/{s.name:<30} {s.preview}")

print("\n" + "=" * 60)
print(f"总计: {len(all_skills)} 个技能")
print("=" * 60)

