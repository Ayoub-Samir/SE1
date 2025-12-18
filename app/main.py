from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import (
    add_audit,
    fetch_all,
    fetch_one,
    init_db,
    list_projects,
    utc_now_iso,
)
from app.services.notifier import notify_mattermost
from app.services.parse_request import parse_revision_request
from app.services.presentation import generate_presentation
from app.services.risk import calculate_risk
from app.services.text_extract import extract_text


BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title=settings.app_name)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def storage_root() -> Path:
    p = Path(settings.storage_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def output_root() -> Path:
    p = Path(settings.output_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _seed_path() -> Path:
    return BASE_DIR / "data" / "projects_seed.csv"


@app.on_event("startup")
def _startup() -> None:
    init_db(seed_csv_path=_seed_path())
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    storage_root()
    output_root()


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "app_name": settings.app_name},
    )


@app.get("/upload", response_class=HTMLResponse)
def upload_form(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})


def _create_request_record(*, filename: str, stored_path: str) -> str:
    request_id = uuid.uuid4().hex[:12]
    now = utc_now_iso()
    from app.db import execute

    execute(
        """
        INSERT INTO revision_requests (
          id, filename, stored_path, status, created_at, updated_at
        ) VALUES (?, ?, ?, 'pending', ?, ?)
        """,
        (request_id, filename, stored_path, now, now),
    )
    add_audit(request_id, "created", f"filename={filename}")
    return request_id


def _update_request_fields(request_id: str, fields: dict[str, Any]) -> None:
    from app.db import execute

    if not fields:
        return
    set_clause = ", ".join([f"{k} = ?" for k in fields.keys()])
    values = list(fields.values())
    values.append(utc_now_iso())
    values.append(request_id)
    execute(
        f"UPDATE revision_requests SET {set_clause}, updated_at = ? WHERE id = ?",
        values,
    )


def _process_pipeline(request_id: str) -> None:
    row = fetch_one("SELECT * FROM revision_requests WHERE id = ?", (request_id,))
    if not row:
        return

    try:
        stored_path = Path(row["stored_path"])
        text = extract_text(stored_path)
        parsed = parse_revision_request(text)

        project = None
        if parsed.project_code:
            from app.db import get_project

            project = get_project(parsed.project_code)

        risk = calculate_risk(project, parsed.requested_amount_try, parsed.justification)
        payload_json = json.dumps(parsed.extracted, ensure_ascii=False)

        try:
            _update_request_fields(
                request_id,
                {
                    "extracted_text": text,
                    "project_code": parsed.project_code,
                    "requested_amount_try": parsed.requested_amount_try,
                    "justification": parsed.justification,
                    "extracted_json": payload_json,
                    "risk_score": risk.score,
                    "risk_notes": risk.notes,
                },
            )
        except Exception as e:
            # If an older DB schema has FK constraints on project_code, migrate and retry once.
            if "FOREIGN KEY constraint failed" in str(e):
                from app.db import migrate_db

                migrate_db()
                _update_request_fields(
                    request_id,
                    {
                        "extracted_text": text,
                        "project_code": parsed.project_code,
                        "requested_amount_try": parsed.requested_amount_try,
                        "justification": parsed.justification,
                        "extracted_json": payload_json,
                        "risk_score": risk.score,
                        "risk_notes": risk.notes,
                    },
                )
            else:
                raise

        add_audit(request_id, "processed", f"risk={risk.score}")

        msg = (
            f"Revizyon Talebi Alındı (ID: {request_id})\\n"
            f"- Proje: {parsed.project_code or '-'}\\n"
            f"- Tutar (TL): {parsed.requested_amount_try if parsed.requested_amount_try is not None else '-'}\\n"
            f"- Risk: {risk.score}/100\\n"
            f"- İncele: {settings.app_base_url.rstrip('/')}/requests/{request_id}"
        )
        try:
            if notify_mattermost(msg):
                add_audit(request_id, "notified", "mattermost")
        except Exception as e:
            add_audit(request_id, "notify_failed", str(e))
    except Exception as e:
        add_audit(request_id, "process_failed", f"{type(e).__name__}: {e}")
        try:
            _update_request_fields(
                request_id,
                {
                    "risk_notes": f"PROCESSING ERROR: {type(e).__name__}: {e}",
                },
            )
        except Exception:
            pass


@app.post("/upload")
async def upload_submit(background: BackgroundTasks, file: UploadFile = File(...)):
    dest_dir = storage_root() / "requests"
    dest_dir.mkdir(parents=True, exist_ok=True)

    filename = (file.filename or "upload.bin").replace("\\", "_").replace("/", "_")
    tmp_id = uuid.uuid4().hex[:12]
    stored_path = dest_dir / f"{tmp_id}_{filename}"

    content = await file.read()
    stored_path.write_bytes(content)

    created_id = _create_request_record(filename=filename, stored_path=str(stored_path))
    background.add_task(_process_pipeline, created_id)
    return RedirectResponse(url=f"/requests/{created_id}", status_code=303)


@app.get("/requests", response_class=HTMLResponse)
def list_requests(request: Request):
    rows = fetch_all(
        """
        SELECT id, filename, status, project_code, requested_amount_try, risk_score, created_at
        FROM revision_requests
        ORDER BY created_at DESC
        """
    )
    return templates.TemplateResponse("requests.html", {"request": request, "rows": rows})


@app.get("/requests/{request_id}", response_class=HTMLResponse)
def request_detail(request: Request, request_id: str):
    row = fetch_one("SELECT * FROM revision_requests WHERE id = ?", (request_id,))
    if not row:
        return HTMLResponse("Not found", status_code=404)

    project = None
    if row.get("project_code"):
        from app.db import get_project

        project = get_project(row["project_code"])

    audits = fetch_all(
        "SELECT action, detail, created_at FROM audit_logs WHERE request_id = ? ORDER BY id DESC",
        (request_id,),
    )
    return templates.TemplateResponse(
        "request_detail.html",
        {
            "request": request,
            "row": row,
            "project": project,
            "audits": audits,
        },
    )


@app.post("/requests/{request_id}/edit")
def edit_request(
    request_id: str,
    project_code: str = Form(default=""),
    requested_amount_try: str = Form(default=""),
    justification: str = Form(default=""),
):
    amt = None
    try:
        amt = int(requested_amount_try) if requested_amount_try.strip() else None
    except Exception:
        amt = None

    project = None
    if project_code.strip():
        from app.db import get_project

        project = get_project(project_code.strip())

    risk = calculate_risk(project, amt, justification)

    _update_request_fields(
        request_id,
        {
            "project_code": project_code.strip() or None,
            "requested_amount_try": amt,
            "justification": justification.strip() or None,
            "risk_score": risk.score,
            "risk_notes": risk.notes,
        },
    )
    add_audit(request_id, "edited", "manual edit")
    return RedirectResponse(url=f"/requests/{request_id}", status_code=303)


def _write_kb_entry(request_id: str, content: str) -> Path:
    kb_dir = output_root() / "knowledge_base"
    kb_dir.mkdir(parents=True, exist_ok=True)
    path = kb_dir / f"{request_id}.md"
    path.write_text(content, encoding="utf-8")
    return path


def _finalize_decision(request_id: str, decision: str, note: str | None) -> None:
    row = fetch_one("SELECT * FROM revision_requests WHERE id = ?", (request_id,))
    if not row:
        return

    from app.db import execute, get_project

    execute(
        """
        UPDATE revision_requests
        SET status = ?, decision = ?, decision_note = ?, decided_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (decision, decision, (note or None), utc_now_iso(), utc_now_iso(), request_id),
    )
    add_audit(request_id, "decision", decision)

    project = get_project(row["project_code"]) if row.get("project_code") else None

    kb_text = "\n".join(
        [
            f"# Revizyon Talebi Kararı – {request_id}",
            "",
            f"- Karar: **{decision.upper()}**",
            f"- Proje Kodu: {row.get('project_code') or '-'}",
            f"- Talep Tutarı (TL): {row.get('requested_amount_try') if row.get('requested_amount_try') is not None else '-'}",
            f"- Risk: {row.get('risk_score') if row.get('risk_score') is not None else '-'}",
            "",
            "## Not",
            (note or "-"),
            "",
            "## Gerekçe (çıkarılan)",
            (row.get("justification") or "-"),
        ]
    )
    _write_kb_entry(request_id, kb_text)

    if decision == "approved":
        try:
            from app.db import execute

            execute(
                "INSERT OR IGNORE INTO project_revisions (request_id, project_code, amount_try, created_at) VALUES (?, ?, ?, ?)",
                (
                    request_id,
                    row.get("project_code"),
                    int(row.get("requested_amount_try") or 0),
                    utc_now_iso(),
                ),
            )
        except Exception as e:
            add_audit(request_id, "revision_record_failed", str(e))

        pres = generate_presentation(
            output_dir=output_root() / "presentations",
            request_id=request_id,
            project_code=row.get("project_code"),
            project_name=project.project_name if project else None,
            ministry=project.ministry if project else None,
            requested_amount_try=row.get("requested_amount_try"),
            risk_score=row.get("risk_score"),
            decision=decision,
            justification=row.get("justification"),
        )
        add_audit(request_id, "presentation_generated", str(pres.path))


@app.post("/requests/{request_id}/approve")
def approve(request_id: str, note: str = Form(default="")):
    _finalize_decision(request_id, "approved", note.strip() or None)
    return RedirectResponse(url=f"/requests/{request_id}", status_code=303)


@app.post("/requests/{request_id}/reject")
def reject(request_id: str, note: str = Form(default="")):
    _finalize_decision(request_id, "rejected", note.strip() or None)
    return RedirectResponse(url=f"/requests/{request_id}", status_code=303)


@app.get("/requests/{request_id}/download")
def download_original(request_id: str):
    row = fetch_one("SELECT * FROM revision_requests WHERE id = ?", (request_id,))
    if not row:
        return HTMLResponse("Not found", status_code=404)
    path = Path(row["stored_path"])
    if not path.exists():
        return HTMLResponse("File missing", status_code=404)
    return FileResponse(path, filename=row["filename"])


@app.get("/requests/{request_id}/presentation")
def download_presentation(request_id: str):
    pres_dir = output_root() / "presentations"
    pptx = pres_dir / f"{request_id}_YPK_Sunumu.pptx"
    md = pres_dir / f"{request_id}_YPK_Sunumu.md"
    if pptx.exists():
        return FileResponse(pptx, filename=pptx.name)
    if md.exists():
        return FileResponse(md, filename=md.name)
    return HTMLResponse("Sunum henüz üretilmedi (Onay sonrası oluşur).", status_code=404)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    projects = list_projects()
    revisions = fetch_all(
        """
        SELECT project_code, SUM(amount_try) AS total_revision_try
        FROM project_revisions
        GROUP BY project_code
        """
    )
    rev_map = {r["project_code"]: int(r["total_revision_try"] or 0) for r in revisions}
    rows = []
    for p in projects:
        total_rev = rev_map.get(p.project_code, 0)
        rows.append(
            {
                "project_code": p.project_code,
                "project_name": p.project_name,
                "ministry": p.ministry,
                "total_budget_try": p.total_budget_try,
                "spent_try": p.spent_try,
                "approved_revision_try": total_rev,
                "revised_total_try": p.total_budget_try + total_rev,
            }
        )

    reqs = fetch_all(
        """
        SELECT id, project_code, requested_amount_try, status, risk_score, created_at
        FROM revision_requests
        ORDER BY created_at DESC
        LIMIT 20
        """
    )
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "projects": rows, "requests": reqs},
    )
