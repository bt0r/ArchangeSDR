# Favorites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Favorite frequencies (starred by hand or added automatically) that the scan visits 4 times per pass, a Favorites tab, and one play button per log row.

**Architecture:** A favorite is a narrow `Band` carrying a `favorite` field ("manual" / "auto") in `ranges.json`. `ScanState` gives favorite hops a weight and spreads their extra visits through the pass. Pure helpers at module level hold the favorite rules (toggle, refused list, auto-add count), so they are tested without GTK; the window only wires them to a star button, a tab and a setting.

**Tech Stack:** Python 3.8, numpy, PyGObject GTK 4, SQLite, `unittest`. Single file `archangesdr`.

**Spec:** `docs/superpowers/specs/2026-11-20-favorites-design.md`

## Global Constraints

- One Python file `archangesdr`, no new dependency, Python 3.8 syntax (check: `python3 -c "import ast; ast.parse(open('archangesdr').read(), feature_version=(3, 8))"`).
- GTK 4.0+ API; newer calls behind a check. Icons `starred-symbolic` / `non-starred-symbolic` (Adwaita, present since GTK 4.0 themes).
- Constants at the top of the file with unit and reason: `FAVORITE_WEIGHT = 4`, `FAVORITE_AUTO_N = 5`, `FAVORITE_HALF_HZ = 6_250`.
- Every new string in `lang/en.sh`, `fr.sh`, `de.sh`, `es.sh` with the same %-arguments (bash syntax, `'\''` for a quote).
- Lists are updated row by row (`App.sync`); the Favorites tab is built only while shown; no whole-list rebuild on a star click.
- English in code, comments, docs and commit messages. The README and AGENT.md change in the same commit as the code they describe.
- Never touch the user's history in tests: use `tests.support.app()` and a temporary `Store`.
- Work on the current branch (`standalone-only`); the user asked for no new branch.

## Review Focus

1. **Starring while a scan runs**: the new favorite's hop is appended live; receivers keep scanning, claim indices of other hops stay valid. → test in Task 2.
2. **Removing a favorite whose hop is claimed right now** by a receiver: no crash, the hop is never picked again, `release` on it still works. → test in Task 2.
3. **Starring a frequency 1 key away from an existing favorite** (e.g. 446.00625 vs 446.0125 MHz): no second favorite; the star shows filled. → test in Task 1.
4. **"Replace with the region's ranges"** in the ranges dialog (`confirm_preset`) must keep the favorites, a reasonable user would not expect a preset to wipe them. → test in Task 1 (`with_favorites`), wired in Task 5.
5. **A favorite unticked in the ranges dialog**: not scanned (no hop), still blocks auto-add and shows in the tab as paused. → test in Task 3.

---

### Task 1: Favorite bands and their rules

**Files:**
- Modify: `archangesdr` (constants near `BAN_PARASITE`; `Band` at ~441; new helpers right after `save_ranges` ~519)
- Test: `tests/test_favorites.py` (new)

**Interfaces:**
- Produces:
  - `Band(lo, hi, label, mode, section, enabled=None, color=None, favorite=None)`; `band.favorite in (None, "manual", "auto")`; `to_dict` writes `"favorite"` only when set; `from_dict` reads it.
  - `fav_key(freq: float) -> int` (= `FreqRules.key`, 6.25 kHz steps; make `FreqRules.key` call it).
  - `favorite_of(bands, freq) -> Band | None`: the favorite band whose centre key is within ±1 key of `freq`'s.
  - `favorites_conf(settings: dict) -> dict`: `settings.setdefault("favorites", {})` with defaults `auto=False`, `refused=[]`.
  - `add_favorite(bands, settings, freq, label, mode, kind="manual") -> Band`: returns the existing favorite if `favorite_of` finds one, else appends `Band(freq - FAVORITE_HALF_HZ, freq + FAVORITE_HALF_HZ, label, mode, T("L_SCN_FAV_GROUP"), True, favorite=kind)`; removes `fav_key(freq)` from `refused`.
  - `remove_favorite(bands, settings, band) -> None`: removes it from `bands`, appends its centre key to `refused` (once).
  - `with_favorites(new_bands, old_bands) -> list`: `new_bands` plus the favorites of `old_bands`.
  - Callers save: `save_ranges(bands)` and `save_settings(settings)`; the helpers do no I/O.

- [ ] **Step 1: Write the failing tests** in `tests/test_favorites.py`, class `Bands`:
  - `test_round_trip`: `Band.from_dict(b.to_dict()).favorite == "auto"` for a favorite; an ordinary band's dict has no `"favorite"` key.
  - `test_add_is_narrow_and_named_like_the_range`: `add_favorite([], s, 446.00625e6, "PMR446", "NFM")` → `lo == 446.00625e6 - 6250`, `hi == 446.00625e6 + 6250`, `label == "PMR446"`, `favorite == "manual"`, `enabled is True`, exactly 1 hop.
  - `test_neighbour_key_is_the_same_favorite` (Review Focus 3): adding 446.0125e6 after 446.00625e6 returns the same object, `len(bands) == 1`; `favorite_of(bands, 446.0125e6)` is it; `favorite_of(bands, 446.025e6)` is None.
  - `test_remove_refuses_and_add_unrefuses`: remove → `fav_key(f) in favorites_conf(s)["refused"]`, removing twice-added keys stays one entry; `add_favorite` again → key gone from `refused`.
  - `test_preset_keeps_favorites` (Review Focus 4): `with_favorites([new], [old_range, fav])` == `[new, fav]`.

- [ ] **Step 2: Run** `python3 -m unittest tests.test_favorites -v` → FAIL (`AttributeError: ... 'add_favorite'`).
- [ ] **Step 3: Implement** the constants, the `Band` field, and the helpers listed above; `L_SCN_FAV_GROUP` in the four languages (en `Favorites`, fr `Favoris`, de `Favoriten`, es `Favoritos`).
- [ ] **Step 4: Run** `python3 -m unittest tests.test_favorites tests.test_static -v` → PASS.
- [ ] **Step 5: Commit** `git add archangesdr lang tests/test_favorites.py && git commit -m "Favorites: narrow bands with a favorite field, refused list"`

### Task 2: Weighted, spread hop plan with live add / remove

**Files:**
- Modify: `archangesdr` `ScanState` (~2117-2215), `Scanner` uses of `st.hops` (check `hop_of`, `revisit`)
- Test: `tests/test_scanner.py` class `Plan`

**Interfaces:**
- Consumes: `Band.favorite` (Task 1).
- Produces:
  - Each hop dict gains `"weight"` (`FAVORITE_WEIGHT` if `band.favorite` else 1), `"phase"` (float in [0, 1)) and `"gone"` (bool).
  - `ScanState.add_band(band) -> None` (appends its hops at the end, under the lock, `_count()` again); `ScanState.remove_band(band) -> None` (marks its hops `gone`; `self.bands` updated).
  - `passes` = `min(visits // weight)` over hops not gone; `max_passes` compares `visits // weight`.

`pick` ordering (the algorithm the tests do not fully determine):

```python
due = (h["visits"] + h["phase"]) / h["weight"]
key = (int(due), h["coverers"], due, i)     # pass first, then coverage, then place in the pass
```

Ordinary hops: `phase = i / n_ordinary` in sweep order (keeps today's order). Favorites: `phase = (j + 0.5) / n_favorites`, j their index among favorites. Gone hops are skipped. Recompute phases in `__init__` and `add_band`.

- [ ] **Step 1: Write the failing tests:**
  - `test_favorite_four_visits_spread`: 40 one-hop ordinary bands + 1 favorite, one receiver; pick/release 41×4 = 164 times; favorite picked exactly 16 times (4 per pass, `passes == 4`); the gaps between its consecutive picks are all ≥ 5 (never back to back).
  - `test_pick_by_coverage_and_visits` still passes unchanged.
  - `test_add_band_live` (Review Focus 1): claim hop 0 with receiver A, `add_band(fav)`, `release(0, True)` works, next picks reach the new hop, `hop_of(fav, centre)` is its index.
  - `test_remove_claimed_band` (Review Focus 2): A claims the favorite's hop, `remove_band(fav)`, `release(i, True)` does not raise, the hop is never picked again, `passes` ignores it.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_scanner -v` → new tests FAIL.
- [ ] **Step 3: Implement** the hop fields, `pick`, `passes`, `add_band`, `remove_band`; `hop_of` and the recency boost skip gone hops.
- [ ] **Step 4: Run** `python3 -m unittest tests.test_scanner -v` → PASS.
- [ ] **Step 5: Commit** `git commit -am "Scan plan: favorites visited FAVORITE_WEIGHT times per pass, spread"`

### Task 3: Auto-add rule (5 successful listens, no time limit)

**Files:**
- Modify: `archangesdr` (`Store`, a helper after the Task 1 helpers)
- Test: `tests/test_favorites.py` class `Auto`

**Interfaces:**
- Consumes: Task 1 helpers.
- Produces:
  - `Store.voice_count(freq: float) -> int`: `kind = 'voice'` detections (whole history) with `fav_key(freq)` within ±1 of `fav_key(detection freq)` (SQL range `ABS(freq - ?) < 1.5 * 6250` is acceptable).
  - `auto_favorite(store, bands, settings, freq, label, mode) -> Band | None`: None unless `favorites_conf(settings)["auto"]`, the key is not refused, `store.rules.banned(freq)` is false, `favorite_of(bands, freq)` is None (ticked or not), and `store.voice_count(freq) >= FAVORITE_AUTO_N`; then `add_favorite(..., kind="auto")`.

- [ ] **Step 1: Write the failing tests** (temporary `Store` as in `tests/test_recordings.py`, rows inserted with `INSERT INTO detections (freq, kind, first_seen, last_seen, hits) ...`):
  - `test_five_listens_add`: 5 voice rows at 145.500e6, some of them 60 days old (no time limit) → returns a band, `favorite == "auto"`.
  - `test_four_or_interference_do_not`: 4 rows → None; 5 `parasite` rows → None; 5 voice rows but the frequency banned (`store.rules.ban(...)`) → None.
  - `test_off_refused_or_existing_do_not`: setting off → None; key refused → None; an existing favorite **unticked** (Review Focus 5) → None and no second band.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_favorites -v` → FAIL.
- [ ] **Step 3: Implement** `Store.voice_count` and `auto_favorite`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -am "Favorites: automatic add after FAVORITE_AUTO_N conversations"`

### Task 4: One play button per log row

**Files:**
- Modify: `archangesdr` `det_row` (~4458-4464)

**Interfaces:** none new.

- [ ] **Step 1: Change** `det_row`: if `r["recording"]` exists on disk → only `play_button(r["recording"], T("L_SCN_LISTEN", ...), T("L_SCN_REC_TIP", ...))`; elif `r["audio"]` exists → only the Preview button. The Interference tab's `rule_row` is unchanged. The row signature already carries `r.values()` (the `recording` path), so the row is rebuilt once when the recording closes: check it by reading `refresh_lists`.
- [ ] **Step 2: Verify** in a copy with another application id (AGENT.md › Testing): a row with only a clip shows "Preview", a row with a recording shows "Listen" only. Run `tools/screenshots.py` and look at `main.png`.
- [ ] **Step 3: Run** `python3 -m unittest` → PASS.
- [ ] **Step 4: Commit** `git commit -am "Log: one play button, Preview until the recording is complete, then Listen"` (README: the log's buttons, if it names both).

### Task 5: Star button and window wiring

**Files:**
- Modify: `archangesdr` (`det_row` after the bug button; new `App.toggle_favorite`, `App.favorites_changed`; `delete_range`, `confirm_preset`, `rebuild_ranges` group title), `lang/*.sh`

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces: `App.toggle_favorite(r: dict) -> None` (row of the log); `App.favorites_changed(added=None, removed=None) -> None`: `save_ranges(self.bands)`, `save_settings(self.settings)`, `self.state.add_band` / `remove_band` when a scan exists, `self.rebuild_ranges()`, `self.refresh_lists()`.

- [ ] **Step 1: Implement** the star (`plain` CSS class, `valign=CENTER`, voice rows only, icon `starred-symbolic` if `favorite_of(self.bands, r["freq"])` else `non-starred-symbolic`, tooltip `L_SCN_FAV_ADD_TIP` / `L_SCN_FAV_REMOVE_TIP`); add the favorite state to the row signature so only that row is rebuilt. `delete_range` of a favorite goes through `remove_favorite`; `confirm_preset` uses `with_favorites`; the ranges dialog titles favorite bands' group with `T("L_SCN_FAV_GROUP")` whatever the stored section.
- [ ] **Step 2: Strings** (four languages, same arguments): `L_SCN_FAV_ADD_TIP='Add %s to favorites: scanned %d times per pass'`, `L_SCN_FAV_REMOVE_TIP='Remove %s from favorites'` (fr: `'Ajouter %s aux favoris : scannée %d fois par passe'`, `'Retirer %s des favoris'`).
- [ ] **Step 3: Verify** in a test copy: star a row, it fills, the ranges dialog shows it under Favorites; unstar, it goes; during a running fake scan (no dongle: `FakeSdr` harness or the screenshots script's receivers) nothing crashes.
- [ ] **Step 4: Run** `python3 -m unittest` → PASS.
- [ ] **Step 5: Commit** `git commit -am "Log: star button to add or remove a favorite"`

### Task 6: Favorites tab

**Files:**
- Modify: `archangesdr` (tabs ~3465-3482, `refresh_lists`, new `App.fav_row`), `lang/*.sh`

**Interfaces:**
- Consumes: Tasks 1, 3 (`Store.voice_count`), 5 (`favorites_changed`).
- Produces: `self.fav_page`, `self.fav_list`, `self.fav_tab_label`; `App.fav_row(band, n, last, rec, audio) -> Gtk.Widget`.

- [ ] **Step 1: Implement** the tab between Interference and Statistics (`tab("starred-symbolic", ...)`, a hint label, `self.paged(self.fav_list, ...)` like the rules tab). In `refresh_lists`, when the tab is shown: for each favorite band, `n = voice_count(centre)`, the last voice detection near it (`last_seen`, `recording`, `audio`); rows via `self.sync`, key = band key. Row: `fmt_mhz(centre)`, label, mode, `P("L_SCN_FAV_LINE", n, n, when)` or `L_SCN_FAV_NEVER`, `L_SCN_FAV_AUTO` mark, `L_SCN_FAV_PAUSED` when unticked, one play button (Listen, else Preview), the filled star (removes via `favorites_changed`). Tab title `L_SCN_TAB_FAV_N` with the count, else `L_SCN_TAB_FAV`. Empty text `L_SCN_NO_FAV`.
- [ ] **Step 2: Strings** (en / fr): `L_SCN_TAB_FAV` Favorites / Favoris; `L_SCN_TAB_FAV_N` Favorites (%d) / Favoris (%d); `L_SCN_FAV_HINT` 'Favorites are scanned %d times per pass. Star a speech row in the log to add one.' / 'Les favoris sont scannés %d fois par passe. Mets une étoile sur une ligne de parole du journal pour en ajouter.'; `L_SCN_FAV_LINE_1` / `_N` '%d conversation · last heard %s' / '%d conversations · last heard %s' (fr '... · dernière écoute %s'); `L_SCN_FAV_NEVER` never heard / jamais entendue; `L_SCN_FAV_AUTO` auto / auto; `L_SCN_FAV_PAUSED` 'paused (unticked in the ranges)' / 'en pause (décochée dans les plages)'; `L_SCN_NO_FAV` 'No favorites yet.' / 'Aucun favori pour l'\''instant.'.
- [ ] **Step 3: Verify** in a test copy (and the window's minimum height: `win.measure(Gtk.Orientation.VERTICAL, -1)[0]` unchanged, ~100 px).
- [ ] **Step 4: Run** `python3 -m unittest` → PASS.
- [ ] **Step 5: Commit** `git commit -am "Favorites tab"`

### Task 7: Auto-add setting

**Files:**
- Modify: `archangesdr` (Settings › Recordings after the alert checkbox ~5019; `on_hit`), `lang/*.sh`

**Interfaces:**
- Consumes: `auto_favorite` (Task 3), `favorites_changed` (Task 5).

- [ ] **Step 1: Implement** a `Gtk.CheckButton(label=T("L_SCN_SET_FAV_AUTO"))` bound to `favorites_conf(self.settings)["auto"]` (saved with `save_settings`), and its `hint(T("L_SCN_SET_FAV_AUTO_HINT", FAVORITE_AUTO_N))`. In `on_hit`, for `new and sig["voice"]`: `band2 = auto_favorite(self.store, self.bands, self.settings, sig["freq"], band.label, sig["mode"])`; if not None → `favorites_changed(added=band2)` and `show_banner(T("L_SCN_FAV_ADDED", fmt_mhz(sig["freq"])), T("L_SCN_FAV_ADDED_BODY", FAVORITE_AUTO_N))`.
- [ ] **Step 2: Strings** (en / fr): `L_SCN_SET_FAV_AUTO` 'Automatically add frequently heard frequencies to favorites' / 'Ajouter automatiquement aux favoris les fréquences entendues régulièrement'; `L_SCN_SET_FAV_AUTO_HINT` 'A frequency heard in %d conversations (not interference) becomes a favorite. A favorite you remove is never added back by itself.' / 'Une fréquence entendue dans %d conversations (hors parasites) devient un favori. Un favori retiré n'\''est jamais rajouté tout seul.'; `L_SCN_FAV_ADDED` 'New favorite: %s' / 'Nouveau favori : %s'; `L_SCN_FAV_ADDED_BODY` 'heard in %d conversations' / 'entendue dans %d conversations'.
- [ ] **Step 3: Run** `python3 -m unittest` → PASS; verify the checkbox in a test copy.
- [ ] **Step 4: Commit** `git commit -am "Settings: add frequently heard frequencies to favorites automatically"`

### Task 8: Docs and screenshots

**Files:**
- Modify: `README.md` (Features, Usage), `AGENT.md` (scan plan weight and spread, `favorite` field, refused list, the single play button), `tools/screenshots.py` (two favorites in the demo data, a `take("favorites")`), `docs/screenshots/*.png`
- Commit the spec and this plan too.

- [ ] **Step 1: Update** the README and AGENT.md; search the README for "Preview" / "Listen" wording made wrong by Task 4.
- [ ] **Step 2: Run** `tools/screenshots.py`; look at every image (`main.png`, `favorites.png`, `settings.png`, `ranges.png`).
- [ ] **Step 3: Run** the full checks: `python3 -m unittest`, the Python 3.8 parse, `bash -n lang/*.sh install.sh` → all pass.
- [ ] **Step 4: Commit** `git add README.md AGENT.md tools docs && git commit -m "Docs: favorites"`
- [ ] **Step 5: Remind the user** that `./install.sh` copies the program to `~/.local/share/archangesdr/app` and the running window must be restarted.
