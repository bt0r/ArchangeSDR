# Favorites: design

Date: 2026-11-20. Status: approved by the user in conversation.

## Why

Some frequencies come back often in the detection log. In a big scan (hundreds of hops, most of them
silent), they are visited no more often than any empty hop, so conversations on them are missed. The
user wants to mark those frequencies as favorites, by hand or automatically, and have the scan come
back to them **more often**, while still sweeping the wide ranges.

In the same change, the log row's two play buttons ("Preview" and "Listen") become one.

## Goals

1. **One play button per log row.** It shows "Preview (2.5 s)" (the capture, `PREVIEW_ICON`) while the
   row has no complete recording; once the row's `recording` exists (written by `Store` when the
   `Recording` closes), the same place shows "Listen (N s)" (the recording) instead. The Interference
   tab keeps its Preview button as it is.
2. **A star button right of the bug button**, on speech rows (`kind = 'voice'`), toggling the row's
   frequency as a favorite. Filled star (`starred-symbolic`) when it is one, outline
   (`non-starred-symbolic`) otherwise; tooltip says which action a click does.
3. **A "Favorites" tab** right of the Interference tab (before Statistics), star icon. One row per
   favorite: frequency, name, mode, number of speech conversations heard there, last heard, a Listen
   button for the last recording (or Preview if none), an "auto" mark for auto-added ones, and the star
   to remove it. Tab title shows the count, like the other tabs.
4. **A setting** in Settings › Recordings: "Automatically add frequently heard frequencies to
   favorites", **off by default**. Rule: **5 successful listens** at the frequency (speech conversations, `kind = 'voice'`, the frequency not banned as interference), with **no time limit** (changed by the user after approval: no 7-day window).
5. **Favorites are scanned more often**: each favorite hop is visited `FAVORITE_WEIGHT` = 4 times per
   pass instead of once.

## Non-goals

- Favorites are not the whitelist: they keep the speech test, are not exempt from muting / banning
  beyond what already exists. The two stay separate features.
- No time-based revisit (the recency boost stays as it is, unrelated).
- No editing of favorite parameters in the Favorites tab beyond what the ranges dialog already allows.

## Anti-goals

- An auto-added favorite the user removed must **never come back by itself**; otherwise removing is
  pointless.
- The whole log must not be rebuilt on a star click (see "Lists are updated row by row" in AGENT.md):
  the star changes in place like the Play buttons.
- Favorites must not slow down the scan of the other ranges beyond their weight (a favorite is one
  narrow hop: 4 × 0.16 s per pass).

## Approaches considered

- **A. A "Favorites" group in the ranges only.** Simple, but a favorite hop is visited once per pass
  like any other: in a big scan it changes nothing. Rejected: does not meet the why.
- **B. A permanent revisit timer** (like the recency boost: a 0.1 s survey every X s). Works, but a
  second scheduling mechanism outside the hop plan, harder to share between receivers.
- **C. A "Favorites" group in the ranges + a weight in the hop plan.** Chosen by the user. Favorites
  are ranges (tickable, editable, deletable in the ranges dialog like any other), and
  `ScanState.pick` visits a favorite hop `FAVORITE_WEIGHT` times per pass. One plan, works with
  several receivers, the pass count stays right.

## Design

### Storage

- A favorite is a `Band` in `ranges.json`: `lo` / `hi` = frequency ± 6.25 kHz, the row's mode, label =
  the row's range label as it is (e.g. "PMR446", never with the frequency appended: `Store.hit` stores
  `band.label`, and the Statistics filters and colours go by label, so hits on a favorite hop count
  under the same range as before; the UI shows the frequency next to it), enabled, and a new field
  `favorite`: `"manual"` or `"auto"` (absent / None for ordinary ranges; `to_dict` / `from_dict` carry
  it). Its `section` is the translated "Favorites" group name (a new string), but code identifies
  favorites by the `favorite` field, never by the section name (it changes with the language).
- A frequency "is a favorite" when an existing favorite band contains it (match on the 6.25 kHz key
  ±1 key, as `FreqRules` does). Toggling off deletes that band.
- Refused favorites: `settings["favorites"]["refused"]`, a list of 6.25 kHz keys. **Any** removal of a
  favorite (manual or auto, by the star, the Favorites tab or the trash button of the ranges dialog)
  adds its key there, so auto-add never brings back what the user took away. Adding it back by hand
  removes the key.
- Unticked in the ranges dialog, a favorite stays a favorite (filled star, row in the tab marked
  "paused", counted, blocks auto-add) but is not scanned. The favorite state lives in one place: the
  bands with a `favorite` field.
- Setting: `settings["favorites"]["auto"]` (bool, default False).

### Scan weight

- `ScanState` hops get a `weight` (4 for a favorite band, 1 otherwise); `passes` is
  `min(visits // weight)`; `max_passes` compares against `visits // weight`.
- **The extra visits are spread evenly through the pass** (builder's call, from the review): a plain
  `visits / weight` ordering in `pick` would give the favorite its 4 visits back to back at the end of
  each pass, then nothing for a whole pass, which defeats the why. A favorite hop is due again once
  about 1 / weight of the pass has gone by since its last visit (e.g. its due point measured in
  ordinary-hop picks); the exact key is the builder's, the test is: with one receiver and N ordinary
  hops, the gaps between a favorite's visits are about N / 4 picks, never 0 in a row.
- A favorite added or removed while a scan runs takes effect live (`ScanState` adds / drops its hops
  under its lock); a removed hop that is claimed is dropped when released.
- A favorite that lies inside another enabled range is covered twice per pass. Accepted: that is
  "more often".

### Auto-add

- Checked in the window process when a **new speech row** is stored (`App.on_hit` with `new` true), if
  the setting is on: count `kind = 'voice'` detections within ±1 6.25 kHz key of the frequency, over the
  whole history. At 5 or more, the frequency not banned (`FreqRules.banned`), and the key neither a
  favorite nor refused, add a
  favorite with `favorite = "auto"` and show a short banner (`show_banner`) saying so.
- Constants at the top of the file: `FAVORITE_WEIGHT = 4`, `FAVORITE_AUTO_N = 5`,
  `FAVORITE_HALF_HZ = 6_250`.

### UI

- Log row: the single play button replaces the two current ones (`build_journal` row builder near
  `L_SCN_PREVIEW` / `L_SCN_LISTEN`). The row signature must include whether the recording exists, so
  the row is rebuilt once when the recording lands (already the case if the signature carries
  `recording`).
- Star: `plain` CSS class like the bug, placed right after it, voice rows only.
- Favorites tab: same paging / row-by-row `sync` pattern as the Interference tab, built only while
  shown. Its list is the favorite bands joined with the detection counts.
- New strings in the four `lang/*.sh` files: tab title (+ count), group name, star tooltips (add /
  remove), "auto" mark, setting label and tip, banner, empty-tab text.

### Docs and checks

- README: Features (favorites, auto-add, single play button), Usage (the star, the tab, the setting).
- AGENT.md: the favorite weight in the scan plan, the `favorite` field, the refused list.
- Screenshots regenerated (`tools/screenshots.py`), the demo data gets a couple of favorites and a
  `favorites.png` of the new tab.
- Tests: `pick` with weights (a favorite visited 4× per pass, `passes` right, two receivers),
  `Band` round trip with `favorite`, auto-add rule (threshold, window, refused), strings in four
  languages (existing static test).

## Left to the builder

- Exact column layout of the Favorites tab rows and the star's tooltip wording.
- Whether the auto-add count query reuses `FreqRules`' key helpers or its own SQL.
- How the live hop add / remove is wired between the window and `ScanState`.
