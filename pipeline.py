"""FileGuard read-only catalog comparison. No store-side updates."""

from collections import Counter
from decimal import Decimal, InvalidOperation
import re

from analyzer import (
    analyze_cost_margin,
    analyze_inventory,
    determine_status,
    to_decimal,
    to_quantity,
)

from mapping import map_columns


CURRENCIES = {
    "USD", "EUR", "GBP", "CAD",
    "AUD", "TRY", "AZN",
}

MODES = {
    "file",
    "owned",
    "supplier_managed",
    "hybrid",
}

SYMBOLS = "$€£₼₺"


def validate_config(data):
    if data is None:
        data = {}

    if not isinstance(data, dict):
        raise ValueError(
            "Inventory configuration must be an object."
        )

    mode = data.get("mode", "file")
    buffer = data.get("buffer_qty", 0)

    approved = data.get(
        "approve_supplier_stock_rule",
        False,
    )

    if (
        mode not in MODES
        or type(buffer) is not int
        or not 0 <= buffer <= 1000000
        or type(approved) is not bool
    ):
        raise ValueError(
            "Invalid inventory configuration."
        )

    for key in (
        "store_pack_single",
        "supplier_pack_single",
        "published_equals_on_hand",
    ):
        if type(data.get(key, False)) is not bool:
            raise ValueError(
                f"{key} must be true or false."
            )

    currency = data.get(
        "assumed_currency",
        "",
    )

    if currency and currency not in CURRENCIES:
        raise ValueError(
            "Unsupported currency selection."
        )

    # Legacy number_format remains a fallback.
    store_style = data.get(
        "store_number_format",
        data.get("number_format", "us"),
    )

    supplier_style = data.get(
        "supplier_number_format",
        data.get("number_format", "us"),
    )

    if (
        store_style not in ("us", "eu")
        or supplier_style not in ("us", "eu")
    ):
        raise ValueError(
            "Choose supported number formats for each file."
        )

    return {
        "mode": mode,
        "buffer_qty": buffer,
        "approve_supplier_stock_rule": approved,
        "store_pack_single": data.get(
            "store_pack_single", False
        ),
        "supplier_pack_single": data.get(
            "supplier_pack_single", False
        ),
        "published_equals_on_hand": data.get(
            "published_equals_on_hand", False
        ),
        "assumed_currency": currency,
        "store_number_format": store_style,
        "supplier_number_format": supplier_style,
    }


def normalized_number(raw, style, field):
    """Explicit locale, strict grouping, optional currency glyphs."""

    raw = str(raw).strip()

    if len(raw) > 64 or not raw:
        raise ValueError(
            f"Invalid numeric value for {field}."
        )

    raw = raw.strip(
        SYMBOLS + " \t\u00a0\u202f"
    )

    raw = raw.replace(
        "\u00a0", " "
    ).replace(
        "\u202f", " "
    )

    raw = raw.replace(" ", "")

    if any(x in raw for x in SYMBOLS) or not raw:
        raise ValueError(
            f"Invalid numeric value for {field}."
        )

    if style == "us":
        valid = (
            r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)"
            r"(?:\.\d+)?"
        )

        clean = raw.replace(",", "")

    else:
        valid = (
            r"[+-]?(?:\d+|\d{1,3}(?:\.\d{3})+)"
            r"(?:,\d+)?"
        )

        clean = (
            raw.replace(".", "")
            .replace(",", ".")
        )

    if not re.fullmatch(
        valid,
        raw,
        flags=re.ASCII,
    ):
        raise ValueError(
            f"Invalid numeric value for {field}."
        )

    try:
        number = Decimal(clean)

    except InvalidOperation:
        raise ValueError(
            f"Invalid numeric value for {field}."
        ) from None

    if (
        not number.is_finite()
        or abs(number) > Decimal("1000000000000")
    ):
        raise ValueError(
            f"Invalid numeric value for {field}."
        )

    return format(number, "f")


def pack(raw):
    if raw == "":
        return None

    try:
        result = Decimal(raw)

    except InvalidOperation:
        raise ValueError(
            "Invalid pack size."
        ) from None

    if (
        not result.is_finite()
        or not 0 < result <= 1000000000
    ):
        raise ValueError(
            "Invalid pack size."
        )

    return result


def barcode(raw):
    text = str(raw).strip()

    if re.fullmatch(r"\d+\.0", text):
        return text[:-2], False

    if re.search(
        r"e[+-]\d+",
        text,
        flags=re.I,
    ):
        return text, True

    return text, False


def sku_key(raw):
    # Leading zeroes are preserved.
    return str(raw).strip().casefold()


def analyze_catalog(
    store_df,
    supplier_df,
    store_mapping=None,
    supplier_mapping=None,
    inventory_config=None,
):
    cfg = validate_config(
        inventory_config
    )

    store = map_columns(
        store_df,
        "store",
        store_mapping,
    ).copy()

    supplier = map_columns(
        supplier_df,
        "supplier",
        supplier_mapping,
    ).copy()

    notes = [
        (
            f"Store number format: "
            f"{cfg['store_number_format']} "
            "(selected by user)."
        ),
        (
            f"Supplier number format: "
            f"{cfg['supplier_number_format']} "
            "(selected by user)."
        ),
    ]

    if cfg["mode"] != "file":
        notes.append(
            f"Inventory ownership: {cfg['mode']} "
            "(selected by user)."
        )

    if (
        "pack_size" not in store
        and cfg["store_pack_single"]
    ):
        store["pack_size"] = "1"

        notes.append(
            "Store pack size = 1 "
            "(confirmed by user)."
        )

    if (
        "pack_size" not in supplier
        and cfg["supplier_pack_single"]
    ):
        supplier["pack_size"] = "1"

        notes.append(
            "Supplier pack size = 1 "
            "(confirmed by user)."
        )

    if cfg["assumed_currency"]:
        for name, df in (
            ("Store", store),
            ("Supplier", supplier),
        ):
            if "currency" not in df:
                df["currency"] = (
                    cfg["assumed_currency"]
                )

                notes.append(
                    f"{name} currency = "
                    f"{cfg['assumed_currency']} "
                    "(confirmed by user)."
                )

    if (
        "store_published_qty" not in store
        and cfg["published_equals_on_hand"]
        and "store_on_hand_qty" in store
    ):
        store["store_published_qty"] = (
            store["store_on_hand_qty"]
        )

        notes.append(
            "Published stock equals on-hand stock "
            "(confirmed by user)."
        )

    # Normalize identifiers without dropping leading zeroes.
    for df, field in (
        (store, "sku"),
        (supplier, "supplier_sku"),
    ):
        df[field] = (
            df[field].astype(str).str.strip()
        )

        df["_key"] = df[field].map(
            sku_key
        )

        df["_barcode"] = ""
        df["_barcode_sci"] = False

        if "barcode" in df:
            parsed = df["barcode"].map(
                barcode
            )

            df["_barcode"] = parsed.map(
                lambda x: x[0]
            )

            df["_barcode_sci"] = parsed.map(
                lambda x: x[1]
            )

    old_counts = Counter(
        store["_key"]
    )

    new_counts = Counter(
        supplier["_key"]
    )

    old_bar_counts = Counter(
        x for x in store["_barcode"] if x
    )

    new_bar_counts = Counter(
        x for x in supplier["_barcode"] if x
    )

    by_sku = {
        r["_key"]: (i, r)
        for i, r in supplier.iterrows()
        if (
            r["_key"]
            and new_counts[r["_key"]] == 1
        )
    }

    by_barcode = {
        r["_barcode"]: (i, r)
        for i, r in supplier.iterrows()
        if (
            r["_barcode"]
            and not r["_barcode_sci"]
            and new_bar_counts[r["_barcode"]] == 1
            and r["_key"]
            and new_counts[r["_key"]] == 1
        )
    }

    def val(row, col):
        if row is None:
            return ""

        return str(
            row.get(col, "")
        ).strip()

    rows = []
    matched = set()

    def build(
        key,
        own=None,
        vendor=None,
        method="NONE",
    ):
        risks = []
        cost = None
        inventory = None
        identity = method == "SKU"

        def add(level, msg):
            issue = {
                "level": level,
                "message": msg,
            }

            if issue not in risks:
                risks.append(issue)

        if (
            val(own, "_barcode_sci") == "True"
            or val(vendor, "_barcode_sci") == "True"
        ):
            add(
                "REVIEW",
                "Barcode uses scientific notation; "
                "verify the original identifier.",
            )

        if not key:
            add(
                "CRITICAL",
                "Missing SKU.",
            )

        elif (
            own is not None
            and old_counts[key] > 1
        ):
            add(
                "CRITICAL",
                "Duplicate store SKU (case-insensitive).",
            )

        elif (
            vendor is not None
            and new_counts[key] > 1
        ):
            add(
                "CRITICAL",
                "Duplicate supplier SKU (case-insensitive).",
            )

        elif (
            own is not None
            and new_counts.get(key, 0) > 1
        ):
            # A store SKU may be present in the supplier
            # file but excluded from by_sku due to duplicates.
            add(
                "CRITICAL",
                "Duplicate supplier SKU (case-insensitive).",
            )

        elif own is None:
            add(
                "REVIEW",
                "Supplier-only SKU; no store match.",
            )

        elif vendor is None:
            add(
                "REVIEW",
                "Store SKU not found in supplier file.",
            )

        else:
            if method == "BARCODE":
                add(
                    "REVIEW",
                    "Barcode-only candidate: "
                    f"supplier SKU "
                    f"{val(vendor, 'supplier_sku')}. "
                    "Verify identity.",
                )

            if (
                method == "SKU"
                and val(own, "_barcode")
                and val(vendor, "_barcode")
                and (
                    val(own, "_barcode")
                    != val(vendor, "_barcode")
                )
            ):
                add(
                    "CRITICAL",
                    "Same SKU but conflicting barcodes; "
                    "comparisons withheld.",
                )

                identity = False

            good_pack = False

            try:
                a = pack(
                    val(own, "pack_size")
                )

                b = pack(
                    val(vendor, "pack_size")
                )

                if a is None or b is None:
                    add(
                        "REVIEW",
                        "Pack size not verified; "
                        "comparisons withheld.",
                    )

                elif a != b:
                    add(
                        "CRITICAL",
                        "Pack size mismatch; "
                        "comparisons withheld.",
                    )

                else:
                    good_pack = True

            except ValueError as exc:
                add(
                    "CRITICAL",
                    str(exc),
                )

            c1 = val(
                own,
                "currency",
            ).upper()

            c2 = val(
                vendor,
                "currency",
            ).upper()

            good_currency = (
                bool(c1)
                and c1 == c2
                and bool(
                    re.fullmatch(
                        "[A-Z]{3}",
                        c1,
                        re.ASCII,
                    )
                )
            )

            if c1 and c2 and c1 != c2:
                add(
                    "CRITICAL",
                    "Currency mismatch; "
                    "cost comparison withheld.",
                )

            elif not good_currency:
                add(
                    "REVIEW",
                    "Currency missing or invalid; "
                    "cost comparison withheld.",
                )

            stopped = val(
                vendor,
                "discontinued",
            ).lower()

            if stopped in ("true", "yes", "1"):
                add(
                    "REVIEW",
                    "Supplier marked product as discontinued.",
                )

            elif stopped not in (
                "", "false", "no", "0"
            ):
                add(
                    "REVIEW",
                    "Unrecognized discontinued value.",
                )

            # Store and supplier price formats are separate.
            finance = {}

            for field, raw in (
                (
                    "selling_price",
                    val(own, "selling_price"),
                ),
                (
                    "current_cost",
                    val(own, "current_cost"),
                ),
                (
                    "new_cost",
                    val(vendor, "new_cost"),
                ),
            ):
                if not raw:
                    add(
                        "REVIEW",
                        f"Missing {field}.",
                    )
                    continue

                try:
                    style = (
                        cfg["supplier_number_format"]
                        if field == "new_cost"
                        else cfg["store_number_format"]
                    )

                    number = normalized_number(
                        raw,
                        style,
                        field,
                    )

                    finance[field] = number

                    if (
                        field != "current_cost"
                        and Decimal(number) <= 0
                    ):
                        raise ValueError(
                            f"{field} must be positive."
                        )

                    if (
                        field == "current_cost"
                        and Decimal(number) < 0
                    ):
                        raise ValueError(
                            "Current cost cannot be negative."
                        )

                except ValueError as exc:
                    finance.pop(field, None)

                    add(
                        "CRITICAL",
                        str(exc),
                    )

            if (
                identity
                and good_pack
                and good_currency
                and len(finance) == 3
            ):
                try:
                    cost = analyze_cost_margin(
                        finance["selling_price"],
                        finance["current_cost"],
                        finance["new_cost"],
                    )

                    risks.extend(
                        cost["risks"]
                    )

                except ValueError as exc:
                    add(
                        "CRITICAL",
                        str(exc),
                    )

            row_mode = val(
                own,
                "inventory_mode",
            ).lower()

            if (
                row_mode
                and row_mode not in (
                    "owned",
                    "supplier_managed",
                    "hybrid",
                )
            ):
                add(
                    "CRITICAL",
                    "Invalid inventory_mode in store file.",
                )

                effective = None

            elif (
                cfg["mode"] != "file"
                and row_mode
                and row_mode != cfg["mode"]
            ):
                add(
                    "REVIEW",
                    "Inventory configuration conflicts "
                    "with store row; "
                    "stock comparison withheld.",
                )

                effective = None

            else:
                effective = (
                    row_mode
                    if cfg["mode"] == "file"
                    else cfg["mode"]
                )

            if (
                not effective
                and not row_mode
                and cfg["mode"] == "file"
            ):
                add(
                    "REVIEW",
                    "Inventory mode is missing.",
                )

            amounts = {}

            for field, raw in (
                (
                    "store_on_hand_qty",
                    val(own, "store_on_hand_qty"),
                ),
                (
                    "store_published_qty",
                    val(own, "store_published_qty"),
                ),
                (
                    "supplier_available_qty",
                    val(vendor, "supplier_available_qty"),
                ),
            ):
                if not raw:
                    add(
                        "REVIEW",
                        f"Missing {field}.",
                    )
                    continue

                try:
                    style = (
                        cfg["supplier_number_format"]
                        if field == "supplier_available_qty"
                        else cfg["store_number_format"]
                    )

                    quantity = normalized_number(
                        raw,
                        style,
                        field,
                    )

                    amounts[field] = str(
                        to_quantity(
                            quantity,
                            field,
                        )
                    )

                except ValueError as exc:
                    add(
                        "CRITICAL",
                        str(exc),
                    )

            if (
                identity
                and good_pack
                and effective
                and len(amounts) == 3
            ):
                try:
                    inventory = analyze_inventory(
                        effective,
                        amounts["store_on_hand_qty"],
                        amounts["store_published_qty"],
                        amounts["supplier_available_qty"],
                        buffer_qty=cfg["buffer_qty"],
                        approve_supplier_stock_rule=(
                            cfg["approve_supplier_stock_rule"]
                        ),
                    )

                    risks.extend(
                        inventory["risks"]
                    )

                except ValueError as exc:
                    add(
                        "CRITICAL",
                        str(exc),
                    )

        return {
            "sku": (
                val(own, "sku")
                or val(vendor, "supplier_sku")
            ),
            "product_name": (
                val(own, "product_name")
                or val(vendor, "supplier_product_name")
            ),
            "match_method": method,
            "status": determine_status(risks),
            "current_cost": val(
                own,
                "current_cost",
            ),
            "new_cost": val(
                vendor,
                "new_cost",
            ),
            "currency": val(
                own,
                "currency",
            ).upper(),
            "supplier_currency": val(
                vendor,
                "currency",
            ).upper(),
            "cost_analysis": cost,
            "inventory_analysis": inventory,
            "risks": risks,
        }

    # Construct once — avoids quadratic barcode matching.
    store_keys = set(store["_key"])

    for _, r in store.iterrows():
        k = r["_key"]

        match = (
            by_sku.get(k)
            if k and old_counts[k] == 1
            else None
        )

        method = (
            "SKU" if match else "NONE"
        )

        if (
            not match
            and k
            and old_counts[k] == 1
        ):
            bc = r["_barcode"]

            if (
                bc
                and not r["_barcode_sci"]
                and old_bar_counts[bc] == 1
            ):
                candidate = by_barcode.get(bc)

                if (
                    candidate
                    and candidate[1]["_key"]
                    not in store_keys
                ):
                    match = candidate
                    method = "BARCODE"

        if match:
            matched.add(match[0])

        rows.append(
            build(
                k,
                r,
                match[1] if match else None,
                method,
            )
        )

    for i, r in supplier.iterrows():
        if (
            i not in matched
            and r["_key"] not in store_keys
        ):
            rows.append(
                build(
                    r["_key"],
                    vendor=r,
                )
            )

    checks = []

    def block(msg):
        checks.append({
            "level": "BLOCK",
            "message": msg,
        })

    for label, df in (
        ("store", store),
        ("supplier", supplier),
    ):
        if df["_key"].duplicated().any():
            block(
                f"Duplicate SKUs found in {label} file."
            )

        if (df["_key"] == "").any():
            block(
                f"Missing SKUs found in {label} file."
            )

    unmatched = sum(
        bool(k)
        and k not in store_keys
        for k in supplier["_key"]
    )

    if (
        len(supplier)
        and unmatched / len(supplier) > .20
    ):
        block(
            f"{100 * unmatched / len(supplier):.1f}% "
            "of supplier rows have no exact store SKU match."
        )

    for label, df, field in (
        ("store", store, "currency"),
        ("supplier", supplier, "currency"),
        ("store", store, "location_code"),
        ("supplier", supplier, "supplier_location"),
    ):
        if field in df:
            distinct = {
                str(x).strip().upper()
                for x in df[field]
                if str(x).strip()
            }

            if len(distinct) > 1:
                block(
                    f"Multiple {field} values in "
                    f"{label} file; single-location "
                    "and single-currency checks "
                    "cannot approve export."
                )

    managed = [
        r["inventory_analysis"]
        for r in rows
        if (
            r["inventory_analysis"]
            and r["inventory_analysis"]["inventory_mode"]
            == "supplier_managed"
        )
    ]

    if managed:
        zeroed = sum(
            (
                x["current_published_qty"] > 0
                and x["potential_published_qty"] == 0
            )
            for x in managed
        )

        if zeroed / len(managed) > .30:
            block(
                "Over 30% of analyzed "
                "supplier-managed rows could "
                "lose all published stock."
            )

    candidates = []

    if not checks:
        for row in rows:
            cost = row["cost_analysis"]
            inv = row["inventory_analysis"]

            if (
                row["status"] != "SAFE"
                or row["match_method"] != "SKU"
                or not cost
                or not inv
                or cost["status"] != "SAFE"
                or inv["status"] != "SAFE"
            ):
                continue

            try:
                price = to_decimal(
                    normalized_number(
                        row["new_cost"],
                        cfg["supplier_number_format"],
                        "new_cost",
                    ),
                    "new_cost",
                )

                if price <= 0:
                    continue

            except ValueError:
                continue

            mode = inv["inventory_mode"]

            if mode == "owned":
                action = "NO_CHANGE"
                proposed = None

            elif (
                mode == "supplier_managed"
                and cfg["approve_supplier_stock_rule"]
                and type(
                    inv["proposed_published_qty"]
                ) is int
            ):
                action = "SET_PUBLISHED_QTY"
                proposed = inv[
                    "proposed_published_qty"
                ]

            else:
                continue

            candidates.append({
                "sku": row["sku"],
                "proposed_cost": format(
                    price,
                    "f",
                ),
                "currency": row["currency"],
                "stock_action": action,
                "proposed_published_qty": proposed,
                "export_purpose": "MANUAL_REVIEW_ONLY",
            })

    counts = Counter(
        r["status"]
        for r in rows
    )

    return {
        "summary": {
            "total": len(rows),
            "safe": counts["SAFE"],
            "review": counts["REVIEW"],
            "critical": counts["CRITICAL"],
            "import_blocked": bool(
                checks
                or counts["REVIEW"]
                or counts["CRITICAL"]
            ),
        },
        "inventory_configuration": cfg,
        "user_confirmations": notes,
        "file_checks": checks,
        "export_policy": {
            "candidate_count": len(candidates),
            "file_blocked": bool(checks),
            "purpose": "MANUAL_REVIEW_ONLY",
        },
        "export_candidates": candidates,
        "rows": rows,
    }