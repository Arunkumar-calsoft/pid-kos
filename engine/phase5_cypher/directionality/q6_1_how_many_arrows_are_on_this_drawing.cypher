// Q6.1: How many arrows are on this drawing?
// Section: 6. Flow Direction & Arrow Evidence
// Operation: count
// Intent: engineering_inventory
MATCH (a:Arrow {pid_id: $pid_id})
RETURN count(a) AS arrow_count
