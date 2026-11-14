# -*- coding: utf-8 -*-
"""prompt_rules.py 的单元测试。

不碰真的 rules.json：把模块的 RULES_DIR 指到临时目录再测。
运行：python_embeded\\python.exe tests\\test_rules.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

import prompt_rules as m  # noqa: E402

TMP = tempfile.mkdtemp(prefix="qg-rules-")
m.RULES_DIR = TMP
m.RULES_FILENAME = "rules.json"

FAILED = 0


def check(label, ok, detail=""):
    global FAILED
    if not ok:
        FAILED += 1
    print(f"  {label:<46}{'PASS' if ok else 'FAIL'}  {detail if not ok else ''}")


def reset():
    path = m.rules_path()
    if os.path.exists(path):
        os.remove(path)


print("=== A. 默认结构 ===")
d = m.default_rules()
check("四组齐全", list(d) == ["optimize", "image", "video", "translate"], list(d))
check("图像反推 4 条", len(d["image"]) == 4, len(d["image"]))
check("视频反推 1 条", len(d["video"]) == 1, len(d["video"]))
check("翻译规则 1 条", len(d["translate"]) == 1, len(d["translate"]))
check("优化组 4 条", len(d["optimize"]) == 4, len(d["optimize"]))
check("优化组首条是扩写-通用", d["optimize"][0]["name"] == "扩写-通用",
      d["optimize"][0]["name"])
for key in ("optimize", "image", "video", "translate"):
    lit = [i for i in d[key] if i["enabled"]]
    check(f"{key} 恰好一条激活", len(lit) == 1, len(lit))
check("激活的是第一条", d["image"][0]["enabled"] and not d["image"][1]["enabled"])

print("=== B. 读写 ===")
reset()
loaded = m.load_rules()
check("没文件用默认", [i["name"] for i in loaded["image"]] == [i["name"] for i in d["image"]])
check("没文件时不写盘", not os.path.exists(m.rules_path()))

saved = m.save_rules(d)
check("保存成功", os.path.exists(m.rules_path()))
with open(m.rules_path(), encoding="utf-8") as fh:
    raw = json.load(fh)
check("文件结构正确", raw.get("version") == m.RULES_VERSION and "groups" in raw,
      [raw.get("version"), list(raw)])
check("读回一致", m.load_rules()["video"][0]["name"] == "视频动态提示词")

# 只写一组：其它组要补默认
m.save_rules({"groups": {"image": [{"name": "只有这一条", "content": "x", "enabled": True}]}})
after = m.load_rules()
check("缺组补默认", len(after["video"]) == 1 and after["video"][0]["name"] == "视频动态提示词")
check("写的组被保留", [i["name"] for i in after["image"]] == ["只有这一条"])

# 空组要保住，不能回落成默认
m.save_rules({"groups": {**m.default_rules(), "image": []}})
check("空组不回落", m.load_rules()["image"] == [])

# 文件写坏
with open(m.rules_path(), "w", encoding="utf-8") as fh:
    fh.write("{ 这不是 json")
check("坏文件用默认", len(m.load_rules()["image"]) == 4)

print("=== C. 规范化 ===")
weird = {
    "groups": {
        "image": [
            {"name": "同名", "content": "a", "enabled": True},
            {"name": "同名", "content": "b", "enabled": True},
            {"name": "  ", "content": "空名字"},
            {"name": "超长" * 40, "content": "x"},
        ],
        "video": [{"name": "全灭", "content": "y", "enabled": False}],
    }
}
m.save_rules(weird)
got = m.load_rules()
check("组内重名只留一条", [i["name"] for i in got["image"]].count("同名") == 1)
check("空名字被丢掉", all(i["name"].strip() for i in got["image"]))
check("名字截断到 60", all(len(i["name"]) <= 60 for i in got["image"]))
check("全灭自动点亮第一条", got["video"][0]["enabled"] is True)

many = {"groups": {**m.default_rules(),
                   "image": [{"name": "A", "content": "", "enabled": True},
                             {"name": "B", "content": "", "enabled": True}]}}
m.save_rules(many)
check("多条激活只留第一条",
      [i["enabled"] for i in m.load_rules()["image"]] == [True, False])

print("=== D. 查询与回退 ===")
reset()
names = m.node_rule_names()
check("节点下拉 9 条", len(names) == 9, names)
check("含优化规则", "扩写-通用" in names)
check("含视频规则", "视频动态提示词" in names)
check("不含翻译规则", "提示词翻译（默认）" not in names)
optimize_only = m.node_rule_choices(("optimize",))
check("优化节点只列优化组",
      [n for n in optimize_only] == [i["name"] for i in m.load_rules()["optimize"]],
      optimize_only)
check("优化节点下拉不含反推规则", "像素级描述" not in optimize_only)

hit, fell = m.resolve("Tag 标签流", ("image", "video"))
check("按名字命中", hit["name"] == "Tag 标签流" and fell is False)

hit, fell = m.resolve("早就删掉的规则", ("image", "video"))
check("找不到会回退", hit is not None and fell is True, hit and hit["name"])
check("回退到激活规则", hit["name"] == "像素级描述", hit and hit["name"])

check("翻译规则有正文", len(m.translate_rule_text()) > 20)
m.save_rules({**m.default_rules(), "optimize": [], "translate": []})
check("空组 active 返回 None", m.active("optimize") is None)
check("翻译规则空时返回空串", m.translate_rule_text() == "")

# 老文件补种：v3 之前没有优化节点，优化组永远是空的（用户存过多少次都空），
# 不能把这种空当成「他想要空的」。读盘时补一次，保存后版本升到 3，
# 此后用户再删空就是明确意图。
reset()
m.save_rules({**m.default_rules(), "optimize": []})
with open(m.rules_path(), encoding="utf-8") as fh:
    legacy = json.load(fh)
legacy["version"] = 2
with open(m.rules_path(), "w", encoding="utf-8") as fh:
    json.dump(legacy, fh, ensure_ascii=False)
seeded = m.load_rules()
check("v2 老文件补出优化规则", len(seeded["optimize"]) == 4, len(seeded["optimize"]))
check("v2 补种后激活第一条", seeded["optimize"][0]["enabled"] is True)
check("补种不写盘", json.load(open(m.rules_path(), encoding="utf-8"))["version"] == 2)
m.save_rules(seeded)
m.save_rules({**m.default_rules(), "optimize": []})
check("升到 v3 后删空不再补", m.load_rules()["optimize"] == [])

print("=== E. id 与旧名别名 ===")
reset()
first = m.load_rules()
all_items = [i for g in first.values() for i in g]
ids = [i["id"] for i in all_items]
check("每条都有 id", all(ids), ids)
check("id 全局唯一", len(ids) == len(set(ids)), ids)
check("id 可重复计算", [i["id"] for i in m.load_rules()["image"]]
      == [i["id"] for i in first["image"]])

m.save_rules(first)
changed = m.load_rules()
target = next(i for i in changed["image"] if i["name"] == "Tag 标签流")
target["content"] = "改名后的正文"
target["name"] = "标签流（新名）"
m.save_rules(changed)

after = m.load_rules()
hit_item = m.find("Tag 标签流")
check("旧名仍能命中", hit_item is not None and hit_item["name"] == "标签流（新名）",
      hit_item and hit_item["name"])
check("命中拿到改后的正文", (hit_item or {}).get("content") == "改名后的正文")
check("旧名进了 aliases", "Tag 标签流" in (hit_item or {}).get("aliases", []),
      (hit_item or {}).get("aliases"))
hit, fell = m.resolve("Tag 标签流", ("optimize", "image", "video"))
check("别名命中不算回退", hit is not None and fell is False, fell)
hit_id, _ = m.resolve((hit_item or {}).get("id", ""), ("image",))
check("按 id 也能命中", hit_id is not None and hit_id["name"] == "标签流（新名）",
      hit_id and hit_id["name"])

# 校验列表必须带上旧名：ComfyUI 提交时按 INPUT_TYPES 的列表校验，少了旧名
# 老工作流会被 "Value not in list" 直接拒收，根本走不到执行里的别名匹配。
choices = m.node_rule_choices()
check("校验列表含新名", "标签流（新名）" in choices, choices[:3])
check("校验列表含旧名", "Tag 标签流" in choices, choices[-2:])
check("下拉用的纯名字不含旧名", "Tag 标签流" not in m.node_rule_names(),
      m.node_rule_names())

# 别名不能盖过真实名字
conflict = m.load_rules()
conflict["image"].append({
    "id": "conflict-rule", "name": "Tag 标签流", "content": "后加的", "enabled": False,
})
m.save_rules(conflict)
named = m.find("Tag 标签流")
check("名字优先于别名", named is not None and named["content"] == "后加的",
      named and named["name"])
old_item = next((i for i in m.load_rules()["image"] if i["name"] == "标签流（新名）"), None)
check("别名与现有名字撞车时被清掉",
      old_item is not None and "Tag 标签流" not in old_item["aliases"],
      old_item and old_item["aliases"])

check("别名不和自身同名", m._clean_aliases(["X", "X", ""], "X") == [])
check("别名去重且保序", m._clean_aliases(["a", "a", "b"], "c") == ["a", "b"])
check("别名数量有上限", len(m._clean_aliases(["a%d" % i for i in range(20)], "x"))
      == m.MAX_ALIASES)

print("=== F. 摘要 ===")
reset()
s = m.summary()
check("摘要带顺序", s["order"] == ["optimize", "image", "video", "translate"])
check("摘要带激活项", s["groups"]["image"]["active"] == "像素级描述")
check("摘要不含正文", "content" not in json.dumps(s))

print("=== G. 内置规则改名的兼容 ===")
reset()
hit, fell = m.resolve("像素级描述（by:阿丹）")
check("旧名仍能命中", hit is not None and hit["name"] == "像素级描述" and fell is False,
      hit and hit["name"])
check("旧名能过 ComfyUI 校验列表", "像素级描述（by:阿丹）" in m.node_rule_choices())
check("节点下拉不显示旧名", "像素级描述（by:阿丹）" not in m.node_rule_names())
check("新名在下拉里", "像素级描述" in m.node_rule_names())
check("旧名不再带第三方署名", all("阿丹" not in n for n in m.node_rule_names()))

print("=== H. 真实目录不被污染 ===")
check("测试没写插件目录",
      not os.path.exists(os.path.join(PKG, "rules.json")))

shutil.rmtree(TMP, ignore_errors=True)
print("\n---")
print(f"失败 {FAILED} 项")
if FAILED:
    sys.exit(1)
print("全部通过")
