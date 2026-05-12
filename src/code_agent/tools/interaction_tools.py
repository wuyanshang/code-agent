from __future__ import annotations

import asyncio
from typing import Any

from code_agent.schemas import ToolResult
from code_agent.tools.base import BaseTool


class AskUserQuestionTool(BaseTool):
    name = "ask_user_question"
    description = "在执行过程中向用户提问，获取用户的选择或输入。用于需要用户决策的场景。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "description": "要问的问题列表（1-4个问题）",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "问题内容"},
                        "header": {"type": "string", "description": "问题标签（最多12字符）"},
                        "options": {
                            "type": "array",
                            "description": "选项列表（2-4个选项）",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {"type": "string", "description": "选项标签（1-5个词）"},
                                    "description": {"type": "string", "description": "选项说明"},
                                },
                                "required": ["label", "description"],
                            },
                        },
                        "multiSelect": {
                            "type": "boolean",
                            "description": "是否允许多选",
                            "default": False,
                        },
                    },
                    "required": ["question", "header", "options"],
                },
            },
        },
        "required": ["questions"],
    }

    def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        questions = arguments.get("questions", [])
        if not questions:
            return ToolResult(ok=False, content="", error="至少需要一个问题")

        if len(questions) > 4:
            return ToolResult(ok=False, content="", error="最多支持4个问题")

        answers = {}
        for q in questions:
            question_text = q["question"]
            header = q.get("header", "选择")
            options = q.get("options", [])
            multi_select = q.get("multiSelect", False)

            if len(options) < 2 or len(options) > 4:
                return ToolResult(ok=False, content="", error=f"问题 '{question_text}' 的选项数量必须在2-4之间")

            # 显示问题
            print(f"\n{'='*60}")
            print(f"[{header}] {question_text}")
            print(f"{'='*60}")

            # 显示选项
            for idx, opt in enumerate(options, 1):
                print(f"{idx}. {opt['label']}")
                print(f"   {opt['description']}")

            # 添加"其他"选项
            print(f"{len(options) + 1}. 其他（自定义输入）")

            # 获取用户输入
            if multi_select:
                print(f"\n请选择（可多选，用逗号分隔，如: 1,3）: ", end="")
            else:
                print(f"\n请选择（1-{len(options) + 1}）: ", end="")

            try:
                user_input = input().strip()
            except (EOFError, KeyboardInterrupt):
                return ToolResult(ok=False, content="", error="用户取消了输入")

            # 解析输入
            if multi_select:
                selected_indices = []
                for part in user_input.split(","):
                    try:
                        idx = int(part.strip())
                        if 1 <= idx <= len(options) + 1:
                            selected_indices.append(idx)
                    except ValueError:
                        pass

                if not selected_indices:
                    return ToolResult(ok=False, content="", error="无效的选择")

                selected_labels = []
                for idx in selected_indices:
                    if idx <= len(options):
                        selected_labels.append(options[idx - 1]["label"])
                    else:
                        print("请输入自定义内容: ", end="")
                        custom = input().strip()
                        selected_labels.append(custom)

                answers[question_text] = ", ".join(selected_labels)
            else:
                try:
                    choice = int(user_input)
                    if choice < 1 or choice > len(options) + 1:
                        return ToolResult(ok=False, content="", error="选择超出范围")

                    if choice <= len(options):
                        answers[question_text] = options[choice - 1]["label"]
                    else:
                        print("请输入自定义内容: ", end="")
                        custom = input().strip()
                        answers[question_text] = custom
                except ValueError:
                    return ToolResult(ok=False, content="", error="无效的输入")

        # 返回结果
        result_lines = ["用户回答:"]
        for q_text, answer in answers.items():
            result_lines.append(f"- {q_text}: {answer}")

        return ToolResult(ok=True, content="\n".join(result_lines), metadata={"answers": answers})

