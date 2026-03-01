"""
crud.py — Micro QA
============================================================
Modular CRUD helper functions for every database table.
All functions open and close their own connection using a
context manager (safe for single-user Streamlit usage).
"""

import sqlite3
import pandas as pd
from datetime import datetime
from typing import Optional

from db_setup import DB_PATH, get_connection


# ===========================================================================
# UNITS
# ===========================================================================

def get_units() -> pd.DataFrame:
    """Return all units as a DataFrame."""
    with get_connection() as conn:
        return pd.read_sql("SELECT * FROM units ORDER BY name;", conn)


def get_unit_by_id(unit_id: int) -> Optional[dict]:
    """Return a single unit as a dict, or None if not found."""
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM units WHERE id=?;", (unit_id,))
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def add_unit(
    name: str,
    modality: str,
    manufacturer: str = "",
    model: str = "",
    serial_no: str = "",
    location: str = "",
    notes: str = "",
) -> int:
    """
    Insert a new unit and return its new primary-key id.
    Raises sqlite3.IntegrityError if the name already exists.
    """
    sql = """
        INSERT INTO units (name, modality, manufacturer, model, serial_no, location, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?);
    """
    with get_connection() as conn:
        cur = conn.execute(sql, (name, modality, manufacturer, model, serial_no, location, notes))
        conn.commit()
        return cur.lastrowid


# ===========================================================================
# TESTS
# ===========================================================================

def get_tests() -> pd.DataFrame:
    """Return all test definitions as a DataFrame."""
    with get_connection() as conn:
        return pd.read_sql("SELECT * FROM tests ORDER BY name;", conn)


def get_tests_for_unit(unit_id: int) -> pd.DataFrame:
    """Return only the tests assigned to a specific unit."""
    sql = """
        SELECT t.*
        FROM tests t
        JOIN unit_tests ut ON ut.test_id = t.id
        WHERE ut.unit_id = ?
        ORDER BY t.name;
    """
    with get_connection() as conn:
        return pd.read_sql(sql, conn, params=(unit_id,))


def get_test_by_id(test_id: int) -> Optional[dict]:
    """Return a single test definition as a dict, or None."""
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM tests WHERE id=?;", (test_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return dict(zip([d[0] for d in cur.description], row))


def add_test(
    name: str,
    data_type: str,
    description: str = "",
    unit_of_measure: str = "",
    reference_value: Optional[float] = None,
    tolerance_low: Optional[float] = None,
    tolerance_high: Optional[float] = None,
    action_low: Optional[float] = None,
    action_high: Optional[float] = None,
    choices: Optional[str] = None,
    frequency: str = "Daily",
) -> int:
    """
    Insert a new test definition.
    Returns the new test id.
    """
    sql = """
        INSERT INTO tests
            (name, description, data_type, unit_of_measure, reference_value,
             tolerance_low, tolerance_high, action_low, action_high, choices, frequency)
        VALUES (?,?,?,?,?,?,?,?,?,?,?);
    """
    with get_connection() as conn:
        cur = conn.execute(
            sql,
            (name, description, data_type, unit_of_measure, reference_value,
             tolerance_low, tolerance_high, action_low, action_high, choices, frequency),
        )
        conn.commit()
        return cur.lastrowid


def update_unit(
    unit_id: int,
    name: str,
    modality: str,
    manufacturer: str = "",
    model: str = "",
    serial_no: str = "",
    location: str = "",
    notes: str = "",
) -> None:
    """
    Update all editable fields of an existing unit.
    Raises sqlite3.IntegrityError if the new name collides with another unit.
    """
    sql = """
        UPDATE units
        SET name=?, modality=?, manufacturer=?, model=?,
            serial_no=?, location=?, notes=?
        WHERE id=?;
    """
    with get_connection() as conn:
        conn.execute(sql, (name, modality, manufacturer, model, serial_no, location, notes, unit_id))
        conn.commit()


def assign_test_to_unit(unit_id: int, test_id: int) -> None:
    """Create a link between a unit and a test (unit_tests junction table)."""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO unit_tests (unit_id, test_id) VALUES (?,?);",
            (unit_id, test_id),
        )
        conn.commit()


# ===========================================================================
# TEST RESULTS
# ===========================================================================

def compute_status(
    value: float,
    action_low: Optional[float],
    action_high: Optional[float],
    tolerance_low: Optional[float],
    tolerance_high: Optional[float],
) -> str:
    """
    Determine if a measured value is 'OK', 'Tolerance', or 'Action'
    based on the test's defined limits.

    Priority: Action > Tolerance > OK
    action_low / action_high are the widest limits (worst breach first).
    """
    # ── Action breach ──────────────────────────────────────────────────────
    if action_low is not None and value < action_low:
        return "Action"
    if action_high is not None and value > action_high:
        return "Action"
    # ── Tolerance breach ───────────────────────────────────────────────────
    if tolerance_low is not None and value < tolerance_low:
        return "Tolerance"
    if tolerance_high is not None and value > tolerance_high:
        return "Tolerance"
    return "OK"


def log_result(
    unit_id: int,
    test_id: int,
    value_float: Optional[float] = None,
    value_boolean: Optional[bool] = None,
    value_choice: Optional[str] = None,
    performed_by: str = "",
    comment: str = "",
    performed_at: Optional[str] = None,
) -> str:
    """
    Insert a new test result row and return its computed status string.

    For float tests, status is computed from the test's tolerance limits.
    For boolean / choice tests, status is always 'OK' (pass/fail is implicit).
    """
    if performed_at is None:
        performed_at = datetime.now().isoformat(timespec="seconds")

    # Determine status for float values
    status = "OK"
    if value_float is not None:
        test = get_test_by_id(test_id)
        if test:
            status = compute_status(
                value_float,
                test.get("action_low"),
                test.get("action_high"),
                test.get("tolerance_low"),
                test.get("tolerance_high"),
            )

    sql = """
        INSERT INTO test_results
            (unit_id, test_id, value_float, value_boolean, value_choice,
             status, performed_by, comment, performed_at)
        VALUES (?,?,?,?,?,?,?,?,?);
    """
    bool_int = None if value_boolean is None else int(value_boolean)
    with get_connection() as conn:
        conn.execute(
            sql,
            (unit_id, test_id, value_float, bool_int, value_choice,
             status, performed_by, comment, performed_at),
        )
        conn.commit()

    return status


def get_historical_data(unit_id: int, test_id: int) -> pd.DataFrame:
    """
    Return all recorded results for a unit+test pair, ordered by date asc.
    Columns: id, value_float, value_boolean, value_choice, status,
             performed_by, comment, performed_at.
    """
    sql = """
        SELECT
            tr.id,
            tr.value_float,
            tr.value_boolean,
            tr.value_choice,
            tr.status,
            tr.performed_by,
            tr.comment,
            tr.performed_at
        FROM test_results tr
        WHERE tr.unit_id = ?
          AND tr.test_id = ?
        ORDER BY tr.performed_at ASC;
    """
    with get_connection() as conn:
        df = pd.read_sql(sql, conn, params=(unit_id, test_id))

    # Coerce performed_at to datetime for clean plotting
    df["performed_at"] = pd.to_datetime(df["performed_at"], errors="coerce")
    return df


def get_recent_results(unit_id: int, limit: int = 50) -> pd.DataFrame:
    """
    Return the most recent `limit` results for a given unit (all tests combined).
    Joins to test name for a friendly display.
    """
    sql = """
        SELECT
            t.name  AS test_name,
            tr.value_float,
            tr.value_boolean,
            tr.value_choice,
            tr.status,
            tr.performed_by,
            tr.performed_at
        FROM test_results tr
        JOIN tests t ON t.id = tr.test_id
        WHERE tr.unit_id = ?
        ORDER BY tr.performed_at DESC
        LIMIT ?;
    """
    with get_connection() as conn:
        return pd.read_sql(sql, conn, params=(unit_id, limit))


# ===========================================================================
# SERVICE LOGS
# ===========================================================================

def add_service_log(
    unit_id: int,
    event_type: str,
    start_datetime: str,
    end_datetime: Optional[str] = None,
    performed_by: str = "",
    description: str = "",
) -> int:
    """Insert a new service log entry and return its id."""
    sql = """
        INSERT INTO service_logs
            (unit_id, event_type, start_datetime, end_datetime, performed_by, description)
        VALUES (?,?,?,?,?,?);
    """
    with get_connection() as conn:
        cur = conn.execute(
            sql,
            (unit_id, event_type, start_datetime, end_datetime, performed_by, description),
        )
        conn.commit()
        return cur.lastrowid


def get_service_logs(unit_id: Optional[int] = None) -> pd.DataFrame:
    """
    Return service log entries.
    If unit_id is provided, filters for that unit only.
    Joins unit name for a friendly display.
    """
    base_sql = """
        SELECT
            sl.id,
            u.name  AS unit_name,
            sl.event_type,
            sl.start_datetime,
            sl.end_datetime,
            sl.performed_by,
            sl.description,
            sl.created_at
        FROM service_logs sl
        JOIN units u ON u.id = sl.unit_id
        {where}
        ORDER BY sl.start_datetime DESC;
    """
    if unit_id is not None:
        sql = base_sql.format(where="WHERE sl.unit_id = ?")
        with get_connection() as conn:
            return pd.read_sql(sql, conn, params=(unit_id,))
    else:
        sql = base_sql.format(where="")
        with get_connection() as conn:
            return pd.read_sql(sql, conn)


# ===========================================================================
# SUMMARY / DASHBOARD HELPERS
# ===========================================================================

def get_status_summary() -> pd.DataFrame:
    """
    Return aggregate counts of OK / Tolerance / Action statuses
    per unit for the current calendar day.
    Useful for a dashboard overview widget.
    """
    sql = """
        SELECT
            u.name          AS unit_name,
            tr.status,
            COUNT(*)        AS count
        FROM test_results tr
        JOIN units u ON u.id = tr.unit_id
        WHERE DATE(tr.performed_at) = DATE('now')
        GROUP BY u.name, tr.status
        ORDER BY u.name, tr.status;
    """
    with get_connection() as conn:
        return pd.read_sql(sql, conn)


# ===========================================================================
# CALIBRATION LOGS (TRS-398)
# ===========================================================================

def log_calibration(
    beam_type: str,
    unit_name: str = "",
    institution: str = "",
    physicist: str = "",
    chamber: str = "",
    energy: str = "",
    setup: str = "",
    n_dw: Optional[float] = None,
    kq: Optional[float] = None,
    k_pol: Optional[float] = None,
    k_s: Optional[float] = None,
    k_tp: Optional[float] = None,
    k_vol_fff: Optional[float] = None,
    m_corrected: Optional[float] = None,
    dose_mu_zref: Optional[float] = None,
    dose_mu_zmax: Optional[float] = None,
    notes: str = "",
    performed_at: Optional[str] = None,
) -> int:
    """Insert a TRS-398 calibration result and return its id."""
    if performed_at is None:
        performed_at = datetime.now().isoformat(timespec="seconds")

    sql = """
        INSERT INTO calibration_logs
            (beam_type, unit_name, institution, physicist, chamber, energy,
             setup, n_dw, kq, k_pol, k_s, k_tp, k_vol_fff,
             m_corrected, dose_mu_zref, dose_mu_zmax, notes, performed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
    """
    with get_connection() as conn:
        cur = conn.execute(
            sql,
            (beam_type, unit_name, institution, physicist, chamber, energy,
             setup, n_dw, kq, k_pol, k_s, k_tp, k_vol_fff,
             m_corrected, dose_mu_zref, dose_mu_zmax, notes, performed_at),
        )
        conn.commit()
        return cur.lastrowid


def get_calibration_logs() -> pd.DataFrame:
    """Return all calibration log entries, most recent first."""
    sql = """
        SELECT *
        FROM calibration_logs
        ORDER BY performed_at DESC;
    """
    with get_connection() as conn:
        return pd.read_sql(sql, conn)

