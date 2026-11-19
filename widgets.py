import math

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QSizePolicy
)
from PyQt6.QtCore import (
    Qt, QTimer, QPoint, QPointF, QRect, QRectF, QEvent,
    QVariantAnimation, QEasingCurve
)
from PyQt6.QtGui import (
    QPixmap, QPainter, QPainterPath,
    QTransform, QColor, QBrush, QPen, QLinearGradient, QPolygonF, QCursor
)

from storage import compute_magnetic_snap


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
        self.btn_dock_bottom.setToolTip("플레이어 아래쪽에 붙이고 가로 폭을 플레이어에 맞추기 (드래그 이동 가능)")
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

    def set_panel_mode(self, new_mode: str, notify: bool = True):
        if new_mode not in ("right", "bottom", "floating"):
            new_mode = "right"
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
            if notify:
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
            if notify:
                self.player_win.show_osd("⤓ 패널 하단 결합 (상단 바 드래그 시 자유 이동 가능)")

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
            if notify:
                self.player_win.show_osd("❐ 독립 창 분리 완료 (상단 헤더를 잡고 원하는 곳으로 이동하세요)")

        if notify and hasattr(self.player_win, "_schedule_save_settings"):
            self.player_win._schedule_save_settings()
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
            was_resizing = self._is_resizing
            self._is_resizing = False
            self._is_dragging = False
            self._resize_edges = Qt.Edge(0)
            self.unsetCursor()
            if was_resizing and hasattr(self.player_win, "_schedule_save_settings"):
                self.player_win._schedule_save_settings()
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
