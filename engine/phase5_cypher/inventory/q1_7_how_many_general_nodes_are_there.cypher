// Q1.7: How many general nodes are there?
// Section: 1. Equipment Inventory
// Operation: count
// Intent: engineering_inventory
MATCH (n:Node {label: 'general', pid_id: $pid_id})
RETURN count(n) AS general_count
