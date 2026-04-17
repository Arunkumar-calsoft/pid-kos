// ============================================================================
// Question 4.13 — 4. Pipe Segments (Physical)
// Engineer question: "Show junctions shared between pipe segments."
//
// Operation: list
// Required keywords: junction
// Intent: segment_junction_topology
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ps1:PipeSegment {pid_id:$pid_id})-[r:JOINS_AT]->(ps2:PipeSegment {pid_id:$pid_id}) RETURN ps1.id, ps2.id, r.kind, r.trace_nodes
LIMIT 50
