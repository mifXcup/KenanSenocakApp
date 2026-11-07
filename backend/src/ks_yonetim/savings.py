"""Açıklanabilir tasarruf / risk fırsatları.

Hiçbiri otomatik işlem yapmaz (sipariş, ödeme, maaş değişikliği yok); her kayıt gerekçe, kaynak kayıt
kimlikleri, veri yeterliliği ve istemci deep-link bilgisi taşır. `estimated_impact_kurus` yalnız gerçekten
hesaplanabilen parasal etkidir; hesaplanamayan türlerde boştur ve ilgili tutar `related_amount_kurus` alanındadır.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import clock
from .api import ApiError, require_sidecar_token
from .customers import advance_split, customer_buckets, effective_rows
from .database import get_session
from .labor_cost import load_settings
from .ml import (
    MIN_PRICE_SAMPLES,
    apply_feedback,
    price_insights,
    supplier_comparisons,
    usable_purchases,
)
from .models import (
    Customer,
    CustomerFinancialMovement,
    Employee,
    ExpenseCategory,
    Material,
    MaterialMovement,
    MovementType,
    Project,
    ProjectChangeOrder,
    ProjectExpense,
    Purchase,
    PurchaseReceipt,
    RecordStatus,
    WorkLog,
)
from .project_finance import collect_cost_sources, compute_profitability
from .textnorm import match_key

router = APIRouter(prefix="/api/v1/analytics", dependencies=[Depends(require_sidecar_token)])

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
LOOKBACK_DAYS = 90
SUPPLIER_SPEND_LOOKBACK_DAYS = 180
MIN_OVERTIME_HOURS = 20
MIN_OVERTIME_RATIO = 0.2
MIN_OVERTIME_LOGS = 10
MAX_SOURCES = 200
CATEGORY_LABELS = {
    "material": "malzeme", "labor": "işçilik", "shipping": "nakliye", "installation": "montaj",
    "subcontractor": "taşeron", "site": "şantiye", "waste_rework": "fire/yeniden işleme", "other": "diğer",
}


def tl(kurus: int) -> str:
    return f"{kurus / 100:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def source(source_type: str, source_id: str, amount_kurus: int | None = None, **extra) -> dict:
    return {"source_type": source_type, "source_id": source_id, "amount_kurus": amount_kurus, **extra}


# saving: ödeme/tedarik tasarrufu · cost_risk: oluşabilecek ek maliyet · receivable: tahsil edilecek tutar
GROUP_OF = {
    "price_anomaly": "saving",
    "cheaper_supplier": "saving",
    "budget_overrun": "cost_risk",
    "overtime_concentration": "cost_risk",
    "rework_increase": "cost_risk",
    "uncollected_change_order": "receivable",
    "unlinked_customer_advance": "receivable",
    "unlinked_expense": "record_quality",
}


def opportunity(
    kind: str,
    key: str,
    severity: str,
    title: str,
    reason: str,
    *,
    impact: int | None,
    related: int | None = None,
    samples: int,
    minimum: int,
    sources: list[dict],
    entity: str,
    entity_id: str,
    project_id: str | None = None,
    extra: dict | None = None,
) -> dict:
    sufficient = samples >= minimum
    return {
        "opportunity_id": f"{kind}:{key}",
        "type": kind,
        "severity": severity,
        "title": title,
        "reason": reason,
        "estimated_impact_kurus": impact,
        "related_amount_kurus": related,
        "confidence": "high" if sufficient and samples >= 2 * minimum else "medium" if sufficient else "low",
        "data_sufficiency": {"sample_count": samples, "minimum_samples": minimum, "sufficient": sufficient},
        "sources": sources[:MAX_SOURCES],
        "sources_truncated": len(sources) > MAX_SOURCES,
        "deep_link": {"entity": entity, "entity_id": entity_id, "project_id": project_id},
        "project_id": project_id,
        **(extra or {}),
    }


def severity_by_share(share: float, high: float, medium: float) -> str:
    return "high" if share >= high else "medium" if share >= medium else "low"


# --- Türler ---------------------------------------------------------------------------------------------


def budget_overruns(session: Session, projects: list[Project]) -> list[dict]:
    found = []
    for project in projects:
        profit = compute_profitability(session, project)
        sources = collect_cost_sources(session, project)
        for category in profit["categories"]:
            variance = category["variance_kurus"]
            if variance is None or variance >= 0:
                continue
            over, budget = -variance, category["budget_kurus"]
            name = category["category"]
            lines = [source("project_budget_line", line_id) for line_id in category["budget_line_ids"]]
            costs = [
                source(item["source_type"], item["source_id"], item["amount_kurus"], role=role)
                for role in ("actual", "commitment")
                for item in sources[name][role]
            ]
            found.append(
                opportunity(
                    "budget_overrun", f"{project.id}:{name}",
                    severity_by_share(over / budget if budget else 1, 0.2, 0.05),
                    f"{project.name}: {CATEGORY_LABELS[name]} bütçe aşımı",
                    (
                        f"{project.name} projesinde {CATEGORY_LABELS[name]} kategorisinin tahmini bitiş maliyeti "
                        f"{tl(category['forecast_kurus'])}; bütçe {tl(budget)} olduğundan {tl(over)} aşım bekleniyor "
                        f"(gerçekleşen {tl(category['actual_kurus'])}, taahhüt {tl(category['commitment_kurus'])}, "
                        f"kalan tahmin {tl(category['remaining_estimate_kurus'])}, kaynak: "
                        f"{'yönetici tahmini' if category['forecast_source'] == 'manual' else 'otomatik'})."
                    ),
                    impact=over, samples=len(costs), minimum=1, sources=lines + costs,
                    entity="project", entity_id=project.id, project_id=project.id,
                    extra={"category": name, "forecast_source": category["forecast_source"]},
                )
            )
    return found


def price_anomalies(session: Session, as_of: date | None = None) -> list[dict]:
    rows, _ = price_insights(session, as_of)
    apply_feedback(session, rows, [], [])
    found = []
    for row in rows:
        if not row.is_anomaly or row.latest_unit_price_kurus <= row.expected_unit_price_kurus:
            continue
        if row.dismissed:  # kullanıcı "yanlış/faydasız" dedi; yeni veri gelene kadar fırsat sayılmaz
            continue
        latest = session.execute(
            select(Purchase)
            .join(Material, Material.id == Purchase.material_id)
            .where(*usable_purchases(), Purchase.material_id == row.material_id,
                   Purchase.quantity.is_not(None), Purchase.purchase_date == row.latest_date)
            .order_by(Purchase.created_at.desc())
        ).scalars().first()
        quantity = Decimal(latest.quantity) if latest and latest.quantity else None
        gap = row.latest_unit_price_kurus - row.expected_unit_price_kurus
        impact = int((Decimal(gap) * quantity).quantize(Decimal(1))) if quantity else None
        found.append(
            opportunity(
                "price_anomaly", f"{row.material_id}:{match_key(row.unit)}",
                "high" if row.anomaly_score >= 5 else "medium",
                f"{row.material_name}: beklenenden pahalı alım",
                (
                    f"{row.material_name} ({row.unit}) son birim fiyatı {tl(row.latest_unit_price_kurus)}; "
                    f"önceki {row.sample_count - 1} alımdan beklenen {tl(row.expected_unit_price_kurus)} "
                    f"(sapma %{row.deviation_percent}, anomali skoru {row.anomaly_score}). "
                    + (f"Son alım miktarı {quantity} olduğundan fazla ödeme {tl(impact)}." if impact is not None
                       else "Son alım miktarı bilinmediği için parasal etki hesaplanamadı.")
                ),
                impact=impact, samples=row.sample_count, minimum=MIN_PRICE_SAMPLES,
                sources=[source("purchase", latest.id, latest.total_kurus)] if latest else [],
                entity="purchase" if latest else "material", entity_id=latest.id if latest else row.material_id,
                project_id=latest.project_id if latest else None,
                extra={"material_id": row.material_id, "unit": row.unit},
            )
        )
    return found


def cheaper_suppliers(session: Session, as_of: date) -> list[dict]:
    rows, _ = supplier_comparisons(session, as_of)
    found = []
    since = as_of - timedelta(days=SUPPLIER_SPEND_LOOKBACK_DAYS)
    for row in rows:
        if not row["comparable"]:
            continue
        unit_key = match_key(row["unit"])
        spend, sources = 0, []
        for receipt, purchase in session.execute(
            select(PurchaseReceipt, Purchase)
            .join(Purchase, Purchase.id == PurchaseReceipt.purchase_id)
            .join(Material, Material.id == Purchase.material_id)
            .where(*usable_purchases(), PurchaseReceipt.status == RecordStatus.ACTIVE,
                   Purchase.material_id == row["material_id"],
                   Purchase.supplier_id != row["cheapest_supplier_id"],
                   PurchaseReceipt.receipt_date >= since, PurchaseReceipt.receipt_date <= as_of)
        ):
            if match_key(purchase.unit or "") == unit_key:
                spend += receipt.amount_kurus
                sources.append(source("purchase_receipt", receipt.id, receipt.amount_kurus, purchase_id=purchase.id))
        percent = row["saving_percent"]
        impact = int(Decimal(spend) * Decimal(str(percent)) / 100) if spend else None
        found.append(
            opportunity(
                "cheaper_supplier", f"{row['material_id']}:{unit_key}",
                severity_by_share(percent / 100, 0.15, 0.07),
                f"{row['material_name']}: daha uygun tedarikçi",
                (
                    f"{row['material_name']} ({row['unit']}) için {row['cheapest_supplier_name']}, tarih etkisi "
                    f"arındırılmış ortalamada %{percent} daha ucuz. Son {SUPPLIER_SPEND_LOOKBACK_DAYS} günde diğer "
                    f"tedarikçilerden {tl(spend)} alım yapıldı; aynı fark uygulansaydı yaklaşık "
                    f"{tl(impact) if impact is not None else '—'} tasarruf olurdu. Karşılaştırma yalnız geçmiş fiyatlara dayanır."
                ),
                impact=impact, samples=row["sample_count"], minimum=4, sources=sources,
                entity="material", entity_id=row["material_id"],
                extra={"cheapest_supplier_id": row["cheapest_supplier_id"], "saving_percent": percent},
            )
        )
    return found


def overtime_concentration(session: Session, as_of: date) -> list[dict]:
    since = as_of - timedelta(days=LOOKBACK_DAYS - 1)
    multiplier = Decimal(load_settings(session).overtime_multiplier_percent) / 100
    groups: dict[str, list[WorkLog]] = defaultdict(list)
    for log in session.scalars(
        select(WorkLog).where(WorkLog.status == RecordStatus.ACTIVE, WorkLog.work_date >= since, WorkLog.work_date <= as_of)
    ):
        groups[log.employee_id].append(log)
    people = dict(session.execute(select(Employee.id, Employee.name).where(Employee.id.in_(list(groups) or [""]))).all())
    found = []
    for employee_id, logs in groups.items():
        normal = sum((Decimal(l.normal_hours) for l in logs), Decimal(0))
        overtime = sum((Decimal(l.overtime_hours) for l in logs), Decimal(0))
        ratio = float(overtime / (normal + overtime)) if normal + overtime else 0.0
        if overtime < MIN_OVERTIME_HOURS or ratio < MIN_OVERTIME_RATIO:
            continue
        premium = Decimal(0)
        for log in logs:
            if log.overtime_hours and log.manual_amount_kurus is None and (Decimal(log.normal_hours) + multiplier * Decimal(log.overtime_hours)) > 0:
                premium += Decimal(log.amount_kurus) * Decimal(log.overtime_hours) * (multiplier - 1) / (
                    Decimal(log.normal_hours) + multiplier * Decimal(log.overtime_hours)
                )
        impact = int(premium.quantize(Decimal(1)))
        found.append(
            opportunity(
                "overtime_concentration", employee_id,
                "high" if ratio >= 0.35 else "medium",
                f"{people.get(employee_id, '')}: fazla mesai yoğunluğu",
                (
                    f"{people.get(employee_id, '')} son {LOOKBACK_DAYS} günde {overtime} saat fazla mesai yaptı "
                    f"(toplam çalışmanın %{round(ratio * 100, 1)}'i). Fazla mesai primi payı yaklaşık {tl(impact)}; "
                    "vardiya veya iş dağılımı gözden geçirilebilir."
                ),
                impact=impact, samples=len(logs), minimum=MIN_OVERTIME_LOGS,
                sources=[source("work_log", l.id, l.amount_kurus) for l in logs if l.overtime_hours],
                entity="employee", entity_id=employee_id,
                extra={"overtime_hours": str(overtime), "overtime_ratio_percent": round(ratio * 100, 2)},
            )
        )
    return found


def rework_increases(session: Session, projects: list[Project], as_of: date) -> list[dict]:
    recent_start = as_of - timedelta(days=LOOKBACK_DAYS - 1)
    prior_start = recent_start - timedelta(days=LOOKBACK_DAYS)
    found = []
    for project in projects:
        recent: list[dict] = []
        prior_total = 0
        prior_count = 0
        for expense in session.scalars(
            select(ProjectExpense).where(
                ProjectExpense.project_id == project.id, ProjectExpense.status == RecordStatus.ACTIVE,
                ProjectExpense.category == ExpenseCategory.REWORK, ProjectExpense.expense_date >= prior_start,
                ProjectExpense.expense_date <= as_of)
        ):
            if expense.expense_date >= recent_start:
                recent.append(source("project_expense", expense.id, expense.amount_kurus))
            else:
                prior_total += expense.amount_kurus
                prior_count += 1
        for movement in session.scalars(
            select(MaterialMovement).where(
                MaterialMovement.project_id == project.id, MaterialMovement.status == RecordStatus.ACTIVE,
                MaterialMovement.movement_type == MovementType.WASTE, MaterialMovement.amount_kurus.is_not(None),
                MaterialMovement.movement_date >= prior_start, MaterialMovement.movement_date <= as_of)
        ):
            if movement.movement_date >= recent_start:
                recent.append(source("material_movement", movement.id, movement.amount_kurus))
            else:
                prior_total += movement.amount_kurus
                prior_count += 1
        recent_total = sum(s["amount_kurus"] for s in recent)
        if recent_total <= 0 or recent_total < prior_total * 1.5:
            continue
        increase = recent_total - prior_total
        cost = compute_profitability(session, project)["actual_cost_kurus"] or 0
        share = recent_total / cost if cost else 1.0
        found.append(
            opportunity(
                "rework_increase", project.id, severity_by_share(share, 0.10, 0.03),
                f"{project.name}: fire / yeniden işleme artışı",
                (
                    f"{project.name} projesinde son {LOOKBACK_DAYS} günde fire ve yeniden işleme maliyeti "
                    f"{tl(recent_total)}; önceki {LOOKBACK_DAYS} günde {tl(prior_total)} idi "
                    f"({tl(increase)} artış, gerçekleşen maliyetin %{round(share * 100, 1)}'i)."
                ),
                impact=increase, samples=len(recent) + prior_count, minimum=2, sources=recent,
                entity="project", entity_id=project.id, project_id=project.id,
                extra={"recent_kurus": recent_total, "prior_kurus": prior_total},
            )
        )
    return found


def unlinked_expenses(session: Session) -> list[dict]:
    found = []
    purchases = list(
        session.scalars(
            select(Purchase).join(Material, Material.id == Purchase.material_id).where(
                *usable_purchases(), Purchase.project_id.is_(None), Purchase.received_kurus > 0
            )
        )
    )
    total_received = int(
        sum(p.received_kurus for p in session.scalars(select(Purchase).join(Material, Material.id == Purchase.material_id).where(*usable_purchases(), Purchase.received_kurus > 0)))
    )
    amount = sum(p.received_kurus for p in purchases)
    if amount > 0:
        share = amount / total_received if total_received else 1
        found.append(
            opportunity(
                "unlinked_expense", "purchases", severity_by_share(share, 0.25, 0.10),
                "Projeye bağlanmamış satın almalar",
                f"{len(purchases)} teslim alınmış satın alma ({tl(amount)}) hiçbir projeye bağlı değil; toplam alımın "
                f"%{round(share * 100, 1)}'i proje kârlılığına yansımıyor. Doğru projeye bağlayın.",
                impact=None, related=amount, samples=len(purchases), minimum=1,
                sources=[source("purchase", p.id, p.received_kurus) for p in purchases],
                entity="purchase", entity_id=purchases[0].id,
            )
        )
    logs = list(
        session.scalars(
            select(WorkLog).where(
                WorkLog.status == RecordStatus.ACTIVE, WorkLog.project_id.is_(None), WorkLog.source == "manual",
                WorkLog.amount_kurus > 0,
            )
        )
    )
    labor_total = int(sum(l.amount_kurus for l in session.scalars(select(WorkLog).where(WorkLog.status == RecordStatus.ACTIVE, WorkLog.amount_kurus > 0))))
    labor_amount = sum(l.amount_kurus for l in logs)
    if labor_amount > 0:
        share = labor_amount / labor_total if labor_total else 1
        found.append(
            opportunity(
                "unlinked_expense", "labor", severity_by_share(share, 0.25, 0.10),
                "Projeye bağlanmamış işçilik",
                f"{len(logs)} puantaj kaydındaki {tl(labor_amount)} işçilik maliyeti hiçbir projeye bağlı değil "
                f"(toplam işçiliğin %{round(share * 100, 1)}'i).",
                impact=None, related=labor_amount, samples=len(logs), minimum=1,
                sources=[source("work_log", l.id, l.amount_kurus) for l in logs],
                entity="work_log", entity_id=logs[0].id,
            )
        )
    return found


def uncollected_change_orders(session: Session, projects: list[Project], as_of: date) -> list[dict]:
    found = []
    ids = {p.id: p for p in projects}
    orders = session.scalars(
        select(ProjectChangeOrder).where(
            ProjectChangeOrder.project_id.in_(list(ids) or [""]),
            ProjectChangeOrder.change_state == "approved", ProjectChangeOrder.status == RecordStatus.ACTIVE,
            ProjectChangeOrder.amount_kurus > 0,
        )
    )
    for order in orders:
        project = ids[order.project_id]
        accruals = list(
            session.scalars(
                select(CustomerFinancialMovement).where(
                    CustomerFinancialMovement.change_order_id == order.id,
                    CustomerFinancialMovement.status == RecordStatus.ACTIVE,
                    CustomerFinancialMovement.movement_type == "accrual",
                )
            )
        )
        live = [a for a in effective_rows(accruals)]
        billed = sum(a.amount_kurus for a in live)
        open_amount = order.amount_kurus - min(billed, order.amount_kurus)
        if open_amount <= 0:
            continue
        age = (as_of - order.decided_at.date()).days if order.decided_at else 0
        found.append(
            opportunity(
                "uncollected_change_order", order.id,
                "high" if age > 30 else "medium" if age > 14 else "low",
                f"{project.name}: tahsil edilmemiş onaylı ek iş",
                (
                    f"'{order.title}' ek işi onaylandı ({tl(order.amount_kurus)}) ancak müşteriye yalnız {tl(billed)} "
                    f"tahakkuk ettirildi; {tl(open_amount)} henüz tahsil edilebilir alacak olarak kaydedilmedi "
                    f"(onaydan {age} gün geçti)."
                ),
                impact=open_amount, samples=1 + len(live), minimum=1,
                sources=[source("project_change_order", order.id, order.amount_kurus)]
                + [source("customer_movement", a.id, a.amount_kurus) for a in live],
                entity="project_change_order", entity_id=order.id, project_id=project.id,
            )
        )
    return found


def unlinked_advances(session: Session, as_of: date) -> list[dict]:
    found = []
    for customer in session.scalars(select(Customer).order_by(Customer.name)):
        buckets = customer_buckets(session, customer.id, as_of)
        unlinked = advance_split(buckets)["unlinked_advance_kurus"]
        if unlinked <= 0:
            continue
        collections = [
            r
            for r in effective_rows(
                list(
                    session.scalars(
                        select(CustomerFinancialMovement).where(
                            CustomerFinancialMovement.customer_id == customer.id,
                            CustomerFinancialMovement.status == RecordStatus.ACTIVE,
                            CustomerFinancialMovement.movement_type == "collection",
                            CustomerFinancialMovement.project_id.is_(None),
                            CustomerFinancialMovement.movement_date <= as_of,
                        )
                    )
                )
            )
        ]
        collected = sum(b["collected_kurus"] for b in buckets.values())
        share = unlinked / collected if collected else 1
        found.append(
            opportunity(
                "unlinked_customer_advance", customer.id, severity_by_share(share, 0.5, 0.2),
                f"{customer.name}: bağlantısız müşteri avansı",
                (
                    f"{customer.name} için projeye bağlanmamış ve plana dağıtılmamış {tl(unlinked)} avans var. "
                    "Bu tutar hiçbir projenin tahsilatına sayılmıyor; tahsilatı projeye bağlayın veya alacak planına dağıtın."
                ),
                impact=None, related=unlinked, samples=max(len(collections), 1), minimum=1,
                sources=[source("customer", customer.id, unlinked)]
                + [source("customer_movement", c.id, c.amount_kurus) for c in collections],
                entity="customer", entity_id=customer.id,
            )
        )
    return found


@router.get("/savings")
def savings_opportunities(
    as_of: date | None = None,
    project_id: str | None = Query(default=None, max_length=36),
    min_severity: Literal["low", "medium", "high"] = "low",
    session: Session = Depends(get_session),
):
    day = as_of or clock.business_today()
    query = select(Project).where(Project.status == RecordStatus.ACTIVE)
    if project_id:
        query = query.where(Project.id == project_id)
    projects = list(session.scalars(query.order_by(Project.name, Project.id)))
    if project_id and not projects:
        raise ApiError("not_found", "Proje bulunamadı.", 404)
    items = budget_overruns(session, projects) + rework_increases(session, projects, day)
    items += uncollected_change_orders(session, projects, day)
    if not project_id:
        items += price_anomalies(session, day) + cheaper_suppliers(session, day)
        items += overtime_concentration(session, day) + unlinked_expenses(session)
        items += unlinked_advances(session, day)
    limit = SEVERITY_ORDER[min_severity]
    items = [i for i in items if SEVERITY_ORDER[i["severity"]] <= limit]
    items.sort(key=lambda i: (SEVERITY_ORDER[i["severity"]], -(i["estimated_impact_kurus"] or 0), i["opportunity_id"]))
    by_type: dict[str, dict] = {}
    for item in items:
        slot = by_type.setdefault(item["type"], {"count": 0, "estimated_impact_kurus": 0})
        slot["count"] += 1
        slot["estimated_impact_kurus"] += item["estimated_impact_kurus"] or 0
    by_group: dict[str, dict] = {}
    for item in items:
        slot = by_group.setdefault(GROUP_OF.get(item["type"], "record_quality"), {"count": 0, "estimated_impact_kurus": 0})
        slot["count"] += 1
        slot["estimated_impact_kurus"] += item["estimated_impact_kurus"] or 0
    return {
        "as_of": day,
        "read_only": True,
        "automatic_actions": [],
        "count": len(items),
        "total_estimated_impact_kurus": sum(i["estimated_impact_kurus"] or 0 for i in items),
        "by_type": by_type,
        # Toplam farklı nitelikte kalemleri karıştırır; gerçek tasarruf, maliyet riski ve alacak ayrı okunmalı.
        "by_group": by_group,
        "by_severity": {s: sum(1 for i in items if i["severity"] == s) for s in SEVERITY_ORDER},
        "opportunities": items,
    }
