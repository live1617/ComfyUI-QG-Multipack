# -*- coding: utf-8 -*-
"""模型自动下载的单元验证（不真下 441MB、不污染真实模型目录）。

机制照搬 test_photokit_geometry.py：把插件根当包加载，相对导入才能成立。

覆盖：
  [1] available_choices 含 4 个预置名
  [2] resolve：本地无 + 预置名 -> 触发下载 -> 落到 <tmp>/background_removal/{save_as}
  [3] resolve：本地已有 -> 直接用，不触发下载
  [4] resolve：既不在 discover 也不在预置 -> 返回 None
  [5] http_download：本地 server 小文件落盘且字节一致
  [6] http_download：server 卡死 -> stall_seconds 后抛 RuntimeError
  [7] _download_face_landmarker：mock http_download -> 落到 <tmp>/mediapipe/face_landmarker.task

所有下载都指向临时目录，真实 models/ 不受影响。
"""
import importlib
import importlib.util
import os
import sys
import threading
import shutil
import socket
import tempfile

import socketserver
import http.server

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
FAILED = 0


def check(label, ok, detail=""):
    global FAILED
    if not ok:
        FAILED += 1
    print(f"  {label:<56}{'PASS' if ok else 'FAIL'}  {detail if not ok else ''}")


def load_package():
    name = "qgmp_dl_test"
    init = os.path.join(PKG, "__init__.py")
    if not os.path.isfile(init):
        raise SystemExit("找不到 %s，路径给错了？" % init)
    spec = importlib.util.spec_from_file_location(
        name, init, submodule_search_locations=[PKG])
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[name] = pkg
    spec.loader.exec_module(pkg)
    return name


class _StallHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if getattr(self.server, "stall", False):
            import time
            time.sleep(3600)  # 接受连接但故意不发任何数据
        body = getattr(self.server, "payload", b"")
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class _TestServer(socketserver.ThreadingTCPServer):
    # 卡死场景的 handler 会长时间 sleep；让请求线程成为 daemon，
    # 进程才能正常退出，不被挂住的请求线程拖死。
    daemon_threads = True
    allow_reuse_address = True


def run_server(payload=b"", stall=False):
    """起一个本地 http server，返回 (url, server)。端口由系统分配。"""
    srv = _TestServer(("127.0.0.1", 0), _StallHandler)
    srv.payload = payload
    srv.stall = stall
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return "http://127.0.0.1:%d/fake.onnx" % port, srv


def main():
    global FAILED
    pkg_name = load_package()
    MM = importlib.import_module(pkg_name + "._matte_models")
    FH = importlib.import_module(pkg_name + "._face_helpers")
    DL = importlib.import_module(pkg_name + "._model_download")

    # 把模型根指向临时目录，避免污染真实 models/
    orig_root = MM._models_root
    tmp_root = tempfile.mkdtemp(prefix="qgmp_root_")
    MM._models_root = lambda: tmp_root

    try:
        print("\n[1] available_choices 含 4 个预置名")
        choices = MM.available_choices()
        for name in MM.PRESET_MODELS:
            check("预置名在 choices: %s" % name, name in choices)
        check("available_choices 非空 list", isinstance(choices, list) and bool(choices))

        print("\n[2] resolve：本地无 + 预置名 -> 触发下载落到 <tmp>/background_removal/{save_as}")
        payload = b"\x00ONNXfake\x01" * 100  # ~1.2KB
        url, srv = run_server(payload)
        name = "modnet_photographic_portrait_matting"
        expected_save = MM.PRESET_MODELS[name]["save_as"]
        orig_url = MM.PRESET_MODELS[name]["url"]
        orig_hint = MM.PRESET_MODELS[name]["size_hint"]
        try:
            MM.PRESET_MODELS[name]["url"] = url
            MM.PRESET_MODELS[name]["size_hint"] = "1KB"  # 下界 ~512B，1.2KB 载荷能过
            dest = MM.resolve(name)
            ok = dest is not None and os.path.basename(dest) == expected_save
            check("resolve 返回落点路径", ok, str(dest))
            ok2 = dest and os.path.exists(dest) and os.path.getsize(dest) == len(payload)
            check("落盘文件字节一致", ok2)
            ok3 = "background_removal" in dest.replace("\\", "/")
            check("落点在 <tmp>/background_removal/", ok3, dest or "")
        finally:
            MM.PRESET_MODELS[name]["url"] = orig_url
            MM.PRESET_MODELS[name]["size_hint"] = orig_hint
            srv.shutdown(); srv.server_close()

        print("\n[3] resolve：本地已有 -> 直接用，不触发下载")
        called = {"n": 0}

        def boom(*a, **k):
            called["n"] += 1
            raise AssertionError("不应触发下载")

        orig_http = DL.http_download
        orig_hint3 = MM.PRESET_MODELS[name]["size_hint"]
        DL.http_download = boom
        try:
            # 沿用 [2] 落地的 1.2KB 文件；把下界压到 1KB 以内，使其被认作"已就绪"。
            MM.PRESET_MODELS[name]["size_hint"] = "1KB"
            dest2 = MM.resolve(name)
            check("本地已有直接返回且未触发下载",
                  dest2 is not None and called["n"] == 0,
                  "download calls=%d" % called["n"])
        finally:
            DL.http_download = orig_http
            MM.PRESET_MODELS[name]["size_hint"] = orig_hint3

        print("\n[4] resolve：非预置且本地无 -> 返回 None")
        check("resolve 未知名返回 None", MM.resolve("完全不存在的模型_xyz") is None)

        print("\n[5] http_download：本地 server 小文件落盘且字节一致")
        payload2 = os.urandom(2048)
        url2, srv2 = run_server(payload2)
        out_dir = tempfile.mkdtemp(prefix="qgmp_out_")
        out = os.path.join(out_dir, "x.onnx")
        try:
            DL.http_download(url2, out, stall_seconds=30)
            ok = os.path.exists(out) and open(out, "rb").read() == payload2
            check("http_download 落盘且字节一致", ok)
        finally:
            srv2.shutdown(); srv2.server_close()
            shutil.rmtree(out_dir, ignore_errors=True)

        print("\n[6] http_download：server 卡死 -> stall_seconds 后抛 RuntimeError")
        url3, srv3 = run_server(b"", stall=True)
        out3_dir = tempfile.mkdtemp(prefix="qgmp_out3_")
        out3 = os.path.join(out3_dir, "y.onnx")
        raised = False
        try:
            DL.http_download(url3, out3, stall_seconds=2)
        except RuntimeError as e:
            raised = True
            check("卡死时抛 RuntimeError 且含停滞字样",
                  "停滞" in str(e), str(e)[:40])
        except Exception as e:
            raised = True
            check("卡死时抛错类型", False,
                  "抛了 %s 而非 RuntimeError" % type(e).__name__)
        finally:
            srv3.shutdown(); srv3.server_close()
            shutil.rmtree(out3_dir, ignore_errors=True)
        if not raised:
            check("卡死时应抛 RuntimeError", False, "什么都没抛")

        print("\n[7] _download_face_landmarker：mock http_download -> 落到 <tmp>/mediapipe/")
        tmp_mp = tempfile.mkdtemp(prefix="qgmp_mediapipe_")
        captured = {}
        orig_cand = FH._model_candidates

        def fake_dl(u, d, stall_seconds=120, min_bytes=None):
            captured["url"] = u
            captured["dest"] = d
            # 写够大的文件，模拟真实 3.6MB 权重，过 >100000 的完整性校验
            with open(d, "wb") as f:
                f.write(b"\x00TASKfake" * 20000)
            return d

        FH._model_candidates = lambda: [tmp_mp]
        orig_http2 = DL.http_download
        DL.http_download = fake_dl
        try:
            res = FH._download_face_landmarker()
            ok = res is not None and os.path.basename(res) == "face_landmarker.task"
            check("_download_face_landmarker 返回 .task 路径", ok, str(res))
            ok2 = res and "mediapipe" in res.replace("\\", "/")
            check("落点在 <tmp>/mediapipe/", ok2, res or "")
            ok3 = "storage.googleapis.com" in captured.get("url", "")
            check("下载地址是官方 mediapipe 源", ok3, captured.get("url", "")[:50])
        finally:
            DL.http_download = orig_http2
            FH._model_candidates = orig_cand
            shutil.rmtree(tmp_mp, ignore_errors=True)

        print("\n[8] http_download：过小文件（疑似错误页）被 min_bytes 拒绝")
        payload_small = b"<html>404 Not Found</html>"
        url_small, srv_small = run_server(payload_small)
        out8_dir = tempfile.mkdtemp(prefix="qgmp_out8_")
        out8 = os.path.join(out8_dir, "x.onnx")
        raised8 = False
        try:
            try:
                DL.http_download(url_small, out8, stall_seconds=30, min_bytes=1024)
            except RuntimeError:
                raised8 = True
            check("过小文件被 min_bytes 拒并抛 RuntimeError", raised8)
            if not raised8:
                check("过小文件应抛 RuntimeError", False, "什么都没抛")
        finally:
            srv_small.shutdown(); srv_small.server_close()
            shutil.rmtree(out8_dir, ignore_errors=True)
    finally:
        MM._models_root = orig_root
        shutil.rmtree(tmp_root, ignore_errors=True)

    print("\n" + ("全部通过" if FAILED == 0 else "有 %d 项失败" % FAILED))
    raise SystemExit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
