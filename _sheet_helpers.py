"""How many photos fit on a sheet, and where they go.

Kept as integer arithmetic in ``plan_sheet`` so the answer can be asserted
without rendering anything, and so the "does not fit" case is a decision made
before a single pixel is drawn.

Units are the part the reference implementation gets muddled: paper, margin
and spacing are centimetres, but its border and font size are pixels, and
nothing says which is which. Here the centimetre values all say ``_cm`` and
the pixel values all say ``_px``, in the signature as well as the UI.
"""

from __future__ import annotations

from typing import NamedTuple

CM_PER_INCH = 2.54


def cm_to_px(cm: float, dpi: int) -> int:
    """Round, not truncate - a 12.7 cm sheet at 350 dpi is 1750 px either way,
    but 8.9 cm lands on 1227 with rounding and 1226 with truncation, and that
    one pixel decides whether a second row fits."""
    return int(round(float(cm) * float(dpi) / CM_PER_INCH))


class SheetPlan(NamedTuple):
    canvas_w: int
    canvas_h: int
    cols: int
    rows: int
    origin_x: int          # top-left of the first photo
    origin_y: int
    step_x: int            # distance between photo origins
    step_y: int
    photo_w: int           # including the border
    photo_h: int
    block_w: int
    block_h: int
    caption_y: int         # baseline area for the caption, 0 when unused

    @property
    def total(self) -> int:
        return self.cols * self.rows


def usable_area(paper_w_cm: float, paper_h_cm: float, dpi: int,
                margin_cm: float, caption_h: int = 0) -> tuple[int, int]:
    """The rectangle inside the margins that photos may occupy."""
    margin = cm_to_px(margin_cm, dpi)
    return (cm_to_px(paper_w_cm, dpi) - 2 * margin,
            cm_to_px(paper_h_cm, dpi) - 2 * margin - caption_h)


def fit_counts(usable_w: int, usable_h: int, photo_w: int, photo_h: int,
               spacing_px: int) -> tuple[int, int]:
    """Largest cols x rows that fits. Zero means it does not fit at all.

    The ``+ spacing`` on both sides of the division is what turns "how many
    photos plus the gaps between them" into a single floor() - three photos
    need two gaps, not three.
    """
    if photo_w <= 0 or photo_h <= 0:
        return 0, 0
    cols = (usable_w + spacing_px) // (photo_w + spacing_px)
    rows = (usable_h + spacing_px) // (photo_h + spacing_px)
    return max(0, cols), max(0, rows)


def plan_sheet(photo_w: int, photo_h: int, paper_w_cm: float, paper_h_cm: float,
               dpi: int, margin_cm: float, spacing_cm: float,
               caption_h: int = 0, auto_orient: bool = False) -> SheetPlan:
    """Resolve the whole grid.

    ``auto_orient`` swaps the paper when the turned-around sheet holds more
    photos. Ties keep the orientation as given, so a square-ish photo does not
    flip the paper for no gain.
    """
    def build(w_cm: float, h_cm: float) -> SheetPlan:
        canvas_w = cm_to_px(w_cm, dpi)
        canvas_h = cm_to_px(h_cm, dpi)
        margin = cm_to_px(margin_cm, dpi)
        spacing = cm_to_px(spacing_cm, dpi)

        usable_w = canvas_w - 2 * margin
        usable_h = canvas_h - 2 * margin - caption_h
        cols, rows = fit_counts(usable_w, usable_h, photo_w, photo_h, spacing)

        block_w = cols * photo_w + max(0, cols - 1) * spacing
        block_h = rows * photo_h + max(0, rows - 1) * spacing

        # Centre the block in the *margin box*, caption included, so the
        # photos plus their label read as one object on the sheet rather than
        # the photos centring and the label hanging off the bottom.
        total_h = block_h + caption_h
        left = margin + max(0, (canvas_w - 2 * margin - block_w) // 2)
        top = margin + max(0, (canvas_h - 2 * margin - total_h) // 2)

        return SheetPlan(
            canvas_w=canvas_w, canvas_h=canvas_h,
            cols=cols, rows=rows,
            origin_x=left, origin_y=top,
            step_x=photo_w + spacing, step_y=photo_h + spacing,
            photo_w=photo_w, photo_h=photo_h,
            block_w=block_w, block_h=block_h,
            caption_y=top + block_h if caption_h else 0,
        )

    plan = build(paper_w_cm, paper_h_cm)
    if auto_orient:
        # Try the turned paper even when the given orientation fits nothing:
        # a tall photo on a landscape sheet fits zero rows, and turning the
        # sheet round is exactly the case this option exists for. Comparing
        # totals afterwards keeps a tie on the orientation as given.
        turned = build(paper_h_cm, paper_w_cm)
        if turned.total > plan.total:
            return turned
    return plan


class FitResult(NamedTuple):
    width: int             # scaled photo size, aspect ratio kept
    height: int
    scale: float

    @property
    def percent(self) -> int:
        return int(round(self.scale * 100.0))


def shrink_to_fit(photo_w: int, photo_h: int, paper_w_cm: float,
                  paper_h_cm: float, dpi: int, margin_cm: float,
                  spacing_cm: float, caption_h: int = 0,
                  auto_orient: bool = False) -> "FitResult | None":
    """Largest copy of the photo that still fits at least one per sheet.

    Only worth calling when nothing fits as given, so ``None`` back means the
    margin and the caption have eaten the sheet rather than that the photo is
    too large: no scale factor rescues that, and blaming the photo would send
    the user off shrinking an image that was never the problem.

    ``floor`` on the scaled size, not round: one pixel over the usable edge
    turns a one-photo sheet back into an empty one, and one pixel under costs
    nothing anybody can see.
    """
    spacing = cm_to_px(spacing_cm, dpi)
    orientations = [(paper_w_cm, paper_h_cm)]
    if auto_orient:
        orientations.append((paper_h_cm, paper_w_cm))

    best = None
    for w_cm, h_cm in orientations:
        usable_w, usable_h = usable_area(w_cm, h_cm, dpi, margin_cm, caption_h)
        if usable_w <= 0 or usable_h <= 0:
            continue
        scale = min(usable_w / photo_w, usable_h / photo_h)
        if scale >= 1.0:
            continue                       # already fits this way round
        width = max(1, int(photo_w * scale))
        height = max(1, int(photo_h * scale))
        cols, rows = fit_counts(usable_w, usable_h, width, height, spacing)
        if cols == 0 or rows == 0:
            continue                       # rounding still left it a pixel over
        if best is None or width * height > best.width * best.height:
            best = FitResult(width, height, min(scale, 1.0))
    return best


def cm_to_px_bbox(plan: SheetPlan, margin_cm: float, dpi: int) -> tuple[int, int, int, int]:
    """The safe area, for drawing an optional guide."""
    margin = cm_to_px(margin_cm, dpi)
    return margin, margin, plan.canvas_w - margin, plan.canvas_h - margin
