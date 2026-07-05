/**
 * Warehouse abstraction — the storage seam (ADR-0022 / ADR-0028).
 *
 * The OSS implementation is `DeltaWarehouse` (`delta-warehouse.ts`) — delta-rs write /
 * DataFusion read. (The Databricks-backed implementation lives in a separate, private
 * sibling product repo and plugs into this same interface; not part of the OSS distribution.)
 *
 * The interface deliberately surfaces SQL primitives rather than ORM-style methods — the
 * storage shape per ADR-0010 already commits to specific DDL, and abstracting away from SQL
 * would add ceremony with no win.
 */

export interface WarehouseRow {
  [column: string]: unknown;
}

export interface Warehouse {
  /** Run a SELECT-style statement; return all rows. */
  query<T extends WarehouseRow = WarehouseRow>(sql: string, params?: unknown[]): Promise<T[]>;
  /** Run an INSERT/UPDATE/DELETE/MERGE-style statement; return affected-row count. */
  execute(sql: string, params?: unknown[]): Promise<number>;
  /** Release any connection resources. */
  close(): Promise<void>;
}
