(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.OrdersGridModel = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function clone(value) { return JSON.parse(JSON.stringify(value)); }

  function create(rows, sourceVersion) {
    return { rows: clone(rows), sourceVersion, revision: 0, ack: 0, pending: [], scrollTop: 0,
      scrollLeft: 0, active: null, draftValue: null };
  }

  function rowKey(row) { return Number.isInteger(row.ID) ? row.ID : row._draft_id; }

  function edit(state, key, field, after, actionType) {
    const row = state.rows.find(item => rowKey(item) === key);
    if (!row || row[field] === after) return state;
    const before = row[field] === undefined ? null : row[field];
    row[field] = after;
    state.revision += 1;
    state.pending.push({ row_key: key, field, before, after,
      client_revision: state.revision, action_type: actionType || "cell" });
    return state;
  }

  function render(state, args) {
    if (args.source_version !== state.sourceVersion) {
      const replacement = create(args.rows, args.source_version);
      replacement.revision = Math.max(state.revision, Number(args.server_ack_revision || 0));
      replacement.ack = Number(args.server_ack_revision || 0);
      return replacement;
    }
    state.ack = Math.max(state.ack, Number(args.server_ack_revision || 0));
    state.pending = state.pending.filter(event => event.client_revision > state.ack);
    return state;
  }

  function payload(state, flushToken) {
    return { client_revision: state.revision, events: clone(state.pending), snapshot: clone(state.rows),
      flush_ack: flushToken || null };
  }
  function flushActive(state, key, field, after, actionType, flushToken) {
    if (key !== null && key !== undefined && field) edit(state, key, field, after, actionType);
    state.draftValue = null;
    return payload(state, flushToken);
  }
  return { create, edit, render, payload, flushActive, rowKey };
});
