"""QG 主色提取：统计图像中出现最多的颜色，输出大写 #RRGGBB。

本节点是「参照功能规格的独立实现」（功能形态参考 Goohaitools
「孤海-主色提取 (多版本兼容)」，GPL-3.0），统计逻辑自行编写：上游用
Python 列表逐像素循环过滤与计数，本实现全程 numpy 向量化（布尔掩码
过滤 + RGB 打包成整数做 unique），桶统计语义一致，大图上快一个数量级。

与上游规格保持一致的语义：
- batch 只取第一帧（上游 image[0] 的行为）；
- 先按降采样系数缩小到 (宽//系数, 高//系数)，两边各下限 4 像素，LANCZOS；
- 平均亮度 <15 或 >240 的像素视为黑边/白边剔除；全被剔除则回退全部像素；
- 容差量化按每通道 c // 容差 * 容差 分桶（容差 0 则逐原色统计）；
- 主色取像素数最多的桶，频次并列时取通道和（亮度）更高的桶。

「多版本兼容」是上游针对旧版 torch / 前端做的 display 探测噱头，与本包
目标环境无关，未照搬；滑块配置直接按当前前端写死。
"""

from __future__ import annotations

import numpy as np
import torch
from PIL import Image

# 模块级常量不写类型标注：开发规范 §5（AST 扫描器只收 ast.Assign）
DOWNSAMPLE_DEFAULT = 8
DOWNSAMPLE_MIN = 1
DOWNSAMPLE_MAX = 16
TOLERANCE_DEFAULT = 15
TOLERANCE_MIN = 0
TOLERANCE_MAX = 100
_MIN_SIDE = 4       # 降采样后宽/高的下限（与上游一致）
_DARK_CUT = 15      # 平均亮度低于此值视为黑边剔除
_BRIGHT_CUT = 240   # 平均亮度高于此值视为白边剔除


def _frame_to_rgb_uint8(frame):
    """单帧 [H, W, C] 转 uint8 RGB：0-1 浮点先放大 255，带 alpha 通道时预乘。

    通道数约定：3 通道直通；4 通道按 alpha 预乘后取 RGB（与上游
    _handle_alpha_channel 同语义，预乘到底色黑上）；1/2 通道灰度复制成
    3 通道；其余通道数超出预期时报 ValueError。
    """
    if not isinstance(frame, np.ndarray) or frame.ndim != 3:
        raise ValueError("单帧图像必须是 [高, 宽, 通道] 的 numpy 数组")
    channels = frame.shape[2]
    if channels == 3:
        rgb = frame[:, :, :3]
    elif channels == 4:  # RGB 与 alpha 各自归一到 0-1 再预乘，float/uint8 输入通吃
        scale = 255.0 if frame.dtype == np.uint8 else 1.0
        rgb = frame[:, :, :3].astype(np.float32) / scale * \
            frame[:, :, 3:4].astype(np.float32) / scale
    elif channels in (1, 2):
        gray = frame[:, :, :1]
        rgb = np.repeat(gray, 3, axis=2)
    else:
        raise ValueError("不支持的通道数：%d" % channels)
    if rgb.dtype == np.uint8:  # 已是 0-255 的输入直通（预乘分支除外）
        return rgb.astype(np.uint8, copy=True)
    return np.clip(np.asarray(rgb, dtype=np.float32) * 255.0, 0, 255
                   ).astype(np.uint8)


def _downsample(rgb, factor):
    """LANCZOS 缩小到 (宽//factor, 高//factor)，两边下限 4 像素。"""
    height, width = rgb.shape[:2]
    new_w = max(width // int(factor), _MIN_SIDE)
    new_h = max(height // int(factor), _MIN_SIDE)
    if (new_w, new_h) == (width, height):
        return rgb
    img = Image.fromarray(rgb).resize((new_w, new_h), Image.Resampling.LANCZOS)
    return np.asarray(img)


def _drop_extreme_colors(pixels):
    """剔除平均亮度 <15 / >240 的黑边白边像素；全被剔时回退全部像素。"""
    mean = pixels.astype(np.float32).mean(axis=1)
    keep = (mean >= _DARK_CUT) & (mean <= _BRIGHT_CUT)
    if not keep.any():
        return pixels
    return pixels[keep]


def _quantized_dominant(pixels, tolerance):
    """容差分桶统计，返回 (主色三元组, 主色桶像素数)。

    每通道按 c // tolerance * tolerance 量化（tolerance<=0 时逐原色），
    RGB 打包成一个整数做 unique 计数；频次并列取通道和更高的桶。
    """
    tol = max(0, int(tolerance))
    if tol > 1:
        pixels = (pixels // tol) * tol
    packed = (pixels[:, 0].astype(np.uint32) << 16 |
              pixels[:, 1].astype(np.uint32) << 8 |
              pixels[:, 2].astype(np.uint32))
    values, counts = np.unique(packed, return_counts=True)
    top = counts.max()
    tied = values[counts == top]
    sums = (tied >> 16) + ((tied >> 8) & np.uint32(0xFF)) + (tied & np.uint32(0xFF))
    best = int(tied[np.argmax(sums)])
    color = ((best >> 16) & 0xFF, (best >> 8) & 0xFF, best & 0xFF)
    return color, int(top)


class QGDominantColor:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "downsample": ("INT", {
                    "default": DOWNSAMPLE_DEFAULT,
                    "min": DOWNSAMPLE_MIN,
                    "max": DOWNSAMPLE_MAX,
                    "step": 1,
                    "display": "slider",
                }),
                "tolerance": ("INT", {
                    "default": TOLERANCE_DEFAULT,
                    "min": TOLERANCE_MIN,
                    "max": TOLERANCE_MAX,
                    "step": 1,
                    "display": "slider",
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("hex",)
    FUNCTION = "extract"
    CATEGORY = "QG 工具"
    DESCRIPTION = (
        "Extract the dominant colour of the image as an uppercase #RRGGBB "
        "string: downsample, drop near-black/near-white border pixels, "
        "bucket colours by per-channel tolerance and take the largest "
        "bucket (ties broken by brightness)."
    )

    def extract(self, image, downsample, tolerance):
        factor = max(DOWNSAMPLE_MIN, min(int(downsample), DOWNSAMPLE_MAX))
        tolerance = max(TOLERANCE_MIN, min(int(tolerance), TOLERANCE_MAX))

        if isinstance(image, torch.Tensor):
            array = image.detach().cpu().numpy()
        else:
            array = np.asarray(image)
        # 空批次：0 帧没有「主色」概念，按本包约定给中文错误，
        # 不静默返回默认色（那会让下游以为真的提取到了）。
        if array.ndim == 4 and array.shape[0] == 0:
            raise ValueError(
                "没有收到任何图像帧（输入 batch 为 0 帧），无法提取主色。"
                "检查上游是不是把照片全部过滤掉了。")
        frame = array[0] if array.ndim == 4 else array
        rgb = _frame_to_rgb_uint8(frame)
        rgb = _downsample(rgb, factor)

        pixels = rgb.reshape(-1, rgb.shape[2])
        pixels = _drop_extreme_colors(pixels)
        color, _count = _quantized_dominant(pixels, tolerance)
        return ("#%02X%02X%02X" % color,)


NODE_CLASS_MAPPINGS = {"QG_DominantColor": QGDominantColor}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_DominantColor": "QG 主色提取"}
