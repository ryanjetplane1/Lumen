import asyncio
import ctypes
import os
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
import winreg

import keyboard
import psutil
import serial
import winrt.windows.media.control as wmc
from comtypes import CLSCTX_ALL
from ctypes import POINTER, cast
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from serial.tools import list_ports


BAUD_RATE = 115200
RECONNECT_SECONDS = 3.0
SEND_INTERVAL_SECONDS = 0.05
BROWSER_SOURCES = {"chrome", "firefox", "msedge", "opera", "brave", "vivaldi", "arc"}
ESP32_HINTS = ["CH340", "CH343", "CP210", "USB-SERIAL", "USB SERIAL", "SILICON LABS", "USB JTAG"]
APP_NAME = "Lumen"
OLD_APP_NAME = "Lumen SSD1306"
SETTINGS_KEY = r"Software\Lumen"


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def get_volume_control():
    try:
        devices = AudioUtilities.GetDeviceEnumerator()
        interface = devices.GetDefaultAudioEndpoint(0, 1)
        volume_iface = interface.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(volume_iface, POINTER(IAudioEndpointVolume))
    except Exception as error:
        print(f"Volume Sync Error: {error}")
        return None


def list_esp32_ports():
    ports = list_ports.comports()
    matching = []
    for port in ports:
        description = (port.description or "").upper()
        if any(hint in description for hint in ESP32_HINTS):
            matching.append(port.device)
    return matching or [port.device for port in ports]


def executable_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --startup-hidden'
    return f'"{sys.executable}" "{os.path.abspath(__file__)}" --startup-hidden'


def set_autostart(enabled):
    run_key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE,
    )
    try:
        if enabled:
            winreg.SetValueEx(run_key, APP_NAME, 0, winreg.REG_SZ, executable_command())
            try:
                winreg.DeleteValue(run_key, OLD_APP_NAME)
            except FileNotFoundError:
                pass
        else:
            for value_name in (APP_NAME, OLD_APP_NAME):
                try:
                    winreg.DeleteValue(run_key, value_name)
                except FileNotFoundError:
                    pass
    finally:
        winreg.CloseKey(run_key)


def get_autostart():
    try:
        run_key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        )
        try:
            winreg.QueryValueEx(run_key, APP_NAME)
            return True
        finally:
            winreg.CloseKey(run_key)
    except FileNotFoundError:
        return False


def set_start_hidden(enabled):
    settings_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY)
    try:
        winreg.SetValueEx(settings_key, "StartHidden", 0, winreg.REG_DWORD, int(enabled))
    finally:
        winreg.CloseKey(settings_key)


def get_start_hidden():
    try:
        settings_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY, 0, winreg.KEY_READ)
        try:
            value, _ = winreg.QueryValueEx(settings_key, "StartHidden")
            return bool(value)
        finally:
            winreg.CloseKey(settings_key)
    except FileNotFoundError:
        return True


class MediaTracker:
    def __init__(self):
        self.song = "No Music"
        self.artist = ""
        self.pos = 0.0
        self.dur = 0.0
        self.playing = 0
        self.prev_playing = 0
        self.is_browser = False


class SenderWorker:
    def __init__(self, status_callback, port_getter):
        self.status_callback = status_callback
        self.port_getter = port_getter
        self.stop_event = threading.Event()
        self.thread = None
        self.serial_port = None
        self.tracker = MediaTracker()
        self.h_bars = [0] * 12
        self.bars_fading = False
        self.volume_ctrl = get_volume_control()
        self.cpu_cache = 0
        self.ram_cache = 0
        self.last_stat_time = 0

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run, name="lumen-sender", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.serial_port:
            try:
                self.serial_port.close()
            except (serial.SerialException, OSError):
                pass
        if self.thread:
            self.thread.join(timeout=2)

    def status(self, text):
        self.status_callback(text)

    def selected_port(self):
        selected = self.port_getter()
        return selected or None

    def connect_serial(self):
        ports = [self.selected_port()] if self.selected_port() else list_esp32_ports()
        for port in ports:
            if not port:
                continue
            try:
                connection = serial.Serial(port, BAUD_RATE, timeout=0.01, write_timeout=0.2)
                time.sleep(1.5)
                self.status(f"Connected to {port}")
                return connection
            except (serial.SerialException, OSError) as error:
                self.status(f"Unable to open {port}: {error}")
        self.status("No ESP32 port found; retrying...")
        return None

    async def media_task(self):
        while not self.stop_event.is_set():
            try:
                manager = await wmc.GlobalSystemMediaTransportControlsSessionManager.request_async()
                session = manager.get_current_session()
                if session:
                    source = session.source_app_user_model_id.lower()
                    self.tracker.is_browser = any(name in source for name in BROWSER_SOURCES)
                    props = await session.try_get_media_properties_async()
                    self.tracker.song = props.title[:40] if props.title else "No Music"
                    self.tracker.artist = props.artist[:40] if props.artist else ""
                    info = session.get_playback_info()
                    self.tracker.prev_playing = self.tracker.playing
                    self.tracker.playing = 1 if info.playback_status == 4 else 0
                    if not self.tracker.is_browser:
                        timeline = session.get_timeline_properties()
                        position = timeline.position.total_seconds()
                        duration = timeline.end_time.total_seconds()
                        self.tracker.pos = max(0.0, position) if position == position else 0.0
                        self.tracker.dur = max(0.0, duration) if duration == duration else 0.0
                    else:
                        self.tracker.pos = 0.0
                        self.tracker.dur = 0.0
                else:
                    self.tracker.prev_playing = self.tracker.playing
                    self.tracker.playing = 0
                    self.tracker.artist = ""
                    self.tracker.is_browser = False
            except Exception as error:
                self.status(f"Media read error: {error}")
                self.tracker.prev_playing = self.tracker.playing
                self.tracker.playing = 0
                self.tracker.artist = ""
                self.tracker.is_browser = False
            await asyncio.sleep(0.5)

    def handle_board_commands(self):
        if not self.serial_port or self.serial_port.in_waiting <= 0:
            return
        line = self.serial_port.readline().decode("utf-8", errors="ignore").strip()
        commands = {
            "CW": "volume up",
            "CCW": "volume down",
            "PAUSE": "play/pause media",
            "NEXT": "next track",
            "PREV": "previous track",
        }
        if line in commands:
            keyboard.press_and_release(commands[line])

    def build_packet(self):
        current_volume = 0
        try:
            if self.volume_ctrl:
                current_volume = round(self.volume_ctrl.GetMasterVolumeLevelScalar() * 100)
            else:
                self.volume_ctrl = get_volume_control()
        except (AttributeError, OSError):
            self.volume_ctrl = None

        if time.time() - self.last_stat_time > 2.0:
            self.cpu_cache = int(psutil.cpu_percent())
            self.ram_cache = round(psutil.virtual_memory().used / (1024 ** 3), 1)
            self.last_stat_time = time.time()

        tracker = self.tracker
        if not tracker.is_browser:
            if tracker.prev_playing == 1 and tracker.playing == 0:
                self.bars_fading = True
            fade_mult = 1.0
            if tracker.playing:
                self.bars_fading = False
                if tracker.dur > 0:
                    time_left = tracker.dur - tracker.pos
                    if tracker.pos < 2.0:
                        fade_mult = tracker.pos / 2.0
                    elif time_left < 2.0:
                        fade_mult = max(0.0, time_left / 2.0)
            for index in range(12):
                if tracker.playing:
                    if random.random() > 0.85:
                        self.h_bars[index] = int(random.randint(10, 32) * fade_mult)
                    self.h_bars[index] = max(0, self.h_bars[index] - 2)
                elif self.bars_fading:
                    self.h_bars[index] = max(0, self.h_bars[index] - 2)
                else:
                    self.h_bars[index] = 0
            if self.bars_fading and all(bar == 0 for bar in self.h_bars):
                self.bars_fading = False
        else:
            self.h_bars = [0] * 12
            self.bars_fading = False

        local_time = time.localtime()
        playing_out = tracker.playing if not tracker.is_browser else 0
        return (
            f"{self.cpu_cache}|{self.ram_cache}G|{tracker.song}|"
            f"{tracker.pos:.3f}|{tracker.dur:.3f}|"
            f"{','.join(map(str, self.h_bars))}|"
            f"{local_time.tm_hour % 12 or 12}|{local_time.tm_min:02d}|"
            f"{playing_out}|{tracker.artist}|{current_volume}\n"
        )

    async def send_loop(self):
        next_tick = time.perf_counter()
        while not self.stop_event.is_set():
            if self.serial_port is None:
                self.serial_port = self.connect_serial()
                if self.serial_port is None:
                    await asyncio.sleep(RECONNECT_SECONDS)
                    continue
            try:
                self.handle_board_commands()
                self.serial_port.write(self.build_packet().encode("utf-8"))
            except (serial.SerialException, OSError, UnicodeError) as error:
                self.status(f"Disconnected; retrying: {error}")
                try:
                    self.serial_port.close()
                except (serial.SerialException, OSError):
                    pass
                self.serial_port = None
                await asyncio.sleep(RECONNECT_SECONDS)
                continue
            await asyncio.sleep(SEND_INTERVAL_SECONDS)

    def run(self):
        try:
            asyncio.run(self.run_async())
        except Exception as error:
            self.status(f"Worker stopped: {error}")

    async def run_async(self):
        media_task = asyncio.create_task(self.media_task())
        try:
            await self.send_loop()
        finally:
            media_task.cancel()
            await asyncio.gather(media_task, return_exceptions=True)


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.port_var = tk.StringVar(value="Auto")
        self.autostart_var = tk.BooleanVar(value=get_autostart())
        self.hide_on_close_var = tk.BooleanVar(value=True)
        self.start_hidden_var = tk.BooleanVar(value=get_start_hidden())
        self.status_var = tk.StringVar(value="Stopped")
        self.worker = None
        self.restore_hotkey = keyboard.add_hotkey(
            "ctrl+shift+l",
            lambda: self.root.after(0, self.show_window),
        )
        self.build_ui()
        if self.autostart_var.get():
            set_autostart(True)
        self.refresh_ports()
        self.root.after(1000, self.refresh_ports)
        if self.autostart_var.get():
            self.root.after(250, self.start_from_autostart)

    def start_from_autostart(self):
        self.toggle_running()
        if "--startup-hidden" in sys.argv and self.start_hidden_var.get():
            self.root.withdraw()

    def build_ui(self):
        frame = ttk.Frame(self.root, padding=14)
        frame.grid()
        ttk.Label(frame, text="ESP32 port:").grid(row=0, column=0, sticky="w")
        self.port_combo = ttk.Combobox(frame, textvariable=self.port_var, state="readonly", width=18)
        self.port_combo.grid(row=0, column=1, padx=(8, 0))
        ttk.Button(frame, text="Refresh", command=self.refresh_ports).grid(row=0, column=2, padx=(8, 0))
        ttk.Checkbutton(
            frame,
            text="Start with Windows",
            variable=self.autostart_var,
            command=self.toggle_autostart,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(12, 0))
        ttk.Checkbutton(
            frame,
            text="Hide window when clicking X",
            variable=self.hide_on_close_var,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Checkbutton(
            frame,
            text="Start hidden when launched with Windows",
            variable=self.start_hidden_var,
            command=self.toggle_start_hidden,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.start_button = ttk.Button(frame, text="Start", command=self.toggle_running)
        self.start_button.grid(row=4, column=0, pady=(12, 0), sticky="w")
        ttk.Label(frame, textvariable=self.status_var, width=42).grid(
            row=4, column=1, columnspan=2, padx=(8, 0), pady=(12, 0), sticky="w"
        )

    def refresh_ports(self):
        ports = ["Auto"] + list_esp32_ports()
        self.port_combo["values"] = ports
        if self.port_var.get() not in ports:
            self.port_var.set("Auto")
        self.root.after(3000, self.refresh_ports)

    def selected_port(self):
        value = self.port_var.get()
        return None if value == "Auto" else value

    def set_status(self, text):
        self.root.after(0, self.status_var.set, text)

    def toggle_autostart(self):
        try:
            set_autostart(self.autostart_var.get())
            self.status_var.set("Autostart enabled" if self.autostart_var.get() else "Autostart disabled")
        except OSError as error:
            self.autostart_var.set(not self.autostart_var.get())
            self.status_var.set(f"Autostart error: {error}")

    def toggle_start_hidden(self):
        try:
            set_start_hidden(self.start_hidden_var.get())
            self.status_var.set(
                "Start-hidden enabled" if self.start_hidden_var.get() else "Start-hidden disabled"
            )
        except OSError as error:
            self.start_hidden_var.set(not self.start_hidden_var.get())
            self.status_var.set(f"Start-hidden error: {error}")

    def toggle_running(self):
        if self.worker and self.worker.thread and self.worker.thread.is_alive():
            self.worker.stop()
            self.worker = None
            self.start_button.configure(text="Start")
            self.status_var.set("Stopped")
        else:
            self.worker = SenderWorker(self.set_status, self.selected_port)
            self.worker.start()
            self.start_button.configure(text="Stop")
            self.status_var.set("Starting...")

    def show_window(self, _event=None):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def close(self):
        if self.hide_on_close_var.get():
            self.root.withdraw()
            return
        if self.worker:
            self.worker.stop()
        keyboard.remove_hotkey(self.restore_hotkey)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if not is_admin():
        print("Warning: not running as administrator; media key and volume control may fail.")
    App().run()
