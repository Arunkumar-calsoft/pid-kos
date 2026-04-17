// Q9.2: What is the average degree of SYMBOL nodes?
// Section: 9. Connectivity & Topology
// Operation: count
// Required keywords: average, degree, symbol
// Intent: connectivity_topology
MATCH (n:Node {pid_id: $pid_id})
WHERE n.structural_type = 'SYMBOL' AND n.label <> 'background'
WITH n, size([(n)-[:PIPE]-() | 1]) AS deg
RETURN round(avg(deg), 2) AS avg_degree
