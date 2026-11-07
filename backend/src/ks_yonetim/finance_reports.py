"""Proje, müşteri, tedarikçi, nakit planı, puantaj ve malzeme raporları (JSON/XLSX/PDF tek üreticiden).

Her rapor bir `ReportTable` üretir; JSON, XLSX ve PDF aynı satır ve toplamlardan çıkar. Tarih varsayımı
`clock.business_today`'dir. 13 haftalık nakit raporu banka veya kasa bakiyesi iddiasında bulunmaz.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import clock
from .api import ApiError, require_sidecar_token
from .attendance import PlanBook, holiday_dates, required_days
from .calendar_api import collect_events
from .customers import (
    advance_split,
    compute_receivables,
    customer_buckets,
    customer_statement,
)
from .exports import Column, ReportTable
from .finance import compute_positions, summarize
from .models import (
    Customer,
    Employee,
    ExpenseCategory,
    Material,
    MaterialMovement,
    MovementType,
    Project,
    ProjectExpense,
    Purchase,
    PurchaseReceipt,
    ReceivableSchedule,
    RecordStatus,
    Site,
    Supplier,
    WorkLog,
)
from .project_finance import compute_profitability
from .receipts import quantity_warnings
from .report_base import build_report as shared_build_report
from .report_base import register_report_routes
from .reports import AGING_LABELS, debt_aging
from .supplier_ledger import supplier_statement
from .textnorm import match_key

router = APIRouter(prefix="/api/v1/reports/finance", dependencies=[Depends(require_sidecar_token)])
WEEKS = 13

CATEGORY_LABELS = {
    "material": "Malzeme",
    "labor": "İşçilik",
    "shipping": "Nakliye",
    "installation": "Montaj",
    "subcontractor": "Taşeron",
    "site": "Şantiye",
    "waste_rework": "Fire / yeniden işleme",
    "other": "Diğer",
}
LIFECYCLE_LABELS = {
    "planned": "Planlandı",
    "ordered": "Sipariş verildi",
    "partially_received": "Kısmen teslim",
    "received": "Teslim edildi",
    "cancelled": "İptal",
}
EVENT_LABELS = {
    "receivable_due": "Tahsilat",
    "supplier_payable": "Tedarikçi ödemesi",
    "payroll_due": "Maaş / personel ödemesi",
}
AGING_KEYS = list(AGING_LABELS)


@dataclass
class Filters:
    date_from: date | None = None
    date_to: date | None = None
    project_id: str | None = None
    customer_id: str | None = None
    supplier_id: str | None = None
    employee_id: str | None = None
    material_id: str | None = None
    site_id: str | None = None
    horizon_days: int = 30

    @property
    def as_of(self) -> date:
        return self.date_to or clock.business_today()

    def as_dict(self) -> dict:
        return {
            "date_from": self.date_from,
            "date_to": self.date_to,
            "project_id": self.project_id,
            "customer_id": self.customer_id,
            "supplier_id": self.supplier_id,
            "employee_id": self.employee_id,
            "material_id": self.material_id,
            "site_id": self.site_id,
        }


def get_filters(
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: str | None = Query(default=None, max_length=36),
    customer_id: str | None = Query(default=None, max_length=36),
    supplier_id: str | None = Query(default=None, max_length=36),
    employee_id: str | None = Query(default=None, max_length=36),
    material_id: str | None = Query(default=None, max_length=36),
    site_id: str | None = Query(default=None, max_length=36),
    horizon_days: int = Query(30, ge=1, le=365),
) -> Filters:
    if date_from and date_to and date_from > date_to:
        raise ApiError("invalid_range", "Başlangıç tarihi bitiş tarihinden sonra olamaz.", 422)
    return Filters(
        date_from, date_to, project_id, customer_id, supplier_id, employee_id, material_id, site_id,
        horizon_days,
    )


def iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def totals_for(rows: list[dict], columns: list[Column], *, skip: tuple[str, ...] = ()) -> dict:
    return {
        c.key: sum(int(row.get(c.key) or 0) for row in rows)
        for c in columns
        if c.kind == "money" and c.key not in skip
    }


def names(session: Session, model, ids: set[str | None]) -> dict[str, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return dict(session.execute(select(model.id, model.name).where(model.id.in_(wanted))).all())


# --- Proje kârlılığı --------------------------------------------------------------------------------


def _projects(session: Session, f: Filters) -> list[Project]:
    query = select(Project).where(Project.status == RecordStatus.ACTIVE)
    if f.project_id:
        query = query.where(Project.id == f.project_id)
    projects = list(session.scalars(query.order_by(Project.name, Project.id)))
    if f.project_id and not projects:
        raise ApiError("not_found", "Proje bulunamadı.", 404)
    return projects


def _advance_warnings(profit: dict, project: Project) -> list[dict]:
    return [{**w, "project_id": project.id, "project_name": project.name} for w in profit["warnings"]]


def report_project_profitability(session: Session, f: Filters) -> ReportTable:
    columns = [
        Column("project_name", "Proje"),
        Column("customer_name", "Müşteri"),
        Column("contract_amount_kurus", "Sözleşme", "money"),
        Column("approved_change_orders_kurus", "Onaylı ek iş", "money"),
        Column("revised_contract_kurus", "Revize sözleşme", "money"),
        Column("actual_cost_kurus", "Gerçekleşen maliyet", "money"),
        Column("commitment_kurus", "Taahhüt", "money"),
        Column("remaining_estimate_kurus", "Kalan tahmin", "money"),
        Column("forecast_cost_at_completion_kurus", "Tahmini bitiş maliyeti", "money"),
        Column("estimated_profit_kurus", "Tahmini kâr", "money"),
        Column("estimated_margin_percent", "Tahmini marj %", "number"),
        Column("net_collected_kurus", "Net tahsilat (projeye bağlı)", "money"),
        Column("open_receivable_kurus", "Açık alacak", "money"),
    ]
    rows, warnings, seen = [], [], set()
    for project in _projects(session, f):
        profit = compute_profitability(session, project)
        collections = profit["collections"] or {}
        rows.append(
            {
                "project_id": project.id,
                "project_name": project.name,
                "customer_name": project.customer_name,
                **{
                    key: profit[key]
                    for key in (
                        "contract_amount_kurus", "approved_change_orders_kurus",
                        "revised_contract_kurus", "actual_cost_kurus", "commitment_kurus",
                        "remaining_estimate_kurus", "forecast_cost_at_completion_kurus",
                        "estimated_profit_kurus", "estimated_margin_percent",
                    )
                },
                "net_collected_kurus": collections.get("net_collected_kurus"),
                "open_receivable_kurus": collections.get("open_receivable_kurus"),
            }
        )
        for warning in _advance_warnings(profit, project):
            if warning["customer_id"] not in seen:
                seen.add(warning["customer_id"])
                warnings.append(warning)
    return ReportTable(
        "project-profitability", "Proje Kâr / Zarar ve Tahmini Marj", columns, rows,
        totals_for(rows, columns), f.as_dict(),
        notes=[
            ("Maliyet teslim fişleri, işçilik tahakkuku ve giderlerden gelir; planlı/siparişli satın alma "
            "gerçekleşen maliyet değil taahhüttür."),
            "Tahsilat yalnız projeye bağlı veya projenin alacak planlarına dağıtılmış tutarları içerir.",
        ],
        warnings=warnings,
    )


def report_project_comparison(session: Session, f: Filters) -> ReportTable:
    base = report_project_profitability(session, f)
    ranked = sorted(
        base.rows,
        key=lambda r: (r["estimated_margin_percent"] is None, -(r["estimated_margin_percent"] or 0), r["project_name"]),
    )
    total_cost = sum(r["actual_cost_kurus"] for r in ranked) or 0
    columns = [
        Column("rank", "Sıra", "number"),
        Column("project_name", "Proje"),
        Column("revised_contract_kurus", "Revize sözleşme", "money"),
        Column("forecast_cost_at_completion_kurus", "Tahmini bitiş maliyeti", "money"),
        Column("estimated_profit_kurus", "Tahmini kâr", "money"),
        Column("estimated_margin_percent", "Tahmini marj %", "number"),
        Column("actual_cost_kurus", "Gerçekleşen maliyet", "money"),
        Column("cost_share_percent", "Maliyet payı %", "number"),
    ]
    rows = [
        {
            "rank": index,
            "project_id": row["project_id"],
            "project_name": row["project_name"],
            "revised_contract_kurus": row["revised_contract_kurus"],
            "forecast_cost_at_completion_kurus": row["forecast_cost_at_completion_kurus"],
            "estimated_profit_kurus": row["estimated_profit_kurus"],
            "estimated_margin_percent": row["estimated_margin_percent"],
            "actual_cost_kurus": row["actual_cost_kurus"],
            "cost_share_percent": round(row["actual_cost_kurus"] / total_cost * 100, 2) if total_cost else None,
        }
        for index, row in enumerate(ranked, start=1)
    ]
    return ReportTable(
        "project-comparison", "Projeler Arası Kârlılık Karşılaştırması", columns, rows,
        totals_for(rows, columns), f.as_dict(),
        notes=["Sıralama tahmini marja göredir; sözleşmesi olmayan projeler sona yazılır."],
        warnings=base.warnings,
    )


def report_budget_variance(session: Session, f: Filters) -> ReportTable:
    columns = [
        Column("project_name", "Proje"),
        Column("category_label", "Kategori"),
        Column("original_budget_kurus", "İlk bütçe", "money"),
        Column("budget_kurus", "Revize bütçe", "money"),
        Column("actual_kurus", "Gerçekleşen", "money"),
        Column("commitment_kurus", "Taahhüt", "money"),
        Column("remaining_estimate_kurus", "Kalan tahmin", "money"),
        Column("forecast_kurus", "Tahmini bitiş", "money"),
        Column("variance_kurus", "Sapma (bütçe − tahmin)", "money"),
        Column("variance_percent", "Sapma %", "number"),
        Column("forecast_source", "Tahmin kaynağı"),
    ]
    rows = []
    for project in _projects(session, f):
        for category in compute_profitability(session, project)["categories"]:
            if not any(
                category[key]
                for key in ("budget_kurus", "actual_kurus", "commitment_kurus", "forecast_kurus")
            ):
                continue
            budget = category["budget_kurus"]
            rows.append(
                {
                    "project_id": project.id,
                    "project_name": project.name,
                    "category": category["category"],
                    "category_label": CATEGORY_LABELS[category["category"]],
                    **{
                        key: category[key]
                        for key in (
                            "original_budget_kurus", "budget_kurus", "actual_kurus", "commitment_kurus",
                            "remaining_estimate_kurus", "forecast_kurus", "variance_kurus",
                            "forecast_source",
                        )
                    },
                    "variance_percent": round(category["variance_kurus"] / budget * 100, 2)
                    if budget and category["variance_kurus"] is not None
                    else None,
                }
            )
    return ReportTable(
        "budget-variance", "Kategori Bazlı Bütçe Sapması", columns, rows,
        totals_for(rows, columns), f.as_dict(),
        notes=["Negatif sapma tahmini bitiş maliyetinin bütçeyi aştığını gösterir."],
    )


# --- Yaşlandırma ve ekstreler -----------------------------------------------------------------------


def report_customer_aging(session: Session, f: Filters) -> ReportTable:
    bucket_labels = {"not_due": "Vadesi gelmemiş", "1_30": "1–30 gün", "31_60": "31–60 gün",
                     "61_90": "61–90 gün", "90_plus": "90+ gün", "no_due_date": "Vadesiz / plansız"}
    columns = [Column("customer_name", "Müşteri")]
    columns += [Column(key, label, "money") for key, label in bucket_labels.items()]
    columns += [
        Column("total_open_kurus", "Toplam açık alacak", "money"),
        Column("overdue_kurus", "Gecikmiş alacak", "money"),
        Column("project_advance_kurus", "Avans (projeye bağlı)", "money"),
        Column("unlinked_advance_kurus", "Avans (bağlantısız)", "money"),
    ]
    query = select(Customer).order_by(Customer.name, Customer.id)
    if f.customer_id:
        query = query.where(Customer.id == f.customer_id)
    rows, warnings = [], []
    for customer in session.scalars(query):
        result = compute_receivables(session, customer.id, f.as_of)
        buckets = dict.fromkeys(bucket_labels, 0)
        for item in result["items"]:
            buckets[item.bucket] += item.remaining_kurus
        split = advance_split(customer_buckets(session, customer.id, f.as_of))
        total = sum(buckets.values())
        if not total and not any(split.values()):
            continue
        rows.append(
            {
                "customer_id": customer.id,
                "customer_name": customer.name,
                **buckets,
                "total_open_kurus": total,
                "overdue_kurus": buckets["1_30"] + buckets["31_60"] + buckets["61_90"] + buckets["90_plus"],
                **split,
            }
        )
        if split["unlinked_advance_kurus"] > 0:
            warnings.append(
                {
                    "code": "unlinked_customer_advance",
                    "customer_id": customer.id,
                    "amount_kurus": split["unlinked_advance_kurus"],
                    "message": f"{customer.name}: {split['unlinked_advance_kurus'] / 100:.2f} TL bağlantısız avans var.",
                }
            )
    return ReportTable(
        "customer-aging", "Müşteri Alacak Yaşlandırması", columns, rows, totals_for(rows, columns),
        f.as_dict(),
        notes=["Avans (kredi) gecikmiş alacaktan ayrı gösterilir ve alacak toplamına karıştırılmaz."],
        warnings=warnings,
    )


def report_supplier_aging(session: Session, f: Filters) -> ReportTable:
    report = debt_aging(session, f.as_of)
    columns = [Column("supplier_name", "Tedarikçi")]
    columns += [Column(key, AGING_LABELS[key], "money") for key in AGING_KEYS]
    columns += [
        Column("total_open_kurus", "Toplam açık borç", "money"),
        Column("overdue_kurus", "Gecikmiş borç", "money"),
        Column("credit_kurus", "Tedarikçi avansı", "money"),
    ]
    rows = [
        {
            "supplier_id": s.supplier_id,
            "supplier_name": s.supplier_name,
            **{key: s.buckets[key] for key in AGING_KEYS},
            "total_open_kurus": s.total_open_kurus,
            "overdue_kurus": s.overdue_kurus,
            "credit_kurus": s.credit_kurus,
        }
        for s in report.suppliers
        if not f.supplier_id or s.supplier_id == f.supplier_id
    ]
    rows.sort(key=lambda r: (-r["total_open_kurus"], r["supplier_name"]))
    return ReportTable(
        "supplier-aging", "Tedarikçi Borç Yaşlandırması", columns, rows, totals_for(rows, columns),
        f.as_dict(), notes=["Borç teslim fişlerine göre hesaplanır; planlı/siparişli kayıtlar borç değildir."],
    )


def report_customer_statement(session: Session, f: Filters) -> ReportTable:
    if not f.customer_id:
        raise ApiError("customer_required", "Cari ekstre için customer_id gereklidir.", 422)
    data = customer_statement(f.customer_id, session=session, date_from=f.date_from, date_to=f.date_to, project_id=f.project_id)
    projects = names(session, Project, {r["project_id"] for r in data["rows"]})
    columns = [
        Column("movement_date", "Tarih", "date"),
        Column("movement_type", "Tür"),
        Column("project_name", "Proje"),
        Column("increase_kurus", "Alacak artışı", "money"),
        Column("decrease_kurus", "Alacak azalışı", "money"),
        Column("balance_kurus", "Yürüyen bakiye", "money"),
        Column("voided", "Hükümsüz"),
        Column("note", "Not"),
    ]
    rows = [
        {
            "movement_date": iso(r["movement_date"]),
            "movement_type": r["movement_type"],
            "project_name": projects.get(r["project_id"]) or "—",
            "increase_kurus": r["increase_kurus"],
            "decrease_kurus": r["decrease_kurus"],
            "balance_kurus": r["balance_kurus"],
            "voided": "evet" if r["is_voided"] else "",
            "note": r["note"],
        }
        for r in data["rows"]
    ]
    return ReportTable(
        "customer-statement", f"Müşteri Cari Ekstresi: {data['customer_name']}", columns, rows,
        {"increase_kurus": data["total_increase_kurus"], "decrease_kurus": data["total_decrease_kurus"]},
        f.as_dict(),
        notes=[
            (f"Açılış bakiyesi {data['opening_balance_kurus'] / 100:.2f} TL; kapanış "
            f"{data['closing_balance_kurus'] / 100:.2f} TL (negatif değer müşteri avansıdır).")
        ],
    )


def report_supplier_statement(session: Session, f: Filters) -> ReportTable:
    if not f.supplier_id:
        raise ApiError("supplier_required", "Cari ekstre için supplier_id gereklidir.", 422)
    data = supplier_statement(f.supplier_id, session=session, date_from=f.date_from, date_to=f.date_to)
    labels = {"purchase_receipt": "Teslim", "payment": "Ödeme", "payment_reversal": "Ödeme ters kaydı"}
    columns = [
        Column("date", "Tarih", "date"),
        Column("row_type", "Tür"),
        Column("increase_kurus", "Borç artışı", "money"),
        Column("decrease_kurus", "Borç azalışı", "money"),
        Column("balance_kurus", "Yürüyen bakiye", "money"),
        Column("note", "Not"),
    ]
    rows = [
        {
            "date": iso(r["date"]), "row_type": labels[r["row_type"]],
            "increase_kurus": r["increase_kurus"], "decrease_kurus": r["decrease_kurus"],
            "balance_kurus": r["balance_kurus"], "note": r["note"],
        }
        for r in data["rows"]
    ]
    return ReportTable(
        "supplier-statement", f"Tedarikçi Cari Ekstresi: {data['supplier_name']}", columns, rows,
        {"increase_kurus": data["total_increase_kurus"], "decrease_kurus": data["total_decrease_kurus"]},
        f.as_dict(),
        notes=[f"Açılış bakiyesi {data['opening_balance_kurus'] / 100:.2f} TL; kapanış {data['closing_balance_kurus'] / 100:.2f} TL."],
    )


def report_customer_advances(session: Session, f: Filters) -> ReportTable:
    columns = [
        Column("customer_name", "Müşteri"),
        Column("project_name", "Proje"),
        Column("link_status", "Bağlantı"),
        Column("project_advance_kurus", "Avans (projeye bağlı)", "money"),
        Column("unlinked_advance_kurus", "Avans (bağlantısız)", "money"),
    ]
    query = select(Customer).order_by(Customer.name, Customer.id)
    if f.customer_id:
        query = query.where(Customer.id == f.customer_id)
    rows, warnings = [], []
    for customer in session.scalars(query):
        buckets = customer_buckets(session, customer.id, f.as_of)
        projects = names(session, Project, {p for p in buckets if p})
        for project_id, bucket in sorted(buckets.items(), key=lambda kv: (kv[0] is None, projects.get(kv[0] or "", ""))):
            if bucket["advance_kurus"] <= 0 or (f.project_id and project_id != f.project_id):
                continue
            linked = project_id is not None
            rows.append(
                {
                    "customer_id": customer.id,
                    "customer_name": customer.name,
                    "project_id": project_id,
                    "project_name": projects.get(project_id, "—") if linked else "Bağlantısız",
                    "link_status": "Projeye bağlı" if linked else "Bağlantısız",
                    "project_advance_kurus": bucket["advance_kurus"] if linked else 0,
                    "unlinked_advance_kurus": 0 if linked else bucket["advance_kurus"],
                }
            )
            if not linked:
                warnings.append(
                    {
                        "code": "unlinked_customer_advance",
                        "customer_id": customer.id,
                        "amount_kurus": bucket["advance_kurus"],
                        "message": f"{customer.name}: bağlantısız avans projeye bağlanmalı veya plana dağıtılmalı.",
                    }
                )
    return ReportTable(
        "customer-advances", "Müşteri Avansları (Projeye Bağlı / Bağlantısız)", columns, rows,
        totals_for(rows, columns), f.as_dict(),
        notes=["Bağlantısız avans proje kârlılığına ve proje tahsilatına sayılmaz."],
        warnings=warnings,
    )


# --- Nakit planı ve takvim ----------------------------------------------------------------------------


def _cash_events(session: Session, start: date, end: date, today: date) -> list[dict]:
    types = {"receivable_due", "supplier_payable", "payroll_due"}
    return [
        e
        for e in collect_events(session, start, end, today, event_types=types)
        if e["state"] in ("overdue", "today", "upcoming") and (e["amount_kurus"] or 0) > 0
    ]


def _project_filter(events: list[dict], f: Filters) -> list[dict]:
    if f.project_id:
        events = [e for e in events if e["project_id"] == f.project_id]
    if f.customer_id:
        events = [e for e in events if e["customer_id"] == f.customer_id]
    if f.supplier_id:
        events = [e for e in events if e["supplier_id"] == f.supplier_id]
    return events


def report_cash_forecast(session: Session, f: Filters) -> ReportTable:
    start = f.as_of
    end = start + timedelta(days=WEEKS * 7 - 1)
    events = _project_filter(_cash_events(session, start - timedelta(days=730), end, start), f)
    columns = [
        Column("period_label", "Dönem"),
        Column("week_start", "Başlangıç", "date"),
        Column("week_end", "Bitiş", "date"),
        Column("planned_inflow_kurus", "Planlı giriş", "money"),
        Column("planned_outflow_kurus", "Planlı çıkış", "money"),
        Column("net_change_kurus", "Net değişim", "money"),
        Column("cumulative_net_change_kurus", "Kümülatif net değişim", "money"),
    ]
    buckets: dict[int, dict[str, int]] = {w: {"in": 0, "out": 0} for w in range(WEEKS + 1)}
    for event in events:
        week = 0 if event["start_date"] < start else (event["start_date"] - start).days // 7 + 1
        if week > WEEKS:
            continue
        key = "in" if event["event_type"] == "receivable_due" else "out"
        buckets[week][key] += event["amount_kurus"]
    rows, cumulative = [], 0
    for week in range(WEEKS + 1):
        inflow, outflow = buckets[week]["in"], buckets[week]["out"]
        if week == 0 and not (inflow or outflow):
            continue
        cumulative += inflow - outflow
        rows.append(
            {
                "week_no": week,
                "period_label": "Vadesi geçmiş (devreden)" if week == 0 else f"Hafta {week}",
                "week_start": None if week == 0 else iso(start + timedelta(days=(week - 1) * 7)),
                "week_end": None if week == 0 else iso(start + timedelta(days=week * 7 - 1)),
                "planned_inflow_kurus": inflow,
                "planned_outflow_kurus": outflow,
                "net_change_kurus": inflow - outflow,
                "cumulative_net_change_kurus": cumulative,
            }
        )
    totals = {
        "planned_inflow_kurus": sum(r["planned_inflow_kurus"] for r in rows),
        "planned_outflow_kurus": sum(r["planned_outflow_kurus"] for r in rows),
        "net_change_kurus": sum(r["net_change_kurus"] for r in rows),
    }
    undated_receivable = 0
    for item_customer in session.scalars(select(ReceivableSchedule.customer_id).distinct()):
        undated_receivable += sum(
            i.remaining_kurus
            for i in compute_receivables(session, item_customer, start)["items"]
            if i.due_date is None
        )
    return ReportTable(
        "cash-forecast-13w", "13 Haftalık Planlı Nakit Hareketi", columns, rows, totals, f.as_dict(),
        notes=[
            ("Bu rapor banka veya kasa bakiyesi içermez; yalnızca planlı giriş, planlı çıkış ve net değişimi "
            "gösterir."),
            ("Planlı giriş: vadeli alacak planları. Planlı çıkış: vadeli tedarikçi borcu ile maaş/personel "
            "ödemeleri. Vadesi gelmiş ve ödenmemiş tutarlar ilk satırda devreden olarak gösterilir."),
            f"Vadesi girilmemiş açık alacak ({undated_receivable / 100:.2f} TL) bu rapora dahil değildir.",
        ],
    )


def report_upcoming_schedule(session: Session, f: Filters) -> ReportTable:
    today = f.as_of
    events = _project_filter(
        _cash_events(session, today - timedelta(days=730), today + timedelta(days=f.horizon_days), today), f
    )
    projects = names(session, Project, {e["project_id"] for e in events})
    columns = [
        Column("start_date", "Vade", "date"),
        Column("kind_label", "Tür"),
        Column("title", "Açıklama"),
        Column("project_name", "Proje"),
        Column("state", "Durum"),
        Column("inflow_kurus", "Tahsilat", "money"),
        Column("outflow_kurus", "Ödeme", "money"),
    ]
    rows = [
        {
            "event_id": e["event_id"],
            "start_date": iso(e["start_date"]),
            "kind_label": EVENT_LABELS[e["event_type"]],
            "title": e["title"],
            "project_name": projects.get(e["project_id"]) or "—",
            "state": e["state"],
            "inflow_kurus": e["amount_kurus"] if e["event_type"] == "receivable_due" else 0,
            "outflow_kurus": 0 if e["event_type"] == "receivable_due" else e["amount_kurus"],
        }
        for e in events
    ]
    return ReportTable(
        "upcoming-schedule", "Yaklaşan Ödeme ve Tahsilat Takvimi", columns, rows,
        totals_for(rows, columns), f.as_dict(),
        notes=[f"Gecikmiş ve önümüzdeki {f.horizon_days} gün içindeki açık vadeler listelenir."],
    )


# --- Personel ------------------------------------------------------------------------------------------


def report_staff_balances(session: Session, f: Filters) -> ReportTable:
    positions = compute_positions(session, [f.employee_id] if f.employee_id else None, f.as_of)
    people = names(session, Employee, set(positions))
    columns = [
        Column("employee_name", "Personel"),
        Column("unpaid_payroll_kurus", "Kalan maaş ödemesi", "money"),
        Column("company_owes_employee_kurus", "Şirketin toplam borcu", "money"),
        Column("active_advance_kurus", "Açık avans", "money"),
        Column("employee_debt_kurus", "Personel borcu", "money"),
        Column("overdue_company_debt_kurus", "Gecikmiş maaş borcu", "money"),
        Column("net_position_kurus", "Net pozisyon", "money"),
    ]
    rows = []
    for employee_id in sorted(positions, key=lambda i: (people.get(i, "").casefold(), i)):
        summary = summarize(positions[employee_id], f.as_of)
        if not any(summary[c.key] for c in columns[1:]):
            continue
        rows.append({"employee_id": employee_id, "employee_name": people.get(employee_id), **{c.key: summary[c.key] for c in columns[1:]}})
    return ReportTable(
        "staff-balances", "Personel Maaş, Avans, Borç ve Kalan Ödeme", columns, rows,
        totals_for(rows, columns), f.as_dict(),
        notes=["İşletme içi takip raporudur; resmî bordro, SGK veya vergi hesabı içermez."],
    )


def report_attendance_overtime_leave(session: Session, f: Filters) -> ReportTable:
    end = f.as_of
    start = f.date_from or end - timedelta(days=29)
    query = select(Employee).where(Employee.status == RecordStatus.ACTIVE)
    if f.employee_id:
        query = query.where(Employee.id == f.employee_id)
    employees = list(session.scalars(query.order_by(Employee.name, Employee.id)))
    logs: dict[str, list[WorkLog]] = defaultdict(list)
    for log in session.scalars(
        select(WorkLog).where(
            WorkLog.status == RecordStatus.ACTIVE, WorkLog.work_date >= start, WorkLog.work_date <= end
        )
    ):
        logs[log.employee_id].append(log)
    plans, holidays = PlanBook(session), holiday_dates(session, start, end)
    columns = [
        Column("employee_name", "Personel"),
        Column("worked_day_count", "Çalışılan gün", "number"),
        Column("normal_hours", "Normal saat", "number"),
        Column("overtime_hours", "Fazla mesai saat", "number"),
        Column("overtime_ratio_percent", "Fazla mesai oranı %", "number"),
        Column("annual_leave_hours", "Yıllık izin saat", "number"),
        Column("sick_leave_hours", "Raporlu saat", "number"),
        Column("excused_leave_hours", "Mazeret saat", "number"),
        Column("other_leave_day_count", "Diğer izin gün", "number"),
        Column("absent_day_count", "Devamsız gün", "number"),
        Column("missing_required_day_count", "Eksik zorunlu gün", "number"),
    ]
    rows = []
    for employee in employees:
        mine = logs.get(employee.id, [])
        worked = [l for l in mine if l.work_status in ("worked", "half_day", "overtime")]
        normal = sum((Decimal(l.normal_hours) for l in worked), Decimal(0))
        overtime = sum((Decimal(l.overtime_hours) for l in worked), Decimal(0))

        def leave_hours(status: str, mine=mine) -> Decimal:
            return sum((Decimal(l.leave_hours or 0) for l in mine if l.work_status == status), Decimal(0))

        covered = {l.work_date for l in mine}
        missing = [d for d in required_days(employee, start, end, plans, holidays) if d not in covered]
        if not mine and not missing:
            continue
        rows.append(
            {
                "employee_id": employee.id,
                "employee_name": employee.name,
                "worked_day_count": len(worked),
                "normal_hours": float(normal),
                "overtime_hours": float(overtime),
                "overtime_ratio_percent": round(float(overtime / (normal + overtime) * 100), 2) if normal + overtime else 0,
                "annual_leave_hours": float(leave_hours("annual_leave")),
                "sick_leave_hours": float(leave_hours("sick_leave")),
                "excused_leave_hours": float(leave_hours("excused_leave")),
                "other_leave_day_count": sum(1 for l in mine if l.work_status in ("paid_leave", "unpaid_leave")),
                "absent_day_count": sum(1 for l in mine if l.work_status == "absent"),
                "missing_required_day_count": len(missing),
            }
        )
    totals = {
        c.key: round(sum(float(r[c.key]) for r in rows), 2)
        for c in columns[1:]
        if c.key != "overtime_ratio_percent"
    }
    return ReportTable(
        "attendance-overtime-leave", "Puantaj, Fazla Mesai, İzin ve Eksik Devam", columns, rows, totals,
        {**f.as_dict(), "date_from": start, "date_to": end},
        notes=["Eksik zorunlu gün: haftalık plan, resmî tatil ve işe giriş/çıkış dikkate alınarak puantajı olmayan günlerdir."],
    )


def report_labor_cost(session: Session, f: Filters) -> ReportTable:
    query = select(WorkLog).where(WorkLog.status == RecordStatus.ACTIVE)
    for column, value in ((WorkLog.project_id, f.project_id), (WorkLog.site_id, f.site_id), (WorkLog.employee_id, f.employee_id)):
        if value:
            query = query.where(column == value)
    if f.date_from:
        query = query.where(WorkLog.work_date >= f.date_from)
    if f.date_to:
        query = query.where(WorkLog.work_date <= f.date_to)
    groups: dict[tuple[str | None, str | None], dict] = defaultdict(
        lambda: {"log_count": 0, "normal_hours": Decimal(0), "overtime_hours": Decimal(0), "labor_kurus": 0}
    )
    for log in session.scalars(query):
        g = groups[(log.project_id, log.site_id)]
        g["log_count"] += 1
        g["normal_hours"] += Decimal(log.normal_hours)
        g["overtime_hours"] += Decimal(log.overtime_hours)
        g["labor_kurus"] += log.amount_kurus
    projects = names(session, Project, {k[0] for k in groups})
    sites = names(session, Site, {k[1] for k in groups})
    columns = [
        Column("project_name", "Proje"),
        Column("site_name", "Şantiye"),
        Column("log_count", "Kayıt sayısı", "number"),
        Column("normal_hours", "Normal saat", "number"),
        Column("overtime_hours", "Fazla mesai saat", "number"),
        Column("labor_kurus", "İşçilik tahakkuku", "money"),
    ]
    rows = [
        {
            "project_name": projects.get(p, "Projesiz") if p else "Projesiz",
            "site_name": sites.get(s, "—") if s else "—",
            "log_count": g["log_count"],
            "normal_hours": float(g["normal_hours"]),
            "overtime_hours": float(g["overtime_hours"]),
            "labor_kurus": g["labor_kurus"],
        }
        for (p, s), g in sorted(groups.items(), key=lambda kv: (projects.get(kv[0][0], "~"), sites.get(kv[0][1], "~")))
    ]
    totals = {
        "log_count": sum(r["log_count"] for r in rows),
        "normal_hours": round(sum(r["normal_hours"] for r in rows), 2),
        "overtime_hours": round(sum(r["overtime_hours"] for r in rows), 2),
        "labor_kurus": sum(r["labor_kurus"] for r in rows),
    }
    return ReportTable("labor-cost", "Proje / Şantiye İşçilik Maliyeti", columns, rows, totals, f.as_dict(),
                       notes=["İşçilik çalışma tarihinden tahakkuk eder; ödeme tarihi maliyeti değiştirmez."])


# --- Malzeme ve satın alma ------------------------------------------------------------------------------


def report_material_price_history(session: Session, f: Filters) -> ReportTable:
    query = (
        select(PurchaseReceipt, Purchase)
        .join(Purchase, Purchase.id == PurchaseReceipt.purchase_id)
        .where(Purchase.status == RecordStatus.ACTIVE, PurchaseReceipt.status == RecordStatus.ACTIVE)
        .order_by(PurchaseReceipt.receipt_date, PurchaseReceipt.id)
    )
    for column, value in ((Purchase.material_id, f.material_id), (Purchase.supplier_id, f.supplier_id), (Purchase.project_id, f.project_id)):
        if value:
            query = query.where(column == value)
    if f.date_from:
        query = query.where(PurchaseReceipt.receipt_date >= f.date_from)
    if f.date_to:
        query = query.where(PurchaseReceipt.receipt_date <= f.date_to)
    records = session.execute(query).all()
    material_names = names(session, Material, {p.material_id for _, p in records})
    suppliers = names(session, Supplier, {p.supplier_id for _, p in records})
    columns = [
        Column("receipt_date", "Teslim tarihi", "date"),
        Column("material_name", "Malzeme"),
        Column("unit", "Birim"),
        Column("supplier_name", "Tedarikçi"),
        Column("quantity", "Miktar", "number"),
        Column("unit_price_kurus", "Birim fiyat", "money"),
        Column("price_change_percent", "Önceki alıma göre %", "number"),
        Column("amount_kurus", "Tutar", "money"),
    ]
    last: dict[tuple[str, str | None], int] = {}
    rows = []
    for receipt, purchase in records:
        quantity = Decimal(receipt.quantity) if receipt.quantity else None
        if quantity:
            unit_price = int((Decimal(receipt.amount_kurus) / quantity).quantize(Decimal(1)))
        else:
            unit_price = purchase.unit_price_kurus
        key = (purchase.material_id, match_key(purchase.unit or "") or None)
        previous = last.get(key)
        change = round((unit_price - previous) / previous * 100, 2) if unit_price and previous else None
        if unit_price:
            last[key] = unit_price
        rows.append(
            {
                "receipt_id": receipt.id,
                "purchase_id": purchase.id,
                "receipt_date": iso(receipt.receipt_date),
                "material_name": material_names.get(purchase.material_id),
                "unit": purchase.unit,
                "supplier_name": suppliers.get(purchase.supplier_id),
                "quantity": float(quantity) if quantity else None,
                "unit_price_kurus": unit_price,
                "price_change_percent": change,
                "amount_kurus": receipt.amount_kurus,
            }
        )
    return ReportTable(
        "material-price-history", "Malzeme Alım Fiyat Geçmişi", columns, rows, totals_for(rows, columns),
        f.as_dict(), notes=["Birim fiyat teslim tutarının teslim miktarına bölünmesiyle bulunur; miktarsız teslimde satın alma birim fiyatı kullanılır."],
    )


def report_waste_rework(session: Session, f: Filters) -> ReportTable:
    rows: list[dict] = []
    expense_query = select(ProjectExpense).where(
        ProjectExpense.status == RecordStatus.ACTIVE, ProjectExpense.category == ExpenseCategory.REWORK
    )
    movement_query = select(MaterialMovement).where(
        MaterialMovement.status == RecordStatus.ACTIVE,
        MaterialMovement.movement_type == MovementType.WASTE,
        MaterialMovement.amount_kurus.is_not(None),
    )
    if f.project_id:
        expense_query = expense_query.where(ProjectExpense.project_id == f.project_id)
        movement_query = movement_query.where(MaterialMovement.project_id == f.project_id)
    if f.date_from:
        expense_query = expense_query.where(ProjectExpense.expense_date >= f.date_from)
        movement_query = movement_query.where(MaterialMovement.movement_date >= f.date_from)
    if f.date_to:
        expense_query = expense_query.where(ProjectExpense.expense_date <= f.date_to)
        movement_query = movement_query.where(MaterialMovement.movement_date <= f.date_to)
    expenses = list(session.scalars(expense_query))
    movements = list(session.scalars(movement_query))
    projects = names(session, Project, {e.project_id for e in expenses} | {m.project_id for m in movements})
    materials = names(session, Material, {m.material_id for m in movements})
    for e in expenses:
        rows.append({"source_type": "project_expense", "source_id": e.id, "date": iso(e.expense_date),
                     "kind_label": "Yeniden işleme gideri", "project_name": projects.get(e.project_id),
                     "material_name": None, "note": e.description, "amount_kurus": e.amount_kurus})
    for m in movements:
        rows.append({"source_type": "material_movement", "source_id": m.id, "date": iso(m.movement_date),
                     "kind_label": "Fire (malzeme)", "project_name": projects.get(m.project_id) or "Projesiz",
                     "material_name": materials.get(m.material_id), "note": m.note, "amount_kurus": m.amount_kurus})
    rows.sort(key=lambda r: (r["date"], r["source_id"]))
    columns = [
        Column("date", "Tarih", "date"), Column("kind_label", "Tür"), Column("project_name", "Proje"),
        Column("material_name", "Malzeme"), Column("note", "Not"), Column("amount_kurus", "Tutar", "money"),
    ]
    return ReportTable(
        "waste-rework-cost", "Fire ve Yeniden İşleme Maliyeti", columns, rows, totals_for(rows, columns),
        f.as_dict(),
        notes=[("Fire tutarı satın alma maliyetinin içindedir; yeniden işleme giderleri ayrı gider kaydıdır. "
               "Bu rapor ikisini ayrı listeler, toplam maliyete eklemez.")],
    )


def report_purchase_lifecycle(session: Session, f: Filters) -> ReportTable:
    return purchase_lifecycle_table(session, f)


def purchase_lifecycle_table(session: Session, f: Filters | None = None) -> ReportTable:
    """Satın alma listesi: planlı / sipariş / teslim ayrı; yalnız teslim edilen tutar gerçek maliyet/borçtur."""
    f = f or Filters()
    query = (
        select(Purchase, Supplier.name, Material.name)
        .join(Supplier, Supplier.id == Purchase.supplier_id)
        .join(Material, Material.id == Purchase.material_id)
        .where(Purchase.status == RecordStatus.ACTIVE)
        .order_by(Purchase.purchase_date, Purchase.id)
    )
    for column, value in ((Purchase.supplier_id, f.supplier_id), (Purchase.project_id, f.project_id), (Purchase.material_id, f.material_id)):
        if value:
            query = query.where(column == value)
    if f.date_from:
        query = query.where(Purchase.purchase_date >= f.date_from)
    if f.date_to:
        query = query.where(Purchase.purchase_date <= f.date_to)
    columns = [
        Column("purchase_date", "Tarih", "date"),
        Column("due_date", "Vade", "date"),
        Column("supplier_name", "Firma"),
        Column("material_name", "Malzeme"),
        Column("lifecycle_label", "Durum"),
        Column("total_kurus", "Sipariş tutarı", "money"),
        Column("received_kurus", "Teslim alınan (gerçek)", "money"),
        Column("commitment_kurus", "Bekleyen taahhüt", "money"),
        Column("warning", "Uyarı"),
        Column("description", "Açıklama"),
    ]
    rows = []
    for purchase, supplier_name, material_name in session.execute(query):
        warnings = quantity_warnings(session, purchase)
        committing = purchase.lifecycle_state in ("planned", "ordered", "partially_received")
        rows.append(
            {
                "purchase_id": purchase.id,
                "purchase_date": iso(purchase.purchase_date),
                "due_date": iso(purchase.due_date),
                "supplier_name": supplier_name,
                "material_name": material_name,
                "lifecycle_state": purchase.lifecycle_state,
                "lifecycle_label": LIFECYCLE_LABELS[purchase.lifecycle_state],
                "total_kurus": purchase.total_kurus,
                "received_kurus": purchase.received_kurus,
                "commitment_kurus": purchase.total_kurus - purchase.received_kurus if committing else 0,
                "warning": "quantity_over_received" if warnings else "",
                "warnings": warnings,
                "description": purchase.description,
            }
        )
    totals = {
        "received_kurus": sum(r["received_kurus"] for r in rows),
        "commitment_kurus": sum(r["commitment_kurus"] for r in rows),
    }
    return ReportTable(
        "purchase-lifecycle", "Satın Alma Raporu (Yaşam Döngüsü)", columns, rows, totals, f.as_dict(),
        notes=[
            "Gerçek maliyet ve borç yalnız 'Teslim alınan' sütunudur; planlı ve siparişli kayıtlar taahhüt olarak ayrı gösterilir.",
            "Sipariş tutarı sütunu toplanmaz.",
        ],
        warnings=[w for r in rows for w in r["warnings"]],
    )


def report_material_usage(session: Session, f: Filters) -> ReportTable:
    """Hangi malzeme hangi projede ne kadar alındı, kullanıldı, fire oldu (miktar bazlı)."""
    query = select(MaterialMovement).where(MaterialMovement.status == RecordStatus.ACTIVE)
    if f.project_id:
        query = query.where(MaterialMovement.project_id == f.project_id)
    if f.material_id:
        query = query.where(MaterialMovement.material_id == f.material_id)
    if f.date_from:
        query = query.where(MaterialMovement.movement_date >= f.date_from)
    if f.date_to:
        query = query.where(MaterialMovement.movement_date <= f.date_to)
    movements = list(session.scalars(query))
    projects = names(session, Project, {m.project_id for m in movements if m.project_id})
    materials = names(session, Material, {m.material_id for m in movements})
    groups: dict[tuple, dict] = {}
    for m in movements:
        unit = (m.unit or "").strip()
        key = (m.project_id, m.material_id, match_key(unit))
        row = groups.setdefault(
            key,
            {
                "project_name": projects.get(m.project_id) if m.project_id else "Projesiz",
                "material_name": materials.get(m.material_id), "unit": unit or None,
                "purchased": Decimal(0), "used": Decimal(0), "waste": Decimal(0), "returned": Decimal(0),
                "adjusted": Decimal(0), "waste_cost_kurus": 0, "untracked": 0,
            },
        )
        quantity = m.quantity
        if quantity is None:
            row["untracked"] += 1  # miktarsız (yalnız tutar) kayıt miktar sütunlarına girmez
            if m.movement_type == MovementType.WASTE and m.amount_kurus:
                row["waste_cost_kurus"] += m.amount_kurus
            continue
        slot = {
            MovementType.PURCHASE: "purchased", MovementType.USE: "used", MovementType.WASTE: "waste",
            MovementType.RETURN: "returned", MovementType.ADJUSTMENT: "adjusted",
        }[m.movement_type]
        row[slot] += quantity
        if m.movement_type == MovementType.WASTE and m.amount_kurus:
            row["waste_cost_kurus"] += m.amount_kurus
    rows = []
    for row in groups.values():
        net = row["purchased"] + row["returned"] + row["adjusted"] - row["used"] - row["waste"]
        rows.append({**{k: (float(v) if isinstance(v, Decimal) else v) for k, v in row.items()}, "net": float(net)})
    rows.sort(key=lambda r: (r["project_name"] or "", r["material_name"] or "", r["unit"] or ""))
    columns = [
        Column("project_name", "Proje"), Column("material_name", "Malzeme"), Column("unit", "Birim"),
        Column("purchased", "Alınan", "number"), Column("used", "Kullanılan", "number"),
        Column("waste", "Fire", "number"), Column("returned", "İade", "number"),
        Column("adjusted", "Sayım düzeltmesi", "number"), Column("net", "Kayıtlara göre kalan", "number"),
        Column("waste_cost_kurus", "Fire maliyeti", "money"),
    ]
    return ReportTable(
        "material-usage", "Malzeme Kullanımı (Projeye Göre)", columns, rows, {}, f.as_dict(),
        notes=[
            (
                "Miktarlar kayıtlı hareketlerden gelir; kesin stok sayımı değildir. 'Kayıtlara göre kalan' "
                "eksiye düşerse kullanım veya sayım kaydı eksik olabilir."
            ),
            "Farklı birimdeki hareketler (örn. kg ve adet) ayrı satırlarda gösterilir, toplanmaz.",
        ],
    )


BUILDERS = {
    "project-profitability": report_project_profitability,
    "budget-variance": report_budget_variance,
    "project-comparison": report_project_comparison,
    "customer-aging": report_customer_aging,
    "supplier-aging": report_supplier_aging,
    "customer-statement": report_customer_statement,
    "supplier-statement": report_supplier_statement,
    "customer-advances": report_customer_advances,
    "cash-forecast-13w": report_cash_forecast,
    "upcoming-schedule": report_upcoming_schedule,
    "staff-balances": report_staff_balances,
    "attendance-overtime-leave": report_attendance_overtime_leave,
    "labor-cost": report_labor_cost,
    "material-price-history": report_material_price_history,
    "waste-rework-cost": report_waste_rework,
    "material-usage": report_material_usage,
    "purchase-lifecycle": report_purchase_lifecycle,
}


def build_report(session: Session, name: str, f: Filters) -> ReportTable:
    return shared_build_report(BUILDERS, session, name, f)


register_report_routes(router, BUILDERS, get_filters)
