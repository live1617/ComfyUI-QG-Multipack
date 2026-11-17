"""QG_ImageBatchBuilder - 图像批次组合：N 个可选输入槽，一给就合成 batch。

解决「示例工作流里要把 6 张图串 5 个 ImageBatch」的繁琐：节点开 24 个可选
IMAGE 槽，接几张就合几张，空槽自动跳过。常用于把多个人的证件照汇成一个
batch，再接「QG 多人证件照拼版」等按帧处理的节点。

设计约定：
- 输入槽 ``image_01..image_24`` 全部可选，只收非 None 的；至少要有 1 张，
  否则明确报错。槽位编号只是顺序，中间空着不影响（按编号顺序拼接）。
- 每个槽本身可以是「一张」或「一个 batch」——整批按顺序展开，所以一次
  给 6 张单帧和给 1 个 6 帧 batch 结果一致。
- 尺寸/通道不一致：核心 ImageBatch 会强行把后来的图 upscale 到首帧尺寸，
  这里把策略显式化：``resize_mode='first'`` 双三次缩放对齐首帧（默认，
  与核心一致）；``'error'`` 直接报错，方便在裁切规格不一时及早发现。
  通道数以首帧为准，RGB 与 RGBA 互相补齐（RGBA→RGB 丢 alpha；RGB→RGBA
  补不透明 alpha），避免 torch.stack 通道数不一致。
- 纯函数 ``collect_frames`` / ``align_frames`` 无副作用，便于单文件加载测试。

本模块保持零相对导入。
"""

from __future__ import annotations

import numpy as np
import torch
from PIL import Image

#: 输入槽数量：A4 证件照 3 列 × 8 行 = 24 人，覆盖「一版」的常见上限。
SLOT_COUNT = 24
RESIZE_MODES = ["first", "error"]
SLOT_NAMES = tuple("image_%02d" % i for i in range(1, SLOT_COUNT + 1))

#: 24 个槽共用同一句说明，清单里也只登记一条（见 _SlotSpecs）。
#: 帮助卡（节点信息面板）按清单逐条渲染，登记 24 条就会把同一句话列 24 遍；
#: 这里靠一个只回一条、却能接收任意 image_NN 的清单容器解决。
SLOT_TOOLTIP = (
    "第 1～24 张图（可空）：接几张合几张，按编号顺序拼，空槽自动跳过；"
    "给最后一个槽接上图会自动多出一个空槽。每个槽可以接单张，也可以接一个 batch。"
)
SLOT_DISPLAY_NAME = "第 1～24 张"


def _as_frames(value):
    """把 ``[H,W,C]`` / ``[B,H,W,C]`` / None 统一成 frame 列表。"""
    if value is None:
        return []
    if not isinstance(value, torch.Tensor):
        value = torch.as_tensor(value)
    if value.ndim == 3:
        return [value]
    if value.ndim == 4:
        return [value[i] for i in range(int(value.shape[0]))]
    raise ValueError("图像维度非法：应为 [H,W,C] 或 [B,H,W,C]，实际 %d 维"
                     % value.ndim)


def collect_frames(values):
    """按槽位顺序把所有非空输入展开成一维 frame 列表。"""
    frames = []
    for name in SLOT_NAMES:
        frames.extend(_as_frames(values.get(name)))
    if not frames:
        raise ValueError("没有可组合的图像：请把图片接到 image_01 起的任意槽位")
    return frames


def _resize_plane(frame, height, width):
    """把单帧双三次缩放到指定高宽（尺寸已一致则原样返回）。"""
    if int(frame.shape[0]) == height and int(frame.shape[1]) == width:
        return frame
    img = Image.fromarray(
        (np.clip(frame.detach().cpu().numpy(), 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8),
        "RGBA" if frame.shape[-1] == 4 else "RGB")
    img = img.resize((width, height), Image.Resampling.BICUBIC)
    return torch.from_numpy(np.asarray(img, dtype=np.float32) / 255.0)


def align_frames(frames, mode="first"):
    """把尺寸/通道不一致的帧对齐到首帧规格，再堆成一个 batch。

    ``mode='error'`` 时任何尺寸不一致都直接抛错；``'first'`` 时缩放到首帧。
    """
    if not frames:
        raise ValueError("没有可对齐的图像帧")
    ref = frames[0]
    height, width = int(ref.shape[0]), int(ref.shape[1])
    channels = int(ref.shape[-1])

    if mode == "error":
        bad = [(int(f.shape[1]), int(f.shape[0])) for f in frames
               if int(f.shape[0]) != height or int(f.shape[1]) != width]
        if bad:
            raise ValueError(
                "图像尺寸不一致：首帧 %dx%d，其余有 %s。"
                "请统一裁切规格，或把 resize_mode 改为 first 自动缩放。"
                % (width, height, ", ".join("%dx%d" % s for s in bad[:5])))
        mode = "first"

    out = []
    for f in frames:
        if mode == "first":
            f = _resize_plane(f, height, width)
        if int(f.shape[-1]) != channels:
            if channels == 3:
                f = f[..., :3]
            else:
                f = torch.nn.functional.pad(f, (0, 1), mode="constant", value=1.0)
        out.append(f)
    return torch.stack(out, dim=0)


class _SlotSpecs(dict):
    """只对外暴露 1 个图像槽，但任何 ``image_NN`` 都按 IMAGE 接收。

    帮助卡（节点信息面板）是照着「节点登记的输入清单」逐条渲染的，一个槽一行。
    24 个同功能的槽写进清单，就等于同一句话列 24 遍 —— 这正是用户盯着问的问题。

    做法（与 rgthree 的「任意切换」同源）：清单里只放 1 条真实条目
    ``image_01``（显示成「第 1～24 张」），其余的 ``image_02``…``image_24``
    靠本类的 ``__contains__`` / ``__getitem__`` 兜住 ——

    * 序列化（``/object_info``、输入顺序表）：只迭代真实键，所以帮助卡只列一行；
    * 校验与执行（``comfy_execution/graph.py`` 的取输入信息函数）：先问
      ``名字 in 清单``，再取 ``清单[名字]``，本类对任意名字都回答「有，是 IMAGE」，
      因此前端动态加出来的槽照样能提交、能执行；
    * 存档键名不变（仍是 ``image_01``…``image_24``），老工作流不受影响。

    注意 ``resize_mode`` 是真实键，取它时走 ``dict`` 原路径，下拉候选不受影响。
    """

    def __contains__(self, key):
        return True

    def __getitem__(self, key):
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        return ("IMAGE", {"hidden": True, "tooltip": SLOT_TOOLTIP})


class QGImageBatchBuilder:
    CATEGORY = "QG 工具"

    @classmethod
    def INPUT_TYPES(cls):
        # 全部槽可选：前端 web/qg_image_batch_builder.js 默认只显示 1 个槽，
        # 接一个自动加一个（上限 24），因此后端不能强制任何槽必填，否则
        # 只接 1 张时 ComfyUI 会因「必填未接」拦截执行。至少 1 张由
        # collect_frames 在运行时检查并给出明确报错。
        #
        # 帮助卡只出现一行，原理见 _SlotSpecs；清单里唯一那条的名字必须是
        # image_01（前端第一个槽的键名、也是存档键名），显示名写清范围。
        optional = _SlotSpecs()
        optional["image_01"] = ("IMAGE", {
            "display_name": SLOT_DISPLAY_NAME,
            "tooltip": SLOT_TOOLTIP,
        })
        optional["resize_mode"] = (RESIZE_MODES, {
            "default": "first",
            "tooltip": "尺寸不一致时：first=以第 1 张为准双三次缩放；"
                       "error=直接报错（规格不一时早点发现）。",
        })
        return {"required": {}, "optional": optional}

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("image", "count")
    RETURN_TOOLTIPS = (
        "所有输入按顺序合成的一个 IMAGE batch。",
        "实际合进去的张数。",
    )
    FUNCTION = "build"

    def build(self, **kwargs):
        frames = collect_frames(kwargs)
        mode = kwargs.get("resize_mode") or "first"
        batch = align_frames(frames, mode)
        print("[QG Image Batch Builder] %d 张 → batch %s（模式 %s）"
              % (len(frames), tuple(batch.shape), mode))
        return (batch, int(len(frames)))


NODE_CLASS_MAPPINGS = {"QG_ImageBatchBuilder": QGImageBatchBuilder}
NODE_DISPLAY_NAME_MAPPINGS = {
    "QG_ImageBatchBuilder": "QG 图像批次组合",
}
