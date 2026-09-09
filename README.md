# Global Markets Macro Journal

Personal Global Markets / FICC / Macro research dashboard and daily journal.

## Site Structure

- `index.html` - GitHub Pages-compatible static website shell.
- `styles.css` - Responsive visual system for the research dashboard.
- `app.js` - Client-side rendering for market data, archive notes, calendar, glossary, and methodology.
- `data/market-data.json` - Dashboard data model. Unverified market values should remain `—`.
- `data/archive.json` - Daily briefing archive index.
- `data/daily/YYYY-MM-DD.json` - Individual daily briefing JSON files.
- `.github/workflows/pages.yml` - GitHub Actions workflow for Pages deployment.
- `.nojekyll` - Ensures GitHub Pages serves the static files directly.

## Data Discipline

This journal intentionally ships with placeholder market values. Before publishing
daily observations, verify market data against the source hierarchy in the
Methodology section and replace only verified fields.
