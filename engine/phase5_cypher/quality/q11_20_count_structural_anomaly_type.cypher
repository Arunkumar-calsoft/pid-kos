// ============================================================================
// Question 11.20 — 11. Structural Anomalies
// Engineer question: "Show a count of each structural anomaly type."
//
// Operation: count
// Intent: drawing_consistency
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (ann:Annotation {pid_id:$pid_id}) WHERE ann.type IN ['orphan_node','dead_end_pipe_segment','structural_branch','structural_t_junction','structural_high_degree','large_manifold_node','pipe_junction','endpoint_collision','pipe_segment_cycle_member'] RETURN ann.type, count(*) AS total ORDER BY total DESC
