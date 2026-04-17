// Q3.5: How many instruments are dead-end (degree=1)?
// Section: 3. Instrument Attachment
// Operation: count
// Intent: annotation_requests
MATCH (n:Node {label: 'instrumentation', pid_id: $pid_id})
WITH n, size([(n)-[:PIPE]-() | 1]) AS deg
WHERE deg = 1
RETURN count(n) AS dead_end_instrument_count
