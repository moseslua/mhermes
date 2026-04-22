"""HMAOM Sandbox Management.

Per-harness isolation using git worktrees and FUSE overlays.
Matches the oh-my-pi isolation backend patterns.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
import re

from hmaom.config import SpecialistConfig


class SandboxManager:
    """Manages sandboxed execution environments for specialists and subagents.

    Isolation levels:
    - none: No isolation (gateway router only)
    - git-worktree: Git worktree for filesystem isolation
    - fuse-overlay: FUSE overlay for full filesystem sandboxing
    """

    def __init__(self, base_dir: Optional[str] = None) -> None:
        self.base_dir = Path(base_dir or tempfile.gettempdir()) / "hmaom-sandboxes"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._active_sandboxes: dict[str, Path] = {}
    @staticmethod
    def _sanitize_name(name: str) -> str:
        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
        if not sanitized or sanitized.startswith('_'):
            raise ValueError(f"Invalid name: {name}")
        return sanitized

    def create(
        self,
        harness_name: str,
        agent_name: str,
        isolation: str = "git-worktree",
        source_dir: Optional[Path] = None,
    ) -> Path:
        """Create a sandbox for an agent and return its working directory."""
        harness_name = self._sanitize_name(harness_name)
        agent_name = self._sanitize_name(agent_name)
        sandbox_id = f"{harness_name}-{agent_name}-{os.urandom(4).hex()}"
        sandbox_path = self.base_dir / sandbox_id
        sandbox_path.mkdir(parents=True, exist_ok=True)

        if isolation == "git-worktree" and source_dir is not None:
            self._setup_git_worktree(sandbox_path, source_dir)
        elif isolation == "fuse-overlay":
            # FUSE overlay would require additional setup
            self._setup_basic_overlay(sandbox_path)
        else:
            # No isolation or basic directory
            pass

        self._active_sandboxes[sandbox_id] = sandbox_path
        return sandbox_path

    def _setup_git_worktree(self, sandbox_path: Path, source_dir: Path) -> None:
        """Set up a git worktree for filesystem isolation."""
        git_dir = source_dir / ".git"
        if git_dir.exists():
            try:
                subprocess.run(
                    ["git", "worktree", "add", str(sandbox_path)],
                    cwd=str(source_dir),
                    check=True,
                    capture_output=True,
                )
            except (subprocess.CalledProcessError, FileNotFoundError):
                # Fallback: simple copy
                self._copy_tree(source_dir, sandbox_path)
        else:
            self._copy_tree(source_dir, sandbox_path)

    def _setup_basic_overlay(self, sandbox_path: Path) -> None:
        """Set up a basic overlay directory structure."""
        (sandbox_path / "upper").mkdir(exist_ok=True)
        (sandbox_path / "work").mkdir(exist_ok=True)

    def _copy_tree(self, src: Path, dst: Path) -> None:
        """Copy a directory tree, respecting .gitignore if present."""
        if not dst.exists():
            dst.mkdir(parents=True, exist_ok=True)

        ignore_patterns = self._read_gitignore(src)

        for item in src.rglob("*"):
            if item.is_file():
                rel = item.relative_to(src)
                if self._should_ignore(rel, ignore_patterns):
                    continue
                dest = dst / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)

    def _read_gitignore(self, source_dir: Path) -> list[str]:
        """Read .gitignore patterns from source directory."""
        gitignore = source_dir / ".gitignore"
        if not gitignore.exists():
            return []
        patterns = []
        for line in gitignore.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
        return patterns

    def _should_ignore(self, rel_path: Path, patterns: list[str]) -> bool:
        """Check if a relative path matches any gitignore pattern."""
        path_str = str(rel_path)
        for pattern in patterns:
            if pattern.endswith("/"):
                if path_str.startswith(pattern.rstrip("/") + "/"):
                    return True
            elif pattern in path_str or path_str.endswith(pattern):
                return True
        return False

    def destroy(self, sandbox_path: Path) -> None:
        """Destroy a sandbox and clean up resources."""
        # Remove from active tracking
        for sid, path in list(self._active_sandboxes.items()):
            if path == sandbox_path:
                del self._active_sandboxes[sid]
                break

        # Try git worktree removal first
        git_file = sandbox_path / ".git"
        if git_file.exists():
            try:
                subprocess.run(
                    ["git", "worktree", "remove", "-f", str(sandbox_path)],
                    check=False,
                    capture_output=True,
                )
                return
            except FileNotFoundError:
                pass

        # Fallback: rm -rf
        if sandbox_path.exists():
            shutil.rmtree(sandbox_path, ignore_errors=True)

    def destroy_all(self) -> None:
        """Destroy all active sandboxes."""
        for path in list(self._active_sandboxes.values()):
            self.destroy(path)
        self._active_sandboxes.clear()

    def list_active(self) -> dict[str, str]:
        """List all active sandboxes."""
        return {sid: str(path) for sid, path in self._active_sandboxes.items()}
