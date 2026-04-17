// Q2.5: Are there any isolated valves (degree=0)?
// Section: 2. Valve Placement & Connectivity
// Operation: count
// Intent: drawing_consistency
MATCH (v:Node {label: 'valve', pid_id: $pid_id})
WHERE NOT (v)-[:PIPE]-()
RETURN v.id AS valve_id, v.xmin AS xmin, v.ymin AS ymin
LIMIT 50
