from __future__ import annotations

import ast
from pathlib import Path


def _extract_refresh_sleeps_tuples(source: str) -> list[tuple[float, ...]]:
    """
    Parse execution_main.py and extract all assignments to `_refresh_sleeps = (<tuple>)`.
    We keep this "offline" and structural: no importing execution_main (avoids side effects).
    """
    tree = ast.parse(source)
    tuples: list[tuple[float, ...]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_refresh_sleeps":
                    # Expect a literal tuple of numeric constants
                    if isinstance(node.value, ast.Tuple):
                        values: list[float] = []
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, (int, float)):
                                values.append(float(elt.value))
                            else:
                                raise AssertionError(
                                    f"_refresh_sleeps must be a literal numeric tuple; got {ast.dump(node.value)}"
                                )
                        tuples.append(tuple(values))
                    else:
                        raise AssertionError(
                            f"_refresh_sleeps must be assigned a tuple literal; got {ast.dump(node.value)}"
                        )
    return tuples


def test_post_submit_refresh_budget_is_present_and_large_enough() -> None:
    path = Path("execution_v2/execution_main.py")
    src = path.read_text()

    tuples = _extract_refresh_sleeps_tuples(src)

    # We currently expect two callsites (one in entry submit path, one in another submit path).
    assert len(tuples) == 2, f"Expected 2 _refresh_sleeps tuples, found {len(tuples)}: {tuples}"

    for t in tuples:
        total = sum(t)
        # lock in a floor so we don't regress to ~1.8s and miss fills again
        assert total >= 3.8, f"Refresh budget too small: sum={total:.2f}s tuple={t}"

        # Optional: also ensure we still have at least 8 steps (shape/coverage).
        assert len(t) >= 8, f"Expected >=8 refresh sleeps, got {len(t)}: {t}"
