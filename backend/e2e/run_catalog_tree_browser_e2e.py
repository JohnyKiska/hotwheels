"""Browser-level integration test for catalog/tree.html against a live HTTP API."""
from playwright.sync_api import sync_playwright
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import CatalogNode, Casting, ChangeLog, Release


PAGE_URL = "http://127.0.0.1:5500/catalog/tree.html"
API_URL = "http://127.0.0.1:8000"


def main() -> None:
    with SessionLocal() as session:
        release_node = (
            session.query(CatalogNode)
            .filter_by(node_type="release", label_override="E2E Skyline Release")
            .one()
        )
        release_id = release_node.release_id
        original_parent_id = release_node.parent_id
        release = session.get(Release, release_id)
        casting_id = release.casting_id
        group_b = (
            session.query(CatalogNode)
            .filter_by(node_type="group", label_override="E2E Group B")
            .one()
        )
        group_b_id = group_b.id

    browser_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda error: browser_errors.append(str(error)))
        page.goto(PAGE_URL, wait_until="domcontentloaded")
        page.locator("#apiBase").fill(API_URL)
        page.locator("#connect").click()
        page.get_by_text("Подключение успешно. Дерево загружено с сервера.").wait_for()

        release_row = page.locator(f'.tree-row[data-id="{release_node.id}"]')
        release_row.wait_for()
        assert page.locator(".tree-row[data-type='release']").count() == 1

        release_row.click()
        page.locator("#newParent").select_option(group_b_id)
        page.locator("#moveReason").fill("Browser E2E integration test")
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#move").click()
        page.get_by_text(
            "Перемещение сохранено, дерево обновлено. Запись аудита создана сервером."
        ).wait_for(timeout=10000)

        moved_row = page.locator(f'.tree-row[data-id="{release_node.id}"]')
        moved_row.wait_for()
        assert page.locator("#connectionStatus").inner_text() == (
            "Подключение успешно. Дерево загружено с сервера."
        )
        assert page.locator("#moveStatus").inner_text() == (
            "Перемещение сохранено, дерево обновлено. Запись аудита создана сервером."
        )
        assert not browser_errors, f"Browser JavaScript errors: {browser_errors}"
        browser.close()

    # Verify persisted state independently of the UI/API response.
    with SessionLocal() as session:
        moved = session.get(CatalogNode, release_node.id)
        assert moved.parent_id == group_b_id
        assert moved.release_id == release_id
        stored_release = session.get(Release, release_id)
        assert stored_release.casting_id == casting_id
        audit = (
            session.query(ChangeLog)
            .filter_by(
                entity_type="catalog_node",
                entity_id=release_node.id,
                action="moved",
            )
            .one()
        )
        assert audit.old_values["parent_id"] == original_parent_id
        assert audit.new_values["parent_id"] == group_b_id
        assert audit.reason == "Browser E2E integration test"

    print(
        "PASS: Chromium loaded the real page, called the live HTTP API, moved the node, "
        "reloaded the tree, and persisted the audit entry without changing Release/Casting identity."
    )


if __name__ == "__main__":
    main()
