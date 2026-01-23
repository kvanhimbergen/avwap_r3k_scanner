from __future__ import annotations

import inspect
import sys


def test_paper_sim_path_does_not_import_alpaca() -> None:
    pre_alpaca = {name for name in sys.modules if name.startswith("alpaca")}

    import execution_v2.paper_sim as paper_sim
    import execution_v2.paper_positions as paper_positions

    post_alpaca = {name for name in sys.modules if name.startswith("alpaca")}

    assert pre_alpaca == post_alpaca
    assert "alpaca" not in inspect.getsource(paper_sim)
    assert "alpaca" not in inspect.getsource(paper_positions)
