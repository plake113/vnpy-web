"""示例资源接口测试。"""

from __future__ import annotations

from httpx import AsyncClient


async def test_create_and_get_item(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/items",
        json={"name": "alpha", "description": "第一个示例"},
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["id"] >= 1
    assert item["name"] == "alpha"
    assert item["is_active"] is True
    assert item["created_at"]

    detail = await client.get(f"/api/v1/items/{item['id']}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "alpha"


async def test_list_items_with_pagination_and_filters(client: AsyncClient) -> None:
    for name in ("alpha", "beta", "gamma"):
        response = await client.post("/api/v1/items", json={"name": name})
        assert response.status_code == 201

    first_page = await client.get("/api/v1/items", params={"page": 1, "page_size": 2})
    assert first_page.status_code == 200
    body = first_page.json()
    assert body["total"] == 3
    assert body["pages"] == 2
    assert len(body["items"]) == 2

    searched = await client.get("/api/v1/items", params={"search": "bet"})
    assert [item["name"] for item in searched.json()["items"]] == ["beta"]

    inactive = await client.post(
        "/api/v1/items", json={"name": "delta", "is_active": False}
    )
    assert inactive.status_code == 201
    filtered = await client.get("/api/v1/items", params={"is_active": "false"})
    assert [item["name"] for item in filtered.json()["items"]] == ["delta"]


async def test_update_item(client: AsyncClient) -> None:
    created = await client.post("/api/v1/items", json={"name": "alpha"})
    item_id = created.json()["id"]

    updated = await client.patch(
        f"/api/v1/items/{item_id}",
        json={"description": "已更新", "is_active": False},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["description"] == "已更新"
    assert body["is_active"] is False
    assert body["name"] == "alpha"


async def test_duplicate_name_returns_conflict(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/items", json={"name": "alpha"})).status_code == 201

    duplicate = await client.post("/api/v1/items", json={"name": "alpha"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "ITEM_NAME_CONFLICT"


async def test_delete_item(client: AsyncClient) -> None:
    created = await client.post("/api/v1/items", json={"name": "alpha"})
    item_id = created.json()["id"]

    deleted = await client.delete(f"/api/v1/items/{item_id}")
    assert deleted.status_code == 204
    assert deleted.content == b""

    missing = await client.get(f"/api/v1/items/{item_id}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "ITEM_NOT_FOUND"


async def test_validation_error_envelope(client: AsyncClient) -> None:
    response = await client.post("/api/v1/items", json={"name": ""})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]

    extra = await client.post(
        "/api/v1/items", json={"name": "alpha", "unexpected": 1}
    )
    assert extra.status_code == 422
