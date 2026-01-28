from execution_v2.orders import generate_idempotency_key


def test_idempotency_key_stable_per_day() -> None:
    key_first = generate_idempotency_key(
        "strategy-1",
        "2026-01-28",
        "AAPL",
        "buy",
        10,
    )
    key_second = generate_idempotency_key(
        "strategy-1",
        "2026-01-28",
        "AAPL",
        "buy",
        10,
    )

    assert key_first == key_second
