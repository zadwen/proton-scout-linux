# Proton Scout 1.0

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

## Recommendations and limitations

- Fetches the ProtonDB summary and up to three pages of detailed **PC** reports (typically 120). It does not claim to analyze the full database.
- Deduplicates reports. Reports with explicit success/failure and a named version in the last 365 days contribute to ranking. Native, unknown and unnamed custom versions are excluded from Proton ranking.
- Weight = 1 for reports within 90 days, 0.6 for 91–180 days, 0.3 for 181–365 days; doubled for matching GPU vendor. Evidence score = `(weighted successes + 1) / (weighted successes + weighted failures + 2)`.
- A candidate needs at least two positive reports, score >= 0.6, and at least one report within 180 days. Moderate evidence additionally needs five positives, three GPU-vendor matches and score >= 0.75. Scores are **not** performance measurements or success probabilities. Repeated reports from the same contributor may affect rankings; only identical reports are deduplicated.
- CPU, driver, resolution, and settings are displayed when available but not automatically performance-matched. A matching vendor is not the same GPU. On hybrid systems either vendor can match.
- A copyable launch profile needs the same complete command string in at least two successful reports from the last 180 days, using the candidate version and matching GPU vendor. Known numeric environment overrides and detected `gamemoderun` / `mangohud` wrappers are accepted. Simple dash-prefixed game arguments are also accepted. Profiles with complex arguments, shell syntax, unrecognized options or unavailable wrappers remain in the notes, not the copy box. These are community proposals, not verified fixes. Options may be obsolete for newer versions; consult the linked documentation.
- No community command is executed. No drivers, Proton versions, Steam settings or game files are modified. You choose and test changes in Steam.
- No maximum-FPS guarantee. Online modes and anti-cheat support must be checked independently. A good overall rating does not prove multiplayer works.
- Native Linux games may not need Proton. Check the Steam store platform support and test the native build separately.
- Installed tools are listed, but no automatic tool installation or switching is performed. Store search can include demos and DLC: verify the exact edition / app ID.

## Live data & offline behavior

Steam store search and ProtonDB public website JSON formats are external interfaces and may change without notice. The detailed-report adapter uses the website's public data-key format. It is isolated in `DataClient.reports` and `report_hash` in `core.py` for maintenance. A missing/changed endpoint produces a visible availability message and no fabricated report recommendation. Summary ratings are never used to invent a Proton version.

Search is cached for 24 hours, summaries/reports for one hour, counts for three minutes. A network failure may return stale cached data, visibly labeled. Refresh bypasses the freshness window but can still fall back to marked stale data. Cache: `${XDG_CACHE_HOME:-~/.cache}/proton-scout`.

**Validation:** Live Steam search, ProtonDB summaries and detailed PC reports were fetched during development. Core ranking, parsing, offline behavior and server protections have automated tests. These external website interfaces can still change later; failures are shown in the app. Performance improvements require testing on your own gaming PC.

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
