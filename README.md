# Proton Scout 1.1

A Linux desktop companion for finding community-supported Proton versions and launch options. Runs a private local dashboard in your default browser. Python 3.10+ is the only required dependency; no pip packages, account, API key, or root permission required.

## Start

Extract the ZIP, open a terminal in the `proton-scout` folder, and run:

```bash
python3 app.py
```

For an applications-menu shortcut:

```bash
python3 install.py
```

Ubuntu / Zorin / Debian normally include Python 3. If missing: `sudo apt install python3`. Optional GPU model detection: `sudo apt install pciutils`. These commands are for your Linux PC, not Windows.

Search by game title or numeric Steam app ID. Installed games are detected from regular Steam, Flatpak, and common Snap locations, including libraries referenced by `libraryfolders.vdf`. Games that are owned but not installed are found through store search, not account access. Heroic/Lutris libraries are not scanned.

For custom library roots:

```bash
python3 app.py --steam-path /mnt/Games/SteamLibrary
```

Repeat `--steam-path` for multiple roots. If a browser does not open, use the local address printed in the terminal. `--no-browser` and `--port 8765` are supported. Use the app's Quit button or Ctrl+C to stop the server. Closing only the browser tab does not stop it.

## What it detects

CPU, installed RAM, GPU names/vendor, kernel, distribution, session type, GPU driver module, NVIDIA driver/VRAM when nvidia-smi is present, installed Steam compatibility tools, and optional GameMode/MangoHud executables. Hardware stays local. The app contacts Steam for search terms and ProtonDB for app IDs; like any web request, those services see your IP address.

## What changed in 1.1

The original app hid many useful report profiles behind a narrow numeric-option filter and an exact-string repetition requirement. Missing consensus could look like a recommendation to leave launch options empty. This update separates missing evidence, explicit out-of-box reports, single-report profiles and repeated profiles. Reported flags are now visible even when no Proton version qualifies.

Hotfix/Experimental now need stronger recent evidence. GE architecture aliases are merged, direct Hotfix variant fields are recognized, and duplicate reports from the same contributor count only once (latest report retained). GPU model and vendor matches are distinguished. Every version comparison explains eligibility; every profile includes report links and context.

## Update from 1.0

1. Quit the old app using its Quit button (or Ctrl+C in its terminal).
2. Extract the new ZIP to a fresh folder.
3. From that extracted `proton-scout` folder, run `python3 install.py` if you used the applications-menu shortcut before. This replaces the installed application code.
4. Reopen Proton Scout. The sidebar must say **v1.1**. Or run `python3 app.py` directly in the newly extracted folder.

## Recommendations and limitations

- Fetches up to 120 PC reports from ProtonDB (three pages); the complete game history is not analyzed. Rating totals can therefore exceed the analyzed count.
- Reports are sorted by date and deduplicated by report ID and, when present, contributor ID. The latest report from each contributor is kept.
- Only explicit version fields are used. Stable, GE, Experimental, Hotfix, native and custom variant fields are handled separately. Unnamed custom versions are not guessed from prose. Generic custom labels remain exactly as reported and may not identify a reproducible build.
- GPU model matches weigh 3; vendor-only matches 1.5; other/unknown GPUs 0.5. Age weight decays exponentially as `exp(-ageDays/45)`. Only reports up to 180 days old with an explicit success/failure verdict contribute to version ranking.
- Score is `(weighted successes + 1)/(weighted successes + weighted failures + 2)`. It is a heuristic for compatibility evidence, NOT an FPS estimate or probability.
- A candidate needs at least two GPU-matched successes within 30 days, more than twice as many recent matching successes as failures, and a score >= 0.65. Experimental and Hotfix need at least three recent matching successes because these are rolling channels.
- Eligible candidates with GPU-model evidence sort ahead of vendor-only candidates, then by score and recency. If the leading two share the same model-evidence status and differ in score by less than 0.07, the app does not force a winner. Old Hotfix/Experimental reports remain visible, but cannot by themselves establish a current candidate. No version is hard-coded as best for Crimson Desert or any other game.
- CPU, driver, kernel and report notes are shown but not automatically performance-matched. GPU model matching retains Ti/Super/XT and laptop qualifiers where supplied by the source. Model labels do not establish identical drivers, game builds, settings or laptop power limits. Hybrid systems match both detected GPUs and display a warning.
- **All explicit launch-option profiles remain visible**, including single-report, old, failed, mismatched-GPU, unknown-option and complex-command cases. Quotes and string-valued options such as `VKD3D_CONFIG=single_queue` are preserved. Simple environment assignment order is normalized for grouping; profiles from different Proton versions are not combined.
- Conditional, version-dependent, unavailable-helper and unrecognized options require manual review. Complex shell syntax is not offered by the copy button. A copy button only indicates the parser accepts the command, not that it is needed or will improve performance.
- Mentions inside report notes may describe a failed attempt or conditional workaround. They are explicitly labeled discussion and never automatically endorsed. Read the linked source and surrounding context.
- An automatic profile proposal needs exactly one eligible complete profile for the candidate Proton version, at least two recent (90-day) positive GPU-matched reports and no explicit failure reports. It still does not prove the flags caused success. Multiple conflicting profiles remain alternatives.
- Empty/missing `launchOptions` never means “no flags required.” Out-of-box evidence requires an explicit positive `verdictOob`, positive verdict, no explicit launch options and a report in the 180-day window.
- No community command is executed; Steam settings, drivers and Proton installations are never modified by Scout. Changes remain manual and reversible in Steam.
- No maximum-FPS guarantee. A positive report can still describe stutter, poor FPS or crashes. Online/anti-cheat support must be checked separately. Native Linux versions may not need Proton. Installed compatibility tools are listed but not downloaded or switched automatically.

## Live data & offline behavior

Steam store search and ProtonDB public website JSON formats are external interfaces and may change without notice. The detailed-report adapter uses the website's public data-key format. It is isolated in `DataClient.reports` and `report_hash` in `core.py` for maintenance. A missing/changed endpoint produces a visible availability message and no fabricated report recommendation. Summary ratings are never used to invent a Proton version.

Search is cached for 24 hours, summaries/reports for one hour, counts for three minutes. A network failure may return stale cached data, visibly labeled. Refresh bypasses the freshness window but can still fall back to marked stale data. Cache: `${XDG_CACHE_HOME:-~/.cache}/proton-scout`.

**Validation:** Live Steam search, ProtonDB summaries and detailed PC reports were fetched during development. Core ranking, parsing, offline behavior and server protections have 38 automated tests. Browser search, profile rendering, source links, refresh and clipboard copying were checked against a captured live Crimson Desert sample. These external website interfaces can still change later; failures are shown in the app. Performance improvements require testing on your own gaming PC.

## Import saved reports

Select a game → Import report JSON. Accepts a JSON array or `{ "reports": [...] }` in ProtonDB's detailed-report structure. This is an offline fallback, not a scraper or an automatic dump downloader. Imports are labeled user-supplied and kept in memory only. Up to 7.5 MB per file. Check that the file belongs to the selected game; rows with a different explicit appId are rejected, but rows without appId cannot be independently verified.

Expected fields per report:

```json
{
  "appId": "123",
  "timestamp": 1790985600,
  "responses": {
    "verdict": "yes",
    "protonVersion": "10.0-3",
    "notes": {"verdict": "Your actual report text"}
  },
  "device": {
    "hardwareType": "pc",
    "inferred": {"steam": {"gpu": "Actual GPU", "cpu": "Actual CPU", "os": "Actual distro"}}
  }
}
```

The above is a **schema example, not a real report**. No sample recommendations are shipped as real data.

## Sources & attribution

- [ProtonDB](https://www.protondb.com/) and each game's `/app/APPID` page — community reports and ratings.
- [ProtonDB data exports](https://github.com/bdefore/protondb-data) — official data project and licensing.
- [Valve Proton runtime configuration](https://github.com/ValveSoftware/Proton#runtime-config-options).
- [Steam store](https://store.steampowered.com/) — title search.

ProtonDB report data is made available under ODbL; individual contents under DbCL. See NOTICE.md. The app is independent of Valve and ProtonDB. No report dataset is bundled.

## Uninstall

Delete `~/.local/share/proton-scout` and `~/.local/share/applications/proton-scout.desktop`. Optionally remove `~/.cache/proton-scout`. No game settings require undoing.

## Development

```bash
python3 -m unittest discover -s tests -v
```

Standard-library backend, static HTML/CSS/JS frontend. Loopback binding, exact Host validation, per-launch secret for API access, no CORS, CSP, no external script/CDN. Does not defend against other fully privileged processes on your PC. Licensed MIT.
