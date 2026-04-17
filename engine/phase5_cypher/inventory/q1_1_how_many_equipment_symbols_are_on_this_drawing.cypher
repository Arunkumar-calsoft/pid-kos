// Q1.1: How many equipment symbols are on this drawing?
// Section: 1. Equipment Inventory
// Operation: count
// Required keywords: many
// Intent: engineering_inventory
MATCH (n:Node {pid_id: $pid_id})
WHERE n.structural_type = 'SYMBOL' AND NOT n.label IN ['background', 'connector']
RETURN count(n) AS equipment_count
