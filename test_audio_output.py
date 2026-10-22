import threading
import unittest
import ast
from pathlib import Path
import queue
import re
import time
from types import SimpleNamespace

import numpy as np

from audio_output import AudioOutput


class FakeDriver:
    class CallbackStop(Exception):
        pass

    def OutputStream(self, **options):
        self.stream = FakeStream(options)
        return self.stream


class FakeStream:
    def __init__(self, options):
        self.options = options
        self.aborted = False
        self.closed = False

    def start(self):
        pass

    def abort(self):
        self.aborted = True

    def close(self):
        self.closed = True


class AudioOutputTests(unittest.TestCase):
    def test_speak_waits_for_each_chunk_and_stop_interrupts(self):
        # Import only the playback functions: importing screen_reader itself
        # downloads/loads the model and requires Windows OCR.
        source = ast.parse(Path(__file__).with_name('screen_reader.py').read_text(encoding='utf-8'))
        functions = [node for node in source.body if isinstance(node, ast.FunctionDef)
                     and node.name in {'speak', 'stop_speaking', 'split_chunks'}]
        played = []
        started = threading.Event()
        drained = threading.Event()

        def play(samples, rate):
            played.append(samples)
            started.set()

        fake = SimpleNamespace(play=play, wait=lambda: drained.wait(2), stop=drained.set)
        namespace = dict(threading=threading, queue=queue, re=re, time=time,
                         speech_id=0, playback_lock=threading.Lock(), audio=fake, sd=fake,
                         VOICE='test', SPEED=1, LANG='en-us',
                         kokoro=SimpleNamespace(create=lambda text, **kwargs: ([text], 1000)))
        exec(compile(ast.Module(body=functions, type_ignores=[]), '<playback>', 'exec'), namespace)
        worker = threading.Thread(target=namespace['speak'], args=('First. Second.',), daemon=True)
        worker.start()
        try:
            self.assertTrue(started.wait(1))
            # Nominal duration is 1ms, but the simulated device hasn't drained.
            time.sleep(.15)
            self.assertEqual(played, [['First.']])
            namespace['stop_speaking']()
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(played, [['First.']])
        finally:
            namespace['stop_speaking']()
            worker.join(1)

    def test_last_buffer_is_drained_including_bluetooth_tail(self):
        driver = FakeDriver()
        audio = AudioOutput(driver)
        samples = np.arange(7, dtype=np.float32)
        audio.play(samples, 10)
        stream = driver.stream
        captured = []
        for _ in range(3):
            out = np.empty((4, 1), dtype=np.float32)
            try:
                stream.options['callback'](out, 4, None, None)
            except driver.CallbackStop:
                captured.extend(out[:, 0])
                break
            captured.extend(out[:, 0])
        else:
            self.fail('Callback did not request a graceful stop')
        np.testing.assert_array_equal(captured[:7], samples)
        np.testing.assert_array_equal(captured[7:], np.zeros(5))
        waiter = threading.Thread(target=audio.wait)
        waiter.start()
        waiter.join(.05)
        self.assertTrue(waiter.is_alive(), 'Must wait for the device to drain')
        stream.options['finished_callback']()
        waiter.join(1)
        self.assertFalse(waiter.is_alive())
        self.assertFalse(stream.aborted)
        self.assertTrue(stream.closed)

    def test_user_stop_aborts_and_releases_waiter(self):
        driver = FakeDriver()
        audio = AudioOutput(driver)
        audio.play([1, 2, 3], 100)
        waiter = threading.Thread(target=audio.wait)
        waiter.start()
        audio.stop()
        waiter.join(1)
        self.assertFalse(waiter.is_alive())
        self.assertTrue(driver.stream.aborted)
        self.assertTrue(driver.stream.closed)
        audio.stop()  # stopping an idle output is harmless


if __name__ == '__main__':
    unittest.main()
