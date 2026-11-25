# Third-party notices

## AlekPet/ComfyUI_Custom_Nodes_AlekPet — GoogleTranslateTextNode (ported via ComfyUI-QG-tools)

This pack's `QG_GoogleTranslate` node (`qg_google_translate.py` +
`web/qg_google_translate.js`) is a **ported** version of AlekPet's
`GoogleTranslateTextNode` (MIT License). The code reached this pack through
`ComfyUI-QG-tools` — the user's own plugin, which had already localized and
reworked the upstream node on 2026-10-24; this pack ported it again on
2026-11-25.

Measured with this pack's line-similarity metric (non-empty, non-comment
lines, blocks of 2+ identical lines / this pack's line count): **72%** of
`qg_google_translate.py` (267/369 lines).

Kept, verbatim or near-verbatim: the embedded `LANGUAGES` table (106 entries —
deliberately one fewer than `googletrans`, see the compliance note in the
source), `normalize_text`, `split_chunks`, `_split_line`, `_free_translate`,
`_key_translate`, `_translate_chunk`, `translate`, the dual-backend
(auto-select free endpoint vs. official API via `GOOGLE_TRANSLATION_API_KEY`),
the two-path retry (normal network stack, then a direct no-proxy session), and
the pass-through-original-text-on-failure behaviour.

Written or rewritten for this pack: the node shell converted from the ComfyUI
V3 `io.Schema` API to this pack's uniform V1 style (`INPUT_TYPES` /
`RETURN_TYPES` / Chinese tooltips), the manual-translate route moved to this
pack's own `/qgmp/translate/manual` path (the QG-tools original stays on
`/qg/translate/manual`; both plugins can coexist), the inlined
`_safe_route_error` path-scrubbing helper, and the front-end button code
re-targeted to the new route and this pack's toast helper.

Upstream: https://github.com/AlekPet/ComfyUI_Custom_Nodes_AlekPet (MIT).
The MIT license text applies to the ported portions; see LICENSE in this pack.

## ComfyUI-AusBoss — Mask by Name (partly adapted)

This pack's `QG_MaskByName` node is **partly adapted** from AusBoss's "Mask by
Name 🆎" node, not written from scratch. Measured against upstream v2.14.0:

| file | upstream lines | kept |
| --- | ---: | ---: |
| `mask_by_name_node.py` | 279 | 225 (81%) |
| `mask_by_name_helpers.py` | 156 | 114 (73%) |

Kept, verbatim or near-verbatim: the node class, its `INPUT_TYPES` and the
tooltip strings, `_detect`, `clean_name`, `search_text`, `nothing_message`,
`split_by_frame`, `pick`, `cut_out`, `tint_preview`, and the small helpers
`_core_nodes` / `_model_management` / `_free_sam3` / `_stopped_by_user` /
`_out_of_memory`.

Written for this pack: the SAM 3 checkpoint dropdown with its loader and the
one-slot cache, the safetensors-header check that refuses a non-SAM 3 file,
the four-step refinement (`grow_mask`, `soften_mask`, `fill_holes_mask`,
`drop_small_pieces` and their pure-torch fallbacks) and the preview saving.
The refinement follows the same approach as AusBoss's own `_mask_helpers.py`
(dilation by `max_pool2d`, border flood for holes), but the code differs:
single square kernels instead of separable passes, scipy when installed with a
torch fallback, and no erosion.

The core detection itself is ComfyUI's own built-in `SAM3_Detect` node, used
by both projects through its public class.

- Upstream: https://github.com/ausboss/ComfyUI-AusBoss
- Author: ausboss
- License: MIT

MIT License text (from the upstream repository):

```
MIT License

Copyright (c) 2025 ausboss

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## ComfyUI

Runs as a ComfyUI custom node; the detection uses ComfyUI's built-in
`SAM3_Detect` (comfy_extras/nodes_sam3.py) and `CLIPTextEncode` through their
public classes.

- https://github.com/comfyanonymous/ComfyUI — GPL-3.0

## BRIA RMBG-2.0 (model weights, optional)

`QG_BiRefNet` offers `RMBG-2.0` as an optional model. The weights are **not**
bundled with this pack: they are downloaded at runtime on first use, either
from the public mirror `1038lab/RMBG-2.0` or from a local model library the
user mounts themselves. The model definition (`birefnet.py`) is loaded from
the user's model directory, not copied into this repository.

- Upstream: https://huggingface.co/briaai/RMBG-2.0
- Author: BRIA AI
- License: BRIA "bria-rmbg-2.0" license — free for non-commercial use,
  commercial use requires a separate license from BRIA.
  See https://bria.ai/license for the full terms.
- The upstream repository is gated; the mirror above is a public copy that
  does not require accepting the terms. Users are responsible for complying
  with the original license when using these weights.

This pack only provides code that loads the weights; it grants no rights to
the model itself.

## Goohaitools-comfyui — functional reference (two ported items, see below)

**Exception — bundled template assets for `QG_IDPhotoOutfit` (from v2.10.0):**
the image templates under `models/id_photo/` (7 category folders, 200 jpg
files) and their `id_photo_data.json` prompt mapping are **copied verbatim**
from Goohaitools-comfyui's `image/ID_Photo/` directory (author-requested
bundling of the full set). Goohaitools-comfyui is distributed under
GPL-3.0, and so is this pack, so redistribution is license-compatible;
the assets are unmodified copies, attribution is recorded here, and the
upstream project (`Goohaitools-comfyui`) remains the origin of these files.
The `QG_IDPhotoOutfit` node code itself (scanning, prompt resolution,
HTTP routes) is this pack's own implementation and does not copy upstream
source.

**Exception — bundled template assets for `QG_MarriageCloth` (from v2.11.0):**
the 81 garment photos under `models/marriage_cloth/` are **copied verbatim**
from Goohaitools-comfyui's `image/marriage registration/` directory
(author-requested bundling of the full set). Same situation as above:
GPL-3.0 to GPL-3.0, unmodified copies, attribution recorded here, upstream
project remains the origin. The `QG_MarriageCloth` node code (scan order,
resize modes, path sanitising, HTTP routes) is this pack's own
implementation and does not copy upstream source.

Most nodes in this pack align their **functional spec** with nodes from
Goohaitools-comfyui (`QG_IDPhotoCrop`, `QG_IDPhotoOutfit`,
`QG_MarriageCloth`, `QG_MaskTopExpand`, `QG_FaceAlign`,
`QG_IDPhotoPrompt`, and `QG_PhotoSheetMixed`).
Their behaviour was studied and then re-implemented independently; each one
also lists what was deliberately changed (see the node's module docstring
and the README source table). No source file from that project is bundled
with this pack; the only bundled upstream material is the template **image
assets and prompt JSON** described in the exception sections above. For
`QG_IDPhotoPrompt` specifically, the Chinese option *labels* come from the
public spec (data, not code); the option values, prompt assembly, random
handling and front-end hook are this pack's own. For `QG_PhotoSheetMixed`,
the thirteen layout names and their centimetre sizes come from the public
spec, while the layout table, geometry engine and rendering are own code.

**Exception — `QG_IDCardSheet` (`id_card_sheet_node.py`), re-written after
studying the Goohaitools "身份证自动扶正拼版" source (GPL-3.0):** unlike the
functional-reference nodes above, this node was written *after* reading the
reference implementation's source, not merely its behaviour. Three core
algorithms (corner detection, portrait-orientation decision, tone-timing)
were replaced with independent implementations; the control flow and
parameter naming follow the reference. Both projects are GPL-3.0, so the
result is license-compatible; this pack does not redistribute any Goohaitools
source file — the rewritten logic lives in this pack's own file with
attribution here, per the license. Whether this constitutes a derivative work
was judged acceptable by the author as an independent re-implementation of
the changed parts.

**Exception — `QG_QwenTextEncode` / `QG_QwenRestore`
(`qwen_text_encode_node.py`), ported from "Qwen Image 2.1 文本编码 GH" /
"Restore Qwen Image 2.1 GH" (`nodes/Text Encode Qwen Image 2.1 GH.py`):
these two ARE a line-for-line port, not an independent re-implementation.**
The node drives ComfyUI conditioning internals
(`reference_latents` injection, `keep_vision` / `prevent_empty_text`
tokenize flags, VAE-encoded initial latents, noise-mask expansion and
feathering) where any paraphrasing could silently change generation
results, so the execution logic was deliberately kept line-identical:
282 comparisons (full sweeps of the pure size/mask/area helpers, six
full-pipeline encode scenarios against the real reference classes with
fake CLIP/VAE recorders, restore edge cases, INPUT_TYPES diff) produce
zero differences. Differences are limited to registration keys
(`QG_QwenTextEncode` / `QG_QwenRestore` vs `TextEncodeQwenImage21GH` /
`RestoreQwenImage21GH`), category, Chinese comments, and a small
front-end addition (the "参考图尺寸" label also covers the widget form,
the reference only covers the input-slot form). The restore info type
name `QWEN_IMAGE_21_GH_RESTORE_INFO` is kept so info ports are
interoperable in both directions. Line similarity under the README's
rule: **92.26%** (274/297 lines). Both projects are GPL-3.0; this pack
does not redistribute any Goohaitools source file — the ported logic
lives in this pack's own file with attribution here, per the license.

**Exception — `QG_QwenPromptOptimizer`
(`qwen_prompt_optimizer_node.py` + `qwen_prompt_optimizer_runtime.py` +
`web/qg_qwen_prompt_optimizer.js`), ported from "Qwen image 2.1 提示词
优化" (`nodes/Qwen image 2.1 提示词优化.py`,
`resources/qwen_image_runtime.py`, `web/js/qwen_image_prompt_optimizer.js`):
this IS a line-for-line port, not an independent re-implementation.**
The prompt assembly (language lock, reverse-prompt instructions,
transparent-background rewriting regexes), the LLM sampling parameters,
and the memory/unload strategy directly determine what is fed to the
local llama-cpp model and how VRAM behaves, so any paraphrasing could
silently change the model's output; the logic was therefore kept
line-identical. 227 comparisons (full sweeps of the pure text-prompt
helpers, INPUT_TYPES diff, nine optimize scenarios with a fake
`QwenImageRuntime.complete` recording every argument, llama installer
helpers) produce zero differences against the real reference classes.
As of v0.1.1 the `en_action.target` character class was restored to the
ASCII punctuation set after a copy-paste slip had briefly replaced it with
the Chinese clause set; regression cases where English punctuation is
followed by further text are now part of the comparison set.
The three embedded system-prompt assets
(`qwen_image_system_prompt_t2i.py` / `_i2i.py` / `_reverse.py`) are
copied verbatim (md5-identical) as GPL-licensed data assets. Differences
are limited to: registration key (`QG_QwenPromptOptimizer`),
HTTP route prefix (`/qg_qwen_prompt_optimizer/*`), internal state flag
names using a `qg` prefix so the reference plugin and this pack can live
on the same canvas without interfering, the console timing prefix
(`[QG Qwen]`), an added `PromptServer` null guard so the module can be
imported outside a running server, and Chinese comments. Line similarity
under the README's rule: runtime **98.94%** (937/947), node **95.65%**
(308/322), front-end **84.54%** (257/304). Both projects are GPL-3.0;
no Goohaitools source file is redistributed — the ported logic lives in
this pack's own files with attribution here, per the license.

**Compliance-driven intentional difference (v2.18.4):** the upstream
"click to auto-install" installs `llama-cpp-python` by calling `pip install`
through `subprocess` from inside the node process. The Comfy Registry
security standard explicitly forbids this
("Runtime package installation through subprocess calls is not permitted",
docs.comfy.org/registry/standards). This pack therefore removes
`_find_llama_wheel`, `_install_llama_cpp`, the `subprocess`/`urllib.request`/
`asyncio` imports and the async install lock. The `/install_llama` route and
its handler name are retained for backward compatibility, but now only return
a manual-install hint (matched wheel suffix + the official releases URL);
the front-end button opens that page instead of POSTing an install request.
The detection helpers that the zero-difference comparison asserts on —
`_version_tuple`, `_llama_install_target`, `_llama_dependency_status` — are
byte-identical to upstream, so all 227 comparison checks still pass.

Measured for `QG_RatioResolution` vs "比例与分辨率"
(`GoohaiRatioAndResolution`): the sizing semantics are deliberately kept
line-for-line equivalent (original-ratio from an optional image, six
sizing modes, 1024²-per-megapixel area, nearest multiple rounding with a
one-multiple floor, simplest-integer-ratio output for original/custom,
ui-event echo of the executed size) so results stay interchangeable —
936 input combinations against the real reference class produce zero
differences, including the `ui` payload. The frontend
(`web/qg_ratio_resolution.js`) reproduces the same widget show/hide rules
and the cyan live width/height preview on the output ports. With the
README's line-similarity rule this file is intentionally high —
**56.15%** (73/130 lines: the option tables, the size helper functions
and the mode branches that mirror the reference semantics); no source
file was copied, the reference was re-typed from its documented behaviour
and verified only through black-box comparison.

Measured for `QG_MaskBlend` vs "孤海-遮罩混合运算", using the README's
line-similarity rule (contiguous blocks of 2+ identical lines divided by
the line count of this pack's file): **1.9%** — 4 lines, all of them the
`INPUT_TYPES` dictionary skeleton (`return {`, `"required": {`, `},`,
`"optional": {`). No business-logic line is shared; the two files also
differ in structure (one long inline `execute` vs. constant tables plus
eight small pure functions). A 960-case behavioural comparison
(8 blend modes x 6 BBOX rules x 5 alignments x 4 input classes) produced
852 identical results, and every difference is a defect fixed in this pack.

Measured for `QG_MaskAnalysis` vs "孤海-遮罩分析" with the same rule:
**1.24%** — 2 lines (`return {`, `"required": {`), with no business-logic
line shared. A 1024-case comparison (4 mask shapes x 4^4 percentage
combinations) produced **1024 identical results**; the only differences are
three boundary fixes in this pack (batch inputs, 2D/4D shapes, all-black
mask). The reference's shrink-guard formula (comparing a percentage sum
against `0.9 x rectangle pixels`) is dimensionally odd but was kept as-is
so that existing workflow parameters stay interchangeable.

Measured for `QG_MaskDetect` vs "孤海遮罩检测" with the same rule:
**8.70%** — 8 lines in 2 contiguous blocks: 4 lines of `INPUT_TYPES`
skeleton, and 4 lines declaring the slider's `default` / `min` / `max` /
`step` numbers (these spec values have to match so workflow parameters stay
interchangeable). No business-logic line is shared: the reference computes
with numpy, this pack with torch. A 448-case comparison (7 shapes x 8 fill
ratios x 8 thresholds), 36 edge-value cases and 12 representative
side-by-side cases all produced identical results. Strict `> 0.5`, the
whole-array area ratio and the zero-threshold shortcut were deliberately
kept as-is rather than "fixed".

Measured for `QG_ImageScale` vs "图像缩放V2 孤海" with the same rule:
**2.43%** — 14 lines in 6 contiguous blocks: 2 `import` lines, 4 lines of
the interpolation-name -> PIL constant table (these names must match so
workflow parameters stay interchangeable), and 6 lines of `INPUT_TYPES`
dictionary skeleton. No business-logic line is shared. A 412-case
comparison (3 scale methods x 6 modes x 5 interpolations x 5 anchors x
3 conditions x several width/height/divisor combinations), 30 boundary
cases (mask-only, image-only, batch, mask broadcast, 4D masks) and 12
representative side-by-side cases all produced byte-identical image and
mask tensors plus identical width/height. Behaviour that looks odd but was
deliberately kept as-is: proportional scaling with `multiple_of <= 1`
ignores the scale mode entirely; masks are resampled with the same
interpolation as the image rather than NEAREST; edge-pixel padding leaves
the four corners black; the "no scaling needed" branch crops the original
instead of resampling. The colour widget reuses this pack's own
`STRING`-based picker rather than the reference plugin's `GHCOLOR` custom
type; the stored `#RRGGBB` value is interchangeable.

Measured for `QG_AddWatermark` vs "孤海-图像添加水印" with the same rule:
**3.60%** — 8 matching lines out of 222 effective lines of this pack,
measured by running `tests/test_watermark.py` against the current source
(8 lines in 4 contiguous blocks: PIL/torch `import` lines,
resampling-constant fallbacks and `Image.alpha_composite` call skeletons).
This percentage moves slightly as the source grows: older notes quoting
3.64% or 3.69% were computed at different line counts and are superseded.
No business-logic line is shared (the reference uses Chinese identifiers and
inline methods; this pack uses English helper functions). A 19-case
comparison (16 text-watermark cases covering the 3x3 position grid,
percentage offsets, tiling, rotation, opacity, alpha output and the
larger-canvas angle quirk, plus 3 image-watermark cases) produced
pixel-identical tensors. Earlier notes quoting "16 cases / 13 text cases"
counted only part of the suite and are superseded. Semantics kept
as-is on purpose: only the first frame of a batch is processed, text size
is a percentage of the base-image height while image watermarks scale by
their own size, rotation uses `expand=True` + bicubic, tiling starts at
minus one watermark size; at angle 0 the position is computed from the text-bbox size while
the pasted layer includes the safety margin (a 1px+ offset at large font sizes), kept
as-is so outputs stay interchangeable. The plugin's local `fonts/` folder
holds assorted proprietary fonts (PingFang, STXihei, Founder, ZhongYi KaiTi /
SimHei, Bitstream OCR-B / Swis721, Akkurat, "Capture it"), whose embedded
name records all claim All Rights Reserved; the PingFang files explicitly
say "Apple Inc internal use only. Do not distribute.". That folder is
excluded by `.gitignore` AND by the packaging script, and the font
dropdowns never read it. See the Noto Sans SC entry below for the
open-licensed font that *is* bundled; user fonts may still be dropped into
`ComfyUI/models/fonts/`.

- Reference plugin: Goohaitools-comfyui (installed locally, not redistributed)
- License: GPL-3.0 — the same license as this pack's own `LICENSE`
- Most of this entry records a *functional reference*, not copied code;
  the exceptions are the Qwen Image 2.1 encode/restore pair and the
  Qwen image 2.1 prompt optimizer described at the top, which are
  GPL-compliant line-for-line ports with attribution.


## ComfyUI_essentials — functional reference only (no code copied)

`QG_GetImageSize` aligns its ports and output values with "获取图像尺寸"
(node id `GetImageSize+`, class `GetImageSize` in `image.py`) from
ComfyUI_essentials by Matteo Spinelli. ComfyUI core also ships a similar
built-in node (`GetImageSize`, third output named `batch_size`); the QG node
follows the essentials naming (`count`). No source file from either project
is bundled with this pack.

Measured with the README's line-similarity rule against the reference
**class** (14 effective lines), not the whole 1379-line `image.py`:
**2.94%** — 2 lines (`return {`, `"required": {`), both `INPUT_TYPES`
dictionary skeleton. The core value expression is not shared: the reference
returns a single `return (image.shape[2], image.shape[1], image.shape[0])`,
while this pack normalises the tensor first and assigns each value
separately. Comparing against the whole `image.py` gives 8.82%, but the
extra 4 lines come from other classes' generic skeleton (`@classmethod` /
`def INPUT_TYPES(cls):`), not from this node.

A 240-case comparison over 4D shapes produced **240 identical results**.
The only differences are boundary fixes in this pack (2D grayscale, plain
lists, missing input, and 5D+ shapes); no standard `[B,H,W,C]` input is
affected.

- Reference plugin: ComfyUI_essentials (installed locally, not redistributed)
- License: MIT (permissive). This pack's own `LICENSE` is GPL-3.0. This
  entry records a *functional reference*, not copied code.
- As before, this is an engineering assessment, not legal advice.


## ComfyUI-KJNodes — functional reference only (no code copied)

`QG_SetPoint` / `QG_GetPoint` ("QG 设置点" / "QG 获取点") reproduce the
user-facing behaviour of the `SetNode` / `GetNode` pair from
ComfyUI-KJNodes by kijai (installed locally as `comfyui-kjnodes`,
`web/js/setgetnodes.js`): a named virtual Set node with one wildcard input
and one wildcard output, and a Get node with a combo of Set names and one
wildcard output, so a long wire can be replaced by a name.

No source file from KJNodes is bundled with this pack. The implementation
is a standalone `web/qg_setget.js`; the mechanism it relies on is the
public ComfyUI frontend contract, verified in the locally installed
frontend package 1.57.4: `graphToPrompt` skips nodes flagged
`isVirtualNode`, and `ExecutableNodeDTO.resolveOutput` re-resolves such a
node through `resolveVirtualOutput(slot)` or `getInputLink(slot)`. The Set
node keeps LiteGraph's own `getInputLink`, while the Get node overrides it
to return the link on the matching Set node's input.

Measured with the README's line-similarity rule (consecutive blocks of at
least 2 identical lines / effective lines of this pack's file):
**9.37%** — 16 blocks, 43 lines, all of them LiteGraph hook signatures and
brace scaffolding (`onAdded() {`, `onConfigure() {`,
`getExtraMenuOptions(_, options) {`, `options.unshift(`, `}`, etc.). No
business logic is shared. The higher figure compared with the Python
nodes comes from both files being JavaScript extensions of `LGraphNode`
using the same public hook names.

Deliberate scope differences: QG nodes use their own registration keys,
fixed Chinese titles / slot labels / widget label, no automatic node
colouring, no virtual-link drawing, no subgraph scope lookup, no settings
commands or keybindings, and no backend `/object_info` definition. They
inject a Chinese node definition through `addCustomNodeDefs`, so they are
searchable under "QG 工具" with the same green `frontend_only` badge,
without restarting the backend.

- Reference plugin: ComfyUI-KJNodes (installed locally, not redistributed)
- Upstream: https://github.com/kijai/ComfyUI-KJNodes
- License: GPL-3.0 — the same license as this pack's own `LICENSE`
- This entry records a *functional reference*, not copied code.


## ComfyUI-Easy-Use — functional reference only (no file copied)

`QG_PromptLine` ("提示词行") reproduces the behaviour of the `easy
promptLine` node from ComfyUI-Easy-Use by yolain (installed locally as
`ComfyUI-Easy-Use`, `py/nodes/prompt.py::promptLine`): a multiline text
widget split into per-line outputs — a STRING list and a COMBO list —
with `start_index` / `max_rows` slicing and an optional empty-line filter.
The frontend part (`web/qg_prompt_line.js`) adds the same "get values
from COMBO link" button that reads the downstream combo widget's full
option list back into the text widget.

No source file from Easy-Use is bundled with this pack. The five lines of
slicing logic are intentionally kept line-for-line equivalent to the
reference (verified equal on 280 input combinations) so outputs are
interchangeable; everything else (registration, tooltips, docs, frontend)
is written independently. One deliberate hardening: the reference crashes
with a bare `TypeError` when the downstream input is not a converted
combo widget; this pack shows an error toast instead.

Measured with the README's line-similarity rule (consecutive blocks of at
least 2 identical lines / effective lines of this pack's file):
**9.09%** — 1 block, 5 lines (the slicing logic described above).

- Reference plugin: ComfyUI-Easy-Use (installed locally, not redistributed)
- Upstream: https://github.com/yolain/ComfyUI-Easy-Use
- License: GPL-3.0 — the same license as this pack's own `LICENSE`
- This entry records a *functional reference*, not copied code.


## HivisionIDPhotos — functional / spec reference (beauty LUT & param split)

`QG_PortraitMatte`'s whitening LUT (`assets/lut_origin.png`, a 64³ cube) and
`QG_IDPhotoParams`'s size/preset table follow the parameter conventions of
HivisionIDPhotos, the open-source ID-photo toolkit: the print-blue `#438edb`,
red `#d93b3b`, dark-blue `#1b4b8f` palette and the 20 standard preset sizes
are taken from its spec. The code is written independently; **no HivisionIDPhotos
source code is bundled** with this pack. Two of its official release ONNX weights
*are* redistributed (see the dedicated entry below).

- Upstream: https://github.com/Zeyi-Lin/HivisionIDPhotos
- License: Apache-2.0
- This entry records a *functional/spec reference*, not copied code.

## MODNet / HivisionIDPhotos ONNX weights (bundled, Apache-2.0)

Two matting weights are redistributed **unmodified** with this pack at
`models/background_removal/`, so `QG_PortraitMatte` works on an offline machine:

| File | Size | SHA-256 | Origin |
| --- | --- | --- | --- |
| `modnet_photographic_portrait_matting.onnx` | 25.9 MB | `07c308cf0fc7e6e8b2065a12ed7fc07e1de8febb7dc7839d7b7f15dd66584df9` | MODNet official weights, served by the HivisionIDPhotos release |
| `hivision_modnet.onnx` | 25.9 MB | `7e0cb9a2a841b426dd0daf1a788ec398dab059bc039041d62b15636c0783bc56` | weight trained by the HivisionIDPhotos project, same release |

- Source: `https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/pretrained-model/`
- Licenses: the HivisionIDPhotos README states *"This repository is licensed under
  the Apache-2.0 License"*; ZHKKKe/MODNet (origin of the first weight) ships the
  standard Apache-2.0 LICENSE. Neither upstream README attaches a separate
  commercial or non-commercial restriction to these two weights. Should upstream
  publish a model-specific notice later, that notice prevails.
- The full Apache-2.0 text is included as
  `models/background_removal/LICENSE-APACHE-2.0.txt`; provenance, download URLs
  and hashes are in `models/background_removal/NOTICE.md`.
- This pack as a whole is GPL-3.0. These ONNX files are independent data assets,
  not linked into the pack's code; their license and attribution are retained
  separately under this entry. Apache-2.0 is GPLv3-compatible.
- `rmbg-1.4.onnx` (BRIA AI) and `birefnet-v1-lite.onnx` (ZhengPeng7) are **not**
  bundled: their upstream terms differ, and they remain on-demand downloads.

## dlib — shape_predictor_5_face_landmarks.dat (bundled model)

- File: `shape_predictor_5_face_landmarks.dat` (about 9.1 MB, bundled)
- Source: the dlib project by Davis King (http://dlib.net) — the 5-point
  face landmark model shipped with dlib's `python_examples`
- License: Boost Software License 1.0 (the dlib project's license)
- Used by: `QG_FaceRectify` (5-point facial landmarks for face
  straightening); the node degrades gracefully to a no-op pass-through
  when the file is missing
- Redistribution note: the model is bundled so the node works offline;
  it may also be obtained directly from dlib's official distribution.


## Noto Sans SC — bundled font (SIL OFL 1.1)

- Files: `assets/fonts/NotoSansSC-VF.ttf` (16.95 MB) and
  `assets/fonts/OFL.txt` (the complete SIL Open Font License 1.1 text).
- Upstream: https://github.com/notofonts/noto-cjk and
  https://github.com/adobe-fonts/source-han-sans
- Copyright (font nameID 0): "© 2014-2021 Adobe (http://www.adobe.com/),
  with Reserved Font Name 'Source'." The font's nameID 13 states
  "This Font Software is licensed under the SIL Open Font License,
  Version 1.1" and nameID 14 points at http://scripts.sil.org/OFL.
- Redistribution: the file is an **unmodified** copy of the official
  variable font shipped with the OS font library. OFL 1.1 permits
  bundling, redistribution and commercial use as long as the license text
  accompanies the font, the font is not sold on its own, and the Reserved
  Font Name ("Source") is not used for derivatives. This pack uses the
  name "Noto Sans SC" and does not use the reserved name.
- Used by: `QG_PhotoSheet`, `QG_PhotoSheetMixed` and `QG_Watermark`.
  It is listed first in the font dropdowns and is the default font for
  `QG_Watermark`, so Chinese captions and watermarks work out of the box
  without relying on fonts installed on the host. Because the official
  file is a variable font whose default instance is Thin, the loader pins
  it to the `Regular` instance at runtime (no font file is modified).
- Not bundled: the proprietary fonts in the plugin's local `fonts/`
  directory. Earlier backup archives (v2.1.0–v2.12.0) accidentally
  included them because the packaging script's exclude list did not
  mirror `.gitignore`; the script now excludes the whole top-level
  `fonts/` directory and asserts that no such file enters an archive.
