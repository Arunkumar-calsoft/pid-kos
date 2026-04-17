class GraphTraceTools:
    def __init__(self, neo4j_loader):
        self.neo4j = neo4j_loader

    def run_trace(self, intent: dict) -> list:
        """
        Connectivity trace using the PIPE relationship (Node-level adjacency).
        PIPE replaces the old CONNECTED_TO — it is the correct undirected
        edge between Node records in the PID graph.

        Traversal excludes background nodes (structural noise, degree=0).
        """
        start_id = intent.get("slots", {}).get("tag")

        if start_id:
            query = (
                f'MATCH (start:Node {{id: "{start_id}"}}) '
                "MATCH path = (start)-[:PIPE*1..8]-(end:Node) "
                "WHERE end.label <> 'background' AND end <> start "
                "RETURN [n IN nodes(path) | n.id] AS node_ids, "
                "       [n IN nodes(path) | n.label] AS node_labels, "
                "       length(path) AS hops "
                "ORDER BY hops LIMIT 10"
            )
        else:
            # Generic: show connected SYMBOL pairs
            query = (
                "MATCH (s:Node)-[:PIPE]->(t:Node) "
                "WHERE s.structural_type = 'SYMBOL' "
                "  AND t.label <> 'background' "
                "RETURN s.id AS from_node, t.id AS to_node, "
                "       s.label AS from_type, t.label AS to_type "
                "LIMIT 10"
            )

        records = self.neo4j.run(query)

        traces = []
        for r in records:
            if "node_ids" in r:
                traces.append({
                    "summary": f"Path of {r.get('hops', 0)} hops found",
                    "nodes":   r["node_ids"],
                    "labels":  r["node_labels"],
                })
            else:
                traces.append({
                    "summary": "PIPE connection found",
                    "from":    r.get("from_node"),
                    "to":      r.get("to_node"),
                    "from_type": r.get("from_type"),
                    "to_type":   r.get("to_type"),
                })

        return traces