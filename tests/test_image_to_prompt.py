# -*- coding: utf-8 -*-
"""图像反推节点回归：选项解析、图片编码、思考链剥离、400 降级。

不依赖 ComfyUI：伪造一个包壳，让模块里的 ``from . import translate_core``
能解析，然后逐项调用纯函数。真实 API 调用不在这里——那是联网且花钱的事。
"""
import base64
import importlib
import io
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

import numpy as np

# 目录名带连字符（ComfyUI-QG-Multipack），不是合法包名，不能直接 import，造一个包壳给它
shell = types.ModuleType("qg_pack")
shell.__path__ = [PKG]
sys.modules["qg_pack"] = shell
mod = importlib.import_module("qg_pack.image_to_prompt_node")

ok = lambda c: "PASS" if c else "FAIL"
fails = []


def check(label, cond, extra=""):
    print(("  " + label + ": " + str(extra)).ljust(66), ok(cond))
    if not cond:
        fails.append(label)


def png_size(data_url):
    """从 data URL 里把图读回来，返回 (宽, 高, 字节数)。"""
    from PIL import Image
    raw = base64.b64decode(data_url.split(",", 1)[1])
    image = Image.open(io.BytesIO(raw))
    return image.size[0], image.size[1], len(raw)


print("=== A. 选项解析 ===")
choices = mod.vision_choices()
check("有默认项", mod.DEFAULT_SERVICE in choices, choices[:2])
check("智谱 4.6v 在列", "智谱/glm-4.6v-flash" in choices, choices[:2])
p, m = mod.parse_vision_choice("智谱/glm-4.6v-flash")
check("中文显示名换回全名", (p, m) == ("Zhipu GLM", "glm-4.6v-flash"), (p, m))
p, m = mod.parse_vision_choice("Zhipu GLM/glm-4.6v-flash")
check("全名也能解析", (p, m) == ("Zhipu GLM", "glm-4.6v-flash"), (p, m))
p, m = mod.parse_vision_choice("OpenRouter/openai/gpt-4o-mini")
check("模型名自带斜杠不被切坏", (p, m) == ("OpenRouter", "openai/gpt-4o-mini"), (p, m))
p, m = mod.parse_vision_choice("不认识的东西")
check("认不出服务商", (p, m) == ("不认识的东西", ""), (p, m))

print("\n=== B. 解析到请求参数 ===")
target = mod.resolve_vision_target("Zhipu GLM/glm-4.6v-flash")
check("模型来自选项", target["model"] == "glm-4.6v-flash", target["model"])
check("地址来自预设", target["api_url"].endswith("/chat/completions"), target["api_url"])
check("服务商名回填", target["provider"] == "Zhipu GLM", target["provider"])
try:
    mod.resolve_vision_target("Zhipu GLM")
    check("无模型应报错", False)
except ValueError as e:
    check("无模型的提示可读", "模型" in str(e), str(e)[:40])

print("\n=== C. 图片编码 ===")
big = np.random.rand(1, 1024, 2048, 3).astype(np.float32)
url = mod.tensor_to_data_url(big, max_side=1024, quality=75)
check("是 jpeg data URL", url.startswith("data:image/jpeg;base64,"), url[:32])
w, h, size = png_size(url)
check("长边压到 1024", max(w, h) == 1024, (w, h))
check("宽高比保持", abs((w / h) - 2.0) < 0.02, round(w / h, 3))
check("体积可控", size < 400_000, f"{size / 1024:.0f} KB")

rgba = np.ones((64, 64, 4), dtype=np.float32) * 0.5
rgba[..., 3] = 0.0
w2, h2, _ = png_size(mod.tensor_to_data_url(rgba))
check("4 通道压成 RGB", (w2, h2) == (64, 64), (w2, h2))

gray = np.ones((32, 32), dtype=np.float32)
w3, h3, _ = png_size(mod.tensor_to_data_url(gray))
check("灰度补成三通道", (w3, h3) == (32, 32), (w3, h3))

print("\n=== D. 缓存指纹 ===")
a = np.zeros((2, 64, 64, 3), dtype=np.float32)
b = a.copy()
check("同图指纹稳定", mod.image_fingerprint(a) == mod.image_fingerprint(b))
check("不是全零占位", mod.image_fingerprint(a) != "0", mod.image_fingerprint(a)[:8])
b[1, 10, 10] = 1.0
check("batch 第二帧变了也认得出", mod.image_fingerprint(a) != mod.image_fingerprint(b))
check("None 有兜底", mod.image_fingerprint(None) == "0")

print("\n=== E. 思考链与围栏清理 ===")
check("剥 <think>",
      mod.clean_answer("<think>想一下</think>一只猫") == "一只猫",
      mod.clean_answer("<think>想一下</think>一只猫"))
check("多行 think 跨行剥",
      mod.clean_answer("<think>\n第一行\n第二行\n</think>\n\n一只猫") == "一只猫")
check("剥代码围栏",
      mod.clean_answer("```markdown\n一只猫\n```") == "一只猫",
      mod.clean_answer("```markdown\n一只猫\n```"))
check("剥 DeepSeek 收尾标记",
      mod.clean_answer("推理到此\n<｜end▁of▁thinking｜>一只猫") == "一只猫",
      mod.clean_answer("推理到此\n<｜end▁of▁thinking｜>一只猫"))
check("正常文本不动",
      mod.clean_answer("  a cat on a sofa  ") == "a cat on a sofa")

print("\n=== F. 关思考的参数只发给支持的模型 ===")
check("glm-4.6v 发 thinking",
      mod._thinking_payload("glm-4.6v-flash") == {"thinking": {"type": "disabled"}},
      mod._thinking_payload("glm-4.6v-flash"))
check("glm-4v-flash 不发",
      mod._thinking_payload("glm-4v-flash") == {},
      mod._thinking_payload("glm-4v-flash"))
check("qwen3-vl 发 enable_thinking",
      mod._thinking_payload("qwen3-vl-plus") == {"enable_thinking": False},
      mod._thinking_payload("qwen3-vl-plus"))
check("未知模型不发", mod._thinking_payload("my-local-model") == {})

print("\n=== G. 消息结构 ===")
messages = mod._build_messages("规则正文", "data:image/jpeg;base64,AAA")
check("两条消息", len(messages) == 2, len(messages))
check("system 独立", messages[0]["role"] == "system" and messages[0]["content"] == "规则正文")
user = messages[1]["content"]
check("user 是内容数组", isinstance(user, list) and len(user) == 2)
check("先文字后图片",
      user[0]["type"] == "text" and user[1]["type"] == "image_url",
      [part.get("type") for part in user])
check("图片走 url 字段", user[1]["image_url"]["url"].startswith("data:image/jpeg"))

print("\n=== H. 400 降级 ===")
seen = []


def fake_post(url, key, payload):
    seen.append(dict(payload))
    if len(seen) == 1:
        raise mod._HTTPFailure(400, "unknown field thinking")
    return {"choices": [{"message": {"content": "一只猫"}}]}


original_post = mod._post
mod._post = fake_post
t = {"model": "glm-4.6v-flash", "api_url": "https://x/chat/completions", "api_key": "k"}
out = mod.ask_vision("规则", "data:image/jpeg;base64,AAA", t)
check("降级后拿到结果", out == "一只猫", out)
check("第一次带 thinking", "thinking" in seen[0], list(seen[0]))
check("第二次去掉 thinking", "thinking" not in seen[1], list(seen[1]))
check("第二次仍保留 max_tokens", "max_tokens" in seen[1])

seen.clear()


def fake_fail(url, key, payload):
    seen.append(dict(payload))
    raise mod._HTTPFailure(400, "still bad")


mod._post = fake_fail
try:
    mod.ask_vision("规则", "data:image/jpeg;base64,AAA", t)
    check("全 400 应抛错", False)
except RuntimeError as e:
    check("抛的是可读错误", "HTTP 400" in str(e) or "请求被拒绝" in str(e), str(e)[:50])
check("降了三级", len(seen) == 3, len(seen))
check("最后一级只剩 model+messages",
      set(seen[-1]) == {"model", "messages"}, list(seen[-1]))

seen.clear()


def fake_401(url, key, payload):
    seen.append(dict(payload))
    raise mod._HTTPFailure(401, "bad key")


mod._post = fake_401
try:
    mod.ask_vision("规则", "data:image/jpeg;base64,AAA", t)
    check("401 应抛错", False)
except RuntimeError as e:
    check("401 不降级", len(seen) == 1, len(seen))
    check("401 提示 Key", "Key" in str(e) or "鉴权" in str(e), str(e)[:60])

mod._post = original_post

print("\n=== I. 节点定义 ===")
spec = mod.QGImageToPrompt.INPUT_TYPES()
order = list(spec["required"])
check("控件顺序与截图一致",
      order == ["image", "rule", "custom_rule", "custom_rule_content",
                "user_prompt", "vlm_service", "auto_unload", "seed"], order)
check("规则预设含默认项", spec["required"]["rule"][1]["default"] == mod.DEFAULT_RULE)
check("自定义规则默认关", spec["required"]["custom_rule"][1]["default"] is False)
check("视觉服务默认可用",
      spec["required"]["vlm_service"][1]["default"] in spec["required"]["vlm_service"][0],
      spec["required"]["vlm_service"][1]["default"])
check("种子可控生成后", spec["required"]["seed"][1]["control_after_generate"] is True)
check("两个输出", mod.QGImageToPrompt.RETURN_TYPES == ("STRING", "STRING"))
check("列表输出", mod.QGImageToPrompt.OUTPUT_IS_LIST == (False, True))
check("中文端口名", mod.QGImageToPrompt.RETURN_NAMES == ("提示词输出", "提示词列表"))

print("\n=== J. 指纹输入 ===")
cls = mod.QGImageToPrompt
base = dict(image=a, rule=mod.DEFAULT_RULE, custom_rule=False,
            custom_rule_content="", user_prompt="", vlm_service=mod.DEFAULT_SERVICE,
            auto_unload=True, seed=0)
check("同参数同指纹", cls.IS_CHANGED(**base) == cls.IS_CHANGED(**base))
changed = dict(base, seed=1)
check("换种子换指纹", cls.IS_CHANGED(**base) != cls.IS_CHANGED(**changed))
changed = dict(base, user_prompt="夜景")
check("换附加要求换指纹", cls.IS_CHANGED(**base) != cls.IS_CHANGED(**changed))
check("是 md5 长度", len(cls.IS_CHANGED(**base)) == 32)

print("\n=== K. 多图合并（对齐 MUJUN-2025 fork，GPL-3.0）===")
check("glm-4.6v 上限 100", mod.model_max_images("glm-4.6v-flash") == 100)
check("普通 glm 上限 5", mod.model_max_images("glm-4v-flash") == 5)
check("qwen 上限 100", mod.model_max_images("qwen-vl-plus-latest") == 100)
check("gpt-4 系上限 100", mod.model_max_images("openai/gpt-4o-mini") == 100)
check("vision 关键词放宽", mod.model_max_images("my-vision-model") == 100)
check("未知模型上限 10", mod.model_max_images("my-local-model") == 10)

small1 = np.zeros((1, 8, 8, 3), dtype=np.float32)
small2 = np.ones((1, 8, 8, 3), dtype=np.float32)
check("batch 展开逐帧", len(mod.flatten_frames([np.zeros((2, 8, 8, 3), dtype=np.float32)])) == 2)
check("3 维整帧收", len(mod.flatten_frames([small1])) == 1)
check("None 跳过", len(mod.flatten_frames([None, small2])) == 1)
check("全空返回空列表", mod.flatten_frames([None, None]) == [])

multi_msgs = mod._build_multi_messages("规则正文", ["u1", "u2", "u3"])
check("多图也是两条消息", len(multi_msgs) == 2)
check("system 独立", multi_msgs[0]["role"] == "system"
      and multi_msgs[0]["content"] == "规则正文")
mu = multi_msgs[1]["content"]
check("1 段引子 + 3 张图", len(mu) == 4 and mu[0]["type"] == "text"
      and sum(1 for c in mu if c["type"] == "image_url") == 3)

spec_multi = cls.INPUT_TYPES()
check("optional 声明 image2..image9",
      all(f"image{n}" in spec_multi["optional"] for n in range(2, 10)))

saved_ask = mod._ask
saved_target = mod.resolve_vision_target
try:
    seen_msgs = []

    def fake_ask(messages, target, on_delta=None, vision=True):
        seen_msgs.append(messages)
        return "综合描述"

    def fake_target(choice):
        return {"provider": "Zhipu GLM", "model": "glm-4.6v-flash",
                "api_url": "http://example.invalid/chat/completions",
                "api_key": ""}

    mod._ask = fake_ask
    mod.resolve_vision_target = fake_target
    # 注意 execute 是实例方法：必须先实例化，否则首个实参会绑给 self
    node = cls()
    out = node.execute(small1, mod.DEFAULT_RULE, False, "", "",
                       mod.DEFAULT_SERVICE, True, 0, image2=small2)
    check("多图输出单条综合描述", out[0] == "综合描述", out[0][:20])
    check("列表口是单元素列表", out[1] == ["综合描述"], out[1])
    check("一次请求带两张图", sum(1 for c in seen_msgs[-1][1]["content"]
                                 if c["type"] == "image_url") == 2)

    fp_a = cls.IS_CHANGED(image=small1, rule=mod.DEFAULT_RULE, image2=small2)
    fp_b = cls.IS_CHANGED(image=small1, rule=mod.DEFAULT_RULE, image2=small1)
    check("换额外图换指纹", fp_a != fp_b)
    check("断开额外口也换指纹",
          fp_a != cls.IS_CHANGED(image=small1, rule=mod.DEFAULT_RULE))

    calls_count = []
    mod._ask = lambda m, t, on_delta=None, vision=True: (
        calls_count.append(m) or "帧%d" % len(calls_count))
    batch2 = np.concatenate([small1, small2], axis=0)
    out2 = node.execute(batch2, mod.DEFAULT_RULE, False, "", "",
                        mod.DEFAULT_SERVICE, True, 0)
    check("主口 batch 仍逐帧独立", len(calls_count) == 2, len(calls_count))
    check("逐帧合并文本", out2[0] == "帧1\n---\n帧2", out2[0][:24])

    # 截断：glm-4v-flash 上限 5，6 帧 → 保留前 5
    seen_msgs.clear()
    mod._ask = fake_ask
    many = [np.full((1, 8, 8, 3), i / 10.0, dtype=np.float32) for i in range(6)]
    limit_target = dict(fake_target(""), model="glm-4v-flash")
    mod.resolve_vision_target = lambda choice: limit_target
    out3 = node.execute(many[0], mod.DEFAULT_RULE, False, "", "",
                        mod.DEFAULT_SERVICE, True, 0,
                        image2=many[1], image3=many[2], image4=many[3],
                        image5=many[4], image6=many[5])
    images_sent = sum(1 for c in seen_msgs[-1][1]["content"]
                      if c["type"] == "image_url")
    check("超上限截断到 5", images_sent == 5, images_sent)
finally:
    mod._ask = saved_ask
    mod.resolve_vision_target = saved_target

check("显示名带 QG 前缀",
      mod.NODE_DISPLAY_NAME_MAPPINGS["QG_ImageToPrompt"] == "QG 图像反推提示词")

print("\n---")
print("失败 %d 项" % len(fails))
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("全部通过")
