#!/usr/bin/env python3
"""Renders the README screenshots into docs/screenshots/, without a dongle and without a screen.

    tools/screenshots.py              all of them
    tools/screenshots.py OUTDIR       somewhere else

Needs gtk4-broadwayd (GTK's own headless display, in the GTK 4 package: gtk4 on Arch, libgtk-4-bin on
Debian / Ubuntu) and nothing else than what ArchangeSDR needs. The window runs on a private Broadway
display at a fixed size, with two simulated receivers, a made-up history (the kind of traffic a scanner
hears in Europe: airband, marine VHF, PMR446, 2 m, CB) and its transcripts, in a temporary home: the
user's own settings and history are never read. Each theme (dark, light) runs in a process of its own,
because the theme is chosen when GTK starts.
"""
import importlib.machinery
import importlib.util
import os
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SIZE = (1280, 860)        # the README's screenshot
TALL = (1280, 1060)       # the tabs: more of their content
RECEIVERS = [
    {"index": 0, "maker": "RTLSDRBlog", "product": "Blog V4", "serial": "00000001", "chip": "", "id": "00000001",
     "label": "RTL-SDR Blog V4", "tuner": 6},
    {"index": 1, "maker": "Nooelec", "product": "NESDR SMArt", "serial": "00000102", "chip": "", "id": "00000102",
     "label": "Nooelec NESDR SMArt", "tuner": 5},
]
# (MHz, mode, range label, score, SNR, recording seconds, minutes ago, transcript or None)
HEARD = [
    (124.625, "AM", "Civil aviation (121.5 emergency)", 2.31, 27, 42.6, 0.3,
     "Skyline four two seven, descend flight level eight zero, then contact approach on one two six decimal "
     "four."),
    (446.00625, "NFM", "PMR446 (walkie-talkies, 16 ch.)", 1.38, 22, 13.7, 4,
     "Okay, I'm at the car park now, meet you at the north entrance in five minutes."),
    (156.800, "NFM", "Marine VHF (ch. 16: 156.800)", 1.64, 31, 23.1, 18,
     "Securite, securite, securite. All stations, this is Coastguard. Navigational warning follows on channel "
     "six seven."),
    (118.925, "AM", "Civil aviation (121.5 emergency)", 1.82, 24, 18.3, 35,
     "Tower, Golf Bravo Charlie Delta, holding point runway two seven, ready for departure."),
    (145.500, "FM", "2 m, repeaters (145.6+)", 2.05, 29, 54.8, 62,
     "CQ CQ, this is a portable station on the hill, listening on one four five five."),
    (27.185, "AM", "CB, 40 ch. (ch. 19: 27.185)", 1.21, 18, 8.0, 95, None),
    (133.375, "AM", "Civil aviation (121.5 emergency)", 1.47, 15, 2.4, 140, None),
]
STATIONS = [(94.2, 31), (98.2, 36), (101.1, 28)]
INTERFERENCE = [(145.600, "2 m, repeaters (145.6+)", "continuous carrier (present at every pass)"),
                (144.800, "2 m SSB (call 144.300)", "no speech (data, tone or noise) · score 0.12"),
                (433.920, "70 cm (repeaters, satellites)", "no speech (data, tone or noise) · score 0.05")]


def free_display():
    for n in range(17, 60):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", 8080 + n)) != 0:
                return n
    raise SystemExit("no free Broadway display")


def tone(path, seconds, seed):
    """A WAV the size of a real capture (the buttons show their length); its sound does not matter."""
    import numpy as np
    rng = np.random.default_rng(seed)
    n = int(16000 * seconds)
    audio = (0.2 * np.sin(2 * np.pi * 440 * np.arange(n) / 16000) + 0.05 * rng.standard_normal(n)) * 32767
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(audio.astype("<i2").tobytes())


def demo_history(a):
    """The made-up history: the detections above (with their captures, recordings and transcripts), a
    week of older ones for the statistics, interference and the rules of the Interference tab."""
    st = a.Store()
    now = time.time()
    rnd = random.Random(7)
    os.makedirs(a.CLIPS_DIR, exist_ok=True)
    os.makedirs(a.RECORDINGS_DIR, exist_ok=True)
    old = st.start_scan([])
    st.q("UPDATE scans SET started = ?, ended = ?, passes = 412 WHERE id = ?", (now - 6 * 86400, now - 5 * 86400, old),
         True)
    for day in range(1, 7):                      # the statistics: a week of traffic, both receivers
        for mhz, mode, lbl, score, snr, _, _, _ in HEARD:
            for dev in RECEIVERS:
                hits = rnd.randint(0, 9 if mhz > 100 else 3)
                if hits:
                    t = now - day * 86400 + rnd.randint(0, 80000)
                    st.q("INSERT INTO detections (scan_id, freq, mode, label, first_seen, last_seen, hits, snr, score, "
                         "kind, device) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'voice', ?)",
                         (old, mhz * 1e6 + rnd.randint(-300, 300), mode, lbl, t, t + 60, hits, snr, score, dev["id"]),
                         True)
        for mhz, lbl, reason in INTERFERENCE:
            st.q("INSERT INTO detections (scan_id, freq, mode, label, first_seen, last_seen, hits, snr, score, kind, "
                 "reason, device) VALUES (?, ?, 'NFM', ?, ?, ?, ?, 14, 0.1, 'parasite', ?, ?)",
                 (old, mhz * 1e6, lbl, now - day * 86400, now - day * 86400 + 30, rnd.randint(2, 14), reason,
                  RECEIVERS[day % 2]["id"]), True)
    sid = st.start_scan([])
    st.q("UPDATE scans SET started = ?, passes = 37 WHERE id = ?", (now - 2.5 * 3600, sid), True)
    for k, (mhz, mode, lbl, score, snr, rec_s, ago, text) in enumerate(HEARD):
        dev = RECEIVERS[k % 2]["id"]
        t = now - ago * 60
        did = st.q("INSERT INTO detections (scan_id, freq, mode, label, first_seen, last_seen, hits, snr, score, kind, "
                   "device, params) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'voice', ?, ?)",
                   (sid, mhz * 1e6, mode, lbl, t - rec_s, t, rnd.randint(2, 9), snr, score, dev,
                    a.json.dumps({"freq": mhz * 1e6, "mode": mode, "demod": "am" if mode == "AM" else "fm",
                                  "window": [mhz * 1e6 - 30e3, mhz * 1e6 + 970e3], "tuned": mhz * 1e6 - 80e3,
                                  "rate": 2.4e6, "dwell": 2.5, "threshold": 8, "gain": 40.2,
                                  "device": next(r["label"] for r in RECEIVERS if r["id"] == dev), "direct": 0,
                                  "snr": snr, "occupancy": 0.71, "tx_s": 1.5, "width_khz": 7.0, "score": score,
                                  "features": [11.2, 0.46, 0.58, 0.41]})), True)
        clip = os.path.join(a.CLIPS_DIR, "%d.wav" % did)
        rec = os.path.join(a.RECORDINGS_DIR, "%d.wav" % did)
        tone(clip, 1.5 if k % 2 else 2.5, did)
        tone(rec, rec_s, did + 100)
        st.q("UPDATE detections SET audio = ?, recording = ?, rec_s = ? WHERE id = ?", (clip, rec, rec_s, did), True)
        st.request_transcript(did, None)
        if text:
            st.save_transcript(did, "done", text, "en", "whisper-cli · ggml-base-q5_1.bin")
        else:
            st.save_transcript(did, "empty")
    for mhz, snr in STATIONS:
        st.q("INSERT INTO detections (scan_id, freq, mode, label, first_seen, last_seen, hits, snr, score, kind, "
             "device) VALUES (?, ?, 'WFM', 'FM radio (stations)', ?, ?, 12, ?, 0, 'station', ?)",
             (sid, mhz * 1e6, now - 9000, now - 7200, snr, RECEIVERS[0]["id"]), True)
    band = a.Band(144e6, 146e6, "2 m, repeaters (145.6+)", "FM", "x")
    for mhz, lbl, reason in INTERFERENCE:        # the Interference tab: two banned, one on its way
        for _ in range(3 if mhz != 145.600 else 1):
            st.rules.parasite({"freq": mhz * 1e6, "mode": "NFM", "reason": reason},
                              a.Band(band.lo, band.hi, lbl, "NFM", "x"))
    st.rules.set_whitelisted(446.09375e6, True, "PMR446 (walkie-talkies, 16 ch.)", "NFM")
    return sid


def spectrum(a, lo, hi, peaks, seed):
    """A display spectrum like Detector._display returns: noise, and peaks (MHz, dB, kHz wide)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    f = np.linspace(lo, hi, 600)
    mean = np.clip(1.2 + 0.5 * rng.standard_normal(600), 0, None)
    for mhz, db, khz in peaks:
        mean += db * np.exp(-0.5 * ((f - mhz * 1e6) / (khz * 1e3 / 2.3)) ** 2)
    return {"freqs": f, "mean": mean, "peak": mean + np.abs(1.5 + 0.6 * rng.standard_normal(600))}


def render(theme, outdir):
    """One process: the app in a temporary home, the screenshots of one theme."""
    # a fixed temporary home: the paths shown (the whisper model's) are the same at each run
    home = os.path.join(tempfile.gettempdir(), "archangesdr-demo")
    shutil.rmtree(home, ignore_errors=True)
    app_dir = os.path.join(home, "app")
    os.makedirs(app_dir)
    for d in ("lang", "ranges"):
        shutil.copytree(os.path.join(ROOT, d), os.path.join(app_dir, d))
    src = open(os.path.join(ROOT, "archangesdr"), encoding="utf-8").read()
    # its own application id: an ArchangeSDR already running must not take the window
    src = src.replace("io.github.bt0r.archangesdr", "io.github.bt0r.archangesdr.screenshots")
    path = os.path.join(app_dir, "archangesdr")
    open(path, "w", encoding="utf-8").write(src)
    os.environ.update(XDG_CONFIG_HOME=os.path.join(home, "config"), XDG_DATA_HOME=os.path.join(home, "data"),
                      SCANNER_LANG="en", SCANNER_REGION="eu", GDK_DEBUG="no-portals")
    sys.argv = [path, "--profile", "standalone"]
    loader = importlib.machinery.SourceFileLoader("archangesdr", path)
    a = importlib.util.module_from_spec(importlib.util.spec_from_loader("archangesdr", loader))
    loader.exec_module(a)

    a.list_devices = lambda: [{k: r[k] for k in ("index", "maker", "product", "serial", "chip", "id")}
                              for r in RECEIVERS]
    a.whisper_binary = lambda conf=None: "/usr/bin/whisper-cli"
    for r in RECEIVERS:
        a.update_device_conf(r["id"], enabled=True, label=r["label"], tuner=r["tuner"])
    os.makedirs(a.MODELS_DIR, exist_ok=True)
    open(os.path.join(a.MODELS_DIR, "ggml-base-q5_1.bin"), "wb").write(b"\0" * 2_000_000)
    a.save_settings({"lang": "en", "region": "eu", "theme": theme, "stats_bucket": 5e3,
                     "join": {"program": "gqrx", "commands": [
                         {"name": "SDR++ (my build)", "command": "~/src/sdrpp/build/sdrpp & sleep 3; "
                                                                 "rigctl -m 2 -r 127.0.0.1:4532 F <frequency>"}]},
                     "ntfy": {"enabled": True, "url": "https://ntfy.sh/my-scanner-7f3k2q", "min_score_on": True,
                              "min_score": 1.5},
                     "transcription": {"engine": "whisper", "auto": True,
                                       "whisper_model": os.path.join(a.MODELS_DIR, "ggml-base-q5_1.bin")}})
    sid = demo_history(a)

    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib, Gtk
    steps = []

    def shot(widget, name, done, tries=20):
        """The widget as a PNG (GTK draws it itself: no screenshot tool, no compositor), then done()."""
        w, h = widget.get_width(), widget.get_height()
        snap = Gtk.Snapshot()
        Gtk.WidgetPaintable.new(widget).snapshot(snap, w, h)
        node = snap.to_node()
        if node is None and tries:             # not drawn yet: a frame later
            GLib.timeout_add(250, lambda: shot(widget, name, done, tries - 1) and False)
            return
        widget.get_native().get_renderer().render_texture(node, None).save_to_png(os.path.join(outdir, name))
        print("  %s (%d x %d)" % (name, w, h), flush=True)
        done()

    run = Gtk.Application.run

    def start(app, argv):
        def do(fn, wait=700):
            steps.append(("do", fn, wait))

        def take(name, widget=lambda: app.win):
            steps.append(("shot", widget, name))

        def next_step():
            """One step at a time: a screenshot is saved before the next step changes the window."""
            if not steps:
                return
            kind, what, arg = steps.pop(0)
            if kind == "shot":
                shot(what(), arg, lambda: GLib.timeout_add(200, lambda: next_step() and False))
            else:
                what()
                GLib.timeout_add(arg, lambda: next_step() and False)

        def scanning():
            """The window during a scan: one receiver records a conversation, the other one surveys."""
            app.win.set_size_request(*SIZE)
            for b in app.bands:
                b.enabled = b.label.startswith(("Civil aviation", "Marine VHF", "PMR446", "2 m", "CB"))
            a.save_ranges(app.bands)
            app.update_ranges_btn()
            app.state = a.ScanState([b for b in app.bands if b.enabled])
            app.state.scan_id = sid
            devs = [dict(r) for r in a.receivers()]
            app.scan_devs = devs
            app.set_cards(devs)
            app.set_button("stop")
            app.lock_ranges(True)
            air = next(b for b in app.bands if b.label.startswith("Civil aviation"))
            pmr = next(b for b in app.bands if b.label.startswith("PMR446"))
            v4, nesdr = devs[0]["id"], devs[1]["id"]
            app.on_tune(v4, air, 124.595e6, 125.595e6, 3, 24, 36, "record")
            app.on_record(v4, air, 124.595e6, 125.595e6,
                          spectrum(a, 124.595e6, 125.595e6, [(124.625, 29, 7), (125.33, 9, 6)], 1),
                          [{"freq": 124.625e6, "voice": True, "continuous": False}],
                          [(124.625e6, 42.6, 2.4, True)], False)
            app.on_tune(nesdr, pmr, 446.0e6, 446.2e6, 17, 24, 36, "survey")
            app.on_window(nesdr, pmr, 446.0e6, 446.2e6,
                          spectrum(a, 446.0e6, 446.2e6, [(446.00625, 22, 9), (446.09375, 12, 9)], 2),
                          [{"freq": 446.00625e6, "snr": 22, "voice": False, "continuous": False, "candidate": True,
                            "quiet": False, "banned": False},
                           {"freq": 446.09375e6, "snr": 12, "voice": False, "continuous": False, "candidate": True,
                            "quiet": True, "banned": False}], 0)
            app.show_banner(a.T("L_SCN_NOTIFY_TITLE", a.fmt_mhz(124.625e6)),
                            "Civil aviation (121.5 emergency) · AM · +27 dB · RTL-SDR Blog V4")
            app.refresh_lists()

        def tab(i):
            app.tabs.set_current_page(i)

        def scroll(px):
            # the Settings tab scrolls in its own scrolled window
            app.tabs.get_nth_page(app.stats_page + 1).get_vadjustment().set_value(px)

        def tall():
            app.win.set_size_request(*TALL)

        do(scanning, 2100)                     # the banner slides in meanwhile
        take("main%s.png" % ("" if theme == "dark" else "-light"))
        if theme == "dark":
            do(tall, 300)
            do(lambda: app.f_search.set_text("runway"), 900)
            take("log-search.png")
            do(lambda: (app.f_search.set_text(""), tab(app.rules_page)))
            take("interference.png")
            do(lambda: (tab(app.stats_page), app.stats_parasites.set_active(True)), 900)
            take("statistics.png")
            do(lambda: tab(app.stats_page + 1), 500)
            do(lambda: scroll(0))
            take("settings.png")
            do(lambda: scroll(900))
            take("settings-transcription.png")
            do(lambda: (scroll(0), tab(app.journal_page), app.open_ranges()), 1000)
            take("ranges.png", lambda: app.ranges_dialog)
        do(app.quit)
        GLib.timeout_add(500, lambda: next_step() and False)
        return run(app, argv)

    Gtk.Application.run = start
    try:
        a.gui()
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--render":
        return render(sys.argv[2], sys.argv[3])
    outdir = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "screenshots"))
    os.makedirs(outdir, exist_ok=True)
    broadway = shutil.which("gtk4-broadwayd") or shutil.which("broadwayd")
    if not broadway:
        raise SystemExit("gtk4-broadwayd not found (package gtk4 on Arch, libgtk-4-bin on Debian / Ubuntu)")
    n = free_display()
    server = subprocess.Popen([broadway, ":%d" % n], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=":%d" % n)
        for theme in ("dark", "light"):
            print(theme, flush=True)
            subprocess.run([sys.executable, os.path.realpath(__file__), "--render", theme, outdir], env=env,
                           timeout=120, check=True)
    finally:
        server.terminate()
    print("written to", outdir)


if __name__ == "__main__":
    main()
