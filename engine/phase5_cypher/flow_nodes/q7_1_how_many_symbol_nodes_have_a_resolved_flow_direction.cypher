// Q7.1: How many SYMBOL nodes have a resolved flow direction?
// Section: 7. Node-Level Flow State
// Operation: count
// Required keywords: many
// Intent: flow_direction
MATCH (n:Node {pid_id: $pid_id})
WHERE n.structural_type = 'SYMBOL' AND n.flow_direction IS NOT NULL
RETURN count(n) AS resolved_flow_count
