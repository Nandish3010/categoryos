def fmt_inr(value: float) -> str:
    """Indian lakh grouping: 1234567 -> ₹12,34,567."""
    negative = value < 0
    digits = str(round(abs(value)))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join([*groups, tail])
    return f"{'-' if negative else ''}₹{digits}"


def fmt_pct(fraction: float, dp: int = 1) -> str:
    return f"{fraction * 100:.{dp}f}%"
