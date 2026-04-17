# phase6_trace/adapters/phase5_adapter.py
#
# Corrections vs original:
#
#   1. Removed non-existent trace.start_block() / trace.event() / trace.end_block() calls.
#      TraceBuilder has no event-bus API. Correct API: add_step(), set_summary(), build().
#
#   2. run_file() now accepts an externally-constructed TraceBuilder and
#      calls add_step() for each Cypher statement executed.
#      Callers are responsible for constructing TraceBuilder (they own
#      question_text, category, context, pid_id, graph_version) and for
#      calling set_summary() and build() after run_file() returns.
#
#   3. pid_id injected into every statement's parameters so all Cypher
#      executions are scoped to the correct P&ID.
#
#   4. Return value changed from file_trace (undefined) to a summary dict
#      containing total_statements and total_rows, for caller use in
#      set_summary().

from pathlib import Path
from typing import List, Dict, Any

from engine.phase6_trace.builder.trace_builder import TraceBuilder
from engine.phase6_trace.builder.trace_step import TraceStep


class Phase5Adapter:
    """
    Adapter that runs Phase-5 static Cypher files and records
    their execution as Phase-6 trace steps.

    Usage:
        builder = TraceBuilder(
            question_text = "Run quality checks",
            category      = "quality",
            context       = {"pid_id": pid_id},
            pid_id        = pid_id,
            graph_version = graph_version,
        )
        adapter  = Phase5Adapter(neo4j_session, pid_id)
        result   = adapter.run_file(Path("10_consistency.cypher"), builder)
        builder.set_summary(
            statement = f"{result['total_rows']} rows checked.",
            counts    = {"rows": result["total_rows"]},
        )
        trace = builder.build()
    """

    def __init__(self, neo4j_session, pid_id: str):
        self.session = neo4j_session
        self.pid_id  = pid_id

    def run_file(
        self,
        cypher_file:   Path,
        trace_builder: TraceBuilder,
        extra_params:  Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:

        if not cypher_file.exists():
            raise FileNotFoundError(cypher_file)

        cypher_text = cypher_file.read_text(encoding="utf-8")
        statements  = self._split_statements(cypher_text)

        total_rows = 0

        for idx, stmt in enumerate(statements, start=1):
            stmt = stmt.strip()
            if not stmt:
                continue

            # All statements must be scoped to pid_id;
            # extra_params allows callers to supply query-specific values
            # (e.g. $start_equipment, $max_hops for reachability queries).
            parameters: Dict[str, Any] = {"pid_id": self.pid_id}
            if extra_params:
                parameters.update(extra_params)

            result    = self.session.run(stmt, parameters)
            rows      = list(result)
            row_count = len(rows)
            total_rows += row_count

            step = TraceStep(
                step_id        = idx,
                intent         = f"Execute statement {idx} from {cypher_file.name}",
                source_phase   = 5,
                source_file    = cypher_file.name,
                source_section = None,
                query          = stmt,
                parameters     = parameters,
                rows           = row_count,
            )
            trace_builder.add_step(step)

        return {
            "total_statements": len(statements),
            "total_rows":       total_rows,
        }

    @staticmethod
    def _split_statements(text: str) -> List[str]:
        """
        Splits Cypher file into executable statements.
        Assumes semicolon-terminated statements.
        """
        return [s.strip() for s in text.split(";") if s.strip()]