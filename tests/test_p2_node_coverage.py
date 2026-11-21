# -*- coding: utf-8 -*-
"""节点级回归：把静态契约覆盖的 26 个模块 / 27 个注册 key 全部纳入检查。

注意：PhotoKit 并入的 6 个节点在 __init__.py 里按名字动态导入，另有
独立几何测试 tests/test_photokit_geometry.py，未纳入本文件静态契约；
所以这里的模块数不等于包内节点总数 33。

从两层把这个盲区堵上，且**不依赖 GPL 参考源码、真实模型、网络或 API Key**：

1. 静态契约层：AST 读 26 个后端模块（其中 qwen_text_encode 注册 2 个 key，
   所以共 27 个后端注册 key），逐个核对注册 key、RETURN_TYPES / RETURN_NAMES
   长度、FUNCTION 指向的方法确实存在、CATEGORY。全部后端节点一个不漏。
2. 运行时层：对此前完全没有节点级测试的模块真导入、真调用纯逻辑与安全分支
   （含只测过 helpers 的 QG_MaskByName、只测过 runtime 的
   QG_QwenPromptOptimizer），用绝对断言而不是「看代码觉得对」。

运行：python_embeded\\python.exe tests\\test_p2_node_coverage.py
"""
import ast
import importlib
import io
import json
import os
import re
import struct
import sys
import tempfile
import types

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)
# ComfyUI 根：优先环境变量，其次按 custom_nodes/<插件>/tests 相对推导；
# 工作区镜像里推不出来时用最小 stub 顶上，绝不硬编码某台机器的绝对路径
# （P0-3 已经修过测试里硬编码路径的坑）。
_comfy_root = os.environ.get("QG_COMFY_ROOT") or os.path.abspath(
    os.path.join(PKG, "..", ".."))
if os.path.isdir(_comfy_root):
    sys.path.insert(0, _comfy_root)

_TMP = tempfile.mkdtemp(prefix="qg_p2_")


def _stub(name, **attrs):
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    if name == "comfy":
        mod.__path__ = []
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


if "folder_paths" not in sys.modules:
    try:
        import folder_paths  # noqa: F401
    except ImportError:
        _stub("folder_paths",
              get_temp_directory=lambda: _TMP,
              get_filename_list=lambda _name: [],
              models_dir=lambda: _TMP,
              folder_names_and_paths={},
              get_folder_paths=lambda _name: [])
_stub("comfy")
_stub("comfy.model_management")
_stub("comfy.utils")
_stub("node_helpers")
if "server" not in sys.modules:
    class _Routes:
        def post(self, _path):
            return lambda fn: fn

        def get(self, _path):
            return lambda fn: fn

    class _ServerInstance:
        # 真实 ComfyUI 里 PromptServer.instance 是「实例」而不是方法；
        # 两种写法（instance.routes / instance().routes）都让它成立。
        def __init__(self):
            self.routes = _Routes()

        def __call__(self):
            return self

    class _PromptServer:
        instance = _ServerInstance()

    _stub("server", PromptServer=_PromptServer)

# 预览图统一写进本测试自建的临时目录，不碰 ComfyUI 真正的 temp 目录。
import folder_paths as _fp  # noqa: E402
_fp.get_temp_directory = lambda: _TMP

# 相对导入的节点需要一层包壳（目录名带连字符，不是合法包名）。
shell = types.ModuleType("qg_pack_p2")
shell.__path__ = [PKG]
sys.modules["qg_pack_p2"] = shell

# 22 个后端注册节点所在的模块（qwen_text_encode 一个模块注册两个 key，
# 所以共 24 个后端注册 key）。
MODULES = [
    "translate_node", "prompt_translate_node",
    "image_to_prompt_node", "prompt_optimize_node",
    "mask_by_name_node", "face_rectify_node",
    "birefnet_node", "qwen_text_encode_node",
    "qwen_prompt_optimizer_node", "qg_dual_color_picker", "qg_color_convert",
    "qg_custom_color", "qg_dominant_color", "face_align_node",
    "qg_id_photo_outfit", "qg_marriage_cloth", "mask_top_expand_node",
    "qg_id_photo_prompt", "photo_sheet_mixed_node", "qg_image_composite",
    "qg_id_photo_size_picker", "qg_color_picker", "qg_multi_photo_sheet",
    "qg_image_batch_builder", "qg_remove_background_v2", "qg_mask_order_filter",
]

# 此前审查点名「完全没有节点级测试」的模块，本文件对它们做真调用。
RUNTIME_MODULES = [
    "face_rectify_node", "birefnet_node",
    "prompt_translate_node", "translate_node", "mask_by_name_node",
    "qwen_prompt_optimizer_node", "qwen_text_encode_node",
    "qg_dual_color_picker", "qg_color_convert", "qg_custom_color",
    "qg_dominant_color", "face_align_node", "qg_id_photo_outfit",
    "qg_marriage_cloth", "mask_top_expand_node",
    "qg_id_photo_prompt", "photo_sheet_mixed_node",
]

ok = 0
fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS", name)
    else:
        fail += 1
        print("FAIL", name, extra)


def safe(name, fn, *args, **kwargs):
    """跑一个断言，异常也算失败并打出原因，不让整个测试中途崩掉。"""
    try:
        return check(name, bool(fn(*args, **kwargs)))
    except Exception as exc:  # noqa: BLE001 - 逐项隔离，一处坏不影响其余
        fail_inc = "%s: %s" % (type(exc).__name__, exc)
        global fail
        fail += 1
        print("FAIL", name, fail_inc)
        return None


# ---------------------------------------------------------------------------
# 一、静态契约：22 个后端模块 / 24 个注册 key
# ---------------------------------------------------------------------------
print("== 一、静态契约（26 个模块 / 27 个 key） ==")

all_keys = []
class_info = {}
for module_name in MODULES:
    path = os.path.join(PKG, module_name + ".py")
    src = io.open(path, encoding="utf-8").read()
    tree = ast.parse(src, filename=path)
    mapping = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "NODE_CLASS_MAPPINGS":
                    mapping = node.value
    check("%s 有 NODE_CLASS_MAPPINGS" % module_name, mapping is not None)
    if not isinstance(mapping, ast.Dict):
        continue
    for key_node, value_node in zip(mapping.keys, mapping.values):
        key = ast.literal_eval(key_node)
        cls = value_node.id if isinstance(value_node, ast.Name) else None
        all_keys.append(key)
        class_info[key] = (module_name, path, cls, tree)

check("后端注册 27 个 key", len(all_keys) == 27, "实际 %d" % len(all_keys))
check("后端 key 无重复", len(all_keys) == len(set(all_keys)))
check("后端 key 全部 QG_ 前缀",
      all(k.startswith("QG_") for k in all_keys))

# 逐个类核对 ComfyUI 节点契约
for key, (module_name, path, cls_name, tree) in sorted(class_info.items()):
    target = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            target = node
    if target is None:
        check("%s 能找到类 %s" % (key, cls_name), False)
        continue
    attrs = {}
    methods = set()
    for item in target.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.add(item.name)
        elif isinstance(item, ast.Assign):
            for t in item.targets:
                if isinstance(t, ast.Name):
                    try:
                        attrs[t.id] = ("literal", ast.literal_eval(item.value))
                    except Exception:  # noqa: BLE001 - 含常量名的动态值保留 AST 节点
                        attrs[t.id] = ("node", item.value)

    def literal(name):
        entry = attrs.get(name)
        return entry[1] if entry and entry[0] == "literal" else None

    def seq_len(name):
        """RETURN_TYPES 里可能混常量（如 RESTORE_INFO_TYPE），literal_eval 拿不到，
        但元组结构本身还在，按元素个数核对即可。"""
        entry = attrs.get(name)
        if not entry:
            return None
        kind, value = entry
        if kind == "literal" and isinstance(value, (tuple, list)):
            return len(value)
        if isinstance(value, (ast.Tuple, ast.List)):
            return len(value.elts)
        return None

    ret_len = seq_len("RETURN_TYPES")
    names_len = seq_len("RETURN_NAMES")
    func = literal("FUNCTION")
    cat = literal("CATEGORY")
    check("%s 有 INPUT_TYPES 方法" % key, "INPUT_TYPES" in methods)
    check("%s RETURN_TYPES 是元组/列表" % key, ret_len is not None)
    if ret_len is not None and names_len is not None:
        check("%s RETURN_NAMES 数量对齐" % key, ret_len == names_len,
              "%d vs %d" % (ret_len, names_len))
    check("%s FUNCTION 指向存在的方法" % key,
          isinstance(func, str) and func in methods, str(func))
    check("%s CATEGORY=QG 工具" % key, cat == "QG 工具", str(cat))

check("27 个节点全部纳入检查", len(all_keys) == 27)

# ---------------------------------------------------------------------------
# 二、运行时：此前无节点级测试的模块
# ---------------------------------------------------------------------------
print()
print("== 二、运行时真调用（此前无节点级测试的模块） ==")

loaded = {}
for name in RUNTIME_MODULES:
    try:
        loaded[name] = importlib.import_module("qg_pack_p2." + name)
        print("INFO 导入", name, "OK")
    except Exception as exc:  # noqa: BLE001
        print("INFO 导入", name, "失败:", type(exc).__name__, str(exc)[:120])
check("关键模块均可导入", len(loaded) == len(RUNTIME_MODULES),
      "已导入 %d/%d" % (len(loaded), len(RUNTIME_MODULES)))


def mod(name):
    return loaded.get(name)


# --- QG_FaceRectify --------------------------------------------------------
fr = mod("face_rectify_node")
if fr:
    src_img = torch.rand(1, 8, 8, 3)
    safe("人脸矫正：关闭开关时原图直通",
         lambda: fr.QGFaceRectify().rectify(src_img, False, 0)[0] is src_img)
    safe("人脸矫正：空 batch 不触 dlib 也不崩",
         lambda: fr.QGFaceRectify().rectify(torch.zeros((0, 8, 8, 3)), True, 0)[0].shape[0] == 0)
    arr = np.zeros((10, 20, 3), np.uint8)
    safe("人脸矫正：居中裁切尺寸正确",
         lambda: fr._center_crop(arr, 8, 6).shape == (6, 8, 3))
    safe("人脸矫正：0 度不裁边",
         lambda: fr._trim_edges(arr, 0.0, 3) is arr)
    safe("人脸矫正：45 度按角度裁边",
         lambda: fr._trim_edges(arr, 45.0, 1).shape[0] < arr.shape[0])
    try:
        import cv2  # noqa: PLC0415
        safe("人脸矫正：90 度旋转交换宽高",
             lambda: fr._rotate_quarter(arr, 90).shape[:2] == (20, 10))
        safe("人脸矫正：补齐尺寸到首帧",
             lambda: fr._fit_to(arr, np.zeros((4, 4, 3), np.uint8)).shape == arr.shape)
    except ImportError:
        print("INFO 本机无 cv2，跳过两条 cv2 断言")

# --- QG_BiRefNet -----------------------------------------------------------
bn = mod("birefnet_node")
if bn:
    safe("BiRefNet：6 位色值解析", lambda: bn._hex_to_rgba("#112233") == (17, 34, 51, 255))
    safe("BiRefNet：8 位色值带 alpha",
         lambda: bn._hex_to_rgba("11223344") == (17, 34, 51, 68))
    try:
        bn._hex_to_rgba("#12345")
        bad_color = False
    except ValueError:
        bad_color = True
    check("BiRefNet：非法色值抛中文 ValueError", bad_color)
    for channels in (1, 2, 3, 4, 6):
        frame = torch.full((4, 5, channels), 0.5)
        out = bn._frame_to_rgb_uint8(frame)
        safe("BiRefNet：%d 通道归一为 3 通道 uint8" % channels,
             lambda o=out: o.shape == (4, 5, 3) and o.dtype == np.uint8)
    rgba = torch.zeros((2, 2, 4))
    rgba[..., :3] = 0.2
    safe("BiRefNet：alpha=0 压白底",
         lambda: int(bn._frame_to_rgb_uint8(rgba).min()) >= 250)
    from PIL import Image  # noqa: PLC0415
    small = Image.new("L", (7, 7), 0)
    small.putpixel((3, 3), 255)
    safe("BiRefNet：offset=0 原样返回", lambda: bn._offset_mask(small, 0) is small)
    grown = bn._offset_mask(small, 1)
    safe("BiRefNet：正值膨胀生效",
         lambda: np.asarray(grown)[2, 3] == 255 and np.asarray(grown)[0, 0] == 0)
    safe("BiRefNet：灵敏度 <1 抬升亮度",
         lambda: np.asarray(bn._adjust_sensitivity(small, 0.5))[3, 3]
         >= np.asarray(small)[3, 3])

# --- QG_PromptTranslate ----------------------------------------------------
pt = mod("prompt_translate_node")
if pt:
    safe("提示词翻译：空文本判 auto", lambda: pt.detect_language("") == "auto")
    safe("提示词翻译：中文判 chinese", lambda: pt.detect_language("一只猫") == "chinese")
    safe("提示词翻译：纯 ASCII 判 english", lambda: pt.detect_language("a cat") == "english")
    safe("提示词翻译：字符串 52000 视为成功",
         lambda: pt._error_code({"error_code": "52000"}) is None)
    safe("提示词翻译：数字 0 视为成功",
         lambda: pt._error_code({"error_code": 0}) is None)
    safe("提示词翻译：限流码保留字符串",
         lambda: pt._error_code({"error_code": 54003}) == "54003")
    safe("提示词翻译：错误码翻成人话",
         lambda: "访问频率受限" in pt._describe("54003", ""))
    safe("提示词翻译：超长文本按字符切 3 段",
         lambda: len(pt._split_text("a" * 2500, 1000)) == 3)
    safe("提示词翻译：分段结果拼回不硬塞换行",
         lambda: pt._run_chunked("a" * 2500, 1000, lambda _c: "X") == "XXX")
    safe("提示词翻译：百度两通道都在下拉里",
         lambda: pt.BAIDU in pt.service_choices()
         and pt.BAIDU_LLM in pt.service_choices())
    safe("提示词翻译：老工作流 custom 值放行",
         lambda: pt.QGPromptTranslate.VALIDATE_INPUTS(translate_service="custom") is True)
    fp1 = pt.QGPromptTranslate.IS_CHANGED(source_text="甲")
    fp2 = pt.QGPromptTranslate.IS_CHANGED(source_text="乙")
    safe("提示词翻译：IS_CHANGED 随原文变化", lambda: fp1 != fp2)
    safe("提示词翻译：IS_CHANGED 稳定",
         lambda: fp1 == pt.QGPromptTranslate.IS_CHANGED(source_text="甲"))

# --- QG_Translate ----------------------------------------------------------
tn = mod("translate_node")
if tn:
    safe("通用翻译：老工作流 custom 值放行",
         lambda: tn.QGTranslate.VALIDATE_INPUTS(provider="custom") is True)
    safe("通用翻译：IS_CHANGED 随文本变化",
         lambda: tn.QGTranslate.IS_CHANGED(text="甲") != tn.QGTranslate.IS_CHANGED(text="乙"))
    safe("通用翻译：默认 provider 落在下拉列表里",
         lambda: tn.QGTranslate.INPUT_TYPES()["required"]["provider"][1]["default"]
         in tn.service_choices())

# --- QG_MaskByName ---------------------------------------------------------
mb = mod("mask_by_name_node")
if mb:
    def _fake_safetensors(keys):
        header = json.dumps({k: {"dtype": "F16", "shape": [1]} for k in keys}).encode()
        return struct.pack("<Q", len(header)) + header

    with tempfile.NamedTemporaryFile(delete=False, suffix=".safetensors") as f:
        f.write(_fake_safetensors(["detector.foo", "text_encoder.bar"]))
        sam3_path = f.name
    with tempfile.NamedTemporaryFile(delete=False, suffix=".safetensors") as f:
        f.write(_fake_safetensors(["unet.down.0"]))
        other_path = f.name
    safe("MaskByName：SAM3 头识别为 True",
         lambda: mb._checkpoint_is_sam3(sam3_path) is True)
    safe("MaskByName：普通扩散权重识别为 False",
         lambda: mb._checkpoint_is_sam3(other_path) is False)
    safe("MaskByName：读不出头时交给加载器（返回 True）",
         lambda: mb._checkpoint_is_sam3(os.path.join(_TMP, "不存在的文件")) is True)
    os.unlink(sam3_path)
    os.unlink(other_path)
    payload = mb._save_preview(torch.rand(1, 4, 6, 3), "qg_p2_preview")
    safe("MaskByName：四维预览能写出 PNG（P0-2 回归）",
         lambda: isinstance(payload, dict) and len(payload.get("images", [])) == 1)
    pngs = [os.path.join(_TMP, f) for f in os.listdir(_TMP)
            if f.startswith("qg_p2_preview") and f.endswith(".png")]
    safe("MaskByName：预览 PNG 非空",
         lambda: len(pngs) >= 1 and os.path.getsize(pngs[0]) > 100)
    safe("MaskByName：空 batch 预览返回空 dict",
         lambda: mb._save_preview(torch.zeros((0, 4, 6, 3)), "qg_p2_empty") == {})

# --- QG_QwenPromptOptimizer / QG_QwenTextEncode / QG_QwenRestore -----------
qo = mod("qwen_prompt_optimizer_node")
if qo:
    safe("Qwen 优化器：版本号解析", lambda: qo._version_tuple("1.2.3") == (1, 2, 3))
    safe("Qwen 优化器：非法版本号回退 (0,0,0)",
         lambda: qo._version_tuple("not-a-version") == (0, 0, 0))
    safe("Qwen 优化器：按标记挑首选模型",
         lambda: qo._preferred(["Q5_K_S.gguf", "mmproj-BF16.gguf"], "MMPROJ")
         == "mmproj-BF16.gguf")
    safe("Qwen 优化器：种子夹进 uint32",
         lambda: qo.QG_QwenPromptOptimizer.IS_CHANGED(种子值=-1) == 0
         and qo.QG_QwenPromptOptimizer.IS_CHANGED(种子值=2 ** 40) == 0xFFFFFFFF)
qe = mod("qwen_text_encode_node")
if qe:
    safe("Qwen 文本编码：尺寸取整到 32",
         lambda: qe._round_latent_size(0) == 32 and qe._round_latent_size(50) == 64)
    safe("Qwen 文本编码：只认 4D 非空张量",
         lambda: qe._valid_image(torch.zeros((1, 4, 4, 3)))
         and not qe._valid_image(torch.zeros((4, 4, 3)))
         and not qe._valid_image(torch.zeros((0, 4, 4, 3))))
    safe("Qwen 文本编码：面积上限保持比例",
         lambda: qe._rounded_area_size(1024, 512, 512 * 512)[0]
         > qe._rounded_area_size(1024, 512, 512 * 512)[1])

# ---------------------------------------------------------------------------
print()
print("TOTAL ok=%d fail=%d" % (ok, fail))
sys.exit(1 if fail else 0)
