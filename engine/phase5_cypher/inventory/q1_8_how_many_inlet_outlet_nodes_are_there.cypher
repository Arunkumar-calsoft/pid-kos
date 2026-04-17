// Q1.8: How many inlet/outlet nodes are there?
// Section: 1. Equipment Inventory
// Operation: count
// Intent: external_interfaces
MATCH (n:Node {label: 'inlet/outlet', pid_id: $pid_id})
RETURN count(n) AS inlet_outlet_count
