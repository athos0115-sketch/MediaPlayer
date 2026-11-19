import sys
import os

# 1. Qt Multimedia FFmpeg 백엔드 강제 지정 (MP4 / MP3 / FLAC / H.264 / HEVC / HLS 완벽 재생 보장)
os.environ["QT_MEDIA_BACKEND"] = "ffmpeg"
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

# 3. Windows 작업표시줄 AppUserModelID 설정
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Wonjae.MinimalMediaPlayer.Pro.v26"
        )
    except Exception:
        pass

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication

from storage import (
    CHROME_UA, VIDEO_EXTS, AUDIO_EXTS, IMAGE_EXTS, SUPPORTED_EXTS,
    get_base_dir, get_data_root_dir, safe_save_json, safe_load_json,
    load_app_settings, save_app_settings, compute_magnetic_snap,
    format_ms_to_time, load_auto_oriented_pixmap
)
from streaming import (
    SoopHeaderInterceptor, PopupSupportWebPage, SOOP_CHAT_DOM_MASK_JS,
    is_soop_url, is_valid_http_url, fetch_soop_live_bno,
    normalize_stream_url, extract_live_chat_url, StreamlinkResolverThread
)
from widgets import DetachablePanel, AnimatedGraphicsView
from dialogs import AddStreamerDialog, ManageStreamersDialog, ManageLayoutsDialog
from player_window import UnifiedMediaPlayer

__all__ = [
    "UnifiedMediaPlayer",
    "StreamlinkResolverThread",
    "DetachablePanel",
    "AnimatedGraphicsView",
    "AddStreamerDialog",
    "ManageStreamersDialog",
    "ManageLayoutsDialog",
    "SoopHeaderInterceptor",
    "PopupSupportWebPage",
    "SOOP_CHAT_DOM_MASK_JS",
    "CHROME_UA",
    "VIDEO_EXTS",
    "AUDIO_EXTS",
    "IMAGE_EXTS",
    "SUPPORTED_EXTS",
    "get_base_dir",
    "get_data_root_dir",
    "safe_save_json",
    "safe_load_json",
    "load_app_settings",
    "save_app_settings",
    "compute_magnetic_snap",
    "format_ms_to_time",
    "load_auto_oriented_pixmap",
    "is_soop_url",
    "is_valid_http_url",
    "fetch_soop_live_bno",
    "normalize_stream_url",
    "extract_live_chat_url",
]


if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)

    is_test_mode = "--test-mode" in sys.argv
    cli_paths = [
        arg for arg in sys.argv[1:]
        if not arg.startswith("-") and os.path.exists(arg.strip('"').strip("'"))
    ]

    player = UnifiedMediaPlayer(initial_paths=cli_paths)
    player.show()
    if is_test_mode:
        QTimer.singleShot(1500, player.quit_all_instances)
    sys.exit(app.exec())
