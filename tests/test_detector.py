"""The detector on synthetic captures: what the survey spots, what the listen calls speech. The verdicts
are fixed; the numbers (score, SNR, frequency) are compared with tests/baseline.json within a margin, so
a change of the signal processing that moves them is seen. After a deliberate change:
python3 -m tests.test_detector --update-baseline (then look at the diff of baseline.json)."""
import json
import os
import sys
import unittest

import numpy as np

from tests import support
from tests.support import Emitter, Scene, app, capture

TUNED = 100e6
LO, HI = TUNED + 50e3, TUNED + 1.05e6       # a listening window, as listen_windows makes them
BASELINE = os.path.join(os.path.dirname(__file__), "baseline.json")


def scenes():
    """name → (band mode, emitters, expected verdict of the strongest signal: True speech, False not
    speech, None no signal at all)."""
    f = TUNED + 300e3
    return {
        "nfm_speech": ("NFM", [Emitter(f, "nfm", audio=support.speech(10))], True),
        "nfm_speech_moderate": ("NFM", [Emitter(f, "nfm", audio=support.speech(10, seed=4), level=0.04)], True),
        "am_speech": ("AM", [Emitter(f, "am", audio=support.speech(10, seed=5), level=0.2)], True),
        "usb_speech": ("USB", [Emitter(f, "usb", audio=support.speech(10, seed=6), level=0.15)], True),
        "lsb_speech": ("LSB", [Emitter(f, "lsb", audio=support.speech(10, seed=8), level=0.15)], True),
        "nfm_music": ("NFM", [Emitter(f, "nfm", audio=support.music(10))], False),
        "carrier": ("NFM", [Emitter(f, "carrier")], False),
        "wide": ("NFM", [Emitter(TUNED + 500e3, "wide", level=0.1)], False),
        "burst": ("NFM", [Emitter(f, "carrier", start_s=0.5, stop_s=0.8)], None),
        "noise": ("NFM", [], None),
        "two_speakers": ("NFM", [Emitter(f, "nfm", audio=support.speech(10, seed=9)),
                                 Emitter(TUNED + 700e3, "nfm", audio=support.speech(10, seed=10), level=0.06)],
                         True),
    }


def run_scene(name, seconds=2.5, rate=support.FS):
    a = app()
    mode, emitters, _ = scenes()[name]
    iq = capture(Scene(emitters), TUNED, seconds, rate=rate)
    det = a.Detector(8.0)
    band = a.Band(LO, HI, name, mode, "test")
    _, cands = det.survey(iq[:int(rate * 0.1)], TUNED, LO, HI, rate)
    _, signals = det.analyze(iq, TUNED, LO, HI, band, rate)
    return cands, signals


def summary(cands, signals):
    return {"candidates": [[round(f - TUNED), round(d, 1)] for f, d in cands],
            "signals": [{"offset": round(s["freq"] - TUNED), "voice": bool(s["voice"]), "score": round(s["score"], 2),
                         "snr": round(s["snr"], 1), "demod": s["demod"], "width": round(s["width"])}
                        for s in sorted(signals, key=lambda s: s["freq"])]}


class Scenes(unittest.TestCase):
    """Each synthetic scene through survey + analyze, as a listen does it."""

    @classmethod
    def setUpClass(cls):
        cls.results = {name: run_scene(name) for name in scenes()}
        try:
            cls.baseline = json.load(open(BASELINE, encoding="utf-8"))
        except OSError:
            cls.baseline = {}

    def test_verdicts(self):
        for name, (_, emitters, verdict) in scenes().items():
            with self.subTest(scene=name):
                cands, signals = self.results[name]
                if verdict is None:
                    self.assertEqual(signals, [])
                    continue
                self.assertTrue(signals)
                strongest = max(signals, key=lambda s: s["snr"])
                self.assertEqual(strongest["voice"], verdict, strongest.get("reason"))
                self.assertAlmostEqual(strongest["peak" if "peak" in strongest else "freq"], emitters[0].freq,
                                       delta=4000)

    def test_demodulation_chosen(self):
        for name, demod in (("nfm_speech", "fm"), ("am_speech", "am"), ("usb_speech", "ssb"), ("lsb_speech", "ssb")):
            with self.subTest(scene=name):
                self.assertEqual(self.results[name][1][0]["demod"], demod)

    def test_ssb_carrier_beside_the_energy(self):
        usb = self.results["usb_speech"][1][0]
        lsb = self.results["lsb_speech"][1][0]
        self.assertLess(usb["freq"], usb["peak"])     # the suppressed carrier is below an upper sideband
        self.assertGreater(lsb["freq"], lsb["peak"])

    def test_two_speakers(self):
        signals = self.results["two_speakers"][1]
        self.assertEqual(len(signals), 2)
        self.assertTrue(all(s["voice"] for s in signals))

    def test_survey(self):
        for name in ("nfm_speech", "am_speech", "carrier"):
            with self.subTest(scene=name):
                cands = self.results[name][0]
                self.assertEqual(len(cands), 1)
                self.assertAlmostEqual(cands[0][0], TUNED + 300e3, delta=2500)
                self.assertGreater(cands[0][1], 8.0)
        for name in ("wide", "noise", "burst"):
            with self.subTest(scene=name):
                self.assertEqual(self.results[name][0], [])

    def test_wide_signal_reason(self):
        sig = self.results["wide"][1][0]
        self.assertGreater(sig["width"], app().MAX_WIDTH_HZ)
        self.assertFalse(sig["voice"])

    def test_capture_audio(self):
        """Every kept signal carries its capture (16 kHz audio, silent outside the transmission)."""
        sig = self.results["nfm_speech"][1][0]
        self.assertEqual(sig["audio"].dtype, np.float32)
        self.assertAlmostEqual(len(sig["audio"]) / (2 * app().AUDIO_HALF_BW), 2.5, delta=0.05)
        self.assertLessEqual(float(np.abs(sig["audio"]).max()), 0.9 + 1e-6)

    def test_against_baseline(self):
        if not self.baseline:
            self.skipTest("no tests/baseline.json")
        for name in scenes():
            with self.subTest(scene=name):
                want, got = self.baseline[name], summary(*self.results[name])
                self.assertEqual(len(got["candidates"]), len(want["candidates"]))
                for g, w in zip(got["candidates"], want["candidates"]):
                    self.assertAlmostEqual(g[0], w[0], delta=1500)
                    self.assertAlmostEqual(g[1], w[1], delta=2.0)
                self.assertEqual(len(got["signals"]), len(want["signals"]))
                for g, w in zip(got["signals"], want["signals"]):
                    self.assertEqual((g["voice"], g["demod"]), (w["voice"], w["demod"]))
                    self.assertAlmostEqual(g["offset"], w["offset"], delta=1500)
                    self.assertAlmostEqual(g["snr"], w["snr"], delta=2.0)
                    self.assertAlmostEqual(g["score"], w["score"], delta=max(0.15, 0.2 * w["score"]))
                    self.assertAlmostEqual(g["width"], w["width"], delta=2500)


class OtherRates(unittest.TestCase):
    """Receivers that cannot do 2.4 MS/s (Airspy: 2.5, 3, 6, 10 MS/s): the same verdicts, the same
    frequencies, the scores close to those at 2.4 MS/s."""

    def test_verdicts_at_other_rates(self):
        base = {name: run_scene(name)[1] for name in ("nfm_speech", "usb_speech", "nfm_music", "wide")}
        for rate in (2_500_000, 3_000_000, 6_000_000):
            for name, ref in base.items():
                with self.subTest(rate=rate, scene=name):
                    cands, signals = run_scene(name, rate=rate)
                    self.assertEqual(len(signals), len(ref))
                    s, r = signals[0], ref[0]
                    self.assertEqual((s["voice"], s["demod"]), (r["voice"], r["demod"]))
                    self.assertAlmostEqual(s["freq"], r["freq"], delta=2000)
                    self.assertAlmostEqual(s["score"], r["score"], delta=max(0.2, 0.2 * r["score"]))
                    self.assertAlmostEqual(len(s["audio"]) / (2 * app().AUDIO_HALF_BW), 2.5, delta=0.05)

    def test_grid_at_the_reference_rate(self):
        """At 2.4 MS/s the widths in Hz give back the bins the detection was tuned with."""
        g = app().Grid.of(support.FS)
        self.assertEqual((g.nfft, g.smooth, g.floor, g.sep), (2048, 5, 128, 5))


class Progressive(unittest.TestCase):
    """analyze() is called again on a growing capture during a listen: the verdict must hold from 1 s on
    for clear speech, and analyze must stay free of side effects."""

    def test_growing_capture(self):
        a = app()
        mode, emitters, _ = scenes()["nfm_speech"]
        iq = capture(Scene(emitters), TUNED, 2.5)
        det = a.Detector(8.0)
        band = a.Band(LO, HI, "t", mode, "test")
        for seconds in (1.0, 1.5, 2.0, 2.5):
            _, signals = det.analyze(iq[:int(support.FS * seconds)], TUNED, LO, HI, band)
            self.assertEqual(len(signals), 1)
            if seconds >= a.LISTEN_VOICE_S:
                self.assertTrue(signals[0]["voice"], "%.1f s" % seconds)
        self.assertEqual((det.continuous, det.ignored, det.quiet), ({}, set(), {}))


class Stations(unittest.TestCase):
    def test_fm_broadcast(self):
        a = app()
        tuned = 99.0e6
        lo, hi = tuned + 50e3, tuned + 1.05e6
        emitters = [Emitter(99.3e6, "wfm", audio=support.music(10), deviation=60_000, level=0.3),
                    Emitter(99.8e6, "wfm", audio=support.music(10, seed=3), deviation=60_000, level=0.2)]
        iq = capture(Scene(emitters), tuned, 2.5)
        _, found = a.Detector(8.0).analyze(iq, tuned, lo, hi, a.Band(lo, hi, "FM", "WFM", "test"))
        self.assertEqual(sorted(s["freq"] for s in found), [99.3e6, 99.8e6])
        for s in found:
            self.assertTrue(s["station"])
            self.assertEqual(s["audio"].dtype, np.float32)


class Memory(unittest.TestCase):
    """What the detector remembers between listens: continuous carriers, muting, bans, whitelist."""

    def sig(self, freq=145.5e6, voice=False, occupancy=1.0, key=True, **kw):
        s = {"freq": freq, "voice": voice, "occupancy": occupancy, "continuous": False}
        if key:
            s["key"] = int(round(freq / 6250))
        s.update(kw)
        return s

    def test_continuous_carrier_after_three_listens(self):
        a = app()
        det = a.Detector()
        for _ in range(a.CONT_VISITS - 1):
            det.track([self.sig()])
        self.assertFalse(det.ignored)
        det.track([self.sig()])
        self.assertIn(int(round(145.5e6 / 6250)), det.ignored)
        det.track([self.sig(voice=True)])          # speech: not a carrier after all
        self.assertFalse(det.ignored)

    def test_muting(self):
        a = app()
        det = a.Detector()
        det.after_listen([self.sig(occupancy=0.5)], passes=4)
        self.assertTrue(det.is_quiet(145.5e6, 4 + a.QUIET_PASSES[0] - 1))
        self.assertFalse(det.is_quiet(145.5e6, 4 + a.QUIET_PASSES[0]))
        self.assertTrue(det.is_quiet(145.5e6 + 6250, 4))           # ±1 key
        det.after_listen([self.sig(occupancy=1.0, continuous=True)], passes=4)
        self.assertTrue(det.is_quiet(145.5e6, 4 + a.QUIET_PASSES[2] - 1))
        det.after_listen([self.sig(voice=True)], passes=5)
        self.assertFalse(det.is_quiet(145.5e6, 5))

    def test_rules(self):
        a = app()
        det = a.Detector()
        self.assertFalse(det.banned(145.5e6) or det.whitelisted(145.5e6))
        det.rules = type("Rules", (), {"banned": lambda self, f: f == 1.0, "whitelisted": lambda self, f: f == 2.0})()
        self.assertTrue(det.banned(1.0))
        self.assertTrue(det.whitelisted(2.0))


def update_baseline():
    out = {name: summary(*run_scene(name)) for name in scenes()}
    with open(BASELINE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, sort_keys=True)
        f.write("\n")
    print("wrote", BASELINE)


if __name__ == "__main__":
    if "--update-baseline" in sys.argv:
        update_baseline()
    else:
        unittest.main()
