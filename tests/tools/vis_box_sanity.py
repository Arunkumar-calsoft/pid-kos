import os
import yaml
import cv2
from neo4j import GraphDatabase

# --------------------------------------------------
# Paths
# --------------------------------------------------
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

IMAGE_PATH = os.path.join(ROOT_DIR, "data", "2.png")
OUTPUT_PATH = os.path.join(ROOT_DIR, "temp_bbox_overlay.png")
CONFIG_PATH = os.path.join(ROOT_DIR, "config", "neo4j.yaml")

# --------------------------------------------------
# Load Neo4j config
# --------------------------------------------------
with open(CONFIG_PATH, "r") as f:
    cfg = yaml.safe_load(f)

neo = cfg["neo4j"]

driver = GraphDatabase.driver(
    neo["uri"],
    auth=(neo["user"], neo["password"])
)

# --------------------------------------------------
# Load image
# --------------------------------------------------
img = cv2.imread(IMAGE_PATH)
if img is None:
    raise RuntimeError(f"Could not load image: {IMAGE_PATH}")

H, W, _ = img.shape

# --------------------------------------------------
# Cypher: fetch ANY bbox style
# --------------------------------------------------
QUERY = """
MATCH (n)
WHERE
    (
        n.xmin IS NOT NULL AND n.ymin IS NOT NULL
        AND n.xmax IS NOT NULL AND n.ymax IS NOT NULL
    )
    OR
    (
        n.bbox_xmin IS NOT NULL AND n.bbox_ymin IS NOT NULL
        AND n.bbox_xmax IS NOT NULL AND n.bbox_ymax IS NOT NULL
    )
    OR
    (
        n.x IS NOT NULL AND n.y IS NOT NULL
        AND n.w IS NOT NULL AND n.h IS NOT NULL
    )
RETURN
    labels(n) AS labels,
    coalesce(n.tag, n.id, n.name, 'UNKNOWN') AS label,

    n.xmin AS xmin, n.ymin AS ymin,
    n.xmax AS xmax, n.ymax AS ymax,

    n.bbox_xmin AS bxmin, n.bbox_ymin AS bymin,
    n.bbox_xmax AS bxmax, n.bbox_ymax AS bymax,

    n.x AS x, n.y AS y,
    n.w AS w, n.h AS h
"""

# --------------------------------------------------
# Draw boxes
# --------------------------------------------------
box_count = 0

with driver.session(database=neo.get("database", "neo4j")) as session:
    rows = session.run(QUERY)

    for r in rows:
        label = r["label"]

        # ---- Resolve bbox ----
        if r["xmin"] is not None:
            x1, y1, x2, y2 = r["xmin"], r["ymin"], r["xmax"], r["ymax"]

        elif r["bxmin"] is not None:
            x1, y1, x2, y2 = r["bxmin"], r["bymin"], r["bxmax"], r["bymax"]

        elif r["x"] is not None:
            x1 = r["x"]
            y1 = r["y"]
            x2 = r["x"] + r["w"]
            y2 = r["y"] + r["h"]

        else:
            continue

        # ---- Clamp ----
        x1, y1 = int(max(0, x1)), int(max(0, y1))
        x2, y2 = int(min(W, x2)), int(min(H, y2))

        if x2 - x1 < 2 or y2 - y1 < 2:
            continue

        # ---- Draw ----
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(
            img,
            label,
            (x1, max(0, y1 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (255, 0, 0),
            1,
            cv2.LINE_AA
        )

        box_count += 1

# --------------------------------------------------
# Save
# --------------------------------------------------
cv2.imwrite(OUTPUT_PATH, img)

print(f"[OK] Saved bbox overlay → {OUTPUT_PATH}")
print(f"[INFO] Total boxes drawn: {box_count}")
