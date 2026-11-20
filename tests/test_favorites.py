"""Favorites: narrow bands with a favorite field, the refused list, the automatic add."""
import os
import shutil
import tempfile
import time
import unittest

from tests.support import app


class Bands(unittest.TestCase):
    def setUp(self):
        self.a = app()
        self.s = {}

    def test_round_trip(self):
        a = self.a
        fav = a.add_favorite([], self.s, 145.5e6, "2 m", "NFM", kind="auto")
        self.assertEqual(a.Band.from_dict(fav.to_dict()).favorite, "auto")
        self.assertNotIn("favorite", a.Band(145e6, 146e6, "2 m", "NFM", "s").to_dict())

    def test_add_is_narrow_and_named_like_the_range(self):
        f = 446.00625e6
        b = self.a.add_favorite([], self.s, f, "PMR446", "NFM")
        self.assertEqual((b.lo, b.hi), (f - 6250, f + 6250))
        self.assertEqual((b.label, b.mode, b.favorite, b.enabled), ("PMR446", "NFM", "manual", True))
        self.assertEqual(len(list(b.hops())), 1)

    def test_neighbour_key_is_the_same_favorite(self):
        a, bands = self.a, []
        b = a.add_favorite(bands, self.s, 446.00625e6, "PMR446", "NFM")
        self.assertIs(a.add_favorite(bands, self.s, 446.0125e6, "PMR446", "NFM"), b)
        self.assertEqual(len(bands), 1)
        self.assertIs(a.favorite_of(bands, 446.0125e6), b)
        self.assertIsNone(a.favorite_of(bands, 446.025e6))

    def test_ordinary_ranges_are_not_favorites(self):
        self.assertIsNone(self.a.favorite_of([self.a.Band(446e6, 446.2e6, "PMR", "NFM", "s")], 446.1e6))

    def test_remove_refuses_and_add_unrefuses(self):
        a, bands, f = self.a, [], 145.5e6
        a.remove_favorite(bands, self.s, a.add_favorite(bands, self.s, f, "2 m", "NFM"))
        a.remove_favorite(bands, self.s, a.add_favorite(bands, self.s, f, "2 m", "NFM"))
        self.assertEqual(bands, [])
        self.assertEqual(a.favorites_conf(self.s)["refused"], [a.fav_key(f)])
        a.add_favorite(bands, self.s, f, "2 m", "NFM")
        self.assertEqual(a.favorites_conf(self.s)["refused"], [])

    def test_preset_keeps_favorites(self):
        a = self.a
        old = a.Band(145e6, 146e6, "2 m", "NFM", "s")
        fav = a.add_favorite([], self.s, 145.5e6, "2 m", "NFM")
        new = a.Band(430e6, 440e6, "70 cm", "NFM", "s")
        self.assertEqual(a.with_favorites([new], [old, fav]), [new, fav])


class Auto(unittest.TestCase):
    F = 145.5e6

    def setUp(self):
        self.a = app()
        self.tmp = tempfile.mkdtemp()
        self.store = self.a.Store(os.path.join(self.tmp, "scanner.db"))
        self.s = {"favorites": {"auto": True}}

    def tearDown(self):
        self.store.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def heard(self, n, kind="voice", days_ago=0, freq=F):
        t = time.time() - days_ago * 86400
        for k in range(n):            # 10 min apart: n separate conversations
            self.store.q("INSERT INTO detections (freq, kind, first_seen, last_seen, hits) VALUES (?, ?, ?, ?, 1)",
                         (freq + (k % 2) * 3000, kind, t - k * 600, t - k * 600), True)

    def auto(self, bands):
        return self.a.auto_favorite(self.store, bands, self.s, self.F, "2 m", "NFM")

    def test_five_listens_add(self):
        self.heard(3, days_ago=60)            # no time limit
        self.heard(2)
        self.heard(5, freq=146.0e6)           # another channel
        self.assertEqual(self.store.voice_count(self.F), 5)
        bands = []
        b = self.auto(bands)
        self.assertEqual((b.favorite, b.label, b.mode), ("auto", "2 m", "NFM"))
        self.assertEqual(bands, [b])

    def test_two_receivers_taking_turns_count_one_conversation(self):
        t = time.time() - 3600
        # one conversation: dongle A heard it, dongle B heard the reply 90 s later (another row: per receiver)
        for dev, first, last in (("A", t, t + 40), ("B", t + 130, t + 150), ("A", t + 200, t + 210)):
            self.store.q("INSERT INTO detections (freq, kind, first_seen, last_seen, hits, device) "
                         "VALUES (?, 'voice', ?, ?, 1, ?)", (self.F, first, last, dev), True)
        self.assertEqual(self.store.voice_count(self.F), 1)
        self.store.q("INSERT INTO detections (freq, kind, first_seen, last_seen, hits, device) "
                     "VALUES (?, 'voice', ?, ?, 1, 'B')", (self.F, t + 210 + 121, t + 400), True)
        self.assertEqual(self.store.voice_count(self.F), 2)       # more than 2 min later: another one

    def test_last_voice(self):
        self.assertIsNone(self.store.last_voice(self.F))
        self.heard(1, days_ago=2)
        self.heard(1, kind="parasite")
        self.store.q("UPDATE detections SET recording = 'r.wav', audio = 'a.wav' WHERE kind = 'voice'", (), True)
        last, rec, audio = self.store.last_voice(self.F)
        self.assertAlmostEqual(last, time.time() - 2 * 86400, delta=60)
        self.assertEqual((rec, audio), ("r.wav", "a.wav"))

    def test_four_or_interference_do_not(self):
        self.heard(4)
        self.heard(5, kind="parasite")
        self.assertIsNone(self.auto([]))
        self.heard(1)
        self.store.rules.ban(self.F, "2 m", "NFM", "marked as interference")
        self.assertIsNone(self.auto([]))

    def test_off_refused_or_existing_do_not(self):
        self.heard(5)
        self.s["favorites"]["auto"] = False
        self.assertIsNone(self.auto([]))
        self.s["favorites"]["auto"] = True
        self.s["favorites"]["refused"] = [self.a.fav_key(self.F) + 1]      # the neighbouring key: same channel
        self.assertIsNone(self.auto([]))
        self.s["favorites"]["refused"] = []
        paused = self.a.add_favorite([], {}, self.F, "2 m", "NFM")
        paused.enabled = False                 # unticked: still a favorite
        bands = [paused]
        self.assertIsNone(self.auto(bands))
        self.assertEqual(bands, [paused])


if __name__ == "__main__":
    unittest.main()
