"""SoapySDR receivers (HackRF, Airspy...) without hardware: a fake SoapySDR module, with the calls of the
real Python bindings that the program uses, reading from a synthetic scene."""
import os
import sys
import types
import unittest
import wave

from tests import support
from tests.support import Emitter, Scene, app


class Range:
    def __init__(self, lo, hi):
        self.lo, self.hi = lo, hi

    def minimum(self):
        return self.lo

    def maximum(self):
        return self.hi


# what each fake driver can do: sample rates (a list, or ranges), frequencies, gain range
SPECS = {
    "hackrf": dict(rates=[], rate_ranges=[Range(1e6, 20e6)], freq=[Range(0, 7.25e9)], gain=(0, 116)),
    "airspy": dict(rates=[10e6, 2.5e6], rate_ranges=[], freq=[Range(24e6, 1.8e9)], gain=(0, 21)),
    "airspyhf": dict(rates=[912e3, 768e3], rate_ranges=[], freq=[Range(9e3, 260e6)], gain=(0, 48)),
}


def fake_soapy(found, scene, overflow_every=0, dead=False):
    """A SoapySDR module: found the enumerate() results, scene the air every device reads."""
    mod = types.ModuleType("SoapySDR")
    mod.SOAPY_SDR_RX, mod.SOAPY_SDR_CF32 = 1, "CF32"
    mod.SOAPY_SDR_TIMEOUT, mod.SOAPY_SDR_OVERFLOW = -1, -4
    mod.opened = []

    class Result:
        def __init__(self, ret):
            self.ret = ret

    class Device:
        @staticmethod
        def enumerate(args=None):
            return [dict(a) for a in found]

        @staticmethod
        def unmake(dev):
            dev.unmade = True

        def __init__(self, args):
            self.args, self.spec = dict(args), SPECS[args["driver"]]
            self.rate = self.freq = None
            self.t, self.gain, self.active, self.reads, self.unmade = 0.0, 0.0, False, 0, False
            self.calls = []
            mod.opened.append(self)

        def listSampleRates(self, direction, channel):
            return list(self.spec["rates"])

        def getSampleRateRange(self, direction, channel):
            return list(self.spec["rate_ranges"])

        def setSampleRate(self, direction, channel, rate):
            self.rate = rate

        def setGainMode(self, direction, channel, auto):
            self.calls.append(("agc", auto))

        def getGainRange(self, direction, channel):
            return Range(*self.spec["gain"])

        def setGain(self, direction, channel, gain):
            self.gain = gain

        def getGain(self, direction, channel):
            return self.gain

        def getFrequencyRange(self, direction, channel):
            return list(self.spec["freq"])

        def setFrequency(self, direction, channel, hz):
            assert not self.active, "tuned while streaming"
            self.freq = hz
            self.calls.append(("tune", hz))

        def setupStream(self, direction, fmt):
            assert fmt == "CF32"
            return "stream"

        def activateStream(self, stream):
            self.active = True
            self.calls.append(("activate",))

        def deactivateStream(self, stream):
            self.active = False
            self.calls.append(("deactivate",))

        def closeStream(self, stream):
            self.calls.append(("close",))

        def readStream(self, stream, buffs, n, timeoutUs=100000):
            assert self.active
            self.reads += 1
            if dead:
                return Result(mod.SOAPY_SDR_TIMEOUT)
            if overflow_every and self.reads % overflow_every == 0:
                return Result(mod.SOAPY_SDR_OVERFLOW)
            n = min(n, 65536, len(buffs[0]))        # a driver hands its own buffer sizes
            buffs[0][:n] = scene.samples(self.freq, self.t, n, self.rate)
            self.t += n / self.rate
            return Result(n)

    mod.Device = Device
    return mod


HACKRF = {"driver": "hackrf", "label": "HackRF One #0 1234", "serial": "1234"}
AIRSPY = {"driver": "airspy", "label": "AirSpy R2", "serial": "a1"}
AIRSPYHF = {"driver": "airspyhf", "label": "AirSpy HF+", "serial": "h1"}
RTL = {"driver": "rtlsdr", "label": "Generic RTL2832U", "serial": "00000001"}
AUDIO = {"driver": "audio", "label": "Built-in microphone"}


class Soapy(unittest.TestCase):
    def setUp(self):
        self.a = a = app()
        self.saved = (sys.modules.get("SoapySDR"), list(a._SOAPY), a.RECORD_SILENCE_S, a.CLIPS_DIR,
                      a.RECORDINGS_DIR, a.DEVICES)
        a.RECORD_SILENCE_S = 2.0
        home = os.path.join(a.TEST_HOME, "soapy-" + self.id().rsplit(".", 1)[-1])
        a.CLIPS_DIR, a.RECORDINGS_DIR = os.path.join(home, "clips"), os.path.join(home, "recordings")
        a.DEVICES = os.path.join(home, "devices.json")
        self.home = home

    def tearDown(self):
        a = self.a
        mod, a._SOAPY[:], a.RECORD_SILENCE_S, a.CLIPS_DIR, a.RECORDINGS_DIR, a.DEVICES = self.saved
        if mod is None:
            sys.modules.pop("SoapySDR", None)
        else:
            sys.modules["SoapySDR"] = mod

    def install(self, found, scene=None, **kw):
        mod = fake_soapy(found, scene or Scene([]), **kw)
        sys.modules["SoapySDR"] = mod
        self.a._SOAPY[:] = []
        return mod

    def test_without_soapysdr(self):
        sys.modules["SoapySDR"] = None           # import SoapySDR raises ImportError
        self.a._SOAPY[:] = []
        self.assertIsNone(self.a.soapy())
        self.assertEqual(self.a.soapy_devices(), [])
        with self.assertRaises(RuntimeError):
            self.a.SoapySdr(HACKRF, 30)

    def test_enumeration_skips_dongles_and_audio(self):
        self.install([HACKRF, RTL, AUDIO, AIRSPY])
        devs = self.a.soapy_devices()
        self.assertEqual([d["id"] for d in devs], ["hackrf:1234", "airspy:a1"])
        self.assertEqual(devs[0]["backend"], "soapy")
        self.assertEqual(devs[0]["args"], HACKRF)
        self.assertTrue(all(d in self.a.list_devices() for d in devs))

    def test_pick_rate(self):
        pick = self.a.SoapySdr.pick_rate
        self.assertEqual(pick([], [Range(1e6, 20e6)]), 2.4e6)             # HackRF
        self.assertEqual(pick([10e6, 2.5e6], []), 2.5e6)                  # Airspy R2
        self.assertEqual(pick([3e6, 6e6], []), 3e6)                       # Airspy Mini
        self.assertEqual(pick([2.4e6, 3.2e6], []), 2.4e6)
        self.assertIsNone(pick([912e3, 768e3], []))                       # Airspy HF+

    def test_opening(self):
        mod = self.install([HACKRF])
        sdr = self.a.SoapySdr(HACKRF, 30)
        dev = mod.opened[0]
        self.assertEqual((sdr.rate, dev.rate), (2.4e6, 2.4e6))
        self.assertEqual(sdr.gain, 30)
        self.assertEqual(sdr.gain_range, (0, 116))
        self.assertIn(("agc", False), dev.calls)
        self.assertEqual(sdr.coverage(), [(self.a.HF_LOW, 7.25e9)])
        self.assertTrue(sdr.hf)
        self.assertIsNone(sdr.tuner)
        sdr.close()
        self.assertTrue(dev.unmade)
        self.assertIn(("close",), dev.calls)

    def test_rate_too_low(self):
        mod = self.install([AIRSPYHF])
        with self.assertRaises(RuntimeError) as e:
            self.a.SoapySdr(AIRSPYHF, 20)
        self.assertIn("0.9", str(e.exception))
        self.assertTrue(mod.opened[0].unmade)

    def test_tune_restarts_the_stream(self):
        mod = self.install([HACKRF])
        sdr = self.a.SoapySdr(HACKRF, 30)
        sdr.tune(145e6)
        sdr.read(1000, None)
        sdr.tune(146e6)
        calls = [c for c in mod.opened[0].calls if c[0] in ("tune", "activate", "deactivate")]
        self.assertEqual(calls, [("tune", 145e6), ("activate",), ("deactivate",), ("tune", 146e6), ("activate",)])

    def test_read_through_overflows(self):
        self.install([HACKRF], overflow_every=3)
        sdr = self.a.SoapySdr(HACKRF, 30)
        sdr.tune(145e6)
        iq = sdr.read(500_000, None)
        self.assertEqual((len(iq), iq.dtype.name), (500_000, "complex64"))

    def test_read_gives_up_on_a_dead_receiver(self):
        self.install([HACKRF], dead=True)
        sdr = self.a.SoapySdr(HACKRF, 30)
        with self.assertRaises(RuntimeError):
            sdr.tune(145e6)

    def test_gqrx_input(self):
        self.assertEqual(self.a.gqrx_input({"backend": "soapy", "args": {"driver": "hackrf", "serial": "1234"}}),
                         "soapy=0,driver=hackrf,serial=1234")
        self.assertEqual(self.a.gqrx_input({"backend": "rtlsdr", "index": 1}), "rtl=1")

    def scan(self, found, device_args):
        a = self.a
        talk = Emitter(145.5e6, "nfm", audio=support.speech(20, seed=11), start_s=0, stop_s=6)
        self.install(found, Scene([talk]))
        dev = next(d for d in a.soapy_devices() if d["args"] == device_args)
        dev.update(label=dev["product"], gain=None, hf=None)
        store = a.Store(os.path.join(self.home, "scanner.db"))
        st = a.ScanState([a.Band(145.0e6, 146.0e6, "2 m", "NFM", "s")], max_passes=1)
        ends = []
        a.Scanner(st, store, dev, {"on_end": lambda *args: ends.append(args)}).run()
        rows = store.q("SELECT freq, recording, device FROM detections WHERE kind = 'voice'")
        store.db.close()
        return dev, ends, rows

    def check_scan(self, dev, ends, rows):
        self.assertEqual(ends, [(dev["id"], None, False)])
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0][0], 145.5e6, delta=5000)
        self.assertEqual(rows[0][2], dev["id"])
        with wave.open(rows[0][1]) as w:
            self.assertGreater(w.getnframes() / w.getframerate(), 2.0)

    def test_scan_with_a_hackrf(self):
        dev, ends, rows = self.scan([HACKRF], HACKRF)
        self.check_scan(dev, ends, rows)
        learned = self.a.load_device_conf()[dev["id"]]
        self.assertEqual(learned["coverage"], [[self.a.HF_LOW, 7.25e9]])
        self.assertEqual(learned["gain_range"], [0, 116])
        self.assertIsNone(learned["tuner"])
        self.assertIn("0.5 – 7250 MHz", self.a.coverage_text(None, True, learned["coverage"], "hackrf"))

    def test_scan_with_an_airspy_at_2_5_msps(self):
        self.check_scan(*self.scan([AIRSPY], AIRSPY))

    def test_unsupported_receiver_ends_with_an_error(self):
        dev, ends, rows = self.scan([AIRSPYHF], AIRSPYHF)
        self.assertEqual(len(ends), 1)
        self.assertIn("2.4 MS/s", ends[0][1])
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
