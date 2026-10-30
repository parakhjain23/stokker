import sqlite3

import pytest

from stockkk import db


def _insert(con):
    con.execute("INSERT INTO recommendations (horizon, symbol, direction, entry, stop, target) "
                "VALUES ('swing','TCS','BUY',100,95,110)")
    return con.execute("SELECT id FROM recommendations").fetchone()["id"]


def test_insert_and_read():
    con = db.connect(":memory:")
    rid = _insert(con)
    row = con.execute("SELECT * FROM recommendations WHERE id=?", (rid,)).fetchone()
    assert row["symbol"] == "TCS" and row["status"] == "OPEN"


def test_core_fields_are_immutable():
    con = db.connect(":memory:")
    rid = _insert(con)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE recommendations SET target=120 WHERE id=?", (rid,))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("DELETE FROM recommendations WHERE id=?", (rid,))


def test_status_update_allowed():
    con = db.connect(":memory:")
    rid = _insert(con)
    con.execute("UPDATE recommendations SET status='TARGET_HIT', exit_price=110 WHERE id=?", (rid,))
    assert con.execute("SELECT status FROM recommendations").fetchone()[0] == "TARGET_HIT"
