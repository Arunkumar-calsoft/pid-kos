// Q6.9: What percentage of LPS have any resolved flow direction?
// Section: 6. Flow Direction & Arrow Evidence
// Operation: count
// Intent: flow_coverage
MATCH (lps:LogicalPipeSegment {pid_id: $pid_id})
WITH count(lps) AS total,
     sum(CASE WHEN lps.flow_state IN ['SEEDED', 'PROPAGATED'] THEN 1 ELSE 0 END) AS resolved
RETURN resolved, total, round(100.0 * resolved / total, 1) AS resolved_pct
