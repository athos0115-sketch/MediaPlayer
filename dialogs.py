from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QLineEdit, QPushButton, QDialog, QComboBox, QFormLayout, QMessageBox,
    QInputDialog
)
from PyQt6.QtCore import Qt

from streaming import is_soop_url, is_valid_http_url

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
        self.edit_url.setPlaceholderText("예: https://chzzk.naver.com/live/... 또는 https://play.sooplive.com/아이디")

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
        if not is_valid_http_url(url):
            QMessageBox.warning(self, "입력 확인", "올바른 웹 주소(http/https URL)를 입력해 주세요.")
            return
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

    def _shared_streamers(self) -> list:
        return self.player_win.__class__.SHARED_STREAMERS

    def _refresh_list(self):
        self.list_widget.clear()
        for idx, item in enumerate(self._shared_streamers()):
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
            self._shared_streamers().append(res)
            self.player_win.save_and_refresh_streamers()
            self._refresh_list()

    def _edit_selected(self):
        cur = self.list_widget.currentItem()
        if not cur:
            return
        idx = cur.data(Qt.ItemDataRole.UserRole)
        streamers = self._shared_streamers()
        if not (0 <= idx < len(streamers)):
            return
        dlg = AddStreamerDialog(self, edit_data=streamers[idx])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            streamers[idx] = dlg.get_result()
            self.player_win.save_and_refresh_streamers()
            self._refresh_list()

    def _delete_selected(self):
        cur = self.list_widget.currentItem()
        if not cur:
            return
        idx = cur.data(Qt.ItemDataRole.UserRole)
        streamers = self._shared_streamers()
        if 0 <= idx < len(streamers):
            removed = streamers.pop(idx)
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

    def _shared_layouts(self) -> list:
        return self.player_win.__class__.SHARED_LAYOUTS

    def _refresh_list(self):
        self.list_widget.clear()
        for idx, item in enumerate(self._shared_layouts()):
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
        if 0 <= idx < len(self._shared_layouts()):
            self.player_win.apply_saved_custom_layout(idx)

    def _rename_selected(self):
        cur = self.list_widget.currentItem()
        if not cur:
            return
        idx = cur.data(Qt.ItemDataRole.UserRole)
        layouts = self._shared_layouts()
        if not (0 <= idx < len(layouts)):
            return
        old_name = layouts[idx].get("name", "")
        new_name, ok = QInputDialog.getText(
            self, "레이아웃 이름 변경", "새 레이아웃 이름을 입력하세요:", QLineEdit.EchoMode.Normal, old_name
        )
        if ok and new_name.strip():
            layouts[idx]["name"] = new_name.strip()
            self.player_win.save_layouts_to_disk()
            self._refresh_list()

    def _delete_selected(self):
        cur = self.list_widget.currentItem()
        if not cur:
            return
        idx = cur.data(Qt.ItemDataRole.UserRole)
        layouts = self._shared_layouts()
        if 0 <= idx < len(layouts):
            removed = layouts.pop(idx)
            self.player_win.save_layouts_to_disk()
            self._refresh_list()
            self.player_win.show_osd(f"🗑 레이아웃 삭제됨: {removed.get('name')}")

    def _import_layouts(self):
        self.player_win.import_layouts_from_file()
        self._refresh_list()
