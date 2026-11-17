# -*- coding: utf-8 -*-
"""QG_MaskByName - type what to find in a picture and get its mask.

Written for the QG 工具 multi-pack (ComfyUI-QG-Multipack) on 2026-11-04.

Origin: the class, its ``INPUT_TYPES``, ``_detect`` and the module-level helpers
below them are adapted from ComfyUI-AusBoss's Mask by Name (MIT, (c) 2025
ausboss) - 225 of its 279 lines are kept, including the tooltip strings. Added
for this pack: the SAM 3 checkpoint dropdown and its loader/cache, the header
check that refuses a non-SAM 3 file, the four-step refinement and the preview
saving. See THIRD-PARTY-NOTICES.md for the exact split.

How it works - and what it deliberately does not do
---------------------------------------------------
The search is ComfyUI's own ``SAM3_Detect`` (comfy_extras/nodes_sam3.py,
0.20+), driven with text conditioning built by the core ``CLIPTextEncode``.
Nothing of either is copied here: the node looks both classes up in the core
``NODE_CLASS_MAPPINGS`` at run time and calls them. That is the whole reason
this node is small and stays correct across core updates - and also the
reason it fails loudly with a plain message when a non-SAM-3 checkpoint is
picked, instead of erroring somewhere inside the detector.

The SAM 3 checkpoint (sam3.1_multiplex_fp16.safetensors, in
models/checkpoints) is picked in the node's own dropdown and loaded here -
no Checkpoint Loader node needed. The loaded model is kept in a one-slot
cache keyed by file stamp, so re-running the node with other settings does
not read the file from disk again; a different checkpoint replaces the
cached one. A checkpoint that is not SAM 3 is refused right after loading,
before any search is paid for.

Design choices kept from the idea, changed for this pack
--------------------------------------------------------
* **Find runs alone.** ``OUTPUT_NODE`` is on, so "Find" on the node runs just
  this node - check the tinted preview before paying for everything after it.
* **Nothing found stops the run by default.** A silent empty mask would flow
  on into a sampler and come back as a confusing full-frame edit. The
  ``if_nothing`` switch flips that to "empty mask" for workflows that expect
  misses.
* **The checkpoint loads inside the node.** One dropdown, no loader node:
  the SAM 3 file is the only thing this node can use, so there is no reason
  to make the graph carry a second Checkpoint Loader for it.
* **Refinement is four independent steps** (drop small pieces, fill holes,
  grow, soften) in helpers that only need torch, each fail-soft on its own.
* **free_vram** takes SAM 3 out of VRAM right after the search (core's own
  per-model unload), for workflows that load a big model after this node.
* Tooltips and messages are English here; the Chinese UI lives in
  ``locales/zh/nodeDefs.json``, per the QG-tools convention this pack
  follows.
"""

from __future__ import annotations

import os
import sys
import time
import uuid

import torch

from .mask_by_name_helpers import (
    IF_NOTHING,
    MISSING_CKPT,
    NEEDS_SAM3,
    NOT_SAM3,
    NO_NAME,
    REFINE_PASSES,
    SEVERAL,
    SMALL_RATIO,
    SURENESS,
    clean_name,
    cut_out,
    nothing_message,
    pick,
    refine_mask,
    search_text,
    split_by_frame,
    tint_preview,
)

# What the frontend could read to show "found N" on the node (reserved).
UI_KEY = "qg_mask_by_name"

# The file this node exists for. First in the dropdown when present, so the
# node arrives ready to run.
SAM3_FILE = "sam3.1_multiplex_fp16.safetensors"

# Small LRU of loaded SAM 3 models: checkpoint name -> (file stamp, model,
# clip). Re-running the node with other settings must not read 1.6 GB from
# disk again. Two slots so that alternating between two checkpoints does not
# reload each time; see _trim_sam3_cache for why not more.
_SAM3_CACHE = {}
_SAM3_CACHE_MAX = 2


def _checkpoint_list() -> list:
    """Checkpoint files ComfyUI knows, the SAM 3 file first if it is there."""
    try:
        import folder_paths  # noqa: PLC0415
        files = sorted(folder_paths.get_filename_list("checkpoints"))
    except Exception:  # noqa: BLE001 - outside ComfyUI the list is just one name
        files = []
    preferred = [f for f in files if "sam3" in f.lower()]
    rest = [f for f in files if "sam3" not in f.lower()]
    return preferred + rest if preferred + rest else [SAM3_FILE]


def _checkpoint_default() -> str:
    """The dropdown's starting value: the SAM 3 file when it is there."""
    files = _checkpoint_list()
    for name in files:
        if "sam3" in name.lower():
            return name
    return files[0]


def _checkpoint_is_sam3(path: str) -> bool:
    """Peek at the file's safetensors header - the few hundred KB of key
    names at the front - for the ``detector.`` keys only a SAM 3 file has,
    without reading the multi-gigabyte body. Refusing a lookalike here keeps
    a six-gigabyte diffusion checkpoint out of memory entirely: loading one
    just to fail later can push a RAM-tight machine over instead of failing
    cleanly. An unreadable header says nothing for or against, so the file
    is passed on and the loader's own error gets to speak."""
    import json  # noqa: PLC0415
    import struct  # noqa: PLC0415

    try:
        with open(path, "rb") as handle:
            (size,) = struct.unpack("<Q", handle.read(8))
            header = json.loads(handle.read(min(size, 8 * 1024 * 1024)))
    except Exception:  # noqa: BLE001 - unknown, not "no"
        return True
    return any(key.startswith("detector.") for key in header if isinstance(key, str))


def _trim_sam3_cache(keep: int = _SAM3_CACHE_MAX) -> None:
    """只留最近用过的 ``keep`` 个 checkpoint（LRU，最早的先走）。

    一个 SAM 3 checkpoint 是 1.74GB。早先的实现是「换模型就把缓存整个清空」，
    在两个 checkpoint 之间来回切（比如一次批量里 3.1 和 3.0 混用）就要反复从
    磁盘重读，每次几十秒。留两个能覆盖绝大多数来回切的场景，又不至于把内存
    吃光；勾了「跑完释放显存」时只留当前这个——那个开关的意图就是尽量少占。
    """
    limit = max(1, int(keep))
    while len(_SAM3_CACHE) > limit:
        _SAM3_CACHE.pop(next(iter(_SAM3_CACHE)), None)


def _load_sam3(ckpt_name: str):
    """The SAM 3 model patcher and its text reader, loaded or from cache.

    The core's own checkpoint loader does the reading (output_vae off: this
    node never touches pixels from the VAE). A file that is not a SAM 3
    model is refused from its header alone, before any of it is read into
    memory - the detector's own failure would come later and say less.
    """
    import folder_paths  # noqa: PLC0415
    import comfy.sd  # noqa: PLC0415

    path = folder_paths.get_full_path("checkpoints", ckpt_name)
    if path is None:
        raise FileNotFoundError(MISSING_CKPT)
    if not _checkpoint_is_sam3(path):
        raise RuntimeError(NOT_SAM3)
    stamp = os.path.getmtime(path)
    hit = _SAM3_CACHE.get(ckpt_name)
    if hit is not None and hit[0] == stamp:
        # 命中也要挪到队尾，否则「刚用过」的那个人反而会被先淘汰
        _SAM3_CACHE.pop(ckpt_name, None)
        _SAM3_CACHE[ckpt_name] = hit
        return hit[1], hit[2]
    model, clip, _vae, _clipvision = comfy.sd.load_checkpoint_guess_config(
        path,
        output_vae=False,
        output_clip=True,
        embedding_directory=folder_paths.get_folder_paths("embeddings"),
    )
    sam3_body = getattr(getattr(model, "model", None), "diffusion_model", None)
    if model is None or clip is None or not hasattr(sam3_body, "forward_segment"):
        raise RuntimeError(NOT_SAM3)
    _SAM3_CACHE.pop(ckpt_name, None)
    _SAM3_CACHE[ckpt_name] = (stamp, model, clip)
    _trim_sam3_cache()
    return model, clip


def _core_nodes() -> dict:
    """ComfyUI's own node classes, by key. Empty outside ComfyUI."""
    mappings = getattr(sys.modules.get("nodes"), "NODE_CLASS_MAPPINGS", None)
    return mappings if isinstance(mappings, dict) else {}


def _model_management():
    """ComfyUI's model management module. None outside ComfyUI."""
    return sys.modules.get("comfy.model_management")


def _free_sam3(model, clip) -> bool:
    """Take SAM 3 and its text reader out of VRAM. Every other model stays.

    ComfyUI's own per-model unload does the work. Best effort: where that
    function is missing or fails, nothing is freed and the run goes on."""
    unload = getattr(_model_management(), "unload_model_and_clones", None)
    if unload is None:
        return False
    freed = False
    for patcher in (model, getattr(clip, "patcher", None)):
        if patcher is None:
            continue
        try:
            unload(patcher)
            freed = True
        except Exception:  # noqa: BLE001 - freeing memory never fails a run
            pass
    return freed


def _stopped_by_user(error: BaseException) -> bool:
    return type(error).__name__ == "InterruptProcessingException"


def _out_of_memory(error: BaseException) -> bool:
    return "OutOfMemory" in type(error).__name__ or "out of memory" in str(error).lower()


def _save_preview(image01_hwc: torch.Tensor, prefix: str) -> dict:
    """Write the tinted preview into ComfyUI's temp folder as a PNG and
    return the standard PreviewImage ui payload.

    ``tint_preview`` 返回带 batch 维的 [1,H,W,3]，Pillow 只接受三维
    [H,W,C]，因此这里先去掉 batch 维（v0.1.1 修 P0-2）。
    """
    from PIL import Image  # noqa: PLC0415 - ComfyUI ships Pillow

    try:
        import folder_paths  # noqa: PLC0415
        out_dir = folder_paths.get_temp_directory()
    except Exception as exc:  # noqa: BLE001 - 预览失败不应中断主流程
        print(f"[QG_MaskByName] 预览目录获取失败：{type(exc).__name__}: {exc}")
        return {}
    try:
        os.makedirs(out_dir, exist_ok=True)
        name = f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:6]}.png"
        arr = (image01_hwc.detach().cpu().clamp(0.0, 1.0).numpy() * 255.0).round().astype("uint8")
        # 兼容 [1,H,W,3] 与 [H,W,C] 两种输入，避免四维张量直接抛错被静默吞掉
        if arr.ndim == 4:
            if arr.shape[0] == 0:
                return {}
            arr = arr[0]
        if arr.ndim != 3:
            print(f"[QG_MaskByName] 预览张量维度异常：{arr.shape}")
            return {}
        Image.fromarray(arr).save(os.path.join(out_dir, name))
        return {"images": [{"filename": name, "subfolder": "", "type": "temp"}]}
    except Exception as exc:  # noqa: BLE001
        print(f"[QG_MaskByName] 预览图保存失败：{type(exc).__name__}: {exc}")
        return {}


class QGMaskByName:
    """Type what to find, get its mask and a cut-out. Search by SAM 3."""

    CATEGORY = "QG 工具"
    SEARCH_ALIASES = [
        "sam", "sam3", "segment", "segment anything", "detect", "find",
        "text to mask", "prompt mask", "object mask", "select by name",
        "remove background", "cut out", "auto mask", "qg",
    ]
    # An output node, so Find can run it on its own.
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "要搜索的图片。"}),
                "checkpoint": (
                    _checkpoint_list(),
                    {
                        "default": _checkpoint_default(),
                        "tooltip": (
                            "SAM 3 检查点：sam3.1_multiplex_fp16.safetensors（放 models/checkpoints，或 extra_model_paths.yaml 里配置的 checkpoints 目录）。节点内部加载，无需检查点加载器；文件里的文字读取器负责读名称，无需单独的 CLIP。"
                        ),
                    },
                ),
                "name": (
                    "STRING",
                    {
                        "default": "the person",
                        "multiline": False,
                        "tooltip": "要找什么，几个普通词即可，如「那只狗」「红色夹克」。要找多个物体就用逗号隔开。",
                    },
                ),
                "several": (
                    list(SEVERAL),
                    {
                        "default": SEVERAL[0],
                        "tooltip": "匹配到多个物体时：全部合并成一个蒙版，或只取面积最大的那个。",
                    },
                ),
                "grow": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 512,
                        "step": 1,
                        "tooltip": "蒙版向外扩多少像素。0 保持精确轮廓。",
                    },
                ),
                "soften": (
                    "FLOAT",
                    {
                        "default": 0.0,
                        "min": 0.0,
                        "max": 100.0,
                        "step": 0.5,
                        "tooltip": "蒙版边缘软化多少像素。0 保持硬边。",
                    },
                ),
                "if_nothing": (
                    list(IF_NOTHING),
                    {
                        "default": IF_NOTHING[0],
                        "tooltip": (
                            "没有任何匹配时怎么办。终止运行：工作流在此停止并给出提示，本节点之后一律不跑。空蒙版：继续运行，输出一张全黑蒙版。"
                        ),
                    },
                ),
            },
            "optional": {
                "preview": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "在节点上显示染色+描边的找到区域。关掉可省去写临时预览文件。",
                    },
                ),
                "drop_small": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": (
                            "剔除搜索偶尔在目标旁边留下的零碎小白斑——蒙版里独立、不属于目标的小岛。面积最大的一块永远保留。"
                        ),
                    },
                ),
                "small_size": (
                    "FLOAT",
                    {
                        "default": SMALL_RATIO * 100.0,
                        "min": 0.1,
                        "max": 50.0,
                        "step": 0.5,
                        "tooltip": (
                            "多小的一块算零碎噪点：以最大块面积的百分比计。仅在「剔除碎块」开启时生效。"
                        ),
                    },
                ),
                "threshold": (
                    "FLOAT",
                    {
                        "default": SURENESS,
                        "min": 0.05,
                        "max": 0.95,
                        "step": 0.05,
                        "tooltip": (
                            "SAM 3 判定「匹配」所需的最低确信度。小物体被漏掉就调低；把不是目标的东西框进来了就调高。"
                        ),
                    },
                ),
                "fill_holes": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": (
                            "填补完全位于蒙版内部的空隙（分割在头发、布料上常留的洞）。开启后得到实心形状。"
                        ),
                    },
                ),
                "free_vram": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": (
                            "搜索结束后立刻把 SAM 3 移出显存。后面还要加载大模型的工作流建议开启；关闭则下一次搜索稍快。"
                        ),
                    },
                ),
            },
        }

    RETURN_TYPES = ("MASK", "IMAGE", "INT")
    RETURN_NAMES = ("mask", "cut_out", "found")
    OUTPUT_TOOLTIPS = (
        "目标所在处为白。每张图一张遮罩。",
        "除目标外全部透明的图（RGBA）。",
        "第一张图里命中了几处。",
    )
    FUNCTION = "execute"

    def __init__(self):
        # Per instance, so two of these in one graph never overwrite each
        # other's preview file.
        self._prefix = f"qg_mask_by_name_{uuid.uuid4().hex[:6]}"

    def _detect(self, model, clip, image, name, threshold):
        """Every match in every picture: (N x H x W masks, matches per picture,
        how sure it was of each match in the first picture).

        ComfyUI's own nodes do the work: CLIP Text Encode reads the name and
        SAM3 Detect searches. Nothing of theirs is copied here."""
        core = _core_nodes()
        detector = core.get("SAM3_Detect")
        encoder = core.get("CLIPTextEncode")
        if detector is None or encoder is None or not hasattr(detector, "execute"):
            raise RuntimeError(NEEDS_SAM3)
        try:
            conditioning = encoder().encode(clip, search_text(name))[0]
            output = detector.execute(
                model=model,
                image=image,
                conditioning=conditioning,
                threshold=float(threshold),
                refine_iterations=REFINE_PASSES,
                individual_masks=True,
            )
        except Exception as error:  # noqa: BLE001 - told apart just below
            if _stopped_by_user(error) or _out_of_memory(error):
                raise
            # A model or text reader that is not SAM 3's fails somewhere
            # inside; say what to wire instead of showing that.
            raise RuntimeError(f"{NOT_SAM3} ({type(error).__name__}: {error})") from error
        masks, boxes = output.result
        counts = [len(frame) for frame in boxes]
        # How sure SAM 3 was of each match in the first picture, best first.
        scores = sorted(
            (float(box.get("score", 0.0)) for box in (boxes[0] if boxes else [])),
            reverse=True,
        )
        return masks, counts, scores

    def execute(
        self, image, checkpoint, name, several, grow, soften, if_nothing,
        preview=True, drop_small=True, small_size=SMALL_RATIO * 100.0,
        threshold=SURENESS, fill_holes=False, free_vram=False,
    ):
        text = clean_name(name)
        if not text:
            raise ValueError(NO_NAME)
        model, clip = _load_sam3(str(checkpoint))
        try:
            masks, counts, scores = self._detect(model, clip, image, text, threshold)
        finally:
            # Also when the search failed or is about to stop the run: SAM 3
            # was loaded for it either way. The cached copy stays in RAM - the
            # unload only takes it out of the graphics card, so the next run
            # does not read the file again.
            if free_vram and _free_sam3(model, clip):
                # 卸载成功才裁缓存：没卸掉时删掉引用也不会释放，反而下次要重读
                _trim_sam3_cache(1)
                print("[QG 工具] SAM 3 unloaded from VRAM.")
        if not sum(counts) and str(if_nothing) != "empty mask":
            raise RuntimeError(nothing_message(text))
        per_picture = [pick(found, str(several)) for found in split_by_frame(masks, counts)]
        mask = torch.stack(per_picture).to(dtype=torch.float32)
        if (
            drop_small or fill_holes
            or int(grow) > 0 or float(soften) > 0
        ):
            mask = refine_mask(
                mask, int(grow), float(soften), bool(fill_holes),
                bool(drop_small), float(small_size) / 100.0,
            )
        found = int(counts[0]) if counts else 0
        result = (mask, cut_out(image, mask), found)
        ui = {}
        if preview:
            ui = _save_preview(tint_preview(image, mask), self._prefix)
        return {"ui": ui, "result": result}


NODE_CLASS_MAPPINGS = {"QG_MaskByName": QGMaskByName}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_MaskByName": "Mask by Name"}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
