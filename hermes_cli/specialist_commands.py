"""
Specialist subcommand for hermes CLI.

Handles standalone specialist management commands like create, list, edit,
delete, and show.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

from hermes_cli.colors import Colors, color
from hermes_cli.curses_ui import flush_stdin
from hermes_constants import get_hermes_home


SPECIALISTS_DIR = get_hermes_home() / "specialists"


_HARNESS_TEMPLATE = '''#!/usr/bin/env python3
"""
Hermes Specialist Harness — {name}

Auto-generated harness for the {domain} specialist.
Run directly or import into a larger workflow.
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from run_agent import AIAgent

CONFIG = {config_repr}


def run(message: str, **kwargs) -> str:
    """Run the specialist on a message."""
    agent = AIAgent(
        model=CONFIG.get("model_override") or kwargs.get("model", "anthropic/claude-opus-4.6"),
        platform="cli",
        **kwargs,
    )
    system = CONFIG.get("system_prompt", "")
    return agent.chat(message, system_message=system)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {{sys.argv[0]}} <message>")
        sys.exit(1)
    print(run(" ".join(sys.argv[1:])))
'''


def _ensure_dir() -> None:
    SPECIALISTS_DIR.mkdir(parents=True, exist_ok=True)


def _config_path(name: str) -> Path:
    return SPECIALISTS_DIR / f"{name}.json"


def _harness_path(name: str) -> Path:
    return SPECIALISTS_DIR / f"{name}_harness.py"


def _load_config(name: str) -> dict[str, Any] | None:
    path = _config_path(name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_config(name: str, cfg: dict[str, Any]) -> None:
    _ensure_dir()
    path = _config_path(name)
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _write_harness(name: str, cfg: dict[str, Any]) -> None:
    path = _harness_path(name)
    content = _HARNESS_TEMPLATE.format(
        name=name,
        domain=cfg.get("domain", "general"),
        config_repr=repr(cfg),
    )
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o755)


def _get_all_specialists() -> list[dict[str, Any]]:
    _ensure_dir()
    results: list[dict[str, Any]] = []
    for path in sorted(SPECIALISTS_DIR.glob("*.json")):
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            cfg["_name"] = path.stem
            results.append(cfg)
        except (OSError, json.JSONDecodeError):
            continue
    return results


def _available_tool_names() -> list[str]:
    """Return sorted list of registered tool names."""
    try:
        from tools.registry import discover_builtin_tools, registry

        discover_builtin_tools()
        entries = registry._snapshot_entries()
        return sorted({e.name for e in entries})
    except Exception:
        return []


def _input_line(prompt: str, default: str = "") -> str:
    """Read a line of input with an optional default."""
    if default:
        full = color(f"{prompt} [{default}]: ", Colors.DIM)
    else:
        full = color(f"{prompt}: ", Colors.DIM)
    try:
        val = input(full).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)
    return val if val else default


def _input_multiline(prompt: str) -> str:
    """Read multi-line input until a blank line."""
    print(color(prompt, Colors.DIM))
    print(color("  (enter blank line to finish)", Colors.DIM))
    lines: list[str] = []
    try:
        while True:
            line = input("  ")
            if line.strip() == "":
                break
            lines.append(line)
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)
    return "\n".join(lines)


def specialist_create(args) -> int:
    """Interactive wizard to create a new specialist."""
    _require_tty("specialist create")

    print(color("\n  Create a new Hermes Specialist\n", Colors.CYAN))

    name = getattr(args, "name", None)
    if not name:
        name = _input_line("Name")
    if not name:
        print(color("Name is required.", Colors.RED))
        return 1

    name = name.lower().replace(" ", "_")
    if _config_path(name).exists():
        print(color(f"Specialist '{name}' already exists.", Colors.RED))
        return 1

    domain = _input_line("Domain (e.g. frontend, security, data-science)")
    description = _input_line("Short description")
    model_override = _input_line("Model override (optional, e.g. openai/gpt-5.4)")
    skills_raw = _input_line("Skills (comma-separated, optional)")
    skills = [s.strip() for s in skills_raw.split(",") if s.strip()]

    # Tools whitelist via curses checklist
    tool_names = _available_tool_names()
    selected_tools: list[str] = []
    if tool_names and sys.stdin.isatty():
        try:
            from hermes_cli.curses_ui import curses_checklist

            print(color("\n  Select whitelisted tools (SPACE to toggle, ENTER to confirm):\n", Colors.DIM))
            selected_indices = curses_checklist(
                title="Whitelisted Tools",
                items=tool_names,
                selected=set(),
            )
            selected_tools = [tool_names[i] for i in sorted(selected_indices)]
        except Exception:
            # Fallback to comma-separated input
            tools_raw = _input_line("Whitelisted tools (comma-separated, optional)")
            selected_tools = [t.strip() for t in tools_raw.split(",") if t.strip()]
    else:
        tools_raw = _input_line("Whitelisted tools (comma-separated, optional)")
        selected_tools = [t.strip() for t in tools_raw.split(",") if t.strip()]

    system_prompt = _input_multiline("System prompt")

    cfg: dict[str, Any] = {
        "name": name,
        "domain": domain,
        "description": description,
        "model_override": model_override or None,
        "skills": skills,
        "tools_whitelist": selected_tools,
        "system_prompt": system_prompt,
    }

    _save_config(name, cfg)
    _write_harness(name, cfg)

    print(color(f"\nCreated specialist: {name}", Colors.GREEN))
    print(f"  Config:  {_config_path(name)}")
    print(f"  Harness: {_harness_path(name)}")
    return 0


def specialist_list() -> int:
    """List all specialists."""
    specialists = _get_all_specialists()
    if not specialists:
        print(color("No specialists found.", Colors.DIM))
        print(color(f"Create one with 'hermes specialist create'", Colors.DIM))
        return 0

    print()
    print(color("┌─────────────────────────────────────────────────────────────────────────┐", Colors.CYAN))
    print(color("│                           Specialists                                   │", Colors.CYAN))
    print(color("└─────────────────────────────────────────────────────────────────────────┘", Colors.CYAN))
    print()

    for cfg in specialists:
        name = cfg["_name"]
        domain = cfg.get("domain", "")
        description = cfg.get("description", "")
        model = cfg.get("model_override") or "(default)"
        skills = cfg.get("skills", [])
        tools = cfg.get("tools_whitelist", [])

        print(f"  {color(name, Colors.YELLOW)}  {color(domain, Colors.DIM)}")
        if description:
            print(f"    {description}")
        print(f"    Model: {model}")
        if skills:
            print(f"    Skills: {', '.join(skills)}")
        if tools:
            print(f"    Tools:  {', '.join(tools)}")
        print()
    return 0


def specialist_show(args) -> int:
    """Show specialist details."""
    name = getattr(args, "name", None)
    if not name:
        print(color("Usage: hermes specialist show <name>", Colors.RED))
        return 1

    cfg = _load_config(name)
    if not cfg:
        print(color(f"Specialist not found: {name}", Colors.RED))
        return 1

    print()
    print(color(f"  {name}", Colors.YELLOW))
    print(f"    Domain:    {cfg.get('domain', '')}")
    print(f"    Description: {cfg.get('description', '')}")
    print(f"    Model:     {cfg.get('model_override') or '(default)'}")
    print(f"    Skills:    {', '.join(cfg.get('skills', [])) or '(none)'}")
    print(f"    Tools:     {', '.join(cfg.get('tools_whitelist', [])) or '(all)'}")
    print(f"    Config:    {_config_path(name)}")
    print(f"    Harness:   {_harness_path(name)}")
    print()
    if cfg.get("system_prompt"):
        print(color("  System prompt:", Colors.DIM))
        for line in cfg["system_prompt"].splitlines():
            print(f"    {line}")
        print()
    return 0


def specialist_edit(args) -> int:
    """Edit a custom specialist's config."""
    _require_tty("specialist edit")
    name = getattr(args, "name", None)
    if not name:
        print(color("Usage: hermes specialist edit <name>", Colors.RED))
        return 1

    cfg = _load_config(name)
    if not cfg:
        print(color(f"Specialist not found: {name}", Colors.RED))
        return 1

    print(color(f"\n  Editing specialist: {name}\n", Colors.CYAN))

    cfg["domain"] = _input_line("Domain", cfg.get("domain", ""))
    cfg["description"] = _input_line("Description", cfg.get("description", ""))
    cfg["model_override"] = _input_line("Model override", cfg.get("model_override") or "") or None

    skills_raw = _input_line("Skills (comma-separated)", ", ".join(cfg.get("skills", [])))
    cfg["skills"] = [s.strip() for s in skills_raw.split(",") if s.strip()]

    tool_names = _available_tool_names()
    current_tools = set(cfg.get("tools_whitelist", []))
    if tool_names and sys.stdin.isatty():
        try:
            from hermes_cli.curses_ui import curses_checklist

            preselected = {i for i, t in enumerate(tool_names) if t in current_tools}
            selected_indices = curses_checklist(
                title="Whitelisted Tools",
                items=tool_names,
                selected=preselected,
            )
            cfg["tools_whitelist"] = [tool_names[i] for i in sorted(selected_indices)]
        except Exception:
            tools_raw = _input_line("Whitelisted tools (comma-separated)", ", ".join(cfg.get("tools_whitelist", [])))
            cfg["tools_whitelist"] = [t.strip() for t in tools_raw.split(",") if t.strip()]
    else:
        tools_raw = _input_line("Whitelisted tools (comma-separated)", ", ".join(cfg.get("tools_whitelist", [])))
        cfg["tools_whitelist"] = [t.strip() for t in tools_raw.split(",") if t.strip()]

    print(color("System prompt (enter blank line to keep current, 'clear' to remove):", Colors.DIM))
    print(color("  (current shown below, edit or leave blank)\n", Colors.DIM))
    for line in cfg.get("system_prompt", "").splitlines():
        print(f"  {line}")
    new_prompt = _input_multiline("New system prompt")
    if new_prompt.strip().lower() == "clear":
        cfg["system_prompt"] = ""
    elif new_prompt.strip():
        cfg["system_prompt"] = new_prompt

    _save_config(name, cfg)
    _write_harness(name, cfg)

    print(color(f"\nUpdated specialist: {name}", Colors.GREEN))
    return 0


def specialist_delete(args) -> int:
    """Delete a custom specialist."""
    name = getattr(args, "name", None)
    if not name:
        print(color("Usage: hermes specialist delete <name>", Colors.RED))
        return 1

    cfg = _load_config(name)
    if not cfg:
        print(color(f"Specialist not found: {name}", Colors.RED))
        return 1

    confirm = input(color(f"Delete specialist '{name}'? [y/N]: ", Colors.YELLOW)).strip().lower()
    if confirm not in ("y", "yes"):
        print("Cancelled.")
        return 0

    _config_path(name).unlink(missing_ok=True)
    _harness_path(name).unlink(missing_ok=True)
    print(color(f"Deleted specialist: {name}", Colors.GREEN))
    return 0


def specialist_command(args) -> int:
    """Handle specialist subcommands."""
    subcmd = getattr(args, "specialist_command", None)

    if subcmd is None or subcmd == "list":
        return specialist_list()

    if subcmd == "create":
        return specialist_create(args)

    if subcmd == "show":
        return specialist_show(args)

    if subcmd == "edit":
        return specialist_edit(args)

    if subcmd == "delete":
        return specialist_delete(args)

    print(color(f"Unknown specialist subcommand: {subcmd}", Colors.RED))
    return 1


def _require_tty(command_name: str) -> None:
    """Exit with a clear error if stdin is not a terminal."""
    if not sys.stdin.isatty():
        print(
            f"Error: 'hermes {command_name}' requires an interactive terminal.\n"
            f"It cannot be run through a pipe or non-interactive subprocess.\n"
            f"Run it directly in your terminal instead.",
            file=sys.stderr,
        )
        sys.exit(1)
