import csv, hashlib
from io import StringIO

def sample_bytes(kind):
    if kind not in ("store", "supplier"):
        raise ValueError("Unknown sample file.")

    stream = StringIO(newline="")
    writer = csv.writer(
        stream,
        lineterminator="\r\n",
    )

    if kind == "store":
        writer.writerow([
            "SKU",
            "Title",
            "Price",
            "Cost per item",
            "Inventory quantity",
            "Barcodes",
            "currency",
            "pack_size",
        ])

        for i in range(1, 51):
            writer.writerow([
                f"FG-{i:03}",
                f"Sample product {i}",
                f"{20+i:.2f}",
                f"{8+i/4:.2f}",
                30+i,
                f"880012300{i:03}",
                "USD",
                1,
            ])

    else:
        writer.writerow([
            "Item No",
            "Description",
            "Wholesale price",
            "Stock",
            "EAN",
            "currency",
            "Case pack",
            "Discontinued",
        ])

        for i in range(1, 51):
            price = 8 + i / 4

            if i == 4:
                # Intentional critical cost increase.
                price *= 1.65

            elif i == 11:
                # Intentional review cost increase.
                price *= 1.27

            writer.writerow([
                f"FG-{i:03}",
                f"Sample product {i}",
                f"{price:.2f}",
                40+i,
                f"880012300{i:03}",
                "USD",
                1,
                "yes" if i == 17 else "no",
            ])

    return (
        "\ufeff" + stream.getvalue()
    ).encode("utf-8")


def sample_hash(kind):
    return hashlib.sha256(
        sample_bytes(kind)
    ).hexdigest()


