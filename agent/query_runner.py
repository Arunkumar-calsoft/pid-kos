# agent/query_runner.py
"""
Query Runner — Layer 4

Executes read-only Cypher strings produced by the HybridOptimizer.
Neo4jLoader is the single source of truth for connection configuration.
"""
from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional
from typing_extensions import LiteralString, cast

from neo4j.exceptions import Neo4jError
from engine.phase0_ingestion.load_to_neo4j import Neo4jLoader

logger = logging.getLogger(__name__)

# Safety limits — prevent DoS via oversized queries or runaway result sets.
# Production server-side query timeout should also be configured in Neo4j:
#   dbms.transaction.timeout = 30s  (in neo4j.conf)
_MAX_QUERY_LEN  = 10_000   # characters — rejects suspiciously large Cypher strings
_MAX_RESULT_ROWS = 1_000   # max records consumed into memory per query


class QueryRunner:

    def __init__(self, loader: Neo4jLoader) -> None:
        self.loader = loader

    def run(
        self,
        cypher: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if len(cypher) > _MAX_QUERY_LEN:
            raise ValueError(
                f"[QueryRunner] Query length {len(cypher)} exceeds limit of "
                f"{_MAX_QUERY_LEN} characters."
            )
        params = params or {}
        try:
            with self.loader.driver.session(
                database=self.loader.database
            ) as session:
                result = session.run(cast(LiteralString, cypher), params)
                rows: List[Dict[str, Any]] = []
                for record in result:
                    rows.append(record.data())
                    if len(rows) >= _MAX_RESULT_ROWS:
                        logger.warning(
                            "[QueryRunner] Result cap hit (%d rows) — "
                            "query may have returned more. Add LIMIT to query.",
                            _MAX_RESULT_ROWS,
                        )
                        break
                return rows
        except Neo4jError as exc:
            raise RuntimeError(
                f"[QueryRunner] Cypher execution failed:\n{cypher}"
            ) from exc

    def run_single_value(
        self,
        cypher: str,
        params: Optional[Dict[str, Any]] = None,
        key: str = "c",
    ) -> Optional[Any]:
        if len(cypher) > _MAX_QUERY_LEN:
            raise ValueError(
                f"[QueryRunner] Query length {len(cypher)} exceeds limit of "
                f"{_MAX_QUERY_LEN} characters."
            )
        params = params or {}
        try:
            with self.loader.driver.session(
                database=self.loader.database
            ) as session:
                record = session.run(cast(LiteralString, cypher), params).single()
                return record.get(key) if record else None
        except Neo4jError as exc:
            raise RuntimeError(
                f"[QueryRunner] Scalar query failed:\n{cypher}"
            ) from exc