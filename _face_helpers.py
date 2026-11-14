"""Find the face, and the two eyes that define "level".

Two backends, because they fail in different places. mediapipe's FaceLandmarker
is the accurate one: 478 points including the iris, so the eye line is measured
between iris centres rather than guessed from an eye-shaped blob. It needs a
3.6 MB .task file and a working install. OpenCV's bundled Haar cascade needs
neither but only runs on OpenCV 4.x (5.0 ships an empty ``cv2/data``) and is
unreliable on a profile or a small face.

Neither is required for the node to load. When both are missing the caller is
told which one failed and why, and fits the picture into the target without a
face - a node that disappears because of a missing optional dependency is worse
than one that admits it cannot see.
"""

from __future__ import annotations

import math
import os
import threading

import numpy as np

_MP_STATE = {"tried": False, "landmarker": None, "reason": ""}
_MP_LOCK = threading.Lock()
# 非默认置信度的 landmarker 缓存（face_align 节点把「面部置信度」真正接到
# FaceLandmarkerOptions 上，其它节点走默认 0.3 不受影响）
_MP_EXTRA = {}

_HAAR = {"tried": False, "face": None, "eye": None, "reason": ""}


class Face:
    """One detected face, in source-image pixels.

    ``box`` is the outline bounding box (forehead to chin, ear to ear).
    ``eye_a``/``eye_b`` are ordered left-to-right in the picture, whatever the
    detector calls them - mediapipe's "left eye" is the subject's left, which is
    on the right of the frame, and feeding that order to atan2 flips the angle
    to nearly 180 degrees.
    """

    def __init__(self, box, eye_a, eye_b, source, contour=None):
        self.x0, self.y0, self.x1, self.y1 = (float(v) for v in box)
        first = (float(eye_a[0]), float(eye_a[1]))
        second = (float(eye_b[0]), float(eye_b[1]))
        if first[0] > second[0]:
            first, second = second, first
        self.eye_a = first
        self.eye_b = second
        self.source = source
        self.contour = contour

    @property
    def width(self):
        return self.x1 - self.x0

    @property
    def height(self):
        return self.y1 - self.y0

    @property
    def center(self):
        return ((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)

    @property
    def eye_center(self):
        return ((self.eye_a[0] + self.eye_b[0]) / 2.0,
                (self.eye_a[1] + self.eye_b[1]) / 2.0)

    @property
    def tilt(self):
        """Eye line angle in radians, measured from the left eye to the right."""
        return math.atan2(self.eye_b[1] - self.eye_a[1],
                          self.eye_b[0] - self.eye_a[0])

    def scaled(self, fx, fy):
        """The same face with coordinates multiplied by ``fx`` / ``fy``.

        Detection often runs on a smaller copy for speed; this maps the answer
        back without re-running anything.
        """
        box = (self.x0 * fx, self.y0 * fy, self.x1 * fx, self.y1 * fy)
        eye_a = (self.eye_a[0] * fx, self.eye_a[1] * fy)
        eye_b = (self.eye_b[0] * fx, self.eye_b[1] * fy)
        contour = None
        if self.contour:
            contour = [(p[0] * fx, p[1] * fy) for p in self.contour]
        return Face(box, eye_a, eye_b, self.source, contour)

    def __repr__(self):
        return ("Face(%s, box=%.0fx%.0f at %.0f,%.0f, tilt=%.2f deg)"
                % (self.source, self.width, self.height, self.x0, self.y0,
                   math.degrees(self.tilt)))


# --------------------------------------------------------------- mediapipe ---

def _model_candidates():
    """Where the .task file may live, most specific first."""
    out = []
    try:
        import folder_paths
        # 用户可能把 mediapipe 配进了 extra_model_paths.yaml；没配时这个
        # 调用会抛 KeyError，忽略即可。
        try:
            for path in folder_paths.get_folder_paths("mediapipe"):
                if path:
                    out.append(path)
        except Exception:                                # noqa: BLE001
            pass
        out.append(os.path.join(folder_paths.models_dir, "mediapipe"))
    except Exception:                                    # noqa: BLE001
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    # <ComfyUI>/custom_nodes/<pack>/nodes -> <ComfyUI>/models
    out.append(os.path.join(here, "..", "..", "..", "models", "mediapipe"))
    out.append(os.path.join(os.getcwd(), "models", "mediapipe"))
    seen, unique = set(), []
    for path in (os.path.abspath(p) for p in out):
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def find_model():
    for directory in _model_candidates():
        path = os.path.join(directory, "face_landmarker.task")
        if os.path.exists(path) and os.path.getsize(path) > 100000:
            return path
    return None


def _mp_index_sets():
    """Landmark index groups, read from mediapipe's own connection tables.

    Hard-coding the 36 oval indices or the iris range would break silently on
    the next model revision; the tables travel with the package.
    """
    from mediapipe.tasks.python.vision import FaceLandmarksConnections as C

    def idx(conn):
        return sorted({c.start for c in conn} | {c.end for c in conn})

    return {"oval": idx(C.FACE_LANDMARKS_FACE_OVAL),
            "eye_left": idx(C.FACE_LANDMARKS_LEFT_EYE),
            "eye_right": idx(C.FACE_LANDMARKS_RIGHT_EYE),
            "iris_left": idx(C.FACE_LANDMARKS_LEFT_IRIS),
            "iris_right": idx(C.FACE_LANDMARKS_RIGHT_IRIS)}


_MP_SETS = None


def mediapipe_ready():
    return _load_mediapipe() is not None


def _build_landmarker(model, confidence):
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import (FaceLandmarker,
                                               FaceLandmarkerOptions,
                                               RunningMode)
    options = FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model),
        running_mode=RunningMode.IMAGE,
        num_faces=5,
        min_face_detection_confidence=confidence)
    return FaceLandmarker.create_from_options(options)


def _load_mediapipe(confidence=None):
    """Build (once) the landmarker, or return None with a reason in _MP_STATE.

    ``confidence`` 传 None / 0.3 走默认缓存；其它值按置信度另建实例缓存
    （模型文件与 index 集合共享，只是检测阈值不同）。
    """
    global _MP_SETS
    try:
        confidence = 0.3 if confidence is None else float(confidence)
    except (TypeError, ValueError):
        confidence = 0.3
    with _MP_LOCK:
        if confidence != 0.3:
            if confidence in _MP_EXTRA:
                return _MP_EXTRA[confidence]
            base = _load_mediapipe_locked()
            if base is None:
                return None
            try:
                model = find_model()
                _MP_EXTRA[confidence] = _build_landmarker(model, confidence)
            except Exception as exc:                     # noqa: BLE001
                print("[QG-Face] 按置信度 %s 重建 landmarker 失败：%s"
                      % (confidence, exc))
                _MP_EXTRA[confidence] = base
            return _MP_EXTRA[confidence]
        return _load_mediapipe_locked()


def _load_mediapipe_locked():
    global _MP_SETS
    if _MP_STATE["tried"]:
        return _MP_STATE["landmarker"]
    _MP_STATE["tried"] = True
    try:
        import mediapipe as mp  # noqa: F401
    except Exception as exc:                             # noqa: BLE001
        _MP_STATE["reason"] = "mediapipe unavailable (%s)" % exc
        return None

    model = find_model()
    if model is None:
        _MP_STATE["reason"] = (
            "mediapipe model missing - put face_landmarker.task in "
            "models/mediapipe/ (falling back to Haar)")
        return None

    try:
        _MP_STATE["landmarker"] = _build_landmarker(model, 0.3)
        _MP_SETS = _mp_index_sets()
    except Exception as exc:                             # noqa: BLE001
        _MP_STATE["reason"] = "mediapipe failed to start (%s)" % exc
        _MP_STATE["landmarker"] = None
    return _MP_STATE["landmarker"]


def _mean_point(points, indices):
    usable = [i for i in indices if i < len(points)]
    if not usable:
        return None
    return (sum(points[i][0] for i in usable) / len(usable),
            sum(points[i][1] for i in usable) / len(usable))


def _download_face_landmarker():
    """找不到 .task 时按需下载到第一个候选目录。失败返回 None（继续 Haar 回退）。"""
    candidates = _model_candidates()
    if not candidates:
        return None
    dest_dir = candidates[0]
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "face_landmarker.task")
    if os.path.exists(dest) and os.path.getsize(dest) > 100000:
        return dest
    url = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
           "face_landmarker/float16/1/face_landmarker.task")
    print("[QG-Face] 未找到 face_landmarker.task，按需下载（约 3.6MB）：%s" % url)
    try:
        from ._model_download import http_download
        http_download(url, dest, stall_seconds=120, min_bytes=100000)
    except Exception as exc:  # noqa: BLE001
        print("[QG-Face] 自动下载失败：%s（回退到 OpenCV Haar）" % exc)
        return None
    if os.path.exists(dest) and os.path.getsize(dest) > 100000:
        return dest
    return None


def _detect_mediapipe(rgb, pick, confidence=None):
    landmarker = _load_mediapipe(confidence)
    if landmarker is None and "model missing" in (_MP_STATE.get("reason") or ""):
        # 用到人脸检测时才按需拉取 face_landmarker.task，再试一次；
        # 状态查询（mediapipe_ready/backend_status）不会走到这里，避免提前下载。
        if _download_face_landmarker() is not None:
            _MP_STATE["tried"] = False
            _MP_STATE["landmarker"] = None
            landmarker = _load_mediapipe()
    if landmarker is None:
        return None
    sets = _MP_SETS or _mp_index_sets()

    import mediapipe as mp
    height, width = rgb.shape[:2]
    image = mp.Image(image_format=mp.ImageFormat.SRGB,
                     data=np.ascontiguousarray(rgb))
    result = landmarker.detect(image)
    if not result.face_landmarks:
        return None

    faces = []
    for landmarks in result.face_landmarks:
        points = [(lm.x * width, lm.y * height) for lm in landmarks]
        oval = [points[i] for i in sets["oval"] if i < len(points)]
        if not oval:
            continue
        box = (min(p[0] for p in oval), min(p[1] for p in oval),
               max(p[0] for p in oval), max(p[1] for p in oval))

        # Iris centres when the model provides them; the eyelid corners are a
        # reasonable stand-in otherwise, just less centred.
        left = _mean_point(points, sets["iris_left"]) or _mean_point(points, sets["eye_left"])
        right = _mean_point(points, sets["iris_right"]) or _mean_point(points, sets["eye_right"])
        if left is None or right is None:
            continue
        faces.append(Face(box, left, right, "mediapipe", oval))

    return _pick(faces, pick, (width / 2.0, height / 2.0))


# -------------------------------------------------------------------- haar ---

def _load_haar():
    if _HAAR["tried"]:
        return _HAAR["face"]
    _HAAR["tried"] = True
    try:
        import cv2
        base = cv2.data.haarcascades
        face_xml = os.path.join(base, "haarcascade_frontalface_default.xml")
        eye_xml = os.path.join(base, "haarcascade_eye.xml")
        # The directory can exist and be empty: OpenCV 5.0 stopped shipping the
        # cascades, and a classifier loaded from a missing file is an empty
        # object that detects nothing rather than an error. Check the file.
        if not os.path.exists(face_xml):
            _HAAR["reason"] = ("opencv %s has no bundled cascades (cv2/data is "
                               "empty) - use mediapipe instead"
                               % cv2.__version__)
            return None
        face = cv2.CascadeClassifier(face_xml)
        if face.empty():
            _HAAR["reason"] = "haarcascade_frontalface_default.xml failed to load"
            return None
        _HAAR["face"] = face
        eye = cv2.CascadeClassifier(eye_xml)
        _HAAR["eye"] = None if eye.empty() else eye
    except Exception as exc:                             # noqa: BLE001
        _HAAR["reason"] = "opencv unavailable (%s)" % exc
        _HAAR["face"] = None
    return _HAAR["face"]


def haar_ready():
    return _load_haar() is not None


def _haar_eyes(gray, x, y, w, h):
    """Both eye centres from the eye cascade, or None when it is not sure."""
    cascade = _HAAR.get("eye")
    if cascade is None:
        return None
    # Search the upper half only: the mouth and collar produce false positives
    # that are much wider than an eye.
    roi = gray[int(y):int(y + h * 0.6), int(x):int(x + w)]
    if roi.size == 0:
        return None
    try:
        found = cascade.detectMultiScale(roi, scaleFactor=1.1, minNeighbors=4,
                                         minSize=(max(8, int(w * 0.12)),) * 2)
    except Exception:                                    # noqa: BLE001
        return None
    if len(found) < 2:
        return None
    boxes = sorted(found, key=lambda b: -b[2])[:4]
    best = None
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            ax = boxes[i][0] + boxes[i][2] / 2.0
            ay = boxes[i][1] + boxes[i][3] / 2.0
            bx = boxes[j][0] + boxes[j][2] / 2.0
            by = boxes[j][1] + boxes[j][3] / 2.0
            if abs(bx - ax) < w * 0.25:
                continue
            score = abs(by - ay) + abs((ay + by) / 2.0 - h * 0.35) * 0.5
            if best is None or score < best[0]:
                best = (score, (ax + x, ay + y), (bx + x, by + y))
    if best is None:
        return None
    return best[1], best[2]


def _detect_haar(rgb, pick):
    cascade = _load_haar()
    if cascade is None:
        return None
    import cv2
    height, width = rgb.shape[:2]
    gray = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2GRAY)
    try:
        boxes = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                         minSize=(40, 40))
    except Exception:                                    # noqa: BLE001
        return None
    faces = []
    for x, y, w, h in boxes:
        eyes = _haar_eyes(gray, x, y, w, h)
        if eyes is None:
            # No eyes means no tilt and no eye line. Estimating from the box is
            # still better than refusing the frame: 40% down the box, a quarter
            # either side of centre.
            cy = y + h * 0.40
            eyes = ((x + w * 0.30, cy), (x + w * 0.70, cy))
        faces.append(Face((x, y, x + w, y + h), eyes[0], eyes[1], "haar"))
    return _pick(faces, pick, (width / 2.0, height / 2.0))


# ------------------------------------------------------------------ public ---

def _pick(faces, pick, image_center):
    if not faces:
        return None
    if str(pick) == "largest":
        return max(faces, key=lambda f: f.width * f.height)

    def dist(face):
        cx, cy = face.center
        return (cx - image_center[0]) ** 2 + (cy - image_center[1]) ** 2

    return min(faces, key=dist)


def detect(rgb, pick="center", confidence=None):
    """Detect one face in an RGB uint8 array. Returns ``Face`` or ``None``."""
    if rgb is None or rgb.size == 0:
        return None
    face = _detect_mediapipe(rgb, pick, confidence)
    if face is not None:
        return face
    return _detect_haar(rgb, pick)


def backend_status():
    """Human-readable line about which backend will be used, for the log."""
    if _load_mediapipe() is not None:
        return "mediapipe"
    mp_reason = _MP_STATE.get("reason") or "mediapipe unavailable"
    if _load_haar() is not None:
        return "haar (%s)" % mp_reason
    return "none (%s; %s)" % (mp_reason, _HAAR.get("reason") or "opencv unavailable")
