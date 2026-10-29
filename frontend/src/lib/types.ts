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

export interface ProjectCostSummary {
  project_id: string
  purchase_kurus: number
  labor_accrual_kurus: number
  labor_kurus: number
  shipping_kurus: number
  installation_kurus: number
  site_kurus: number
  other_kurus: number
  total_cost_kurus: number
  budget_kurus: number | null
  budget_variance_kurus: number | null
  contract_amount_kurus: number | null
  estimated_profit_kurus: number | null
  profit_margin_percent: number | null
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

export interface Customer {
  id: string; name: string; phone: string | null; address: string | null; contact_person: string | null; note: string | null; status: RecordStatus
}
export interface CustomerDetail extends Customer {
  receivable_kurus: number; credit_kurus: number; net_balance_kurus: number; balance_kurus: number; unallocated_collection_kurus: number; project_count: number
}
export interface ReceivableSchedule {
  id: string; customer_id: string; project_id: string | null; title: string; amount_kurus: number; due_date: string | null; note: string | null; status: RecordStatus; paid_kurus: number; remaining_kurus: number; payment_state: 'open' | 'partial' | 'paid' | 'overdue' | 'cancelled'
}
export interface CustomerFinancialMovement {
  id: string; customer_id: string; project_id: string | null; receivable_schedule_id: string | null; change_order_id: string | null; movement_date: string; movement_type: string; direction: string; amount_kurus: number; note: string | null; idempotency_key: string; reversed_movement_id: string | null; source: string; status: RecordStatus; is_voided: boolean; allocated_kurus?: number | null; unallocated_kurus?: number | null
}
export interface CustomerPaymentAllocation {
  id: string; customer_id: string; collection_id: string; receivable_schedule_id: string; amount_kurus: number; allocation_date: string; note: string | null; idempotency_key: string; status: RecordStatus; cancelled_at: string | null; cancel_reason: string | null
}
export type BudgetCategory = 'material' | 'labor' | 'shipping' | 'installation' | 'subcontractor' | 'site' | 'waste_rework' | 'other'
export interface ProjectBudgetLine { id: string; project_id: string; category: BudgetCategory; title: string; amount_kurus: number; original_amount_kurus: number; revision_no: number; note: string | null; status: RecordStatus }
export interface ProjectBudgetRevision { id: string; budget_line_id: string; revision_no: number; previous_amount_kurus: number | null; amount_kurus: number; reason: string | null; created_at: string }
export interface ProjectChangeOrder { id: string; project_id: string; title: string; description: string | null; amount_kurus: number; change_state: 'draft' | 'approved' | 'rejected' | 'cancelled'; decided_at: string | null; decision_note: string | null; status: RecordStatus }
export interface CostForecastRevision { id: string; category: BudgetCategory; revision_no: number; remaining_estimate_kurus: number | null; forecast_source: 'manual' | 'auto'; as_of_date: string; reason: string; is_current: boolean; created_at: string }
export interface ProfitabilityCategory { category: BudgetCategory; budget_kurus: number; original_budget_kurus: number; actual_kurus: number; commitment_kurus: number; remaining_estimate_kurus: number; forecast_kurus: number; variance_kurus: number; forecast_source?: 'manual' | 'auto'; budget_line_ids: string[] }
export interface ProjectProfitability { project_id: string; contract_amount_kurus: number | null; approved_change_orders_kurus: number; pending_change_orders_kurus: number; revised_contract_kurus: number | null; original_budget_kurus: number | null; revised_budget_kurus: number | null; actual_cost_kurus: number; commitment_kurus: number; remaining_estimate_kurus: number; forecast_cost_at_completion_kurus: number; budget_variance_kurus: number | null; current_profit_kurus: number | null; estimated_profit_kurus: number | null; estimated_margin_percent: number | null; categories: ProfitabilityCategory[]; collections: { collected_kurus: number; refunded_kurus: number; net_collected_kurus: number; billed_kurus: number; open_receivable_kurus: number; project_advance_kurus: number; unlinked_customer_advance_kurus: number; basis: string }; warnings: Array<{ code: string; message: string }> }
export interface CostSource { source_type: string; source_id: string; purchase_id?: string; date: string; amount_kurus: number; label: string; lifecycle_state?: string }
export interface ProjectCostDrilldown { project_id: string; actual_total_kurus: number; commitment_total_kurus: number; categories: Array<{ category: BudgetCategory; actual_kurus: number; commitment_kurus: number; actual_source_count: number; commitment_source_count: number; truncated: boolean; actual_sources: CostSource[]; commitment_sources: CostSource[]; remaining_estimate_kurus: number; forecast_source: 'manual' | 'auto'; forecast_kurus: number }> }
export interface PurchaseReceipt { id: string; purchase_id: string; receipt_date: string; quantity: string | null; amount_kurus: number; note: string | null; idempotency_key: string; status: RecordStatus; cancelled_at: string | null; cancel_reason: string | null; warnings: Array<{ code: string; message: string }> }
export interface AttendanceCheck { date_from: string; date_to: string; enforcement_start_date: string | null; employees_checked: number; totals: { missing_required_day: number; enforced_missing_day: number; inconsistency: number }; employees: Array<{ employee_id: string; employee_name: string; required_day_count: number; logged_day_count: number; issues: Array<{ code: string; date: string; enforced: boolean; work_log_id?: string }> }> }
export interface LeaveRequest { id: string; employee_id: string; leave_type_id: string; leave_type_code: string | null; start_date: string; end_date: string; day_part: 'full' | 'half_am' | 'half_pm' | 'hourly'; hours_per_day: string | null; total_hours: string | null; request_state: 'pending' | 'approved' | 'rejected' | 'cancelled'; reason: string | null; decision_note: string | null; decided_at: string | null; status: RecordStatus; work_log_ids: string[] }
export interface CalendarSourceRoute { entity: string; entity_id: string; project_id?: string; employee_id?: string; customer_id?: string; supplier_id?: string }
export interface CalendarEvent { event_id: string; source_type: string; source_id: string; occurrence_date: string; event_type: string; title: string; description: string | null; start_date: string; end_date: string; all_day: boolean; state: 'overdue' | 'today' | 'upcoming' | 'completed' | 'cancelled'; amount_kurus: number | null; project_id: string | null; employee_id: string | null; customer_id: string | null; supplier_id: string | null; source_route: CalendarSourceRoute; notification_defaults: { enabled: boolean; offsets_days: number[]; is_financial: boolean } }
export interface TodayGroup { count: number; amount_kurus: number; receivable_kurus: number; payable_kurus: number; events: CalendarEvent[] }
export interface TodayView { as_of: string; overdue: TodayGroup; today: TodayGroup; next_7_days: TodayGroup; totals: { count: number; amount_kurus: number } }
export interface DueNotification { delivery_key: string; channel: 'windows'; offset_days: number; fire_date: string; title: string; body: string | null; event: CalendarEvent }
export interface ReportTable { name: string; title: string; filters: Record<string, unknown>; columns: Array<{ key: string; label: string; kind: 'text' | 'money' | 'number' | 'date' }>; rows: Array<Record<string, unknown>>; totals: Record<string, unknown>; row_count: number; notes: string[]; warnings: Array<{ code: string; message: string }> }
export interface SavingsOpportunity { opportunity_id: string; type: 'budget_overrun' | 'price_anomaly' | 'cheaper_supplier' | 'overtime_concentration' | 'rework_increase' | 'unlinked_expense' | 'uncollected_change_order' | 'unlinked_customer_advance'; severity: 'low' | 'medium' | 'high'; title: string; reason: string; estimated_impact_kurus: number | null; related_amount_kurus: number | null; confidence: 'low' | 'medium' | 'high'; data_sufficiency: { sample_count: number; minimum_samples: number; sufficient: boolean }; sources: CostSource[]; deep_link: CalendarSourceRoute; project_id: string | null }
