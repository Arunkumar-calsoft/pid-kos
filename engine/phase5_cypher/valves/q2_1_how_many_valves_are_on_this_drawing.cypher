// Q2.1: How many valves are on this drawing?
// Section: 2. Valve Placement & Connectivity
// Operation: count
// Intent: valve_placement
MATCH (n:Node {label: 'valve', pid_id: $pid_id})
RETURN count(n) AS valve_count
