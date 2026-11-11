#!/usr/bin/env python3
"""Processing cost of each scan step on this machine, on synthetic signals (no dongle needed):

    tools/bench.py              # about 10 s on a PC, 1 - 2 min on a Raspberry Pi 4 / uConsole

"real time" is the processing time over the duration of the samples processed: above 100 %, the
machine cannot keep up with the dongle (the stream buffer fills, then drops samples). One core: the
scanner thread is single-threaded."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.dont_write_bytecode = True

import numpy as np                                                  # noqa: E402

from tests import support                                          # noqa: E402
from tests.support import Emitter, Scene, capture                  # noqa: E402


def timed(fn, repeat):
    fn()                     # warm-up (FFT plans, caches)
    t = time.perf_counter()
    for _ in range(repeat):
        fn()
    return (time.perf_counter() - t) / repeat


def main():
    a = support.app()
    fs = support.FS
    tuned = 100e6
    lo, hi = tuned + 50e3, tuned + 1.05e6
    band = a.Band(lo, hi, "bench", "NFM", "bench")
    talk = Scene([Emitter(tuned + 300e3, "nfm", audio=support.speech(10))])
    quiet = Scene([])
    print("numpy %s, python %s" % (np.__version__, sys.version.split()[0]))
    print("%-42s %9s %10s" % ("step", "ms", "real time"))

    def row(name, seconds, fn, repeat=3):
        t = timed(fn, repeat)
        print("%-42s %9.1f %9.0f %%" % (name, t * 1000, 100 * t / seconds))

    raw = np.random.default_rng(0).integers(0, 256, int(fs * 0.5) * 2, dtype=np.uint8).tobytes()
    row("IQ conversion (0.5 s)", 0.5, lambda: a.RtlSdr._iq(raw), 5)
    s = capture(talk, tuned, a.SURVEY_S)
    row("survey hop (0.1 s)", a.SURVEY_S, lambda: a.Detector(8.0).survey(s, tuned, lo, hi), 5)
    x = capture(quiet, tuned, 2.5)
    row("analyze 2.5 s, noise only", 2.5, lambda: a.Detector(8.0).analyze(x, tuned, lo, hi, band))
    x = capture(talk, tuned, 2.5)
    row("analyze 2.5 s, speech", 2.5, lambda: a.Detector(8.0).analyze(x, tuned, lo, hi, band))

    # a listen as Scanner._listen runs it, without an early verdict: blocks of LISTEN_STEP_S
    class Sdr(support.FakeSdr):
        def read(self, n, stop):
            i = int(self.t * fs)
            self.t += n / fs
            return x[i:i + n]

    class Quick(a.Scanner):
        @staticmethod
        def decided(signals, group, t):
            return False

        def record(self, *args):
            pass

    st = a.ScanState([band], dwell=2.5)
    store = a.Store(os.path.join(a.TEST_HOME, "bench.db"))
    sc = Quick(st, store, {"id": "bench", "index": 0, "label": "bench", "gain": None, "hf": None})

    def listen():
        sdr = Sdr(talk)
        sdr.freq = tuned
        sc._listen(sdr, band, lo, hi, tuned, [tuned + 300e3])

    row("listen 2.5 s (progressive, no verdict)", 2.5, listen)

    # one recording block, as Scanner.follow handles it (without the file)
    blk = capture(talk, tuned, a.RECORD_CHUNK_S)
    sig = {"id": 0, "freq": tuned + 300e3, "demod": "fm", "audio": np.zeros(16, np.float32)}

    class Rec(a.Recording):
        def __init__(self):
            self.freq = self.peak = sig["freq"]
            self.kind, self.gain, self.threshold = "fm", 1.0, 8.0
            self.silent_s, self.live, self.pending, self.frames = 0.0, True, 0, 0
            self.channel, self.last = None, None

        def write(self, audio):
            pass

    rec = Rec()
    freqs = tuned + (np.arange(a.NFFT) - a.NFFT // 2) * fs / a.NFFT
    keep = (freqs >= lo) & (freqs <= hi)

    def record_block():
        P = a.frame_spectra(blk)
        rec.feed(blk, tuned, freqs, P, np.median(P[:, keep], axis=1))

    row("recording block (0.5 s, 1 conversation)", a.RECORD_CHUNK_S, record_block, 5)
    store.db.close()


if __name__ == "__main__":
    main()
