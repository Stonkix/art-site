import re


def fmt_price(value: int | float | None) -> str:
    if value is None:
        return ""
    return f"{int(value):,}".replace(",", " ") + " ₽"


def fmt_num(value: int | float | None) -> str:
    if value is None:
        return ""
    return f"{value:g}".replace(".", ",")


def normalize_phone(raw: str) -> str | None:
    """Возвращает +7XXXXXXXXXX или None, если номер не похож на российский."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] in "78":
        digits = "7" + digits[1:]
    elif len(digits) == 10 and digits[0] == "9":
        digits = "7" + digits
    else:
        return None
    return "+" + digits
