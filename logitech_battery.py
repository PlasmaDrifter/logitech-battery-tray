#!/usr/bin/env python3
import os
import sys
import json
import time
import subprocess
import setproctitle

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
else:
    QtAlignHCenter = QtCore.Qt.AlignmentFlag.AlignHCenter
    QtAlignVCenter = QtCore.Qt.AlignmentFlag.AlignVCenter


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
        
        self.warning_spin = QtWidgets.QSpinBox()
        self.warning_spin.setRange(2, 100)
        self.warning_spin.setValue(self.app.warning_threshold)
        self.warning_spin.setSuffix(" %")
        
        self.critical_spin = QtWidgets.QSpinBox()
        self.critical_spin.setRange(1, 99)
        self.critical_spin.setValue(self.app.critical_threshold)
        self.critical_spin.setSuffix(" %")
        
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
        
        form.addRow("Warning (Orange) Threshold:", self.warning_spin)
        form.addRow("Critical (Red) Threshold:", self.critical_spin)
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
        
    def update_theme_combo_state(self):
        is_svg = (self.source_combo.currentIndex() == 1)
        self.theme_combo.setEnabled(is_svg)
        self.prog_style_combo.setEnabled(not is_svg)

    def validate_thresholds(self):
        warn_val = self.warning_spin.value()
        crit_val = self.critical_spin.value()
        if crit_val >= warn_val:
            self.warning_spin.setValue(crit_val + 1)
 
    def apply_settings(self):
        warn_val = self.warning_spin.value()
        crit_val = self.critical_spin.value()
        horiz_layout = (self.layout_combo.currentIndex() == 1)
        icon_sty = self.source_combo.currentIndex()
        theme_idx = self.theme_combo.currentIndex()
        prog_sty = self.prog_style_combo.currentIndex()
        
        interval_vals = [5, 10, 30, 60]
        interval_val = interval_vals[self.interval_combo.currentIndex()]
        
        show_txt = self.text_check.isChecked()
        autostart = self.autostart_check.isChecked()
        
        self.app.warning_threshold = warn_val
        self.app.critical_threshold = crit_val
        self.app.icon_style = icon_sty
        self.app.colored_theme = theme_idx
        self.app.programmatic_style = prog_sty
        self.app.horizontal_layout = horiz_layout
        self.app.show_text = show_txt
        self.app.poll_interval = interval_val
        self.app.autostart_enabled = autostart
        
        self.app.settings.setValue("warning_threshold", warn_val)
        self.app.settings.setValue("critical_threshold", crit_val)
        self.app.settings.setValue("icon_style", icon_sty)
        self.app.settings.setValue("colored_theme", theme_idx)
        self.app.settings.setValue("programmatic_style", prog_sty)
        self.app.settings.setValue("horizontal_layout", horiz_layout)
        self.app.settings.setValue("show_text", show_txt)
        self.app.settings.setValue("poll_interval", interval_val)
        self.app.settings.setValue("autostart", autostart)
        
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
        try:
            setproctitle.setproctitle("Logitech Battery")
        except Exception:
            pass
        super().__init__(argv)
        self.setApplicationName("zzz_logitech_battery")
        self.setApplicationDisplayName("zzz_logitech_battery")
        self.setDesktopFileName("logitech-battery-tray")
        self.setWindowIcon(QtGui.QIcon.fromTheme("input-mouse"))
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
        self.warning_threshold = self.settings.value("warning_threshold", 20, type=int)
        self.critical_threshold = self.settings.value("critical_threshold", 14, type=int)
        
        # Load charged timestamp (float or None)
        self.last_charged_time = self.settings.value("last_charged_time", 0.0, type=float)
        
        # Load programmatic style (0=solid, 1=segmented, 2=minimalist, 3=capsule)
        self.programmatic_style = self.settings.value("programmatic_style", 0, type=int)

        # Set Breeze or Fusion style for consistent widget drawing
        if "Breeze" in QtWidgets.QStyleFactory.keys():
            self.setStyle(QtWidgets.QStyleFactory.create("Breeze"))
        else:
            self.setStyle(QtWidgets.QStyleFactory.create("Fusion"))


        # State variables
        self.battery_percentage = 0
        self.is_charging = False
        self.query_success = False
        self.device_name = ""
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
        
        # History setup
        try:
            self.battery_history = json.loads(self.settings.value("battery_history", "[]"))
        except Exception:
            self.battery_history = []
        
        # Initialize UI Components
        self.init_tray()
        
        # Polling Timer Setup
        self.poll_timer = QtCore.QTimer(self)
        self.poll_timer.timeout.connect(self.start_query)
        self.poll_timer.start(self.poll_interval * 1000)
        
        # Trigger initial query
        self.start_query()

    def init_tray(self):
        # Create System Tray Icon
        self.tray_icon = QtWidgets.QSystemTrayIcon(self)
        self.update_icon()
        
        # Construct Context Menu
        self.menu = QtWidgets.QMenu()
        
        # 1. Info Header Section (Rendered as standard actions for D-Bus compatibility and bright text)
        self.header_action = QActionClass("Logitech Device", self.menu)
        self.menu.addAction(self.header_action)
        
        self.status_action = QActionClass("Querying state...", self.menu)
        self.menu.addAction(self.status_action)
        
        self.charged_time_action = QActionClass("Charged to 95%: Unknown", self.menu)
        self.menu.addAction(self.charged_time_action)
        
        self.menu.addSeparator()
        
        # 2. Refresh Action
        self.refresh_action = QActionClass("Refresh Now", self.menu)
        self.refresh_action.triggered.connect(self.start_query)
        self.menu.addAction(self.refresh_action)
        
        self.menu.addSeparator()
        
        # 3. Settings Submenu - Refresh Interval
        self.interval_menu = self.menu.addMenu("Refresh Interval")
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
        self.action_autostart.setCheckable(True)
        self.action_autostart.setChecked(self.autostart_enabled)
        self.action_autostart.triggered.connect(self.toggle_autostart)
        self.menu.addAction(self.action_autostart)
        # 5. Preferences settings panel launcher
        self.prefs_action = QActionClass("Preferences...", self.menu)
        self.prefs_action.triggered.connect(self.show_preferences)
        self.menu.addAction(self.prefs_action)
        
        self.menu.addSeparator()
        
        # 7. Quit Action
        self.quit_action = QActionClass("Quit Monitor", self.menu)
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
                    # Single shot 2 seconds timer
                    QtCore.QTimer.singleShot(2000, self.confirm_debounce)
                else:
                    if new_percentage == self.debounce_target_percentage and new_charging == self.debounce_target_charging:
                        self.is_debouncing = False
                        self.apply_battery_data(new_percentage, new_charging)
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
            self.status_action.setText(f"Not Connected (Last seen: {self.battery_percentage}%)" if self.has_valid_data else "Not Connected")
            self.tray_icon.setToolTip(f"Logitech Battery Monitor\n{self.error_details}")
            
        self.update_icon()

    def confirm_debounce(self):
        self.is_debouncing = False
        self.start_query()

    def apply_battery_data(self, percentage, is_charging):
        self.battery_percentage = percentage
        self.is_charging = is_charging
        
        # Update charge timestamp if conditions met
        if percentage >= 95 or (is_charging and percentage >= 95):
            self.last_charged_time = time.time()
            self.settings.setValue("last_charged_time", self.last_charged_time)
            
        self.update_battery_history(percentage, is_charging)
        estimate = self.estimate_hours_left(percentage)
        
        status_text = f"Battery: {self.battery_percentage}%{estimate}"
        if self.is_charging:
            status_text += " (Charging)"
        else:
            status_text += " (Discharging)"
            
        self.header_action.setText(self.device_name)
        self.status_action.setText(status_text)
        
        # Calculate and format elapsed time since charged
        if self.last_charged_time > 0.0:
            elapsed = time.time() - self.last_charged_time
            if elapsed < 0:
                elapsed = 0
            
            days = int(elapsed // 86400)
            hours = int((elapsed % 86400) // 3600)
            minutes = int((elapsed % 3600) // 60)
            
            if days > 0:
                time_str = f"{days}d {hours}h"
            elif hours > 0:
                time_str = f"{hours}h {minutes}m"
            else:
                time_str = f"{minutes}m"
                if minutes == 0:
                    time_str = f"{int(elapsed)}s"
            charged_text = f"Charged to 95%: {time_str} ago"
        else:
            charged_text = "Charged to 95%: Unknown"
            
        self.charged_time_action.setText(charged_text)
        self.tray_icon.setToolTip(f"{self.device_name}\nCharge: {self.battery_percentage}%{estimate}\n{charged_text}")
        
        # Save historical values
        self.last_percentage = percentage
        self.last_charging = is_charging
        self.has_valid_data = True

    def update_battery_history(self, percentage, is_charging):
        # Reset history if charging starts
        if is_charging:
            if self.battery_history:
                self.battery_history = []
                self.settings.setValue("battery_history", "[]")
            return
            
        now = time.time()
        
        # If history is empty, initialize it
        if not self.battery_history:
            self.battery_history = [{"time": now, "percent": percentage}]
            self.settings.setValue("battery_history", json.dumps(self.battery_history))
            return
            
        last_point = self.battery_history[-1]
        
        # If the percentage dropped, log it
        if percentage < last_point["percent"]:
            self.battery_history.append({"time": now, "percent": percentage})
            if len(self.battery_history) > 10:
                self.battery_history.pop(0)
            self.settings.setValue("battery_history", json.dumps(self.battery_history))

    def estimate_hours_left(self, current_percentage):
        if self.is_charging:
            return ""
            
        if not self.battery_history or len(self.battery_history) < 2:
            # Default fallback: ~120 hours total life (0.83% drop per hour)
            default_rate = 0.83
            hours = current_percentage / default_rate
            return f" (~{int(hours)}h left)"
            
        first = self.battery_history[0]
        last = self.battery_history[-1]
        
        pct_drop = first["percent"] - last["percent"]
        time_elapsed = last["time"] - first["time"]
        
        if pct_drop <= 0 or time_elapsed < 60:
            default_rate = 0.83
            hours = current_percentage / default_rate
            return f" (~{int(hours)}h left)"
            
        hours_elapsed = time_elapsed / 3600.0
        drain_rate = pct_drop / hours_elapsed
        
        if drain_rate < 0.2:
            drain_rate = 0.2
        elif drain_rate > 10.0:
            drain_rate = 10.0
            
        hours = current_percentage / drain_rate
        return f" (~{int(hours)}h left)"

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
            # Green when charging
            color_hex = "#2ECC71"
        elif self.battery_percentage <= self.critical_threshold:
            # Light Red when critical
            color_hex = "#FF6B6B"
        elif self.battery_percentage <= self.warning_threshold:
            # Orange when warning
            color_hex = "#F39C12"
        else:
            # Default white/light grey for standard discharging battery levels
            color_hex = "#E0E0E0"
            
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
        
        # Style 5 is Circular Ring Gauge
        if self.programmatic_style == 5:
            rect = QtCore.QRectF(4, 4, 24, 24)
            
            # Background track ring
            track_color = QtGui.QColor("#3A3A3C")
            painter.setPen(QtGui.QPen(track_color, 3.0))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawArc(rect, 0, 360 * 16)
            
            # Progress arc overlay
            color = QtGui.QColor(battery_color_hex)
            pen = QtGui.QPen(color, 3.0, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
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

    def load_svg_icon(self, filename, show_text, is_horizontal):
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
        renderer = QtSvg.QSvgRenderer(svg_path)
        
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
            
            font = QtGui.QFont("Sans Serif", 9, QtGui.QFont.Bold)
            painter.setFont(font)
            
            text = str(self.battery_percentage)
            rect = pixmap.rect()
            
            bg_color = QtGui.QColor("#FFFFFF")
            painter.setPen(bg_color)
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx != 0 or dy != 0:
                        painter.drawText(rect.translated(dx, dy), QtAlignHCenter | QtAlignVCenter, text)
                        
            painter.setPen(QtGui.QColor("#2C3E50"))
            painter.drawText(rect, QtAlignHCenter | QtAlignVCenter, text)
            
        painter.end()
        return QtGui.QIcon(pixmap)

    def sync_menu_states(self):
        # Update autostart checkbox in tray menu
        if hasattr(self, 'action_autostart'):
            self.action_autostart.setChecked(self.autostart_enabled)
        # Update refresh interval checkmarks in tray menu
        if hasattr(self, 'interval_menu'):
            for act in self.interval_menu.actions():
                if act.text().startswith(str(self.poll_interval)):
                    act.setChecked(True)
                else:
                    act.setChecked(False)

    def set_interval(self, seconds):
        self.poll_interval = seconds
        self.settings.setValue("poll_interval", seconds)
        self.poll_timer.setInterval(seconds * 1000)
        self.poll_timer.start()

    def toggle_autostart(self, checked):
        self.autostart_enabled = checked
        self.settings.setValue("autostart", checked)
        autostart_dir = os.path.expanduser("~/.config/autostart")
        desktop_file = os.path.join(autostart_dir, "logitech-battery-tray.desktop")
        
        if checked:
            os.makedirs(autostart_dir, exist_ok=True)
            content = f"""[Desktop Entry]
Type=Application
Version=1.0
Name=Logitech Battery
Comment=Logitech Battery Monitor System Tray Application
Exec=python3 {os.path.abspath(__file__)}
Icon=input-mouse
Terminal=false
Categories=Utility;System;
StartupNotify=false
"""
            try:
                with open(desktop_file, "w") as f:
                    f.write(content)
                os.chmod(desktop_file, 0o755)
            except Exception as e:
                print(f"Error creating autostart entry: {e}")
        else:
            if os.path.exists(desktop_file):
                try:
                    os.remove(desktop_file)
                except Exception as e:
                    print(f"Error removing autostart entry: {e}")


if __name__ == '__main__':
    app = LogitechBatteryTrayApp(sys.argv)
    sys.exit(app.exec())
