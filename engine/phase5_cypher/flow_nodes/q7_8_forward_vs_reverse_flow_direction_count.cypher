// ============================================================================
// Question 7.8 — 7. Node-Level Flow State
// Engineer question: "Show the FORWARD vs REVERSE flow direction count at node level."
//
// Operation: count
// Required keywords: forward, reverse
// Intent: engineering_inventory
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {pid_id:$pid_id}) WHERE n.flow_direction IS NOT NULL RETURN n.flow_direction, count(*) AS total ORDER BY total DESC
