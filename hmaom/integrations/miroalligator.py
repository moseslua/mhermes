"""MiroAlligator integration: spawning, debate, and collaboration patterns.

Adapted from MiroShark's multi-agent orchestration idioms for HMAOM
sub-harnesses.  Provides:

* :class:`HeavyProjectSubHarness` – slices large projects across workers.
* :class:`DebateOrchestrator` – structured Proponent/Opponent/Judge debates.
* :class:`CollaborationCoordinator` – file-level locking + merge detection.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from hmaom.config import SpecialistConfig
from hmaom.protocol.schemas import (
    ContextSlice,
    SpawnRequest,
    TaskDescription,
)
from hmaom.specialists.base import SpecialistHarness


class HeavyProjectSubHarness(SpecialistHarness):
    """A :class:`SpecialistHarness` that shards large codebases across workers.

    Each worker receives a slice of the project (e.g. one module or directory)
    and operates on it independently.  Results are gathered and returned as a
    single payload.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._workers: dict[str, asyncio.Task] = {}

    @property
    def default_tools(self) -> list[str]:
        return ["file_read", "file_write", "spawn", "synthesize"]

    @property
    @property
    def _default_system_prompt(self) -> str:
        return (
            "You are a heavy-project sub-harness.  Your role is to divide large "
            "codebases into slices and delegate each slice to a dedicated worker."
        )

    async def _handle_task(self, request: SpawnRequest) -> Any:
        slices = self._slice_project(request.task.description)
        results: list[Any] = []
        failures: list[str] = []

        for slc in slices:
            child_task = TaskDescription(
                title=f"worker-{self.config.name}-{slc['module']}",
                description=slc["description"],
            )
            ctx = ContextSlice(
                source_agent=self.config.name,
                relevance_score=1.0,
                content=slc["content"],
                source=slc["module"],
            )
            result = await self.spawn_subagent(
                parent_request=request,
                subagent_type="explore",
                task=child_task,
                context_slice=ctx,
            )
            if result.status == "success":
                results.append(result.result)
            else:
                failures.append(result.error or "unknown error")

        return {
            "harness": self.config.name,
            "slices": len(slices),
            "results": results,
            "failures": failures,
        }

    # ── Slicing heuristics ───────────────────────────────────────────────────

    def _slice_project(self, description: str) -> list[dict[str, str]]:
        """Naive project slicer – looks for ``MODULE:`` markers in the description.

        Falls back to a single slice when no markers are present.
        """
        lines = description.splitlines()
        slices: list[dict[str, str]] = []
        current: dict[str, str] | None = None

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("MODULE:"):
                if current:
                    slices.append(current)
                current = {
                    "module": stripped.split(":", 1)[1].strip(),
                    "description": "",
                    "content": "",
                }
            elif current is not None:
                current["description"] += line + "\n"
                current["content"] += line + "\n"

        if current:
            slices.append(current)

        if not slices:
            slices.append(
                {"module": "default", "description": description, "content": description}
            )
        return slices


class DebateOrchestrator:
    """Structured debate orchestration using Proponent / Opponent / Judge.

    1. Spawn Proponent agent (defends position A).
    2. Spawn Opponent agent (defends position B).
    3. Both agents engage in structured debate rounds.
    4. Judge agent evaluates and decides.
    5. Full debate transcript is returned.
    """

    def __init__(
        self,
        harness: SpecialistHarness,
        rounds: int = 3,
    ) -> None:
        self.harness = harness
        self.rounds = max(1, rounds)
        self._transcript: list[dict[str, Any]] = []

    async def run_debate(
        self,
        topic: str,
        position_a: str,
        position_b: str,
    ) -> dict[str, Any]:
        """Run a full debate cycle.

        Returns::

            {
                "topic": str,
                "rounds": int,
                "transcript": [...],
                "verdict": {"winner": ..., "reasoning": ...},
            }
        """
        self._transcript = []
        prev_proponent: dict[str, Any] = {}
        prev_opponent: dict[str, Any] = {}

        for i in range(1, self.rounds + 1):
            proponent = await self._spawn_agent(
                role="proponent",
                topic=topic,
                position=position_a,
                round_num=i,
                prior=prev_opponent.get("argument", ""),
            )
            opponent = await self._spawn_agent(
                role="opponent",
                topic=topic,
                position=position_b,
                round_num=i,
                prior=prev_proponent.get("argument", ""),
            )
            self._transcript.append({
                "round": i,
                "proponent": proponent,
                "opponent": opponent,
            })
            prev_proponent = proponent
            prev_opponent = opponent

        verdict = await self._spawn_judge(topic, self._transcript)
        return {
            "topic": topic,
            "rounds": self.rounds,
            "transcript": self._transcript,
            "verdict": verdict,
        }

    # ── Internal spawners ────────────────────────────────────────────────────

    async def _spawn_agent(
        self,
        role: str,
        topic: str,
        position: str,
        round_num: int,
        prior: str = "",
    ) -> dict[str, Any]:
        desc = (
            f"Role: {role}\n"
            f"Topic: {topic}\n"
            f"Your position: {position}\n"
            f"Opponent's last argument: {prior}\n"
            "Provide a concise, structured argument."
        )
        task = TaskDescription(title=f"{role}-round-{round_num}", description=desc)
        parent = SpawnRequest(
            spawn_id=f"debate-{uuid.uuid4().hex[:8]}",
            parent_id="debate-orchestrator",
            correlation_id=f"debate-{uuid.uuid4().hex}",
            depth=0,
            task=task,
            context_slice=ContextSlice(
                source_agent="debate",
                relevance_score=1.0,
                content="",
                source="debate",
            ),
        )
        result = await self.harness.spawn_subagent(
            parent_request=parent,
            subagent_type="explore",
            task=task,
            context_slice=ContextSlice(
                source_agent="debate",
                relevance_score=1.0,
                content="",
                source="debate",
            ),
        )
        if result.status == "success" and isinstance(result.result, dict):
            return result.result
        return {"argument": str(result.result), "role": role}

    async def _spawn_judge(
        self,
        topic: str,
        transcript: list[dict[str, Any]],
    ) -> dict[str, Any]:
        desc = (
            f"Evaluate the debate on '{topic}' and render a verdict.\n"
            f"Transcript: {transcript}"
        )
        task = TaskDescription(title="judge", description=desc)
        parent = SpawnRequest(
            spawn_id=f"judge-{uuid.uuid4().hex[:8]}",
            parent_id="debate-orchestrator",
            correlation_id=f"judge-{uuid.uuid4().hex}",
            depth=0,
            task=task,
            context_slice=ContextSlice(
                source_agent="debate",
                relevance_score=1.0,
                content="",
                source="debate",
            ),
        )
        result = await self.harness.spawn_subagent(
            parent_request=parent,
            subagent_type="verify",
            task=task,
            context_slice=ContextSlice(
                source_agent="debate",
                relevance_score=1.0,
                content="",
                source="debate",
            ),
        )
        if result.status == "success" and isinstance(result.result, dict):
            return result.result
        return {"verdict": str(result.result), "winner": "undecided"}


class CollaborationCoordinator:
    """Multi-agent codebase collaboration with optimistic locking.

    * Agents **claim** files before editing.
    * The coordinator detects **overlapping edits** (merge conflicts).
    * Accepted proposals are **integrated sequentially**.
    """

    def __init__(self) -> None:
        self._locks: dict[str, str] = {}          # file_path -> agent_id
        self._proposals: dict[str, list[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    # ── File locking ─────────────────────────────────────────────────────────

    async def claim_file(self, agent_id: str, file_path: str) -> bool:
        """Attempt to claim *file_path* for exclusive editing.

        Returns ``True`` on success, ``False`` if already claimed by another agent.
        """
        async with self._lock:
            if file_path in self._locks:
                return False
            self._locks[file_path] = agent_id
            return True

    async def release_file(self, agent_id: str, file_path: str) -> bool:
        """Release a claim.  Only the owning agent may release a file."""
        async with self._lock:
            if self._locks.get(file_path) != agent_id:
                return False
            del self._locks[file_path]
            return True

    # ── Edit proposals ───────────────────────────────────────────────────────

    async def propose_edit(
        self,
        agent_id: str,
        file_path: str,
        diff: str,
    ) -> dict[str, Any]:
        """Submit a diff for *file_path*.  The file must be claimed by *agent_id*."""
        async with self._lock:
            if self._locks.get(file_path) != agent_id:
                return {
                    "status": "rejected",
                    "reason": "file_not_claimed",
                    "file": file_path,
                }
            proposal = {
                "agent_id": agent_id,
                "diff": diff,
                "proposal_id": f"prop-{uuid.uuid4().hex[:8]}",
            }
            self._proposals.setdefault(file_path, []).append(proposal)
            return {
                "status": "accepted",
                "proposal_id": proposal["proposal_id"],
                "file": file_path,
            }

    # ── Conflict detection ───────────────────────────────────────────────────

    def detect_conflicts(self, file_path: str) -> list[dict[str, Any]]:
        """Return a list of overlapping edits for *file_path*."""
        proposals = self._proposals.get(file_path, [])
        conflicts: list[dict[str, Any]] = []
        for i, p1 in enumerate(proposals):
            for p2 in proposals[i + 1 :]:
                if self._diffs_overlap(p1["diff"], p2["diff"]):
                    conflicts.append({
                        "file": file_path,
                        "agents": [p1["agent_id"], p2["agent_id"]],
                        "proposal_ids": [p1["proposal_id"], p2["proposal_id"]],
                    })
        return conflicts

    @staticmethod
    def _diffs_overlap(diff_a: str, diff_b: str) -> bool:
        """Heuristic overlap detector.

        Compares unified-diff hunk headers (``@@``) and shared context lines.
        """
        headers_a = {ln.strip() for ln in diff_a.splitlines() if ln.strip().startswith("@@")}
        headers_b = {ln.strip() for ln in diff_b.splitlines() if ln.strip().startswith("@@")}
        if headers_a and headers_b:
            return bool(headers_a & headers_b)

        # Fallback: shared context lines (lines starting with a space)
        ctx_a = {ln.strip() for ln in diff_a.splitlines() if ln.startswith(" ")}
        ctx_b = {ln.strip() for ln in diff_b.splitlines() if ln.startswith(" ")}
        return bool(ctx_a & ctx_b)

    # ── Integration ──────────────────────────────────────────────────────────

    async def integrate_changes(self, file_path: str) -> dict[str, Any]:
        """Integrate all accepted proposals for *file_path* sequentially.

        Returns a status payload.  If conflicts are detected the integration is
        aborted and the conflict list is returned.
        """
        async with self._lock:
            proposals = self._proposals.get(file_path, [])
            if not proposals:
                return {"status": "no_op", "file": file_path}

            conflicts = self.detect_conflicts(file_path)
            if conflicts:
                return {
                    "status": "conflict",
                    "file": file_path,
                    "conflicts": conflicts,
                }

            applied = [
                {
                    "proposal_id": p["proposal_id"],
                    "agent_id": p["agent_id"],
                    "applied": True,
                }
                for p in proposals
            ]
            self._proposals[file_path] = []
            return {
                "status": "integrated",
                "file": file_path,
                "applied": applied,
            }
