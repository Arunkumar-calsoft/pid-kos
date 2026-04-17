"""
tests/verify_pixel_tip_detection.py

Runs detect_arrow_tip_direction against every arrow node in both registered PIDs
and saves an annotated verification image showing:
  - The arrow crop (scaled 8x for visibility)
  - Detected direction label
  - Dark-pixel counts in each third-band
  - Whether pixel detection returned None (undecidable)

Usage:
    python tests/verify_pixel_tip_detection.py
"""

import math
import sys
import os
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.phase2_flow.arrow_pixel_analysis import detect_arrow_tip_direction

# ─── PID registry ─────────────────────────────────────────────────────────────
PIDS = [
    {
        "name": "PID_0",
        "graphml": r"c:\Users\arun.kumar\OneDrive - Calsoft Pvt Ltd\Desktop\Python\Chatbot\pid_store\PLANT_001\SKID_01\PID_0\0.graphml",
        "image":   r"c:\Users\arun.kumar\OneDrive - Calsoft Pvt Ltd\Desktop\Python\Chatbot\pid_store\PLANT_001\SKID_01\PID_0\0.png",
    },
    {
        "name": "PID_2",
        "graphml": r"c:\Users\arun.kumar\OneDrive - Calsoft Pvt Ltd\Desktop\Python\Chatbot\pid_store\PLANT_001\SKID_01\PID_2\2.graphml",
        "image":   r"c:\Users\arun.kumar\OneDrive - Calsoft Pvt Ltd\Desktop\Python\Chatbot\pid_store\PLANT_001\SKID_01\PID_2\2.png",
    },
]

OUT_DIR = r"c:\Users\arun.kumar\OneDrive - Calsoft Pvt Ltd\Desktop\Python\Chatbot\logs"
SCALE   = 10          # magnification for crop thumbnails
THUMB_W = 140         # thumbnail cell width in output sheet
THUMB_H = 100         # thumbnail cell height (label area below crop)
LABEL_H = 60          # pixels reserved below crop for text
COLS    = 10          # thumbnails per row


def load_arrows_from_graphml(path):
    tree = ET.parse(path)
    root = tree.getroot()
    ns   = {"g": "http://graphml.graphdrawing.org/xmlns"}
    keys = {k.get("id"): k.get("attr.name") for k in root.findall("g:key", ns)}
    arrows = []
    for node in root.findall(".//g:node", ns):
        nid   = node.get("id")
        attrs = {
            keys[d.get("key")]: d.text
            for d in node.findall("g:data", ns)
            if d.get("key") in keys
        }
        if "arrow" in (attrs.get("label") or "").lower():
            arrows.append((nid, attrs))
    return arrows


def third_band_counts(img_gray, xmin, ymin, xmax, ymax, dark_thr=128):
    """Return (a_count, b_count, axis) where a=first-third, b=last-third."""
    w = xmax - xmin
    h = ymax - ymin
    img_w, img_h = img_gray.size

    cx0 = max(0, int(math.floor(xmin)))
    cy0 = max(0, int(math.floor(ymin)))
    cx1 = min(img_w, int(math.ceil(xmax)))
    cy1 = min(img_h, int(math.ceil(ymax)))

    crop = img_gray.crop((cx0, cy0, cx1, cy1))
    cw, ch = crop.size
    if cw < 3 or ch < 3:
        return 0, 0, "?"
    px = crop.load()

    if w >= h:  # horizontal
        band = max(1, cw // 3)
        left  = sum(1 for x in range(band)        for y in range(ch) if px[x, y] < dark_thr)
        right = sum(1 for x in range(cw - band, cw) for y in range(ch) if px[x, y] < dark_thr)
        return left, right, "H"
    else:
        band   = max(1, ch // 3)
        top    = sum(1 for y in range(band)        for x in range(cw) if px[x, y] < dark_thr)
        bottom = sum(1 for y in range(ch - band, ch) for x in range(cw) if px[x, y] < dark_thr)
        return top, bottom, "V"


def direction_arrow_char(d):
    return {"EAST": "→", "WEST": "←", "SOUTH": "↓", "NORTH": "↑"}.get(d or "None", "?")


def run_pid(pid_cfg):
    name   = pid_cfg["name"]
    arrows = load_arrows_from_graphml(pid_cfg["graphml"])
    img    = Image.open(pid_cfg["image"]).convert("L")
    img_rgb = Image.open(pid_cfg["image"]).convert("RGB")

    results = []
    none_count = 0

    print(f"\n{'─'*72}")
    print(f"  {name}  ({img.size[0]}×{img.size[1]} px)  |  {len(arrows)} arrows")
    print(f"{'─'*72}")
    print(f"  {'ID':<14} {'W':>5} {'H':>5} {'ratio':>6} {'axis':>5} {'A-dark':>7} {'B-dark':>7} {'winner':>7} {'detected':>9}")
    print(f"  {'-'*14} {'-'*5} {'-'*5} {'-'*6} {'-'*5} {'-'*7} {'-'*7} {'-'*7} {'-'*9}")

    for nid, attrs in arrows:
        x0 = float(attrs.get("xmin", 0))
        x1 = float(attrs.get("xmax", 0))
        y0 = float(attrs.get("ymin", 0))
        y1 = float(attrs.get("ymax", 0))
        w  = x1 - x0
        h  = y1 - y0

        direction = detect_arrow_tip_direction(img, x0, y0, x1, y1)
        a, b, axis = third_band_counts(img, x0, y0, x1, y1)

        if direction is None:
            none_count += 1
            winner = "TIE/SML"
        else:
            if axis == "H":
                winner = "LEFT<" if a < b else "RIGHT>"
            else:
                winner = "TOP^" if a < b else "BOT_v"

        flag = "" if direction is not None else "  ← UNDECIDED"
        print(f"  {nid:<14} {w:>5.1f} {h:>5.1f} {w/h if h else 0:>6.2f} {axis:>5} "
              f"{a:>7} {b:>7} {winner:>7} {direction_arrow_char(direction):>9}{flag}")

        results.append({
            "nid": nid, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "w": w, "h": h, "direction": direction, "a": a, "b": b, "axis": axis,
        })

    print(f"\n  Summary: {len(arrows)} arrows  |  decided={len(arrows)-none_count}"
          f"  |  undecided={none_count}"
          f"  |  success_rate={100*(len(arrows)-none_count)/len(arrows):.1f}%")

    # ── Build verification sheet ──────────────────────────────────────────
    n_rows = math.ceil(len(results) / COLS)
    sheet_w = COLS * THUMB_W
    sheet_h = n_rows * (SCALE * 20 + LABEL_H + 10)  # rough, recalc below

    CELL_H = SCALE * 20 + LABEL_H  # max crop height at 10× + label
    sheet_h = n_rows * (CELL_H + 8)
    sheet = Image.new("RGB", (sheet_w, sheet_h + 30), (240, 240, 240))
    draw  = ImageDraw.Draw(sheet)
    draw.text((4, 4), f"{name}  — arrow tip pixel detection", fill=(0, 0, 0))

    COLORS = {
        "EAST":  (0, 180, 0),
        "WEST":  (200, 80, 0),
        "SOUTH": (0, 80, 200),
        "NORTH": (150, 0, 200),
        None:    (180, 0, 0),
    }

    for i, r in enumerate(results):
        col = i % COLS
        row = i // COLS
        cell_x = col * THUMB_W
        cell_y = 30 + row * (CELL_H + 8)

        # Crop arrow region at SCALE×
        cx0 = max(0, int(math.floor(r["x0"])))
        cy0 = max(0, int(math.floor(r["y0"])))
        cx1 = min(img_rgb.size[0], int(math.ceil(r["x1"])))
        cy1 = min(img_rgb.size[1], int(math.ceil(r["y1"])))
        crop = img_rgb.crop((cx0, cy0, cx1, cy1))
        scaled_w = max(1, crop.size[0]) * SCALE
        scaled_h = max(1, crop.size[1]) * SCALE
        scaled_w = min(scaled_w, THUMB_W - 4)
        scaled_h = min(scaled_h, CELL_H - LABEL_H - 4)
        try:
            thumb = crop.resize((scaled_w, scaled_h), Image.NEAREST)
        except Exception:
            thumb = crop

        # Paste thumb centred in cell
        px_off = cell_x + (THUMB_W - thumb.size[0]) // 2
        py_off = cell_y + 2
        sheet.paste(thumb, (px_off, py_off))

        # Direction label
        d   = r["direction"]
        col_c = COLORS.get(d, (100, 100, 100))
        label = f"{r['nid']}\n{direction_arrow_char(d)} {d or 'NONE'}\n"
        if r["axis"] == "H":
            label += f"L={r['a']} R={r['b']}"
        else:
            label += f"T={r['a']} B={r['b']}"

        ty = cell_y + thumb.size[1] + 4
        for li, line in enumerate(label.split("\n")):
            draw.text((cell_x + 2, ty + li * 14), line, fill=col_c)

        # Border colour by decision
        draw.rectangle(
            [cell_x, cell_y, cell_x + THUMB_W - 2, cell_y + CELL_H - 2],
            outline=col_c, width=2,
        )

    out_path = os.path.join(OUT_DIR, f"{name}_pixel_tip_verification.png")
    sheet.save(out_path)
    print(f"\n  Verification sheet saved: {out_path}\n")
    return results


if __name__ == "__main__":
    all_results = {}
    for pid in PIDS:
        all_results[pid["name"]] = run_pid(pid)

    # Final cross-PID summary
    total = sum(len(v) for v in all_results.values())
    decided = sum(
        sum(1 for r in v if r["direction"] is not None)
        for v in all_results.values()
    )
    print(f"\n{'='*72}")
    print(f"  TOTAL:  {total} arrows  |  decided={decided}  |  undecided={total-decided}"
          f"  |  overall_success={100*decided/total:.1f}%")

    # Distribution of detected directions
    from collections import Counter
    counts = Counter(
        r["direction"]
        for v in all_results.values()
        for r in v
    )
    print(f"\n  Direction distribution:")
    for d, c in sorted(counts.items(), key=lambda x: -(x[1] or 0)):
        print(f"    {direction_arrow_char(d)} {d or 'UNDECIDED':>10}  {c:>3} arrows")
    print(f"{'='*72}\n")
