// ============================================================================
// Question 20.14 — 20. Engineering Correctness Validation
// Engineer question: "Which valves have potential bypass paths (degree >= 3)?"
//
// Operation: list
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (v:Node {pid_id:$pid_id, label:'valve'}) WITH v, size([(v)-[:PIPE]-() | 1]) AS pipe_degree WHERE pipe_degree >= 3 RETURN v.id AS valve_id, pipe_degree ORDER BY pipe_degree DESC, v.id LIMIT 50
