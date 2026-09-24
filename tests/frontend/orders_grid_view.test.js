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

const baseArgs = {columns: ["Выбран", "Имя"], read_only: ["Имя"],
  boolean_fields: ["Выбран"], numeric_fields: [], options: {}, single_selection: true};
assert.equal(V.displaySignature(baseArgs), V.displaySignature({...baseArgs,
  grid_id: "another-grid", source_version: 999, rows: [{ID: 2}], flush_token: "save"}),
"data identity, rows, and flush barriers are handled independently from display configuration");
assert.equal(V.displaySignature(baseArgs), V.displaySignature({...baseArgs,
  read_only: ["Имя"], boolean_fields: ["Выбран"]}));
assert.equal(V.displaySignature({columns: ["Выбран"]}),
  V.displaySignature({columns: ["Выбран"],
    boolean_fields: Array.from(V.BOOLEAN_FIELDS), numeric_fields: Array.from(V.NUMERIC_FIELDS)}),
  "omitted field type lists use the renderer defaults");
for (const changed of [
  {...baseArgs, columns: ["Имя", "Выбран"]},
  {...baseArgs, read_only: []},
  {...baseArgs, boolean_fields: []},
  {...baseArgs, numeric_fields: ["Имя"]},
  {...baseArgs, options: {Имя: ["A", "B"]}},
  {...baseArgs, single_selection: false},
]) assert.notEqual(V.displaySignature(baseArgs), V.displaySignature(changed));

const html = fs.readFileSync(path.join(__dirname,
  "../../app/ui/components/orders_grid/frontend/index.html"), "utf8");
assert.match(html, /\.viewport\{max-height:420px;overflow:auto/);
assert.doesNotMatch(html, /\.viewport\{height:420px/);
assert.match(html, /background:var\(--background\)/);
assert.match(html, /event\.data\.theme/);
assert.doesNotMatch(html, /if\(field==="Выбран"\)/);
assert.match(html, /readOnly\?makeRenderer\(row,field\):makeEditor/);
assert.match(html, /state=state\?M\.render\(state,args\):M\.create/);
assert.match(html, /nextSignature!==displaySignature/);
assert.match(html, /viewport!==currentViewport\|\|!viewport\.isConnected\|\|!host\.contains\(viewport\)/);
assert.match(html, /cancelAnimationFrame\(heightFrame\)/);
assert.match(html, /new ResizeObserver\(\(\)=>scheduleFrameHeight\(viewport\)\)/);
assert.doesNotMatch(html, /single_selection\)draw\(\)/);

console.log("orders grid renderer/layout tests passed");
