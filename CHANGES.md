# Source edition changes

Removed paid plans, checkout, Firebase login and authorization, remote trial tracking and commercial pages. Retained original CSV/XLSX catalog analysis, mapping, export UI, sample files, input size limits and bounded upload wrapper. Local-only unauthenticated entrypoint; do not expose to the internet.

Validation: Python compilation, local HTTP home/health/sample/preview and repeated analysis of 50 fictional records, cross-origin rejection. Browser PDF print and real customer inputs not tested.

## GitHub Pages edition
- Added `docs/` with original UI and read-only Python engine running locally in a Web Worker via Pyodide.
- Removed stale paid-tier copy from both interfaces.
- Bundled fictional sample CSV files, added sample shortcut and browser setup documentation.
- Added native boundary tests; browser/CDN execution is not verified in this environment.
