// Q18.1: How many isolated nodes are there (degree=0, excluding background)?
// Section: 18. Isolation & Reachability
// Operation: count
// Intent: isolation_reachability
MATCH (n:Node {pid_id: $pid_id})
WHERE n.label <> 'background' AND NOT (n)-[:PIPE]-()
RETURN count(n) AS isolated_node_count
