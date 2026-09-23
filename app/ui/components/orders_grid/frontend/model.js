(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.OrdersGridModel = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function clone(value) { return JSON.parse(JSON.stringify(value)); }

  function create(rows, gridId, sourceVersion, serverAckRevision) {
    const acknowledged = Number(serverAckRevision || 0);
    return { rows: clone(rows), gridId, sourceVersion, revision: acknowledged, ack: acknowledged, pending: [], scrollTop: 0,
      scrollLeft: 0, active: null, draftValue: null, lastFlushedToken: null };
  }

  function rowKey(row) { return Number.isInteger(row.ID) ? row.ID : row._draft_id; }

  function edit(state, key, field, after, actionType, singleSelection) {
    const row = state.rows.find(item => rowKey(item) === key);
    if (!row || row[field] === after) return state;
    const before = row[field] === undefined ? null : row[field];
    row[field] = after;
    if (singleSelection && field === "Выбран" && after) {
      for (const other of state.rows) {
        if (rowKey(other) !== key) other[field] = false;
      }
    }
    state.revision += 1;
    state.pending.push({ row_key: key, field, before, after,
      client_revision: state.revision, action_type: actionType || "cell" });
    return state;
  }

  function render(state, args) {
    if (args.grid_id !== state.gridId) {
      // A component iframe can be reused for a different Streamlit table.  Its
      // local state is meaningful only for the table that created it.
      return create(args.rows, args.grid_id, args.source_version, args.server_ack_revision);
    }
    if (args.source_version !== state.sourceVersion) {
      const replacement = create(args.rows, args.grid_id, args.source_version, args.server_ack_revision);
      replacement.revision = Math.max(state.revision, Number(args.server_ack_revision || 0));
      replacement.ack = Number(args.server_ack_revision || 0);
      // A server snapshot must not make an already acknowledged barrier new
      // again.  The iframe can receive the same token on several renders.
      replacement.lastFlushedToken = state.lastFlushedToken;
      return replacement;
    }
    state.ack = Math.max(state.ack, Number(args.server_ack_revision || 0));
    state.pending = state.pending.filter(event => event.client_revision > state.ack);
    return state;
  }

  function payload(state, flushToken) {
    return { grid_id: state.gridId, source_version: state.sourceVersion, client_revision: state.revision,
      events: clone(state.pending), snapshot: clone(state.rows),
      flush_ack: flushToken || null };
  }
  function flushActive(state, key, field, after, actionType, flushToken) {
    if (key !== null && key !== undefined && field) edit(state, key, field, after, actionType);
    state.draftValue = null;
    return payload(state, flushToken);
  }
  function claimFlush(state, flushToken) {
    if (!flushToken || state.lastFlushedToken === flushToken) return false;
    // Claim before posting the value: the post itself schedules a rerender.
    state.lastFlushedToken = flushToken;
    return true;
  }
  return { create, edit, render, payload, flushActive, claimFlush, rowKey };
});
