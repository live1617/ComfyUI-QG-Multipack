# -*- coding: utf-8 -*-
"""真实调用一次视觉模型，验证请求格式与输出（会联网）。

用法：python tests/live_image_to_prompt.py [图片路径] [规则名]
只打印结果，不打印任何密钥。
"""
import importlib
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

import numpy as np
from PIL import Image

shell = types.ModuleType("qg_pack")
shell.__path__ = [PKG]
sys.modules["qg_pack"] = shell
mod = importlib.import_module("qg_pack.image_to_prompt_node")

path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(PKG), "..", "input", "portrait_model_denim.png")
path = os.path.abspath(path)
rule = sys.argv[2] if len(sys.argv) > 2 else mod.DEFAULT_RULE
service = sys.argv[3] if len(sys.argv) > 3 else mod.DEFAULT_SERVICE

image = Image.open(path).convert("RGB")
array = np.asarray(image, dtype=np.float32) / 255.0
array = array[None]                       # [1, H, W, C]

target = mod.resolve_vision_target(service)
system_text = mod.RULES[rule] + "\n\n" + mod.NO_THINKING_HINT
data_url = mod.tensor_to_data_url(array, max_side=1024, quality=75)

print(f"图片: {path}  {image.size[0]}x{image.size[1]}")
print(f"模型: {target['model']}")
print(f"规则: {rule}")
print(f"请求体积: {len(data_url) / 1024:.0f} KB（base64）")
print("-" * 60)

answer = mod.clean_answer(mod.ask_vision(system_text, data_url, target))
print(answer)
print("-" * 60)
print(f"输出 {len(answer)} 字")
