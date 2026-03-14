from typing import Any

# Function default arguments used by data-provider calls.
# Parameter-less functions are represented by empty dicts for clarity.
FUNCTION_DEFAULT_ARGS: dict[str, dict[str, Any]] = {
    "Supply-Transaction Unit Statistic": {"area_range_size": 20},
    "Area x Price Cross Pivot": {"area_range_size": 20, "price_range_size": 5},
    "Area Segment Distribution": {"area_range_size": 20},
    "Price Segment Distribution": {"price_range_size": 1},
    "Annual Supply-Demand Comparison": {},
    "Supply-Transaction Area": {},
}

# Allowed arg keys per function.
FUNCTION_KEY_PARAMS: dict[str, set[str]] = {
    function_key: set(default_args.keys())
    for function_key, default_args in FUNCTION_DEFAULT_ARGS.items()
}


def get_default_function_args(function_key: str) -> dict[str, Any]:
    """Return a copy of default args for a function_key."""
    return dict(FUNCTION_DEFAULT_ARGS.get(function_key, {}))


def filter_function_args(function_key: str, args: dict[str, Any]) -> dict[str, Any]:
    """Filter args by the allowed keys of a function_key."""
    valid_params = FUNCTION_KEY_PARAMS.get(function_key, set())
    return {k: v for k, v in args.items() if k in valid_params}
