"""QG BiRefNet 去除背景 —— 高精度二分图像分割（DIS）抠图节点。

行为对齐 1038lab/ComfyUI-RMBG 的 BiRefNet 节点（先读懂其 AILab_BiRefNet.py
后自行实现，代码结构全部重写）。模型权重与该插件共享同一缓存目录
（models/RMBG/BiRefNet），任一节点先下载过，另一边直接复用。

模型定义文件（birefnet.py / birefnet_lite.py）来自 HuggingFace
1038lab/BiRefNet 仓库，运行时动态加载；BiRefNet 模型与权重遵循
Apache-2.0（ZhengPeng7），本集成代码不复制其文件、仅在运行时加载。

权重来源共 3 个 HF 仓库（逐个模型的地址与放置位置见 README「QG_BiRefNet
支持的模型」一节）：
  1038lab/BiRefNet           BiRefNet 12 个变体 + 3 个模型定义文件
  ZhengPeng7/BiRefNet-*      DIS / DIS-TR_TEs / COD / HRSOD / legacy 五个
  1038lab/RMBG-2.0           RMBG-2.0（官方 briaai 仓库 gated，走公开镜像）
落盘位置统一在 models/RMBG/ 下按模型分子目录，与 ComfyUI-RMBG 共用缓存。

流水线：
  1. 预处理：整图缩放到方形 process_res（32 对齐；512 档强制 512），
     BICUBIC + ImageNet 均值方差归一化
  2. 推理：BiRefNet 多尺度输出取最后一层，sigmoid 得 0..1 前景概率
  3. 后处理链：灵敏度增益 → 高斯模糊 → Min/MaxFilter 腐蚀膨胀（遮罩偏移）
     → 可选反转 → 可选前景精修（过渡区 alpha 混合）→ 背景合成
  4. 输出：(IMAGE, MASK, MASK_IMAGE)——RGBA 前景或纯色底合成图、
     单通道遮罩、遮罩的三通道可视化图
"""

import gc
import hashlib
import importlib.util
import os
import sys
import tempfile

import folder_paths
import numpy as np
import torch
from PIL import Image, ImageFilter

import comfy.model_management as mm

try:  # scipy 是可选的：没装时遮罩偏移退回逐次 3×3 滤波，结果一样只是慢
    from scipy import ndimage as _ndimage
except ImportError:  # pragma: no cover - 取决于运行环境
    _ndimage = None

_REPO_ID = "1038lab/BiRefNet"

# 每个变体：模型定义脚本、权重文件、推理分辨率档位。
# default_res 是推理输入的方形边长（模型按固定分辨率训练）。
# 可选字段：
#   subdir  —— 权重放到 models/RMBG/<subdir>/（默认落在 models/RMBG/BiRefNet/）
#   repo    —— 权重下载源（默认 1038lab/BiRefNet）
#   dl_name —— 仓库里的文件名（默认与 weights 同名）。ZhengPeng7 各数据集仓库
#              统一叫 model.safetensors，下载后另存为 weights 指定的本地名。
MODEL_CONFIG = {
    # BRIA RMBG-2.0：结构就是 BiRefNet，实测权重 754 个张量的 key/shape/dtype 与
    # BiRefNet-general 逐项一致，因此复用同一份 birefnet.py，不需要第二套模型定义。
    # 权重只认 1038lab 的镜像仓库：官方 briaai/RMBG-2.0 是 gated，不带 token 会 401。
    "RMBG-2.0":            {"script": "birefnet.py",      "weights": "model.safetensors",
                            "res": 1024, "repo": "1038lab/RMBG-2.0", "subdir": "RMBG-2.0"},
    "BiRefNet-general":    {"script": "birefnet.py",      "weights": "BiRefNet-general.safetensors",    "res": 1024},
    "BiRefNet-HR":         {"script": "birefnet.py",      "weights": "BiRefNet-HR.safetensors",         "res": 2048},
    "BiRefNet-portrait":   {"script": "birefnet.py",      "weights": "BiRefNet-portrait.safetensors",   "res": 1024},
    "BiRefNet-matting":    {"script": "birefnet.py",      "weights": "BiRefNet-matting.safetensors",    "res": 1024},
    "BiRefNet-HR-matting": {"script": "birefnet.py",      "weights": "BiRefNet-HR-matting.safetensors", "res": 2048},
    "BiRefNet_dynamic":    {"script": "birefnet.py",      "weights": "BiRefNet_dynamic.safetensors",    "res": 1024},
    "BiRefNet_toonout":    {"script": "birefnet.py",      "weights": "BiRefNet_toonout.safetensors",    "res": 1024},
    "Lucida":              {"script": "birefnet.py",      "weights": "Lucida.safetensors",              "res": 1024},
    "BiRefNet_512x512":    {"script": "birefnet.py",      "weights": "BiRefNet_512x512.safetensors",    "res": 512,  "force_res": True},
    "BiRefNet_lite":       {"script": "birefnet_lite.py", "weights": "BiRefNet_lite.safetensors",       "res": 1024},
    "BiRefNet_lite-2K":    {"script": "birefnet_lite.py", "weights": "BiRefNet_lite-2K.safetensors",    "res": 2048},
    "BiRefNet_lite-matting": {"script": "birefnet_lite.py", "weights": "BiRefNet_lite-matting.safetensors", "res": 1024},
    # 以下变体 RMBG 插件没有；权重名直接用 ZhengPeng7 官方命名（常见于模型库）。
    # 这几个在 1038lab/BiRefNet 里没有，必须去 ZhengPeng7 的各数据集仓库取，
    # 且仓库内文件名统一是 model.safetensors —— 所以配 repo + dl_name，
    # 下载后另存为本地名（权重结构已验证与 General 完全一致，754 个张量无差异）。
    "BiRefNet-dis":        {"script": "birefnet.py",      "weights": "DIS.safetensors",       "res": 1024,
                            "repo": "ZhengPeng7/BiRefNet-DIS5K",        "dl_name": "model.safetensors"},
    "BiRefNet-dis-tr":     {"script": "birefnet.py",      "weights": "DIS-TR_TEs.safetensors", "res": 1024,
                            "repo": "ZhengPeng7/BiRefNet-DIS5K-TR_TEs", "dl_name": "model.safetensors"},
    "BiRefNet-cod":        {"script": "birefnet.py",      "weights": "COD.safetensors",       "res": 1024,
                            "repo": "ZhengPeng7/BiRefNet-COD",          "dl_name": "model.safetensors"},
    "BiRefNet-hrsod":      {"script": "birefnet.py",      "weights": "HRSOD.safetensors",     "res": 1024,
                            "repo": "ZhengPeng7/BiRefNet-HRSOD",        "dl_name": "model.safetensors"},
    "BiRefNet-legacy":     {"script": "birefnet.py",      "weights": "General-legacy.safetensors", "res": 1024,
                            "repo": "ZhengPeng7/BiRefNet-legacy",       "dl_name": "model.safetensors"},
}

# RMBG 命名 → ZhengPeng7 官方命名（同一权重的两种文件名，哈希已验证一致）。
# 挂载模型库（extra_model_paths 的 BiRefNet 类别）通常用右列命名。
ZHENG_PENG7_ALIAS = {
    "BiRefNet-general.safetensors": "General.safetensors",
    "BiRefNet-HR.safetensors": "General-HR.safetensors",
    "BiRefNet-portrait.safetensors": "Portrait.safetensors",
    "BiRefNet-matting.safetensors": "Matting.safetensors",
    "BiRefNet-HR-matting.safetensors": "Matting-HR.safetensors",
    "BiRefNet_lite.safetensors": "General-Lite.safetensors",
    "BiRefNet_lite-2K.safetensors": "General-Lite-2K.safetensors",
    "BiRefNet_lite-matting.safetensors": "Matting-Lite.safetensors",
    "BiRefNet_dynamic.safetensors": "General-dynamic.safetensors",
    "BiRefNet_512x512.safetensors": "General-reso_512.safetensors",
}

_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)


def _cache_dir(model_name=None):
    """与 ComfyUI-RMBG 共享的模型缓存目录（下载落这里）。

    带 subdir 的模型（如 RMBG-2.0）落在自己的子目录，和 RMBG 插件完全一致，
    两边谁先下载另一边都能直接用。
    """
    root = os.path.join(folder_paths.models_dir, "RMBG")
    sub = MODEL_CONFIG.get(model_name, {}).get("subdir") if model_name else None
    return os.path.join(root, sub) if sub else os.path.join(root, "BiRefNet")


def _search_dirs(model_name=None):
    """按优先级列出模型搜索目录：本模型专属目录 → 共享缓存 → 挂载库。"""
    dirs = []
    cfg = MODEL_CONFIG.get(model_name, {}) if model_name else {}
    sub = cfg.get("subdir")

    if sub:
        dirs.append(os.path.join(folder_paths.models_dir, "RMBG", sub))
    dirs.append(_cache_dir())

    # 挂载库里除了根目录，常见子目录也要看：BiRefNet/ 与各模型自己的子目录
    wanted = {"", "BiRefNet"}
    if sub:
        wanted.add(sub)
    for folder_name in ("BiRefNet", "RMBG"):
        try:
            roots = folder_paths.get_folder_paths(folder_name)
        except KeyError:
            continue
        for root in roots:
            for name in sorted(wanted):
                d = os.path.join(str(root), name) if name else str(root)
                if d not in dirs and os.path.isdir(d):
                    dirs.append(d)
    return dirs


def _find_file(filename, dirs):
    for d in dirs:
        p = os.path.join(d, filename)
        if os.path.isfile(p):
            return p
    return None


def _download_with_watchdog(fname, cdir, repo_id=_REPO_ID, stall_seconds: float = 60.0,
                            dest_name=None):
    """hf_hub_download 带停滞看门狗。

    hf_hub_download 在网络半死（TCP 活着但不再来数据）时会无限期挂起，
    没有总超时——曾把一次执行卡了 19 分钟（22:15 停在 88MB 直到用户重启）。
    这里在后台线程跑下载，主线程每 5 秒检查一次"最终文件 + .incomplete 临时
    文件"的总字节数，超过 stall_seconds 无任何增长就放弃并报错。

    dest_name：仓库文件名与本地文件名不同时（ZhengPeng7 各数据集仓库一律叫
    model.safetensors），下载完就地改名，节点后续按本地名查找。
    """
    import glob
    import threading
    import time

    result = {}
    local_name = dest_name or fname

    def work():
        try:
            from huggingface_hub import hf_hub_download

            path = hf_hub_download(
                repo_id=repo_id, filename=fname, local_dir=cdir)
            if local_name != fname:
                dest = os.path.join(cdir, local_name)
                os.replace(path, dest)
                path = dest
            result["path"] = path
        except Exception as e:  # noqa: BLE001 - 原样抛给主线程
            result["error"] = e

    worker = threading.Thread(target=work, daemon=True)
    worker.start()

    def _progress_bytes() -> int:
        total = 0
        final = os.path.join(cdir, local_name)
        if os.path.exists(final):
            total += os.path.getsize(final)
        for inc in glob.glob(os.path.join(cdir, "**", "*.incomplete"),
                             recursive=True):
            try:
                total += os.path.getsize(inc)
            except OSError:
                pass
        return total

    last_size = -1
    last_change = time.time()
    while worker.is_alive():
        time.sleep(5)
        size = _progress_bytes()
        if size > last_size:
            last_size = size
            last_change = time.time()
        elif time.time() - last_change > stall_seconds:
            raise RuntimeError(
                f"模型文件 {fname} 下载停滞超过 {int(stall_seconds)} 秒"
                f"（已下载 {last_size / 1e6:.0f}MB），已放弃本次执行。"
                "请检查网络/代理后重新运行节点，已下载的部分会断点续传。")
    if "error" in result:
        raise result["error"]
    return result["path"]


def _resolve_files(model_name):
    """解析模型文件的实际路径；缺的从 HuggingFace 下载到共享缓存。

    BiRefNet 家族要「脚本 + 配置 + 权重」三件，统一命名规则见 ZHENG_PENG7_ALIAS。
    """
    cfg = MODEL_CONFIG[model_name]
    dirs = _search_dirs(model_name)
    script_name = cfg["script"]
    resolved = {
        "script": _find_file(script_name, dirs),
        "config_py": _find_file("BiRefNet_config.py", dirs),
        "weights": _find_file(cfg["weights"], dirs),
    }
    if resolved["weights"] is None:
        alias = ZHENG_PENG7_ALIAS.get(cfg["weights"])
        if alias:
            resolved["weights"] = _find_file(alias, dirs)

    cdir = _cache_dir(model_name)
    os.makedirs(cdir, exist_ok=True)
    repo = cfg.get("repo", _REPO_ID)

    # 模型定义与配置文件统一从主仓库取（各数据集仓库里也有同一份，但版本未必同步）
    for key, fname in (("script", script_name),
                       ("config_py", "BiRefNet_config.py")):
        if resolved[key] is None:
            print(f"[QG-BiRefNet] 挂载库中未找到 {fname}，从 {_REPO_ID} 下载 ...")
            try:
                resolved[key] = _download_with_watchdog(fname, cdir, _REPO_ID)
            except Exception as e:
                raise RuntimeError(
                    f"模型文件 {fname} 下载失败：{e}\n"
                    "网络受限时可先设置环境变量 HF_ENDPOINT=https://hf-mirror.com 后重试，"
                    f"或手动把文件放到 {cdir} 或挂载的模型库目录。"
                ) from e

    if resolved["weights"] is None:
        fname = cfg["weights"]
        dl_name = cfg.get("dl_name", fname)
        print(f"[QG-BiRefNet] 未找到权重 {fname}，从 {repo} 下载 {dl_name} ...")
        try:
            resolved["weights"] = _download_with_watchdog(
                dl_name, cdir, repo, dest_name=fname)
        except Exception as e:
            raise RuntimeError(
                f"模型权重 {fname} 下载失败：{e}\n"
                "网络受限时可先设置环境变量 HF_ENDPOINT=https://hf-mirror.com 后重试，"
                f"或手动把文件放到 {cdir} 或挂载的模型库目录 "
                f"（下载地址 https://huggingface.co/{repo}/resolve/main/{dl_name}，"
                f"保存为 {fname}）。"
            ) from e
    return resolved


def _writable_patch_dir():
    """找一个能写补丁副本的目录：共享缓存 → 本包目录 → 系统临时目录。"""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        # 放在 models/RMBG 下一级，不进 BiRefNet/ 子目录，免得和模型文件混在一起
        os.path.join(folder_paths.models_dir, "RMBG", "_qg_patched"),
        os.path.join(here, ".patched"),
        os.path.join(tempfile.gettempdir(), "qg_birefnet_patched"),
    ]
    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, ".probe")
            with open(probe, "w", encoding="utf-8") as handle:
                handle.write("1")
            os.remove(probe)
            return d
        except OSError:
            continue
    return None


def _patched_script(script_path):
    """返回可以直接 exec 的模型定义路径（必要时先打补丁写到副本）。

    上游 birefnet.py 有两处必须改的地方：相对导入（动态 exec 时没有包上下文
    会 ImportError）、window-attention 里 mask 与 attn 的 dtype 不一致（fp16
    推理时报错）。早期实现是**就地写回原文件**，代价很明确：

    * 与 ComfyUI-RMBG 共用 ``models/RMBG`` 缓存，改了会影响另一个插件；
    * 模型库挂在 NAS / 只读盘时直接抛 PermissionError，整个节点不可用；
    * 上游更新覆盖文件后，补丁会以「悄悄失效 → 报错」的形式暴露。

    现在只读原文件，把补丁写进自己的副本目录；原文件换了版本（mtime 或大小
    变化）会自动重新生成副本。原文件本来就修好过时（patch 前后一致）直接返回
    原路径，不做任何多余拷贝。
    """
    with open(script_path, "r", encoding="utf-8") as handle:
        src = handle.read()
    patched = src.replace(
        "from .BiRefNet_config", "from BiRefNet_config"
    ).replace(
        "attn = attn.view(B_ // nW, nW, self.num_heads, N, N)"
        " + mask.unsqueeze(1).unsqueeze(0)",
        "attn = attn.view(B_ // nW, nW, self.num_heads, N, N)"
        " + mask.to(attn.dtype).unsqueeze(1).unsqueeze(0)",
    )
    if patched == src:
        return script_path

    try:
        info = os.stat(script_path)
        stamp = f"{int(info.st_mtime)}_{info.st_size}"
    except OSError:
        stamp = "0_0"
    digest = hashlib.md5(stamp.encode("utf-8")).hexdigest()[:8]
    name = f"{os.path.splitext(os.path.basename(script_path))[0]}.{digest}.py"

    out_dir = _writable_patch_dir()
    if out_dir:
        dest = os.path.join(out_dir, name)
        if os.path.isfile(dest):
            return dest
        try:
            tmp = dest + f".{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(patched)
            os.replace(tmp, dest)
            return dest
        except OSError:
            pass  # 落到下面的兜底

    # 一个可写目录都没有：退回「就地修」，但先给出能照做的报错
    try:
        with open(script_path, "w", encoding="utf-8") as handle:
            handle.write(patched)
        return script_path
    except OSError as exc:
        raise RuntimeError(
            f"BiRefNet 模型定义 {script_path} 需要打补丁后才能加载，但既找不到可写的"
            f"缓存目录，原文件也写不进去（{exc}）。\n"
            "解决办法（任选其一）：\n"
            "  1. 让 ComfyUI 对 models/RMBG 目录有写权限；\n"
            "  2. 手动把该文件里的 `from .BiRefNet_config` 改成 "
            "`from BiRefNet_config`，并把 window-attention 里的 "
            "`+ mask.unsqueeze(1).unsqueeze(0)` 改成 "
            "`+ mask.to(attn.dtype).unsqueeze(1).unsqueeze(0)`。"
        ) from exc


class _Runner:
    """单例模型运行器：按需加载/切换，保留最后一次加载的模型。"""

    def __init__(self):
        self.model = None
        self.loaded_name = None

    def _load(self, model_name):
        if self.loaded_name == model_name and self.model is not None:
            return
        self.unload()
        files = _resolve_files(model_name)
        model = self._load_birefnet(files)

        self.model = model
        self.loaded_name = model_name
        print(f"[QG-BiRefNet] 已加载 {model_name}（权重：{files['weights']}）"
              f"到 {mm.get_torch_device()}")

    def _load_birefnet(self, files):
        # 上游 birefnet.py 用相对导入引用配置、window-attention 的 mask 加法在
        # fp16 下 dtype 不一致。补丁写进副本，源文件保持只读（见 _patched_script）。
        script_path = _patched_script(files["script"])

        # 动态加载 config 与模型定义，再用 safetensors 权重实例化
        for mod_name, path in (("BiRefNet_config", files["config_py"]),
                               ("birefnet_qg", script_path)):
            spec = importlib.util.spec_from_file_location(mod_name, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)

        from safetensors.torch import load_file

        model = sys.modules["birefnet_qg"].BiRefNet(sys.modules["BiRefNet_config"].BiRefNetConfig())
        model.load_state_dict(load_file(files["weights"]))
        model.eval()

        device = mm.get_torch_device()
        if device.type == "cuda":
            # CUDA 上 fp16 省显存提速度；CPU 上 half 又慢又容易踩算子坑
            model.half()
            torch.set_float32_matmul_precision("high")
        return model.to(device)

    def predict(self, image_pil, model_name, process_res):
        """跑一次推理，返回与原图同尺寸的 0..255 前景概率 PIL L 模式遮罩。"""
        self._load(model_name)
        return self._predict_birefnet(image_pil, process_res)

    def _predict_birefnet(self, image_pil, process_res):
        device = mm.get_torch_device()

        w, h = image_pil.size
        x = image_pil.convert("RGB").resize((process_res, process_res), Image.BICUBIC)
        arr = np.asarray(x).astype(np.float32) / 255.0
        mean = np.array(_IMAGENET_MEAN, dtype=np.float32)
        std = np.array(_IMAGENET_STD, dtype=np.float32)
        arr = (arr - mean) / std
        tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)
        if device.type == "cuda":
            tensor = tensor.half()
        tensor = tensor.to(device)

        with torch.no_grad():
            preds = self.model(tensor)
            prob = preds[-1].float().sigmoid()[0, 0].cpu().numpy()
        prob_img = Image.fromarray((prob * 255.0 + 0.5).clip(0, 255).astype(np.uint8), "L")
        return prob_img.resize((w, h), Image.BICUBIC)

    def unload(self):
        if self.model is not None:
            del self.model
            self.model = None
            self.loaded_name = None
            gc.collect()
            try:
                mm.soft_empty_cache()
            except Exception:
                pass


_runner = _Runner()


def _adjust_sensitivity(mask_pil, sensitivity):
    """灵敏度 <1 时线性抬升遮罩亮度：值越小前景判定越宽松。"""
    if sensitivity >= 1.0:
        return mask_pil
    gain = 1.0 + (1.0 - sensitivity)
    arr = np.asarray(mask_pil).astype(np.float32) / 255.0 * gain
    return Image.fromarray((arr.clip(0.0, 1.0) * 255.0 + 0.5).astype(np.uint8), "L")


def _offset_mask(mask_pil, offset):
    """遮罩偏移：正值膨胀、负值收缩（灰度图上取方形邻域的最大/最小值）。

    早先的写法是 3×3 ``MaxFilter``/``MinFilter`` 循环 N 次，N 由 mask_offset
    决定（上限 20）。2048² 图上 offset=20 要 2 秒左右，4K 图更慢，而节点上
    没有任何提示——看起来就像卡住了。方形邻域的 max/min 是可分离的，两条一维
    滤波一次算完，与「循环 N 次」的定义逐像素一致（含边缘复制边界）。
    """
    px = abs(int(offset))
    if px <= 0:
        return mask_pil
    if _ndimage is not None:
        arr = np.asarray(mask_pil)
        # mode="nearest" 等于复制边缘像素，与 Pillow 的 3×3 滤波边界一致
        filter_fn = _ndimage.maximum_filter if offset > 0 else _ndimage.minimum_filter
        out = filter_fn(arr, size=2 * px + 1, mode="nearest")
        return Image.fromarray(out.astype(np.uint8), "L")
    for _ in range(px):  # 没有 scipy 时退回逐次 3×3，结果一样只是慢
        mask_pil = mask_pil.filter(
            ImageFilter.MaxFilter(3) if offset > 0 else ImageFilter.MinFilter(3))
    return mask_pil


def _refine_foreground(rgb_pil, mask_pil):
    """前景颜色精修：对 0.05..0.95 过渡区做二值边缘与原概率的混合，
    弱化半透明边缘残留的原背景色。"""
    try:
        import cv2
    except ImportError as error:
        # 裸 ModuleNotFoundError 只会说「No module named 'cv2'」，用户不知道该
        # 装哪个包、也不知道这只是一个可选开关。opencv 故意没写进
        # requirements.txt（三个变体抢同一个 cv2，会顶掉 ComfyUI 自带的 contrib 版）。
        raise RuntimeError(
            "「前景颜色精修」这个开关需要 opencv（cv2），当前环境里没有。"
            "把它关掉，或者用 ComfyUI 自带的 Python 装一次："
            "python_embeded\\python.exe -m pip install opencv-contrib-python"
        ) from error

    mask = np.asarray(mask_pil).astype(np.float32) / 255.0
    binary = (mask > 0.45).astype(np.float32)
    edge_blur = cv2.GaussianBlur(binary, (3, 3), 0)
    transition = (mask > 0.05) & (mask < 0.95)
    refined = np.where(transition, 0.85 * mask + 0.15 * edge_blur, binary)
    edge_band = (mask > 0.2) & (mask < 0.8)
    refined = np.where(edge_band, refined * 0.98, refined)

    img = np.asarray(rgb_pil).astype(np.float32)
    out = img * refined[..., None]
    return Image.fromarray(out.clip(0, 255).astype(np.uint8), "RGB")


def _hex_to_rgba(color):
    """#RRGGBB 或 #RRGGBBAA → (r, g, b, a)。"""
    text = color.lstrip("#")
    if len(text) == 6:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), 255
    if len(text) == 8:
        return (int(text[0:2], 16), int(text[2:4], 16),
                int(text[4:6], 16), int(text[6:8], 16))
    raise ValueError(f"无效的颜色格式：{color}（应为 #RRGGBB 或 #RRGGBBAA）")


def _frame_to_rgb_uint8(frame):
    """一帧 IMAGE（0~1 浮点）→ 3 通道 uint8，喂给 BiRefNet 前统一归一。

    ComfyUI 的 IMAGE 一般是 [B,H,W,3]，但上游可能给 RGBA（例如抠图节点的
    输出）、灰度或多通道特征图。原先直接把数组交给
    ``Image.fromarray(..., "RGB")``，非 3 通道会抛 ValueError，且发生在推理
    之前，用户只看到一句看不懂的英文。这里按本包既有惯例处理：

    * 4 通道：按 alpha 压到白底（与 ``tensor_to_data_url`` 一致）；
    * 1 / 2 通道：复制灰度到三通道（2 通道只取第一通道，避免 LA 偏绿）；
    * 3 通道：原样；>4 通道：切前三个。
    """
    array = frame.cpu().numpy() if hasattr(frame, "cpu") else np.asarray(frame)
    array = np.clip(array, 0.0, 1.0)
    if array.ndim == 2:
        array = array[..., None]
    channels = array.shape[-1]
    if channels == 4:
        alpha = array[..., 3:4]
        array = array[..., :3] * alpha + (1.0 - alpha)
    elif channels == 1:
        array = np.repeat(array, 3, axis=-1)
    elif channels == 2:
        array = np.repeat(array[..., :1], 3, axis=-1)
    elif channels > 4:
        array = array[..., :3]
    return (array * 255.0 + 0.5).clip(0, 255).astype(np.uint8)


class QGBiRefNet:
    CATEGORY = "QG 工具"
    DESCRIPTION = (
        "高精度抠图。18 个 BiRefNet / RMBG 模型任选，首次使用自动下载到 "
        "models/RMBG/（与 ComfyUI-RMBG 共用同一份缓存，谁先下另一边直接用）。"
        "输出原图、遮罩、遮罩预览图；可调敏感度、羽化与边缘收缩，可选只留"
        "前景或换成纯色背景。"
    )
    SEARCH_ALIASES = [
        "birefnet", "rmbg", "remove background", "background removal",
        "matting", "segmentation", "cutout", "抠图", "去背景", "去背",
        "蒙版", "qg",
    ]
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "MASK", "IMAGE")
    RETURN_NAMES = ("IMAGE", "MASK", "MASK_IMAGE")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "要抠图的图像。批次里每帧独立推理，输出与输入同尺寸。"}),
                "model": (list(MODEL_CONFIG.keys()), {"tooltip":
                    "BiRefNet 变体。general 通用；portrait 人像；matting / HR-matting "
                    "适合发丝级半透明；HR 系列按 2048 推理，慢但边缘更细。首次选择会下载权重。"}),
            },
            "optional": {
                "sensitivity": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "遮罩亮度增益。1.0 保持模型原判；调小（如 0.8）让半透明边缘更倾向判成前景，"
                               "适合浅色、透明或毛发多的主体。"}),
                "mask_blur": ("INT", {"default": 0, "min": 0, "max": 64, "step": 1,
                    "tooltip": "边缘高斯模糊半径（像素）。0 不模糊；1~3 能软化锯齿，"
                               "值越大前景边缘越虚。"}),
                "mask_offset": ("INT", {"default": 0, "min": -20, "max": 20, "step": 1,
                    "tooltip": "整体扩张/收缩遮罩（像素）。正值向外扩，吃掉一圈背景；"
                               "负值向内收，去掉边缘残留的背景色。"}),
                "invert_output": ("BOOLEAN", {"default": False,
                    "tooltip": "反转遮罩：主体变透明、背景留下。做「去掉主体」时用。"}),
                "refine_foreground": ("BOOLEAN", {"default": False,
                    "tooltip": "前景颜色精修：对边缘过渡区做 alpha 混合，弱化半透明处残留的原背景色。"
                               "需要 opencv（没装会给出安装命令）。"}),
                "unload_model": ("BOOLEAN", {"default": False,
                    "tooltip": "跑完把模型移出显存。连续跑多张时关掉更快；显存紧张或要和别的模型混用时打开。"}),
                "background": (["Alpha", "Color"], {"default": "Alpha",
                    "tooltip": "输出图的底：Alpha 保留透明通道；Color 用下面的颜色铺底（输出不透明）。"}),
                "background_color": ("STRING", {"default": "#222222",
                    "tooltip": "底色，十六进制。支持 #RRGGBB 或 #RRGGBBAA（带透明度）。格式不对会直接报错。"}),
            },
        }

    def run(self, image, model, sensitivity=1.0, mask_blur=0, mask_offset=0,
            invert_output=False, refine_foreground=False, unload_model=False,
            background="Alpha", background_color="#222222"):
        if model not in MODEL_CONFIG:
            # 老工作流可能存着已下线的模型名（INSPYRENET / BEN / BEN2 已移除），
            # 直接 KeyError 的话报错信息看不出原因，这里给一句能照着改的提示
            raise ValueError(
                f"模型 {model!r} 已不在支持列表里（INSPYRENET / BEN / BEN2 已移除）。"
                f"请在该节点上重新选一个模型，可选：{', '.join(MODEL_CONFIG)}"
            )
        cfg = MODEL_CONFIG[model]
        if cfg.get("force_res"):
            process_res = cfg["res"]
        else:
            process_res = cfg["res"] // 32 * 32

        shape = tuple(getattr(image, "shape", ()) or ())
        if len(shape) == 3:            # 单帧 [H,W,C] → 补上 batch 维
            image = image[None]
            shape = tuple(image.shape)
        if len(shape) != 4:
            raise ValueError(
                f"图像输入的形状必须是 [batch,高,宽,通道]，实际是 {shape}。")

        images_out, masks_out = [], []
        try:
            if shape[0] == 0:
                # 空 batch：torch.stack([]) 会抛裸 ValueError；本包其它图像
                # 节点一律返回空张量，这里保持一致，finally 仍会卸载模型。
                empty_mask = torch.empty(
                    (0, shape[1], shape[2]), dtype=torch.float32)
                return (
                    torch.empty((0, shape[1], shape[2], 3), dtype=torch.float32),
                    empty_mask,
                    empty_mask.unsqueeze(-1).expand(-1, -1, -1, 3).clone(),
                )
            for frame in image:
                # ComfyUI IMAGE 帧是 HWC 0..1 float；统一成 RGB 再进模型
                rgb = Image.fromarray(_frame_to_rgb_uint8(frame))
                w, h = rgb.size

                mask = _runner.predict(rgb, model, process_res)
                mask = _adjust_sensitivity(mask, sensitivity)
                if mask_blur > 0:
                    mask = mask.filter(ImageFilter.GaussianBlur(radius=mask_blur))
                if mask_offset != 0:
                    mask = _offset_mask(mask, mask_offset)
                if invert_output:
                    mask = Image.fromarray(255 - np.asarray(mask), "L")

                if refine_foreground:
                    fg_rgb = _refine_foreground(rgb, mask)
                else:
                    fg_rgb = rgb
                foreground = Image.merge("RGBA", (*fg_rgb.split(), mask))

                if background == "Alpha":
                    frame_out = foreground
                else:
                    bg = Image.new("RGBA", (w, h), _hex_to_rgba(background_color))
                    frame_out = Image.alpha_composite(bg, foreground).convert("RGB")

                arr = np.asarray(frame_out).astype(np.float32) / 255.0
                images_out.append(torch.from_numpy(arr))
                masks_out.append(torch.from_numpy(
                    np.asarray(mask).astype(np.float32) / 255.0))

            image_tensor = torch.stack(images_out, dim=0)
            mask_tensor = torch.stack(masks_out, dim=0)
            mask_image = mask_tensor.unsqueeze(-1).expand(-1, -1, -1, 3).clone()
            return (image_tensor, mask_tensor, mask_image)
        finally:
            if unload_model:
                _runner.unload()


NODE_CLASS_MAPPINGS = {"QG_BiRefNet": QGBiRefNet}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_BiRefNet": "QG BiRefNet 去除背景"}
