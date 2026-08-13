const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const V = require("../../app/ui/components/orders_grid/frontend/view.js");

assert.equal(V.cellKind("Связанные заказы", false), "boolean-editor");
assert.equal(V.cellKind("Запланирован", true), "boolean-display");
assert.equal(V.cellKind("Расчётная дата запуска", true), "date-display");
assert.equal(V.cellKind("Тираж", false), "number-editor");
assert.equal(V.formatDate("2026-08-13"), "13.08.2026");

const dark = V.themeVars({primaryColor: "#00aaff", backgroundColor: "#101010",
  secondaryBackgroundColor: "#202020", textColor: "#fafafa", font: "serif"});
assert.equal(dark["--background"], "#101010");
assert.equal(dark["--secondary-background"], "#202020");
assert.equal(dark["--text"], "#fafafa");
assert.equal(dark["--primary"], "#00aaff");
assert.equal(V.frameHeight({getBoundingClientRect: () => ({height: 157.2})}), 160);
assert.equal(V.frameHeight({getBoundingClientRect: () => ({height: 420})}), 422);

const html = fs.readFileSync(path.join(__dirname,
  "../../app/ui/components/orders_grid/frontend/index.html"), "utf8");
assert.match(html, /\.viewport\{max-height:420px;overflow:auto/);
assert.doesNotMatch(html, /\.viewport\{height:420px/);
assert.match(html, /background:var\(--background\)/);
assert.match(html, /event\.data\.theme/);
assert.doesNotMatch(html, /if\(field==="Выбран"\)/);
assert.match(html, /readOnly\?makeRenderer\(row,field\):makeEditor/);

console.log("orders grid renderer/layout tests passed");
