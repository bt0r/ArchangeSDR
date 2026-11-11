"""Shared by the tests: the application loaded as a module in a throwaway home, synthetic IQ scenes and a
fake receiver. Everything is generated (no recording of a real transmission) and seeded, so a run gives
the same samples every time."""
import atexit
import importlib.machinery
import importlib.util
import os
import shutil
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FS = 2_400_000
AUDIO_RATE = 16_000

_APP = []


def app():
    """archangesdr as a module, loaded once per test run. The program reads its profile, settings and
    language at import: they come from a temporary home, so the user's history is never touched."""
    if _APP:
        return _APP[0]
    home = tempfile.mkdtemp(prefix="archangesdr-test-")
    atexit.register(shutil.rmtree, home, True)
    os.environ.update({"XDG_CONFIG_HOME": os.path.join(home, "config"),
                       "XDG_DATA_HOME": os.path.join(home, "data"),
                       "ARCHANGESDR_PROFILE": "standalone", "SCANNER_LANG": "en", "SCANNER_REGION": "eu",
                       "LANG": "C"})
    # ARCHANGESDR_PROGRAM: test another copy of the program (an installed one, a modified one)
    path = os.environ.get("ARCHANGESDR_PROGRAM") or os.path.join(ROOT, "archangesdr")
    loader = importlib.machinery.SourceFileLoader("archangesdr", path)
    spec = importlib.util.spec_from_loader("archangesdr", loader)
    mod = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, [path]
    try:
        loader.exec_module(mod)
    finally:
        sys.argv = argv
    mod.TEST_HOME = home
    _APP.append(mod)
    return mod


# --- Audio --------------------------------------------------------------------------------------------

def _shape(x, rate, bumps):
    """x filtered by a sum of Gaussian bumps [(centre Hz, width Hz, gain)] (formants), in the frequency
    domain."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / rate)
    H = sum(g * np.exp(-0.5 * ((f - c) / w) ** 2) for c, w, g in bumps)
    return np.fft.irfft(X * H, len(x))


def _syllable(n):
    """Envelope of a syllable: quick rise and fall, steady vowel in between."""
    w = np.ones(n)
    k = max(1, n // 6)
    ramp = 0.5 * (1 - np.cos(np.pi * np.arange(k) / k))
    w[:k], w[-k:] = ramp, ramp[::-1]
    return w


def speech(seconds, seed=1, rate=AUDIO_RATE):
    """Speech-like audio in [-1, 1]: a glottal pulse train (pitch 100-170 Hz, drifting) through three
    formants, cut into syllables of 120-260 ms separated by 40-160 ms gaps, with a breath pause now and
    then. Enough for the four criteria of the detector (dynamics, 2-10 Hz rhythm, 300-3000 Hz energy,
    voiced frames); not meant to be intelligible."""
    rng = np.random.default_rng(seed)
    n = int(seconds * rate)
    t = np.arange(n) / rate
    pitch = 135 + 30 * np.sin(2 * np.pi * 0.7 * t + rng.uniform(0, 6))
    phase = np.cumsum(pitch / rate)
    pulses = np.diff(np.floor(phase), prepend=0.0)          # one impulse per period
    voiced = _shape(pulses, rate, [(650, 150, 1.0), (1150, 200, 0.7), (2500, 300, 0.35)])
    env = np.zeros(n)
    i = int(rng.uniform(0.02, 0.1) * rate)
    while i < n:
        syl = int(rng.uniform(0.12, 0.26) * rate)
        k = min(syl, n - i)
        env[i:i + k] = rng.uniform(0.5, 1.0) * _syllable(syl)[:k]
        i += syl + int((rng.uniform(0.35, 0.7) if rng.random() < 0.08 else rng.uniform(0.04, 0.16)) * rate)
    out = voiced * env + 0.01 * rng.standard_normal(n)
    return (out / np.abs(out).max()).astype(np.float32)


def music(seconds, seed=2, rate=AUDIO_RATE):
    """A few steady tones (a broadcast station's programme, no speech rhythm)."""
    t = np.arange(int(seconds * rate)) / rate
    rng = np.random.default_rng(seed)
    out = sum(np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) for f in (220, 330, 440, 1250))
    return (out / np.abs(out).max()).astype(np.float32)


# --- Emitters: complex baseband at a given offset, continuous across reads ------------------------

class Emitter:
    """A transmitter at freq (Hz, absolute) heard from start_s to stop_s (receiver time) at amplitude
    level (the noise has a standard deviation of NOISE per I and Q)."""

    def __init__(self, freq, kind, level=0.1, start_s=0.0, stop_s=1e9, audio=None, deviation=3000,
                 width=100_000, seed=3):
        self.freq, self.kind, self.level = freq, kind, level
        self.start_s, self.stop_s = start_s, stop_s
        self.audio = audio
        self.deviation, self.width, self.seed = deviation, width, seed
        if audio is not None and kind in ("nfm", "wfm"):
            # FM phase at the audio rate, integrated once: reads at any time interpolate it (continuous)
            self.phase = 2 * np.pi * deviation * np.concatenate(([0.0], np.cumsum(audio, dtype=np.float64))) \
                / AUDIO_RATE
        if audio is not None and kind in ("usb", "lsb"):
            A = np.fft.fft(audio.astype(np.float64))
            f = np.fft.fftfreq(len(audio), 1 / AUDIO_RATE)
            A[f < 0 if kind == "usb" else f > 0] = 0
            self.analytic = np.fft.ifft(2 * A)

    def _at(self, arr, t):
        """arr (audio rate) at the times t (s), looped, linearly interpolated."""
        x = (t * AUDIO_RATE) % (len(arr) - 1)
        i = x.astype(np.int64)
        w = x - i
        return arr[i] * (1 - w) + arr[i + 1] * w

    def baseband(self, t, tuned, rng, rate=FS):
        """Samples at the times t (s), as the receiver tuned to tuned sees them (zeros outside the
        transmission)."""
        on = (t >= self.start_s) & (t < self.stop_s)
        if not on.any():
            return None
        carrier = 2 * np.pi * (self.freq - tuned) * t
        if self.kind == "carrier":
            z = np.exp(1j * carrier)
        elif self.kind in ("nfm", "wfm"):
            z = np.exp(1j * (carrier + self._at(self.phase, t)))
        elif self.kind == "am":
            z = (1 + 0.8 * self._at(self.audio, t)) * np.exp(1j * carrier) / 1.8
        elif self.kind in ("usb", "lsb"):
            z = self._at(self.analytic, t) * np.exp(1j * carrier)
        elif self.kind == "wide":      # band-limited noise, width Hz wide
            n = len(t)
            Z = np.fft.fft(rng.standard_normal(n) + 1j * rng.standard_normal(n))
            Z[np.abs(np.fft.fftfreq(n, 1 / rate)) > self.width / 2] = 0
            z = np.fft.ifft(Z) * np.sqrt(rate / self.width) / np.sqrt(2) * np.exp(1j * carrier)
        else:
            raise ValueError(self.kind)
        return np.where(on, z, 0) * self.level


NOISE = 0.05


class Scene:
    """The air around the receiver: some emitters over a Gaussian noise floor."""

    def __init__(self, emitters=(), noise=NOISE, seed=7):
        self.emitters, self.noise = list(emitters), noise
        self.rng = np.random.default_rng(seed)

    def samples(self, tuned, t0, n, rate=FS):
        t = t0 + np.arange(n) / rate
        z = (self.rng.standard_normal(n) + 1j * self.rng.standard_normal(n)) * self.noise
        for e in self.emitters:
            if abs(e.freq - tuned) < rate / 2:
                b = e.baseband(t, tuned, self.rng, rate)
                if b is not None:
                    z = z + b
        return z.astype(np.complex64)


def capture(scene, tuned, seconds, t0=0.0, rate=FS):
    return scene.samples(tuned, t0, int(seconds * rate), rate)


class FakeSdr:
    """Stands for RtlSdr (same attributes and methods) and reads from a Scene; its clock is the number of
    samples delivered, so a test runs as fast as the processing, not in real time."""

    def __init__(self, scene, name="Fake RTL-SDR", coverage=((24e6, 1766e6),), rate=FS):
        self.scene, self.name, self.segs, self.rate = scene, name, list(coverage), rate
        self.tuner, self.hf, self.gain, self.direct, self.index = 5, False, 40.0, 0, 0
        self.freq, self.t = None, 0.0
        self.tunes, self.reads, self.streaming, self.closed = [], 0, False, False

    def coverage(self):
        return list(self.segs)

    def tune(self, hz):
        self.stop_stream()
        self.freq = hz
        self.tunes.append(hz)
        self.t += 0.03       # the real one drops 30 ms while the PLL settles

    def start_stream(self):
        self.streaming = True

    def stop_stream(self):
        self.streaming = False

    def read(self, n, stop):
        if stop is not None and stop.is_set():
            return None
        out = self.scene.samples(self.freq, self.t, n, self.rate)
        self.t += n / self.rate
        self.reads += 1
        return out

    def close(self):
        self.closed = True
