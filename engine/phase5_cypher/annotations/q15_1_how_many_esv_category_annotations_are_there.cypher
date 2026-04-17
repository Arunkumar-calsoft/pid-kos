// Q15.1: How many ESV-category annotations are there?
// Section: 15. ESV / KAV Annotation Classification
// Operation: count
// Intent: cross_domain
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.category = 'ESV'
RETURN count(ann) AS esv_count
