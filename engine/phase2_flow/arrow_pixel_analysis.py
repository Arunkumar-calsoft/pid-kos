# engine/phase2_flow/arrow_pixel_analysis.py
#
# Arrow direction utilities.
#
# detect_arrow_tip_direction — pixel-level tip vs tail identification.
#   The pointed tip of an arrow symbol has fewer dark (ink) pixels at its
#   extreme edge than the flat tail end.  Comparing dark-pixel counts in the
#   first third vs last third of the dominant axis yields a deterministic
#   EAST/WEST/NORTH/SOUTH label — no probabilistic threshold required.
#
# arrow_cos_alignment — cosine similarity between two 2-D vectors.
#   Used for sanity-checking and confidence scoring after the signed arrow_vec
#   is established by pixel analysis.

import math


def arrow_cos_alignment(segment_vec, arrow_vec):
    """
    Cosine similarity (signed) between segment and arrow vectors.

    Returns:
        float in [-1, 1]; positive = same direction.
    """
    dx1, dy1 = segment_vec
    dx2, dy2 = arrow_vec
    mag1 = math.hypot(dx1, dy1)
    mag2 = math.hypot(dx2, dy2)
    if mag1 == 0 or mag2 == 0:
        return 0.0
    cos = (dx1 * dx2 + dy1 * dy2) / (mag1 * mag2)
    return max(-1.0, min(1.0, cos))  # clamp numerical noise


def detect_arrow_tip_direction(image, xmin, ymin, xmax, ymax, dark_threshold=128):
    """
    Determine which end of an arrow bbox is the pointed tip by comparing
    dark-pixel density at each extreme of the dominant axis.

    Physics of the method
    ---------------------
    An arrow symbol narrows to a point at the tip.  Counting dark (ink) pixels
    in the first third vs the last third of the dominant axis reveals which end
    is narrower (= tip).  The tail / stem end is wider and therefore has MORE
    dark pixels at the same band width.

    Coordinate convention (matches GraphML + PIL)
    ----------------------------------------------
    x increases rightward, y increases downward.

    Args:
        image:           PIL Image already converted to grayscale ("L" mode).
        xmin/ymin/xmax/ymax: Arrow bbox in image-pixel coordinates.
        dark_threshold:  Pixels strictly below this value count as "dark" ink.

    Returns:
        "EAST"  — tip is on the right  → arrow points rightward  (+x)
        "WEST"  — tip is on the left   → arrow points leftward   (−x)
        "SOUTH" — tip is at the bottom → arrow points downward   (+y)
        "NORTH" — tip is at the top    → arrow points upward     (−y)
        None    — undecidable (equal counts, crop too small, or ambiguous)
    """
    w = xmax - xmin
    h = ymax - ymin
    if w < 2.0 or h < 2.0:
        return None

    img_w, img_h = image.size
    cx0 = max(0, int(math.floor(xmin)))
    cy0 = max(0, int(math.floor(ymin)))
    cx1 = min(img_w, int(math.ceil(xmax)))
    cy1 = min(img_h, int(math.ceil(ymax)))

    if cx1 - cx0 < 3 or cy1 - cy0 < 3:
        return None

    crop = image.crop((cx0, cy0, cx1, cy1))
    cw, ch = crop.size
    if cw < 3 or ch < 3:
        return None

    px = crop.load()

    def _dark_cols(c0, c1):
        total = 0
        for x in range(c0, c1):
            for y in range(ch):
                if px[x, y] < dark_threshold:
                    total += 1
        return total

    def _dark_rows(r0, r1):
        total = 0
        for y in range(r0, r1):
            for x in range(cw):
                if px[x, y] < dark_threshold:
                    total += 1
        return total

    if w >= h:  # horizontal arrow — compare left third vs right third
        band       = max(1, cw // 3)
        left_dark  = _dark_cols(0, band)
        right_dark = _dark_cols(cw - band, cw)
        if left_dark == right_dark:
            return None
        # Fewer dark pixels = tip end
        return "WEST" if left_dark < right_dark else "EAST"
    else:       # vertical arrow — compare top third vs bottom third
        band        = max(1, ch // 3)
        top_dark    = _dark_rows(0, band)
        bottom_dark = _dark_rows(ch - band, ch)
        if top_dark == bottom_dark:
            return None
        return "NORTH" if top_dark < bottom_dark else "SOUTH"