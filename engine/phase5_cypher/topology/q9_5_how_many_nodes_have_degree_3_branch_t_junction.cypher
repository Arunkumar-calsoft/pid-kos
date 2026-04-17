// Q9.5: How many nodes have degree = 3 (branch/T-junction)?
// Section: 9. Connectivity & Topology
// Operation: count
// Intent: drawing_consistency
MATCH (n:Node {pid_id: $pid_id})
WHERE NOT (n.label IN ['background', 'connector'])
WITH n, size([(n)-[:PIPE]-() | 1]) AS deg
WHERE deg = 3
RETURN count(n) AS branch_junction_count
