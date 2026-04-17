// ============================================================================
// Question 10.11 — 10. External Interfaces
// Engineer question: "Show annotation role property values on LPS segments connected to interface nodes."
//
// Operation: list
// Intent: external_interfaces
// Source: PID Question Catalogue v5
// ============================================================================

MATCH (n:Node {label:'inlet/outlet', pid_id:$pid_id})-[:ENDPOINT_OF]->(lps)<-[:ANNOTATES]-(ann) WHERE ann.role IS NOT NULL RETURN n.id, ann.role
LIMIT 50
