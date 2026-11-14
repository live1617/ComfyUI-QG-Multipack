# -*- coding: utf-8 -*-
"""QG_Translate —— 通用翻译节点（走任意 OpenAI 兼容服务商）。

这里只有节点外壳：翻译逻辑、服务商预设、config.json 读写全部在
``translate_core.py``。**整个文件可以安全删除** —— 连同 ``__init__.py`` 里
那两行注册一起去掉后，设置面板、提示词翻译节点、缓存都照常工作。

日常要做「中文提示词 → 英文提示词」这种固定链路，用 ``QG_PromptTranslate``
更省事：它只有四个控件，不用在节点上挑服务商字段。
"""

from __future__ import annotations

import hashlib

from . import prompt_rules as _rules
from .translate_core import (
    IF_FAIL, LANGUAGES, default_service_choice, push_notice, service_choices,
    translate,
)


class QGTranslate:
    """Translate text through an OpenAI-compatible chat API."""

    CATEGORY = "QG 工具"
    SEARCH_ALIASES = [
        "translate", "translation", "translator", "中文翻译", "翻译",
        "英文", "英语", "chinese to english", "llm", "deepseek", "kimi",
        "qwen", "glm", "ollama", "qg",
    ]

    @classmethod
    def INPUT_TYPES(cls):
        # 选项来自「内置预设 + 设置面板里配的服务商」；面板改完由前端刷新
        # 节点下拉，这里只管给出当前这一份。一个服务商配了多个模型时，默认
        # 模型用服务商名本身表示，其余模型显示成「服务商/模型」。
        choices = service_choices()
        return {
            "required": {
                "text": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": (
                            "要翻译的文字。直接在这里输入，或把上游文本接到这个口上（右键字段可转换为输入口）。"
                        ),
                    },
                ),
                "provider": (
                    choices,
                    {
                        # 不能用 default_provider()：它可能返回 "custom"，
                        # 而 choices 是 service_choices()（不含 custom），
                        # 那样新拖出的节点就带一个不在列表里的值。
                        "default": default_service_choice(),
                        "tooltip": (
                            "调用哪一条服务商。列表 = 内置厂商 + 你在 设置 → QG 工具 里添加的条目；只写服务商名就用它的默认模型，写成「服务商/模型」可以指名某个模型。地址、模型、Key 都跟着设置面板那条配置走。"
                        ),
                    },
                ),
                "to_lang": (
                    list(LANGUAGES),
                    {
                        "default": "english",
                        "tooltip": (
                            "翻译成什么语言。默认英文——SAM 3 这类检测模型只认英文。"
                        ),
                    },
                ),
            },
            "optional": {
                "from_lang": (
                    list(LANGUAGES),
                    {
                        "default": "auto",
                        "tooltip": (
                            "原文是什么语言。auto 让模型自己判断；原文很短且有歧义时建议指定。"
                        ),
                    },
                ),
                "api_url": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": (
                            "已移到系统设置，一般不用填。老工作流里如果还留着值，会优先生效。"
                        ),
                    },
                ),
                "model": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": (
                            "已移到系统设置，一般不用填。老工作流里如果还留着值，会优先生效。"
                        ),
                    },
                ),
                "api_key": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": (
                            "已移到系统设置，一般不用填。Key 存在 ComfyUI/user/ComfyUI-QG-Multipack/config.json，插件目录和工作流都不含密钥。这里填的只在本次会话有效，不会写进工作流。"
                        ),
                    },
                ),
                "if_fail": (
                    list(IF_FAIL),
                    {
                        "default": IF_FAIL[0],
                        "tooltip": (
                            "API 连不上或拒绝时怎么办。输出原文：继续运行，文字原样传下去。终止运行：工作流在此停止并给出服务商的报错信息。"
                        ),
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    OUTPUT_TOOLTIPS = ("The translated text.",)
    FUNCTION = "execute"

    @classmethod
    def VALIDATE_INPUTS(cls, provider=""):
        """只接管 provider 这一项的校验，其余输入照常走默认规则。

        老工作流里可能存着 "custom" —— 那是早期下拉里的「空地址占位」，
        用户拖出节点、没改服务商就保存，存下的就是它。这个值现在不在下拉
        里了，默认校验会在**提交阶段**判 ``Value not in list``，而报错里
        只有一个字符串，用户完全不知道要改哪里。

        放行它，让 execute 去报「这个服务商没有配置地址」——那句话才告诉
        用户下一步该做什么。同理，设置面板里删掉一个自定义服务商之后，
        老节点也不会卡在提交这一步。

        只声明 provider：ComfyUI 只对「VALIDATE_INPUTS 签名里出现的参数」
        跳过默认校验，to_lang / if_fail 这些照样受约束。
        """
        return True

    @classmethod
    def IS_CHANGED(cls, text="", provider="", to_lang="", from_lang="auto",
                   api_url="", model="", api_key="", if_fail="", **_kwargs):
        """输入或规则正文变了才重跑。

        这个节点原先没有 ``IS_CHANGED``，ComfyUI 按输入值自行判断，行为本来
        也对。加上它的原因只有一个：**翻译规则不在输入里**（它在 rules.json
        里，由规则管理器编辑）。用户在管理器里改了措辞之后，``translate()``
        的缓存键会跟着变，可节点在缓存判断这一步就被认定「没变」、根本不会
        执行，那层缓存键等于摆设。规则库的指纹只看文件 mtime，不读盘。

        ``api_key`` 只记「有没有填」，不把内容算进哈希。
        """
        digest = hashlib.md5
        blob = "\x1f".join([
            digest(str(text or "").encode("utf-8")).hexdigest(),
            str(provider), str(to_lang), str(from_lang),
            str(api_url), str(model),
            "1" if str(api_key or "").strip() else "0",
            str(if_fail),
            _rules.fingerprint(),
        ])
        return digest(blob.encode("utf-8")).hexdigest()

    def execute(self, text, provider, to_lang, from_lang="auto", api_url="",
                model="", api_key="", if_fail=IF_FAIL[0]):
        strict = str(if_fail) == "stop the run"
        try:
            answer = translate(
                text, provider, api_url, model, api_key, from_lang, to_lang,
                _rules.translate_rule_text(),
            )
        except Exception as error:  # noqa: BLE001 - the switch below decides
            if strict:
                raise
            print(f"[QG-Translate] passing original text through: {error}")
            # 节点原样输出时画布上看不出任何区别，把原因贴到节点下方
            push_notice(f"翻译失败，已原样输出：{error}")
            return (str(text or ""),)
        return (answer,)


NODE_CLASS_MAPPINGS = {"QG_Translate": QGTranslate}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_Translate": "Translate (LLM)"}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
