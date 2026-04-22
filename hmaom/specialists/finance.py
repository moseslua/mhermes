"""HMAOM Finance Specialist.

Quant analysis, risk modeling, market data, portfolio optimization.
"""

from typing import Any

from hmaom.config import SpecialistConfig
from hmaom.protocol.schemas import SpawnRequest, TaskDescription, ContextSlice
from hmaom.specialists.base import SpecialistHarness


class FinanceHarness(SpecialistHarness):
    """Finance domain specialist with quant and risk modeling capabilities."""

    @property
    def default_tools(self) -> list[str]:
        return [
            "web_search",
            "execute_code",
            "file_read",
            "file_write",
        ]

    @property
    def _default_system_prompt(self) -> str:
        return (
            "You are the Finance Specialist in the HMAOM mesh. "
            "Your expertise includes quantitative analysis, risk modeling, "
            "market data interpretation, and portfolio optimization. "
            "You have access to web search for real-time market data, "
            "and a Python execution environment for numerical computation. "
            "Always cite your data sources and note model assumptions."
        )

    async def _handle_task(self, request: SpawnRequest) -> Any:
        """Handle finance-specific tasks."""
        task = request.task
        desc = task.description.lower()

        # Route to appropriate subagent based on task content
        if any(term in desc for term in ["black-scholes", "option", "derivative", "pricing"]):
            return await self._handle_options_pricing(request)
        elif any(term in desc for term in ["risk", "var", "volatility", "stress test"]):
            return await self._handle_risk_analysis(request)
        elif any(term in desc for term in ["portfolio", "allocation", "optimization", "efficient frontier"]):
            return await self._handle_portfolio_optimization(request)
        elif any(term in desc for term in ["market", "ticker", "stock", "price", "data"]):
            return await self._handle_market_data(request)
        else:
            # General finance analysis
            return await self._handle_general_finance(request)

    async def _handle_options_pricing(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="calculate",
            task=TaskDescription(
                title=f"Options pricing: {request.task.title}",
                description=request.task.description,
                expected_output_schema={"type": "object", "properties": {"price": {"type": "number"}}},
            ),
            context_slice=ContextSlice(
                source_agent="finance",
                relevance_score=0.95,
                content="Using Black-Scholes or binomial tree models as appropriate.",
                memory_keys=["finance/options"],
            ),
        )
        return result.result

    async def _handle_risk_analysis(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="calculate",
            task=TaskDescription(
                title=f"Risk analysis: {request.task.title}",
                description=request.task.description,
            ),
            context_slice=ContextSlice(
                source_agent="finance",
                relevance_score=0.95,
                content="VaR, CVaR, and stress testing methodologies.",
                memory_keys=["finance/risk"],
            ),
        )
        return result.result

    async def _handle_portfolio_optimization(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="calculate",
            task=TaskDescription(
                title=f"Portfolio optimization: {request.task.title}",
                description=request.task.description,
            ),
            context_slice=ContextSlice(
                source_agent="finance",
                relevance_score=0.95,
                content="Mean-variance optimization, Sharpe ratio maximization.",
                memory_keys=["finance/portfolio"],
            ),
        )
        return result.result

    async def _handle_market_data(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="explore",
            task=TaskDescription(
                title=f"Market data: {request.task.title}",
                description=request.task.description,
            ),
            context_slice=ContextSlice(
                source_agent="finance",
                relevance_score=0.9,
                content="Search for current market data and historical prices.",
                memory_keys=["finance/market"],
            ),
        )
        return result.result

    async def _handle_general_finance(self, request: SpawnRequest) -> Any:
        result = await self.spawn_subagent(
            parent_request=request,
            subagent_type="explore",
            task=request.task,
            context_slice=ContextSlice(
                source_agent="finance",
                relevance_score=0.8,
                content="General financial analysis and research.",
            ),
        )
        return result.result
