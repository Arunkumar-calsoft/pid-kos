import os
import yaml
import cv2
from neo4j import GraphDatabase

# --------------------------------------------------
# Paths
# --------------------------------------------------
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

IMAGE_PATH = os.path.join(ROOT_DIR, "data", "2.png")
OUTPUT_PATH = os.path.join(ROOT_DIR, "temp_annotation_inspection.png")
CONFIG_PATH = os.path.join(ROOT_DIR, "config", "neo4j.yaml")

# --------------------------------------------------
# Load Neo4j config (NESTED YAML)
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
# Visualization Logic
# --------------------------------------------------
def visualize_annotated_pid():
    img = cv2.imread(IMAGE_PATH)

    if img is None:
        raise RuntimeError(f"Failed to load image: {IMAGE_PATH}")

    height, width = img.shape[:2]

    with driver.session(database=NEO4J_DB) as session:
        result = session.run(
            """
            MATCH (n)
            OPTIONAL MATCH (a:Annotation)-[:ANNOTATES]->(n)
            WHERE n.bbox IS NOT NULL
            RETURN
                n.id          AS node_id,
                labels(n)[0]  AS node_label,
                n.bbox        AS bbox,
                a.value       AS annotation,
                a.confidence  AS confidence
            """
        )

        for r in result:
            bbox = r["bbox"]
            if not bbox or len(bbox) != 4:
                continue

            x1, y1, x2, y2 = map(int, bbox)

            # Clamp coordinates
            x1 = max(0, min(x1, width - 1))
            x2 = max(0, min(x2, width - 1))
            y1 = max(0, min(y1, height - 1))
            y2 = max(0, min(y2, height - 1))

            annotation = r["annotation"] or "UNANNOTATED"
            confidence = r["confidence"]

            label_text = annotation
            if confidence is not None:
                label_text += f" ({confidence:.2f})"

            # Color scheme
            if annotation == "UNANNOTATED":
                color = (0, 0, 255)    # Red
            else:
                color = (0, 255, 0)    # Green

            # Bounding box
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)

            # Label background
            (tw, th), _ = cv2.getTextSize(
                label_text,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                1
            )

            cv2.rectangle(
                img,
                (x1, y1 - th - 6),
                (x1 + tw + 6, y1),
                color,
                -1
            )

            # Label text
            cv2.putText(
                img,
                label_text,
                (x1 + 3, y1 - 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (0, 0, 0),
                1,
                cv2.LINE_AA
            )

    cv2.imwrite(OUTPUT_PATH, img)
    print(f"[OK] Annotated P&ID written to:\n{OUTPUT_PATH}")

# --------------------------------------------------
# Entry point
# --------------------------------------------------
if __name__ == "__main__":
    visualize_annotated_pid()
