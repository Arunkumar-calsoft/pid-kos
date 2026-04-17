// Q1.9: How many arrow nodes are there?
// Section: 1. Equipment Inventory
// Operation: count
// Required keywords: many
// Intent: engineering_inventory
MATCH (n:Node {label: 'arrow', pid_id: $pid_id})
RETURN count(n) AS arrow_node_count
