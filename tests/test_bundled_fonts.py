# -*- coding: utf-8 -*-
"""随包开放许可字体：许可合规性 + 字体发现 + 中文渲染 + 打包规则。

用户 2026-11-15 要求「无版权字体也随包」。这里固化的口径是：

* 随包字体必须是明确 **SIL OFL 1.1**、可自由再分发/商用、且附许可全文；
* 插件目录顶层 ``fonts/`` 里的专有字体一律不进仓库、不进备份包；
* ``QG_PhotoSheet`` / ``QG_PhotoSheetMixed`` / ``QG_Watermark`` 的字体
  下拉必须优先列出随包字体，中文标注/水印开箱即用；
* 可变字体在运行时固定到 Regular，但字体文件本身保持官方原样。

不依赖 GPL 参考源码，可单独运行。
"""
import importlib
import importlib.util
import json
import pathlib
import sys
import types

from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).resolve().parent
PKG = HERE.parent
WORKSPACE = PKG.parent

ok = 0
fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS", name)
    else:
        fail += 1
        print("FAIL", name, detail)


# --------------------------------------------------------------- 资产与许可
font_dir = PKG / "assets" / "fonts"
font_file = font_dir / "NotoSansSC-VF.ttf"
license_file = font_dir / "OFL.txt"

check("资产：assets/fonts/ 存在", font_dir.is_dir(), str(font_dir))
check("资产：NotoSansSC-VF.ttf 存在", font_file.is_file(), str(font_file))
size_mb = font_file.stat().st_size / 1048576 if font_file.is_file() else 0
check("资产：字体体积 > 10 MB（未被截断）", size_mb > 10, "%.2f MB" % size_mb)
check("资产：OFL.txt 存在", license_file.is_file(), str(license_file))

lic = license_file.read_text(encoding="utf-8") if license_file.is_file() else ""
check("许可：含 OFL 1.1 标题行",
      "SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007" in lic)
check("许可：含 PERMISSION & CONDITIONS", "PERMISSION & CONDITIONS" in lic)
check("许可：含 TERMINATION", "TERMINATION" in lic)
check("许可：含 DISCLAIMER", "DISCLAIMER" in lic)
check("许可：声明保留字体名 Source", "Reserved Font Name" in lic and "Source" in lic)
check("许可：声明原样分发未修改", "UNMODIFIED" in lic.upper() or "未修改" in lic)

# 字体内嵌 name 表是许可判定的第一手证据；fontTools 是可选依赖，
# 缺失时只跳过这几项，其余断言照常执行。
try:
    from fontTools.ttLib import TTFont
    has_ft = True
except ImportError:
    has_ft = False

if has_ft:
    tt = TTFont(str(font_file), lazy=True)

    def name_text(nid):
        values = []
        for rec in tt["name"].names:
            if rec.nameID == nid:
                values.append(rec.toUnicode())
        return " ".join(values)

    check("字体：nameID 13 声明 OFL 1.1",
          "SIL Open Font License" in name_text(13)
          and "Version 1.1" in name_text(13), name_text(13)[:120])
    check("字体：nameID 14 指向 scripts.sil.org/OFL",
          "scripts.sil.org/OFL" in name_text(14), name_text(14)[:120])
    check("字体：nameID 0 含 Adobe 版权与保留名 Source",
          "Adobe" in name_text(0) and "Source" in name_text(0),
          name_text(0)[:120])
    cmap = tt.getBestCmap() or {}
    probe = "证件照中文排版文字水印一二三四五六"
    check("字体：中文常用字全覆盖",
          all(ord(ch) in cmap for ch in probe),
          "%d/%d" % (sum(1 for ch in probe if ord(ch) in cmap), len(probe)))
    check("字体：覆盖拉丁字母", ord("A") in cmap)
else:
    print("SKIP fontTools 不可用，跳过 name 表 / cmap 断言")

check("字体：PIL 能加载", bool(ImageFont.truetype(str(font_file), 32)))

# 官方文件原样分发：与系统字体库里的同一文件逐字节相同（若该文件存在）
system_copy = pathlib.Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf")
if system_copy.is_file():
    import hashlib
    same = (hashlib.sha256(system_copy.read_bytes()).digest()
            == hashlib.sha256(font_file.read_bytes()).digest())
    check("字体：与官方原文件字节一致（未修改）", same)
else:
    print("SKIP 系统字体库无同源副本，跳过字节比对")

# --------------------------------------------------------------- 字体发现
# photo_sheet_node / watermark_node 有包内相对导入，用虚拟包加载（不执行
# __init__.py）；photo_sheet_mixed_node 保持零相对导入，按单文件加载，
# 与 tests/test_photo_sheet_mixed.py 的方式一致。
pkg_name = "_qg_bundled_font_test_pkg"
if pkg_name not in sys.modules:
    virtual = types.ModuleType(pkg_name)
    virtual.__path__ = [str(PKG)]
    sys.modules[pkg_name] = virtual
PS = importlib.import_module(pkg_name + ".photo_sheet_node")
WM = importlib.import_module(pkg_name + ".watermark_node")

spec = importlib.util.spec_from_file_location(
    "qg_bundled_font_psm", str(PKG / "photo_sheet_mixed_node.py"))
MX = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MX)

BUNDLED = "NotoSansSC-VF.ttf"
check("发现：两个节点指向同一内置目录",
      PS.BUNDLED_FONTS_DIR == MX.BUNDLED_FONTS_DIR,
      (PS.BUNDLED_FONTS_DIR, MX.BUNDLED_FONTS_DIR))
check("发现：内置目录就是 assets/fonts",
      pathlib.Path(PS.BUNDLED_FONTS_DIR).resolve() == font_dir.resolve())
check("发现：PhotoSheet 内置目录排第一",
      PS._font_dirs()[0] == PS.BUNDLED_FONTS_DIR)
check("发现：Mixed 内置目录排第一",
      MX._font_dirs()[0] == MX.BUNDLED_FONTS_DIR)
check("发现：PhotoSheet 下拉首项是随包字体",
      PS.font_choices()[1] == BUNDLED, PS.font_choices()[:3])
check("发现：Mixed 下拉首项是随包字体",
      MX.font_choices()[1] == BUNDLED, MX.font_choices()[:3])
resolved = PS.resolve_font(BUNDLED)
check("发现：resolve_font 命中 assets/fonts",
      bool(resolved) and pathlib.Path(resolved).parent.resolve() == font_dir.resolve(),
      str(resolved))
check("发现：Watermark 默认字体是随包字体",
      WM._default_font() == BUNDLED, WM._default_font())

for proprietary in ("苹方粗体.ttf", "华文细黑.ttf", "楷体.ttf", "FZCCHJW.TTF"):
    check("发现：下拉不含商业字体 %s" % proprietary,
          proprietary not in PS.font_choices()
          and proprietary not in MX.font_choices())


# --------------------------------------------------------------- 中文渲染
def ink(face, text="证件照中文排版测试"):
    image = Image.new("L", (420, 64), 0)
    ImageDraw.Draw(image).text((4, 4), text, font=face, fill=255)
    return sum(1 for value in image.get_flattened_data() if value > 20)


bitmap_ink = ink(ImageFont.load_default())
ps_face, ps_used = PS.load_font(BUNDLED, 36)
mx_face = MX.load_font(BUNDLED, 36)
check("渲染：PhotoSheet 用上随包字体", ps_used == BUNDLED, ps_used)
check("渲染：PhotoSheet 固定到 Regular 字重",
      ps_face.getname()[1] == "Regular", str(ps_face.getname()))
check("渲染：Mixed 固定到 Regular 字重",
      mx_face.getname()[1] == "Regular", str(mx_face.getname()))
check("渲染：PhotoSheet 中文有真实字形（墨迹 > 位图 3 倍）",
      ink(ps_face) > bitmap_ink * 3, (ink(ps_face), bitmap_ink))
check("渲染：Mixed 中文有真实字形（墨迹 > 位图 3 倍）",
      ink(mx_face) > bitmap_ink * 3, (ink(mx_face), bitmap_ink))
check("渲染：两路字体渲染结果一致", ink(ps_face) == ink(mx_face))

# --------------------------------------------------------------- 打包规则
pack_script = (WORKSPACE / "打包备份.py").read_text(encoding="utf-8")
gitignore = (PKG / ".gitignore").read_text(encoding="utf-8")
gitattributes = (PKG / ".gitattributes").read_text(encoding="utf-8")

rule_lines = [line.strip() for line in gitignore.splitlines()
              if line.strip() and not line.strip().startswith("#")]
check("打包：.gitignore 用 /fonts/ 锚定顶层", "/fonts/" in rule_lines)
check("打包：.gitignore 无裸 fonts/ 规则（否则会误伤 assets/fonts）",
      "fonts/" not in rule_lines, rule_lines)
check("打包：.gitignore 不排除 assets/fonts/",
      not any("assets/fonts/" in line for line in rule_lines))
# 文本断言之外，再让 git 自己判一次，避免规则写法与实际行为不一致
try:
    import subprocess
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "assets/fonts/NotoSansSC-VF.ttf"],
        cwd=str(PKG), capture_output=True)
    check("打包：git check-ignore 实测不忽略随包字体",
          ignored.returncode == 1, "returncode=%s" % ignored.returncode)
except OSError:
    print("SKIP git 不可用，跳过 check-ignore 实测")
check("打包：.gitattributes 把 ttf 当二进制", "*.ttf binary" in gitattributes)
check("打包：EXCLUDE_TOP_DIRS 含 fonts",
      'EXCLUDE_TOP_DIRS = {"fonts"}' in pack_script)
check("打包：collect_files 使用 EXCLUDE_TOP_DIRS",
      "rel.parts[0] in EXCLUDE_TOP_DIRS" in pack_script)
check("打包：make_zip 校验 fonts/ 不得入包",
      'TOP_DIR + "/fonts/"' in pack_script)
check("打包：REQUIRED 含随包字体",
      '"assets/fonts/NotoSansSC-VF.ttf"' in pack_script)
check("打包：REQUIRED 含许可全文",
      '"assets/fonts/OFL.txt"' in pack_script)

# --------------------------------------------------------------- 文档与词表
readme = (PKG / "README.md").read_text(encoding="utf-8")
notices = (PKG / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
nd = json.loads((PKG / "locales/zh/nodeDefs.json").read_text(encoding="utf-8"))

check("文档：README 说明随包字体与 OFL",
      "assets/fonts/" in readme and "SIL OFL 1.1" in readme)
check("文档：README 不再写「字体不随仓库分发」",
      "**字体**：`fonts/` 目录不随 git 仓库分发" not in readme)
check("文档：README 列出不随包的专有字体",
      "Do not distribute" in readme)
check("文档：THIRD-PARTY-NOTICES 有 Noto Sans SC 条目",
      "## Noto Sans SC — bundled font (SIL OFL 1.1)" in notices)
check("文档：THIRD-PARTY-NOTICES 改成双重排除口径",
      "not distributed through the git repository" not in notices
      and "excluded by `.gitignore` AND by the packaging script" in notices)
for key in ("QG_PhotoSheet", "QG_PhotoSheetMixed", "QG_Watermark"):
    tip = nd[key]["inputs"]["font"]["tooltip"]
    check("词表：%s 的 font tooltip 提到 Noto Sans SC" % key,
          "Noto Sans SC" in tip, tip)

print("\nPASS %d / FAIL %d" % (ok, fail))
sys.exit(1 if fail else 0)
