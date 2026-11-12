"""Recordings: the retention (old audio deleted at start), the squelch during a recording (off: the pauses
as heard, on: zeros) and the new-activity alert (a chime, then the preview)."""
import os
import shutil
import tempfile
import time
import unittest
import wave

import numpy as np

from tests.support import FS, app

RATE = 16_000
STEP = RATE // 10                     # one 100 ms frame of audio


def frames(path):
    with wave.open(path) as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2")


class Retention(unittest.TestCase):
    def setUp(self):
        self.a = app()
        self.tmp = tempfile.mkdtemp()
        self.store = self.a.Store(os.path.join(self.tmp, "scanner.db"))

    def tearDown(self):
        self.store.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def detection(self, days_ago, name):
        paths = []
        for kind in ("clip", "rec"):
            paths.append(os.path.join(self.tmp, "%s-%s.wav" % (name, kind)))
            self.a.write_wav(paths[-1], np.zeros(STEP))
        seen = time.time() - days_ago * 86400
        did = self.store.q("INSERT INTO detections (scan_id, freq, mode, label, first_seen, last_seen, hits, snr, "
                           "score, kind, audio, recording, rec_s) VALUES (0, 145.5e6, 'NFM', '2 m', ?, ?, 1, 20, "
                           "1.5, 'voice', ?, ?, 1)", (seen, seen, paths[0], paths[1]), True)
        return did, paths

    def test_purge(self):
        old, old_paths = self.detection(40, "old")
        new, new_paths = self.detection(5, "new")
        self.store.q("INSERT INTO freq_rules (key, freq, audio) VALUES (1, 145.5e6, ?)", (old_paths[0],), True)
        self.store.request_transcript(old)
        self.assertEqual(self.store.purge(0), 0)                 # 0: kept for good
        self.assertTrue(all(os.path.exists(p) for p in old_paths))
        self.assertEqual(self.store.purge(30), 2)
        self.assertFalse(any(os.path.exists(p) for p in old_paths))
        self.assertTrue(all(os.path.exists(p) for p in new_paths))
        rows = dict((r[0], r[1:]) for r in self.store.q("SELECT id, audio, recording, rec_s FROM detections"))
        self.assertEqual(rows[old], (None, None, 1))               # the row stays, its audio goes
        self.assertEqual(rows[new][:2], tuple(new_paths))
        self.assertIsNone(self.store.q("SELECT audio FROM freq_rules")[0][0])
        self.assertIsNone(self.store.next_transcript())           # nothing left to transcribe
        self.assertEqual(self.store.purge(30), 0)

    def test_default(self):
        settings = self.a.load_settings()
        try:
            self.a.save_settings({})
            self.assertEqual(self.a.recording_conf(), (30, False, False))
            self.a.save_settings({"retention_days": "x", "record_squelch": True, "preview_alert": True})
            self.assertEqual(self.a.recording_conf(), (30, True, True))
        finally:
            self.a.save_settings(settings)


class Squelch(unittest.TestCase):
    def setUp(self):
        self.a = app()
        self.tmp = tempfile.mkdtemp()
        self.store = self.a.Store(os.path.join(self.tmp, "scanner.db"))
        self.settings, self.dir = self.a.load_settings(), self.a.RECORDINGS_DIR
        self.a.RECORDINGS_DIR = self.tmp

    def tearDown(self):
        self.a.save_settings(self.settings)
        self.a.RECORDINGS_DIR = self.dir
        self.store.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def record(self, squelch, on):
        """A recording fed one second of noise whose frames are on (above the threshold) or not."""
        self.a.save_settings({"record_squelch": squelch})
        start = np.full(STEP, 0.5)
        sig = {"id": len(on) + 10 * squelch, "freq": 0.0, "demod": "am", "gain": 1.0,
               "audio": np.concatenate([start, np.zeros(STEP)]), "audio_open": start}
        rec = self.a.Recording(self.store, sig, 10)
        iq = (np.random.default_rng(1).standard_normal((FS, 2)) @ [1, 1j]).astype(np.complex64)
        freqs = np.linspace(-100_000, 100_000, 201)
        P = np.where(np.array(on, bool)[:, None], 1000.0, 1.0) * np.ones((len(on), len(freqs)))
        rec.feed(iq, 0.0, freqs, P, np.ones(len(on)), FS)
        rec.close()
        return frames(rec.path)[STEP:]                # after the capture that started it

    def test_pause(self):
        on = [1, 1, 0, 0, 0, 0, 0, 1, 1, 1]           # a pause longer than the hang time
        with_squelch, without = self.record(True, on), self.record(False, on)
        self.assertEqual(len(with_squelch), 10 * STEP)
        self.assertEqual(len(without), 10 * STEP)
        pause = slice(2 * STEP, 7 * STEP)
        self.assertFalse(with_squelch[pause].any())             # zeros
        self.assertGreater(np.count_nonzero(without[pause]), 4 * STEP)    # the audio as heard

    def test_end(self):
        on = [1, 1, 0, 0, 0, 0, 0, 0, 0, 0]
        self.assertEqual(len(self.record(True, on)), 2 * STEP)             # the final silence goes
        self.assertEqual(len(self.record(False, on)), 2 * STEP + 8 * STEP)  # up to REC_TAIL_S of it stays
        self.assertEqual(self.a.REC_TAIL_S, 1.0)


class Alert(unittest.TestCase):
    def test_chime_then_preview(self):
        a = app()
        preview = np.linspace(-0.5, 0.5, 2 * RATE)
        out = a.alert_audio(preview, RATE)
        chime = int(a.ALERT_TONE_S * RATE)
        self.assertEqual(len(out), chime + int(a.ALERT_GAP_S * RATE) + len(preview))
        np.testing.assert_array_equal(out[-len(preview):], preview)
        self.assertLessEqual(np.abs(out[:chime]).max(), 1.0)
        self.assertGreater(np.abs(out[:chime]).max(), 0.3)
        self.assertLess(abs(out[0]), 0.01)                     # no click


if __name__ == "__main__":
    unittest.main()
