"""What AGENT.md asks to check by hand: Python 3.8 syntax, the language files, the default ranges."""
import ast
import glob
import json
import os
import re
import shutil
import subprocess
import unittest

from tests.support import ROOT, app

LANGS = ("en", "fr", "de", "es")


def lang_keys(lang):
    text = open(os.path.join(ROOT, "lang", lang + ".sh"), encoding="utf-8").read()
    return set(re.findall(r"^(L_[A-Za-z0-9_]+)=", text, re.M))


class Syntax(unittest.TestCase):
    def test_python38(self):
        for path in ["archangesdr"] + glob.glob(os.path.join(ROOT, "tools", "*.py")):
            src = open(os.path.join(ROOT, path), encoding="utf-8").read()
            ast.parse(src, filename=path, feature_version=(3, 8))

    @unittest.skipUnless(shutil.which("bash"), "bash not installed")
    def test_bash(self):
        for path in glob.glob(os.path.join(ROOT, "lang", "*.sh")) + [os.path.join(ROOT, "install.sh")]:
            r = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, "%s: %s" % (path, r.stderr))


class Strings(unittest.TestCase):
    def test_every_key_in_every_language(self):
        src = open(os.path.join(ROOT, "archangesdr"), encoding="utf-8").read()
        used = set(re.findall(r"""\bT\(\s*["'](L_[A-Za-z0-9_]+)["']""", src))
        for key in re.findall(r"""\bP\(\s*["'](L_[A-Za-z0-9_]+)["']""", src):
            used |= {key + "_1", key + "_N"}
        self.assertTrue(used)
        # T("L_SCN_MODEL_" + name): a prefix completed at run time, some keys must carry it
        prefixes = {k for k in used if k.endswith("_")}
        for lang in LANGS:
            keys = lang_keys(lang)
            missing = sorted(used - prefixes - keys)
            self.assertEqual(missing, [], "missing in lang/%s.sh" % lang)
            for prefix in prefixes:
                self.assertTrue(any(k.startswith(prefix) for k in keys), "no %s* in lang/%s.sh" % (prefix, lang))

    def test_languages_have_the_same_keys(self):
        en = lang_keys("en")
        for lang in LANGS[1:]:
            self.assertEqual(sorted(en - lang_keys(lang)), [], "in en.sh, not in %s.sh" % lang)
            self.assertEqual(sorted(lang_keys(lang) - en), [], "in %s.sh, not in en.sh" % lang)

    def test_format_arguments_match(self):
        """A translation takes the same %-arguments as the English string (T() would raise otherwise)."""
        a = app()
        spec = re.compile(r"%(?:\([^)]*\))?[-+ #0]*\d*(?:\.\d+)?[sdifgxXc%]")
        en = a.load_lang("en")
        for lang in LANGS[1:]:
            strings = a.load_lang(lang)
            for key, value in strings.items():
                if key in en:
                    want = [s for s in spec.findall(en[key]) if s != "%%"]
                    got = [s for s in spec.findall(value) if s != "%%"]
                    self.assertEqual(len(got), len(want), "%s in %s.sh: %r vs %r" % (key, lang, value, en[key]))


class Icons(unittest.TestCase):
    def test_shipped_icons(self):
        """Every icon of the app's own (archangesdr-*) is in icons/, symbolic, and installed."""
        src = open(os.path.join(ROOT, "archangesdr"), encoding="utf-8").read()
        used = set(re.findall(r"archangesdr-[a-z]+-symbolic", src))
        self.assertTrue(used)
        for name in used:
            path = os.path.join(ROOT, "icons", name + ".svg")
            self.assertTrue(os.path.isfile(path), name)
            self.assertIn("<svg", open(path, encoding="utf-8").read())
        self.assertIn("icons", open(os.path.join(ROOT, "install.sh"), encoding="utf-8").read().split("cp -r")[1]
                      .splitlines()[0])


class Ranges(unittest.TestCase):
    def test_default_ranges(self):
        a = app()
        files = glob.glob(os.path.join(ROOT, "ranges", "*", "*.json"))
        self.assertTrue(files)
        for path in files:
            data = json.load(open(path, encoding="utf-8"))
            self.assertIsInstance(data, list, path)
            for d in data:
                self.assertIn(d["mode"], ("AM", "NFM", "FM", "USB", "LSB", "WFM"), path)
                self.assertLess(d["lo_mhz"], d["hi_mhz"], "%s: %s" % (path, d.get("label")))
                self.assertTrue(d.get("label"), path)
                a.Band.from_dict(d)


if __name__ == "__main__":
    unittest.main()
