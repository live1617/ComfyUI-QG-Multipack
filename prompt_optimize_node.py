# -*- coding: utf-8 -*-
"""QG_PromptOptimize —— 提示词优化：一段粗糙的提示词进去，一段能直接出图的出来。

和 ``QG_ImageToPrompt`` 的关系
------------------------------
反推是「图 → 提示词」，这里是「提示词 → 更好的提示词」，两头共用同一份
服务商配置（``config.json``）和同一套 HTTP/流式/降级实现（
``image_to_prompt_node.ask_text``）。区别只在两处：消息体是纯文本（没有
图片），规则读的是规则库的 ``optimize`` 组而不是 ``image`` 组。

为什么值得单独一个节点
----------------------
改提示词是出图流程里最费时的环节，而「怎么改」比「用哪个模型」更决定效
果：扩写要补细节但必须不换题材，润色只能整理不许加料，改写英文要保住
括号权重和 LoRA 标签。这三件事的指令互相冲突，塞进一个节点只会互相打架，
所以做成规则——和反推节点一样，规则在设置面板里改，节点下拉跟着变。

几个必须照做的地方
------------------
* **user 消息只放原文**。不写「请优化下面这段」这类引导句：那会把「待处理
  的内容」和「对模型的指令」混成一条，模型有时会去回答正文里的问题（正文
  是一句台词、一个疑问句时尤其明显）。任务说明全在 system 里。
* **权重语法要显式保护**。``(word:1.2)``、``[word]``、``<lora:name:0.8>``
  是生图模型才认识的语法，通用大模型看到会当成 Markdown 或笔误顺手改掉。
  每条规则都写明「原样保留」，输出端再兜一次（见 ``clean_answer``）。
* **失败就报错，不原样输出**。翻译节点失败时原样传下去还算合理（下游照样
  能跑）；优化失败却把烂提示词原样吐给下游，用户会以为「优化没生效」，比
  直接报错更难查。
* **种子只进 IS_CHANGED**。固定种子时同一段原文不重复扣费；切成 randomize
  就每跑一次换个写法。
"""

from __future__ import annotations

import hashlib

from . import prompt_rules as _rules
from . import translate_core as _translate
from .image_to_prompt_node import (
    NO_THINKING_HINT, ask_text, clean_answer, release_local_model, stream_pusher,
)

# 优化组被用户整组删空时的兜底名字。下拉至少要有这一项，否则 INPUT_TYPES
# 返回空列表，节点在提交阶段就会被 ComfyUI 拒掉（Value not in list）。
FALLBACK_RULE = _rules.OPTIMIZE_FALLBACK


def text_services() -> list:
    """文本模型下拉：所有配了地址的服务商的「名字 / 名字-模型」。

    直接用 ``translate_core.service_choices()``：它列的是「服务商」加
    「服务商/模型」，翻译节点用的就是这份。视觉模型清单（VISUAL_MODELS）
    在这里不适用——优化是纯文本任务，任何对话模型都能干。
    """
    return _translate.service_choices()


def default_service() -> str:
    """新节点默认用谁。

    逻辑在 ``translate_core.default_service_choice()``：翻译节点、反推节点
    和这里用的是同一个下拉（都是 ``service_choices()``），默认值必须由同一
    份代码算，否则哪天改了规则就会出现「这个节点默认合法、那个节点默认
    非法」的偏差。只保留这个名字给本模块内部调用。
    """
    return _translate.default_service_choice()


def resolve_service(choice: str) -> dict:
    """下拉选项 → 请求要用的地址、模型、Key，缺什么就说什么。"""
    choice = str(choice or "").strip()
    if not choice:
        raise ValueError(
            "QG 提示词优化：没有选择 LLM 服务。节点上选一个，"
            "或者在 设置 → QG 工具 → API 服务商 里先配一家。")
    entry = _translate.resolve_provider(choice)
    provider = str(entry.get("provider") or "").strip()
    url = str(entry.get("api_url") or "").strip()
    model = str(entry.get("model") or "").strip()
    if not url:
        raise ValueError(
            f"QG 提示词优化：服务商「{provider or choice}」没有配置 API 地址。"
            "打开 设置 → QG 工具 → API 服务商 补上，或换成别家。")
    if not model:
        raise ValueError(
            f"QG 提示词优化：服务「{choice}」没有解析出模型名。"
            "自定义服务商请在设置面板里把模型填上。")
    key = str(entry.get("api_key") or "").strip() or _translate.config_api_key()
    return {"provider": provider or choice, "model": model,
            "api_url": url, "api_key": key}


def merge_texts(text, extra_text) -> str:
    """两路文字合成一份：本框里写的 + 上游接进来的。

    中间空一行：提示词本身不带换行语义，空行只是让人在框里看得清分界。
    任意一路为空就不留空行，避免原文前后多出空行。
    """
    parts = [str(text or "").strip(), str(extra_text or "").strip()]
    return "\n\n".join(part for part in parts if part)


class QGPromptOptimize:
    """提示词优化：扩写 / 润色 / 改写英文，规则来自规则库 optimize 组。"""

    CATEGORY = "QG 工具"
    SEARCH_ALIASES = [
        "prompt optimize", "optimize prompt", "prompt enhance", "enhance prompt",
        "提示词优化", "优化提示词", "扩写", "润色", "改写", "提示词扩写",
        "rewrite prompt", "llm", "glm", "qwen", "deepseek", "qg",
    ]

    @classmethod
    def INPUT_TYPES(cls):
        # 只列 optimize 组：反推规则（像素级描述、Tag 标签流…）写的是「怎么
        # 看图」，套到纯文本上会让模型开始描述一段文字「看起来像什么」。
        rules = _rules.node_rule_choices(("optimize",)) or [FALLBACK_RULE]
        current = _rules.active("optimize")
        default_rule = (
            current["name"] if current and current["name"] in rules else rules[0])
        services = text_services()
        default = default_service()
        if default not in services:
            default = services[0]
        return {
            "required": {
                "text": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": (
                            "要优化的提示词，直接写在这里。也可以接上游的文本输出"
                            "（右键这个输入框 → Convert to input），或者用下面的"
                            " extra_text 口——两路会合在一起处理。"
                        ),
                    },
                ),
                "rule": (
                    rules,
                    {
                        "default": default_rule,
                        "tooltip": (
                            "优化规则，来自 设置 → QG 工具 → 提示词规则 的「提示词"
                            "优化规则」页。扩写-通用补细节但保留原意；润色-精炼只"
                            "去重调序、不加料；扩写-细节质感专攻材质与光影；改写-"
                            "英文输出逗号短语，喂 SDXL / Flux。改措辞或加新规则去"
                            "设置面板，这里会自动跟着变。"
                        ),
                    },
                ),
                "custom_rule": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "label_on": "Enable",
                        "label_off": "Disable",
                        "tooltip": (
                            "打开后用下面的「自定义规则」整段替换上面的规则"
                            "（不是追加）。追加会让两套互相矛盾的格式要求打架。"
                        ),
                    },
                ),
                "custom_rule_content": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": (
                            "自定义规则正文，只在「自定义规则」打开时生效。写清"
                            "任务、要补什么、禁止什么、输出形态——这四段缺一段，"
                            "模型就容易自由发挥。"
                        ),
                    },
                ),
                "llm_service": (
                    services,
                    {
                        "default": default,
                        "tooltip": (
                            "用哪家的哪个模型。列表是「服务商」或「服务商/模型」："
                            "地址与 Key 取自 设置 → QG 工具 → API 服务商，节点上"
                            "只选名字，工作流里不落密钥。纯文本任务，任何对话模型"
                            "都能干，不必挑视觉模型。"
                        ),
                    },
                ),
                "auto_unload": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "label_on": "Enable",
                        "label_off": "Disable",
                        "tooltip": (
                            "优化完立刻把本地 Ollama 的模型请出显存，给后面的采样器"
                            "腾地方。云端服务忽略这个开关。"
                        ),
                    },
                ),
                "seed": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 0xffffffffffffffff,
                        "control_after_generate": True,
                        "tooltip": (
                            "不参与推理，只控制节点要不要重跑。固定时同一段原文"
                            "复用上次结果、不重复扣费；切成 randomize 就每跑一次"
                            "换一种写法，用来挑一版最喜欢的。"
                        ),
                    },
                ),
            },
            "optional": {
                "extra_text": (
                    "STRING",
                    {
                        "default": "",
                        "forceInput": True,
                        "tooltip": (
                            "另一路文本，接上游节点用（比如反推出来的提示词）。"
                            "连上就和上面的 text 合在一起优化；不接时忽略。"
                        ),
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("提示词输出",)
    OUTPUT_TOOLTIPS = ("优化后的提示词，可直接接采样器的正向提示词。",)
    FUNCTION = "execute"

    @classmethod
    def VALIDATE_INPUTS(cls, llm_service=""):
        """只接管 ``llm_service`` 一项，其余输入照常走默认校验。

        下拉里现在不列视觉专用模型，老工作流（或设置面板里删掉的自定义
        服务商）可能存着「不在列表里」的值。默认校验会在提交阶段直接判
        ``Value not in list``，用户看不出该改哪；放行它，让 execute 去报
        「没有配置地址」这类能照做的提示。
        """
        return True

    @classmethod
    def IS_CHANGED(cls, text="", rule="", custom_rule=False,
                   custom_rule_content="", llm_service="", auto_unload=True,
                   seed=0, extra_text="", **_kwargs):
        """原文、规则、服务或种子变了才重跑。

        用 md5 而不是内置 ``hash()``：字符串 hash 每个进程带随机盐，重启后
        同一个值算出来不一样，节点会被判成「变了」白跑一次。

        ``rule`` 存的是规则**名字**，正文在 rules.json 里。只把名字拼进
        缓存键的话，用户在规则管理器里改措辞（名字不变）时 ComfyUI 会认为
        输入没变、直接复用上次输出，规则改了等于没改。所以再拼一个规则库
        指纹——它只看文件的 mtime 与大小，不读盘。
        """
        blob = "\x1f".join([
            hashlib.md5(str(text or "").encode("utf-8")).hexdigest(),
            hashlib.md5(str(extra_text or "").encode("utf-8")).hexdigest(),
            str(rule), str(bool(custom_rule)),
            hashlib.md5(str(custom_rule_content or "").encode("utf-8")).hexdigest(),
            str(llm_service), str(bool(auto_unload)), str(seed),
            _rules.fingerprint(),
        ])
        return hashlib.md5(blob.encode("utf-8")).hexdigest()

    def execute(self, text, rule, custom_rule, custom_rule_content,
                llm_service, auto_unload=True, seed=0, extra_text=""):
        source = merge_texts(text, extra_text)
        if not source:
            raise RuntimeError(
                "QG 提示词优化：没有输入。在节点的文本框里写一段提示词，"
                "或者把上游的文本输出接到 extra_text 上。")

        target = resolve_service(llm_service)

        # 规则：自定义开着且写了内容就用它整段替换；否则按名字去 optimize
        # 组取。名字找不到（改过名、规则被删、工作流来自别人）时不崩，退回
        # 内置的扩写规则并打一行日志。
        if custom_rule and str(custom_rule_content or "").strip():
            system_text = str(custom_rule_content).strip()
            rule_name = "自定义规则"
        else:
            picked, fell_back = _rules.resolve(rule, ("optimize",))
            if picked and str(picked.get("content") or "").strip():
                system_text = picked["content"]
                rule_name = picked["name"]
            else:
                system_text = _rules.optimize_fallback_text()
                rule_name = FALLBACK_RULE
                fell_back = True
            if fell_back and str(rule or "").strip() and str(rule) != rule_name:
                print(f"[QG-PromptOptimize] 规则「{rule}」不在优化组里，"
                      f"改用「{rule_name}」。可在 设置 → QG 工具 → 提示词规则 里核对。")
        system_text = system_text + "\n\n" + NO_THINKING_HINT

        print(f"[QG-PromptOptimize] {rule_name} · {llm_service} · "
              f"原文 {len(source)} 字")

        push = stream_pusher("优化")
        on_delta = None
        if push:
            def on_delta(partial):
                push(clean_answer(partial))

        try:
            answer = clean_answer(
                ask_text(system_text, source, target, on_delta))
        except Exception as error:  # noqa: BLE001 - 报错信息要留在节点上
            if push:
                push("优化失败：%s" % error, done=True)
            # 气泡 6 秒就消失，报错原因再挂一条停留更久的提示
            _translate.push_notice(str(error), title="⚠ 优化失败")
            raise
        finally:
            if auto_unload:
                release_local_model(target["provider"], target["model"])

        if not answer:
            raise RuntimeError(
                f"模型「{target['model']}」返回了空结果。可能是它只输出了思考过程，"
                "或者这段原文被判定为无需修改。换个模型或把规则写得更具体一点。")

        if push:
            push(answer, done=True)
        return (answer,)


NODE_CLASS_MAPPINGS = {"QG_PromptOptimize": QGPromptOptimize}
NODE_DISPLAY_NAME_MAPPINGS = {"QG_PromptOptimize": "QG 提示词优化"}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
