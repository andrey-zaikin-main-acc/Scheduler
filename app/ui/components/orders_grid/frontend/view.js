(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.OrdersGridView = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const BOOLEAN_FIELDS = new Set([
    "Выбран", "Связанные заказы", "Запланирован", "Конфликт планирования",
  ]);
  const DATE_FIELDS = new Set([
    "Заданная дата запуска", "Заданная дата отгрузки",
    "Расчётная дата запуска", "Расчётная дата отгрузки",
  ]);
  const NUMERIC_FIELDS = new Set(["Приоритет", "Тираж"]);

  function cellKind(field, readOnly, options) {
    if (BOOLEAN_FIELDS.has(field)) return readOnly ? "boolean-display" : "boolean-editor";
    if (readOnly) return DATE_FIELDS.has(field) ? "date-display" : "text-display";
    if (options) return "select-editor";
    if (DATE_FIELDS.has(field)) return "date-editor";
    if (NUMERIC_FIELDS.has(field)) return "number-editor";
    return "text-editor";
  }

  function formatDate(value) {
    if (!value) return "";
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value));
    return match ? `${match[3]}.${match[2]}.${match[1]}` : String(value);
  }

  function themeVars(theme) {
    theme = theme || {};
    return {
      "--text": theme.textColor || "#31333f",
      "--background": theme.backgroundColor || "#ffffff",
      "--secondary-background": theme.secondaryBackgroundColor || "#f0f2f6",
      "--primary": theme.primaryColor || "#ff4b4b",
      "--font": theme.font || "sans-serif",
    };
  }

  function frameHeight(viewport) {
    // The border and horizontal scrollbar are part of the viewport's border box.
    return Math.ceil(viewport.getBoundingClientRect().height) + 2;
  }

  function displaySignature(args) {
    args = args || {};
    const sorted = values => Array.from(values || []).sort();
    const options = {};
    for (const field of args.columns || []) {
      if (Object.prototype.hasOwnProperty.call(args.options || {}, field)) {
        options[field] = args.options[field];
      }
    }
    return JSON.stringify({
      columns: args.columns || [],
      readOnly: sorted(args.read_only),
      booleanFields: sorted(args.boolean_fields || BOOLEAN_FIELDS),
      numericFields: sorted(args.numeric_fields || NUMERIC_FIELDS),
      options,
      singleSelection: !!args.single_selection,
    });
  }

  return {BOOLEAN_FIELDS, DATE_FIELDS, NUMERIC_FIELDS, cellKind, formatDate, themeVars, frameHeight,
    displaySignature};
});
