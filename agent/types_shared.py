# agent/types_shared.py
"""
Shared Type Definitions

Common types used across multiple agent modules.
Created to prevent circular import dependencies between:
  - grounded_generator.py
  - hybrid_optimizer.py
  - other optimizer components

All dataclasses that are imported by multiple modules should live here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, TYPE_CHECKING

# QueryEntry is imported at runtime (not just TYPE_CHECKING) so that Pylance
# can fully resolve the OptimizerResult dataclass fields.  There is no circular
# import risk because query_registry.py does not import types_shared.
from agent.query_registry import QueryEntry

if TYPE_CHECKING:
    pass  # reserved for future TYPE_CHECKING-only imports


@dataclass
class GeneratorResult:
    """
    What a schema generator emits: a verified Cypher string plus a
    human-readable description of which graph pattern was chosen and why.

    `reasoning` travels through OptimizerResult → TraceAdapter →
    TraceStep.intent → _distill_trace → LLM, giving the NL explainer
    a real traversal description instead of an opaque query title.
    """
    cypher:    str
    reasoning: str


@dataclass
class OptimizerResult:
    """
    Result of HybridOptimizer.optimize() - contains the resolved Cypher
    and metadata about which strategy was used.
    """
    cypher:      str
    strategy:    str        # "template" | "registry_file" | "llm_grounded" | "schema_generated"
    query_entry: QueryEntry  # Properly typed as QueryEntry (not just Dict)
    reasoning:   str = ""   # human-readable description of what was queried
    metadata:    Dict[str, Any] = field(default_factory=dict)