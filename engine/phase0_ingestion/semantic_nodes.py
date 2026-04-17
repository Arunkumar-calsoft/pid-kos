# engine/phase0_ingestion/semantic_nodes.py
#
# LEGACY MODULE — not called by any run_phase*.py script.
# Semantic labeling is now handled by Phase 3's annotation system.
# Imports fixed from old package paths to current engine layout.

from engine.phase0_ingestion.load_to_neo4j import Neo4jLoader
from engine.domain_knowledge.symbol_dictionary import SYMBOL_DICTIONARY

# Explicit fallback mapping for common labels in your GraphML
LABEL_TO_TYPE = {
    "connector": ("Connector", 0.65),
    "crossing": ("Crossing", 0.70),
    "instrumentation": ("Instrument", 0.65),
    "inlet/outlet": ("Interface", 0.55),
    "general": ("General", 0.40),
    "background": ("Background", 0.30),
    # Add more as needed based on future labels
}

def assign_semantics(driver, database):
    with driver.session(database=database) as session:
        nodes = session.run("MATCH (n:Node) RETURN n.id AS id, n.label AS label")
        for rec in nodes:
            nid, label = rec["id"], (rec["label"] or "").lower().strip()

            sem_type = None
            conf = 0.0

            # Step 1: Explicit fallback for exact or partial matches to your common labels
            matched = False
            for key, (typ, c) in LABEL_TO_TYPE.items():
                if key in label or label in key:  # Relaxed: substring match
                    sem_type = typ
                    conf = c
                    matched = True
                    break

            # Step 2: If no fallback match, try SYMBOL_DICTIONARY with relaxed matching
            if not matched:
                for kw, entry in SYMBOL_DICTIONARY.items():
                    aliases = [a.lower() for a in entry["aliases"]]
                    if any(alias in label or label in alias for alias in aliases):  # Substring + bidirectional
                        sem_type = entry.get("meaning", kw.capitalize())
                        conf = entry["confidence"]
                        break

            # Step 3: Ultimate fallback for true unknowns
            if not sem_type:
                sem_type = "Unknown"
                conf = 0.20  # Lower confidence

            tag = (rec["label"] or f"{sem_type}_{nid}").strip()
            labels = [sem_type] if sem_type != "Unknown" else []

            # Cypher to apply changes (with APOC and WITH clause)
            session.run("""
                MATCH (n:Node {id: $nid})
                SET n.semantic_type = $type,
                    n.tag = $tag,
                    n.semantic_confidence = $conf
                WITH n
                CALL apoc.create.addLabels(n, $labels)
                YIELD node
                RETURN node
            """, nid=nid, type=sem_type, tag=tag, conf=conf, labels=labels)

    print("[Phase 1.7] Semantic node labeling complete")