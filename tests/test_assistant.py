import json

import pytest
from typer.testing import CliRunner

from frappectl.cli import app
from frappectl.commands import assistant, guide

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Installed binaries, an isolated frappe config dir, and a deterministic
    site block, so tests never depend on the developer's real setup."""
    installed = {"pi", "claude", "codex", "flow", "opencode", "frappectl"}
    monkeypatch.setattr(
        assistant.shutil, "which", lambda name: name if name in installed else None
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(guide, "render_sites", lambda: "    - staging: https://x")


def _argv(result) -> list[str]:
    for ln in result.stdout.splitlines():
        if ln.startswith("cmd: "):
            return json.loads(ln[len("cmd: ") :])
    raise AssertionError(f"no cmd line in output:\n{result.stdout}")


def test_auto_picks_first_installed():
    result = runner.invoke(app, ["assistant", "--dry-run"])
    assert result.exit_code == 0
    assert _argv(result)[0] == "pi"


def test_auto_pick_skips_missing(monkeypatch):
    monkeypatch.setattr(
        assistant.shutil,
        "which",
        lambda name: name if name in {"codex", "frappectl"} else None,
    )
    result = runner.invoke(app, ["assistant", "--dry-run"])
    assert result.exit_code == 0
    assert _argv(result)[0] == "codex"


def test_pi_gets_flags():
    result = runner.invoke(app, ["assistant", "pi", "--dry-run"])
    argv = _argv(result)
    assert argv[0] == "pi"
    for flag in ("--approve", "--offline", "--no-skills", "--no-context-files"):
        assert flag in argv
    assert "--append-system-prompt" in argv


def test_codex_uses_agents_md_and_symlinks(tmp_path):
    real = tmp_path / "realcodex"
    real.mkdir()
    (real / "auth.json").write_text("{}")
    (real / "config.toml").write_text("")
    launch = assistant._codex_build("SYSTEM PROMPT", tmp_path / "out")
    assert launch.argv == ["codex"]
    assert launch.env["CODEX_HOME"] == str(tmp_path / "out")
    assert launch.writes[0][0] == "AGENTS.md"
    assert "SYSTEM PROMPT" in launch.writes[0][1]


def test_codex_dry_run_reports_home_and_agents():
    result = runner.invoke(app, ["assistant", "codex", "--dry-run"])
    out = result.stdout
    assert _argv(result) == ["codex"]
    assert "env: CODEX_HOME=" in out
    assert "assistant/codex" in out
    assert "AGENTS.md" in out


def test_claude_gets_append_flag():
    result = runner.invoke(app, ["assistant", "claude", "--dry-run"])
    argv = _argv(result)
    assert argv[0] == "claude"
    assert "--append-system-prompt" in argv
    assert "--system-prompt" not in argv


def test_opencode_writes_agent_file_and_uses_agent_flag(tmp_path):
    launch = assistant._opencode_build("SYSTEM PROMPT", tmp_path / "out")
    assert launch.argv == ["opencode", "--agent", "frappe"]
    path, content = launch.writes[0]
    assert path.endswith(".config/opencode/agents/frappe.md")
    assert "SYSTEM PROMPT" in content
    assert "description: Frappe assistant" in content


def test_opencode_dry_run_shows_agent_file_path():
    result = runner.invoke(app, ["assistant", "opencode", "--dry-run"])
    assert result.exit_code == 0
    assert _argv(result) == ["opencode", "--agent", "frappe"]
    assert "frappe.md" in result.stdout


def test_materialize_supports_absolute_write_path(tmp_path):
    abs_file = tmp_path / "abs" / "agent.md"
    launch = assistant.Launch(argv=["x"], writes=[(str(abs_file), "content")])
    assistant._materialize(launch, tmp_path / "tool_dir")
    assert abs_file.read_text() == "content"


def test_flow_starts_web_with_append_flag():
    result = runner.invoke(app, ["assistant", "flow", "--dry-run"])
    argv = _argv(result)
    assert argv[:2] == ["flow", "web"]
    assert "--append-system-prompt" in argv
    assert "frappectl" in argv[argv.index("--append-system-prompt") + 1]


def test_passthrough_after_ddash_is_appended():
    result = runner.invoke(
        app, ["assistant", "pi", "--dry-run", "--", "--continue", "hi there"]
    )
    argv = _argv(result)
    assert argv[-2:] == ["--continue", "hi there"]


def test_unsupported_tool_errors():
    result = runner.invoke(app, ["assistant", "bogus", "--dry-run"])
    assert result.exit_code == 2
    assert "Unsupported tool" in result.stderr


def test_missing_binary_exits_127(monkeypatch):
    monkeypatch.setattr(assistant.shutil, "which", lambda name: None)
    result = runner.invoke(app, ["assistant", "pi", "--dry-run"])
    assert result.exit_code == 127


def test_dry_run_writes_nothing(tmp_path):
    runner.invoke(app, ["assistant", "codex", "--dry-run"])
    assert not (tmp_path / "config" / "frappe").exists()


def test_materialize_writes_and_symlinks(tmp_path):
    target = tmp_path / "real.json"
    target.write_text("{}")
    launch = assistant.Launch(
        argv=["x"],
        writes=[("AGENTS.md", "hello")],
        symlinks=[("auth.json", target)],
    )
    out = tmp_path / "out"
    assistant._materialize(launch, out)
    assert (out / "AGENTS.md").read_text() == "hello"
    assert (out / "auth.json").is_symlink()
    assert (out / "auth.json").read_text() == "{}"


def test_system_prompt_includes_guide_and_sites():
    sp = assistant._system_prompt()
    assert "frappectl" in sp
    assert "staging: https://x" in sp
