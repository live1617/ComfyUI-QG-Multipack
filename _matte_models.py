"""人像抠图的模型发现与推理。

三套 onnx 模型，预处理各不相同，这里按文件名分红：

| 模型 | 输入 | 归一化 | 输出 |
|---|---|---|---|
| ``*modnet*`` | 512x512 | /255 再 (x-0.5)/0.5 | 直接就是 alpha 0..1 |
| ``rmbg-*`` | 1024x1024 | /255 再 (x-0.5)/0.5 | logits，要按本图 min-max 拉伸 |
| ``birefnet*`` | 1024x1024 | ImageNet 均值方差 | logits，要 sigmoid |

两个 modnet 权重随包放在插件 ``models/background_removal``（Apache-2.0，
来源与校验见该目录 NOTICE.md），让节点离线也能开箱即用。发现顺序：
ComfyUI 的 ``models/background_removal``（含 extra_model_paths 挂载）→
``models/matting`` → 插件内置兜底 → 兼容 HivisionIDPhotos 插件自带 weights。
用户自己放的同名权重优先，内置副本命中后不会再触发下载。
其余两个大模型仍首次使用时按需下载；一个可选依赖不该让整个包加载失败。

``rmbg-1.4`` 是例外：官方完整权重（model.pth + onnx）通常按仓库结构放在
``models/background_removal/RMBG-1.4/`` 子目录，``discover()`` 只扫根目录
读不到它，故 :func:`resolve` 对该模型优先查这个子目录，下载落点也一致。
根目录散落的 rmbg-1.4.onnx 仍作兼容读取，不删不搬。
"""

from __future__ import annotations

import os
import re

import numpy as np
from PIL import Image

# 根目录解析统一走 qg_model_paths；两种加载场景都要能拿到：
# ① 包上下文（ComfyUI 里 `from . import`）；② 顶层 import（测试把包根插进 sys.path）。
try:  # pragma: no cover - 取决于加载方式
    from . import qg_model_paths as _QP
except ImportError:  # pragma: no cover
    import qg_model_paths as _QP

try:
    import onnxruntime as ort
except Exception:  # pragma: no cover - 只在没装时报
    ort = None

# 目录按优先级排。第一个出现的同名文件胜出。
_FOLDERS = (
    ("background_removal", "ComfyUI/models/background_removal"),
    ("matting", "ComfyUI/models/matting"),
)

# rmbg-1.4 官方完整权重（model.pth + onnx）按仓库结构放在这个子目录里；
# discover() 只扫根目录读不到，故 resolve() 对它单独走前置分支。
RMBG14_SUBDIR = "RMBG-1.4"
_RMBG14_FILE = "rmbg-1.4.onnx"

# 会话是懒加载的，加载一次 birefnet 要 8.7 秒，不能每帧重建。
_SESSIONS = {}


def _models_root():
    """ComfyUI/models 的绝对路径，拿不到就退回相对路径。

    实现委托给统一解析层 ``qg_model_paths``；返回语义与旧版一致，测试与
    其它模块可直接替换此函数。
    """
    return _QP.models_root()


def _bundled_dir():
    """随包分发的离线兜底权重目录。

    不依赖 ComfyUI 的 folder_paths：插件目录本身就知道自己在哪里，
    纯离线环境（没有 models 目录、没有网络）也能找到这两个 modnet。
    """
    return _QP.bundled_dir("background_removal")


def _source_folders():
    """要扫的目录，按优先级。

    先问 ``folder_paths.get_folder_paths``：它会把 ``extra_model_paths.yaml``
    里配的额外路径一并带出来，所以模型放 ``D:/comfyui/models/background_removal``
    和放 ``ComfyUI/models/background_removal`` 是一样的待遇。只拼 ``models_dir``
    的直子目录是不够的 —— 那样额外路径里的模型明明在，节点却说"没找到"。
    """
    # 挂载路径 + models_dir 兜底统一由 qg_model_paths 解析；两个类别分别
    # 取，保持旧版「先所有 background_removal、再所有 matting」的相对顺序。
    folders = []
    for name, _ in _FOLDERS:
        # 注入 _models_root() 而非让统一层自己取：保留本模块的可 mock 点，
        # 根目录解析（挂载 + 去重）仍集中在 qg_model_paths。
        for path in _QP.category_roots(name, root=_models_root()):
            if path not in folders:
                folders.append(path)

    # 随包的离线兜底放在用户目录之后：用户自己更新过的同名权重优先，
    # 内置副本只在用户目录没有时补上，命中后 resolve() 不会再去联网。
    bundled = _bundled_dir()
    if bundled not in folders:
        folders.append(bundled)

    # 兼容：HivisionIDPhotos 插件自带的 weights 已经有现成模型，
    # 不去复制一份，能读到就用。
    comfy_root = os.path.dirname(_models_root())
    folders.append(os.path.join(comfy_root, "custom_nodes",
                                "HivisionIDPhotos-ComfyUI", "hivision",
                                "creator", "weights"))
    return folders


def discover():
    """返回 ``{文件名去后缀: 绝对路径}``，按搜索顺序去重。"""
    found = {}
    for folder in _source_folders():
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith(".onnx"):
                continue
            key = os.path.splitext(name)[0]
            if key not in found:
                found[key] = os.path.join(folder, name)
    return found


def _rmbg14_dirs():
    """rmbg-1.4 专用子目录候选（挂载优先、本机主库兜底，去重保序）。

    官方完整权重按仓库结构放在 ``background_removal/RMBG-1.4/`` 下，
    ``discover()`` 只扫根目录读不到这里，单独列出来供 :func:`resolve` 前置查找。
    """
    dirs = []
    for root in _QP.category_roots("background_removal", root=_models_root()):
        d = os.path.join(str(root), RMBG14_SUBDIR)
        if d not in dirs:
            dirs.append(d)
    return dirs


def _rmbg14_local():
    """在 ``RMBG-1.4/`` 子目录里找 onnx，命中返回绝对路径，否则 None。"""
    for d in _rmbg14_dirs():
        cand = os.path.join(d, _RMBG14_FILE)
        if os.path.isfile(cand):
            return cand
    return None


def family_of(path):
    """按文件名判断预处理，返回 ``modnet`` / ``rmbg`` / ``birefnet``。"""
    name = os.path.basename(path).lower()
    if "rmbg" in name:
        return "rmbg"
    if "birefnet" in name:
        return "birefnet"
    return "modnet"


def _session(path):
    if ort is None:
        raise RuntimeError(
            "没装 onnxruntime，抠图节点用不了。装法：在 ComfyUI 的 python 里 "
            "pip install onnxruntime（GPU 版是 onnxruntime-gpu）")
    key = (path, os.path.getmtime(path))
    sess = _SESSIONS.get(key)
    if sess is None:
        providers = (["CUDAExecutionProvider", "CPUExecutionProvider"]
                     if "CUDAExecutionProvider" in ort.get_available_providers()
                     else ["CPUExecutionProvider"])
        try:
            sess = ort.InferenceSession(path, providers=providers)
        except Exception:
            sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        _SESSIONS[key] = sess
    return sess


def _prepare(rgb, size, family):
    """HWC uint8 -> NCHW float32，按模型家族的规矩归一化。"""
    small = np.asarray(Image.fromarray(rgb).resize((size, size), Image.BILINEAR),
                       dtype=np.float32)
    if family == "birefnet":
        small = small / 255.0
        small = (small - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / \
            np.array([0.229, 0.224, 0.225], dtype=np.float32)
    else:
        small = small / 255.0
        small = (small - 0.5) / 0.5
    return np.ascontiguousarray(small.transpose(2, 0, 1)[None], dtype=np.float32)


def matte_alpha(rgb, model_path):
    """跑一次抠图，返回与原图同尺寸的 alpha（uint8，0..255）。

    模型用的是固定输入尺寸（512 或 1024），所以结果一定是放大回来的 ——
    头发边缘那种半透明过渡会被拉伸得偏软，这是模型本身的限制，不是这里
    的毛病。要做锐利的发丝边缘得用原分辨率推理的模型。
    """
    if rgb.ndim == 2:
        rgb = np.stack([rgb] * 3, axis=-1)
    elif rgb.shape[2] == 4:
        rgb = rgb[:, :, :3]

    fam = family_of(model_path)
    size = 1024 if fam in ("rmbg", "birefnet") else 512
    sess = _session(model_path)
    feed = _prepare(rgb, size, fam)

    out = sess.run(None, {sess.get_inputs()[0].name: feed})[0]
    pred = np.squeeze(out).astype(np.float32)
    if pred.ndim == 3:
        pred = pred[0]

    if fam == "birefnet":
        pred = 1.0 / (1.0 + np.exp(-pred))
    elif fam == "rmbg":
        lo, hi = float(pred.min()), float(pred.max())
        pred = (pred - lo) / (hi - lo) if hi - lo > 1e-6 else np.zeros_like(pred)
    # modnet 直接输出 alpha，不做后处理

    # NaN 必须先清掉再 cast：np.clip 不拦 NaN，astype(uint8) 会把它变成 0，
    # 结果就是「遮罩静默全空 → 只剩纯色背景」（BiRefNet 那个 fp16 NaN 事故同源）。
    pred = np.nan_to_num(pred, nan=0.0, posinf=1.0, neginf=0.0)
    pred = np.clip(pred, 0.0, 1.0)
    mask = Image.fromarray((pred * 255.0 + 0.5).astype(np.uint8), mode="L")
    mask = mask.resize((rgb.shape[1], rgb.shape[0]), Image.BILINEAR)
    return np.asarray(mask)


def backend_note():
    if ort is None:
        return "onnxruntime 未安装"
    return "onnxruntime %s / %s" % (ort.__version__, ", ".join(ort.get_available_providers()))


# ---------------------------------------------------------------------------
# 自动下载（用到节点时按需拉取）
#
# 下拉菜单现在常驻显示下面这套预置模型名；用户选中、且本地没有时，节点在
# execute 阶段按需把它们下载到 models/background_removal/。文件名刻意按本包
# family_of 的三族关键词命名（modnet / rmbg / birefnet），这样 discover() 也能
# 识别，且预处理分支（512 vs 1024、归一化、alpha 直出 vs logits）与文件头注释
# 的表格完全对得上 —— 下错名字会出烂图且不报错，这里把名字卡死。
#
# 源均来自 HivisionIDPhotos 官方权重（birefnet-v1-lite 取自 ZhengPeng7 官方
# release）。HF 那一份下载下来叫 model.onnx，必须按 save_as 重命名。
# ---------------------------------------------------------------------------

PRESET_MODELS = {
    "modnet_photographic_portrait_matting": {
        "url": "https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/pretrained-model/modnet_photographic_portrait_matting.onnx",
        "save_as": "modnet_photographic_portrait_matting.onnx",
        "size_hint": "24.7MB",
    },
    "hivision_modnet": {
        "url": "https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/pretrained-model/hivision_modnet.onnx",
        "save_as": "hivision_modnet.onnx",
        "size_hint": "24.7MB",
    },
    "rmbg-1.4": {
        "url": "https://huggingface.co/briaai/RMBG-1.4/resolve/main/onnx/model.onnx?download=true",
        "save_as": "rmbg-1.4.onnx",
        "size_hint": "176.2MB",
    },
    "birefnet-v1-lite": {
        "url": "https://github.com/ZhengPeng7/BiRefNet/releases/download/v1/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx",
        "save_as": "birefnet-v1-lite.onnx",
        "size_hint": "224MB",
    },
}


def preset_names():
    """下拉里始终出现的模型名（即使本地还没下载）。"""
    return sorted(PRESET_MODELS)


def available_choices():
    """预置名 ∪ 本地 discover 名，去重排序。"""
    return sorted(set(preset_names()) | set(discover()))


def _parse_size_hint(text):
    """把 ``'24.7MB'`` 这种注解放成字节下界（取标注值的 50%，容忍四舍五入/压缩）。

    解析不出来返回 ``None``（不强制校验）。
    """
    if not text:
        return None
    m = re.match(r"\s*([\d.]+)\s*([KMG])B\s*$", text, re.IGNORECASE)
    if not m:
        return None
    val = float(m.group(1))
    mult = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}[m.group(2).upper()]
    return int(val * mult * 0.5)


def _resolve_preset(name):
    """预置模型：本地已有且体积达标就返回，否则下载后返回。

    rmbg-1.4 按官方仓库结构落到 ``background_removal/RMBG-1.4/`` 子目录，
    与 :func:`resolve` 的读取口径一致；其余模型仍落 ``background_removal/`` 根。
    """
    info = PRESET_MODELS.get(name)
    if info is None:
        return None
    root = _QP.primary_root("background_removal", root=_models_root())
    if name == "rmbg-1.4":
        root = os.path.join(root, RMBG14_SUBDIR)
    dest = os.path.join(root, info["save_as"])
    min_bytes = _parse_size_hint(info.get("size_hint"))
    if os.path.exists(dest) and (min_bytes is None or os.path.getsize(dest) >= min_bytes):
        return dest
    print("[QG-Matte] 未找到 %s，按需下载（约 %s）：%s"
          % (name, info["size_hint"], info["url"]))
    from ._model_download import http_download
    try:
        http_download(info["url"], dest, stall_seconds=300, min_bytes=min_bytes)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "抠图模型 %s 自动下载失败：%s\n"
            "可手动下载后放到：%s" % (name, exc, os.path.dirname(dest))) from exc
    return dest


def resolve(name):
    """本地命中就用本地；否则若是预置模型就按需下载。

    rmbg-1.4 的官方完整权重在 ``RMBG-1.4/`` 子目录，优先查那里；根目录
    散落的旧 onnx 由 ``discover()`` 兜底兼容，不删不搬。
    """
    if name == "rmbg-1.4":
        sub = _rmbg14_local()
        if sub:
            return sub
    local = discover().get(name)
    if local:
        return local
    return _resolve_preset(name)
