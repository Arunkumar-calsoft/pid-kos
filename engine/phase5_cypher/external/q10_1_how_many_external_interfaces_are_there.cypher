// Q10.1: How many external interfaces are there?
// Section: 10. External Interfaces
// Operation: count
// Intent: external_interfaces
MATCH (n:Node {label: 'inlet/outlet', pid_id: $pid_id})
RETURN count(n) AS external_interface_count
