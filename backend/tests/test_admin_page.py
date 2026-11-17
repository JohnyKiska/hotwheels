from fastapi.testclient import TestClient

from app.main import app


def test_admin_page_is_served_by_backend():
    response = TestClient(app).get("/admin")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "HW Catalog · Администрирование" in response.text
    assert "/api/v1/admin/catalog/castings" in response.text
