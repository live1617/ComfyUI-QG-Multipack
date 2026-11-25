# 开发相关说明

> 本文档从 README 抽出独立维护（2026-11-25 起，开发向内容不再写进 README，
> README 只留入口引用）。另有本机开发纪律文档 `开发规范.md`（不进 git，
> 仅本地）。

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
├── qg_id_photo_size_picker.py  QG_IDPhotoSizePicker（尺寸选择，preset 可连裁剪/参数节点的下拉）
├── qg_multi_photo_sheet.py     QG_MultiPhotoSheet（多人各占一格拼到同一张纸，统一格居中裁切）
├── qg_remove_background_v2.py  QG_RemoveBackgroundV2（BiRefNet 粗分割 + ViTMatte/PyMatting/GuidedFilter 细节精修）
├── web/                        前端脚本（逐个说明见 README「前端增强」一章）
├── workflows/                  两份可直接加载的证件照示例工作流 json
├── models/id_photo/            内置证件照服装/发型素材（7 分类 200 张 + 提示词 JSON）
├── models/marriage_cloth/      内置结婚登记照服装素材（81 张）
├── assets/fonts/               随包开放许可字体：Noto Sans SC (OFL 1.1) + OFL.txt
├── locales/zh/nodeDefs.json    中文界面文案与 tooltip（ComfyUI 官方前端 i18n 标准）
├── translations/zh-CN/         交给汉化插件的词表（Nodes/Menus，见下方「汉化词表」）
├── tests/                      纯函数单测（python -m pytest tests）
├── shape_predictor_5_face_landmarks.dat  人脸 5 点模型
├── config.example.json         config.json（在 ComfyUI/user/ComfyUI-QG-Multipack/）的空字段模板
├── .gitignore                  排除 config.json / rules.json / 运行产物 / 商业字体 fonts/
├── rules.json                  规则库（运行时生成于 user 目录；插件目录可能残留旧副本）
├── SOURCE-NOTES.md             来源与搬运说明（哪些是原创、哪些是搬运）
└── THIRD-PARTY-NOTICES.md      第三方代码与模型许可
```

## 汉化词表（两套标准，各自独立）

本包的中文文案有两套词表，对应两个不同生态，**不要合并、也不要互相套用字段**：

| 文件 | 标准 | 谁在读 | 字段口径 |
|---|---|---|---|
| `locales/zh/nodeDefs.json` | ComfyUI 官方前端 i18n | ComfyUI 前端自动加载 | 节点 key → `display_name` / `description` / `inputs`({name,tooltip}) / `outputs`（**输出索引字符串** "0"/"1"…） |
| `translations/zh-CN/Nodes/`、`Menus/ComfyUI-QG-Multipack.json` | ComfyUI-Global-Translation（原 AIGODLIKE 系） | 汉化插件按需加载 | 节点 key → `title` / `description` / `inputs` / `widgets` / `outputs`（**槽名/控件参数名**）；Menus 是全局下拉值映射 |

- **交付方式**：把 `translations/zh-CN/Nodes/` 与 `Menus/` 下这两个 JSON 拷进汉化插件的 `zh-CN/Nodes`、`zh-CN/Menus` 即可，插件会自动识别。本包有 30 个节点、Menus 286 条（证件照 13 维下拉的英文编号值→中文显示映射都在里面）。
- **规范约定**：`widgets` 键用源码里的真实参数名，不用界面显示名；**不写恒等翻译**（键==值的条目无意义，还会污染插件的「已翻译文本」判定）；`ui` 字段用于翻译节点内嵌 DOM 面板的英文原文——本包面板文案本身就是中文，暂不需要 `ui` 词条。分类也不用 `Categories` 词表（本包 category 已是「QG 工具」）。
- 新增/改名节点、增删控件或输出槽时，两套词表都要同步；`tests/test_i18n_standard.py` 会校验节点数、需汉化项覆盖、无恒等翻译、description 齐全。
