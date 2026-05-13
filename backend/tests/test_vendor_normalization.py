import pytest
from app.db.init_db import normalize_vendor


@pytest.mark.parametrize("input_name,expected", [
    ("Widgets Inc.", "widgets"),
    ("widgets, inc.", "widgets"),
    ("WIDGETS INC", "widgets"),
    ("Atlas Industrial Supply", "atlas industrial supply"),
    ("Acme Co.", "acme"),
    ("Acme Corporation", "acme"),
    ("  Acme   Corp  ", "acme"),
    ("Reliable Components Inc.", "reliable components"),
])
def test_normalization_table(input_name, expected):
    assert normalize_vendor(input_name) == expected
