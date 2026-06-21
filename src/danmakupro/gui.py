"""文件选择 GUI 模块

提供 PySide6 图形界面，让用户选择视频文件和对应的弹幕 XML 文件。
"""

import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QFileDialog, QMessageBox,
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton,
)


class FileSelectDialog(QDialog):
    """文件选择对话框：选择视频文件和弹幕 XML 文件。

    功能：
        - 浏览并选择视频文件（.mp4 / .flv）
        - 浏览并选择弹幕 XML 文件（.xml）
        - 自动检测同名的 XML 文件（视频与 XML 同目录同前缀）
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("选择视频和弹幕文件")
        self.setMinimumWidth(550)

        layout = QVBoxLayout(self)

        # ---- 视频文件选择行 ----
        video_layout = QHBoxLayout()
        video_layout.addWidget(QLabel("视频文件:"))
        self.video_edit = QLineEdit()
        self.video_edit.setReadOnly(True)
        self.video_edit.setPlaceholderText("请选择视频文件 (.mp4/.flv)")
        video_layout.addWidget(self.video_edit)
        video_btn = QPushButton("浏览...")
        video_btn.clicked.connect(self._browse_video)
        video_layout.addWidget(video_btn)
        layout.addLayout(video_layout)

        # ---- XML 文件选择行 ----
        xml_layout = QHBoxLayout()
        xml_layout.addWidget(QLabel("弹幕XML:"))
        self.xml_edit = QLineEdit()
        self.xml_edit.setReadOnly(True)
        self.xml_edit.setPlaceholderText("请选择弹幕 XML 文件 (.xml)")
        xml_layout.addWidget(self.xml_edit)
        xml_btn = QPushButton("浏览...")
        xml_btn.clicked.connect(self._browse_xml)
        xml_layout.addWidget(xml_btn)
        layout.addLayout(xml_layout)

        # ---- 确定/取消按钮 ----
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _browse_video(self):
        """浏览视频文件，并自动检测同名 XML 文件"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频文件", "./source",
            "视频文件 (*.mp4 *.flv);;所有文件 (*.*)",
        )
        if path:
            self.video_edit.setText(path)
            # 自动检测同名的 XML 文件
            xml_guess = str(Path(path).with_suffix(".xml"))
            if not self.xml_edit.text() and Path(xml_guess).exists():
                self.xml_edit.setText(xml_guess)

    def _browse_xml(self):
        """浏览 XML 文件"""
        start_dir = str(Path(self.video_edit.text()).parent) if self.video_edit.text() else "./source"
        path, _ = QFileDialog.getOpenFileName(
            self, "选择弹幕 XML 文件", start_dir,
            "XML 文件 (*.xml);;所有文件 (*.*)",
        )
        if path:
            self.xml_edit.setText(path)

    def video_path(self) -> str:
        """获取用户选择的视频文件路径"""
        return self.video_edit.text()

    def xml_path(self) -> str:
        """获取用户选择的 XML 文件路径"""
        return self.xml_edit.text()


def select_files() -> tuple[str, str]:
    """打开文件选择对话框，让用户选择视频和弹幕 XML 文件。

    Returns:
        (video_path, xml_path) 元组

    Raises:
        SystemExit: 用户取消选择或未选择文件
    """
    _app = QApplication.instance() or QApplication(sys.argv)

    dlg = FileSelectDialog()
    if dlg.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)

    video_path = dlg.video_path()
    xml_path = dlg.xml_path()

    if not video_path:
        QMessageBox.warning(None, "提示", "未选择视频文件，程序退出")
        sys.exit(1)
    if not xml_path:
        QMessageBox.warning(None, "提示", "未选择 XML 文件，程序退出")
        sys.exit(1)

    return video_path, xml_path


def main() -> None:
    """GUI 入口：弹出文件选择对话框，选定文件后启动压制引擎"""
    try:
        from .burner import DanmakuBurner
    except ImportError:
        from danmakupro.burner import DanmakuBurner

    video_path, xml_path = select_files()
    burner = DanmakuBurner(video_in=video_path, xml_in=xml_path)
    burner.run()

if __name__ == "__main__":
    main()