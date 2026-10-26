# Map Data Update History

Each upstream map-data refresh is documented in this directory before it is committed.

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

