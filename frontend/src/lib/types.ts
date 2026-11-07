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
  customer_id?: string | null
  contract_amount_kurus: number | null
  contract_currency: 'TRY' | 'USD' | 'EUR' | 'GBP'
  contract_foreign_amount_minor: number | null
  contract_fx_rate: number | string | null
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

export interface ProjectContract { project_id: string; file_name: string; mime_type: string; size_bytes: number }

export interface ProjectNote { id: string; project_id: string; content: string; pinned: boolean; created_at: string }
export interface ProjectTask { id: string; project_id: string; title: string; due_date: string | null; task_state: 'todo' | 'waiting' | 'done'; waiting_on: string | null; note: string | null; created_at: string }
export interface ProjectColor { id: string; project_id: string; label: string; color_code: string; material: string | null; note: string | null; created_at: string }
export interface ProjectVisit { id: string; project_id: string; visit_date: string; purpose: string; visit_state: 'planned' | 'completed' | 'cancelled'; note: string | null; created_at: string }
export interface ProjectHub { project: Project; notes: ProjectNote[]; tasks: ProjectTask[]; colors: ProjectColor[]; visits: ProjectVisit[] }

export interface ProductCostFactor {
  id: string
  factor_key: string
  label: string
  material_id: string | null
  share_percent: number
  reference_unit_price_kurus: number
  reference_date: string
  source: 'manual' | 'purchase'
}

export interface PricingComparableFactor {
  factor_key: string
  label: string
  share_percent: number
  reference_unit_price_kurus: number
  current_unit_price_kurus: number
  change_percent: number
  current_source: string
  current_date: string
}

export interface PricingSuggestion {
  id: string
  suggested_low_kurus: number
  suggested_mid_kurus: number
  suggested_high_kurus: number
  confidence: 'low' | 'medium' | 'high'
  comparable_count: number
  model_version: string
  created_at: string
  explanation: {
    as_of: string
    method: string
    spread_percent: number
    warnings: string[]
    comparables: Array<{
      product_id: string
      project_id: string
      quote_date: string
      base_price_kurus: number
      normalized_price_kurus: number
      used_actual_cost: boolean
      factors: PricingComparableFactor[]
    }>
  }
}

export interface ProjectProduct {
  id: string
  project_id: string
  product_type: string
  description: string | null
  quantity: number
  unit: string
  finish: string | null
  hardware_level: string | null
  complexity_percent: number
  quote_date: string
  quoted_total_kurus: number | null
  accepted_total_kurus: number | null
  actual_cost_kurus: number | null
  target_margin_percent: number
  pricing_state: 'draft' | 'offered' | 'accepted' | 'rejected' | 'completed'
  note: string | null
  factors: ProductCostFactor[]
  latest_suggestion: PricingSuggestion | null
  created_at: string
  updated_at: string
}

export interface PricingLearningStatus {
  model_name: 'product_pricing'
  model_version: string
  product_count: number
  priced_product_count: number
  actual_cost_count: number
  factor_coverage_count: number
  ready: boolean
  message: string
  product_types: Array<{ product_type: string; priced_count: number }>
  latest_manual_indices: Array<{ id: string; factor_key: string; label: string; material_id: string | null; recorded_on: string; unit_price_kurus: number; source: string }>
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
  lifecycle_state?: 'planned' | 'ordered' | 'partially_received' | 'received' | 'cancelled'
  received_kurus?: number
}

export interface Payment {
  id: string
  supplier_id: string
  purchase_id: string | null
  payment_date: string
  amount_kurus: number
  payment_method: 'cash' | 'bank_transfer' | 'other' | null
  note: string | null
  status: RecordStatus
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

export interface UpdateState {
  status: 'idle' | 'unavailable' | 'checking' | 'available' | 'current' | 'downloading' | 'downloaded' | 'error'
  version: string | null
  message: string | null
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
  email?: string | null
  address?: string | null
  skill?: string | null
  emergency_contact_name?: string | null
  emergency_contact_phone?: string | null
  emergency_contact_relation?: string | null
  payment_method?: string | null
  salary_day?: number | null
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

export type PayrollState = 'draft' | 'calculated' | 'finalized' | 'closed'

export interface PayrollPeriod {
  id: string
  period_start: string
  period_end: string
  title: string
  state: PayrollState
  overtime_multiplier_percent: number | null
  calculated_at: string | null
  finalized_at: string | null
  closed_at: string | null
  status: RecordStatus
  created_at: string
  updated_at: string
}

export interface PayrollPeriodDetail extends PayrollPeriod {
  entry_count: number
  totals: Record<string, number> & { gross_earning_kurus: number; net_due_kurus: number; remaining_kurus: number }
}

export interface PayrollEntry {
  id: string
  payroll_period_id: string
  employee_id: string
  employee_name: string | null
  wage_type: 'monthly' | 'daily' | 'hourly'
  base_rate_kurus: number
  normal_hours: string
  overtime_hours: string
  worked_days: string
  base_earning_kurus: number
  overtime_earning_kurus: number
  bonus_kurus: number
  additional_earning_kurus: number
  deduction_kurus: number
  advance_deduction_kurus: number
  gross_earning_kurus: number
  net_due_kurus: number
  paid_kurus: number
  remaining_kurus: number
  calculation_detail: Record<string, unknown> | null
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
  dismissed?: boolean
  user_feedback?: string | null
}

export interface ReorderForecast {
  material_id: string
  material_name: string
  sample_count: number
  median_interval_days: number
  next_expected_date: string
  days_until_expected: number
  confidence: string
  confidence_score?: number
  stale?: boolean
  days_since_last?: number
  dismissed?: boolean
  user_feedback?: string | null
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
  confidence_score?: number
  dismissed?: boolean
  user_feedback?: string | null
}

export interface MLInsights {
  as_of: string
  status: MLStatus
  price_anomalies: PriceAnomaly[]
  reorder_forecasts: ReorderForecast[]
  project_risks: ProjectRisk[]
}

export interface Customer {
  id: string; name: string; phone: string | null; address: string | null; contact_person: string | null; note: string | null; status: RecordStatus
}
export interface CostSource { source_type: string; source_id: string; purchase_id?: string; date: string; amount_kurus: number; label: string; lifecycle_state?: string }
export interface CalendarSourceRoute { entity: string; entity_id: string; project_id?: string; employee_id?: string; customer_id?: string; supplier_id?: string }
export interface CalendarEvent { event_id: string; source_type: string; source_id: string; occurrence_date: string; event_type: string; title: string; description: string | null; start_date: string; end_date: string; all_day: boolean; state: 'overdue' | 'today' | 'upcoming' | 'completed' | 'cancelled'; amount_kurus: number | null; project_id: string | null; employee_id: string | null; customer_id: string | null; supplier_id: string | null; source_route: CalendarSourceRoute; notification_defaults: { enabled: boolean; offsets_days: number[]; is_financial: boolean } }
export interface TodayGroup { count: number; amount_kurus: number; receivable_kurus: number; payable_kurus: number; events: CalendarEvent[] }
