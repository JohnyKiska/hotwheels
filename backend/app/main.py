from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .db import get_db
from .conflict_queue import list_conflicts

app = FastAPI(
    title="Hot Wheels Catalog API",
    version="0.1.0",
    description="Backend foundation for the test Hot Wheels catalog.",
)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Return a basic health status without accessing catalog data."""
    return {"status": "ok"}


@app.get("/conflicts", tags=["review"])
def get_conflicts(
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    conflict_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> dict:
    """List conflicts for review; defaults to unresolved conflicts."""
    try:
        return list_conflicts(
            session,
            status=status,
            severity=severity,
            conflict_type=conflict_type,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
