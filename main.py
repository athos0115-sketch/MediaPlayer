import sys
import os
import re

# 0. Python 3.14 / 3.15 환경에서 urllib3 / requests / streamlink / yt-dlp 호환성 버그 자동 패치
try:
    import urllib3.util.url as _u3_url
    if hasattr(_u3_url, "_PERCENT_RE") and not hasattr(_u3_url._PERCENT_RE, "sub"):
        _u3_url._PERCENT_RE = re.compile(r"%[a-fA-F0-9]{2}")
except Exception:
    pass

# 1. Qt Multimedia FFmpeg 백엔드 강제 지정 (MP4 / MP3 / FLAC / H.264 / HEVC / HLS 완벽 재생 보장)
os.environ["QT_MEDIA_BACKEND"] = "ffmpeg"
# FFmpeg HLS 스트리밍 시 불필요한 Packet corrupt 경고 로그 억제
os.environ["AV_LOG_FORCE_NOCOLOR"] = "1"

# 2. Chromium / WebEngine 하드웨어 가속 및 백그라운드 타이머 절전 해제(실시간 채팅 끊김 방지)
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--enable-gpu-rasterization "
    "--ignore-gpu-blocklist "
    "--autoplay-policy=no-user-gesture-required "
    "--disable-background-timer-throttling "
    "--disable-renderer-backgrounding "
    "--disable-backgrounding-occluded-windows "
    "--enable-features=WebRTC-H264WithOpenH264FFmpeg"
)

import json
import math
import wave
import struct
import random
import shutil
import urllib.parse
import urllib.request

# Windows DWM 네이티브 스냅, 레지스트리 및 작업표시줄 AppUserModelID 제어용 내장 모듈
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    import winreg
    HAS_WIN32 = True
    HAS_WINREG = True
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Wonjae.MinimalMediaPlayer.Pro.v26"
        )
    except Exception:
        pass
else:
    HAS_WIN32 = False
    HAS_WINREG = False

from natsort import natsorted

# Streamlink 연동
try:
    import streamlink
    HAS_STREAMLINK = True
except ImportError:
    HAS_STREAMLINK = False

# yt-dlp 연동
try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QLabel, QListWidget, QListWidgetItem, QSystemTrayIcon,
    QMenu, QStyle, QLineEdit, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QSizePolicy, QFileDialog, QSlider, QPushButton,
    QDialog, QComboBox, QFormLayout, QMessageBox, QFrame, QInputDialog
)
from PyQt6.QtCore import (
    Qt, QUrl, QTimer, QPoint, QPointF, QRect, QRectF, QEvent,
    QVariantAnimation, QEasingCurve, QThread, pyqtSignal, QSize,
    QByteArray, QBuffer, QIODevice
)
from PyQt6.QtGui import (
    QPixmap, QIcon, QAction, QPainter, QPainterPath,
    QTransform, QColor, QBrush, QPen, QLinearGradient, QPolygonF,
    QCursor, QShortcut, QKeySequence
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QSoundEffect
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import (
    QWebEngineSettings, QWebEngineProfile, QWebEnginePage, QWebEngineScript
)

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

# 3대 플랫폼 로그인 페이지 URL
LOGIN_URLS = {
    "NAVER": "https://nid.naver.com/nidlogin.login",
    "SOOP": "https://login.sooplive.co.kr/app/index.php",
    "GOOGLE": "https://accounts.google.com/ServiceLogin?service=youtube",
}

# Windows API 상수 정의 (64비트 안전 호출용)
GWL_STYLE = -16
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000

# ==============================================================================
# SOOP 본 방송 비파괴(Non-Destructive) 채팅창 풀스크린 오버레이 스크립트
# ==============================================================================
SOOP_CHAT_DOM_MASK_JS = """
(function() {
    if (window.__soopChatMaskInjected) return;
    if (!location.hostname.includes('sooplive') && !location.hostname.includes('afreecatv')) return;
    if (location.hostname.includes('login.')) return;
    window.__soopChatMaskInjected = true;

    const CHAT_SELECTORS = [
        '#chat_area',
        '#chatting_area',
        '#chatting',
        '.chat_area',
        '.chat_box',
        '#webplayer_chat',
        'div[id*="chat_area"]',
        'div[class*="chat_area"]',
        'div[class*="chatting_area"]',
        'aside[class*="chat"]',
        'section[class*="chat"]'
    ];

    function expandSoopChatOverlay() {
        document.querySelectorAll('video, audio').forEach(el => {
            try {
                el.muted = true;
                el.volume = 0;
            } catch (e) {}
        });

        document.body.classList.remove('chat_close', 'close_chat', 'full_screen', 'theater_mode', 'mode_extend');
        const wrap = document.getElementById('webplayer') || document.getElementById('player_wrap');
        if (wrap) wrap.classList.remove('chat_close', 'close_chat', 'mode_extend');

        const openBtn = document.querySelector(
            '.btn_chat_open, #btn_chat_open, button[class*="chat_open"], .chat_open'
        );
        if (openBtn && openBtn.offsetParent !== null) {
            try { openBtn.click(); } catch (e) {}
        }

        let chatEl = null;
        for (const sel of CHAT_SELECTORS) {
            const found = document.querySelector(sel);
            if (found && found.querySelector('ul,ol,div[class*="chat"],textarea,input')) {
                chatEl = found;
                break;
            }
        }
        if (!chatEl) {
            for (const sel of CHAT_SELECTORS) {
                const found = document.querySelector(sel);
                if (found) {
                    chatEl = found;
                    break;
                }
            }
        }
        if (!chatEl) return;

        if (!document.getElementById('__mp_soop_chat_overlay_css__')) {
            const style = document.createElement('style');
            style.id = '__mp_soop_chat_overlay_css__';
            style.textContent = `
                html, body {
                    margin: 0 !important;
                    padding: 0 !important;
                    width: 100vw !important;
                    height: 100vh !important;
                    min-width: 100vw !important;
                    overflow: hidden !important;
                    background: #121216 !important;
                }
                #header, header, .header, #gnb, .gnb, .sidebar, #sidebar,
                .broadcast_information, #footer, footer, .player_ctrlBox, .layer_ad {
                    display: none !important;
                }
                #player_area, .player_area, #video_area, #webplayer_area, #html5_player {
                    position: fixed !important;
                    top: -9999px !important;
                    left: -9999px !important;
                    width: 2px !important;
                    height: 2px !important;
                    opacity: 0.01 !important;
                    pointer-events: none !important;
                    z-index: -1 !important;
                }
            `;
            (document.head || document.documentElement).appendChild(style);
        }

        chatEl.style.setProperty('display', 'flex', 'important');
        chatEl.style.setProperty('flex-direction', 'column', 'important');
        chatEl.style.setProperty('position', 'fixed', 'important');
        chatEl.style.setProperty('top', '0px', 'important');
        chatEl.style.setProperty('left', '0px', 'important');
        chatEl.style.setProperty('right', '0px', 'important');
        chatEl.style.setProperty('bottom', '0px', 'important');
        chatEl.style.setProperty('width', '100vw', 'important');
        chatEl.style.setProperty('height', '100vh', 'important');
        chatEl.style.setProperty('max-width', '100vw', 'important');
        chatEl.style.setProperty('max-height', '100vh', 'important');
        chatEl.style.setProperty('margin', '0px', 'important');
        chatEl.style.setProperty('padding', '0px', 'important');
        chatEl.style.setProperty('z-index', '2147483647', 'important');
        chatEl.style.setProperty('visibility', 'visible', 'important');
        chatEl.style.setProperty('opacity', '1', 'important');
        chatEl.style.setProperty('background-color', '#121216', 'important');

        let p = chatEl.parentElement;
        while (p && p !== document.body && p !== document.documentElement) {
            const cs = window.getComputedStyle(p);
            if (cs.display === 'none') {
                p.style.setProperty('display', 'block', 'important');
            }
            if (cs.transform && cs.transform !== 'none') {
                p.style.setProperty('transform', 'none', 'important');
            }
            if (cs.filter && cs.filter !== 'none') {
                p.style.setProperty('filter', 'none', 'important');
            }
            if (cs.backdropFilter && cs.backdropFilter !== 'none') {
                p.style.setProperty('backdrop-filter', 'none', 'important');
            }
            p.style.setProperty('overflow', 'visible', 'important');
            p.style.setProperty('visibility', 'visible', 'important');
            p.style.setProperty('opacity', '1', 'important');
            p.style.setProperty('z-index', 'auto', 'important');
            p = p.parentElement;
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', expandSoopChatOverlay);
    } else {
        expandSoopChatOverlay();
    }

    const obs = new MutationObserver(expandSoopChatOverlay);
    obs.observe(document.documentElement, { childList: true, subtree: true });
    setInterval(expandSoopChatOverlay, 800);
})();
"""


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
    if os.path.basename(parent1).lower() == "dist":
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

    # 프로젝트 assets 및 로컬 assets 폴더에 player_icon.ico 자동 생성
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
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
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


def is_soop_url(url: str) -> bool:
    u = url.lower()
    return any(k in u for k in ("sooplive.co.kr", "sooplive.com", "afreecatv.com"))


def fetch_soop_live_bno(bj_id: str) -> str:
    """SOOP 공식 플레이어 API를 통해 해당 BJ의 현재 진행 중인 실시간 방송번호(BNO)를 조회"""
    api_urls = [
        f"https://live.sooplive.co.kr/afreeca/player_live_api.php?bjid={bj_id}",
        f"https://live.sooplive.com/afreeca/player_live_api.php?bjid={bj_id}",
    ]
    data_payload = urllib.parse.urlencode({
        "bid": bj_id,
        "type": "live",
        "player_type": "html5",
    }).encode("utf-8")

    for api_url in api_urls:
        try:
            req = urllib.request.Request(
                api_url,
                data=data_payload,
                headers={
                    "User-Agent": CHROME_UA,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": f"https://play.sooplive.co.kr/{bj_id}",
                    "Origin": "https://play.sooplive.co.kr",
                }
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
                j = json.loads(raw)
                channel = j.get("CHANNEL", {})
                bno = str(channel.get("BNO", "") or "")
                if bno and bno.isdigit() and int(bno) > 0:
                    return bno
        except Exception:
            pass

    for domain in ("sooplive.co.kr", "sooplive.com"):
        try:
            req = urllib.request.Request(
                f"https://play.{domain}/{bj_id}",
                headers={
                    "User-Agent": CHROME_UA,
                    "Referer": f"https://www.{domain}/"
                }
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                final_url = resp.geturl()
                m_final = re.search(r"/([^/?#]+)/(\d{6,})", final_url)
                if m_final:
                    return m_final.group(2)
                html_text = resp.read(65536).decode("utf-8", errors="ignore")
                m_bno = re.search(r"(?:nBroadNo|broad_no|bno)\s*[:=]\s*['\"]?(\d{6,})['\"]?", html_text)
                if m_bno:
                    return m_bno.group(1)
        except Exception:
            pass
    return ""


def normalize_stream_url(url: str) -> str:
    u = url.strip()
    u_clean = re.sub(r"[?&]vtype=chat", "", u)

    m_soop = re.search(
        r"https?://(?:play|ch|www|m)\.(sooplive\.(?:com|co\.kr)|afreecatv\.com)/(?:station/)?([^/?#]+)(?:/(\d+))?",
        u_clean
    )
    if m_soop:
        bj_id = m_soop.group(2)
        live_bno = fetch_soop_live_bno(bj_id)
        bno = live_bno if live_bno else m_soop.group(3)
        if bno:
            return f"https://play.sooplive.co.kr/{bj_id}/{bno}"
        return f"https://play.sooplive.co.kr/{bj_id}"

    m_chzzk = re.search(r"https?://chzzk\.naver\.com/(?:live/)?([a-fA-F0-9]{16,})(?:/chat)?", u_clean)
    if m_chzzk:
        return f"https://chzzk.naver.com/live/{m_chzzk.group(1)}"

    return u_clean


def extract_live_chat_url(url: str, already_normalized: bool = False) -> str:
    u = url.strip()

    m_chzzk = re.search(r"chzzk\.naver\.com/(?:live/)?([a-fA-F0-9]{16,})", u)
    if m_chzzk:
        cid = m_chzzk.group(1)
        return f"https://chzzk.naver.com/live/{cid}/chat"

    if is_soop_url(u):
        return u if already_normalized else normalize_stream_url(u)

    m_twitch = re.search(r"twitch\.tv/([a-zA-Z0-9_]+)", u)
    if m_twitch:
        channel = m_twitch.group(1)
        return f"https://www.twitch.tv/popout/{channel}/chat?popout="

    m_yt = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/live/)([a-zA-Z0-9_-]{11})", u)
    if m_yt:
        vid = m_yt.group(1)
        return f"https://www.youtube.com/live_chat?v={vid}"

    return ""


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


DIALOG_DARK_QSS = """
    QDialog {
        background-color: #16161d;
        color: #e5e7eb;
        border: 1px solid #323242;
        font-family: 'Segoe UI', 'Malgun Gothic', sans-serif;
    }
    QLabel {
        color: #d1d5db;
        font-size: 13px;
        font-weight: bold;
    }
    QLineEdit, QComboBox {
        background-color: #20202a;
        color: #ffffff;
        border: 1px solid #3b3b4f;
        border-radius: 6px;
        padding: 7px 10px;
        font-size: 13px;
    }
    QLineEdit:focus, QComboBox:focus {
        border: 1px solid #00e5ff;
    }
    QComboBox::drop-down {
        border: none;
    }
    QComboBox QAbstractItemView {
        background-color: #20202a;
        color: #ffffff;
        selection-background-color: #005fb8;
    }
    QListWidget {
        background-color: #121217;
        border: 1px solid #2e2e3d;
        border-radius: 6px;
        padding: 6px;
        font-size: 13px;
        color: #e0e0e0;
    }
    QListWidget::item {
        padding: 8px 10px;
        border-radius: 4px;
        margin-bottom: 2px;
    }
    QListWidget::item:selected {
        background-color: #005fb8;
        color: #ffffff;
        font-weight: bold;
    }
    QPushButton {
        background-color: #262635;
        color: #e5e7eb;
        border: 1px solid #3b3b4f;
        border-radius: 6px;
        padding: 7px 14px;
        font-size: 12px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #00e5ff;
        color: #000000;
        border-color: #00e5ff;
    }
"""


class AddStreamerDialog(QDialog):
    """새 스트리머 등록 (또는 기존 스트리머 수정) 대화상자"""
    def __init__(self, parent=None, default_url: str = "", edit_data: dict = None):
        super().__init__(parent)
        self.setWindowTitle("⭐ 스트리머 즐겨찾기 등록" if not edit_data else "⭐ 스트리머 정보 수정")
        self.setFixedSize(460, 230)
        self.setStyleSheet(DIALOG_DARK_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(14)

        form = QFormLayout()
        form.setSpacing(10)

        self.combo_platform = QComboBox(self)
        self.combo_platform.addItems(["CHZZK", "SOOP"])

        self.edit_name = QLineEdit(self)
        self.edit_name.setPlaceholderText("예: 스트리머 닉네임 (이름순 자동 정렬)")

        self.edit_url = QLineEdit(self)
        self.edit_url.setPlaceholderText("예: https://chzzk.naver.com/live/... 또는 https://play.sooplive.co.kr/아이디")

        if edit_data:
            idx = 0 if edit_data.get("platform") == "CHZZK" else 1
            self.combo_platform.setCurrentIndex(idx)
            self.edit_name.setText(edit_data.get("name", ""))
            self.edit_url.setText(edit_data.get("url", ""))
        elif default_url:
            self.edit_url.setText(default_url)
            if is_soop_url(default_url):
                self.combo_platform.setCurrentIndex(1)
            elif "chzzk" in default_url:
                self.combo_platform.setCurrentIndex(0)

        form.addRow("플랫폼 구분:", self.combo_platform)
        form.addRow("스트리머명:", self.edit_name)
        form.addRow("방송국 주소:", self.edit_url)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_save = QPushButton("💾 저장", self)
        btn_save.clicked.connect(self._on_save)
        btn_cancel = QPushButton("취소", self)
        btn_cancel.clicked.connect(self.reject)

        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _on_save(self):
        name = self.edit_name.text().strip()
        url = self.edit_url.text().strip()
        if not name:
            QMessageBox.warning(self, "입력 확인", "스트리머명을 입력해 주세요.")
            return
        if not url:
            QMessageBox.warning(self, "입력 확인", "방송국 주소(URL)를 입력해 주세요.")
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
            self.edit_url.setText(url)
        self.accept()

    def get_result(self) -> dict:
        return {
            "platform": self.combo_platform.currentText(),
            "name": self.edit_name.text().strip(),
            "url": self.edit_url.text().strip(),
        }


class ManageStreamersDialog(QDialog):
    """즐겨찾기 추가 / 수정 / 삭제 및 파일 내보내기(백업)·불러오기(복원) 통합 관리 대화상자"""
    def __init__(self, player_window):
        super().__init__(player_window)
        self.player_win = player_window
        self.setWindowTitle("🗂 스트리머 즐겨찾기 관리 및 백업/복원")
        self.resize(620, 420)
        self.setStyleSheet(DIALOG_DARK_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        guide = QLabel("등록된 스트리머 목록 ([CHZZK] / [SOOP] 구분 · 더블클릭 시 수정 · JSON 파일 백업/복원 지원)")
        layout.addWidget(guide)

        self.list_widget = QListWidget(self)
        self.list_widget.itemDoubleClicked.connect(self._edit_selected)
        layout.addWidget(self.list_widget, stretch=1)

        row1 = QHBoxLayout()
        btn_add = QPushButton("➕ 새 스트리머 추가", self)
        btn_add.clicked.connect(self._add_new)

        btn_edit = QPushButton("✏ 선택 수정", self)
        btn_edit.clicked.connect(self._edit_selected)

        btn_del = QPushButton("🗑 선택 삭제", self)
        btn_del.clicked.connect(self._delete_selected)

        row1.addWidget(btn_add)
        row1.addWidget(btn_edit)
        row1.addWidget(btn_del)
        row1.addStretch()
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        btn_export = QPushButton("📤 즐겨찾기 파일로 백업 저장 (Export)...", self)
        btn_export.clicked.connect(self._export_backup)

        btn_import = QPushButton("📥 백업 파일에서 불러오기 (Import)...", self)
        btn_import.clicked.connect(self._import_backup)

        btn_close = QPushButton("닫기", self)
        btn_close.clicked.connect(self.accept)

        row2.addWidget(btn_export)
        row2.addWidget(btn_import)
        row2.addStretch()
        row2.addWidget(btn_close)
        layout.addLayout(row2)

        self._refresh_list()

    def _refresh_list(self):
        self.list_widget.clear()
        for idx, item in enumerate(UnifiedMediaPlayer.SHARED_STREAMERS):
            plat = item.get("platform", "CHZZK")
            name = item.get("name", "")
            url = item.get("url", "")
            lw_item = QListWidgetItem(f"[{plat}]  {name}   —   {url}")
            lw_item.setData(Qt.ItemDataRole.UserRole, idx)
            self.list_widget.addItem(lw_item)

    def _add_new(self):
        dlg = AddStreamerDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            res = dlg.get_result()
            UnifiedMediaPlayer.SHARED_STREAMERS.append(res)
            self.player_win.save_and_refresh_streamers()
            self._refresh_list()

    def _edit_selected(self):
        cur = self.list_widget.currentItem()
        if not cur:
            return
        idx = cur.data(Qt.ItemDataRole.UserRole)
        if not (0 <= idx < len(UnifiedMediaPlayer.SHARED_STREAMERS)):
            return
        dlg = AddStreamerDialog(self, edit_data=UnifiedMediaPlayer.SHARED_STREAMERS[idx])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            UnifiedMediaPlayer.SHARED_STREAMERS[idx] = dlg.get_result()
            self.player_win.save_and_refresh_streamers()
            self._refresh_list()

    def _delete_selected(self):
        cur = self.list_widget.currentItem()
        if not cur:
            return
        idx = cur.data(Qt.ItemDataRole.UserRole)
        if 0 <= idx < len(UnifiedMediaPlayer.SHARED_STREAMERS):
            removed = UnifiedMediaPlayer.SHARED_STREAMERS.pop(idx)
            self.player_win.save_and_refresh_streamers()
            self._refresh_list()
            self.player_win.show_osd(f"🗑 즐겨찾기 삭제됨: [{removed.get('platform')}] {removed.get('name')}")

    def _export_backup(self):
        self.player_win.export_streamers_to_file()

    def _import_backup(self):
        self.player_win.import_streamers_from_file()
        self._refresh_list()


class ManageLayoutsDialog(QDialog):
    """화면 분할 및 커스텀 창 배치 묶음(Layout) 관리 · 백업/복원 대화상자"""
    def __init__(self, player_window):
        super().__init__(player_window)
        self.player_win = player_window
        self.setWindowTitle("📐 화면 분할 & 커스텀 레이아웃 묶음 관리")
        self.resize(660, 450)
        self.setStyleSheet(DIALOG_DARK_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        lbl_preset = QLabel("⚡ 원클릭 그리드 자동 분할 프리셋 (현재 모니터 기준)")
        layout.addWidget(lbl_preset)

        preset_row = QHBoxLayout()
        for code, title in (
            ("grid_1", "1) 단일 전체 창 (Alt+1)"),
            ("grid_2h", "2) 좌우 2분할 (Alt+2)"),
            ("grid_3h", "3) 3분할 뷰 (Alt+3)"),
            ("grid_4q", "4) 4분할 쿼드뷰 (Alt+4)"),
        ):
            btn_p = QPushButton(title, self)
            btn_p.clicked.connect(lambda checked=False, c=code: self.player_win.apply_grid_preset(c))
            preset_row.addWidget(btn_p)
        layout.addLayout(preset_row)

        lbl_custom = QLabel("💾 저장된 커스텀 창 배치 묶음 (방송 URL 제외 · 창 개수 및 위치/크기만 저장 · 더블클릭 시 즉시 배치)")
        layout.addWidget(lbl_custom)

        self.list_widget = QListWidget(self)
        self.list_widget.itemDoubleClicked.connect(self._apply_selected)
        layout.addWidget(self.list_widget, stretch=1)

        row1 = QHBoxLayout()
        btn_capture = QPushButton("➕ 현재 열려있는 창 배치 저장", self)
        btn_capture.clicked.connect(self._capture_current)

        btn_apply = QPushButton("▶ 선택 레이아웃 즉시 적용", self)
        btn_apply.clicked.connect(self._apply_selected)

        btn_rename = QPushButton("✏ 이름 변경", self)
        btn_rename.clicked.connect(self._rename_selected)

        btn_del = QPushButton("🗑 선택 삭제", self)
        btn_del.clicked.connect(self._delete_selected)

        row1.addWidget(btn_capture)
        row1.addWidget(btn_apply)
        row1.addWidget(btn_rename)
        row1.addWidget(btn_del)
        row1.addStretch()
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        btn_export = QPushButton("📤 레이아웃 묶음 백업 저장 (Export)...", self)
        btn_export.clicked.connect(self.player_win.export_layouts_to_file)

        btn_import = QPushButton("📥 레이아웃 묶음 불러오기 (Import)...", self)
        btn_import.clicked.connect(self._import_layouts)

        btn_close = QPushButton("닫기", self)
        btn_close.clicked.connect(self.accept)

        row2.addWidget(btn_export)
        row2.addWidget(btn_import)
        row2.addStretch()
        row2.addWidget(btn_close)
        layout.addLayout(row2)

        self._refresh_list()

    def _refresh_list(self):
        self.list_widget.clear()
        for idx, item in enumerate(UnifiedMediaPlayer.SHARED_LAYOUTS):
            name = item.get("name", f"레이아웃 {idx + 1}")
            wins = item.get("windows", [])
            lw_item = QListWidgetItem(f"📐 [{idx + 1}]  {name}   —   플레이어 창 {len(wins)}개 묶음 배치")
            lw_item.setData(Qt.ItemDataRole.UserRole, idx)
            self.list_widget.addItem(lw_item)

    def _capture_current(self):
        if self.player_win.capture_and_save_current_layout(parent_widget=self):
            self._refresh_list()

    def _apply_selected(self):
        cur = self.list_widget.currentItem()
        if not cur:
            return
        idx = cur.data(Qt.ItemDataRole.UserRole)
        if 0 <= idx < len(UnifiedMediaPlayer.SHARED_LAYOUTS):
            self.player_win.apply_saved_custom_layout(idx)

    def _rename_selected(self):
        cur = self.list_widget.currentItem()
        if not cur:
            return
        idx = cur.data(Qt.ItemDataRole.UserRole)
        if not (0 <= idx < len(UnifiedMediaPlayer.SHARED_LAYOUTS)):
            return
        old_name = UnifiedMediaPlayer.SHARED_LAYOUTS[idx].get("name", "")
        new_name, ok = QInputDialog.getText(
            self, "레이아웃 이름 변경", "새 레이아웃 이름을 입력하세요:", QLineEdit.EchoMode.Normal, old_name
        )
        if ok and new_name.strip():
            UnifiedMediaPlayer.SHARED_LAYOUTS[idx]["name"] = new_name.strip()
            self.player_win.save_layouts_to_disk()
            self._refresh_list()

    def _delete_selected(self):
        cur = self.list_widget.currentItem()
        if not cur:
            return
        idx = cur.data(Qt.ItemDataRole.UserRole)
        if 0 <= idx < len(UnifiedMediaPlayer.SHARED_LAYOUTS):
            removed = UnifiedMediaPlayer.SHARED_LAYOUTS.pop(idx)
            self.player_win.save_layouts_to_disk()
            self._refresh_list()
            self.player_win.show_osd(f"🗑 레이아웃 삭제됨: {removed.get('name')}")

    def _import_layouts(self):
        self.player_win.import_layouts_from_file()
        self._refresh_list()


class DetachablePanel(QWidget):
    """채팅창, 스트리머 즐겨찾기창, 재생목록창을 위한 멀티 도킹/분리 & 자체 드래그·마그네틱 스냅 위젯"""
    RESIZE_MARGIN = 8

    def __init__(self, player_window, title_text: str, default_dock_width: int = 360):
        super().__init__(player_window)
        self.player_win = player_window
        self.dock_width = default_dock_width
        self.mode = "right"
        self.bottom_height = 600

        self._drag_pos = QPoint()
        self._is_dragging = False
        self._is_resizing = False
        self._resize_edges = Qt.Edge(0)
        self._resize_start_global = QPoint()
        self._resize_start_geom = QRect()
        self._resize_start_dock_width = default_dock_width

        self.setMouseTracking(True)
        self.setFixedWidth(self.dock_width)

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        self.header = QWidget(self)
        self.header.setFixedHeight(36)
        self.header.setMouseTracking(True)
        self.header.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
        self.header.setStyleSheet(
            "background-color: #16161d; border-left: 2px solid #2a2a38; "
            "border-bottom: 1px solid #2a2a35; border-top: 1px solid #2a2a35;"
        )
        h_layout = QHBoxLayout(self.header)
        h_layout.setContentsMargins(10, 0, 6, 0)
        h_layout.setSpacing(4)

        self.title_label = QLabel(title_text, self.header)
        self.title_label.setStyleSheet("color: #00e5ff; font-size: 12px; font-weight: bold; border: none;")
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        h_layout.addWidget(self.title_label)
        h_layout.addStretch()

        self.btn_dock_right = QPushButton("⇥우측", self.header)
        self.btn_dock_right.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_dock_right.setToolTip("플레이어 내부 우측에 붙이기 (좌측 경계선 드래그로 폭 조절)")
        self.btn_dock_right.clicked.connect(lambda: self.set_panel_mode("right"))

        self.btn_dock_bottom = QPushButton("⤓하단(폭맞춤)", self.header)
        self.btn_dock_bottom.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_dock_bottom.setToolTip("플레이어 아래쪽에 붙이고 가로 폭을 플레이어에 맞추기 (높이 3배 확장 · 드래그 이동 가능)")
        self.btn_dock_bottom.clicked.connect(lambda: self.set_panel_mode("bottom"))

        self.btn_detach = QPushButton("❐분리", self.header)
        self.btn_detach.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_detach.setToolTip("독립된 창으로 분리하기 (상단 바 드래그로 자유 이동 · 자석 스냅 · 8방향 크기 조절)")
        self.btn_detach.clicked.connect(lambda: self.set_panel_mode("floating"))

        self.btn_close = QPushButton("✕", self.header)
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_close.setToolTip("패널 숨기기")
        self.btn_close.setStyleSheet(
            "QPushButton { background: transparent; color: #aaa; border: none; font-size: 13px; } "
            "QPushButton:hover { color: #ff5555; }"
        )
        self.btn_close.clicked.connect(self.hide_panel)

        h_layout.addWidget(self.btn_dock_right)
        h_layout.addWidget(self.btn_dock_bottom)
        h_layout.addWidget(self.btn_detach)
        h_layout.addWidget(self.btn_close)

        self.root_layout.addWidget(self.header)
        self._update_mode_buttons_style()

        self.installEventFilter(self)
        self.header.installEventFilter(self)

    def add_Header_Extra_Button(self, btn: QPushButton):
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        layout = self.header.layout()
        layout.insertWidget(2, btn)

    def set_content_widget(self, widget: QWidget):
        widget.setMouseTracking(True)
        self.root_layout.addWidget(widget, stretch=1)

    def _update_mode_buttons_style(self):
        active_qss = (
            "QPushButton { background-color: #00e5ff; color: #000000; "
            "border: 1px solid #00e5ff; border-radius: 4px; font-size: 11px; font-weight: bold; padding: 2px 6px; }"
        )
        inactive_qss = (
            "QPushButton { background-color: #22222c; color: #cccccc; "
            "border: 1px solid #353545; border-radius: 4px; font-size: 11px; font-weight: bold; padding: 2px 6px; }"
            "QPushButton:hover { background-color: #00e5ff; color: #000000; }"
        )
        self.btn_dock_right.setStyleSheet(active_qss if self.mode == "right" else inactive_qss)
        self.btn_dock_bottom.setStyleSheet(active_qss if self.mode == "bottom" else inactive_qss)
        self.btn_detach.setStyleSheet(active_qss if self.mode == "floating" else inactive_qss)

    def set_panel_mode(self, new_mode: str):
        was_visible = self.isVisible()
        self.mode = new_mode
        self._update_mode_buttons_style()

        if new_mode == "right":
            self.setParent(self.player_win.central_widget)
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setMinimumSize(220, 150)
            self.setMaximumSize(900, 16777215)
            self.setFixedWidth(self.dock_width)
            self.player_win.main_layout.addWidget(self, stretch=0)
            if was_visible:
                self.show()
            self.player_win.show_osd("⇥ 패널 우측 결합 (좌측 경계선을 마우스로 끌어 폭 조절 가능)")

        elif new_mode == "bottom":
            self.player_win.main_layout.removeWidget(self)
            self.setParent(None)
            self.setWindowFlags(
                Qt.WindowType.Window |
                Qt.WindowType.FramelessWindowHint
            )
            self.setMinimumSize(300, 180)
            self.setMaximumSize(16777215, 16777215)
            self.sync_bottom_geometry()
            if was_visible:
                self.show()
                self.raise_()
                self.activateWindow()
            self.player_win.show_osd("⤓ 패널 하단 결합 (높이 3배 확장 · 상단 바 드래그 시 자유 이동 가능)")

        elif new_mode == "floating":
            self.player_win.main_layout.removeWidget(self)
            self.setParent(None)
            self.setWindowFlags(
                Qt.WindowType.Window |
                Qt.WindowType.FramelessWindowHint
            )
            self.setMinimumSize(240, 180)
            self.setMaximumSize(16777215, 16777215)
            p_geom = self.player_win.frameGeometry()
            screen = self.player_win.screen() or QApplication.primaryScreen()
            avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

            target_x = p_geom.right() + 1
            if target_x + self.dock_width > avail.right():
                target_x = max(avail.left(), avail.right() - self.dock_width)

            self.setGeometry(target_x, p_geom.top(), self.dock_width, max(520, p_geom.height()))
            if was_visible:
                self.show()
                self.raise_()
                self.activateWindow()
            self.player_win.show_osd("❐ 독립 창 분리 완료 (상단 헤더를 잡고 원하는 곳으로 이동하세요)")

        QTimer.singleShot(25, self.player_win._force_layout_sync)

    def sync_bottom_geometry(self):
        if self.mode != "bottom":
            return
        p_geom = self.player_win.frameGeometry()
        screen = self.player_win.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

        target_h = min(self.bottom_height, max(360, avail.height() - 80))
        target_y = p_geom.bottom() + 1
        if target_y + target_h > avail.bottom():
            target_y = max(avail.top(), avail.bottom() - target_h)

        self.setGeometry(p_geom.left(), target_y, p_geom.width(), target_h)

    def show_panel(self):
        if self.mode == "bottom":
            self.sync_bottom_geometry()
        self.show()
        if self.mode in ("bottom", "floating"):
            self.raise_()

    def hide_panel(self):
        self.hide()
        self.unsetCursor()
        QTimer.singleShot(25, self.player_win._force_layout_sync)

    def detect_panel_resize_edges(self, global_pos: QPoint) -> Qt.Edge:
        if not self.isVisible():
            return Qt.Edge(0)

        m = self.RESIZE_MARGIN

        if self.mode == "right":
            top_left = self.mapToGlobal(QPoint(0, 0))
            panel_rect = QRect(top_left.x(), top_left.y(), self.width(), self.height())
            if panel_rect.adjusted(-m, 0, 0, 0).contains(global_pos):
                if abs(global_pos.x() - top_left.x()) <= m:
                    return Qt.Edge.LeftEdge
            return Qt.Edge(0)

        rect = self.frameGeometry()
        if not rect.adjusted(-2, -2, 2, 2).contains(global_pos):
            return Qt.Edge(0)

        edges = Qt.Edge(0)
        if self.mode in ("floating", "bottom"):
            if global_pos.x() <= rect.left() + m:
                edges |= Qt.Edge.LeftEdge
            elif global_pos.x() >= rect.right() - m:
                edges |= Qt.Edge.RightEdge

        if global_pos.y() <= rect.top() + m:
            edges |= Qt.Edge.TopEdge
        elif global_pos.y() >= rect.bottom() - m:
            edges |= Qt.Edge.BottomEdge

        return edges

    def update_panel_cursor(self, edges: Qt.Edge):
        if not edges:
            self.unsetCursor()
            return
        if edges in (
            Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
            Qt.Edge.BottomEdge | Qt.Edge.RightEdge
        ):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edges in (
            Qt.Edge.TopEdge | Qt.Edge.RightEdge,
            Qt.Edge.BottomEdge | Qt.Edge.LeftEdge
        ):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edges in (Qt.Edge.LeftEdge, Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edges in (Qt.Edge.TopEdge, Qt.Edge.BottomEdge):
            self.setCursor(Qt.CursorShape.SizeVerCursor)

    def start_panel_interaction(self, global_pos: QPoint) -> bool:
        edges = self.detect_panel_resize_edges(global_pos)
        if edges:
            self._is_resizing = True
            self._resize_edges = edges
            self._resize_start_global = global_pos
            self._resize_start_geom = self.geometry()
            self._resize_start_dock_width = self.width()
            return True

        if self.mode in ("bottom", "floating"):
            local_pos = self.mapFromGlobal(global_pos)
            if 0 <= local_pos.y() <= self.header.height():
                if self.mode == "bottom":
                    self.mode = "floating"
                    self._update_mode_buttons_style()
                self._is_dragging = True
                self._drag_pos = global_pos - self.frameGeometry().topLeft()
                return True

        return False

    def perform_panel_drag_or_resize(self, global_pos: QPoint) -> bool:
        if self._is_resizing:
            delta = global_pos - self._resize_start_global

            if self.mode == "right" and (self._resize_edges & Qt.Edge.LeftEdge):
                new_w = max(220, min(900, self._resize_start_dock_width - delta.x()))
                self.dock_width = new_w
                self.setFixedWidth(new_w)
                self.player_win._force_layout_sync()
                return True

            g = QRect(self._resize_start_geom)
            min_w, min_h = self.minimumWidth(), self.minimumHeight()

            if self._resize_edges & Qt.Edge.LeftEdge:
                if g.right() - (g.left() + delta.x()) >= min_w:
                    g.setLeft(g.left() + delta.x())
            elif self._resize_edges & Qt.Edge.RightEdge:
                if g.width() + delta.x() >= min_w:
                    g.setWidth(g.width() + delta.x())

            if self._resize_edges & Qt.Edge.TopEdge:
                if g.bottom() - (g.top() + delta.y()) >= min_h:
                    g.setTop(g.top() + delta.y())
            elif self._resize_edges & Qt.Edge.BottomEdge:
                if g.height() + delta.y() >= min_h:
                    g.setHeight(g.height() + delta.y())

            self.setGeometry(g)
            if self.mode == "bottom":
                self.bottom_height = g.height()
            else:
                self.dock_width = g.width()
            return True

        if self._is_dragging:
            raw_tl = global_pos - self._drag_pos
            cand_rect = QRect(raw_tl.x(), raw_tl.y(), self.width(), self.height())
            targets = self.player_win._get_snap_target_rects(exclude_widget=self)
            snapped_tl = compute_magnetic_snap(cand_rect, targets, snap_dist=18)
            self.move(snapped_tl)
            return True

        return False

    def stop_panel_interaction(self):
        if self._is_resizing or self._is_dragging:
            self._is_resizing = False
            self._is_dragging = False
            self._resize_edges = Qt.Edge(0)
            self.unsetCursor()
            return True
        return False

    def eventFilter(self, watched, event):
        if watched in (self, self.header):
            etype = event.type()
            if etype == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                child = self.childAt(self.mapFromGlobal(event.globalPosition().toPoint()))
                if isinstance(child, QPushButton):
                    return False
                if self.start_panel_interaction(event.globalPosition().toPoint()):
                    event.accept()
                    return True
            elif etype == QEvent.Type.MouseMove:
                global_pos = event.globalPosition().toPoint()
                if self._is_dragging or self._is_resizing:
                    if self.perform_panel_drag_or_resize(global_pos):
                        event.accept()
                        return True
                else:
                    edges = self.detect_panel_resize_edges(global_pos)
                    self.update_panel_cursor(edges)
            elif etype == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                if self.stop_panel_interaction():
                    event.accept()
                    return True
        return super().eventFilter(watched, event)


class StreamlinkResolverThread(QThread):
    resolved = pyqtSignal(str, str, str, bool, str, str)
    failed = pyqtSignal(str, str)

    def __init__(self, target_url: str, parent=None):
        super().__init__(parent)
        self.target_url = target_url

    def run(self):
        normalized_url = normalize_stream_url(self.target_url)
        chat_url = extract_live_chat_url(normalized_url, already_normalized=True)

        if HAS_STREAMLINK:
            candidate_urls = [normalized_url]
            if "sooplive.co.kr" in normalized_url:
                candidate_urls.append(normalized_url.replace("sooplive.co.kr", "sooplive.com"))
            elif "sooplive.com" in normalized_url:
                candidate_urls.append(normalized_url.replace("sooplive.com", "sooplive.co.kr"))

            for try_url in candidate_urls:
                try:
                    session = streamlink.Streamlink()
                    session.set_option("http-headers", {
                        "User-Agent": CHROME_UA,
                        "Referer": "https://play.sooplive.co.kr/"
                    })
                    streams = session.streams(try_url)
                    if streams:
                        chosen_q = None
                        for q in ("best", "1080p60", "1080p", "720p60", "720p"):
                            if q in streams:
                                chosen_q = q
                                break
                        if not chosen_q:
                            chosen_q = list(streams.keys())[-1]

                        stream_url = streams[chosen_q].to_url()
                        is_live = not ("youtube.com/watch" in self.target_url or "youtu.be/" in self.target_url)
                        self.resolved.emit(
                            normalized_url, stream_url, f"Streamlink {chosen_q}", is_live, normalized_url, chat_url
                        )
                        return
                except Exception as e:
                    print(f"[Streamlink 시도 ({try_url})] {e}")

        if HAS_YTDLP:
            candidate_urls = [normalized_url]
            if self.target_url != normalized_url:
                candidate_urls.append(self.target_url)
            for try_url in candidate_urls:
                try:
                    ydl_opts = {
                        'format': 'best[ext=mp4]/best',
                        'quiet': True,
                        'no_warnings': True,
                        'noplaylist': True,
                        'http_headers': {'User-Agent': CHROME_UA}
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(try_url, download=False)
                        stream_url = info.get('url', '')
                        is_live = bool(info.get('is_live', False)) or bool(chat_url)
                        title = info.get('title', normalized_url)
                        vid_id = info.get('id', '')
                        if is_live and vid_id and ("youtube.com" in self.target_url or "youtu.be" in self.target_url):
                            chat_url = f"https://www.youtube.com/live_chat?v={vid_id}"
                        if stream_url:
                            self.resolved.emit(
                                normalized_url, stream_url, "yt-dlp", is_live, title, chat_url
                            )
                            return
                except Exception as e:
                    print(f"[yt-dlp 시도 ({try_url})] {e}")

        err_msg = "streamlink/yt-dlp 미설치" if (not HAS_STREAMLINK and not HAS_YTDLP) else "스트림 추출 불가(방송 종료 등)"
        self.failed.emit(normalized_url, err_msg)


class AnimatedGraphicsView(QGraphicsView):
    """QGraphicsView 기반 이미지 뷰어 (4대 전환 애니메이션 탑재)"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene_obj = QGraphicsScene(self)
        self.setScene(self.scene_obj)

        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

        self.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setBackgroundBrush(QBrush(QColor("#0f0f0f")))

        self.back_item = QGraphicsPixmapItem()
        self.front_item = QGraphicsPixmapItem()
        self.back_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.front_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)

        self.back_item.setZValue(0)
        self.front_item.setZValue(1)

        self.scene_obj.addItem(self.back_item)
        self.scene_obj.addItem(self.front_item)

        self.current_raw_pixmap = None
        self.next_raw_pixmap = None
        self._cached_front_scaled = None
        self._cached_back_scaled = None

        self.transition_mode = 4
        self.is_animating = False

        self.anim = QVariantAnimation(self)
        self.anim.valueChanged.connect(self._on_anim_step)
        self.anim.finished.connect(self._on_anim_finished)

    def _fit_pixmap_to_view(self, raw_pixmap: QPixmap) -> QPixmap:
        if not raw_pixmap or raw_pixmap.isNull():
            return QPixmap()
        vw = max(10, self.viewport().width())
        vh = max(10, self.viewport().height())
        return raw_pixmap.scaled(
            vw, vh,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

    def _reset_item_states(self):
        vw = max(1, self.viewport().width())
        vh = max(1, self.viewport().height())
        self.scene_obj.setSceneRect(0, 0, vw, vh)

        for item in (self.back_item, self.front_item):
            item.setOpacity(1.0)
            item.setScale(1.0)
            item.setTransform(QTransform())

        self._center_item(self.back_item)
        self._center_item(self.front_item)

    def _center_item(self, item: QGraphicsPixmapItem):
        pix = item.pixmap()
        if pix.isNull():
            return
        vw = max(1, self.viewport().width())
        vh = max(1, self.viewport().height())
        pw = pix.width()
        ph = pix.height()

        item.setTransformOriginPoint(pw / 2.0, ph / 2.0)
        item.setPos((vw - pw) / 2.0, (vh - ph) / 2.0)

    def _render_page_curl_frame(self, front_pix: QPixmap, back_pix: QPixmap, p: float) -> QPixmap:
        vw = max(10, self.viewport().width())
        vh = max(10, self.viewport().height())

        canvas = QPixmap(vw, vh)
        canvas.fill(QColor("#0f0f0f"))

        painter = QPainter(canvas)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )

        if back_pix and not back_pix.isNull():
            bx = (vw - back_pix.width()) / 2.0
            by = (vh - back_pix.height()) / 2.0
            painter.drawPixmap(QPointF(bx, by), back_pix)

        if not front_pix or front_pix.isNull():
            painter.end()
            return canvas

        fw = float(front_pix.width())
        fh = float(front_pix.height())
        fx = (vw - fw) / 2.0
        fy = (vh - fh) / 2.0

        dx = max(4.0, p * fw * 1.48)
        dy = max(4.0, p * fh * 1.38)

        e1 = QPointF(fw - dx, fh)
        e2 = QPointF(fw, fh - dy)

        page_rect_path = QPainterPath()
        page_rect_path.addRect(QRectF(0.0, 0.0, fw, fh))

        peeled_triangle = QPainterPath()
        peeled_triangle.moveTo(fw + 2.0, fh + 2.0)
        peeled_triangle.lineTo(e1.x(), e1.y())
        peeled_triangle.lineTo(e2.x(), e2.y())
        peeled_triangle.closeSubpath()

        remain_path = page_rect_path.subtracted(peeled_triangle)

        painter.save()
        painter.translate(fx, fy)

        painter.save()
        painter.setClipPath(remain_path)
        painter.drawPixmap(0, 0, front_pix)
        painter.restore()

        vx = e2.x() - e1.x()
        vy = e2.y() - e1.y()
        len_sq = vx * vx + vy * vy

        if len_sq > 1e-3:
            t_proj = (dx * vx) / len_sq
            proj_x = e1.x() + t_proj * vx
            proj_y = e1.y() + t_proj * vy

            cp_x = 2.0 * proj_x - fw
            cp_y = 2.0 * proj_y - fh
            c_prime = QPointF(cp_x, cp_y)

            fold_poly_path = QPainterPath()
            fold_poly_path.addPolygon(QPolygonF([c_prime, e1, e2]))
            visible_flap_path = fold_poly_path.intersected(page_rect_path)

            if not visible_flap_path.isEmpty():
                painter.save()
                painter.setClipPath(page_rect_path)
                shadow_grad = QLinearGradient(QPointF(proj_x, proj_y), QPointF(fw, fh))
                shadow_alpha = int(160 * (1.0 - 0.5 * p))
                shadow_grad.setColorAt(0.0, QColor(0, 0, 0, shadow_alpha))
                shadow_grad.setColorAt(0.28, QColor(0, 0, 0, int(shadow_alpha * 0.35)))
                shadow_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
                painter.fillPath(page_rect_path.subtracted(remain_path), QBrush(shadow_grad))
                painter.restore()

                curved_flap = QPainterPath()
                curved_flap.moveTo(e1)
                ctrl_pt1 = QPointF((e1.x() + cp_x) * 0.5 + vy * 0.05, (e1.y() + cp_y) * 0.5 - vx * 0.05)
                ctrl_pt2 = QPointF((e2.x() + cp_x) * 0.5 + vy * 0.05, (e2.y() + cp_y) * 0.5 - vx * 0.05)
                curved_flap.quadTo(ctrl_pt1, c_prime)
                curved_flap.quadTo(ctrl_pt2, e2)
                curved_flap.closeSubpath()

                clipped_curved_flap = curved_flap.intersected(page_rect_path)

                angle_deg = math.degrees(math.atan2(vy, vx))
                refl_transform = QTransform()
                refl_transform.translate(e1.x(), e1.y())
                refl_transform.rotate(angle_deg)
                refl_transform.scale(1.0, -1.0)
                refl_transform.rotate(-angle_deg)
                refl_transform.translate(-e1.x(), -e1.y())

                painter.save()
                painter.setClipPath(clipped_curved_flap)
                painter.setTransform(refl_transform, True)
                painter.drawPixmap(0, 0, front_pix)
                painter.restore()

                painter.save()
                flap_shade = QLinearGradient(c_prime, QPointF(proj_x, proj_y))
                flap_shade.setColorAt(0.0, QColor(0, 0, 0, 75))
                flap_shade.setColorAt(0.55, QColor(255, 255, 255, 45))
                flap_shade.setColorAt(0.88, QColor(0, 0, 0, 65))
                flap_shade.setColorAt(1.0, QColor(0, 0, 0, 110))
                painter.fillPath(clipped_curved_flap, QBrush(flap_shade))

                pen = QPen(QColor(255, 255, 255, 130), 1.2)
                painter.setPen(pen)
                painter.drawPath(clipped_curved_flap)
                painter.restore()

        painter.restore()
        painter.end()
        return canvas

    def show_image(self, new_pixmap: QPixmap, play_sound_callback=None, force: bool = False):
        if new_pixmap is None or new_pixmap.isNull():
            return False

        if self.is_animating:
            if force:
                self.anim.stop()
                if self.next_raw_pixmap is not None:
                    self.current_raw_pixmap = self.next_raw_pixmap
                    self.next_raw_pixmap = None
                self.is_animating = False
            else:
                return False

        if self.current_raw_pixmap is None or self.transition_mode == 1:
            if self.current_raw_pixmap is not None and play_sound_callback:
                play_sound_callback()
            self.current_raw_pixmap = new_pixmap
            self._reset_item_states()
            self.front_item.setPixmap(self._fit_pixmap_to_view(self.current_raw_pixmap))
            self._center_item(self.front_item)
            self.back_item.setPixmap(QPixmap())
            return True

        self.is_animating = True
        if play_sound_callback:
            play_sound_callback()

        self.next_raw_pixmap = new_pixmap
        self._reset_item_states()

        self._cached_front_scaled = self._fit_pixmap_to_view(self.current_raw_pixmap)
        self._cached_back_scaled = self._fit_pixmap_to_view(self.next_raw_pixmap)

        self.front_item.setPixmap(self._cached_front_scaled)
        self.back_item.setPixmap(self._cached_back_scaled)
        self._center_item(self.front_item)
        self._center_item(self.back_item)

        self.anim.stop()
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)

        if self.transition_mode == 2:
            self.anim.setDuration(320)
            self.anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
            self.back_item.setOpacity(1.0)
            self.front_item.setOpacity(1.0)
        elif self.transition_mode == 3:
            self.anim.setDuration(420)
            self.anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
            self.back_item.setOpacity(0.0)
            self.front_item.setOpacity(1.0)
        elif self.transition_mode == 4:
            self.anim.setDuration(520)
            self.anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
            self.back_item.setOpacity(0.0)
            self.front_item.setOpacity(1.0)
            self.front_item.setPos(0, 0)

        self.anim.start()
        return True

    def _on_anim_step(self, progress: float):
        p = float(progress)
        if self.transition_mode == 2:
            self.front_item.setOpacity(1.0 - p)
        elif self.transition_mode == 3:
            if p < 0.5:
                t = p * 2.0
                scale = 1.0 - (0.28 * t)
                self.front_item.setScale(scale)
                self.front_item.setOpacity(1.0 - (0.3 * t))
                self.back_item.setOpacity(0.0)
            else:
                t = (p - 0.5) * 2.0
                self.front_item.setOpacity(0.0)
                scale = 0.72 + (0.28 * t)
                self.back_item.setScale(scale)
                self.back_item.setOpacity(t)
        elif self.transition_mode == 4:
            curled_frame = self._render_page_curl_frame(
                self._cached_front_scaled, self._cached_back_scaled, p
            )
            self.front_item.setPos(0, 0)
            self.front_item.setPixmap(curled_frame)

    def _on_anim_finished(self):
        if self.next_raw_pixmap is not None:
            self.current_raw_pixmap = self.next_raw_pixmap
            self.next_raw_pixmap = None
        self._reset_item_states()
        if self.current_raw_pixmap is not None:
            self.front_item.setPixmap(self._fit_pixmap_to_view(self.current_raw_pixmap))
            self._center_item(self.front_item)
        self.back_item.setPixmap(QPixmap())
        self.is_animating = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh_scale_on_resize()

    def refresh_scale_on_resize(self):
        if self.is_animating:
            return
        self._reset_item_states()
        if self.current_raw_pixmap and not self.current_raw_pixmap.isNull():
            self.front_item.setPixmap(self._fit_pixmap_to_view(self.current_raw_pixmap))
            self._center_item(self.front_item)

    def clear_view(self):
        self.anim.stop()
        self.is_animating = False
        self.current_raw_pixmap = None
        self.next_raw_pixmap = None
        self.front_item.setPixmap(QPixmap())
        self.back_item.setPixmap(QPixmap())


class UnifiedMediaPlayer(QMainWindow):
    ACTIVE_INSTANCES = []
    SHARED_WEB_PROFILE = None
    SHARED_STREAMERS = None
    SHARED_LAYOUTS = None

    RESIZE_MARGIN = 8
    SNAP_BAR_TOP_ZONE = 48

    def __init__(self, initial_paths=None):
        self._ui_initialized = False
        self._is_cleaned_up = False
        self._win32_snap_applied = False
        self._normal_geometry = None

        self.chat_panel = None
        self.streamer_panel = None
        self.playlist_panel = None
        self.jump_input = None
        self.interval_input = None
        self.url_input = None
        self.osd_window = None
        self.control_bar = None
        self._active_interacting_panel = None
        self._active_login_platform = None

        super().__init__()
        UnifiedMediaPlayer.ACTIVE_INSTANCES.append(self)

        win_num = len(UnifiedMediaPlayer.ACTIVE_INSTANCES)
        title_suffix = f" #{win_num}" if win_num > 1 else ""
        self.setWindowTitle(f"Minimal Media Player v2.6{title_suffix}")
        self.resize(1280, 720)
        self.setMinimumSize(420, 260)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Window |
            Qt.WindowType.WindowSystemMenuHint |
            Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.setAcceptDrops(True)
        self.setMouseTracking(True)

        self.playlist = []
        self.current_index = -1
        self.current_web_url = ""
        self.current_chat_url = ""
        self.is_live_stream_playing = False
        self.stream_resolver = None

        data_root = get_data_root_dir()
        self.streamers_file = os.path.join(data_root, "streamers.json")
        self.layouts_file = os.path.join(data_root, "layouts.json")
        self._init_shared_repositories()

        self.drag_pos = QPoint()
        self._is_dragging_window = False
        self._is_resizing = False
        self._resize_edges = Qt.Edge(0)
        self._resize_start_global = QPoint()
        self._resize_start_geom = QRect()

        self.is_slider_dragging = False
        self.custom_seek_sec = 89
        self.playback_rate = 1.0
        self.is_shuffle = False
        self.is_repeat_all = False
        self.shuffle_order = []
        self.shuffle_pos = -1

        self.image_slideshow_interval = 5000
        self.image_timer = QTimer(self)
        self.image_timer.setSingleShot(True)
        self.image_timer.timeout.connect(self._on_media_finished)
        self.is_image_paused = False

        self._init_web_profiles()
        self._init_media_core()
        self._init_sound_effect()
        self._init_ui()
        self._init_top_level_overlays()
        self._init_global_shortcuts()
        self._init_tray()
        self._apply_dark_theme()
        self._refresh_streamer_ui()
        self._position_initial_window()

        self.hover_poll_timer = QTimer(self)
        self.hover_poll_timer.setInterval(45)
        self.hover_poll_timer.timeout.connect(self._poll_mouse_state)
        self.hover_poll_timer.start()

        self.installEventFilter(self)
        for child_w in (
            self.central_widget, self.stack, self.guide_label,
            self.video_widget, self.image_view.viewport(), self.audio_cover_label
        ):
            child_w.installEventFilter(self)

        self._ui_initialized = True

        if initial_paths:
            QTimer.singleShot(80, lambda: self._append_paths_to_playlist(initial_paths))

    def _init_shared_repositories(self):
        if UnifiedMediaPlayer.SHARED_STREAMERS is None:
            loaded_st = safe_load_json(self.streamers_file, None)
            if loaded_st is None:
                loaded_st = safe_load_json(os.path.join(get_base_dir(), "streamers.json"), [])
            UnifiedMediaPlayer.SHARED_STREAMERS = loaded_st if isinstance(loaded_st, list) else []
            self._sort_streamers()

        if UnifiedMediaPlayer.SHARED_LAYOUTS is None:
            loaded_ly = safe_load_json(self.layouts_file, None)
            if loaded_ly is None:
                loaded_ly = safe_load_json(os.path.join(get_base_dir(), "layouts.json"), [])
            UnifiedMediaPlayer.SHARED_LAYOUTS = loaded_ly if isinstance(loaded_ly, list) else []

    def showEvent(self, event):
        super().showEvent(event)
        if HAS_WIN32 and not self._win32_snap_applied:
            self._win32_snap_applied = True
            self._enable_windows_aero_snap_style()

    def _enable_windows_aero_snap_style(self):
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t

            style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
            new_style = style | WS_MAXIMIZEBOX | WS_MINIMIZEBOX | WS_SYSMENU
            user32.SetWindowLongPtrW(hwnd, GWL_STYLE, new_style)
        except Exception as e:
            print(f"[Win32 스타일 적용 참고] {e}")

    def _is_web_or_input_focused(self) -> bool:
        fw = QApplication.focusWidget()
        if fw is None:
            return False
        if isinstance(fw, QLineEdit):
            return True
        p = fw
        while p is not None:
            if isinstance(p, QWebEngineView):
                return True
            p = p.parentWidget()
        return False

    def _bind_non_conflicting_shortcut(self, key_str: str, callback):
        sc = QShortcut(QKeySequence(key_str), self)
        sc.setContext(Qt.ShortcutContext.WindowShortcut)
        sc.activated.connect(lambda: callback() if not self._is_web_or_input_focused() else None)
        return sc

    def spawn_new_player_window(self):
        new_win = UnifiedMediaPlayer()
        cur_geom = self.frameGeometry()
        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

        if cur_geom.right() + cur_geom.width() <= avail.right():
            new_win.setGeometry(cur_geom.right() + 1, cur_geom.top(), cur_geom.width(), cur_geom.height())
        else:
            new_win.setGeometry(
                min(avail.right() - 640, cur_geom.left() + 40),
                min(avail.bottom() - 400, cur_geom.top() + 40),
                cur_geom.width(),
                cur_geom.height()
            )
        new_win.show()
        new_win.activateWindow()
        new_win.show_osd(f"🗔 새 플레이어 창 #{len(UnifiedMediaPlayer.ACTIVE_INSTANCES)} 생성됨")

    def _ensure_player_window_count(self, required_count: int, close_excess: bool = False):
        alive = [w for w in UnifiedMediaPlayer.ACTIVE_INSTANCES if not w._is_cleaned_up]
        while len(alive) < required_count:
            new_win = UnifiedMediaPlayer()
            new_win.show()
            alive.append(new_win)

        if close_excess and len(alive) > required_count:
            ordered = [self] + [w for w in alive if w is not self]
            to_keep = ordered[:required_count]
            for w in list(alive):
                if w not in to_keep:
                    w._cleanup_instance_resources()
                    w.close()
            alive = to_keep

        return alive[:required_count]

    def apply_grid_preset(self, preset_code: str):
        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        ax, ay, aw, ah = avail.x(), avail.y(), avail.width(), avail.height()

        if preset_code == "grid_1":
            rects = [QRect(ax, ay, aw, ah)]
            label = "1) 단일 전체 창 배치"
        elif preset_code == "grid_2h":
            w2 = aw // 2
            rects = [
                QRect(ax, ay, w2, ah),
                QRect(ax + w2, ay, aw - w2, ah),
            ]
            label = "2) 좌우 2분할 (1×2) 배치"
        elif preset_code == "grid_3h":
            w3 = aw // 3
            rects = [
                QRect(ax, ay, w3, ah),
                QRect(ax + w3, ay, w3, ah),
                QRect(ax + w3 * 2, ay, aw - w3 * 2, ah),
            ]
            label = "3) 울트라와이드 3분할 (1×3) 배치"
        elif preset_code == "grid_4q":
            w2 = aw // 2
            h2 = ah // 2
            rects = [
                QRect(ax, ay, w2, h2),
                QRect(ax + w2, ay, aw - w2, h2),
                QRect(ax, ay + h2, w2, ah - h2),
                QRect(ax + w2, ay + h2, aw - w2, ah - h2),
            ]
            label = "4) 4분할 쿼드뷰 (2×2) 배치"
        else:
            return

        target_wins = self._ensure_player_window_count(len(rects), close_excess=False)
        for win, r in zip(target_wins, rects):
            if win.isFullScreen() or win.isMaximized():
                win.showNormal()
            win.setGeometry(r)
            win.show()
            win.raise_()
            QTimer.singleShot(25, win._force_layout_sync)

        self.activateWindow()
        self.show_osd(f"📐 화면 분할 적용 완료: {label}", duration=3000)

    def capture_and_save_current_layout(self, parent_widget=None) -> bool:
        alive = [w for w in UnifiedMediaPlayer.ACTIVE_INSTANCES if w.isVisible() and not w._is_cleaned_up]
        if not alive:
            return False

        default_name = f"레이아웃 {len(UnifiedMediaPlayer.SHARED_LAYOUTS) + 1} ({len(alive)}창 묶음)"
        name, ok = QInputDialog.getText(
            parent_widget or self,
            "💾 현재 창 배치 묶음 저장",
            f"현재 열려 있는 플레이어 창 {len(alive)}개의 위치·크기 묶음을 저장합니다.\n(방송 URL은 저장하지 않고 순수 창 배치만 기록합니다)\n\n레이아웃 이름:",
            QLineEdit.EchoMode.Normal,
            default_name
        )
        if not ok or not name.strip():
            return False

        alive.sort(key=lambda w: (w.frameGeometry().top(), w.frameGeometry().left()))

        win_records = []
        for w in alive:
            g = w.frameGeometry()
            scr = w.screen() or QApplication.primaryScreen()
            avail = scr.availableGeometry() if scr else QRect(0, 0, 1920, 1080)
            aw = max(1, avail.width())
            ah = max(1, avail.height())
            win_records.append({
                "rx": round((g.x() - avail.x()) / aw, 4),
                "ry": round((g.y() - avail.y()) / ah, 4),
                "rw": round(g.width() / aw, 4),
                "rh": round(g.height() / ah, 4),
                "x": g.x(),
                "y": g.y(),
                "w": g.width(),
                "h": g.height(),
            })

        new_entry = {
            "name": name.strip(),
            "windows": win_records
        }
        UnifiedMediaPlayer.SHARED_LAYOUTS.append(new_entry)
        self.save_layouts_to_disk()
        self.show_osd(f"💾 레이아웃 저장 완료: [{new_entry['name']}] ({len(win_records)}개 창)", duration=3000)
        return True

    def apply_saved_custom_layout(self, index: int):
        if not (0 <= index < len(UnifiedMediaPlayer.SHARED_LAYOUTS)):
            return
        entry = UnifiedMediaPlayer.SHARED_LAYOUTS[index]
        name = entry.get("name", f"레이아웃 {index + 1}")
        win_records = entry.get("windows", [])
        if not win_records:
            return

        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        ax, ay, aw, ah = avail.x(), avail.y(), avail.width(), avail.height()

        target_wins = self._ensure_player_window_count(len(win_records), close_excess=True)
        for win, rec in zip(target_wins, win_records):
            if win.isFullScreen() or win.isMaximized():
                win.showNormal()
            if "rx" in rec and "rw" in rec:
                x = ax + int(round(rec["rx"] * aw))
                y = ay + int(round(rec["ry"] * ah))
                w = max(360, int(round(rec["rw"] * aw)))
                h = max(220, int(round(rec["rh"] * ah)))
            else:
                x = int(rec.get("x", ax))
                y = int(rec.get("y", ay))
                w = max(360, int(rec.get("w", 800)))
                h = max(220, int(rec.get("h", 600)))

            win.setGeometry(x, y, w, h)
            win.show()
            win.raise_()
            QTimer.singleShot(25, win._force_layout_sync)

        self.activateWindow()
        self.show_osd(f"📐 [{name}] 레이아웃 배치 적용 ({len(win_records)}개 창)", duration=3000)

    def save_layouts_to_disk(self):
        safe_save_json(self.layouts_file, UnifiedMediaPlayer.SHARED_LAYOUTS)

    def export_layouts_to_file(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "레이아웃 묶음 백업 파일 저장",
            os.path.join(get_data_root_dir(), "my_layouts_backup.json"),
            "JSON Files (*.json);;All Files (*.*)"
        )
        if not file_path:
            return
        safe_save_json(file_path, UnifiedMediaPlayer.SHARED_LAYOUTS)
        self.show_osd(f"📤 레이아웃 백업 저장 완료: {os.path.basename(file_path)}", duration=3500)

    def import_layouts_from_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "레이아웃 묶음 백업 파일 불러오기",
            get_data_root_dir(),
            "JSON Files (*.json *.bak);;All Files (*.*)"
        )
        if not file_path:
            return
        loaded = safe_load_json(file_path, None)
        if not isinstance(loaded, list):
            QMessageBox.warning(self, "불러오기 실패", "유효한 레이아웃 JSON 파일이 아닙니다.")
            return

        valid_items = [
            item for item in loaded
            if isinstance(item, dict) and isinstance(item.get("windows"), list)
        ]
        if not valid_items:
            QMessageBox.warning(self, "불러오기 확인", "파일 내에 저장된 레이아웃 묶음 데이터가 없습니다.")
            return

        existing_names = {x.get("name") for x in UnifiedMediaPlayer.SHARED_LAYOUTS}
        for item in valid_items:
            if item.get("name") in existing_names:
                for idx, ex in enumerate(UnifiedMediaPlayer.SHARED_LAYOUTS):
                    if ex.get("name") == item.get("name"):
                        UnifiedMediaPlayer.SHARED_LAYOUTS[idx] = item
                        break
            else:
                UnifiedMediaPlayer.SHARED_LAYOUTS.append(item)

        self.save_layouts_to_disk()
        self.show_osd(
            f"📥 레이아웃 불러오기 완료 (총 {len(UnifiedMediaPlayer.SHARED_LAYOUTS)}개 등록됨)",
            duration=3500
        )

    def open_manage_layouts_dialog(self):
        dlg = ManageLayoutsDialog(self)
        dlg.exec()

    def _show_layout_quick_menu(self):
        menu = QMenu(self)
        self._populate_layout_menu(menu)
        btn_pos = self.btn_layout_quick.mapToGlobal(QPoint(0, -menu.sizeHint().height()))
        menu.exec(btn_pos)

    def _populate_layout_menu(self, layout_menu: QMenu):
        layout_menu.addAction("🗔 새 플레이어 창 추가 열기\tCtrl+N", self.spawn_new_player_window)
        layout_menu.addSeparator()
        layout_menu.addAction("⚡ 1) 단일 전체 창 배치 (1×1)\tAlt+1", lambda: self.apply_grid_preset("grid_1"))
        layout_menu.addAction("⚡ 2) 좌우 2분할 배치 (1×2)\tAlt+2", lambda: self.apply_grid_preset("grid_2h"))
        layout_menu.addAction("⚡ 3) 울트라와이드 3분할 배치 (1×3)\tAlt+3", lambda: self.apply_grid_preset("grid_3h"))
        layout_menu.addAction("⚡ 4) 4분할 쿼드뷰 배치 (2×2)\tAlt+4", lambda: self.apply_grid_preset("grid_4q"))
        layout_menu.addSeparator()
        layout_menu.addAction("💾 현재 열려있는 창 배치 묶음으로 등록...", self.capture_and_save_current_layout)
        layout_menu.addAction("🗂 레이아웃 묶음 관리 및 백업/복원...", self.open_manage_layouts_dialog)

        if UnifiedMediaPlayer.SHARED_LAYOUTS:
            layout_menu.addSeparator()
            for idx, item in enumerate(UnifiedMediaPlayer.SHARED_LAYOUTS):
                l_name = item.get("name", f"레이아웃 {idx + 1}")
                w_cnt = len(item.get("windows", []))
                layout_menu.addAction(
                    f"📐 [{idx + 1}] {l_name} ({w_cnt}창 묶음)",
                    lambda checked=False, i=idx: self.apply_saved_custom_layout(i)
                )

    def _get_snap_target_rects(self, exclude_widget=None) -> list:
        targets = []
        screen = self.screen() or QApplication.primaryScreen()
        if screen:
            targets.append(screen.availableGeometry())

        for inst in UnifiedMediaPlayer.ACTIVE_INSTANCES:
            if inst is not exclude_widget and inst.isVisible() and not inst.isMinimized():
                targets.append(inst.frameGeometry())
            for panel in inst._all_managed_panels():
                if (
                    panel is not None
                    and panel is not exclude_widget
                    and panel.isVisible()
                    and panel.mode in ("bottom", "floating")
                ):
                    targets.append(panel.frameGeometry())
        return targets

    def _position_initial_window(self):
        if len(UnifiedMediaPlayer.ACTIVE_INSTANCES) == 1:
            screen = QApplication.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                x = avail.x() + (avail.width() - self.width()) // 2
                y = avail.y() + (avail.height() - self.height()) // 2
                self.move(x, y)

    def _sort_streamers(self):
        if UnifiedMediaPlayer.SHARED_STREAMERS is None:
            return
        UnifiedMediaPlayer.SHARED_STREAMERS.sort(
            key=lambda x: (
                0 if x.get("platform", "CHZZK") == "CHZZK" else 1,
                x.get("name", "").lower()
            )
        )

    def save_and_refresh_streamers(self):
        self._sort_streamers()
        safe_save_json(self.streamers_file, UnifiedMediaPlayer.SHARED_STREAMERS)

        for inst in UnifiedMediaPlayer.ACTIVE_INSTANCES:
            inst._refresh_streamer_ui()

    def export_streamers_to_file(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "스트리머 즐겨찾기 백업 파일 저장",
            os.path.join(get_data_root_dir(), "my_streamers_backup.json"),
            "JSON Files (*.json);;All Files (*.*)"
        )
        if not file_path:
            return
        safe_save_json(file_path, UnifiedMediaPlayer.SHARED_STREAMERS)
        self.show_osd(
            f"📤 즐겨찾기 {len(UnifiedMediaPlayer.SHARED_STREAMERS)}명 백업 완료: {os.path.basename(file_path)}",
            duration=3500
        )

    def import_streamers_from_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "스트리머 즐겨찾기 백업 파일 불러오기",
            get_data_root_dir(),
            "JSON & Backup Files (*.json *.bak);;All Files (*.*)"
        )
        if not file_path:
            return
        loaded = safe_load_json(file_path, None)
        if not isinstance(loaded, list):
            QMessageBox.warning(self, "불러오기 실패", "유효한 즐겨찾기 JSON 파일이 아닙니다.")
            return

        valid_items = [
            item for item in loaded
            if isinstance(item, dict) and item.get("name") and item.get("url")
        ]
        if not valid_items:
            QMessageBox.warning(self, "불러오기 확인", "파일 내에 유효한 스트리머 정보가 없습니다.")
            return

        existing_urls = {x.get("url", "").strip(): idx for idx, x in enumerate(UnifiedMediaPlayer.SHARED_STREAMERS)}
        for item in valid_items:
            u = item.get("url", "").strip()
            entry = {
                "platform": item.get("platform", "CHZZK"),
                "name": item.get("name", "").strip(),
                "url": u,
            }
            if u in existing_urls:
                UnifiedMediaPlayer.SHARED_STREAMERS[existing_urls[u]] = entry
            else:
                UnifiedMediaPlayer.SHARED_STREAMERS.append(entry)

        self.save_and_refresh_streamers()
        self.show_osd(
            f"📥 즐겨찾기 불러오기 완료 (총 {len(UnifiedMediaPlayer.SHARED_STREAMERS)}명 등록됨)",
            duration=3500
        )

    def _refresh_streamer_ui(self):
        if not hasattr(self, "streamer_list_widget") or self.streamer_list_widget is None:
            return
        self.streamer_list_widget.clear()

        for plat_code, plat_title, header_color in (
            ("CHZZK", "⚡ [CHZZK] 치지직 스트리머", "#00ffa3"),
            ("SOOP", "🌲 [SOOP] 숲 스트리머", "#00e5ff"),
        ):
            group = [s for s in UnifiedMediaPlayer.SHARED_STREAMERS if s.get("platform") == plat_code]
            header_item = QListWidgetItem(f"{plat_title} ({len(group)})")
            header_item.setFlags(Qt.ItemFlag.NoItemFlags)
            header_item.setForeground(QBrush(QColor(header_color)))
            header_item.setBackground(QBrush(QColor("#1c1c26")))
            self.streamer_list_widget.addItem(header_item)

            if not group:
                empty_item = QListWidgetItem("   (등록된 스트리머 없음)")
                empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
                empty_item.setForeground(QBrush(QColor("#666677")))
                self.streamer_list_widget.addItem(empty_item)
            else:
                for s in group:
                    name = s.get("name", "")
                    url = s.get("url", "")
                    item = QListWidgetItem(f"  [{plat_code}]  {name}")
                    item.setToolTip(f"{name}\n주소: {url}\n(더블클릭 시 라이브 즉시 연결)")
                    item.setData(Qt.ItemDataRole.UserRole, s)
                    self.streamer_list_widget.addItem(item)

    def open_add_streamer_dialog(self):
        default_u = self.current_web_url if self.current_web_url else ""
        dlg = AddStreamerDialog(self, default_url=default_u)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            res = dlg.get_result()
            UnifiedMediaPlayer.SHARED_STREAMERS.append(res)
            self.save_and_refresh_streamers()
            self.show_osd(f"⭐ 스트리머 등록 완료: [{res['platform']}] {res['name']}", duration=3000)
            if not self.streamer_panel.isVisible():
                self.streamer_panel.show_panel()
                QTimer.singleShot(25, self._force_layout_sync)

    def open_manage_streamers_dialog(self):
        dlg = ManageStreamersDialog(self)
        dlg.exec()

    def toggle_streamer_panel(self):
        if self.streamer_panel.isVisible():
            self.streamer_panel.hide_panel()
            self.show_osd("⭐ 스트리머 즐겨찾기 창 숨김 (B 키로 다시 열기)")
        else:
            self._refresh_streamer_ui()
            self.streamer_panel.show_panel()
            self.show_osd("⭐ 스트리머 즐겨찾기 목록 열림 (더블클릭으로 방송 연결)")
        QTimer.singleShot(25, self._force_layout_sync)

    def _on_streamer_item_double_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data or not isinstance(data, dict):
            return
        url = data.get("url", "").strip()
        name = data.get("name", "")
        plat = data.get("platform", "")
        if url:
            self.load_stream_url_directly(url, display_label=f"[{plat}] {name}")

    def load_stream_url_directly(self, raw_url: str, display_label: str = ""):
        if not raw_url:
            return
        if not raw_url.startswith(("http://", "https://")):
            raw_url = "https://" + raw_url

        self.image_timer.stop()
        self.player.stop()
        self.image_view.clear_view()
        self.current_web_url = raw_url
        self.current_chat_url = ""
        self.is_live_stream_playing = False

        label_info = f" ({display_label})" if display_label else ""
        self.show_osd(f"⏳ 라이브 스트림 및 채팅 연결 중{label_info}...", duration=5000)

        self.stream_resolver = StreamlinkResolverThread(raw_url, self)
        self.stream_resolver.resolved.connect(self._on_streamlink_resolved)
        self.stream_resolver.failed.connect(self._on_streamlink_failed)
        self.stream_resolver.start()

    def _init_web_profiles(self):
        if UnifiedMediaPlayer.SHARED_WEB_PROFILE is None:
            profile_dir = os.path.join(get_data_root_dir(), "web_profile")
            os.makedirs(profile_dir, exist_ok=True)
            prof = QWebEngineProfile("MinimalPlayerMainProfile", QApplication.instance())
            prof.setPersistentStoragePath(profile_dir)
            prof.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
            prof.setHttpUserAgent(CHROME_UA)

            s = prof.settings()
            s.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
            s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.AllowWindowActivationFromJavaScript, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

            UnifiedMediaPlayer.SHARED_WEB_PROFILE = prof

        self.web_profile = UnifiedMediaPlayer.SHARED_WEB_PROFILE
        self.chat_profile = UnifiedMediaPlayer.SHARED_WEB_PROFILE

    def toggle_login_drawer(self, platform_key: str):
        if self.login_drawer_container.isVisible() and self._active_login_platform == platform_key:
            self.close_login_drawer()
            return

        target_url = LOGIN_URLS.get(platform_key, "")
        if not target_url:
            return

        self._active_login_platform = platform_key
        self.login_web_view.load(QUrl(target_url))
        self.login_drawer_container.show()
        self.btn_fold_login.show()
        self._update_login_bar_styles()
        self.show_osd(f"🔑 [{platform_key}] 로그인 창이 열렸습니다. 로그인 후 [▲접기]를 누르세요.", duration=3000)

    def close_login_drawer(self):
        self._active_login_platform = None
        self.login_drawer_container.hide()
        self.btn_fold_login.hide()
        self._update_login_bar_styles()

        if self.current_chat_url:
            self._connect_live_chat(self.current_web_url, self.current_chat_url)
            self.show_osd("🔄 로그인 세션이 채팅창에 반영되었습니다.", duration=2500)

    def _update_login_bar_styles(self):
        active_qss = (
            "QPushButton { background-color: #00e5ff; color: #000000; "
            "border: 1px solid #00e5ff; border-radius: 4px; font-size: 11px; font-weight: bold; padding: 2px 7px; }"
        )
        inactive_qss = (
            "QPushButton { background-color: #20202b; color: #d1d5db; "
            "border: 1px solid #343446; border-radius: 4px; font-size: 11px; font-weight: bold; padding: 2px 7px; }"
            "QPushButton:hover { background-color: #00e5ff; color: #000000; }"
        )
        for key, btn in (
            ("NAVER", self.btn_login_naver),
            ("SOOP", self.btn_login_soop),
            ("GOOGLE", self.btn_login_google),
        ):
            btn.setStyleSheet(active_qss if self._active_login_platform == key else inactive_qss)

    def _connect_live_chat(self, stream_page_url: str, chat_url: str):
        target_url = chat_url or (normalize_stream_url(stream_page_url) if stream_page_url else "")
        if not target_url:
            return

        self.current_chat_url = target_url
        self.chat_web_page.setAudioMuted(True)
        self.chat_web_view.load(QUrl(target_url))

    def _on_chat_view_load_finished(self, ok: bool):
        cur_url = self.chat_web_view.url().toString()
        if is_soop_url(cur_url):
            self.chat_web_page.setAudioMuted(True)
            self.chat_web_page.runJavaScript(SOOP_CHAT_DOM_MASK_JS)

    def reload_current_chat(self):
        if self.current_chat_url:
            if is_soop_url(self.current_web_url or self.current_chat_url):
                self.current_chat_url = normalize_stream_url(self.current_web_url or self.current_chat_url)
            self._connect_live_chat(self.current_web_url, self.current_chat_url)
            self.show_osd("↻ 라이브 채팅창 새로고침 중...", duration=2000)
        else:
            self.chat_web_view.reload()

    def _init_global_shortcuts(self):
        sc_new_win = QShortcut(QKeySequence("Ctrl+N"), self)
        sc_new_win.setContext(Qt.ShortcutContext.WindowShortcut)
        sc_new_win.activated.connect(self.spawn_new_player_window)

        for key_str, preset_code in (
            ("Alt+1", "grid_1"),
            ("Alt+2", "grid_2h"),
            ("Alt+3", "grid_3h"),
            ("Alt+4", "grid_4q"),
        ):
            sc_grid = QShortcut(QKeySequence(key_str), self)
            sc_grid.setContext(Qt.ShortcutContext.WindowShortcut)
            sc_grid.activated.connect(lambda c=preset_code: self.apply_grid_preset(c))

        self._bind_non_conflicting_shortcut("L", self.toggle_chat_panel)
        self._bind_non_conflicting_shortcut("B", self.toggle_streamer_panel)
        self._bind_non_conflicting_shortcut("U", self.open_url_popup)
        self._bind_non_conflicting_shortcut("G", self.open_jump_popup)
        self._bind_non_conflicting_shortcut("I", self.open_slideshow_interval_popup)
        self._bind_non_conflicting_shortcut("[", lambda: self.prev_media(force=True))
        self._bind_non_conflicting_shortcut("]", lambda: self.next_media(force=True))

    def _init_media_core(self):
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.7)

        self.player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.errorOccurred.connect(self._on_player_error)

    def _on_player_error(self, error, error_string):
        if error != QMediaPlayer.Error.NoError:
            self.show_osd(f"⚠ 미디어 재생 오류: {error_string}", duration=3500)

    def _init_sound_effect(self):
        self.sound_path = os.path.join(get_data_root_dir(), "assets", "transition.wav")
        ensure_default_transition_sound(self.sound_path)

        self.transition_sound = QSoundEffect(self)
        if os.path.exists(self.sound_path):
            self.transition_sound.setSource(QUrl.fromLocalFile(self.sound_path))
            self.transition_sound.setVolume(0.65)

    def play_transition_sfx(self):
        if self.transition_sound.source().isValid():
            if self.transition_sound.isPlaying():
                self.transition_sound.stop()
            self.transition_sound.play()

    def _get_custom_seek_str(self) -> str:
        if float(self.custom_seek_sec).is_integer():
            return str(int(self.custom_seek_sec))
        return f"{self.custom_seek_sec:.1f}"

    def _get_interval_sec_str(self) -> str:
        sec = self.image_slideshow_interval / 1000.0
        if sec.is_integer():
            return str(int(sec))
        return f"{sec:.1f}"

    def _build_startup_command(self, target_media_path: str) -> str:
        norm_media = os.path.abspath(target_media_path)
        if getattr(sys, 'frozen', False):
            exe_path = os.path.abspath(sys.executable)
            return f'"{exe_path}" "{norm_media}"'
        else:
            py_exe = os.path.abspath(sys.executable)
            pyw_exe = os.path.join(os.path.dirname(py_exe), "pythonw.exe")
            runner = pyw_exe if os.path.exists(pyw_exe) else py_exe
            script_path = os.path.abspath(__file__)
            return f'"{runner}" "{script_path}" "{norm_media}"'

    def get_startup_registered_file(self) -> str:
        if not HAS_WINREG:
            return ""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_PATH, 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, STARTUP_APP_NAME)
                matches = re.findall(r'"([^"]+)"', str(val))
                if matches:
                    return matches[-1]
                return str(val)
        except FileNotFoundError:
            return ""
        except Exception:
            return ""

    def set_startup_auto_play(self, file_path: str):
        if not HAS_WINREG:
            self.show_osd("⚠ Windows 환경에서만 지원하는 기능입니다")
            return
        if not file_path or not os.path.isfile(file_path):
            self.show_osd("⚠ 유효한 파일이 아닙니다")
            return
        try:
            cmd = self._build_startup_command(file_path)
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, STARTUP_APP_NAME, 0, winreg.REG_SZ, cmd)
            self.show_osd(f"🚀 부팅 시 자동 재생 등록 완료: {os.path.basename(file_path)}", duration=3500)
        except Exception as e:
            self.show_osd(f"⚠ 레지스트리 등록 실패: {e}", duration=3500)

    def register_current_file_for_startup(self):
        if 0 <= self.current_index < len(self.playlist):
            cur_file = self.playlist[self.current_index]
            self.set_startup_auto_play(cur_file)
        else:
            self.show_osd("⚠ 현재 재생 중인 로컬 파일이 없습니다. 먼저 파일을 재생하거나 직접 선택해 주세요.")

    def select_and_register_startup_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "부팅 시 자동 재생할 음악/미디어 파일 선택", "",
            "Media & Audio Files (*.mp3 *.wav *.flac *.ogg *.m4a *.aac *.wma *.opus *.mp4 *.mkv *.avi *.mov *.webm);;All Files (*.*)"
        )
        if file_path:
            self.set_startup_auto_play(file_path)

    def remove_startup_auto_play(self):
        if not HAS_WINREG:
            return
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, STARTUP_APP_NAME)
            self.show_osd("❌ 부팅 시 자동 실행 설정이 해제되었습니다", duration=3000)
        except FileNotFoundError:
            self.show_osd("ℹ 현재 등록된 부팅 자동 실행 설정이 없습니다")
        except Exception as e:
            self.show_osd(f"⚠ 해제 실패: {e}")

    def _init_ui(self):
        self.central_widget = QWidget(self)
        self.central_widget.setMouseTracking(True)
        self.setCentralWidget(self.central_widget)

        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.stack = QStackedWidget(self)
        self.stack.setMouseTracking(True)
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.guide_label = QLabel(
            "파일(MP4, MKV, MP3, FLAC, JPG 등)이나 폴더를 드래그 앤 드롭하세요 (우클릭: 그룹별 통합 메뉴)\n"
            "💡 [Alt + 1 / 2 / 3 / 4] 원클릭 화면 분할 (단일 / 좌우 2분할 / 3분할 / 4분할 쿼드뷰)\n"
            "💡 [채팅창 상단 로그인 허브] 네이버(치지직) · SOOP · 구글(유튜브) 1회 로그인 시 영구 유지 & 채팅 입력 지원\n\n"
            "[Ctrl + N] 새 플레이어 창 열기   |   [B] 스트리머 즐겨찾기 (백업/복원)   |   [L] 라이브 채팅창\n"
            "[← / →] 3초 탐색(이미지 넘김)   |   [Shift + ← / →] 설정 초 탐색 (기본 89초)   |   [G] 탐색 단위 설정\n"
            "[1 / 2 / 3 / 4] 이미지 전환 효과   |   [I] 이미지 자동넘김 시간 설정   |   [Tab] 재생목록"
        )
        self.guide_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.guide_label.setStyleSheet("color: #666666; font-size: 14px; line-height: 170%;")
        self.guide_label.setMouseTracking(True)
        self.stack.addWidget(self.guide_label)

        self.image_view = AnimatedGraphicsView(self)
        self.stack.addWidget(self.image_view)

        self.video_widget = QVideoWidget(self)
        self.video_widget.setMouseTracking(True)
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.player.setVideoOutput(self.video_widget)
        self.stack.addWidget(self.video_widget)

        self.web_view = QWebEngineView(self)
        self.web_view.setPage(QWebEnginePage(self.web_profile, self.web_view))
        self.web_view.setMouseTracking(True)
        self.web_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.web_view.page().setBackgroundColor(QColor("#0f0f0f"))
        self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.web_view.customContextMenuRequested.connect(
            lambda pos: self.show_context_menu(self.web_view.mapToGlobal(pos))
        )
        self.web_view.urlChanged.connect(self._on_web_url_changed)
        self.stack.addWidget(self.web_view)

        self.audio_cover_label = QLabel(self)
        self.audio_cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.audio_cover_label.setMouseTracking(True)
        self.audio_cover_label.setStyleSheet(
            "background-color: #0d0d12; color: #00e5ff; font-size: 20px; font-weight: bold; line-height: 180%;"
        )
        self.stack.addWidget(self.audio_cover_label)

        self.main_layout.addWidget(self.stack, stretch=1)

        # 1. 라이브 채팅 패널
        self.chat_panel = DetachablePanel(self, "💬 라이브 채팅", default_dock_width=360)

        ch_reload_btn = QPushButton("↻", self.chat_panel.header)
        ch_reload_btn.setFixedSize(24, 24)
        ch_reload_btn.setToolTip("채팅창 및 세션 새로고침")
        ch_reload_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #aaa; border: none; font-size: 14px; } "
            "QPushButton:hover { color: #00e5ff; }"
        )
        ch_reload_btn.clicked.connect(self.reload_current_chat)
        self.chat_panel.add_Header_Extra_Button(ch_reload_btn)

        self.chat_body_widget = QWidget(self.chat_panel)
        chat_body_layout = QVBoxLayout(self.chat_body_widget)
        chat_body_layout.setContentsMargins(0, 0, 0, 0)
        chat_body_layout.setSpacing(0)

        self.login_bar = QWidget(self.chat_body_widget)
        self.login_bar.setFixedHeight(30)
        self.login_bar.setStyleSheet(
            "background-color: #15151e; border-bottom: 1px solid #282836; border-left: 2px solid #2a2a38;"
        )
        lb_layout = QHBoxLayout(self.login_bar)
        lb_layout.setContentsMargins(8, 2, 8, 2)
        lb_layout.setSpacing(4)

        lbl_login_tag = QLabel("🔑 로그인:", self.login_bar)
        lbl_login_tag.setStyleSheet("color: #9ca3af; font-size: 11px; font-weight: bold; border: none;")
        lb_layout.addWidget(lbl_login_tag)

        self.btn_login_naver = QPushButton("⚡네이버", self.login_bar)
        self.btn_login_naver.setToolTip("치지직(네이버) 로그인 창 열기/닫기")
        self.btn_login_naver.clicked.connect(lambda: self.toggle_login_drawer("NAVER"))

        self.btn_login_soop = QPushButton("🌲SOOP", self.login_bar)
        self.btn_login_soop.setToolTip("SOOP(숲) 로그인 창 열기/닫기")
        self.btn_login_soop.clicked.connect(lambda: self.toggle_login_drawer("SOOP"))

        self.btn_login_google = QPushButton("🔴구글", self.login_bar)
        self.btn_login_google.setToolTip("유튜브(구글) 로그인 창 열기/닫기")
        self.btn_login_google.clicked.connect(lambda: self.toggle_login_drawer("GOOGLE"))

        self.btn_fold_login = QPushButton("▲접기", self.login_bar)
        self.btn_fold_login.setToolTip("로그인 창을 접고 채팅창 새로고침")
        self.btn_fold_login.setStyleSheet(
            "QPushButton { background-color: #ff5555; color: #ffffff; border: none; "
            "border-radius: 4px; font-size: 11px; font-weight: bold; padding: 2px 6px; }"
        )
        self.btn_fold_login.clicked.connect(self.close_login_drawer)
        self.btn_fold_login.hide()

        lb_layout.addWidget(self.btn_login_naver)
        lb_layout.addWidget(self.btn_login_soop)
        lb_layout.addWidget(self.btn_login_google)
        lb_layout.addStretch()
        lb_layout.addWidget(self.btn_fold_login)
        chat_body_layout.addWidget(self.login_bar)

        self.login_drawer_container = QWidget(self.chat_body_widget)
        self.login_drawer_container.setFixedHeight(260)
        self.login_drawer_container.setStyleSheet("border-bottom: 2px solid #00e5ff;")
        ld_layout = QVBoxLayout(self.login_drawer_container)
        ld_layout.setContentsMargins(0, 0, 0, 0)
        ld_layout.setSpacing(0)

        self.login_web_view = QWebEngineView(self.login_drawer_container)
        self.login_web_view.setPage(QWebEnginePage(self.web_profile, self.login_web_view))
        self.login_web_view.page().setBackgroundColor(QColor("#16161d"))
        ld_layout.addWidget(self.login_web_view)
        self.login_drawer_container.hide()
        chat_body_layout.addWidget(self.login_drawer_container)

        self.chat_web_view = QWebEngineView(self.chat_body_widget)
        self.chat_web_page = QWebEnginePage(self.chat_profile, self.chat_web_view)
        self.chat_web_page.setAudioMuted(True)

        mask_script = QWebEngineScript()
        mask_script.setName("SoopMainPageChatMask")
        mask_script.setSourceCode(SOOP_CHAT_DOM_MASK_JS)
        mask_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        mask_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        mask_script.setRunsOnSubFrames(False)
        self.chat_web_page.scripts().insert(mask_script)

        self.chat_web_view.setPage(self.chat_web_page)
        self.chat_web_view.page().setBackgroundColor(QColor("#121216"))
        self.chat_web_view.loadFinished.connect(self._on_chat_view_load_finished)
        self.chat_web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chat_web_view.customContextMenuRequested.connect(
            lambda pos: self.show_context_menu(self.chat_web_view.mapToGlobal(pos))
        )
        chat_body_layout.addWidget(self.chat_web_view, stretch=1)

        self._update_login_bar_styles()
        self.chat_panel.set_content_widget(self.chat_body_widget)
        self.chat_panel.hide()
        self.main_layout.addWidget(self.chat_panel, stretch=0)

        # 2. 스트리머 즐겨찾기 패널
        self.streamer_panel = DetachablePanel(self, "⭐ 즐겨찾기", default_dock_width=330)

        st_add_btn = QPushButton("＋", self.streamer_panel.header)
        st_add_btn.setFixedSize(24, 24)
        st_add_btn.setToolTip("새 스트리머 등록")
        st_add_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #00e5ff; border: none; font-size: 15px; font-weight: bold; } "
            "QPushButton:hover { color: #ffffff; }"
        )
        st_add_btn.clicked.connect(self.open_add_streamer_dialog)

        st_imp_btn = QPushButton("📥", self.streamer_panel.header)
        st_imp_btn.setFixedSize(24, 24)
        st_imp_btn.setToolTip("백업 파일에서 즐겨찾기 불러오기 (Import)")
        st_imp_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #aaa; border: none; font-size: 13px; } "
            "QPushButton:hover { color: #00e5ff; }"
        )
        st_imp_btn.clicked.connect(self.import_streamers_from_file)

        st_exp_btn = QPushButton("📤", self.streamer_panel.header)
        st_exp_btn.setFixedSize(24, 24)
        st_exp_btn.setToolTip("즐겨찾기 목록을 파일로 백업 저장 (Export)")
        st_exp_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #aaa; border: none; font-size: 13px; } "
            "QPushButton:hover { color: #00e5ff; }"
        )
        st_exp_btn.clicked.connect(self.export_streamers_to_file)

        st_mgr_btn = QPushButton("⚙", self.streamer_panel.header)
        st_mgr_btn.setFixedSize(24, 24)
        st_mgr_btn.setToolTip("즐겨찾기 통합 관리 (추가/수정/삭제/백업)")
        st_mgr_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #aaa; border: none; font-size: 13px; } "
            "QPushButton:hover { color: #00e5ff; }"
        )
        st_mgr_btn.clicked.connect(self.open_manage_streamers_dialog)

        self.streamer_panel.add_Header_Extra_Button(st_mgr_btn)
        self.streamer_panel.add_Header_Extra_Button(st_exp_btn)
        self.streamer_panel.add_Header_Extra_Button(st_imp_btn)
        self.streamer_panel.add_Header_Extra_Button(st_add_btn)

        self.streamer_list_widget = QListWidget(self.streamer_panel)
        self.streamer_list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.streamer_list_widget.itemDoubleClicked.connect(self._on_streamer_item_double_clicked)
        self.streamer_list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.streamer_list_widget.customContextMenuRequested.connect(
            lambda pos: self.show_context_menu(self.streamer_list_widget.mapToGlobal(pos))
        )

        self.streamer_panel.set_content_widget(self.streamer_list_widget)
        self.streamer_panel.hide()
        self.main_layout.addWidget(self.streamer_panel, stretch=0)

        # 3. 재생목록 패널
        self.playlist_panel = DetachablePanel(self, "📋 재생목록", default_dock_width=320)
        self.playlist_widget = QListWidget(self.playlist_panel)
        self.playlist_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.playlist_widget.itemDoubleClicked.connect(self._on_playlist_item_double_clicked)
        self.playlist_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.playlist_widget.customContextMenuRequested.connect(
            lambda pos: self.show_context_menu(self.playlist_widget.mapToGlobal(pos))
        )

        self.playlist_panel.set_content_widget(self.playlist_widget)
        self.playlist_panel.hide()
        self.main_layout.addWidget(self.playlist_panel, stretch=0)

    def _create_toolbar_separator(self) -> QFrame:
        sep = QFrame(self.cb_container)
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedWidth(1)
        sep.setFixedHeight(22)
        sep.setStyleSheet("background-color: rgba(255, 255, 255, 45); border: none;")
        return sep

    def _init_top_level_overlays(self):
        overlay_flags_no_focus = (
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        overlay_flags_focusable = (
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )

        self.osd_window = QWidget(self)
        self.osd_window.setWindowFlags(overlay_flags_no_focus)
        self.osd_window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.osd_window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        osd_layout = QVBoxLayout(self.osd_window)
        osd_layout.setContentsMargins(0, 0, 0, 0)

        self.osd_label = QLabel(self.osd_window)
        self.osd_label.setStyleSheet("""
            background-color: rgba(18, 18, 24, 230);
            color: #00e5ff;
            font-size: 14px;
            font-weight: bold;
            padding: 8px 16px;
            border-radius: 6px;
            border: 1px solid rgba(0, 229, 255, 80);
        """)
        osd_layout.addWidget(self.osd_label)
        self.osd_window.hide()

        self.osd_timer = QTimer(self)
        self.osd_timer.setSingleShot(True)
        self.osd_timer.timeout.connect(self.osd_window.hide)

        popup_qss = """
            QLineEdit {
                background-color: rgba(20, 20, 28, 248);
                color: #ffffff;
                font-size: 15px;
                font-weight: bold;
                border: 2px solid #00e5ff;
                border-radius: 8px;
                padding: 6px 14px;
            }
        """

        self.jump_input = QLineEdit(self)
        self.jump_input.setWindowFlags(overlay_flags_focusable)
        self.jump_input.setPlaceholderText("탐색 단위(초) 입력 (예: 89, 30) 후 Enter")
        self.jump_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.jump_input.setFixedSize(380, 48)
        self.jump_input.setStyleSheet(popup_qss)
        self.jump_input.returnPressed.connect(self._execute_custom_jump)
        self.jump_input.installEventFilter(self)
        self.jump_input.hide()

        self.interval_input = QLineEdit(self)
        self.interval_input.setWindowFlags(overlay_flags_focusable)
        self.interval_input.setPlaceholderText("이미지 자동 넘김 시간(초) 입력 (예: 5, 3.5) 후 Enter")
        self.interval_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.interval_input.setFixedSize(420, 48)
        self.interval_input.setStyleSheet(popup_qss)
        self.interval_input.returnPressed.connect(self._execute_slideshow_interval)
        self.interval_input.installEventFilter(self)
        self.interval_input.hide()

        self.url_input = QLineEdit(self)
        self.url_input.setWindowFlags(overlay_flags_focusable)
        self.url_input.setPlaceholderText("라이브/유튜브 URL 입력 (예: play.sooplive.co.kr/... 또는 chzzk...) 후 Enter")
        self.url_input.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.url_input.setFixedSize(580, 48)
        self.url_input.setStyleSheet(popup_qss)
        self.url_input.returnPressed.connect(self._execute_url_load)
        self.url_input.installEventFilter(self)
        self.url_input.hide()

        self.control_bar = QWidget(self)
        self.control_bar.setWindowFlags(overlay_flags_no_focus)
        self.control_bar.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.control_bar.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.control_bar.setFixedHeight(58)

        cb_outer = QVBoxLayout(self.control_bar)
        cb_outer.setContentsMargins(0, 0, 0, 0)

        self.cb_container = QWidget(self.control_bar)
        self.cb_container.setStyleSheet("""
            QWidget#cbContainer {
                background-color: rgba(16, 16, 22, 235);
                border: 1px solid rgba(255, 255, 255, 38);
                border-radius: 10px;
            }
            QPushButton {
                background-color: transparent;
                color: #e5e7eb;
                border: none;
                font-size: 12px;
                font-weight: bold;
                padding: 4px 7px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: rgba(0, 229, 255, 35);
                color: #00e5ff;
            }
            QLabel {
                color: #d1d5db;
                font-size: 12px;
                font-weight: bold;
                border: none;
                background: transparent;
            }
            QSlider::groove:horizontal {
                border: none;
                height: 6px;
                background: #374151;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #00e5ff;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                border: 2px solid #00e5ff;
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
        """)
        self.cb_container.setObjectName("cbContainer")
        cb_layout = QHBoxLayout(self.cb_container)
        cb_layout.setContentsMargins(12, 6, 12, 6)
        cb_layout.setSpacing(5)

        self.btn_play_pause = QPushButton("⏸")
        self.btn_play_pause.setToolTip("재생 / 일시정지 (Space)")
        self.btn_play_pause.clicked.connect(self.toggle_play_pause)

        self.lbl_current_time = QLabel("00:00")
        self.lbl_current_time.setMinimumWidth(42)
        self.lbl_current_time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self.seek_slider.sliderMoved.connect(self._on_slider_moved)
        self.seek_slider.sliderReleased.connect(self._on_slider_released)

        self.lbl_total_time = QLabel("00:00")
        self.lbl_total_time.setMinimumWidth(42)
        self.lbl_total_time.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.btn_speed = QPushButton("1.00x")
        self.btn_speed.setToolTip("클릭 시 1.0x 복원 (C/X로 배속 조절)")
        self.btn_speed.clicked.connect(lambda: self.adjust_playback_rate(reset=True))

        self.btn_seek_unit = QPushButton(f"🎯{self._get_custom_seek_str()}s")
        self.btn_seek_unit.setToolTip("Shift+방향키 점프 단위 설정 (G)")
        self.btn_seek_unit.clicked.connect(self.open_jump_popup)

        self.btn_new_win = QPushButton("🗔새창")
        self.btn_new_win.setToolTip("새 플레이어 창 추가 열기 (Ctrl+N)")
        self.btn_new_win.clicked.connect(self.spawn_new_player_window)

        self.btn_layout_quick = QPushButton("📐분할")
        self.btn_layout_quick.setToolTip("원클릭 2분할/4분할 및 커스텀 레이아웃 묶음 메뉴 (Alt+1~4)")
        self.btn_layout_quick.clicked.connect(self._show_layout_quick_menu)

        self.btn_chat_toggle = QPushButton("💬채팅")
        self.btn_chat_toggle.setToolTip("라이브 채팅창 열기/닫기 (L)")
        self.btn_chat_toggle.clicked.connect(self.toggle_chat_panel)

        self.btn_streamer_toggle = QPushButton("⭐방송")
        self.btn_streamer_toggle.setToolTip("스트리머 즐겨찾기 열기/닫기 (B)")
        self.btn_streamer_toggle.clicked.connect(self.toggle_streamer_panel)

        self.btn_plist_toggle = QPushButton("📋목록")
        self.btn_plist_toggle.setToolTip("재생목록 열기/닫기 (Tab)")
        self.btn_plist_toggle.clicked.connect(self._toggle_playlist_panel)

        cb_layout.addWidget(self.btn_play_pause)
        cb_layout.addWidget(self.lbl_current_time)
        cb_layout.addWidget(self.seek_slider, stretch=1)
        cb_layout.addWidget(self.lbl_total_time)

        cb_layout.addWidget(self._create_toolbar_separator())

        cb_layout.addWidget(self.btn_speed)
        cb_layout.addWidget(self.btn_seek_unit)

        cb_layout.addWidget(self._create_toolbar_separator())

        cb_layout.addWidget(self.btn_new_win)
        cb_layout.addWidget(self.btn_layout_quick)

        cb_layout.addWidget(self._create_toolbar_separator())

        cb_layout.addWidget(self.btn_chat_toggle)
        cb_layout.addWidget(self.btn_streamer_toggle)
        cb_layout.addWidget(self.btn_plist_toggle)

        cb_outer.addWidget(self.cb_container)
        self.control_bar.hide()

    def _init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        icon_path = resolve_app_icon_path()
        app_icon = build_multi_size_qicon(icon_path)
        if app_icon.isNull():
            app_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)

        QApplication.instance().setWindowIcon(app_icon)
        self.tray_icon.setIcon(app_icon)
        self.setWindowIcon(app_icon)
        self.tray_icon.setToolTip("Minimal Media Player - 대기 중")

        tray_menu = QMenu()
        act_show = QAction("열기 / 포커스", self)
        act_show.triggered.connect(self._restore_from_tray)

        act_new = QAction("🗔 새 플레이어 창 열기", self)
        act_new.triggered.connect(self.spawn_new_player_window)

        act_quit = QAction("전체 종료", self)
        act_quit.triggered.connect(self.quit_all_instances)

        tray_menu.addAction(act_show)
        tray_menu.addAction(act_new)
        tray_menu.addSeparator()
        tray_menu.addAction(act_quit)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        if len(UnifiedMediaPlayer.ACTIVE_INSTANCES) == 1:
            self.tray_icon.show()

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #0f0f0f;
                color: #e0e0e0;
                font-family: 'Segoe UI', 'Malgun Gothic', sans-serif;
            }
            QListWidget {
                background-color: #141418;
                border: 1px solid #2a2a35;
                padding: 6px;
                font-size: 13px;
                outline: none;
            }
            QListWidget::item {
                padding: 8px 10px;
                border-radius: 4px;
                margin-bottom: 2px;
                color: #bbbbbb;
            }
            QListWidget::item:hover {
                background-color: #22222c;
            }
            QListWidget::item:selected {
                background-color: #005fb8;
                color: #ffffff;
                font-weight: bold;
            }
            QMenu {
                background-color: #18181d;
                color: #e5e7eb;
                border: 1px solid #32323c;
                border-radius: 8px;
                padding: 6px 4px;
                font-size: 13px;
            }
            QMenu::item {
                padding: 7px 26px 7px 14px;
                border-radius: 4px;
                margin: 1px 4px;
            }
            QMenu::item:selected {
                background-color: #005fb8;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background: #2c2c35;
                margin: 5px 8px;
            }
        """)

    def _all_managed_panels(self):
        return (self.chat_panel, self.streamer_panel, self.playlist_panel)

    def _detect_resize_edges(self, global_pos: QPoint) -> Qt.Edge:
        if self.isFullScreen() or self.isMaximized():
            return Qt.Edge(0)

        rect = self.frameGeometry()
        m = self.RESIZE_MARGIN

        if not rect.adjusted(-2, -2, 2, 2).contains(global_pos):
            return Qt.Edge(0)

        edges = Qt.Edge(0)
        if global_pos.x() <= rect.left() + m:
            edges |= Qt.Edge.LeftEdge
        elif global_pos.x() >= rect.right() - m:
            edges |= Qt.Edge.RightEdge

        if global_pos.y() <= rect.top() + m:
            edges |= Qt.Edge.TopEdge
        elif global_pos.y() >= rect.bottom() - m:
            edges |= Qt.Edge.BottomEdge

        return edges

    def _update_cursor_for_edges(self, edges: Qt.Edge):
        if not edges:
            self.unsetCursor()
            return

        if edges in (
            Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
            Qt.Edge.BottomEdge | Qt.Edge.RightEdge
        ):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edges in (
            Qt.Edge.TopEdge | Qt.Edge.RightEdge,
            Qt.Edge.BottomEdge | Qt.Edge.LeftEdge
        ):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edges in (Qt.Edge.LeftEdge, Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edges in (Qt.Edge.TopEdge, Qt.Edge.BottomEdge):
            self.setCursor(Qt.CursorShape.SizeVerCursor)

    def _perform_manual_resize(self, global_pos: QPoint):
        delta = global_pos - self._resize_start_global
        g = QRect(self._resize_start_geom)
        min_w, min_h = self.minimumWidth(), self.minimumHeight()

        if self._resize_edges & Qt.Edge.LeftEdge:
            new_left = g.left() + delta.x()
            if g.right() - new_left >= min_w:
                g.setLeft(new_left)
        elif self._resize_edges & Qt.Edge.RightEdge:
            new_w = g.width() + delta.x()
            if new_w >= min_w:
                g.setWidth(new_w)

        if self._resize_edges & Qt.Edge.TopEdge:
            new_top = g.top() + delta.y()
            if g.bottom() - new_top >= min_h:
                g.setTop(new_top)
        elif self._resize_edges & Qt.Edge.BottomEdge:
            new_h = g.height() + delta.y()
            if new_h >= min_h:
                g.setHeight(new_h)

        self.setGeometry(g)

    def _poll_mouse_state(self):
        if not self._ui_initialized or not self.isVisible() or self.isMinimized():
            if self.control_bar and self.control_bar.isVisible():
                self.control_bar.hide()
            return

        cursor_global = QCursor.pos()

        if not self._is_resizing and not self._active_interacting_panel and (
            QApplication.mouseButtons() == Qt.MouseButton.NoButton
        ):
            panel_edge_found = False
            for panel in self._all_managed_panels():
                if panel and panel.isVisible():
                    p_edges = panel.detect_panel_resize_edges(cursor_global)
                    if p_edges:
                        panel.update_panel_cursor(p_edges)
                        if panel.mode == "right":
                            self._update_cursor_for_edges(p_edges)
                        panel_edge_found = True
                    else:
                        panel.unsetCursor()

            if not panel_edge_found:
                main_edges = self._detect_resize_edges(cursor_global)
                if main_edges:
                    self._update_cursor_for_edges(main_edges)
                else:
                    self.unsetCursor()

        if not self.control_bar:
            return
        if self.stack.currentIndex() not in (2, 4):
            if self.control_bar.isVisible():
                self.control_bar.hide()
            return

        video_tl = self.stack.mapToGlobal(QPoint(0, 0))
        video_rect = QRect(video_tl.x(), video_tl.y(), self.stack.width(), self.stack.height())
        if video_rect.contains(cursor_global):
            bottom_threshold = video_rect.bottom() - 95
            if cursor_global.y() >= bottom_threshold:
                if not self.control_bar.isVisible():
                    self._reposition_control_bar()
                    self.control_bar.show()
                    self.control_bar.raise_()
                return

        if not self.is_slider_dragging and self.control_bar.isVisible():
            self.control_bar.hide()

    def _hide_all_input_popups(self):
        for inp in (self.jump_input, self.interval_input, self.url_input):
            if inp and inp.isVisible():
                inp.hide()

    def _reposition_control_bar(self):
        if not self.control_bar or not self._ui_initialized:
            return
        video_global_tl = self.stack.mapToGlobal(QPoint(0, 0))
        vw = self.stack.width()
        vh = self.stack.height()

        bar_w = min(max(420, vw - 36), 1040)
        bar_x = video_global_tl.x() + (vw - bar_w) // 2
        bar_y = video_global_tl.y() + vh - self.control_bar.height() - 22

        self.control_bar.setFixedWidth(bar_w)
        self.control_bar.move(bar_x, bar_y)

    def _sync_attached_bottom_panels(self):
        if not self._ui_initialized:
            return
        for panel in self._all_managed_panels():
            if panel and panel.isVisible() and panel.mode == "bottom":
                panel.sync_bottom_geometry()

    def _on_position_changed(self, position_ms: int):
        if not self.is_slider_dragging and not self.is_live_stream_playing:
            self.seek_slider.setValue(position_ms)
            self.lbl_current_time.setText(format_ms_to_time(position_ms))

    def _on_duration_changed(self, duration_ms: int):
        if self.is_live_stream_playing or duration_ms <= 0:
            self.seek_slider.setEnabled(False)
            self.seek_slider.setRange(0, 100)
            self.seek_slider.setValue(100)
            self.lbl_current_time.setText("🔴 LIVE")
            self.lbl_total_time.setText("실시간")
        else:
            self.seek_slider.setEnabled(True)
            self.seek_slider.setRange(0, duration_ms)
            self.lbl_total_time.setText(format_ms_to_time(duration_ms))

    def _on_slider_pressed(self):
        self.is_slider_dragging = True

    def _on_slider_moved(self, pos_ms: int):
        self.lbl_current_time.setText(format_ms_to_time(pos_ms))

    def _on_slider_released(self):
        self.is_slider_dragging = False
        if not self.is_live_stream_playing:
            target_ms = self.seek_slider.value()
            self.player.setPosition(target_ms)
            self.show_osd(f"⏱ 이동: {format_ms_to_time(target_ms)} / {format_ms_to_time(self.player.duration())}")

    def toggle_chat_panel(self):
        if self.chat_panel.isVisible():
            self.chat_panel.hide_panel()
            self.show_osd("💬 라이브 채팅창 숨김 (L 키로 다시 열기)")
        else:
            if not self.current_chat_url and self.current_web_url:
                self.current_chat_url = extract_live_chat_url(self.current_web_url)

            if self.current_chat_url:
                current_loaded = self.chat_web_view.url().toString()
                if current_loaded != self.current_chat_url:
                    self._connect_live_chat(self.current_web_url, self.current_chat_url)
                self.chat_panel.show_panel()
                self.show_osd("💬 실시간 라이브 채팅 연결됨", duration=2400)
            else:
                self.chat_panel.show_panel()
                self.show_osd("💬 채팅 패널 표시됨 (상단 버튼으로 3사 로그인 가능)")

        QTimer.singleShot(25, self._force_layout_sync)

    def _toggle_playlist_panel(self):
        if self.playlist_panel.isVisible():
            self.playlist_panel.hide_panel()
            self.show_osd("📋 재생목록 숨김 (Tab 키로 다시 열기)")
        else:
            self.playlist_panel.show_panel()
            self.show_osd("📋 재생목록 열림")
        QTimer.singleShot(25, self._force_layout_sync)

    def _set_panel_layout_mode(self, panel: DetachablePanel, mode: str):
        panel.set_panel_mode(mode)
        if not panel.isVisible():
            panel.show_panel()

    def show_context_menu(self, global_pos: QPoint):
        menu = QMenu(self)

        is_playing = (
            self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            if self.stack.currentIndex() in (2, 4) else not self.is_image_paused
        )
        act_play = menu.addAction(f"{'⏸ 일시정지' if is_playing else '▶ 재생'}\tSpace")
        act_play.triggered.connect(self.toggle_play_pause)

        act_prev = menu.addAction("⏮ 이전 미디어 (강제 넘김)\t[ / PageUp")
        act_prev.triggered.connect(lambda: self.prev_media(force=True))

        act_next = menu.addAction("⏭ 다음 미디어 (강제 넘김)\t] / PageDown")
        act_next.triggered.connect(lambda: self.next_media(force=True))

        sec_str = self._get_custom_seek_str()
        custom_ms = int(self.custom_seek_sec * 1000)

        seek_menu = menu.addMenu(f"⏱ 정밀 탐색 및 배속 ({self.playback_rate:.2f}x · {sec_str}초)")
        seek_menu.addAction("⏪ 3초 뒤로 (이전 이미지)\t←", lambda: self.seek_relative(-3000))
        seek_menu.addAction("⏩ 3초 앞으로 (다음 이미지)\t→", lambda: self.seek_relative(3000))
        seek_menu.addAction("⏪ 10초 뒤로\tCtrl+←", lambda: self.seek_relative(-10000))
        seek_menu.addAction("⏩ 10초 앞으로\tCtrl+→", lambda: self.seek_relative(10000))
        seek_menu.addSeparator()
        seek_menu.addAction(f"🎯 [{sec_str}초] 탐색 단위 설정...\tG", self.open_jump_popup)
        seek_menu.addAction(f"⏪ {sec_str}초 뒤로\tShift+←", lambda: self.seek_relative(-custom_ms, f"[{sec_str}초 이동]"))
        seek_menu.addAction(f"⏩ {sec_str}초 앞으로\tShift+→", lambda: self.seek_relative(custom_ms, f"[{sec_str}초 이동]"))
        seek_menu.addSeparator()
        for rate in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
            act_rate = QAction(f"⚡ {rate:.2f}x 배속", seek_menu, checkable=True)
            act_rate.setChecked(abs(self.playback_rate - rate) < 0.01)
            act_rate.triggered.connect(lambda checked, r=rate: self._set_exact_playback_rate(r))
            seek_menu.addAction(act_rate)
        seek_menu.addSeparator()
        seek_menu.addAction("➕ 0.25배속 빠르게\tC", lambda: self.adjust_playback_rate(0.25))
        seek_menu.addAction("➖ 0.25배속 느리게\tX", lambda: self.adjust_playback_rate(-0.25))
        seek_menu.addAction("🔄 1.00x 기본 배속 복원\tZ", lambda: self.adjust_playback_rate(reset=True))

        mode_menu = menu.addMenu(f"🔁 재생 모드 및 볼륨 ({self._get_mode_short_label()} · {round(self.audio_output.volume() * 100)}%)")
        for s_flag, r_flag, m_title in (
            (False, False, "1) 순차 재생 · 1회 재생 후 정지"),
            (False, True, "2) 순차 재생 · 목록 전체 반복"),
            (True, False, "3) 랜덤 셔플 · 1회 재생 후 정지"),
            (True, True, "4) 랜덤 셔플 · 목록 전체 반복"),
        ):
            act_m = QAction(m_title, mode_menu, checkable=True)
            act_m.setChecked(self.is_shuffle == s_flag and self.is_repeat_all == r_flag)
            act_m.triggered.connect(lambda checked=False, sf=s_flag, rf=r_flag: self._set_matrix_mode(sf, rf))
            mode_menu.addAction(act_m)
        mode_menu.addSeparator()
        mode_menu.addAction("🔊 볼륨 +5%\t↑ / 휠 업", lambda: self.change_volume(5))
        mode_menu.addAction("🔉 볼륨 -5%\t↓ / 휠 다운", lambda: self.change_volume(-5))
        for v in (100, 70, 50, 25, 0):
            mode_menu.addAction(f"볼륨 {v}% 설정", lambda checked=False, val=v: self._set_exact_volume(val))

        interval_str = self._get_interval_sec_str()
        fx_menu = menu.addMenu(f"✨ 이미지 전환 효과 (모드 {self.image_view.transition_mode} · {interval_str}초)")
        fx_menu.addAction(f"⏱ [{interval_str}초] 자동 넘김 시간 설정...\tI", self.open_slideshow_interval_popup)
        fx_menu.addSeparator()
        fx_names = {
            1: "모드 1: 즉시 전환 (Instant)\t1",
            2: "모드 2: 크로스페이드 (Cross-Fade)\t2",
            3: "모드 3: 시네마틱 줌 (Cinematic Zoom)\t3",
            4: "모드 4: 모서리 책장 넘기기 (뒷면 투영)\t4",
        }
        for mode_idx, label in fx_names.items():
            act_fx = QAction(label, fx_menu, checkable=True)
            act_fx.setChecked(self.image_view.transition_mode == mode_idx)
            act_fx.triggered.connect(lambda checked, m=mode_idx: self.set_transition_preset(m))
            fx_menu.addAction(act_fx)

        menu.addSeparator()

        layout_menu = menu.addMenu(f"📐 화면 분할 & 레이아웃 묶음 (현재 {len(UnifiedMediaPlayer.ACTIVE_INSTANCES)}창)")
        self._populate_layout_menu(layout_menu)

        menu.addSeparator()

        menu.addAction("🌐 라이브 / 유튜브 URL 직접 열기...\tU", self.open_url_popup)

        streamer_menu = menu.addMenu(f"⭐ 스트리머 즐겨찾기 ({len(UnifiedMediaPlayer.SHARED_STREAMERS)}명)")
        act_st_vis = QAction("⭐ 즐겨찾기 패널 열기 / 닫기\tB", streamer_menu, checkable=True)
        act_st_vis.setChecked(self.streamer_panel.isVisible())
        act_st_vis.triggered.connect(self.toggle_streamer_panel)
        streamer_menu.addAction(act_st_vis)
        streamer_menu.addAction("➕ 새 스트리머 등록...", self.open_add_streamer_dialog)
        streamer_menu.addAction("🗂 즐겨찾기 삭제 / 수정 / 관리...", self.open_manage_streamers_dialog)
        streamer_menu.addSeparator()
        streamer_menu.addAction("📤 즐겨찾기 파일로 백업 저장 (Export)...", self.export_streamers_to_file)
        streamer_menu.addAction("📥 백업 파일에서 즐겨찾기 불러오기 (Import)...", self.import_streamers_from_file)
        streamer_menu.addSeparator()
        streamer_menu.addAction("⇥ 패널 위치: 우측 도킹", lambda: self._set_panel_layout_mode(self.streamer_panel, "right"))
        streamer_menu.addAction("⤓ 패널 위치: 하단 결합(폭 맞춤)", lambda: self._set_panel_layout_mode(self.streamer_panel, "bottom"))
        streamer_menu.addAction("❐ 패널 위치: 독립 창 분리", lambda: self._set_panel_layout_mode(self.streamer_panel, "floating"))

        if UnifiedMediaPlayer.SHARED_STREAMERS:
            streamer_menu.addSeparator()
            for plat_code in ("CHZZK", "SOOP"):
                group = [s for s in UnifiedMediaPlayer.SHARED_STREAMERS if s.get("platform") == plat_code]
                for s in group:
                    s_name = s.get("name", "")
                    s_url = s.get("url", "")
                    streamer_menu.addAction(
                        f"▶ [{plat_code}] {s_name}",
                        lambda checked=False, u=s_url, n=s_name, p=plat_code: self.load_stream_url_directly(u, f"[{p}] {n}")
                    )

        chat_menu = menu.addMenu("💬 라이브 채팅창 및 3사 로그인")
        act_chat_vis = QAction("채팅창 표시 / 숨기기\tL", chat_menu, checkable=True)
        act_chat_vis.setChecked(self.chat_panel.isVisible())
        act_chat_vis.triggered.connect(self.toggle_chat_panel)
        chat_menu.addAction(act_chat_vis)
        chat_menu.addAction("↻ 채팅창 새로고침", self.reload_current_chat)
        chat_menu.addSeparator()
        chat_menu.addAction("🔑 네이버(치지직) 로그인 창 열기", lambda: (self.chat_panel.show_panel(), self.toggle_login_drawer("NAVER")))
        chat_menu.addAction("🔑 SOOP(숲) 로그인 창 열기", lambda: (self.chat_panel.show_panel(), self.toggle_login_drawer("SOOP")))
        chat_menu.addAction("🔑 구글(유튜브) 로그인 창 열기", lambda: (self.chat_panel.show_panel(), self.toggle_login_drawer("GOOGLE")))
        chat_menu.addSeparator()
        chat_menu.addAction("⇥ 플레이어 우측에 결합", lambda: self._set_panel_layout_mode(self.chat_panel, "right"))
        chat_menu.addAction("⤓ 플레이어 하단에 붙이기 (폭 맞춤 · 높이 3배)", lambda: self._set_panel_layout_mode(self.chat_panel, "bottom"))
        chat_menu.addAction("❐ 독립된 창으로 분리", lambda: self._set_panel_layout_mode(self.chat_panel, "floating"))

        menu.addSeparator()

        menu.addAction("📂 로컬 파일 추가 열기 (MP4, MP3, 이미지 등)...", self.open_files_dialog)
        menu.addAction("📁 폴더 통째로 추가...", self.open_folder_dialog)

        plist_menu = menu.addMenu(f"📋 재생목록 패널 ({len(self.playlist)}개)")
        act_plist_vis = QAction("재생목록 표시 / 숨기기\tTab", plist_menu, checkable=True)
        act_plist_vis.setChecked(self.playlist_panel.isVisible())
        act_plist_vis.triggered.connect(self._toggle_playlist_panel)
        plist_menu.addAction(act_plist_vis)
        plist_menu.addSeparator()
        plist_menu.addAction("⇥ 플레이어 우측에 결합", lambda: self._set_panel_layout_mode(self.playlist_panel, "right"))
        plist_menu.addAction("⤓ 플레이어 하단에 붙이기 (폭 맞춤)", lambda: self._set_panel_layout_mode(self.playlist_panel, "bottom"))
        plist_menu.addAction("❐ 독립된 창으로 분리", lambda: self._set_panel_layout_mode(self.playlist_panel, "floating"))

        menu.addSeparator()

        reg_file = self.get_startup_registered_file()
        reg_status = os.path.basename(reg_file) if reg_file else "미설정"
        startup_menu = menu.addMenu(f"🚀 부팅 시 자동 실행 설정 [{reg_status}]")
        startup_menu.addAction("📌 현재 재생 파일을 부팅 시 자동 재생으로 등록", self.register_current_file_for_startup)
        startup_menu.addAction("🎵 부팅 시 자동 재생할 파일 직접 선택...", self.select_and_register_startup_file)
        startup_menu.addSeparator()
        act_startup_info = QAction(f"등록 파일: {reg_file if reg_file else '없음'}", startup_menu)
        act_startup_info.setEnabled(False)
        startup_menu.addAction(act_startup_info)
        startup_menu.addAction("❌ 부팅 시 자동 실행 해제", self.remove_startup_auto_play)

        fs_label = "🗗 창 모드로 복귀\tAlt+Enter" if self.isFullScreen() else "⛶ 전체화면 전환\tAlt+Enter"
        menu.addAction(fs_label, self.toggle_fullscreen)

        menu.addSeparator()
        if len(UnifiedMediaPlayer.ACTIVE_INSTANCES) > 1:
            menu.addAction("❌ 현재 플레이어 창만 닫기\tESC", self.close_this_window)
            menu.addAction("🛑 모든 플레이어 창 종료", self.quit_all_instances)
        else:
            menu.addAction("❌ 플레이어 종료\tESC", self.close_this_window)

        menu.exec(global_pos)

    def _set_exact_playback_rate(self, rate: float):
        self.playback_rate = rate
        self.player.setPlaybackRate(self.playback_rate)
        self.btn_speed.setText(f"{self.playback_rate:.2f}x")
        self.show_osd(f"⚡ 재생 배속: {self.playback_rate:.2f}x")

    def _set_exact_volume(self, percent: int):
        self.audio_output.setVolume(percent / 100.0)
        self.show_osd(f"🔊 볼륨: {percent}%")

    def _set_matrix_mode(self, shuffle: bool, repeat_all: bool):
        self.is_shuffle = shuffle
        self.is_repeat_all = repeat_all
        if self.is_shuffle:
            self._rebuild_shuffle_order(keep_current=True)
        if 0 <= self.current_index < len(self.playlist):
            self._sync_title_and_tray(os.path.basename(self.playlist[self.current_index]))
        self.show_osd(f"🔁 재생 모드 변경: {self._get_mode_short_label()}")

    def open_files_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "미디어 파일 선택", "",
            "Media Files (*.mp4 *.m4v *.mov *.mkv *.avi *.wmv *.webm *.flv *.ts *.mts *.m2ts *.mpg *.mpeg *.3gp *.mp3 *.wav *.flac *.ogg *.m4a *.aac *.wma *.opus *.jpg *.jpeg *.png *.bmp *.webp *.gif *.tiff *.jfif);;All Files (*.*)"
        )
        if files:
            self._append_paths_to_playlist(files)

    def open_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "미디어 폴더 선택")
        if folder:
            self._append_paths_to_playlist([folder])

    def show_osd(self, message: str, duration: int = 2000):
        if not self.osd_window:
            return
        self.osd_label.setText(message)
        self.osd_label.adjustSize()
        self.osd_window.adjustSize()

        global_tl = self.mapToGlobal(QPoint(24, 24))
        self.osd_window.move(global_tl)
        self.osd_window.show()
        self.osd_window.raise_()
        self.osd_timer.start(duration)

    def _sync_title_and_tray(self, display_name: str):
        mode_tag = self._get_mode_short_label()
        title_text = f"[{mode_tag}] {display_name} - Minimal Media Player"
        self.setWindowTitle(title_text)
        self.tray_icon.setToolTip(f"재생 중: {display_name} ({mode_tag})")

    def _get_mode_short_label(self) -> str:
        order_str = "셔플" if self.is_shuffle else "순차"
        repeat_str = "전체반복" if self.is_repeat_all else "1회재생"
        return f"{order_str}·{repeat_str}"

    def set_transition_preset(self, mode: int):
        names = {
            1: "모드 1: 즉시 전환 (Instant)",
            2: "모드 2: 크로스페이드 (Cross-Fade)",
            3: "모드 3: 시네마틱 줌 (Cinematic Zoom)",
            4: "모드 4: 모서리 책장 넘기기 (뒷면 이미지 투영)"
        }
        self.image_view.transition_mode = mode
        self.show_osd(f"✨ 이미지 전환 프리셋: {names.get(mode, '')}")

    def open_url_popup(self):
        self._hide_all_input_popups()
        global_center = self.mapToGlobal(QPoint(
            (self.width() - self.url_input.width()) // 2,
            (self.height() - self.url_input.height()) // 2
        ))
        self.url_input.move(global_center)
        self.url_input.setText(self.current_web_url)
        self.url_input.selectAll()
        self.url_input.show()
        self.url_input.raise_()
        self.url_input.activateWindow()
        self.url_input.setFocus()

    def open_jump_popup(self):
        self._hide_all_input_popups()
        global_center = self.mapToGlobal(QPoint(
            (self.width() - self.jump_input.width()) // 2,
            (self.height() - self.jump_input.height()) // 2
        ))
        self.jump_input.move(global_center)
        self.jump_input.setText(self._get_custom_seek_str())
        self.jump_input.selectAll()
        self.jump_input.show()
        self.jump_input.raise_()
        self.jump_input.activateWindow()
        self.jump_input.setFocus()

    def _execute_custom_jump(self):
        text = self.jump_input.text().strip()
        self.jump_input.hide()
        self.activateWindow()
        self.setFocus()

        if not text:
            return

        try:
            seconds = abs(float(text))
            if seconds <= 0:
                self.show_osd("⚠ 탐색 단위는 0보다 큰 숫자로 입력하세요 (예: 89, 30)")
                return
            self.custom_seek_sec = int(seconds) if seconds.is_integer() else round(seconds, 1)
            sec_str = self._get_custom_seek_str()
            if self.btn_seek_unit:
                self.btn_seek_unit.setText(f"🎯{sec_str}s")
            self.show_osd(f"🎯 탐색 단위 설정 완료: {sec_str}초 (Shift + ← / → 로 이동)")
        except ValueError:
            self.show_osd("⚠ 올바른 숫자를 입력하세요 (예: 89, 30)")

    def open_slideshow_interval_popup(self):
        self._hide_all_input_popups()
        global_center = self.mapToGlobal(QPoint(
            (self.width() - self.interval_input.width()) // 2,
            (self.height() - self.interval_input.height()) // 2
        ))
        self.interval_input.move(global_center)
        self.interval_input.setText(self._get_interval_sec_str())
        self.interval_input.selectAll()
        self.interval_input.show()
        self.interval_input.raise_()
        self.interval_input.activateWindow()
        self.interval_input.setFocus()

    def _execute_slideshow_interval(self):
        text = self.interval_input.text().strip()
        self.interval_input.hide()
        self.activateWindow()
        self.setFocus()

        if not text:
            return

        try:
            seconds = abs(float(text))
            if seconds < 0.5:
                self.show_osd("⚠ 자동 넘김 시간은 최소 0.5초 이상으로 입력하세요")
                return
            self.image_slideshow_interval = int(round(seconds * 1000))
            sec_str = self._get_interval_sec_str()
            if self.stack.currentIndex() == 1 and not self.is_image_paused:
                self.image_timer.start(self.image_slideshow_interval)
            self.show_osd(f"⏱ 이미지 자동 넘김 시간 설정 완료: {sec_str}초")
        except ValueError:
            self.show_osd("⚠ 올바른 숫자를 입력하세요 (예: 5, 3.5)")

    def _execute_url_load(self):
        raw_url = self.url_input.text().strip()
        self.url_input.hide()
        self.activateWindow()
        self.setFocus()
        self.load_stream_url_directly(raw_url)

    def _on_streamlink_resolved(
        self, orig_url: str, stream_url: str, engine_tag: str, is_live: bool, title: str, chat_url: str
    ):
        if self.stack.currentIndex() == 3:
            self.web_view.setUrl(QUrl("about:blank"))

        self.is_live_stream_playing = is_live
        self.current_web_url = orig_url
        self.current_chat_url = chat_url

        self.stack.setCurrentIndex(2)
        self.player.stop()
        self.player.setSource(QUrl(stream_url))
        self.player.setPlaybackRate(1.0)
        self.playback_rate = 1.0
        self.btn_speed.setText("1.00x")
        self.player.play()
        self.btn_play_pause.setText("⏸")

        if self.current_chat_url:
            self._connect_live_chat(orig_url, self.current_chat_url)
            self.chat_panel.show_panel()

        self._force_layout_sync()

        tag = f"LIVE·{engine_tag}" if is_live else f"VOD·{engine_tag}"
        self._sync_title_and_tray(f"[{tag}] {title}")
        self.show_osd(f"🔴 방송 및 실시간 채팅 연결 완료 ({tag})", duration=3000)

    def _on_streamlink_failed(self, orig_url: str, reason: str):
        self.is_live_stream_playing = False
        self.current_web_url = orig_url
        self.stack.setCurrentIndex(3)
        self.web_view.load(QUrl(orig_url))
        self._force_layout_sync()
        self._sync_title_and_tray(orig_url)
        self.show_osd(f"⚠ 스트림 직결 실패({reason}) -> 웹뷰 모드로 전환 (채팅창은 L키로 제어)", duration=3500)

    def _on_web_url_changed(self, qurl: QUrl):
        if self.stack.currentIndex() == 3:
            url_str = qurl.toString()
            if url_str and url_str != "about:blank":
                self.current_web_url = url_str
                new_chat = extract_live_chat_url(url_str)
                if new_chat:
                    self.current_chat_url = new_chat
                self._sync_title_and_tray(self.current_web_url)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        dropped_paths = [url.toLocalFile() for url in event.mimeData().urls()]
        self._append_paths_to_playlist(dropped_paths)

    def _append_paths_to_playlist(self, paths_list):
        collected = []
        for path in paths_list:
            clean_path = os.path.normpath(path.strip('"').strip("'"))
            if os.path.isdir(clean_path):
                folder_files = []
                for root, _, files in os.walk(clean_path):
                    for f in files:
                        ext = os.path.splitext(f)[1].lower()
                        if ext in SUPPORTED_EXTS:
                            folder_files.append(os.path.normpath(os.path.join(root, f)))
                collected.extend(natsorted(folder_files))
            elif os.path.isfile(clean_path):
                ext = os.path.splitext(clean_path)[1].lower()
                if ext in SUPPORTED_EXTS:
                    collected.append(clean_path)

        if not collected:
            self.show_osd("지원하지 않는 파일 형식입니다")
            return

        collected = natsorted(collected)
        was_empty = (len(self.playlist) == 0)

        current_file = self.playlist[self.current_index] if (0 <= self.current_index < len(self.playlist)) else None

        for item in collected:
            if item not in self.playlist:
                self.playlist.append(item)

        self.playlist = natsorted(self.playlist)
        if current_file and current_file in self.playlist:
            self.current_index = self.playlist.index(current_file)

        self._rebuild_shuffle_order(keep_current=True)
        self._refresh_playlist_ui()

        if was_empty and self.playlist:
            start_idx = self.shuffle_order[0] if self.is_shuffle else 0
            self.shuffle_pos = 0
            self.load_media(start_idx, force=True)
        else:
            self.show_osd(f"목록에 {len(collected)}개 추가됨 (총 {len(self.playlist)}개)")

    def _refresh_playlist_ui(self):
        self.playlist_widget.clear()
        for idx, path in enumerate(self.playlist):
            self.playlist_widget.addItem(f"{idx + 1}. {os.path.basename(path)}")
        if 0 <= self.current_index < len(self.playlist):
            self.playlist_widget.setCurrentRow(self.current_index)

    def _rebuild_shuffle_order(self, keep_current: bool = True):
        n = len(self.playlist)
        if n == 0:
            self.shuffle_order = []
            self.shuffle_pos = -1
            return

        indices = list(range(n))
        if keep_current and (0 <= self.current_index < n):
            indices.remove(self.current_index)
            random.shuffle(indices)
            self.shuffle_order = [self.current_index] + indices
            self.shuffle_pos = 0
        else:
            random.shuffle(indices)
            self.shuffle_order = indices
            self.shuffle_pos = 0

    def toggle_shuffle_mode(self):
        self.is_shuffle = not self.is_shuffle
        if self.is_shuffle:
            self._rebuild_shuffle_order(keep_current=True)
        if 0 <= self.current_index < len(self.playlist):
            self._sync_title_and_tray(os.path.basename(self.playlist[self.current_index]))
        self.show_osd(f"🔀 재생 순서: {'랜덤 셔플' if self.is_shuffle else '순차 재생'} ({self._get_mode_short_label()})")

    def toggle_repeat_mode(self):
        self.is_repeat_all = not self.is_repeat_all
        if 0 <= self.current_index < len(self.playlist):
            self._sync_title_and_tray(os.path.basename(self.playlist[self.current_index]))
        self.show_osd(f"🔁 반복 설정: {'전체 반복' if self.is_repeat_all else '한 번 재생 후 종료'} ({self._get_mode_short_label()})")

    def _compute_next_index(self, forward: bool = True, manual: bool = False) -> int:
        n = len(self.playlist)
        if n == 0:
            return -1

        if self.is_shuffle:
            if len(self.shuffle_order) != n:
                self._rebuild_shuffle_order(keep_current=True)

            if self.current_index in self.shuffle_order:
                self.shuffle_pos = self.shuffle_order.index(self.current_index)
            else:
                self.shuffle_pos = 0

            step = 1 if forward else -1
            next_pos = self.shuffle_pos + step

            if 0 <= next_pos < n:
                self.shuffle_pos = next_pos
                return self.shuffle_order[self.shuffle_pos]
            else:
                if self.is_repeat_all or manual:
                    self._rebuild_shuffle_order(keep_current=False)
                    self.shuffle_pos = 0 if forward else (n - 1)
                    return self.shuffle_order[self.shuffle_pos]
                else:
                    return -1
        else:
            step = 1 if forward else -1
            next_idx = self.current_index + step

            if 0 <= next_idx < n:
                return next_idx
            else:
                if self.is_repeat_all or manual:
                    return 0 if forward else (n - 1)
                else:
                    return -1

    def load_media(self, index: int, force: bool = False):
        if not (0 <= index < len(self.playlist)):
            return

        if self.stack.currentIndex() == 1 and self.image_view.is_animating and not force:
            return

        if self.stack.currentIndex() == 3:
            self.web_view.setUrl(QUrl("about:blank"))

        self.is_live_stream_playing = False
        self.current_web_url = ""
        self.current_chat_url = ""
        self.image_timer.stop()

        target_path = os.path.abspath(self.playlist[index])
        ext = os.path.splitext(target_path)[1].lower()
        base_name = os.path.basename(target_path)

        if ext in IMAGE_EXTS:
            self.player.stop()
            if self.control_bar:
                self.control_bar.hide()
            if self.stack.currentIndex() != 1:
                self.stack.setCurrentIndex(1)
                self._force_layout_sync()

            new_pixmap = QPixmap(target_path)
            accepted = self.image_view.show_image(
                new_pixmap, play_sound_callback=self.play_transition_sfx, force=force
            )
            if not accepted:
                return

            self.current_index = index
            if self.is_shuffle and self.current_index in self.shuffle_order:
                self.shuffle_pos = self.shuffle_order.index(self.current_index)

            self.playlist_widget.setCurrentRow(self.current_index)
            self._sync_title_and_tray(base_name)

            if not self.is_image_paused:
                self.image_timer.start(self.image_slideshow_interval)
            self.show_osd(f"🖼 [{index + 1}/{len(self.playlist)}] {base_name}")

        elif ext in VIDEO_EXTS or ext in AUDIO_EXTS:
            self.image_view.clear_view()
            self.current_index = index
            if self.is_shuffle and self.current_index in self.shuffle_order:
                self.shuffle_pos = self.shuffle_order.index(self.current_index)

            self.playlist_widget.setCurrentRow(self.current_index)
            self._sync_title_and_tray(base_name)

            if ext in AUDIO_EXTS:
                self.audio_cover_label.setText(
                    f"🎵 지금 재생 중인 오디오\n\n{base_name}\n\n"
                    f"[Space] 일시정지/재생   |   [← / →] 3초 탐색   |   [Shift + ← / →] {self._get_custom_seek_str()}초 탐색"
                )
                self.stack.setCurrentIndex(4)
            else:
                self.stack.setCurrentIndex(2)

            self._force_layout_sync()

            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(target_path))
            self.player.setPlaybackRate(self.playback_rate)
            self.btn_speed.setText(f"{self.playback_rate:.2f}x")
            self.player.play()
            self.btn_play_pause.setText("⏸")
            rate_str = f" ({self.playback_rate:.2f}x)" if self.playback_rate != 1.0 else ""
            icon_tag = "🎵" if ext in AUDIO_EXTS else "▶"
            self.show_osd(f"{icon_tag} [{index + 1}/{len(self.playlist)}] {base_name}{rate_str}")

    def _on_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia and not self.is_live_stream_playing:
            self._on_media_finished()

    def _on_media_finished(self):
        next_idx = self._compute_next_index(forward=True, manual=False)
        if next_idx != -1:
            self.load_media(next_idx, force=False)
        else:
            self.show_osd(f"⏹ 재생 완료 ({self._get_mode_short_label()})")

    def _on_playlist_item_double_clicked(self):
        row = self.playlist_widget.currentRow()
        self.load_media(row, force=True)

    def toggle_play_pause(self):
        if self.stack.currentIndex() in (2, 4):
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
                self.btn_play_pause.setText("▶")
                self.show_osd("⏸ 일시정지")
            else:
                self.player.play()
                self.btn_play_pause.setText("⏸")
                self.show_osd("▶ 재생")
        elif self.stack.currentIndex() == 1:
            sec_str = self._get_interval_sec_str()
            if self.is_image_paused:
                self.is_image_paused = False
                self.image_timer.start(self.image_slideshow_interval)
                self.show_osd(f"▶ 이미지 자동넘김 재개 ({sec_str}초 간격)")
            else:
                self.is_image_paused = True
                self.image_timer.stop()
                self.show_osd("⏸ 이미지 자동넘김 일시정지")

    def seek_relative(self, offset_ms: int, label_prefix: str = ""):
        if self.stack.currentIndex() in (2, 4):
            if self.is_live_stream_playing:
                self.show_osd("⚠ 실시간 라이브 방송은 타임라인 탐색을 지원하지 않습니다")
                return
            duration = self.player.duration()
            new_pos = max(0, self.player.position() + offset_ms)
            if duration > 0:
                new_pos = min(duration, new_pos)
            self.player.setPosition(new_pos)
            offset_sec = offset_ms // 1000
            sign = "+" if offset_sec >= 0 else ""
            prefix_str = f"{label_prefix} " if label_prefix else ""
            self.show_osd(
                f"⏱ {prefix_str}{sign}{offset_sec}초 ({format_ms_to_time(new_pos)} / {format_ms_to_time(duration)})"
            )
        elif self.stack.currentIndex() == 1:
            if offset_ms > 0:
                self.next_media(force=True)
            else:
                self.prev_media(force=True)

    def adjust_playback_rate(self, delta: float = 0.0, reset: bool = False):
        if reset:
            self.playback_rate = 1.0
        else:
            self.playback_rate = max(0.25, min(4.0, round(self.playback_rate + delta, 2)))

        self.player.setPlaybackRate(self.playback_rate)
        self.btn_speed.setText(f"{self.playback_rate:.2f}x")
        self.show_osd(f"⚡ 재생 배속: {self.playback_rate:.2f}x")

    def change_volume(self, delta_percent: int):
        current_vol = round(self.audio_output.volume() * 100)
        new_vol = max(0, min(100, current_vol + delta_percent))
        self.audio_output.setVolume(new_vol / 100.0)
        self.show_osd(f"🔊 볼륨: {new_vol}%")

    def next_media(self, force: bool = True):
        if self.stack.currentIndex() == 1 and self.image_view.is_animating and not force:
            return
        next_idx = self._compute_next_index(forward=True, manual=True)
        if next_idx != -1:
            self.load_media(next_idx, force=force)

    def prev_media(self, force: bool = True):
        if self.stack.currentIndex() == 1 and self.image_view.is_animating and not force:
            return
        prev_idx = self._compute_next_index(forward=False, manual=True)
        if prev_idx != -1:
            self.load_media(prev_idx, force=force)

    def toggle_fullscreen(self, force_fullscreen: bool = False):
        if self.isFullScreen() and not force_fullscreen:
            self.showNormal()
            if self._normal_geometry:
                self.setGeometry(self._normal_geometry)
            self.unsetCursor()
            self.show_osd("창 모드")
        else:
            if not self.isFullScreen():
                self._normal_geometry = self.geometry()
            screen = self.screen() or QApplication.primaryScreen()
            if screen:
                self.setGeometry(screen.geometry())
            self.showFullScreen()
            self.unsetCursor()
            self.show_osd("전체화면 모드")

        QTimer.singleShot(30, self._force_layout_sync)

    def _force_layout_sync(self):
        if not self._ui_initialized:
            return
        self.central_widget.updateGeometry()
        self.main_layout.activate()
        self.image_view.refresh_scale_on_resize()
        if self.control_bar and self.control_bar.isVisible():
            self._reposition_control_bar()
        self._sync_attached_bottom_panels()

    def keyPressEvent(self, event):
        if self._is_web_or_input_focused():
            super().keyPressEvent(event)
            return

        key = event.key()
        modifiers = event.modifiers()

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (modifiers & Qt.KeyboardModifier.AltModifier):
            self.toggle_fullscreen()
            event.accept()
            return

        if key == Qt.Key.Key_1:
            self.set_transition_preset(1)
            event.accept()
            return
        elif key == Qt.Key.Key_2:
            self.set_transition_preset(2)
            event.accept()
            return
        elif key == Qt.Key.Key_3:
            self.set_transition_preset(3)
            event.accept()
            return
        elif key == Qt.Key.Key_4:
            self.set_transition_preset(4)
            event.accept()
            return

        if key == Qt.Key.Key_Right:
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                custom_ms = int(self.custom_seek_sec * 1000)
                self.seek_relative(custom_ms, label_prefix=f"[{self._get_custom_seek_str()}초 이동]")
            elif modifiers & Qt.KeyboardModifier.ControlModifier:
                self.seek_relative(10000)
            else:
                self.seek_relative(3000)
            event.accept()
            return

        if key == Qt.Key.Key_Left:
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                custom_ms = int(self.custom_seek_sec * 1000)
                self.seek_relative(-custom_ms, label_prefix=f"[{self._get_custom_seek_str()}초 이동]")
            elif modifiers & Qt.KeyboardModifier.ControlModifier:
                self.seek_relative(-10000)
            else:
                self.seek_relative(-3000)
            event.accept()
            return

        if key == Qt.Key.Key_Home:
            if self.playlist:
                self.load_media(0, force=True)
        elif key == Qt.Key.Key_End:
            if self.playlist:
                self.load_media(len(self.playlist) - 1, force=True)
        elif key == Qt.Key.Key_C:
            self.adjust_playback_rate(delta=0.25)
        elif key == Qt.Key.Key_X:
            self.adjust_playback_rate(delta=-0.25)
        elif key == Qt.Key.Key_Z:
            self.adjust_playback_rate(reset=True)
        elif key == Qt.Key.Key_M:
            self.toggle_shuffle_mode()
        elif key == Qt.Key.Key_R:
            self.toggle_repeat_mode()
        elif key == Qt.Key.Key_Space:
            self.toggle_play_pause()
        elif key == Qt.Key.Key_Up:
            self.change_volume(5)
        elif key == Qt.Key.Key_Down:
            self.change_volume(-5)
        elif key == Qt.Key.Key_PageDown:
            self.next_media(force=True)
        elif key == Qt.Key.Key_PageUp:
            self.prev_media(force=True)
        elif key == Qt.Key.Key_Tab:
            self._toggle_playlist_panel()
        elif key == Qt.Key.Key_Escape:
            if any(inp and inp.isVisible() for inp in (self.jump_input, self.interval_input, self.url_input)):
                self._hide_all_input_popups()
                self.activateWindow()
                self.setFocus()
            elif self.isFullScreen():
                self.toggle_fullscreen()
            else:
                self.close_this_window()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        angle = event.angleDelta().y()
        if angle > 0:
            self.change_volume(5)
        elif angle < 0:
            self.change_volume(-5)
        event.accept()

    def eventFilter(self, source, event):
        if not self._ui_initialized:
            return super().eventFilter(source, event)

        active_inputs = [
            inp for inp in (self.jump_input, self.interval_input, self.url_input) if inp is not None
        ]
        if source in active_inputs and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                source.hide()
                self.activateWindow()
                self.setFocus()
                return True
            return False

        if not isinstance(source, QWidget):
            return super().eventFilter(source, event)

        top_win = source.window()
        managed_windows = (self, self.chat_panel, self.streamer_panel, self.playlist_panel)
        if top_win not in managed_windows:
            return super().eventFilter(source, event)

        etype = event.type()
        draggable_surfaces = (
            self, self.central_widget, self.stack,
            self.guide_label, self.video_widget,
            self.image_view.viewport(), self.audio_cover_label
        )

        if etype == QEvent.Type.MouseButtonPress:
            global_pos = event.globalPosition().toPoint()
            if any(inp and inp.isVisible() for inp in active_inputs):
                self._hide_all_input_popups()
                self.activateWindow()
                self.setFocus()

            if source in draggable_surfaces:
                self.setFocus()

            if event.button() == Qt.MouseButton.RightButton:
                self.show_context_menu(global_pos)
                return True

            if event.button() == Qt.MouseButton.LeftButton:
                for panel in self._all_managed_panels():
                    if panel and panel.isVisible() and panel.mode == "right":
                        if panel.start_panel_interaction(global_pos):
                            self._active_interacting_panel = panel
                            return True

                if top_win is self and not self.isFullScreen():
                    edges = self._detect_resize_edges(global_pos)
                    if edges and not self.isMaximized():
                        win_handle = self.windowHandle()
                        if win_handle and win_handle.startSystemResize(edges):
                            return True
                        self._is_resizing = True
                        self._resize_edges = edges
                        self._resize_start_global = global_pos
                        self._resize_start_geom = self.geometry()
                        return True

                    if source in draggable_surfaces:
                        local_y = self.mapFromGlobal(global_pos).y()
                        if 0 <= local_y <= self.SNAP_BAR_TOP_ZONE:
                            win_handle = self.windowHandle()
                            if win_handle and win_handle.startSystemMove():
                                return True

                        if not self.isMaximized():
                            self._is_dragging_window = True
                            self.drag_pos = global_pos - self.frameGeometry().topLeft()

        elif etype == QEvent.Type.MouseMove:
            global_pos = event.globalPosition().toPoint()

            if self._active_interacting_panel is not None:
                if self._active_interacting_panel.perform_panel_drag_or_resize(global_pos):
                    return True

            if self._is_resizing:
                self._perform_manual_resize(global_pos)
                return True

            if (
                self._is_dragging_window
                and (event.buttons() & Qt.MouseButton.LeftButton)
                and top_win is self
                and not self.isFullScreen()
                and not self.isMaximized()
            ):
                if source in draggable_surfaces:
                    raw_tl = global_pos - self.drag_pos
                    cand_rect = QRect(raw_tl.x(), raw_tl.y(), self.width(), self.height())
                    targets = self._get_snap_target_rects(exclude_widget=self)
                    snapped_tl = compute_magnetic_snap(cand_rect, targets, snap_dist=18)
                    self.move(snapped_tl)
                    return True

        elif etype == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                self._is_dragging_window = False
                if self._active_interacting_panel is not None:
                    self._active_interacting_panel.stop_panel_interaction()
                    self._active_interacting_panel = None
                    self.unsetCursor()
                    return True
                if self._is_resizing:
                    self._is_resizing = False
                    self._resize_edges = Qt.Edge(0)
                    self.unsetCursor()
                    return True

        elif etype == QEvent.Type.MouseButtonDblClick:
            if event.button() == Qt.MouseButton.LeftButton and top_win is self:
                global_pos = event.globalPosition().toPoint()
                if not self._detect_resize_edges(global_pos) and source in draggable_surfaces:
                    self.toggle_fullscreen()
                    return True

        elif etype == QEvent.Type.Wheel:
            if top_win is self and source in draggable_surfaces:
                self.wheelEvent(event)
                return True

        return super().eventFilter(source, event)

    def moveEvent(self, event):
        super().moveEvent(event)
        if not self._ui_initialized:
            return
        if self.control_bar and self.control_bar.isVisible():
            self._reposition_control_bar()
        if self.osd_window and self.osd_window.isVisible():
            self.osd_window.move(self.mapToGlobal(QPoint(24, 24)))
        self._sync_attached_bottom_panels()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._ui_initialized:
            return
        self.image_view.refresh_scale_on_resize()
        if self.control_bar and self.control_bar.isVisible():
            self._reposition_control_bar()
        self._sync_attached_bottom_panels()

    def _restore_from_tray(self):
        self.showNormal()
        if self._normal_geometry:
            self.setGeometry(self._normal_geometry)
        self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._restore_from_tray()

    def _cleanup_instance_resources(self):
        if self._is_cleaned_up:
            return
        self._is_cleaned_up = True

        if hasattr(self, "hover_poll_timer") and self.hover_poll_timer:
            self.hover_poll_timer.stop()
        if hasattr(self, "image_timer") and self.image_timer:
            self.image_timer.stop()
        if hasattr(self, "player") and self.player:
            self.player.stop()

        if hasattr(self, "chat_web_view") and self.chat_web_view:
            self.chat_web_view.setUrl(QUrl("about:blank"))

        for w in (
            self.osd_window, self.control_bar, self.jump_input,
            self.interval_input, self.url_input,
            self.chat_panel, self.streamer_panel, self.playlist_panel
        ):
            if w is not None:
                try:
                    w.close()
                except Exception:
                    pass

        if hasattr(self, "tray_icon") and self.tray_icon:
            self.tray_icon.hide()

        if self in UnifiedMediaPlayer.ACTIVE_INSTANCES:
            UnifiedMediaPlayer.ACTIVE_INSTANCES.remove(self)

    def close_this_window(self):
        self._cleanup_instance_resources()
        self.close()
        if not UnifiedMediaPlayer.ACTIVE_INSTANCES:
            QApplication.quit()

    def quit_all_instances(self):
        for inst in list(UnifiedMediaPlayer.ACTIVE_INSTANCES):
            inst._cleanup_instance_resources()
            inst.close()
        QApplication.quit()

    def closeEvent(self, event):
        self._cleanup_instance_resources()
        super().closeEvent(event)
        if not UnifiedMediaPlayer.ACTIVE_INSTANCES:
            QApplication.quit()


if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)

    cli_paths = [
        arg for arg in sys.argv[1:]
        if not arg.startswith("-") and os.path.exists(arg.strip('"').strip("'"))
    ]

    player = UnifiedMediaPlayer(initial_paths=cli_paths)
    player.show()
    sys.exit(app.exec())