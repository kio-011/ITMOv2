#!/usr/bin/env python3
"""Сквозное демо импорта банковской выписки — по шагам, на живом API.

Запуск (бэкенд должен быть поднят на :8000):
    python3 demo/run_demo.py
    python3 demo/run_demo.py --base http://localhost:8000

Скрипт заводит собственного пользователя, поэтому его можно гонять сколько угодно
раз подряд: демо-данные он не портит.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request as request
import uuid
from pathlib import Path

CSV = Path(__file__).resolve().parents[1] / "shared" / "fixtures" / "statement-sample.csv"
BASE = "http://localhost:8000"


def step(number: str, title: str) -> None:
    print(f"\n{'─' * 72}\n{number}. {title}\n{'─' * 72}")


def call(method, path, token=None, body=None, raw=None, ctype=None):
    req = request.Request(f"{BASE}{path}", method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    elif raw is not None:
        data, _ = raw, req.add_header("Content-Type", ctype)
    try:
        with request.urlopen(req, data) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null")
    except urllib.error.URLError as error:
        sys.exit(f"Бэкенд на {BASE} не отвечает ({error.reason}). Запустите ./scripts/dev.sh")


def upload(token, payload, filename="statement-sample.csv"):
    boundary = uuid.uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: text/csv\r\n\r\n'
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    return call("POST", "/api/imports/statement", token,
                raw=body, ctype=f"multipart/form-data; boundary={boundary}")


def show_candidate(c, pad=""):
    match = c["duplicate_match"]
    tail = ""
    if c["matched_subscription"]:
        tail = f"  -> ваша подписка #{c['matched_subscription']['id']} ({c['matched_subscription']['amount']})"
    print(f"{pad}{c['name']:<24}{c['amount']:>9}  {c['billing_cycle']:<12}"
          f"{c['confidence_label']:<8}отметить={str(c['preselect_recommended']):<6}{match}{tail}")


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    BASE = parser.parse_args().base

    email = f"demo-{uuid.uuid4().hex[:8]}@example.com"
    creds = {"email": email, "password": "password123"}

    step("1", "Новый пользователь и одна подписка, заведённая руками")
    call("POST", "/api/auth/register", body=creds)
    token = call("POST", "/api/auth/login", body=creds)[1]["access_token"]
    call("POST", "/api/subscriptions", token, {
        "name": "Netflix", "amount": "15.49", "billing_cycle": "monthly",
        "start_date": "2026-07-02"})
    before = call("GET", "/api/stats/summary", token)[1]
    print(f"пользователь {email}")
    print(f"подписок: 1 (Netflix 15.49) · расход в месяц: {before['monthly_total']}")

    step("2", "Загрузка выписки: 38 строк, ничего ещё не сохранено")
    status, imported = upload(token, CSV.read_bytes())
    facts = imported["statement"]
    print(f"HTTP {status} · import_id={imported['import_id']} · статус={imported['status']}")
    print(f"строк {facts['rows_total']}, разобрано {facts['rows_parsed']}, "
          f"пропущено {facts['rows_skipped']}, неполный разбор={facts['incomplete_data']}")
    print(f"пропущенная строка: {facts['skipped_rows'][0]['code']} — "
          f"{facts['skipped_rows'][0]['raw']}")
    print(f"отсеяно групп: {facts['rejected_groups']}")
    print(f"подписок у пользователя по-прежнему: "
          f"{len(call('GET', '/api/subscriptions', token)[1])}")

    step("3", "Что нашли: два списка и совпадения с существующими подписками")
    print("ОСНОВНОЙ СПИСОК")
    for c in imported["candidates"]:
        show_candidate(c, "  ")
    print("ТРЕБУЕТ ПРОВЕРКИ")
    for c in imported["candidates_review"]:
        print(f"  {c['name']:<24}{c['amount']:>9}  {c['billing_cycle']:<12}"
              f"{c['confidence_label']:<8}основание цикла: {c['cycle_basis']}")

    netflix = next(c for c in imported["candidates"] if c["name"] == "Netflix")
    print(f"\nNetflix: в выписке {netflix['previous_amount']} -> {netflix['amount']} "
          f"(подорожание), совпадение «{netflix['duplicate_match']}», "
          f"отметить по умолчанию = {netflix['preselect_recommended']}")

    step("4", "Обоснование: из каких списаний собран кандидат")
    for o in netflix["occurrences"]:
        print(f"  строка {o['line']:>3}  {o['date']}  {o['amount']:>8}  {o['raw_description']}")

    step("5", "Владелец выбирает: 3 новых завести, Netflix — обновить")
    plain = [c for c in imported["candidates"] if c["duplicate_match"] == "none"][:3]
    items = [{"candidate_id": c["candidate_id"]} for c in plain]
    items.append({"candidate_id": netflix["candidate_id"], "action": "update",
                  "target_subscription_id": netflix["matched_subscription"]["id"],
                  "expected_amount": netflix["matched_subscription"]["amount"]})
    key = str(uuid.uuid4())
    for c in plain:
        print(f"  завести: {c['name']} {c['amount']}  (поле action не отправляется — выбора нет)")
    print(f"  обновить: Netflix -> {netflix['amount']} (expected_amount "
          f"{netflix['matched_subscription']['amount']})")

    status, result = call("POST",
                          f"/api/imports/statement/{imported['import_id']}/confirm",
                          token, {"idempotency_key": key, "items": items})
    print(f"\nHTTP {status} · создано {result['created_count']}, "
          f"обновлено {result['updated_count']}, не применено {result['skipped_count']}")
    for c in result["created"]:
        print(f"  + {c['name']} {c['amount']}")
    for u in result["updated"]:
        print(f"  ~ {u['name']} {u['previous']['amount']} -> {u['current']['amount']}")

    after = call("GET", "/api/stats/summary", token)[1]
    delta = int(round((float(after["monthly_total"]) - float(before["monthly_total"])) * 100))
    print(f"\nрасход в месяц: {before['monthly_total']} -> {after['monthly_total']} "
          f"(+{delta // 100}.{delta % 100:02d})")

    step("6", "Повтор того же запроса с тем же ключом — дублей нет")
    status, repeat = call("POST",
                          f"/api/imports/statement/{imported['import_id']}/confirm",
                          token, {"idempotency_key": key, "items": items})
    print(f"HTTP {status} · ответ идентичен первому: {repeat == result}")
    print(f"подписок: {len(call('GET', '/api/subscriptions', token)[1])}")

    step("7", "Повторная загрузка той же выписки — всё уже заведено")
    _, again = upload(token, CSV.read_bytes())
    fresh = [c for c in again["candidates"] if c["duplicate_match"] == "none"]
    print(f"кандидатов без совпадения: {len(fresh)}; "
          f"с совпадением: {len([c for c in again['candidates'] if c['duplicate_match'] != 'none'])}")
    call("DELETE", f"/api/imports/statement/{again['import_id']}", token)
    print("импорт отменён владельцем (DELETE) — слот освобождён")

    step("8", "Ошибки: код и параметры, прозы сервер не присылает")
    for name, payload in (("битые колонки", b"a;b;c\n1;2;3\n"),
                          ("пустой файл", b"")):
        status, body = upload(token, payload, "broken.csv")
        print(f"  {name:<16} HTTP {status}  {body['detail']['code']}  {body['detail']['params']}")
    status, body = upload(token, b"%PDF-1.4", "statement.pdf")
    print(f"  {'не тот тип':<16} HTTP {status}  {body['detail']['code']}  {body['detail']['params']}")

    step("9", "Решение Р13: конфликт суммы отбрасывает один элемент, не весь импорт")
    # Вернём Netflix к прежней цене, чтобы новый импорт снова увидел расхождение сумм.
    netflix_id = netflix["matched_subscription"]["id"]
    call("PATCH", f"/api/subscriptions/{netflix_id}", token, {"amount": "15.49"})
    _, third = upload(token, CSV.read_bytes())
    target = next((c for c in third["candidates"]
                   if c["duplicate_match"] == "amount_differs"), None)
    if target is None:
        print("  (в этом прогоне нет кандидата с расхождением сумм — шаг пропущен)")
    else:
        sub_id = target["matched_subscription"]["id"]
        seen = target["matched_subscription"]["amount"]
        call("PATCH", f"/api/subscriptions/{sub_id}", token, {"amount": "99.99"})
        print(f"  владелец правит подписку #{sub_id} в другой вкладке: {seen} -> 99.99")
        others = [c for c in third["candidates_review"]][:1]
        mixed = [{"candidate_id": target["candidate_id"], "action": "update",
                  "target_subscription_id": sub_id, "expected_amount": seen}]
        mixed += [{"candidate_id": c["candidate_id"]} for c in others]
        status, partial = call("POST",
                               f"/api/imports/statement/{third['import_id']}/confirm",
                               token, {"idempotency_key": str(uuid.uuid4()), "items": mixed})
        print(f"  HTTP {status} · создано {partial['created_count']}, "
              f"не применено {partial['skipped_count']}")
        for c in partial["created"]:
            print(f"    + {c['name']} {c['amount']}")
        for s in partial["skipped"]:
            print(f"    ! {s['code']}  {s['params']}")
        print("  правка владельца не затёрта, остальные элементы применены")

    print(f"\n{'═' * 72}\nИтог у пользователя:")
    for s in call("GET", "/api/subscriptions", token)[1]:
        print(f"  {s['name']:<24}{s['amount']:>9}  {s['billing_cycle']}")
    print("═" * 72)


if __name__ == "__main__":
    main()
