# QG-Multipack —— 多合一插件（旧名 0-QYH-SnapLines，界面品牌为「QG 工具」）
#   · 前端：翻译服务商设置面板（web/qg_translate.js）
#   · 后端：LLM 翻译节点（translate_node.py，注册 key 仍为 QG_Translate）
#           + 服务商配置/连通测试接口（/qg_translate/*）
#   · 后端：提示词翻译节点（prompt_translate_node.py，注册 key
#           QG_PromptTranslate，原文进、译好的提示词出，带百度翻译通道）
#   · 后端：图像反推提示词节点（image_to_prompt_node.py，注册 key
#           QG_ImageToPrompt，图片进、提示词出，支持 batch 逐帧）
#   · 后端：提示词优化节点（prompt_optimize_node.py，注册 key
#           QG_PromptOptimize，原文进、优化后的提示词出，规则取 optimize 组）
#   · 后端：文字取蒙版节点（mask_by_name_node.py + mask_by_name_helpers.py，
#           注册 key 仍为 QG_MaskByName，原独立包 ComfyUI-QG-MaskByName 并入）
#   · 后端：人脸自动矫正节点（face_rectify_node.py，注册 key QG_FaceRectify，
#           dlib + 5 点 landmark 模型 shape_predictor_5_face_landmarks.dat）
#   · 后端：BiRefNet 去除背景节点（birefnet_node.py，注册 key QG_BiRefNet，
#           模型缓存与 ComfyUI-RMBG 共享 models/RMBG/BiRefNet/）
#           多行文本按行拆列表，前端按钮可抄下游 COMBO 下拉的全部选项
#   · 后端：Qwen Image 2.1 文本编码 + 还原画布节点（qwen_text_encode_node.py，
#           注册 key QG_QwenTextEncode / QG_QwenRestore，image 口动态增减
#           web/qg_qwen_text_encode.js）
#   · 后端：Qwen image 2.1 提示词优化节点（qwen_prompt_optimizer_node.py，
#           注册 key QG_QwenPromptOptimizer，本地 llama-cpp 反推/优化提示词，
#           运行时 qwen_prompt_optimizer_runtime.py + 三个 system prompt 资产，
#           llama-cpp 缺失时节点内按钮自动安装 web/qg_qwen_prompt_optimizer.js）
#   · 后端：证件照参数节点（id_photo_params_node.py，注册 key QG_IDPhotoParams，
#           尺寸/底色/渲染/dpi 一路传递）
#   · 后端：人像抠图换背景节点（portrait_matte_node.py，注册 key QG_PortraitMatte，
#           抠图/换底/美颜/按证件照构图裁好）
#   · 后端：证件照裁剪节点（id_photo_crop_node.py，注册 key QG_IDPhotoCrop，
#           把已有照片裁成指定尺寸、眼睛摆平）
#   · 后端：照片排版节点（photo_sheet_node.py，注册 key QG_PhotoSheet，
#           铺满相纸/画裁切角标/放不下自动缩）
#   · 后端：身份证拼版节点（id_card_sheet_node.py，注册 key QG_IDCardSheet，
#           找四角扶正/铺到纸上；参考 Goohaitools 重写）
#   · 后端：斜向水印节点（watermark_node.py，注册 key QG_Watermark，斜向平铺文字水印）
#   · 后端：主色提取节点（qg_dominant_color.py，注册 key QG_DominantColor，
#           图片进、主色 #RRGGBB 出，降采样+滤边+容差分桶）
#   · 后端：面部对齐节点（face_align_node.py，注册 key QG_FaceAlign，
#           目标图人脸按参考图缩放旋转对齐，无参考图时仅摆平角度）
#   · 后端：证件照服装发型节点（qg_id_photo_outfit.py，注册 key QG_IDPhotoOutfit，
#           扫描 models/id_photo/ 自备素材，前端网格选模板出提示词）
#   · 后端：遮罩次序过滤节点（qg_mask_order_filter.py，注册 key QG_MaskOrderFilter，
#           参考 Goohaitools「Seg次序过滤」规格独立实现，只吃/出 MASK，不依赖 SEGS）
#   · 后端：简易 Seg 检测三件套（qg_yolo_detector_loader.py / qg_sam_model_loader.py
#           / qg_simple_seg_detector.py，注册 key QG_YoloDetectorLoader /
#           QG_SamModelLoader / QG_SimpleSegDetector，自造类型 QG_YOLO_DETECTOR /
#           QG_SAM_MODEL / QG_SEGS，只用 ultralytics + segment_anything，不依赖 Impact）
#   · 后端：遮罩到 Seg 节点（qg_mask_to_seg.py，注册 key QG_MaskToSeg，
#           把 MASK 连通域转成自造 QG_SEGS，参考 Impact MaskToSeg 规格独立实现）
#   · 后端：图像与遮罩预览（qg_image_mask_preview.py，注册 key QG_ImageMaskPreview，
#           遮罩区域上色 + 按帧序号，参考 Goohaitools 规格独立实现，颜色走本包色块）

# 版本号单一真源是插件根目录的 VERSION 文件；每次改完节点用工作区的
# 打包备份.py --bump patch|minor|major 递增，并同步打包到 D:\插件开发。
__version__ = "2.22.13"

import asyncio
import time

from . import prompt_rules as _rules_lib
from . import translate_core as _translate_core


NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

# LLM 翻译节点（外壳）：翻译核心与配置在 translate_core.py。删掉
# translate_node.py 只会少这一个节点，设置面板与提示词翻译照常工作，
# 所以这里的导入失败也不该拖垮整个包。
try:
    from . import translate_node as _translate

    NODE_CLASS_MAPPINGS.update(_translate.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_translate.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] LLM 翻译节点导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")

# 提示词翻译：复用上面的服务商列表，单独 try/except
try:
    from . import prompt_translate_node as _prompt_translate

    NODE_CLASS_MAPPINGS.update(_prompt_translate.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_prompt_translate.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] 提示词翻译节点导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")

# 图像反推提示词：同样复用 translate_core 的服务商配置，单独 try/except。
# 它依赖 numpy/Pillow（ComfyUI 自带），缺失时也只少这一个节点。
try:
    from . import image_to_prompt_node as _img2prompt

    NODE_CLASS_MAPPINGS.update(_img2prompt.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_img2prompt.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] 图像反推提示词节点导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")

# 提示词优化：纯文本进、纯文本出。复用反推节点的 HTTP/流式层与 translate_core
# 的服务商配置，所以它依赖 image_to_prompt_node 能导入成功——单独 try/except
# 保证即使那边挂了，其余节点照常。
try:
    from . import prompt_optimize_node as _optimize

    NODE_CLASS_MAPPINGS.update(_optimize.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_optimize.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] 提示词优化节点导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")

# 文字取蒙版：单独 try/except，导入失败（如 torch 异常）不拖垮整个包
try:
    from . import mask_by_name_node as _mask

    NODE_CLASS_MAPPINGS.update(_mask.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_mask.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] 文字取蒙版节点导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")

# 人脸自动矫正：单独 try/except（dlib 缺失时不拖垮整个包）
try:
    from . import face_rectify_node as _facerect

    NODE_CLASS_MAPPINGS.update(_facerect.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_facerect.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] 人脸自动矫正节点导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")

# BiRefNet 去除背景：单独 try/except，导入失败不拖垮整个包
try:
    from . import birefnet_node as _birefnet

    NODE_CLASS_MAPPINGS.update(_birefnet.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_birefnet.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] BiRefNet 去除背景节点导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")

# Qwen Image 2.1 文本编码 + 还原画布：依赖 torch/cv2/comfy，单独 try/except，
# 导入失败不拖垮整个包
try:
    from . import qwen_text_encode_node as _qwentext

    NODE_CLASS_MAPPINGS.update(_qwentext.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_qwentext.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] Qwen Image 2.1 文本编码节点导入失败（上面的 traceback "
          "是原因），其余节点不受影响。")

# Qwen Image 2.1 提示词优化：依赖 llama-cpp-python（缺失时运行期报错引导
# 自动安装，导入本身不失败）与 torch/numpy/PIL，单独 try/except 不拖垮整个包
try:
    from . import qwen_prompt_optimizer_node as _qwenprompt

    NODE_CLASS_MAPPINGS.update(_qwenprompt.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_qwenprompt.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] Qwen image 2.1 提示词优化节点导入失败（上面的 traceback "
          "是原因），其余节点不受影响。")

# 证件照 / 排版 / 拼版 / 水印（自 ComfyUI-PhotoKit 并入，2026-11-09）：
# 六个节点共享七个 _ 开头的辅助模块，必须和节点一起放在包根。任一节点导入
# 失败只丢那一个，其余照常注册。依赖都是可选的（onnxruntime/mediapipe/opencv/
# scipy），缺哪个就少哪条能力，节点本身不会消失。
from importlib import import_module as _import_module

for _pk_mod, _pk_label in (
    ("id_photo_params_node", "证件照参数"),
    ("portrait_matte_node", "人像抠图换背景"),
    ("id_photo_crop_node", "证件照裁剪"),
    ("photo_sheet_node", "照片排版"),
    ("id_card_sheet_node", "身份证拼版"),
    ("watermark_node", "斜向水印"),
):
    try:
        _m = _import_module("." + _pk_mod, __package__ or __name__)
        NODE_CLASS_MAPPINGS.update(_m.NODE_CLASS_MAPPINGS)
        NODE_DISPLAY_NAME_MAPPINGS.update(_m.NODE_DISPLAY_NAME_MAPPINGS)
    except Exception:
        import traceback

        traceback.print_exc()
        print("[QG-Multipack] %s（%s）导入失败，其余节点不受影响。"
              % (_pk_label, _pk_mod))

# QG 双色取色器：纯字符串节点，无第三方依赖，单独 try/except。
try:
    from . import qg_dual_color_picker as _dual_color

    NODE_CLASS_MAPPINGS.update(_dual_color.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_dual_color.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 双色取色器导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")

# QG 颜色转换：纯字符串节点，无第三方依赖，单独 try/except。
try:
    from . import qg_color_convert as _color_convert

    NODE_CLASS_MAPPINGS.update(_color_convert.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_color_convert.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 颜色转换导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")

# QG 自定义颜色：图像生成节点（依赖 torch/numpy，ComfyUI 环境必有），单独 try/except。
try:
    from . import qg_custom_color as _custom_color

    NODE_CLASS_MAPPINGS.update(_custom_color.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_custom_color.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 自定义颜色导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")


# QG 主色提取：图像统计节点（依赖 torch/numpy/PIL，ComfyUI 环境必有），单独 try/except。
try:
    from . import qg_dominant_color as _dominant_color

    NODE_CLASS_MAPPINGS.update(_dominant_color.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_dominant_color.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 主色提取导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")


# QG 面部对齐：人脸检测复用 _face_helpers（mediapipe/Haar 可选依赖），单独 try/except。
try:
    from . import face_align_node as _face_align

    NODE_CLASS_MAPPINGS.update(_face_align.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_face_align.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 面部对齐导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")

# 证件照服装发型：qg_id_photo_outfit.py（注册 key QG_IDPhotoOutfit）
try:
    from . import qg_id_photo_outfit as _id_photo_outfit

    NODE_CLASS_MAPPINGS.update(_id_photo_outfit.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_id_photo_outfit.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 证件照服装发型导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")


# 结婚登记照服装：qg_marriage_cloth.py（注册 key QG_MarriageCloth）
try:
    from . import qg_marriage_cloth as _marriage_cloth

    NODE_CLASS_MAPPINGS.update(_marriage_cloth.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_marriage_cloth.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 结婚登记照服装导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")


# 头顶遮罩扩展：mask_top_expand_node.py（注册 key QG_MaskTopExpand）
try:
    from . import mask_top_expand_node as _mask_top

    NODE_CLASS_MAPPINGS.update(_mask_top.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_mask_top.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 头顶遮罩扩展导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")


# 证件照简易提示词：qg_id_photo_prompt.py（注册 key QG_IDPhotoPrompt）
try:
    from . import qg_id_photo_prompt as _id_photo_prompt

    NODE_CLASS_MAPPINGS.update(_id_photo_prompt.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_id_photo_prompt.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 证件照简易提示词导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")


# 证件照混合排版（A5）：photo_sheet_mixed_node.py（注册 key QG_PhotoSheetMixed）
try:
    from . import photo_sheet_mixed_node as _photo_sheet_mixed

    NODE_CLASS_MAPPINGS.update(_photo_sheet_mixed.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_photo_sheet_mixed.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 证件照混合排版导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")


# 图像合成：qg_image_composite.py（注册 key QG_ImageComposite）
try:
    from . import qg_image_composite as _image_composite

    NODE_CLASS_MAPPINGS.update(_image_composite.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_image_composite.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 图像合成导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")


# 证件照尺寸选择：qg_id_photo_size_picker.py（注册 key QG_IDPhotoSizePicker）
try:
    from . import qg_id_photo_size_picker as _id_photo_size_picker

    NODE_CLASS_MAPPINGS.update(_id_photo_size_picker.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_id_photo_size_picker.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 证件照尺寸选择导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")

# QG 取色器：纯字符串节点，无第三方依赖，单独 try/except。
try:
    from . import qg_color_picker as _color_picker

    NODE_CLASS_MAPPINGS.update(_color_picker.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_color_picker.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 取色器导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")


# 多人证件照拼版：qg_multi_photo_sheet.py（注册 key QG_MultiPhotoSheet）
try:
    from . import qg_multi_photo_sheet as _multi_photo_sheet

    NODE_CLASS_MAPPINGS.update(_multi_photo_sheet.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_multi_photo_sheet.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 多人证件照拼版导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")


# 图像批次组合：qg_image_batch_builder.py（注册 key QG_ImageBatchBuilder）
try:
    from . import qg_image_batch_builder as _image_batch_builder

    NODE_CLASS_MAPPINGS.update(_image_batch_builder.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_image_batch_builder.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 图像批次组合导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")


# 移除背景 V2：qg_remove_background_v2.py（注册 key QG_RemoveBackgroundV2）
try:
    from . import qg_remove_background_v2 as _remove_bg_v2

    NODE_CLASS_MAPPINGS.update(_remove_bg_v2.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_remove_bg_v2.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 移除背景 V2 导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")


# 遮罩次序过滤：qg_mask_order_filter.py（注册 key QG_MaskOrderFilter）
try:
    from . import qg_mask_order_filter as _mask_order

    NODE_CLASS_MAPPINGS.update(_mask_order.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_mask_order.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 遮罩次序过滤导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")


# 简易 Seg 检测三件套：自造类型，只用 ultralytics + segment_anything，不依赖 Impact
try:
    from . import qg_yolo_detector_loader as _yolo_loader

    NODE_CLASS_MAPPINGS.update(_yolo_loader.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_yolo_loader.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 检测模型加载器导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")

try:
    from . import qg_sam_model_loader as _sam_loader

    NODE_CLASS_MAPPINGS.update(_sam_loader.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_sam_loader.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG SAM 模型加载器导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")

try:
    from . import qg_simple_seg_detector as _simple_seg

    NODE_CLASS_MAPPINGS.update(_simple_seg.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_simple_seg.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 简易 Seg 检测导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")

# 遮罩到 Seg：qg_mask_to_seg.py（注册 key QG_MaskToSeg）
try:
    from . import qg_mask_to_seg as _mask_to_seg

    NODE_CLASS_MAPPINGS.update(_mask_to_seg.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_mask_to_seg.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 遮罩到 Seg 导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")

# 图像与遮罩预览：qg_image_mask_preview.py（注册 key QG_ImageMaskPreview）
try:
    from . import qg_image_mask_preview as _image_mask_preview

    NODE_CLASS_MAPPINGS.update(_image_mask_preview.NODE_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_image_mask_preview.NODE_DISPLAY_NAME_MAPPINGS)
except Exception:
    import traceback

    traceback.print_exc()
    print("[QG-Multipack] QG 图像与遮罩预览导入失败（上面的 traceback 是原因），"
          "其余节点不受影响。")


WEB_DIRECTORY = "./web"
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]


def _provider_id(existing):
    """新增条目用的稳定 id：时间戳 + 序号，不需要全局唯一性。"""
    base = "p%d" % int(time.time() * 1000)
    pid = base
    n = 1
    while pid in existing:
        n += 1
        pid = "%s_%d" % (base, n)
    return pid


def _register_routes():
    """翻译服务商设置面板的三个接口（/qg_translate/config、/qg_translate/test）。

    前端只认「服务商列表」这一种数据：读回来是打码的 key，存回去时带上
    掩码就表示没改过、沿用原 key —— 否则每次保存都要重新贴一遍 key。
    """
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception:  # 不在 ComfyUI 里（单测 / 纯导入）就安静跳过
        return
    mod = _translate_core
    routes = getattr(PromptServer, "instance", None)
    if routes is None:  # 服务未启动的进程（单测/纯导入）里安静跳过
        return
    routes = routes.routes

    def _host_only(value):
        """从 Host / Origin / Referer 里取出主机名（小写，丢掉端口与路径）。"""
        text = str(value or "").strip().lower()
        if not text:
            return ""
        if "://" in text:
            text = text.split("://", 1)[1]
        text = text.split("/", 1)[0]
        if text.startswith("["):              # IPv6：[::1]:8188
            end = text.find("]")
            return text[1:end] if end > 0 else text
        return text.split(":", 1)[0]

    def _cross_site(request):
        """跨站写入防护：命中就返回 403 响应，放行返回 None。

        这些接口没有任何鉴权，而浏览器里任何一个第三方页面都能向
        ``http://127.0.0.1:8188/qg_translate/config`` 发一个表单 POST，把
        用户的服务商整份覆盖成攻击者指定的地址 —— 之后每次翻译都会把提示词
        送到那台机器上，Key 也一并交出去（CSRF，不需要读响应就能生效）。

        这里**不加鉴权**（从局域网、反代访问也要照常能用），只检查浏览器
        自动附带的来源标记：

        * 没有 Origin / Referer 的请求放行 —— curl、脚本、节点内部调用都不带；
        * 带了就必须与本次请求的 Host 同源；只比主机名不比端口，反代改写
          端口时不误伤，``X-Forwarded-Host`` 也认；
        * ``Origin: null``（sandbox iframe、file:// 页面）一律拒绝。
        """
        origin = request.headers.get("Origin") or request.headers.get("Referer")
        if not origin:
            return None
        if str(origin).strip().lower() == "null":
            return web.json_response(
                {"ok": False, "message": "拒绝来自 file:// 或沙箱页面的写入"},
                status=403)
        want = _host_only(origin)
        allowed = {_host_only(request.host)}
        forwarded = request.headers.get("X-Forwarded-Host")
        if forwarded:
            allowed.add(_host_only(forwarded))
        allowed.discard("")
        if want and allowed and want not in allowed:
            return web.json_response(
                {"ok": False,
                 "message": "拒绝跨站写入：来源 %s 与本服务 %s 不同源" %
                            (want, " / ".join(sorted(allowed)))},
                status=403)
        return None

    def _public(entry):
        key = entry.get("api_key") or ""
        return {
            "id": entry["id"],
            "name": entry["name"],
            "api_url": entry["api_url"],
            # model 是默认模型的镜像，models 是全部——前端两个都要：
            # 前者兼容老面板，后者用来渲染模型列表
            "model": entry["model"],
            "models": list(entry.get("models") or []),
            "default_model": entry.get("default_model") or entry["model"],
            "has_key": bool(key),
            "api_key_masked": mod.mask_key(key),
        }

    def _preset_keys_masked():
        # 内置预设的 key 同样只以掩码出门；掩码原样传回 = 没改过
        cfg = mod.load_config()
        keys = cfg.get("preset_api_keys")
        keys = keys if isinstance(keys, dict) else {}
        return {name: mod.mask_key(str(val))
                for name, val in keys.items() if str(val).strip()}

    def _baidu_public():
        """百度翻译那对凭证：appid 明文，密钥只出门掩码。"""
        section = mod.load_config().get("baidu")
        section = section if isinstance(section, dict) else {}
        key = str(section.get("key") or "")
        return {
            "appid": str(section.get("appid") or ""),
            "has_key": bool(key),
            "key_masked": mod.mask_key(key),
        }

    def _merge_baidu(body, cfg):
        """设置面板传回的百度凭证：掩码沿用旧值，两样都空就删掉这一段。"""
        incoming = body.get("baidu")
        if not isinstance(incoming, dict):
            return
        old = cfg.get("baidu")
        old = old if isinstance(old, dict) else {}
        appid = str(incoming.get("appid") or "").strip()[:64]
        key = str(incoming.get("key") or "").strip()[:200]
        if mod.KEY_MASK in key:
            key = str(old.get("key") or "")
        if appid or key:
            cfg["baidu"] = {"appid": appid, "key": key}
        else:
            cfg.pop("baidu", None)

    def _merge_preset_keys(body, cfg):
        """设置面板传回的内置预设 key：掩码沿用旧值，空值删除该条。"""
        incoming = body.get("preset_api_keys")
        if not isinstance(incoming, dict):
            return
        old = cfg.get("preset_api_keys")
        old = old if isinstance(old, dict) else {}
        merged = {}
        for k, v in incoming.items():
            name = str(k).strip()[:60]
            val = str(v).strip()[:400]
            if name not in mod.PRESETS:
                continue
            if mod.KEY_MASK in val:
                val = str(old.get(name) or "")
            if val:
                merged[name] = val
        cfg["preset_api_keys"] = merged

    def _vision_services():
        """图像反推节点那套「服务商/模型」下拉。

        前端在设置面板里改完服务商之后要刷新已存在节点的下拉，所以这份
        列表得由后端给——前端自己拼不出视觉模型清单。节点模块导入失败时
        （比如 Pillow 缺失）返回空列表，前端就保持原样，不删选项。
        """
        module = globals().get("_img2prompt")
        if module is None:
            return []
        try:
            return module.vision_choices()
        except Exception:  # noqa: BLE001 - 下拉刷不出来不该让接口 500
            return []

    def _rules_full():
        """规则管理器的全量数据（带正文），保存后原样回传给前端。"""
        try:
            groups = _rules_lib.load_rules()
        except Exception as error:  # noqa: BLE001 - rules.json 写坏也不能 500
            print("[QG-Multipack] 读取规则库失败：%s" % error)
            groups = _rules_lib.clean(_rules_lib.default_rules())
        return {
            "order": list(_rules_lib.GROUP_ORDER),
            "labels": dict(_rules_lib.GROUP_LABELS),
            "hints": dict(_rules_lib.GROUP_HINTS),
            "groups": groups,
            "node_rules": _rules_lib.node_rule_names(),
        }

    def _rules_summary():
        """给节点下拉用的轻量摘要：只有名字，不带正文。"""
        try:
            return _rules_lib.summary()
        except Exception:  # noqa: BLE001
            return {"order": list(_rules_lib.GROUP_ORDER), "groups": {},
                    "node_rules": []}

    try:
        @routes.get("/qg_translate/config")
        async def qg_config_get(request):
            providers = mod.list_providers(with_key=True)
            return web.json_response({
                "providers": [_public(p) for p in providers],
                "default_provider": mod.default_provider(),
                "choices": mod.service_choices(),
                "presets": mod.PRESETS,
                "preset_api_keys": _preset_keys_masked(),
                "baidu": _baidu_public(),
                "vision_services": _vision_services(),
                "rules": _rules_summary(),
            })

        @routes.post("/qg_translate/config")
        async def qg_config_set(request):
            blocked = _cross_site(request)
            if blocked is not None:
                return blocked
            try:
                body = await request.json()
            except Exception:
                body = {}
            incoming = body.get("providers")
            if not isinstance(incoming, list):
                return web.json_response(
                    {"ok": False, "message": "providers 必须是数组"}, status=400)

            old = {p["id"]: p for p in mod.list_providers(with_key=True)}
            existing_ids = set(old)
            clean = []
            for i, raw in enumerate(incoming):
                if not isinstance(raw, dict):
                    continue
                entry = mod._clean_provider(raw, i)
                if not entry["name"]:
                    continue
                if not str(raw.get("id") or "").strip():
                    entry["id"] = _provider_id(existing_ids)
                    existing_ids.add(entry["id"])
                # 掩码 = 用户没动这个 key；原样保留（新增条目则视为空）
                submitted = str(raw.get("api_key") or "")
                if mod.KEY_MASK in submitted:
                    entry["api_key"] = old.get(entry["id"], {}).get("api_key", "")
                clean.append(entry)

            cfg = mod.load_config()
            cfg["providers"] = clean
            _merge_preset_keys(body, cfg)
            _merge_baidu(body, cfg)
            want = str(body.get("default_provider") or "").strip()
            cfg["default_provider"] = want
            try:
                mod.save_config(cfg)
            except Exception as error:  # noqa: BLE001 - 磁盘只读 / 占用
                return web.json_response(
                    {"ok": False, "message": "写入 config.json 失败：%s" % error},
                    status=500)
            return web.json_response({
                "ok": True,
                "providers": [_public(p) for p in clean],
                "default_provider": mod.default_provider(),
                "choices": mod.service_choices(),
                "preset_api_keys": _preset_keys_masked(),
                "baidu": _baidu_public(),
                "vision_services": _vision_services(),
                "rules": _rules_summary(),
            })

        @routes.post("/qg_translate/test")
        async def qg_provider_test(request):
            blocked = _cross_site(request)
            if blocked is not None:
                return blocked
            try:
                body = await request.json()
            except Exception:
                body = {}
            raw = body.get("provider") if isinstance(body, dict) else None
            raw = raw if isinstance(raw, dict) else {}
            entry = mod._clean_provider(raw)
            if mod.KEY_MASK in str(raw.get("api_key") or ""):
                # 掩码 = 沿用已保存的 key：先查自定义条目，再查内置预设
                name = entry["name"]
                saved = {p["id"]: p for p in mod.list_providers(with_key=True)}
                entry["api_key"] = saved.get(entry["id"], {}).get("api_key", "")
                if not entry["api_key"] and name in mod.PRESETS:
                    entry["api_key"] = mod.preset_key(name)
            # test_provider 里是同步 urllib，最长会等满 60 秒。直接在 async
            # handler 里调用会把整个 aiohttp event loop 卡住——界面的进度推
            # 送、队列状态、其他请求全部停摆，看起来就是「ComfyUI 死了」。
            # 丢进线程池，event loop 继续转，只有这个请求在等。
            result = await asyncio.to_thread(mod.test_provider, entry)
            return web.json_response(result)
    except Exception as error:  # noqa: BLE001 - 路由重复注册（热重载）不该炸全插件
        print("[QG-Multipack] 注册翻译设置接口失败：%s" % error)

    # 规则管理器的接口。单独一个 try：规则写坏 / 老版本残留不该影响
    # 上面那套服务商配置，反过来说服务商接口挂了也不该连累规则编辑。
    try:
        @routes.get("/qg_rules")
        async def qg_rules_get(request):
            return web.json_response({"ok": True, **_rules_full()})

        @routes.post("/qg_rules")
        async def qg_rules_set(request):
            blocked = _cross_site(request)
            if blocked is not None:
                return blocked
            try:
                body = await request.json()
            except Exception:
                body = {}
            groups = body.get("groups") if isinstance(body, dict) else None
            if not isinstance(groups, dict):
                return web.json_response(
                    {"ok": False, "message": "groups 必须是对象"}, status=400)
            # 名称重名在组内会被去重，跨组重名会让节点下拉出现两个同名项，
            # 这里先拦下来，直接把冲突的名字告诉前端。
            seen = {}
            for key, items in groups.items():
                if key not in _rules_lib.GROUP_ORDER or not isinstance(items, list):
                    continue
                for item in items:
                    name = str((item or {}).get("name") or "").strip() \
                        if isinstance(item, dict) else ""
                    if not name:
                        continue
                    if name in seen:
                        return web.json_response({
                            "ok": False,
                            "message": "规则名「%s」在「%s」和「%s」里重复了，"
                                       "名字不能跨组同名" % (
                                           name,
                                           _rules_lib.GROUP_LABELS.get(seen[name], seen[name]),
                                           _rules_lib.GROUP_LABELS.get(key, key)),
                        }, status=400)
                    seen[name] = key
            try:
                _rules_lib.save_rules(groups)
            except Exception as error:  # noqa: BLE001 - 磁盘只读 / 占用
                return web.json_response(
                    {"ok": False, "message": "写入 rules.json 失败：%s" % error},
                    status=500)
            return web.json_response({"ok": True, **_rules_full()})

        @routes.post("/qg_rules/reset")
        async def qg_rules_reset(request):
            """恢复内置规则。整份覆盖，包括用户自己加的条目。"""
            blocked = _cross_site(request)
            if blocked is not None:
                return blocked
            try:
                _rules_lib.save_rules(_rules_lib.default_rules())
            except Exception as error:  # noqa: BLE001
                return web.json_response(
                    {"ok": False, "message": "写入 rules.json 失败：%s" % error},
                    status=500)
            return web.json_response({"ok": True, **_rules_full()})
    except Exception as error:  # noqa: BLE001
        print("[QG-Multipack] 注册规则接口失败：%s" % error)


_register_routes()
