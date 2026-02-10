import sys
import time
import psutil
import ctypes
import subprocess
import win32gui
import win32process
import win32api
import win32con

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QPushButton,
    QSystemTrayIcon, QMenu, QAction, QInputDialog, QHBoxLayout
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QPoint, QRect, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt5.QtGui import QFont, QPainter, QPen, QColor, QIcon, QPixmap, QBrush


def get_refresh_rate():
    dev = win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS)
    return dev.DisplayFrequency


class SlideButton(QWidget):
    """滑动按钮控件"""
    triggered = pyqtSignal()
    
    def __init__(self, text, icon, color, parent=None):
        super().__init__(parent)
        self.text = text
        self.icon = icon
        self.color = QColor(color)
        self.bg_color = QColor(40, 40, 45, 200)  # 深色半透明背景
        self.slider_pos = 0
        self.dragging = False
        self.start_x = 0
        
        self.setFixedHeight(36)
        self.setMinimumWidth(160)
        self.setCursor(Qt.PointingHandCursor)
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 左边距
        margin_left = 10
        
        # 绘制背景
        painter.setBrush(QBrush(self.bg_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(margin_left, 0, self.width() - margin_left, self.height(), 18, 18)
        
        # 绘制进度（更柔和的渐变）
        if self.slider_pos > 0:
            progress_width = int(self.slider_pos + 32)
            progress_color = QColor(self.color)
            progress_color.setAlpha(80)  # 半透明
            painter.setBrush(QBrush(progress_color))
            painter.drawRoundedRect(margin_left, 0, progress_width, self.height(), 18, 18)
        
        # 绘制滑块
        slider_x = int(self.slider_pos) + margin_left
        painter.setBrush(QBrush(self.color))
        painter.drawRoundedRect(slider_x + 2, 2, 32, 32, 16, 16)
        
        # 绘制图标
        painter.setPen(QPen(Qt.white))
        painter.setFont(QFont("Segoe UI Emoji", 12))
        painter.drawText(QRect(slider_x + 2, 2, 32, 32), Qt.AlignCenter, self.icon)
        
        # 绘制文字提示
        if self.slider_pos < self.width() - 40 - margin_left:
            painter.setPen(QPen(QColor(160, 160, 160)))
            painter.setFont(QFont("Microsoft YaHei UI", 9))
            text_x = int(self.slider_pos + 40) + margin_left
            painter.drawText(QRect(text_x, 0, self.width() - text_x, self.height()), 
                           Qt.AlignLeft | Qt.AlignVCenter, f"滑动{self.text} →")
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            margin_left = 10
            adjusted_slider_pos = self.slider_pos + margin_left
            if event.pos().x() >= adjusted_slider_pos and event.pos().x() <= adjusted_slider_pos + 36:
                self.dragging = True
                self.start_x = event.pos().x() - (self.slider_pos + margin_left)
    
    def mouseMoveEvent(self, event):
        if self.dragging:
            new_pos = event.pos().x() - self.start_x
            max_pos = self.width() - 36
            self.slider_pos = max(0, min(new_pos, max_pos))
            self.update()
    
    def mouseReleaseEvent(self, event):
        if self.dragging:
            self.dragging = False
            max_pos = self.width() - 36
            
            if self.slider_pos >= max_pos * 0.8:  # 滑动超过80%触发
                self.slider_pos = max_pos
                self.update()
                QTimer.singleShot(100, self.triggered.emit)
                QTimer.singleShot(200, self.reset_slider)
            else:
                self.reset_slider()
    
    def reset_slider(self):
        """重置滑块位置"""
        self.slider_pos = 0
        self.update()


class FloatingConsole(QWidget):
    def __init__(self):
        super().__init__()
        self.click_count = {"lock": 0, "shutdown": 0}
        self.last_click_time = 0
        self.offwork_time = None  # 下班时间 (小时, 分钟)
        self.offwork_click_count = 0
        self.offwork_last_click = 0
        self.cpu_max = 0  # CPU最大使用率
        self.mem_max = 0  # 内存最大使用率
        self.init_ui()
        self.init_timer()
        self.init_tray()

    def init_ui(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        font = QFont("Consolas", 10)
        layout = QVBoxLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(0, 0, 0, 0)

        def label(text, clickable=False):
            l = QLabel(text)
            l.setFont(font)
            l.setStyleSheet(
                "color:#E8E8E8;"
                "background:rgba(30,30,35,0.85);"
                "padding:6px;"
                "border-radius:4px;"
            )
            if clickable:
                l.setCursor(Qt.PointingHandCursor)
            return l

        self.cpu = label("CPU:0%")
        self.mem = label("内存:0%")
        self.refresh = label("刷新率:-- Hz")
        
        self.offwork = label("下班剩余时间", clickable=True)
        self.offwork.mousePressEvent = self.offwork_clicked

        # 创建滑动按钮
        self.lock_slide = SlideButton("锁屏", "🔒", "#888888")  # 灰色
        self.lock_slide.triggered.connect(self.do_lock)
        self.lock_slide.setStyleSheet("margin-left:10px;")
        
        self.shutdown_slide = SlideButton("关机", "⏻", "#888888")  # 灰色
        self.shutdown_slide.triggered.connect(self.do_shutdown)
        self.shutdown_slide.setStyleSheet("margin-left:10px;")

        for w in [
            self.cpu, self.mem, self.refresh, 
            self.offwork,
            self.lock_slide, self.shutdown_slide
        ]:
            layout.addWidget(w)

        self.setLayout(layout)
        self.border_color = QColor(100, 100, 110, 150)
        
        # 自适应高度
        self.adjustSize()
        self.setFixedWidth(180)

    def init_timer(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_info)
        self.timer.start(1000)

    def init_tray(self):
        # 检查系统托盘是否可用
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("系统托盘不可用")
            return
        
        # 创建一个简单的彩色图标
        pixmap = QPixmap(64, 64)  # 增大尺寸
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制圆形背景
        painter.setBrush(QColor(70, 130, 180))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(4, 4, 56, 56)
        
        # 绘制字母F
        painter.setPen(QPen(Qt.white, 3))
        painter.setFont(QFont("Arial", 36, QFont.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "F")
        painter.end()
        
        # 创建多个尺寸的图标以提高兼容性
        icon = QIcon()
        icon.addPixmap(pixmap, QIcon.Normal, QIcon.Off)
        
        # 创建16x16的小图标
        small_pixmap = pixmap.scaled(16, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon.addPixmap(small_pixmap, QIcon.Normal, QIcon.Off)
        
        # 创建系统托盘图标
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip("浮动控制台")
        
        # 创建托盘菜单
        tray_menu = QMenu()
        
        show_action = QAction("显示/隐藏窗口", self)
        show_action.triggered.connect(self.toggle_visibility)
        
        quit_action = QAction("退出程序", self)
        quit_action.triggered.connect(self.quit_app)
        
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_icon_activated)
        
        # 立即显示
        self.tray_icon.show()
        
        # 多次尝试确保显示
        for delay in [50, 100, 200, 500, 1000]:
            QTimer.singleShot(delay, self.ensure_tray_visible)
    
    def ensure_tray_visible(self):
        """确保托盘图标可见"""
        if hasattr(self, 'tray_icon') and not self.tray_icon.isVisible():
            self.tray_icon.show()

    def tray_icon_activated(self, reason):
        # 双击托盘图标时显示/隐藏窗口
        if reason == QSystemTrayIcon.DoubleClick:
            self.toggle_visibility()

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.activateWindow()

    def quit_app(self):
        self.tray_icon.hide()
        QApplication.quit()

    def update_info(self):
        cpu = psutil.cpu_percent()
        mem = psutil.virtual_memory().percent
        hz = get_refresh_rate()

        # 更新最大值
        if cpu > self.cpu_max:
            self.cpu_max = cpu
        if mem > self.mem_max:
            self.mem_max = mem

        # 使用固定宽度格式，确保MAX值右对齐
        cpu_text = f"CPU:{cpu:.1f}%"
        mem_text = f"内存:{mem:.1f}%"
        # 计算需要的空格数，确保MAX部分对齐
        max_padding = 10  # 调整固定宽度，确保显示完整
        cpu_padding = max_padding - len(cpu_text)
        mem_padding = max_padding - len(mem_text)
        cpu_padding = max(0, cpu_padding)
        mem_padding = max(0, mem_padding)
        
        self.cpu.setText(f"{cpu_text}{' ' * cpu_padding}MAX:{self.cpu_max:.1f}%")
        self.mem.setText(f"{mem_text}{' ' * mem_padding}MAX:{self.mem_max:.1f}%")
        self.refresh.setText(f"刷新率:{hz} Hz")
        
        # 更新下班倒计时
        self.update_offwork_time()
        
        # 根据CPU使用率改变边框颜色
        if cpu < 60:
            self.border_color = QColor(100, 100, 110, 150)
        elif cpu < 85:
            self.border_color = QColor(180, 130, 0, 160)
        else:
            self.border_color = QColor(180, 60, 50, 180)

        self.update()

    def do_lock(self):
        """执行锁屏"""
        ctypes.windll.user32.LockWorkStation()
    
    def do_shutdown(self):
        """执行关机"""
        subprocess.Popen("shutdown /s /t 0", shell=True)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(self.border_color, 2))
        p.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, 8, 8)

    def mousePressEvent(self, e):
        self.oldPos = e.globalPos()

    def mouseMoveEvent(self, e):
        delta = e.globalPos() - self.oldPos
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.oldPos = e.globalPos()

    def leaveEvent(self, event):
        self.click_count["lock"] = 0
        self.click_count["shutdown"] = 0
        self.offwork_click_count = 0
        # 恢复下班时间显示
        self.update_offwork_time()

    def closeEvent(self, event):
        # 点击关闭按钮时隐藏到托盘而不是退出
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "浮动控制台",
            "程序已最小化到系统托盘",
            QSystemTrayIcon.Information,
            2000
        )

    def offwork_clicked(self, event):
        now = time.time()
        if now - self.offwork_last_click > 2:
            self.offwork_click_count = 0

        self.offwork_last_click = now
        self.offwork_click_count += 1

        # 更新显示
        if self.offwork_time is None:
            self.offwork.setText(f"下班剩余时间 ({self.offwork_click_count}/5)")
        else:
            self.update_offwork_time(show_count=True)

        if self.offwork_click_count >= 5:
            self.offwork_click_count = 0
            self.set_offwork_time()

    def set_offwork_time(self):
        from PyQt5.QtWidgets import QInputDialog, QLineEdit
        current_time = ""
        if self.offwork_time:
            current_time = f"{self.offwork_time[0]:02d}:{self.offwork_time[1]:02d}"
        
        dialog = QInputDialog(self)
        dialog.setWindowTitle("设置下班时间")
        dialog.setLabelText("请输入下班时间（格式:18:00 或 18:00）:")
        dialog.setTextValue(current_time)
        dialog.setOkButtonText("确定")
        dialog.setCancelButtonText("取消")
        
        # 获取输入框并设置焦点
        line_edit = dialog.findChild(QLineEdit)
        if line_edit:
            line_edit.setFocus()
            # 确保回车键可以触发确定按钮
            line_edit.returnPressed.connect(dialog.accept)
        
        if dialog.exec_() == QInputDialog.Accepted:
            time_str = dialog.textValue()
            if time_str:
                try:
                    # 替换中文冒号为英文冒号
                    time_str = time_str.replace(':', ':').replace(' ', '').strip()
                    
                    # 分割时间
                    parts = time_str.split(':')
                    if len(parts) != 2:
                        raise ValueError("格式错误")
                    
                    hour = int(parts[0])
                    minute = int(parts[1])
                    
                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        self.offwork_time = (hour, minute)
                        self.update_offwork_time()
                    else:
                        self.offwork.setText("下班剩余时间")
                        self.offwork_time = None
                except:
                    self.offwork.setText("下班剩余时间")
                    self.offwork_time = None
        else:
            # 取消输入，恢复显示
            self.update_offwork_time()

    def update_offwork_time(self, show_count=False):
        if self.offwork_time is None:
            if show_count:
                self.offwork.setText(f"下班剩余时间 ({self.offwork_click_count}/5)")
            else:
                self.offwork.setText("下班剩余时间")
            return

        from datetime import datetime, timedelta
        now = datetime.now()
        target = now.replace(hour=self.offwork_time[0], minute=self.offwork_time[1], second=0, microsecond=0)
        
        # 如果目标时间已过，设置为明天
        if target <= now:
            target += timedelta(days=1)
        
        delta = target - now
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        seconds = delta.seconds % 60
        
        if show_count:
            self.offwork.setText(f"下班:{hours}时{minutes}分{seconds}秒 ({self.offwork_click_count}/5)")
        else:
            self.offwork.setText(f"下班:{hours}时{minutes}分{seconds}秒")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # 关闭窗口不退出程序
    w = FloatingConsole()
    w.show()
    sys.exit(app.exec_())
