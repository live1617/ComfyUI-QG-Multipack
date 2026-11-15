"""QG_MarriageCloth - 结婚登记照服装：选一张服装参考图，出 IMAGE 给图生图。

功能规格参考 Goohaitools「孤海-结婚登记照服装」（GPL-3.0），代码为独立实现，
未复制上游源码。上游的形态是「序号 + 隐藏文件名」两个输入配一个节点内嵌画廊，
这里保留同样的存档字段（序号与文件名都留着），因此上游工作流换过来不用改连线。

和上游做法的差别，都是实测会咬人的地方：

* **不再无条件拉伸到 1024x512。** 上游把任何图 ``resize`` 到固定尺寸，竖图或
  方图会被压扁。这里目标尺寸可配，且默认 ``fit_pad``：按比例缩到框内、居中
  补底色，宁可留边也不变形（``stretch`` 保留上游行为，``original`` 完全不缩放）。
* **序号按自然排序。** 上游用 ``sorted(os.listdir(...))``，``10.jpg`` 会排到
  ``2.jpg`` 前面，序号全错位。这里把文件名里的数字段按数值比较。
* **素材增删不用重启。** 扫描结果按目录签名（文件名 + mtime + 大小）缓存，
  换图、补图后刷新前端即生效。
* **双根合并。** 插件目录自带一批素材，用户还能往 ``ComfyUI/models/marriage_cloth/``
  补自己的图，两边合并显示（同名以内置优先）。
* **文件名白名单清洗。** 图片路由只接受单层图片文件名，穿越、反斜杠、绝对路径、
  非图片扩展一律拒绝。

素材目录（任一存在即生效，多根合并）::

    <插件目录>/models/marriage_cloth/      ← 随包内置
    ComfyUI/models/marriage_cloth/         ← 用户自己补

注册 key：QG_MarriageCloth；输出单帧 IMAGE。
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageColor, ImageOps

try:
    from server import PromptServer
    from aiohttp import web
    # 纯导入 / 测试环境里 instance 还没建，此时不注册路由（节点逻辑不受影响）
    _HAS_SERVER = getattr(PromptServer, "instance", None) is not None
except Exception:  # ImportError 等：无 ComfyUI 环境
    PromptServer = None
    web = None
    _HAS_SERVER = False

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

# 序号 0 表示"不用服装"，此时给一张纯色底图（与上游同色，方便直接接图生图）
FLAT_COLOR_DEFAULT = "#6c1e27"
TARGET_W_DEFAULT = 1024
TARGET_H_DEFAULT = 512
RESIZE_MODES = ["fit_pad", "stretch", "original"]

# 扫描缓存：key 是多根目录签名，素材变动自动失效
_SCAN_CACHE = {"key": None, "items": []}


def _candidate_roots():
    """素材根候选：ComfyUI 的各个 models 根 + 插件目录兜底。"""
    roots = []
    try:
        import folder_paths
        models_dir = getattr(folder_paths, "models_dir", None)
        if models_dir:
            roots.append(Path(models_dir) / "marriage_cloth")
        # extra_model_paths 挂载根：<根>/models/<子目录>/... 的倒数第二段是 models
        registry = getattr(folder_paths, "folder_names_and_paths", {}) or {}
        for paths, _exts in registry.values():
            for p in paths:
                parts = Path(p).parts
                if len(parts) >= 2 and parts[-2].lower() == "models":
                    roots.append(Path(*parts[:-1]) / "marriage_cloth")
    except Exception:
        pass
    # 插件内置素材（测试环境没有 folder_paths 时也走这里）
    roots.append(Path(__file__).resolve().parent / "models" / "marriage_cloth")

    seen, uniq = set(), []
    for r in roots:
        key = str(r).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq


def _active_roots():
    """实际存在的素材根，按候选顺序（用户 models 目录优先，内置兜底）。"""
    roots = [r for r in _candidate_roots() if r.is_dir()]
    return roots or [_candidate_roots()[0]]


def _natural_key(name):
    """自然排序键：数字段按数值比，其余按小写字符串比。

    ``01.jpg / 02.jpg / 10.jpg`` 得到 1、2、10 的顺序；纯数字命名与带前缀
    命名都能排对。
    """
    parts = re.split(r"(\d+)", name.lower())
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts)


def _dir_signature(root):
    """目录签名：文件名 + mtime + 体积，用于缓存失效。"""
    try:
        entries = []
        for f in sorted(root.iterdir(), key=lambda p: _natural_key(p.name)):
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                try:
                    st = f.stat()
                    entries.append((f.name, round(st.st_mtime, 3), st.st_size))
                except OSError:
                    continue
        return tuple(entries)
    except OSError:
        return ()


def scan_clothes(force=False, roots=None):
    """扫描素材（多根合并），返回 ``[{"index", "name", "title"}, ...]``。

    index 从 1 开始（0 被"纯色底"占用，与上游一致）；同名文件以先出现的根为准。
    roots 显式传入时只扫这些目录（测试 / 单目录场景），否则走 _active_roots()。
    """
    if roots is not None:
        roots = [Path(r) for r in roots]
    else:
        roots = _active_roots()
    sig = tuple((str(r), _dir_signature(r)) for r in roots)
    if not force and _SCAN_CACHE["key"] == sig:
        return _SCAN_CACHE["items"]

    seen, items = set(), []
    for root in roots:
        if not root.is_dir():
            continue
        files = [f for f in root.iterdir()
                 if f.is_file() and f.suffix.lower() in IMAGE_EXTS]
        for f in sorted(files, key=lambda p: _natural_key(p.name)):
            lower = f.name.lower()
            if lower in seen:
                continue
            seen.add(lower)
            items.append({
                "index": len(items) + 1,
                "name": f.name,
                "title": f.stem,
            })

    _SCAN_CACHE.update({"key": sig, "items": items})
    return items


def safe_name(value):
    """清洗文件名：只允许单层图片文件名，拒绝穿越 / 分隔符 / 非法字符。

    白名单含中文与全角标点（``，。、（）`` 这类在素材命名里很常见，之前
    QG_IDPhotoOutfit 就因为漏掉全角标点让图片整个 404）。
    """
    if not value or "\\" in value or "/" in value or ".." in value:
        return None
    if value.strip() != value or value.startswith("."):
        return None
    if not re.fullmatch(r"[\w\u4e00-\u9fff .,()\[\]（）【】、，。：·-]+", value):
        return None
    if not value.lower().endswith(IMAGE_EXTS):
        return None
    return value


def resolve_image(name, roots=None):
    """按文件名在各素材根里定位图片，返回 Path 或 None。"""
    name = safe_name(name or "")
    if name is None:
        return None
    target = name.lower()
    for root in (roots if roots is not None else _active_roots()):
        root = Path(root)
        candidate = root / name
        if candidate.is_file():
            return candidate
        # 大小写 / Unicode 归一不一致时按小写名回退匹配一次
        try:
            for f in root.iterdir():
                if f.is_file() and f.name.lower() == target:
                    return f
        except OSError:
            continue
    return None


def flat_image(color=FLAT_COLOR_DEFAULT, width=TARGET_W_DEFAULT,
               height=TARGET_H_DEFAULT):
    """纯色底图（序号 0 用）：颜色非法时退回默认色。"""
    try:
        rgb = ImageColor.getrgb(str(color).strip())
        if len(rgb) == 4:
            rgb = rgb[:3]
    except (ValueError, AttributeError):
        rgb = ImageColor.getrgb(FLAT_COLOR_DEFAULT)
    canvas = Image.new("RGB", (max(1, int(width)), max(1, int(height))), rgb)
    return torch.from_numpy(np.asarray(canvas, dtype=np.float32) / 255.0)[None]


def load_image(path, mode="fit_pad", width=TARGET_W_DEFAULT,
               height=TARGET_H_DEFAULT, pad_color=FLAT_COLOR_DEFAULT):
    """把素材读成 0-1 浮点 RGB 帧，按 mode 处理尺寸后返回 ``[1, H, W, 3]``。

    ``fit_pad``  按比例缩进目标框，空白处补 pad_color（默认，不变形）
    ``stretch``  直接拉伸到目标尺寸（上游行为，可能变形）
    ``original`` 原尺寸输出，目标尺寸被忽略
    """
    img = Image.open(path).convert("RGB")
    if mode == "original":
        pass
    elif mode == "stretch":
        size = (max(1, int(width)), max(1, int(height)))
        if img.size != size:
            img = img.resize(size, Image.LANCZOS)
    else:  # fit_pad（未知值也走这里，宁可留边也不变形）
        try:
            rgb = ImageColor.getrgb(str(pad_color).strip())
            if len(rgb) == 4:
                rgb = rgb[:3]
        except (ValueError, AttributeError):
            rgb = ImageColor.getrgb(FLAT_COLOR_DEFAULT)
        img = ImageOps.pad(img, (max(1, int(width)), max(1, int(height))),
                           method=Image.LANCZOS, color=rgb, centering=(0.5, 0.5))
    array = np.asarray(img, dtype=np.float32) / 255.0
    return torch.from_numpy(np.ascontiguousarray(array))[None]


def pick_by_name(name, items):
    """文件名 → 素材条目；未命中返回 None。"""
    if not name:
        return None
    lower = name.lower()
    for item in items:
        if item["name"].lower() == lower:
            return item
    return None


class QGMarriageCloth:
    """结婚登记照服装：序号或文件名指定一张参考图，输出 IMAGE。"""

    CATEGORY = "QG 工具"
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "execute"
    DESCRIPTION = (
        "Wedding registration outfit reference: pick one garment photo (index 1..N, "
        "0 = plain colour) and output it as an IMAGE for image-to-image. "
        "Built-in library ships with the pack; extra photos go in "
        "ComfyUI/models/marriage_cloth/. Non-square sources are letterboxed "
        "instead of being squashed."
    )
    SEARCH_ALIASES = ["marriage", "结婚登记照", "服装", "wedding", "cloth"]

    @classmethod
    def INPUT_TYPES(cls):
        count = len(scan_clothes())
        return {
            "required": {
                "image_index": ("INT", {
                    "default": 1, "min": 0, "max": 999, "step": 1,
                    "display": "number",
                    "tooltip": "1..N picks a photo in scan order, 0 outputs a "
                               "plain colour plate. N is shown in the node panel.",
                }),
                "resize_mode": (list(RESIZE_MODES), {
                    "default": "fit_pad",
                    "tooltip": "fit_pad: keep aspect ratio, pad the rest. "
                               "stretch: fill the frame (may distort). "
                               "original: no resize at all.",
                }),
                "target_width": ("INT", {
                    "default": TARGET_W_DEFAULT, "min": 64, "max": 8192, "step": 8,
                    "tooltip": "Output width in pixels (ignored by 'original').",
                }),
                "target_height": ("INT", {
                    "default": TARGET_H_DEFAULT, "min": 64, "max": 8192, "step": 8,
                    "tooltip": "Output height in pixels (ignored by 'original').",
                }),
                "pad_color": ("STRING", {
                    "default": FLAT_COLOR_DEFAULT,
                    "tooltip": "Colour for the plain plate and for fit_pad "
                               "borders. Takes #RRGGBB, #ABC or a colour name.",
                }),
            },
            "hidden": {
                "cloth_name": "STRING",
                "unique_id": "UNIQUE_ID",
            },
        }

    def execute(self, image_index=1, resize_mode="fit_pad",
                target_width=TARGET_W_DEFAULT, target_height=TARGET_H_DEFAULT,
                pad_color=FLAT_COLOR_DEFAULT, cloth_name="", unique_id=None):
        items = scan_clothes()

        # 文件名比序号更可靠（素材顺序变了也还能命中），优先用它
        chosen = pick_by_name(cloth_name, items)
        if chosen is None and items and image_index > 0:
            idx = max(0, min(int(image_index) - 1, len(items) - 1))
            chosen = items[idx]

        if chosen is None:
            # 序号 0、无素材、或文件名失效：都退回纯色底图，不中断工作流
            return (flat_image(pad_color, target_width, target_height),)

        path = resolve_image(chosen["name"])
        if path is None:
            return (flat_image(pad_color, target_width, target_height),)
        return (load_image(path, resize_mode, target_width, target_height,
                           pad_color),)


# ============ API 路由（前端画廊的数据与图片来源） ============

if _HAS_SERVER:
    @PromptServer.instance.routes.get("/qg-multipack/marriage_cloth/list")
    async def qg_marriage_cloth_list(request):
        """返回素材清单（带序号），前端据此建画廊。"""
        items = scan_clothes(force=True)
        return web.json_response({"count": len(items), "images": items})

    @PromptServer.instance.routes.get("/qg-multipack/marriage_cloth/image/{filename}")
    async def qg_marriage_cloth_image(request):
        """按文件名返回素材原图。"""
        from urllib.parse import unquote
        path = resolve_image(unquote(request.match_info["filename"]))
        if path and path.is_file():
            return web.FileResponse(path)
        return web.Response(status=404, text="Not found")


NODE_CLASS_MAPPINGS = {"QG_MarriageCloth": QGMarriageCloth}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_MarriageCloth": "QG 结婚登记照服装"}
