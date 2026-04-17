// Q1.10: How many connector nodes are there?
// Section: 1. Equipment Inventory
// Operation: count
// Required keywords: many
// Intent: engineering_inventory
MATCH (n:Node {structural_type: 'CONNECTOR', pid_id: $pid_id})
RETURN count(n) AS connector_count
