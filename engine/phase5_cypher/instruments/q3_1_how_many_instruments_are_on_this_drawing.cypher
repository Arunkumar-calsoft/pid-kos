// Q3.1: How many instruments are on this drawing?
// Section: 3. Instrument Attachment
// Operation: count
// Intent: instrument_attachment
MATCH (n:Node {label: 'instrumentation', pid_id: $pid_id})
RETURN count(n) AS instrument_count
