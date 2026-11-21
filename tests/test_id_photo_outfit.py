# -*- coding: utf-8 -*-
"""QG_IDPhotoOutfit 节点级测试：扫描/解析 / 路径安全 / 契约 / i18n / README 登记。

素材全部自备：测试用 tmp 目录构造假素材，不依赖真实 models/id_photo。
运行：python_embeded\\python.exe tests\\test_id_photo_outfit.py
"""
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile

from PIL import Image

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PKG)

_spec = importlib.util.spec_from_file_location(
    "qg_id_photo_outfit_under_test", os.path.join(PKG, "qg_id_photo_outfit.py"),
    submodule_search_locations=[PKG])
IPO = importlib.util.module_from_spec(_spec)
sys.modules["qg_id_photo_outfit_under_test"] = IPO
_spec.loader.exec_module(IPO)

ok = 0
fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS", name)
    else:
        fail += 1
        print("FAIL", name, extra)


def make_img(path):
    Image.new("RGB", (32, 40), (150, 160, 170)).save(path)


def build_tree(root, layout, prompts=None):
    """layout: {分类: [文件名, ...]}；prompts: {分类: {stem: 提示词}}"""
    root.mkdir(parents=True, exist_ok=True)
    for cat, files in layout.items():
        d = root / cat
        d.mkdir(parents=True, exist_ok=True)
        for f in files:
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                make_img(d / f)
            else:
                (d / f).write_text("占位", encoding="utf-8")
    if prompts:
        (root / "id_photo_data.json").write_text(
            json.dumps({"prompts": prompts}, ensure_ascii=False),
            encoding="utf-8")


# ---------- 一、扫描与提示词解析 ----------

tmp = tempfile.mkdtemp(prefix="qg_ipo_test_")
root = IPO.Path(tmp)
layout = {
    "2. 服装_男士": ["01.衬衫-白衬衫配黑领带.jpg", "02.西装.jpg"],
    "1. 服装_女士": ["03.马甲.jpg"],
    ".hidden": ["x.jpg"],                      # 点开头目录应被跳过
    "notes": ["readme.txt"],                   # 无图片文件的目录不算分类
}
prompts = {"1. 服装_女士": {"03.马甲": "米白色西装马甲内搭粉色短款衬衫"}}
build_tree(root, layout, prompts)

cats, templates, files = IPO.scan_templates(root, force=True)
check("扫描：分类按目录名排序", cats == ["1. 服装_女士", "2. 服装_男士"], cats)
check("扫描：点开头目录被跳过", ".hidden" not in cats)
check("扫描：无图片目录不算分类", "notes" not in cats)
check("扫描：女士分类 1 个模板", len(templates["1. 服装_女士"]) == 1)
check("扫描：男士分类 2 个模板", len(templates["2. 服装_男士"]) == 2)

w = templates["1. 服装_女士"][0]
check("解析：JSON 映射优先（提示词来自 id_photo_data.json）",
      w["prompt"] == "米白色西装马甲内搭粉色短款衬衫", w)
w = templates["2. 服装_男士"][0]
check("解析：文件名内嵌（标题-提示词）", w["title"] == "01.衬衫"
      and w["prompt"] == "白衬衫配黑领带", w)
w = templates["2. 服装_男士"][1]
check("解析：无提示词来源时为空", w["prompt"] == "", w)
check("索引：stem 小写 → 实际文件名",
      files["1. 服装_女士"].get("03.马甲") == "03.马甲.jpg")

# ---------- 二、缓存失效（新增素材不重启） ----------

make_img(root / "2. 服装_男士" / "03.马甲.jpg")
cats2, templates2, _f = IPO.scan_templates(root)
check("缓存：目录签名变化后自动重扫", len(templates2["2. 服装_男士"]) == 3,
      len(templates2["2. 服装_男士"]))

# ---------- 三、空目录兜底 ----------

empty = IPO.Path(tempfile.mkdtemp(prefix="qg_ipo_empty_"))
cats_e, tpl_e, files_e = IPO.scan_templates(empty, force=True)
check("兜底：空素材目录 → 「无数据」分类", cats_e == ["无数据"], cats_e)
check("兜底：「无数据」分类模板为空", tpl_e["无数据"] == [])

# ---------- 三·五、多根合并（插件内置 + 用户 models 目录） ----------

multi_a = IPO.Path(tempfile.mkdtemp(prefix="qg_ipo_multi_a_"))
multi_b = IPO.Path(tempfile.mkdtemp(prefix="qg_ipo_multi_b_"))
(multi_a / "1. 服装_女士").mkdir(parents=True, exist_ok=True)
(multi_b / "1. 服装_女士").mkdir(parents=True, exist_ok=True)
(multi_b / "8. 发型_女士").mkdir(parents=True, exist_ok=True)
make_img(multi_a / "1. 服装_女士" / "01.西装.jpg")
make_img(multi_a / "1. 服装_女士" / "02.衬衫.jpg")
make_img(multi_b / "1. 服装_女士" / "03.圆领.jpg")   # 同名分类补图
make_img(multi_b / "8. 发型_女士" / "01.短发.jpg")   # 只在第二根的新分类
_orig_roots = IPO._candidate_roots
IPO._candidate_roots = lambda: [multi_a, multi_b]
try:
    cats_m, tpl_m, _f_m = IPO.scan_templates(force=True)
    check("多根：分类合并且保序", cats_m == ["1. 服装_女士", "8. 发型_女士"], cats_m)
    check("多根：同名分类跨根补图", len(tpl_m["1. 服装_女士"]) == 3,
          len(tpl_m["1. 服装_女士"]))
    check("多根：新分类可见", len(tpl_m["8. 发型_女士"]) == 1)
    check("多根：resolve 命中第二根的分类图",
          IPO.resolve_image("8. 发型_女士", "01.短发.jpg") is not None)
finally:
    IPO._candidate_roots = _orig_roots
    shutil.rmtree(multi_a, ignore_errors=True)
    shutil.rmtree(multi_b, ignore_errors=True)

# ---------- 四、路径安全 ----------

check("清洗：目录穿越拒绝", IPO._safe_part("..%2F..") is None
      and IPO._safe_part("a/../b") is None)
check("清洗：反斜杠拒绝", IPO._safe_part("a\\b.jpg") is None)
check("清洗：绝对路径拒绝", IPO._safe_part("/etc/passwd") is None)
check("清洗：点开头拒绝", IPO._safe_part(".git") is None)
check("清洗：空值拒绝", IPO._safe_part("") is None)
check("清洗：常规中文分类名通过", IPO._safe_part("1. 服装_女士") == "1. 服装_女士")
check("清洗：全角标点文件名通过（v2.9.1 修复）",
      IPO._safe_part("01.西装-深灰西装，白衬衫，领带.jpg")
      == "01.西装-深灰西装，白衬衫，领带.jpg"
      and IPO._safe_part("05.高领（米色）.png") == "05.高领（米色）.png")

check("resolve：非法分类返回 None",
      IPO.resolve_image("../x", "01.西装.jpg", root) is None)
check("resolve：非法文件名返回 None",
      IPO.resolve_image("2. 服装_男士", "..\\evil.jpg", root) is None)
check("resolve：非图片扩展名拒绝",
      IPO.resolve_image("2. 服装_男士", "evil.exe", root) is None)
check("resolve：存在的图命中",
      (IPO.resolve_image("2. 服装_男士", "02.西装.jpg", root) or IPO.Path())
      .name == "02.西装.jpg")
check("resolve：不存在的图返回 None",
      IPO.resolve_image("2. 服装_男士", "99.不存在.jpg", root) is None)
check("resolve：旧长文件名回退（磁盘短名，请求长名）",
      (IPO.resolve_image("2. 服装_男士", "03.马甲-旧提示词.jpg", root)
       or IPO.Path()).name == "03.马甲.jpg")
check("resolve：旧长文件名回退（磁盘同为长名，同短标题）",
      (IPO.resolve_image("2. 服装_男士", "01.衬衫-旧提示词.jpg", root)
       or IPO.Path()).name == "01.衬衫-白衬衫配黑领带.jpg")

# ---------- 五、节点契约与执行 ----------

# INPUT_TYPES 默认走 _template_root()；测试把它指到 tmp 素材目录再校验下拉
IPO._template_root = lambda: root

node = IPO.QGIDPhotoOutfit()
inp = node.INPUT_TYPES()
check("契约：注册 key", "QG_IDPhotoOutfit" in IPO.NODE_CLASS_MAPPINGS)
check("契约：显示名",
      IPO.NODE_DISPLAY_NAME_MAPPINGS["QG_IDPhotoOutfit"] == "QG 证件照服装发型")
check("契约：RETURN_TYPES", node.RETURN_TYPES == ("STRING",))
check("契约：RETURN_NAMES", node.RETURN_NAMES == ("提示词",))
check("契约：FUNCTION/CATEGORY",
      node.FUNCTION == "execute" and node.CATEGORY == "QG 工具")
check("契约：输入下拉含扫描到的分类",
      set(inp["required"]["style"][0]) >= {"1. 服装_女士", "2. 服装_男士"},
      inp["required"]["style"][0])
check("契约：提示词控件 multiline",
      inp["required"]["prompt_output"][1].get("multiline") is True)
check("契约：hidden unique_id", inp["hidden"]["unique_id"] == "UNIQUE_ID")
check("执行：透传提示词", node.execute("1. 服装_女士", "测试 ABC")[0] == "测试 ABC")
check("执行：空值容错", node.execute("x")[0] == "")

# ---------- 六、i18n 与登记 ----------

nd = json.load(open(os.path.join(PKG, "locales", "zh", "nodeDefs.json"),
                    encoding="utf-8"))
tr = json.load(open(os.path.join(PKG, "translations", "zh-CN", "Nodes",
                                 "ComfyUI-QG-Multipack.json"), encoding="utf-8"))
entry = nd.get("QG_IDPhotoOutfit", {})
check("i18n：nodeDefs display_name",
      entry.get("display_name") == "QG 证件照服装发型")
check("i18n：nodeDefs 官方字段口径",
      "title" not in entry and "description" in entry)
check("i18n：nodeDefs outputs 索引 key",
      list(entry.get("outputs", {})) == ["0"])
tr_entry = tr.get("QG_IDPhotoOutfit", {})
check("i18n：translations 标题与 inputs",
      tr_entry.get("title") == "QG 证件照服装发型"
      and tr_entry.get("inputs", {}).get("style") == "风格类型"
      and tr_entry.get("inputs", {}).get("prompt_output") == "提示词")
check("i18n：两份词表节点数一致（随包 37 节点）", len(nd) == len(tr) == 37,
      "%d/%d" % (len(nd), len(tr)))

js_path = os.path.join(PKG, "web", "qg_id_photo_outfit.js")
js = open(js_path, encoding="utf-8").read()
check("前端：扩展文件存在且注册面板扩展", 'name: "QG.IDPhotoOutfit"' in js)
check("前端：接入节点 key", "QG_IDPhotoOutfit" in js)
check("前端：API 路由一致",
      "/qg-multipack/id_photo/templates" in js
      and "/qg-multipack/id_photo/image" in js)
check("前端：规范红线（.connect/.bind 字面量）",
      ".connect(" not in js and ".bind(" not in js)

init_src = open(os.path.join(PKG, "__init__.py"), encoding="utf-8").read()
check("注册：__init__.py 导入块", "qg_id_photo_outfit" in init_src)

readme = open(os.path.join(PKG, "README.md"), encoding="utf-8").read()
check("README：一览表登记", "QG_IDPhotoOutfit" in readme)
check("README：覆盖节点数与包内一致", "覆盖全部 37 个节点" in readme)
check("README：概括句与包内一致", "37 个节点里 36 个" in readme)
check("README：新章节含素材格式", "models/id_photo/" in readme
      and "id_photo_data.json" in readme)

gi = open(os.path.join(PKG, ".gitignore"), encoding="utf-8").read()
check("gitignore：素材随包分发（无生效的 models/id_photo 排除行）",
      not any(line.strip() == "models/id_photo/"
              or line.strip() == "models/id_photo"
              for line in gi.splitlines()))
asset_dir = os.path.join(PKG, "models", "id_photo")
check("内置素材：目录存在且分类齐全",
      os.path.isdir(asset_dir)
      and len([d for d in os.listdir(asset_dir)
               if os.path.isdir(os.path.join(asset_dir, d))]) == 7)
check("内置素材：200 张图 + 提示词 JSON",
      len([f for f in os.listdir(os.path.join(asset_dir, "1. 服装_女士"))
           if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]) > 0
      and os.path.isfile(os.path.join(asset_dir, "id_photo_data.json")))

shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(empty, ignore_errors=True)

print("\nPASS %d / FAIL %d" % (ok, fail))
sys.exit(1 if fail else 0)
