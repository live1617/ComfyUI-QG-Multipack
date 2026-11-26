# 来源与搬运说明：哪些是原创，哪些是搬运

> 本文档从 README 抽出独立维护（2026-11-25 起，搬运/来源说明不再写进 README，
> README 只留入口引用）。节点功能与使用方法仍在 README「各节点使用说明」；
> 作者、许可证全文与逐项代码拆分见 `THIRD-PARTY-NOTICES.md`。

先给结论。**相似度口径**：把两边文件的空行、纯注释行去掉后逐行比对，只统计「连续 2 行以上完全一致」的块，再除以本包该文件的行数——即「有多少比例的代码是成段照抄的」。只零散碰巧命名相同、或调用同样的 LiteGraph 样板接口，不算。对照对象是本机已安装的同类插件（ComfyUI-RMBG / Goohaitools / Xinbao / ComfyUI-Prompt-Assistant / ComfyUI_essentials）；`QG_MaskByName` 的上游包不在本机，用 `THIRD-PARTY-NOTICES.md` 里对上游 v2.14.0 的实测值。

**「原创」只指代码实现，不指功能概念**：本包多个节点的功能规格 / 控件布局 / 交互形态对齐了第三方插件（见下表「上游 / 参考对象」列），代码是读懂行为后自行编写的。换句话说，这些是「参照规格的独立实现（兼容实现）」，不是自主发明的新功能。唯一复制了第三方代码的是 `QG_MaskByName`（MIT，已署名）。

| 节点 | 来源 | 上游 / 参考对象 | 逐行相似度 |
| --- | --- | --- | --- |
| `QG_MaskByName` | ⚠️ **部分搬运** | ComfyUI-AusBoss「Mask by Name」，MIT / ausboss | **81%**（主文件 225/279 行；helpers 73%） |
| `QG_QwenTextEncode` / `QG_QwenRestore` | ⚠️ GPL 逐行移植 | 功能对齐 Goohaitools「Qwen Image 2.1 文本编码 GH」+「Restore Qwen Image 2.1 GH」（GPL-3.0） | **92.26%**（见下方小节说明：该节点深度依赖 comfy 条件注入内部行为，逐行移植是唯一能保证行为可互换的方式；本包与参考同为 GPL-3.0，已按协议要求在 NOTICES 声明来源） |
| `QG_QwenPromptOptimizer` | ⚠️ GPL 逐行移植 | 功能对齐 Goohaitools「Qwen image 2.1 提示词优化」（`QwenImagePromptOptimizer`，GPL-3.0，后端 + llama-cpp 运行时 + 前端） | runtime **98.94%**（937/947） / 节点 **95.65%**（308/322） / 前端 **84.54%**（257/304）：提示词组装、语言锁、透明背景改写、内存管理与 LLM 采样参数直接决定模型输出与显存行为，逐行移植保证与原版可互换；差异为 qg 前缀标识、路由前缀与中文注释。217 组对照零差异，见下方小节 |
| `QG_FaceRectify` | ✅ 原创 | 思路参考 Goohaitools「Face Rectify」 | 1% |
| `QG_BiRefNet` | ✅ 原创 | 行为对齐 1038lab/ComfyUI-RMBG | 1% |
| `QG_Translate` | ✅ 原创 | — | 1% |
| `QG_ImageToPrompt` | ✅ 原创（含 GPL-3.0 参考） | 控件顺序参考 ComfyUI-Prompt-Assistant；多图合并（image2~image9 动态口、一次请求合并、上限截断）按 MUJUN-2025/ComfyUI-Prompt-Assistant fork 的功能规格独立实现，模型上限映射口径与其 `get_model_max_images` 一致（GPL-3.0） | 0%（对照本机原版）；多图部分为按规格重写，无逐行照抄 |
| `QG_PromptOptimize` | ✅ 原创 | 面板形态参考 ComfyUI-Prompt-Assistant「提示词优化」 | 新建，未比对（HTTP 层与反推节点同源） |
| `QG_PromptTranslate` | ✅ 原创 | — | 0% |
| `QG_IDPhotoParams` | ✅ 原创 | 参数规格参考 HivisionIDPhotos（Apache-2.0） | 0% |
| `QG_PortraitMatte` | ✅ 原创 | 美白 LUT 与参数划分参考 HivisionIDPhotos（Apache-2.0） | 0% |
| `QG_IDPhotoCrop` | ✅ 原创 | 裁剪几何对齐孤海工具箱口径（自实现） | 1% |
| `QG_PhotoSheet` | ✅ 原创 | 排版几何自实现 | 0% |
| `QG_MultiPhotoSheet` | ✅ 原创 | 多人各占一格的拼版几何自实现（纯整数规划），与「一张照片复制多份」的排版节点正交 | 0% |
| `QG_GoogleTranslate` | ⚠️ **MIT 移植** | 思路与实现来自 AlekPet「GoogleTranslateTextNode」（MIT），经自有插件 ComfyUI-QG-tools 中转后移植；免费/官方双通道、分片、双跳重试逻辑逐字保留，V3 节点外壳改写为本包统一的 V1 风格 | **72%**（语言表 106 项与网络层逐字保留；节点外壳与路由新写/改写） |
| `QG_RemoveBackgroundV2` | ✅ 原创（参照规格） | 功能规格参考 LayerStyle「RmBgUltra V2」；粗分割复用本包 BiRefNet，trimap / ViTMatte 推理 / PyMatting / 引导滤波全部独立实现，未复制上游源码 | 0% |
| `QG_IDCardSheet` | ⚠️ GPL 参考后重写 | Goohaitools「身份证自动扶正拼版」（GPL-3.0），三处核心算法已替换 | 未逐项统计（结构/命名沿用） |
| `QG_Watermark` | ✅ 原创 | 斜向水印自实现 | 0% |
| `QG_FaceAlign` | ✅ 原创（参照规格） | 功能规格参考 Goohaitools「孤海-面部对齐」（GPL-3.0）；几何与统计自写，人脸检测复用本包 `_face_helpers`（上游只支持 mediapipe），未复制上游源码 | 0% |
| `QG_IDPhotoOutfit` | ✅ 原创（参照规格） | 功能规格参考 Goohaitools「孤海-证件照服装发型」（GPL-3.0）；扫描与提示词解析逻辑自写，**内置素材取自孤海公开素材库**（7 分类 200 张，见 THIRD-PARTY-NOTICES），前端界面形态与其一致，未复制上游代码 | 0%（代码）/ 素材 100% 同源 |
| `QG_MarriageCloth` | ✅ 原创（参照规格） | 功能规格参考 Goohaitools「孤海-结婚登记照服装」（GPL-3.0）；扫描 / 缩放 / 路径清洗自写，**内置素材取自孤海公开素材库**（81 张，见 THIRD-PARTY-NOTICES），未复制上游代码 | 0%（代码）/ 素材 100% 同源 |
| `QG_MaskTopExpand` | ✅ 原创（参照规格） | 功能规格参考 Goohaitools「孤海-头顶遮罩」（GPL-3.0）；矩形计算自写，并修掉上游丢原遮罩、只处理单帧两个问题，未复制上游代码 | 0% |
| `QG_IDPhotoPrompt` | ✅ 原创（参照规格） | 功能规格参考 Goohaitools「孤海-证件照简易提示词」（GPL-3.0）；13 维选项中文词条取自公开规格（属数据），组装 / 随机 / 值映射自写，未复制上游代码；修掉上游 `random.seed()` 污染进程全局随机与「简单背景」重复叠加 | 0% |
| `QG_PhotoSheetMixed` | ✅ 原创（参照规格） | 功能规格参考 Goohaitools「孤海-证件照排版（A5定制）」（GPL-3.0）；13 个版式用数据表 + 统一排版引擎重写（上游每个版式一段分支、共约 700 行），未复制上游代码；修掉批次只取第一帧、描边撑大网格、超界静默裁切、短 hex 崩溃 | 0% |
| `QG_YoloDetectorLoader` | ✅ 原创（参照规格） | 控件与用途参考 Impact-Subpack 的检测加载器；模型扫描、路径解析、软依赖提示、自造类型全自写，只调 ultralytics 的公开 `YOLO(path)` 接口，类型不与 Impact 互通，未复制上游源码 | 0% |
| `QG_SamModelLoader` | ✅ 原创（参照规格） | 控件与用途参考 Impact-Pack 的 SAM 加载器；权重扫描、类型推断、后端分流（`segment_anything` / `segment_anything_hq`）、设备解析、自造类型全自写，只调它们的公开 `sam_model_registry` / `SamPredictor` 接口，未复制上游源码 | 0% |
| `QG_SimpleSegDetector` | ✅ 原创（参照规格） | 控件与数据流参考 Impact-Pack「简易 Seg 检测」；出框/逐框 SAM 精修/膨胀/质量过滤/自造 QG_SEGS 容器全部自写，类型不与 Impact 互通，另出原生 MASK，未复制上游源码 | 0% |
| `QG_MaskToSeg` | ✅ 原创（参照规格） | 控件语义参考 Impact-Pack「MaskToSeg」；连通域提取/合并/填充 BBox/最小尺寸/填充轮廓/自造 QG_SEGS 全部自写，类型不与 Impact 互通，缺 cv2 有纯 numpy 回退，未复制上游源码 | 0% |

一句话概括：**30 个节点里 28 个自行实现或按 GPL 移植并声明，2 个按 MIT 移植**（`QG_MaskByName` 为 MIT 代码的部分改编、`QG_GoogleTranslate` 为 MIT 实现的移植），且已在 `THIRD-PARTY-NOTICES.md` 里写明作者、上游地址、许可证全文，以及「保留了哪些函数、新写了哪些」的逐项拆分。两个带内置素材的节点（`QG_IDPhotoOutfit`、`QG_MarriageCloth`）另有一节说明素材来源：图与提示词取自 Goohaitools 公开素材库（GPL-3.0），原样复制未修改。

几个容易误会的点：

- **「参考了某个插件」不等于搬运**。`QG_FaceRectify`、`QG_ImageToPrompt`、`QG_PromptOptimize` 都是「先读懂它怎么做的，再自己写」，所以逐行相似度都在 10% 以下，但做的是同一个功能。README 和文件头都如实写明了参考对象。
- **`QG_MaskByName` 是本包里唯一需要特别说明的**。它改编自 AusBoss 的 MIT 代码，节点类、`INPUT_TYPES`、`_detect`、`cut_out` 等成段保留；本包新增的是 SAM 3 权重下拉与加载缓存、权重文件头校验、四步遮罩精修、预览保存。许可证允许这么用，但**必须署名**——所以 `THIRD-PARTY-NOTICES.md` 里那份声明不是可选项。
