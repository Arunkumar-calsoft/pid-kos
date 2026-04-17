// Q1.14: How many background (noise) nodes are there?
// Section: 1. Equipment Inventory
// Operation: count
// Intent: engineering_inventory
MATCH (n:Node {label: 'background', pid_id: $pid_id})
RETURN count(n) AS background_count
