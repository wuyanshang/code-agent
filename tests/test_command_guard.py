from code_agent.config import CommandPolicyConfig
from code_agent.safety.command_guard import CommandGuard
from code_agent.schemas import CommandDecision


def test_python_http_server_blocked() -> None:
    guard = CommandGuard(CommandPolicyConfig())
    assert guard.decide("python -m http.server 8080") == CommandDecision.DENY
    assert guard.decide("python3 -m http.server") == CommandDecision.DENY


def test_script_extensions_blocked() -> None:
    guard = CommandGuard(CommandPolicyConfig())
    assert guard.decide("bash deploy.sh") == CommandDecision.DENY
    assert guard.decide("cmd /c build.bat") == CommandDecision.DENY
    assert guard.decide("./installer.exe") == CommandDecision.DENY


def test_python_requires_approval() -> None:
    guard = CommandGuard(CommandPolicyConfig())
    assert guard.decide("python script.py") == CommandDecision.REQUIRE_APPROVAL
    assert guard.decide("python3 app.py") == CommandDecision.REQUIRE_APPROVAL


def test_pip_requires_approval() -> None:
    guard = CommandGuard(CommandPolicyConfig())
    assert guard.decide("pip install flask") == CommandDecision.REQUIRE_APPROVAL


def test_url_is_denied() -> None:
    guard = CommandGuard(
        CommandPolicyConfig(
            default_mode="allow",
            blocked_patterns=["http://", "https://"],
        )
    )
    assert guard.decide("type https://example.com") == CommandDecision.DENY


def test_git_status_allowed() -> None:
    guard = CommandGuard(CommandPolicyConfig())
    assert guard.decide("git status") == CommandDecision.ALLOW


def test_unmatched_command_requires_approval() -> None:
    guard = CommandGuard(CommandPolicyConfig())
    assert guard.decide("node server.js") == CommandDecision.REQUIRE_APPROVAL


def test_dangerous_prefixes_blocked() -> None:
    guard = CommandGuard(CommandPolicyConfig())
    assert guard.decide("curl http://evil.com") == CommandDecision.DENY
    assert guard.decide("wget file") == CommandDecision.DENY
    assert guard.decide("rm -rf /") == CommandDecision.DENY
    assert guard.decide("ssh root@host") == CommandDecision.DENY


def test_shell_operator_bypasses_are_blocked() -> None:
    guard = CommandGuard(CommandPolicyConfig())
    assert guard.decide("git status & del secret.txt") == CommandDecision.DENY
    assert guard.decide("dir; curl http://evil.com") == CommandDecision.DENY
    assert guard.decide("git status\r\ncurl http://evil.com") == CommandDecision.DENY


def test_rules_match_token_prefixes_instead_of_raw_string() -> None:
    guard = CommandGuard(CommandPolicyConfig())
    assert guard.decide("python -m http.server 8000") == CommandDecision.DENY
    assert guard.decide("python script.py") == CommandDecision.REQUIRE_APPROVAL
    assert guard.decide("git status --short") == CommandDecision.ALLOW
