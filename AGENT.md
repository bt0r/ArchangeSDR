# ArchangeSDR: notes for agents and maintainers

What you need to know before changing anything. The README is the user documentation; this file is
the why and the conventions.

## What it is

Formerly SDRScanner (renamed 2026-11). `sdrscanner` stays a command (a symlink made by install.sh):
archSDR's `radio-menu` and waybar call it and pause the scan with `pkill -USR1 -f "/sdrscanner( |$)"`,
so `restart()` re-executes the name it was started with. `migrate_old_name` moves the standalone
folders and rewrites the paths stored in the history; `SDRSCANNER_PROFILE` is still read. The `L_SCN_`
string keys keep their prefix (the desktops' scripts share them).

An RTL-SDR conversation scanner: it sweeps frequency ranges and lists the frequencies where someone
is **talking** (plus the FM stations on the air), with a 2.5 s capture and a recording of the whole
conversation. A GTK 4 window, a `--cli` mode for tuning the detection, in en / fr / de / es. It ships
standalone and inside two desktops by the same author: archSDR (Hyprland) and uBonsole (i3 on the
ClockworkPi uConsole, an ARM handheld running Debian).

## Architecture decisions (keep them)

- **One Python file, `archangesdr`, no build, no pip.** It runs from the distribution's packages
  only: Python >= 3.8, numpy, PyGObject with GTK 4, librtlsdr. That is what makes it install the same
  way on Arch, Debian / Raspberry Pi OS, Ubuntu, Fedora and openSUSE, x86_64 and ARM. Do not add a
  dependency that is not packaged by those distributions; do not split into a package unless asked.
- **librtlsdr through ctypes** (`RtlSdr`), not pyrtlsdr (not packaged everywhere). Blocking reads
  (`rtlsdr_read_sync`) for the survey hops; a continuous stream (`rtlsdr_read_async` in a thread,
  `start_stream` / `stop_stream`, stopped by every `tune`) while the scan stays on one frequency
  (listen, recording): blocking reads lose 1 - 3 % of the samples between two calls (a buzz in the
  recordings) and the analysis of a block would cost the next one. If the stream delivers nothing, it
  falls back to blocking reads; `SDR_ASYNC=0` forces them.
  Below 24 MHz: direct sampling (Q branch), except on the RTL-SDR Blog V4 (HF upconverter, R828D tuner).
- **Other receivers through SoapySDR, optional** (`soapy`, `soapy_devices`, `SoapySdr`, `open_receiver`):
  `import SoapySDR` is probed; without it, RTL-SDR only. `SoapySdr` has `RtlSdr`'s interface (`tune`,
  `read`, `coverage`, `rate`, `gain`...); its stream runs from one tune to the next. RTL-SDR dongles stay
  on librtlsdr even when soapyrtlsdr is installed. A receiver needs 2.4 MS/s or more (the hop plan is
  ±1.2 MHz): `pick_rate` takes 2.4 MS/s, else the lowest rate above (Airspy R2: 2.5 MS/s).
- **The sample rate belongs to the receiver** (`sdr.rate`, `Capture.rate`), never `FS` in the
  processing: `Grid` turns the detection's widths in Hz (`SMOOTH_HZ`, `FLOOR_HZ`, `PEAK_SEP_HZ`,
  `DC_HZ`) into bins of ~1.17 kHz at any rate (2048 bins at 2.4 MS/s, the values the detection was tuned
  with); coarser bins move the SSB carrier guessed from the voice's centroid.
- **Signal processing in numpy only** (no scipy). A channel (`Channel`) is a mixer and two decimating
  FIR filters (2.4 MS/s → 96 kS/s → 16 kS/s, `Decimator`, then `Resampler` for a rate that is not a
  multiple of 16 kHz), fed block by block with its state carried over: same output as the whole capture
  at once, a fixed cost per block. An FFT of the whole capture cost 2.6 s per 2.5 s listen on a
  Raspberry Pi 4 (CM4); keep the processing per block. Check: `tools/bench.py` (above 100 % "real
  time", the machine cannot keep up with the dongle).
- **External programs are optional and probed** (`launch`, `run_quiet`, `FileNotFoundError` caught):
  pw-play / paplay / aplay, notify-send, gqrx, xdg-open, pkill / pgrep, hyprctl. A missing one must
  never crash the app.
- **Python 3.8 syntax** (`:=` is used, nothing newer: no `match`, no `X | Y` types, no `list[int]` at
  runtime). Check: `python3 -c "import ast; ast.parse(open('archangesdr').read(), feature_version=(3, 8))"`.
- **GTK 4.0+ API, newer calls behind a check** (`gtk-interface-color-scheme` on 4.20+, `GLibUnix` on
  GLib 2.80+, `style_context_add_provider_for_display` before 4.10). `GDK_DEBUG=no-portals`: GTK hangs
  at start waiting for a desktop portal under i3 (none) and with a stuck one under Hyprland.
- **The window must fit a short tile.** Tiling window managers impose the height (about 400 px on the
  uConsole, a split under Hyprland). Both columns are in `scroll_column` (the left one with its Start /
  Stop bar pinned below), so the window's minimum height stays ~100 px; GTK prints "Trying to measure
  GtkApplicationWindow for height of N, but it needs at least M" at every frame otherwise. A new
  fixed-height widget goes inside a scrolled column. Check: `win.measure(Gtk.Orientation.VERTICAL, -1)[0]`.

## How the scan works

- **Two steps.** Survey: 0.1 s hops 2.06 MHz apart (±1.08 MHz, 90 % of the 2.4 MS/s capture); the
  noise floor is local (`local_floor`, ~150 kHz blocks) so the filter roll-off does not hide the edges;
  narrow peaks above the threshold become candidates. Listen: on 1 MHz windows around the candidates.
  Every other pass, the hops shift by 50 kHz so the DC spike never hides the same channel.
  The speed idea comes from FalconSDR (0.1 s per window); unlike it, we keep the speech verdict.
- **Progressive listen** (`Scanner._listen`, `decided`): 0.5 s blocks, analysed from 1 s on (a
  `Capture` keeps the frame spectra and the channels already extracted: each analysis only processes the
  new block); it stops
  when every survey candidate is gone, a continuous carrier, wide or scores below `LISTEN_GIVE_UP`, or
  when speech is confirmed (from `LISTEN_VOICE_S` = 1.5 s); the dwell setting is the maximum.
  `analyze` runs several times per listen, so it must stay free of side effects: the continuous-carrier
  counting is in `Detector.track`, called once at the end.
- **Recency boost** (`ScanState.boosts`, `Scanner.revisit`): after a recording, the conversation's
  window gets a 0.1 s survey every `RECENCY_EVERY_S` = 8 s for `RECENCY_S` = 90 s, between two hops,
  and a listen if it is back.
- **Speech, not "a signal".** A listened signal is speech when it lasts >= 0.8 s, is narrower than
  30 kHz and its demodulated audio (FM, AM and, on SSB ranges, SSB are all tried, the best kept)
  passes four criteria: syllable/pause dynamics, 2-10 Hz envelope modulation, 300-3000 Hz energy,
  voiced (80-400 Hz periodic) frames. The thresholds are `VOICE_*` at the top of the file; change them
  only with `--cli` measurements on real signals.
- **Muting.** What was listened to without speech is muted for 2, 10 or 30 passes (intermittent,
  continuous, carrier present on 3 listens in a row).
- **Ban and whitelist** (`FreqRules`, table `freq_rules`, persistent across scans): `BAN_PARASITE` = 3
  listens *in a row* without speech ban a frequency for good (speech resets the count). Banned: the
  survey skips it and its signals are dropped from listens. Whitelisted (by the user): never banned
  nor muted, and captured like speech as soon as it is above the threshold (false positives).
  Frequencies are matched on a 6.25 kHz key, ±1 key.
- **Recording** (`Recording`, `Scanner.follow`): after a capture with speech the scan stays on the
  window and records each conversation heard there until `RECORD_SILENCE_S` = 20 s without a
  transmission, `RECORD_MAX_S` = 15 min at most. Pauses are kept, the final silence is not. One file
  per detection row (`recordings/<id>.wav`); a conversation heard again within 2 min (the same row) is
  appended. The level is the gain of the first capture (no normalisation afterwards: it streams to
  disk).
- **Captures**: every kept signal, interference included, gets its 2.5 s WAV (`clips/<id>.wav`), so a
  false positive can be heard before whitelisting it.
- **FM broadcast** (WFM ranges): no speech test, the station finder works on the 100 kHz raster (so
  the 30 kHz OIRT band is not listed for Russia).

## Threads and state

- **One `Scanner` thread per receiver** (dongle), all on one `ScanState`. A thread talks to the window
  only through callbacks (`on_start`, `on_tune`, `on_window`, `on_hit`, `on_record`, `on_end`), each
  called with the receiver id first, that the window wraps in `GLib.idle_add`. Never touch GTK from a
  scanner thread.
- **Multi-receiver plan** (`ScanState.pick`): the hops have disjoint own intervals (`Band.hops`), a hop
  is claimed by one receiver at a time (`claims`), listen windows are clipped to the hop, so two
  receivers never analyse the same frequency. A receiver takes the free hop with the fewest visits,
  then the fewest receivers able to tune it (`coverers`: what only it reaches goes first, the HF for a
  Blog V4), then the sweep order. Coverage comes from the tuner type (`TUNERS`, learned at opening) plus
  HF (V4 upconverter, or direct sampling where the user says the dongle has it). The DC-spike shift
  alternates per hop visit (0 / -50 kHz) so the own interval stays covered.
- Shared mutable state in `ScanState` (detector memory, boosts, stations, done) is changed under
  `ScanState.lock`. The last receiver thread out closes the scan (`end_scan`) or keeps it for a resume.
- `ScanState` survives a pause ("Join" frees every dongle and opens GQRX on the one that heard the
  frequency, SIGUSR1 frees them for another app); new `Scanner`s carry on with the least visited hops.
- **Receivers** (`list_devices`, `receivers`, the profile's devices file, e.g.
  `~/.config/archangesdr/devices.json`): id = serial number, or `serial#index` when two dongles share it;
  per receiver: enabled, label, gain, hf (None = automatic), tuner and name learned at the first
  opening. `detections.device` stores the id (the Statistics tab filters on it; rows merge per receiver).
- `Store` (SQLite, one connection, a lock) is shared by the window and the scanner. Schema changes are
  additive: `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE ... ADD COLUMN` checked against
  `PRAGMA table_info`. Never drop or rename a column: users keep their history.

## The window (`gui()`)

One column, top to bottom: the scan cards (one per receiver, full width), the scan bar (receivers,
"N ranges" button opening the ranges modal, dwell, threshold, Start), then the tabs: Detection log
(filters; the former Active tab is the "active" badge on its rows), Interference, Statistics,
Settings. The whole column is in `scroll_column`. Buttons that carry an action have an icon and a text
(`icon_button`); Start / Stop use the `primary` / `danger` CSS classes (white text) rather than the
theme's `suggested-action`, which some GTK themes draw with dark text. Themes: "Dark" and "Light" draw GTK's built-in theme and icons with the app's palettes
(`PALETTES`, a light and a dark set: scores keep their contrast); a desktop theme installed as
`~/.config/gtk-4.0/gtk.css` (Rose-Pine here: dark only, 7000 lines) outranks any app style, so `gui()`
starts GTK with a config folder of its own (`DATA_DIR/gtk-config`: the desktop's settings.ini without
the theme and icon names) and puts `XDG_CONFIG_HOME` back once GTK has read it (GLib caches it), so the
programs the app launches are not affected. "The desktop's" keeps that theme, with `DESKTOP_FIX` for
its drop-downs and menu buttons. The app's CSS is at `STYLE_PROVIDER_PRIORITY_USER + 1`, above the
user's gtk.css. An icon theme named in the settings but not installed falls back to Adwaita. Switching
to or from the desktop's theme needs a restart; accent and dark / light are applied by
`apply_theme` (live, no restart); language and region need a restart (`restart()` re-executes `ARGV`),
because the strings and `CONF` are read at import.

## Transcription

- Optional, after the recording: `Recording.close` queues it (`Store.request_transcript`) when the
  engine is on and "auto" is ticked; `Transcriber` (a thread of the window process, never the scanner
  threads) takes the oldest pending one, runs `transcribe()`, stores the text (`transcripts`, plus the
  FTS5 table `transcripts_fts` for the log's search; LIKE when SQLite has no FTS5).
- Engines: `whisper-cli` as a subprocess at nice 19 (`-oj` JSON output, `-l auto`), probed under
  several names (`WHISPER_BINARIES`); or any OpenAI-compatible `POST /audio/transcriptions` with
  urllib (multipart built by hand, `verbose_json` then `json` when a server refuses it). Presets in
  `API_PRESETS` are starting points (the Ollama and Scaleway model names are unverified). Claude has no
  audio input: do not add it.
- Models: `WHISPER_MODELS` (the compressed multilingual files: q5 is a third of the size for almost the
  same accuracy), installed by `download_model` into `MODELS_DIR` (`.part` then renamed, cancellable)
  only when the user clicks Install; `WHISPER_DEFAULT` is base.
- `clean_transcript` drops Whisper's hallucinations on noise (subtitle credits, a phrase repeated);
  recordings under `TRANSCRIBE_MIN_S` are not sent.
- Settings live in the profile's settings file (`load_settings` / `save_settings`, mode 600: it holds
  API keys). Never log or display a key; error messages carry the HTTP code and the server's text only.

## Join and notifications

- `JOIN_PROGRAMS` (gqrx: config + remote control; sdrpp: launched, then rigctl on 4532; rtl_fm:
  `RTL_FM_COMMAND`) and the user's commands (`settings["join"]["commands"]`, ids `cmd:<n>`): templates
  filled by `fill_template` (every value `shlex.quote`d, unknown `<name>` left as is) and run with
  `sh -c` in their own process group; `stop_joined` kills that group when the scan resumes.
- ntfy: `notify_recording` runs in a thread when a `Recording` closes; `ntfy_wanted` applies the
  conditions; `ntfy_send` POSTs the message (title and tags as query parameters, UTF-8 safe) or PUTs the
  WAV with `filename`/`message` parameters; the token goes in `Authorization: Bearer`, never in the URL.
  Settings in `settings["ntfy"]`.

## Files and profiles

- The **profile** (`ubonsole`, `archsdr`, `standalone`) decides where settings, ranges and data live,
  so the scanner reuses the files of the desktop it runs in. Do not move these paths: the desktops'
  scripts read them.
- `lang/<lang>.sh`: UI strings in **bash syntax** (`L_KEY='value'`, a quote is `'\''`), shared with the
  desktops' shell scripts. `en.sh` is the fallback. **Every new string goes into the four files.**
  Plurals are `KEY_1` / `KEY_N` through `P()`. Check: every `T("L_...")` key exists in each language.
- `ranges/<region>/<lang>.json`: default ranges, a list of `{label, lo_mhz, hi_mhz, mode, section,
  enabled}`; mode is one of AM, NFM, FM, USB, LSB, WFM. `eu fr uk de es us ca` come from uBonsole's
  `tools/gen-frequencies.py` (edit them there); `br ar cl co sa jp cn ru au` come from
  `tools/gen-ranges.py` here (edit the script, then run it; never hand-edit its output).
  Rules: analog voice only (no digital voice, no data), never a "do not listen" range (police,
  emergency services, mobile phones), HF and > 20 MHz ranges unticked, the last section states how the
  region treats listening. Each region's sources are in the comments of `tools/gen-ranges.py`.
- A new region also needs its date format in `DAY_FMT` and a line in the README's Regions table.

## Testing

The dongle is not always plugged in; the tests need none.

- **`python3 -m unittest`** (about 40 s, the standard library and numpy only, runs in a CI as is):
  `tests/test_static.py` (Python 3.8 syntax, `bash -n`, every string in the four languages with the
  same %-arguments, the default ranges), `test_dsp.py` (helpers, demodulation, speech criteria),
  `test_detector.py` (synthetic scenes through survey and analyze: speech in NFM, AM, USB, LSB; music,
  carrier, wide signal, burst, noise, two speakers, FM stations; other sample rates; the detector's
  memory), `test_scanner.py` (the sweep plan and whole scans on fake receivers, recording included),
  `test_soapy.py` (a fake SoapySDR module). `tests/support.py` has the speech generator (glottal
  pulses, formants, syllables: invented, no real recording), the emitters, `Scene` and `FakeSdr`.
- The detector's numbers (score, SNR, frequency) are compared with `tests/baseline.json` within a margin.
  After a deliberate change of the processing: `python3 -m tests.test_detector --update-baseline`, then
  read the diff of the JSON. A verdict that changes is a regression, not a baseline to update.
- `ARCHANGESDR_PROGRAM=/path/to/archangesdr python3 -m unittest` tests another copy (an installed one, a
  modified one: break a constant and check that a test fails).
- `archangesdr --cli 144-146 --passes 2` with a dongle: every signal, its criteria and the verdict.
- Without a dongle: load the file as a module (`importlib.machinery.SourceFileLoader`), give a
  `Scanner` a fake SDR object (`tune`, `read` returning complex64 IQ at 2.4 MS/s) and call
  `scanner.listen(...)`. Point `XDG_DATA_HOME` / `XDG_CONFIG_HOME` at a temporary folder and pass
  `--profile standalone` so the user's history is never touched.
- The window: GTK keeps **one instance per application id**. If the user's ArchangeSDR is running,
  launching `./archangesdr` only raises their window and your code never runs. Test a copy with another
  `application_id` (`sed 's/io.github.bt0r.archangesdr/io.github.bt0r.archangesdrtest/'`). A harness that
  imports GTK itself must set `GDK_DEBUG=no-portals` first, or it hangs on the user's desktop portal.
  Screenshots without a screenshot tool: `Gtk.WidgetPaintable.new(win)` → `Gtk.Snapshot` →
  `win.get_renderer().render_texture(node, None).save_to_png(path)`.
- Several receivers without hardware: replace `RtlSdr` (needs `coverage`, `tune`, `read`,
  `start_stream`, `stop_stream`, `close`, `name`, `tuner`, `hf`, `gain`, `direct`) and `list_devices`.
- Syntax and strings: the Python 3.8 check above, `bash -n lang/*.sh`, `bash -n install.sh`.
- GTK versions: Ubuntu 22.04 ships GTK 4.6, Debian 12 GTK 4.8. A call added later goes behind a check
  with a fallback (`fg_color` for `get_color()` 4.10, `check_label` for `CheckButton.set_child()` 4.8,
  `color_button` for `ColorDialogButton` 4.10, the file chooser's `Gtk.FileDialog` 4.10).

## Screenshots

The README shows `docs/screenshots/main.png` and links the others. **Regenerate them after any visible
change to the window** (layout, strings, colours) and look at every image before committing:

```bash
tools/screenshots.py          # → docs/screenshots/*.png (about 30 s)
```

- Needs `gtk4-broadwayd` (GTK's headless display: `gtk4` on Arch, `libgtk-4-bin` on Debian / Ubuntu).
  Nothing appears on screen, the size is fixed (1280 × 860 for `main`, 1280 × 1060 for the tabs), and an
  ArchangeSDR already running is not disturbed (its own application id).
- It runs the real window in a temporary home (`$TMPDIR/archangesdr-demo`, removed afterwards: the
  user's settings and history are never read) with two simulated receivers and a made-up history:
  `HEARD`, `STATIONS`, `INTERFERENCE` and `RECEIVERS` at the top of the script. Keep the demo data
  invented (no real recordings or transcripts) and plausible for Europe.
- The scan state of `main.png` is not a running scan: the script calls the window's own handlers
  (`on_tune`, `on_record`, `on_window`, `show_banner`) with fixed spectra, so every run gives the same
  picture.
- Steps run one after the other (`do` / `take`): a screenshot is saved before the next step changes the
  window. A new screenshot is a `take(...)` line, plus a link in the README's caption.
- Files: `main.png` (README), `main-light.png`, `log-search.png`, `statistics.png`, `interference.png`,
  `settings.png`, `settings-transcription.png`, `ranges.png`.

## Conventions

- English everywhere in the repository (code, comments, docs, commit messages); the UI is translated
  through `lang/`.
- Comments say why, in the style already there; constants with a unit and a reason at the top of the
  file.
- `install.sh` installs per user (`~/.local/share/archangesdr/app`, `~/.local/bin/archangesdr`), no
  root. It lists missing dependencies with the command of the detected distribution.
- Legal: the tool listens and records; it never decodes encrypted traffic, and the default ranges never
  include what must not be listened to. Keep it that way.
