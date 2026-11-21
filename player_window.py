import sys
import os
import re
import random

from natsort import natsorted

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QLabel, QListWidget, QListWidgetItem, QSystemTrayIcon,
    QMenu, QStyle, QLineEdit, QSizePolicy, QFileDialog, QSlider, QPushButton,
    QMessageBox, QFrame, QInputDialog
)
from PyQt6.QtCore import Qt, QUrl, QTimer, QPoint, QRect, QEvent
from PyQt6.QtGui import QAction, QColor, QBrush, QCursor, QShortcut, QKeySequence
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QSoundEffect
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEngineProfile, QWebEngineScript

from storage import (
    ctypes, wintypes, winreg, HAS_WIN32, HAS_WINREG,
    VIDEO_EXTS, AUDIO_EXTS, IMAGE_EXTS, SUPPORTED_EXTS,
    STARTUP_REG_PATH, STARTUP_APP_NAME, CHROME_UA, LOGIN_URLS,
    GWL_STYLE, WS_MINIMIZEBOX, WS_MAXIMIZEBOX, WS_SYSMENU,
    get_base_dir, get_data_root_dir, resolve_app_icon_path, build_multi_size_qicon,
    load_auto_oriented_pixmap, format_ms_to_time, safe_save_json, safe_load_json,
    load_app_settings, save_app_settings, ensure_default_transition_sound,
    compute_magnetic_snap
)
from streaming import (
    SoopHeaderInterceptor, PopupSupportWebPage, SOOP_CHAT_DOM_MASK_JS,
    is_soop_url, extract_live_chat_url, StreamlinkResolverThread
)
from widgets import DetachablePanel, AnimatedGraphicsView
from dialogs import AddStreamerDialog, ManageStreamersDialog, ManageLayoutsDialog


class UnifiedMediaPlayer(QMainWindow):
    ACTIVE_INSTANCES = []
    SHARED_WEB_PROFILE = None
    SHARED_WEB_INTERCEPTOR = None
    SHARED_COOKIES = {}
    SHARED_STREAMERS = None
    SHARED_LAYOUTS = None
    SHARED_SETTINGS = None

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
        self._stream_request_id = 0
        self.current_stream_qualities = {}
        self.current_stream_quality = ""

        data_root = get_data_root_dir()
        self.streamers_file = os.path.join(data_root, "streamers.json")
        self.layouts_file = os.path.join(data_root, "layouts.json")
        self.settings_file = os.path.join(data_root, "settings.json")
        self._init_shared_repositories()

        cfg = UnifiedMediaPlayer.SHARED_SETTINGS
        self.drag_pos = QPoint()
        self._is_dragging_window = False
        self._is_resizing = False
        self._resize_edges = Qt.Edge(0)
        self._resize_start_global = QPoint()
        self._resize_start_geom = QRect()

        self.is_slider_dragging = False
        self.custom_seek_sec = cfg.get("custom_seek_sec", 89)
        self.playback_rate = float(cfg.get("playback_rate", 1.0))
        self.is_shuffle = bool(cfg.get("is_shuffle", False))
        self.is_repeat_all = bool(cfg.get("is_repeat_all", False))
        self.preferred_quality = str(cfg.get("preferred_quality", "best"))
        self.is_always_on_top = bool(cfg.get("always_on_top", False))
        self.is_muted = bool(cfg.get("is_muted", False))
        self._initial_volume_percent = max(0, min(100, int(cfg.get("volume", 70))))
        self.shuffle_order = []
        self.shuffle_pos = -1

        self.image_slideshow_interval = max(500, int(cfg.get("image_slideshow_interval", 5000)))
        self.image_timer = QTimer(self)
        self.image_timer.setSingleShot(True)
        self.image_timer.timeout.connect(self._on_media_finished)
        self.is_image_paused = False

        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.setInterval(300)
        self._settings_save_timer.timeout.connect(self._flush_settings_to_disk)

        self._init_web_profiles()
        self._init_media_core()
        self._init_sound_effect()
        self._init_ui()
        self._init_top_level_overlays()
        self._restore_saved_ui_state()
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

        if UnifiedMediaPlayer.SHARED_SETTINGS is None:
            UnifiedMediaPlayer.SHARED_SETTINGS = load_app_settings(self.settings_file)

    def _restore_saved_ui_state(self):
        cfg = UnifiedMediaPlayer.SHARED_SETTINGS
        self.image_view.transition_mode = int(cfg.get("transition_mode", 4))
        self.btn_speed.setText(f"{self.playback_rate:.2f}x")
        self.btn_seek_unit.setText(f"🎯{self._get_custom_seek_str()}s")
        self._sync_volume_controls()
        self._update_always_on_top_button()

        panels_cfg = cfg.get("panels", {})
        for key, panel in (
            ("chat", self.chat_panel),
            ("streamer", self.streamer_panel),
            ("playlist", self.playlist_panel),
        ):
            p_cfg = panels_cfg.get(key, {})
            if isinstance(p_cfg, dict) and panel is not None:
                dw = int(p_cfg.get("dock_width", panel.dock_width))
                bh = int(p_cfg.get("bottom_height", panel.bottom_height))
                panel.dock_width = max(220, min(900, dw))
                panel.bottom_height = max(180, min(1400, bh))
                mode = p_cfg.get("mode", "right")
                if mode in ("right", "bottom", "floating"):
                    panel.set_panel_mode(mode, notify=False)

    def _collect_current_settings(self) -> dict:
        return {
            "volume": round(self.audio_output.volume() * 100),
            "is_muted": self.is_muted,
            "playback_rate": self.playback_rate,
            "custom_seek_sec": self.custom_seek_sec,
            "transition_mode": self.image_view.transition_mode,
            "image_slideshow_interval": self.image_slideshow_interval,
            "is_shuffle": self.is_shuffle,
            "is_repeat_all": self.is_repeat_all,
            "preferred_quality": self.preferred_quality,
            "always_on_top": self.is_always_on_top,
            "panels": {
                "chat": {
                    "mode": self.chat_panel.mode,
                    "dock_width": self.chat_panel.dock_width,
                    "bottom_height": self.chat_panel.bottom_height,
                },
                "streamer": {
                    "mode": self.streamer_panel.mode,
                    "dock_width": self.streamer_panel.dock_width,
                    "bottom_height": self.streamer_panel.bottom_height,
                },
                "playlist": {
                    "mode": self.playlist_panel.mode,
                    "dock_width": self.playlist_panel.dock_width,
                    "bottom_height": self.playlist_panel.bottom_height,
                },
            },
        }

    def _schedule_save_settings(self):
        if not self._ui_initialized or self._is_cleaned_up:
            return
        self._settings_save_timer.start()

    def _flush_settings_to_disk(self):
        if self._settings_save_timer.isActive():
            self._settings_save_timer.stop()
        UnifiedMediaPlayer.SHARED_SETTINGS = self._collect_current_settings()
        save_app_settings(self.settings_file, UnifiedMediaPlayer.SHARED_SETTINGS)

    def showEvent(self, event):
        super().showEvent(event)
        if HAS_WIN32 and not self._win32_snap_applied:
            self._win32_snap_applied = True
            self._enable_windows_aero_snap_style()
            if self.is_always_on_top:
                self._apply_always_on_top_native()

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

    def _all_overlay_windows(self):
        return [
            w for w in (
                getattr(self, "control_bar", None),
                getattr(self, "osd_window", None),
                getattr(self, "jump_input", None),
                getattr(self, "interval_input", None),
                getattr(self, "url_input", None),
            )
            if w is not None
        ]

    def _sync_overlay_zorder_native(self, overlay_widget):
        """소유 Tool 오버레이 창이 항상 위 상태와 일치하도록 Win32 Z-order를 동기화합니다."""
        if not overlay_widget or not overlay_widget.isWindow():
            return
        if HAS_WIN32:
            try:
                hwnd = int(overlay_widget.winId())
                HWND_TOPMOST = -1
                HWND_NOTOPMOST = -2
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_NOACTIVATE = 0x0010
                user32 = ctypes.windll.user32
                user32.SetWindowPos.argtypes = [
                    wintypes.HWND, wintypes.HWND,
                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint
                ]
                user32.SetWindowPos.restype = wintypes.BOOL
                insert_after = HWND_TOPMOST if self.is_always_on_top else HWND_NOTOPMOST
                user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            except Exception:
                pass

    def _apply_always_on_top_native(self):
        if HAS_WIN32:
            try:
                hwnd = int(self.winId())
                HWND_TOPMOST = -1
                HWND_NOTOPMOST = -2
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_NOACTIVATE = 0x0010
                user32 = ctypes.windll.user32
                user32.SetWindowPos.argtypes = [
                    wintypes.HWND, wintypes.HWND,
                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint
                ]
                user32.SetWindowPos.restype = wintypes.BOOL
                insert_after = HWND_TOPMOST if self.is_always_on_top else HWND_NOTOPMOST
                user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                for ov in self._all_overlay_windows():
                    if ov.isVisible():
                        self._sync_overlay_zorder_native(ov)
                return
            except Exception as e:
                print(f"[Win32 항상 위 적용 참고] {e}")

        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.is_always_on_top)
        self.show()

    def _update_always_on_top_button(self):
        if not hasattr(self, "btn_always_on_top") or self.btn_always_on_top is None:
            return
        if self.is_always_on_top:
            self.btn_always_on_top.setStyleSheet(
                "QPushButton { background-color: rgba(0, 229, 255, 50); color: #00e5ff; "
                "border: 1px solid #00e5ff; border-radius: 5px; font-size: 12px; font-weight: bold; padding: 3px 6px; }"
            )
        else:
            self.btn_always_on_top.setStyleSheet("")

    def toggle_always_on_top(self):
        self.is_always_on_top = not self.is_always_on_top
        self._apply_always_on_top_native()
        self._update_always_on_top_button()
        self._schedule_save_settings()
        self.show_osd("📌 항상 위 고정 켜짐 (T)" if self.is_always_on_top else "📌 항상 위 고정 해제됨")

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
        return new_win

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
        screens = QApplication.screens()

        win_records = []
        for w in alive:
            g = w.frameGeometry()
            scr = w.screen() or QApplication.primaryScreen()
            scr_idx = screens.index(scr) if scr in screens else 0
            avail = scr.availableGeometry() if scr else QRect(0, 0, 1920, 1080)
            aw = max(1, avail.width())
            ah = max(1, avail.height())
            win_records.append({
                "screen_idx": scr_idx,
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

        screens = QApplication.screens()
        fallback_scr = self.screen() or QApplication.primaryScreen()

        target_wins = self._ensure_player_window_count(len(win_records), close_excess=True)
        for win, rec in zip(target_wins, win_records):
            if win.isFullScreen() or win.isMaximized():
                win.showNormal()

            scr_idx = rec.get("screen_idx")
            if isinstance(scr_idx, int) and 0 <= scr_idx < len(screens):
                target_scr = screens[scr_idx]
            else:
                target_scr = fallback_scr
            avail = target_scr.availableGeometry() if target_scr else QRect(0, 0, 1920, 1080)
            ax, ay, aw, ah = avail.x(), avail.y(), avail.width(), avail.height()

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

    def _cancel_pending_stream_resolver(self):
        self._stream_request_id += 1
        if self.stream_resolver is not None:
            for sig_name in ("chat_ready", "resolved", "failed"):
                try:
                    getattr(self.stream_resolver, sig_name).disconnect()
                except Exception:
                    pass
            self.stream_resolver = None

    def _on_stream_chat_ready(self, req_id: int, orig_url: str, chat_url: str):
        if req_id != self._stream_request_id or self._is_cleaned_up or not chat_url:
            return
        self.current_chat_url = chat_url
        self._connect_live_chat(orig_url, chat_url, force_reload=False)
        if not self.chat_panel.isVisible():
            self.chat_panel.show_panel()
            self._force_layout_sync()

    def load_stream_url_directly(self, raw_url: str, display_label: str = ""):
        if not raw_url:
            return
        if not raw_url.startswith(("http://", "https://")):
            raw_url = "https://" + raw_url

        self._cancel_pending_stream_resolver()
        req_id = self._stream_request_id

        self.image_timer.stop()
        self.player.stop()
        self.image_view.clear_view()
        if self.stack.currentIndex() == 3:
            self.web_view.setUrl(QUrl("about:blank"))

        self.current_index = -1
        if self.playlist_widget:
            self.playlist_widget.clearSelection()

        self.current_web_url = raw_url
        self.current_chat_url = ""
        self.current_stream_qualities = {}
        self.current_stream_quality = ""
        if hasattr(self, "btn_quality") and self.btn_quality:
            self.btn_quality.hide()
        self.is_live_stream_playing = False

        label_info = f" ({display_label})" if display_label else ""
        self.show_osd(f"⏳ 라이브 스트림 및 채팅 연결 중{label_info}...", duration=5000)

        cookies_snap = [
            (dom, name, val)
            for (dom, name), val in list(UnifiedMediaPlayer.SHARED_COOKIES.items())
        ]
        resolver = StreamlinkResolverThread(
            raw_url,
            cookies_snapshot=cookies_snap,
            preferred_quality=self.preferred_quality,
            parent=self
        )
        resolver.chat_ready.connect(
            lambda orig_u, ch_u, rid=req_id: self._on_stream_chat_ready(rid, orig_u, ch_u)
        )
        resolver.resolved.connect(
            lambda orig_u, st_u, eng, live, title, ch_u, qmap, rid=req_id: self._on_streamlink_resolved(
                rid, orig_u, st_u, eng, live, title, ch_u, qmap
            )
        )
        resolver.failed.connect(
            lambda orig_u, reason, rid=req_id: self._on_streamlink_failed(rid, orig_u, reason)
        )
        self.stream_resolver = resolver
        resolver.start()

    @staticmethod
    def _on_web_cookie_added(cookie):
        try:
            dom = cookie.domain().strip()
            name = bytes(cookie.name()).decode("utf-8", errors="ignore")
            val = bytes(cookie.value()).decode("utf-8", errors="ignore")
            if dom and name:
                UnifiedMediaPlayer.SHARED_COOKIES[(dom, name)] = val
        except Exception:
            pass

    @staticmethod
    def _on_web_cookie_removed(cookie):
        try:
            dom = cookie.domain().strip()
            name = bytes(cookie.name()).decode("utf-8", errors="ignore")
            UnifiedMediaPlayer.SHARED_COOKIES.pop((dom, name), None)
        except Exception:
            pass

    def _init_web_profiles(self):
        if UnifiedMediaPlayer.SHARED_WEB_PROFILE is None:
            profile_dir = os.path.join(get_data_root_dir(), "web_profile")
            os.makedirs(profile_dir, exist_ok=True)
            prof = QWebEngineProfile("MinimalPlayerMainProfile", QApplication.instance())
            prof.setPersistentStoragePath(profile_dir)
            prof.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
            prof.setHttpUserAgent(CHROME_UA)

            UnifiedMediaPlayer.SHARED_WEB_INTERCEPTOR = SoopHeaderInterceptor(prof)
            prof.setUrlRequestInterceptor(UnifiedMediaPlayer.SHARED_WEB_INTERCEPTOR)

            try:
                cookie_store = prof.cookieStore()
                cookie_store.cookieAdded.connect(UnifiedMediaPlayer._on_web_cookie_added)
                cookie_store.cookieRemoved.connect(UnifiedMediaPlayer._on_web_cookie_removed)
                cookie_store.loadAllCookies()
            except Exception:
                pass

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

    def _on_login_web_url_changed(self, qurl: QUrl):
        """로그인 서랍에서 인증 완료 후 메인 도메인으로 이동하면 접기 전이라도 채팅창을 자동 갱신"""
        if not self.login_drawer_container.isVisible() or not self.current_chat_url:
            return
        host = (qurl.host() or "").lower()
        path = (qurl.path() or "").lower()
        if not host:
            return
        if host.startswith(("login.", "nid.", "accounts.")):
            return
        completed = (
            ("sooplive." in host and not path.startswith("/login"))
            or host == "chzzk.naver.com"
            or host == "www.naver.com"
            or "youtube.com" in host
        )
        if completed:
            if not hasattr(self, "_login_chat_reload_timer"):
                self._login_chat_reload_timer = QTimer(self)
                self._login_chat_reload_timer.setSingleShot(True)
                self._login_chat_reload_timer.timeout.connect(self._reload_chat_after_login)
            self._login_chat_reload_timer.start(450)

    def _reload_chat_after_login(self):
        if self.current_chat_url:
            self._connect_live_chat(self.current_web_url, self.current_chat_url)
            self.show_osd("🔑 로그인 완료 감지: 채팅창을 새로고침했습니다.", duration=2200)

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

    def _connect_live_chat(self, stream_page_url: str, chat_url: str, force_reload: bool = True):
        """플랫폼별 전용 실시간 채팅 URL을 로드합니다."""
        target_url = chat_url or (extract_live_chat_url(stream_page_url) if stream_page_url else "")
        if not target_url:
            return

        self.current_chat_url = target_url
        self.chat_web_page.setAudioMuted(True)
        if not force_reload and self.chat_web_view.url().toString() == target_url:
            return
        self.chat_web_view.load(QUrl(target_url))

    def _on_chat_view_load_finished(self, ok: bool):
        cur_url = self.chat_web_view.url().toString()
        if is_soop_url(cur_url):
            self.chat_web_page.setAudioMuted(True)
            self.chat_web_page.runJavaScript(SOOP_CHAT_DOM_MASK_JS)

    def reload_current_chat(self):
        if self.current_chat_url or self.current_web_url:
            if is_soop_url(self.current_web_url or self.current_chat_url):
                self.current_chat_url = extract_live_chat_url(self.current_web_url or self.current_chat_url)
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
        self._bind_non_conflicting_shortcut("S", self.solo_this_window_audio)
        self._bind_non_conflicting_shortcut("T", self.toggle_always_on_top)
        self._bind_non_conflicting_shortcut("Ctrl+M", self.toggle_mute)
        self._bind_non_conflicting_shortcut("[", lambda: self.prev_media(force=True))
        self._bind_non_conflicting_shortcut("]", lambda: self.next_media(force=True))

    def _init_media_core(self):
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(self._initial_volume_percent / 100.0)
        self.audio_output.setMuted(self.is_muted)

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
            script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
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
            "💡 [Alt + 1 / 2 / 3 / 4] 원클릭 화면 분할   |   [Ctrl + M] 음소거   |   [S] 이 창만 듣기(Solo)   |   [T] 항상 위\n"
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
        self.web_view.setPage(PopupSupportWebPage(self.web_profile, self.web_view))
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
        self.login_web_view.setPage(PopupSupportWebPage(self.web_profile, self.login_web_view))
        self.login_web_view.page().setBackgroundColor(QColor("#16161d"))
        self.login_web_view.urlChanged.connect(self._on_login_web_url_changed)
        ld_layout.addWidget(self.login_web_view)
        self.login_drawer_container.hide()
        chat_body_layout.addWidget(self.login_drawer_container)

        self.chat_web_view = QWebEngineView(self.chat_body_widget)
        self.chat_web_page = PopupSupportWebPage(self.chat_profile, self.chat_web_view)
        self.chat_web_page.setAudioMuted(True)

        mask_script = QWebEngineScript()
        mask_script.setName("SoopMainPageChatMask")
        mask_script.setSourceCode(SOOP_CHAT_DOM_MASK_JS)
        mask_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
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
        """
        재생바(control_bar), OSD, 입력 팝업을 WindowStaysOnTopHint 없는 소유(Owned) Tool 창으로 구성하여
        QVideoWidget/QWebEngineView 네이티브 영상 표면 위에는 선명하게 그려지면서도,
        플레이어보다 앞에 있는 외부 창은 절대 뚫고 나오지 않도록 보장합니다.
        """
        overlay_flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        osd_flags = (
            overlay_flags
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )

        self.osd_window = QWidget(self, osd_flags)
        self.osd_window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.osd_window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.osd_window.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.osd_window.setStyleSheet("background: transparent; border: none;")
        osd_layout = QVBoxLayout(self.osd_window)
        osd_layout.setContentsMargins(0, 0, 0, 0)

        self.osd_label = QLabel(self.osd_window)
        self.osd_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
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
        self.jump_input.setWindowFlags(overlay_flags)
        self.jump_input.setPlaceholderText("탐색 단위(초) 입력 (예: 89, 30) 후 Enter")
        self.jump_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.jump_input.setFixedSize(380, 48)
        self.jump_input.setStyleSheet(popup_qss)
        self.jump_input.returnPressed.connect(self._execute_custom_jump)
        self.jump_input.installEventFilter(self)
        self.jump_input.hide()

        self.interval_input = QLineEdit(self)
        self.interval_input.setWindowFlags(overlay_flags)
        self.interval_input.setPlaceholderText("이미지 자동 넘김 시간(초) 입력 (예: 5, 3.5) 후 Enter")
        self.interval_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.interval_input.setFixedSize(420, 48)
        self.interval_input.setStyleSheet(popup_qss)
        self.interval_input.returnPressed.connect(self._execute_slideshow_interval)
        self.interval_input.installEventFilter(self)
        self.interval_input.hide()

        self.url_input = QLineEdit(self)
        self.url_input.setWindowFlags(overlay_flags)
        self.url_input.setPlaceholderText("라이브/유튜브 URL 입력 (예: play.sooplive.com/... 또는 chzzk...) 후 Enter")
        self.url_input.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.url_input.setFixedSize(580, 48)
        self.url_input.setStyleSheet(popup_qss)
        self.url_input.returnPressed.connect(self._execute_url_load)
        self.url_input.installEventFilter(self)
        self.url_input.hide()

        self.control_bar = QWidget(self, overlay_flags)
        self.control_bar.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.control_bar.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.control_bar.setStyleSheet("background: transparent; border: none;")
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
                padding: 4px 6px;
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
        cb_layout.setContentsMargins(10, 6, 10, 6)
        cb_layout.setSpacing(4)

        self.btn_play_pause = QPushButton("⏸")
        self.btn_play_pause.setToolTip("재생 / 일시정지 (Space)")
        self.btn_play_pause.clicked.connect(self.toggle_play_pause)

        self.lbl_current_time = QLabel("00:00")
        self.lbl_current_time.setMinimumWidth(40)
        self.lbl_current_time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self.seek_slider.sliderMoved.connect(self._on_slider_moved)
        self.seek_slider.sliderReleased.connect(self._on_slider_released)

        self.lbl_total_time = QLabel("00:00")
        self.lbl_total_time.setMinimumWidth(40)
        self.lbl_total_time.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.btn_mute = QPushButton("🔊")
        self.btn_mute.setToolTip("음소거 토글 (Ctrl+M) · 다른 창 모두 끄기 (S)")
        self.btn_mute.clicked.connect(self.toggle_mute)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setFixedWidth(56)
        self.volume_slider.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.volume_slider.setToolTip("볼륨 조절 (↑/↓ 또는 마우스 휠)")
        self.volume_slider.valueChanged.connect(self._on_volume_slider_changed)

        self.btn_speed = QPushButton("1.00x")
        self.btn_speed.setToolTip("클릭 시 1.0x 복원 (C/X로 배속 조절)")
        self.btn_speed.clicked.connect(lambda: self.adjust_playback_rate(reset=True))

        self.btn_seek_unit = QPushButton(f"🎯{self._get_custom_seek_str()}s")
        self.btn_seek_unit.setToolTip("Shift+방향키 점프 단위 설정 (G)")
        self.btn_seek_unit.clicked.connect(self.open_jump_popup)

        self.btn_quality = QPushButton("📺화질")
        self.btn_quality.setToolTip("라이브 스트림 화질 선택")
        self.btn_quality.clicked.connect(self._show_quality_menu)
        self.btn_quality.hide()

        self.btn_new_win = QPushButton("🗔새창")
        self.btn_new_win.setToolTip("새 플레이어 창 추가 열기 (Ctrl+N)")
        self.btn_new_win.clicked.connect(self.spawn_new_player_window)

        self.btn_layout_quick = QPushButton("📐분할")
        self.btn_layout_quick.setToolTip("원클릭 2분할/4분할 및 커스텀 레이아웃 묶음 메뉴 (Alt+1~4)")
        self.btn_layout_quick.clicked.connect(self._show_layout_quick_menu)

        self.btn_always_on_top = QPushButton("📌")
        self.btn_always_on_top.setToolTip("항상 위 고정 토글 (T)")
        self.btn_always_on_top.clicked.connect(self.toggle_always_on_top)

        self.btn_fullscreen = QPushButton("⛶")
        self.btn_fullscreen.setToolTip("전체화면 / 창 모드 전환 (Alt+Enter)")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)

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
        cb_layout.addWidget(self.btn_mute)
        cb_layout.addWidget(self.volume_slider)

        cb_layout.addWidget(self._create_toolbar_separator())
        cb_layout.addWidget(self.btn_speed)
        cb_layout.addWidget(self.btn_seek_unit)
        cb_layout.addWidget(self.btn_quality)

        cb_layout.addWidget(self._create_toolbar_separator())
        cb_layout.addWidget(self.btn_new_win)
        cb_layout.addWidget(self.btn_layout_quick)
        cb_layout.addWidget(self.btn_always_on_top)
        cb_layout.addWidget(self.btn_fullscreen)

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

    def _is_cursor_over_this_window(self, cursor_global: QPoint) -> bool:
        """마우스 포인터 위치의 최상단 창이 현재 플레이어 창(또는 소속 패널·오버레이)인지 판별"""
        if HAS_WIN32:
            try:
                user32 = ctypes.windll.user32
                pt = wintypes.POINT(cursor_global.x(), cursor_global.y())
                hwnd_at = user32.WindowFromPoint(pt)
                if not hwnd_at:
                    return False
                root_hwnd = user32.GetAncestor(hwnd_at, 2)  # GA_ROOT = 2
                allowed_hwnds = {int(self.winId())}
                for panel in self._all_managed_panels():
                    if panel and panel.isVisible() and panel.isWindow():
                        allowed_hwnds.add(int(panel.winId()))
                for ov in self._all_overlay_windows():
                    if ov and ov.isVisible() and ov.isWindow():
                        allowed_hwnds.add(int(ov.winId()))
                return root_hwnd in allowed_hwnds
            except Exception:
                pass
        top_w = QApplication.topLevelAt(cursor_global)
        return (
            top_w is self
            or top_w in self._all_managed_panels()
            or top_w in self._all_overlay_windows()
        )

    def _poll_mouse_state(self):
        if not self._ui_initialized or not self.isVisible() or self.isMinimized():
            if self.control_bar and self.control_bar.isVisible():
                self.control_bar.hide()
            return

        cursor_global = QCursor.pos()
        cursor_over_self = self._is_cursor_over_this_window(cursor_global)

        if not self._is_resizing and not self._active_interacting_panel and (
            QApplication.mouseButtons() == Qt.MouseButton.NoButton
        ):
            if cursor_over_self:
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
            else:
                self.unsetCursor()

        if not self.control_bar:
            return
        if self.stack.currentIndex() not in (2, 3, 4):
            if self.control_bar.isVisible():
                self.control_bar.hide()
            return

        if cursor_over_self:
            video_tl = self.stack.mapToGlobal(QPoint(0, 0))
            video_rect = QRect(video_tl.x(), video_tl.y(), self.stack.width(), self.stack.height())
            if video_rect.contains(cursor_global):
                bottom_threshold = video_rect.bottom() - 95
                if cursor_global.y() >= bottom_threshold:
                    if not self.control_bar.isVisible():
                        self._reposition_control_bar()
                        self.control_bar.show()
                        self._sync_overlay_zorder_native(self.control_bar)
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

        bar_w = min(max(400, vw - 24), 1160)
        compact = bar_w < 700
        self.volume_slider.setVisible(not compact)
        self.btn_new_win.setText("🗔" if compact else "🗔새창")
        self.btn_layout_quick.setText("📐" if compact else "📐분할")
        self.btn_chat_toggle.setText("💬" if compact else "💬채팅")
        self.btn_streamer_toggle.setText("⭐" if compact else "⭐방송")
        self.btn_plist_toggle.setText("📋" if compact else "📋목록")

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

    def _sync_volume_controls(self):
        vol_pct = round(self.audio_output.volume() * 100)
        if hasattr(self, "volume_slider") and self.volume_slider:
            self.volume_slider.blockSignals(True)
            self.volume_slider.setValue(0 if self.is_muted else vol_pct)
            self.volume_slider.blockSignals(False)
        if hasattr(self, "btn_mute") and self.btn_mute:
            self.btn_mute.setText("🔇" if (self.is_muted or vol_pct == 0) else "🔊")

    def _on_volume_slider_changed(self, value: int):
        self._set_exact_volume(value)

    def toggle_mute(self):
        self.is_muted = not self.is_muted
        self.audio_output.setMuted(self.is_muted)
        self._sync_volume_controls()
        self._schedule_save_settings()
        vol_pct = round(self.audio_output.volume() * 100)
        self.show_osd("🔇 음소거 됨" if self.is_muted else f"🔊 음소거 해제 ({vol_pct}%)")

    def solo_this_window_audio(self):
        """현재 창만 소리 켜고 열려 있는 나머지 모든 플레이어 창을 음소거 (멀티뷰 솔로 듣기)"""
        self.is_muted = False
        if round(self.audio_output.volume() * 100) == 0:
            self.audio_output.setVolume(0.7)
        self.audio_output.setMuted(False)
        self._sync_volume_controls()

        muted_others = 0
        for inst in UnifiedMediaPlayer.ACTIVE_INSTANCES:
            if inst is not self and not inst._is_cleaned_up:
                inst.is_muted = True
                inst.audio_output.setMuted(True)
                inst._sync_volume_controls()
                muted_others += 1

        self._schedule_save_settings()
        if muted_others > 0:
            self.show_osd(f"🎧 이 창만 소리 듣기 활성화 (다른 {muted_others}개 창 음소거)")
        else:
            self.show_osd(f"🎧 이 창 소리 활성화 ({round(self.audio_output.volume() * 100)}%)")

    def _show_quality_menu(self):
        if not self.current_stream_qualities:
            return
        menu = QMenu(self)
        for q_name in self.current_stream_qualities.keys():
            act = QAction(f"📺 {q_name}", menu, checkable=True)
            act.setChecked(q_name == self.current_stream_quality)
            act.triggered.connect(lambda checked=False, q=q_name: self.switch_stream_quality(q))
            menu.addAction(act)
        btn_pos = self.btn_quality.mapToGlobal(QPoint(0, -menu.sizeHint().height()))
        menu.exec(btn_pos)

    def switch_stream_quality(self, quality_name: str):
        stream_url = self.current_stream_qualities.get(quality_name)
        if not stream_url:
            return
        self.current_stream_quality = quality_name
        self.preferred_quality = quality_name
        self.btn_quality.setText(f"📺{quality_name}")

        self.player.stop()
        self.player.setSource(QUrl(stream_url))
        self.player.setPlaybackRate(1.0)
        self.player.play()
        self.btn_play_pause.setText("⏸")
        self._schedule_save_settings()
        self.show_osd(f"📺 화질 전환됨: {quality_name}")

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

        if self.current_stream_qualities:
            qual_menu = menu.addMenu(f"📺 라이브 화질 선택 ({self.current_stream_quality})")
            for q_name in self.current_stream_qualities.keys():
                act_q = QAction(q_name, qual_menu, checkable=True)
                act_q.setChecked(q_name == self.current_stream_quality)
                act_q.triggered.connect(lambda checked=False, q=q_name: self.switch_stream_quality(q))
                qual_menu.addAction(act_q)

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

        vol_label = "음소거" if self.is_muted else f"{round(self.audio_output.volume() * 100)}%"
        mode_menu = menu.addMenu(f"🔁 재생 모드 및 볼륨 ({self._get_mode_short_label()} · {vol_label})")
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
        act_mute = QAction("🔇 음소거\tCtrl+M", mode_menu, checkable=True)
        act_mute.setChecked(self.is_muted)
        act_mute.triggered.connect(self.toggle_mute)
        mode_menu.addAction(act_mute)
        mode_menu.addAction("🎧 이 창만 소리 듣기 (Solo)\tS", self.solo_this_window_audio)
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
        chat_menu.addAction("⤓ 플레이어 하단에 붙이기 (폭 맞춤)", lambda: self._set_panel_layout_mode(self.chat_panel, "bottom"))
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

        act_pin = QAction("📌 항상 위 고정\tT", menu, checkable=True)
        act_pin.setChecked(self.is_always_on_top)
        act_pin.triggered.connect(self.toggle_always_on_top)
        menu.addAction(act_pin)

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
        self._schedule_save_settings()
        self.show_osd(f"⚡ 재생 배속: {self.playback_rate:.2f}x")

    def _set_exact_volume(self, percent: int):
        clamped = max(0, min(100, int(percent)))
        self.audio_output.setVolume(clamped / 100.0)
        if clamped > 0 and self.is_muted:
            self.is_muted = False
            self.audio_output.setMuted(False)
        self._sync_volume_controls()
        self._schedule_save_settings()
        self.show_osd(f"🔊 볼륨: {clamped}%")

    def _set_matrix_mode(self, shuffle: bool, repeat_all: bool):
        self.is_shuffle = shuffle
        self.is_repeat_all = repeat_all
        if self.is_shuffle:
            self._rebuild_shuffle_order(keep_current=True)
        if 0 <= self.current_index < len(self.playlist):
            self._sync_title_and_tray(os.path.basename(self.playlist[self.current_index]))
        self._schedule_save_settings()
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

        self.osd_window.move(self.mapToGlobal(QPoint(24, 24)))
        self.osd_window.show()
        self._sync_overlay_zorder_native(self.osd_window)
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
        self._schedule_save_settings()
        self.show_osd(f"✨ 이미지 전환 프리셋: {names.get(mode, '')}")

    def open_url_popup(self):
        self._hide_all_input_popups()
        local_center = QPoint(
            (self.width() - self.url_input.width()) // 2,
            (self.height() - self.url_input.height()) // 2
        )
        self.url_input.move(self.mapToGlobal(local_center))
        self.url_input.setText(self.current_web_url)
        self.url_input.selectAll()
        self.url_input.show()
        self._sync_overlay_zorder_native(self.url_input)
        self.url_input.activateWindow()
        self.url_input.setFocus()

    def open_jump_popup(self):
        self._hide_all_input_popups()
        local_center = QPoint(
            (self.width() - self.jump_input.width()) // 2,
            (self.height() - self.jump_input.height()) // 2
        )
        self.jump_input.move(self.mapToGlobal(local_center))
        self.jump_input.setText(self._get_custom_seek_str())
        self.jump_input.selectAll()
        self.jump_input.show()
        self._sync_overlay_zorder_native(self.jump_input)
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
            self._schedule_save_settings()
            self.show_osd(f"🎯 탐색 단위 설정 완료: {sec_str}초 (Shift + ← / → 로 이동)")
        except ValueError:
            self.show_osd("⚠ 올바른 숫자를 입력하세요 (예: 89, 30)")

    def open_slideshow_interval_popup(self):
        self._hide_all_input_popups()
        local_center = QPoint(
            (self.width() - self.interval_input.width()) // 2,
            (self.height() - self.interval_input.height()) // 2
        )
        self.interval_input.move(self.mapToGlobal(local_center))
        self.interval_input.setText(self._get_interval_sec_str())
        self.interval_input.selectAll()
        self.interval_input.show()
        self._sync_overlay_zorder_native(self.interval_input)
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
            self._schedule_save_settings()
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
        self, req_id: int, orig_url: str, stream_url: str,
        engine_tag: str, is_live: bool, title: str, chat_url: str, qualities: dict
    ):
        if req_id != self._stream_request_id or self._is_cleaned_up:
            return
        if self.stack.currentIndex() == 3:
            self.web_view.setUrl(QUrl("about:blank"))

        self.is_live_stream_playing = is_live
        self.current_web_url = orig_url
        self.current_chat_url = chat_url
        self.current_stream_qualities = qualities or {}
        self.current_stream_quality = engine_tag

        if hasattr(self, "btn_quality") and self.btn_quality:
            if self.current_stream_qualities:
                self.btn_quality.setText(f"📺{engine_tag}")
                self.btn_quality.show()
            else:
                self.btn_quality.hide()

        self.stack.setCurrentIndex(2)
        self.player.stop()
        self.player.setSource(QUrl(stream_url))
        self.player.setPlaybackRate(1.0)
        self.playback_rate = 1.0
        self.btn_speed.setText("1.00x")
        self.player.play()
        self.btn_play_pause.setText("⏸")

        if self.current_chat_url:
            self._connect_live_chat(orig_url, self.current_chat_url, force_reload=False)
            self.chat_panel.show_panel()

        self._force_layout_sync()

        tag = f"LIVE·{engine_tag}" if is_live else f"VOD·{engine_tag}"
        self._sync_title_and_tray(f"[{tag}] {title}")
        self.show_osd(f"🔴 방송 및 실시간 채팅 연결 완료 ({tag})", duration=3000)

    def _on_streamlink_failed(self, req_id: int, orig_url: str, reason: str):
        if req_id != self._stream_request_id or self._is_cleaned_up:
            return
        self.is_live_stream_playing = False
        self.current_web_url = orig_url
        self.current_chat_url = extract_live_chat_url(orig_url, already_normalized=True)
        self.current_stream_qualities = {}
        self.current_stream_quality = ""
        if hasattr(self, "btn_quality") and self.btn_quality:
            self.btn_quality.hide()
        self.stack.setCurrentIndex(3)
        self.web_view.load(QUrl(orig_url))
        if self.current_chat_url:
            self._connect_live_chat(orig_url, self.current_chat_url, force_reload=False)
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

        seen = set(self.playlist)
        added_count = 0
        for item in collected:
            if item not in seen:
                seen.add(item)
                self.playlist.append(item)
                added_count += 1

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
            self.show_osd(f"목록에 {added_count}개 추가됨 (총 {len(self.playlist)}개)")

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
        self._schedule_save_settings()
        self.show_osd(f"🔀 재생 순서: {'랜덤 셔플' if self.is_shuffle else '순차 재생'} ({self._get_mode_short_label()})")

    def toggle_repeat_mode(self):
        self.is_repeat_all = not self.is_repeat_all
        if 0 <= self.current_index < len(self.playlist):
            self._sync_title_and_tray(os.path.basename(self.playlist[self.current_index]))
        self._schedule_save_settings()
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
            if not self.is_image_paused:
                self.image_timer.start(self.image_slideshow_interval)
            return

        self._cancel_pending_stream_resolver()

        if self.stack.currentIndex() == 3:
            self.web_view.setUrl(QUrl("about:blank"))
        if self.current_chat_url and hasattr(self, "chat_web_view") and self.chat_web_view:
            self.chat_web_view.setUrl(QUrl("about:blank"))

        self.is_live_stream_playing = False
        self.current_web_url = ""
        self.current_chat_url = ""
        self.current_stream_qualities = {}
        self.current_stream_quality = ""
        if hasattr(self, "btn_quality") and self.btn_quality:
            self.btn_quality.hide()
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

            new_pixmap = load_auto_oriented_pixmap(target_path)
            accepted = self.image_view.show_image(
                new_pixmap, play_sound_callback=self.play_transition_sfx, force=force
            )
            if not accepted:
                if not self.is_image_paused:
                    self.image_timer.start(self.image_slideshow_interval)
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
        self._schedule_save_settings()
        self.show_osd(f"⚡ 재생 배속: {self.playback_rate:.2f}x")

    def change_volume(self, delta_percent: int):
        current_vol = 0 if self.is_muted else round(self.audio_output.volume() * 100)
        new_vol = max(0, min(100, current_vol + delta_percent))
        self._set_exact_volume(new_vol)

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
        elif key == Qt.Key.Key_M and not (modifiers & Qt.KeyboardModifier.ControlModifier):
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
        if self.osd_window and self.osd_window.isVisible():
            self.osd_window.move(self.mapToGlobal(QPoint(24, 24)))
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

        self._flush_settings_to_disk()
        self._cancel_pending_stream_resolver()

        if hasattr(self, "hover_poll_timer") and self.hover_poll_timer:
            self.hover_poll_timer.stop()
        if hasattr(self, "image_timer") and self.image_timer:
            self.image_timer.stop()
        if hasattr(self, "player") and self.player:
            self.player.stop()

        for wv_attr in ("web_view", "login_web_view", "chat_web_view"):
            wv = getattr(self, wv_attr, None)
            if wv is not None:
                try:
                    wv.setUrl(QUrl("about:blank"))
                except Exception:
                    pass

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

        was_tray_visible = False
        if hasattr(self, "tray_icon") and self.tray_icon:
            was_tray_visible = self.tray_icon.isVisible()
            self.tray_icon.hide()

        if self in UnifiedMediaPlayer.ACTIVE_INSTANCES:
            UnifiedMediaPlayer.ACTIVE_INSTANCES.remove(self)

        if was_tray_visible and UnifiedMediaPlayer.ACTIVE_INSTANCES:
            next_inst = UnifiedMediaPlayer.ACTIVE_INSTANCES[0]
            if hasattr(next_inst, "tray_icon") and next_inst.tray_icon:
                next_inst.tray_icon.show()

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
