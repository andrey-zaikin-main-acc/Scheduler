const assert = require("node:assert/strict");
const M = require("../../app/ui/components/orders_grid/frontend/model.js");

let state = M.create([{ID: 1, A: "a", B: "b", C: "c"}], 1);
M.edit(state, 1, "A", "A"); M.edit(state, 1, "B", "B"); M.edit(state, 1, "C", "C");
assert.deepEqual(state.rows[0], {ID: 1, A: "A", B: "B", C: "C"});
assert.equal(state.pending.length, 3, "rapid edits remain pending without acknowledgement");

state.scrollTop = 900; state.scrollLeft = 120; state.active = {key: 1, field: "C"}; state.draftValue = "typing";
state = M.render(state, {source_version: 1, server_ack_revision: 2, rows: [{ID: 1, A: "old"}]});
assert.equal(state.rows[0].C, "C", "stale same-source response cannot replace revision 3");
assert.equal(state.pending.length, 1, "old ack only removes acknowledged events");
assert.equal(state.scrollTop, 900); assert.equal(state.scrollLeft, 120);
assert.deepEqual(state.active, {key: 1, field: "C"}); assert.equal(state.draftValue, "typing");

state = M.render(state, {source_version: 2, server_ack_revision: 3, rows: [{ID: 1, A: "server"}]});
assert.equal(state.rows[0].A, "server", "new source accepts authoritative snapshot");
assert.equal(state.scrollTop, 0); assert.equal(state.active, null);

let active = M.create([{ID: 9, Name: "before"}], 1);
active.active = {key: 9, field: "Name"}; active.draftValue = "visible active value";
const flushed = M.flushActive(active, 9, "Name", active.draftValue, "cell", "save-1");
assert.equal(flushed.flush_ack, "save-1");
assert.equal(flushed.snapshot[0].Name, "visible active value", "flush commits the active input");
assert.equal(flushed.events.length, 1, "flush emits the business edit exactly once");

console.log("orders grid model tests passed");
