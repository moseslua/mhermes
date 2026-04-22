"""HMAOM Reporter Specialist.



Document generation, formatting, cross-domain synthesis, debate mode.

"""



import json
from typing import Any, Literal



from hmaom.config import SpecialistConfig

from hmaom.protocol.schemas import (

    AgentAddress,
    AgentResult,

    ContextSlice,

    DebateRound,

    SpawnRequest,

    SynthesisRequest,

    SynthesisResult,

    TaskDescription,

)

from hmaom.specialists.base import SpecialistHarness





class ReporterHarness(SpecialistHarness):

    """Reporter domain specialist with document synthesis and debate capabilities."""



    @property

    def default_tools(self) -> list[str]:

        return [

            "file_read",

            "file_write",

            "web_search",

        ]



    @property

    def _default_system_prompt(self) -> str:
        return (
            "You are the Reporter Specialist in the HMAOM mesh. "
            "Your expertise includes document generation, formatting, "
            "and cross-domain synthesis. You reconcile conflicting results, "
            "structure reports, and ensure citations trace back to source agents. "
            "In debate mode, you simulate structured proponent/opponent/judge rounds."
        )



    async def _handle_task(self, request: SpawnRequest) -> Any:

        task = request.task

        desc_lower = task.description.lower()

        

        # Detect debate mode from task description keywords

        is_debate = any(kw in desc_lower for kw in ("debate", "compare", " vs ", " versus "))

        

        if is_debate:

            # Extract topic and two positions from the task

            topic = task.title or task.description

            position_a = "in favor"

            position_b = "against"

            # Try to split on " vs " or " versus " or "compare"

            for splitter in (" vs ", " versus ", "compare ", "compared to "):

                if splitter in desc_lower:

                    parts = task.description.split(splitter, 1)

                    if len(parts) == 2:

                        position_a = parts[0].strip()

                        position_b = parts[1].strip()

                        break

            return await self._synthesize_debate(request, topic, position_a, position_b)

        

        # Standard synthesis: collect sources from the task description
        sources: list[AgentResult] = []
        desc = task.description
        marker = "[HMAOM_SYNTHESIS_SOURCES]:"
        if marker in desc:
            try:
                json_start = desc.index(marker) + len(marker)
                source_data = json.loads(desc[json_start:])
                sources = [
                    AgentResult(
                        source=AgentAddress(
                            harness=s["source"]["harness"],
                            agent=s["source"]["agent"],
                            depth=s["source"]["depth"],
                        ),
                        result=s["result"],
                        confidence=s["confidence"],
                        tokens_used=s.get("tokens_used", 0),
                        time_ms=s.get("time_ms", 0),
                    )
                    for s in source_data
                ]
            except Exception:
                sources = []
        

        if not sources:

            # Fallback: spawn a simple explore subagent to gather info

            explore_result = await self.spawn_subagent(

                parent_request=request,

                subagent_type="explore",

                task=task,

                context_slice=ContextSlice(

                    source_agent="reporter",

                    relevance_score=0.9,

                    content="Document synthesis and formatting.",

                ),

            )

            sources = [

                AgentResult(

                    source=self._agent_address("explore"),

                    result=explore_result.result,

                    confidence=1.0 if explore_result.status == "success" else 0.0,

                    tokens_used=explore_result.tokens_used,

                    time_ms=explore_result.time_ms,

                )

            ]

        

        synth_request = SynthesisRequest(

            correlation_id=request.correlation_id,

            sources=sources,

            synthesis_type="unify",

        )

        return await self._synthesize_standard(synth_request, sources)



    async def _synthesize_standard(

        self,

        request: SynthesisRequest,

        sources: list[AgentResult],

    ) -> SynthesisResult:

        """Standard synthesis: merge results with conflict detection."""

        if len(sources) == 1:

            # Single source: format directly, no conflicts possible

            src = sources[0]

            content = f"# Synthesis Result\n\n{self._format_result(src.result)}\n\n_Source: {src.source}_"

            return SynthesisResult.from_agent_results(

                results=sources,

                content=content,

                confidence=src.confidence,

                tokens_used=src.tokens_used,

            )

        

        # Detect and resolve conflicts across multiple sources

        conflicts = self._detect_conflicts(sources)

        resolution_text = self._resolve_conflicts(conflicts) if conflicts else "No conflicts detected."

        

        # Build synthesized content

        sections: list[str] = ["# Synthesis Result\n"]

        for i, src in enumerate(sources, start=1):

            sections.append(f"## Source {i}: {src.source}\n")

            sections.append(self._format_result(src.result))

            sections.append("")

        

        if conflicts:

            sections.append("## Conflicts Resolved\n")

            sections.append(resolution_text)

            sections.append("")

        

        # Compute aggregate confidence

        avg_confidence = sum(s.confidence for s in sources) / len(sources)

        if conflicts:

            avg_confidence *= max(0.5, 1.0 - len(conflicts) * 0.15)

        

        tokens_used = sum(s.tokens_used for s in sources)

        

        content = "\n".join(sections)

        uncertainty_note = None

        if conflicts and len(conflicts) == len(sources):

            uncertainty_note = "All sources conflict; confidence is low."

        

        return SynthesisResult.from_agent_results(

            results=sources,

            content=content,

            confidence=round(avg_confidence, 3),

            conflicts_resolved=conflicts,

            tokens_used=tokens_used,

            uncertainty_note=uncertainty_note,

        )



    async def _synthesize_debate(

        self,

        request: SpawnRequest,

        topic: str,

        position_a: str,

        position_b: str,

    ) -> SynthesisResult:

        """Debate mode: simulate 2 rounds of proponent/opponent/judge."""

        debate_rounds: list[DebateRound] = []

        total_tokens = 0

        

        for round_num in range(1, 3):

            # Proponent argues for position A

            proponent_task = TaskDescription(

                title=f"Debate Round {round_num} - Proponent",

                description=f"Argue IN FAVOR of: {position_a}\nTopic: {topic}\nBe concise and structured.",

            )

            proponent_result = await self.spawn_subagent(

                parent_request=request,

                subagent_type="explore",

                task=proponent_task,

                context_slice=ContextSlice(

                    source_agent="reporter",

                    relevance_score=0.95,

                    content=f"Debate round {round_num}: proponent for '{position_a}'.",

                ),

            )

            total_tokens += proponent_result.tokens_used

            

            # Opponent argues for position B

            opponent_task = TaskDescription(

                title=f"Debate Round {round_num} - Opponent",

                description=f"Argue IN FAVOR of: {position_b}\nTopic: {topic}\nBe concise and structured.",

            )

            opponent_result = await self.spawn_subagent(

                parent_request=request,

                subagent_type="explore",

                task=opponent_task,

                context_slice=ContextSlice(

                    source_agent="reporter",

                    relevance_score=0.95,

                    content=f"Debate round {round_num}: opponent for '{position_b}'.",

                ),

            )

            total_tokens += opponent_result.tokens_used

            

            # Judge evaluates the round

            judge_task = TaskDescription(

                title=f"Debate Round {round_num} - Judge",

                description=(

                    f"Evaluate this debate round on '{topic}'.\n\n"

                    f"Proponent argument ({position_a}):\n{proponent_result.result}\n\n"

                    f"Opponent argument ({position_b}):\n{opponent_result.result}\n\n"

                    f"Declare a winner: proponent, opponent, or tie. Explain briefly."

                ),

            )

            judge_result = await self.spawn_subagent(

                parent_request=request,

                subagent_type="verify",

                task=judge_task,

                context_slice=ContextSlice(

                    source_agent="reporter",

                    relevance_score=0.95,

                    content=f"Debate round {round_num}: judge verdict.",

                ),

            )

            total_tokens += judge_result.tokens_used

            

            debate_rounds.append(

                DebateRound.from_spawn_results(

                    round_number=round_num,

                    proponent_result=proponent_result,

                    opponent_result=opponent_result,

                    judge_result=judge_result,

                )

            )

        

        # Final verdict: summarize all rounds

        verdict_sections: list[str] = [f"# Debate: {topic}\n"]

        for dr in debate_rounds:

            verdict_sections.append(f"## Round {dr.round_number}\n")

            verdict_sections.append(f"**Proponent ({position_a}):** {dr.proponent_argument}\n")

            verdict_sections.append(f"**Opponent ({position_b}):** {dr.opponent_argument}\n")

            verdict_sections.append(f"**Judge:** {dr.judge_verdict} (Winner: {dr.winner})\n")

        

        # Simple confidence based on judge consistency

        winners = [dr.winner for dr in debate_rounds]

        if all(w == winners[0] for w in winners):

            confidence = 0.85

        elif winners.count("tie") == len(winners):

            confidence = 0.5

        else:

            confidence = 0.65

        

        citations = [self._agent_address("reporter")]

        content = "\n".join(verdict_sections)

        

        return SynthesisResult(

            content=content,

            citations=citations,

            confidence=confidence,

            conflicts_resolved=[],

            tokens_used=total_tokens,

            debate_rounds=[dr.model_dump() for dr in debate_rounds],

        )



    def _detect_conflicts(self, results: list[AgentResult]) -> list[dict]:

        """Heuristically detect contradictions across agent results."""

        conflicts: list[dict] = []

        n = len(results)

        for i in range(n):

            for j in range(i + 1, n):

                a, b = results[i], results[j]

                conflict_type = None

                detail = None

                

                # Boolean contradiction

                if isinstance(a.result, bool) and isinstance(b.result, bool):

                    if a.result != b.result:

                        conflict_type = "boolean_contradiction"

                        detail = f"{a.source} says {a.result}, {b.source} says {b.result}"

                

                # Numeric difference > 10%

                elif isinstance(a.result, (int, float)) and isinstance(b.result, (int, float)):

                    if a.result == 0 and b.result == 0:

                        continue

                    denom = max(abs(a.result), abs(b.result))

                    if denom > 0:

                        diff_ratio = abs(a.result - b.result) / denom

                        if diff_ratio > 0.10:

                            conflict_type = "numeric_discrepancy"

                            detail = (

                                f"{a.source} = {a.result}, {b.source} = {b.result} "

                                f"(diff {diff_ratio:.1%})"

                            )

                

                # String equality check for explicit opposites

                elif isinstance(a.result, str) and isinstance(b.result, str):

                    lower_a, lower_b = a.result.lower().strip(), b.result.lower().strip()

                    opposites = {

                        ("true", "false"), ("yes", "no"), ("pass", "fail"),

                        ("safe", "unsafe"), ("valid", "invalid"),

                    }

                    if (lower_a, lower_b) in opposites or (lower_b, lower_a) in opposites:

                        conflict_type = "semantic_contradiction"

                        detail = f"{a.source} says '{a.result}', {b.source} says '{b.result}'"

                

                if conflict_type:

                    conflicts.append({

                        "type": conflict_type,

                        "sources": [str(a.source), str(b.source)],

                        "detail": detail,

                        "resolution": "pending",

                    })

        return conflicts



    def _resolve_conflicts(self, conflicts: list[dict]) -> str:

        """Generate resolution text for detected conflicts."""

        if not conflicts:

            return "No conflicts detected across sources."

        

        lines: list[str] = [f"Detected {len(conflicts)} conflict(s):\n"]

        for i, c in enumerate(conflicts, start=1):

            lines.append(f"{i}. **{c['type'].replace('_', ' ').title()}**")

            lines.append(f"   - Between: {', '.join(c['sources'])}")

            lines.append(f"   - Detail: {c['detail']}")

            # Simple resolution heuristic: prefer higher-confidence source if available

            resolution = (

                "Resolution: Discrepancy noted; recommend human review or "

                "re-execution with tighter constraints."

            )

            lines.append(f"   - {resolution}")

            lines.append("")

            c["resolution"] = resolution

        return "\n".join(lines)



    @staticmethod

    def _format_result(result: Any) -> str:

        """Format a result for inclusion in synthesis text."""

        if isinstance(result, dict):

            import json

            return f"```json\n{json.dumps(result, indent=2)}\n```"

        return str(result)
