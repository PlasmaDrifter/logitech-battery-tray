#!/usr/bin/env python3
import os
import sys
import json
import time
import subprocess
try:
    import setproctitle
except ImportError:
    setproctitle = None


__version__ = "1.1.2"

# 1. Dynamic Qt Bindings Discovery & Compatibility layer
try:
    from PySide6 import QtWidgets, QtGui, QtCore
    QtVariant = "PySide6"
    QtCoreSignal = QtCore.Signal
    QActionClass = QtGui.QAction
except ImportError:
    try:
        from PyQt6 import QtWidgets, QtGui, QtCore
        QtVariant = "Qt6"
        QtCoreSignal = QtCore.pyqtSignal
        QActionClass = QtGui.QAction
    except ImportError:
        try:
            from PyQt5 import QtWidgets, QtGui, QtCore
            QtVariant = "PyQt5"
            QtCoreSignal = QtCore.pyqtSignal
            QActionClass = QtWidgets.QAction
        except ImportError:
            print("Error: PySide6, PyQt6, or PyQt5 is required to run this application.")
            sys.exit(1)

# Alignments cross-compatibility definitions
if QtVariant == "PyQt5":
    QtAlignHCenter = QtCore.Qt.AlignHCenter
    QtAlignVCenter = QtCore.Qt.AlignVCenter
    QtAlignTop = QtCore.Qt.AlignTop
else:
    QtAlignHCenter = QtCore.Qt.AlignmentFlag.AlignHCenter
    QtAlignVCenter = QtCore.Qt.AlignmentFlag.AlignVCenter
    QtAlignTop = QtCore.Qt.AlignmentFlag.AlignTop

CE_MenuItem = getattr(QtWidgets.QStyle.ControlElement, 'CE_MenuItem', getattr(QtWidgets.QStyle, 'CE_MenuItem', 14))
CT_MenuItem = getattr(QtWidgets.QStyle.ContentsType, 'CT_MenuItem', getattr(QtWidgets.QStyle, 'CT_MenuItem', 3))
PM_SmallIconSize = getattr(QtWidgets.QStyle.PixelMetric, 'PM_SmallIconSize', getattr(QtWidgets.QStyle, 'PM_SmallIconSize', 13))
PM_MenuHMargin = getattr(QtWidgets.QStyle.PixelMetric, 'PM_MenuHMargin', getattr(QtWidgets.QStyle, 'PM_MenuHMargin', 4))
State_Selected = getattr(QtWidgets.QStyle.StateFlag, 'State_Selected', getattr(QtWidgets.QStyle, 'State_Selected', 1))

class RichMenuStyle(QtWidgets.QProxyStyle):
    def sizeFromContents(self, ct, opt, size, widget=None):
        sz = super().sizeFromContents(ct, opt, size, widget)
        if ct == CT_MenuItem and opt and hasattr(opt, 'text') and opt.text.startswith('<html>'):
            doc = QtGui.QTextDocument()
            doc.setDefaultFont(opt.font)
            doc.setHtml(opt.text)
            extra_w = int(doc.idealWidth()) - opt.fontMetrics.horizontalAdvance(opt.text)
            if extra_w > 0:
                sz.setWidth(sz.width() + extra_w)
        return sz

    def drawControl(self, element, opt, painter, widget=None):
        if element == CE_MenuItem and opt.text.startswith('<html>'):
            raw_html = opt.text
            copy_opt = QtWidgets.QStyleOptionMenuItem(opt)
            copy_opt.text = ''
            super().drawControl(element, copy_opt, painter, widget)
            
            doc = QtGui.QTextDocument()
            doc.setDefaultFont(opt.font)
            
            is_selected = bool(opt.state & State_Selected)
            text_color = opt.palette.color(QtGui.QPalette.ColorGroup.Active, QtGui.QPalette.ColorRole.HighlightedText if is_selected else QtGui.QPalette.ColorRole.WindowText).name()
            doc.setDefaultStyleSheet(f'* {{ color: {text_color}; }}')
            doc.setHtml(raw_html)
            
            icon_size = self.pixelMetric(PM_SmallIconSize, opt, widget)
            if icon_size <= 0:
                icon_size = 16
            h_margin = self.pixelMetric(PM_MenuHMargin, opt, widget)
            spacing = 8
            text_x = opt.rect.x() + h_margin + icon_size + spacing
            text_y = opt.rect.y() + (opt.rect.height() - doc.size().height()) / 2
            
            painter.save()
            painter.translate(text_x, text_y)
            doc.drawContents(painter)
            painter.restore()
            return
        super().drawControl(element, opt, painter, widget)


# 2. Worker Thread for Hardware Read (prevents main GUI thread blocking/freezing)
class QueryWorker(QtCore.QThread):
    result_ready = QtCoreSignal(dict)
    
    def __init__(self, script_path):
        super().__init__()
        self.script_path = script_path
        
    def run(self):
        try:
            res = subprocess.run(
                ["python3", self.script_path],
                capture_output=True,
                text=True,
                timeout=4
            )
            if res.returncode == 0:
                data = json.loads(res.stdout)
                self.result_ready.emit(data)
            else:
                self.result_ready.emit({"success": False, "error": f"Script failed: {res.stderr}"})
        except subprocess.TimeoutExpired:
            self.result_ready.emit({"success": False, "error": "Query timeout (mouse is likely asleep)"})
        except Exception as e:
            self.result_ready.emit({"success": False, "error": str(e)})


# 3. Preferences Dialog
class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, app_instance=None):
        super().__init__(parent)
        self.app = app_instance
        self.setWindowTitle("Preferences")
        self.setWindowIcon(QtGui.QIcon.fromTheme("input-mouse"))
        self.setMinimumWidth(340)
        
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        
        self.charged_spin = QtWidgets.QSpinBox()
        self.charged_spin.setRange(80, 100)
        self.charged_spin.setValue(getattr(self.app, "charged_threshold", 95))
        self.charged_spin.setSuffix(" %")
        self.charged_spin.setFixedWidth(72)
        self.charged_spin.valueChanged.connect(self.validate_thresholds)
        
        self.warning_spin = QtWidgets.QSpinBox()
        self.warning_spin.setRange(2, 99)
        self.warning_spin.setValue(self.app.warning_threshold)
        self.warning_spin.setSuffix(" %")
        self.warning_spin.setFixedWidth(72)
        
        self.critical_spin = QtWidgets.QSpinBox()
        self.critical_spin.setRange(1, 98)
        self.critical_spin.setValue(self.app.critical_threshold)
        self.critical_spin.setSuffix(" %")
        self.critical_spin.setFixedWidth(72)
        
        self.warning_spin.valueChanged.connect(self.validate_thresholds)
        self.critical_spin.valueChanged.connect(self.validate_thresholds)
        
        self.layout_combo = QtWidgets.QComboBox()
        self.layout_combo.addItems(["Vertical Layout", "Horizontal Layout"])
        self.layout_combo.setCurrentIndex(1 if self.app.horizontal_layout else 0)
        
        self.source_combo = QtWidgets.QComboBox()
        self.source_combo.addItems(["Programmatic Drawing", "Colored SVG Icons"])
        self.source_combo.setCurrentIndex(self.app.icon_style)
        
        self.theme_combo = QtWidgets.QComboBox()
        self.theme_combo.addItems([
            "Dynamic Colors (Green -> Blue -> Orange -> Red)",
            "Amber", "Blue", "Cyan", "Green", "Indigo", 
            "Lime", "Orange", "Pink", "Purple", "Red", "Teal", "Yellow"
        ])
        self.theme_combo.setCurrentIndex(self.app.colored_theme)
        
        self.prog_style_combo = QtWidgets.QComboBox()
        self.prog_style_combo.addItems([
            "Solid Continuous", 
            "Segmented (3 Blocks)", 
            "Minimalist Outline", 
            "Rounded Capsule",
            "Rainbow Gradient",
            "Circular Ring Gauge"
        ])
        self.prog_style_combo.setCurrentIndex(self.app.programmatic_style)
        
        self.source_combo.currentIndexChanged.connect(self.update_theme_combo_state)
        self.interval_combo = QtWidgets.QComboBox()
        self.interval_combo.addItems(["5 Seconds", "10 Seconds", "30 Seconds", "60 Seconds"])
        interval_map = {5: 0, 10: 1, 30: 2, 60: 3}
        self.interval_combo.setCurrentIndex(interval_map.get(self.app.poll_interval, 1))
        
        self.text_check = QtWidgets.QCheckBox("Show Percentage Text")
        self.text_check.setChecked(self.app.show_text)
        
        self.autostart_check = QtWidgets.QCheckBox("Start on Boot")
        self.autostart_check.setChecked(self.app.autostart_enabled)
        
        # Connect layout combos for instant visual updates in the system tray
        self.layout_combo.currentIndexChanged.connect(self.apply_settings)
        self.source_combo.currentIndexChanged.connect(self.apply_settings)
        self.theme_combo.currentIndexChanged.connect(self.apply_settings)
        self.prog_style_combo.currentIndexChanged.connect(self.apply_settings)
        self.text_check.toggled.connect(self.apply_settings)
        
        self.color_normal_val = self.app.color_normal
        self.color_warning_val = self.app.color_warning
        self.color_critical_val = self.app.color_critical
        self.color_charging_val = self.app.color_charging
        self.color_empty_val = getattr(self.app, "color_empty", "#FFFFFF")

        self.btn_color_normal = QtWidgets.QPushButton(self.color_normal_val)
        self.btn_color_warning = QtWidgets.QPushButton(self.color_warning_val)
        self.btn_color_critical = QtWidgets.QPushButton(self.color_critical_val)
        self.btn_color_charging = QtWidgets.QPushButton(self.color_charging_val)
        self.btn_color_empty = QtWidgets.QPushButton(self.color_empty_val)

        self.update_btn_style(self.btn_color_normal, self.color_normal_val)
        self.update_btn_style(self.btn_color_warning, self.color_warning_val)
        self.update_btn_style(self.btn_color_critical, self.color_critical_val)
        self.update_btn_style(self.btn_color_charging, self.color_charging_val)
        self.update_btn_style(self.btn_color_empty, self.color_empty_val)

        self.btn_color_normal.clicked.connect(lambda: self.pick_color("color_normal_val", self.btn_color_normal))
        self.btn_color_warning.clicked.connect(lambda: self.pick_color("color_warning_val", self.btn_color_warning))
        self.btn_color_critical.clicked.connect(lambda: self.pick_color("color_critical_val", self.btn_color_critical))
        self.btn_color_charging.clicked.connect(lambda: self.pick_color("color_charging_val", self.btn_color_charging))
        self.btn_color_empty.clicked.connect(lambda: self.pick_color("color_empty_val", self.btn_color_empty))

        self.icon_scale_spin = QtWidgets.QSpinBox()
        self.icon_scale_spin.setRange(70, 140)
        self.icon_scale_spin.setValue(self.app.icon_scale)
        self.icon_scale_spin.setSuffix(" %")
        self.icon_scale_spin.setSingleStep(5)
        self.icon_scale_spin.setFixedWidth(85)
        self.icon_scale_spin.valueChanged.connect(self.apply_settings)

        self.track_opacity_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.track_opacity_slider.setRange(0, 100)
        self.track_opacity_slider.setValue(getattr(self.app, "track_opacity", 25))
        self.track_opacity_slider.setTickPosition(QtWidgets.QSlider.TickPosition.TicksBelow)
        self.track_opacity_slider.setTickInterval(10)
        self.track_opacity_slider.valueChanged.connect(self.apply_settings)

        self.notify_charged_check = QtWidgets.QCheckBox("Notify")
        self.notify_charged_check.setToolTip("Show notification when battery reaches full charge threshold")
        self.notify_charged_check.setChecked(getattr(self.app, "notify_charged", True))
        self.notify_charged_check.toggled.connect(self.apply_settings)
        
        self.notify_warn_check = QtWidgets.QCheckBox("Notify")
        self.notify_warn_check.setToolTip("Show notification when battery drops to warning threshold")
        self.notify_warn_check.setChecked(getattr(self.app, "notify_warning", True))
        self.notify_warn_check.toggled.connect(self.apply_settings)
        
        self.notify_crit_check = QtWidgets.QCheckBox("Notify")
        self.notify_crit_check.setToolTip("Show notification when battery drops to critical threshold")
        self.notify_crit_check.setChecked(getattr(self.app, "notify_critical", True))
        self.notify_crit_check.toggled.connect(self.apply_settings)

        charged_layout = QtWidgets.QHBoxLayout()
        charged_layout.addWidget(self.charged_spin)
        charged_layout.addWidget(self.notify_charged_check)
        
        self.tip_btn = QtWidgets.QToolButton()
        self.tip_btn.setIcon(QtGui.QIcon.fromTheme("help-about", QtGui.QIcon.fromTheme("dialog-information")))
        self.tip_btn.setToolTip("Click to view Full Charge Threshold Tip")
        self.tip_btn.setStyleSheet("QToolButton { border: 1px solid #555; border-radius: 4px; padding: 2px; } QToolButton:hover { background: #3d3d3d; }")
        self.tip_btn.clicked.connect(self.show_tip_popup)
        charged_layout.addWidget(self.tip_btn)
        charged_layout.addStretch()

        warn_layout = QtWidgets.QHBoxLayout()
        warn_layout.addWidget(self.warning_spin)
        warn_layout.addWidget(self.notify_warn_check)
        warn_layout.addStretch()

        crit_layout = QtWidgets.QHBoxLayout()
        crit_layout.addWidget(self.critical_spin)
        crit_layout.addWidget(self.notify_crit_check)
        crit_layout.addStretch()

        form.addRow("Full Charge Threshold:", charged_layout)
        form.addRow("Warning (Orange) Threshold:", warn_layout)
        form.addRow("Critical (Red) Threshold:", crit_layout)
        form.addRow("Tray Icon Visual Zoom:", self.icon_scale_spin)
        form.addRow("Normal Level Color:", self.btn_color_normal)
        form.addRow("Warning Level Color:", self.btn_color_warning)
        form.addRow("Critical Level Color:", self.btn_color_critical)
        form.addRow("Charging State Color:", self.btn_color_charging)
        
        empty_track_layout = QtWidgets.QHBoxLayout()
        empty_track_layout.addWidget(self.btn_color_empty)
        lbl_empty_note = QtWidgets.QLabel("(Circular Ring Gauge only)")
        lbl_empty_note.setStyleSheet("color: #777777; font-size: 8.5pt;")
        empty_track_layout.addWidget(lbl_empty_note)
        empty_track_layout.addStretch()
        self.btn_color_empty.setToolTip("Applies only to the Circular Ring Gauge icon style")
        self.track_opacity_slider.setToolTip("Applies only to the Circular Ring Gauge icon style")
        
        form.addRow("Empty Track Color:", empty_track_layout)
        form.addRow("Empty Track Opacity:", self.track_opacity_slider)
        form.addRow("Icon Direction Style:", self.layout_combo)
        form.addRow("Icon Source Set:", self.source_combo)
        form.addRow("Programmatic Draw Style:", self.prog_style_combo)
        form.addRow("Colored Icon Theme:", self.theme_combo)
        form.addRow("Refresh Frequency:", self.interval_combo)
        form.addRow("", self.text_check)
        form.addRow("", self.autostart_check)
        
        layout.addLayout(form)
        
        if QtVariant == "PyQt5":
            OkButton = QtWidgets.QDialogButtonBox.Ok
            CancelButton = QtWidgets.QDialogButtonBox.Cancel
        else:
            OkButton = QtWidgets.QDialogButtonBox.StandardButton.Ok
            CancelButton = QtWidgets.QDialogButtonBox.StandardButton.Cancel
            
        buttons = QtWidgets.QDialogButtonBox(OkButton | CancelButton)
        buttons.accepted.connect(self.save_settings)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.validate_thresholds()
        self.update_theme_combo_state()

    def show_tip_popup(self):
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle("Full Charge Threshold Tip")
        if QtVariant == "PyQt5":
            msg.setIcon(QtWidgets.QMessageBox.Information)
        else:
            msg.setIcon(QtWidgets.QMessageBox.Icon.Information)
        html = """
<div style="min-width: 450px; font-size: 10pt; line-height: 1.45;">
  <h3 style="margin-top: 0; margin-bottom: 10px;">Full Charge Threshold</h3>

  <p style="margin-top: 0; margin-bottom: 12px;">
    <b>&bull; No need to wait for 100%</b><br>
    Logitech wireless mice often charge rapidly up to ~90–95%, then slow down into trickle charging to protect Li-ion battery health (or hover around 95–98%). Setting this threshold lets you unplug early without missing a full-cycle reset.
  </p>

  <p style="margin-top: 0; margin-bottom: 12px;">
    <b>&bull; Runtime timer resets</b><br>
    As soon as the battery reaches this threshold or higher, the <i>Runtime</i> tracker automatically resets and begins tracking elapsed time from that moment.
  </p>

  <p style="margin-top: 0; margin-bottom: 4px;">
    <b>&bull; Drain rate estimator resets</b><br>
    Discharge history and the remaining hours estimate (<i>~Xh left est.</i>) reset at this percentage so calculations start fresh for the new discharge cycle.
  </p>
</div>
"""
        msg.setText(html)
        msg.setInformativeText("")
        msg.exec()
        
    def update_theme_combo_state(self):
        is_svg = (self.source_combo.currentIndex() == 1)
        self.theme_combo.setEnabled(is_svg)
        self.prog_style_combo.setEnabled(not is_svg)

    def update_btn_style(self, btn, color_hex):
        btn.setText(color_hex.upper())
        qcol = QtGui.QColor(color_hex)
        lum = (0.299 * qcol.red() + 0.587 * qcol.green() + 0.114 * qcol.blue()) / 255.0
        text_col = "#000000" if lum > 0.5 else "#FFFFFF"
        rgba_str = f"rgba({qcol.red()}, {qcol.green()}, {qcol.blue()}, {qcol.alpha() / 255.0:.2f})"
        btn.setStyleSheet(f"QPushButton {{ background-color: {rgba_str}; color: {text_col}; border: 1px solid #555; border-radius: 4px; padding: 4px; font-weight: bold; }}")

    def pick_color(self, attr_name, btn_target):
        current_hex = getattr(self, attr_name)
        init_color = QtGui.QColor(current_hex)
        init_color.setAlpha(255) # force color picker starting state to be solid
        
        color = QtWidgets.QColorDialog.getColor(init_color, self, "Select Color")
        if color.isValid():
            new_hex = color.name().upper()
            setattr(self, attr_name, new_hex)
            self.update_btn_style(btn_target, new_hex)
            self.apply_settings()

    def validate_thresholds(self):
        charged_val = self.charged_spin.value()
        warn_val = self.warning_spin.value()
        crit_val = self.critical_spin.value()
        if warn_val >= charged_val:
            self.warning_spin.setValue(charged_val - 1)
            warn_val = charged_val - 1
        if crit_val >= warn_val:
            self.critical_spin.setValue(warn_val - 1)
 
    def apply_settings(self):
        charged_val = self.charged_spin.value()
        warn_val = self.warning_spin.value()
        crit_val = self.critical_spin.value()
        horiz_layout = (self.layout_combo.currentIndex() == 1)
        icon_sty = self.source_combo.currentIndex()
        theme_idx = self.theme_combo.currentIndex()
        prog_sty = self.prog_style_combo.currentIndex()
        icon_scale_val = self.icon_scale_spin.value()
        
        interval_vals = [5, 10, 30, 60]
        interval_val = interval_vals[self.interval_combo.currentIndex()]
        
        show_txt = self.text_check.isChecked()
        autostart = self.autostart_check.isChecked()
        notify_charged = self.notify_charged_check.isChecked()
        notify_warn = self.notify_warn_check.isChecked()
        notify_crit = self.notify_crit_check.isChecked()
        
        self.app.charged_threshold = charged_val
        self.app.warning_threshold = warn_val
        self.app.critical_threshold = crit_val
        self.app.notify_charged = notify_charged
        self.app.notify_warning = notify_warn
        self.app.notify_critical = notify_crit
        self.app.icon_style = icon_sty
        self.app.colored_theme = theme_idx
        self.app.programmatic_style = prog_sty
        self.app.icon_scale = icon_scale_val
        self.app.horizontal_layout = horiz_layout
        self.app.show_text = show_txt
        self.app.poll_interval = interval_val
        self.app.autostart_enabled = autostart
        self.app.color_normal = self.color_normal_val
        self.app.color_warning = self.color_warning_val
        self.app.color_critical = self.color_critical_val
        self.app.color_charging = self.color_charging_val
        self.app.color_empty = self.color_empty_val
        self.app.track_opacity = self.track_opacity_slider.value()
        
        self.app.settings.setValue("charged_threshold", charged_val)
        self.app.settings.setValue("warning_threshold", warn_val)
        self.app.settings.setValue("critical_threshold", crit_val)
        self.app.settings.setValue("notify_charged", notify_charged)
        self.app.settings.setValue("notify_warning", notify_warn)
        self.app.settings.setValue("notify_critical", notify_crit)
        self.app.settings.setValue("icon_style", icon_sty)
        self.app.settings.setValue("colored_theme", theme_idx)
        self.app.settings.setValue("programmatic_style", prog_sty)
        self.app.settings.setValue("icon_scale", icon_scale_val)
        self.app.settings.setValue("horizontal_layout", horiz_layout)
        self.app.settings.setValue("show_text", show_txt)
        self.app.settings.setValue("poll_interval", interval_val)
        self.app.settings.setValue("autostart", autostart)
        self.app.settings.setValue("color_normal", self.color_normal_val)
        self.app.settings.setValue("color_warning", self.color_warning_val)
        self.app.settings.setValue("color_critical", self.color_critical_val)
        self.app.settings.setValue("color_charging", self.color_charging_val)
        self.app.settings.setValue("color_empty", self.color_empty_val)
        self.app.settings.setValue("track_opacity", self.app.track_opacity)
        
        self.app.toggle_autostart(autostart)
        self.app.poll_timer.setInterval(interval_val * 1000)
        
        self.app.sync_menu_states()
        self.app.update_icon()

    def save_settings(self):
        self.apply_settings()
        self.accept()


# 4. Main Tray Application Class
class LogitechBatteryTrayApp(QtWidgets.QApplication):
    def __init__(self, argv):
        if setproctitle is not None:
            try:
                setproctitle.setproctitle("Logitech Battery")
            except Exception:
                pass
        super().__init__(argv)
        self.setApplicationName("zzz_logitech_battery")
        self.setApplicationDisplayName("Logitech Battery")
        self.setDesktopFileName("logitech-battery-tray")
        self.setWindowIcon(QtGui.QIcon.fromTheme("logitech-battery-tray", QtGui.QIcon.fromTheme("input-mouse")))
        self.setQuitOnLastWindowClosed(False)
        
        # Paths setup
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.query_script = os.path.join(self.script_dir, "get_battery.py")
        
        # Load persistent configuration
        self.settings = QtCore.QSettings("logitech-battery-tray", "Settings")
        self.horizontal_layout = self.settings.value("horizontal_layout", False, type=bool)
        
        raw_style = self.settings.value("icon_style", 0, type=int)
        if raw_style == 2:
            self.icon_style = 1 # Colored SVG Icons
        else:
            self.icon_style = raw_style
            
        self.colored_theme = self.settings.value("colored_theme", 0, type=int) # 0=dynamic, 1=amber, etc.
        self.theme_colors = [
            "dynamic", "amber", "blue", "cyan", "green", "indigo", 
            "lime", "orange", "pink", "purple", "red", "teal", "yellow"
        ]
        self.show_text = self.settings.value("show_text", False, type=bool)
        self.poll_interval = self.settings.value("poll_interval", 10, type=int)
        self.autostart_enabled = self.settings.value("autostart", False, type=bool)
        self.charged_threshold = self.settings.value("charged_threshold", 95, type=int)
        self.warning_threshold = self.settings.value("warning_threshold", 20, type=int)
        self.critical_threshold = self.settings.value("critical_threshold", 14, type=int)
        self.notify_charged = self.settings.value("notify_charged", True, type=bool)
        self.notify_warning = self.settings.value("notify_warning", True, type=bool)
        self.notify_critical = self.settings.value("notify_critical", True, type=bool)
        self.icon_scale = self.settings.value("icon_scale", 100, type=int)
        
        # Status colors configuration
        self.color_normal = self.settings.value("color_normal", "#E0E0E0", type=str)
        self.color_warning = self.settings.value("color_warning", "#F39C12", type=str)
        self.color_critical = self.settings.value("color_critical", "#FF6B6B", type=str)
        self.color_charging = self.settings.value("color_charging", "#2ECC71", type=str)
        self.color_empty = self.settings.value("color_empty", "#FFFFFF", type=str)
        
        # Clean any old #AARRGGBB hex codes to #RRGGBB
        if len(self.color_empty) == 9:
            self.color_empty = "#" + self.color_empty[3:]
            
        self.track_opacity = self.settings.value("track_opacity", 25, type=int)
        
        # Load charged timestamp (float or None)
        self.last_charged_time = self.settings.value("last_charged_time", 0.0, type=float)
        
        # Load programmatic style (0=solid, 1=segmented, 2=minimalist, 3=capsule)
        self.programmatic_style = self.settings.value("programmatic_style", 0, type=int)

        # Set Breeze or Fusion style with RichMenuStyle proxy
        if "Breeze" in QtWidgets.QStyleFactory.keys():
            base_style = QtWidgets.QStyleFactory.create("Breeze")
        else:
            base_style = QtWidgets.QStyleFactory.create("Fusion")
        self.setStyle(RichMenuStyle(base_style))


        # State variables
        self.battery_percentage = 0
        self.is_charging = False
        self.query_success = False
        self.device_name = "Logitech Device"
        self.error_details = "Initializing..."
        
        # Debounce filter state
        self.last_percentage = 0
        self.last_charging = False
        self.has_valid_data = False
        self.is_debouncing = False
        self.debounce_target_percentage = 0
        self.debounce_target_charging = False
        
        # Thread worker setup
        self.worker = None
        
        # History and smart estimator setup
        try:
            self.battery_history = json.loads(self.settings.value("battery_history", "[]"))
        except Exception:
            self.battery_history = []
        
        self.learned_drain_rate = self.settings.value("learned_drain_rate", 0.83, type=float)
        self.cycle_active_seconds = self.settings.value("cycle_active_seconds", 0.0, type=float)
        self.cycle_start_percent = self.settings.value("cycle_start_percent", 100, type=int)
        self.last_poll_time = time.time()
        self.charge_start_percent = None
        
        # Notification alert latch states (prevent repeat notification spam)
        self._alerted_critical = False
        self._alerted_warning = False
        self._alerted_charged = False
        
        # Initialize UI Components
        self.init_tray()
        
        # Polling Timer Setup
        self.poll_timer = QtCore.QTimer(self)
        self.poll_timer.timeout.connect(self.start_query)
        self.poll_timer.start(self.poll_interval * 1000)
        
        # Trigger initial query
        self.start_query()

    def make_battery_bar(self, percentage, is_charging=False, width=10):
        clamped = max(0, min(100, int(percentage)))
        filled = int(round((clamped / 100.0) * width))
        empty = width - filled
        
        crit_thresh = getattr(self, "critical_threshold", 14)
        warn_thresh = getattr(self, "warning_threshold", 20)
        
        if is_charging:
            fill_char = "🟩"
        elif clamped <= crit_thresh:
            fill_char = "🟥"
        elif clamped <= warn_thresh:
            fill_char = "🟧"
        else:
            fill_char = "⬜"
            
        empty_char = "⬛"
        return fill_char * filled + empty_char * empty

    def get_battery_status_icon(self, percentage, is_charging):
        crit_thresh = getattr(self, "critical_threshold", 14)
        warn_thresh = getattr(self, "warning_threshold", 20)

        if not getattr(self, "has_valid_data", False) and percentage == 0:
            color_hex = "#7F8C8D"
        elif is_charging:
            color_hex = getattr(self, "color_charging", "#2ECC71")
        elif percentage <= crit_thresh:
            color_hex = getattr(self, "color_critical", "#FF6B6B")
        elif percentage <= warn_thresh:
            color_hex = getattr(self, "color_warning", "#F39C12")
        else:
            color_hex = getattr(self, "color_normal", "#E0E0E0")

        # Select corresponding SVG icon level
        if is_charging:
            filename = "battery-charging-green.svg"
        elif percentage <= crit_thresh:
            filename = "battery-empty-green.svg"
        elif percentage <= warn_thresh:
            filename = "battery-low-green.svg"
        elif percentage >= 80:
            filename = "battery-full-green.svg"
        elif percentage >= 40:
            filename = "battery-half-green.svg"
        else:
            filename = "battery-low-green.svg"

        # Always render vertical (is_horizontal=False) with condition color
        try:
            return self.load_svg_icon(filename, False, False, color_override=color_hex)
        except Exception:
            svg_path = os.path.join(self.script_dir, "icons", filename)
            if os.path.exists(svg_path):
                return QtGui.QIcon(svg_path)
            return QtGui.QIcon.fromTheme("battery-charging" if is_charging else ("battery-good" if percentage >= 50 else "battery-low"))

    def get_checkbox_icon(self, checked):
        # Always draw clean vector checkbox to ensure reliable distinction across all icon themes
        pix = QtGui.QPixmap(24, 24)
        pix.fill(QtGui.QColor(0, 0, 0, 0))
        
        NoPen = getattr(QtCore.Qt.PenStyle, 'NoPen', getattr(QtCore.Qt, 'NoPen', 0))
        NoBrush = getattr(QtCore.Qt.BrushStyle, 'NoBrush', getattr(QtCore.Qt, 'NoBrush', 0))
        RoundCap = getattr(QtCore.Qt.PenCapStyle, 'RoundCap', getattr(QtCore.Qt, 'RoundCap', 0x20))
        RoundJoin = getattr(QtCore.Qt.PenJoinStyle, 'RoundJoin', getattr(QtCore.Qt, 'RoundJoin', 0x40))
        Antialiasing = getattr(QtGui.QPainter.RenderHint, 'Antialiasing', getattr(QtGui.QPainter, 'Antialiasing', 1))
        
        p = QtGui.QPainter(pix)
        p.setRenderHint(Antialiasing)
        rect = QtCore.QRectF(3, 3, 18, 18)
        if checked:
            p.setBrush(QtGui.QBrush(QtGui.QColor("#2ecc71")))
            p.setPen(NoPen)
            p.drawRoundedRect(rect, 4, 4)
            pen = QtGui.QPen(QtGui.QColor("#ffffff"), 2.2)
            pen.setCapStyle(RoundCap)
            pen.setJoinStyle(RoundJoin)
            p.setPen(pen)
            p.drawLine(QtCore.QPointF(7, 12), QtCore.QPointF(10.5, 15.5))
            p.drawLine(QtCore.QPointF(10.5, 15.5), QtCore.QPointF(17, 8.5))
        else:
            pen = QtGui.QPen(QtGui.QColor("#888888"), 1.8)
            p.setPen(pen)
            p.setBrush(NoBrush)
            p.drawRoundedRect(rect, 4, 4)
        p.end()
        return QtGui.QIcon(pix)

    def init_tray(self):
        # Create System Tray Icon
        self.tray_icon = QtWidgets.QSystemTrayIcon(self)
        self.update_icon()
        
        # Construct Context Menu
        self.menu = QtWidgets.QMenu()
        
        # 1. Device Status Section
        self.menu.addSection("DEVICE STATUS")
        
        self.header_action = QActionClass("Logitech Device", self.menu)
        self.header_action.setIcon(QtGui.QIcon.fromTheme("input-mouse"))
        self.menu.addAction(self.header_action)
        
        self.status_action = QActionClass("Querying state...", self.menu)
        self.status_action.setIcon(self.get_battery_status_icon(0, False))
        self.menu.addAction(self.status_action)
        
        self.time_left_action = QActionClass("Calculating time left...", self.menu)
        self.time_left_action.setIcon(QtGui.QIcon.fromTheme("preferences-system-time", QtGui.QIcon.fromTheme("clock")))
        self.menu.addAction(self.time_left_action)
        
        self.state_action = QActionClass("Charging", self.menu)
        self.state_action.setIcon(QtGui.QIcon.fromTheme("battery-charging", QtGui.QIcon.fromTheme("weather-storm")))
        self.state_action.setVisible(False)
        self.menu.addAction(self.state_action)
        
        self.time_on_battery_action = QActionClass("Runtime: Unknown", self.menu)
        self.time_on_battery_action.setIcon(QtGui.QIcon.fromTheme("document-open-recent", QtGui.QIcon.fromTheme("preferences-system-time")))
        self.menu.addAction(self.time_on_battery_action)
        
        self.menu.addSeparator()
        
        # 2. Refresh Action
        self.refresh_action = QActionClass("Refresh Now", self.menu)
        self.refresh_action.setIcon(QtGui.QIcon.fromTheme("view-refresh"))
        self.refresh_action.triggered.connect(self.start_query)
        self.menu.addAction(self.refresh_action)
        
        self.menu.addSeparator()
        
        # 3. Controls Section
        self.menu.addSection("CONTROLS")
        
        self.interval_menu = self.menu.addMenu("Polling Interval")
        self.interval_menu.setIcon(QtGui.QIcon.fromTheme("appointment-recurring", QtGui.QIcon.fromTheme("preferences-system-time")))
        self.interval_group = QtGui.QActionGroup(self.interval_menu)
        
        intervals = [5, 10, 30, 60]
        for sec in intervals:
            act = QActionClass(f"{sec} Seconds", self.interval_menu)
            act.setCheckable(True)
            act.setChecked(self.poll_interval == sec)
            act.triggered.connect(lambda checked, s=sec: self.set_interval(s))
            self.interval_group.addAction(act)
            self.interval_menu.addAction(act)
            
        # 4. Autostart checkbox
        self.action_autostart = QActionClass("Start on Boot", self.menu)
        self.action_autostart.setIcon(self.get_checkbox_icon(self.autostart_enabled))
        self.action_autostart.triggered.connect(lambda checked=False: self.toggle_autostart(not self.autostart_enabled))
        self.menu.addAction(self.action_autostart)
        
        # 5. Preferences settings panel launcher
        self.prefs_action = QActionClass("Preferences...", self.menu)
        self.prefs_action.setIcon(QtGui.QIcon.fromTheme("preferences-system", QtGui.QIcon.fromTheme("configure")))
        self.prefs_action.triggered.connect(self.show_preferences)
        self.menu.addAction(self.prefs_action)
        
        self.menu.addSeparator()
        
        # 6. Quit Action
        self.quit_action = QActionClass("Quit Monitor", self.menu)
        self.quit_action.setIcon(QtGui.QIcon.fromTheme("application-exit"))
        self.quit_action.triggered.connect(self.quit)
        self.menu.addAction(self.quit_action)
        
        # Assign menu and show tray
        self.tray_icon.setContextMenu(self.menu)
        self.tray_icon.show()
        
        # Support clicking the tray icon to trigger manual refresh
        self.tray_icon.activated.connect(self.on_tray_activated)

    def on_tray_activated(self, reason):
        # Click or double click refreshes the battery state instantly
        if reason in [QtWidgets.QSystemTrayIcon.ActivationReason.Trigger, QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick]:
            self.start_query()

    def show_preferences(self):
        self.dialog = SettingsDialog(app_instance=self)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def start_query(self):
        # Prevent starting a worker if one is currently active
        if self.worker and self.worker.isRunning():
            return
        
        # Disable Refresh button during query to indicate activity
        self.refresh_action.setEnabled(False)
        
        self.worker = QueryWorker(self.query_script)
        self.worker.result_ready.connect(self.handle_query_result)
        self.worker.start()

    def handle_query_result(self, result):
        self.refresh_action.setEnabled(True)
        if result.get("success", False):
            new_percentage = result.get("percentage", 0)
            new_charging = (result.get("status") == "charging")
            
            self.query_success = True
            self.error_details = ""
            self.device_name = result.get("device_name", "Logitech Device")
            
            # Debouncer filter: filter out transient low battery/charging handshakes
            sudden_jump = self.has_valid_data and (abs(new_percentage - self.last_percentage) > 20)
            low_battery_charging_state_change = self.has_valid_data and (new_charging != self.last_charging) and new_charging and (new_percentage < 25)
            
            if sudden_jump or low_battery_charging_state_change:
                if not self.is_debouncing:
                    self.is_debouncing = True
                    self.debounce_target_percentage = new_percentage
                    self.debounce_target_charging = new_charging
                    # Single shot 2 seconds timer to confirm
                    QtCore.QTimer.singleShot(2000, self.confirm_debounce)
                    return
                else:
                    self.is_debouncing = False
                    if new_percentage == self.debounce_target_percentage and new_charging == self.debounce_target_charging:
                        self.apply_battery_data(new_percentage, new_charging)
                    else:
                        return
            else:
                self.is_debouncing = False
                self.apply_battery_data(new_percentage, new_charging)
        else:
            self.is_debouncing = False
            self.query_success = False
            self.error_details = result.get("error", "Unknown query error")
            
            # Keep previous battery values, but set charging state to False (since it is asleep)
            self.is_charging = False
            
            self.header_action.setText("Logitech Device")
            last_seen_pct = self.battery_percentage if self.has_valid_data else 0
            bar = self.make_battery_bar(last_seen_pct)
            self.status_action.setText(f"Not Connected (Last: {last_seen_pct}%) [{bar}]" if self.has_valid_data else "Not Connected")
            self.status_action.setIcon(self.get_battery_status_icon(last_seen_pct, False))
            if hasattr(self, 'time_left_action'):
                self.time_left_action.setVisible(False)
            if hasattr(self, 'state_action'):
                self.state_action.setVisible(False)
            if hasattr(self, 'time_on_battery_action'):
                if self.has_valid_data and self.last_charged_time > 0.0:
                    elapsed = time.time() - self.last_charged_time
                    time_str = self.format_duration(elapsed)
                    self.time_on_battery_action.setText(f"Runtime: {time_str}")
                else:
                    self.time_on_battery_action.setText("Runtime: Unknown")
            self.tray_icon.setToolTip(f"Logitech Battery Monitor\n{self.error_details}")
            
        self.update_icon()

    def confirm_debounce(self):
        self.start_query()

    def apply_battery_data(self, percentage, is_charging):
        self.battery_percentage = percentage
        self.is_charging = is_charging
        
        # Update charge timestamp and full cycle state if conditions met
        charged_thresh = getattr(self, "charged_threshold", 95)
        if (is_charging and percentage >= charged_thresh) or (self.last_charged_time == 0.0 and percentage >= charged_thresh):
            self.last_charged_time = time.time()
            self.settings.setValue("last_charged_time", self.last_charged_time)
            self.cycle_active_seconds = 0.0
            self.cycle_start_percent = percentage
            self.settings.setValue("cycle_active_seconds", 0.0)
            self.settings.setValue("cycle_start_percent", percentage)
            
        self.update_battery_history(percentage, is_charging)
        estimate = self.estimate_hours_left(percentage)
        bar = self.make_battery_bar(percentage, is_charging=is_charging)
        
        status_text = f"{self.battery_percentage}% [{bar}]"
            
        self.header_action.setText(self.device_name or "Logitech Device")
        self.status_action.setText(status_text)
        self.status_action.setIcon(self.get_battery_status_icon(percentage, is_charging))
        
        clean_estimate = estimate.strip().strip("()")
        if hasattr(self, 'time_left_action'):
            if clean_estimate and not self.is_charging:
                self.time_left_action.setText(clean_estimate)
                self.time_left_action.setVisible(True)
            elif self.is_charging:
                self.time_left_action.setVisible(False)
            else:
                self.time_left_action.setText("Estimating time left...")
                self.time_left_action.setVisible(True)
        
        if hasattr(self, 'state_action'):
            if self.is_charging:
                self.state_action.setText("Charging")
                self.state_action.setIcon(QtGui.QIcon.fromTheme("battery-charging", QtGui.QIcon.fromTheme("weather-storm")))
                self.state_action.setVisible(True)
            else:
                self.state_action.setVisible(False)
        
        # Calculate and format elapsed time on battery
        if self.last_charged_time > 0.0:
            elapsed = time.time() - self.last_charged_time
            time_str = self.format_duration(elapsed)
            if self.is_charging:
                on_batt_text = f"On Charger: {time_str}"
            else:
                on_batt_text = f"Runtime: {time_str}"
            charged_text = on_batt_text
        else:
            on_batt_text = "Runtime: Unknown"
            charged_text = "Runtime: Unknown"
            
        if hasattr(self, 'time_on_battery_action'):
            self.time_on_battery_action.setText(on_batt_text)
            self.time_on_battery_action.setIcon(QtGui.QIcon.fromTheme("document-open-recent", QtGui.QIcon.fromTheme("preferences-system-time")))
            
        self.tray_icon.setToolTip(f"{self.device_name}\nCharge: {self.battery_percentage}%{estimate}\n{charged_text}")
        
        # Trigger desktop notifications if threshold crossed
        self.check_notifications(percentage, is_charging)
        
        # Save historical values
        self.last_percentage = percentage
        self.last_charging = is_charging
        self.has_valid_data = True

    def check_notifications(self, percentage, is_charging):
        dev_name = self.device_name or "Logitech Device"
        MsgIcon = QtWidgets.QSystemTrayIcon.MessageIcon
        
        if is_charging:
            # Clear low-battery latch flags when mouse is charging
            self._alerted_critical = False
            self._alerted_warning = False
            
            # Check full charge threshold notification
            charged_thresh = getattr(self, "charged_threshold", 95)
            if getattr(self, "notify_charged", True) and percentage >= charged_thresh:
                if not self._alerted_charged:
                    self._alerted_charged = True
                    self.tray_icon.showMessage(
                        f"{dev_name} Charged",
                        f"Battery has reached {percentage}% (full charge threshold).",
                        MsgIcon.Information,
                        6000
                    )
            elif percentage < charged_thresh:
                self._alerted_charged = False
        else:
            # Discharging state
            self._alerted_charged = False
            
            crit_thresh = getattr(self, "critical_threshold", 14)
            warn_thresh = getattr(self, "warning_threshold", 20)
            
            # Critical alert
            if percentage <= crit_thresh:
                if getattr(self, "notify_critical", True) and not self._alerted_critical:
                    self._alerted_critical = True
                    self._alerted_warning = True # Suppress warning if critical hits first
                    self.tray_icon.showMessage(
                        f"{dev_name} Battery Critical",
                        f"Battery level is at {percentage}%. Please connect the charger.",
                        MsgIcon.Critical,
                        8000
                    )
            # Warning alert
            elif percentage <= warn_thresh:
                self._alerted_critical = False
                if getattr(self, "notify_warning", True) and not self._alerted_warning:
                    self._alerted_warning = True
                    self.tray_icon.showMessage(
                        f"{dev_name} Battery Low",
                        f"Battery level has reached {percentage}%.",
                        MsgIcon.Warning,
                        6000
                    )
            else:
                # Normal battery level: reset warning & critical latches
                self._alerted_critical = False
                self._alerted_warning = False

    def update_battery_history(self, percentage, is_charging):
        now = time.time()
        poll_gap = now - getattr(self, "last_poll_time", now)
        self.last_poll_time = now
        max_normal_gap = max(self.poll_interval * 4, 300)

        # Handle charging state without prematurely wiping history on brief plug-ins
        if is_charging:
            if self.charge_start_percent is None:
                self.charge_start_percent = percentage

            charged_thresh = getattr(self, "charged_threshold", 95)
            # Only reset if reached full charge threshold or gained >= 3%
            if percentage >= charged_thresh or (percentage >= self.charge_start_percent + 3):
                if self.battery_history:
                    self.battery_history = []
                    self.settings.setValue("battery_history", "[]")
                self.cycle_active_seconds = 0.0
                self.cycle_start_percent = percentage
                self.settings.setValue("cycle_active_seconds", 0.0)
                self.settings.setValue("cycle_start_percent", percentage)
            return

        # If user just unplugged:
        if self.charge_start_percent is not None:
            charged_thresh = getattr(self, "charged_threshold", 95)
            if percentage >= charged_thresh or percentage >= (self.charge_start_percent + 3):
                # Substantial charging took place before unplugging
                self.last_charged_time = now
                self.settings.setValue("last_charged_time", self.last_charged_time)
                self.cycle_active_seconds = 0.0
                self.cycle_start_percent = percentage
                self.battery_history = [{"time": now, "active_seconds": 0.0, "percent": percentage}]
                self.settings.setValue("battery_history", json.dumps(self.battery_history))
                self.settings.setValue("cycle_active_seconds", 0.0)
                self.settings.setValue("cycle_start_percent", percentage)
            self.charge_start_percent = None

        # Accumulate active discharge time (filtering out sleep/suspend gaps > 5 mins)
        if 0 < poll_gap <= max_normal_gap:
            self.cycle_active_seconds += poll_gap
            self.settings.setValue("cycle_active_seconds", self.cycle_active_seconds)

        # If history is empty, initialize it
        if not self.battery_history:
            self.battery_history = [{"time": now, "active_seconds": self.cycle_active_seconds, "percent": percentage}]
            self.settings.setValue("battery_history", json.dumps(self.battery_history))
            return

        last_point = self.battery_history[-1]
        charged_thresh = getattr(self, "charged_threshold", 95)

        # Full charge threshold reset
        if percentage >= charged_thresh and (last_point.get("percent", 0) < charged_thresh or any(p.get("percent", 0) < charged_thresh for p in self.battery_history)):
            self.last_charged_time = now
            self.settings.setValue("last_charged_time", self.last_charged_time)
            self.cycle_active_seconds = 0.0
            self.cycle_start_percent = percentage
            self.battery_history = [{"time": now, "active_seconds": 0.0, "percent": percentage}]
            self.settings.setValue("battery_history", json.dumps(self.battery_history))
            self.settings.setValue("cycle_active_seconds", 0.0)
            self.settings.setValue("cycle_start_percent", percentage)
            return

        # If battery percentage increased by >= 3% while unplugged (e.g. battery swap or recalibration)
        if percentage >= last_point.get("percent", 0) + 3:
            self.cycle_active_seconds = 0.0
            self.cycle_start_percent = percentage
            self.battery_history = [{"time": now, "active_seconds": 0.0, "percent": percentage}]
            self.settings.setValue("battery_history", json.dumps(self.battery_history))
            self.settings.setValue("cycle_active_seconds", 0.0)
            self.settings.setValue("cycle_start_percent", percentage)
            return

        # If percentage dropped, record the drop point with active_seconds
        if percentage < last_point.get("percent", 0):
            entry = {
                "time": now,
                "active_seconds": self.cycle_active_seconds,
                "percent": percentage
            }
            self.battery_history.append(entry)
            if len(self.battery_history) > 15:
                self.battery_history.pop(0)
            self.settings.setValue("battery_history", json.dumps(self.battery_history))

    def format_duration(self, seconds):
        if seconds < 0:
            seconds = 0
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0 or days > 0:
            parts.append(f"{hours}h")
        if days == 0 and hours == 0 and minutes == 0:
            return f"{int(seconds)}s"
        parts.append(f"{minutes}m")
        return " ".join(parts)

    def estimate_hours_left(self, current_percentage):
        if self.is_charging:
            return ""

        macro_rate = None
        micro_rate = None
        
        # 1. Macro rate from cycle start (e.g. from 95% down to current percentage)
        cycle_start = getattr(self, "cycle_start_percent", 100)
        cycle_active_sec = getattr(self, "cycle_active_seconds", 0.0)
        cycle_drop = cycle_start - current_percentage
        
        if cycle_drop >= 2 and cycle_active_sec >= 900:  # at least 2% drop and 15 mins active
            hours_cycle = cycle_active_sec / 3600.0
            rate = cycle_drop / hours_cycle
            if 0.25 <= rate <= 5.0:
                macro_rate = rate

        # 2. Weighted micro rate across intervals in battery_history
        if len(self.battery_history) >= 2:
            interval_rates = []
            interval_weights = []
            
            for i in range(1, len(self.battery_history)):
                p_prev = self.battery_history[i - 1].get("percent", 0)
                p_curr = self.battery_history[i].get("percent", 0)
                
                a_prev = self.battery_history[i - 1].get("active_seconds", None)
                a_curr = self.battery_history[i].get("active_seconds", None)
                
                if a_prev is not None and a_curr is not None:
                    delta_sec = a_curr - a_prev
                else:
                    # Fallback for older entries without active_seconds
                    delta_sec = self.battery_history[i].get("time", 0) - self.battery_history[i - 1].get("time", 0)
                    if delta_sec > 300:
                        delta_sec = 300
                
                delta_pct = p_prev - p_curr
                if delta_pct > 0 and delta_sec >= 60:
                    r = delta_pct / (delta_sec / 3600.0)
                    if 0.25 <= r <= 5.0:
                        interval_rates.append(r)
                        interval_weights.append(i)  # more recent intervals have higher weight
                        
            if interval_rates:
                micro_rate = sum(r * w for r, w in zip(interval_rates, interval_weights)) / sum(interval_weights)

        # 3. Blend rates or fall back to learned rate
        if macro_rate is not None and micro_rate is not None:
            effective_rate = 0.5 * macro_rate + 0.5 * micro_rate
        elif micro_rate is not None:
            effective_rate = micro_rate
        elif macro_rate is not None:
            effective_rate = macro_rate
        else:
            effective_rate = getattr(self, "learned_drain_rate", 0.83)

        # Clamp rate within practical hardware limits (0.25% to 5.0% / hour)
        effective_rate = max(0.25, min(5.0, effective_rate))

        # Update learned drain rate with light exponential smoothing (10% new rate, 90% prior)
        current_learned = getattr(self, "learned_drain_rate", 0.83)
        self.learned_drain_rate = 0.9 * current_learned + 0.1 * effective_rate
        self.settings.setValue("learned_drain_rate", self.learned_drain_rate)

        hours = current_percentage / effective_rate
        time_str = self.format_duration(hours * 3600)
        return f" (~{time_str} left est.)"

    def update_icon(self):
        if self.icon_style == 1:
            if not self.has_valid_data:
                svg_file = "battery-empty-red.svg"
            elif self.is_charging:
                color = "green" if self.colored_theme == 0 else self.theme_colors[self.colored_theme]
                svg_file = f"battery-charging-{color}.svg"
            else:
                if self.battery_percentage <= self.critical_threshold:
                    level = "empty"
                    color = "red" if self.colored_theme == 0 else self.theme_colors[self.colored_theme]
                elif self.battery_percentage <= self.warning_threshold:
                    level = "low"
                    color = "orange" if self.colored_theme == 0 else self.theme_colors[self.colored_theme]
                elif self.battery_percentage >= 80:
                    level = "full"
                    color = "green" if self.colored_theme == 0 else self.theme_colors[self.colored_theme]
                else:
                    level = "half"
                    color = "blue" if self.colored_theme == 0 else self.theme_colors[self.colored_theme]
                
                svg_file = f"battery-{level}-{color}.svg"
            
            icon = self.load_svg_icon(svg_file, self.show_text, self.horizontal_layout)
            self.tray_icon.setIcon(icon)
            return

        # Resolve Color code:
        if not self.has_valid_data:
            # Gray when offline and we have no historical data yet
            color_hex = "#7F8C8D"
        elif self.is_charging:
            # Custom charging color
            color_hex = self.color_charging
        elif self.battery_percentage <= self.critical_threshold:
            # Custom critical color
            color_hex = self.color_critical
        elif self.battery_percentage <= self.warning_threshold:
            # Custom warning color
            color_hex = self.color_warning
        else:
            # Custom normal color for standard discharging battery levels
            color_hex = self.color_normal
            
        icon = self.draw_battery_icon(
            percentage=self.battery_percentage,
            is_charging=self.is_charging,
            is_horizontal=self.horizontal_layout,
            show_text=self.show_text,
            battery_color_hex=color_hex
        )
        self.tray_icon.setIcon(icon)


        
    def draw_battery_icon(self, percentage, is_charging, is_horizontal, show_text, battery_color_hex):
        size = 32
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtGui.QColor(0, 0, 0, 0)) # transparent background
        
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        
        # Apply visual zoom scaling around center
        zoom_scale = getattr(self, "icon_scale", 100) / 100.0
        if zoom_scale != 1.0:
            painter.translate(size / 2.0, size / 2.0)
            painter.scale(zoom_scale, zoom_scale)
            painter.translate(-size / 2.0, -size / 2.0)
        
        # Style 5 is Circular Ring Gauge
        if self.programmatic_style == 5:
            rect = QtCore.QRectF(3, 3, 26, 26)
            stroke_w = 5.0
            
            # Background track ring (customizable color & opacity, default to 25% white)
            track_color = QtGui.QColor(getattr(self, "color_empty", "#FFFFFF"))
            track_opacity_val = getattr(self, "track_opacity", 25)
            track_color.setAlpha(int((track_opacity_val / 100.0) * 255))
            painter.setPen(QtGui.QPen(track_color, stroke_w))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawArc(rect, 0, 360 * 16)
            
            # Progress arc overlay
            color = QtGui.QColor(battery_color_hex)
            pen = QtGui.QPen(color, stroke_w, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
            painter.setPen(pen)
            
            starting_angle = 90 * 16 # Top center
            span_angle = int(- (percentage / 100.0) * 360 * 16)
            painter.drawArc(rect, starting_angle, span_angle)
            
            # Draw charging symbol in center if charging
            if is_charging:
                center_x = 16
                center_y = 16
                bg_color = QtGui.QColor("#000000")
                painter.setPen(QtGui.QPen(bg_color, 4.0))
                painter.drawLine(center_x - 4, center_y, center_x + 4, center_y)
                painter.drawLine(center_x, center_y - 4, center_x, center_y + 4)
                
                painter.setPen(QtGui.QPen(color, 2.0))
                painter.drawLine(center_x - 4, center_y, center_x + 4, center_y)
                painter.drawLine(center_x, center_y - 4, center_x, center_y + 4)
            
            # Text will draw in center natively by text overlay if enabled
            
        else:
            color = QtGui.QColor(battery_color_hex)
            pen_width = 1.2 if self.programmatic_style == 2 else 2.5
            pen = QtGui.QPen(color, pen_width)
            painter.setPen(pen)
            
            is_gradient = (self.programmatic_style == 4)
            
            if is_horizontal:
                # Draw Horizontal battery shape
                shell_rect = QtCore.QRectF(2, 7, 24, 18)
                term_rect = QtCore.QRectF(26, 12, 3, 8)
                
                # Rounded capsule style rounding
                shell_round = shell_rect.height() / 2.0 if self.programmatic_style == 3 else 3.0
                painter.drawRoundedRect(shell_rect, shell_round, shell_round)
                painter.setBrush(QtGui.QBrush(color))
                painter.drawRoundedRect(term_rect, 1, 1)
                
                margin = 2.0 if self.programmatic_style == 2 else 4.0
                fill_width = shell_rect.width() - (margin * 2)
                
                if not show_text:
                    if self.programmatic_style == 1:
                        # Segmented (3 blocks)
                        gap = 2.0
                        seg_w = (fill_width - 2 * gap) / 3.0
                        for i in range(3):
                            if i == 0 and percentage < 15: continue
                            if i == 1 and percentage < 50: continue
                            if i == 2 and percentage < 80: continue
                            
                            x = shell_rect.x() + margin + seg_w * i + gap * i
                            seg_rect = QtCore.QRectF(x, shell_rect.y() + margin, seg_w, shell_rect.height() - (margin * 2))
                            painter.drawRoundedRect(seg_rect, 1.0, 1.0)
                    else:
                        # Solid or Capsule
                        bar_w = max(0.0, fill_width * (percentage / 100.0))
                        if bar_w > 0:
                            fill_rect = QtCore.QRectF(shell_rect.x() + margin, shell_rect.y() + margin, bar_w, shell_rect.height() - (margin * 2))
                            fill_round = fill_rect.height() / 2.0 if self.programmatic_style == 3 else 1.5
                            
                            if is_gradient:
                                grad = QtGui.QLinearGradient(fill_rect.left(), 0, fill_rect.right(), 0)
                                grad.setColorAt(0.0, QtGui.QColor("#FF3B30")) # Red
                                grad.setColorAt(0.5, QtGui.QColor("#FF9500")) # Orange
                                grad.setColorAt(1.0, QtGui.QColor("#34C759")) # Green
                                painter.setBrush(QtGui.QBrush(grad))
                                painter.setPen(QtCore.Qt.NoPen)
                            else:
                                painter.setBrush(QtGui.QBrush(color))
                                
                            painter.drawRoundedRect(fill_rect, fill_round, fill_round)
            else:
                # Draw Vertical battery shape
                shell_rect = QtCore.QRectF(7, 5, 18, 25)
                term_rect = QtCore.QRectF(12, 2, 8, 3)
                
                # Rounded capsule style rounding
                shell_round = shell_rect.width() / 2.0 if self.programmatic_style == 3 else 3.0
                painter.drawRoundedRect(shell_rect, shell_round, shell_round)
                painter.setBrush(QtGui.QBrush(color))
                painter.drawRoundedRect(term_rect, 1, 1)
                
                margin = 2.0 if self.programmatic_style == 2 else 4.0
                fill_height = shell_rect.height() - (margin * 2)
                
                if not show_text:
                    if self.programmatic_style == 1:
                        # Segmented (3 blocks)
                        gap = 2.0
                        seg_h = (fill_height - 2 * gap) / 3.0
                        for i in range(3):
                            if i == 0 and percentage < 15: continue
                            if i == 1 and percentage < 50: continue
                            if i == 2 and percentage < 80: continue
                            
                            y = shell_rect.bottom() - margin - seg_h * (i + 1) - gap * i
                            seg_rect = QtCore.QRectF(shell_rect.x() + margin, y, shell_rect.width() - (margin * 2), seg_h)
                            painter.drawRoundedRect(seg_rect, 1.0, 1.0)
                    else:
                        # Solid or Capsule
                        bar_h = max(0.0, fill_height * (percentage / 100.0))
                        if bar_h > 0:
                            fill_rect = QtCore.QRectF(shell_rect.x() + margin, shell_rect.bottom() - margin - bar_h, shell_rect.width() - (margin * 2), bar_h)
                            fill_round = fill_rect.width() / 2.0 if self.programmatic_style == 3 else 1.5
                            
                            if is_gradient:
                                grad = QtGui.QLinearGradient(0, fill_rect.bottom(), 0, fill_rect.top())
                                grad.setColorAt(0.0, QtGui.QColor("#FF3B30")) # Red
                                grad.setColorAt(0.5, QtGui.QColor("#FF9500")) # Orange
                                grad.setColorAt(1.0, QtGui.QColor("#34C759")) # Green
                                painter.setBrush(QtGui.QBrush(grad))
                                painter.setPen(QtCore.Qt.NoPen)
                            else:
                                painter.setBrush(QtGui.QBrush(color))
                                
                            painter.drawRoundedRect(fill_rect, fill_round, fill_round)
                
        # Draw charging indicator (+ symbol) on top of battery shape if charging
        # (Only draw if standard shapes are active, Circular has its own charging symbol)
        if is_charging and self.programmatic_style != 5:
            center_x = 14 if is_horizontal else 16
            center_y = 16 if is_horizontal else 17
            
            # Thick black background glow outline
            bg_color = QtGui.QColor("#000000")
            painter.setPen(QtGui.QPen(bg_color, 4))
            painter.drawLine(center_x - 5, center_y, center_x + 5, center_y)
            painter.drawLine(center_x, center_y - 5, center_x, center_y + 5)
            
            # Main color stroke
            color = QtGui.QColor(battery_color_hex)
            painter.setPen(QtGui.QPen(color, 2))
            painter.drawLine(center_x - 5, center_y, center_x + 5, center_y)
            painter.drawLine(center_x, center_y - 5, center_x, center_y + 5)
            
        elif show_text and self.query_success:
            # Draw percentage numbers inside the battery shell
            font = QtGui.QFont("Inter", 8, QtGui.QFont.Weight.Bold)
            painter.setFont(font)
            
            txt = str(percentage)
            rect = QtCore.QRectF(0, 0, size, size)
            if is_horizontal and self.programmatic_style != 5:
                rect.translate(-1, 0)
            elif not is_horizontal and self.programmatic_style != 5:
                rect.translate(0, 1)
                
            # Outline/Shadow glow to guarantee legibility on any theme
            bg_color = QtGui.QColor("#000000")
            painter.setPen(bg_color)
            
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx != 0 or dy != 0:
                        painter.drawText(rect.translated(dx, dy), QtAlignHCenter | QtAlignVCenter, txt)
                        
            # Inner text
            color = QtGui.QColor(battery_color_hex)
            painter.setPen(color)
            painter.drawText(rect, QtAlignHCenter | QtAlignVCenter, txt)
            
        painter.end()
        return QtGui.QIcon(pixmap)

    def load_svg_icon(self, filename, show_text, is_horizontal, color_override=None):
        svg_path = os.path.join(self.script_dir, "icons", filename)
        size = 32
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtGui.QColor(0, 0, 0, 0))
        
        try:
            from PySide6 import QtSvg
        except ImportError:
            try:
                from PyQt5 import QtSvg
            except ImportError:
                from PyQt6 import QtSvg
                
        painter = QtGui.QPainter(pixmap)
        if color_override:
            try:
                with open(svg_path, 'r', encoding='utf-8') as f:
                    svg_data = f.read()
                import re
                recolored = re.sub(r'fill="[^"]*"', f'fill="{color_override}"', svg_data)
                renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(recolored.encode('utf-8')))
            except Exception:
                renderer = QtSvg.QSvgRenderer(svg_path)
        else:
            renderer = QtSvg.QSvgRenderer(svg_path)
        
        # Apply visual zoom scaling around center
        zoom_scale = getattr(self, "icon_scale", 100) / 100.0
        if zoom_scale != 1.0:
            painter.translate(size / 2.0, size / 2.0)
            painter.scale(zoom_scale, zoom_scale)
            painter.translate(-size / 2.0, -size / 2.0)
        
        if not is_horizontal:
            painter.translate(size / 2.0, size / 2.0)
            painter.rotate(-90)
            painter.translate(-size / 2.0, -size / 2.0)
            
        renderer.render(painter)
        
        if not is_horizontal:
            painter.resetTransform()
            
        if show_text and self.has_valid_data and not self.is_charging:
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setRenderHint(QtGui.QPainter.TextAntialiasing)
            
            font = QtGui.QFont("Sans Serif", max(6, int(9 * scale)), QtGui.QFont.Bold)
            painter.setFont(font)
            
            text = str(self.battery_percentage)
            rect = pixmap.rect()
            
            bg_color = QtGui.QColor("#FFFFFF")
            painter.setPen(bg_color)
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx != 0 or dy != 0:
                        painter.drawText(rect.translated(dx * scale, dy * scale), QtAlignHCenter | QtAlignVCenter, text)
                        
            painter.setPen(QtGui.QColor("#2C3E50"))
            painter.drawText(rect, QtAlignHCenter | QtAlignVCenter, text)
            
        painter.end()
        return QtGui.QIcon(pixmap)

    def sync_menu_states(self):
        # Update autostart icon in tray menu
        if hasattr(self, 'action_autostart'):
            self.action_autostart.setIcon(self.get_checkbox_icon(self.autostart_enabled))
        # Update refresh interval checkmarks in tray menu
        if hasattr(self, 'interval_menu'):
            for act in self.interval_menu.actions():
                if act.text().startswith(str(self.poll_interval)):
                    act.setChecked(True)
                else:
                    act.setChecked(False)
        if hasattr(self, 'status_action'):
            self.status_action.setIcon(self.get_battery_status_icon(self.battery_percentage, self.is_charging))

    def set_interval(self, seconds):
        self.poll_interval = seconds
        self.settings.setValue("poll_interval", seconds)
        self.poll_timer.setInterval(seconds * 1000)
        self.poll_timer.start()

    def toggle_autostart(self, checked):
        self.autostart_enabled = checked
        self.settings.setValue("autostart", checked)
        if hasattr(self, 'action_autostart'):
            self.action_autostart.setIcon(self.get_checkbox_icon(checked))
        autostart_dir = os.path.join(QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.ConfigLocation), "autostart")
        desktop_file = os.path.join(autostart_dir, "logitech-battery-tray.desktop")
        
        if checked:
            os.makedirs(autostart_dir, exist_ok=True)
            content = """[Desktop Entry]
Type=Application
Version=1.0
Name=Logitech Battery
Comment=Logitech wireless mouse and device battery monitor tray application
Exec=sh -c "exec ~/.local/bin/logitech-battery-tray"
Icon=logitech-battery-tray
Terminal=false
Categories=Utility;Qt;
StartupNotify=false
"""
            try:
                with open(desktop_file, "w") as f:
                    f.write(content)
                os.chmod(desktop_file, 0o644)
            except Exception as e:
                print(f"Error creating autostart entry: {e}")
        else:
            if os.path.exists(desktop_file):
                try:
                    os.remove(desktop_file)
                except Exception as e:
                    print(f"Error removing autostart entry: {e}")


if __name__ == '__main__':
    lock_path = os.path.join(QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.TempLocation), "logitech-battery-tray.lock")
    lock_file = QtCore.QLockFile(lock_path)
    if not lock_file.tryLock(100):
        print("Logitech Battery Tray is already running. Exiting.", file=sys.stderr)
        sys.exit(0)

    app = LogitechBatteryTrayApp(sys.argv)
    exit_func = getattr(app, 'exec', getattr(app, 'exec_', None))
    exit_code = exit_func() if exit_func else 0
    lock_file.unlock()
    sys.exit(exit_code)
