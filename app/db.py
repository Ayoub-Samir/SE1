from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.config import settings


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_dirs() -> None:
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)


def db_path() -> Path:
    _ensure_dirs()
    return Path(settings.data_dir) / "app.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(seed_csv_path: Path | None = None) -> None:
    _ensure_dirs()
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
              project_code TEXT PRIMARY KEY,
              project_name TEXT NOT NULL,
              ministry TEXT NOT NULL,
              total_budget_try INTEGER NOT NULL,
              spent_try INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS revision_requests (
              id TEXT PRIMARY KEY,
              filename TEXT NOT NULL,
              stored_path TEXT NOT NULL,
              status TEXT NOT NULL, -- pending | approved | rejected

              extracted_text TEXT,
              project_code TEXT,
              requested_amount_try INTEGER,
              justification TEXT,
              extracted_json TEXT,

              risk_score INTEGER,
              risk_notes TEXT,

              decision TEXT,
              decision_note TEXT,
              decided_at TEXT,

              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
              -- project_code serbest metin olarak tutulur; örnek proje DB'siyle eşleşmeyebilir.
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              request_id TEXT NOT NULL,
              action TEXT NOT NULL,
              detail TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY(request_id) REFERENCES revision_requests(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS project_revisions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              request_id TEXT NOT NULL UNIQUE,
              project_code TEXT NOT NULL,
              amount_try INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY(request_id) REFERENCES revision_requests(id) ON DELETE CASCADE
              -- project_code serbest metin olarak tutulur; dashboard'da örnek projelerle eşleştirilir.
            );
            """
        )

    migrate_db()

    if seed_csv_path:
        seed_projects_if_empty(seed_csv_path)


def seed_projects_if_empty(seed_csv_path: Path) -> None:
    seed_csv_path = seed_csv_path.resolve()
    if not seed_csv_path.exists():
        return

    with connect() as conn:
        existing = conn.execute("SELECT COUNT(1) AS c FROM projects").fetchone()["c"]
        if existing and int(existing) > 0:
            return

        now = utc_now_iso()
        with seed_csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append(
                    (
                        row["project_code"].strip(),
                        row["project_name"].strip(),
                        row["ministry"].strip(),
                        int(row["total_budget_try"]),
                        int(row["spent_try"]),
                        now,
                        now,
                    )
                )
        conn.executemany(
            """
            INSERT INTO projects (
              project_code, project_name, ministry, total_budget_try, spent_try, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def _table_has_fk_to_projects(conn: sqlite3.Connection, table: str) -> bool:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    return any(r["table"] == "projects" for r in rows)


def migrate_db() -> None:
    """
    Lightweight migration for earlier demo DBs.

    - Drops foreign keys from revision_requests.project_code -> projects.project_code
    - Drops foreign keys from project_revisions.project_code -> projects.project_code
      (project_code is treated as free text so requests don't fail if not in seed DB)
    """
    with connect() as conn:
        needs_revision_requests = _table_has_fk_to_projects(conn, "revision_requests")
        needs_project_revisions = _table_has_fk_to_projects(conn, "project_revisions")
        if not (needs_revision_requests or needs_project_revisions):
            return

        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.execute("BEGIN")
            if needs_revision_requests:
                conn.execute(
                    """
                    CREATE TABLE revision_requests_new (
                      id TEXT PRIMARY KEY,
                      filename TEXT NOT NULL,
                      stored_path TEXT NOT NULL,
                      status TEXT NOT NULL,
                      extracted_text TEXT,
                      project_code TEXT,
                      requested_amount_try INTEGER,
                      justification TEXT,
                      extracted_json TEXT,
                      risk_score INTEGER,
                      risk_notes TEXT,
                      decision TEXT,
                      decision_note TEXT,
                      decided_at TEXT,
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO revision_requests_new (
                      id, filename, stored_path, status,
                      extracted_text, project_code, requested_amount_try, justification, extracted_json,
                      risk_score, risk_notes,
                      decision, decision_note, decided_at,
                      created_at, updated_at
                    )
                    SELECT
                      id, filename, stored_path, status,
                      extracted_text, project_code, requested_amount_try, justification, extracted_json,
                      risk_score, risk_notes,
                      decision, decision_note, decided_at,
                      created_at, updated_at
                    FROM revision_requests
                    """
                )
                conn.execute("DROP TABLE revision_requests")
                conn.execute("ALTER TABLE revision_requests_new RENAME TO revision_requests")

            if needs_project_revisions:
                conn.execute(
                    """
                    CREATE TABLE project_revisions_new (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      request_id TEXT NOT NULL UNIQUE,
                      project_code TEXT NOT NULL,
                      amount_try INTEGER NOT NULL,
                      created_at TEXT NOT NULL,
                      FOREIGN KEY(request_id) REFERENCES revision_requests(id) ON DELETE CASCADE
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO project_revisions_new (id, request_id, project_code, amount_try, created_at)
                    SELECT id, request_id, project_code, amount_try, created_at
                    FROM project_revisions
                    """
                )
                conn.execute("DROP TABLE project_revisions")
                conn.execute("ALTER TABLE project_revisions_new RENAME TO project_revisions")

            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON")


def execute(sql: str, params: Iterable[Any] = ()) -> None:
    with connect() as conn:
        conn.execute(sql, tuple(params))
        conn.commit()


def fetch_one(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None


def fetch_all(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]


def add_audit(request_id: str, action: str, detail: str | None = None) -> None:
    execute(
        "INSERT INTO audit_logs (request_id, action, detail, created_at) VALUES (?, ?, ?, ?)",
        (request_id, action, detail, utc_now_iso()),
    )


@dataclass(frozen=True)
class Project:
    project_code: str
    project_name: str
    ministry: str
    total_budget_try: int
    spent_try: int

    @property
    def remaining_try(self) -> int:
        return max(0, self.total_budget_try - self.spent_try)

    @property
    def spent_ratio(self) -> float:
        if self.total_budget_try <= 0:
            return 0.0
        return min(1.0, self.spent_try / self.total_budget_try)


def get_project(project_code: str) -> Project | None:
    row = fetch_one(
        """
        SELECT project_code, project_name, ministry, total_budget_try, spent_try
        FROM projects WHERE project_code = ?
        """,
        (project_code,),
    )
    if not row:
        return None
    return Project(
        project_code=row["project_code"],
        project_name=row["project_name"],
        ministry=row["ministry"],
        total_budget_try=int(row["total_budget_try"]),
        spent_try=int(row["spent_try"]),
    )


def list_projects() -> list[Project]:
    rows = fetch_all(
        """
        SELECT project_code, project_name, ministry, total_budget_try, spent_try
        FROM projects ORDER BY project_code
        """
    )
    return [
        Project(
            project_code=r["project_code"],
            project_name=r["project_name"],
            ministry=r["ministry"],
            total_budget_try=int(r["total_budget_try"]),
            spent_try=int(r["spent_try"]),
        )
        for r in rows
    ]
