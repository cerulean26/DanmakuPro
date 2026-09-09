"""弹幕压制 GUI 主窗口"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDropEvent, QFont, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..config.loader import load_config
from .worker import BurnWorker

VIDEO_EXTENSIONS = {".mp4", ".flv", ".mkv", ".avi", ".mov", ".ts", ".webm", ".wmv"}


class MainWindow(QMainWindow):
    """弹幕压制主窗口"""

    def __init__(self) -> None:
        super().__init__()
        self._worker: BurnWorker | None = None
        self._last_dir: str = ""
        self._config_path: str = ""
        self._setup_ui()
        self._setup_menu()
        self._connect_signals()
        self._auto_detect_config()

    def _setup_ui(self) -> None:
        self.setWindowTitle("DanmakuPro - 弹幕压制")
        self.setMinimumSize(620, 520)
        self.resize(680, 560)
        self.setAcceptDrops(True)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        font = QFont("Microsoft YaHei", 10)

        file_group = QGroupBox("输入文件（支持拖拽视频/XML 到窗口）")
        file_layout = QVBoxLayout(file_group)
        file_layout.setSpacing(8)

        self._video_edit = QLineEdit()
        self._video_edit.setPlaceholderText("选择视频文件或拖拽到窗口...")
        self._video_edit.setFont(font)
        video_btn = QPushButton("浏览")
        video_btn.setFont(font)
        video_btn.clicked.connect(self._browse_video)
        video_row = QHBoxLayout()
        video_row.addWidget(QLabel("视频:"))
        video_row.addWidget(self._video_edit)
        video_row.addWidget(video_btn)
        file_layout.addLayout(video_row)

        self._xml_edit = QLineEdit()
        self._xml_edit.setPlaceholderText("自动匹配同名 XML...")
        self._xml_edit.setFont(font)
        xml_btn = QPushButton("浏览")
        xml_btn.setFont(font)
        xml_btn.clicked.connect(self._browse_xml)
        xml_row = QHBoxLayout()
        xml_row.addWidget(QLabel("弹幕:"))
        xml_row.addWidget(self._xml_edit)
        xml_row.addWidget(xml_btn)
        file_layout.addLayout(xml_row)

        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText("自动生成 xx-弹幕版.mp4...")
        self._output_edit.setFont(font)
        output_btn = QPushButton("浏览")
        output_btn.setFont(font)
        output_btn.clicked.connect(self._browse_output)
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("输出:"))
        output_row.addWidget(self._output_edit)
        output_row.addWidget(output_btn)
        file_layout.addLayout(output_row)

        root.addWidget(file_group)

        # 编码选项
        option_row = QHBoxLayout()
        option_row.setSpacing(16)
        option_row.addWidget(QLabel("编码模式:"))
        self._encode_combo = QComboBox()
        self._encode_combo.setFont(font)
        self._encode_combo.addItems(["自动", "GPU (NVENC)", "CPU (x264)", "QSV"])
        self._encode_combo.setCurrentIndex(0)
        option_row.addWidget(self._encode_combo)
        option_row.addStretch()
        self._overwrite_check = QCheckBox("覆盖已有文件")
        self._overwrite_check.setChecked(True)
        self._overwrite_check.setFont(font)
        option_row.addWidget(self._overwrite_check)
        root.addLayout(option_row)

        config_row = QHBoxLayout()
        config_row.setSpacing(8)
        config_row.addWidget(QLabel("弹幕设置:"))
        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(10, 60)
        self._font_size_spin.setValue(25)
        self._font_size_spin.setSuffix(" px")
        self._font_size_spin.setFont(font)
        self._font_size_spin.setToolTip("弹幕字体大小")
        config_row.addWidget(QLabel("字体"))
        config_row.addWidget(self._font_size_spin)
        config_row.addSpacing(12)
        self._text_rows_spin = QSpinBox()
        self._text_rows_spin.setRange(1, 10)
        self._text_rows_spin.setValue(4)
        self._text_rows_spin.setSuffix(" 行")
        self._text_rows_spin.setFont(font)
        self._text_rows_spin.setToolTip("同时显示的文本弹幕行数")
        config_row.addWidget(QLabel("文本"))
        config_row.addWidget(self._text_rows_spin)
        config_row.addSpacing(12)
        self._gift_rows_spin = QSpinBox()
        self._gift_rows_spin.setRange(1, 5)
        self._gift_rows_spin.setValue(2)
        self._gift_rows_spin.setSuffix(" 行")
        self._gift_rows_spin.setFont(font)
        self._gift_rows_spin.setToolTip("同时显示的礼物弹幕行数")
        config_row.addWidget(QLabel("礼物"))
        config_row.addWidget(self._gift_rows_spin)
        config_row.addStretch()
        root.addLayout(config_row)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._start_btn = QPushButton("开始压制")
        self._start_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self._start_btn.setFixedSize(140, 36)
        self._start_btn.clicked.connect(self._start)
        btn_row.addWidget(self._start_btn)
        self._stop_btn = QPushButton("停止压制")
        self._stop_btn.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self._stop_btn.setFixedSize(100, 36)
        self._stop_btn.setVisible(False)
        self._stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(self._stop_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # 进度条
        self._progress = QProgressBar()
        self._progress.setFont(font)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._speed_label = QLabel("")
        self._speed_label.setFont(font)
        self._speed_label.setVisible(False)
        root.addWidget(self._speed_label)

        # 日志输出
        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFont(QFont("Consolas", 9))
        self._log_view.setStyleSheet("QTextEdit { background: #1e1e1e; color: #d4d4d4; }")
        root.addWidget(self._log_view)

        # 状态栏
        self.statusBar().setFont(font)
        self.statusBar().showMessage("就绪")

    def _connect_signals(self) -> None:
        self._video_edit.textChanged.connect(self._on_video_changed)

    def _setup_menu(self) -> None:
        menu_bar = self.menuBar()
        settings_menu = menu_bar.addMenu("设置")
        config_action = QAction("配置文件...", self)
        config_action.triggered.connect(self._select_config)
        settings_menu.addAction(config_action)

    def _select_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择配置文件", self._last_dir,
            "YAML 文件 (*.yaml *.yml);;所有文件 (*)",
        )
        if path:
            self._config_path = self._normalize(path)
            self._update_last_dir(path)
            self.statusBar().showMessage(f"已加载配置: {self._config_path}", 3000)

    def _auto_detect_config(self) -> None:
        candidates = [Path("danmakupro.yaml"), Path.home() / "danmakupro.yaml"]
        for p in candidates:
            if p.exists():
                self._config_path = p.as_posix()
                config = load_config(self._config_path)
                self._font_size_spin.setValue(config.style.font_size)
                self._text_rows_spin.setValue(config.ratio.max_text_rows)
                self._gift_rows_spin.setValue(config.ratio.max_gift_rows)
                return

    def _normalize(self, file_path: str) -> str:
        return Path(file_path).as_posix()

    def _on_video_changed(self, text: str) -> None:
        if not text:
            return
        video_path = Path(text)
        if video_path.suffix.lower() in VIDEO_EXTENSIONS:
            if not self._xml_edit.text():
                xml_path = video_path.with_suffix(".xml")
                if xml_path.exists():
                    self._xml_edit.setText(xml_path.as_posix())
            out_path = video_path.parent / f"{video_path.stem}-弹幕版.mp4"
            self._output_edit.setText(out_path.as_posix())

    def _update_last_dir(self, file_path: str) -> None:
        parent = Path(file_path).parent.as_posix()
        if parent:
            self._last_dir = parent

    def _browse_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频文件", self._last_dir,
            "视频文件 (*.mp4 *.flv *.mkv *.avi *.mov *.ts *.webm);;所有文件 (*)",
        )
        if path:
            path = self._normalize(path)
            self._update_last_dir(path)
            self._video_edit.setText(path)

    def _browse_xml(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择弹幕 XML 文件", self._last_dir,
            "XML 文件 (*.xml);;所有文件 (*)",
        )
        if path:
            path = self._normalize(path)
            self._update_last_dir(path)
            self._xml_edit.setText(path)

    def _browse_output(self) -> None:
        start_dir = self._last_dir
        default_name = ""
        if self._video_edit.text():
            video_path = Path(self._video_edit.text())
            start_dir = video_path.parent.as_posix()
            default_name = f"{video_path.stem}-弹幕版.mp4"
        path, _ = QFileDialog.getSaveFileName(
            self, "选择输出路径",
            str(Path(start_dir) / default_name) if default_name else start_dir,
            "视频文件 (*.mp4 *.flv *.mkv *.avi *.mov);;所有文件 (*)",
        )
        if path:
            path = self._normalize(path)
            self._update_last_dir(path)
            self._output_edit.setText(path)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._video_edit.setStyleSheet("QLineEdit { border: 2px solid #4a90d9; }")
            self._xml_edit.setStyleSheet("QLineEdit { border: 2px solid #4a90d9; }")

    def dragLeaveEvent(self, event) -> None:
        self._video_edit.setStyleSheet("")
        self._xml_edit.setStyleSheet("")

    def dropEvent(self, event: QDropEvent) -> None:
        self._video_edit.setStyleSheet("")
        self._xml_edit.setStyleSheet("")
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if not file_path or not Path(file_path).is_file():
                continue
            file_path = self._normalize(file_path)
            suffix = Path(file_path).suffix.lower()
            if suffix in VIDEO_EXTENSIONS:
                self._video_edit.setText(file_path)
                self._update_last_dir(file_path)
            elif suffix == ".xml":
                self._xml_edit.setText(file_path)
                self._update_last_dir(file_path)

    def _start(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.warning(self, "提示", "正在压制中，请先停止当前任务")
            return

        video_in = self._video_edit.text().strip()
        xml_in = self._xml_edit.text().strip()
        video_out = self._output_edit.text().strip()

        if not video_in:
            QMessageBox.warning(self, "提示", "请选择视频文件")
            return
        if not Path(video_in).exists():
            QMessageBox.warning(self, "提示", f"视频文件不存在:\n{video_in}")
            return

        if not xml_in:
            video_path = Path(video_in)
            xml_path = video_path.with_suffix(".xml")
            if not xml_path.exists():
                QMessageBox.warning(
                    self, "提示",
                    f"未找到同名 XML 文件，请手动选择:\n{xml_path}",
                )
                return
            xml_in = xml_path.as_posix()

        if not video_out:
            video_path = Path(video_in)
            video_out = (video_path.parent / f"{video_path.stem}-弹幕版.mp4").as_posix()

        if Path(video_out).exists() and not self._overwrite_check.isChecked():
            reply = QMessageBox.question(
                self, "确认覆盖",
                f"输出文件已存在，是否覆盖?\n{video_out}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        mode_map = {"自动": "auto", "GPU (NVENC)": "gpu", "CPU (x264)": "cpu", "QSV": "qsv"}
        encode_mode = mode_map[self._encode_combo.currentText()]

        config_path = self._config_path or None
        config = load_config(config_path)
        config = replace(
            config,
            style=replace(config.style, font_size=self._font_size_spin.value()),
            ratio=replace(
                config.ratio,
                max_text_rows=self._text_rows_spin.value(),
                max_gift_rows=self._gift_rows_spin.value(),
            ),
        )

        self._start_btn.setEnabled(False)
        self._stop_btn.setVisible(True)
        self._progress.setVisible(True)
        self._progress.setMaximum(100)
        self._progress.setValue(0)
        self._speed_label.setVisible(True)
        self._speed_label.setText("准备中...")
        self._log_view.clear()
        self.statusBar().showMessage("正在压制...")

        self._worker = BurnWorker(video_in, xml_in, video_out, encode_mode, config)
        self._worker.progress.connect(self._on_progress)
        self._worker.speed.connect(self._on_speed)
        self._worker.log.connect(self._on_log)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, current: int, total: int) -> None:
        if self._progress.maximum() != total:
            self._progress.setMaximum(total)
        self._progress.setValue(current)

    def _on_speed(self, value: float) -> None:
        self._speed_label.setText(f"编码速度: {value:.1f}x" if value > 0 else "编码速度: --")

    def _on_log(self, message: str) -> None:
        self._log_view.append(message.rstrip("\n"))
        cursor = self._log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._log_view.setTextCursor(cursor)

    def _stop(self) -> None:
        if self._worker is not None:
            self._worker.force_stop()
            self._stop_btn.setEnabled(False)
            self.statusBar().showMessage("正在停止...")

    def _on_finished(self, success: bool, message: str) -> None:
        self._start_btn.setEnabled(True)
        self._stop_btn.setVisible(False)
        self._stop_btn.setEnabled(True)
        if message == "STOPPED":
            self._progress.setValue(0)
            self._progress.setVisible(False)
            self._speed_label.setText("")
            self._speed_label.setVisible(False)
            self._log_view.clear()
            self.statusBar().showMessage("已停止")
        elif success:
            self._progress.setValue(self._progress.maximum())
            self._progress.setVisible(False)
            self._speed_label.setText("")
            self._speed_label.setVisible(False)
            self.statusBar().showMessage("完成")
            self._video_edit.clear()
            self._xml_edit.clear()
            self._output_edit.clear()
        else:
            self._progress.setValue(0)
            self._progress.setVisible(False)
            self._speed_label.setText("")
            self._speed_label.setVisible(False)
            self.statusBar().showMessage("失败")
            QMessageBox.critical(self, "错误", f"压制失败:\n{message}")
        self._disconnect_worker()

    def _disconnect_worker(self) -> None:
        if self._worker is not None:
            self._worker.progress.disconnect(self._on_progress)
            self._worker.speed.disconnect(self._on_speed)
            self._worker.log.disconnect(self._on_log)
            self._worker.finished.disconnect(self._on_finished)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._worker is not None and self._worker.isRunning():
            reply = QMessageBox.question(
                self, "确认退出",
                "压制正在进行中，退出将中断压制任务。\n确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._worker.force_stop()
            self._worker.wait(5000)
        event.accept()