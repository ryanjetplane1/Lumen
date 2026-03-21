import psutil, serial, time, asyncio, random, keyboard
import winrt.windows.media.control as wmc
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from comtypes import CLSCTX_ALL
from ctypes import cast, POINTER

def get_volume_control():
    try:
        devices = AudioUtilities.GetDeviceEnumerator()
        interface = devices.GetDefaultAudioEndpoint(0, 1)
        volume_iface = interface.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(volume_iface, POINTER(IAudioEndpointVolume))
    except Exception as e:
        print(f"Volume Sync Error: {e}")
        return None

volume_ctrl = get_volume_control()
COM_PORT = 'COM3'
BAUD_RATE = 115200

try:
    ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.01)
    print(f"Connected to {COM_PORT}. Syncing System Volume...")
    time.sleep(2)
except Exception as e:
    print(f"Serial Error: {e}"); exit()

class SpotifyTracker:
    def __init__(self):
        self.song, self.pos, self.dur = "No Music", 0.0, 0.0
        self.playing = 0
        self.prev_playing = 0

tracker = SpotifyTracker()

async def media_task():
    while True:
        try:
            manager = await wmc.GlobalSystemMediaTransportControlsSessionManager.request_async()
            session = manager.get_current_session()
            if session:
                props = await session.try_get_media_properties_async()
                tracker.song = props.title[:20]
                info = session.get_playback_info()
                tracker.prev_playing = tracker.playing
                tracker.playing = 1 if info.playback_status == 4 else 0
                timeline = session.get_timeline_properties()
                tracker.pos = timeline.position.total_seconds()
                tracker.dur = timeline.end_time.total_seconds()
            else:
                tracker.prev_playing = tracker.playing
                tracker.playing = 0
        except:
            tracker.prev_playing = tracker.playing
            tracker.playing = 0
        await asyncio.sleep(0.5)

h_bars = [0] * 12
bars_fading = False
cpu_cache, ram_cache = 0, 0
last_stat_time = 0

async def main_loop():
    global cpu_cache, ram_cache, volume_ctrl, bars_fading, last_stat_time

    asyncio.ensure_future(media_task())

    next_tick = time.perf_counter()

    while True:
        now = time.perf_counter()
        if now < next_tick:
            await asyncio.sleep(next_tick - now)
        next_tick += 0.05

        if ser.in_waiting > 0:
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line == "CW": keyboard.press_and_release('volume up')
                elif line == "CCW": keyboard.press_and_release('volume down')
                elif line == "PAUSE": keyboard.press_and_release('play/pause media')
                elif line == "NEXT": keyboard.press_and_release('next track')
                elif line == "PREV": keyboard.press_and_release('previous track')
            except:
                pass

        current_vol = 0
        try:
            if volume_ctrl:
                current_vol = round(volume_ctrl.GetMasterVolumeLevelScalar() * 100)
            else:
                volume_ctrl = get_volume_control()
        except:
            pass

        if time.time() - last_stat_time > 2.0:
            cpu_cache = int(psutil.cpu_percent())
            ram_cache = round(psutil.virtual_memory().used / (1024**3), 1)
            last_stat_time = time.time()

        if tracker.prev_playing == 1 and tracker.playing == 0:
            bars_fading = True

        fade_mult = 1.0
        if tracker.playing:
            bars_fading = False
            time_left = tracker.dur - tracker.pos
            if tracker.pos < 3.0: fade_mult = tracker.pos / 3.0
            elif time_left < 3.0: fade_mult = time_left / 3.0

        for i in range(12):
            if tracker.playing:
                if random.random() > 0.85: h_bars[i] = int(random.randint(10, 32) * fade_mult)
                h_bars[i] = max(0, h_bars[i] - 2)
            elif bars_fading:
                h_bars[i] = max(0, h_bars[i] - 2)
                if all(b == 0 for b in h_bars):
                    bars_fading = False
            else:
                h_bars[i] = 0

        t = time.localtime()
        packet = f"{cpu_cache}|{ram_cache}G|{tracker.song}|{int(tracker.pos)}|{int(tracker.dur)}|{','.join(map(str, h_bars))}|{t.tm_hour % 12 or 12}|{t.tm_min:02d}|{tracker.playing}|{current_vol}\n"
        ser.write(packet.encode())

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        ser.close()