# -*- coding: utf-8 -*-
"""提示词规则库：设置面板「规则管理器」读写的那一份,节点按名字来取内容。

为什么要单独抽一个模块
----------------------
规则原本写死在 ``image_to_prompt_node.py`` 的 ``RULES`` 字典里，改一句措辞
就得动代码、重启后端。现在规则是数据：存在 ``rules.json``，面板上增删改，
节点下拉立刻跟着变。**优先放 ComfyUI user 目录**（与 config.json 同一处），
插件装在 Program Files 这类只读位置时也能保存；拿不到 user 目录才回退
插件目录。旧版写在插件目录的那份会在首次访问时复制过去，原文件保留。

分组照 Prompt-Assistant 的做法，每组分四条用途：

* ``optimize``  提示词优化（扩写、润色）
* ``image``     图像反推（图 → 提示词）
* ``video``     视频反推（首帧 → 带运动的提示词）
* ``translate`` 翻译规则（翻提示词时的风格约束）

**每组只能激活一条**（面板上那一列单选圆点），作用是「新节点默认选谁」和
「规则被删了兜底用谁」。图像反推节点仍然可以在下拉里临时选别的规则。

几条实现上的取舍
----------------
* **下拉显示名字，内部认 id**。ComfyUI 的下拉值就是显示出来的那串字，值
  换成 id 的话节点上会显示一排 uuid，所以节点里存的仍是名字。但每条规则
  同时有一个稳定 ``id``：改名时后端把旧名自动记进 ``aliases``，
  ``find()`` 依次按「名字 → id → 旧名」匹配，于是改名的老工作流照样能取到
  改后的正文，而不是悄悄回退到别的规则。
* **缺组才回落到内置**，空组不回落。用户把某一组删干净是明确意图，不能
  每次读盘又给他塞回来——这是「删不掉」类 bug 的常见来源。
* **每组至少一条激活**。全 False 时自动把第一条点亮，否则新拖出来的节点
  没有默认规则可选。
* 写盘走临时文件 + ``os.replace``，写到一半断电不会留下半个 json。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

RULES_FILENAME = "rules.json"
_PACK_DIR = os.path.dirname(os.path.abspath(__file__))
# None = 自动定位（user 目录优先）。测试把它指到临时目录即可完全脱离真文件。
# 显式赋值时一切迁移逻辑都不参与，保证既有测试的行为不变。
RULES_DIR = None
_auto_rules_dir_cache = None
MAX_NAME = 60
MAX_CONTENT = 20000
MAX_PER_GROUP = 200
# 一条规则最多记几个旧名。改十来次名还认得出的情况基本不存在，留个上限
# 防止别名列表无限增长。
MAX_ALIASES = 8
RULES_VERSION = 3

GROUP_ORDER = ("optimize", "image", "video", "translate")

GROUP_LABELS = {
    "optimize": "提示词优化规则",
    "image": "图像反推规则",
    "video": "视频反推规则",
    "translate": "翻译规则",
}

# 面板顶部的说明文字，解释这一组是给谁用的
GROUP_HINTS = {
    "optimize": "把短提示词扩写成完整版本，或按风格润色。",
    "image": "图片反推成提示词：观察顺序、成文格式都写在规则里。",
    "video": "以图片为首帧，写带运动与镜头调度的视频提示词。",
    "translate": "翻译提示词时的风格约束，会拼进翻译请求。",
}

# 输出语言规则。写成公共条款而不是给节点加一个「输出语言」下拉：
# 语言其实只有两种意图——「给我能直接用的提示词」和「我要英文标签」。
# 前者跟随 user prompt 的语言、为空就用中文，后者由具体规则自己锁死英文。
LANGUAGE_RULE = (
    "输出语言：以 user prompt 为准——user prompt 为空时用中文输出；"
    "user prompt 用英文写就用英文，用中文写就用中文。"
    "不要把随图附带的那句固定分析请求当成用户语言。"
)

# 翻译规则默认值：这是百度大模型通道 reference 字段的原文，也是通用通道
# 唯一能表达「别把提示词翻成散文」的地方。
TRANSLATE_RULE = (
    "这是 AI 图像生成提示词。只做语言转换：保持逗号分隔的短语结构，"
    "不要合并成完整句子，不要添加原文没有的描述；保留括号权重语法"
    "（如 (word:1.2)、[word]）、LoRA 标签（如 <lora:name:0.8>）、"
    "数字参数与符号；不要输出任何解释。"
)

_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# 内置默认
# --------------------------------------------------------------------------

# 内置规则改过名的旧名 → 新名。
# 和 aliases 的区别：aliases 是「用户自己改名」时存进 rules.json 的，跟着
# 文件走；这张表写死在代码里，针对的是「内置规则的默认名字变了」——用户从
# 来没保存过 rules.json 时它也在，用来接住老工作流里存的旧字符串。
DEFAULT_RENAMES = {
    "像素级描述（by:阿丹）": "像素级描述",
}


def _default_image_rules() -> list:
    """图像反推的四条内置规则。

    顺序即下拉顺序。每条都写成「观察顺序 + 成文格式 + 禁止项」，而不是
    一句「描述这张图」——模型对结构化指令的服从度明显更高。

    「像素级描述」这条的名字参考自 ComfyUI-Prompt-Assistant 的同名规则
    （by:阿丹），正文是按本节点重写的精简版（本包 584 字，上游 2188 字，
    相同率 0.11），所以不带他人署名——把别人的名字挂在自己写的内容上会
    误导读者。规则名变更由上面的 DEFAULT_RENAMES 兼容。
    """
    return [
        {
            "name": "像素级描述",
            "content": (
                "你是一名专业的 AI 生图提示词工程师，任务是把参考图反推成能复现画面的提示词。\n\n"
                "最高指令\n"
                "1. " + LANGUAGE_RULE + "\n"
                "2. 格式绝对纯净：只输出提示词正文。不要 Markdown 标记，不要中英对照，"
                "不要「以下是」「这张图片显示了」这类前言，不要任何解释。\n"
                "3. 不臆造：画面里看不见的东西一律不写，宁可少写也不要补。\n\n"
                "观察顺序（按这个顺序看，不要跳）\n"
                "主体：数量、身份与年龄感、体型、表情、视线方向、手部动作与持物。\n"
                "服装：品类、材质、版型、颜色、穿法、褶皱与垂坠。\n"
                "构图：景别（特写/半身/全身/远景）、机位高低、主体在画面中的位置与占比、"
                "前中后景的层次。\n"
                "环境：地点、时间、天气、地面与墙面材质、背景里的具体物件。\n"
                "光线：主光方向、软硬、色温、高光落点、阴影朝向、大气透视。\n"
                "色彩：主色、辅色、饱和度与对比度、是否偏色。\n"
                "质感与风格：摄影还是绘画、镜头焦段感、景深、颗粒、渲染风格。\n\n"
                "成文要求\n"
                "按「主体—服装—构图—环境—光线—色彩—风格」的顺序写成连贯段落，"
                "200 到 400 字。用具体名词和可见细节，不要「很美」「氛围感」「高级感」"
                "这类空话。数字、品牌名、专有名词保持原样。"
            ),
            "enabled": True,
        },
        {
            "name": "Tag 标签流",
            "content": (
                "你是 Stable Diffusion 的标签工程师。把画面拆成 Danbooru 风格的标签流。\n\n"
                "输出语言：标签默认用英文（SD 生态的通用写法）；只有 user prompt "
                "明确要求中文标签时才用中文。\n"
                "输出格式：单个标签串，逗号加空格分隔，全部小写（专有名词除外），"
                "按重要度从高到低排列，共 30 到 60 个标签。\n"
                "标签顺序：质量词 → 主体与人数 → 面部与表情 → 服装 → 动作姿态 → "
                "视角与镜头 → 背景环境 → 光线 → 色彩 → 画风。\n"
                "权重：主体和关键元素写成 (tag:1.2)，次要元素写成 (tag:0.8)，其余不加权重。\n"
                "禁止：完整句子、编号、解释、同一条标签里中英混排、"
                "Markdown 标记、画面里没有的元素。\n"
                "只输出标签串本身。"
            ),
            "enabled": False,
        },
        {
            "name": "自然语言短描述",
            "content": (
                "Write one English paragraph of 60 to 90 words describing this image as a "
                "text-to-image prompt.\n\n"
                "Always answer in English, even when the request text is written in another "
                "language - this rule exists to feed English-only models such as SDXL and "
                "Flux.\n\n"
                "Lead with the subject and what it is doing, then the setting, then the light, "
                "then the photographic look (lens, depth of field, colour grade).\n"
                "Use concrete nouns and observable details only; no metaphor, no mood words "
                "such as 'beautiful' or 'cinematic vibe', no watermark or UI if they are not "
                "part of the scene.\n"
                "Output the paragraph only - no title, no quotes, no explanation."
            ),
            "enabled": False,
        },
        {
            "name": "图像编辑指令",
            "content": (
                "你是图像编辑模型的指令工程师。结合画面内容和 user prompt 里的修改意图，"
                "输出一条可直接执行的编辑指令。\n\n"
                + LANGUAGE_RULE + "\n"
                "1. 意图优先：user prompt 指定的改动是最高优先级，即使它与原图状态冲突。\n"
                "2. 锁定对象：先把指令里指代的目标识别出来（「那个」「左边那个」），"
                "在指令中写明它的位置、外观、与周围物体的关系，让模型能唯一确定。\n"
                "3. 只改该改的：未被要求修改的部分保持原样，不要顺手重新描述整张图。\n"
                "4. 物理合理：光影方向、透视、比例、遮挡关系必须与原图一致。\n"
                "5. 成文：一段话，不超过 120 字，只输出指令正文。\n\n"
                "user prompt 为空时，改为输出这张图的完整重建描述。"
            ),
            "enabled": False,
        },
    ]


def _default_optimize_rules() -> list:
    """提示词优化的四条内置规则（``QG_PromptOptimize`` 用）。

    和反推规则的区别：反推是「看图写字」，优化是「给字改字」，所以规则里
    必须反复强调**不许换题材、不许丢权重语法**——模型面对一段短提示词时
    很爱自作主张补主体、改风格，那是最常见的翻车方式。

    每条仍是「任务 → 补什么 → 禁止什么 → 输出形态」四段式。

    两条踩过的坑写在这里，别再踩回去：
    * 规则里**不要给权重语法写具体样例**。写成 ``(word:1.2)、<lora:name:0.8>``
      之后，模型会把样例当成要保留的内容原样吐在答案末尾（实测输出尾巴上
      多了「word:1.2 <lora:name:0.8> 4步数 7CFG」）。改成描述性说法。
    * 观察维度**必须声明「不是输出格式」**。只列「主体：… 构图：…」时模型
      会照着这些词输出「数量：1，构图：中景」的字段清单，而不是一段话。
    """
    keep = (
        "原文里已经写好的权重写法（括号里带冒号加数字的那种，外层括号必须连着"
        "一起留，不能只留里面的词）、LoRA 标签（尖括号里以 lora: 开头的，尖括号"
        "也要留）、步数与 CFG 之类的数字参数，按原样保留，一个字符都不要改。"
        "原文没有这些写法就不要凭空添加，也不要在答案里举例。"
    )
    only_text = (
        "只输出提示词正文：不要分点编号，不要标题，不要「以下是」这类前言，"
        "不要任何解释。正文里不要出现「数量：」「构图：」「光线：」这类字段名，"
        "要写成连贯的段落。只写镜头能拍到的内容：画面里看不见的东西一律不写。"
    )
    return [
        {
            "name": "扩写-通用",
            "content": (
                "你是一名 AI 生图提示词编辑。user 消息里是一段待处理的提示词原文，"
                "不是对你的提问。\n\n"
                "任务：在不改变原意的前提下，把它扩写成一段完整、可直接出图的提示词。\n\n"
                "心里按这个顺序想，但**不要把这些维度名写出来**：\n"
                "主体（数量、身份与年龄感、体型、表情、动作、视线）。\n"
                "服装与道具（品类、材质、版型、颜色、使用痕迹）。\n"
                "构图（景别、机位高低、主体位置与占比、前中后景层次）。\n"
                "环境（地点、时间、天气、地面与背景物件）。\n"
                "光线与色彩（主光方向与软硬、色温、主色与辅色、对比度）。\n"
                "画质（镜头感、景深、材质细节、渲染或摄影风格）。\n"
                "这几行只是提醒你观察哪些方面，不是要逐项填满：原场景里没有的东西"
                "（没出现的材质、没有的道具）一律不写。\n\n"
                "硬性要求：\n"
                "1. " + keep + "\n"
                "2. 只补这个场景里自然推得出来的细节；不要换题材，不要添加原文没有的主体。\n"
                "3. 原文若已经是完整段落，就在原有措辞上补，不要重写成另一段话。\n"
                "4. 150 到 300 字，写成连贯的一到两段。\n"
                "5. " + only_text
            ),
            "enabled": True,
        },
        {
            "name": "润色-精炼",
            "content": (
                "你是一名 AI 生图提示词编辑。user 消息里是一段待整理的提示词原文。\n\n"
                "任务：整理成规范的提示词串，**不扩写**。\n\n"
                "输出格式（先看这条）：一条提示词，元素之间用中文逗号「，」分隔；"
                "每个元素是 2 到 8 个字的短语（名词加上必要的修饰），"
                "例如「蓝色连衣裙」「海浪起伏」。不要拆成孤立的单字，"
                "不要用空格分隔，不要写成一句话。\n\n"
                "整理规则：\n"
                "1. **每个具体元素都要留下**：物件、颜色、动作、位置一样都不能丢。\n"
                "2. 去重只去掉重复出现的同一个词；那些夸气氛、夸好看、却指不出具体东西的"
                "形容词一律删掉（不管它是哪几个字），一个都不要留。\n"
                "3. 顺序：主体，服装道具，动作，构图镜头，环境，光线，色彩，画质风格。\n"
                "4. 不添加原文没有的元素；改完的正文不能短于原文的 60%。\n"
                "5. " + keep + "\n"
                "6. " + only_text
            ),
            "enabled": False,
        },
        {
            "name": "扩写-细节质感",
            "content": (
                "你是一名 AI 生图提示词编辑。user 消息里是一段待扩写的提示词原文。\n\n"
                "任务：保持原意与题材不变，重点把「材质与光影」写到能出片的程度。\n"
                "下面几类只是提醒你观察哪些方面，**只写场景里真实存在的**：\n"
                "木工房里没有织物就不要写织物，没有皮革就不要写皮革，"
                "人物不在画面里就不要写皮肤。宁可少写一类，也不要硬塞。\n"
                "材质——织物的纹理与厚薄、皮革的磨损、金属的反射与氧化、皮肤的质感与"
                "次表面散射、玻璃与水的折射。\n"
                "光影——主光方向与软硬、高光的具体形状与落点、阴影边缘的虚实、"
                "逆光时的轮廓光、环境反射带来的补色。\n"
                "镜头——焦段感（广角畸变或长焦压缩）、景深范围、焦外形状、"
                "轻微颗粒或色差。\n\n"
                "禁止：堆砌夸气氛的形容词——凡是说不出具体形状、材质、颜色的修饰语都不要；"
                "不要引入原文没有的主体或场景。\n"
                "1. " + keep + "\n"
                "2. 200 到 350 字，连贯段落。\n"
                "3. " + only_text
            ),
            "enabled": False,
        },
        {
            "name": "改写-英文",
            "content": (
                "You are a prompt editor for text-to-image models. The user message is a "
                "prompt to rewrite, not a question addressed to you.\n\n"
                "Task: rewrite that prompt in English for English-only models such as SDXL, "
                "Flux and SD3. Keep the original intent, subject and level of detail.\n\n"
                "Rules:\n"
                "1. Output comma-separated phrases, not full sentences.\n"
                "2. Order: quality words - subject - clothing and props - pose - "
                "composition and lens - setting - lighting - colour - style.\n"
                "3. Keep every existing weight group exactly as written, INCLUDING its "
                "outer brackets and the colon-number part. A weight that looks like a word "
                "with a colon and a number must stay wrapped in brackets - never output the "
                "bare word:number. Keep LoRA tags with their angle brackets, and keep every "
                "numeric parameter. If the original has none, do not invent any and do not "
                "show examples.\n"
                "4. Do not translate proper nouns (people, brands, titles, place names).\n"
                "5. Do not add subjects or elements that are not in the original.\n"
                "6. Output one plain phrase list - no field names such as 'subject:' or "
                "'lighting:', no heading, no notes, no explanation. Describe only what is "
                "visible - no sounds, smells, temperature or other non-visual senses."
            ),
            "enabled": False,
        },
    ]


def _default_video_rules() -> list:
    return [
        {
            "name": "视频动态提示词",
            "content": (
                "以这张图作为视频首帧，写一段视频生成提示词。\n\n"
                + LANGUAGE_RULE + "\n"
                "结构：先用一句话交代静态画面（主体、场景、光线、风格），再写运动。\n"
                "运动要写清楚：主体动作的幅度与方向、速度感；头发、衣物、飘带的随动；"
                "镜头运动（推、拉、摇、移、跟拍，或固定机位）；环境动态（风、水、烟、"
                "行人、光斑）。\n"
                "时长按 3 到 5 秒写，不要出现分镜编号和时间码。一段话，150 字以内。\n"
                "只输出提示词正文。"
            ),
            "enabled": True,
        },
    ]


def _default_translate_rules() -> list:
    return [{"name": "提示词翻译（默认）", "content": TRANSLATE_RULE, "enabled": True}]


#
# 优化组的兜底名字。下拉至少要有一项，否则 INPUT_TYPES 给出空列表，节点会
# 在提交阶段就被拒（Value not in list）；用户把整组删空时就用它。
OPTIMIZE_FALLBACK = "扩写-通用"


def optimize_fallback_text() -> str:
    """优化组被删空时用的正文：内置「扩写-通用」那条。

    兜底走代码里的常量而不是 rules.json，是为了「用户删组」这件事不连带
    把节点搞坏——节点还能跑，只是用回了出厂规则。
    """
    for item in _default_optimize_rules():
        if item["name"] == OPTIMIZE_FALLBACK:
            return item["content"]
    return ""


def default_rules() -> dict:
    """全新安装时的四组规则。

    ``optimize`` 组在 v3 之前是空的（那时还没有优化节点），现在由
    ``QG_PromptOptimize`` 使用，所以给了四条内置规则；老文件由
    ``load_rules()`` 里的一次性补种接住。
    """
    return {
        "optimize": _default_optimize_rules(),
        "image": _default_image_rules(),
        "video": _default_video_rules(),
        "translate": _default_translate_rules(),
    }


# --------------------------------------------------------------------------
# 读写
# --------------------------------------------------------------------------

def _auto_rules_dir() -> str:
    """定位可写的规则目录，结果缓存一次（IS_CHANGED 每次提交都会调这里）。"""
    global _auto_rules_dir_cache
    if _auto_rules_dir_cache:
        return _auto_rules_dir_cache
    try:
        from folder_paths import get_user_directory
        base = os.path.join(get_user_directory(), "ComfyUI-QG-Multipack")
        os.makedirs(base, exist_ok=True)
    except Exception:  # noqa: BLE001 - 裸单测 / 只读介质
        base = _PACK_DIR
    _auto_rules_dir_cache = base
    return base


def _seed_user_rules(path: str) -> None:
    """把旧版写在插件目录的 rules.json 复制一份到 user 目录，原文件保留。

    刻意用「复制」而不是 ``os.replace`` 迁移：8177 测试实例与 8188 共用
    同一个 custom_nodes 插件目录，却各有自己的 user 目录，谁先把原文件搬走，
    另一个就会退回内置默认规则、丢掉用户自定义内容。复制让每个实例各持有
    一份，插件目录也不缺文件。写盘仍走临时文件 + os.replace。
    """
    legacy = os.path.join(_PACK_DIR, RULES_FILENAME)
    if os.path.exists(path) or not os.path.exists(legacy):
        return
    if os.path.abspath(legacy) == os.path.abspath(path):
        return
    tmp_name = None
    try:
        with open(legacy, "r", encoding="utf-8") as handle:
            data = handle.read()
        with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=os.path.dirname(path),
                prefix=".rules-", suffix=".json", delete=False) as tmp:
            tmp_name = tmp.name
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
        tmp_name = None
        print("[QG-Multipack] 已把插件目录的 rules.json 复制到 user 目录"
              "（原文件保留）")
    except (OSError, ValueError):
        pass
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def rules_path() -> str:
    if RULES_DIR is not None:      # 测试显式指定的临时目录，不参与任何迁移
        return os.path.join(RULES_DIR, RULES_FILENAME)
    path = os.path.join(_auto_rules_dir(), RULES_FILENAME)
    if not os.path.exists(path):
        _seed_user_rules(path)
    return path


def fingerprint() -> str:
    """规则库的短指纹：内容一改，读它的节点缓存就该失效。

    为什么是 mtime 而不是内容哈希：``IS_CHANGED`` 每次提交都会被每个
    节点各调一次，每次都把整份 rules.json 读进来算哈希是白费磁盘；而
    这份文件只经由 ``save_rules`` 的 ``os.replace`` 改动，替换后 mtime
    一定会变，拿它当「有没有改过」的信号足够准。

    文件不存在时返回版本号：这时节点用的是代码里的内置默认规则，默认
    规则变过一定会顺手改 ``RULES_VERSION``。
    """
    try:
        stat = os.stat(rules_path())
    except OSError:
        return "v%d" % RULES_VERSION
    return "%d:%d" % (stat.st_mtime_ns, stat.st_size)


def _as_text(value) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


def _make_id(seed: str, taken: set) -> str:
    """按种子派生一个稳定短 id；撞了就加后缀。

    用名字做种子是为了「老文件里没有 id」时也能得到确定值——每次读盘都
    算出同一个 id，不会因为进程重启而对不上。id 一旦落盘就不再变，之后
    改名也不会动它，这才是它能当稳定主键的前提。
    """
    base = hashlib.md5(str(seed).encode("utf-8")).hexdigest()[:10]
    candidate = base
    suffix = 2
    while candidate in taken:
        candidate = "%s-%d" % (base, suffix)
        suffix += 1
    return candidate


def _clean_aliases(raw, name: str) -> list:
    """旧名列表：去空、去重、去掉和当前名字相同的。"""
    out = []
    values = raw if isinstance(raw, (list, tuple)) else []
    for item in values:
        alias = _as_text(item).strip()[:MAX_NAME]
        if alias and alias != name and alias not in out:
            out.append(alias)
    return out[:MAX_ALIASES]


def _clean_group(items, taken_ids: set = None) -> list:
    """一组规则去重 + 截断 + 保证有且只有一条激活。

    ``taken_ids`` 是跨组共用的 id 池：节点的下拉跨三组，id 只在一组内唯一
    是不够的。
    """
    out = []
    seen = set()
    taken_ids = taken_ids if taken_ids is not None else set()
    if not isinstance(items, list):
        return out
    for raw in items[:MAX_PER_GROUP]:
        if not isinstance(raw, dict):
            continue
        name = _as_text(raw.get("name")).strip()[:MAX_NAME]
        if not name or name in seen:
            continue
        seen.add(name)
        rule_id = _as_text(raw.get("id")).strip()[:40]
        if not rule_id or rule_id in taken_ids:
            rule_id = _make_id(name if not rule_id else rule_id, taken_ids)
        taken_ids.add(rule_id)
        out.append({
            "id": rule_id,
            "name": name,
            "aliases": _clean_aliases(raw.get("aliases"), name),
            "content": _as_text(raw.get("content")).strip()[:MAX_CONTENT],
            "enabled": bool(raw.get("enabled")),
        })
    if out:
        if not any(item["enabled"] for item in out):
            out[0]["enabled"] = True
        else:
            # 只留第一条为 True，避免面板上出现两个圆点
            lit = False
            for item in out:
                if item["enabled"]:
                    if lit:
                        item["enabled"] = False
                    lit = True
    return out


def _sanitize_aliases(groups: dict) -> dict:
    """去掉会和「现有名字」撞车的别名。

    别名的作用是接住改名前的旧名字。如果用户后来又把某条规则改成了那个
    旧名字，别名就该让位给真实的名字，否则两条会争同一个匹配键。
    """
    all_names = {item["name"] for items in groups.values() for item in items}
    for items in groups.values():
        for item in items:
            keep = [a for a in item.get("aliases", []) if a not in all_names]
            item["aliases"] = keep[:MAX_ALIASES]
    return groups


def clean(data) -> dict:
    """把任意输入整理成合法结构：缺的组补默认，空组保留空。"""
    base = default_rules()
    if not isinstance(data, dict):
        return base
    groups = data.get("groups") if isinstance(data.get("groups"), dict) else data
    out = {}
    taken_ids = set()
    for key in GROUP_ORDER:
        if key in groups:
            out[key] = _clean_group(groups.get(key), taken_ids)
        else:
            out[key] = _clean_group(base[key], taken_ids)
    return _sanitize_aliases(out)


def _legacy_optimize(version) -> bool:
    """这份文件里的「优化组为空」是不是历史遗留（而不是用户主动删空）。

    v3 之前没有优化节点，规则管理器里那一页永远是空的——用户保存过多少次
    都还是空，所以不能把空当成「他就想要空的」。打完补丁并保存一次之后，
    文件版本变成 3，此后用户再删空就是明确意图，不再补。
    """
    try:
        return int(version) < 3
    except (TypeError, ValueError):
        return True          # 没有 version 字段 = 更老的文件


def _seed_optimize(groups: dict) -> dict:
    """把内置扩写规则补进空的优化组，重新过一遍 clean 分配 id。"""
    base = default_rules()
    return clean({"groups": {**groups, "optimize": base["optimize"]}})


def load_rules() -> dict:
    """读 rules.json；文件不存在就返回内置默认（不急着写盘）。

    默认值也过一遍 ``clean()``：内置规则在代码里只写了名字和正文，id 与
    aliases 由 clean 现算，这样没保存过规则的用户也能拿到完整的结构。
    """
    path = rules_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return clean(default_rules())
    out = clean(data)
    if not out.get("optimize") and _legacy_optimize(data.get("version")):
        return _seed_optimize(out)
    return out


def save_rules(data) -> dict:
    """规范化后原子写盘，返回真正存进去的那份。

    保存前先和磁盘上的旧数据按 id 对一遍：名字变了就把旧名字塞进
    ``aliases``。这一步放在后端而不是前端，是因为改名可能来自任何入口
    （面板、脚本、将来的导入功能），兜在写盘这一层才不会漏。
    """
    cleaned = clean(data)
    before = load_rules()
    old_by_id = {item["id"]: item for items in before.values() for item in items}
    renamed = False
    for items in cleaned.values():
        for item in items:
            old = old_by_id.get(item["id"])
            if not old or old["name"] == item["name"]:
                continue
            alias = old["name"]
            if alias and alias != item["name"] and alias not in item["aliases"]:
                item["aliases"].insert(0, alias)
                del item["aliases"][MAX_ALIASES:]
                renamed = True
    if renamed:
        cleaned = _sanitize_aliases(cleaned)

    payload = {"version": RULES_VERSION, "groups": cleaned}
    path = rules_path()
    # user 目录可能在读到路径之后被外部清掉；写盘前补一次，避免
    # NamedTemporaryFile(dir=...) 直接抛 FileNotFoundError。
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with _LOCK:
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=os.path.dirname(path),
            prefix=".rules-", suffix=".json", delete=False)
        try:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, path)
    return cleaned


# --------------------------------------------------------------------------
# 查询
# --------------------------------------------------------------------------

def flatten(groups=None) -> list:
    """按组顺序摊平成一维，每项补上 group 字段。"""
    data = load_rules()
    keys = [g for g in GROUP_ORDER if groups is None or g in groups]
    out = []
    for key in keys:
        for item in data.get(key, []):
            out.append({**item, "group": key})
    return out


def names(groups=None) -> list:
    return [item["name"] for item in flatten(groups)]


def find(name, groups=None):
    """按名字找规则；``groups`` 限定只在某几组里找。

    匹配顺序是「当前名字 → id → 旧名」：节点下拉和给用户看的都是名字，
    但工作流里存的值可能来自改名之前，或者来自直接写 id 的脚本。三条
    路径都认，改名才不会把老工作流打断。
    """
    key = _as_text(name).strip()
    if not key:
        return None
    items = flatten(groups)
    for item in items:
        if item["name"] == key:
            return item
    for item in items:
        if item.get("id") == key:
            return item
    for item in items:
        if key in (item.get("aliases") or []):
            return item
    # 内置规则改过名：旧名字经 DEFAULT_RENAMES 指向新名字，再按新名字找一遍。
    renamed = DEFAULT_RENAMES.get(key)
    if renamed and renamed != key:
        return find(renamed, groups)
    return None


def active(group: str):
    """某组当前激活的那条，没有就退回第一条。"""
    items = load_rules().get(group) or []
    if not items:
        return None
    for item in items:
        if item.get("enabled"):
            return {**item, "group": group}
    return {**items[0], "group": group}


def resolve(name, groups=None) -> tuple:
    """节点用的取值入口：返回 (规则条目, 是否回退过)。

    名字找不到（用户改过名、删过规则、工作流来自别人）时退回该组的激活
    规则，不抛错——一个存量的工作流不该因为规则改名就跑不动。
    """
    hit = find(name, groups)
    if hit:
        return hit, False
    for group in (groups or GROUP_ORDER):
        fallback = active(group)
        if fallback:
            return fallback, True
    return None, True


def node_rule_names(groups=("optimize", "image", "video")) -> list:
    """节点下拉的纯名字：默认优化 + 反推 + 视频三组，翻译规则不参与。"""
    return names(groups)


def node_rule_choices(groups=("optimize", "image", "video")) -> list:
    """INPUT_TYPES 用的选项：当前名字 + 所有旧名。

    ComfyUI 在提交工作流时会拿 ``INPUT_TYPES`` 返回的列表做校验，值不在
    列表里就直接拒收（``Value not in list``）——那样 ``resolve()`` 支持别名
    也白搭，老工作流根本走不到执行。所以校验列表必须把旧名也放进去。

    前端的下拉只用纯名字（``CONFIG.rules.node_rules``），所以用户看不到
    这串旧名；它只为让存量工作流通过校验。

    ``groups`` 默认是三组（图像反推节点用）；优化节点传 ``("optimize",)``
    只要自己那一组，免得下拉里混进「像素级描述」这种反推规则。
    """
    groups = tuple(groups)
    out = names(groups)
    for item in flatten(groups):
        for alias in item.get("aliases") or []:
            if alias not in out:
                out.append(alias)
    # 内置规则改名前的老名字：用户没保存过 rules.json 时 aliases 里没有它，
    # 但老工作流存的正是这个字符串，缺了就会在提交时被判 Value not in list。
    for old, new in DEFAULT_RENAMES.items():
        if new in out and old not in out:
            out.append(old)
    return out


def translate_rule_text() -> str:
    """翻译节点用的规则正文，没有就返回空串（退回默认的翻译指令）。"""
    item = active("translate")
    return item["content"] if item else ""


def summary() -> dict:
    """给前端用的轻量摘要：组名、组内名称、激活项。不含正文。"""
    data = load_rules()
    return {
        "order": list(GROUP_ORDER),
        "labels": GROUP_LABELS,
        "hints": GROUP_HINTS,
        "groups": {
            key: {
                "names": [item["name"] for item in data.get(key, [])],
                "ids": [item["id"] for item in data.get(key, [])],
                "active": next(
                    (item["name"] for item in data.get(key, []) if item.get("enabled")), ""),
            }
            for key in GROUP_ORDER
        },
        "node_rules": node_rule_names(),
    }
