import csv, hashlib, json
from io import BytesIO, StringIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile
import pandas as pd
from pipeline import analyze_catalog
from samples import sample_hash
MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 30000
MAX_COLUMNS = 150
MAX_XLSX_UNCOMPRESSED = 24 * 1024 * 1024
MAX_XLSX_PARTS = 512

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
    from openpyxl import load_workbook
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



def read_catalog(filename, data):
    ext = Path(filename).suffix.lower()
    if ext not in ('.csv', '.xlsx'):
        raise ValueError('Only CSV and XLSX files are supported.')
    if not data or len(data) > MAX_BYTES:
        raise ValueError('Each file must contain data and be at most 5 MB.')
    try:
        if ext == '.xlsx':
            validate_xlsx_container(data)
            frame = xlsx_frame(data, MAX_ROWS)
        else:
            frame = csv_frame(data, MAX_ROWS)
    except UnicodeError:
        raise ValueError('Unsupported encoding; use UTF-8 or UTF-16 CSV.') from None
    except ValueError:
        raise
    except Exception:
        raise ValueError('File could not be read. Check format and headers.') from None
    if frame.empty:
        raise ValueError('File contains no data rows.')
    return frame

def dispatch(action, store_name, store_data, supplier_name, supplier_data, options):
    a = read_catalog(store_name, store_data)
    b = read_catalog(supplier_name, supplier_data)
    if action == '/preview':
        result = {key: {'filename': name, 'rows': len(frame), 'columns': frame.columns.tolist(), 'example': frame.iloc[0].to_dict()} for key, name, frame in [('store', store_name, a), ('supplier', supplier_name, b)]}
    elif action == '/analyze':
        result = analyze_catalog(a, b, store_mapping=options.get('store_mapping', {}), supplier_mapping=options.get('supplier_mapping', {}), inventory_config=options.get('inventory_config', {}))
        result['sample_analysis'] = hashlib.sha256(store_data).hexdigest() == sample_hash('store') and hashlib.sha256(supplier_data).hexdigest() == sample_hash('supplier')
    else:
        raise ValueError('Unsupported operation.')
    return json.dumps(result, allow_nan=False)
