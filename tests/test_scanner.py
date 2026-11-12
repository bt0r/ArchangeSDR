"""The scanner end to end with fake receivers: sweep plan, survey, listen, capture, recording, history."""
import os
import threading
import unittest
import wave

from tests import support
from tests.support import Emitter, FakeSdr, Scene, app


class Plan(unittest.TestCase):
    def test_narrow_range_one_hop_above_it(self):
        a = app()
        hops = list(a.Band(446.0e6, 446.2e6, "PMR", "NFM", "s").hops())
        self.assertEqual(hops, [(446.2e6 + a.DC_GAP, 446.0e6, 446.2e6, False)])

    def test_wide_range_hops_tile_without_overlap(self):
        a = app()
        band = a.Band(144e6, 150e6, "2 m", "NFM", "s")
        hops = list(band.hops())
        self.assertGreater(len(hops), 2)
        self.assertEqual(hops[0][1], band.lo)
        self.assertEqual(hops[-1][2], band.hi)
        for (c, lo, hi, wide), nxt in zip(hops, hops[1:]):
            self.assertTrue(wide)
            self.assertEqual(hi, nxt[1])                       # own intervals touch, never overlap
            self.assertLessEqual(c - a.SURVEY_HALF, lo)        # the capture holds the interval
            self.assertGreaterEqual(c + a.SURVEY_HALF, hi)

    def test_dc_shift_alternates(self):
        a = app()
        h = {"c": 145e6, "wide": True, "visits": 0}
        self.assertEqual(a.ScanState.tuned(h), 145e6)
        h["visits"] = 1
        self.assertEqual(a.ScanState.tuned(h), 145e6 - 50_000)

    def test_listen_windows(self):
        a = app()
        wins = a.listen_windows(144e6, 146e6, [144.1e6, 144.5e6, 145.3e6])
        self.assertEqual([w[2] for w in wins], [[144.1e6, 144.5e6], [145.3e6]])
        for lo, hi, group in wins:
            self.assertLessEqual(hi - lo, a.WINDOW)
            self.assertTrue(all(lo <= f < hi for f in group))
        self.assertEqual(a.listen_windows(144e6, 144.05e6, [144.04e6])[0][:2], (144.01e6, 144.05e6))

    def test_pick_by_coverage_and_visits(self):
        a = app()
        hf = a.Band(14.0e6, 14.35e6, "20 m", "USB", "s")
        vhf = a.Band(145.0e6, 145.5e6, "2 m", "NFM", "s")
        st = a.ScanState([vhf, hf])
        st.register("v4", [(0.5e6, 1766e6)])
        st.register("r820t", [(24e6, 1766e6)])
        self.assertEqual(st.reachable("r820t"), [0])
        self.assertEqual(st.pick("v4"), 1)          # what only it reaches goes first
        self.assertEqual(st.pick("r820t"), 0)
        self.assertIsNone(st.pick("v4"))           # the other hop is claimed
        st.release(1, True)
        st.release(0, True)
        self.assertEqual(st.passes, 1)
        st.max_passes = 1
        self.assertIs(st.pick("v4"), False)


class EndToEnd(unittest.TestCase):
    """A whole scan pass on fake receivers; RtlSdr and the 20 s recording silence are replaced for the
    test's duration."""

    def setUp(self):
        self.a = a = app()
        self.saved = (a.RtlSdr, a.RECORD_SILENCE_S, a.CLIPS_DIR, a.RECORDINGS_DIR)
        a.RECORD_SILENCE_S = 2.0
        # a history of its own (a recording file of the same id is appended to: a conversation heard again)
        home = os.path.join(a.TEST_HOME, self.id().rsplit(".", 1)[-1])
        a.CLIPS_DIR, a.RECORDINGS_DIR = os.path.join(home, "clips"), os.path.join(home, "recordings")
        self.store = a.Store(os.path.join(home, "scanner.db"))

    def tearDown(self):
        self.a.RtlSdr, self.a.RECORD_SILENCE_S, self.a.CLIPS_DIR, self.a.RECORDINGS_DIR = self.saved
        self.store.db.close()

    def use(self, *fakes):
        by_index = {i: f for i, f in enumerate(fakes)}
        self.a.RtlSdr = lambda index, gain, async_ok=True, hf=None: by_index[index]

    def device(self, index, dev_id):
        return {"id": dev_id, "index": index, "label": dev_id, "gain": None, "hf": None}

    def test_speech_is_detected_captured_and_recorded(self):
        a = self.a
        talk = Emitter(145.5e6, "nfm", audio=support.speech(20, seed=11), start_s=0, stop_s=6)
        fake = FakeSdr(Scene([talk, Emitter(145.2e6, "carrier")]))
        self.use(fake)
        events = {"on_window": [], "on_record": [], "on_hit": [], "on_end": []}
        cbs = {k: (lambda k: lambda *args: events[k].append(args))(k) for k in events}
        st = a.ScanState([a.Band(145.0e6, 146.0e6, "2 m", "NFM", "s")], max_passes=1)
        sc = a.Scanner(st, self.store, self.device(0, "fake"), cbs)
        sc.run()

        self.assertTrue(fake.closed)
        self.assertEqual(events["on_end"], [("fake", None, False)])
        rows = self.store.q("SELECT id, freq, kind, audio, recording, rec_s, device, params FROM detections")
        voice = [r for r in rows if abs(r[1] - 145.5e6) < 5000]
        self.assertEqual(len(voice), 1, rows)
        did, freq, kind, clip, recording, rec_s, device, params = voice[0]
        self.assertEqual(device, "fake")
        self.assertTrue(clip and os.path.isfile(clip))
        self.assertTrue(recording and os.path.isfile(recording))
        with wave.open(recording) as w:
            self.assertEqual(w.getframerate(), 2 * a.AUDIO_HALF_BW)
            seconds = w.getnframes() / w.getframerate()
        # the talk lasts 6 s from the start of the scan; the survey and the listen took the first ~2.6 s;
        # without the squelch (the default) up to REC_TAIL_S after the last word is kept
        self.assertGreater(seconds, 2.0)
        self.assertLess(seconds, 6.5 + a.REC_TAIL_S)
        self.assertAlmostEqual(rec_s, seconds, delta=0.1)
        self.assertTrue(any(hit[1]["voice"] for hit in events["on_hit"]))
        self.assertTrue(events["on_record"][-1][-1])            # the recording was closed
        # the carrier was heard, kept as interference, not as speech
        carrier = [r for r in rows if abs(r[1] - 145.2e6) < 5000]
        self.assertEqual(len(carrier), 1)
        self.assertTrue(carrier[0][3] and os.path.isfile(carrier[0][3]))
        scans = self.store.q("SELECT passes, error FROM scans")
        self.assertEqual(scans, [(1, None)])

    def test_receiver_at_another_rate(self):
        """A receiver at 2.5 MS/s (Airspy R2) finds, captures and records the same conversation."""
        a = self.a
        talk = Emitter(145.5e6, "nfm", audio=support.speech(20, seed=11), start_s=0, stop_s=6)
        fake = FakeSdr(Scene([talk]), rate=2_500_000)
        self.use(fake)
        st = a.ScanState([a.Band(145.0e6, 146.0e6, "2 m", "NFM", "s")], max_passes=1)
        a.Scanner(st, self.store, self.device(0, "airspy")).run()
        rows = self.store.q("SELECT freq, recording, params FROM detections WHERE kind = 'voice'")
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0][0], 145.5e6, delta=5000)
        self.assertIn('"rate": 2500000', rows[0][2])
        with wave.open(rows[0][1]) as w:
            self.assertEqual(w.getframerate(), 2 * a.AUDIO_HALF_BW)
            self.assertGreater(w.getnframes() / w.getframerate(), 2.0)

    def test_nothing_on_the_air(self):
        a = self.a
        fake = FakeSdr(Scene([]))
        self.use(fake)
        st = a.ScanState([a.Band(145.0e6, 150.0e6, "2 m", "NFM", "s")], max_passes=2)
        a.Scanner(st, self.store, self.device(0, "fake")).run()
        self.assertEqual(self.store.q("SELECT COUNT(*) FROM detections"), [(0,)])
        self.assertEqual(st.passes, 2)
        self.assertEqual(len(fake.tunes), 2 * len(st.hops))      # survey only, no listen

    def test_two_receivers_share_the_plan(self):
        a = self.a
        scene = Scene([Emitter(14.2e6, "usb", audio=support.speech(20, seed=12), level=0.15, stop_s=3),
                       Emitter(145.5e6, "nfm", audio=support.speech(20, seed=13), stop_s=3)])
        hf = FakeSdr(scene, name="HF", coverage=[(0.5e6, 1766e6)])
        vhf = FakeSdr(scene, name="VHF", coverage=[(24e6, 1766e6)])
        self.use(hf, vhf)
        st = a.ScanState([a.Band(14.0e6, 14.35e6, "20 m", "USB", "s"), a.Band(144e6, 148e6, "2 m", "NFM", "s")],
                         max_passes=1)
        scanners = [a.Scanner(st, self.store, self.device(0, "hf")), a.Scanner(st, self.store, self.device(1, "vhf"))]
        for sc in scanners:
            sc.start()
        for sc in scanners:
            sc.join(120)
            self.assertFalse(sc.is_alive())
        self.assertEqual(st.passes, 1)
        self.assertTrue(all(f >= 24e6 for f in vhf.tunes))
        self.assertTrue(any(f < 24e6 for f in hf.tunes))             # only it reaches 20 m
        rows = {r[0]: r[1] for r in self.store.q("SELECT device, freq FROM detections WHERE kind = 'voice'")}
        self.assertIn("hf", rows)
        self.assertAlmostEqual(rows["hf"], 14.2e6, delta=5000)

    def test_stop_ends_the_scan(self):
        a = self.a
        fake = FakeSdr(Scene([]))
        self.use(fake)
        st = a.ScanState([a.Band(144e6, 148e6, "2 m", "NFM", "s")])        # no max_passes: endless
        sc = a.Scanner(st, self.store, self.device(0, "fake"))
        timer = threading.Timer(0.5, sc.stop)
        timer.start()
        sc.run()
        timer.cancel()
        self.assertTrue(fake.closed)
        self.assertGreater(st.passes, 0)


if __name__ == "__main__":
    unittest.main()
