# FileGuard Agency

Local, read-only catalog risk analysis for e-commerce data. Compare store and supplier CSV/XLSX files, map columns, review cost and inventory findings, export CSV and print a PDF-ready report. No external store writes.

## Run locally

Python 3.12 recommended.

```bash
python -m venv .venv
# Activate the virtual environment for your OS
python -m pip install -r requirements.txt
python -m uvicorn secure_app:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Download fictional sample files in the interface. No account, payment, cloud service or credentials required.

Limits: 5 MiB and 30,000 rows per input; 150 columns; 11 MiB request; two concurrent upload requests per process. CSV/XLSX input checks remain. Keep the service bound to loopback: it does not authenticate users and is not suitable for public deployment. Only analyze data you are authorized to process. Findings require human review; no imports are authorized.

This is a free portfolio project. The browser edition lives in `docs/` and can be hosted on GitHub Pages; see [PAGES.md](PAGES.md).

No open-source license has been selected by the author; public visibility alone does not grant reuse rights.
