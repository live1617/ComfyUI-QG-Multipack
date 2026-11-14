"""Qwen image 2.1 提示词优化 对照测试。

必须在 ComfyUI 自带 python_embeded 下、以 ComfyUI 根目录为工作目录运行
（参考模块与本包模块都要 import torch/numpy/PIL）：

    cd D:/ComfyUI_windows_portable/ComfyUI
    ../python_embeded/python.exe custom_nodes/ComfyUI-QG-Multipack/tests/test_qwen_prompt_optimizer.py

对照方式：从 Goohaitools 源文件直接加载真·参考 runtime 与真·参考节点类
（stub folder_paths / server，两节点同 stub 环境加载），纯函数全量扫描 +
INPUT_TYPES 逐项 + optimize 场景矩阵（fake QwenImageRuntime.complete 录制
全部入参），要求逐项零差异。llama-cpp 本体不参与（两边都保持未安装时的
降级路径）。
"""

import importlib.util
import json
import pathlib
import sys
import types

# ---- 本机环境规避（必须在 import torch / 参考模块之前）----
# 1) comfy_kitchen 在本机裸 import 即段错误，stub 掉（本测试不碰量化）；
# 2) 测试进程不触发 CUDA 探测，等效 --cpu 规避（旧注释里的 RX 590 /
#    ROCm 是旧电脑环境；本机为 GTX 1650 + CUDA torch）。
sys.modules["comfy_kitchen"] = None
import torch  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
PKG_ROOT = HERE.parent
COMFY_ROOT = PKG_ROOT.parent.parent
sys.path.insert(0, str(COMFY_ROOT))
sys.path.insert(0, str(HERE))

import comfy.cli_args  # noqa: E402
from ref_helper import ref_root, require_ref  # noqa: E402

comfy.cli_args.args.cpu = True

REF_ROOT = pathlib.Path(ref_root())
REF_NODE_FILE = pathlib.Path(require_ref("nodes", "Qwen image 2.1 提示词优化.py"))
REF_RUNTIME_FILE = pathlib.Path(require_ref("resources", "qwen_image_runtime.py"))

# ---- folder_paths stub（两个节点模块加载前就位，行为完全可控）----
LLM_FILES = [
    "Qwen-Image-2.1-PE-T2I.Q5_K_S.gguf",
    "Qwen-Image-2.1-PE-I2I.Q5_K_S.gguf",
    "Qwen-Image-2.1-PE-I2I.mmproj-bf16.gguf",
    "OtherModel.Q4_K_M.gguf",
]


def _fake_full_path(key, name):
    if name in LLM_FILES:
        return str(COMFY_ROOT / "models" / "LLM" / name)
    return None


_fp = types.ModuleType("folder_paths")
_fp.models_dir = str(COMFY_ROOT / "models")
_fp.folder_names_and_paths = {}
_fp.get_filename_list = lambda key: list(LLM_FILES) if key == "LLM" else []
_fp.get_full_path = _fake_full_path
sys.modules["folder_paths"] = _fp

# ---- server stub：PromptServer.instance.routes.get/post 返回原函数 ----
_fake_routes = types.SimpleNamespace(
    get=lambda path: (lambda fn: fn),
    post=lambda path: (lambda fn: fn),
)
_server_mod = types.ModuleType("server")
_server_mod.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(routes=_fake_routes))
sys.modules["server"] = _server_mod


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# 参考 runtime：直接文件加载
ref_rt = load_module(str(REF_RUNTIME_FILE), "gh_qwen_prompt_rt_ref")

# 参考 node 里 `from resources.qwen_image_runtime import ...`：
# 把上面加载好的模块注册成 resources.qwen_image_runtime
_res_pkg = types.ModuleType("resources")
_res_pkg.__path__ = [str(REF_ROOT / "resources")]
sys.modules["resources"] = _res_pkg
sys.modules["resources.qwen_image_runtime"] = ref_rt

ref_node = load_module(str(REF_NODE_FILE), "gh_qwen_prompt_node_ref")

# 本包：手工挂父包名，让相对导入正常工作（不执行包 __init__.py）
_pkg = types.ModuleType("qg_multipack_under_test")
_pkg.__path__ = [str(PKG_ROOT)]
sys.modules["qg_multipack_under_test"] = _pkg
ours_node = importlib.import_module("qg_multipack_under_test.qwen_prompt_optimizer_node")
ours_rt = sys.modules["qg_multipack_under_test.qwen_prompt_optimizer_runtime"]


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
    count = 0

    def check(name, cond, detail=""):
        nonlocal ok, count
        count += 1
        mark = "PASS" if cond else "FAIL"
        if not cond:
            ok = False
        print(f"[{mark}] {name}" + (f"  {detail}" if detail and not cond else ""))

    # ============ 1. system prompt 资产与组装结果 ============
    check("T2I_SYSTEM_PROMPT 逐字节一致", ours_rt.T2I_SYSTEM_PROMPT == ref_rt.T2I_SYSTEM_PROMPT)
    check("I2I_SYSTEM_PROMPT 逐字节一致", ours_rt.I2I_SYSTEM_PROMPT == ref_rt.I2I_SYSTEM_PROMPT)
    check("REVERSE_SYSTEM_PROMPT 逐字节一致", ours_rt.REVERSE_SYSTEM_PROMPT == ref_rt.REVERSE_SYSTEM_PROMPT)
    check("TRANSPARENT_PREFIX/SUFFIX 一致",
          ours_rt.TRANSPARENT_PREFIX == ref_rt.TRANSPARENT_PREFIX
          and ours_rt.TRANSPARENT_SUFFIX == ref_rt.TRANSPARENT_SUFFIX)
    check("UNLOAD_* 常量一致",
          all(getattr(ours_rt, k) == getattr(ref_rt, k)
              for k in ("UNLOAD_AUTO", "UNLOAD_KEEP", "UNLOAD_AFTER", "UNLOAD_BEFORE_AFTER")))
    check("DEFAULT_MAX_OUTPUT_TOKENS 一致",
          ours_rt.DEFAULT_MAX_OUTPUT_TOKENS == ref_rt.DEFAULT_MAX_OUTPUT_TOKENS)

    # ============ 2. _language_override_text 全量对照 ============
    langs = ["自动", "中文", "English", "其他"]
    prompts = ["一只猫", "a cat", "", "   ", "!!!", "猫 cat"]
    for lang in langs:
        for p in prompts:
            check(f"_language_override_text({lang!r},{p!r})",
                  ours_rt._language_override_text(lang, p) == ref_rt._language_override_text(lang, p))

    # ============ 3. _wrap_user_prompt_for_language 全量对照 ============
    for lang in ["自动", "中文", "English"]:
        for transparent in [False, True]:
            for image_count in [0, 1, 3]:
                for reverse in [False, True]:
                    a = ours_rt._wrap_user_prompt_for_language(
                        "白色背景下的产品图", lang, "白色背景下的产品图",
                        transparent_background=transparent,
                        image_count=image_count, reverse_mode=reverse)
                    b = ref_rt._wrap_user_prompt_for_language(
                        "白色背景下的产品图", lang, "白色背景下的产品图",
                        transparent_background=transparent,
                        image_count=image_count, reverse_mode=reverse)
                    check(f"_wrap(lang={lang},tp={transparent},n={image_count},rev={reverse})",
                          a == b)

    # ============ 4. _rewrite_language_rules 对照三个 system prompt ============
    for label, base in [("T2I", ours_rt.T2I_SYSTEM_PROMPT),
                        ("I2I", ours_rt.I2I_SYSTEM_PROMPT),
                        ("REVERSE", ours_rt.REVERSE_SYSTEM_PROMPT)]:
        for lang in ["自动", "中文", "English"]:
            for transparent in [False, True]:
                for reverse in [False, True]:
                    a = ours_rt._rewrite_language_rules(
                        base, lang, "一只猫", transparent_background=transparent,
                        reverse_mode=reverse)
                    b = ref_rt._rewrite_language_rules(
                        base, lang, "一只猫", transparent_background=transparent,
                        reverse_mode=reverse)
                    check(f"_rewrite_rules({label},{lang},tp={transparent},rev={reverse})",
                          a == b)

    # ============ 5. 透明背景改写全量对照 ============
    transparency_cases = [
        "把背景改为红色",
        "请将背景颜色换成蓝色",
        "a cat on a white background",
        "change the background to blue",
        # 回归（v0.1.1）：英文标点后还有内容时，target 必须停在标点处，
        # 否则整个后半句会被当成背景描述一起吞掉（P0-1）。
        "change the background to red, keep the subject unchanged",
        "Replace the background with blue. A cat sits on a chair",
        "产品照片，深色背景，保持白色背景的倒影，replace background with gray backdrop",
        "black backdrop with golden base",
        "背景是白色的，改为透明",  # 先有直述背景再改
        "no background words here",
        "",
    ]
    for text in transparency_cases:
        check(f"rewrite_user_prompt_for_transparency({text!r})",
              ours_rt.rewrite_user_prompt_for_transparency(text, True)
              == ref_rt.rewrite_user_prompt_for_transparency(text, True))
        check(f"rewrite_user_prompt_for_transparency(disabled, {text!r})",
              ours_rt.rewrite_user_prompt_for_transparency(text, False)
              == ref_rt.rewrite_user_prompt_for_transparency(text, False))
        check(f"_force_transparent_background_text({text!r})",
              ours_rt._force_transparent_background_text(text)
              == ref_rt._force_transparent_background_text(text))
        check(f"_remove_transparent_background_residue({text!r})",
              ours_rt._remove_transparent_background_residue(text)
              == ref_rt._remove_transparent_background_residue(text))

    # 绝对断言：不依赖参考源码，直接验证英文标点后的内容没有被吞掉。
    # 若两侧同时写错字符类，上面与参考的对拍仍会「零差异」，这条能兜住。
    for text, tail in [
        ("change the background to red, keep the subject unchanged",
         "keep the subject unchanged"),
        ("Replace the background with blue. A cat sits on a chair",
         "A cat sits on a chair"),
    ]:
        got = ours_rt.rewrite_user_prompt_for_transparency(text, True)
        check(f"英文标点后内容保留（绝对断言）{text!r}", tail in got, got)

    # ============ 6. 输出后处理对照 ============
    results = [
        {"rewritten_prompt": "a cat", "wh_ratio": "16:9"},
        {"rewritten_prompt": "一只猫", "wh_ratio": "1:1", "ratio_follow": "yes"},
        {"rewritten_prompt": "sky above, clouds", "wh_ratio": "4:3"},
    ]
    for i, r in enumerate(results):
        for tp in [False, True]:
            check(f"prompt_text_from_result#{i}(tp={tp})",
                  ours_rt.prompt_text_from_result(dict(r), tp)
                  == ref_rt.prompt_text_from_result(dict(r), tp))
            check(f"json_text_from_result#{i}(tp={tp})",
                  ours_rt.json_text_from_result(dict(r), tp)
                  == ref_rt.json_text_from_result(dict(r), tp))
    for tp in [False, True]:
        check(f"reverse_prompt_instruction(tp={tp})",
              ours_rt.reverse_prompt_instruction(tp) == ref_rt.reverse_prompt_instruction(tp))
    check("append_transparency 幂等去前缀",
          ours_rt.append_transparency(ours_rt.TRANSPARENT_PREFIX + "a cat" + ours_rt.TRANSPARENT_SUFFIX, True)
          == ref_rt.append_transparency(ref_rt.TRANSPARENT_PREFIX + "a cat" + ref_rt.TRANSPARENT_SUFFIX, True))

    # ============ 7. JSON 解析与规范化对照 ============
    parse_cases = [
        '{"rewritten_prompt":"a cat","wh_ratio":"16:9"}',
        '```json\n{"rewritten_prompt":"a cat","wh_ratio":"16:9"}\n```',
        '<think>reasoning</think>{"rewritten_prompt":"a cat","wh_ratio":"16:9"}',
        'junk before {"rewritten_prompt":"a cat","wh_ratio":"16:9"} junk after',
        '{"rewritten_prompt":"  spaced  ","wh_ratio":null}',
        '{"rewritten_prompt":"","wh_ratio":"1:1"}',
    ]
    for i, text in enumerate(parse_cases):
        def run(mod):
            try:
                return ("ok", mod._parse_json(text))
            except Exception as exc:
                return ("err", type(exc).__name__, str(exc))
        check(f"_parse_json#{i}", run(ours_rt) == run(ref_rt))

    for i, r in enumerate(results):
        for editing in [False, True]:
            check(f"_normalize_result#{i}(editing={editing})",
                  ours_rt._normalize_result(dict(r), editing) == ref_rt._normalize_result(dict(r), editing))
    for image_mode in [False, True]:
        check(f"_schema({image_mode})", ours_rt._schema(image_mode) == ref_rt._schema(image_mode))

    # ============ 8. collect_images 对照 ============
    def img(value, n=1):
        return torch.full((n, 8, 8, 3), value)

    empty = torch.zeros((0, 8, 8, 3))
    collect_cases = [
        {},
        {"图像_01": img(0.1)},
        {"图像_01": img(0.1), "图像_03": img(0.3, 2)},
        {"图像_03": img(0.3), "图像_01": img(0.1)},  # 乱序进、按序出
        {"image_02": img(0.2)},
        {"图像_01": empty},
        {"图像_01": img(0.1), "unrelated": img(0.9)},
        {"seed": 1, "图像_02": img(0.5)},
    ]
    for i, kwargs in enumerate(collect_cases):
        a = ours_rt.collect_images(dict(kwargs))
        b = ref_rt.collect_images(dict(kwargs))
        check(f"collect_images#{i}", tensors_equal(a, b) and len(a) == len(b))

    both_overflow = []
    for mod in (ours_rt, ref_rt):
        try:
            mod.collect_images({f"图像_{i:02d}": img(0.1) for i in range(1, 12)})
            both_overflow.append("no-error")
        except ValueError as exc:
            both_overflow.append(str(exc))
    check("collect_images 超过 10 张报错一致", both_overflow[0] == both_overflow[1], str(both_overflow))

    # ============ 9. _image_data_url 对照 ============
    small = torch.rand((8, 8, 3))
    check("_image_data_url 缩放路径一致",
          ours_rt._image_data_url(small, 4) == ref_rt._image_data_url(small, 4))
    check("_image_data_url 原尺寸路径一致",
          ours_rt._image_data_url(small, 64) == ref_rt._image_data_url(small, 64))

    # ============ 10. llama 安装辅助函数对照 ============
    for v in ["0.3.48", "0.3.47", "0.4.1", "", "abc", " 0.2.9"]:
        check(f"_version_tuple({v!r})",
              ours_node._version_tuple(v) == ref_node._version_tuple(v))
    check("_llama_install_target 一致（同机同 torch）",
          ours_node._llama_install_target() == ref_node._llama_install_target())

    def status_of(mod):
        s = mod._llama_dependency_status()
        s.pop("system", None)
        s.pop("machine", None)
        s.pop("python_tag", None)
        s.pop("backend", None)
        s.pop("cuda", None)
        s.pop("tag_marker", None)
        s.pop("wheel_suffix", None)
        return s
    check("_llama_dependency_status 核心字段一致",
          status_of(ours_node) == status_of(ref_node))

    # ============ 11. INPUT_TYPES 逐项对照 ============
    ours_it = ours_node.QG_QwenPromptOptimizer.INPUT_TYPES()
    ref_it = ref_node.QwenImagePromptOptimizer.INPUT_TYPES()
    for section in ("required", "optional", "hidden"):
        check(f"INPUT_TYPES.{section} 键一致",
              list(ours_it.get(section, {}).keys()) == list(ref_it.get(section, {}).keys()),
              f"{list(ours_it.get(section, {}).keys())} vs {list(ref_it.get(section, {}).keys())}")
    for key in ref_it["required"]:
        a, b = ours_it["required"][key], ref_it["required"][key]
        check(f"INPUT_TYPES.required[{key}] 一致", a == b, f"{a} vs {b}")
    check("RETURN_TYPES 一致",
          ours_node.QG_QwenPromptOptimizer.RETURN_TYPES == ref_node.QwenImagePromptOptimizer.RETURN_TYPES)
    check("RETURN_NAMES 一致",
          ours_node.QG_QwenPromptOptimizer.RETURN_NAMES == ref_node.QwenImagePromptOptimizer.RETURN_NAMES)
    check("IS_CHANGED 一致",
          ours_node.QG_QwenPromptOptimizer.IS_CHANGED(种子值=-5)
          == ref_node.QwenImagePromptOptimizer.IS_CHANGED(种子值=-5)
          and ours_node.QG_QwenPromptOptimizer.IS_CHANGED(种子值=2**40)
          == ref_node.QwenImagePromptOptimizer.IS_CHANGED(种子值=2**40))

    # ============ 12. optimize 场景矩阵（fake runtime 录制入参）============
    FAKE_RESULT = {"rewritten_prompt": "a fluffy cat", "wh_ratio": "16:9"}

    class FakeComplete:
        def __init__(self):
            self.calls = []

        def __call__(self, **kwargs):
            self.calls.append(kwargs)
            return dict(FAKE_RESULT)

    ours_fake, ref_fake = FakeComplete(), FakeComplete()
    ours_node.QwenImageRuntime.complete = ours_fake
    ref_node.QwenImageRuntime.complete = ref_fake

    img1 = img(0.7)
    scenarios = [
        # (名字, 位置参数字典)
        ("T2I：无图有提示词", dict(用户提示词="一只猫", 文生图模型=LLM_FILES[0],
                                图生图模型=LLM_FILES[1], 视觉模型=LLM_FILES[2],
                                输出语言="自动", 透明背景=False, 种子值=11111)),
        ("T2I：无图空提示词", dict(用户提示词="", 文生图模型=LLM_FILES[0],
                                图生图模型=LLM_FILES[1], 视觉模型=LLM_FILES[2],
                                输出语言="自动", 透明背景=False, 种子值=0)),
        ("反推：1 图空提示词", dict(用户提示词="", 文生图模型=LLM_FILES[0],
                                图生图模型=LLM_FILES[1], 视觉模型=LLM_FILES[2],
                                输出语言="自动", 透明背景=False, 种子值=7,
                                图像_01=img1)),
        ("I2I：1 图有提示词", dict(用户提示词="改成夜晚", 文生图模型=LLM_FILES[0],
                                图生图模型=LLM_FILES[1], 视觉模型=LLM_FILES[2],
                                输出语言="中文", 透明背景=False, 种子值=2**32 - 1,
                                图像_01=img1)),
        ("透明背景 + T2I", dict(用户提示词="白色背景的产品", 文生图模型=LLM_FILES[0],
                              图生图模型=LLM_FILES[1], 视觉模型=LLM_FILES[2],
                              输出语言="English", 透明背景=True, 种子值=5)),
        ("透明背景 + 反推", dict(用户提示词="  ", 文生图模型=LLM_FILES[0],
                              图生图模型=LLM_FILES[1], 视觉模型=LLM_FILES[2],
                              输出语言="自动", 透明背景=True, 种子值=5,
                              图像_01=img1)),
        ("种子越界夹取", dict(用户提示词="cat", 文生图模型=LLM_FILES[0],
                           图生图模型=LLM_FILES[1], 视觉模型=LLM_FILES[2],
                           输出语言="自动", 透明背景=False, 种子值=-100)),
        ("卸载模型字符串", dict(用户提示词="cat", 文生图模型=LLM_FILES[0],
                             图生图模型=LLM_FILES[1], 视觉模型=LLM_FILES[2],
                             输出语言="自动", 透明背景=False, 种子值=1,
                             种子模式="随机", 卸载模型="运行前后自动卸载")),
        ("卸载模型 bool 兼容", dict(用户提示词="cat", 文生图模型=LLM_FILES[0],
                                图生图模型=LLM_FILES[1], 视觉模型=LLM_FILES[2],
                                输出语言="自动", 透明背景=False, 种子值=1,
                                卸载模型=False)),
    ]

    class RefNodeStub:
        """参考节点 optimize 的关键字形态包装（hidden unique_id 可省）。"""
        QwenImageRuntime = ref_node.QwenImageRuntime

    for name, kwargs in scenarios:
        kwargs = dict(kwargs)
        images_in = {k: kwargs.pop(k) for k in list(kwargs) if k.startswith("图像_")}
        a = ours_node.QG_QwenPromptOptimizer().optimize(**kwargs, **images_in)
        b = ref_node.QwenImagePromptOptimizer().optimize(**kwargs, **images_in)
        ca, cb = ours_fake.calls[-1], ref_fake.calls[-1]
        same_call = tensors_equal(ca, cb)
        same_out = tensors_equal(a["result"], b["result"]) and \
            tensors_equal(a["ui"], b["ui"])
        check(f"optimize {name}", same_call and same_out,
              "" if same_call and same_out else f"call_equal={same_call} out_equal={same_out}")

    # 覆盖位置默认参数路径（种子模式/卸载模型省略）
    base = dict(用户提示词="dog", 文生图模型=LLM_FILES[0], 图生图模型=LLM_FILES[1],
                视觉模型=LLM_FILES[2], 输出语言="自动", 透明背景=False, 种子值=9)
    ours_node.QG_QwenPromptOptimizer().optimize(**base)
    ref_node.QwenImagePromptOptimizer().optimize(**base)
    check("optimize 省略可选参数调用一致",
          tensors_equal(ours_fake.calls[-1], ref_fake.calls[-1]))

    # complete 收到的 system prompt 是「对应常量经 _rewrite_language_rules
    # 追加语言锁」后的结果（裸常量相等已由第 1 组验证、入参一致由第 12 组验证）
    rev_call = [c for c in ours_fake.calls if c.get("reverse_mode")]
    check("反推场景收到 REVERSE system prompt（加语言锁）",
          bool(rev_call) and rev_call[0]["system_prompt"] == ours_rt._rewrite_language_rules(
              ours_rt.REVERSE_SYSTEM_PROMPT, "自动", "",
              transparent_background=False, reverse_mode=True))
    i2i_call = [c for c in ours_fake.calls if c.get("prompt_mode") == "I2I"]
    check("I2I 场景收到 I2I system prompt（加语言锁）",
          bool(i2i_call) and i2i_call[0]["system_prompt"] == ours_rt._rewrite_language_rules(
              ours_rt.I2I_SYSTEM_PROMPT, "中文", "改成夜晚",
              transparent_background=False, reverse_mode=False))
    check("T2I 场景收到 T2I system prompt（加语言锁）",
          ours_fake.calls[0]["system_prompt"] == ours_rt._rewrite_language_rules(
              ours_rt.T2I_SYSTEM_PROMPT, "自动", "一只猫",
              transparent_background=False, reverse_mode=False))

    # 13. 路由注册形态（stub 环境下装饰器直接通过，函数存在即可）
    check("本包状态接口函数存在", callable(getattr(ours_node, "qg_qwen_llama_status", None)))
    check("本包安装接口函数存在", callable(getattr(ours_node, "qg_qwen_install_llama", None)))
    check("参考状态接口函数存在", callable(getattr(ref_node, "qwen_image_llama_status", None)))

    print()
    print(f"合计 {count} 项，通过 {count if ok else '部分'}"
          if ok else f"存在失败项！合计 {count} 项")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
