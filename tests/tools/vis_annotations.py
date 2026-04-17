"""
Temporary visualization:
Shows which node is annotated as what, with confidence.

This is a DEBUG / INSPECTION tool.
"""

import sys
from pathlib import Path

# Ensure project root is on PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ingestion.load_to_neo4j import Neo4jLoader
import matplotlib.pyplot as plt

def visualize_annotations():
    loader = Neo4jLoader()

    try:
        with loader.driver.session(database="kos") as session:
            result = session.run("""
                MATCH (a:Annotation)-[:ANNOTATES]->(n)
                RETURN
                    n.tag AS tag,
                    labels(n) AS labels,
                    a.value AS value,
                    a.confidence AS confidence,
                    a.source AS source
                ORDER BY n.tag
            """)

            rows = list(result)

    finally:
        loader.close()

    if not rows:
        print("No annotations found.")
        return

    # ---- Prepare text blocks ----
    blocks = []
    for r in rows:
        block = (
            f"Tag: {r['tag']}\n"
            f"Label: {', '.join(r['labels'])}\n"
            f"Annotation: {r['value']}\n"
            f"Confidence: {r['confidence']:.2f}\n"
            f"Source: {r['source']}"
        )
        blocks.append(block)

    # ---- Plot ----
    fig, ax = plt.subplots(figsize=(10, len(blocks) * 1.2))
    ax.axis("off")

    y = 1.0
    dy = 1.0 / (len(blocks) + 1)

    for block in blocks:
        ax.text(
            0.01,
            y,
            block,
            fontsize=10,
            verticalalignment="top",
            family="monospace",
            bbox=dict(boxstyle="round,pad=0.3", alpha=0.15)
        )
        y -= dy

    out = "temp_annotation_inspection.png"
    plt.savefig(out, dpi=200, bbox_inches="tight")
    plt.close()

    print(f"Saved annotation inspection visualization to: {out}")

if __name__ == "__main__":
    visualize_annotations()
