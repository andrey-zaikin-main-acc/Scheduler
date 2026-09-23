const assert = require("node:assert/strict");
const M = require("../../app/ui/components/orders_grid/frontend/model.js");

let state = M.create([{ID: 1, A: "a", B: "b", C: "c"}], "orders", 1);
M.edit(state, 1, "A", "A"); M.edit(state, 1, "B", "B"); M.edit(state, 1, "C", "C");
assert.deepEqual(state.rows[0], {ID: 1, A: "A", B: "B", C: "C"});
assert.equal(state.pending.length, 3, "rapid edits remain pending without acknowledgement");

state.scrollTop = 900; state.scrollLeft = 120; state.active = {key: 1, field: "C"}; state.draftValue = "typing";
state = M.render(state, {grid_id: state.gridId, source_version: 1, server_ack_revision: 2, rows: [{ID: 1, A: "old"}]});
assert.equal(state.rows[0].C, "C", "stale same-source response cannot replace revision 3");
assert.equal(state.pending.length, 1, "old ack only removes acknowledged events");
assert.equal(state.scrollTop, 900); assert.equal(state.scrollLeft, 120);
assert.deepEqual(state.active, {key: 1, field: "C"}); assert.equal(state.draftValue, "typing");

state = M.render(state, {grid_id: state.gridId, source_version: 2, server_ack_revision: 3, rows: [{ID: 1, A: "server"}]});
assert.equal(state.rows[0].A, "server", "new source accepts authoritative snapshot");
assert.equal(state.scrollTop, 0); assert.equal(state.active, null);

let active = M.create([{ID: 9, Name: "before"}], "orders", 1);
active.active = {key: 9, field: "Name"}; active.draftValue = "visible active value";
const flushed = M.flushActive(active, 9, "Name", active.draftValue, "cell", "save-1");
assert.equal(flushed.source_version, 1, "payload identifies the source generation");
assert.equal(flushed.flush_ack, "save-1");
assert.equal(flushed.snapshot[0].Name, "visible active value", "flush commits the active input");
assert.equal(flushed.events.length, 1, "flush emits the business edit exactly once");

let barrier = M.create([{ID: 1, Name: "route"}], "orders", 1);
assert.equal(M.claimFlush(barrier, "save-1"), true, "first render claims the flush");
for (let render = 0; render < 100; render += 1) {
  barrier = M.render(barrier, {grid_id: barrier.gridId, source_version: render === 50 ? 2 : barrier.sourceVersion,
    server_ack_revision: 0, rows: barrier.rows});
  assert.equal(M.claimFlush(barrier, "save-1"), false, "same token is never posted twice");
}
assert.equal(M.claimFlush(barrier, "save-2"), true, "a new save barrier can flush");
assert.equal(M.claimFlush(barrier, "save-2"), false, "new token is also idempotent");

const routeEditor = M.create([], "orders", 1), operationEditor = M.create([], "orders", 1);
assert.equal(M.claimFlush(routeEditor, "atomic-1"), true);
assert.equal(M.claimFlush(operationEditor, "atomic-1"), true);
assert.equal(M.claimFlush(routeEditor, "atomic-1"), false);
assert.equal(M.claimFlush(operationEditor, "atomic-1"), false);

let probe = M.create([{ID: 7, Name: "Route A"}], "orders", 1);
probe.active = {key: 7, field: "Name"}; probe.draftValue = "Route B";
assert.equal(M.claimFlush(probe, "navigation-1"), true);
const probePayload = M.flushActive(
  probe, probe.active.key, probe.active.field, probe.draftValue, "cell", "navigation-1"
);
assert.equal(probePayload.snapshot[0].Name, "Route B");
assert.equal(probePayload.events.length, 1);
assert.equal(probePayload.flush_ack, "navigation-1");
assert.equal(M.claimFlush(probe, "navigation-1"), false, "one navigation token emits once");

console.log("orders grid model tests passed");

let reopened = M.create([{ID: 1, "Выбран": false}], "orders", 3, 8);
assert.equal(reopened.revision, 8);
assert.equal(reopened.ack, 8);
M.edit(reopened, 1, "Выбран", true, "selection");
assert.equal(reopened.pending[0].client_revision, 9,
  "the first event after reopening is newer than the retained server ack");

let single = M.create([
  {ID: 1, "Выбран": true, Name: "A"},
  {ID: 2, "Выбран": false, Name: "B"},
], "orders", 1, 0);
M.edit(single, 2, "Выбран", true, "selection", true);
assert.deepEqual(single.rows.map(row => row["Выбран"]), [false, true]);
assert.equal(single.pending.length, 1, "implicit deselection is not a business event");
assert.equal(single.pending[0].action_type, "selection");
M.edit(single, 2, "Выбран", false, "selection", true);
assert.deepEqual(single.rows.map(row => row["Выбран"]), [false, false]);

let multiple = M.create([{ID: 1, "Выбран": false}, {ID: 2, "Выбран": false}], "orders", 1, 0);
M.edit(multiple, 1, "Выбран", true, "selection", false);
M.edit(multiple, 2, "Выбран", true, "selection", false);
assert.deepEqual(multiple.rows.map(row => row["Выбран"]), [true, true],
  "orders and work centres retain multiple selection");

let pendingSelection = M.create([
  {ID: 1, "Выбран": true, Name: "A"},
  {ID: 2, "Выбран": false, Name: "B"},
], "orders", 1, 0);
M.edit(pendingSelection, 1, "Name", "unsent", "cell");
M.edit(pendingSelection, 2, "Выбран", true, "selection", true);
assert.equal(pendingSelection.rows[0].Name, "unsent");
assert.equal(pendingSelection.pending.length, 2,
  "single-selection reconciliation preserves unrelated pending edits");

// One browser model can be reused by Streamlit for unrelated tables whose
// row IDs and source generations happen to coincide.
let switched = M.create([{ID: 1, "Выбран": true, Name: "Route"}], "routes_page_route_editor", 5, 3);
M.edit(switched, 1, "Выбран", false, "selection", true);
switched.active = {key: 1, field: "Name"}; switched.draftValue = "route typing";
switched.scrollTop = 200; switched.scrollLeft = 40;
assert.equal(M.claimFlush(switched, "route-flush"), true);
switched = M.render(switched, {grid_id: "work_centers_page_editor", source_version: 5,
  server_ack_revision: 11, rows: [{ID: 1, "Выбран": true, Name: "Work centre"}]});
assert.deepEqual(switched.rows, [{ID: 1, "Выбран": true, Name: "Work centre"}]);
assert.equal(switched.revision, 11); assert.equal(switched.ack, 11);
assert.deepEqual(switched.pending, []); assert.equal(switched.active, null);
assert.equal(switched.scrollTop, 0); assert.equal(switched.scrollLeft, 0);
assert.equal(switched.lastFlushedToken, null);
assert.equal(M.payload(switched, null).grid_id, "work_centers_page_editor");

M.edit(switched, 1, "Выбран", false, "selection", false);
switched = M.render(switched, {grid_id: "routes_page_route_editor", source_version: 5,
  server_ack_revision: 4, rows: [{ID: 1, "Выбран": true, Name: "Route again"}]});
assert.deepEqual(switched.rows, [{ID: 1, "Выбран": true, Name: "Route again"}]);
assert.equal(switched.revision, 4, "returning table uses its own acknowledged counter");
M.edit(switched, 1, "Выбран", false, "selection", true);
assert.equal(switched.pending[0].client_revision, 5, "first click after returning is accepted");

switched = M.render(switched, {grid_id: "orders_page_editor", source_version: 5,
  server_ack_revision: 2, rows: [{ID: 1, "Выбран": false, Name: "Order"}]});
assert.deepEqual(switched.rows, [{ID: 1, "Выбран": false, Name: "Order"}]);
assert.deepEqual(switched.pending, []);
