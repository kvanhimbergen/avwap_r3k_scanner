from execution_v2.exits import ExitPositionState, apply_r1_transition


def test_apply_r1_transition_moves_stop_to_breakeven() -> None:
    state = ExitPositionState(
        symbol="TEST",
        entry_time=0.0,
        entry_price=10.0,
        entry_qty=10,
        stop_price=9.0,
        stop_order_id=None,
        r_value=1.0,
        r1_price=11.0,
        r2_price=12.0,
        r1_qty=5,
        r2_qty=5,
        stage="OPEN",
        qty_remaining=10,
    )

    next_state = apply_r1_transition(state, last_price=11.25)

    assert next_state.stage == "R1_TAKEN"
    assert next_state.qty_remaining == 5
    assert next_state.stop_price == 10.0
