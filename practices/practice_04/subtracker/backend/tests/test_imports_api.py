"""End-to-end checks for the statement import contract."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.main import app
from app.routers import imports as imports_router

FIXTURE = Path(__file__).parent / "fixtures" / "statement-sample.csv"
NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
KEY = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def pinned_now():
    """Pin the clock so TTL and the rate limit are testable."""
    current = {"value": NOW}
    app.dependency_overrides[imports_router._now] = lambda: current["value"]
    yield current
    app.dependency_overrides.pop(imports_router._now, None)


@pytest.fixture
async def headers(make_headers, pinned_today, pinned_now):
    return await make_headers("importer@example.com")


def upload_payload(name: str = "statement-sample.csv", data: bytes | None = None):
    return {
        "file": (name, data if data is not None else FIXTURE.read_bytes(), "text/csv")
    }


async def upload(client, headers, **kwargs):
    return await client.post(
        "/api/imports/statement", headers=headers, files=upload_payload(**kwargs)
    )


def names(items):
    return {item["name"] for item in items}


# --- Happy path -------------------------------------------------------------


async def test_upload_returns_two_lists_and_statement_facts(client, headers):
    response = await upload(client, headers)
    assert response.status_code == 201
    body = response.json()

    assert names(body["candidates"]) == {
        "Adobe Creative Cloud",
        "Claude.ai",
        "Яндекс Плюс",
        "Notion Labs",
        "Spotify",
        "Netflix",
    }
    assert names(body["candidates_review"]) == {"VPN Service", "Github Pro Annual"}
    assert body["statement"]["rows_total"] == 38
    assert body["statement"]["incomplete_data"] is True
    assert body["statement"]["skipped_by_code"] == {"row.amount_missing": 1}
    assert all(item["preselect_recommended"] for item in body["candidates"])
    assert not any(item["preselect_recommended"] for item in body["candidates_review"])
    # Money crosses the boundary as a string, never as a float.
    assert body["candidates"][0]["amount"] == "54.99"


async def test_end_to_end_owner_deselects_one_and_confirms(client, headers):
    body = (await upload(client, headers)).json()
    chosen = [item for item in body["candidates"] if item["name"] != "Notion Labs"]

    confirmed = await client.post(
        f"/api/imports/statement/{body['import_id']}/confirm",
        headers=headers,
        json={
            "idempotency_key": KEY,
            "items": [{"candidate_id": item["candidate_id"]} for item in chosen],
        },
    )
    assert confirmed.status_code == 201
    result = confirmed.json()
    assert result["created_count"] == 5
    assert result["skipped_count"] == 0

    listed = (await client.get("/api/subscriptions", headers=headers)).json()
    assert names(listed) == names(chosen)

    summary = (await client.get("/api/stats/summary", headers=headers)).json()
    expected = sum(float(item["amount"]) for item in chosen)
    assert float(summary["monthly_total"]) == pytest.approx(expected, abs=0.01)


async def test_nothing_is_created_before_confirmation(client, headers):
    await upload(client, headers)
    assert (await client.get("/api/subscriptions", headers=headers)).json() == []


async def test_import_is_restored_by_id_after_a_reload(client, headers):
    body = (await upload(client, headers)).json()
    again = await client.get(
        f"/api/imports/statement/{body['import_id']}", headers=headers
    )
    assert again.status_code == 200
    assert again.json()["candidates"] == body["candidates"]


# --- Duplicates and updates -------------------------------------------------


async def make_netflix(client, headers, amount="15.49"):
    response = await client.post(
        "/api/subscriptions",
        headers=headers,
        json={
            "name": "Netflix",
            "amount": amount,
            "billing_cycle": "monthly",
            "start_date": "2026-07-02",
        },
    )
    return response.json()


async def test_existing_subscription_is_matched_and_not_preselected(client, headers):
    await make_netflix(client, headers)
    body = (await upload(client, headers)).json()
    netflix = next(i for i in body["candidates"] if i["name"] == "Netflix")

    assert netflix["duplicate_match"] == "amount_differs"
    assert netflix["matched_subscription"]["amount"] == "15.49"
    assert netflix["preselect_recommended"] is False


async def test_duplicate_without_an_action_is_refused(client, headers):
    await make_netflix(client, headers)
    body = (await upload(client, headers)).json()
    netflix = next(i for i in body["candidates"] if i["name"] == "Netflix")

    response = await client.post(
        f"/api/imports/statement/{body['import_id']}/confirm",
        headers=headers,
        json={
            "idempotency_key": KEY,
            "items": [{"candidate_id": netflix["candidate_id"]}],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "confirm.action_required"


async def test_update_narrows_to_the_amount_and_reports_both_values(client, headers):
    existing = await make_netflix(client, headers)
    body = (await upload(client, headers)).json()
    netflix = next(i for i in body["candidates"] if i["name"] == "Netflix")

    response = await client.post(
        f"/api/imports/statement/{body['import_id']}/confirm",
        headers=headers,
        json={
            "idempotency_key": KEY,
            "items": [
                {
                    "candidate_id": netflix["candidate_id"],
                    "action": "update",
                    "target_subscription_id": existing["id"],
                    "expected_amount": "15.49",
                }
            ],
        },
    )
    assert response.status_code == 201
    updated = response.json()["updated"][0]
    assert updated["previous"] == {"amount": "15.49"}
    assert updated["current"] == {"amount": "17.99"}

    listed = (await client.get("/api/subscriptions", headers=headers)).json()
    assert len(listed) == 1 and listed[0]["amount"] == "17.99"


# --- Repeats, conflicts and partial results --------------------------------


async def test_repeating_a_confirmation_creates_nothing_new(client, headers):
    body = (await upload(client, headers)).json()
    items = [{"candidate_id": body["candidates"][0]["candidate_id"]}]
    payload = {"idempotency_key": KEY, "items": items}
    url = f"/api/imports/statement/{body['import_id']}/confirm"

    first = await client.post(url, headers=headers, json=payload)
    second = await client.post(url, headers=headers, json=payload)

    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json() == first.json()
    assert len((await client.get("/api/subscriptions", headers=headers)).json()) == 1


async def test_a_new_key_on_a_confirmed_import_is_a_conflict(client, headers):
    body = (await upload(client, headers)).json()
    url = f"/api/imports/statement/{body['import_id']}/confirm"
    items = [{"candidate_id": body["candidates"][0]["candidate_id"]}]

    await client.post(
        url, headers=headers, json={"idempotency_key": KEY, "items": items}
    )
    again = await client.post(
        url, headers=headers, json={"idempotency_key": KEY[::-1], "items": items}
    )
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "import.already_confirmed"


async def test_a_conflicting_element_is_skipped_while_the_rest_are_applied(
    client, headers
):
    """Decision Р13: a stale amount costs one element, not the whole import."""
    existing = await make_netflix(client, headers)
    body = (await upload(client, headers)).json()
    netflix = next(i for i in body["candidates"] if i["name"] == "Netflix")
    other = next(i for i in body["candidates"] if i["name"] == "Claude.ai")

    await client.patch(
        f"/api/subscriptions/{existing['id']}",
        headers=headers,
        json={"amount": "16.99"},
    )

    response = await client.post(
        f"/api/imports/statement/{body['import_id']}/confirm",
        headers=headers,
        json={
            "idempotency_key": KEY,
            "items": [
                {
                    "candidate_id": netflix["candidate_id"],
                    "action": "update",
                    "target_subscription_id": existing["id"],
                    "expected_amount": "15.49",
                },
                {"candidate_id": other["candidate_id"]},
            ],
        },
    )
    assert response.status_code == 201
    result = response.json()
    assert result["created_count"] == 1
    assert result["skipped"][0]["code"] == "confirm.amount_conflict"
    assert result["skipped"][0]["params"]["actual_amount"] == "16.99"


async def test_a_lone_conflicting_element_reports_its_own_cause(client, headers):
    existing = await make_netflix(client, headers)
    body = (await upload(client, headers)).json()
    netflix = next(i for i in body["candidates"] if i["name"] == "Netflix")
    await client.patch(
        f"/api/subscriptions/{existing['id']}",
        headers=headers,
        json={"amount": "16.99"},
    )

    response = await client.post(
        f"/api/imports/statement/{body['import_id']}/confirm",
        headers=headers,
        json={
            "idempotency_key": KEY,
            "items": [
                {
                    "candidate_id": netflix["candidate_id"],
                    "action": "update",
                    "target_subscription_id": existing["id"],
                    "expected_amount": "15.49",
                }
            ],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "confirm.amount_conflict"


# --- File-level failures and limits ----------------------------------------


async def test_a_file_without_the_expected_columns_is_refused(client, headers):
    response = await upload(client, headers, data=b"a;b;c\n1;2;3\n")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "statement.missing_columns"


async def test_a_file_over_the_limit_is_refused_before_parsing(client, headers):
    response = await upload(client, headers, data=b"x" * (2 * 1024 * 1024 + 1))
    assert response.status_code == 413
    detail = response.json()["detail"]
    assert detail["code"] == "statement.too_large"
    assert detail["params"]["limit_bytes"] == 2 * 1024 * 1024


async def test_a_file_of_the_wrong_type_is_refused(client, headers):
    response = await upload(client, headers, name="statement.pdf", data=b"%PDF-1.4")
    assert response.status_code == 415


async def test_a_fourth_active_import_is_refused_with_the_list_of_the_others(
    client, headers
):
    for _ in range(3):
        assert (await upload(client, headers)).status_code == 201
    response = await upload(client, headers)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "import.too_many_active"
    assert len(detail["params"]["active"]) == 3
    assert detail["params"]["active"][0]["filename"] == "statement-sample.csv"


async def test_an_expired_import_is_gone(client, headers, pinned_now):
    body = (await upload(client, headers)).json()
    pinned_now["value"] = NOW + timedelta(hours=3)

    response = await client.get(
        f"/api/imports/statement/{body['import_id']}", headers=headers
    )
    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "import.expired"


async def test_discarding_frees_the_slot_and_hides_the_import(client, headers):
    body = (await upload(client, headers)).json()
    assert (
        await client.delete(
            f"/api/imports/statement/{body['import_id']}", headers=headers
        )
    ).status_code == 204

    gone = await client.get(
        f"/api/imports/statement/{body['import_id']}", headers=headers
    )
    assert gone.status_code == 404


async def test_another_owner_cannot_see_the_import(client, headers, make_headers):
    body = (await upload(client, headers)).json()
    stranger = await make_headers("stranger@example.com")

    response = await client.get(
        f"/api/imports/statement/{body['import_id']}", headers=stranger
    )
    assert response.status_code == 404
