# Нагрузочные проверки (RAG-версия)

Эта версия составлена строго по локальным источникам. Все числовые параметры, которых нет в источниках, помечены как «[допущение — TBD]» до заполнения соответствующих артефактов (например, `practices/practice_01/problem.md`, `practices/practice_01/adr.md`).

| Сценарий | Нагрузка и длительность | Допустимый предел | Что измеряем | Evidence |
|---|---|---|---|---|
| База: POST /api/reviews | [допущение — TBD] | [допущение — TBD] | Латентность, 4xx/5xx; соответствие ограничениям наблюдаемости | Логи без содержимого diff/ответа: только request_id/длительность/статус (OBS-1; Source: practices/practice_01/CASE.md, «Правила репозитория» → OBS-1) |
| Большие diff (API-1) | [допущение — TBD] | HTTP 413 для diff > 20 000 (API-1; Source: practices/practice_01/CASE.md → API-1) | Доля 413; отсутствие 5xx | Эндпоинт POST /api/reviews (Source: practices/practice_01/TRAINING_PR.diff, app/api.py:35-37); правило API-1 |
| Деградация внешнего LLM (REL-1) | [допущение — TBD] | Таймаут внешнего LLM 10 секунд; ошибка → контролируемый ответ (REL-1; Source: practices/practice_01/CASE.md → REL-1) | Отсутствие 5xx; наличие контролируемого ответа при таймауте | Вызов LLM из ReviewService (Source: practices/practice_01/TRAINING_PR.diff, app/review_service.py:19-22); правило REL-1 |

Подтверждающие ограничения и границы:

- SEC-1: перед отправкой во внешний LLM из diff удаляются токены, пароли и приватные ключи. Источник: practices/practice_01/CASE.md, «Правила репозитория» → SEC-1.
- OBS-1: в лог пишутся только `request_id`, длительность и статус. Содержимое diff и ответа модели не логируется. Источник: practices/practice_01/CASE.md, «Правила репозитория» → OBS-1.
- Эндпоинты тестирования: POST `/api/reviews`; sanity-check GET `/health`. Источник: practices/practice_01/TRAINING_PR.diff (app/api.py:35-37, 40-42).

Если нагрузочное тестирование пока не требуется, обоснуйте это и назовите условие, после которого оно понадобится. Источник: practices/practice_01/tests_load.md (верх файла).

