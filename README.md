# code-agent

一个面向企业内网受限环境的本地代码 Agent CLI 工具。

支持交互式 REPL 对话、流式输出、Skills 技能系统、子 Agent 委派、多 Agent 团队协作，兼容任意 OpenAI 格式的 API 接口。

## 功能特性

- **交互式 REPL** — 多轮对话、流式逐字输出、斜杠命令、Tab 补全、输入历史
- **Skill 系统** — 可扩展的技能模板，支持 frontmatter 元数据、参数传递、直接 `/名称` 调用
- **子 Agent 委派** — LLM 自动将子任务委派给专职 agent（代码搜索、审查、规划）
- **Agent Teams** — 多角色协作，任务自动分解、并行执行、结果汇总
- **Plan 模式** — 只读研究 + 方案输出，确认后再执行
- **任务管理** — 复杂任务分解为子任务，跟踪执行进度（P0新增 ✨）
- **用户交互** — 运行时向用户提问，获取选择和决策（P0新增 ✨）
- **智能代码搜索** — 基于 AST 的语义搜索，精确查找类/函数定义、引用、导入（新增 ✨）
- **安全防护** — 路径沙箱、命令黑白名单、交互式分级审批（上下键选择）
- **项目记忆** — 通过 AGENT.md 让 Agent 自动了解项目背景
- **模型无关** — 支持任意 OpenAI 兼容接口（阿里百炼、私有部署等），运行时 `/model` 切换
- **Token 统计** — 实时累计用量，`/cost` 随时查看

---

## 安装

```bash
# Python >= 3.11
pip install -e .
```

安装完成后，在任意终端输入 `ca` 即可启动。

---

## 快速开始

```bash
# 交互模式（指定项目和配置）
ca --project ./my-project --config config/default.yaml

# 在当前目录启动（mock 模式，可验证全链路）
ca --project .

# 单次执行任务
ca run "帮我审查这个项目" --project . --skill code-review --config config/default.yaml

# Agent Teams 执行
ca team run "审查代码并生成报告" --project . --config config/default.yaml
```

进入交互模式后直接输入需求即可：

```
> 帮我看看这个项目的入口文件

  ⚡ list_files(path=., max_depth=2)
  ✓ src/main.py src/utils.py ...

  ⚡ read_file(path=src/main.py)
  ✓ import sys ...

这个项目的入口是 src/main.py，主要做了以下几件事...
```

### 接入真实模型

所有服务都走 **OpenAI 兼容** HTTP，只需改同一份 YAML（默认 `config/default.yaml`），或复制成 `config/prod.yaml` 等多套配置。

```yaml
model:
  provider: openai_compatible
  model_name: your-model
  base_url: https://你的网关/v1
  api_key: your-key
  timeout_seconds: 120
```

启动时用 `--config` 指向对应文件；也可用环境变量 `CODE_AGENT_API_KEY` 等覆盖。

---

## 目录约定

code-agent 使用 **三级目录**，同名时高优先级覆盖低优先级：

### Skills 目录

| 优先级 | 位置 | 说明 |
|--------|------|------|
| 1. 最高 | `~/.code-agent/skills/` | **全局个人技能**，任何项目都能用 |
| 2. 中 | 项目下 `./skills/` | 项目专属技能（可通过配置修改路径） |
| 3. 最低 | 内置 bundled | 预装的 Superpowers 等技能 |

### Agents 目录

| 优先级 | 位置 | 说明 |
|--------|------|------|
| 1. 最高 | `~/.code-agent/agents/` | **全局个人 agent**，任何项目都能用 |
| 2. 中 | 项目下 `.code-agent/agents/` | 项目专属 agent |
| 3. 最低 | 内置 bundled | 预装 explore / reviewer / planner |

### 全局目录结构示例

```
~/.code-agent/                    # 全局配置目录（Windows: C:\Users\你的用户名\.code-agent\）
├── skills/                       # 全局技能 — 任何项目都能用
│   ├── my-review/
│   │   └── SKILL.md
│   └── my-deploy/
│       └── SKILL.md
└── agents/                       # 全局子 agent — 任何项目都能用
    ├── security-checker.md
    └── db-expert.md
```

### 项目目录结构示例

```
your-project/
├── .code-agent/                  # 项目级配置
│   ├── AGENT.md                  # 项目记忆（自动注入 system prompt）
│   ├── agents/                   # 项目专属子 agent
│   │   └── api-reviewer.md
│   ├── sessions/                 # 会话存档（/save，JSON，可加入 .gitignore）
│   └── history                   # REPL 输入历史（自动生成）
└── skills/                       # 项目专属技能
    ├── code-review/
    │   └── SKILL.md
    └── bug-fix/
        └── SKILL.md
```

---

## 斜杠命令

| 命令 | 功能 |
|------|------|
| `/help` | 显示所有命令 + 可用技能 + 可用子 agent |
| `/clear` | 清空对话历史 |
| `/status` | 查看会话状态（模式、模型、轮数、文件变更） |
| `/cost` | 查看 Token 用量 |
| `/tools` | 列出所有可用工具 |
| `/skill list` | 列出所有技能 |
| `/skill use <name>` | 启用某个技能（持续生效直到 clear） |
| `/skill clear` | 取消当前技能 |
| `/agents list` | 列出所有可用子 agent |
| `/agents info <name>` | 查看某个 agent 的详细配置 |
| `/model` | 有 `model.presets` 时上下键选预设；否则提示如何配置 |
| `/model <别名或模型 id>` | 匹配预设名则套用整段配置并重建客户端；否则只改 `model_name` |
| `/plan` | 切换 Plan 模式（只读研究，不修改文件） |
| `/team <任务>` | Agent Teams 多角色协作 |
| `/team roles` | 查看当前团队角色 |
| `/team add <name> <描述>` | 动态添加角色 |
| `/compact` | 压缩对话上下文（**优先用当前模型生成摘要**，失败则回退为「最近几条 + 占位」） |
| `/sessions` | 列出本地已保存会话（`project/.code-agent/sessions/`） |
| `/sessions delete <id前缀>` | 删除唯一匹配的会话文件 |
| `/save [标题]` | 保存当前对话为 JSON；再次保存覆盖同一 id（见 `/status` 存档 id） |
| `/resume` | 无参：上下键选择会话恢复；有参：按 uuid 前缀或标题关键词唯一匹配 |
| `/continue` | 与 `/resume` 相同（对齐 Claude Code 别名） |
| `/quit` | 退出 |

**技能直接调用：** 输入 `/<技能名>` 可直接调用技能，例如 `/brainstorming 给项目加缓存层`。

所有斜杠命令支持 Tab 自动补全。

---

## Skill 系统

Skill 是可复用的指令模板，注入到 system prompt 中指导 Agent 按特定流程工作。

### 使用技能

```bash
# 交互模式 — 直接 /技能名 调用
> /code-review

# 交互模式 — 带参数调用
> /brainstorming 我想给项目加缓存层

# 命令行模式
ca run "帮我审查" --project . --skill code-review --config config/default.yaml
```

LLM 也会根据任务自动建议合适的技能。

### 创建技能

在 `~/.code-agent/skills/`（全局）或项目 `./skills/`（项目级）下创建：

```
skills/
└── database-migration/
    └── SKILL.md
```

**SKILL.md 基本格式：**

```markdown
# database-migration

## 何时使用
当用户要求进行数据库迁移或表结构变更时。

## 工作流程
1. 先用 search_text 查找现有的 migration 文件
2. 用 read_file 阅读最新的 migration 和 model 定义
3. 生成新的 migration 文件
4. 不要自动执行 migrate 命令
```

**SKILL.md 高级格式（带 frontmatter）：**

```markdown
---
name: database-migration
description: 数据库迁移助手
argument_hint: <表名>
user_invocable: true
disable_model_invocation: false
---

将 $ARGUMENTS 相关的表结构进行迁移。

## 步骤
1. 搜索现有 migration 文件
2. 读取模型定义
3. 生成迁移脚本
```

frontmatter 可选字段：

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `name` | 技能名称 | 目录名 |
| `description` | 简短描述 | — |
| `argument_hint` | 参数提示（显示在 /help 中） | — |
| `user_invocable` | 用户能否手动调用 | `true` |
| `disable_model_invocation` | 禁止 LLM 自动调用 | `false` |

参数占位符：`$ARGUMENTS`（全部参数）、`$0` `$1` `$2`（按空格拆分的参数）。

### 内置技能

安装后自带 Superpowers 系列技能（brainstorming、systematic-debugging 等），输入 `/help` 即可查看完整列表。

---

## 子 Agent 委派

子 Agent 是专职角色，LLM 会在合适的时机自动把子任务委派给它们，用完即回到主对话。

### 内置子 Agent

| Agent | 职责 | 可用工具 |
|-------|------|----------|
| `explore` | 快速搜索和分析代码库（只读） | list_files, read_file, find_files, glob_files, search_text |
| `reviewer` | 代码审查，分析质量和安全隐患（只读） | list_files, read_file, find_files, glob_files, search_text |
| `planner` | 任务规划，拆解方案和评估技术路线（只读） | list_files, read_file, find_files, glob_files, search_text |

### 查看 / 管理

```
> /agents list          # 列出所有子 agent
> /agents info explore  # 查看详细配置
```

### 创建自定义子 Agent

在 `~/.code-agent/agents/`（全局）或项目 `.code-agent/agents/`（项目级）下创建 `.md` 文件：

```markdown
---
name: security-checker
description: 安全审查专家，检查代码中的安全隐患
tools: list_files, read_file, find_files, search_text
maxTurns: 6
---

你是一位安全审查专家。

审查重点：
1. SQL 注入
2. XSS 攻击
3. 敏感数据泄露
4. 不安全的依赖版本

按严重程度输出结果，引用具体文件和行号。
```

frontmatter 字段：

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `name` | agent 名称（必填） | — |
| `description` | 简短描述 | — |
| `tools` | 允许使用的工具（逗号分隔或列表） | 全部工具 |
| `disallowed_tools` / `disallowedTools` | 禁用的工具 | — |
| `model` | 使用的模型（留空则继承主模型） | — |
| `maxTurns` / `max_turns` | 最大对话轮数 | `8` |
| `skills` | 关联的技能 | — |

---

## Agent Teams（多角色协作）

Teams 模式将复杂任务自动分解，分配给不同角色的子 Agent 并行执行，最后汇总结果。

> **子 Agent 委派 vs Agent Teams：**
> - 子 Agent 委派：LLM 在对话中按需委派单个子任务，轻量灵活
> - Agent Teams：一次性多角色并行协作，适合大型综合任务

### 使用

```bash
# 交互模式
> /team 审查这个项目的代码质量并修复发现的问题
> /team roles             # 查看角色
> /team add tester 测试工程师  # 动态添加角色

# 命令行模式
ca team run "审查代码并生成报告" --project . --config config/default.yaml

# 显示进度信息
ca team run "分析项目架构" --project . --verbose

# 从checkpoint恢复
ca team run "继续之前的任务" --project . --checkpoint .code-agent/checkpoints/team_checkpoint_1.json
```

### 新增功能 ✨

**1. 超时控制**
- 配置 `team.timeout_seconds` 设置整个team执行的超时时间（默认300秒）
- 超时后自动返回已完成的部分结果

**2. 失败重试**
- 配置 `team.max_retries` 设置SubAgent失败重试次数（默认2次）
- 自动重试失败的子任务，提高成功率

**3. 成本追踪**
- 自动统计token使用量和LLM调用次数
- 配置 `team.max_total_tokens` 设置token上限（0表示不限制）
- 输出结果包含 `total_tokens_used` 和 `llm_calls_count`

**4. 进度回调**
- 使用 `--verbose` 参数查看实时进度
- 显示任务分解、执行轮次、评估等关键节点

**5. Checkpoint持久化**
- 每轮执行后自动保存checkpoint到 `.code-agent/checkpoints/`
- 失败或中断后可使用 `--checkpoint` 参数恢复执行
- 避免长时间任务重新开始

**6. 配置化常量**
- `team.max_context_messages`: SubAgent上下文最大消息数（默认40）
- `team.trim_keep_recent`: 裁剪时保留的最近消息数（默认20）
- 可根据模型上下文长度灵活调整

### 默认角色

| 角色 | 职责 | 可用工具 |
|------|------|----------|
| `coder` | 代码开发，可读写修改文件 | list_files, read_file, find_files, glob_files, search_text, write_file, replace_in_file, append_file, preview_diff |
| `reviewer` | 代码审查，只读不写 | list_files, read_file, find_files, glob_files, search_text |
| `devops` | 运维，执行构建/测试命令 | run_command, list_files, read_file |

可在 YAML 配置的 `team.roles` 中自定义角色。

---

## Plan 模式

在修改代码前先让 Agent 做只读分析，输出方案供你确认。

```
> /plan                   # 进入 Plan 模式
> 重构用户认证模块        # Agent 只能读文件/搜索，不能修改
  （输出分析方案...）
> /plan                   # 退出 Plan 模式，恢复全部工具
> 按方案执行              # 现在可以修改了
```

Plan 模式下 LLM 只能使用只读工具（read_file、search_text、list_files 等），不能写文件或执行命令。

---

## 项目记忆（AGENT.md）

在项目中创建 `.code-agent/AGENT.md` 或根目录的 `AGENT.md`，Agent 启动时会自动注入到 system prompt。

```markdown
# 项目说明

这是一个 Spring Boot + Vue3 的后台管理系统。

## 技术栈
- 后端：Java 17 + Spring Boot 3 + MyBatis-Plus
- 前端：Vue3 + Element Plus + Vite

## 规范
- 始终使用中文回答
- 修改代码前先阅读相关上下文
- SQL 不使用 SELECT *
```

---

## 命令执行安全策略

所有通过 `run_command` 工具执行的命令都受三级安全策略控制：

| 级别 | 行为 | 默认配置 |
|------|------|----------|
| **blocked** | 直接拒绝 | curl, wget, ssh, rm, del, `python -m http.server`, 含 .sh/.bat/.exe 的命令 |
| **approval** | 需要用户确认 | python, pip, git commit, git push, pytest 等 |
| **allowed** | 直接放行 | git status, git diff, git log, dir, type |

未匹配任何规则的命令默认需要审批。

审批时使用上下键选择（类似 Claude Code）：

```
╭──── ⚠ 需要执行命令 ────╮
│  pip install flask      │
│  安装项目依赖            │
╰─────────────────────────╯
  ▸ 本次允许
    永久允许
    拒绝
```

`--yes` 模式可跳过审批（blocked 级别依然拒绝）：

```bash
ca --yes --project . --config config/default.yaml
```

---

## 可用工具

| 工具 | 功能 |
|------|------|
| `list_files` | 列出目录下的文件和子目录 |
| `read_file` | 读取文本文件（可指定行范围） |
| `find_files` | 按文件名关键词查找文件 |
| `glob_files` | 按 glob 模式列出文件（如 `**/*.py`） |
| `search_text` | 文本搜索：默认纯 Python；`search_use_ripgrep: true` 时优先 `rg`。默认 `files_with_matches`；未传 `head_limit` 时默认 250 条（`search_default_head_limit`）；另有 content/count、`glob`、`type` 等 |
| `search_symbol` | 智能搜索符号定义（类、函数），基于 AST 分析，比 search_text 更精确 |
| `search_references` | 查找符号的所有引用位置，支持重构前影响分析 |
| `search_imports` | 查找导入语句，支持依赖分析 |
| `write_file` | 写入整个文件内容 |
| `replace_in_file` | 精确文本替换 |
| `append_file` | 向文件末尾追加内容 |
| `preview_diff` | 查看最近一次文件修改的 diff |
| `view_session_diff` | 查看本次会话的所有文件变更摘要（支持筛选和统计） |
| `view_file_diff` | 查看指定文件的详细 diff（unified diff 格式） |
| `compare_file_versions` | 比较文件的原始版本和当前版本 |
| `run_command` | 执行受策略控制的命令 |
| `list_skills` | 列出可用技能 |
| `read_skill` | 读取技能内容 |
| `invoke_skill` | 激活技能（LLM 自动调用） |
| `list_agents` | 列出可用子 agent |
| `delegate_agent` | 将子任务委派给子 agent（LLM 自动调用） |

---

## CLI 命令参考

```bash
# 交互模式（默认）
ca [--project PATH] [--config PATH] [--yes]

# 单次执行
ca run <task> [--project PATH] [--skill NAME] [--config PATH]

# Agent Teams
ca team run <task> [--project PATH] [--config PATH] [--checkpoint PATH] [--verbose]

# 查看工具/技能
ca tools list
ca skills list [--project PATH]
ca skills show <name> [--project PATH]
```

---

## 配置说明

完整配置结构（`config/default.yaml`）：

```yaml
model:
  provider: mock               # mock | openai_compatible | tongyi
  model_name: ""
  base_url: ""
  api_key: ""
  timeout_seconds: 60
  presets:                     # 可选：命名预设，REPL 里 /model 无参为上下键选择
    fast:
      description: 快速
      model_name: qwen-turbo
    max:
      model_name: qwen-max
      timeout_seconds: 120
    # 不同模型走不同网关时，每个预设写各自的 base_url / api_key 即可，例如：
    # office:
    #   description: 公司内网 OpenAI 兼容
    #   provider: openai_compatible
    #   model_name: gpt-4o-mini
    #   base_url: https://llm.corp.example/v1
    #   api_key: sk-office
    # vendor-b:
    #   description: 另一供应商
    #   provider: openai_compatible
    #   model_name: some-model
    #   base_url: https://api.vendor-b.com/v1
    #   api_key: sk-b
    # 未写的字段沿用根上 model；切换预设会重建 LLM 客户端

agent:
  max_steps: 8                 # 单轮最大步数
  max_tool_failures: 3
  system_prompt: "..."

project:
  root: "."
  ignore_patterns: [".git", "__pycache__", "node_modules"]

tools:
  read_file_max_chars: 12000
  search_max_results: 50
  search_default_head_limit: 250
  search_use_ripgrep: false  # true：优先用 rg；默认 false 为纯 Python 搜索
  command_timeout_seconds: 20

skills:
  directory: "./skills"        # 项目级技能目录（相对于项目根目录）

context:                        # 对话体积控制（估算 token，防读大量文件后爆上下文）
  budget_tokens_warn: 60000     # 超过则提示 /compact
  budget_tokens_compact: 90000  # 超过则自动压缩（0=关闭）
  tool_message_max_chars: 10000 # 写入历史的单条 tool 返回上限
  compact_keep_recent: 6        # 压缩后保留的最近消息条数
  compact_source_max_chars: 80000
  compact_auto_use_llm: false   # true：自动压缩也走模型摘要（多一次 API）

command_policy:
  default_mode: approval       # allow | deny | approval
  blocked_prefixes: [...]
  approval_required_prefixes: [...]
  allowed_prefixes: [...]
  blocked_patterns: [...]

team:
  mode: coordinate
  max_parallel: 2               # 并行子 Agent 数，过大易触发网关限流
  max_rounds: 2                 # 最大执行轮次
  timeout_seconds: 300          # 整个team执行的超时时间（秒），0表示不限制
  max_retries: 2                # SubAgent失败重试次数
  max_context_messages: 40      # SubAgent上下文最大消息数
  trim_keep_recent: 20          # 裁剪时保留的最近消息数
  max_total_tokens: 0           # 最大token使用量限制，0表示不限制
  checkpoint_dir: ".code-agent/checkpoints"  # checkpoint保存目录
  roles: [...]

logging:
  level: "INFO"
```

环境变量（可选，优先级高于 YAML）：`CODE_AGENT_CONFIG`、`CODE_AGENT_PROVIDER`、`CODE_AGENT_MODEL`、`CODE_AGENT_BASE_URL`、`CODE_AGENT_API_KEY`、`CODE_AGENT_PROJECT_ROOT`。

---

## 项目结构

```
code-agent/
├── config/                         # YAML 配置文件（默认 default.yaml）
│   └── default.yaml
├── skills/                         # 项目级 Skill 示例
│   ├── bug-fix/SKILL.md
│   └── code-review/SKILL.md
├── src/code_agent/
│   ├── agent/                      # Agent 核心（上下文、Runner、Prompt 构建）
│   ├── agents/                     # 子 Agent 加载器 + 内置 agent
│   │   ├── loader.py               # AgentDef 数据模型 + AgentLoader
│   │   └── bundled/                # 内置子 agent（explore/reviewer/planner）
│   ├── bundled_skills/             # 内置技能（Superpowers 系列）
│   ├── llm/                        # LLM 客户端（OpenAI 兼容 / 通义 / Mock）
│   ├── repl/                       # 交互式 REPL（会话、命令、渲染）
│   ├── skills/                     # Skill 加载器（frontmatter 解析、多目录扫描）
│   ├── teams/                      # Agent Teams 编排器
│   ├── tools/                      # 工具定义（文件/编辑/搜索/命令/技能/agent）
│   ├── safety/                     # 路径沙箱、命令策略
│   └── utils/                      # 公共工具函数
├── tests/                          # 测试
├── pyproject.toml
└── .env.example
```

---

## 常见问题

**Windows 终端中文乱码** — 使用 Windows Terminal，或 PowerShell 中执行 `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`。

**阿里百炼等 OpenAI 兼容网关** — 按服务商文档填写 `base_url`（例如百炼为 `https://dashscope.aliyuncs.com/compatible-mode/v1`）。

**Agent 执行步数不够** — 修改配置 `agent.max_steps: 20`。

**对话上下文太长** — 用 `/compact`（会调用当前模型生成摘要；失败则回退为粗粒度压缩），或 `/clear` 清空重新开始。自动触发见 `context.compact_auto_use_llm`。

**技能/Agent 没显示** — 检查文件路径是否正确：技能要放在 `<name>/SKILL.md` 目录结构下，agent 直接放 `.md` 文件。输入 `/help` 确认加载情况。
