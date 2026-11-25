
STORE_REQUIRED = ["sku"]

SUPPLIER_REQUIRED = ["supplier_sku"]


STORE_OPTIONAL = [
    "product_name",
    "selling_price",
    "current_cost",
    "store_on_hand_qty",
    "store_published_qty",
    "inventory_mode",
    "barcode",
    "currency",
    "pack_size",
    "location_code",
]


SUPPLIER_OPTIONAL = [
    "supplier_product_name",
    "new_cost",
    "supplier_available_qty",
    "barcode",
    "currency",
    "pack_size",
    "supplier_location",
    "lead_time_days",
    "discontinued",
]


def get_fields(file_type):
    if file_type == "store":
        return STORE_REQUIRED, STORE_OPTIONAL

    if file_type == "supplier":
        return SUPPLIER_REQUIRED, SUPPLIER_OPTIONAL

    raise ValueError("Invalid file type.")


def map_columns(
    df,
    file_type,
    column_mapping=None
):
    required, optional = get_fields(file_type)

    if column_mapping is None:
        column_mapping = {}

    if not isinstance(column_mapping, dict):
        raise ValueError(
            "Column mapping must be an object."
        )

    frame = df.copy()

    frame.columns = [
        str(name).strip()
        for name in frame.columns
    ]

    if any(not name for name in frame.columns):
        raise ValueError(
            "Column headers cannot be empty."
        )

    if frame.columns.duplicated().any():
        raise ValueError(
            "Duplicate column headers detected."
        )

    all_fields = required + optional

    unknown = (
        set(column_mapping) - set(all_fields)
    )

    if unknown:
        raise ValueError(
            f"Unknown mapping fields: {sorted(unknown)}"
        )

    explicit = bool(column_mapping)

    selected = {}
    missing = []

    for field in all_fields:
        source = (
            column_mapping.get(field)
            if explicit else field
        )

        if source is None or source == "":
            if field in required:
                missing.append(field)

            continue

        if not isinstance(source, str):
            raise ValueError(
                f"Invalid mapping for {field}."
            )

        source = source.strip()

        if source not in frame.columns:
            if field in required:
                missing.append(field)

            elif explicit:
                raise ValueError(
                    f"Column not found for {field}: {source}"
                )

            continue

        selected[field] = source

    if missing:
        raise ValueError(
            f"Missing required mappings: {missing}"
        )

    if len(set(selected.values())) != len(selected):
        raise ValueError(
            "One source column cannot map "
            "to multiple fields."
        )

    normalized = frame[
        list(selected.values())
    ].copy()

    normalized.columns = list(selected)

    return normalized
