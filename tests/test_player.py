import os
import sys
import json
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QRect, QPoint
from PyQt6.QtGui import QImage, QColor

import storage
import streaming
import main as mp


class TestStorageAndStreaming(unittest.TestCase):
    def test_format_ms_to_time(self):
        self.assertEqual(storage.format_ms_to_time(0), "00:00")
        self.assertEqual(storage.format_ms_to_time(65000), "01:05")
        self.assertEqual(storage.format_ms_to_time(3661000), "01:01:01")
        self.assertEqual(storage.format_ms_to_time(-500), "00:00")

    def test_safe_json_and_backup_recovery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "sample.json")
            storage.safe_save_json(fpath, {"a": 1})
            storage.safe_save_json(fpath, {"a": 2})
            self.assertEqual(storage.safe_load_json(fpath, None), {"a": 2})

            # Corrupt main file and verify automatic .bak recovery
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("{broken json")
            self.assertEqual(storage.safe_load_json(fpath, None), {"a": 1})

    def test_settings_merge_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            s_path = os.path.join(tmpdir, "settings.json")
            storage.safe_save_json(s_path, {"volume": 42, "panels": {"chat": {"dock_width": 410}}})
            loaded = storage.load_app_settings(s_path)
            self.assertEqual(loaded["volume"], 42)
            self.assertEqual(loaded["custom_seek_sec"], 89)
            self.assertEqual(loaded["panels"]["chat"]["dock_width"], 410)
            self.assertEqual(loaded["panels"]["chat"]["mode"], "right")

    def test_compute_magnetic_snap(self):
        target = QRect(0, 0, 500, 500)
        moving = QRect(510, 5, 300, 400)
        snapped = storage.compute_magnetic_snap(moving, [target], snap_dist=18)
        self.assertEqual(snapped, QPoint(500, 0))

    def test_url_validation_and_chat_extraction(self):
        self.assertTrue(streaming.is_valid_http_url("https://play.sooplive.com/ecvhao"))
        self.assertFalse(streaming.is_valid_http_url("javascript:alert(1)"))
        self.assertTrue(streaming.is_soop_url("https://play.sooplive.co.kr/devil0108"))
        self.assertFalse(streaming.is_soop_url("https://evil.example.com/?q=sooplive.com"))

        self.assertEqual(
            streaming.extract_live_chat_url("https://chzzk.naver.com/live/bb382c2c0cc9fa7c86ab3b037fb5799c"),
            "https://chzzk.naver.com/live/bb382c2c0cc9fa7c86ab3b037fb5799c/chat"
        )
        self.assertEqual(
            streaming.extract_live_chat_url("https://www.twitch.tv/testuser"),
            "https://www.twitch.tv/popout/testuser/chat?popout="
        )
        self.assertEqual(
            streaming.extract_live_chat_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "https://www.youtube.com/live_chat?v=dQw4w9WgXcQ"
        )
        self.assertEqual(
            streaming.extract_live_chat_url("https://play.sooplive.com/ecvhao/298687593?vtype=chat", already_normalized=True),
            "https://play.sooplive.com/ecvhao/298687593"
        )
        self.assertEqual(
            streaming.extract_live_chat_url("https://vod.sooplive.co.kr/player/12345", already_normalized=True),
            ""
        )


class TestPlayerWindowOffscreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_player_features_and_settings_isolation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Backup shared settings state
            prev_settings = mp.UnifiedMediaPlayer.SHARED_SETTINGS
            mp.UnifiedMediaPlayer.SHARED_SETTINGS = dict(storage.DEFAULT_SETTINGS)

            p1 = mp.UnifiedMediaPlayer()
            p1.settings_file = os.path.join(tmpdir, "settings.json")

            # 1. Mute & Volume
            p1._set_exact_volume(55)
            self.assertEqual(round(p1.audio_output.volume() * 100), 55)
            p1.toggle_mute()
            self.assertTrue(p1.is_muted)
            self.assertTrue(p1.audio_output.isMuted())
            p1._set_exact_volume(60)
            self.assertFalse(p1.is_muted)

            # 2. Multi-window Audio Solo
            p2 = p1.spawn_new_player_window()
            p2.settings_file = os.path.join(tmpdir, "settings.json")
            p1.solo_this_window_audio()
            self.assertFalse(p1.is_muted)
            self.assertTrue(p2.is_muted)

            # 3. Always on top toggle
            orig_pin = p1.is_always_on_top
            p1.toggle_always_on_top()
            self.assertEqual(p1.is_always_on_top, not orig_pin)
            p1.toggle_always_on_top()
            self.assertEqual(p1.is_always_on_top, orig_pin)

            # 4. Quality switch with resolved stream map
            p1._stream_request_id += 1
            rid = p1._stream_request_id
            qmap = {"1080p60": "https://example.com/1080.m3u8", "720p60": "https://example.com/720.m3u8"}
            p1._on_streamlink_resolved(
                rid, "https://play.sooplive.com/test", qmap["1080p60"],
                "1080p60", True, "테스트 방송", "", qmap
            )
            self.assertEqual(p1.current_stream_quality, "1080p60")
            p1.switch_stream_quality("720p60")
            self.assertEqual(p1.current_stream_quality, "720p60")
            self.assertEqual(p1.preferred_quality, "720p60")

            # 5. Playlist deduplication & shuffle/repeat index matrix
            img1 = os.path.join(tmpdir, "01.png")
            img2 = os.path.join(tmpdir, "02.png")
            for p in (img1, img2):
                im = QImage(32, 32, QImage.Format.Format_ARGB32)
                im.fill(QColor("#00e5ff"))
                im.save(p, "PNG")
            p1._append_paths_to_playlist([img1, img2, img1])
            self.assertEqual(len(p1.playlist), 2)
            self.assertEqual(p1.current_stream_qualities, {})

            # 6. Settings persistence verification
            p1._flush_settings_to_disk()
            saved = storage.load_app_settings(p1.settings_file)
            self.assertEqual(saved["volume"], 60)
            self.assertEqual(saved["preferred_quality"], "720p60")

            # Clean up windows without exiting Python process before assertions finish
            p2._cleanup_instance_resources()
            p2.close()
            p1._cleanup_instance_resources()
            p1.close()
            mp.UnifiedMediaPlayer.SHARED_SETTINGS = prev_settings


if __name__ == "__main__":
    unittest.main(verbosity=2)
