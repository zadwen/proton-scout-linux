# Validation notes

Development verification, 2026-10-04 (Asia/Muscat):

- 22 automated Python tests passed: report variant normalization, GPU weighting, negative evidence, old/future dates, report deduplication, cross-game exclusion, command filtering, Steam/Flatpak/external-library discovery, stale cache labeling, API token protection, Host validation and CSP headers.
- Python compilation and JavaScript syntax checks passed.
- Real Steam title search returned The First Berserker: Khazan and related entries.
- Real ProtonDB summary and detailed PC report requests succeeded for Khazan; 25 detailed reports were analyzed without endpoint errors.
- A live Cyberpunk 2077 report page was fetched and parsed to verify official / Experimental / GE / other variants, launchOptions, concludingNotes, GPU and driver fields.
- The application has not been tested on the recipient's gaming PC, and no FPS benchmark was performed.
- Full browser visual / interaction verification was unavailable in the build environment: Chromium installation failed. The static dashboard and JavaScript were reviewed and syntax-checked, but layout and clipboard behavior still need a normal Linux browser.

No fetched community dataset or synthetic recommendations are included in this package.
