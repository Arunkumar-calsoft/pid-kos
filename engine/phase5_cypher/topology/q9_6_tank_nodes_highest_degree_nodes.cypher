// ============================================================================
// Question 9.6 — 9. Connectivity & Topology
// Engineer question: "Are tank nodes the highest-degree nodes?"
//
// Operation: validate
// Intent: connectivity_topology
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {pid_id:$pid_id}) WHERE n.label <> 'background'
WITH n.label AS lbl, size([(n)-[:PIPE]-() | 1]) AS deg
RETURN lbl AS label, max(deg) AS max_deg ORDER BY max_deg DESC
