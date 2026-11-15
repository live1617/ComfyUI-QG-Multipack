# -*- coding: utf-8 -*-
"""QG 证件照服装发型选择节点（qg_id_photo_outfit.py）

功能：按分类扫描服装/发型模板素材，前端提供内嵌面板（预览 / 搜索 / 点选），
把选中模板的提示词写回 STRING 控件，后端原样透传给下游。

素材来源**多根合并**（都可见，同名文件先命中者优先）：

1. 插件目录自带内置素材 ``<插件目录>/models/id_photo/``（随包分发，
   当前内置 7 个分类 200 张：女士/男士/女童/男童/老年服装 + 女士/男士发型，
   全部配好提示词）
2. 用户自备 ``ComfyUI/models/id_photo/``（extra_model_paths 挂载的其它
   models 根也认）——放自己的分类或同名分类补充图片即可

素材目录格式（id_photo_data.json 与分类目录同级）::

    models/id_photo/
    ├── 1. 服装_女士/          ← 分类目录，名字任意
    │   ├── 01.西装.jpg        ← 模板图（jpg/jpeg/png/webp）
    │   ├── 02.衬衫.png
    │   └── ...
    ├── 2. 服装_男士/
    ├── id_photo_data.json     ← 提示词映射
    │   {"prompts": {"1. 服装_女士": {"01.西装": "深灰色……"}}}
    └── ...

提示词解析优先级：id_photo_data.json 的 prompts 映射 →
文件名内嵌（「标题-提示词.扩展名」）→ 空字符串。
目录格式与 Goohaitools「孤海-证件照服装发型」素材兼容（内置素材即取自
其公开素材库的精选子集，来源与许可见 THIRD-PARTY-NOTICES.md）。

注册 key：QG_IDPhotoOutfit；输出 STRING 提示词。
"""

import json
import re
from pathlib import Path

try:
    from server import PromptServer
    from aiohttp import web
    # 路由注册要求 instance 已建好（ComfyUI 运行时满足）；纯导入/测试环境 instance
    # 未创建，此时不做路由注册，节点与扫描逻辑不受影响。
    _HAS_SERVER = getattr(PromptServer, "instance", None) is not None
except Exception:  # ImportError 等：无 ComfyUI 环境
    PromptServer = None
    web = None
    _HAS_SERVER = False

# 素材根目录候选：ComfyUI 主 models 根 + extra_model_paths 挂载的其它根
# （从 folder_names_and_paths 已注册目录反推）各拼一个 id_photo 子目录；
# 都不存在时退回插件目录 models/id_photo。
def _candidate_roots():
    roots = []
    try:
        import folder_paths
        models_dir = getattr(folder_paths, "models_dir", None)
        if models_dir:
            roots.append(Path(models_dir) / "id_photo")
        # 反推挂载根：<models根>/<子目录名>/... 的倒数第二段是 "models"
        registry = getattr(folder_paths, "folder_names_and_paths", {}) or {}
        for paths, _exts in registry.values():
            for p in paths:
                parts = Path(p).parts
                if len(parts) >= 2 and parts[-2].lower() == "models":
                    roots.append(Path(*parts[:-1]) / "id_photo")
    except Exception:
        pass
    # 兜底：插件目录下 models/id_photo（无 ComfyUI 环境的测试场景用）
    roots.append(Path(__file__).resolve().parent / "models" / "id_photo")
    # 去重保序
    seen, uniq = set(), []
    for r in roots:
        key = str(r).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq


def _template_root():
    # 兼容旧接口：取第一个真正放了 id_photo 目录的根；一个都没有则用第一个候选
    for root in _candidate_roots():
        if root.is_dir():
            return root
    return _candidate_roots()[0]


def _active_roots():
    """所有实际存在的素材根，按候选顺序（用户 models 目录优先，插件内置兜底）。

    多根会**合并扫描**：插件目录自带一批内置模板（随包分发），用户还可以往
    ComfyUI/models/id_photo/ 加自己的分类，两边同时可见；同名分类合并、
    同名文件以先出现的根为准。
    """
    roots = [r for r in _candidate_roots() if r.is_dir()]
    return roots or [_candidate_roots()[0]]


_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
# 提示词映射文件名（放在 id_photo 根目录下）
_DATA_JSON = "id_photo_data.json"
# 分类兜底名：素材目录为空时下拉仍有项，前端据此提示自备素材
_EMPTY_CATEGORY = "无数据"

# 扫描缓存（带目录 mtime 的失效机制，新增素材不用重启）
_SCAN_CACHE = {"key": None, "categories": [], "templates": {}, "files": {}}


def _dir_signature(root):
    """目录签名：各分类子目录的 (名字, 文件数, 最新 mtime) 汇总，用于缓存失效。"""
    parts = []
    try:
        for d in sorted(root.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                try:
                    files = [f for f in d.iterdir()
                             if f.is_file()
                             and f.suffix.lower() in _IMAGE_EXTS]
                    newest = max((f.stat().st_mtime for f in files), default=0.0)
                    parts.append((d.name, len(files), newest))
                except OSError:
                    continue
    except OSError:
        pass
    return tuple(parts)


def scan_templates(root=None, force=False):
    """扫描素材目录（多根合并），返回 (categories, templates, files)。

    templates: {分类: [{"title","prompt","filename","category"}, ...]}
    files:     {分类: {stem_lower: 实际文件名}}  供图片路由解析
    扫描结果按各根目录签名缓存，素材增删改无需重启后端。
    root 显式指定时只扫该目录（测试/单目录场景）。
    """
    roots = [Path(root)] if root else _active_roots()
    sig = tuple((str(r), _dir_signature(r), r.exists()) for r in roots)
    if not force and _SCAN_CACHE["key"] == sig:
        return _SCAN_CACHE["categories"], _SCAN_CACHE["templates"], _SCAN_CACHE["files"]

    categories, templates, files = [], {}, {}
    seen_cat = set()
    for r in roots:
        # 每根各自的提示词映射（JSON 放各自根目录下）
        prompt_map = {}
        data_json = r / _DATA_JSON
        if data_json.is_file():
            try:
                loaded = json.loads(data_json.read_text(encoding="utf-8"))
                prompt_map = loaded.get("prompts", {}) or {}
                if not isinstance(prompt_map, dict):
                    prompt_map = {}
            except (ValueError, OSError):
                prompt_map = {}

        if not r.is_dir():
            continue
        for d in sorted(r.iterdir()):
            if not (d.is_dir() and not d.name.startswith(".")):
                continue
            category = d.name
            cat_prompts = prompt_map.get(category, {})
            if not isinstance(cat_prompts, dict):
                cat_prompts = {}
            # 同名分类跨根合并：先出现的根的条目在前，同名文件不重复
            entries = templates.get(category)
            if entries is None:
                entries = []
            index = files.setdefault(category, {})
            existing = {e["filename"] for e in entries}
            for img in sorted(d.iterdir()):
                if not (img.is_file() and img.suffix.lower() in _IMAGE_EXTS):
                    continue
                stem, filename = img.stem, img.name
                if filename in existing:
                    continue
                existing.add(filename)
                index.setdefault(stem.lower(), filename)
                if stem in cat_prompts:
                    title, prompt = stem, str(cat_prompts[stem])
                elif "-" in stem:
                    head, tail = stem.split("-", 1)
                    title, prompt = head.strip(), tail.strip()
                else:
                    title, prompt = stem, ""
                entries.append({
                    "title": title,
                    "prompt": prompt,
                    "filename": filename,
                    "category": category,
                })
            if entries:
                if category not in seen_cat:
                    seen_cat.add(category)
                    categories.append(category)
                templates[category] = entries

    if not categories:
        categories = [_EMPTY_CATEGORY]
        templates[_EMPTY_CATEGORY] = []

    _SCAN_CACHE.update({"key": sig, "categories": categories,
                        "templates": templates, "files": files})
    return categories, templates, files


def _safe_part(value):
    """清洗路径片段：拒绝穿越/反斜杠/绝对路径，只放行常见字符。

    白名单含：中文与全角标点（，。、：；！？「」等，文件名里常见）、
    字母数字下划线、空格、点、括号、连字符；半角斜杠/反斜杠/.. 一律拒绝。
    """
    if not value or "\\" in value or "/" in value or ".." in value:
        return None
    if value.startswith(".") or value.strip() != value:
        return None
    if not re.fullmatch(r"[\w\u4e00-\u9fff\u3000-\u303f\uFF00-\uFFEF\u00B7 .()\[\]-]+", value):
        return None
    return value


def _resolve_in(img_dir, category, filename):
    """在单个分类目录内定位图片（含旧长文件名的短标题回退）。"""
    if not img_dir.is_dir():
        return None
    candidate = img_dir / filename
    if candidate.is_file():
        return candidate
    # 旧格式回退：请求文件名带「标题-提示词」时，按短标题在分类目录里
    # 找现文件（磁盘上是短名或长名都能命中；精确 stem 优先于前缀匹配）
    stem = Path(filename).stem
    if "-" in stem:
        short = stem.split("-", 1)[0].strip().lower()
        matches = []
        try:
            for cand in img_dir.iterdir():
                if not (cand.is_file() and cand.suffix.lower() in _IMAGE_EXTS):
                    continue
                cand_stem = cand.stem.lower()
                if cand_stem == short:
                    matches.insert(0, cand)   # 精确命中排最前
                elif cand_stem.split("-", 1)[0].strip().lower() == short:
                    matches.append(cand)      # 长名同短标题，排后面
        except OSError:
            return None
        return matches[0] if matches else None
    return None


def resolve_image(category, filename, root=None):
    """按分类与文件名定位模板图；返回 Path 或 None（找不到/非法都返回 None）。

    多根场景按候选顺序（用户 models 目录 → 插件内置）查找，先命中者优先。
    """
    category = _safe_part(category or "")
    filename = _safe_part(filename or "")
    if category is None or filename is None:
        return None
    if not filename.lower().endswith(_IMAGE_EXTS):
        return None
    roots = [Path(root)] if root else _active_roots()
    for r in roots:
        found = _resolve_in(r / category, category, filename)
        if found is not None:
            return found
    return None


class QGIDPhotoOutfit:
    """证件照服装发型选择：前端面板选模板，后端透传提示词。"""

    @classmethod
    def _refresh(cls):
        cls._categories, cls._templates, cls._files = scan_templates()
        return cls._categories

    @classmethod
    def INPUT_TYPES(cls):
        cats = list(scan_templates()[0])
        return {
            "required": {
                "style": (cats,),
                "prompt_output": ("STRING", {"default": "", "multiline": True}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("提示词",)
    FUNCTION = "execute"
    CATEGORY = "QG 工具"
    DESCRIPTION = ("证件照服装/发型模板选择：节点面板里浏览缩略图、搜索、点选模板，"
                   "选中模板的服装/发型提示词写进提示词控件输出给下游（可直接接 "
                   "QG_IDPhotoParams 之类）。插件自带 7 个分类 200 张内置模板（女士/男士/"
                   "女童/男童/老年服装 + 女士/男士发型，均配提示词），开箱即用；还可往 "
                   "ComfyUI/models/id_photo/ 放自己的分类或补图，两边合并显示。")

    def execute(self, style, prompt_output="", unique_id=None):
        return (prompt_output or "",)


# ============ API 路由（前端面板的数据与图片来源） ============

if _HAS_SERVER:
    @PromptServer.instance.routes.get("/qg-multipack/id_photo/templates")
    async def qg_id_photo_templates(request):
        """返回全部分类与模板元数据。"""
        categories, templates, _files = scan_templates()
        return web.json_response({"categories": categories,
                                  "templates": templates})

    @PromptServer.instance.routes.get("/qg-multipack/id_photo/image/{category}/{filename}")
    async def qg_id_photo_image(request):
        """按分类与文件名返回模板缩略图（带路径清洗与旧名回退）。"""
        from urllib.parse import unquote
        path = resolve_image(unquote(request.match_info["category"]),
                             unquote(request.match_info["filename"]))
        if path and path.is_file():
            return web.FileResponse(path)
        return web.Response(status=404, text="Not found")


NODE_CLASS_MAPPINGS = {"QG_IDPhotoOutfit": QGIDPhotoOutfit}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_IDPhotoOutfit": "QG 证件照服装发型"}
