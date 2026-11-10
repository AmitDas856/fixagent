"""Small statistics helpers."""


def mean(values):
    if not values:
        raise ValueError("mean of empty list")
    return sum(values) / len(values)


def median(values):
    if not values:
        raise ValueError("median of empty list")
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle]


def value_range(values):
    if not values:
        raise ValueError("range of empty list")
    return max(values) - min(values)
