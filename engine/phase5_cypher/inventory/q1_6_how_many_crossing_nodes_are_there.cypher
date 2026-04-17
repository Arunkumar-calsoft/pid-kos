// Q1.6: How many crossing nodes are there?
// Section: 1. Equipment Inventory
// Operation: count
// Intent: segment_junction_topology
MATCH (n:Node {label: 'crossing', pid_id: $pid_id})
RETURN count(n) AS crossing_count
