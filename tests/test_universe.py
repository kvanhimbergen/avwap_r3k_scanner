import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")

pytestmark = pytest.mark.requires_pandas

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

import universe


def test_allow_network_false_avoids_requests(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    snapshot_path = tmp_path / "iwv_holdings_snapshot.csv"
    snapshot_path.write_text("Ticker,Weight (%)\nAAPL,1.0\n")

    def _raise_on_get(*_args, **_kwargs):
        raise AssertionError("requests.get should not be called when allow_network=False")

    monkeypatch.setattr(universe, "LOCAL_CACHE_PATH", str(tmp_path / "missing_cache.csv"))
    monkeypatch.setattr(universe.cfg, "UNIVERSE_SNAPSHOT_PATH", str(snapshot_path))
    monkeypatch.setattr(universe.requests, "get", _raise_on_get)

    df = universe.load_r3k_universe_from_iwv(allow_network=False)
    assert "Ticker" in df.columns
    assert df["Ticker"].tolist() == ["AAPL"]


def test_discover_iwv_holdings_url_from_fixture() -> None:
    fixture_path = Path("tests/fixtures/ishares_iwv.html")
    html_text = fixture_path.read_text()

    url = universe._discover_iwv_holdings_url(
        html_text,
        "https://www.ishares.com/us/products/239714/ishares-russell-3000-etf",
    )
    assert url.startswith("https://www.ishares.com/us/products/239714/")
    assert "fileType=csv" in url
    assert "fileName=IWV_holdings" in url
    assert "dataType=fund" in url
