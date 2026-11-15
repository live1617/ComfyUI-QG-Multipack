# -*- coding: utf-8 -*-
"""示例工作流回归测试：结构自洽 + 控件值合法 + 说明不过时。

三份 ``workflows/*.json`` 是给用户直接拖进画布的 UI 格式，不经过 Python
导入，所以后端节点改控件、字体换名、模型授权变化时，其它测试全都发现不了。
v2.14.0 把两个 modnet 权重改成随包之后，``id_photo_pipeline.json`` 的便签
还写着「首次使用 ③ 会自动下载抠图 / 人脸模型，需联网」—— 就是缺这层校验
导致的。这里把工作流当成契约来守：

* JSON 顶层字段、id 唯一、last_node_id / last_link_id 与最大值一致；
* 每条 link 两端槽位存在、类型一致、源 outputs.links 与目标 inputs.link
  双向登记齐全（断链拖进画布会变空输入）；
* widgets_values 数量与真机 ``/object_info`` 的控件数一致；
* 下拉值合法，尤其随包模型名与随包字体名，示例不得引用专有商业字体；
* 所有 QG_ 节点都在 ``locales/zh/nodeDefs.json`` 的注册 key 里；
* 每份都有中文「使用说明」便签，且不得残留过时的「需联网下载抠图」表述；
* README 与打包脚本 REQUIRED 覆盖全部工作流文件。

WIDGET_COUNT 是 8177 真机 ``/object_info`` 的快照（2026-11-15，v2.14.0）。
节点增删控件时必须同步它 —— 测试报错就是提醒回来核对工作流里的
widgets_values 顺序，这正是它存在的意义。不依赖 ComfyUI 实例、不依赖
GPL 参考源码，可单独运行。
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
PKG = HERE.parent
WORKSPACE = PKG.parent
WF_DIR = PKG / "workflows"

EXPECTED_FILES = (
    "id_photo_pipeline.json",
    "id_photo_templates.json",
    "id_photo_offline.json",
)

# 真机 /object_info 快照：节点类型 -> widgets_values 元素个数。
# 连线输入（IMAGE / MASK / QG_IDPHOTO_PARAMS）不占 widget 位置。
WIDGET_COUNT = {
    "LoadImage": 1,
    "PreviewImage": 0,
    "PreviewAny": 1,
    "MaskToImage": 0,
    "MarkdownNote": 1,
    "QG_IDPhotoParams": 8,
    "QG_PortraitMatte": 11,
    "QG_IDPhotoCrop": 12,
    "QG_PhotoSheet": 13,
    "QG_PhotoSheetMixed": 8,
    "QG_IDPhotoPrompt": 14,
    "QG_IDPhotoOutfit": 2,
    "QG_MarriageCloth": 5,
    "QG_Watermark": 7,
    "QG_MaskTopExpand": 5,
}

# PreviewAny 的 source 输入被连线占用时，前端会把 widget 隐藏，
# widgets_values 为空；没接连线时才有一个占位值。两种都合法。
FLEXIBLE_WIDGETS = {"PreviewAny"}

BUNDLED_MODELS = {
    "hivision_modnet",
    "modnet_photographic_portrait_matting",
}
DOWNLOAD_ONLY_MODELS = {"rmbg-1.4", "birefnet-v1-lite"}
ALL_MATTING_MODELS = BUNDLED_MODELS | DOWNLOAD_ONLY_MODELS
BUNDLED_FONT = "NotoSansSC-VF.ttf"
SAFE_FONTS = {"<default>", BUNDLED_FONT}
LAYOUT_CENTER_MODES = {"top_center", "bbox_center", "mask_center"}

# 曾经写错的说明，出现任何一句都算回归。
STALE_PHRASES = (
    "首次使用 ③ 会自动下载抠图",
    "首次使用 ③ 会自动下载抠图 / 人脸模型",
    "无模型时节点会降级或给出明确提示",
)

ok = 0
fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS", name)
    else:
        fail += 1
        print("FAIL", name, "-", detail)


def load(name):
    path = WF_DIR / name
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def notes(data):
    return [str(w) for n in data["nodes"] if n.get("type") == "MarkdownNote"
            for w in (n.get("widgets_values") or [])]


def main():
    print("=== 文件与顶层结构 ===")
    for name in EXPECTED_FILES:
        p = WF_DIR / name
        check(f"{name} 存在", p.is_file(), str(p))
        if not p.is_file():
            continue
        try:
            d = load(name)
        except Exception as exc:
            check(f"{name} 是合法 JSON", False, str(exc)[:120])
            continue
        check(f"{name} 是合法 JSON", True)
        need = {"id", "revision", "last_node_id", "last_link_id", "nodes",
                "links", "groups", "config", "extra", "version"}
        check(f"{name} 顶层字段齐全", need <= set(d),
              f"缺 {sorted(need - set(d))}")
        check(f"{name} id 与文件名一致", d.get("id") == p.stem,
              f"{d.get('id')} != {p.stem}")
        check(f"{name} version 为 0.4（ComfyUI UI 格式）",
              d.get("version") == 0.4, str(d.get("version")))

    print("\n=== 节点 / 连线自洽 ===")
    node_keys = set()
    ndefs = PKG / "locales" / "zh" / "nodeDefs.json"
    if ndefs.is_file():
        with open(ndefs, "r", encoding="utf-8") as fh:
            node_keys = set(json.load(fh))
        check("nodeDefs.json 可读且有 QG_ 注册 key",
              any(k.startswith("QG_") for k in node_keys), f"共 {len(node_keys)} 个")

    for name in EXPECTED_FILES:
        if not (WF_DIR / name).is_file():
            continue
        d = load(name)
        nodes = {n["id"]: n for n in d["nodes"]}
        links = d.get("links", [])
        check(f"{name} 节点 id 唯一", len(nodes) == len(d["nodes"]))
        check(f"{name} last_node_id 与最大值一致",
              d["last_node_id"] == max(nodes), str(d["last_node_id"]))
        max_link = max([l[0] for l in links] or [0])
        check(f"{name} last_link_id 与最大值一致",
              d["last_link_id"] == max_link, str(d["last_link_id"]))
        check(f"{name} link id 唯一",
              len({l[0] for l in links}) == len(links))

        for n in d["nodes"]:
            t = n.get("type")
            check(f"{name} #{n['id']} 有完整字段",
                  all(k in n for k in ("type", "pos", "size", "flags",
                                      "order", "mode", "inputs", "outputs",
                                      "properties")))
            if t == "MarkdownNote":
                continue
            expect = WIDGET_COUNT.get(t)
            if expect is None:
                check(f"{name} #{n['id']} {t} 在 WIDGET_COUNT 契约里", False,
                      "新增节点类型需同步契约表")
                continue
            got = len(n.get("widgets_values") or [])
            if t in FLEXIBLE_WIDGETS:
                check(f"{name} #{n['id']} {t} 控件数允许 0 或 1", got in (0, 1),
                      f"实际 {got}")
            else:
                check(f"{name} #{n['id']} {t} 控件数 {expect}", got == expect,
                      f"实际 {got}；节点改控件后需同步 WIDGET_COUNT 与工作流")
            if t.startswith("QG_") and node_keys:
                check(f"{name} #{n['id']} {t} 已注册", t in node_keys)

        for l in links:
            lid, src, sslot, dst, dslot, ltype = l
            good = src in nodes and dst in nodes
            if good:
                s, t = nodes[src], nodes[dst]
                good = sslot < len(s.get("outputs", [])) and dslot < len(t.get("inputs", []))
                if good:
                    st = s["outputs"][sslot].get("type")
                    dt = t["inputs"][dslot].get("type")
                    good = ltype in (st, dt, "*")
                    good = good and lid in s["outputs"][sslot].get("links", [])
                    good = good and t["inputs"][dslot].get("link") == lid
            check(f"{name} link{lid} 两端登记且类型一致", good, str(l))

        for n in d["nodes"]:
            if n.get("type") in ("PreviewImage", "PreviewAny"):
                has = any(i.get("link") is not None for i in n.get("inputs", []))
                check(f"{name} #{n['id']} 预览节点有输入连线", has)

    print("\n=== 控件值：随包模型 / 随包字体 / 下拉合法 ===")
    for name in EXPECTED_FILES:
        if not (WF_DIR / name).is_file():
            continue
        d = load(name)
        for n in d["nodes"]:
            t = n.get("type")
            wv = n.get("widgets_values") or []
            if t == "QG_PortraitMatte":
                check(f"{name} 抠图模型值合法",
                      bool(wv) and wv[0] in ALL_MATTING_MODELS, str(wv[:1]))
            if t in ("QG_PhotoSheet", "QG_PhotoSheetMixed", "QG_Watermark"):
                idx = {"QG_PhotoSheet": 9, "QG_PhotoSheetMixed": 5,
                       "QG_Watermark": 1}[t]
                val = wv[idx] if len(wv) > idx else None
                check(f"{name} {t} 字体只用随包 OFL 或 <default>",
                      val in SAFE_FONTS, str(val))
            if t == "QG_MaskTopExpand":
                check(f"{name} 头顶扩展 center_mode 合法",
                      len(wv) > 2 and wv[2] in LAYOUT_CENTER_MODES, str(wv[:3]))
            if t == "QG_IDPhotoPrompt":
                check(f"{name} 提示词 seed 为整数",
                      len(wv) == 14 and isinstance(wv[-1], int), str(wv[-1:]))

    offline = WF_DIR / "id_photo_offline.json"
    if offline.is_file():
        d = load("id_photo_offline.json")
        matte = [n for n in d["nodes"] if n.get("type") == "QG_PortraitMatte"]
        wm = [n for n in d["nodes"] if n.get("type") == "QG_Watermark"]
        check("离线工作流用随包抠图模型",
              bool(matte) and matte[0]["widgets_values"][0] in BUNDLED_MODELS,
              str(matte[0]["widgets_values"][:1]) if matte else "无该节点")
        check("离线工作流不引用按需下载的大模型",
              all(n["widgets_values"][0] not in DOWNLOAD_ONLY_MODELS
                  for n in matte))
        check("离线工作流中文水印用随包字体",
              bool(wm) and wm[0]["widgets_values"][1] == BUNDLED_FONT)
        check("离线工作流覆盖 QG_MaskTopExpand",
              any(n.get("type") == "QG_MaskTopExpand" for n in d["nodes"]))
        check("离线工作流覆盖 QG_Watermark", bool(wm))
        check("随包字体文件确实存在",
              (PKG / "assets" / "fonts" / BUNDLED_FONT).is_file())

    print("\n=== 使用说明便签不过时 ===")
    for name in EXPECTED_FILES:
        if not (WF_DIR / name).is_file():
            continue
        d = load(name)
        ns = notes(d)
        check(f"{name} 有中文说明便签", bool(ns) and len(ns[0]) > 100,
              f"{len(ns[0]) if ns else 0} 字")
        text = "\n".join(ns)
        check(f"{name} 便签无过时的「需联网下载抠图」表述",
              not any(p in text for p in STALE_PHRASES))
        check(f"{name} 便签含步骤说明", "①" in text or "步骤" in text)
    pipeline = WF_DIR / "id_photo_pipeline.json"
    if pipeline.is_file():
        text = "\n".join(notes(load("id_photo_pipeline.json")))
        check("全链路便签写明两个 modnet 已随包",
              "已随包" in text and "Apache-2.0" in text)
    if offline.is_file():
        text = "\n".join(notes(load("id_photo_offline.json")))
        check("离线便签写明 Apache-2.0 与 SIL OFL",
              "Apache-2.0" in text and "SIL OFL" in text)
        check("离线便签写明如何完全离线（关 face_alignment）",
              "face_alignment" in text and "完全离线" in text)
        check("离线便签提示占位图需替换", "example.png" in text or "占位" in text)

    print("\n=== 文档与打包清单同步 ===")
    readme = PKG / "README.md"
    if readme.is_file():
        rtext = readme.read_text(encoding="utf-8", errors="ignore")
        for name in EXPECTED_FILES:
            check(f"README 列出 {name}", name in rtext)
        check("README 工作流表格行数与文件数一致",
              len(re.findall(r"`(id_photo_[a-z]+\.json)`", rtext)) >= len(EXPECTED_FILES))
    packer = WORKSPACE / "打包备份.py"
    if packer.is_file():
        ptext = packer.read_text(encoding="utf-8", errors="ignore")
        for name in EXPECTED_FILES:
            check(f"打包 REQUIRED 必带 {name}",
                  f"workflows/{name}" in ptext)
        check("打包脚本有 models 资产白名单",
              "MODELS_ASSET_DIRS" in ptext)
        for d in ("background_removal", "id_photo", "marriage_cloth"):
            check(f"models 白名单含 {d}", f'"{d}"' in ptext)
        check("打包脚本按白名单过滤历史素材目录",
              "rel.parts[1] not in MODELS_ASSET_DIRS" in ptext)
        check("make_zip 断言历史素材不得混进包",
              "n.split(\"/\")[2] not in MODELS_ASSET_DIRS" in ptext)
    else:
        print("SKIP 运行真源目录下没有打包脚本，跳过 REQUIRED 断言（不算失败）")

    print("\n=== 工作区不含早期「精选 62 张」历史素材目录 ===")
    mdir = PKG / "models"
    legacy = [p.name for p in mdir.iterdir() if p.is_dir()
              and p.name[:1].isdigit()] if mdir.is_dir() else []
    check("工作区 models/ 无历史编号目录", not legacy, str(legacy[:5]))
    for d in ("id_photo", "marriage_cloth", "background_removal"):
        check(f"随包资产目录 {d} 存在", (mdir / d).is_dir())

    print(f"\n合计 {ok + fail} 项，PASS {ok}，FAIL {fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
