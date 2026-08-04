# Модель данных SQLite для MVP

## Основные решения

- MVP однопользовательский, авторизация не нужна.
- Клиент и продукция на первом этапе хранятся как текстовые поля заказа.
- Плановые операции хранят агрегированные даты начала/окончания и отдельные дневные размещения со временем начала/окончания внутри рабочего дня.
- Поле `min_transfer_quantity_to_next` хранится в операции маршрута. В интерфейсе оно подписано как минимальная передаточная партия, а текущий планировщик использует его как минимальную стартовую партию текущей операции.

## Таблицы

### orders

Заказы.

Поля:

- `id` — внутренний ID;
- `order_number` — номер заказа;
- `client_name` — клиент текстом;
- `product_name` — продукция текстом;
- `quantity` — тираж;
- `shipment_date` — срок отгрузки;
- `route_id` — маршрут;
- `status` — статус;
- `calculated_start_date` — рассчитанная дата запуска;
- `created_at`;
- `updated_at`.

### work_centers

Производственные участки.

Поля:

- `id`;
- `name`;
- `available_hours_per_day` — месячная доступная мощность участка в часах; историческое имя поля сохранено в коде;
- `workday_start_time` — время начала рабочего дня участка, по умолчанию 09:00;
- `is_active`;
- `prevent_order_interruption` — запрет прерывания заказа другим заказом при планировании, `NOT NULL`, по умолчанию `False`;
- `created_at`;
- `updated_at`.

`available_hours_per_day` должен быть больше 0. `prevent_order_interruption` для существующих баз добавляется безопасной миграцией `ALTER TABLE` со значением по умолчанию `False`. Несмотря на историческое имя поля, код использует его как месячную мощность и делит её на количество календарных дней в месяце при расчёте дневной мощности. `workday_start_time` сохраняется и редактируется в справочнике, но в расчётной логике используется только как справочное поле: технические интервалы дневных размещений нормализуются внутри календарной даты.

### routes

Технологические маршруты.

Поля:

- `id`;
- `name`;
- `description`;
- `is_active`;
- `prevent_order_interruption` — запрет прерывания заказа другим заказом при планировании, `NOT NULL`, по умолчанию `False`;
- `created_at`;
- `updated_at`.

### route_operations

Операции маршрута.

Поля:

- `id`;
- `route_id`;
- `sequence_number`;
- `work_center_id`;
- `labor_hours_per_1000`;
- `min_transfer_quantity_to_next` — минимальная стартовая партия текущей операции, если задана; в интерфейсе значение `0` сохраняется как отсутствие ограничения;
- `created_at`;
- `updated_at`.

`labor_hours_per_1000` должен быть больше 0. `sequence_number` должен быть больше 0 и уникален внутри маршрута. `min_transfer_quantity_to_next`, если задано, должно быть больше 0; UI принимает 0 и перед сохранением преобразует его в `NULL`.

### planned_operations

Агрегированные плановые операции.

Поля:

- `id`;
- `order_id`;
- `route_operation_id`;
- `work_center_id`;
- `sequence_number`;
- `planned_start_date`;
- `planned_end_date`;
- `required_hours`;
- `planned_hours`;
- `status`;
- `created_at`;
- `updated_at`.

### planned_operation_days

Дневные размещения операции.

Поля:

- `id`;
- `planned_operation_id`;
- `work_center_id`;
- `date`;
- `hours`;
- `start_datetime` — фактическое время начала размещения внутри рабочего дня;
- `end_datetime` — фактическое время окончания размещения внутри рабочего дня;
- `quantity_part`.

### planning_conflicts

Конфликты планирования.

Поля:

- `id`;
- `order_id`;
- `shipment_date`;
- `work_center_id`;
- `required_hours`;
- `available_hours`;
- `deficit_hours`;
- `blocking_order_ids`;
- `reason`;
- `created_at`.

### recalculation_runs

Запуски пересчёта.

Поля:

- `id`;
- `started_at`;
- `finished_at`;
- `status`;
- `summary`.

### plan_changes

Изменения после пересчёта.

Поля:

- `id`;
- `recalculation_run_id`;
- `order_id`;
- `planned_operation_id`;
- `change_type`;
- `old_start_date`;
- `old_end_date`;
- `new_start_date`;
- `new_end_date`;
- `description`.

### settings

Настройки прототипа.

Поля:

- `key`;
- `value`.

Примеры настроек:

- `default_free_slot_days = 30`;
- `max_backward_search_months = 12`.

## Model migration (session-draft release)

`orders.calculated_shipment_date` separates planner output from the requested `shipment_date`; start-driven legacy results are recovered from the last saved operation. A blank persisted status represents system-owned planning outcome while `Новый`/`Отменён` remain manual values. `route_operations.is_active` is a non-null boolean with `DEFAULT 1`. `plan_changes.operation_sequence_number` is a stable history key independent of recreated planned-operation IDs. Migrations use column inspection and are idempotent; legacy columns such as `workday_start_time` remain for compatibility but are not editable.

## Модель экранного сохранения (актуальная)

Все правки сначала являются экранным черновиком. Локальное сохранение справочника не пересчитывает план; глобальная команда проверяет все разделы и pending delete до единой транзакции. Ошибка заполнения сохраняет черновик и историю, конфликт планирования является успешным системным результатом.

Полный проход использует неизменяемый snapshot трёх очередей: ранее запланированные, новые, ранее конфликтные. Приоритет — глобально уникальное положительное целое; связанные строки одной группы занимают непрерывный блок. Оба заданных поля даты разрешены в черновике, а неиспользуемое поле очищается только после успешного расчёта. Системный результат читается из planned operations либо planning conflicts.

Таблицы блокируют только фиксированные системные столбцы; в заказах это ID, группа, две расчётные даты и два флага результата. «Связанные заказы» редактируется. История undo/redo, отдельные черновики операций по route ID и навигационное подтверждение живут в сессии. Свободные слоты обязаны использовать неперсистентную симуляцию основного PlanningEngine. Статические ресурсы табличного адаптера должны включаться в Windows EXE и не зависеть от CDN.

## Идентификаторы экранного черновика

В сессии сохранённые строки имеют положительный DB ID, а ещё не сохранённые строки — устойчивый отрицательный `_draft_id`. Временный ключ никогда не записывается в предметные таблицы.
