from neo4j import GraphDatabase

_PUMP_WIDTH_MAX = 100.0
_HX_WIDTH_MAX   = 450.0

driver = GraphDatabase.driver("neo4j://localhost:7687", auth=("neo4j", "awesomepassword.0"))
with driver.session(database="chatbot") as s:

    # Migrate: stamp heat_exchanger on medium-width tank nodes
    result = s.run("""
        MATCH (n:Node {label:'tank'})
        WHERE (n.xmax - n.xmin) >= $pump_max
          AND (n.xmax - n.xmin) < $hx_max
        SET n.functional_label = 'heat_exchanger'
        RETURN count(n) AS c
    """, pump_max=_PUMP_WIDTH_MAX, hx_max=_HX_WIDTH_MAX)
    rec = result.single()
    print(f"Stamped heat_exchanger: {rec['c'] if rec else 0}")

    # Verify final state
    rows = s.run("""
        MATCH (n:Node {label:'tank'})
        RETURN n.id AS id, n.functional_label AS fl,
               round(n.xmax - n.xmin, 0) AS w, round(n.ymax - n.ymin, 0) AS h
        ORDER BY n.id
    """).data()
    print("\nFinal tank node functional_labels:")
    for r in rows:
        print(f"  {str(r['id']):<12}  fl={str(r['fl']):<16}  {r['w']}x{r['h']}")

driver.close()
