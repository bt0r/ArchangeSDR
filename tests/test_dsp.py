"""The small signal-processing helpers, on hand-made inputs."""
import unittest

import numpy as np

from tests import support
from tests.support import AUDIO_RATE, app


class Helpers(unittest.TestCase):
    def setUp(self):
        self.a = app()

    def test_longest_run(self):
        self.assertEqual(self.a.longest_run([0, 1, 1, 0, 1, 1, 1, 0]), 3)
        self.assertEqual(self.a.longest_run([]), 0)

    def test_fill_gaps(self):
        got = self.a.fill_gaps(np.array([1, 0, 0, 1, 0, 0, 0, 0, 1], bool), 2)
        self.assertEqual(got.astype(int).tolist(), [1, 1, 1, 1, 0, 0, 0, 0, 1])

    def test_run_bounds(self):
        self.assertEqual(self.a.run_bounds([0, 1, 1, 0, 1, 1, 1]), (4, 7))
        self.assertEqual(self.a.run_bounds([0, 0]), (0, 0))

    def test_local_floor_ignores_a_narrow_peak(self):
        p = np.ones(2048)
        p[1000:1004] = 1000.0
        floor = self.a.local_floor(p)
        self.assertEqual(len(floor), 2048)
        self.assertAlmostEqual(float(floor[1002]), 1.0, places=6)

    def test_local_floor_follows_the_roll_off(self):
        p = np.concatenate([np.full(256, 0.1), np.ones(1536), np.full(256, 0.1)])
        floor = self.a.local_floor(p)
        self.assertLess(floor[10], 0.2)
        self.assertGreater(floor[1000], 0.9)


class Demodulation(unittest.TestCase):
    def setUp(self):
        self.a = app()
        self.t = np.arange(AUDIO_RATE) / AUDIO_RATE
        self.tone = np.sin(2 * np.pi * 700 * self.t)

    def dominant(self, audio):
        spec = np.abs(np.fft.rfft(audio))
        return np.fft.rfftfreq(len(audio), 1 / AUDIO_RATE)[spec.argmax()]

    def test_fm(self):
        phase = 2 * np.pi * 3000 * np.cumsum(self.tone) / AUDIO_RATE
        audio = self.a.demodulate(np.exp(1j * phase), "fm", AUDIO_RATE)
        self.assertEqual(audio.dtype, np.float32)
        self.assertAlmostEqual(self.dominant(audio), 700, delta=2)

    def test_am(self):
        audio = self.a.demodulate((1 + 0.5 * self.tone) * np.exp(1j * 0.3), "am", AUDIO_RATE)
        self.assertAlmostEqual(self.dominant(audio), 700, delta=2)

    def test_ssb(self):
        audio = self.a.demodulate(np.exp(2j * np.pi * 700 * self.t), "ssb", AUDIO_RATE)
        self.assertAlmostEqual(self.dominant(audio), 700, delta=2)


class VoiceFeatures(unittest.TestCase):
    """The four speech criteria separate speech from a tone and from noise."""

    def setUp(self):
        self.a = app()

    def score(self, audio):
        dyn, mod, band, voiced = self.a.voice_features(audio, AUDIO_RATE)
        a = self.a
        return min(dyn / a.VOICE_DYN_DB, mod / a.VOICE_MOD_RATIO, band / a.VOICE_BAND_RATIO,
                   voiced / a.VOICE_PITCH_RATIO)

    def test_speech_passes(self):
        self.assertGreater(self.score(support.speech(2.0)), 1.0)

    def test_tone_and_noise_fail(self):
        self.assertLess(self.score(support.music(2.0)), 0.5)
        noise = np.random.default_rng(0).standard_normal(2 * AUDIO_RATE).astype(np.float32)
        self.assertLess(self.score(noise), 0.5)

    def test_too_short(self):
        self.assertEqual(self.a.voice_features(support.speech(0.5), AUDIO_RATE), (0.0, 0.0, 0.0, 0.0))

    def test_voiced_ratio(self):
        self.assertGreater(self.a.voiced_ratio(support.speech(2.0), AUDIO_RATE), self.a.VOICE_PITCH_RATIO)
        noise = np.random.default_rng(1).standard_normal(2 * AUDIO_RATE)
        self.assertLess(self.a.voiced_ratio(noise, AUDIO_RATE), 0.1)


if __name__ == "__main__":
    unittest.main()
