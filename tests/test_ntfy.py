"""ntfy attachments: the recording in MP3 when it fits under ntfy.sh's free limit, else its preview; the
WAV when no encoder is installed. A local HTTP server stands for ntfy (nothing leaves the machine)."""
import http.server
import os
import shutil
import tempfile
import threading
import unittest
import wave

import numpy as np

from tests.support import app


def write_wav(path, seconds, seed=1):
    rng = np.random.default_rng(seed)
    audio = (0.2 * np.sin(2 * np.pi * 440 * np.arange(int(16000 * seconds)) / 16000) +
             0.05 * rng.standard_normal(int(16000 * seconds))) * 32767
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(audio.astype("<i2").tobytes())
    return path


class Ntfy(http.server.BaseHTTPRequestHandler):
    got = []

    def do_PUT(self):
        self.got.append((self.command, self.path, self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.end_headers()

    do_POST = do_PUT

    def log_message(self, *_):
        pass


class Attachment(unittest.TestCase):
    def setUp(self):
        self.a = app()
        self.tmp = tempfile.mkdtemp()
        self.rec = write_wav(os.path.join(self.tmp, "rec.wav"), 20)
        self.clip = write_wav(os.path.join(self.tmp, "clip.wav"), 2.5, seed=2)
        self.limit, self.encoder = self.a.NTFY_MAX_ATTACH, self.a.to_mp3

    def tearDown(self):
        self.a.NTFY_MAX_ATTACH, self.a.to_mp3 = self.limit, self.encoder
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_limit(self):
        self.assertEqual(self.a.NTFY_MAX_ATTACH, 2_000_000)

    @unittest.skipUnless(shutil.which("lame") or shutil.which("ffmpeg"), "no MP3 encoder")
    def test_mp3_recording(self):
        f, preview = self.a.ntfy_attachment(self.rec, self.clip, self.tmp, 7)
        self.assertFalse(preview)
        self.assertTrue(f.endswith("7.mp3"))
        self.assertLess(os.path.getsize(f), os.path.getsize(self.rec) / 4)

    @unittest.skipUnless(shutil.which("lame") or shutil.which("ffmpeg"), "no MP3 encoder")
    def test_too_long_sends_the_preview(self):
        self.a.NTFY_MAX_ATTACH = 50_000          # 20 s at 32 kbit/s is 80 kB, 2.5 s is 10 kB
        f, preview = self.a.ntfy_attachment(self.rec, self.clip, self.tmp, 7)
        self.assertTrue(preview)
        self.assertTrue(f.endswith("7-preview.mp3"))

    def test_without_encoder(self):
        self.a.to_mp3 = lambda wav, out: None
        self.assertEqual(self.a.ntfy_attachment(self.rec, self.clip, self.tmp, 7), (self.rec, False))  # 640 kB
        self.a.NTFY_MAX_ATTACH = 100_000
        self.assertEqual(self.a.ntfy_attachment(self.rec, self.clip, self.tmp, 7), (self.clip, True))
        self.a.NTFY_MAX_ATTACH = 1_000
        self.assertEqual(self.a.ntfy_attachment(self.rec, self.clip, self.tmp, 7), (None, False))

    def test_notify_recording(self):
        """A whole sending to a local server: the preview and its note when the recording is too big."""
        a = self.a
        server = http.server.HTTPServer(("127.0.0.1", 0), Ntfy)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        Ntfy.got = []
        a.NTFY_MAX_ATTACH = 100_000
        a.to_mp3 = lambda wav, out: None
        settings = a.load_settings()
        try:
            a.save_settings(dict(settings, ntfy={"enabled": True, "attach": True,
                                                 "url": "http://127.0.0.1:%d/topic" % server.server_port}))
            store = a.Store()
            did = store.q("INSERT INTO detections (scan_id, freq, mode, label, first_seen, last_seen, hits, snr, "
                          "score, kind, audio, recording, rec_s) VALUES (0, 145.5e6, 'NFM', '2 m', 0, 0, 1, 20, 1.5, "
                          "'voice', ?, ?, 20)", (self.clip, self.rec), True)
            a.notify_recording(store, did)
        finally:
            a.save_settings(settings)
            server.shutdown()
            server.server_close()
        self.assertIsNone(a.NTFY_LAST.get("error"))
        method, path, body = Ntfy.got[0]
        self.assertEqual(method, "PUT")
        self.assertIn("filename=clip.wav", path)
        with open(self.clip, "rb") as f:
            self.assertEqual(body, f.read())


if __name__ == "__main__":
    unittest.main()
