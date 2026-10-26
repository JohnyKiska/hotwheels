from fastapi import FastAPI

app = FastAPI(
    title="Hot Wheels Catalog API",
    version="0.1.0",
    description="Backend foundation for the test Hot Wheels catalog.",
)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Return a basic health status without accessing catalog data."""
    return {"status": "ok"}
