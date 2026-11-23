from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.auth import DatabaseSession, require_admin
from app.models import ReliabilityTestRun
from app.services.reports import reliability_report, render_junit, render_report

reports_router = APIRouter(
    prefix="/localpay/admin/v1/projects/{project_id}/test-runs/{run_id}/report",
    tags=["LocalPay reports"],
    dependencies=[Depends(require_admin)],
)


def get_report(
    project_id: UUID, run_id: UUID, session: DatabaseSession
) -> ReliabilityTestRun:
    run = session.get(ReliabilityTestRun, (project_id, run_id))
    if run is None:
        raise HTTPException(404)
    return run


@reports_router.get("/json")
def report_json(project_id: UUID, run_id: UUID, session: DatabaseSession) -> Response:
    run = get_report(project_id, run_id, session)
    return JSONResponse(
        reliability_report(session, run),
        headers={
            "Content-Disposition": f'attachment; filename="localpay-report-{run.id}.json"'
        },
    )


@reports_router.get("/html")
def report_html(project_id: UUID, run_id: UUID, session: DatabaseSession) -> Response:
    run = get_report(project_id, run_id, session)
    return HTMLResponse(
        render_report(reliability_report(session, run)),
        headers={
            "Content-Disposition": f'attachment; filename="localpay-report-{run.id}.html"',
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        },
    )


@reports_router.get("/junit")
def report_junit(project_id: UUID, run_id: UUID, session: DatabaseSession) -> Response:
    run = get_report(project_id, run_id, session)
    if run.status in {"pending", "running"}:
        raise HTTPException(409)
    return Response(
        render_junit(run),
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="localpay-report-{run.id}.xml"'
        },
    )
