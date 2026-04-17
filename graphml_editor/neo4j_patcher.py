# graphml_editor/neo4j_patcher.py  (STANDALONE — not imported by main pipeline)
#
# Applies and reverts corrections directly in Neo4j without a full pipeline re-run.
#
# Supported ops
# ─────────────
# add_edge       MERGE (a)-[:PIPE]-(b) — marks as source='editor'
# remove_edge    DELETE all PIPE rels between (a) and (b) (both directions)
# relabel        SET n.label = new, recalculate n.structural_type
# set_property   SET n.<safe_key> = value  (key validated against identifier regex)
# rename_node    SET n.id = new  + cascade string references in Annotation nodes
#
# Undo semantics
# ──────────────
# revert() applies the logical inverse of every op.
# For set_property / relabel / rename_node the patch must carry old_value.
# For add_edge undo is remove_edge and vice-versa.
#
# Note on Phase consistency
# ─────────────────────────
# Editor patches fix the Node/PIPE layer in Neo4j immediately.
# PipeSegment, LogicalPipeSegment, Annotation, and Evidence nodes built by
# phases 1–4 are NOT automatically updated.  Re-run phases 1+ after editing
# to fully propagate structural changes.

import re
from typing import Any, Dict, Optional

# Only alphanumeric + underscore identifiers are allowed as property keys
# when used via string formatting in Cypher (prevents injection).
_PROP_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")

# Labels that are drawn as equipment symbols vs topological connectors
_SYMBOL_LABELS: frozenset = frozenset({
    "valve", "tank", "instrumentation", "instrument", "general",
    "arrow", "inlet/outlet", "inferred_check_valve", "inferred_inline_equipment",
})
_CONNECTOR_LABELS: frozenset = frozenset({"connector", "crossing"})

# Annotation string properties that hold node IDs — updated on rename_node
_ANN_NODE_ID_PROPS = ("boundary_node_id", "equipment_id", "node_id")


def _structural_type(label: str) -> str:
    """Derive structural_type from label, matching normalize_nodes.py logic."""
    if label in _SYMBOL_LABELS:
        return "SYMBOL"
    if label in _CONNECTOR_LABELS:
        return "CONNECTOR"
    return "SYMBOL"


def _coerce(value: Any) -> Any:
    """Try to preserve numeric/bool types sent as strings from the UI."""
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    s = str(value)
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


class Neo4jPatcher:
    """
    Applies/reverts a single patch dict against a live Neo4j graph.

    Args:
        loader: Neo4jLoader instance (caller owns lifecycle).
    """

    def __init__(self, loader) -> None:
        self._loader = loader

    def _sess(self):
        return self._loader.driver.session(database=self._loader.database)

    # ── Public apply / revert ─────────────────────────────────────────────────

    def apply(self, patch: Dict) -> bool:
        """Apply patch to Neo4j.  Returns True on success."""
        op  = patch["op"]
        pid = patch["pid_id"]
        nid = patch["node_id"]
        tid = patch.get("target_id")
        key = patch.get("prop_key")
        val = patch.get("new_value")

        with self._sess() as s:
            if op == "add_edge":
                self._add_edge(s, nid, tid, pid)
            elif op == "remove_edge":
                self._remove_edge(s, nid, tid, pid)
            elif op == "relabel":
                self._relabel(s, nid, pid, str(val))
            elif op == "set_property":
                self._set_property(s, nid, pid, str(key), val)
            elif op == "rename_node":
                self._rename_node(s, str(patch.get("old_value", nid)), str(val), pid)
            else:
                raise ValueError(f"Unknown op: {op!r}")
        return True

    def revert(self, patch: Dict) -> bool:
        """Apply the logical inverse of a patch."""
        op = patch["op"]
        if op == "add_edge":
            return self.apply({**patch, "op": "remove_edge"})
        if op == "remove_edge":
            return self.apply({**patch, "op": "add_edge"})
        if op in ("relabel", "set_property"):
            return self.apply({**patch, "new_value": patch.get("old_value"), "old_value": patch.get("new_value")})
        if op == "rename_node":
            return self.apply({
                **patch,
                "node_id":   str(patch.get("new_value")),
                "old_value": str(patch.get("new_value")),
                "new_value": str(patch.get("old_value")),
            })
        return False

    def fetch_node_props(self, pid_id: str, node_id: str) -> Optional[Dict]:
        """Return all Neo4j properties of a node (for the UI properties panel)."""
        with self._sess() as s:
            rec = s.run(
                "MATCH (n:Node {id: $id, pid_id: $p}) RETURN properties(n) AS props",
                id=node_id, p=pid_id,
            ).single()
        if rec is None:
            return None
        return dict(rec["props"])

    # ── Op implementations ────────────────────────────────────────────────────

    @staticmethod
    def _add_edge(session, nid: str, tid: str, pid: str) -> None:
        session.run(
            "MATCH (a:Node {id: $a, pid_id: $p}), (b:Node {id: $b, pid_id: $p}) "
            "MERGE (a)-[r:PIPE]-(b) "
            "ON CREATE SET r.edge_label     = 'editor_patch', "
            "              r.flow_direction  = 'UNKNOWN', "
            "              r.source          = 'editor', "
            "              r.pid_id          = $p",
            a=nid, b=tid, p=pid,
        )

    @staticmethod
    def _remove_edge(session, nid: str, tid: str, pid: str) -> None:
        # Delete in both traversal directions to guarantee full removal.
        session.run(
            "MATCH (a:Node {id: $a, pid_id: $p})-[r:PIPE]-(b:Node {id: $b, pid_id: $p}) DELETE r",
            a=nid, b=tid, p=pid,
        )

    @staticmethod
    def _relabel(session, nid: str, pid: str, label: str) -> None:
        st = _structural_type(label)
        session.run(
            "MATCH (n:Node {id: $id, pid_id: $p}) SET n.label = $lbl, n.structural_type = $st",
            id=nid, p=pid, lbl=label, st=st,
        )

    @staticmethod
    def _set_property(session, nid: str, pid: str, key: str, value: Any) -> None:
        if not _PROP_KEY_RE.match(key):
            raise ValueError(f"Unsafe property key {key!r} — only [a-zA-Z_][a-zA-Z0-9_]* allowed")
        session.run(
            f"MATCH (n:Node {{id: $id, pid_id: $p}}) SET n.{key} = $v",
            id=nid, p=pid, v=_coerce(value),
        )

    @staticmethod
    def _rename_node(session, old_id: str, new_id: str, pid: str) -> None:
        # Rename the id property on the Node node itself
        session.run(
            "MATCH (n:Node {id: $old, pid_id: $p}) SET n.id = $new",
            old=old_id, p=pid, new=new_id,
        )
        # Cascade: update string references in Annotation nodes for this PID
        for prop in _ANN_NODE_ID_PROPS:
            session.run(
                f"MATCH (a:Annotation {{pid_id: $p}}) WHERE a.{prop} = $old SET a.{prop} = $new",
                p=pid, old=old_id, new=new_id,
            )
