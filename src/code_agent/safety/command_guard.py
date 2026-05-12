from __future__ import annotations

import shlex
from dataclasses import dataclass

from code_agent.config import CommandPolicyConfig
from code_agent.schemas import CommandDecision


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

        for pattern in self.policy.blocked_patterns:
            words = pattern.lower().split()
            # 多个词：所有词都必须出现在命令中（AND 逻辑）
            # 单个词：直接子串匹配
            if all(w in lowered for w in words):
                return CommandDecision.DENY

        for op in self.policy.deny_operators:
            if op in command:
                return CommandDecision.DENY

        for rule in self.policy.deny_rules:
            if self._matches_rule(parsed, rule):
                return CommandDecision.DENY

        for rule in self.policy.allow_rules:
            if self._matches_rule(parsed, rule):
                return CommandDecision.ALLOW

        for rule in self.policy.ask_rules:
            if self._matches_rule(parsed, rule):
                return CommandDecision.REQUIRE_APPROVAL

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
