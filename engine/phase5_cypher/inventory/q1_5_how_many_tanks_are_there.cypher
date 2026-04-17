// Q1.5: How many tanks are there?
// Section: 1. Equipment Inventory
// Operation: count
// Intent: engineering_inventory
MATCH (n:Node {label: 'tank', pid_id: $pid_id})
RETURN count(n) AS tank_count
