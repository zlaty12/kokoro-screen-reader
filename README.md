# 🔊 Kokoro Screen Reader

**Double-click your middle mouse button, draw a box around any text on your screen, and hear it read aloud in a natural-sounding voice.**

It works on anything you can see: web pages, PDFs, games, subtitles, screenshots, images, apps that won't let you copy text. It runs entirely on your own PC, with no accounts, API keys or internet needed after the first run.

---

## Why I built this

Most text-to-speech tools make you copy and paste text into a box first, and a lot of text can't be copied at all: text inside images, game dialogue, scanned documents, videos, locked PDFs. I wanted something where I could just point at the screen and say "read that."

I also wanted it to sound good. Classic Windows voices sound robotic. [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) is a small (82M parameter) open-source TTS model that sounds close to a real person, and it's light enough to run locally on a normal laptop CPU.

So this little tool glues three things together:

1. **A mouse hook** that watches for a double middle-click from anywhere in Windows.
2. **A snipping overlay** that freezes your screen so you can drag a box around the text you want.
3. **OCR + TTS**: the selected area goes through Windows' built-in text recognition, and the text is spoken by Kokoro.

## ✨ Features

- 🖱️ **One gesture**: double-click the middle mouse button from any app
- ✂️ **Snipping-tool style selection** that works across multiple monitors
- 👁️ **Built-in Windows OCR**: fast (well under a second) with nothing extra to install
- 🗣️ **Kokoro TTS**: high-quality, natural voices, running 100% offline
- ⚡ **Starts speaking fast**: text is generated sentence by sentence, so it talks while it prepares the next part
- ⏹️ **Easy to interrupt**: double middle-click again to stop and pick something new
- 🔒 **Private**: nothing you read ever leaves your computer

## 🚀 Getting started

**Requirements:** Windows 10/11 and [Python 3.10+](https://www.python.org/downloads/) (tick *"Add Python to PATH"* during install).

```bash
git clone https://github.com/zlaty12/kokoro-screen-reader.git
cd kokoro-screen-reader
```

Then just double-click **`Start Screen Reader.bat`**.

On the first run it will:
- install the Python packages from `requirements.txt`
- download the Kokoro model (~325 MB) and voices file (~28 MB)

After that it starts in a few seconds.

<details>
<summary>Prefer the command line?</summary>

```bash
pip install -r requirements.txt
python screen_reader.py
```
</details>

## 🎮 How to use

| Action | What it does |
|---|---|
| **Double middle-click** | Freeze the screen and start selecting |
| **Left-drag** | Draw a box around the text |
| **Release** | Reads the text aloud |
| **Esc** / **right-click** | Cancel the selection |
| **Double middle-click while speaking** | Stop and start a new selection |
| **Close the console window** | Quit |

## ⚙️ Settings

Open `screen_reader.py` and change the values at the top:

```python
VOICE = "af_heart"        # the voice to use
SPEED = 1.0               # 0.5 = slower, 1.5 = faster
LANG = "en-us"            # "en-gb" for British pronunciation
DOUBLE_CLICK_TIME = 0.4   # max seconds between the two middle clicks
```

Some voices to try:

| Voice | Style |
|---|---|
| `af_heart` | American female (default, warm) |
| `af_bella` | American female |
| `af_nicole` | American female, soft |
| `am_adam` | American male |
| `am_michael` | American male |
| `bf_emma` | British female |
| `bm_george` | British male |

## 🛠️ How it works

```
 double middle-click ──► screenshot of all monitors ──► dimmed fullscreen overlay
                                                              │
                                                     you drag a box
                                                              ▼
 speakers ◄── Kokoro TTS (sentence by sentence) ◄── Windows OCR on the cropped area
```

- **[pynput](https://pypi.org/project/pynput/)** listens for mouse clicks globally.
- **[mss](https://pypi.org/project/mss/)** grabs the screen, and **tkinter** draws the selection overlay.
- **Windows.Media.Ocr** (through the [winrt](https://pypi.org/project/winrt-runtime/) Python bindings) recognises the text. Small text is upscaled first for better accuracy, and words hyphenated across lines are joined back together.
- **[kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx)** runs the Kokoro model with ONNX Runtime on the CPU, and **[sounddevice](https://pypi.org/project/sounddevice/)** plays the audio.

## 💡 Tips and troubleshooting

- **Browsers show a scroll icon when I middle-click.** That's the browser's auto-scroll. It's harmless and goes away when the overlay appears.
- **It reads the wrong words.** Select a tighter box around just the text. OCR works best on clear, high-contrast text.
- **There's a short pause before it speaks.** The first sentence has to be generated before playback starts. Selecting a shorter piece of text makes it start faster.
- **OCR language.** Windows OCR uses the languages installed on your system (Settings → Time & language → Language).

## 🙏 Credits

- [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) by hexgrad, the voice model
- [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) by thewh1teagle, the ONNX runtime wrapper and model files

## 📄 License

MIT. Do whatever you like with it.
