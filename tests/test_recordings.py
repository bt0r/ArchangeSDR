"""Recordings: the retention (old audio deleted at start), the squelch during a recording (off: the pauses
as heard, on: zeros), the two files of a recording (raw, and clean: voice band, NFM de-emphasis) and the
new-activity alert (a chime, then the preview)."""
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

    def test_purge_both_files(self):
        """A recording is two files: the raw one, next to the clean one the row points to, goes too."""
        clean = os.path.join(self.tmp, "7_clean.wav")
        raw = os.path.join(self.tmp, "7_raw.wav")
        for path in (clean, raw):
            self.a.write_wav(path, np.zeros(STEP))
        seen = time.time() - 40 * 86400
        self.store.q("INSERT INTO detections (scan_id, freq, mode, label, first_seen, last_seen, hits, snr, score, "
                     "kind, recording, rec_s) VALUES (0, 145.5e6, 'NFM', '2 m', ?, ?, 1, 20, 1.5, 'voice', ?, 1)",
                     (seen, seen, clean), True)
        self.assertEqual(self.store.purge(30), 2)
        self.assertFalse(os.path.exists(clean) or os.path.exists(raw))

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


class ManualBan(unittest.TestCase):
    def test_ban(self):
        """A frequency banned by hand: banned for the scan, off the whitelist, in the Interference tab."""
        a = app()
        tmp = tempfile.mkdtemp()
        try:
            store = a.Store(os.path.join(tmp, "scanner.db"))
            rules = store.rules
            rules.set_whitelisted(145.5e6, True, "2 m", "NFM")
            rules.ban(145.5e6, "2 m", "NFM", "marked as interference")
            self.assertTrue(rules.banned(145.5e6))
            self.assertTrue(rules.banned(145.5e6 + 6250))           # the neighbouring key too
            self.assertFalse(rules.whitelisted(145.5e6))
            self.assertFalse(rules.banned(145.6e6))
            row = store.q("SELECT label, mode, banned IS NOT NULL, whitelisted, reason FROM freq_rules")
            self.assertEqual(row, [("2 m", "NFM", 1, None, "marked as interference")])
            self.assertTrue(a.FreqRules(store).banned(145.5e6))      # kept across restarts
            store.db.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


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
        return frames(rec.raw)[STEP:]                 # after the capture that started it

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


class Clean(unittest.TestCase):
    """Each recording is written twice: <id>_raw.wav as demodulated, <id>_clean.wav through the voice band
    (300 - 3000 Hz) and, in NFM, the de-emphasis. Same length, aligned; the log plays the clean one, the
    transcription takes the raw one (whisper-cli does worse on the filtered audio)."""

    def setUp(self):
        self.a = app()
        self.tmp = tempfile.mkdtemp()
        self.store = self.a.Store(os.path.join(self.tmp, "scanner.db"))
        self.settings, self.dir = self.a.load_settings(), self.a.RECORDINGS_DIR
        self.a.RECORDINGS_DIR = self.tmp
        self.a.save_settings({"record_squelch": False})

    def tearDown(self):
        self.a.save_settings(self.settings)
        self.a.RECORDINGS_DIR = self.dir
        self.store.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def record(self, did, audio, demod="am"):
        """A recording made of the capture's audio alone (no block fed after it)."""
        sig = {"id": did, "freq": 0.0, "demod": demod, "gain": 1.0, "audio": audio, "audio_open": audio}
        rec = self.a.Recording(self.store, sig, 10)
        rec.close()
        return rec

    @staticmethod
    def tone(hz, seconds=1.0, level=0.5):
        return level * np.sin(2 * np.pi * hz * np.arange(int(seconds * RATE)) / RATE)

    @staticmethod
    def level_db(x):
        x = x[RATE // 5:-RATE // 5]                           # away from the edges
        return 10 * np.log10(np.mean(x.astype(float) ** 2) + 1e-12)

    def test_two_files(self):
        rec = self.record(1, self.tone(1000))
        self.assertEqual(rec.path, os.path.join(self.tmp, "1_clean.wav"))
        self.assertEqual(rec.raw, os.path.join(self.tmp, "1_raw.wav"))
        raw, clean = frames(rec.raw), frames(rec.path)
        self.assertEqual(len(raw), RATE)
        self.assertEqual(len(clean), len(raw))
        self.assertEqual(sorted(os.listdir(self.tmp)), ["1_clean.wav", "1_raw.wav", "scanner.db"])

    def test_voice_band(self):
        for hz, kept in ((100, False), (1000, True), (2000, True), (6000, False)):
            raw = frames(self.record(hz, self.tone(hz)).raw)
            clean = frames(self.record(hz + 1, self.tone(hz)).path)
            drop = self.level_db(raw) - self.level_db(clean)
            if kept:
                self.assertLess(abs(drop), 1.5, hz)
            else:
                self.assertGreater(drop, 20, hz)

    def test_aligned(self):
        """The FIR's delay is taken off: a click is at the same place in both files."""
        x = np.zeros(RATE)
        x[RATE // 2] = 0.9
        rec = self.record(1, x)
        self.assertEqual(np.argmax(np.abs(frames(rec.path))), np.argmax(np.abs(frames(rec.raw))))

    def test_nfm_deemphasis(self):
        """FM is transmitted with its treble raised: the clean NFM file brings 2.5 kHz down, AM keeps it."""
        am = self.level_db(frames(self.record(1, self.tone(2500)).path))
        fm = self.level_db(frames(self.record(2, self.tone(2500), "fm").path))
        self.assertGreater(am - fm, 6)
        self.assertLess(abs(self.level_db(frames(self.record(3, self.tone(1000), "fm").path)) -
                            self.level_db(frames(self.record(4, self.tone(1000)).path))), 1.5)

    def test_appended(self):
        """A conversation heard again is appended to both files, which stay the same length."""
        self.record(1, self.tone(1000))
        rec = self.record(1, self.tone(1000))
        self.assertEqual(len(frames(rec.path)), len(frames(rec.raw)))
        self.assertEqual(len(frames(rec.raw)), 2 * RATE + int(self.a.REC_GAP_S * RATE))

    def test_older_recording(self):
        """A recording made before the clean copy (<id>.wav) heard again: it becomes the start of both."""
        old = os.path.join(self.tmp, "1.wav")
        self.a.write_wav(old, self.tone(1000))
        rec = self.record(1, self.tone(1000))
        self.assertFalse(os.path.exists(old))
        self.assertEqual(len(frames(rec.path)), len(frames(rec.raw)))
        self.assertEqual(len(frames(rec.raw)), 2 * RATE + int(self.a.REC_GAP_S * RATE))

    def test_raw_for_transcription(self):
        rec = self.record(1, self.tone(1000))
        self.assertEqual(self.a.raw_recording(rec.path), rec.raw)
        old = os.path.join(self.tmp, "9.wav")                   # an older recording: its only file
        self.assertEqual(self.a.raw_recording(old), old)
        self.assertIsNone(self.a.raw_recording(None))


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
