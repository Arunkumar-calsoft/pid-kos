import os
import yaml
import random
import cv2
from neo4j import GraphDatabase

# --------------------------------------------------
# Paths
# --------------------------------------------------
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

IMAGE_PATH = os.path.join(ROOT_DIR, "data", "2.png")
OUTPUT_PATH = os.path.join(ROOT_DIR, "temp_connection_inspection.png")
CONFIG_PATH = os.path.join(ROOT_DIR, "config", "neo4j.yaml")

# --------------------------------------------------
# Load Neo4j config
# --------------------------------------------------
with open(CONFIG_PATH, "r") as f:
    cfg = yaml.safe_load(f)

neo = cfg["neo4j"]

NEO4J_URI = neo["uri"]
NEO4J_USER = neo["user"]
NEO4J_PASSWORD = neo["password"]
NEO4J_DB = neo.get("database", "neo4j")

# --------------------------------------------------
# Neo4j Driver
# --------------------------------------------------
driver = GraphDatabase.driver(
    NEO4J_URI,
    auth=(NEO4J_USER, NEO4J_PASSWORD)
)

# --------------------------------------------------
# Utility
# --------------------------------------------------
def random_color():
    return (
        random.randint(50, 255),
        random.randint(50, 255),
        random.randint(50, 255),
    )


def extract_bbox(props):
    """
    Resolve bbox from known property formats.
    Returns (xmin, ymin, xmax, ymax) or None.
    """

    # Format A: d1..d4
    if all(k in props for k in ("d1", "d2", "d3", "d4")):
        return (
            int(props["d1"]),
            int(props["d2"]),
            int(props["d3"]),
            int(props["d4"]),
        )

    # Format B: d5..d8
    if all(k in props for k in ("d5", "d6", "d7", "d8")):
        return (
            int(props["d5"]),
            int(props["d6"]),
            int(props["d7"]),
            int(props["d8"]),
        )

    # Format C: xmin/xmax
    if all(k in props for k in ("xmin", "ymin", "xmax", "ymax")):
        return (
            int(props["xmin"]),
            int(props["ymin"]),
            int(props["xmax"]),
            int(props["ymax"]),
        )

    return None


# --------------------------------------------------
# Main
# --------------------------------------------------
def main():
    img = cv2.imread(IMAGE_PATH)
    if img is None:
        raise RuntimeError(f"Failed to load image: {IMAGE_PATH}")

    overlay = img.copy()

    with driver.session(database=NEO4J_DB) as session:
        rows = session.run("""
            MATCH (j:Junction:SMART)<-[:CONNECTS_TO_JUNCTION]-(n)
            WHERE
                n.d1 IS NOT NULL
             OR n.d5 IS NOT NULL
             OR n.xmin IS NOT NULL
            RETURN
                j.geometry_hash AS gh,
                collect({
                    id: coalesce(n.id, n.tag, 'UNKNOWN'),
                    labels: labels(n),
                    props: properties(n)
                }) AS nodes
        """).data()

    print(f"[INFO] Junction groups found: {len(rows)}")

    total_nodes = 0
    bbox_nodes = 0
    drawn_boxes = 0

    for row in rows:
        nodes = row["nodes"]

        # Ignore trivial junctions
        if len(nodes) <= 1:
            continue

        color = random_color()

        for n in nodes:
            total_nodes += 1

            bbox = extract_bbox(n["props"])
            if bbox is None:
                continue

            bbox_nodes += 1
            xmin, ymin, xmax, ymax = bbox

            cv2.rectangle(
                overlay,
                (xmin, ymin),
                (xmax, ymax),
                color,
                2
            )

            cv2.putText(
                overlay,
                n["id"],
                (xmin, max(ymin - 5, 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                color,
                1,
                cv2.LINE_AA
            )

            drawn_boxes += 1

    print(f"[DBG] total nodes seen: {total_nodes}, with bbox: {bbox_nodes}")

    if drawn_boxes == 0:
        print("[WARN] No node bbox could be resolved from database properties. Nothing to draw.")

    cv2.imwrite(OUTPUT_PATH, overlay)
    print(f"[OK] Saved inspection overlay → {OUTPUT_PATH}")
    print(f"[INFO] Total boxes drawn: {drawn_boxes}")

    driver.close()


if __name__ == "__main__":
    main()
