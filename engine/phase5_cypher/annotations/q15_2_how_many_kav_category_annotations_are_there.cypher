// Q15.2: How many KAV-category annotations are there?
// Section: 15. ESV / KAV Annotation Classification
// Operation: count
// Intent: cross_domain
MATCH (ann:Annotation {pid_id: $pid_id})
WHERE ann.category = 'KAV'
RETURN count(ann) AS kav_count
