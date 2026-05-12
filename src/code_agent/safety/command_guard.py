from __future__ import annotations

import shlex
from dataclasses import dataclass

from code_agent.config import CommandPolicyConfig
from code_agent.schemas import CommandDecision

# 链式/重定向操作符：命中时将 ALLOW 降级为 REQUIRE_APPROVAL，而非直接 DENY
# 不再硬拦，让用户审批后自己判断
_CHAIN_OPERATORS = ("|", "||", "&&", ";", ">", ">>", "<", "<<", "$(", "\n", "\r")


@dataclass(frozen=True)
class ParsedCommand:
    raw: str
    argv: list[str]

    @property
    def normalized(self) -> str:
        return " ".join(part.lower() for part in self.argv)


class CommandGuard:
    def __init__(self, policy: CommandPolicyConfig) -> None:
        self.policy = policy

    def decide(self, command: str) -> CommandDecision:
        parsed = self.parse(command)
        lowered = parsed.normalized

        # 1. blocked_patterns：始终 DENY（黑名单关键词，如 http.server）
        for pattern in self.policy.blocked_patterns:
            words = pattern.lower().split()
            if all(w in lowered for w in words):
                return CommandDecision.DENY

        # 2. deny_operators（config 里保留字段，仍支持自定义追加）：始终 DENY
        for op in self.policy.deny_operators:
            if op in command:
                return CommandDecision.DENY

        # 3. deny_rules：始终 DENY
        for rule in self.policy.deny_rules:
            if self._matches_rule(parsed, rule):
                return CommandDecision.DENY

        # 4. 检测链式/重定向操作符
        #    命令含操作符时：ALLOW → REQUIRE_APPROVAL（用户看到完整命令后决定）
        #                    REQUIRE_APPROVAL/DENY 保持不变
        has_chain_op = any(op in command for op in _CHAIN_OPERATORS)

        # 5. allow_rules：简单命令直接放行，链式命令升级为审批
        for rule in self.policy.allow_rules:
            if self._matches_rule(parsed, rule):
                if has_chain_op:
                    return CommandDecision.REQUIRE_APPROVAL
                return CommandDecision.ALLOW

        # 6. ask_rules：始终审批
        for rule in self.policy.ask_rules:
            if self._matches_rule(parsed, rule):
                return CommandDecision.REQUIRE_APPROVAL

        # 7. 兜底
        if self.policy.default_mode == "allow":
            return CommandDecision.ALLOW
        if self.policy.default_mode == "approval":
            return CommandDecision.REQUIRE_APPROVAL
        return CommandDecision.DENY

    def parse(self, command: str) -> ParsedCommand:
        self.validate_simple_command(command)
        argv = shlex.split(command, posix=False)
        return ParsedCommand(raw=command, argv=argv)

    def normalize(self, command: str) -> str:
        return self.parse(command).normalized

    def validate_simple_command(self, command: str) -> None:
        if not command.strip():
            raise ValueError("command is empty")
        shlex.split(command, posix=False)

    def _matches_rule(self, parsed: ParsedCommand, rule: str) -> bool:
        rule_argv = shlex.split(rule, posix=False)
        if not rule_argv or len(rule_argv) > len(parsed.argv):
            return False
        return [part.lower() for part in parsed.argv[: len(rule_argv)]] == [
            part.lower() for part in rule_argv
        ]
