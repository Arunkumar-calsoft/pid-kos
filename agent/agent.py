# agent/agent.py
"""
Phase-8 Agent — Orchestrator

Wires the complete pipeline:

    User Query
        ↓
    Intent Parser          Layer 1   — deterministic, microseconds
        ↓
    Intent Confirmer       Layer 1.5 — LLM correction for unknown_intent only
        ↓                             (no-op pass-through if LLM unavailable)
    Logical Plan Builder   Layer 2   — deterministic, microseconds
        ↓
    Hybrid Optimizer       Layer 3   — deterministic, microseconds
          ├── Template Match      (fast path — hardcoded Cypher)
          ├── Registry File       (Phase 5 pre-validated .cypher)
          ├── Grounded Generator  (LLM — custom entity filters only)
          └── Schema Generator    (deterministic fallback)
        ↓
    Query Runner           Layer 4  — Neo4j I/O, ~50-200ms
        ↓
    Trace Builder          Layer 5a — deterministic, internal only
        ↓
    NL Explainer           Layer 5b — LLM call, ~300-800ms
        ↓                           (falls back to SimpleExplainer)
    Engineer-readable answer

    Query Logger           Cross-cutting — logs every outcome
                           Feeds RegistryEnricher offline pipeline

Changes vs previous version:
  - TraceBuilderProtocol.build() accepts reasoning: Optional[str] = None
  - _execute() passes optimizer_result.reasoning through to trace_builder.build()
    so TraceStep.intent receives the generator's human-readable description
    instead of the opaque query title.
"""
from __future__ import annotations

import logging
from typing import Dict, List, TypedDict, Protocol, Any, Optional, cast

from agent.query_registry import QueryEntry, QueryRegistry
from agent.hybrid_optimizer import OptimizerResult
from agent.query_logger import QueryLogger
from agent.logical_plan_builder import AmbiguityError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Layer Protocols
# ---------------------------------------------------------------------------

class IntentParserProtocol(Protocol):
    def parse(self, question: str, pid_id: str = "UNKNOWN") -> Dict[str, Any]: ...


class IntentConfirmerProtocol(Protocol):
    """
    Layer 1.5 — LLM-powered intent correction.
    Must be a no-op pass-through when LLM is unavailable.
    """
    def confirm(
        self,
        question: str,
        intent: Dict[str, Any],
    ) -> Dict[str, Any]: ...


class LogicalPlanBuilderProtocol(Protocol):
    def build(self, intent: Dict[str, Any]) -> QueryEntry: ...


class HybridOptimizerProtocol(Protocol):
    def optimize(
        self, query_entry: QueryEntry, intent: Dict[str, Any]
    ) -> OptimizerResult: ...


class QueryRunnerProtocol(Protocol):
    def run(
        self,
        cypher: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]: ...


class TraceBuilderProtocol(Protocol):
    def build(
        self,
        *,
        question:      str,
        records:       List[Dict[str, Any]],
        query_meta:    QueryEntry,
        context:       Dict[str, Any],
        pid_id:        str,
        graph_version: str,
        cypher:        Optional[str] = None,
        strategy:      Optional[str] = None,
        reasoning:     Optional[str] = None,   # NEW — from OptimizerResult.reasoning
    ) -> List[Dict[str, Any]]: ...


class ExplainerProtocol(Protocol):
    def explain(
        self,
        *,
        question:    str,
        query_entry: QueryEntry,
        intent:      Dict[str, Any],
        records:     List[Dict[str, Any]],
        traces:      List[Dict[str, Any]],
    ) -> str: ...


# ---------------------------------------------------------------------------
# No-op confirmer — default when no IntentConfirmer is injected
# ---------------------------------------------------------------------------

class _PassthroughConfirmer:
    """Zero-overhead pass-through used when no LLM confirmer is wired."""
    def confirm(
        self,
        question: str,  # noqa: ARG002
        intent: Dict[str, Any],
    ) -> Dict[str, Any]:
        return intent


# ---------------------------------------------------------------------------
# Answer result
# ---------------------------------------------------------------------------

class AnswerResult(TypedDict):
    answer:   str
    traces:   List[Dict[str, Any]]
    records:  List[Dict[str, Any]]
    intent:   Dict[str, Any]
    query:    Dict[str, str]
    strategy: str
    cypher:   str       # the Cypher that was actually executed


# ---------------------------------------------------------------------------
# Ambiguity fallback helper
# ---------------------------------------------------------------------------

# Operation preference for auto-picking among tied candidates.
# "list" and "query" return full detail — prefer these for UI highlighting.
# "count" returns aggregate — only prefer when user explicitly asked "how many".
_OP_PREFERENCE = {"list": 0, "query": 1, "count": 2, "path": 3}


def _pick_best_fallback(
    candidates: List[QueryEntry],
    intent: Dict[str, Any],
) -> QueryEntry:
    """
    Among tied candidates, prefer the one whose boost keywords most closely
    match the question keywords. Among equal matches, prefer shorter boost
    lists (more specific = more precise). Falls back to first by ID.
    """
    kw_set = set(intent.get("keywords", []))

    def _score(c: QueryEntry) -> tuple:
        boost = {k.lower() for k in c.get("boost_keywords", [])}
        kw_overlap = len(boost & kw_set)
        # Penalty for unmatched boost keywords — more unmatched = less specific
        unmatched = len(boost) - kw_overlap
        # Prefer list/query over count unless user said "how many"
        op_rank = _OP_PREFERENCE.get(c.get("operation", ""), 9)
        if not (kw_set & {"how", "many", "count", "total"}):
            if c.get("operation") == "count":
                op_rank = 10
        # Primary: most keyword overlap; then suitable operation; then specificity
        return (-kw_overlap, op_rank, unmatched, c.get("id", ""))

    return min(candidates, key=_score)


# ---------------------------------------------------------------------------
# Phase-8 Agent
# ---------------------------------------------------------------------------

class Phase8Agent:
    """
    Registry-locked, deterministic QA agent with LLM-powered NL output.

    Layer sequence:
      1   IntentParser      — deterministic keyword extraction
      1.5 IntentConfirmer   — optional LLM reclassification (unknown_intent only)
      2   LogicalPlanBuilder — registry-locked query selection
      3   HybridOptimizer   — Cypher resolution (template / registry / LLM / schema)
      4   QueryRunner        — Neo4j execution
      5a  TraceBuilder       — deterministic trace assembly
      5b  NLExplainer        — LLM explanation (with SimpleExplainer fallback)
      x   QueryLogger        — cross-cutting observability
    """

    def __init__(
        self,
        *,
        registry:           QueryRegistry,
        intent_parser:      IntentParserProtocol,
        plan_builder:       LogicalPlanBuilderProtocol,
        optimizer:          HybridOptimizerProtocol,
        query_runner:       QueryRunnerProtocol,
        trace_builder:      TraceBuilderProtocol,
        explainer:          ExplainerProtocol,
        intent_confirmer:   Optional[IntentConfirmerProtocol] = None,
        query_logger:       Optional[QueryLogger] = None,
        ambiguity_resolver: Optional[Any] = None,   # AmbiguityResolver | None
    ) -> None:
        self.registry           = registry
        self.intent_parser      = intent_parser
        self.intent_confirmer: IntentConfirmerProtocol = (
            intent_confirmer if intent_confirmer is not None
            else _PassthroughConfirmer()
        )
        self.plan_builder       = plan_builder
        self.optimizer          = optimizer
        self.query_runner       = query_runner
        self.trace_builder      = trace_builder
        self.explainer          = explainer
        self._logger            = query_logger
        self._ambiguity_resolver = ambiguity_resolver

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def answer(self, question: str, pid_id: str = "UNKNOWN") -> AnswerResult:
        """
        Standard QA flow.
        Layer sequence: IntentParser -> IntentConfirmer -> LogicalPlanBuilder -> _execute()
        """
        # Layer 1: keyword-based extraction (always runs, zero latency)
        intent = self.intent_parser.parse(question, pid_id=pid_id)

        # Log unknown_intent before confirmer can change it
        if intent["intent_type"] == "unknown_intent":
            self._log_unknown_intent(question, intent)

        # Layer 1.5: LLM reclassification (unknown_intent only by default)
        intent = self.intent_confirmer.confirm(question, intent)

        try:
            query_entry = self.plan_builder.build(intent)
        except RuntimeError:
            # No registry entry matched. Build a synthetic QueryEntry so
            # HybridOptimizer can route to SchemaGenerator.
            intent_type = intent.get("intent_type", "unknown_intent")

            keywords: set[str] = set(intent.get("keywords", []))
            if keywords & {"how", "many", "count", "total", "quantity", "number"}:
                op: Optional[str] = "count"
            elif keywords & {"path", "between", "route"}:
                op = "path"
            else:
                op = "list"

            # Synthetic entry — cypher_file="" so Tier 3 guard raises
            # NotImplementedError instead of crashing on path-escape check.
            query_entry = cast(QueryEntry, {
                "id":                f"schema_gen_{intent_type}",
                "intent":            intent_type,
                "title":             f"Schema-generated: {intent_type}",
                "category":          "schema_generated",
                "operation":         op,
                "cypher_file":       "",
                "verified":          True,
                "target_entity":     "",
                "scope":             "global",
                "output_type":       "table",
                "required_keywords": [],
                "boost_keywords":    [],
                "exclude_keywords":  [],
            })

        except AmbiguityError as exc:
            # Layer 2.5: LLM auto-resolution before burdening the user
            if self._ambiguity_resolver is not None:
                res = self._ambiguity_resolver.resolve(question, intent, exc.candidates)
                if res.resolved and res.query_entry is not None:
                    return self._execute(question, intent, res.query_entry)
                # Resolver failed (rate limit, parse error, etc.) — pick the
                # best candidate rather than refusing to answer.
                remaining = res.remaining_candidates or exc.candidates
                if remaining:
                    chosen = _pick_best_fallback(remaining, intent)
                    logger.warning(
                        "[Phase8Agent] AmbiguityResolver failed — auto-selecting "
                        "'%s' from %d tied entries",
                        chosen.get("id", "?"),
                        len(remaining),
                    )
                    return self._execute(question, intent, chosen)
                raise AmbiguityError(
                    candidates = remaining,
                    message    = exc.args[0],
                ) from exc
            # No resolver: pick best candidate as best-effort
            if exc.candidates:
                return self._execute(
                    question, intent,
                    _pick_best_fallback(exc.candidates, intent),
                )
            raise

        return self._execute(question, intent, query_entry)

    def answer_with_query(
        self,
        question:    str,
        query_entry: QueryEntry,
        pid_id:      str = "UNKNOWN",
    ) -> AnswerResult:
        """
        Explicit query path — used after ambiguity resolution in CLI.
        Skips LogicalPlanBuilder and IntentConfirmer (query already resolved).
        """
        intent = self.intent_parser.parse(question, pid_id=pid_id)
        return self._execute(question, intent, query_entry)

    # ------------------------------------------------------------------
    # Core execution pipeline
    # ------------------------------------------------------------------

    def _execute(
        self,
        question:    str,
        intent:      Dict[str, Any],
        query_entry: QueryEntry,
    ) -> AnswerResult:
        # Layer 3: resolve Cypher
        optimizer_result = self.optimizer.optimize(query_entry, intent)

        # Layer 4: execute
        # Always pass pid_id as a Neo4j parameter — Phase 5 .cypher files
        # use $pid_id; other tiers inline it via f-string and Neo4j silently
        # ignores the unused param.
        pid_id = intent.get("pid_id", "UNKNOWN")
        run_params = {"pid_id": pid_id}
        records = self.query_runner.run(optimizer_result.cypher, run_params)

        # Layer 5a: build traces
        # reasoning travels from OptimizerResult → TraceAdapter → TraceStep.intent
        # so the NL explainer sees the generator's graph traversal description.
        traces = self.trace_builder.build(
            question      = question,
            records       = records,
            query_meta    = query_entry,
            context       = intent,
            pid_id        = intent.get("pid_id", "UNKNOWN"),
            graph_version = intent.get("graph_version", "latest"),
            cypher        = optimizer_result.cypher,
            strategy      = optimizer_result.strategy,
            reasoning     = optimizer_result.reasoning,   # NEW
        )

        # Layer 5b: NL explanation
        answer_text = self.explainer.explain(
            question    = question,
            query_entry = query_entry,
            intent      = intent,
            records     = records,
            traces      = traces,
        )

        self._log_success(
            question    = question,
            intent      = intent,
            query_entry = query_entry,
            strategy    = optimizer_result.strategy,
            records     = records,
        )

        return {
            "answer":   answer_text,
            "traces":   traces,
            "records":  records,
            "intent":   intent,
            "strategy": optimizer_result.strategy,
            "cypher":   optimizer_result.cypher,
            "query": {
                "id":       query_entry["id"],
                "title":    query_entry["title"],
                "category": query_entry.get("category", "schema_generated"),
            },
        }

    # ------------------------------------------------------------------
    # Logger helpers (never raise)
    # ------------------------------------------------------------------

    def _log_success(
        self,
        *,
        question:    str,
        intent:      Dict[str, Any],
        query_entry: QueryEntry,
        strategy:    str,
        records:     List[Dict[str, Any]],
    ) -> None:
        if self._logger is None:
            return
        try:
            self._logger.log_success(
                question    = question,
                intent      = intent,
                query_id    = query_entry["id"],
                query_title = query_entry["title"],
                strategy    = strategy,
                records     = len(records),
            )
        except Exception:
            pass

    def _log_unknown_intent(
        self,
        question: str,
        intent:   Dict[str, Any],
    ) -> None:
        if self._logger is None:
            return
        try:
            self._logger.log_unknown_intent(question=question, intent=intent)
        except Exception:
            pass