# Модель данных SQLite для MVP

## Основные решения

- MVP однопользовательский, авторизация не нужна.
- Клиент и продукция на первом этапе хранятся как текстовые поля заказа.
- Плановые операции хранят агрегированные даты начала/окончания и отдельные дневные размещения, потому что операция может выполняться с разрывами.
- Передаточная партия хранится на переходе к следующей операции маршрута через поле `min_transfer_quantity_to_next`.

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
- `available_hours_per_day`;
- `is_active`;
- `created_at`;
- `updated_at`.

`available_hours_per_day` должен быть больше 0.

### routes

Технологические маршруты.

Поля:

- `id`;
- `name`;
- `description`;
- `is_active`;
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
- `min_transfer_quantity_to_next`;
- `created_at`;
- `updated_at`.

`labor_hours_per_1000` должен быть больше 0.

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
