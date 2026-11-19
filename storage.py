import sys
import os
import json
import math
import wave
import struct
import shutil

from PyQt6.QtCore import Qt, QPoint, QRect, QSize, QByteArray, QBuffer, QIODevice
from PyQt6.QtGui import QPixmap, QIcon, QImageReader

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    import winreg
    HAS_WIN32 = True
    HAS_WINREG = True
else:
    ctypes = None
    wintypes = None
    winreg = None
    HAS_WIN32 = False
    HAS_WINREG = False

VIDEO_EXTS = {
    '.mp4', '.m4v', '.mov', '.mkv', '.avi', '.wmv',
    '.webm', '.flv', '.ts', '.mts', '.m2ts', '.mpg', '.mpeg', '.3gp'
}
AUDIO_EXTS = {
    '.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.wma', '.opus'
}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.gif', '.tiff', '.jfif'}
SUPPORTED_EXTS = VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS

STARTUP_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_APP_NAME = "MinimalMediaPlayer_AutoPlay"

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

LOGIN_URLS = {
    "NAVER": "https://nid.naver.com/nidlogin.login",
    "SOOP": "https://login.sooplive.com/app/index.php",
    "GOOGLE": "https://accounts.google.com/ServiceLogin?service=youtube",
}

GWL_STYLE = -16
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000

DEFAULT_SETTINGS = {
    "volume": 70,
    "is_muted": False,
    "playback_rate": 1.0,
    "custom_seek_sec": 89,
    "transition_mode": 4,
    "image_slideshow_interval": 5000,
    "is_shuffle": False,
    "is_repeat_all": False,
    "preferred_quality": "best",
    "always_on_top": False,
    "panels": {
        "chat": {"mode": "right", "dock_width": 360, "bottom_height": 600},
        "streamer": {"mode": "right", "dock_width": 330, "bottom_height": 600},
        "playlist": {"mode": "right", "dock_width": 320, "bottom_height": 600},
    },
}


def get_base_dir() -> str:
    """실행 파일(.exe) 또는 스크립트(.py)의 기본 폴더 반환"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_data_root_dir() -> str:
    """
    PyInstaller 재빌드 시 dist/MinimalMediaPlayer 폴더가 초기화되거나
    web_profile 잠금(PermissionError)이 발생하는 것을 방지하기 위해,
    dist 하위에서 실행 중이면 상위 프로젝트 루트 폴더를 데이터 저장소로 사용합니다.
    """
    base = get_base_dir()
    parent1 = os.path.dirname(base)
    if os.path.basename(parent1).lower() in ("dist", "dist_v2", "dist_new"):
        project_root = os.path.dirname(parent1)
        if os.path.isdir(project_root):
            return project_root
    return base


def convert_png_to_ico_pure_qt(png_path: str, ico_path: str) -> bool:
    """외부 PIL(Pillow) 없이 순수 PyQt6 + 표준 struct만으로 멀티 해상도 .ico 파일 생성"""
    pix = QPixmap(png_path)
    if pix.isNull():
        return False

    sizes = [16, 24, 32, 48, 64, 128, 256]
    png_payloads = []
    for sz in sizes:
        scaled = pix.scaled(
            QSize(sz, sz),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        scaled.save(buf, "PNG")
        buf.close()
        raw_bytes = bytes(ba)
        if raw_bytes:
            png_payloads.append((sz, raw_bytes))

    if not png_payloads:
        return False

    try:
        os.makedirs(os.path.dirname(ico_path), exist_ok=True)
        header = struct.pack("<HHH", 0, 1, len(png_payloads))
        offset = 6 + 16 * len(png_payloads)
        dir_entries = []
        for sz, data in png_payloads:
            b_sz = 0 if sz >= 256 else sz
            entry = struct.pack(
                "<BBBBHHII",
                b_sz, b_sz, 0, 0, 1, 32, len(data), offset
            )
            dir_entries.append(entry)
            offset += len(data)

        with open(ico_path, "wb") as f:
            f.write(header)
            for entry in dir_entries:
                f.write(entry)
            for _, data in png_payloads:
                f.write(data)
        return True
    except Exception:
        return False


def resolve_app_icon_path() -> str:
    """
    실행 폴더, PyInstaller _MEIPASS, 상위 프로젝트 폴더(../../assets)를 모두 탐색하여
    아이콘을 찾고, player_icon.ico가 없으면 자동 생성합니다.
    """
    base = get_base_dir()
    data_root = get_data_root_dir()

    search_dirs = [
        os.path.join(data_root, "assets"),
        os.path.join(base, "assets"),
        data_root,
        base,
    ]
    if hasattr(sys, "_MEIPASS"):
        search_dirs.append(os.path.join(sys._MEIPASS, "assets"))
        search_dirs.append(sys._MEIPASS)

    icon_names = (
        "player_icon.ico",
        "player_icon_2.png",
        "player_icon.png",
        "icon.ico",
        "icon.png",
    )

    found_path = ""
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for name in icon_names:
            cand = os.path.join(d, name)
            if os.path.isfile(cand):
                found_path = cand
                break
        if found_path:
            break

    if not found_path:
        return ""

    target_dirs = {os.path.dirname(found_path), os.path.join(data_root, "assets")}
    for t_dir in target_dirs:
        ico_target = os.path.join(t_dir, "player_icon.ico")
        if not os.path.exists(ico_target) and found_path.lower().endswith(".png"):
            convert_png_to_ico_pure_qt(found_path, ico_target)

    preferred_ico = os.path.join(data_root, "assets", "player_icon.ico")
    if os.path.isfile(preferred_ico):
        return preferred_ico
    return found_path


def build_multi_size_qicon(icon_path: str) -> QIcon:
    """트레이(16x16), 제목줄(32x32), 작업표시줄(48x48~256x256) 모든 해상도에서 선명한 QIcon 생성"""
    if not icon_path or not os.path.isfile(icon_path):
        return QIcon()
    icon = QIcon(icon_path)
    pix = QPixmap(icon_path)
    if not pix.isNull():
        for sz in (16, 24, 32, 48, 64, 128, 256):
            scaled = pix.scaled(
                QSize(sz, sz),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            icon.addPixmap(scaled)
    return icon


def load_auto_oriented_pixmap(image_path: str) -> QPixmap:
    """EXIF Orientation 메타데이터를 자동 반영하여 이미지 QPixmap 로드"""
    reader = QImageReader(image_path)
    reader.setAutoTransform(True)
    img = reader.read()
    if not img.isNull():
        return QPixmap.fromImage(img)
    return QPixmap(image_path)


def format_ms_to_time(ms: int) -> str:
    """밀리초(ms)를 HH:MM:SS 또는 MM:SS 문자열로 변환"""
    total_sec = max(0, int(ms // 1000))
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    seconds = total_sec % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def safe_save_json(file_path: str, data):
    """데이터 유실 방지를 위해 기존 파일을 .bak으로 백업한 뒤 임시 파일을 거쳐 안전하게 저장"""
    try:
        parent_dir = os.path.dirname(os.path.abspath(file_path))
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        if os.path.exists(file_path) and os.path.getsize(file_path) > 2:
            shutil.copy2(file_path, file_path + ".bak")
        tmp_path = file_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, file_path)
    except Exception as e:
        print(f"[JSON 안전 저장 오류 ({file_path})] {e}")


def safe_load_json(file_path: str, default_val):
    """메인 JSON 파일이 손상되었거나 비어 있을 경우 .bak 백업 파일에서 자동 복구"""
    for candidate in (file_path, file_path + ".bak"):
        if os.path.exists(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data is not None:
                        return data
            except Exception:
                pass
    return default_val


def _deep_merge_settings(defaults: dict, loaded: dict) -> dict:
    merged = {}
    for k, v in defaults.items():
        if isinstance(v, dict):
            sub = loaded.get(k) if isinstance(loaded.get(k), dict) else {}
            merged[k] = _deep_merge_settings(v, sub)
        else:
            merged[k] = loaded.get(k, v)
    return merged


def load_app_settings(file_path: str) -> dict:
    """settings.json에서 사용자 설정을 안전하게 불러오며 누락 키는 기본값으로 보완"""
    raw = safe_load_json(file_path, {})
    if not isinstance(raw, dict):
        raw = {}
    return _deep_merge_settings(DEFAULT_SETTINGS, raw)


def save_app_settings(file_path: str, settings: dict):
    """사용자 설정을 settings.json에 안전하게 저장"""
    safe_save_json(file_path, settings)


def compute_magnetic_snap(moving_rect: QRect, target_rects: list, snap_dist: int = 18) -> QPoint:
    """포토샵 스타일 마그네틱 스냅 엔진"""
    x, y = moving_rect.left(), moving_rect.top()
    w, h = moving_rect.width(), moving_rect.height()

    best_dx = snap_dist + 1
    best_dy = snap_dist + 1
    snapped_x = x
    snapped_y = y

    for r in target_rects:
        if not (y + h < r.top() - 60 or y > r.bottom() + 60):
            x_candidates = [
                (r.right() + 1, x),
                (r.left() - w - 1, x),
                (r.left(), x),
                (r.right() - w + 1, x),
            ]
            for target_x, cur_x in x_candidates:
                dist = abs(target_x - cur_x)
                if dist < best_dx:
                    best_dx = dist
                    snapped_x = target_x

        if not (x + w < r.left() - 60 or x > r.right() + 60):
            y_candidates = [
                (r.bottom() + 1, y),
                (r.top() - h - 1, y),
                (r.top(), y),
                (r.bottom() - h + 1, y),
            ]
            for target_y, cur_y in y_candidates:
                dist = abs(target_y - cur_y)
                if dist < best_dy:
                    best_dy = dist
                    snapped_y = target_y

    return QPoint(snapped_x, snapped_y)


def ensure_default_transition_sound(sound_path: str):
    if os.path.exists(sound_path):
        return
    try:
        os.makedirs(os.path.dirname(sound_path), exist_ok=True)
        sample_rate = 44100
        duration = 0.08
        num_samples = int(sample_rate * duration)
        with wave.open(sound_path, 'w') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            for i in range(num_samples):
                t = i / sample_rate
                freq = 600 * math.exp(-t * 35) + 120
                envelope = math.exp(-t * 45)
                val = int(32767.0 * 0.25 * envelope * math.sin(2.0 * math.pi * freq * t))
                wav_file.writeframesraw(struct.pack('<h', val))
    except Exception:
        pass
