"""Qwen Image 2.1 文本编码 + 还原画布对照测试。

必须在 ComfyUI 自带 python_embeded 下、以 ComfyUI 根目录为工作目录运行
（参考模块与本包模块都要 import comfy/torch/cv2）：

    cd D:/ComfyUI_windows_portable/ComfyUI
    ../python_embeded/python.exe custom_nodes/ComfyUI-QG-Multipack/tests/test_qwen_text_encode.py

对照方式：从 Goohaitools 源文件直接加载真·参考类（TextEncodeQwenImage21GH /
RestoreQwenImage21GH），用 fake clip / fake vae 记录全部中间产物，与
本包 QG_QwenTextEncode / QG_QwenRestore 同输入对照，要求逐项零差异。
"""

import importlib.util
import pathlib
import sys

# ---- 本机环境规避（必须在 import comfy / 参考模块之前）----
# 1) comfy_kitchen 在本机裸 import 即段错误，quant_ops 有 ImportError
#    fallback，stub 掉只损失 fp8 量化支持，本节点用不到；
# 2) 测试进程不触发 CUDA 上下文：等效 --cpu，把 cli_args.args.cpu 置真。
#    （旧注释里的 RX 590 / ROCm 是旧电脑环境；本机为 GTX 1650 + CUDA torch。）
sys.modules["comfy_kitchen"] = None
COMFY_ROOT = None  # 占位，下面真正赋值
import torch  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
PKG_ROOT = HERE.parent
COMFY_ROOT = PKG_ROOT.parent.parent
sys.path.insert(0, str(COMFY_ROOT))
sys.path.insert(0, str(PKG_ROOT))
sys.path.insert(0, str(HERE))

import comfy.cli_args  # noqa: E402
from ref_helper import require_ref  # noqa: E402

comfy.cli_args.args.cpu = True

REF_FILE = pathlib.Path(require_ref("nodes", "Text Encode Qwen Image 2.1 GH.py"))


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeClip:
    """记录 tokenize / encode 调用，返回可被 conditioning_set_values 处理的结构。"""

    def __init__(self, tag):
        self.tag = tag
        self.tokenize_calls = []
        self.encode_calls = []

    def tokenize(self, prompt, images=None, keep_vision=None, prevent_empty_text=None, **kw):
        self.tokenize_calls.append({
            "prompt": prompt,
            "images": None if images is None else [t.detach().cpu().clone() for t in images],
            "keep_vision": keep_vision,
            "prevent_empty_text": prevent_empty_text,
        })
        return {"tokens": prompt, "images": len(images or [])}

    def encode_from_tokens_scheduled(self, tokens, **kw):
        self.encode_calls.append(tokens)
        return [["cond", {}]]


class FakeVae:
    """记录 encode 输入；返回与输入同形状减半的确定值 latent。"""

    def __init__(self):
        self.calls = []

    def encode(self, image):
        self.calls.append(image.detach().cpu().clone())
        h, w = image.shape[1] // 16, image.shape[2] // 16
        base = image[:1, :1, :1, :1].mean().item()
        return torch.full((1, 64, h, w), 0.5 + base * 0.01 + len(self.calls) * 0.001)


def run_encode(mod_cls, clip, vae, kwargs, seed):
    torch.manual_seed(seed)
    return mod_cls().encode(clip=clip, vae=vae and vae or None, **kwargs)


def tensors_equal(a, b):
    if isinstance(a, (list, tuple)):
        return (isinstance(b, type(a)) and len(a) == len(b)
                and all(tensors_equal(x, y) for x, y in zip(a, b)))
    if isinstance(a, dict):
        return (isinstance(b, dict) and set(a) == set(b)
                and all(tensors_equal(a[k], b[k]) for k in a))
    if isinstance(a, torch.Tensor):
        return (isinstance(b, torch.Tensor) and a.shape == b.shape
                and torch.equal(a.cpu(), b.cpu()))
    return a == b


def main():
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        mark = "PASS" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"[{mark}] {name}" + (f"  {detail}" if detail and not cond else ""))

    ref = load_module(str(REF_FILE), "gh_qwen_ref")
    ours = load_module(str(PKG_ROOT / "qwen_text_encode_node.py"), "qg_qwen_ours")

    # 0. info 类型名与参考一致（保证互相可连）
    check("info 类型名与参考一致",
          ours.RESTORE_INFO_TYPE == ref.RESTORE_INFO_TYPE)

    # 1. 纯函数全量对照
    for w in (32, 100, 1024, 1025, 2047, 4096):
        check(f"_round_latent_size({w})",
              ours._round_latent_size(w) == ref._round_latent_size(w))
    sizes = [(512, 512), (640, 960), (1000, 1500), (2048, 2048), (4096, 1000), (97, 61)]
    areas = [32 * 32, 512 * 512, 1024 * 1024, 2048 * 2048, 800 * 800]
    for (w, h) in sizes:
        for a in areas:
            check(f"_area_limited_size({w},{h},{a})",
                  ours._area_limited_size(w, h, a) == ref._area_limited_size(w, h, a))
            check(f"_rounded_area_size({w},{h},{a})",
                  ours._rounded_area_size(w, h, a) == ref._rounded_area_size(w, h, a))
        for tw, th in [(1024, 1024), (640, 960), (2048, 100)]:
            check(f"_cover_crop_is_small({w},{h},{tw},{th})",
                  ours._cover_crop_is_small(w, h, tw, th) == ref._cover_crop_is_small(w, h, tw, th))
    # 注：非法 ref_image_size 的防御在 encode 层（两个实现都有
    # not-in-options -> 自动 的回退），纯函数不设防，不在此对照。
    for opt in ref.REFERENCE_SIZE_OPTIONS:
        for n in (0, 1, 2, 3, 4, 5, 11):
            for lw, lh in [(1024, 1024), (640, 960), (2048, 2048)]:
                check(f"_reference_area({opt},{n},{lw},{lh})",
                      ours._reference_area(opt, n, lw, lh) == ref._reference_area(opt, n, lw, lh))

    # 2. encode 全流程对照（fake clip / vae，真实 torch + comfy upscale + cv2）
    def make_image(b, h, w, seedval, channels=3):
        g = torch.Generator().manual_seed(seedval)
        return torch.rand((b, h, w, channels), generator=g)

    def corner_mask():
        m = torch.zeros(1, 64, 64)
        m[0, :20, :20] = 1.0
        return m

    scenarios = []
    # 场景 A：截图路径——图 1 宽高比接近 latent（覆盖 primary_matches_target
    # + 填充模式 + restore_info=padding）
    scenarios.append({
        "name": "A 填充/图1比例接近",
        "kw": dict(prompt="1girl", negative_prompt="bad", mode="填充",
                   latent_width=1024, latent_height=1024, ref_image_size="自动"),
        "imgs": {1: make_image(1, 512, 512, 11)},
    })
    # 场景 B：裁剪模式 + 图 1 比例悬殊（覆盖 _area_limited_size 主参考路径）
    scenarios.append({
        "name": "B 裁剪/图1比例悬殊",
        "kw": dict(prompt="a cat", negative_prompt="", mode="裁剪",
                   latent_width=768, latent_height=1024, ref_image_size="自动"),
        "imgs": {1: make_image(2, 900, 1600, 22)},
    })
    # 场景 C：多图（1~5）+ 固定参考尺寸 + vae
    scenarios.append({
        "name": "C 多图/固定1024/带vae",
        "kw": dict(prompt="p", negative_prompt="n", mode="填充",
                   latent_width=640, latent_height=640, ref_image_size="1024"),
        "imgs": {1: make_image(1, 600, 800, 33), 2: make_image(1, 300, 300, 34),
                 3: make_image(1, 1280, 720, 35), 5: make_image(1, 64, 64, 36)},
        "vae": True,
    })
    # 场景 D：带 mask（全流程含膨胀羽化 + noise_mask）
    scenarios.append({
        "name": "D 填充+局部遮罩",
        "kw": dict(prompt="x", negative_prompt="y", mode="填充",
                   latent_width=1024, latent_height=1024, ref_image_size="自动"),
        "imgs": {1: make_image(1, 512, 512, 44)},
        "mask": corner_mask(),
    })
    # 场景 E：全黑 mask（应走无遮罩路径）+ 无图（纯文本）
    scenarios.append({
        "name": "E 全黑mask",
        "kw": dict(prompt="x", negative_prompt="y", mode="填充",
                   latent_width=512, latent_height=512, ref_image_size="自动"),
        "imgs": {1: make_image(1, 256, 256, 55)},
        "mask": torch.zeros(1, 64, 64),
    })
    scenarios.append({
        "name": "F 无参考图",
        "kw": dict(prompt="only text", negative_prompt="neg", mode="裁剪",
                   latent_width=1000, latent_height=800, ref_image_size="自动"),
        "imgs": {},
    })

    for sc in scenarios:
        clip_a, clip_b = FakeClip("ours"), FakeClip("ref")
        vae_kw = sc.get("vae")
        vae_a = FakeVae() if vae_kw else None
        vae_b = FakeVae() if vae_kw else None
        kw = dict(sc["kw"])
        kw.update({f"image_{i:02d}": img for i, img in sc["imgs"].items()})
        if "mask" in sc:
            kw["mask"] = sc["mask"]
        out_a = ours.QG_QwenTextEncode().encode(
            clip=clip_a, vae=vae_a, **kw)
        out_b = ref.TextEncodeQwenImage21GH().encode(
            clip=clip_b, vae=vae_b, **kw)
        # 输出四元组逐项对照
        for idx, (x, y) in enumerate(zip(out_a, out_b)):
            check(f"{sc['name']} 输出[{idx}] 一致", tensors_equal(x, y),
                  f"{type(x)} vs {type(y)}")
        # clip 收到的视觉图序列逐张对照
        imgs_a = clip_a.tokenize_calls[0]["images"] or []
        imgs_b = clip_b.tokenize_calls[0]["images"] or []
        check(f"{sc['name']} tokenize 图片张数一致", len(imgs_a) == len(imgs_b),
              f"{len(imgs_a)} vs {len(imgs_b)}")
        for i, (x, y) in enumerate(zip(imgs_a, imgs_b)):
            check(f"{sc['name']} 视觉图[{i}] 逐像素一致", tensors_equal(x, y))
        check(f"{sc['name']} tokenize 参数一致",
              clip_a.tokenize_calls[0]["prompt"] == clip_b.tokenize_calls[0]["prompt"]
              and clip_a.tokenize_calls[0]["keep_vision"] == clip_b.tokenize_calls[0]["keep_vision"]
              and clip_a.tokenize_calls[0]["prevent_empty_text"] == clip_b.tokenize_calls[0]["prevent_empty_text"])
        # vae 收到的输入序列对照
        if vae_kw:
            check(f"{sc['name']} vae 调用数一致", len(vae_a.calls) == len(vae_b.calls))
            for i, (x, y) in enumerate(zip(vae_a.calls, vae_b.calls)):
                check(f"{sc['name']} vae 输入[{i}] 逐像素一致", tensors_equal(x, y))
        # reference_latents 注入顺序
        ra = out_a[0][0][1].get("reference_latents")
        rb = out_b[0][0][1].get("reference_latents")
        check(f"{sc['name']} reference_latents 一致", tensors_equal(ra, rb))

    # 3. restore 全量对照
    info_pad = {
        "mode": "padding", "canvas_width": 1024, "canvas_height": 1024,
        "content_left": 112, "content_top": 0, "content_width": 800,
        "content_height": 1000, "padding_left": 112, "padding_top": 0,
        "padding_right": 112, "padding_bottom": 24, "fill_value": 128.0 / 255.0,
    }
    for shape in [(1, 1024, 1024, 3), (1, 2048, 2048, 3), (1, 512, 512, 4)]:
        g = torch.Generator().manual_seed(7)
        img = torch.rand(shape, generator=g)
        a = ours.QG_QwenRestore().restore(image=img, info=info_pad)
        b = ref.RestoreQwenImage21GH().restore(image=img, info=info_pad)
        check(f"restore {shape} 一致", tensors_equal(a, b))
    # 非 padding info / 坏 info：原图直通
    for info in [{"mode": "none"}, None, "junk"]:
        img = torch.zeros(1, 8, 8, 3)
        a = ours.QG_QwenRestore().restore(image=img, info=info)
        b = ref.RestoreQwenImage21GH().restore(image=img, info=info)
        check(f"restore info={info!r} 直通一致", tensors_equal(a, b))

    # 4. INPUT_TYPES 对照（控件/选项/默认值/范围）
    ti_a = ours.QG_QwenTextEncode.INPUT_TYPES()
    ti_b = ref.TextEncodeQwenImage21GH.INPUT_TYPES()
    check("required 键序一致", list(ti_a["required"]) == list(ti_b["required"]))
    for k in ti_b["required"]:
        va, vb = ti_a["required"][k], ti_b["required"][k]
        check(f"required.{k} 定义一致", list(va) == list(vb), f"{va} vs {vb}")
    check("optional 键一致", list(ti_a["optional"]) == list(ti_b["optional"]))
    check("输出类型/名称一致",
          ours.QG_QwenTextEncode.RETURN_TYPES == ref.TextEncodeQwenImage21GH.RETURN_TYPES
          and ours.QG_QwenTextEncode.RETURN_NAMES == ref.TextEncodeQwenImage21GH.RETURN_NAMES)

    print()
    print("全部通过" if ok else "存在失败项")
    return 0 if ok else 1

    # 4. INPUT_TYPES 对照（控件/选项/默认值/范围）


if __name__ == "__main__":
    raise SystemExit(main())
