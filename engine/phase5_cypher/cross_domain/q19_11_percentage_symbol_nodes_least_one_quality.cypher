// ============================================================================
// Question 19.11 — 19. Cross-Domain & Combined Questions
// Engineer question: "What percentage of SYMBOL nodes have at least one quality annotation?"
//
// Operation: count
// Required keywords: percentage
// Intent: drawing_consistency
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {pid_id: $pid_id, structural_type: 'SYMBOL'})
OPTIONAL MATCH (ann:Annotation)-[:ANNOTATES]->(n)
WHERE ann.type IN ['orphan_node','dead_end_pipe_segment','structural_branch','structural_t_junction','structural_high_degree','endpoint_collision']
WITH n, count(ann) AS annotation_count
RETURN count(n) AS total_symbols,
       count(CASE WHEN annotation_count > 0 THEN 1 END) AS annotated_symbols,
       round(100.0 * count(CASE WHEN annotation_count > 0 THEN 1 END) / count(n), 1) AS annotated_pct
