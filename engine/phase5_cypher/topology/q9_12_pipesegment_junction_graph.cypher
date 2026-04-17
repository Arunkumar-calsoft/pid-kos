// ============================================================================
// Question 9.12 — 9. Connectivity & Topology
// Engineer question: "Show the PipeSegment junction graph."
//
// Operation: list
// Intent: segment_junction_topology
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ps1:PipeSegment {pid_id:$pid_id})-[r:JOINS_AT]->(ps2:PipeSegment {pid_id:$pid_id}) RETURN ps1.id, ps2.id, r.kind, r.trace_nodes
LIMIT 50
