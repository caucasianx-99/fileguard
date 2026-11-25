
from decimal import Decimal, InvalidOperation
import re


NUMBER_PATTERN = re.compile(
    r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)\Z",
    re.ASCII
)


def to_decimal(value, field_name):
    """
    Accept dot-decimal numbers without guessing
    locale-specific separators.
    """
    raw = str(value).strip()

    if (
        not raw
        or len(raw) > 50
        or not NUMBER_PATTERN.fullmatch(raw)
    ):
        raise ValueError(
            f"Invalid numeric value for {field_name}."
        )

    try:
        number = Decimal(raw)
    except InvalidOperation:
        raise ValueError(
            f"Invalid numeric value for {field_name}."
        ) from None

    if (
        not number.is_finite()
        or abs(number) > Decimal("1000000000000")
    ):
        raise ValueError(
            f"Invalid numeric value for {field_name}."
        )

    return number


def to_quantity(value, field_name):
    number = to_decimal(value, field_name)

    if (
        number < 0
        or number != number.to_integral_value()
        or number > 1000000000
    ):
        raise ValueError(
            f"Invalid quantity for {field_name}."
        )

    return int(number)


def determine_status(risks):
    if any(r["level"] == "CRITICAL" for r in risks):
        return "CRITICAL"

    if any(r["level"] == "REVIEW" for r in risks):
        return "REVIEW"

    return "SAFE"


def analyze_cost_margin(
    selling_price,
    current_cost,
    new_cost,
    minimum_margin=30
):
    selling = to_decimal(
        selling_price, "selling_price"
    )

    current = to_decimal(
        current_cost, "current_cost"
    )

    new = to_decimal(
        new_cost, "new_cost"
    )

    minimum = to_decimal(
        minimum_margin, "minimum_margin"
    )

    if not 0 <= minimum <= 100:
        raise ValueError(
            "Minimum margin must be between 0 and 100."
        )

    risks = []

    if selling <= 0:
        risks.append({
            "level": "CRITICAL",
            "message": "Selling price must be positive."
        })

    if current < 0:
        risks.append({
            "level": "CRITICAL",
            "message": "Current cost cannot be negative."
        })

    elif current == 0:
        risks.append({
            "level": "REVIEW",
            "message": "Cost change baseline is zero."
        })

    if new <= 0:
        risks.append({
            "level": "CRITICAL",
            "message": "New cost must be positive."
        })

    change = None
    margin = None

    if current > 0 and new > 0:
        change = (new - current) / current * 100

        if change > 50:
            risks.append({
                "level": "CRITICAL",
                "message": "Cost increased by over 50%."
            })

        elif change > 20:
            risks.append({
                "level": "REVIEW",
                "message": "Cost increased by over 20%."
            })

    if selling > 0 and new > 0:
        margin = (selling - new) / selling * 100

        if margin < 20:
            risks.append({
                "level": "CRITICAL",
                "message": "Gross margin is below 20%."
            })

        elif margin < minimum:
            risks.append({
                "level": "REVIEW",
                "message": (
                    f"Gross margin is below {minimum:g}%."
                )
            })

    return {
        "status": determine_status(risks),
        "cost_change_percent": (
            round(float(change), 2)
            if change is not None else None
        ),
        "gross_margin_percent": (
            round(float(margin), 2)
            if margin is not None else None
        ),
        "risks": risks
    }


def analyze_inventory(
    inventory_mode,
    store_on_hand_qty,
    store_published_qty,
    supplier_available_qty,
    buffer_qty=0,
    approve_supplier_stock_rule=False
):
    mode = str(inventory_mode).strip().lower()

    if mode not in (
        "owned",
        "supplier_managed",
        "hybrid"
    ):
        raise ValueError("Invalid inventory mode.")

    if type(approve_supplier_stock_rule) is not bool:
        raise ValueError(
            "Supplier stock rule approval "
            "must be true or false."
        )

    own = to_quantity(
        store_on_hand_qty,
        "store_on_hand_qty"
    )

    published = to_quantity(
        store_published_qty,
        "store_published_qty"
    )

    supplier = to_quantity(
        supplier_available_qty,
        "supplier_available_qty"
    )

    buffer = to_quantity(
        buffer_qty,
        "buffer_qty"
    )

    risks = []
    proposed = None
    potential = None

    if mode == "owned":
        if supplier == 0:
            risks.append({
                "level": "INFO",
                "message": (
                    "Supplier stock is zero; "
                    "owned store stock is unchanged."
                )
            })

    elif mode == "hybrid":
        risks.append({
            "level": "REVIEW",
            "message": (
                "Hybrid inventory formula is not "
                "configured; no stock change proposed."
            )
        })

    else:
        potential = max(0, supplier - buffer)

        if own > 0:
            risks.append({
                "level": "REVIEW",
                "message": (
                    "Supplier-managed product also has "
                    "owned stock; verify inventory ownership."
                )
            })

        if published > 0 and potential == 0:
            risks.append({
                "level": "CRITICAL",
                "message": (
                    "Supplier sync would reduce "
                    "published stock to zero."
                )
            })

        elif published > 0 and potential < published:
            reduction = (
                (published - potential) / published * 100
            )

            if reduction > 70:
                risks.append({
                    "level": "REVIEW",
                    "message": (
                        "Supplier sync would reduce "
                        "published stock by over 70%."
                    )
                })

        if not approve_supplier_stock_rule:
            risks.append({
                "level": "REVIEW",
                "message": (
                    "Supplier stock rule is not explicitly "
                    "approved; stock proposal withheld."
                )
            })

        elif own == 0:
            proposed = potential

    return {
        "status": determine_status(risks),
        "inventory_mode": mode,
        "store_on_hand_qty": own,
        "current_published_qty": published,
        "supplier_available_qty": supplier,
        "potential_published_qty": potential,
        "proposed_published_qty": proposed,
        "risks": risks
    }
