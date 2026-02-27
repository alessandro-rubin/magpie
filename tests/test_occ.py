"""Tests for OCC symbol parser."""

from datetime import date

import pytest

from magpie.market.occ import is_occ_symbol, parse_occ


class TestParseOCC:
    def test_standard_call(self):
        r = parse_occ("AAPL260320C00275000")
        assert r.underlying == "AAPL"
        assert r.expiry == date(2026, 3, 20)
        assert r.option_type == "call"
        assert r.strike == 275.0

    def test_standard_put(self):
        r = parse_occ("TSLA260417P00350000")
        assert r.underlying == "TSLA"
        assert r.expiry == date(2026, 4, 17)
        assert r.option_type == "put"
        assert r.strike == 350.0

    def test_fractional_strike(self):
        r = parse_occ("SPY260116C00512500")
        assert r.strike == 512.5

    def test_single_char_root(self):
        r = parse_occ("F260320C00012000")
        assert r.underlying == "F"
        assert r.strike == 12.0

    def test_long_root(self):
        r = parse_occ("GOOGL260320P00175000")
        assert r.underlying == "GOOGL"

    def test_preserves_raw(self):
        r = parse_occ("AAPL260320C00275000")
        assert r.raw == "AAPL260320C00275000"

    def test_invalid_too_short(self):
        with pytest.raises(ValueError):
            parse_occ("AAPL")

    def test_invalid_option_type(self):
        with pytest.raises(ValueError):
            parse_occ("AAPL260320X00275000")


class TestIsOCCSymbol:
    def test_valid_occ(self):
        assert is_occ_symbol("AAPL260320C00275000") is True

    def test_stock_ticker(self):
        assert is_occ_symbol("AAPL") is False

    def test_empty(self):
        assert is_occ_symbol("") is False
