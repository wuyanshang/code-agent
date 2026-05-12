# P0 核心功能使用指南

本文档介绍新实现的三个P0级别核心功能的使用方法。

## 1. 任务管理系统

任务管理系统允许Agent将复杂工作分解为多个子任务，并跟踪执行进度。

### 可用工具

#### task_create - 创建任务
创建一个新任务来跟踪工作进度。

**参数**:
- `subject` (必需): 任务标题，简短描述
- `description` (必需): 任务详细描述
- `activeForm` (可选): 进行中时显示的动词形式，如"正在修复bug"
- `metadata` (可选): 任务元数据，JSON对象

**示例**:
```json
{
  "subject": "修复登录功能bug",
  "description": "用户报告无法使用邮箱登录，需要检查认证逻辑",
  "activeForm": "正在修复登录bug"
}
```

#### task_update - 更新任务
更新任务的状态或内容。

**参数**:
- `taskId` (必需): 任务ID
- `status` (可选): 任务状态，可选值: "pending", "in_progress", "completed"
- `subject` (可选): 新的任务标题
- `description` (可选): 新的任务描述
- `activeForm` (可选): 新的进行中形式
- `metadata` (可选): 要合并的元数据
- `addBlocks` (可选): 添加此任务阻塞的其他任务ID列表
- `addBlockedBy` (可选): 添加阻塞此任务的其他任务ID列表

**示例**:
```json
{
  "taskId": "1",
  "status": "in_progress"
}
```

#### task_list - 列出所有任务
列出所有任务及其状态。

**参数**: 无

**输出示例**:
```
任务列表:
  #1 🔄 修复登录功能bug [in_progress]
  #2 ⏳ 添加日志记录 [pending]
  #3 ✅ 更新文档 [completed]
```

#### task_get - 获取任务详情
获取指定任务的详细信息。

**参数**:
- `taskId` (必需): 任务ID

### 使用场景

**场景1: 复杂功能开发**
```
用户: 实现用户认证功能

Agent:
1. task_create: "设计认证架构"
2. task_create: "实现登录接口"
3. task_create: "实现注册接口"
4. task_create: "添加单元测试"
5. task_create: "更新API文档"

然后逐个完成，每完成一个就 task_update 标记为 completed
```

**场景2: Bug修复**
```
用户: 修复支付流程的bug

Agent:
1. task_create: "重现bug"
2. task_create: "定位问题代码"
3. task_create: "修复代码"
4. task_create: "验证修复"
5. task_create: "回归测试"
```

---

## 2. 用户交互工具 (ask_user_question)

允许Agent在执行过程中向用户提问，获取用户的选择或输入。

### 参数

- `questions` (必需): 问题列表，1-4个问题
  - `question`: 问题内容
  - `header`: 问题标签（最多12字符）
  - `options`: 选项列表（2-4个选项）
    - `label`: 选项标签（1-5个词）
    - `description`: 选项说明
  - `multiSelect`: 是否允许多选（默认false）

### 示例

**单选问题**:
```json
{
  "questions": [
    {
      "question": "应该使用哪种认证方式？",
      "header": "认证方式",
      "options": [
        {
          "label": "JWT Token",
          "description": "使用JSON Web Token，适合无状态API"
        },
        {
          "label": "Session Cookie",
          "description": "使用服务器端Session，更安全但需要状态管理"
        },
        {
          "label": "OAuth 2.0",
          "description": "使用第三方OAuth，适合社交登录"
        }
      ],
      "multiSelect": false
    }
  ]
}
```

**多选问题**:
```json
{
  "questions": [
    {
      "question": "需要支持哪些登录方式？",
      "header": "登录方式",
      "options": [
        {
          "label": "邮箱密码",
          "description": "传统的邮箱+密码登录"
        },
        {
          "label": "手机验证码",
          "description": "通过短信验证码登录"
        },
        {
          "label": "第三方登录",
          "description": "微信、QQ等第三方账号登录"
        }
      ],
      "multiSelect": true
    }
  ]
}
```

### 交互流程

1. Agent调用工具，显示问题和选项
2. 用户看到格式化的问题界面
3. 用户输入选择（数字）
4. 如果选择"其他"，用户可以输入自定义内容
5. Agent收到用户的回答，继续执行

### 使用场景

**场景1: 技术选型**
```
Agent: 我需要实现缓存功能，让我询问用户偏好
ask_user_question: "应该使用哪种缓存方案？"
  - Redis (分布式，高性能)
  - Memcached (简单，轻量)
  - 本地内存 (无需额外服务)
```

**场景2: 代码风格**
```
Agent: 发现多种可行的实现方式
ask_user_question: "应该如何处理错误？"
  - 抛出异常 (调用者处理)
  - 返回错误码 (Go风格)
  - 返回Result类型 (Rust风格)
```

**场景3: 功能确认**
```
Agent: 准备修改数据库schema
ask_user_question: "是否需要保留旧数据？"
  - 是，创建迁移脚本
  - 否，直接删除重建
```

---

## 3. 计划模式 (Plan Mode)

计划模式允许Agent在执行前制定详细计划，获得用户批准后再实施。

### 工具

#### enter_plan_mode - 进入计划模式
进入计划模式，此时只能读取和研究代码，不能修改文件或执行命令。

**参数**: 无

**效果**:
- 设置 `plan_mode = true`
- 创建计划文件 `.code-agent/plans/plan_YYYYMMDD_HHMMSS.md`
- 限制可用工具为只读工具

**可用工具**:
- ✅ 文件读取: list_files, read_file, find_files, glob_files
- ✅ 代码搜索: search_text
- ✅ 任务管理: task_list, task_get
- ✅ 用户交互: ask_user_question
- ❌ 文件修改: write_file, replace_in_file, append_file
- ❌ 命令执行: run_command

#### exit_plan_mode - 退出计划模式
退出计划模式，恢复正常的文件修改和命令执行能力。

**参数**:
- `approved` (可选): 计划是否已获得批准，默认false

### 计划文件模板

进入计划模式后，会自动创建包含以下结构的计划文件：

```markdown
# 实施计划

## 任务概述
[在此描述要完成的任务]

## 分析
[分析当前代码状态、问题根源等]

## 实施步骤
1. [步骤1]
2. [步骤2]
3. [步骤3]

## 需要修改的文件
- `文件路径1`: [修改说明]
- `文件路径2`: [修改说明]

## 风险和注意事项
- [风险1]
- [风险2]

## 测试计划
- [测试项1]
- [测试项2]
```

### 工作流程

1. **进入计划模式**
   ```
   用户: 重构认证模块
   Agent: enter_plan_mode
   ```

2. **研究和分析**
   ```
   Agent:
   - read_file: 读取相关文件
   - search_text: 搜索相关代码
   - 分析架构和依赖关系
   ```

3. **制定计划**
   ```
   Agent: 在计划文件中写入:
   - 任务概述
   - 当前问题分析
   - 详细实施步骤
   - 需要修改的文件列表
   - 风险评估
   - 测试计划
   ```

4. **征求用户意见**
   ```
   Agent: ask_user_question
   "计划已制定完成，是否批准执行？"
   - 批准，开始执行
   - 需要修改计划
   - 取消任务
   ```

5. **退出计划模式**
   ```
   Agent: exit_plan_mode(approved=true)
   ```

6. **执行计划**
   ```
   Agent: 按照计划逐步实施
   - task_create: 为每个步骤创建任务
   - 执行修改
   - task_update: 标记完成
   ```

### 使用场景

**场景1: 大型重构**
```
用户: 将同步API改为异步

Agent:
1. enter_plan_mode
2. 分析所有API端点
3. 识别依赖关系
4. 制定迁移计划
5. ask_user_question: 确认计划
6. exit_plan_mode(approved=true)
7. 逐步执行重构
```

**场景2: 复杂Bug修复**
```
用户: 修复内存泄漏问题

Agent:
1. enter_plan_mode
2. 分析代码，定位可能的泄漏点
3. 制定修复方案
4. 评估影响范围
5. ask_user_question: 确认方案
6. exit_plan_mode(approved=true)
7. 实施修复
```

**场景3: 新功能开发**
```
用户: 添加支付功能

Agent:
1. enter_plan_mode
2. 研究现有架构
3. 设计支付模块
4. 规划数据库变更
5. 制定测试策略
6. ask_user_question: 技术选型
7. exit_plan_mode(approved=true)
8. 分步骤实现
```

---

## 综合使用示例

### 示例: 实现用户认证功能

```
用户: 为系统添加JWT认证功能

Agent:
1. enter_plan_mode
   "进入计划模式，开始分析..."

2. read_file: 读取现有的用户模型
3. search_text: 搜索现有的认证相关代码
4. read_file: 读取API路由定义

5. 在计划文件中写入:
   """
   # JWT认证实施计划

   ## 任务概述
   为系统添加基于JWT的用户认证功能

   ## 分析
   - 当前系统没有认证机制
   - 已有User模型，包含username和password字段
   - API路由在 src/routes/ 目录

   ## 实施步骤
   1. 安装JWT库 (PyJWT)
   2. 创建认证中间件
   3. 实现登录接口
   4. 实现token验证
   5. 保护需要认证的API
   6. 添加单元测试

   ## 需要修改的文件
   - `requirements.txt`: 添加PyJWT依赖
   - `src/auth/jwt.py`: 新建，JWT工具函数
   - `src/auth/middleware.py`: 新建，认证中间件
   - `src/routes/auth.py`: 新建，登录/注册路由
   - `src/routes/api.py`: 修改，添加认证装饰器
   - `tests/test_auth.py`: 新建，认证测试

   ## 风险和注意事项
   - 需要安全存储密钥
   - Token过期时间需要合理设置
   - 密码需要加密存储

   ## 测试计划
   - 测试登录成功/失败
   - 测试token验证
   - 测试未认证访问保护接口
   - 测试token过期
   """

6. ask_user_question:
   "JWT认证计划已制定，请选择token过期时间："
   - 1小时 (高安全性)
   - 24小时 (平衡)
   - 7天 (便利性)

   用户选择: 24小时

7. exit_plan_mode(approved=true)
   "计划已批准，开始实施"

8. task_create: "安装JWT库"
9. task_update: #1 -> in_progress
10. run_command: "pip install PyJWT"
11. task_update: #1 -> completed

12. task_create: "创建JWT工具函数"
13. task_update: #2 -> in_progress
14. write_file: src/auth/jwt.py
15. task_update: #2 -> completed

... (继续执行其他步骤)

最终: 所有任务完成，认证功能实现完毕
```

---

## 最佳实践

### 任务管理
1. **合理拆分**: 将大任务拆分为可独立完成的小任务
2. **及时更新**: 开始任务时标记为in_progress，完成时标记为completed
3. **使用阻塞**: 对有依赖关系的任务设置blocked_by
4. **添加元数据**: 在metadata中记录重要信息

### 用户交互
1. **清晰的选项**: 每个选项都要有明确的描述
2. **合理的数量**: 选项不要太多（2-4个最佳）
3. **提供"其他"**: 系统自动提供，用户可以自定义输入
4. **适时询问**: 在关键决策点询问，不要过度打扰

### 计划模式
1. **复杂任务必用**: 超过3个文件的修改建议使用计划模式
2. **详细分析**: 在计划中充分分析问题和风险
3. **获得批准**: 重要修改必须获得用户批准
4. **保存计划**: 计划文件会保存，可供后续参考

---

## 注意事项

1. **任务ID**: 任务ID是自动生成的数字，从1开始递增
2. **计划文件**: 保存在 `.code-agent/plans/` 目录，不会自动删除
3. **Plan模式限制**: 在plan模式下，修改文件和执行命令的工具会被禁用
4. **用户输入**: ask_user_question 是同步的，会阻塞等待用户输入
5. **任务持久化**: 任务保存在 `.code-agent/tasks.json`，重启后仍然存在
