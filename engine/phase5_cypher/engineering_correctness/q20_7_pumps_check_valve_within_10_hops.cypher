// ============================================================================
// Question 20.7 — 20. Engineering Correctness Validation
// Engineer question: "Do all pumps have a check valve within 10 hops downstream? (heuristic check)"
//
// Operation: validate
// Required keywords: pump
// Intent: engineering_correctness
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (pump:Node {pid_id:$pid_id, label:'tank'}) WHERE pump.functional_label = 'pump' OPTIONAL MATCH (pump)-[:ENDPOINT_OF]->(lps1:LogicalPipeSegment)-[:ADJACENT_VIA_NODES*0..10]-(lps2:LogicalPipeSegment)<-[:ENDPOINT_OF]-(cv:Node) WHERE cv.label IN ['valve','tank'] AND (cv.functional_label IN ['check_valve','inferred_check_valve'] OR cv.label = 'valve') WITH pump, collect(DISTINCT cv.id) AS check_valves WHERE size(check_valves) = 0 RETURN pump.id AS pump_without_check_valve, coalesce(pump.functional_label, pump.label) AS equipment_role ORDER BY pump.id LIMIT 50
