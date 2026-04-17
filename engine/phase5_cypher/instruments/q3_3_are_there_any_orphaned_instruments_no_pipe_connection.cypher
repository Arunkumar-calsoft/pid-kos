// Q3.3: Are there any orphaned instruments (no pipe connection)?
// Section: 3. Instrument Attachment
// Operation: count
// Intent: drawing_consistency
MATCH (n:Node {label: 'instrumentation', pid_id: $pid_id})
WHERE NOT (n)-[:PIPE]-()
RETURN count(n) AS orphan_instrument_count
