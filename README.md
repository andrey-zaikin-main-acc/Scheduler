# Production Planner MVP

Локальный однопользовательский MVP приложения планирования производства с хранением данных в SQLite.

## Цель

Прототип проверяет ключевую расчётную логику:

- расчёт потребности по трудоёмкости на 1000 шт.;
- обратное планирование от срока отгрузки;
- учёт маршрутов и производственных участков;
- частичную передачу партии между операциями;
- пересчёт всего плана при изменениях;
- выявление конфликтов;
- свободные слоты;
- диаграмму Ганта по заказам и по участкам.

## Стек

- Python 3.12+
- Streamlit
- SQLite
- SQLAlchemy
- Plotly
- pytest

## Локальный запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app/main.py
```

## Тесты

```bash
pytest
```

## Документация

- `docs/planning_algorithm.md` — правила алгоритма планирования.
- `docs/data_model.md` — модель данных SQLite.
- `docs/acceptance_scenarios.md` — приёмочные сценарии.
- `docs/ui_spec.md` — спецификация экранов MVP.
