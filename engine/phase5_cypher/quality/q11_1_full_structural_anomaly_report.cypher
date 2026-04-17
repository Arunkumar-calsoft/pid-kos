// ============================================================================
// Question 11.1 — 11. Structural Anomalies
// Engineer question: "Give me a full structural anomaly report."
//
// Operation: list
// Intent: drawing_consistency
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {pid_id:$pid_id})-[:ANNOTATES]->(t) WHERE ann.type IN ['orphan_node','dead_end_pipe_segment','structural_branch','structural_t_junction','structural_high_degree','large_manifold_node','pipe_junction','endpoint_collision','pipe_segment_cycle_member'] RETURN ann.type, labels(t), elementId(t) AS element_id
LIMIT 50
