"""通用的模型文件 HTTP 下载（带停滞看门狗）。

供各节点「用到时按需拉取」权重。设计要点：

- 只依赖标准库 ``urllib``，不引入 ``requests`` / ``huggingface_hub``，
  保持零额外依赖（BiRefNet 那套走 ``hf_hub_download``，本模块不掺和）。
- 在后台线程跑下载，主线程每 5 秒检查一次 ``.incomplete`` 临时文件的总字节数，
  超过 ``stall_seconds`` 无任何增长就放弃并报错——避免「TCP 连着但不再来数据」
  时无限期挂起（曾把一次执行卡了 19 分钟那种）。
- ``urlopen(timeout=30)`` 负责更底层的「单次读超时」，双重保险防无限挂起。
- 临时写 ``.incomplete``，整文件落盘成功才 ``os.replace`` 成最终名；中途失败
  清掉半截文件，下次重试能断点重下（urllib 不支持断点，这里只保证不残留垃圾）。

调用方负责把抛出的 ``RuntimeError`` 转成人能看懂的提示（含手动下载地址）。
"""

from __future__ import annotations

import os
import threading
import time
import urllib.request
import uuid

_USER_AGENT = "ComfyUI-QG-Multipack"

# 同一目标路径的下载串行化 + 唯一临时名，避免两个线程同时下同一模型互相踩。
_DOWNLOAD_LOCKS: dict = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(dest: str) -> "threading.Lock":
    """同一 ``dest`` 取同一把锁，让并发下载同一文件变成串行（不同文件互不影响）。"""
    with _LOCKS_GUARD:
        lock = _DOWNLOAD_LOCKS.get(dest)
        if lock is None:
            lock = threading.Lock()
            _DOWNLOAD_LOCKS[dest] = lock
        return lock


def http_download(url: str, dest: str, stall_seconds: float = 120.0,
                 min_bytes: int | None = None) -> str:
    """把 ``url`` 下载到 ``dest``（先写唯一 ``.incomplete``，完成再 rename）。

    返回最终文件路径。下载停滞超过 ``stall_seconds`` 秒、网络错误、或落盘后体积
    不足 ``min_bytes``（疑似下到错误页/拦截页）都抛 ``RuntimeError``，并清掉
    旁边的临时文件。

    线程安全：同一 ``dest`` 的并发调用会串行执行，临时文件名带 uuid，互不覆盖。
    """
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    # 每次调用一个唯一临时名：两个线程同时下同一模型也不会写坏同一文件。
    dest_tmp = "%s.%s.incomplete" % (dest, uuid.uuid4().hex)
    lock = _lock_for(dest)
    with lock:
        result: dict = {}

        def work() -> None:
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": _USER_AGENT})
                with urllib.request.urlopen(req, timeout=30) as resp, \
                        open(dest_tmp, "wb") as fh:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        fh.write(chunk)
                if min_bytes is not None:
                    got = os.path.getsize(dest_tmp)
                    if got < min_bytes:
                        raise IOError(
                            "下载文件仅 %d 字节，预期至少 %d 字节，"
                            "可能下到了错误页/拦截页" % (got, min_bytes))
                os.replace(dest_tmp, dest)
                result["ok"] = True
            except Exception as exc:  # noqa: BLE001 - 任何失败都透传给主线程
                result["error"] = exc

        th = threading.Thread(target=work, daemon=True)
        th.start()

        last_size = -1
        last_change = time.time()
        while th.is_alive():
            try:
                size = os.path.getsize(dest_tmp)
            except OSError:
                size = 0
            if size != last_size:
                last_size = size
                last_change = time.time()
            elif time.time() - last_change > stall_seconds:
                try:
                    if os.path.exists(dest_tmp):
                        os.remove(dest_tmp)
                except OSError:
                    pass
                raise RuntimeError(
                    "下载 %s 停滞超过 %d 秒（已下载 %.0f MB），已放弃本次执行。\n"
                    "可能是网络/代理半死连接。请检查网络或设置代理后重试；"
                    "或手动把文件放到：\n  %s"
                    % (os.path.basename(dest), int(stall_seconds),
                       size / 1e6, os.path.dirname(dest)))
            time.sleep(5)

        if "error" in result:
            try:
                if os.path.exists(dest_tmp):
                    os.remove(dest_tmp)
            except OSError:
                pass
            raise RuntimeError(
                "下载 %s 失败：%s\n请检查网络/代理，或手动把文件放到：\n  %s"
                % (os.path.basename(dest), result["error"], os.path.dirname(dest)))
    return dest
