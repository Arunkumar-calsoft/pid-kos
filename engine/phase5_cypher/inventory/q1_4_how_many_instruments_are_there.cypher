// Q1.4: How many instruments are there?
// Section: 1. Equipment Inventory
// Operation: count
// Intent: instrument_attachment
MATCH (n:Node {label: 'instrumentation', pid_id: $pid_id})
RETURN count(n) AS instrument_count
