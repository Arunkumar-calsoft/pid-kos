# phase6_trace/builder/trace_step.py
"""
TraceStep — Single execution step within a Phase-6 trace.

Fix applied vs original:
  - parameters type narrowed from Dict[str, object] to Dict[str, ScalarValue].
    Schema: "parameters": { "additionalProperties": { "type": ["string","number","boolean"] } }
    Dict[str, object] previously accepted nested dicts/lists — schema violation.

  - Removed unused `asdict` import (imported but never called; to_dict()
    builds the dict manually to control the schema-required structure).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Union

ScalarValue = Union[str, int, float, bool]


@dataclass
class TraceStep:
    step_id: int
    intent:  str

    source_phase:   int
    source_file:    str
    source_section: Optional[str]

    query:      str
    parameters: Dict[str, ScalarValue]   # was Dict[str, object]

    rows:                  int
    nodes_touched:         Optional[int] = None
    relationships_touched: Optional[int] = None

    def to_dict(self) -> Dict:
        return {
            "step_id": self.step_id,
            "intent":  self.intent,
            "source": {
                "phase": self.source_phase,
                "file":  self.source_file,
                **({"section": self.source_section} if self.source_section else {}),
            },
            "query":      self.query,
            "parameters": self.parameters,
            "result_stats": {
                "rows": self.rows,
                **({"nodes_touched":         self.nodes_touched}
                   if self.nodes_touched is not None else {}),
                **({"relationships_touched": self.relationships_touched}
                   if self.relationships_touched is not None else {}),
            },
        }