export type RecordStatus = 'active' | 'cancelled' | 'archived' | 'reversed'
export type TrackingMode = 'exact' | 'estimated' | 'value_only'

export interface Supplier {
  id: string
  name: string
  phone: string | null
  note: string | null
  status: RecordStatus
  created_at: string
}

export interface SupplierBalance {
  supplier_id: string
  purchase_total_kurus: number
  payment_total_kurus: number
  remaining_kurus: number
}

export interface Material {
  id: string
  name: string
  default_unit: string
  tracking_mode: TrackingMode
  note: string | null
  status: RecordStatus
}

export interface Project {
  id: string
  name: string
  customer_name: string
  contract_amount_kurus: number | null
  budget_kurus: number | null
  project_state: string
  status: RecordStatus
}

export interface Purchase {
  id: string
  supplier_id: string
  material_id: string
  project_id: string | null
  purchase_date: string
  due_date: string | null
  quantity: string | null
  unit: string | null
  unit_price_kurus: number | null
  total_kurus: number
  description: string | null
  status: RecordStatus
}

export interface Payment {
  id: string
  supplier_id: string
  purchase_id: string | null
  payment_date: string
  amount_kurus: number
  note: string | null
  status: RecordStatus
}

export interface SupplierReportRow {
  supplier_id: string
  supplier_name: string
  purchase_count: number
  purchase_total_kurus: number
  payment_total_kurus: number
  current_debt_kurus: number
}

export interface MaterialReportRow {
  material_id: string
  material_name: string
  unit: string | null
  purchase_count: number
  quantity: string | null
  total_kurus: number
}

export interface MonthReportRow {
  month: string
  purchase_count: number
  total_kurus: number
}

export interface PurchaseReport {
  date_from: string | null
  date_to: string | null
  purchase_count: number
  purchase_total_kurus: number
  payment_total_kurus: number
  by_supplier: SupplierReportRow[]
  by_material: MaterialReportRow[]
  by_month: MonthReportRow[]
}

export interface AgingBucket {
  key: string
  label: string
  amount_kurus: number
  count: number
}

export interface AgingItem {
  purchase_id: string
  supplier_id: string
  supplier_name: string
  material_name: string
  purchase_date: string
  due_date: string | null
  total_kurus: number
  remaining_kurus: number
  days_overdue: number | null
  bucket: string
}

export interface AgingSupplier {
  supplier_id: string
  supplier_name: string
  total_open_kurus: number
  overdue_kurus: number
  credit_kurus: number
  buckets: Record<string, number>
}

export interface DebtAgingReport {
  as_of: string
  total_open_kurus: number
  overdue_kurus: number
  credit_kurus: number
  buckets: AgingBucket[]
  suppliers: AgingSupplier[]
  items: AgingItem[]
}

export interface ApiErrorShape {
  error?: { code?: string; message?: string; details?: unknown }
}

export interface DesktopInfo {
  version: string
  platform: string
  packaged: boolean
  dataDirectory: string
}

export type BackupIntegrity = 'ok'

export interface BackupStatus {
  healthy: boolean
  in_progress: boolean
  last_error: string | null
  backup_count: number
  latest_backup: BackupRecord | null
  latest_automatic: BackupRecord | null
  automatic_retention: number
}

export interface BackupRecord {
  backup_id: string
  created_at: string
  size_bytes: number
  kind: 'automatic' | 'manual' | 'pre_restore'
  integrity: BackupIntegrity
  sha256: string
  app_version: string
}

export interface RestoreResult {
  restored_backup: BackupRecord
  pre_restore_backup: BackupRecord
  restart_required: true
}
