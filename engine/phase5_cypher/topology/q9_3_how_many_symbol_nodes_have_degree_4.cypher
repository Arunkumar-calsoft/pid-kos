// Q9.3: How many SYMBOL nodes have degree ≥ 4?
// Section: 9. Connectivity & Topology
// Operation: count
// Required keywords: degree, symbol
// Intent: connectivity_topology
MATCH (n:Node {pid_id: $pid_id})
WHERE n.structural_type = 'SYMBOL' AND n.label <> 'background'
WITH n, size([(n)-[:PIPE]-() | 1]) AS deg
WHERE deg >= 4
RETURN count(n) AS high_degree_count
