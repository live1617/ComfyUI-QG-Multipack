# -*- coding: utf-8 -*-
"""config.json 迁移到 user 目录的路径逻辑测试。

不碰真实 config.json：legacy 路径 monkeypatch 到临时目录。
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PACK = os.path.dirname(HERE)
sys.path.insert(0, PACK)
sys.path.insert(0, os.path.join(PACK, "..", "..", ".."))  # ComfyUI 根，供 folder_paths

import translate_core as t  # noqa: E402

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


tmp = tempfile.mkdtemp(prefix="_qg_cfgtest_")
fake_pack = os.path.join(tmp, "pack")           # 假装插件目录
fake_user = os.path.join(tmp, "user")           # 假装 user 目录
os.makedirs(fake_pack)
os.makedirs(os.path.join(fake_user, "ComfyUI-QG-Multipack"))

# --- 场景 0：拿不到 user 目录时退回插件目录 ---
import folder_paths  # noqa: E402  ComfyUI 根已在 sys.path
real_user = folder_paths.get_user_directory()

# 把 user 目录临时指到假目录，验证真实分支
folder_paths.set_user_directory(fake_user)
t._legacy_config_path = lambda: os.path.join(fake_pack, "config.json")

# --- 场景 1：user 里已有 config.json → 直接用 ---
p_new = os.path.join(fake_user, "ComfyUI-QG-Multipack", "config.json")
with open(p_new, "w", encoding="utf-8") as f:
    json.dump({"api_key": "in-user"}, f)
check("user 已有配置时用 user 路径", t._config_path() == p_new)
check("load 读到 user 的值", t.load_config().get("api_key") == "in-user")

# --- 场景 2：user 没有、插件目录有旧文件 → 自动迁移，旧文件消失 ---
os.remove(p_new)
t._config_cache["stamp"] = None
t._config_cache["data"] = {}
p_legacy = os.path.join(fake_pack, "config.json")
with open(p_legacy, "w", encoding="utf-8") as f:
    json.dump({"api_key": "legacy", "baidu": {"appid": "a", "key": "k"}}, f)
resolved = t._config_path()
check("无 user 配置时解析到 user 路径", resolved == p_new, resolved)
check("迁移后旧文件已消失", not os.path.exists(p_legacy))
check("迁移后内容一致", t.load_config().get("api_key") == "legacy")
check("迁移后 baidu 段完整", t.load_config().get("baidu", {}).get("key") == "k")

# --- 场景 3：两边都没有 → 返回 user 路径，读作空 ---
os.remove(p_new)
t._config_cache["stamp"] = None
t._config_cache["data"] = {}
check("两边都没有时返回 user 路径", t._config_path() == p_new)
check("读作空 dict", t.load_config() == {})

# --- 场景 4：save 落在 user 目录 ---
t.save_config({"api_key": "saved"})
check("save 写进 user 目录", os.path.exists(p_new))
check("save 后读回一致", t.load_config().get("api_key") == "saved")
check("save 不污染插件目录", not os.path.exists(os.path.join(fake_pack, "config.json")))

# --- 场景 5：folder_paths 不可用（裸进程）→ 退回插件目录 ---
folder_paths.set_user_directory(real_user)  # 先恢复
import builtins
real_import = builtins.__import__


def blocked(name, *a, **kw):
    if name == "folder_paths":
        raise ImportError("simulated standalone")
    return real_import(name, *a, **kw)


t._config_cache["stamp"] = None
t._config_cache["data"] = {}
builtins.__import__ = blocked
try:
    fallback = t._config_path()
finally:
    builtins.__import__ = real_import
check("无 folder_paths 时退回插件目录",
      fallback == os.path.join(PACK, "config.json"), fallback)

# --- 真实环境验证（不迁移，只确认路径解析指向 user）---
check("真实环境解析到 user 目录",
      os.path.normcase(t._config_path()) ==
      os.path.normcase(os.path.join(real_user, "ComfyUI-QG-Multipack", "config.json")),
      t._config_path())

print("\n通过 %d / 失败 %d" % (ok, fail))
sys.exit(1 if fail else 0)
