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
  stage: 'planning' | 'design' | 'approval' | 'production' | 'delivery' | 'installation' | 'completed'
  progress_percent: number
  accent_color: string
  address: string | null
  next_step: string | null
  note: string | null
  status: RecordStatus
}

export interface ProjectNote { id: string; project_id: string; content: string; pinned: boolean; created_at: string }
export interface ProjectTask { id: string; project_id: string; title: string; due_date: string | null; task_state: 'todo' | 'waiting' | 'done'; waiting_on: string | null; note: string | null; created_at: string }
export interface ProjectColor { id: string; project_id: string; label: string; color_code: string; material: string | null; note: string | null; created_at: string }
export interface ProjectMeasurement { id: string; project_id: string; space_name: string; label: string; value: string; unit: string; measured_on: string; note: string | null; created_at: string }
export interface ProjectVisit { id: string; project_id: string; visit_date: string; purpose: string; visit_state: 'planned' | 'completed' | 'cancelled'; note: string | null; created_at: string }
export interface ProjectHub { project: Project; notes: ProjectNote[]; tasks: ProjectTask[]; colors: ProjectColor[]; measurements: ProjectMeasurement[]; visits: ProjectVisit[] }

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

export interface Employee {
  id: string
  name: string
  phone: string | null
  role: string | null
  daily_rate_kurus: number | null
  wage_type?: 'monthly' | 'daily' | 'hourly'
  current_rate_kurus?: number | null
  employment_start_date?: string | null
  employment_end_date?: string | null
  employment_state?: 'active' | 'inactive' | 'left'
  iban?: string | null
  payment_note?: string | null
  note: string | null
  status: RecordStatus
}

export interface Site {
  id: string
  project_id: string | null
  name: string
  address: string | null
  note: string | null
  status: RecordStatus
}

export interface WorkLog {
  id: string
  employee_id: string
  project_id: string | null
  site_id: string | null
  work_date: string
  hours: string
  amount_kurus: number
  note: string | null
  status: RecordStatus
}

export interface EmployeePayment {
  id: string
  employee_id: string
  payment_date: string
  amount_kurus: number
  payment_type: 'advance' | 'wage'
  note: string | null
  status: RecordStatus
}

export interface MLStatus {
  ready: boolean
  purchase_count: number
  material_series_ready: number
  reorder_series_ready: number
  project_series_ready: number
  minimum_price_samples: number
  minimum_reorder_samples: number
  message: string
}

export interface PriceAnomaly {
  material_id: string
  material_name: string
  unit: string
  sample_count: number
  latest_date: string
  latest_unit_price_kurus: number
  expected_unit_price_kurus: number
  deviation_percent: number
  anomaly_score: number
  is_anomaly: boolean
  next_expected_unit_price_kurus: number
}

export interface ReorderForecast {
  material_id: string
  material_name: string
  sample_count: number
  median_interval_days: number
  next_expected_date: string
  days_until_expected: number
  confidence: string
}

export interface ProjectRisk {
  project_id: string
  project_name: string
  sample_count: number
  current_cost_kurus: number
  budget_kurus: number
  projected_30d_cost_kurus: number
  budget_usage_percent: number
  projected_usage_percent: number
  risk_level: string
}

export interface MLInsights {
  as_of: string
  status: MLStatus
  price_anomalies: PriceAnomaly[]
  reorder_forecasts: ReorderForecast[]
  project_risks: ProjectRisk[]
}
