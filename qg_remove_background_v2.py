# -*- coding: utf-8 -*-
"""QG 移除背景 V2 —— 粗分割 + 多种边缘细节精修。

按 LayerStyle「RmBgUltra V2」（节点 key ``LayerMask: RmBgUltra V2``）的
**功能规格**独立实现，源码结构与实现细节全部自行编写，未复制其代码。
两者的定位差异：

* 粗分割不自带 RMBG-1.4 权重，直接复用本包 ``QG_BiRefNet`` 的推理器与
  缓存（models/RMBG），因此不会额外下载第二套模型；
* 细节精修保留截图里的五种方法：VITMatte / VITMatte(local) /
  vitmatte-base-composition-1k / PyMatting / GuidedFilter；
* 输出与原节点一致：RGBA 图像 + 单通道 MASK。

依赖：transformers（ViTMatte）、pymatting + pyamg（PyMatting）、
opencv-contrib（GuidedFilter 与 trimap 形态学）。缺少某一项时只影响
对应的细节方法，给出明确中文提示；``process_detail=False`` 时不依赖它们。
"""

from __future__ import annotations

import math
import os

import numpy as np
import torch
from PIL import Image

import comfy.model_management as mm

try:  # 本包内部复用：粗分割走 QG_BiRefNet 的单例运行器与权重缓存
    from . import birefnet_node as _BR
except (ImportError, ValueError):  # 单文件 spec 加载时没有包上下文
    try:
        import birefnet_node as _BR
    except ImportError:  # pragma: no cover - 插件不完整时才走到
        _BR = None

# 根目录解析统一走 qg_model_paths（两种加载场景都要拿到）
try:  # pragma: no cover - 取决于加载方式
    from . import qg_model_paths as _QP
except ImportError:  # pragma: no cover
    import qg_model_paths as _QP

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


DETAIL_METHODS = [
    "VITMatte",
    "VITMatte(local)",
    "vitmatte-base-composition-1k",
    "PyMatting",
    "GuidedFilter",
]
DEVICES = ["auto", "cuda", "cpu"]

# 粗分割默认模型。可用环境变量覆盖，无需在工作流里多一个控件。
DEFAULT_COARSE_MODEL = "BiRefNet-general"
_MODEL_ENV = "QG_REMOVEBG_MODEL"

_VIT_REPOS = {
    "VITMatte": "hustvl/vitmatte-small-composition-1k",
    "VITMatte(local)": "hustvl/vitmatte-small-composition-1k",
    "vitmatte-base-composition-1k": "hustvl/vitmatte-base-composition-1k",
}
# 每种 ViTMatte 方法在 ComfyUI/models/background_removal 下的目录名。
# 权重放这里（随用户模型库走，不进插件包），离线环境无需联网下载。
_VIT_MODEL_DIRS = {
    "VITMatte": "vitmatte-small-composition-1k",
    "VITMatte(local)": "vitmatte-small-composition-1k",
    "vitmatte-base-composition-1k": "vitmatte-base-composition-1k",
}
_VIT_DIR_ENV = "QG_VITMATTE_DIR"

# 模型按 (仓库, 本地目录) 缓存，避免批次里每帧重新加载。
_VIT_CACHE = {}


def _coarse_model_name(model):
    return os.environ.get(_MODEL_ENV) or model or DEFAULT_COARSE_MODEL


# --------------------------------------------------------------------------
# 基础转换
# --------------------------------------------------------------------------
def _frame_to_rgb(frame):
    """一帧 ComfyUI IMAGE（0..1 浮点）→ uint8 RGB PIL。"""
    if _BR is None:
        array = np.asarray(frame)
        array = np.clip(array, 0.0, 1.0)
        if array.ndim == 3 and array.shape[-1] >= 3:
            array = array[..., :3]
        elif array.ndim == 2:
            array = np.repeat(array[..., None], 3, axis=-1)
        data = (array * 255.0 + 0.5).clip(0, 255).astype(np.uint8)
    else:
        data = _BR._frame_to_rgb_uint8(frame)
    return Image.fromarray(data, "RGB")


def _to_alpha_u8(alpha):
    """0..1 浮点遮罩 → 0..255 uint8，先 nan_to_num 再 clamp。"""
    arr = np.asarray(alpha, dtype=np.float32)
    arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=0.0)
    return (np.clip(arr, 0.0, 1.0) * 255.0 + 0.5).clip(0, 255).astype(np.uint8)


def remap_histogram(alpha, black_point, white_point):
    """按黑/白点重映射 alpha：bp 与 wp 之间线性拉到 0..1。"""
    bp = min(float(black_point), float(white_point) - 0.001)
    scale = 1.0 / max(float(white_point) - bp, 0.001)
    arr = np.asarray(alpha, dtype=np.float32)
    return np.clip((arr - bp) * scale, 0.0, 1.0)


# --------------------------------------------------------------------------
# 粗遮罩 → trimap（ViTMatte 用）
# --------------------------------------------------------------------------
def build_trimap(mask_pil, erode_px, dilate_px):
    """生成 0/128/255 三值 trimap PIL L：膨胀区未知、腐蚀区确定前景。"""
    if cv2 is None:
        raise RuntimeError(
            "生成 trimap 需要 opencv（cv2）。请用 ComfyUI 的 Python 安装 "
            "opencv-contrib-python；或者把「处理细节」关掉。")
    mask = np.asarray(mask_pil.convert("L"), dtype=np.uint8)
    binary = (mask > 127).astype(np.uint8) * 255
    ke = np.ones((max(1, int(erode_px)), max(1, int(erode_px))), np.uint8)
    kd = np.ones((max(1, int(dilate_px)), max(1, int(dilate_px))), np.uint8)
    eroded = cv2.erode(binary, ke, iterations=5)
    dilated = cv2.dilate(binary, kd, iterations=5)
    tri = np.zeros_like(binary)
    tri[dilated > 0] = 128
    tri[eroded > 0] = 255
    return Image.fromarray(tri, "L")


# --------------------------------------------------------------------------
# 细节方法 1/3：ViTMatte
# --------------------------------------------------------------------------
def _resolve_device(device):
    if device == "cpu":
        return torch.device("cpu")
    if device == "cuda" and not torch.cuda.is_available():
        print("[QG-RemoveBG-V2] 指定 cuda 但当前不可用，已回退到 CPU。")
        return torch.device("cpu")
    return mm.get_torch_device()


def _vitmatte_model_roots():
    """ComfyUI/models/background_removal 的全部根路径，按优先级。

    先问 folder_paths（带上 extra_model_paths.yaml 的挂载），再拼 models_dir
    兜底。只拼 models_dir 会让挂载库里的模型明明在、节点却说没找到。
    """
    # 挂载路径 + models_dir 兜底统一由 qg_model_paths 解析，去重保序；
    # 与 _matte_models / birefnet_node 现在共用同一套根目录口径。
    return _QP.category_roots("background_removal")


def _is_vitmatte_dir(path):
    """目录里有可用权重（safetensors 或 bin）+ 两份配置才算命中。"""
    if not os.path.isdir(path):
        return False
    has_weights = (os.path.isfile(os.path.join(path, "model.safetensors"))
                   or os.path.isfile(os.path.join(path, "pytorch_model.bin")))
    has_config = (os.path.isfile(os.path.join(path, "config.json"))
                  and os.path.isfile(os.path.join(path, "preprocessor_config.json")))
    return has_weights and has_config


def _vitmatte_source(method):
    """返回 (模型标识, 是否只允许本地文件)。

    优先级：环境变量 > 用户模型库 > HuggingFace 仓库。命中模型库时返回本地
    绝对路径并置 local_only=True，from_pretrained 只读本地、完全不联网。
    ``VITMatte(local)`` 的严格语义另行保留：即便模型库和缓存都没有，也不联网。
    """
    local_dir = os.environ.get(_VIT_DIR_ENV, "").strip()
    if local_dir:
        return local_dir, True

    folder = _VIT_MODEL_DIRS.get(method, _VIT_MODEL_DIRS["VITMatte"])
    for root in _vitmatte_model_roots():
        candidate = os.path.join(root, folder)
        if _is_vitmatte_dir(candidate):
            return candidate, True

    repo = _VIT_REPOS.get(method, _VIT_REPOS["VITMatte"])
    return repo, method == "VITMatte(local)"


def _load_vitmatte(method):
    try:
        from transformers import VitMatteForImageMatting, VitMatteImageProcessor
    except ImportError as error:
        raise RuntimeError(
            "ViTMatte 细节方法需要 transformers。请用 ComfyUI 的 Python 安装 "
            "transformers；或者改用 GuidedFilter / PyMatting。") from error

    source, local_only = _vitmatte_source(method)
    key = (source, local_only)
    cached = _VIT_CACHE.get(key)
    if cached is None:
        try:
            model = VitMatteForImageMatting.from_pretrained(source, local_files_only=local_only)
            processor = VitMatteImageProcessor.from_pretrained(source, local_files_only=local_only)
        except Exception as error:
            raise RuntimeError(
                "ViTMatte 模型加载失败（%s）。可把权重放到 ComfyUI 的 "
                "models/background_removal/%s 目录（离线可用），或设置环境变量 "
                "%s 指向本地权重目录；首次联网下载 hustvl 权重也可。"
                % (error, _VIT_MODEL_DIRS.get(method, _VIT_MODEL_DIRS["VITMatte"]),
                   _VIT_DIR_ENV)) from error
        cached = (model, processor)
        _VIT_CACHE[key] = cached
    return cached, local_only


def vitmatte_alpha(image_pil, trimap_pil, method, device, max_megapixels):
    """ViTMatte 推理，返回与原图同尺寸的 0..1 alpha numpy 数组。"""
    (model, processor), _ = _load_vitmatte(method)
    work_device = _resolve_device(device)
    orig_w, orig_h = image_pil.size
    ratio = orig_w / float(orig_h)
    max_pixels = max(float(max_megapixels), 1.0) * 1048576.0

    work_image, work_trimap = image_pil, trimap_pil
    if orig_w * orig_h > max_pixels:
        tw = max(1, int(math.sqrt(ratio * max_pixels)))
        th = max(1, int(tw / ratio))
        work_image = image_pil.resize((tw, th), Image.BILINEAR)
        work_trimap = trimap_pil.resize((tw, th), Image.BILINEAR)
    else:
        tw, th = orig_w, orig_h

    model.to(work_device)
    model.eval()
    inputs = processor(images=work_image, trimaps=work_trimap, return_tensors="pt")
    with torch.no_grad():
        inputs = {k: v.to(work_device) for k, v in inputs.items()}
        alpha = model(**inputs).alphas
    arr = alpha[0, 0].float().cpu().numpy()
    arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=0.0)

    # processor 会把边长补到 32 的倍数，先裁掉 padding 再缩放回原尺寸。
    h, w = arr.shape[:2]
    if w > tw or h > th:
        arr = arr[:th, :tw]
    if arr.shape[:2] != (orig_h, orig_w):
        arr = np.asarray(
            Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), "L")
            .resize((orig_w, orig_h), Image.BILINEAR), dtype=np.float32) / 255.0
    return np.clip(arr, 0.0, 1.0).astype(np.float32)


# --------------------------------------------------------------------------
# 细节方法 2/3：PyMatting（闭合形式抠图）
# --------------------------------------------------------------------------
def pymatting_alpha(image_pil, mask_pil, detail_range, black_point, white_point):
    try:
        from pymatting import estimate_alpha_cf, fix_trimap
    except ImportError as error:
        raise RuntimeError(
            "PyMatting 细节方法需要 pymatting 与 pyamg。请用 ComfyUI 的 Python "
            "安装 pymatting pyamg；或者改用 VITMatte / GuidedFilter。") from error
    if cv2 is None:
        raise RuntimeError("PyMatting 细节方法需要 opencv（cv2）做 trimap 平滑。")

    d = int(detail_range) * 5 + 1
    if d % 2 == 0:
        d += 1
    src = np.asarray(mask_pil.convert("L"), dtype=np.float32) / 255.0
    tri = cv2.GaussianBlur(src, (d, d), 0)
    tri = fix_trimap(tri, float(black_point), float(white_point))
    # pymatting 的闭合形式解要求图像是 0..1 浮点，避免库对 0..255 的告警。
    img = np.asarray(image_pil.convert("RGB"), dtype=np.float64) / 255.0
    alpha = estimate_alpha_cf(
        img, tri,
        laplacian_kwargs={"epsilon": 1e-6},
        cg_kwargs={"maxiter": 500},
    )
    return np.clip(np.nan_to_num(np.asarray(alpha, dtype=np.float32)), 0.0, 1.0)


# --------------------------------------------------------------------------
# 细节方法 3/3：引导滤波
# --------------------------------------------------------------------------
def guided_alpha(image_pil, mask_pil, detail_range):
    if cv2 is None or not hasattr(cv2, "ximgproc"):
        raise RuntimeError(
            "GuidedFilter 细节方法需要 opencv-contrib-python（cv2.ximgproc）。"
            "或者改用 VITMatte / PyMatting。")
    radius = int(detail_range) // 6 + 1
    if radius % 2 == 0:
        radius += 1
    guide = np.asarray(image_pil.convert("RGB"), dtype=np.uint8)
    src = np.asarray(mask_pil.convert("L"), dtype=np.float32) / 255.0
    out = cv2.ximgproc.guidedFilter(guide, src, radius, 0.015)
    return np.clip(np.nan_to_num(np.asarray(out, dtype=np.float32)), 0.0, 1.0)


# --------------------------------------------------------------------------
# 节点
# --------------------------------------------------------------------------
class QGRemoveBackgroundV2:
    DESCRIPTION = (
        "Remove background with BiRefNet coarse segmentation and five optional "
        "detail matting methods, output RGBA premultiplied image and mask."
    )
    CATEGORY = "QG 工具"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("IMAGE", "MASK")
    OUTPUT_TOOLTIPS = (
        "去掉背景后的 RGBA 图像；alpha 来自精修后的遮罩，原图颜色保持不变。",
        "单通道遮罩，白色为前景、黑色为背景，灰色是半透明边缘。",
    )
    SEARCH_ALIASES = [
        "remove background", "background removal", "rmbg", "matting",
        "vitmatte", "pymatting", "guided filter", "抠图", "去背景", "去背",
        "移除背景", "边缘细节", "遮罩", "qg",
    ]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {
                    "tooltip": "要移除背景的图像。批次逐帧处理，输出与输入同尺寸。"}),
                "detail_method": (DETAIL_METHODS, {
                    "tooltip": "边缘细节精修方法。VITMatte 系列最细，需首次下载模型；"
                               "PyMatting 需 pymatting+pyamg；GuidedFilter 最快、"
                               "靠 opencv 保持边缘。"}),
                "detail_erode": ("INT", {"default": 6, "min": 1, "max": 255, "step": 1,
                    "tooltip": "trimap 腐蚀核尺寸。值越大，确定前景区越收缩、待处理边缘越宽。"}),
                "detail_dilate": ("INT", {"default": 6, "min": 1, "max": 255, "step": 1,
                    "tooltip": "trimap 膨胀核尺寸。值越大，待处理边缘越宽，细节保留越多。"}),
                "black_point": ("FLOAT", {"default": 0.01, "min": 0.01, "max": 0.98,
                    "step": 0.01, "tooltip": "黑点。低于该透明度判为全透明，可信度过滤用。"}),
                "white_point": ("FLOAT", {"default": 0.99, "min": 0.02, "max": 0.99,
                    "step": 0.01, "tooltip": "白点。高于该透明度判为不透明，与黑点一起拉伸 alpha 范围。"}),
                "process_detail": ("BOOLEAN", {
                    "default": True, "label_on": "开启", "label_off": "关闭",
                    "tooltip": "关闭时直接输出粗分割遮罩，不做任何细节精修，也不需要额外依赖。"}),
                "device": (DEVICES, {
                    "tooltip": "ViTMatte 推理设备。auto 跟随 ComfyUI 当前设备；"
                               "选 cuda 但不可用时自动回退 CPU。"}),
                "max_megapixels": ("FLOAT", {"default": 2.0, "min": 1.0, "max": 999.0,
                    "step": 0.1, "tooltip": "ViTMatte 推理时的最大像素数（百万像素）。"
                                            "超出会按比例缩小再处理，完成后放大回原尺寸。"}),
            },
            "optional": {
                "model": (list(_BR.MODEL_CONFIG.keys()) if _BR else [DEFAULT_COARSE_MODEL], {
                    "tooltip": "粗分割的 BiRefNet 变体。默认 general；portrait 是人像专用。"
                               "也可用环境变量 QG_REMOVEBG_MODEL 覆盖。"}),
            },
        }

    def run(self, image, detail_method, detail_erode, detail_dilate,
            black_point, white_point, process_detail, device, max_megapixels,
            model=DEFAULT_COARSE_MODEL):
        if _BR is None:
            raise RuntimeError(
                "QG 移除背景 V2 依赖本包的 birefnet_node.py，请确认插件完整安装。")

        model_name = _coarse_model_name(model)
        cfg = _BR.MODEL_CONFIG.get(model_name) or {}
        process_res = int(cfg.get("res") or 1024)
        detail_range = max(1, int(detail_erode)) + max(1, int(detail_dilate))
        out_images, out_masks = [], []

        # 上游偶尔给 3 维 [H,W,C]（没有 batch 维）。直接 for 会按行迭代，
        # 静默产出 H 张 2 像素高的图并「成功」返回。本包其它节点都补维。
        # 用 ndim 而不是 dim()：单元测试会直接喂 numpy 数组。
        if int(getattr(image, "ndim", 4)) == 3:
            image = image.unsqueeze(0) if hasattr(image, "unsqueeze") else image[None, ...]

        for frame in image:
            rgb = _frame_to_rgb(frame)
            coarse = _BR._runner.predict(rgb, model_name, process_res)

            if process_detail:
                if detail_method == "GuidedFilter":
                    alpha = guided_alpha(rgb, coarse, detail_range)
                    alpha = remap_histogram(alpha, black_point, white_point)
                elif detail_method == "PyMatting":
                    alpha = pymatting_alpha(
                        rgb, coarse, detail_range, black_point, white_point)
                else:
                    trimap = build_trimap(coarse, detail_erode, detail_dilate)
                    alpha = vitmatte_alpha(
                        rgb, trimap, detail_method, device, max_megapixels)
                    alpha = remap_histogram(alpha, black_point, white_point)
            else:
                alpha = np.asarray(coarse.convert("L"), dtype=np.float32) / 255.0

            alpha = np.nan_to_num(np.asarray(alpha, dtype=np.float32), nan=0.0)
            alpha = np.clip(alpha, 0.0, 1.0)
            rgba = np.dstack((
                np.asarray(rgb, dtype=np.uint8),
                _to_alpha_u8(alpha),
            ))
            out_images.append(rgba.astype(np.float32) / 255.0)
            out_masks.append(alpha.astype(np.float32))

        if not out_images:
            raise RuntimeError("没有可处理的图像。")
        return (
            torch.from_numpy(np.stack(out_images, axis=0)),
            torch.from_numpy(np.stack(out_masks, axis=0)),
        )


NODE_CLASS_MAPPINGS = {"QG_RemoveBackgroundV2": QGRemoveBackgroundV2}
NODE_DISPLAY_NAME_MAPPINGS = {
    "QG_RemoveBackgroundV2": "QG 移除背景 V2 · 细节精修"
}
