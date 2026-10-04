# Proton Scout 1.1 validation

2026-10-04:

- 38 automated tests passed. New regression cases cover hidden single-report profiles, unknown/string/quoted options, missing-vs-out-of-box evidence, Hotfix freshness and variant parsing, near-tied versions, contributor deduplication, GPU model distinctions, GE naming aliases, command normalization and conditional discussion context.
- Live Steam search resolved Crimson Desert to app 3321460 (the store currently returns the name Crimson Desert Enhanced). Related soundtrack/DLC entries remain separate IDs.
- Live ProtonDB requests returned 120 PC reports for Crimson Desert. They were deduplicated and analyzed against explicitly chosen NVIDIA RTX 4070, NVIDIA RTX 5070 Ti and AMD RX 7900 XTX test profiles. These are test inputs, not the recipient's hardware.
- Launch profiles were present and displayed by the analysis even when they did not satisfy automatic recommendation criteria. Hotfix did not qualify as a current candidate in those three test profiles.
- Python compilation and JavaScript syntax checks passed.
- Chromium browser integration passed against the captured live Crimson Desert sample: search, selecting a game, refresh, profile display, specific source links, source context expansion and clipboard copy. Eight parsed profiles had copy buttons; 166 report links were rendered. No JavaScript page errors. Desktop screenshots were inspected and a 390-pixel mobile viewport had no horizontal overflow.
- The Crimson sample exposed 58 profiles from 108 reports after contributor deduplication.
- No game benchmark or testing on the recipient's actual PC was performed. Public JSON interfaces, game patches and rolling Proton builds can change. Source reports may contain inaccuracies or omitted details.

No fetched report dataset is bundled. Regression fixtures are synthetic.
