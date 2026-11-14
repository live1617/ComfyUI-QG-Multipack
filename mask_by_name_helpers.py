# -*- coding: utf-8 -*-
"""QG Mask by Name helpers: everything around the search that needs no model.

The search itself is ComfyUI's own ``SAM3_Detect`` (comfy_extras/nodes_sam3.py),
called from the node with text conditioning built by the core ``CLIPTextEncode``.
This module owns everything else, torch only, so it imports without ComfyUI:

* cleaning the typed name and turning it into the ``name:count`` syntax the
  SAM 3 text reader expects,
* splitting the detector's flat N x H x W mask stack back into one stack per
  picture (the detector returns every match of every frame in one tensor),
* choosing among several matches (all joined, or the biggest one),
* the cut-out (image + mask as alpha) and the tinted preview with an outline,
* mask refinement: drop small pieces, grow, soften, fill holes - each step
  independent, so a future core change can only take that one step away, not
  the node,
* the plain-text messages the node raises with.

Nothing here imports ComfyUI at module level; the node file does that part.

Origin (MIT, (c) 2025 ausboss): ``clean_name``, ``search_text``,
``nothing_message``, ``split_by_frame``, ``pick``, ``cut_out`` and
``tint_preview`` are adapted from AusBoss's ``_mask_by_name_helpers.py`` - 114
of its 156 lines are kept, a few reworded. Written for this pack: ``grow_mask``,
``soften_mask``, ``fill_holes_mask``, ``drop_small_pieces`` and their pure-torch
fallbacks. The approach matches AusBoss's own ``_mask_helpers.py`` (dilation by
``max_pool2d``, border flood for holes), but the code differs: single square
kernels instead of separable passes, scipy when installed with a torch fallback,
and no erosion. See THIRD-PARTY-NOTICES.md.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F

SEVERAL = ("all matches", "largest only")
IF_NOTHING = ("stop the run", "empty mask")
NAME_MAX = 200
# SAM 3 returns one match per name unless the name asks for more. Sixteen is
# plenty for a still picture; a higher cap just wastes decoder passes.
MATCHES_MAX = 16
# How sure SAM 3 must be by default. The core node's 0.5 would "find"
# something for about every second wrong name; 0.7 keeps real small things
# (straps, lips, shoes) while filtering most wrong names. Exposed as the
# Sureness input so a missed small object can be chased below it.
SURENESS = 0.7
# SAM decoder refinement passes inside the core detect node. Two is what
# ComfyUI's own SAM3 examples use; more barely changes still-image masks.
REFINE_PASSES = 2
# A separate white piece below this share of the biggest piece's area counts
# as a stray speck (SAM 3 joining several candidates can leave little islands
# next to the thing). Exposed as the node's small_size input, in percent.
SMALL_RATIO = 0.05

# Preview tint. QG blue, a little lighter for the outline so both read on
# dark pictures.
TINT = (0.231, 0.510, 0.965)
OUTLINE = (0.553, 0.827, 1.0)
TINT_STRENGTH = 0.55

NO_NAME = 'QG Mask by Name: type what to find, like "the dog" or "the red jacket".'
NEEDS_SAM3 = (
    "QG Mask by Name needs ComfyUI 0.20 or newer: it calls ComfyUI's own "
    "SAM3 Detect node, and this install does not have it."
)
NOT_SAM3 = (
    "QG Mask by Name could not search the picture: the checkpoint picked in "
    "this node is not a SAM 3 model. Pick sam3.1_multiplex_fp16.safetensors "
    "(in models/checkpoints, or a checkpoints folder added through "
    "extra_model_paths.yaml) in the node's checkpoint dropdown."
)
MISSING_CKPT = (
    "QG Mask by Name could not find that checkpoint file. Put it in "
    "models/checkpoints (or a checkpoints folder added through "
    "extra_model_paths.yaml), then pick it in the node's checkpoint dropdown."
)


def clean_name(name) -> str:
    """The typed name with stray spaces and line breaks gone."""
    return " ".join(str(name or "").split())[:NAME_MAX]


def search_text(name: str, limit: int = MATCHES_MAX) -> str:
    """The name in the ``name:count`` syntax SAM 3's text reader expects.

    Comma-separated names each become ``name:limit`` so two scarves are both
    found; a count the user already typed (``cat:3``) is left alone. Quotes
    and parentheses are stripped: they belong to diffusion prompts, not to
    open-vocabulary detection.
    """
    parts = []
    for part in clean_name(name).replace("(", "").replace(")", "").replace('"', "").split(","):
        part = part.strip()
        if not part:
            continue
        head, colon, tail = part.rpartition(":")
        if colon and head.strip() and tail.strip().replace(".", "", 1).isdigit():
            parts.append(f"{head.strip()}:{tail.strip()}")
        else:
            parts.append(f"{part.rstrip(':').strip()}:{int(limit)}")
    return ", ".join(parts)


def nothing_message(name: str) -> str:
    """What the run stops with when the name matches nothing."""
    return (
        f'QG Mask by Name: nothing called "{name}" was found in the picture. '
        "Try another name, or lower Sureness."
    )


def split_by_frame(masks: torch.Tensor, counts: list) -> list:
    """One stack of masks per picture.

    The detector returns every match of every picture in one N x H x W stack
    plus a per-picture match count. A count that does not add up means the
    detector changed its return shape; that is an error here, never a silent
    wrong mask.
    """
    if not isinstance(masks, torch.Tensor) or masks.ndim != 3:
        raise ValueError("QG Mask by Name expected the detector's masks as one N x H x W stack.")
    total = sum(int(c) for c in counts)
    if total != int(masks.shape[0]):
        raise ValueError(
            f"QG Mask by Name got {int(masks.shape[0])} masks for {total} matches; "
            "the detector's answer does not add up."
        )
    frames = []
    start = 0
    for count in counts:
        frames.append(masks[start:start + int(count)])
        start += int(count)
    return frames


def pick(found: torch.Tensor, several: str) -> torch.Tensor:
    """One H x W mask from a picture's matches: all of them joined, or the
    biggest one. No match gives an empty mask."""
    if found.shape[0] == 0:
        return torch.zeros(found.shape[1:], dtype=torch.float32, device=found.device)
    found = found.float().clamp(0.0, 1.0)
    if several == "largest only" and found.shape[0] > 1:
        areas = found.flatten(1).sum(dim=1)
        return found[int(areas.argmax())]
    return found.amax(dim=0)


def grow_mask(mask: torch.Tensor, pixels: int) -> torch.Tensor:
    """Grow the mask outward by ``pixels`` (square footprint, 3x3 steps).

    A square 3x3 footprint applied ``pixels`` times is exactly "chessboard
    distance <= pixels", so scipy's distance transform answers it in one
    linear pass. That matters because the node lets the value go to 512 and
    a single max-pool with a 2*px+1 kernel costs time proportional to
    ``pixels**2``: px=128 on a 1024x1024 mask took 51s, px=512 would have
    been minutes. Without scipy the plain-torch loop is still correct, just
    linear in ``pixels``.
    """
    px = int(pixels)
    if px <= 0:
        return mask
    binary = mask > 0.5
    try:
        from scipy import ndimage  # noqa: PLC0415 - optional, has a fallback
    except ImportError:
        ndimage = None
    if ndimage is not None:
        out = torch.empty_like(binary)
        for i in range(binary.shape[0]):
            plane = binary[i]
            if not bool(plane.any()):
                # 空遮罩保持空：距离变换对"没有前景"的输入返回 -1（无定义），
                # 直接拿去比较会被判成"距离够近"，把整张图填成前景。
                out[i] = plane
                continue
            dist = ndimage.distance_transform_cdt(
                (~plane).detach().cpu().numpy(), metric="chessboard")
            out[i] = torch.from_numpy(dist <= px).to(binary.device)
        return out.float()
    grown = binary.float().unsqueeze(1)
    for _ in range(px):
        grown = F.max_pool2d(grown, 3, stride=1, padding=1)
    return grown.squeeze(1)


def soften_mask(mask: torch.Tensor, pixels: float) -> torch.tensor:
    """Soften the edge by box-blurring over ``pixels`` on each side.

    Fully-inside and fully-outside areas keep their exact 1 and 0; only the
    rim gets the gradient, and the ramp's width is what the number means.

    The window sum comes from an integral image, so the cost is flat in
    ``pixels`` (px=100 on 1024x1024: 10s with avg_pool2d, 0.03s here).
    Zero padding is kept on purpose - it matches avg_pool2d's default and
    lets the border darken the same way it always did.
    """
    px = int(round(float(pixels)))
    if px <= 0:
        return mask
    k = 2 * px + 1
    # float64 on CPU keeps the running totals exact enough at 4K sizes;
    # on the GPU float32 is the faster trade and still lands within 1e-5.
    dtype = torch.float64 if mask.device.type == "cpu" else torch.float32
    padded = F.pad(mask.to(dtype), (px, px, px, px))
    padded = F.pad(padded, (1, 0, 1, 0))  # zero row/col so sums start at 0
    integ = padded.cumsum(-1).cumsum(-2)
    total = (
        integ[..., k:, k:]
        - integ[..., :-k, k:]
        - integ[..., k:, :-k]
        + integ[..., :-k, :-k]
    )
    return (total / float(k * k)).to(mask.dtype)


def fill_holes_mask(mask: torch.Tensor) -> torch.Tensor:
    """Fill gaps that lie fully inside the mask (hair curls, cloth folds).

    scipy when present (exact, fast); otherwise a border flood from the
    outside in plain torch - anything the flood cannot reach from the frame
    edge is inside the shape and gets filled.
    """
    binary = mask > 0.5
    try:
        from scipy import ndimage  # noqa: PLC0415 - optional, has a fallback
    except ImportError:
        return _fill_holes_torch(binary)
    out = torch.empty_like(binary)
    for i in range(binary.shape[0]):
        filled = ndimage.binary_fill_holes(binary[i].detach().cpu().numpy())
        out[i] = torch.from_numpy(filled).to(binary.device)
    return out.float()


def _fill_holes_torch(binary: torch.Tensor) -> torch.Tensor:
    """Border-flood fallback for fill holes, no scipy needed.

    Mark every background pixel reachable from the frame edge (3x3 dilation
    steps, capped at the longest side so it always terminates), then keep
    everything else - reached background stays background, unreachable gaps
    become part of the mask.
    """
    result = torch.empty_like(binary)
    for i in range(binary.shape[0]):
        body = binary[i]
        outside = torch.zeros_like(body)
        outside[0, :] = ~body[0, :]
        outside[-1, :] = ~body[-1, :]
        outside[:, 0] = ~body[:, 0]
        outside[:, -1] = ~body[:, -1]
        limit = max(int(body.shape[0]), int(body.shape[1]))
        for _ in range(limit):
            spread = F.max_pool2d(outside.float().unsqueeze(0), 3, stride=1, padding=1).squeeze(0) > 0.5
            spread = spread & ~body
            if bool((spread == outside).all()):
                break
            outside = spread
        result[i] = (~outside).float()
    return result


def drop_small_pieces(mask: torch.Tensor, ratio: float) -> torch.Tensor:
    """Drop separate white pieces that are stray specks, not part of the thing.

    A piece is a white island of its own. One is a speck when its area is
    below ``ratio`` of the biggest island's area - the little islands SAM 3
    can leave next to the thing when it joins several candidates. The biggest
    island itself always stays, so a mask of one real small thing is never
    emptied, and a ratio of 0 (or below) keeps everything.

    scipy when present (exact, fast); otherwise an iterative label spread in
    plain torch - slower, same answer.
    """
    r = float(ratio)
    if r <= 0.0:
        return mask
    binary = mask > 0.5
    try:
        import numpy  # noqa: PLC0415 - scipy pulls numpy in with itself
        from scipy import ndimage  # noqa: PLC0415 - optional, has a fallback
    except ImportError:
        return _drop_small_torch(binary, r)
    out = torch.empty_like(binary)
    for i in range(binary.shape[0]):
        plane = binary[i].detach().cpu().numpy()
        labels, count = ndimage.label(plane)
        if count <= 1:
            out[i] = binary[i]
            continue
        areas = ndimage.sum(plane, labels, index=list(range(1, count + 1)))
        keep = [idx + 1 for idx, area in enumerate(areas) if area >= r * areas.max()]
        if len(keep) == count:
            out[i] = binary[i]
            continue
        out[i] = torch.from_numpy(numpy.isin(labels, keep)).to(binary.device)
    return out.float()


def _drop_small_torch(binary: torch.Tensor, ratio: float) -> torch.Tensor:
    """Label-spread fallback for drop small pieces, no scipy needed.

    Every white pixel starts as its own id (its position in the plane); ids
    spread through 3x3 neighbourhoods, smallest id wins, never across black.
    When nothing changes any more, a pixel's id is its island's number - the
    island that holds the plane's first white pixel. Then areas decide what
    stays. One pool step per unit of that distance, so a full spread over a
    picture takes at most max(height, width) steps.
    """
    result = torch.empty_like(binary)
    for i in range(binary.shape[0]):
        body = binary[i]
        if not bool(body.any()):
            result[i] = body
            continue
        ids = torch.where(
            body,
            torch.arange(body.numel(), dtype=torch.float64, device=body.device).view_as(body) + 1.0,
            torch.full(body.shape, float("inf"), dtype=torch.float64, device=body.device),
        )
        while True:
            spread = -F.max_pool2d((-ids).unsqueeze(0).unsqueeze(0), 3, stride=1, padding=1)
            spread = spread.squeeze(0).squeeze(0)
            spread = torch.where(body, torch.minimum(spread, ids), ids)
            if bool((spread == ids).all()):
                break
            ids = spread
        island_ids = ids[body]
        _, counts = torch.unique(island_ids, return_counts=True)
        keep = counts >= ratio * counts.max()
        kept_ids = torch.unique(island_ids)[keep]
        result[i] = (torch.isin(ids, kept_ids) & body).float()
    return result


def refine_mask(
    mask: torch.Tensor, grow: int, soften: float, fill: bool,
    drop_small: bool = False, small_ratio: float = 0.0,
) -> torch.Tensor:
    """The refinement steps, in the one order that makes sense: stray specks
    first (so they survive nothing downstream), then fill (so the outline is
    a solid shape), then grow, then soften."""
    out = mask
    if drop_small:
        out = drop_small_pieces(out, float(small_ratio))
    if fill:
        out = fill_holes_mask(out)
    out = grow_mask(out, int(grow))
    out = soften_mask(out, float(soften))
    return out.clamp(0.0, 1.0)


def cut_out(image: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """The picture with the mask as its alpha channel (B x H x W x 4).

    One mask for a batch of pictures is used for each of them."""
    rgb = image[..., :3]
    alpha = mask.to(device=rgb.device, dtype=rgb.dtype).clamp(0.0, 1.0)
    if alpha.shape[0] != rgb.shape[0]:
        alpha = alpha[:1].expand(rgb.shape[0], -1, -1)
    return torch.cat([rgb, alpha.unsqueeze(-1)], dim=-1)


def tint_preview(image: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """The first picture with what was found tinted blue and outlined.

    The outline's width follows the picture size, so it reads the same on a
    small preview of a large picture."""
    frame = image[:1, ..., :3].detach().float().cpu().clamp(0.0, 1.0)
    found = mask[:1].detach().float().cpu().clamp(0.0, 1.0).unsqueeze(-1)
    tint = torch.tensor(TINT, dtype=torch.float32).view(1, 1, 1, 3)
    out = frame * (1.0 - TINT_STRENGTH * found) + tint * (TINT_STRENGTH * found)
    height, width = int(frame.shape[1]), int(frame.shape[2])
    reach = max(1, round(min(height, width) / 300))
    plane = found.movedim(-1, 1)
    size = 2 * reach + 1
    grown = F.max_pool2d(plane, size, stride=1, padding=reach)
    shrunk = 1.0 - F.max_pool2d(1.0 - plane, size, stride=1, padding=reach)
    edge = ((grown - shrunk) > 0.5).float().movedim(1, -1)
    line = torch.tensor(OUTLINE, dtype=torch.float32).view(1, 1, 1, 3)
    return out * (1.0 - edge) + line * edge


__all__ = [
    "IF_NOTHING",
    "MATCHES_MAX",
    "MISSING_CKPT",
    "NEEDS_SAM3",
    "NOT_SAM3",
    "NO_NAME",
    "REFINE_PASSES",
    "SEVERAL",
    "SMALL_RATIO",
    "SURENESS",
    "clean_name",
    "cut_out",
    "drop_small_pieces",
    "nothing_message",
    "pick",
    "refine_mask",
    "search_text",
    "split_by_frame",
    "tint_preview",
]
