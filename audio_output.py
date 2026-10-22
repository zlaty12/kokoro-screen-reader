"""Drain audio at normal completion; abort only for an explicit Stop."""
import threading

import numpy as np
import sounddevice as sd


class AudioOutput:
    def __init__(self, driver=sd):
        self.driver = driver
        self.lock = threading.RLock()
        self.current = None

    def play(self, samples, rate):
        # Preserve a short quiet tail for Bluetooth output pipelines. In contrast
        # to sounddevice.play(), normal completion uses CallbackStop, not Abort.
        data = np.concatenate((np.asarray(samples, dtype=np.float32),
                               np.zeros(round(rate * .3), dtype=np.float32)))
        position = 0
        finished = threading.Event()

        def callback(out, frames, timing, status):
            nonlocal position
            count = min(frames, len(data) - position)
            out.fill(0)
            out[:count, 0] = data[position:position + count]
            position += count
            if position == len(data):
                # PortAudio plays the supplied buffer and drains pending output.
                raise self.driver.CallbackStop

        with self.lock:
            stream = self.driver.OutputStream(
                samplerate=rate, channels=1, dtype="float32",
                callback=callback, finished_callback=finished.set)
            self.current = (stream, finished)
            try:
                stream.start()
            except Exception:
                self.current = None
                stream.close()
                raise

    def wait(self):
        with self.lock:
            current = self.current
        if current is None:
            return
        stream, finished = current
        finished.wait()
        with self.lock:
            if self.current is current:
                stream.close()
                self.current = None

    def stop(self):
        with self.lock:
            if self.current is not None:
                stream, finished = self.current
                try:
                    stream.abort()
                finally:
                    stream.close()
                    finished.set()
                    self.current = None
