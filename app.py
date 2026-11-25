"""FileGuard file-reading API. Local entrypoint is secure_app:app."""

import csv
import hashlib
import json

from io import BytesIO, StringIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pandas as pd

from openpyxl import load_workbook

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    Request,
)

from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from pipeline import analyze_catalog
from sample_data import sample_hash, sample_csv


ROOT = Path(__file__).resolve().parent

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 30000
MAX_COLUMNS = 150

MAX_XLSX_UNCOMPRESSED = 24 * 1024 * 1024
MAX_XLSX_PARTS = 512


app = FastAPI(
    title="FileGuard Agency",
    description="Read-only catalog preflight",
    version="1.1.1",
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "application": "FileGuard Agency",
    }


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(
        ROOT / "index.html",
        media_type="text/html",
    )


@app.get("/samples/store.csv")
def store_sample():
    return sample_csv("store")


@app.get("/samples/supplier.csv")
def supplier_sample():
    return sample_csv("supplier")


def headers_or_error(items):
    result = [
        str(x).strip()
        if x is not None else ""
        for x in items
    ]

    if not result or any(not x for x in result):
        raise ValueError(
            "All column headers must be non-empty."
        )

    if len(result) != len(set(result)):
        raise ValueError(
            "Duplicate column headers detected."
        )

    if len(result) > MAX_COLUMNS:
        raise ValueError(
            f"Analysis supports at most {MAX_COLUMNS} columns."
        )

    return result


def csv_frame(content, row_limit):
    if content.startswith(
        (b"\xff\xfe", b"\xfe\xff")
    ):
        text = content.decode("utf-16")
    else:
        text = content.decode("utf-8-sig")

    if "\x00" in text:
        raise ValueError(
            "Unsupported encoding; use UTF-8 or UTF-16."
        )

    sample = text[:16000]

    try:
        sep = csv.Sniffer().sniff(
            sample,
            delimiters=",;\t|",
        ).delimiter

    except csv.Error:
        first = (
            text.splitlines()[0]
            if text.splitlines()
            else ""
        )

        counts = {
            ch: first.count(ch)
            for ch in ",;\t|"
        }

        sep = (
            max(counts, key=counts.get)
            if any(counts.values())
            else ","
        )

    reader = csv.reader(
        StringIO(text),
        delimiter=sep,
        strict=True,
    )

    try:
        cols = headers_or_error(
            next(reader, [])
        )

        records = []

        for line, cells in enumerate(
            reader,
            start=2,
        ):
            if (
                not cells
                or all(
                    not value.strip()
                    for value in cells
                )
            ):
                continue

            if len(cells) != len(cols):
                raise ValueError(
                    f"CSV record {line} has an unexpected "
                    "number of columns."
                )

            if len(records) >= row_limit:
                raise ValueError(
                    f"Analysis supports at most {row_limit} data rows."
                )

            records.append(cells)

    except csv.Error:
        raise ValueError(
            "CSV has malformed quoted fields."
        ) from None

    return pd.DataFrame(
        records,
        columns=cols,
        dtype=str,
    )


def validate_xlsx_container(content):
    """
    Preserve XLSX archive, expansion, encryption
    and macro safeguards from version 1.1.1.
    """

    try:
        with ZipFile(
            BytesIO(content)
        ) as archive:
            parts = archive.infolist()

            names = {
                part.filename
                for part in parts
            }

            if "xl/workbook.xml" not in names:
                raise ValueError(
                    "Invalid XLSX workbook structure."
                )

            if len(parts) > MAX_XLSX_PARTS:
                raise ValueError(
                    "XLSX has too many internal parts."
                )

            total = 0

            for part in parts:
                if part.flag_bits & 1:
                    raise ValueError(
                        "Encrypted XLSX files "
                        "are not supported."
                    )

                if part.filename.lower().endswith(
                    "vbaproject.bin"
                ):
                    raise ValueError(
                        "Macro-enabled workbooks "
                        "are not supported."
                    )

                total += part.file_size

                if total > MAX_XLSX_UNCOMPRESSED:
                    raise ValueError(
                        "XLSX expanded content exceeds "
                        "the safety limit."
                    )

    except BadZipFile:
        raise ValueError(
            "Invalid or damaged XLSX file."
        ) from None


def xlsx_frame(content, row_limit):
    book = load_workbook(
        BytesIO(content),
        read_only=True,
        data_only=True,
        keep_links=False,
    )

    try:
        rows = book.worksheets[0].iter_rows(
            values_only=True
        )

        cols = headers_or_error(
            next(rows, [])
        )

        records = []

        for line in rows:
            values = list(line)

            if (
                len(values) > len(cols)
                and any(
                    value is not None
                    and str(value).strip()
                    for value in values[len(cols):]
                )
            ):
                raise ValueError(
                    "Excel has values outside "
                    "its header columns."
                )

            values = (
                values[:len(cols)]
                + [None] * len(cols)
            )[:len(cols)]

            if all(
                value is None
                or str(value).strip() == ""
                for value in values
            ):
                continue

            if len(records) >= row_limit:
                raise ValueError(
                    f"Analysis supports at most {row_limit} data rows."
                )

            records.append([
                ""
                if value is None
                else str(value)
                for value in values
            ])

    finally:
        book.close()

    return pd.DataFrame(
        records,
        columns=cols,
        dtype=str,
    )


async def read_file(upload, row_limit):
    ext = Path(
        upload.filename or ""
    ).suffix.lower()

    if ext not in (".csv", ".xlsx"):
        raise HTTPException(
            400,
            "Only CSV and XLSX files are supported.",
        )

    content = await upload.read(
        MAX_BYTES + 1
    )

    if len(content) > MAX_BYTES:
        raise HTTPException(
            413,
            "Maximum file size is 5 MB per file.",
        )

    if not content:
        raise HTTPException(
            400,
            "The uploaded file is empty.",
        )

    try:
        if ext == ".xlsx":
            await run_in_threadpool(
                validate_xlsx_container,
                content,
            )

        parser = (
            csv_frame
            if ext == ".csv"
            else xlsx_frame
        )

        frame = await run_in_threadpool(
            parser,
            content,
            row_limit,
        )

    except UnicodeError:
        raise HTTPException(
            400,
            "Unsupported encoding; "
            "use UTF-8 or UTF-16 CSV.",
        ) from None

    except ValueError as exc:
        raise HTTPException(
            400,
            str(exc),
        ) from None

    except Exception:
        raise HTTPException(
            400,
            "File could not be read. "
            "Check format and headers.",
        ) from None

    if frame.empty:
        raise HTTPException(
            400,
            "File contains no data rows.",
        )

    digest = hashlib.sha256(
        content
    ).hexdigest()

    return frame, digest


def limit_for(request):
    return MAX_ROWS


def json_object(raw, label):
    try:
        result = json.loads(raw)

    except (TypeError, ValueError):
        raise HTTPException(
            400,
            f"{label} must be valid JSON.",
        ) from None

    if not isinstance(result, dict):
        raise HTTPException(
            400,
            f"{label} must be a JSON object.",
        )

    return result


@app.post("/preview")
async def preview(
    request: Request,
    current_store: UploadFile = File(...),
    supplier: UploadFile = File(...),
):
    limit = limit_for(request)

    a, _ = await read_file(
        current_store,
        limit,
    )

    b, _ = await read_file(
        supplier,
        limit,
    )

    return {
        "store": {
            "filename": current_store.filename,
            "rows": len(a),
            "columns": a.columns.tolist(),
            "example": a.iloc[0].to_dict(),
        },
        "supplier": {
            "filename": supplier.filename,
            "rows": len(b),
            "columns": b.columns.tolist(),
            "example": b.iloc[0].to_dict(),
        },
    }


@app.post("/analyze")
async def analyze(
    request: Request,
    current_store: UploadFile = File(...),
    supplier: UploadFile = File(...),
    store_mapping: str = Form("{}"),
    supplier_mapping: str = Form("{}"),
    inventory_config: str = Form("{}"),
):
    limit = limit_for(request)

    a, store_digest = await read_file(
        current_store,
        limit,
    )

    b, supplier_digest = await read_file(
        supplier,
        limit,
    )

    is_official_sample = (
        store_digest == sample_hash("store")
        and supplier_digest == sample_hash("supplier")
    )

    try:
        result = await run_in_threadpool(
            analyze_catalog,
            a,
            b,
            store_mapping=json_object(
                store_mapping,
                "Store mapping",
            ),
            supplier_mapping=json_object(
                supplier_mapping,
                "Supplier mapping",
            ),
            inventory_config=json_object(
                inventory_config,
                "Inventory configuration",
            ),
        )

        result["sample_analysis"] = is_official_sample

        return result

    except ValueError as exc:
        raise HTTPException(
            400,
            str(exc),
        ) from None