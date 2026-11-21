# QG 工具（ComfyUI-QG-Multipack）

> 当前版本：**v2.19.0** ｜ 版本号真源在插件根目录 `VERSION` 文件；每次修改节点后递增版本号，并打包备份到 `D:\插件开发\ComfyUI-QG-Multipack-vX.Y.Z.zip`。

ComfyUI 自定义节点包，界面里的品牌名是「QG 工具」，节点都收在 **添加节点 → QG 工具** 分类下。

目录名 `ComfyUI-QG-Multipack`。早期叫 `0-QYH-SnapLines`（那时包里只有拖动对齐参考线），后来陆续并入翻译、反推、提示词优化、计时器、注释、抠图等节点，2026-11 改成现在的名字，前缀也换成了 ComfyUI 官方的 `ComfyUI-` 规范。

## 节点一览

| 节点 key | 显示名 | 作用 | 输出 |
| --- | --- | --- | --- |
| `QG_BiRefNet` | QG BiRefNet 去除背景 | 18 个抠图模型的统一入口（18 个模型见下文） | `IMAGE` / `MASK` / `MASK_IMAGE` |
| `QG_MaskByName` | Mask by Name | 输入一句话（如 "the girl's hair"），用 ComfyUI 内置 SAM 3 找出对应区域（需自备 SAM 3 权重，见[安装](#安装)） | `MASK` / `cut_out` / `found` |
| `QG_QwenTextEncode` | Qwen Image 2.1 文本编码 | Qwen Image 2.1 专用条件编码：最多 10 张参考图（输入口动态增减）+ 填充/裁剪 + 局部遮罩，一次出 positive / negative / 初始 latent / 还原信息 | `positive` / `negative` / `latent` / `info` |
| `QG_QwenRestore` | 还原 Qwen Image 2.1 画布 | 吃上面节点的 `info`，把「填充」模式加的灰边画布按比例裁回去（与本包或 Goohaitools 原版的 info 均可互连） | `image` |
| `QG_QwenPromptOptimizer` | Qwen image 2.1 提示词优化 | 本地 llama-cpp 反推/优化提示词：接图+空提示词=看图反推完整生成提示词，接图+有提示词=按指令改写，不接图=文生图扩写；需 `models/LLM` 下的 Qwen GGUF + mmproj，依赖缺失时节点内按钮给出手动安装指引 | `prompt` / `json` / `是否反推` |
| `QG_Translate` | LLM 翻译 | 调 DeepSeek / Kimi / 通义 / 智谱 / 硅基流动 / OpenRouter / 本地 Ollama 等 OpenAI 兼容接口做翻译 | `text` |
| `QG_PromptTranslate` | 提示词翻译 | 原文进、译好的提示词出；服务可选两条百度通道（通用 / 大模型）或任一已配服务商，目标语言 / 自动释放显存 / 种子四个控件 | `translated_text` |
| `QG_ImageToPrompt` | 图像反推提示词 | 图片进、提示词出：规则来自设置里的规则管理器（内置 5 条：像素级描述 / Tag 标签流 / 自然语言短描述 / 图像编辑指令 / 视频动态提示词），视觉模型按「服务商/模型」选，**边推理边在节点下方出字**，batch 逐帧反推 | `提示词输出` / `提示词列表` |
| `QG_PromptOptimize` | 提示词优化 | 提示词进、更好的提示词出：规则取「提示词优化规则」组（内置 4 条：扩写-通用 / 润色-精炼 / 扩写-细节质感 / 改写-英文），保留括号权重与 LoRA 标签，**边生成边在节点下方出字**，可接上游文本两路合并 | `提示词输出` |
| `QG_FaceRectify` | Face Rectify | 自动把人脸转正：先按 90° 粗扫矫正横躺/倒置，再用 5 点 landmark 纠正倾斜，最后统一裁边 | `image` |
| `QG_IDPhotoParams` | QG 证件照参数 | 尺寸/底色/渲染/dpi 集中一路传出，供抠图与排版节点复用 | `params` / `宽` / `高` / `DPI` / `主色` |
| `QG_PortraitMatte` | QG 人像抠图换背景 | 抠图→换底→美颜→按证件照构图裁好（可选 mediapipe 人脸对齐） | `成品图` / `蒙版` / `高清图` |
| `QG_IDPhotoCrop` | QG 证件照裁剪 | 把已有照片裁成指定尺寸、眼睛摆平（不抠图） | `裁剪后图像` / `扩展遮罩` / `是否扩图` / `DPI` / `定位示意图` |
| `QG_IDPhotoSizePicker` | QG 证件照尺寸选择 | 一处选好尺寸，`preset` 直接连裁剪 / 参数节点的预设下拉，另出像素宽高与 DPI | `预设` / `宽` / `高` / `DPI` |
| `QG_PhotoSheet` | QG 照片排版 | 铺满相纸、画裁切角标、放不下自动缩 | `排版图像` / `列数` / `行数` / `总张数` |
| `QG_MultiPhotoSheet` | QG 多人证件照拼版 | 多人的照片各占一格拼到同一张纸，统一格居中裁切、列数指定行数自动 | `拼版图像` / `行数` / `列数` / `人数` |
| `QG_ImageBatchBuilder` | QG 图像批次组合 | 输入槽动态增减（默认 1 个，接一个加一个，上限 24），接几张合几张成 batch，省掉串一堆「合并图像」节点 | `image` / `count` |
| `QG_RemoveBackgroundV2` | QG 移除背景 V2 · 细节精修 | 本包 BiRefNet 粗分割 + 五种边缘精修（VITMatte / VITMatte(local) / base / PyMatting / GuidedFilter），腐蚀膨胀控制 trimap、黑白点拉伸 alpha，输出透明 RGBA 与遮罩 | `IMAGE` / `MASK` |
| `QG_IDCardSheet` | QG 身份证拼版 | 拍歪的卡片找四角扶正、加圆角投影、按厘米铺到纸上 | `IMAGE` |
| `QG_Watermark` | QG 斜向水印 | 斜向平铺文字水印（默认用随包 OFL 中文字体，中文不再成方框） | `IMAGE` |
| `QG_DualColorPicker` | QG 双色取色器 | 一次输出模式 + 主色 + 辅色三路字符串，颜色控件点开弹出色板 | `模式` / `主色` / `辅色` |
| `QG_ColorPicker` | QG 取色器 | 点色块选一个颜色，按 HEX / RGB / HSL 输出颜色值与字符串，可作工作流颜色起点 | `颜色控件` / `字符串` |
| `QG_ColorConvert` | QG 颜色转换 | 把 hex / RGB / HSL / 0-1 浮点等写法互转成目标格式，另出一路规范化 hex | `字符串` / `颜色控件` |
| `QG_CustomColor` | QG 自定义颜色 | 按宽高生成纯色 / 上下渐变 / 中心渐变底图，可加灰度颗粒 | `图像` |
| `QG_DominantColor` | QG 主色提取 | 统计图像出现最多的颜色（降采样 + 滤黑边白边 + 容差分桶），输出大写 `#RRGGBB` | `主色 HEX` |
| `QG_FaceAlign` | QG 面部对齐 | 目标图人脸按参考图缩放/旋转对齐后裁回参考尺寸；无参考图时仅摆平角度 | `图像` |
| `QG_IDPhotoOutfit` | QG 证件照服装发型 | 面板网格选服装/发型模板出提示词（内置 7 分类 200 张，可自行补图） | `提示词` |
| `QG_MarriageCloth` | QG 结婚登记照服装 | 面板画廊选服装参考图，出一张 IMAGE 给图生图（内置 81 张，序号 0 = 纯色底） | `image` |
| `QG_MaskTopExpand` | QG 头顶遮罩扩展 | 从遮罩最高点向上补矩形，给外补画板留发量空间（可羽化、可合并原遮罩） | `mask` |
| `QG_IDPhotoPrompt` | QG 证件照简易提示词 | 13 维下拉 + seed 组合成一句中文人像提示词（随机可复现，值英文编号、中文仅显示） | `prompt` |
| `QG_PhotoSheetMixed` | QG 证件照混合排版（A5） | 13 种 A5 固定版式，含双尺寸混排 / 旋转 / 竖版 / 零间距，批量逐帧出图 | `sheet` / `layout_name` / `total` |
| `QG_ImageComposite` | QG 图像合成 | 把源图按坐标贴到目标画布，遮罩控制混合；负坐标与四边越界按裁切处理，批次自动补齐 | `image` |
| `QG_SimpleSegDetectorSEGS` | QG 简易 Seg 检测 (SEGS) | 用 Impact-Pack 的 BBox 检测器找目标，可选 SAM 细化为轮廓或 SEGM 遮罩取交，输出 SEGS 给 Impact 下游；需本机安装 Impact-Pack | `segs` |

## 示例工作流

`workflows/` 下有三份可直接加载的 json（ComfyUI 菜单「工作流 → 打开」，或把文件拖进画布）：

| 文件 | 内容 | 依赖 |
| --- | --- | --- |
| `id_photo_pipeline.json` | 证件照全链路：上传一张人像 → `QG_IDPhotoParams` → `QG_PortraitMatte` → `QG_IDPhotoCrop` → 两路排版（`QG_PhotoSheetMixed` 的 13 种 A5 版式 / `QG_PhotoSheet` 的自定义相纸）→ 预览；另附「简易提示词」节点供图生图使用 | 需在 ① 里自己选一张人像；两个 modnet 权重已随包，另两个大模型首次使用时按需下载 |
| `id_photo_templates.json` | 纯模板与提示词：`QG_IDPhotoPrompt`（13 维 + seed）、`QG_IDPhotoOutfit`（内置 200 张）、`QG_MarriageCloth`（内置 81 张）三路输出，开箱即用 | 无外部模型、无需选图 |
| `id_photo_offline.json` | **离线开箱即用**：用随包的 `hivision_modnet` 抠图 + 随包的 OFL 中文字体打水印，另演示 `QG_MaskTopExpand` 头顶遮罩扩展（③ 的 `mask` → 扩展 → 转图 → 预览）。覆盖此前没有示例的 `QG_Watermark` / `QG_MaskTopExpand` | 只需在 ① 里换掉占位图；把 ③ 的 `face_alignment` 关掉即可**完全断网**运行 |

三份都由 8177 真机 `/object_info` 生成控件默认值与连线类型。前两份曾用真机前端验证过 `graphToPrompt()` 成立；本轮三份又统一按 `graphToPrompt` 的规则转成 API prompt 提交给 8177，全部 `node_errors={}`、执行 `success`（全链路 2 组图 / 模板 1 组 / 离线 2 组）：节点与连线完整、无未知节点、无断链。画布上的「使用说明」便签写了每一步该做什么，也写清哪些资源已随包、哪些仍需按需下载。

## 各节点使用说明

下面按一条典型工作流的**数据流顺序**排：图进画布 → 矫正朝向 → 对齐分辨率 → 抠图 / 反推 → 优化 / 翻译提示词 → 采样；最后四个是纯画布辅助节点，跟数据流无关，放末尾。

本节覆盖全部 33 个节点（含并入的证件照 / 排版 / 拼版 / 水印 7 个节点）。

每节固定四块：作用、怎么接线、控件说明、输出怎么接。参数默认值都是「拖出来就是能跑」的那一档，先把默认值跑通再调。

### ⚠️ PhotoKit 模型权重（2 个随包，2 个按需下载）

两个 modnet 抠图权重**已随包分发**在插件 `models/background_removal/`：离线机器装好插件
就能直接出图，不需要联网。它们取自 HivisionIDPhotos / MODNet 官方 release，
按 **Apache-2.0** 再分发、原样字节未修改；许可全文、来源 URL 与 SHA-256 见该目录
`NOTICE.md`，仓库根目录 `THIRD-PARTY-NOTICES.md` 也有对应条目。

其余权重仍是「用到时按需拉取」：节点第一次真正运行、且本地找不到对应权重时，
自动从官方源下载到 `ComfyUI/models/` 下的对应目录；下载过一次后本地缓存，之后直接读。

| 权重文件 | 用途 | 大小 | 分发方式 | 源 |
| --- | --- | --- | --- | --- |
| `modnet_photographic_portrait_matting.onnx` | 抠图（modnet 族） | ~24.7 MB | **随包**，插件 `models/background_removal/` | MODNet 官方权重，经 HivisionIDPhotos release |
| `hivision_modnet.onnx` | 抠图（modnet 族，纯色换底更稳） | ~24.7 MB | **随包**，同上 | HivisionIDPhotos 官方 release |
| `face_landmarker.task` | `QG_PortraitMatte` 人脸对齐（mediapipe） | ~3.6 MB | 按需下载 → `models/mediapipe/` | Google 官方 mediapipe 仓库 |
| `rmbg-1.4.onnx` | 抠图（rmbg 族） | ~176 MB | 按需下载 → `models/background_removal/RMBG-1.4/`（官方完整权重目录；根目录旧文件仍兼容读取） | BRIA AI / HuggingFace |
| `birefnet-v1-lite.onnx` | 抠图（birefnet 族，精度最高） | ~224 MB | 按需下载 → `models/background_removal/` | ZhengPeng7 BiRefNet 官方 release |

发现顺序：`ComfyUI/models/background_removal`（含 `extra_model_paths.yaml` 挂载）
→ `ComfyUI/models/matting` → **插件内置副本** → 兼容读取 HivisionIDPhotos 插件自带
weights。**用户自己放的同名权重优先**，内置副本只在用户目录没有时兜底；
命中内置副本后不会再触发网络下载。

失败兜底：

- `face_landmarker.task` 下载失败或缺失 → 自动回退到 OpenCV Haar 人脸检测（精度较差，侧脸 / 小脸不稳），节点照常出图。
- `rmbg-1.4` / `birefnet-v1-lite` 下载失败或缺失 → 节点报错并提示手动放置路径，不会出烂图。
- 自动下载带停滞看门狗：网络半死（连着但不来数据）超过数分钟会主动放弃并报错，不会无限卡住；可重跑或手动放置。

手动放置（自动下载失败时的兜底）：把上表「按需下载」的目标目录里的文件放好即可，
无需改名。`QG_PortraitMatte` 的下拉常驻显示 4 个抠图模型名：两个 modnet 开箱即用，
另外两个选中才触发下载。

> 许可提示：`rmbg-1.4`（BRIA AI）与 `birefnet-v1-lite` 的上游授权与随包的 modnet
> **不同**，商用前请自行核对各自仓库的条款。

### 来源：哪些是原创，哪些是搬运

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
| `QG_ImageToPrompt` | ✅ 原创 | 控件顺序参考 ComfyUI-Prompt-Assistant | 0% |
| `QG_PromptOptimize` | ✅ 原创 | 面板形态参考 ComfyUI-Prompt-Assistant「提示词优化」 | 新建，未比对（HTTP 层与反推节点同源） |
| `QG_PromptTranslate` | ✅ 原创 | — | 0% |
| `QG_IDPhotoParams` | ✅ 原创 | 参数规格参考 HivisionIDPhotos（Apache-2.0） | 0% |
| `QG_PortraitMatte` | ✅ 原创 | 美白 LUT 与参数划分参考 HivisionIDPhotos（Apache-2.0） | 0% |
| `QG_IDPhotoCrop` | ✅ 原创 | 裁剪几何对齐孤海工具箱口径（自实现） | 1% |
| `QG_PhotoSheet` | ✅ 原创 | 排版几何自实现 | 0% |
| `QG_MultiPhotoSheet` | ✅ 原创 | 多人各占一格的拼版几何自实现（纯整数规划），与「一张照片复制多份」的排版节点正交 | 0% |
| `QG_ImageBatchBuilder` | ✅ 原创 | 多输入槽汇总成 batch 的收集/对齐逻辑自实现，独立于核心 `ImageBatch` | 0% |
| `QG_RemoveBackgroundV2` | ✅ 原创（参照规格） | 功能规格参考 LayerStyle「RmBgUltra V2」；粗分割复用本包 BiRefNet，trimap / ViTMatte 推理 / PyMatting / 引导滤波全部独立实现，未复制上游源码 | 0% |
| `QG_IDCardSheet` | ⚠️ GPL 参考后重写 | Goohaitools「身份证自动扶正拼版」（GPL-3.0），三处核心算法已替换 | 未逐项统计（结构/命名沿用） |
| `QG_Watermark` | ✅ 原创 | 斜向水印自实现 | 0% |
| `QG_DualColorPicker` | ✅ 原创（参照规格） | 功能规格参考 Goohaitools「孤海 取色器（双）」（GPL-3.0）；代码自写，前端复用本包 `qg_color_picker.js`，未复制上游源码 | 0% |
| `QG_ColorPicker` | ✅ 原创（参照规格） | 功能规格参考 Goohaitools「孤海 取色器」（GPL-3.0）；代码自写，前端复用本包 `qg_color_picker.js`，未复制上游源码 | 0% |
| `QG_ColorConvert` | ✅ 原创（参照规格） | 功能规格参考 Goohaitools「孤海 颜色转换」（GPL-3.0）；解析 / 转换代码自写，未复制上游源码 | 0% |
| `QG_CustomColor` | ✅ 原创（参照规格） | 功能规格参考 Goohaitools「孤海 自定义颜色」（GPL-3.0）；渲染用 numpy 向量化重写（上游逐像素画点），未复制上游源码 | 0% |
| `QG_DominantColor` | ✅ 原创（参照规格） | 功能规格参考 Goohaitools「孤海-主色提取 (多版本兼容)」（GPL-3.0）；统计用 numpy 向量化重写（上游 Python 逐像素循环），未复制上游源码 | 0% |
| `QG_FaceAlign` | ✅ 原创（参照规格） | 功能规格参考 Goohaitools「孤海-面部对齐」（GPL-3.0）；几何与统计自写，人脸检测复用本包 `_face_helpers`（上游只支持 mediapipe），未复制上游源码 | 0% |
| `QG_IDPhotoOutfit` | ✅ 原创（参照规格） | 功能规格参考 Goohaitools「孤海-证件照服装发型」（GPL-3.0）；扫描与提示词解析逻辑自写，**内置素材取自孤海公开素材库**（7 分类 200 张，见 THIRD-PARTY-NOTICES），前端界面形态与其一致，未复制上游代码 | 0%（代码）/ 素材 100% 同源 |
| `QG_MarriageCloth` | ✅ 原创（参照规格） | 功能规格参考 Goohaitools「孤海-结婚登记照服装」（GPL-3.0）；扫描 / 缩放 / 路径清洗自写，**内置素材取自孤海公开素材库**（81 张，见 THIRD-PARTY-NOTICES），未复制上游代码 | 0%（代码）/ 素材 100% 同源 |
| `QG_MaskTopExpand` | ✅ 原创（参照规格） | 功能规格参考 Goohaitools「孤海-头顶遮罩」（GPL-3.0）；矩形计算自写，并修掉上游丢原遮罩、只处理单帧两个问题，未复制上游代码 | 0% |
| `QG_IDPhotoPrompt` | ✅ 原创（参照规格） | 功能规格参考 Goohaitools「孤海-证件照简易提示词」（GPL-3.0）；13 维选项中文词条取自公开规格（属数据），组装 / 随机 / 值映射自写，未复制上游代码；修掉上游 `random.seed()` 污染进程全局随机与「简单背景」重复叠加 | 0% |
| `QG_PhotoSheetMixed` | ✅ 原创（参照规格） | 功能规格参考 Goohaitools「孤海-证件照排版（A5定制）」（GPL-3.0）；13 个版式用数据表 + 统一排版引擎重写（上游每个版式一段分支、共约 700 行），未复制上游代码；修掉批次只取第一帧、描边撑大网格、超界静默裁切、短 hex 崩溃 | 0% |
| `QG_ImageComposite` | ✅ 原创（参照规格） | 功能规格参考 ComfyUI_essentials 的 `ImageComposite+`（GPL-3.0）；坐标求交、遮罩混合、批次补齐自写，并修掉上游负坐标走负索引贴错位置、只处理右下越界、目标帧被截短三个问题，未复制上游源码 | 0% |
| `QG_SimpleSegDetectorSEGS` | ✅ 原创（参照规格，运行时依赖） | 功能规格参考 ComfyUI-Impact-Pack 的 `ImpactSimpleDetectorSEGS`（GPL-3.0）；节点壳 / 参数校验 / 软依赖提示自写，未复制上游源码。类型 `BBOX_DETECTOR` / `SAM_MODEL` / `SEGM_DETECTOR` / `SEGS` 与 SEG 结构由 Impact-Pack 定义，运行时调用其 `impact.core` 公开接口（make_sam_mask / segs_bitwise_and_mask / dilate_segs / segs_to_combined_mask），本机必须安装 Impact-Pack | 0% |

一句话概括：**33 个节点里 32 个自行实现或按 GPL 移植并声明，1 个（`QG_MaskByName`）是 MIT 代码的部分改编**，且已在 `THIRD-PARTY-NOTICES.md` 里写明作者、上游地址、许可证全文，以及「保留了哪些函数、新写了哪些」的逐项拆分。两个带内置素材的节点（`QG_IDPhotoOutfit`、`QG_MarriageCloth`）另有一节说明素材来源：图与提示词取自 Goohaitools 公开素材库（GPL-3.0），原样复制未修改。

几个容易误会的点：

- **「参考了某个插件」不等于搬运**。`QG_FaceRectify`、`QG_ImageToPrompt`、`QG_PromptOptimize` 都是「先读懂它怎么做的，再自己写」，所以逐行相似度都在 10% 以下，但做的是同一个功能。README 和文件头都如实写明了参考对象。
- **`QG_MaskByName` 是本包里唯一需要特别说明的**。它改编自 AusBoss 的 MIT 代码，节点类、`INPUT_TYPES`、`_detect`、`cut_out` 等成段保留；本包新增的是 SAM 3 权重下拉与加载缓存、权重文件头校验、四步遮罩精修、预览保存。许可证允许这么用，但**必须署名**——所以 `THIRD-PARTY-NOTICES.md` 里那份声明不是可选项。

### `QG_FaceRectify` 人脸自动矫正

> **来源：原创**。思路参考 Goohaitools 的「Face Rectify」，代码自行实现；dlib 检测器全局复用（不是每次执行都重建）和 batch 尺寸补齐是这里新加的。逐行相似度 1%。

**作用**：把横躺、倒置、歪头的照片转正。90°/270° 转正时宽高互换、尺寸不变；轻微倾斜时会裁掉旋转带出的边缘，输出略小于原图（裁多少由 `edge_trim` 决定）。一批多张时以第一帧的尺寸为准，其余帧居中裁切或复制边缘补齐。

**接线**：

```
Load Image ──▶ image   QG_FaceRectify   image ──▶ 后面的抠图 / 反推 / 采样
```

**控件**：

| 控件 | 默认 | 说明 |
| --- | --- | --- |
| `enable_fix` | `True` | 关掉就是**原图直通**，用来 A/B 对比「到底动了什么」 |
| `edge_trim` | `2` | 旋转后四边会糊一条软边，这个值控制削掉多少。范围 1~5，**数值越大削得越少**（反直觉，按公式 `边长 × 角度^0.8 / 100 / edge_trim` 计算） |

**它实际做的四步**：

1. 在 0° / 90° / 180° / 270° 四个方向各跑一次人脸检测，按「是否正立（鼻尖在眼线下方）→ 转正角度绝对值最小」排序取最优。原版是「第一个检出就算」，遇到倒置脸会判错，这里改成打分排序。
2. 用 5 点 landmark 取两眼中心连线，`atan2` 得到倾斜角；超过 ±45° 视为头侧躺，折回 90° 的补角。
3. Lanczos4 绕中心旋转，边界像素复制（不留黑角），再居中裁回目标尺寸。
4. 按上面 `edge_trim` 的公式削边。

**输出**：`image`（同名输出口，单帧或 batch 都保持）。

**注意**：

- **没检测到脸就原样输出**，不会报错。所以「跑完没变化」是正常结果，不是没执行。
- 缺 `dlib` 或缺 `shape_predictor_5_face_landmarks.dat` 时同样原图直通，控制台打一行 `[QG 工具] 人脸自动矫正：缺少 dlib…`。
- batch 里每帧单独处理，若某帧因旋转导致尺寸与其他帧不同，会**按第一帧的尺寸居中裁切 / 复制补边**，保证能 `torch.stack`。
- 它只解决「脸不正」，不解决构图。需要人脸居中放大，得另接裁剪节点。

### `QG_MaskByName` 按名字找区域

> ⚠️ **来源：部分搬运**。改编自 **ComfyUI-AusBoss「Mask by Name」（MIT，© 2025 ausboss）**——主文件 225/279 行、helpers 114/156 行成段保留（含 `INPUT_TYPES`、tooltip 文案、`_detect`、`cut_out`）。本包新写：SAM 3 权重下拉与加载缓存、权重文件头校验、四步遮罩精修、预览保存。**按 MIT 要求已署名**，逐项拆分见 `THIRD-PARTY-NOTICES.md`。

**作用**：给一句话（"the girl's hair"、"the red jacket"），用 ComfyUI 内置 SAM 3 把对应区域分割成遮罩。

**接线**：

```
任意图 ──▶ image   QG_MaskByName ──┬─ mask ────▶ 遮罩类节点 / 局部重绘
                                   ├─ cut_out ─▶ Image Save（已抠好的预览图）
                                   └─ found ───▶ 数量判断
```

**控件**：

| 控件 | 默认 | 说明 |
| --- | --- | --- |
| `checkpoint` | 自动挑含 `sam3` 的那个 | SAM 3 权重，放 `models/checkpoints` 或 `extra_model_paths.yaml` 挂的 checkpoints 目录。**下拉列的是全部 checkpoint**，选到普通大模型会报「这不是 SAM 3 权重」 |
| `name` | `the person` | 要找什么，用几个普通词，如 `the dog`、`the red jacket`。多个目标用逗号分隔 |
| `several` | `all matches` | 命中多个时：`all matches` 全部合并成一个遮罩 / `largest only` 只留最大的那个 |
| `grow` | `0` | 向外扩多少像素。0 = 严格贴合轮廓；做描边、留白时给 2~8 |
| `soften` | `0.0` | 边缘羽化像素数。0 = 硬边 |
| `if_nothing` | `stop the run` | 什么都没找到时：停下整条工作流 / 给一张空遮罩继续跑 |
| `preview` | `True` | 是否在节点上显示命中区域（着色 + 描边）。关掉可省一次临时文件写入 |
| `drop_small` | `True` | 去掉搜索残留的小碎块，最大那块永远保留 |
| `small_size` | `5.0` | 多小的碎块算残留：**占最大块面积的百分比**。只在 `drop_small` 打开时生效 |
| `threshold` | `0.7` | SAM 3 的置信度门槛。**小目标漏了调低**（0.5~0.6），**抓错东西调高**（0.8~0.9） |
| `fill_holes` | `False` | 填掉遮罩内部的空洞（头发缝隙、衣服镂空）。打开后是实心块 |
| `free_vram` | `False` | 搜完立刻把 SAM 3 请出显存。后面要加载大模型时打开；关着下次搜索更快（权重还留在内存里）。打开时只会保留当前这个 checkpoint 的缓存，关着则记住最近用过的两个，在两个模型之间来回切不用反复读 1.7GB |

**输出**：

| 输出 | 类型 | 是什么 |
| --- | --- | --- |
| `mask` | MASK | 遮罩，可直接接 `Set Latent Noise Mask`、`InpaintModelConditioning` |
| `cut_out` | IMAGE | 按遮罩把目标抠出来的预览图（白底可见），不必再接抠图节点 |
| `found` | INT | 命中个数，**batch 时只取第一帧的数字**，不是总和 |

**注意**：

- 这是个 `OUTPUT_NODE`，勾了 `preview` 就会在跑完后直接出图，工作流里不接任何下游也能单独测试。
- **CPU 上很慢**：1.74 GB 的 fp16 权重，单张图十几秒到一分钟不等。调参阶段把图缩小到 512 再试，别拿 4K 原图反复试。
- `name` 写英文效果最好（SAM 3 的文本编码器按英文训练）。中文名请先过一遍 `QG_PromptTranslate`。
- 想要「人物 + 衣服」两套独立遮罩，就复制两个节点分别搜，别用逗号合并——合并后是一张遮罩。

### `QG_BiRefNet` 高精度抠图

> **来源：原创**。行为对齐 1038lab/ComfyUI-RMBG 的 BiRefNet 节点，代码结构全部重写（模型定义 `birefnet.py` 来自 HF 仓库，运行时加载，不随包分发）。逐行相似度 1%。

**作用**：18 个 BiRefNet 系列模型（含 RMBG-2.0）的统一入口，按张量 → 遮罩 → 后处理 → 合成出图。

**接线**：

```
任意图 ──▶ image   QG_BiRefNet ──┬─ IMAGE ──────▶ 保存 / 合成
                                  ├─ MASK ───────▶ 局部重绘 / 遮罩合成
                                  └─ MASK_IMAGE ─▶ 保存（遮罩的可视化图，三通道）
```

**控件**：

| 控件 | 默认 | 说明 |
| --- | --- | --- |
| `model` | — | 18 选 1，见[模型清单](#qg_birefnet-支持的模型)。日常用 `BiRefNet_lite-matting` |
| `sensitivity` | `1.0` | 前景概率的增益。**等于 1.0 时不做任何调整**；调小（0.5~0.9）会放大中间调的差异，让半透明边缘更明确 |
| `mask_blur` | `0` | 高斯模糊半径，柔化边缘。做合成时给 1~2 更自然 |
| `mask_offset` | `0` | 腐蚀 / 膨胀，范围 -20~20。**正值向外扩、负值向内收**，用来去掉边缘一圈背景光晕 |
| `invert_output` | `False` | 反转遮罩（留背景、去前景） |
| `refine_foreground` | `False` | 前景精修：对过渡区做 alpha 混合，发丝边缘更干净。**明显更慢**，只在需要贴新背景时开 |
| `unload_model` | `False` | 跑完卸载模型，释放显存。一次工作流只跑一次就开，要反复调就关着 |
| `background` | `Alpha` | `Alpha` 出 RGBA 透明底；`Color` 用下面的颜色把背景填实 |
| `background_color` | `#222222` | 仅 `background=Color` 时生效，节点上是色块 + 取色板 |

**输出**：`IMAGE`（RGBA 或已合成纯色底）、`MASK`（单通道遮罩）、`MASK_IMAGE`（遮罩转三通道，用来直接看效果）。

**注意**：

- **推理精度固定 fp32**（v2.15.11 起）。曾经在 CUDA 上自动用 fp16，BiRefNet 的中间特征会溢出 fp16 上限，整张遮罩 100% 变 NaN，而 `(nan*255).astype(uint8)` 把 NaN 悄悄变成 0 —— 结果就是**输出一整块纯色背景、看不到人**，日志里只有一行不起眼的 RuntimeWarning。fp32 下同一张图前景占比 48%，完全正常。若显存实在紧张，可设环境变量 `QG_BIRefNET_FP16=1` 再试：节点检测到 NaN 会自动降级回 fp32 重跑一次，本次进程内该模型之后不再尝试 fp16。
- 遮罩几乎全空时会打印一条提示（前景占比 < 0.1%），告诉你输出会是整块背景色，并建议换 `general` / `portrait` 模型或把灵敏度调小。
- 首次跑某个模型会**自动下载权重**，6.7 GB 那个仓库里挑一个也是几百 MB 起，网络差先设 `HF_ENDPOINT=https://hf-mirror.com`。
- 同一个模型重复运行不会重新加载；**切换模型会先卸掉上一个**，显存不会叠加。
- CPU 上极慢（`BiRefNet_lite-matting` 单张 84 秒，`BiRefNet-portrait` 近 5 分钟）。速度实测表见[这里的「速度提醒」](#速度提醒)。

### `QG_QwenTextEncode` + `QG_QwenRestore` Qwen Image 2.1 文本编码 / 还原画布

> **来源：GPL 逐行移植**。对齐 Goohaitools「Qwen Image 2.1 文本编码 GH」+「Restore Qwen Image 2.1 GH」（孤海工具箱，GPL-3.0）。**逐行相似度 92.26%**——这是三处刻意为之：①该节点深度依赖 comfy 条件注入（`reference_latents` / `keep_vision` / `prevent_empty_text`）与 Qwen 采样的内部行为，改写任何一行都可能改变生成结果且难以察觉，逐行移植是唯一能保证行为可互换的方式；②本包与参考同为 GPL-3.0，按协议移植并声明来源即可；③info 类型名沿用 `QWEN_IMAGE_21_GH_RESTORE_INFO`，本包节点与 Goohaitools 原版的 `info` 口可直接互连。**282 组对照（纯函数全量扫描 + 6 个 encode 全流程场景 + restore 全量 + INPUT_TYPES 逐项）与真·参考类零差异**。差异仅：注册 key / 分类 / 中文注释，前端「参考图尺寸」标签兼容了控件形态（参考只处理输入口形态）。

**作用**：Qwen Image 2.1 专用的文本编码节点——普通 CLIPTextEncode 只能编文本，这个节点把**最多 10 张参考图**（视觉 token + `reference_latents`）一起编进条件，同时给出初始 latent 和局部重绘遮罩，一个节点顶掉「文本编码 + 参考图预处理 + 空白 latent + 遮罩合成」四件套。`Restore` 节点则在采样后把「填充」模式垫上的灰边裁掉。

**接线**（还原节点可选）：

```
CLIP ──▶ clip            prompt ────────▶┐
VAE(可选) ──▶ vae        negative ──────▶┤ QG_QwenTextEncode ──┬─ positive ──▶ 采样器 positive
MASK(可选) ──▶ mask       latent_width ──▶│                     ├─ negative ──▶ 采样器 negative
图像 1~10 ──▶ 参考图      mode ──────────▶│                     ├─ latent ────▶ 采样器 latent
                          参考图尺寸 ────▶┘                     └─ info ──────▶ QG_QwenRestore ──▶ 图像 ──▶ 保存
```

**控件**（与参考截图逐项一致，控件名保持英文）：

| 控件 | 默认 | 说明 |
| --- | --- | --- |
| `prompt` / `negative_prompt` | 空 | 正 / 负面提示词。负面分支不做第二次编码（面向 CFG=1 工作流，CFG>1 时负面提示词有意不生效——参考原版同此行为） |
| `latent_width` / `latent_height` | 1024 / 1024 | 初始 latent 尺寸，自动按 32 取整 |
| `mode` | 填充 | 「填充」：图 1 等比放进 latent 画布、空余垫灰（配 `info` → 还原画布）；「裁剪」：居中裁到 latent 尺寸 |
| `参考图尺寸` | 自动 | 参考图目标面积：自动按 latent（1~2 图）/ 1024²（3~4 图）/ 768²（5 图+）；或固定 768~2048 |

**输入口**：`clip` / `vae`（可选，接了才注 reference_latents 并用图 1 latent 当初始 latent）/ `mask`（图 1 局部重绘，白改黑保，自动膨胀 30px + 羽化 10px，可见面积 ≤0.2% 按没接处理）/ `图像 1~10`（**动态增减**：接一个多显示两个空位，最多 10 个——参考同款前端逻辑）。

### `QG_QwenPromptOptimizer` Qwen image 2.1 提示词优化

> **来源：GPL 逐行移植**。对齐 Goohaitools「Qwen image 2.1 提示词优化」（`QwenImagePromptOptimizer`，孤海工具箱，GPL-3.0），覆盖节点本体 + 1060 行 llama-cpp 运行时 + 3 个 system prompt 资产 + 327 行前端。逐行相似度：runtime **98.94%** / 节点 **95.65%** / 前端 **84.54%**——提示词组装（语言锁 / 反推指令 / 透明背景改写正则）、LLM 采样参数、显存卸载策略直接决定模型输出，改写任何一行都会静默改变结果，逐行移植是唯一能保证行为可互换的方式；本包与参考同为 GPL-3.0，三个 system prompt 资产文件按协议原样复制（md5 一致）并在 NOTICES 声明。**217 组对照（纯函数全量扫描 + INPUT_TYPES 逐项 + optimize 九场景入参录制 + llama 安装辅助函数）与真·参考类零差异**。有意差异仅：注册 key `QG_QwenPromptOptimizer`、HTTP 路由前缀 `/qg_qwen_prompt_optimizer/*`、内部状态标识与控制台前缀 `[QG Qwen]`、路由注册加了 PromptServer 空指针保护。

**作用**：在本地用 llama-cpp 跑 Qwen GGUF 模型来「写提示词」，不花 API 钱、不出本机。三种模式自动判定：

| 场景 | 行为 |
| --- | --- |
| 不接图 + 有提示词 | 文生图扩写：把一句话扩成 Qwen Image 2.1 可用的完整描述（JSON 里带最佳宽高比） |
| 接图 + 空提示词 | **反推**：视觉模型看图，直接写出能复刻这张图的完整生成提示词（自动忽略水印文字） |
| 接图 + 有提示词 | 图生图改写：按提示词指令改写图片内容描述 |

**模型要求**：`models/LLM`（或 `llm`）目录下放 Qwen Image 2.1 的三个 GGUF——文生图模型（文件名含 `PE-T2I`）、图生图模型（含 `PE-I2I`）、视觉编码器（含 `mmproj`）。目录没注册过也没关系，节点导入时会自动把 `models/LLM` 注册进 ComfyUI 的模型目录表。**依赖 llama-cpp-python ≥ 0.3.48（JamePeng fork，带 Qwen3.5 视觉支持）+ diskcache**；没装时节点上会出现「llama-cpp需0.3.48以上，点击查看安装说明」按钮，点击后弹出匹配当前系统/Python/CUDA 的 wheel 文件名后缀与官方发布页地址，需自行下载 wheel 并用 ComfyUI 自带 Python 执行 `python -m pip install <wheel文件> diskcache`（装完完全重启 ComfyUI）。**本包不自动安装依赖**：在节点进程内用 subprocess 调 pip 违反 Comfy Registry 安全标准，故改为手动安装指引（与上游 GPL 逐行移植的详见 NOTICES 的有意差异）。没装时执行会报「llama-cpp-python 不可用」，不影响其他节点。

**控件**（与参考截图逐项一致）：`用户提示词`（多行）/ `文生图模型` / `图生图模型` / `视觉模型` / `输出语言`（自动/中文/English，自动按提示词语言判断，反推固定中文）/ `透明背景`（强制输出 RGBA 透明背景描述，自动改写并删除与背景矛盾的内容）/ `种子值` + `种子模式`（随机时每次排队自动换种子、执行后回填实际值）/ `卸载模型`（自动/保持加载/运行后自动卸载/运行前后自动卸载——「自动」按剩余内存判断）。输入口 `图像 1~10` 与 `QG_QwenTextEncode` 同款**动态增减**（接一个多显示两个空位，最多 10 个）；提示词文本框高度可拖拽节点边缘调整并按节点记忆。

**输出**：`prompt`（最终提示词文本）/ `json`（`rewritten_prompt` + `wh_ratio` 等的 JSON 串）/ `是否反推`（BOOLEAN，本次是否走了反推模式，可接分支）。前端在每次点队列时统一为本机所有本节点换随机种子，与参考实现一致。

### `QG_ImageToPrompt` 图像反推提示词

> **来源：原创**。控件顺序与「图像反推提示词」这一形态参考 ComfyUI-Prompt-Assistant（规则分组也照它的做法），后端实现自行编写。逐行相似度 0%。

**作用**：给一张图，用视觉模型反推成能复现它的提示词。**边推理边在节点下方出字**。

**接线**：

```
任意图 ──▶ image   QG_ImageToPrompt ──┬─ 提示词输出 ─▶ CLIP Text Encode
                                       └─ 提示词列表 ─▶ 逐帧处理
```

**控件**：

| 控件 | 默认 | 说明 |
| --- | --- | --- |
| `rule` | `像素级描述` | 反推规则，来自 `设置 → QG 工具 → 提示词规则` 里的规则管理器。**规则决定输出形态**，不是换个说法 |
| `custom_rule` | `False` | 打开后用 `custom_rule_content` **整段替换**预设（不是追加） |
| `custom_rule_content` | 空 | 自定义规则正文，仅在上一项打开时生效。写清观察顺序与输出格式 |
| `user_prompt` | 空 | 附加要求，拼在规则后面。**同时决定输出语言**：空或中文 → 中文，写英文 → 英文 |
| `vlm_service` | `智谱/glm-4.6v-flash` | 「服务商/模型」，地址与 Key 取自 `设置 → QG 工具 → API 服务商`。**必须选支持图像输入的模型** |
| `auto_unload` | `True` | 本地 Ollama 跑完即卸载；云端服务忽略 |
| `seed` | `0` | 不影响结果，只控制「要不要重跑」。固定时同图复用缓存不重复扣费，`randomize` 则每次重推换措辞 |

**输出**：`提示词输出`（STRING，batch 时用 `\n---\n` 连接）、`提示词列表`（STRING 列表，逐帧一条）。

完整的规则对照表、batch 策略、错误降级、流式预览机制见后面的「图像反推提示词」专章。

**注意**：失败**直接报错**，不像翻译节点那样原样直通——反推没有「原文」，静默返回空串只会让下游拿到空提示词。

### `QG_PromptOptimize` 提示词优化

> **来源：原创**。面板形态参考 ComfyUI-Prompt-Assistant 的「提示词优化」节点，后端与规则为自行编写；HTTP/流式层与 `QG_ImageToPrompt` 共用同一份实现（`ask_text`），所以两边不会各自演化出不同的重试行为。

**作用**：把一段粗糙的提示词改成能直接出图的版本——扩写补细节、润色去冗余、改写英文喂 SDXL / Flux。**边生成边在节点下方出字**。

**接线**：

```
手写文本 ──▶ text        QG_PromptOptimize   提示词输出 ──▶ CLIP Text Encode
上游文本 ──▶ extra_text  （两路合并后一起处理）
```

**控件**：

| 控件 | 默认 | 说明 |
| --- | --- | --- |
| `text` | 空 | 要优化的提示词，直接写在节点上；右键输入框可以转成输入口 |
| `extra_text` | — | 可选输入口（`forceInput`），接上游文本用。连上就和 `text` 空一行拼接；不接时忽略 |
| `rule` | `扩写-通用` | 来自规则管理器的「提示词优化规则」页，**只列这一组**——反推规则写的是「怎么看图」，套到纯文本上会让模型开始描述文字「看起来像什么」 |
| `custom_rule` | `False` | 打开后用 `custom_rule_content` **整段替换**预设 |
| `custom_rule_content` | 空 | 自定义规则正文，仅在上一项打开时生效 |
| `llm_service` | 第一个配了 Key 的服务商（本机是 `Zhipu GLM`） | 「服务商」或「服务商/模型」。纯文本任务，任何对话模型都能跑，**不必挑视觉模型** |
| `auto_unload` | `True` | 本地 Ollama 跑完即卸载；云端服务忽略 |
| `seed` | `0` | 不影响结果，只控制「要不要重跑」。固定时同段原文复用缓存不重复扣费，`randomize` 则每次换一种写法 |

**四条内置规则**：

| 规则 | 做什么 | 长度 |
| --- | --- | --- |
| `扩写-通用` | 补主体、服装、构图、环境、光线、画质；只补场景里自然推得出的细节，不换题材 | 150–300 字 |
| `润色-精炼` | 去重、删空词、调顺序，输出**逗号分隔的短语串**（2–8 字一个元素）；不添加原文没有的元素 | 不短于原文 60% |
| `扩写-细节质感` | 专攻材质（织物纹理、金属反射、次表面散射）与光影（高光形状、阴影软硬、轮廓光） | 200–350 字 |
| `改写-英文` | 输出逗号短语，顺序为质量词 → 主体 → 服装 → 动作 → 构图 → 环境 → 光线 → 色彩 → 风格 | 与原文同量级 |

**保留语法**：`(word:1.2)`、`[word]`、`<lora:name:0.8>`、步数 / CFG 这类数字参数在所有规则里都写明「原样保留」——通用大模型看到这些会当成 Markdown 或笔误顺手改掉，所以请求里强调一次，输出端再剥一次思考段和代码围栏。

**输出**：`提示词输出`（STRING）。没有第二个口——优化是「一段进一段出」，不需要列表。

**注意**：失败**直接报错**，不原样输出。翻译节点失败时原样直通还算合理（下游照常能跑），优化失败却把烂提示词吐给下游，用户会以为「优化没生效」，比报错更难查。

**实测（glm-4-flash，四条规则各跑一轮）**：格式都对得上——扩写出连贯段落、润色出逗号短语串、英文出短语列表；括号权重和 LoRA 标签能保住（`(smile:1.2)`、`<lora:film:0.8>` 原样返回，不会被拆成 `smile:1.2`）。但两件事免费模型做不稳：

1. **删空词**：原文里的「氛围感」「高级感」常被原样留下，规则里写了「必须零出现」也没用。
2. **不外扩材质**：木工房场景会冒出「皮革的质感」「木香」——规则里列的是「只写场景里有的」，它仍会按类别联想补齐。

这两条已经是模型能力边界，不是规则措辞问题（试过点名具体词，反而被模型当成要保留的词汇复述进输出，所以现在的规则一律用描述性禁止、不举例）。要稳就换模型：`Zhipu GLM/glm-4.5` 或 `DeepSeek` 明显更守规则，代价是慢一点、要花额度。默认给免费模型是因为它够用来验证链路和日常粗调。

### `QG_PromptTranslate` 提示词翻译

> **来源：原创**。翻译核心 `translate_core.py` 与本节点均为自行实现，百度两条通道的分块 / 退避 / 回落也是自己踩坑后加的。逐行相似度 0%。

**作用**：中文提示词进、英文提示词出的固定链路快捷节点，只有四个控件。

**接线**：

```
文本来源 ──▶ source_text   QG_PromptTranslate   translated_text ──▶ CLIP Text Encode
```

**控件**：

| 控件 | 默认 | 说明 |
| --- | --- | --- |
| `source_text` | — | **只做成输入口**，节点上不显示文本框（提示词几乎总是上游产生）。内容为空时直接输出空串，不发请求 |
| `target_language` | `English` | 8 种。原文已是目标语言时**直接跳过**，不花请求 |
| `translate_service` | `百度翻译` | 两条百度通道（通用 / 大模型）+ 设置面板里的所有服务商 |
| `auto_unload` | `True` | 只对本地 Ollama 生效 |
| `seed` | `0` | 不影响译文，只让节点重跑一次；同段原文有缓存不重复扣费 |

**输出**：`translated_text`（STRING）。

**注意**：失败时**原样输出**并在节点下方画红框气泡写明原因，不阻塞工作流。百度两条通道的字符限制与重试策略见[专章](#百度通道的几个硬限制踩过才知道)。

### `QG_Translate` 通用 LLM 翻译

> **来源：原创**。`translate_node.py` 只是外壳，逻辑全在自行编写的 `translate_core.py` 里。逐行相似度 1%。

**作用**：把源语言 / 目标语言 / 地址 / 模型 / Key 全摊在节点上的通用翻译器，接任意 OpenAI 兼容接口。

**接线**：

```
文本来源 ──▶ text   QG_Translate   text ──▶ 下游
```

**控件**（必填三个 + 可选五个）：

| 控件 | 默认 | 说明 |
| --- | --- | --- |
| `text` | 空 | 多行文本框。要接上游，**右键字段 → Convert text to input** 转成输入口 |
| `provider` | `Zhipu GLM`（本机实测，随配置变化） | 内置厂商 + 设置面板里存的每一条服务商，故意不含 `custom` 空地址占位；本机实测 **14 项**，项数随配置增减。默认值由 `default_service_choice()` 决定（设置里指定的默认 → 第一个填了 Key 的服务商 → 第一个可用项），保证一定落在下拉里。写服务商名 = 用默认模型；写 `服务商/模型` = 指名模型 |
| `to_lang` | `english` | 9 种语言 |
| `from_lang`（可选） | `auto` | 源语言。自动判断常出错时手指定，短文本尤其 |
| `api_url`（可选） | 空 | 填了就覆盖服务商地址，这是接任意第三方中转的口子 |
| `model`（可选） | 空 | 填了就覆盖服务商默认模型 |
| `api_key`（可选） | 空 | **留空，Key 存在 `ComfyUI/user/ComfyUI-QG-Multipack/config.json`（设置面板里填）**。这里填的只在本次会话有效，**不会**写进工作流 JSON（发给别人也不带密钥）。本地 Ollama 不需要 |
| `if_fail`（可选） | `output original` | 调用失败时：原样输出继续跑 / 停下并抛出厂商原文 |

**输出**：`text`（STRING）。

**和 `QG_PromptTranslate` 的分工**：这个是通用翻译器，什么都能翻；那个是固定链路快捷版。翻译核心（服务商预设、`config.json` 读写、HTTP、缓存）共用 `translate_core.py`。

**注意**：和反推节点一样**不要挑视觉模型**。`glm-4.6v-flash` 这类高峰期限流 429，纯翻译用 `glm-4-flash` 或 `glm-4.5`。

## 提示词翻译（`QG_PromptTranslate`）

工作流里「中文提示词 → 英文提示词」这条链路形状是固定的，所以单独做了一个只有四个控件的快捷节点：

```
原文（输入口）──▶ 目标语言   English
                  翻译服务   百度翻译
                  自动释放显存 Enable
                  随机种子    0 + 生成后控制
                                    └──▶ 提示词输出
```

- **原文只做成输入口**，节点上不显示文本框——提示词几乎总是由上游节点产生（文本编辑、字符串拼接、注释）。
- **翻译服务有两条百度通道**，都在 `设置 → QG 工具 → API 服务商 → 百度翻译` 里填同一对 `appid` / 密钥，存在本机 user 目录的 `config.json`，不进工作流：
  - `百度翻译`：通用文本翻译接口，未认证账号 5 万字符/月、QPS 1、单次 1000 字符。
  - `百度翻译（大模型）`：调 `/ait/api/aiTextTranslate`，带一段提示词专用翻译指令（保持逗号短语结构、不合并成句子、保留 `(word:1.2)` 权重与 `<lora:xxx>` 标签）。**要在百度控制台单独开通，并完成开发者认证**；没开通时自动回落到通用翻译，不会报错卡住流程。
- **源语言自动判断**：含中文字符算中文、纯 ASCII 算英文、其余交给服务端 `auto`。目标语言与源语言相同时直接跳过，不花一次请求。
- **自动释放显存只对本地 Ollama 生效**：翻译完立刻 `keep_alive: 0` 把模型请出显存；云端服务忽略这个开关。
- **种子不影响译文**，只让节点重新执行一次（对措辞不满意时换个数值重翻）。同一段原文有缓存，重复运行不会重复扣费。
- **失败不挡工作流**：原文原样传给下游，**同时在节点下方画一个红框气泡写明失败原因**（跟反推节点的流式气泡是同一套绘制，保留 15 秒）。只打控制台日志是不够的——原样输出时画布上跟成功一模一样，用户只会觉得「怎么翻完还是中文」。

### `QG_IDPhotoParams` 证件照参数

> **来源：原创**。参数规格参考 HivisionIDPhotos（Apache-2.0），代码自行实现；中文名已带 `QG ` 前缀。

**作用**：不发图像，只把「这张照片要什么样」集中在一处（尺寸 / 底色 / 渲染 / dpi），一路连给抠图与排版节点；同时把算好的宽高和 dpi 单独引出。

**接线**：

```
IDPhotoParams ──params──▶ PortraitMatte / IDPhotoCrop
            └─DPI──────▶ PhotoSheet（photo_dpi）
```

**控件**：`preset`（20 项标准尺寸 + custom）、`bg_color`（白 / 蓝 / 深蓝 / 红 / 浅蓝 / 灰 / 自定义，注意这套蓝是印刷蓝 `#438edb` 不是 CSS 蓝）、`render`（纯色 / 上下渐变 / 中心渐变）、`dpi`、`custom_width/height`（厘米）。

**输出**：`params` / `宽` / `高` / `DPI` / `主色`。主色是主背景色解析后的 `#RRGGBB`（印刷蓝是 `#438edb`，不是 CSS 蓝；渐变取第一色），可以直接连给取色器、颜色转换等节点复用。「自定义色值」这一格点一下弹色板取色，取完会自动把「背景颜色」切到「自定义」，不用手动再切一次。


### `QG_PortraitMatte` 人像抠图换背景

> **来源：原创**。美白 LUT 与参数划分参考 HivisionIDPhotos（Apache-2.0），代码自行实现。

**作用**：抠图 → 换底 → 美颜 → 按证件照构图裁好。依赖可选的 onnxruntime（抠图模型）、mediapipe（人脸对齐，缺失退回 OpenCV Haar）。

**接线**：`image` 进；`params` 可选（不接则退回一寸蓝底 300dpi）；`成品图` 给下游裁剪或排版。

**控件**：`matting_model`（下拉常驻 4 个，其中 2 个 modnet 已随包）、`face_alignment`（双眼转水平，超 2° 才动）、`change_bg_only` / `crop_only`（同时开会报错）、`head_height`（头发顶到下巴占画面比例，国标约 0.667）、`top_distance`、`whitening_strength`（美白，10 满）、亮度 / 对比度 / 饱和度 / 锐化。

**输出**：`成品图` / `蒙版` / `高清图`。


### `QG_IDPhotoCrop` 证件照裁剪

> **来源：原创**。裁剪几何对齐孤海工具箱口径，自实现；与抠图节点的「头高 + 留白」口径不同，参数不可互换。

**作用**：把**已有**照片裁成指定尺寸、眼睛自动摆平（不抠图）。一次仿射重采样出结果。

**控件**：`preset` / `unit`（厘米 / 像素）/ `dpi` / `face_ratio`（脸宽占比）/ `eye_line`（眼线位置）/ `auto_rotate`（摆平 / 保持倾斜）/ `face_pick`（居中 / 最大）/ `max_side` / `fill_mode`（边框色 / 自定义色）/ `fill_color` / `alpha_mode`（透明区域：填平透明 / 保留透明）。

**输出**：`裁剪后图像` / `扩展遮罩` / `是否扩图`（布尔）/ `DPI` / `定位示意图`。

**越界补边**：`face_ratio` 要的是「人脸占输出宽度的比例」，素材本身已经裁得比这个比例更紧时，取景框会算得比原图还大 —— 一张 429×600、脸占 52% 的人像按 0.42 算要 533×746 的框，越界那部分只能凭空造像素，照片四周就会多出一圈背景色、人物同时被缩小。此时把 `face_ratio` 调大（调到人脸在素材里的实际占比附近）即可让取景框收回原图内，`扩展遮罩` 会显示为全黑、`是否扩图` 为 `False`。确实需要补边时，`fill_mode=border` 用原图**四条边各自的背景色**补，且只统计与顶部基准色同族的像素 —— 直接把底部衣领、西装算进去会补出一条黑边。

**倾斜角怎么来的**：默认取两眼连线。但眼睛被刘海、眼镜或浓妆盖住时，检测器会把整只眼的点整体挪到上眼睑上（一只眼偏 1/3 个眼高），双眼连线就变成反方向的大角度，转完比不转还歪。所以两眼连线之外，还会用**鼻翼、颧骨、下颌角、太阳穴**这四对硬结构各投一票；两边差超过 6° 就判定眼睛不可信，改用这四对的中位角度，并在日志打印一行 `[QG-Face]` 说明。这四对不经过眼睛，也不跟着表情走（眉毛会被同一片刘海盖住、嘴角会被笑容拉起，所以都不用）。眼睛干净的正常照片走的仍是原来那条路，结果不变。

**`auto_rotate` 的两个状态直接写在源码里**（`摆平` / `保持倾斜`）：新前端的切换控件按 `label_on` / `label_off` 原样打印，没有走词表的通道，所以这两串中文不在词表里也能显示。

**透明通道（RGBA）输入**：接抠图节点（本包 `QG_BiRefNet` 的 `background=Alpha`、`QG_PortraitMatte`）输出的四通道图像不再报错，1 / 2 / 3 / 4 通道都能吃（灰度自动扩成三通道，两通道取第一路，多于四通道取前三路）。`alpha_mode` 决定透明区怎么落：

- **填平透明**（默认 `fill`）：透明区按 `fill_color`（`fill_mode=custom`）或边框采样色压成实心，输出**不透明 RGB** 证件照，下游排版 / 保存直接可用。
- **保留透明**（`keep`）：输出 **RGBA**，透明区保持透明（补边区 alpha 也是 0），供后续自行合成任意底色。

普通 RGB 图两种模式结果完全一样。`alpha_mode` 是**可选输入**，老工作流没这个键也能照常执行（按 `fill` 处理）。整批只要有一帧是 RGBA 且选了 `keep`，全部帧统一升成四通道（RGB 帧补不透明 alpha），避免 `torch.stack` 因通道数不一致失败。


### `QG_IDPhotoSizePicker` 证件照尺寸选择

> **来源：原创**。预设表与裁剪节点同源（`_id_photo_helpers.PRESETS`），未复制第三方代码。

**作用**：一处选好尺寸，`preset` 一路喂给「证件照裁剪」「证件照参数」等节点的预设下拉，另出换算好的像素宽高与 DPI 给排版 / 生成节点。改尺寸只改这一个节点。

**控件**：`preset`（20 项，与裁剪节点同一份表）/ `dpi` / `custom_width` / `custom_height` / `unit`（厘米 / 像素，仅 `custom` 生效）。

**输出**：`预设` / `宽` / `高` / `DPI`。

**为什么第 1 路能连下拉**：这里有个绕不过去的坑 —— 输出槽写 `"STRING"` 连不上，写 `"COMBO"` **照样连不上**。后端 `validate_node_input` 拿到的输入类型是下拉的**原始选项列表**，只有输出类型是「与下游逐项相同的数组」才放行；前端再把槽类型对齐成 `"COMBO"`，两侧才对得上。所以第 1 槽写的是 `PRESET_ORDER` 本身，前端由 `web/qg_id_photo_size_picker.js` 负责对齐（改 `nodeData` 有冻结风险，用 `try/catch` 兜住）。

**尺寸怎么算**：与裁剪节点共用 `_id_photo_helpers.output_pixels`，同一个预设两边算出的像素逐个相同；按像素给的预设（358×441 这类）自带 dpi，会覆盖控件里的值。

**一个限制**：选 `custom` 时这根线只传 `custom` 这个字符串，具体宽高仍要在下游节点各填一次 —— 一根线传不了五个数字。


### `QG_PhotoSheet` 照片排版

> **来源：原创**。排版几何自实现。

**作用**：把照片铺满相纸，能放多少张居中、等距排多少张，放不下就自动缩小；可画裁切角标、加底部文字。

**控件**：`paper_w/h`（厘米）、`dpi`、`margin`、`spacing`、`border`（描边像素）、`cut_marks`、`auto_orient`、`caption`、`font`、`font_size`、`auto_fit`、`photo_dpi`（**务必接上游 DPI**，否则 600dpi 像素按 350dpi 解释会被放大）。

**输出**：`排版图像` / `列数` / `行数` / `总张数`。`auto_fit` 关且放不下时 `cols=rows=0`，输出一张空纸不报错。

**常用尺寸预设**：节点上有一个「常用尺寸」下拉（不写进工作流存档的辅助控件），列出冲印常用纸型 5 寸 / 6 寸 / 7 寸 / 8 寸 / A5 / A4，选中即一次填好 `paper_w` / `paper_h` / `dpi`（冲印纸型 350dpi、A 系列 300dpi）；手动改了纸宽 / 纸高 / DPI 后下拉自动回到「自定义尺寸」。

### `QG_MultiPhotoSheet` 多人证件照拼版

> **来源：原创**。多人拼版几何自实现，纯整数规划，与「一张照片复制多份」的排版节点正交。

**作用**：好几个人的证件照拼到同一张纸上打印——**每人各占一格**，而不是把同一张照片复制满纸。主环境现成的 `ImageGridComposite2x2/3x3` 要求固定 4/9 个独立输入且尺寸一致、`MTB_SaveImageGrid` 无边距控制且是保存节点，都不适合证件照打印；本节点直接从 batch 取人，列数一定、行数自动。

**接线**：把每个人的证件照合成一个 batch 接到 `image`（每人一帧）——推荐用「QG 图像批次组合」：每个 LoadImage 接一个槽即可，不用自己串 ImageBatch。同一人要多张就多放几帧，按帧顺序逐格排。

**控件**：

| 控件 | 默认 | 说明 |
| --- | --- | --- |
| `paper_w` / `paper_h` | 21.0 / 29.7 | 纸张宽高，厘米（A4） |
| `dpi` | 300 | 打印分辨率，厘米 × dpi 定像素 |
| `cols` | 3 | 每行几人；行数 = ⌈人数 / 列数⌉ 自动，实际列数不超过人数 |
| `margin_cm` / `spacing_cm` | 0.5 / 0.3 | 页边距与人与人间距，厘米 |
| `fit_to_paper` | 开 | 人太多放不下时整体等比缩小（格子与间距一起缩）；关闭则明确报错 |
| `bg_color` / `border_px` / `border_color` | 白 / 0 / 黑 | 纸张底色、每格描边（画在格内）、描边色 |

**常用尺寸预设**：节点上的「常用尺寸」下拉（不写进存档的辅助控件）列出办公纸型 A4 / A5 / B5 / 信纸 / A4 横向，选中即一次填好 `paper_w` / `paper_h` / `dpi`（均 300dpi）；手动改这三个值后下拉自动回到「自定义尺寸」。`bg_color` 与 `border_color` 已接入本包通用调色盘——点控件弹色板（预设色 / 输入 HEX / 系统取色器），也可手填色值。

**统一格规则**：所有格子同尺寸，宽高比取**首帧照片**的比例，居中裁切填进格子，不拉伸人脸。所以 batch 里第一张照片的宽高比决定整版格子形状——建议先把所有人的照片裁成同一规格（用「QG 证件照裁剪」）再拼。最后一行不满时居中，不留一侧大空档。

**输出**：`拼版图像`（一张纸）/ `行数` / `列数` / `人数`（实际拼进去的帧数）。


### `QG_ImageBatchBuilder` 图像批次组合

> **来源：原创**。多输入槽收集与尺寸对齐逻辑自实现，不依赖核心 `ImageBatch`。

**作用**：一个节点把多张照片合成 batch，专治「6 张图要串 5 个 ImageBatch」的繁琐。输入槽**动态增减**：节点刚拖出来只显示 1 个槽，给最后一个槽接上图就自动在后面加一个空槽（「接一个加一槽」），最多 24 个；断开末尾连线会收起多余空槽。节点高度会跟着实际槽数自适应——新建时收紧到内容高度，接线加槽时自动增高；从工作流加载的节点则保留你拉过的尺寸，不会被改回默认。

**怎么接线**：每个 LoadImage 的输出接一个槽，从上往下依次接；槽是按编号顺序拼的，不是按连线顺序。每个槽既能接单张，也能接一个 batch（整批按顺序展开），所以「6 个单帧」和「1 个 6 帧 batch」结果一样。输出直接接「QG 多人证件照拼版」的 `image`。后端 24 个槽全可选，只接 1 张也能跑；一张都不接会在运行时明确报错。

**控件说明**：唯一控件是 `resize_mode`：

| 值 | 说明 |
| --- | --- |
| `first`（默认） | 尺寸不一致时以第 1 张为准双三次缩放对齐，通道数也对齐（RGB/RGBA 互转），与核心 `ImageBatch` 行为一致 |
| `error` | 尺寸不同直接报错，适合规格不一时早点发现、避免悄悄缩放变形 |

**输出**：`image`（合成后的单个 batch）/ `count`（实际张数）。张数输出可接下游做分支判断。

**槽位不够怎么办**：24 个（自动加到上限）对应 A4 证件照 3 列 × 8 行的常见上限；更多张建议先把图片放到 `input` 的某个文件夹，用能读整批的节点导入，或分两批拼两张纸。


### `QG_RemoveBackgroundV2` 移除背景 V2 · 细节精修

> **来源：✅ 原创（参照规格）**。功能规格参考 LayerStyle 的「LayerMask: RmBgUltra V2」（GPL-3.0），流程与参数含义对齐，实现全部自写；粗分割直接复用本包的 `QG_BiRefNet`，不引入第二套权重，也不复制上游源码。

**作用**：把图片抠成透明背景，并在粗遮罩基础上重做边缘细节（发丝、半透明边）。五选一的细节方法与截图节点一致：

| 细节方法 | 依赖与特点 |
| --- | --- |
| `VITMatte`（默认） | 用 `hustvl/vitmatte-small-composition-1k`，优先读模型库，缺失才联网下载；按 trimap 出发丝级 alpha，边缘最细 |
| `VITMatte(local)` | 同一个小模型，只允许读本地，不联网 |
| `vitmatte-base-composition-1k` | 更大的 base 模型，更细但更慢、显存更高；同样优先读模型库 |
| `PyMatting` | 闭合形式抠图，需 `pymatting` + `pyamg` |
| `GuidedFilter` | opencv 引导滤波，速度最快，细节不如前几种 |

**控件**：`detail_erode` / `detail_dilate`（默认 6）决定 trimap 的腐蚀/膨胀核，值越大待处理边缘越宽；`black_point` / `white_point`（默认 0.01 / 0.99）把精修后的 alpha 线性拉伸到 0..1；`process_detail` 关掉就只输出 BiRefNet 粗分割结果，不需要任何额外依赖；`device` 选 `auto` 跟随 ComfyUI 当前设备，指定 `cuda` 但不可用时自动回退 CPU；`max_megapixels`（默认 2.0）是 ViTMatte 推理时的像素上限（百万像素），超出会按比例缩小处理再放大回原尺寸。

**粗分割模型**：新增可选 `model`，默认 `BiRefNet-general`（与 `QG_BiRefNet` 共用 models/background_removal 缓存）；也可用环境变量 `QG_REMOVEBG_MODEL` 覆盖。

**ViTMatte 权重放哪**：优先从 ComfyUI 的 `models/background_removal/` 模型库读取，按方法自动选子目录——`VITMatte` / `VITMatte(local)` 读 `vitmatte-small-composition-1k/`，base 读 `vitmatte-base-composition-1k/`（目录内需有 `model.safetensors` 或 `pytorch_model.bin`，外加 `config.json` 与 `preprocessor_config.json`）。模型库命中即纯本地加载、不联网，也兼容 `extra_model_paths.yaml` 的挂载路径。模型库没有时才回退 HuggingFace 在线/缓存；也可用环境变量 `QG_VITMATTE_DIR` 指向自定义本地目录（优先级最高）。两个权重仓库均为 Apache-2.0，可自行下载后放入上述目录离线使用。

**输出**：`IMAGE` 是 RGBA（alpha 即精修遮罩，原图 RGB 不变），`MASK` 是同尺寸单通道遮罩。批次逐帧处理，帧数与顺序和输入一致。


### `QG_IDCardSheet` 身份证拼版

> **来源：⚠️ GPL 参考后重写**。功能参考 Goohaitools「身份证自动扶正拼版」（GPL-3.0），三处核心算法已替换（找四角、竖放判断、调色时机），流程与命名沿用；本包同为 GPL-3.0，已在 `THIRD-PARTY-NOTICES.md` 声明来源。是否构成衍生作品由作者判定为可接受重写。

**作用**：拍歪的卡片按蒙版找四角、拉成正射图，加圆角与投影，按厘米居中排在纸上。

**接线**：`front_image` + `front_mask`（必填，蒙版自动反相纠错）；`back_image` / `back_mask` 可选。

**控件**：`paper_w/h`（默认 A4）、`dpi`、`gap`、`card_w/h`（二代证 8.56×5.4cm）、`corner_pct`（圆角）、`rotate_180`（**卡片倒拍时手动打开**）、阴影三参、自动对比度 / 色调、`grayscale`、`bg_color`（普通字符串，手填 `#ffffff`）。

**输出**：`IMAGE`（整张纸）。


### `QG_Watermark` 斜向水印

> **来源：原创**。斜向平铺文字水印自实现。

**作用**：斜向平铺文字水印。`font` 默认指向随包的 **Noto Sans SC**（SIL OFL 1.1，含中文字形），中文水印开箱即用，不再依赖本机装没装中文字体；手动选 `<default>` 则是 PIL 内置位图字体，只有英文字形。

**控件**：`text`、`font`、`size`、`color`（`#RRGGBB` / 颜色名 / `r,g,b`）、`opacity`、`spacing`、`angle`。

**输出**：`IMAGE`。


### `QG_DualColorPicker` 双色取色器

> **来源：参照规格的独立实现**。功能形态参考 Goohaitools「孤海 取色器（双）」（GPL-3.0），代码自行编写，未复制其任何源码；图形化色板复用本包已有的 `web/qg_color_picker.js`。

**作用**：一次给出「模式 + 主色 + 辅色」三路字符串，供下游做纯色 / 渐变背景、配色、水印等用途。两个颜色控件直接画成整块色块（背景就是当前颜色），点一下弹出预设色板，也可以直接手填色值。

**怎么接线**：无输入，拖出来即可用。`主色` / `辅色` 两路是 `STRING`，接到任何接受字符串颜色的控件上（在目标控件右键选「转换为输入」再连）；`模式` 一路的类型是它的选项列表（前端显示为 `COMBO`），**可以直接驱动任何下拉输入**，例如本包「QG 自定义颜色」的 `模式`。

**控件说明**：

| 控件 | 默认 | 说明 |
| --- | --- | --- |
| `mode` | `solid` | 中文界面显示「纯色 / 上下渐变 / 中心渐变」，**存档值是英文** `solid` / `vertical_gradient` / `radial_gradient` |
| `primary_color` | `#213d50` | 主色，色块背景即当前颜色 |
| `secondary_color` | `#402633` | 辅色。纯色模式下不使用，但仍会输出 |

后端把颜色统一成小写 `#rrggbb`：`#rgb` 自动展开、无 `#` 前缀可吃、8 位带透明度取前 6 位、`(r, g, b)` 元组也能转；非法值回退默认色，不会把脏字符串透传给下游。

**输出怎么接**：`primary_color` / `secondary_color` 两路 `STRING`，`mode` 一路是下拉类型（值为英文字符串，可直连「QG 自定义颜色」等任何下拉输入）。本节点只负责「给颜色」，不生成图像；要出纯色 / 渐变图请用下游节点按 `mode` 自行合成。

### `QG_ColorPicker` 取色器

> **来源：参照规格的独立实现**。功能形态参考 Goohaitools「孤海 取色器」（GPL-3.0），代码自行编写，未复制上游源码。

**作用**：工作流的颜色起点。拖出来点色块选色，按模式直接输出颜色值和字符串，不需要上游先喂一个色值进来。

**与「QG 颜色转换」的区别**：颜色转换是中间节点，吃各种写法的色值字符串做格式互转；本节点是源头节点，自带图形化色块，直接选。

**控件说明**：

| 控件 | 默认 | 说明 |
| --- | --- | --- |
| `color`（颜色） | `#213d50` | 点整块色条打开色板（预设 24 色 / 手填 HEX / 系统取色器），也可直接手填带 `#` 的 3/6 位十六进制；非法值回退 `#213d50` |
| `mode`（模式） | `HEX` | `HEX` 大写十六进制 / `RGB` 整数 / `HSL` 百分比；值保持英文原文，存档与 API 不变 |

**输出怎么接**：

| 输出 | 内容 | 接到哪里 |
| --- | --- | --- |
| `color_control`（颜色控件） | 小写 `#rrggbb`，3 位输入保持 3 位 | 本包任意颜色控件：右键目标控件「转换为输入」再连 |
| `string`（字符串） | `HEX` → `#RRGGBB`；`RGB` → `r, g, b`；`HSL` → `h, s%, l%`（逗号后均带一个空格） | 提示词、文件名等文本输入 |

> **与孤海的 socket 差异**：孤海第 1 路输出是它自有的 `GHCOLOR` 类型，只能接孤海系节点；本包无自定义 socket，两路都用 `STRING`，因此**不能接孤海的 `GHCOLOR` 输入**，但能接本包所有文本 / 颜色输入。字符串值与孤海逐字节一致。

### `QG_ColorConvert` 颜色转换

> **来源：参照规格的独立实现**。功能形态参考 Goohaitools「孤海 颜色转换」（GPL-3.0），解析与转换代码自行编写，未复制上游源码。

**作用**：把一种写法的颜色字符串转成另一种格式。上游常接「QG 双色取色器」的输出（转输入后连线），也接受手填。

**怎么接线**：把上游 STRING 节点连到「色值」（在色值控件右键选「转换为输入」），或直接在控件里手填。

**控件说明**：

| 控件 | 默认 | 说明 |
| --- | --- | --- |
| `color`（色值） | `#FFFFFF` | 接受：`#hex` / `hex`（3 位自动展开）/ RGB 整数 / HSL 百分比 / 0-1 浮点；全角逗号括号自动归一；非法写法按白色处理 |
| `format`（转换后） | `#HEX` | 下拉值保持 `#HEX` / `HEX` / `RGB` / `HSL` 原文（存档与 API 不变），中文界面显示「带 # 十六进制」等注释 |

**输出怎么接**：

| 输出 | 内容 |
| --- | --- |
| `string`（字符串） | 按所选格式转换的结果：`#ffffff` / `ffffff` / `255,255,255` / `0,0%,100%` |
| `color_control`（颜色控件） | 同一颜色的规范化小写 `#rrggbb`，供把颜色喂给控件类下游 |

注意：与上游参考实现一致，`rgb(...)` / `hsl(...)` 函数式前缀**不**解析（裸 `255,0,128` 或全角括号写法可以）；0-1 浮点换算用截断（`0.5` → `#7f…` 而非 `#80…`）。

### `QG_CustomColor` 自定义颜色

> **来源：参照规格的独立实现**。功能形态参考 Goohaitools「孤海 自定义颜色」（GPL-3.0），渲染逻辑用 numpy 向量化自行编写（上游逐像素画点），未复制上游源码。

**作用**：按宽高生成一张纯色 / 渐变底图（`IMAGE`），做背景、底色、测试图都行。两个颜色控件直接画成整块色条（截图同款），点一下弹色板。

**控件说明**：

| 控件 | 默认 | 说明 |
| --- | --- | --- |
| `width` / `height` | `512` / `512` | 输出尺寸，1-8192 |
| `mode` | `solid` | 中文界面显示「纯色 / 上下渐变 / 中心渐变」，**存档值英文** `solid` / `vertical_gradient` / `radial_gradient`（与双色取色器同一套，可直接互换） |
| `color1` | `#364254` | 纯色整图用色；上下渐变**顶部**色；中心渐变**边缘**色 |
| `color2` | `#4C3843` | 上下渐变**底部**色；中心渐变**中心**色 |
| `scale` | `100` | 渐变推进（上下）或半径（中心）百分比：>100 提前完成、<100 更慢 |
| `grain` | `0` | 灰度颗粒噪声强度 0-100 |

**渐变方向**（与上游规格一致）：上下渐变是 颜色1（顶）→ 颜色2（底）；中心渐变是 颜色2（中心）→ 颜色1（边缘）。

**两处语义差异（刻意改进，已注明）**：插值系数钳制在 [0, 1]，缩放 >100 不会溢出颜色区间卷绕成杂色（上游未钳制）；缩放为 0 时上游语义保留——上下渐变退化为正常渐变、中心渐变全图为颜色1。

### `QG_DominantColor` 主色提取

> **来源：参照规格的独立实现**。功能形态参考 Goohaitools「孤海-主色提取 (多版本兼容)」（GPL-3.0），统计逻辑用 numpy 向量化自行编写（上游 Python 逐像素循环），未复制上游源码。上游标题里的「多版本兼容」是它针对旧版 torch / 前端做的 display 探测，与本包目标环境无关，未照搬。

**作用**：给一张图，输出整张图里**出现最多的颜色**（大写 `#RRGGBB` 字符串）。适合从参考图里取主色喂给换背景底色、渐变底图这些颜色控件。

**控件说明**：

| 控件 | 默认 | 说明 |
| --- | --- | --- |
| `downsample` | `8` | 降采样系数 1-16：统计前先把图缩到 宽//系数 × 高//系数（两边下限 4 像素），越大越快、越忽略局部细节 |
| `tolerance` | `15` | 颜色容差 0-100：每通道按 `c // 容差 * 容差` 量化分桶，0 则逐原色统计；越大越容易凑出 dominant 色 |

**统计规则**（与上游规格一致）：黑边白边像素（平均亮度 <15 或 >240）先剔除，全被剔则回退全部像素；主色取像素数最多的桶，频次并列时取亮度（通道和）更高的桶；批量图像只统计第一帧。

**输出怎么接**：`hex`（主色 HEX）是大写 `#RRGGBB` 字符串，可直接接到 `QG_BiRefNet` 的背景色、`QG_CustomColor` 的颜色控件、`QG_IDCardSheet` 的底色等 STRING 颜色入口。

### `QG_FaceAlign` 面部对齐

> **来源：参照规格的独立实现**。功能形态参考 Goohaitools「孤海-面部对齐」（GPL-3.0），几何与统计逻辑自行编写，未复制上游源码。人脸检测复用本包 `_face_helpers`（mediapipe 优先 + Haar 回退 + 模型按需下载），上游只支持 mediapipe。

**作用**：把**目标图**的人脸对齐到**参考图**——按人脸面积比缩放整图、按眼线角差旋转，让目标脸中心与参考脸中心重合后裁回参考图尺寸。做证件照排版前把歪脸/大小不一的照片统一构图，或换脸工作流前对齐两张脸，都靠它。不接参考图时只把目标图绕图中心摆平。

**控件说明**：

| 控件 | 默认 | 说明 |
| --- | --- | --- |
| `target_image` / `reference_image` | — | 目标图（必接）/ 参考图（可选）；批量都只取第一帧 |
| `confidence` | `0.3` | 人脸检测最低置信度 0-1。检出不了脸调低、误检调高（上游这个控件实际没接进检测器，本实现真正生效） |
| `angle_align` | `true` | 按两图眼线角差旋转目标图（>90° 自动归到 ±90° 内）；关闭则只缩放不平转 |
| `fill_mode` | `边框颜色` | 旋转/扩画布空白区底色：`自定义颜色` 用下面的色值；`边框颜色` 按目标图四边像素 /10 取整统计前 5 名加权平均（存档值英文 `custom_color` / `border_color`） |
| `custom_fill_color` | `#364254` | 自定义填充色的色值，点色块弹色板 |

**行为分支**：有参考图且两边都检出人脸 → 缩放+旋转+对齐裁剪（输出尺寸=参考图）；没检出参考脸或没接参考图但目标有人脸且角度对齐开 → 只摆平目标图（输出尺寸可能因旋转 expand 变大）；没检出人脸 → 原样返回目标图。

**人脸怎么选**：一张图里有多张脸时，取**离图中心最近**的那张（与上游一致）。


### `QG_IDPhotoOutfit` 证件照服装发型

节点内嵌式模板选择器（界面形态与 Goohaitools「孤海-证件照服装发型」一致）：节点体内直接展示「当前选中预览框 + 提示词框 + 搜索框 + 4 列缩略图网格」，点选模板即把其服装/发型提示词写进节点输出，下游可直接接 `QG_IDPhotoParams` 等证件照参数节点。

```
┌ QG 证件照服装发型 ────────────────────────┐
│ 风格类型   1. 服装_女士  ▾                │
│ ┌────────┐  ┌──────────────────────────┐ │
│ │ 已选    │  │ 提示词（选中自动填，可手改）│ │
│ │ 预览图  │  │ [🔍 搜索模板........... ✕]│ │
│ └────────┘  └──────────────────────────┘ │
│ ┌────┐┌────┐┌────┐┌────┐                 │
│ │缩略││缩略││缩略││缩略│  ← 4 列网格      │
│ └────┘└────┘└────┘└────┘                 │
└──────────────────────────────────────────┘
```

**面板功能**（`web/qg_id_photo_outfit.js`）：

| 功能 | 说明 |
| --- | --- |
| 预览框 | 左上角固定显示当前选中模板（绿框 + 「已选」徽章）；点它取消选择 |
| 风格类型下拉 | 节点控件保留原位；切换分类即刷新网格 |
| 提示词框 | 原生提示词控件隐藏，由面板内文本框替代；手动编辑实时写回 |
| 搜索 | 多关键词用**任意符号**隔开（空格/逗号/顿号/斜杠均可），全部命中才保留；搜索时跨全部分类并给结果带分类角标 |
| 网格 | 4 列缩略图懒加载，hover 放大；选中卡绿框 + 右上角 ✓；图片加载失败自动退化为标题占位块 |
| 高度自适应 | 画廊随节点缩放自动调整可见行数；新建节点默认按 3 行固定尺寸 |
| 状态恢复 | 选中状态存节点 properties，保存/刷新工作流后自动还原；旧档按提示词反查模板 |

**素材随包内置，开箱即用**：插件目录 `models/id_photo/` 自带 **7 个分类 200 张**模板图（女士 48 / 男士 40 / 女童 24 / 男童 32 / 老年 24 / 发型_女士 28 / 发型_男士 4），每张都配好提示词（`id_photo_data.json`）。素材来源为 Goohaitools「孤海」公开素材库，许可见 `THIRD-PARTY-NOTICES.md`。

想用自己的素材，放 **`ComfyUI/models/id_photo/`** 即可——**两个位置合并显示**（同名分类补图，同名文件以内置优先）。目录格式：

```
models/id_photo/                ← 插件目录内置 / ComfyUI/models 用户自备，两处同格式
├── 1. 服装_女士/              ← 分类目录，名字任意
│   ├── 01.西装.jpg            ← 模板图（jpg/jpeg/png/webp）
│   └── ...
├── 2. 服装_男士/
└── id_photo_data.json         ← 提示词映射
    {"prompts": {"1. 服装_女士": {"01.西装": "深灰色廓形西装……"}}}
```

提示词解析优先级：`id_photo_data.json` 的映射 → 文件名内嵌（`标题-提示词.jpg`）→ 空。**目录格式与 Goohaitools「孤海-证件照服装发型」的素材完全兼容**——把其 `image/ID_Photo/` 下任何内容拷进任一 `models/id_photo/` 即可直接使用。没放素材时下拉显示「无数据」，网格里有放置指引；素材增删改**无需重启**，后端按目录签名自动重扫，刷新页面即生效。


### `QG_MarriageCloth` 结婚登记照服装

> **来源：原创（参照规格）**。功能规格参考 Goohaitools「孤海-结婚登记照服装」（GPL-3.0），代码自行实现；内置素材取自其公开素材库（81 张，原样复制）。

**作用**：挑一张双人服装参考图，直接当 IMAGE 输出给图生图——比用文字描述服装稳定得多。`image_index = 0` 时输出纯色底图（`#6c1e27`），跟上游一致，也方便当"没有服装"的占位。

```
QG_MarriageCloth ──image──▶ 图生图（Qwen-Image 等）的参考图输入
```

```
┌ QG 结婚登记照服装 ──────────────────────┐
│ 服装序号   1        （面板点选自动写回） │
│ 缩放方式   等比缩放补边 ▾               │
│ 目标宽/高  1024 / 512                   │
│ 底色       #6c1e27                      │
│ ┌─────────── 预览（已选）────────────┐  │
│ │                                    │  │
│ └────────────────────────────────────┘  │
│ ┌────┐┌────┐┌────┐   ← 缩略图网格      │
│ └────┘└────┘└────┘     点选 = 写回序号   │
└─────────────────────────────────────────┘
```

**控件**：

| 控件 | 说明 |
| --- | --- |
| `image_index` 服装序号 | 1..N 选一张（N 见面板），0 = 纯色底图。素材增删后序号按**文件名自然排序**重排（`2.jpg` 不会再跑到 `10.jpg` 后面） |
| `resize_mode` 缩放方式 | `fit_pad` 等比缩到框内、空白补底色（默认，**不变形**）；`stretch` 拉伸填满（上游行为）；`original` 完全不缩放 |
| `target_width` / `target_height` | 输出像素尺寸，默认 1024×512；`original` 模式下忽略 |
| `pad_color` 底色 | 纯色底图与 `fit_pad` 补边的颜色，吃 `#RRGGBB`、`#ABC` 或颜色名 |

**面板**（`web/qg_marriage_cloth.js`）：上方预览框（白框 + 「已选」绿标，未选时显示「无」），下方缩略图网格——列数随节点宽度自适应（2~5 列），再点一次已选中的卡片 = 取消选择。选中项存进节点 `properties`，存盘/重开工作流自动还原。

**素材**：插件内置 81 张（`models/marriage_cloth/`），开箱即用；还可以往 `ComfyUI/models/marriage_cloth/` 放自己的图，两个目录**合并显示**（同名以内置优先），增删改无需重启后端。

### `QG_MaskTopExpand` 头顶遮罩扩展

> **来源：原创（参照规格）**。功能规格参考 Goohaitools「孤海-头顶遮罩」（GPL-3.0），代码自行实现。

**作用**：证件照头顶留白不够时，光靠裁剪无法把发量补回来——得让生成阶段"往上画"。这个节点从遮罩最高点向上补一块矩形，交给外补画板/扩图节点当重绘区。

```
QG_IDPhotoCrop ──mask──▶ QG_MaskTopExpand ──mask──▶ 外补画板 / 扩图节点
```

| 控件 | 说明 |
| --- | --- |
| `expand_x` 水平半径 | 矩形宽度 = 中心 x ± 该值 |
| `expand_y` 向上高度 | 从最高点向上延伸多少像素 |
| `center_mode` 中心取法 | `top_center` 顶行中点（默认，贴头顶）；`bbox_center` 外接框中点（人物居中更稳）；`mask_center` 质心（头发左右不对称时偏向发量多的一侧） |
| `feather` 羽化 | 矩形边缘高斯模糊半径，0 = 硬边。硬边直接接外补画板会在接缝处留一条亮线 |
| `keep_original` 合并原遮罩 | 开启（默认）与原遮罩取并集；关闭只输出新矩形 |

**和上游的两处不同**（都是实测会咬人的）：

- **原遮罩不再被丢掉。** 上游 `new_mask = zeros_like(...)` 之后只填矩形，叫 expand 实际是 replace。
- **批量遮罩逐帧处理。** 上游 `mask.squeeze(0)` 假定只有一帧，批次进来后维度错位。
- 另外顶行偶尔一个游离像素会把矩形整体拽偏，所以中心取**顶行横坐标的中位数**而不是平均值。


### `QG_ImageComposite` 图像合成

> **来源：原创（参照规格）**。功能规格参考 ComfyUI_essentials 的 `ImageComposite+`（GPL-3.0），代码自行实现。

**作用**：把源图（角标、水印、裁下来的头像、另一张尺寸不同的图）放到目标画布的指定位置，遮罩决定哪些像素替换底图。**目标图的尺寸就是输出尺寸**，输出永远是目标大小的完整画面——不是把两张图拼成一张更大的图。

```
目标画布 ──▶ destination ┐
源图     ──▶ source      ├──▶ QG_ImageComposite ──▶ 合成图（= 目标尺寸）
遮罩（可选）▶ mask       ┘
```

**坐标怎么算**：

```
最终位置 = (x + offset_x, y + offset_y)
```

原点在画布左上角，x 向右、y 向下，单位是像素。`offset_x` / `offset_y` 只是叠加量：单独用时留 0；接上游动态值（逐帧坐标、滑块输出）时接到偏移上，x/y 保持基线不动，清掉偏移就回原位。

| 控件 | 说明 |
| --- | --- |
| `x` / `y` | 源图左上角落在画布上的位置，**可为负**（负值 = 从左侧 / 上侧裁掉一部分再贴） |
| `offset_x` / `offset_y` | 叠加到 x / y 上，便于被上游驱动 |
| `mask` 遮罩（可选） | 与源图同尺寸：白 = 用源图、黑 = 留底图、灰 = 按比例混合。尺寸不符自动缩放到源图尺寸；单帧遮罩覆盖所有帧。不接 = 源图直接覆盖 |

**和上游的三处不同**（都是实测会出错的地方）：

- **负坐标不再贴错位置。** 上游用 `d[y:y+h, x:x+w]` 直接切片，x/y 为负时 Python 走负索引，本该从左侧裁掉的像素反而被贴到画布右边。这里先求「源图矩形 ∩ 画布矩形」的交集再取对应区域，四边越界统一按裁切处理。
- **目标帧不会被悄悄丢掉。** 上游把目标强行截到源图帧数，目标帧更多时后面的帧直接消失。这里取 `max(目标帧数, 源帧数)`，短的一边重复最后一帧补齐。
- **完全落在画布外会留一行日志**，而不是静默输出一张和底图一模一样的图（输出结果本身仍是对的）。

**典型用法**：

- 证件照加斜向水印：`QG_IDPhotoCrop` → `destination`，`QG_Watermark` → `source`，`x`/`y` 留 0，不接遮罩；
- 抠好的头像贴到纯色底：纯色图 → `destination`，前景图 → `source`，遮罩 → `mask`，用 x/y 微调位置；
- 批量贴同一张角标：`source` 只有一帧时自动广播到目标每一帧。


### 百度通道的几个硬限制（踩过才知道）

| 限制 | 现状 | 处理方式 |
| --- | --- | --- |
| 未认证账号单次 **1000 字符**、QPS **1** | 按字符切块（不是字节），块间强制隔 1.05 s | 超长文本自动分段，不会因为第二段撞限流而整段失败 |
| 认证后单次 6000 字符 | 仍按 1000 切 | 更保守，但一条提示词通常几百字符，实际只发一次请求 |
| 54003 / 54005 / 52002 属可重试 | 指数退避重试 3 次（54005 等 3 s，官方建议） | 网络抖动不再直接原文直通 |
| 54004 余额不足、20003 内容风险 | 不重试，立即报错 | 错误码翻成中文并给出处理建议 |
| 提示词里有 `blood`、`gun` 这类词可能被判 20003 | 百度两条通道都会 | 换 GLM / DeepSeek 通道，或改写措辞 |

和 `QG_Translate` 是分工不是替代：那个是通用翻译器（源语言/目标语言/地址/模型/Key 全摊在节点上），这个是固定链路的快捷版。翻译核心（服务商预设、`config.json` 读写、HTTP 调用、缓存）在 `translate_core.py` 里，两个节点共用——**以后不想要 `QG_Translate` 了，直接删掉 `translate_node.py` 和 `__init__.py` 里那几行注册即可**，设置面板和提示词翻译都不受影响。

## API 服务商（`设置 → QG 工具 → API 服务商`）

一个服务商可以挂多个模型，不用再为同一个中转站的每个模型各建一条。

- 自定义服务商的详情里是「模型列表」：每行一个模型名，★ 是默认模型，✕ 删除，右上角「＋ 添加模型」。改完失焦即存，没有保存按钮。
- **节点下拉的规则**：只写服务商名 = 用它当前的默认模型；写成 `服务商/模型` = 指名那个模型。默认模型不会重复列一遍（`DeepSeek` 和 `DeepSeek/deepseek-chat` 两个选项看着一样，只用前者）。
- **老配置自动兼容**：只有单个 `model` 字段的条目读进来就展开成一元素列表，`model` 继续作为默认模型的镜像写回，不需要手动迁移。
- 内置预设也各自带了几个常用模型（如智谱 `glm-4-flash` / `glm-4.5` / `glm-4.5v` / `glm-4.6v-flash`）。内置厂商的地址和模型列表只读——想加自己的模型，新建一条自定义服务商。
- 图像反推节点的「视觉服务」下拉会把每个服务商的**所有**模型展开成独立选项；翻译类节点（`QG_Translate` / `QG_PromptTranslate`）用同一份展开列表。
- **翻译不要挑视觉模型**：`glm-4.6v-flash` 这类是看图用的，热门时段经常回 `HTTP 429 该模型当前访问量过大`，节点就只能原样输出。纯翻译用 `glm-4-flash`（免费、快）或 `glm-4.5`。
- **删掉或改名一个服务后，节点上已选的那个值不会被悄悄换掉**。早先的写法是「值不在下拉列表里就换成第一项」，结果在设置面板里删了一个服务，节点会静默切到另一个服务上跑，界面上没有任何痕迹。现在改成保留原值，只在第一次遇到时弹一条提示（`QG 工具：服务已失效`）并写一条 `console.warn`；真正跑的时候后端会明确报「这个服务没有 API 地址」，由你决定改选哪个。空值（新拖出来的节点）仍然按默认服务补齐。

### Key 存哪里（重要）

所有 Key 都存在 **`ComfyUI/user/ComfyUI-QG-Multipack/config.json`**（user 目录随 ComfyUI 走，不在插件目录里）：自定义服务商的 `api_key`、内置预设的 `preset_api_keys`、百度翻译的 `appid` + `key`。

这是刻意设计：**插件目录整个拷给别人、传 GitHub、打成 zip，都不会带上密钥**。老版本把 config.json 放在插件目录，首次运行时插件会自动把它迁移到 user 目录，无需手动处理。`.gitignore` 仍保留 `config.json` 条目作为兜底。

在 `设置 → QG 工具 → API 服务商` 面板里填 Key 即可；`config.json` 不存在时插件按「什么都没配」启动，不会报错。分享给别人的插件包，对方在自己的设置面板里填自己的 Key。

注意 `rules.json`（自定义规则）现在也优先存在 **`ComfyUI/user/ComfyUI-QG-Multipack/`**（与 config.json 同一处），插件装在 Program Files 这类只读位置时照样能保存。老版本写在插件目录的那份会在首次访问时复制过去、原文件保留；插件目录里若残留旧副本，打包前删掉即可（默认规则在代码里，删了不影响）。

如果 Key 已经泄露过，去各家控制台**重新生成**，不要指望删文件能收回——它可能已经进了某个 git 历史或聊天记录。

## 图像反推提示词（`QG_ImageToPrompt`）

给一张图，用视觉模型反推成能复现它的提示词。控件顺序和 `ComfyUI-Prompt-Assistant` 的「图像反推提示词」一致：

```
图像（输入口）──▶ 规则预设        像素级描述   ← 设置 → QG 工具 → 提示词规则
                  自定义规则      Disable
                  自定义规则内容  （自定义规则打开时整段替换预设）
                  user_prompt     （附加要求，拼在规则后面）
                  视觉服务        智谱/glm-4.6v-flash
                  自动释放显存    Enable
                  随机种子        0 + 生成后控制
                                    └──▶ 提示词输出 / 提示词列表
```

- **规则决定输出形态**，不是换个说法而已：

  | 规则 | 输出 | 语言 |
  | --- | --- | --- |
  | 像素级描述 | 按「主体—服装—构图—环境—光线—色彩—风格」组织的 200~400 字段落 | 中文（跟随 `user_prompt`） |
  | Tag 标签流 | 30~60 个逗号分隔标签，带 `(tag:1.2)` 权重 | 英文（SD 生态通用） |
  | 自然语言短描述 | 60~90 词英文段落，面向 SDXL / Flux | 固定英文 |
  | 图像编辑指令 | 配合 `user_prompt` 说明要改什么，输出一条编辑指令 | 中文（跟随 `user_prompt`） |
  | 视频动态提示词 | 首帧静态描述 + 运动 / 镜头 / 环境动态 | 中文（跟随 `user_prompt`） |

- **语言只看 `user_prompt`**：它为空就输出中文，用英文写就用英文。随图附带的那句固定分析请求不算用户语言——这一点在提示词里写死了，否则模型会跟着那句英文跑。
- **视觉服务是「服务商/模型」**：地址与 Key 取自 `设置 → QG 工具 → API 服务商`，节点上只选名字，工作流文件里不落密钥。内置清单有智谱（`glm-4.6v-flash` / `glm-4.5v` / `glm-4v-flash` / `glm-4v-plus`）、通义（`qwen3-vl-plus` 等）、硅基流动、OpenRouter、本地 Ollama；自定义服务商配了几个模型，下拉里就展开几项。
- **图片先压再发**：长边 1024、JPEG 质量 75，一张 896×1152 的图 base64 后约 65 KB。batch 帧数越多压得越狠（>6 帧 768、>10 帧 640、>16 帧 512），否则一次请求几十帧会超时。
- **400 自动降级**：先带着各家关思考的参数（`thinking: disabled` / `enable_thinking: false` / `reasoning_effort: none`）发；服务商不认就逐级去掉，最后只剩 `model` + `messages`。规则与图片分两条消息发（system 独立），这是智谱 GLM-4V 一类的硬要求。
- **思考链两处都关**：请求里关一次，输出端再剥一次 `<think>...</think>`、`<｜end▁of▁thinking｜>` 和 Markdown 围栏。
- **batch 逐帧反推**：每帧独立调用，`提示词输出` 用 `\n---\n` 合并，`提示词列表` 给出逐帧结果（单张时是单元素列表）。
- **种子只控制要不要重跑**：固定时同一张图复用上次结果、不重复扣费；切成 `randomize` 每跑一次重新反推，用来换措辞。
- **失败直接报错**，不像翻译节点那样原文直通——反推没有「原文」，静默返回空串只会让下游拿到空提示词。
- **流式预览**：请求带 `stream=true`，后端逐块收 SSE，通过 `qg-vlm-stream` 事件推给前端，节点下方实时显示「反推中…」和已经收到的文字，跑完保留 6 秒。服务商不吃 `stream` 时（返回整包 JSON）自动退回等全部返回，行为与以前一致。预览只是锦上添花，推流失败不影响执行。

### 规则管理器（`设置 → QG 工具 → 提示词规则`）

规则正文不存在 Python 里，改措辞不用动代码、不用重启。卡片上显示「几组几条 · 图像反推默认用哪条」，点「规则管理器…」打开：

| 页签 | 用途 | 内置 |
| --- | --- | --- |
| 提示词优化规则 | 提示词 → 更好的提示词（`QG_PromptOptimize`） | 4 条：扩写-通用 / 润色-精炼 / 扩写-细节质感 / 改写-英文 |
| 图像反推规则 | 图 → 提示词 | 4 条：像素级描述 / Tag 标签流 / 自然语言短描述 / 图像编辑指令 |
| 视频反推规则 | 首帧 → 带运动的提示词 | 1 条：视频动态提示词 |
| 翻译规则 | 翻提示词时的风格约束 | 1 条：提示词翻译（默认） |

- **每组只能激活一条**（表格第一列那个圆点）。它的两个用处：新拖出来的节点默认选它；某条规则被删、而老工作流还存着它的名字时，用它兜底。
- **改完点「保存」才落盘**，点「取消」当没动过；「恢复内置」会覆盖全部改动（含自己加的规则）。
- 数据优先存在 user 目录的 `rules.json`（与 config.json 同一处；原子写入，不会留半个文件）。**没有这个文件也能跑**——直接用代码里的内置默认，所以删掉它等于恢复出厂设置；拿不到 user 目录时才回退插件目录。
- **改名不会打断老工作流**。每条规则在 `rules.json` 里有稳定 `id`；改名保存时后端自动把旧名记进 `aliases`，`resolve()` 依次按「名字 → id → 旧名」匹配。ComfyUI 提交工作流时还会按节点定义的选项列表校验，所以这份列表里也带着旧名（前端下拉只显示当前名字，界面上看不到旧名）。要注意的反面是：改名后旧名会一直留着，重名时以真实名字优先，别名自动让位。
- 翻译规则会拼进翻译请求的同一条 system 消息（百度大模型通道走 `reference` 字段）；改了措辞，翻译缓存会跟着失效，不会拿旧结果。
- **规则是数据，改了全局生效**。`QG_PromptOptimize` 的规则正文在 `rules.json` 里，改完所有工作流里的这个节点都跟着变——想让老工作流保持原样，就得为它单独存一条自定义规则。
- **改规则不会让你白跑一次**。节点上只存规则**名字**，正文在文件里，所以后端的 `IS_CHANGED` 会额外拼一个 `rules.json` 的指纹（文件名 + mtime + 大小，不读盘）。改完措辞保存，同一个节点下次执行时会重新请求，不会拿 `rules.json` 里那份旧正文的缓存结果。这条对三个用规则的节点都成立：`QG_ImageToPrompt`、`QG_PromptOptimize`、`QG_PromptTranslate`、`QG_Translate`。
- **节点下拉会实时跟着变**。规则管理器保存后派发一次前端事件，已打开的画布上那几类节点的下拉会立刻换成新清单；`QG_PromptOptimize` 只列「提示词优化」这一组（后端 `INPUT_TYPES` 就是这么给的），不会混进图像反推的规则。
- **优化组曾经是空的**（v3 之前没有对应节点），所以升级后读到一个空的优化组且文件版本低于 3 时会自动补上四条内置规则；补过一次并保存后版本升到 3，此后主动删空就是明确意图，不会再塞回来。整组删空时节点仍能跑——它内部兜底用「扩写-通用」的正文。

## 证件照简易提示词（`QG_IDPhotoPrompt`）

13 个下拉（构图 / 国籍 / 性别 / 体型 / 发色 / 发型 / 服装颜色 / 服装款式 / 服饰佩饰 / 妆容 / 表情 / 背景色 / 其他佩饰）加一个 `seed`，组合成一句中文人像提示词，输出 `STRING` 直接接文本编码器。每维都能选「无」（不写入）或「随机」（按 seed 从该维候选里抽一个），相同 seed + 相同下拉必然得到同一句。

**下拉值是稳定的英文编号**（`composition_01`、`nationality_03` …），中文只是显示名（`web/qg_id_photo_prompt.js` 的 `getOptionLabel` 与 Menus 词表，共 229 条，均由后端选项表生成）。这样以后改中文文案不会让旧工作流的存档值失效，也不会把中文塞进 API / 存档。

相对参照规格修掉三处：

| 问题 | 本包做法 |
| --- | --- |
| 上游 `random.seed(seed)` 改的是**进程全局**随机状态，会悄悄影响 ComfyUI 里其它节点的随机结果 | 每个维度由 seed 派生一个独立 `random.Random`，互不干扰，也不碰全局状态 |
| 背景选「简单背景」会拼出「简单背景简单背景」 | 值里已含「背景」时不再追加后缀 |
| 中文值进存档，改文案即坏工作流 | 英文编号值 + 中文显示映射 |

## 证件照混合排版（`QG_PhotoSheetMixed`）

A5 相纸上的 13 种固定版式：6 种单尺寸网格（小1寸 14 张 / 标准1寸 12 张 / 大1寸 8 张 / 小2寸 8 张 / 标准2寸 8 张 / 大2寸 8 张）、6 种双尺寸混排（如「1寸 8张 + 2寸 4张」「小1寸 9张 + 小2寸 4张」，部分版式把照片旋转 90° 横排，另有竖版 A5 的「22x32 8张 + 31x46 4张」与「2.4×3.4 + 3.3×4.8 无间距」）、1 种零间距单尺寸网格（3.4×4.9 8 张）。相纸尺寸、照片尺寸、间距都是**厘米**，描边宽度与文字大小是**像素**，DPI 负责换算。

| 控件 | 说明 |
| --- | --- |
| `layout` | 13 种版式，值为英文 key（`mix_1_8_2_4` 等），中文名仅显示 |
| `dpi` | 默认 300；A5 横版 21×14.8cm 在 300dpi 下是 2480×1748 px |
| `border_px` / `border_color` | 描边画在**照片内部**，不会把网格撑大；颜色支持 `#RGB` / `#RRGGBB` / 颜色名 |
| `caption` / `font` / `font_size` | 底部文字（默认 0 = 不印），字体下拉首项是随包的 Noto Sans SC（OFL，含中文），其后是 `models/fonts` 与系统字体 |
| `fit_to_paper` | 版式放不下时整体等比缩小；关闭则报出「需要多少 px / 可用多少 px」 |

输出 `IMAGE`（批量逐帧，一帧一张相纸）、`STRING` 版式中文名、`INT` 一张相纸上的份数。

实现上 13 个版式是**数据**：每条版式由若干「横带」组成，横带里是若干「区域」（尺寸 + 行列 + 是否旋转），一个引擎统一算居中与粘贴，几何计算 `layout_plan()` 是纯整数运算、不依赖 PIL，所以 5 档 DPI × 13 版式的「不越界 / 不重叠 / 份数正确」可以离线断言。相对参照规格修掉四处：批量只取第一帧、`ImageOps.expand` 描边撑大照片挤占相邻格、超界被 `paste` 静默裁切、`#ABC` 短 hex 按固定下标切字符串导致异常。

## 简易 Seg 检测（`QG_SimpleSegDetectorSEGS`）

把 BBox 检测器找出的矩形框打包成 Impact-Pack 的 `SEGS`，直接接它的 Detailer 等下游节点。控件与 Impact-Pack「简单检测器 (SEGS)」一致：BBox 阈值/膨胀、裁剪系数、最小尺寸、次要三项、SAM 遮罩提示阈值、扩张后。

- **前置条件**：本机必须装 `ComfyUI-Impact-Pack`。本节点的三个输入类型（`BBOX_DETECTOR` / `SAM_MODEL` / `SEGM_DETECTOR`）与输出 `SEGS` 都是它定义的；未安装时节点仍会显示，只在运行时给中文提示，不影响本包其余节点。类型字符串故意不加 QG 前缀——要与 Impact-Pack 逐字一致才能连线。
- **推荐接线**：Impact 的 BBox 检测器加载器 → 本节点的「BBox 检测器」；图片进「图像」；可选接 Impact 的 `SAMLoader` 输出把矩形细化成轮廓。给了 SAM 时优先走 SAM，否则给了 SEGM 检测器才用其遮罩取交。若 SEGM 与 BBox 是同一个检测器对象（YOLO-World 常见接法），自动省掉一次重复检测。
- **限制**：只接受单张图片，batch 大于 1 直接报错（与 Impact 的 detector 口径一致）。
- **实现边界**：按公开规格独立实现，未复制上游源码；运行时调用 `impact.core` 的公开接口。来源与许可证见 `THIRD-PARTY-NOTICES.md`。

## 前端增强（不产生节点，直接作用于画布）

| 文件 | 作用 |
| --- | --- |
| `web/qg_color_picker.js` | 把字符串颜色字段变成色块 + 弹出色板（`QG_BiRefNet.background_color` 用胶囊样式；`QG_DualColorPicker` 的 `primary_color` / `secondary_color`、`QG_CustomColor` 的 `color1` / `color2`、`QG_ColorPicker` 的 `color` 用整块色条样式） |
| `web/qg_custom_color.js` | 「QG 自定义颜色」模式下拉的中文显示（值仍为英文，与双色取色器同一套） |
| `web/qg_dual_color_picker.js` | 「QG 双色取色器」模式下拉的中文显示（值仍为英文）；把 `mode` 输出槽类型对齐成 `COMBO`，使它可直接连下游下拉输入 |
| `web/qg_id_photo_size_picker.js` | 「QG 证件照尺寸选择」把 `preset` 输出槽类型对齐成 `COMBO`，使它可直接连裁剪 / 参数节点的预设下拉（改 `nodeData` 用 `try/catch` 兜住冻结）；中文标签复用 `qg_photokit_zh.js` 的同一份预设文案 |
| `web/qg_color_convert.js` | 「QG 颜色转换」格式下拉的中文显示（值保持 `#HEX` / `HEX` / `RGB` / `HSL` 原文） |
| `qg_color_picker.py` | QG_ColorPicker（点色块选色，按 HEX / RGB / HSL 输出颜色值与字符串） |
| `web/qg_face_align.js` | 「QG 面部对齐」填充模式下拉的中文显示（值仍为英文 `custom_color` / `border_color`） |
| `web/qg_id_photo_outfit.js` | 「QG 证件照服装发型」的模板选择面板（网格缩略图 / 搜索 / 点选写回提示词） |
| `web/qg_marriage_cloth.js` | 「QG 结婚登记照服装」的画廊面板（预览框 / 缩略图网格 / 点选写回序号与文件名） |
| `web/qg_id_photo_prompt.js` | 「QG 证件照简易提示词」13 个下拉的中文显示（229 条映射由后端选项表生成，值仍为英文编号） |
| `web/qg_photo_sheet_mixed.js` | 「QG 证件照混合排版（A5）」13 种版式的中文显示（值仍为英文 key） |
| `web/qg_translate.js` | 「设置 → QG 工具」里的翻译服务商管理面板（含百度翻译页签） |
| `web/qg_rules.js` | 「设置 → QG 工具 → 提示词规则」里的规则管理器（四个页签、增删改、单选激活） |
| `web/qg_stream.js` | 两件事：图像反推 / 提示词优化的实时预览画在节点下方（标题由后端 `label` 决定，所以是「反推中…」或「优化中…」）；失败原因也画在同一位置（canvas 绘制，随节点移动缩放） |

下面一节说明如何给别的颜色字段加取色器。

### 给别的颜色字段加取色器

想给别的节点的字符串颜色字段也加图形化取色，在 `web/qg_color_picker.js` 顶部的 `COLOR_WIDGETS` 里加一行即可，后端不用改。目前挂着 `QG_BiRefNet` 的 `background_color`、`QG_DualColorPicker` 的 `primary_color` / `secondary_color`、`QG_CustomColor` 的 `color1` / `color2` 与 `QG_FaceAlign` 的 `custom_fill_color`；写进 `BANNER_TEXT` 的控件会改用「整块色块 + 居中文字」绘制。

## 安装

1. 整个目录放进 `<ComfyUI>/custom_nodes/`；
2. 装额外依赖：

   ```
   <ComfyUI>/python_embeded/python.exe -m pip install -r requirements.txt
   ```

3. 重启 ComfyUI。

> **字体（随包）**：`assets/fonts/` 内置 **Noto Sans SC**（`NotoSansSC-VF.ttf`，16.9 MB，SIL OFL 1.1，可自由再分发与商用），许可全文在同目录 `OFL.txt`；字体文件为官方原样分发、未修改。`QG_PhotoSheet` / `QG_PhotoSheetMixed` / `QG_Watermark` 的字体下拉把它排在首位，`QG_Watermark` 的默认字体也指向它，中文标注与水印开箱即用。官方文件是可变字体、默认字重为 Thin，加载时统一固定到 `Regular` 实例（不改动字体文件本身）。
>
> 想用自己的字体：把 `.ttf/.otf/.ttc` 放进 `ComfyUI/models/fonts/`，或直接用系统字体目录（Windows 为 `C://Windows//Fonts`），下拉会自动列出。
>
> **不随包的字体**：插件目录下原有的 `fonts/` 是本机自备的专有字体（苹方、华文细黑、方正超粗黑、中易楷体/黑体、Bitstream OCR-B / Swis721、Akkurat、Capture it），内嵌许可均为 All Rights Reserved，其中苹方明确写着 `Apple Inc internal use only. Do not distribute.`。该目录被 `.gitignore` 与 `打包备份.py` 双重排除，**不进仓库、不进备份包**，节点字体下拉也不读它。
>
> **模板素材**：`QG_IDPhotoOutfit`（证件照服装发型）与 `QG_MarriageCloth`（结婚登记照服装）的素材**随插件内置**——前者 7 分类 200 张服装/发型模板 + 提示词 JSON，后者 81 张双人服装图。还可以往 `ComfyUI/models/id_photo/` 和 `ComfyUI/models/marriage_cloth/` 放自己的图，与内置素材**合并显示**（同名以内置优先）。目录格式见各自章节说明，与 Goohaitools「孤海」素材兼容。

### 各节点依赖一览

大部分节点只用 ComfyUI 自带的 numpy / Pillow / torch，装上就能用；下表列出需要额外东西的节点。

| 节点 | 需要什么 | 缺了会怎样 |
| --- | --- | --- |
| `QG_MaskByName` | ComfyUI 内置的 `SAM3_Detect`（`comfy_extras/nodes_sam3.py`），以及 SAM3 权重 `sam3.1_multiplex_fp16.safetensors`（放 `models/checkpoints`，或 `extra_model_paths.yaml` 里配置的任一 checkpoints 目录） | 节点仍在菜单里；下拉里可能列出别的 checkpoint，运行时报「这不是 SAM 3 权重」 |
| `QG_BiRefNet` | pip：`timm`、`transformers`、`opencv-python`；权重按需从 HuggingFace 下载 | 缺 pip 包时节点能拖出来，**运行时**才报 ImportError；权重首次运行自动下载（见下一节） |
| `QG_FaceRectify` | pip：`dlib-bin`；`opencv-python`；随包的 `shape_predictor_5_face_landmarks.dat` | 缺 `dlib` 时运行报 ImportError；缺 `.dat` 时原图直通并在控制台打一行提示 |
| `QG_Translate` | 外部大模型 API 与 Key（DeepSeek / Kimi / 通义 / 智谱 / SiliconFlow / OpenRouter / Ollama / 自定义） | 没配 Key 运行会报 401，原因画在节点下方 |
| `QG_PromptTranslate` | 百度翻译（appid + key），或上面任一 LLM 服务商 | 同上，失败原因同样画在节点下方 |
| `QG_ImageToPrompt` | 视觉模型 API（共用服务商配置，要选**支持图像输入**的模型） | 选到纯文本模型会报错 |
| `QG_PromptOptimize` | 对话模型 API（共用服务商配置，无需图像能力） | 没配地址/Key 时运行报错，原因同时画在节点下方 |
| `QG_QwenPromptOptimizer` | pip：`llama-cpp-python>=0.3.48`（JamePeng fork）+ `diskcache`；`models/LLM` 下自备 Qwen Image 2.1 GGUF（T2I / I2I / mmproj 三个文件） | 缺依赖时节点能拖出来、能连线，运行报「llama-cpp-python 不可用」；节点上会出现「点击查看安装说明」按钮，给出匹配 wheel 后缀与发布页地址，**需手动下载安装**（Registry 合规，不自动装），装完要完全重启 ComfyUI |

### 容错到什么程度

每个节点在 `__init__.py` 里都是独立的 `try/except` 导入，删掉任意一个节点文件只会少那一个节点，其余照常加载。

要注意的是 **pip 包缺失属于运行时错误，不是加载时错误**：`dlib`、`timm` 都是延迟导入的，所以缺包时节点照样出现在菜单里、也能连线，只有真正执行到那一步才会红。只有 `shape_predictor_5_face_landmarks.dat` 缺失是优雅降级（原图直通）。排查时遇到「节点在、一跑就 `ModuleNotFoundError`」，就是这个原因。

## QG_BiRefNet 支持的模型

下拉里共 18 项，全部是 BiRefNet 架构，**权重来自 3 个不同的 HuggingFace 仓库**，下表逐项列出「本地文件名 → 完整下载地址 → 放置路径」。节点首次运行某个模型时会按这张表自动下载；想手动放，也照这张表放。

### 目录约定

v2.19 起本包所有抠图模型统一收敛到 ComfyUI 的 `models/background_removal/` 类别（与本包其它抠图节点同一处，便于集中管理）：

```
<ComfyUI>/models/background_removal/
├── BiRefNet/     ← 17 个 BiRefNet 变体（RMBG-2.0 除外）+ 3 个模型定义文件
├── RMBG-2.0/     ← RMBG-2.0 单独一个目录（subdir）
├── vitmatte-small-composition-1k/  ← 细节精修小模型
├── vitmatte-base-composition-1k/   ← 细节精修大模型
├── RMBG-1.4/      ← rmbg-1.4 官方完整权重（rmbg-1.4.onnx + model.pth），优先从这里读
├── rmbg-1.4.onnx / birefnet-v1-lite.onnx  ← 根目录旧 rmbg-1.4.onnx 仍兼容读取；birefnet-v1-lite 按需下载在根目录
└── modnet_*.onnx  ← 随包副本（也在插件 models/background_removal/）
```

**旧目录仍可读**：以前下载在 `<ComfyUI>/models/RMBG/{BiRefNet,RMBG-2.0}/` 的模型照常命中，不必搬动；但新下载一律写进上表的 `background_removal/`，不再生成 RMBG 副本。

`<ComfyUI>` 指 ComfyUI 主目录（本机是 `D:/ComfyUI_windows_portable/ComfyUI`）。

### 一、BiRefNet 家族：1038lab 主仓库（12 项）

仓库：<https://huggingface.co/1038lab/BiRefNet>
放置位置：全部 `<ComfyUI>/models/background_removal/BiRefNet/`（旧 `models/RMBG/BiRefNet/` 仍可读）

| 模型名 | 本地文件名（不可改） | 大小 | 下载地址 |
| --- | --- | --- | --- |
| `BiRefNet-general` | `BiRefNet-general.safetensors` | 885 MB | <https://huggingface.co/1038lab/BiRefNet/resolve/main/BiRefNet-general.safetensors> |
| `BiRefNet-HR` | `BiRefNet-HR.safetensors` | 444 MB | <https://huggingface.co/1038lab/BiRefNet/resolve/main/BiRefNet-HR.safetensors> |
| `BiRefNet-portrait` | `BiRefNet-portrait.safetensors` | 885 MB | <https://huggingface.co/1038lab/BiRefNet/resolve/main/BiRefNet-portrait.safetensors> |
| `BiRefNet-matting` | `BiRefNet-matting.safetensors` | 885 MB | <https://huggingface.co/1038lab/BiRefNet/resolve/main/BiRefNet-matting.safetensors> |
| `BiRefNet-HR-matting` | `BiRefNet-HR-matting.safetensors` | 444 MB | <https://huggingface.co/1038lab/BiRefNet/resolve/main/BiRefNet-HR-matting.safetensors> |
| `BiRefNet_dynamic` | `BiRefNet_dynamic.safetensors` | 444 MB | <https://huggingface.co/1038lab/BiRefNet/resolve/main/BiRefNet_dynamic.safetensors> |
| `BiRefNet_toonout` | `BiRefNet_toonout.safetensors` | 885 MB | <https://huggingface.co/1038lab/BiRefNet/resolve/main/BiRefNet_toonout.safetensors> |
| `Lucida` | `Lucida.safetensors` | 885 MB | <https://huggingface.co/1038lab/BiRefNet/resolve/main/Lucida.safetensors> |
| `BiRefNet_512x512` | `BiRefNet_512x512.safetensors` | 444 MB | <https://huggingface.co/1038lab/BiRefNet/resolve/main/BiRefNet_512x512.safetensors> |
| `BiRefNet_lite` | `BiRefNet_lite.safetensors` | 178 MB | <https://huggingface.co/1038lab/BiRefNet/resolve/main/BiRefNet_lite.safetensors> |
| `BiRefNet_lite-2K` | `BiRefNet_lite-2K.safetensors` | 178 MB | <https://huggingface.co/1038lab/BiRefNet/resolve/main/BiRefNet_lite-2K.safetensors> |
| `BiRefNet_lite-matting` | `BiRefNet_lite-matting.safetensors` | 89 MB | <https://huggingface.co/1038lab/BiRefNet/resolve/main/BiRefNet_lite-matting.safetensors> |

这 12 个里有 10 个还接受 ZhengPeng7 官方命名（`General.safetensors`、`General-Lite.safetensors`、`General-HR.safetensors` 等，同一权重两种文件名），挂在模型库里的老文件可以直接用——映射关系在 `birefnet_node.py` 的 `ZHENG_PENG7_ALIAS`。`BiRefNet_toonout` 与 `Lucida` 是 1038lab 独有的微调，没有官方别名，只认上表文件名。

### 二、BiRefNet 家族：ZhengPeng7 数据集仓库（5 项）

1038lab 主仓库里**没有**这 5 个，必须去作者按数据集发布的独立仓库取：

放置位置：同样 `<ComfyUI>/models/background_removal/BiRefNet/`（旧 RMBG 目录仍可读）

| 模型名 | 本地文件名（不可改） | 大小 | 仓库地址 | 仓库内文件名 |
| --- | --- | --- | --- | --- |
| `BiRefNet-dis` | `DIS.safetensors` | 885 MB | <https://huggingface.co/ZhengPeng7/BiRefNet-DIS5K> | `model.safetensors` |
| `BiRefNet-dis-tr` | `DIS-TR_TEs.safetensors` | 885 MB | <https://huggingface.co/ZhengPeng7/BiRefNet-DIS5K-TR_TEs> | `model.safetensors` |
| `BiRefNet-cod` | `COD.safetensors` | 885 MB | <https://huggingface.co/ZhengPeng7/BiRefNet-COD> | `model.safetensors` |
| `BiRefNet-hrsod` | `HRSOD.safetensors` | 885 MB | <https://huggingface.co/ZhengPeng7/BiRefNet-HRSOD> | `model.safetensors` |
| `BiRefNet-legacy` | `General-legacy.safetensors` | 885 MB | <https://huggingface.co/ZhengPeng7/BiRefNet-legacy> | `model.safetensors` |

⚠️ **这 5 个仓库里的文件统一叫 `model.safetensors`**，直接手动下载的话记得改名成上表「本地文件名」那一列。节点自己下载时会自动改名，不用管。

直链格式（以 DIS 为例）：<https://huggingface.co/ZhengPeng7/BiRefNet-DIS5K/resolve/main/model.safetensors>

### 三、RMBG-2.0（1 项）

放置位置：`<ComfyUI>/models/background_removal/RMBG-2.0/`（旧 RMBG 目录仍可读）

| 模型名 | 本地文件名 | 大小 | 下载地址 |
| --- | --- | --- | --- |
| `RMBG-2.0` | `model.safetensors` | 885 MB | <https://huggingface.co/1038lab/RMBG-2.0/resolve/main/model.safetensors> |

官方仓库 `briaai/RMBG-2.0` 是 gated 仓库，不带 token 直接下会 401，所以走 1038lab 的公开镜像。镜像权重与 `BiRefNet-general` 的结构完全一致（safetensors 头里 754 个张量的 key / shape / dtype 逐项比对，零差异），因此复用同一份 `birefnet.py`，不需要第二套模型定义。

### 四、模型定义文件（3 个，自动下载）

放在 `<ComfyUI>/models/background_removal/BiRefNet/`，BiRefNet 家族共用，缺少时自动从主仓库补：

| 文件 | 大小 | 下载地址 |
| --- | --- | --- |
| `birefnet.py` | 92 KB | <https://huggingface.co/1038lab/BiRefNet/resolve/main/birefnet.py> |
| `birefnet_lite.py` | 94 KB | <https://huggingface.co/1038lab/BiRefNet/resolve/main/birefnet_lite.py> |
| `BiRefNet_config.py` | 298 B | <https://huggingface.co/1038lab/BiRefNet/resolve/main/BiRefNet_config.py> |

`birefnet.py` 首次加载时就地打两处补丁（相对导入改成绝对导入、window-attention 的 mask 加 fp16 dtype 转换），这是 ComfyUI-RMBG 同款修复，重复执行不变。

### 磁盘占用

只下常用的 `BiRefNet_lite` + `BiRefNet_lite-matting` 约 270 MB；18 个全下齐约 **12.0 GB**（其中 1038lab 主仓库 12 个 6.7 GB、ZhengPeng7 五个 4.4 GB、RMBG-2.0 0.9 GB）。

### 下载与手动放置

首次运行自动下载，带停滞看门狗：超过 60 秒没有任何字节增长就放弃并报错，不会像裸 `hf_hub_download` 那样在网络半死时无限挂起。

网络受限时先设环境变量再启动 ComfyUI：

```
HF_ENDPOINT=https://hf-mirror.com
```

手动放的三条规则：

1. **文件名必须和上表「本地文件名」完全一致**，大小写也要对（Linux 上尤其严格）。
2. 放在上表指定的目录；也可以挂载到别的盘，在 `extra_model_paths.yaml` 里配 `BiRefNet` 或 `RMBG` 类别，节点会搜「根目录 + 根目录/BiRefNet + 根目录/<模型子目录>」三层。
3. 除了权重，还要有模型定义：同目录下至少要有 `birefnet.py`（`BiRefNet_lite` 系列用 `birefnet_lite.py`）和 `BiRefNet_config.py`，缺了节点会自动从主仓库补。

文件放错或没找到时，节点报错信息里会直接给出「应该放的完整路径」和「该文件的下载直链」，照着放即可。

### 速度提醒

18 个模型都是通用前景分割模型，分辨率 512~2048 不等，**CPU 上很慢**。实测（本机 CPU，真人侧脸半身像 398×512）：

| 模型 | 单张耗时 |
| --- | --- |
| `BiRefNet_lite-matting` | ~84 s |
| `BiRefNet_lite` | ~118 s |
| `RMBG-2.0` | ~260 s |
| `BiRefNet-matting` | ~286 s |
| `BiRefNet-portrait` | ~298 s |

`BiRefNet-HR` / `BiRefNet-HR-matting` / `BiRefNet_lite-2K` 是 2048 输入，比上表还要慢数倍，没逐个计时。日常建议 `BiRefNet_lite-matting`（速度与质量的最佳折中）；要极致发丝用 `BiRefNet-matting`；贴纯色背景要硬边用 `BiRefNet_lite`。同一个模型重复运行时不会重新加载，第二次起省掉加载时间；切换模型会先卸载上一个，不会叠加占用。

## 目录结构

```
ComfyUI-QG-Multipack/
├── __init__.py                 节点注册、翻译服务商接口（/qg_translate/*）
├── birefnet_node.py            QG_BiRefNet
├── mask_by_name_node.py        QG_MaskByName（+ mask_by_name_helpers.py）
├── translate_core.py           翻译核心：服务商预设与多模型、config.json、HTTP、缓存
├── translate_node.py           QG_Translate（外壳，可单独删除）
├── prompt_translate_node.py    QG_PromptTranslate（+ 百度翻译通道）
├── image_to_prompt_node.py     QG_ImageToPrompt（图像反推，复用服务商配置）
├── prompt_optimize_node.py     QG_PromptOptimize（提示词优化，复用上面那套 HTTP/流式层）
├── prompt_rules.py             规则库：四组规则的内置默认 + rules.json 读写
├── qwen_text_encode_node.py    QG_QwenTextEncode + QG_QwenRestore（GPL 移植）
├── qwen_prompt_optimizer_node.py     QG_QwenPromptOptimizer（GPL 移植，llama-cpp 提示词优化）
├── qwen_prompt_optimizer_runtime.py  上面的运行时：模型加载/卸载 + 提示词组装（GPL 移植）
├── qwen_image_system_prompt_t2i.py / _i2i.py / _reverse.py  提示词优化的 system prompt 资产（GPL，原样复制）
├── face_rectify_node.py        QG_FaceRectify
├── qg_id_photo_prompt.py       QG_IDPhotoPrompt（13 维提示词，选项表是 JS/词表单一真源）
├── photo_sheet_mixed_node.py   QG_PhotoSheetMixed（13 版式数据表 + 统一排版引擎）
├── qg_image_composite.py       QG_ImageComposite（源图按坐标贴到目标画布，可选遮罩混合）
├── qg_id_photo_size_picker.py  QG_IDPhotoSizePicker（尺寸选择，preset 可连裁剪/参数节点的下拉）
├── qg_color_picker.py          QG_ColorPicker（点色块选色，按 HEX/RGB/HSL 输出颜色值与字符串）
├── qg_multi_photo_sheet.py     QG_MultiPhotoSheet（多人各占一格拼到同一张纸，统一格居中裁切）
├── qg_image_batch_builder.py   QG_ImageBatchBuilder（动态槽：默认 1 个接一个加一个，上限 24，成 IMAGE batch）
├── qg_remove_background_v2.py  QG_RemoveBackgroundV2（BiRefNet 粗分割 + ViTMatte/PyMatting/GuidedFilter 细节精修）
├── web/                        前端脚本（逐个说明见「前端增强」一章）
├── workflows/                  两份可直接加载的证件照示例工作流 json
├── models/id_photo/            内置证件照服装/发型素材（7 分类 200 张 + 提示词 JSON）
├── models/marriage_cloth/      内置结婚登记照服装素材（81 张）
├── assets/fonts/               随包开放许可字体：Noto Sans SC (OFL 1.1) + OFL.txt
├── locales/zh/nodeDefs.json    中文界面文案与 tooltip（ComfyUI 官方前端 i18n 标准）
├── translations/zh-CN/         交给汉化插件的词表（Nodes/Menus，见「汉化词表」一节）
├── tests/                      纯函数单测（python -m pytest tests）
├── shape_predictor_5_face_landmarks.dat  人脸 5 点模型
├── config.example.json         config.json（在 ComfyUI/user/ComfyUI-QG-Multipack/）的空字段模板
├── .gitignore                  排除 config.json / rules.json / 运行产物 / 商业字体 fonts/
├── rules.json                  规则库（运行时生成于 user 目录；插件目录可能残留旧副本）
└── THIRD-PARTY-NOTICES.md      第三方代码与模型许可
```

## 汉化词表（两套标准，各自独立）

本包的中文文案有两套词表，对应两个不同生态，**不要合并、也不要互相套用字段**：

| 文件 | 标准 | 谁在读 | 字段口径 |
|---|---|---|---|
| `locales/zh/nodeDefs.json` | ComfyUI 官方前端 i18n | ComfyUI 前端自动加载 | 节点 key → `display_name` / `description` / `inputs`({name,tooltip}) / `outputs`（**输出索引字符串** "0"/"1"…） |
| `translations/zh-CN/Nodes/`、`Menus/ComfyUI-QG-Multipack.json` | ComfyUI-Global-Translation（原 AIGODLIKE 系） | 汉化插件按需加载 | 节点 key → `title` / `description` / `inputs` / `widgets` / `outputs`（**槽名/控件参数名**）；Menus 是全局下拉值映射 |

- **交付方式**：把 `translations/zh-CN/Nodes/` 与 `Menus/` 下这两个 JSON 拷进汉化插件的 `zh-CN/Nodes`、`zh-CN/Menus` 即可，插件会自动识别。本包有 33 个节点、Menus 286 条（证件照 13 维下拉的英文编号值→中文显示映射都在里面）。
- **规范约定**：`widgets` 键用源码里的真实参数名，不用界面显示名；**不写恒等翻译**（键==值的条目无意义，还会污染插件的「已翻译文本」判定）；`ui` 字段用于翻译节点内嵌 DOM 面板的英文原文——本包面板文案本身就是中文，暂不需要 `ui` 词条。分类也不用 `Categories` 词表（本包 category 已是「QG 工具」）。
- 新增/改名节点、增删控件或输出槽时，两套词表都要同步；`tests/test_i18n_standard.py` 会校验节点数、需汉化项覆盖、无恒等翻译、description 齐全。

## 已知限制

- **「Nodes 2.0（Vue 节点）」下计时器与流式气泡已单独适配**。ComfyUI 新版前端把节点正文交给 Vue 渲染，LiteGraph 的 `drawNode` 提前返回，`onDrawBackground` / `onDrawForeground` 都不再被调用，所以在节点上直接画的内容会整片消失。本包的做法是在主画布之上叠一张透明 `canvas`（`position:absolute; pointer-events:none`），每帧按画布的平移/缩放换算坐标，只重画计时器面板和流式气泡；正常模式下不会创建这张画布，仍走原来的 `onDrawBackground`，因此不会重复绘制。实测（前端 1.57.4）读数、气泡、缩放 60% / 160% 下的位置与大小都正常。
  （中途试过包 `drawFrontCanvas` 往主画布补画：像素采样证明内容确实画出来了，但 Vue 模式把节点画在另一张 overlay canvas 上、压在主画布之上，补画被完全盖住，所以最终改成独立图层。）
- **右侧「节点参数」面板里颜色还是原生输入框**。节点画布上的颜色字段已经图形化，但右侧面板由前端 Vue 渲染，ComfyUI 前端（1.5x）没有开放 widget 渲染器的扩展点，扩展侧改不了。
- **`QG_BiRefNet` 首次加载会给模型定义打两处补丁，但只改副本**。`birefnet.py` 是随权重下载的实现，其中 `from .BiRefNet_config import` 的相对导入、以及 window-attention 里 `mask` 与 `attn` 的 dtype 不一致，在本机都会直接报错。节点把打过补丁的版本写进 `models/background_removal/_qg_patched/`（原文件只读），源文件按 `mtime + 大小` 认版本，上游更新后会自动生成新副本。原文件本来就修好过（patch 前后一致）时直接用原文件，不做任何拷贝；万一连一个可写目录都没有，才退回「就地修」，并在写不进去时给出一条说清两种解决方法的报错。
- **计时器靠事件判定起停**：`execution_start` 起表，`execution_success` / `execution_error` / `execution_interrupted` 收表，执行中其它节点的 `executing` 事件不参与判定——否则一有节点开始执行就会误停。
- **改名后旧名会一直留着**：`rules.json` 里每条规则有稳定 `id`，改名时后端自动把旧名记进 `aliases`（最多 8 个），老工作流照常命中，下拉里只显示当前名字。要彻底清掉旧名，删掉这条规则重新建一条即可。
- **图像反推必须联网、且要有能看图的模型**：本地 Ollama 也要先拉一个视觉模型（如 `qwen2.5vl:7b`）。免费模型（`glm-4.6v-flash`）高峰期会返回 429「访问量过大」，换个模型或等一会儿即可；节点会把接口原文一并报出来。

## 许可

本包代码为 GPL-3.0（见 `LICENSE`）。

第三方代码与模型权重的来源、许可、以及「哪些内容不随包分发」都记在 `THIRD-PARTY-NOTICES.md`，使用前请一并阅读——尤其是 `RMBG-2.0`（BRIA 自定义协议，商用需授权）。
