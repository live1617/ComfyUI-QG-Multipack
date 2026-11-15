# 随包抠图模型权重说明

本目录的两个 `.onnx` 文件随 ComfyUI-QG-Multipack 一起分发，目的是让
`QG_PortraitMatte` 在**完全离线**的机器上开箱即用。文件均为官方 release
原样字节复制，**未修改**、未重新导出。

## 授权

两个模型的上游均按 **Apache License 2.0** 发布：

- `Zeyi-Lin/HivisionIDPhotos` 仓库 README 的 License 章节原文：
  `This repository is licensed under the Apache-2.0 License.`
  （<https://github.com/Zeyi-Lin/HivisionIDPhotos>）
- `ZHKKKe/MODNet`（`modnet_photographic_portrait_matting.onnx` 的原始出处）
  仓库 LICENSE 为 Apache License 2.0 全文：
  <https://github.com/ZHKKKe/MODNet>
- 上游 README 的模型清单中，这两个权重只描述用途与体积，
  **没有附加模型专属的商用 / 非商业限制条款**；若上游日后单独声明了更严格的
  模型授权，以上游声明为准。

Apache-2.0 许可全文见同目录 `LICENSE-APACHE-2.0.txt`（再分发必须附带）。
本包整体为 GPL-3.0；这些权重是独立的数据资产，不与本包代码链接构成衍生
作品，其授权与署名按本节单独保留，详见仓库根目录
`THIRD-PARTY-NOTICES.md`。

> 注意：`rmbg-1.4.onnx`（BRIA AI）与 `birefnet-v1-lite.onnx`（ZhengPeng7）
> **不随包分发**，仍由节点首次使用时按需下载；两者的上游授权与此处不同，
> 使用前请自行核对各自仓库的条款。

## 文件清单

| 文件 | 大小 | SHA-256 | 来源 |
| --- | --- | --- | --- |
| `modnet_photographic_portrait_matting.onnx` | 25.9 MB | `07c308cf0fc7e6e8b2065a12ed7fc07e1de8febb7dc7839d7b7f15dd66584df9` | MODNet 官方权重，经 HivisionIDPhotos 官方 release 分发 |
| `hivision_modnet.onnx` | 25.9 MB | `7e0cb9a2a841b426dd0daf1a788ec398dab059bc039041d62b15636c0783bc56` | HivisionIDPhotos 项目方训练、经其官方 release 分发 |

下载源（两个文件同一 release）：

```
https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/pretrained-model/modnet_photographic_portrait_matting.onnx
https://github.com/Zeyi-Lin/HivisionIDPhotos/releases/download/pretrained-model/hivision_modnet.onnx
```

## 优先级

模型发现顺序见 `_matte_models.py` 的 `_source_folders()`：
`ComfyUI/models/background_removal` → `ComfyUI/models/matting` →
**本目录（插件内置，离线兜底）** → 兼容读取 HivisionIDPhotos 插件自带 weights。
用户自己放置的同名权重优先于内置副本；内置副本命中后不会再触发网络下载。
