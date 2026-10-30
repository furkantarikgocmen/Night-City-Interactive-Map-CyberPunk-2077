# Map Data Update History

Each upstream map-data refresh is documented in this directory before it is committed.

## Updates

- [2026-10-30](2026-10-30.md) — 14 new locations, including seven Phantom Liberty main jobs, six vehicle contracts, and the Page of Swords tarot card
- [2026-10-28](2026-10-28.md) — 15 new locations, including Clampdown and the Night City Prison/BD Therapy cluster
- [2026-10-26](2026-10-26.md) — 46 additions, one removal, Glamdoc, and the v11 marker sprite

## File naming

Use the refresh date in ISO 8601 format:

```text
YYYY-MM-DD.md
```

If more than one refresh is intentionally kept for the same day, append a short sequence such as `YYYY-MM-DD-2.md`.

## Required contents

Every update record should include:

- Source URLs and refresh date
- Old and new totals
- Every added and removed location, including its ID, category, and region
- Existing locations whose metadata or descriptions changed
- Category, region, tile, and marker-sprite changes
- Validation results and any unresolved compatibility issues
- Commit status

