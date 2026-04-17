// ============================================================================
// Question 9.4 — 9. Connectivity & Topology
// Engineer question: "Show all nodes with degree ≥ 4 and their labels."
//
// Operation: list
// Intent: engineering_inventory
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {pid_id:$pid_id}) WHERE n.label <> 'background' WITH n, size([(n)-[:PIPE]-() |1]) AS deg WHERE deg>=4 RETURN n.id, n.label, deg ORDER BY deg DESC
LIMIT 50
