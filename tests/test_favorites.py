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


if __name__ == "__main__":
    unittest.main()
