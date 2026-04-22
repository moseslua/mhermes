#!/usr/bin/env python3
"""Plugin Guard — security scanner for externally-sourced plugin packages.

Plugins can execute Python on import and ship dashboard assets consumed by the web UI,
so Hermes scans plugin directories before install/update and before exposing dashboard
extensions. The scanner is intentionally bounded: it performs structural checks,
regex-based threat detection, and invisible-unicode detection for obvious bad patterns.
"""

from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

from tools.skills_guard import (
    Finding,
    INVISIBLE_CHARS,
    SUSPICIOUS_BINARY_EXTENSIONS,
    THREAT_PATTERNS,
    _determine_verdict,
    _unicode_char_name,
)

INSTALL_POLICY = {
    #                  safe      caution    dangerous
    "builtin":       ("allow", "allow",   "block"),
    "community":     ("allow", "block",   "block"),
}

VERDICT_INDEX = {"safe": 0, "caution": 1, "dangerous": 2}

SCANNABLE_EXTENSIONS = {
    ".md", ".txt", ".py", ".sh", ".bash", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts",
    ".rb", ".yaml", ".yml", ".json", ".toml", ".cfg", ".ini", ".conf",
    ".html", ".css", ".xml", ".sql",
}

MAX_FILE_COUNT = 250
MAX_TOTAL_SIZE_KB = 8192
MAX_SINGLE_FILE_KB = 2048


@dataclass
class PluginScanResult:
    plugin_name: str
    source: str
    trust_level: str
    verdict: str
    findings: List[Finding] = field(default_factory=list)
    scanned_at: str = ""
    summary: str = ""


def scan_file(file_path: Path, rel_path: str = "") -> List[Finding]:
    """Scan one plugin file for threat patterns and hidden unicode."""
    if not rel_path:
        rel_path = file_path.name
    rel_path_obj = Path(rel_path)
    suffixes = [suffix.lower() for suffix in rel_path_obj.suffixes]
    if suffixes[-1:] == [".example"] and len(suffixes) >= 2:
        effective_suffix = suffixes[-2]
    else:
        effective_suffix = suffixes[-1] if suffixes else ""
    if effective_suffix not in SCANNABLE_EXTENSIONS:
        return []

    try:
        content = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        return [
            Finding(
                pattern_id="unreadable_scannable_file",
                severity="critical",
                category="structural",
                file=rel_path,
                line=0,
                match=type(exc).__name__,
                description="scannable file could not be read as UTF-8 during plugin scan",
            )
        ]

    findings: list[Finding] = []
    lines = content.split("\n")
    seen: set[tuple[str, int]] = set()

    for pattern, pattern_id, severity, category, description in THREAT_PATTERNS:
        for line_number, line in enumerate(lines, start=1):
            if (pattern_id, line_number) in seen:
                continue
            if re.search(pattern, line, re.IGNORECASE):
                seen.add((pattern_id, line_number))
                matched_text = line.strip()
                if len(matched_text) > 120:
                    matched_text = matched_text[:117] + "..."
                findings.append(
                    Finding(
                        pattern_id=pattern_id,
                        severity=severity,
                        category=category,
                        file=rel_path,
                        line=line_number,
                        match=matched_text,
                        description=description,
                    )
                )

    for line_number, line in enumerate(lines, start=1):
        for char in INVISIBLE_CHARS:
            if char in line:
                findings.append(
                    Finding(
                        pattern_id="invisible_unicode",
                        severity="high",
                        category="injection",
                        file=rel_path,
                        line=line_number,
                        match=f"U+{ord(char):04X} ({_unicode_char_name(char)})",
                        description=(
                            f"invisible unicode character {_unicode_char_name(char)} "
                            "(possible text hiding/injection)"
                        ),
                    )
                )
                break

    return findings


def scan_plugin(plugin_path: Path, source: str = "community") -> PluginScanResult:
    """Scan a plugin directory or file for bounded security issues."""
    plugin_name = plugin_path.name
    trust_level = _resolve_trust_level(source)
    findings: list[Finding] = []

    if plugin_path.is_dir():
        findings.extend(_check_structure(plugin_path))
        for candidate in plugin_path.rglob("*"):
            if candidate.is_symlink():
                continue
            if candidate.is_file():
                rel = str(candidate.relative_to(plugin_path))
                findings.extend(scan_file(candidate, rel))
    elif plugin_path.is_file():
        findings.extend(scan_file(plugin_path, plugin_path.name))

    verdict = _determine_verdict(findings)
    summary = _build_summary(plugin_name, verdict, findings)
    return PluginScanResult(
        plugin_name=plugin_name,
        source=source,
        trust_level=trust_level,
        verdict=verdict,
        findings=findings,
        scanned_at=datetime.now(timezone.utc).isoformat(),
        summary=summary,
    )


def should_allow_plugin_install(result: PluginScanResult) -> Tuple[bool, str]:
    """Apply the plugin install/discovery policy to a scan result."""
    policy = INSTALL_POLICY.get(result.trust_level, INSTALL_POLICY["community"])
    decision = policy[VERDICT_INDEX.get(result.verdict, 2)]
    if decision == "allow":
        return True, f"Allowed ({result.trust_level} source, {result.verdict} verdict)"
    return False, (
        f"Blocked ({result.trust_level} source + {result.verdict} verdict, "
        f"{len(result.findings)} findings)."
    )


def format_scan_report(result: PluginScanResult) -> str:
    """Format a plugin scan result for CLI/logging."""
    lines = [
        f"Plugin scan: {result.plugin_name} ({result.source}/{result.trust_level})  "
        f"Verdict: {result.verdict.upper()}"
    ]
    if result.findings:
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for finding in sorted(result.findings, key=lambda item: severity_order.get(item.severity, 4)):
            sev = finding.severity.upper().ljust(8)
            cat = finding.category.ljust(14)
            loc = f"{finding.file}:{finding.line}".ljust(30)
            lines.append(f"  {sev} {cat} {loc} \"{finding.match[:60]}\"")
        lines.append("")
    allowed, reason = should_allow_plugin_install(result)
    status = "ALLOWED" if allowed else "BLOCKED"
    lines.append(f"Decision: {status} — {reason}")
    return "\n".join(lines)


def content_hash(plugin_path: Path) -> str:
    """Compute a short content hash for a plugin tree."""
    digest = hashlib.sha256()
    if plugin_path.is_dir():
        for candidate in sorted(plugin_path.rglob("*")):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            try:
                digest.update(candidate.read_bytes())
            except OSError:
                continue
    elif plugin_path.is_file():
        digest.update(plugin_path.read_bytes())
    return f"sha256:{digest.hexdigest()[:16]}"


def _check_structure(plugin_dir: Path) -> List[Finding]:
    findings: list[Finding] = []
    file_count = 0
    total_size = 0
    plugin_root = plugin_dir.resolve()

    for candidate in plugin_dir.rglob("*"):
        if not candidate.is_file() and not candidate.is_symlink():
            continue

        rel = str(candidate.relative_to(plugin_dir))
        file_count += 1

        if candidate.is_symlink():
            try:
                resolved = candidate.resolve()
                if not resolved.is_relative_to(plugin_root):
                    findings.append(
                        Finding(
                            pattern_id="symlink_escape",
                            severity="critical",
                            category="traversal",
                            file=rel,
                            line=0,
                            match=f"symlink -> {resolved}",
                            description="symlink points outside the plugin directory",
                        )
                    )
                elif resolved.is_dir():
                    findings.append(
                        Finding(
                            pattern_id="symlinked_directory",
                            severity="high",
                            category="traversal",
                            file=rel,
                            line=0,
                            match=f"symlink dir -> {resolved}",
                            description="symlinked directories are not allowed in plugin packages",
                        )
                    )
                elif resolved.is_file():
                    findings.extend(scan_file(resolved, rel))
            except OSError:
                findings.append(
                    Finding(
                        pattern_id="broken_symlink",
                        severity="medium",
                        category="traversal",
                        file=rel,
                        line=0,
                        match="broken symlink",
                        description="broken or circular symlink",
                    )
                )
            continue

        try:
            size = candidate.stat().st_size
        except OSError:
            continue
        total_size += size

        if size > MAX_SINGLE_FILE_KB * 1024:
            findings.append(
                Finding(
                    pattern_id="oversized_file",
                    severity="medium",
                    category="structural",
                    file=rel,
                    line=0,
                    match=f"{size // 1024}KB",
                    description=f"file is {size // 1024}KB (limit: {MAX_SINGLE_FILE_KB}KB)",
                )
            )

        ext = candidate.suffix.lower()
        if ext in SUSPICIOUS_BINARY_EXTENSIONS:
            findings.append(
                Finding(
                    pattern_id="binary_file",
                    severity="critical",
                    category="structural",
                    file=rel,
                    line=0,
                    match=f"binary: {ext}",
                    description=f"binary/executable file ({ext}) should not be in a plugin",
                )
            )

    if file_count > MAX_FILE_COUNT:
        findings.append(
            Finding(
                pattern_id="too_many_files",
                severity="medium",
                category="structural",
                file="(directory)",
                line=0,
                match=f"{file_count} files",
                description=f"plugin has {file_count} files (limit: {MAX_FILE_COUNT})",
            )
        )
    if total_size > MAX_TOTAL_SIZE_KB * 1024:
        findings.append(
            Finding(
                pattern_id="oversized_plugin",
                severity="high",
                category="structural",
                file="(directory)",
                line=0,
                match=f"{total_size // 1024}KB total",
                description=f"plugin is {total_size // 1024}KB total (limit: {MAX_TOTAL_SIZE_KB}KB)",
            )
        )
    return findings


def _resolve_trust_level(source: str) -> str:
    if source in {"builtin", "bundled"}:
        return "builtin"
    return "community"


def _build_summary(name: str, verdict: str, findings: List[Finding]) -> str:
    if not findings:
        return f"{name}: clean scan, no threats detected"
    categories = sorted({finding.category for finding in findings})
    return f"{name}: {verdict} — {len(findings)} finding(s) in {', '.join(categories)}"
