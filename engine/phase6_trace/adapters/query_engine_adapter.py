# phase6_trace/adapters/query_engine_adapter.py
#
# Corrections vs original:
#
#   1. Removed non-existent trace.start_block() / trace.event() / trace.end_block() calls.
#
#   2. Removed direct TraceBuilder construction — canonical path for
#      query result → trace is TraceAdapter.build(). Building TraceBuilder
#      here duplicated category mapping and summary logic that live in
#      TraceAdapter and would have drifted.
#
#   3. Removed local INTENT_TO_CATEGORY map — the authoritative mapping
#      is _INTENT_TO_CATEGORY in agent/trace_adapter.py. Maintaining two
#      maps would cause silent category mismatches as intents are added.
#
#   4. pid_id and graph_version moved to constructor — required for
#      TraceAdapter.build() provenance and for injecting pid_id into params.
#
#   5. reasoning passed through from engine.answer_builder result if present,
#      so TraceAdapter.build() can use it as step.intent (new param added in
#      trace_adapter.py for HybridOptimizer GeneratorResult.reasoning).

from typing import Dict, Any, Optional

from agent.trace_adapter import TraceAdapter


class QueryEngineAdapter:
    """
    Adapter that wraps the query_engine and records
    interactive reasoning as Phase-6 traces via TraceAdapter.
    """

    def __init__(self, query_engine, pid_id: str, graph_version: str,
                 executed_by: str = "interactive"):
        self.engine        = query_engine
        self.pid_id        = pid_id
        self.graph_version = graph_version
        self.executed_by   = executed_by
        self._trace        = TraceAdapter()

    def run(self, user_query: str) -> Dict[str, Any]:

        # 1. Intent detection
        intent = self.engine.intent_fsm.classify(user_query)

        # 2. Parameter extraction
        params = self.engine.param_extractor.extract(user_query, intent)
        params.setdefault("pid_id", self.pid_id)

        # 3. Template / registry entry resolution
        query_meta = self.engine.templates.get(intent)
        cypher     = query_meta.render(params)

        # 4. Execution
        result = self.engine.executor.run(cypher, params)
        rows   = list(result)

        # 5. Answer generation — may carry .reasoning from HybridOptimizer
        answer_result = self.engine.answer_builder.build(intent, rows)
        answer:    str           = answer_result if isinstance(answer_result, str) \
                                   else answer_result.get("answer", "")
        reasoning: Optional[str] = None if isinstance(answer_result, str) \
                                   else answer_result.get("reasoning")

        # 6. Build trace via TraceAdapter — single authoritative path
        context = {
            "intent_type": intent,
            "slots":       params,
        }
        traces = self._trace.build(
            question      = user_query,
            records       = rows,
            query_meta    = query_meta,
            context       = context,
            pid_id        = self.pid_id,
            graph_version = self.graph_version,
            cypher        = cypher,
            strategy      = query_meta.get("strategy"),
            reasoning     = reasoning,
        )

        return {
            "intent":     intent,
            "parameters": params,
            "answer":     answer,
            "rows":       rows,
            "traces":     traces,
        }