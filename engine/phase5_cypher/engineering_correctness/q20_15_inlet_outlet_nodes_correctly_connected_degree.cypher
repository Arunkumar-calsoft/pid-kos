// ============================================================================
// Question 20.15 — 20. Engineering Correctness Validation
// Engineer question: "Are all inlet/outlet nodes correctly connected (degree=1)?"
//
// Operation: validate
// Intent: external_interfaces
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (io:Node {pid_id:$pid_id, label:'inlet/outlet'}) WITH io, size([(io)-[:PIPE]-() | 1]) AS pipe_degree WHERE pipe_degree <> 1 RETURN io.id AS interface_id, pipe_degree AS actual_degree ORDER BY io.id LIMIT 50
