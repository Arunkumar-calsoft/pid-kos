// Q1.3: How many valves are there?
// Section: 1. Equipment Inventory
// Operation: count
// Intent: valve_placement
MATCH (n:Node {label: 'valve', pid_id: $pid_id})
RETURN count(n) AS valve_count
