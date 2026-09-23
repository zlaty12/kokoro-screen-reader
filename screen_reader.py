"""
Double-click the middle mouse button -> drag to select an area of the screen ->
the text in that area is read aloud with Kokoro TTS.

  Esc / right-click while selecting : cancel
  Double middle-click while speaking: stop speaking (and start a new selection)
  Ctrl+C in this window             : quit
"""
import asyncio
import ctypes
import ctypes.wintypes as wintypes
import os
import queue
import re
import threading
import time
import tkinter as tk
import urllib.request

import mss
import onnxruntime as ort
import sounddevice as sd
from kokoro_onnx import Kokoro
from PIL import Image, ImageEnhance, ImageTk
from pynput import mouse
from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter

# ---------------- settings ----------------
VOICE = "af_heart"        # other voices: af_bella, af_nicole, am_adam, am_michael, bf_emma, bm_george ...
SPEED = 1.0
LANG = "en-us"
DOUBLE_CLICK_TIME = 0.4   # seconds between the two middle clicks
# ------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))

# Use real pixel coordinates so the screenshot, the overlay and the mouse all line up.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()


def disable_power_throttling():
    """Windows parks background apps on slow efficiency cores, which makes speech
    generation several times slower and very inconsistent. Opt out of that."""
    class PowerThrottlingState(ctypes.Structure):
        _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]

    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    proc = k32.GetCurrentProcess()
    state = PowerThrottlingState(1, 1, 0)  # control EXECUTION_SPEED, state = not throttled
    k32.SetProcessInformation(proc, 4, ctypes.byref(state), ctypes.sizeof(state))  # 4 = ProcessPowerThrottling
    k32.SetPriorityClass(proc, 0x80)  # HIGH_PRIORITY_CLASS


disable_power_throttling()


# ---------------- OCR (built-in Windows OCR) ----------------
ocr_engine = OcrEngine.try_create_from_user_profile_languages()


def ocr(img: Image.Image) -> str:
    # Small text is recognised much better when enlarged.
    scale = 3 if img.height < 150 else 2 if img.height < 600 else 1
    if scale > 1:
        img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    limit = OcrEngine.max_image_dimension
    if max(img.size) > limit:
        img.thumbnail((limit, limit))

    r, g, b, a = img.convert("RGBA").split()
    bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()

    writer = DataWriter()
    writer.write_bytes(bgra)
    bitmap = SoftwareBitmap.create_copy_from_buffer(
        writer.detach_buffer(), BitmapPixelFormat.BGRA8, img.width, img.height)

    async def run():
        return await ocr_engine.recognize_async(bitmap)

    result = asyncio.run(run())
    text = ""
    for line in result.lines:
        t = line.text.strip()
        if text.endswith("-"):          # re-join words hyphenated across lines
            text = text[:-1] + t
        else:
            text = (text + " " + t).strip()
    return text


# ---------------- TTS ----------------
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        print(f"Downloading {name} (first run only, this can take a few minutes)...")
        urllib.request.urlretrieve(MODEL_URL + name, path + ".part")
        os.replace(path + ".part", path)

print("Loading Kokoro...")
_opts = ort.SessionOptions()
_opts.intra_op_num_threads = min(6, os.cpu_count() or 6)  # more threads is slower on hybrid (P/E-core) CPUs
kokoro = Kokoro.from_session(
    ort.InferenceSession(os.path.join(HERE, "kokoro-v1.0.onnx"), _opts, providers=["CPUExecutionProvider"]),
    os.path.join(HERE, "voices-v1.0.bin"))
kokoro.create("Ready.", voice=VOICE, speed=SPEED, lang=LANG)  # warm-up: the first run is always slow
speech_id = 0  # bumped to cancel whatever is currently being spoken


def stop_speaking():
    global speech_id
    speech_id += 1
    sd.stop()


def split_chunks(text: str) -> list[str]:
    """Split into sentences, and keep the first chunk short so speech starts right away."""
    sentences = [s for s in re.split(r"(?<=[.!?;:])\s+", text) if s.strip()]
    if not sentences:
        return []
    words = sentences[0].split()
    if len(words) > 12:
        # cut after the first comma within the first 12 words, otherwise after 8 words
        cut = next((i + 1 for i, w in enumerate(words[:12]) if i >= 2 and w.endswith(",")), 8)
        sentences[0:1] = [" ".join(words[:cut]), " ".join(words[cut:])]
    return sentences


def speak(text: str):
    """Generate and play chunk by chunk so speech starts quickly."""
    my_id = speech_id
    sentences = split_chunks(text)
    chunks: queue.Queue = queue.Queue(maxsize=3)

    def generate():
        for s in sentences:
            if my_id != speech_id:
                break
            try:
                samples, sr = kokoro.create(s, voice=VOICE, speed=SPEED, lang=LANG)
                chunks.put((samples, sr))
            except Exception as e:
                print("TTS error:", e)
        chunks.put(None)

    threading.Thread(target=generate, daemon=True).start()
    while my_id == speech_id:
        item = chunks.get()
        if item is None:
            break
        samples, sr = item
        if my_id != speech_id:
            break
        sd.play(samples, sr)
        # wait in small steps so we can be interrupted
        end = time.time() + len(samples) / sr
        while time.time() < end and my_id == speech_id:
            time.sleep(0.05)


def read_image(img: Image.Image):
    text = ocr(img)
    if not text:
        print("No text found.")
        return
    print("Reading:", text)
    speak(text)


# ---------------- selection overlay ----------------
class Selector:
    def __init__(self, root: tk.Tk):
        self.root = root

    def open(self):
        with mss.mss() as sct:
            mon = sct.monitors[0]  # the whole virtual screen (all monitors)
            shot = sct.grab(mon)
        self.full = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        self.left, self.top = mon["left"], mon["top"]

        win = self.win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.geometry(f"{mon['width']}x{mon['height']}+{mon['left']}+{mon['top']}")

        dimmed = ImageEnhance.Brightness(self.full).enhance(0.55)
        self.bg = ImageTk.PhotoImage(dimmed)
        c = self.canvas = tk.Canvas(win, cursor="crosshair", highlightthickness=0)
        c.pack(fill="both", expand=True)
        c.create_image(0, 0, image=self.bg, anchor="nw")
        self.bright = None
        self.rect = None
        self.start = None

        c.bind("<ButtonPress-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<ButtonPress-3>", lambda e: self.close())
        win.bind("<Escape>", lambda e: self.close())
        win.focus_force()
        win.after(50, win.focus_force)

    def on_press(self, e):
        self.start = (e.x, e.y)

    def on_drag(self, e):
        if not self.start:
            return
        x0, y0 = self.start
        box = (min(x0, e.x), min(y0, e.y), max(x0, e.x), max(y0, e.y))
        c = self.canvas
        # show the selected region at full brightness
        if box[2] - box[0] > 1 and box[3] - box[1] > 1:
            self.bright = ImageTk.PhotoImage(self.full.crop(box))
            if getattr(self, "bright_item", None):
                c.itemconfig(self.bright_item, image=self.bright)
                c.coords(self.bright_item, box[0], box[1])
            else:
                self.bright_item = c.create_image(box[0], box[1], image=self.bright, anchor="nw")
        if self.rect:
            c.coords(self.rect, *box)
        else:
            self.rect = c.create_rectangle(*box, outline="#4da3ff", width=2)
        c.tag_raise(self.rect)

    def on_release(self, e):
        if not self.start:
            return
        x0, y0 = self.start
        box = (min(x0, e.x), min(y0, e.y), max(x0, e.x), max(y0, e.y))
        self.close()
        if box[2] - box[0] < 5 or box[3] - box[1] < 5:
            return
        crop = self.full.crop(box)
        threading.Thread(target=read_image, args=(crop,), daemon=True).start()

    def close(self):
        self.bright_item = None
        try:
            self.win.destroy()
        except Exception:
            pass


# ---------------- main: middle double-click hook ----------------
def main():
    root = tk.Tk()
    root.withdraw()
    selector = Selector(root)
    triggers: queue.Queue = queue.Queue()
    last_click = [0.0]

    def on_click(x, y, button, pressed):
        if button == mouse.Button.middle and pressed:
            now = time.time()
            if now - last_click[0] < DOUBLE_CLICK_TIME:
                last_click[0] = 0.0
                triggers.put(True)
            else:
                last_click[0] = now

    def poll():
        try:
            while True:
                triggers.get_nowait()
                stop_speaking()
                selector.close()
                selector.open()
        except queue.Empty:
            pass
        root.after(30, poll)

    mouse.Listener(on_click=on_click, daemon=True).start()
    poll()
    print("Ready! Double-click the middle mouse button to select text to read. Ctrl+C to quit.")
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
