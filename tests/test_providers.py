# -*- coding: utf-8 -*-
"""服务商配置层回归：设置面板存的多条 API 能不能被节点正确解析。

不依赖 ComfyUI —— 直接按文件加载包根的 translate_core.py（配置读写都在
那里；translate_node.py 只是节点外壳，2026-11-05 拆分后不再含这些函数）。
"""
import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

spec_path = os.path.join(PKG, "translate_core.py")
mod = types.ModuleType("qg_tr")
mod.__file__ = spec_path
code = compile(open(spec_path, encoding="utf-8").read(), spec_path, "exec")
exec(code, mod.__dict__)

ok = lambda c: "PASS" if c else "FAIL"
fails = []


def check(label, cond, extra=""):
    print(("  " + label + ": " + str(extra)).ljust(64), ok(cond))
    if not cond:
        fails.append(label)


tmpdir = tempfile.mkdtemp(prefix="qg-prov-")
mod._config_dir = lambda: tmpdir
mod._config_cache["stamp"] = None
mod._config_cache["data"] = {}
CFG = os.path.join(tmpdir, "config.json")

print("=== A. 条目清洗 ===")
p = mod._clean_provider({"name": "  智谱  ", "api_url": " http://a ", "model": " glm ", "api_key": " sk-1 "})
check("name 去空白", p["name"] == "智谱", p["name"])
check("url 去空白", p["api_url"] == "http://a", p["api_url"])
check("model 去空白", p["model"] == "glm", p["model"])
check("key 去空白", p["api_key"] == "sk-1", p["api_key"])
check("缺 id 自己补", bool(p["id"]), p["id"])
p = mod._clean_provider({"name": "x", "api_url": 123, "model": None}, 4)
check("脏类型不炸", p["api_url"] == "123" and p["model"] == "", (p["api_url"], p["model"]))

print("\n=== B. 读写 config.json ===")
mod.save_config({"api_key": "legacy-key", "providers": [
    {"id": "a", "name": "智谱 GLM", "api_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
     "model": "glm-4-flash", "api_key": "sk-aaaa1111"},
    {"id": "b", "name": "中转站", "api_url": "https://relay.example.com/v1/chat/completions",
     "model": "gpt-4o-mini", "api_key": "sk-bbbb2222"},
]})
check("文件落盘", os.path.exists(CFG))
cfg = json.load(open(CFG, encoding="utf-8"))
check("保留旧 api_key", cfg.get("api_key") == "legacy-key", cfg.get("api_key"))
check("条目数", len(cfg.get("providers") or []) == 2)

print("\n=== C. 列表 / 掩码 ===")
lst = mod.list_providers()
check("默认不吐 key", all("api_key" not in x for x in lst), lst[0].keys() if lst else None)
lst2 = mod.list_providers(with_key=True)
check("显式要才给 key", lst2[0]["api_key"] == "sk-aaaa1111", lst2[0]["api_key"])
check("掩码", mod.mask_key("sk-aaaa1111") == "sk-a****", mod.mask_key("sk-aaaa1111"))
check("空 key 掩码为空", mod.mask_key("") == "")
check("超短 key 全掩", mod.mask_key("short") == "****", mod.mask_key("short"))

print("\n=== D. 下拉选项 ===")
choices = mod.provider_choices()
check("含内置 custom", "custom" in choices, choices[:3])
check("含内置 DeepSeek", "DeepSeek" in choices)
check("含自定义条目", "智谱 GLM" in choices and "中转站" in choices, choices[-2:])

print("\n=== E. 解析：自定义条目 ===")
r = mod.resolve_provider("智谱 GLM")
check("url 来自条目", r["api_url"].startswith("https://open.bigmodel.cn"), r["api_url"])
check("model 来自条目", r["model"] == "glm-4-flash", r["model"])
check("key 来自条目", r["api_key"] == "sk-aaaa1111", r["api_key"])

print("\n=== F. 解析：内置预设仍可用 ===")
r = mod.resolve_provider("DeepSeek")
check("内置 url", r["api_url"] == mod.PRESETS["DeepSeek"]["api_url"], r["api_url"])
check("内置无 key", r["api_key"] == "", r["api_key"])

print("\n=== G. 自定义同名条目覆盖内置 ===")
mod.save_config({"providers": [
    {"id": "c", "name": "DeepSeek", "api_url": "https://my-proxy/deepseek",
     "model": "deepseek-reasoner", "api_key": "sk-cccc"},
]})
r = mod.resolve_provider("DeepSeek")
check("用自己的地址", r["api_url"] == "https://my-proxy/deepseek", r["api_url"])
check("选项不重复", mod.provider_choices().count("DeepSeek") == 1,
      mod.provider_choices()[:2])

print("\n=== H. 默认服务商 ===")
mod.save_config({"providers": [
    {"id": "c", "name": "DeepSeek", "api_url": "https://my-proxy/deepseek",
     "model": "deepseek-reasoner", "api_key": "sk-cccc"},
], "default_provider": "DeepSeek"})
check("配置里的默认值生效", mod.default_provider() == "DeepSeek", mod.default_provider())
mod.save_config({"providers": [], "default_provider": "不存在的"})
check("非法默认值退回 custom", mod.default_provider() == "custom", mod.default_provider())

print("\n=== I. 无名条目被忽略（下拉里选不到） ===")
mod.save_config({"providers": [
    {"id": "d", "name": "  ", "api_url": "https://x", "model": "m"},
    {"id": "e", "name": "有效", "api_url": "https://y", "model": "m"},
]})
check("只留一条", len(mod.list_providers()) == 1, mod.list_providers())

print("\n=== J. translate 用条目的地址与 key ===")
mod.save_config({"providers": [
    {"id": "f", "name": "我的站", "api_url": "https://mine/v1/chat/completions",
     "model": "my-model", "api_key": "sk-mine"},
]})
seen = {}


def fake_call(url, key, model, messages, meta=None):
    # translate() 会传 meta 用来判断译文是否被截断（截断结果不进缓存），
    # 替身必须接受这个形参，否则契约一改测试就假失败。
    seen.update({"url": url, "key": key, "model": model})
    if isinstance(meta, dict):
        meta["truncated"] = False
    return "translated"


mod.call_api = fake_call
mod._CACHE.clear()
out = mod.translate("你好", "我的站", "", "", "", "auto", "english")
check("返回结果", out == "translated", out)
check("用的是条目 url", seen["url"] == "https://mine/v1/chat/completions", seen["url"])
check("用的是条目 model", seen["model"] == "my-model", seen["model"])
check("用的是条目 key", seen["key"] == "sk-mine", seen["key"])

seen.clear()
mod._CACHE.clear()
mod.translate("你好2", "我的站", "https://override/v1", "override-model", "sk-typed", "auto", "english")
check("节点上手填的优先", seen["url"] == "https://override/v1" and seen["key"] == "sk-typed", seen)

print("\n=== K. 没有地址时报错清楚 ===")
mod.save_config({"providers": []})
mod._CACHE.clear()
try:
    mod.translate("x", "custom", "", "", "", "auto", "english")
    check("应当抛错", False)
except ValueError as e:
    check("提示指向设置面板", "settings panel" in str(e), str(e)[:60])

print("\n=== L. config 缓存会因写盘失效 ===")
mod.save_config({"providers": [{"id": "g", "name": "第一次", "api_url": "u", "model": "m"}]})
check("读到第一次", mod.list_providers()[0]["name"] == "第一次")
mod.save_config({"providers": [{"id": "g", "name": "第二次", "api_url": "u", "model": "m"}]})
check("立刻读到第二次", mod.list_providers()[0]["name"] == "第二次",
      mod.list_providers()[0]["name"])

print("\n=== M. 内置预设的 key（设置面板可给内置厂商存 key） ===")
mod.save_config({"preset_api_keys": {"DeepSeek": "sk-preset-1"}, "providers": []})
mod._CACHE.clear()
check("preset_key 读出", mod.preset_key("DeepSeek") == "sk-preset-1", mod.preset_key("DeepSeek"))
check("preset_key 没配的为空", mod.preset_key("没有的") == "")
r = mod.resolve_provider("DeepSeek")
check("resolve 带出预设 key", r["api_key"] == "sk-preset-1", r["api_key"])
check("resolve 地址仍是内置", r["api_url"] == mod.PRESETS["DeepSeek"]["api_url"])
mod.save_config({"preset_api_keys": {}})
check("删掉后 resolve 无 key", mod.resolve_provider("DeepSeek")["api_key"] == "")

print("\n=== N. 自定义条目 key 优先于内置预设 key（同名覆盖语义完整） ===")
mod.save_config({"preset_api_keys": {"DeepSeek": "sk-preset-1"}, "providers": [
    {"id": "h", "name": "DeepSeek", "api_url": "https://my-proxy/ds",
     "model": "deepseek-reasoner", "api_key": "sk-custom-2"},
]})
r = mod.resolve_provider("DeepSeek")
check("同名自定义整体覆盖", r["api_key"] == "sk-custom-2" and r["api_url"] == "https://my-proxy/ds", r)

print("\n=== O. 一个服务商挂多个模型 ===")
mod.save_config({"providers": [], "preset_api_keys": {}})
mod._CACHE.clear()

# 老配置只有单模型字段：要自动展开成一元素列表
legacy = mod._clean_provider({"name": "老条目", "api_url": "u", "model": "m-old"})
check("老字段展开成列表", legacy["models"] == ["m-old"], legacy["models"])
check("老字段就是默认模型", legacy["default_model"] == "m-old", legacy["default_model"])

multi = mod._clean_provider({
    "name": "中转站", "api_url": "https://x/chat/completions",
    "models": ["gpt-4o-mini", " claude-3-5 ", "gpt-4o-mini", ""],
    "default_model": "claude-3-5",
})
check("模型去重去空", multi["models"] == ["gpt-4o-mini", "claude-3-5"], multi["models"])
check("默认模型保留", multi["default_model"] == "claude-3-5", multi["default_model"])
check("model 镜像默认", multi["model"] == "claude-3-5", multi["model"])

bad_default = mod._clean_provider({
    "name": "x", "models": ["a", "b"], "default_model": "根本不在列表里"})
check("默认模型非法时落到第一个", bad_default["default_model"] == "a", bad_default["default_model"])

too_many = mod._clean_provider({"name": "y", "models": ["m%d" % i for i in range(60)]})
check("模型数量有上限", len(too_many["models"]) == mod.MAX_MODELS, len(too_many["models"]))

mod.save_config({"providers": [{
    "id": "p1", "name": "中转站", "api_url": "https://x/v1/chat/completions",
    "models": ["gpt-4o-mini", "claude-3-5-sonnet"], "default_model": "gpt-4o-mini",
    "api_key": "sk-1",
}]})

r = mod.resolve_provider("中转站")
check("只写服务商名用默认模型", r["model"] == "gpt-4o-mini", r["model"])
r = mod.resolve_provider("中转站/claude-3-5-sonnet")
check("写 服务商/模型 用指名模型", r["model"] == "claude-3-5-sonnet", r["model"])
check("拆分后地址仍是同一家", r["api_url"] == "https://x/v1/chat/completions", r["api_url"])
check("拆分后 key 仍带出", r["api_key"] == "sk-1", r["api_key"])

choices = mod.service_choices()
check("下拉含服务商名", "中转站" in choices, choices)
check("下拉展开非默认模型", "中转站/claude-3-5-sonnet" in choices, choices)
check("默认模型不重复出现", "中转站/gpt-4o-mini" not in choices, choices)
check("provider_choices 仍是纯名字", "中转站" in mod.provider_choices()
      and not any("/" in n for n in mod.provider_choices()), mod.provider_choices())
check("provider_models 列出全部", mod.provider_models("中转站")
      == ["gpt-4o-mini", "claude-3-5-sonnet"], mod.provider_models("中转站"))

# 内置预设也支持多模型与 服务商/模型 写法
check("预设带模型列表", "deepseek-reasoner" in mod.provider_models("DeepSeek"),
      mod.provider_models("DeepSeek"))
r = mod.resolve_provider("DeepSeek/deepseek-reasoner")
check("预设按名取模型", r["model"] == "deepseek-reasoner", r["model"])
check("预设默认仍是 deepseek-chat",
      mod.resolve_provider("DeepSeek")["model"] == "deepseek-chat",
      mod.resolve_provider("DeepSeek")["model"])

# 模型名自带斜杠时不能被短前缀切错
r = mod.resolve_provider("OpenRouter/openai/gpt-4o-mini")
check("嵌套斜杠不切错", r["model"] == "openai/gpt-4o-mini", r["model"])

# 认不出服务商
r = mod.resolve_provider("不存在的服务商/某个模型")
check("未知服务商不炸", isinstance(r, dict) and r["api_url"] == "", r)

# --- 文本 / 视觉模型分流（2026-11-06）------------------------------------
# 翻译、润色、扩写都是纯文本任务，下拉里不该出现视觉专用模型；看图反推
# 的节点走 vision_choices()，仍然要能看到它们。
check("视觉识别 glm-4.5v", mod.is_vision_only("glm-4.5v"))
check("视觉识别 glm-4v-flash", mod.is_vision_only("glm-4v-flash"))
check("视觉识别 glm-4.6v-flash", mod.is_vision_only("glm-4.6v-flash"))
check("视觉识别 qwen3-vl-plus", mod.is_vision_only("qwen3-vl-plus"))
check("视觉识别 qwen2.5-vl-72b", mod.is_vision_only("qwen/qwen2.5-vl-72b-instruct"))
check("视觉识别 llama3.2-vision", mod.is_vision_only("llama3.2-vision:11b"))
check("通用多模态不算视觉专用", not mod.is_vision_only("gpt-4o-mini"))
check("deepseek-v3 不误判", not mod.is_vision_only("deepseek-ai/DeepSeek-V3"))
check("glm-4-flash 不误判", not mod.is_vision_only("glm-4-flash"))

text_choices = mod.service_choices()
all_choices = mod.service_choices(True)
check("文本下拉无视觉模型",
      not any(mod.is_vision_only(x.split("/", 1)[1]) for x in text_choices
              if "/" in x),
      [x for x in text_choices if "/" in x and mod.is_vision_only(x.split("/", 1)[1])])
check("含视觉模式确实更多", len(all_choices) > len(text_choices),
      "%d vs %d" % (len(all_choices), len(text_choices)))
check("文本下拉是全集的子集", set(text_choices) <= set(all_choices))
check("默认值落在文本下拉里", mod.default_service_choice() in text_choices,
      mod.default_service_choice())

print("\n---")
print("失败 %d 项" % len(fails))
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("全部通过")
