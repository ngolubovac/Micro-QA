"""
db_setup.py — Micro QA
============================================================
Handles SQLite database initialisation and seeding.

Tables:
  - units        : Medical devices / treatment machines
  - tests        : QA test definitions with tolerances
  - test_results : Measured QA values linked to unit + test
  - service_logs : Downtime and maintenance records
"""

import sqlite3
import os

# ---------------------------------------------------------------------------
# Path Configuration
# ---------------------------------------------------------------------------
DB_PATH = os.path.join(os.path.dirname(__file__), "qa_data.db")


def get_connection() -> sqlite3.Connection:
    """Return a sqlite3 connection with foreign-key enforcement enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# ---------------------------------------------------------------------------
# Schema Creation
# ---------------------------------------------------------------------------
def init_db() -> None:
    """
    Create all required tables if they do not already exist.
    Safe to call every time the app starts (idempotent).
    """
    ddl_statements = [
        # ── Units (medical devices) ──────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS units (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL UNIQUE,
            modality    TEXT    NOT NULL,           -- e.g. LINAC, CT, MRI
            manufacturer TEXT,
            model       TEXT,
            serial_no   TEXT,
            location    TEXT,
            notes       TEXT,
            created_at  TEXT    DEFAULT (datetime('now'))
        );
        """,

        # ── Tests (QA test definitions) ──────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS tests (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT    NOT NULL,
            description     TEXT,
            data_type       TEXT    NOT NULL CHECK(data_type IN ('float','boolean','choice')),
            unit_of_measure TEXT,                  -- e.g. %, cGy, mm
            reference_value REAL,                  -- expected / baseline
            tolerance_low   REAL,                  -- lower warn limit  (value < tol_low → warning)
            tolerance_high  REAL,                  -- upper warn limit  (value > tol_high → warning)
            action_low      REAL,                  -- lower action limit
            action_high     REAL,                  -- upper action limit
            choices         TEXT,                  -- CSV list for 'choice' type
            frequency       TEXT    DEFAULT 'Daily',  -- Daily / Weekly / Monthly
            created_at      TEXT    DEFAULT (datetime('now'))
        );
        """,

        # ── Unit–Test Link: which tests belong to which unit ─────────────
        """
        CREATE TABLE IF NOT EXISTS unit_tests (
            unit_id  INTEGER NOT NULL REFERENCES units(id)  ON DELETE CASCADE,
            test_id  INTEGER NOT NULL REFERENCES tests(id)  ON DELETE CASCADE,
            PRIMARY KEY (unit_id, test_id)
        );
        """,

        # ── Test Results (measured values) ───────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS test_results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            unit_id         INTEGER NOT NULL REFERENCES units(id)  ON DELETE CASCADE,
            test_id         INTEGER NOT NULL REFERENCES tests(id)  ON DELETE CASCADE,
            value_float     REAL,                  -- used when data_type = 'float'
            value_boolean   INTEGER,               -- 0/1, used when data_type = 'boolean'
            value_choice    TEXT,                  -- used when data_type = 'choice'
            status          TEXT,                  -- 'OK', 'Tolerance', 'Action'
            performed_by    TEXT,
            comment         TEXT,
            performed_at    TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        """,

        # ── Service Logs ─────────────────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS service_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            unit_id         INTEGER NOT NULL REFERENCES units(id)  ON DELETE CASCADE,
            event_type      TEXT    NOT NULL,      -- 'Downtime', 'Maintenance', 'Repair', 'Note'
            start_datetime  TEXT    NOT NULL,
            end_datetime    TEXT,                  -- NULL if ongoing
            performed_by    TEXT,
            description     TEXT,
            created_at      TEXT    DEFAULT (datetime('now'))
        );
        """,

        # ── Calibration Logs (TRS-398 results) ──────────────────────────
        """
        CREATE TABLE IF NOT EXISTS calibration_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            beam_type       TEXT    NOT NULL,       -- 'photon' | 'electron'
            unit_name       TEXT,
            institution     TEXT,
            physicist       TEXT,
            chamber         TEXT,
            energy          TEXT,
            setup           TEXT,
            n_dw            REAL,
            kq              REAL,
            k_pol           REAL,
            k_s             REAL,
            k_tp            REAL,
            k_vol_fff       REAL,                  -- FFF volume correction (Farmer)
            m_corrected     REAL,
            dose_mu_zref    REAL,
            dose_mu_zmax    REAL,
            notes           TEXT,
            performed_at    TEXT    DEFAULT (datetime('now'))
        );
        """,
    ]

    with get_connection() as conn:
        for stmt in ddl_statements:
            conn.execute(stmt)
        conn.commit()

    print(f"[db_setup] Database ready at: {DB_PATH}")


# ---------------------------------------------------------------------------
# Seed Data (runs only if tables are empty)
# ---------------------------------------------------------------------------
def seed_db() -> None:
    """
    Populate the database with realistic demo data for a LINAC unit.
    Skips seeding if data already exists.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        # ── 1. Seed Units ────────────────────────────────────────────────
        cur.execute("SELECT COUNT(*) FROM units;")
        if cur.fetchone()[0] == 0:
            units = [
                ("Varian TrueBeam #1", "LINAC",  "Varian Medical Systems", "TrueBeam",  "SN-TB-001", "Vault 1",  "Primary treatment LINAC"),
                ("Varian TrueBeam #2", "LINAC",  "Varian Medical Systems", "TrueBeam",  "SN-TB-002", "Vault 2",  "Secondary treatment LINAC"),
                ("Siemens SOMATOM CT", "CT",     "Siemens Healthineers",   "SOMATOM Definition AS+", "SN-CT-007", "CT Suite 3", "CT Simulation scanner"),
            ]
            cur.executemany(
                "INSERT INTO units (name, modality, manufacturer, model, serial_no, location, notes) VALUES (?,?,?,?,?,?,?);",
                units,
            )

        # ── 2. Seed Tests ────────────────────────────────────────────────
        cur.execute("SELECT COUNT(*) FROM tests;")
        if cur.fetchone()[0] == 0:
            tests = [
                # (name, description, data_type, unit_of_measure, ref, tol_lo, tol_hi, act_lo, act_hi, choices, freq)
                (
                    "Daily Output Constancy",
                    "Measures the daily beam output relative to a calibrated reference value.",
                    "float", "%", 100.0, 97.0, 103.0, 95.0, 105.0, None, "Daily",
                ),
                (
                    "Flatness – 6 MV",
                    "Beam flatness measurement at 6 MV photon energy.",
                    "float", "%", 0.0, -1.5, 1.5, -2.5, 2.5, None, "Daily",
                ),
                (
                    "Symmetry – 6 MV",
                    "Beam symmetry measurement at 6 MV photon energy.",
                    "float", "%", 0.0, -1.5, 1.5, -2.5, 2.5, None, "Daily",
                ),
                (
                    "Laser Alignment Check",
                    "Verify room lasers align with the radiation isocenter.",
                    "float", "mm", 0.0, -1.0, 1.0, -2.0, 2.0, None, "Daily",
                ),
                (
                    "Door Interlock",
                    "Pass/Fail check for treatment room door interlock.",
                    "boolean", None, None, None, None, None, None, None, "Daily",
                ),
                (
                    "kVp Accuracy – CT",
                    "CT tube voltage accuracy check.",
                    "float", "%", 0.0, -1.0, 1.0, -2.0, 2.0, None, "Monthly",
                ),
            ]
            cur.executemany(
                """INSERT INTO tests
                   (name, description, data_type, unit_of_measure, reference_value,
                    tolerance_low, tolerance_high, action_low, action_high, choices, frequency)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?);""",
                tests,
            )

        # ── 3. Link tests to units (unit_tests junction) ─────────────────
        cur.execute("SELECT COUNT(*) FROM unit_tests;")
        if cur.fetchone()[0] == 0:
            cur.execute("SELECT id FROM units;")
            unit_ids = [r[0] for r in cur.fetchall()]

            cur.execute("SELECT id FROM tests;")
            test_ids = [r[0] for r in cur.fetchall()]

            # Assign LINAC tests (id 1–5) to LINACs (id 1–2), CT test to CT (id 3)
            linac_tests = test_ids[:5]   # Daily Output, Flatness, Symmetry, Laser, Door
            ct_tests    = test_ids[5:]   # kVp Accuracy

            for uid in unit_ids[:2]:
                for tid in linac_tests:
                    cur.execute("INSERT OR IGNORE INTO unit_tests VALUES (?,?);", (uid, tid))

            if len(unit_ids) >= 3:
                for tid in ct_tests:
                    cur.execute("INSERT OR IGNORE INTO unit_tests VALUES (?,?);", (unit_ids[2], tid))

        # ── 4. Seed historical test results (30 days of daily output) ────
        cur.execute("SELECT COUNT(*) FROM test_results;")
        if cur.fetchone()[0] == 0:
            import random, datetime
            random.seed(42)

            output_test_id = cur.execute("SELECT id FROM tests WHERE name='Daily Output Constancy';").fetchone()[0]
            unit1_id       = cur.execute("SELECT id FROM units  WHERE name='Varian TrueBeam #1';").fetchone()[0]

            results = []
            base_date = datetime.date.today() - datetime.timedelta(days=30)
            for i in range(30):
                day = base_date + datetime.timedelta(days=i)
                value = round(100.0 + random.gauss(0, 0.8), 2)   # realistic scatter
                if value < 95.0 or value > 105.0:
                    status = "Action"
                elif value < 97.0 or value > 103.0:
                    status = "Tolerance"
                else:
                    status = "OK"
                results.append((
                    unit1_id, output_test_id,
                    value, None, None,
                    status, "Seed Script", "Auto-generated seed entry",
                    f"{day.isoformat()}T08:30:00",
                ))

            cur.executemany(
                """INSERT INTO test_results
                   (unit_id, test_id, value_float, value_boolean, value_choice,
                    status, performed_by, comment, performed_at)
                   VALUES (?,?,?,?,?,?,?,?,?);""",
                results,
            )

        conn.commit()

    print("[db_setup] Seed data applied.")


# ---------------------------------------------------------------------------
# Entry point (run directly to initialise the DB)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    seed_db()
    print("[db_setup] Done.")
