from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import clock
from .api import ApiError, add_audit, require_active, require_sidecar_token
from .database import get_session
from .ml import usable_purchases
from .models import (
    Material,
    PricingIndexEntry,
    PricingSuggestion,
    ProductCostFactor,
    Project,
    ProjectProduct,
    Purchase,
    RecordStatus,
)
from .textnorm import match_key

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_sidecar_token)])
MODEL_VERSION = "1.0"
# Öneride yalnız gerçek teklif geçmişi kullanılır: taslak ve reddedilmiş kayıtlar dışarıda.
USABLE_PRICING_STATES = ("offered", "accepted", "completed")
STALE_PRICE_DAYS = 180
_CONFIDENCE_ORDER = ("low", "medium", "high")


def _lower_confidence(level: str) -> str:
    return _CONFIDENCE_ORDER[max(0, _CONFIDENCE_ORDER.index(level) - 1)]


def _cap_confidence(level: str, ceiling: str) -> str:
    return _CONFIDENCE_ORDER[min(_CONFIDENCE_ORDER.index(level), _CONFIDENCE_ORDER.index(ceiling))]


class CostFactorInput(BaseModel):
    factor_key: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9_-]+$")
    label: str = Field(min_length=2, max_length=120)
    material_id: str | None = None
    share_percent: Decimal = Field(gt=0, le=100, decimal_places=2)
    reference_unit_price_kurus: int = Field(gt=0)
    reference_date: date
    source: Literal["manual", "purchase"] = "manual"


class ProjectProductCreate(BaseModel):
    product_type: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=280)
    quantity: Decimal = Field(gt=0, decimal_places=3)
    unit: str = Field(min_length=1, max_length=24)
    finish: str | None = Field(default=None, max_length=120)
    hardware_level: str | None = Field(default=None, max_length=80)
    complexity_percent: int = Field(default=100, ge=50, le=200)
    quote_date: date
    quoted_total_kurus: int | None = Field(default=None, ge=0)
    accepted_total_kurus: int | None = Field(default=None, ge=0)
    actual_cost_kurus: int | None = Field(default=None, ge=0)
    target_margin_percent: Decimal = Field(default=Decimal(25), ge=0, lt=95)
    pricing_state: Literal["draft", "offered", "accepted", "rejected", "completed"] = "draft"
    note: str | None = Field(default=None, max_length=2000)
    factors: list[CostFactorInput] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_factors(self):
        keys = [factor.factor_key for factor in self.factors]
        if len(keys) != len(set(keys)):
            raise ValueError("Aynı maliyet etkisi bir ürüne iki kez eklenemez.")
        if sum((factor.share_percent for factor in self.factors), Decimal(0)) > 100:
            raise ValueError("Maliyet etkilerinin toplam payı yüzde 100'ü aşamaz.")
        return self


class ProjectProductUpdate(BaseModel):
    product_type: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=280)
    quantity: Decimal | None = Field(default=None, gt=0, decimal_places=3)
    unit: str | None = Field(default=None, min_length=1, max_length=24)
    finish: str | None = Field(default=None, max_length=120)
    hardware_level: str | None = Field(default=None, max_length=80)
    complexity_percent: int | None = Field(default=None, ge=50, le=200)
    quote_date: date | None = None
    quoted_total_kurus: int | None = Field(default=None, ge=0)
    accepted_total_kurus: int | None = Field(default=None, ge=0)
    actual_cost_kurus: int | None = Field(default=None, ge=0)
    target_margin_percent: Decimal | None = Field(default=None, ge=0, lt=95)
    pricing_state: Literal["draft", "offered", "accepted", "rejected", "completed"] | None = None
    note: str | None = Field(default=None, max_length=2000)
    factors: list[CostFactorInput] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set:
            raise ValueError("En az bir alan gönderilmelidir.")
        if self.factors is not None:
            keys = [factor.factor_key for factor in self.factors]
            if len(keys) != len(set(keys)):
                raise ValueError("Aynı maliyet etkisi bir ürüne iki kez eklenemez.")
            if sum((factor.share_percent for factor in self.factors), Decimal(0)) > 100:
                raise ValueError("Maliyet etkilerinin toplam payı yüzde 100'ü aşamaz.")
        return self


class PricingIndexCreate(BaseModel):
    factor_key: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9_-]+$")
    label: str = Field(min_length=2, max_length=120)
    material_id: str | None = None
    recorded_on: date
    unit_price_kurus: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=280)


def _factor_dict(factor: ProductCostFactor) -> dict:
    return {
        "id": factor.id,
        "factor_key": factor.factor_key,
        "label": factor.label,
        "material_id": factor.material_id,
        "share_percent": float(factor.share_percent),
        "reference_unit_price_kurus": factor.reference_unit_price_kurus,
        "reference_date": factor.reference_date,
        "source": factor.source,
    }


def _factors(session: Session, product_id: str) -> list[ProductCostFactor]:
    return list(
        session.scalars(
            select(ProductCostFactor)
            .where(ProductCostFactor.project_product_id == product_id)
            .order_by(ProductCostFactor.factor_key)
        )
    )


def _suggestion_dict(row: PricingSuggestion | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "suggested_low_kurus": row.suggested_low_kurus,
        "suggested_mid_kurus": row.suggested_mid_kurus,
        "suggested_high_kurus": row.suggested_high_kurus,
        "confidence": row.confidence,
        "comparable_count": row.comparable_count,
        "explanation": row.explanation,
        "model_version": row.model_version,
        "created_at": row.created_at,
    }


def _product_dict(session: Session, product: ProjectProduct) -> dict:
    latest = session.scalar(
        select(PricingSuggestion)
        .where(PricingSuggestion.project_product_id == product.id)
        .order_by(PricingSuggestion.created_at.desc(), PricingSuggestion.id.desc())
    )
    return {
        "id": product.id,
        "project_id": product.project_id,
        "product_type": product.product_type,
        "description": product.description,
        "quantity": float(product.quantity),
        "unit": product.unit,
        "finish": product.finish,
        "hardware_level": product.hardware_level,
        "complexity_percent": product.complexity_percent,
        "quote_date": product.quote_date,
        "quoted_total_kurus": product.quoted_total_kurus,
        "accepted_total_kurus": product.accepted_total_kurus,
        "actual_cost_kurus": product.actual_cost_kurus,
        "target_margin_percent": float(product.target_margin_percent),
        "pricing_state": product.pricing_state,
        "note": product.note,
        "factors": [_factor_dict(factor) for factor in _factors(session, product.id)],
        "latest_suggestion": _suggestion_dict(latest),
        "created_at": product.created_at,
        "updated_at": product.updated_at,
    }


def _replace_factors(
    session: Session, product: ProjectProduct, factors: list[CostFactorInput]
) -> None:
    existing = _factors(session, product.id)
    for factor in existing:
        session.delete(factor)
    session.flush()
    for payload in factors:
        if payload.material_id:
            require_active(session, Material, payload.material_id, "Malzeme")
        session.add(ProductCostFactor(project_product_id=product.id, **payload.model_dump()))


@router.get("/projects/{project_id}/products")
def list_project_products(project_id: str, session: Session = Depends(get_session)):
    require_active(session, Project, project_id, "Proje")
    rows = session.scalars(
        select(ProjectProduct)
        .where(
            ProjectProduct.project_id == project_id,
            ProjectProduct.status == RecordStatus.ACTIVE,
        )
        .order_by(ProjectProduct.quote_date.desc(), ProjectProduct.created_at.desc())
    ).all()
    return [_product_dict(session, row) for row in rows]


@router.post("/projects/{project_id}/products", status_code=201)
def create_project_product(
    project_id: str, payload: ProjectProductCreate, session: Session = Depends(get_session)
):
    require_active(session, Project, project_id, "Proje")
    values = payload.model_dump(exclude={"factors"})
    product = ProjectProduct(project_id=project_id, **values)
    session.add(product)
    session.flush()
    _replace_factors(session, product, payload.factors)
    add_audit(
        session,
        "project_product",
        product.id,
        "created",
        {"project_id": project_id, "product_type": product.product_type},
    )
    session.commit()
    session.refresh(product)
    return _product_dict(session, product)


@router.patch("/project-products/{product_id}")
def update_project_product(
    product_id: str, payload: ProjectProductUpdate, session: Session = Depends(get_session)
):
    product = require_active(session, ProjectProduct, product_id, "Ürün")
    values = payload.model_dump(exclude_unset=True, exclude={"factors"})
    for field, value in values.items():
        setattr(product, field, value)
    if "factors" in payload.model_fields_set:
        _replace_factors(session, product, payload.factors or [])
    add_audit(session, "project_product", product.id, "updated", {"fields": sorted(values)})
    session.commit()
    session.refresh(product)
    return _product_dict(session, product)


@router.delete("/project-products/{product_id}", status_code=204)
def delete_project_product(product_id: str, session: Session = Depends(get_session)):
    product = require_active(session, ProjectProduct, product_id, "Ürün")
    product.status = RecordStatus.ARCHIVED
    add_audit(session, "project_product", product.id, "deleted", {"project_id": product.project_id})
    session.commit()


@router.post("/pricing/indices", status_code=201)
def create_pricing_index(payload: PricingIndexCreate, session: Session = Depends(get_session)):
    if payload.material_id:
        require_active(session, Material, payload.material_id, "Malzeme")
    row = PricingIndexEntry(**payload.model_dump(), source="manual")
    session.add(row)
    session.flush()
    add_audit(session, "pricing_index_entry", row.id, "created", payload.model_dump(mode="json"))
    session.commit()
    session.refresh(row)
    return row


def _purchase_unit_price(purchase: Purchase) -> int | None:
    if purchase.unit_price_kurus is not None:
        return purchase.unit_price_kurus
    if purchase.quantity and purchase.quantity > 0:
        return int((Decimal(purchase.total_kurus) / purchase.quantity).quantize(Decimal(1)))
    return None


def _current_factor_price(
    session: Session, factor: ProductCostFactor, as_of: date
) -> tuple[int, str, date] | None:
    if factor.material_id:
        purchases = session.scalars(
            select(Purchase)
            .join(Material, Material.id == Purchase.material_id)
            .where(
                # Yalnız teslim alınmış, açılış bakiyesi olmayan alımlar "güncel fiyat" sayılır.
                *usable_purchases(),
                Purchase.material_id == factor.material_id,
                Purchase.purchase_date <= as_of,
                Purchase.quantity.is_not(None),
                Purchase.quantity > 0,
                Purchase.unit.is_not(None),
            )
            .order_by(Purchase.purchase_date.desc(), Purchase.created_at.desc())
        ).all()
        # Referans fiyatın birimiyle karşılaştır: referans tarihine en yakın alımın birimi esas alınır,
        # başka birimdeki (örn. kg) alımlar levha fiyatını bozmasın.
        if purchases:
            anchor = min(
                purchases,
                key=lambda p: (abs((p.purchase_date - factor.reference_date).days), p.purchase_date),
            )
            wanted = match_key(anchor.unit)
            purchases = [p for p in purchases if match_key(p.unit) == wanted]
        for purchase in purchases:
            price = _purchase_unit_price(purchase)
            if price and price > 0:
                return price, "purchase", purchase.purchase_date

    query = select(PricingIndexEntry).where(
        PricingIndexEntry.status == RecordStatus.ACTIVE,
        PricingIndexEntry.recorded_on <= as_of,
        PricingIndexEntry.factor_key == factor.factor_key,
    )
    if factor.material_id:
        query = query.where(PricingIndexEntry.material_id == factor.material_id)
    row = session.scalar(
        query.order_by(PricingIndexEntry.recorded_on.desc(), PricingIndexEntry.created_at.desc())
    )
    if row:
        return row.unit_price_kurus, row.source, row.recorded_on
    return None


def _normalized_comparable(
    session: Session, target: ProjectProduct, candidate: ProjectProduct, as_of: date
) -> dict:
    sale_price = candidate.accepted_total_kurus or candidate.quoted_total_kurus
    assert sale_price is not None
    using_actual_cost = bool(candidate.actual_cost_kurus and candidate.actual_cost_kurus > 0)
    base = candidate.actual_cost_kurus if using_actual_cost else sale_price
    factors = _factors(session, candidate.id)
    factor_share = Decimal(0)
    factor_multiplier = Decimal(0)
    details = []
    for factor in factors:
        share = Decimal(factor.share_percent)
        factor_share += share
        current = _current_factor_price(session, factor, as_of)
        current_price, source, current_date = (
            current
            if current is not None
            else (factor.reference_unit_price_kurus, "reference_fallback", factor.reference_date)
        )
        ratio = Decimal(current_price) / Decimal(factor.reference_unit_price_kurus)
        factor_multiplier += (share / Decimal(100)) * ratio
        details.append(
            {
                "factor_key": factor.factor_key,
                "label": factor.label,
                "share_percent": float(share),
                "reference_unit_price_kurus": factor.reference_unit_price_kurus,
                "current_unit_price_kurus": current_price,
                "change_percent": round(float((ratio - 1) * 100), 2),
                "current_source": source,
                "current_date": current_date.isoformat(),
            }
        )
    multiplier = ((Decimal(100) - factor_share) / Decimal(100)) + factor_multiplier
    quantity_ratio = Decimal(target.quantity) / Decimal(candidate.quantity)
    complexity_ratio = Decimal(target.complexity_percent) / Decimal(candidate.complexity_percent)
    normalized_cost = Decimal(base) * multiplier * quantity_ratio * complexity_ratio
    if using_actual_cost:
        # Hedef marj SATIŞ FİYATI üzerindendir: fiyat = maliyet / (1 − marj). (Eskiden maliyete eklenen
        # yüzde olarak hesaplanıyordu; %25 "marj" gerçekte %20 marja denk geliyordu.)
        margin = min(Decimal(target.target_margin_percent), Decimal(94))
        normalized = normalized_cost / (Decimal(1) - margin / Decimal(100))
    else:
        normalized = normalized_cost
    return {
        "product_id": candidate.id,
        "project_id": candidate.project_id,
        "quote_date": candidate.quote_date.isoformat(),
        "quantity": float(candidate.quantity),
        "unit": candidate.unit,
        "base_price_kurus": sale_price,
        "used_actual_cost": using_actual_cost,
        "normalized_price_kurus": int(normalized.quantize(Decimal(1), ROUND_HALF_UP)),
        "quantity_ratio": round(float(quantity_ratio), 4),
        "complexity_ratio": round(float(complexity_ratio), 4),
        "cost_factor_multiplier": round(float(multiplier), 6),
        "factors": details,
    }


@router.post("/project-products/{product_id}/suggestions", status_code=201)
def create_pricing_suggestion(
    product_id: str,
    as_of: date | None = Query(default=None),
    session: Session = Depends(get_session),
):
    target = require_active(session, ProjectProduct, product_id, "Ürün")
    effective_date = as_of or clock.business_today()
    candidates = [
        row
        for row in session.scalars(
            select(ProjectProduct).where(
                ProjectProduct.status == RecordStatus.ACTIVE,
                ProjectProduct.id != target.id,
            )
        )
        if match_key(row.product_type) == match_key(target.product_type)
        and match_key(row.unit) == match_key(target.unit)
        and (row.accepted_total_kurus or row.quoted_total_kurus)
        # Gelecek tarihli, taslak ve reddedilmiş teklifler öneriyi kaydırmasın.
        and row.quote_date <= effective_date
        and row.pricing_state in USABLE_PRICING_STATES
    ]
    if not candidates:
        raise ApiError(
            "pricing_history_insufficient",
            "Bu ürün türü ve birimi için fiyatı bulunan, taslak/reddedilmemiş ve tarihi gelecekte olmayan geçmiş bir ürün kaydı gerekiyor.",
            409,
            {"product_type": target.product_type, "unit": target.unit},
        )
    comparables = [
        _normalized_comparable(session, target, candidate, effective_date)
        for candidate in candidates
    ]
    values = sorted(item["normalized_price_kurus"] for item in comparables)
    mid = int(Decimal(str(median(values))).quantize(Decimal(1), ROUND_HALF_UP))
    deviations = [abs(value - mid) / mid for value in values] if mid else [0]
    model_spread = min(0.25, max(0.08, (sum(deviations) / len(deviations)) + 0.05))
    low = round(mid * (1 - model_spread))
    high = round(mid * (1 + model_spread))
    # Aralık, benzer kayıtların gerçek dağılımını kapsar: veriler 10M ile 90M arasındaysa öneri dar görünmez.
    if len(values) >= 2:
        low = min(low, values[0])
        high = max(high, values[-1])
    spread = ((high - low) / 2 / mid) if mid else model_spread
    dispersion_ratio = (values[-1] / values[0]) if values[0] > 0 else None
    actual_count = sum(bool(item["used_actual_cost"]) for item in comparables)
    factor_count = sum(bool(item["factors"]) for item in comparables)
    if len(comparables) >= 6 and actual_count >= 3 and factor_count >= 3:
        confidence = "high"
    elif len(comparables) >= 3 and factor_count >= 1:
        confidence = "medium"
    else:
        confidence = "low"

    all_factors = [factor for item in comparables for factor in item["factors"]]
    total_share = sum(factor["share_percent"] for factor in all_factors)
    fallback_share = sum(
        factor["share_percent"] for factor in all_factors if factor["current_source"] == "reference_fallback"
    )
    fallback_heavy = total_share > 0 and fallback_share / total_share >= 0.5
    stale_cutoff = effective_date - timedelta(days=STALE_PRICE_DAYS)
    stale_factors = [
        factor for factor in all_factors
        if factor["current_source"] != "reference_fallback" and date.fromisoformat(factor["current_date"]) < stale_cutoff
    ]
    extreme_quantity = [
        item for item in comparables if item["quantity_ratio"] > 3 or item["quantity_ratio"] < 1 / 3
    ]
    wide_spread = dispersion_ratio is not None and dispersion_ratio > 2
    moderate_spread = dispersion_ratio is not None and dispersion_ratio > 1.5
    if wide_spread:
        confidence = "low"
    elif moderate_spread:
        confidence = _cap_confidence(confidence, "medium")
    if fallback_heavy:
        confidence = _lower_confidence(confidence)
    if len(extreme_quantity) * 2 > len(comparables):
        confidence = _lower_confidence(confidence)
    explanation = {
        "as_of": effective_date.isoformat(),
        "method": "historical_comparable_cost_indexation",
        "target_quantity": float(target.quantity),
        "target_unit": target.unit,
        "target_complexity_percent": target.complexity_percent,
        "target_margin_percent": float(target.target_margin_percent),
        "spread_percent": round(spread * 100, 2),
        "dispersion_ratio": round(dispersion_ratio, 2) if dispersion_ratio is not None else None,
        "comparables": comparables,
        "warnings": [
            warning
            for condition, warning in (
                (factor_count == 0, "Geçmiş kayıtlarda maliyet payı yok; fiyat artışı doğrulanamadı."),
                (actual_count == 0, "Gerçekleşen maliyet yok; öneri geçmiş satış fiyatlarına dayanıyor."),
                (len(comparables) < 3, "Benzer kayıt sayısı düşük; öneri aralığını dikkatle değerlendirin."),
                (moderate_spread, "Benzer kayıtların fiyatları birbirinden çok farklı; aralık bu farkı kapsar, öneriyi dikkatle değerlendirin."),
                (fallback_share > 0, "Bazı maliyet payları için güncel fiyat bulunamadı; referans fiyat kullanıldı (fiyat değişimi %0 sayıldı)."),
                (bool(stale_factors), f"Bazı güncel fiyatlar {STALE_PRICE_DAYS} günden eski; güncel alış veya endeks girin."),
                (bool(extreme_quantity), "Miktar farkı büyük (3 kattan fazla); doğrusal ölçekleme güvenilmez."),
            )
            if condition
        ],
    }
    suggestion = PricingSuggestion(
        project_product_id=target.id,
        suggested_low_kurus=low,
        suggested_mid_kurus=mid,
        suggested_high_kurus=high,
        confidence=confidence,
        comparable_count=len(comparables),
        explanation=explanation,
        model_version=MODEL_VERSION,
    )
    session.add(suggestion)
    session.flush()
    add_audit(
        session,
        "pricing_suggestion",
        suggestion.id,
        "created",
        {"product_id": target.id, "mid_kurus": mid, "confidence": confidence},
    )
    session.commit()
    session.refresh(suggestion)
    return _suggestion_dict(suggestion)


@router.get("/pricing/status")
def pricing_status(session: Session = Depends(get_session)):
    products = list(
        session.scalars(
            select(ProjectProduct).where(ProjectProduct.status == RecordStatus.ACTIVE)
        )
    )
    priced = [p for p in products if p.accepted_total_kurus or p.quoted_total_kurus]
    completed = [p for p in products if p.actual_cost_kurus is not None]
    with_factors = [p for p in products if _factors(session, p.id)]
    types: dict[str, int] = {}
    for product in priced:
        types[product.product_type] = types.get(product.product_type, 0) + 1
    latest_indices = list(
        session.scalars(
            select(PricingIndexEntry)
            .where(PricingIndexEntry.status == RecordStatus.ACTIVE)
            .order_by(PricingIndexEntry.recorded_on.desc(), PricingIndexEntry.created_at.desc())
            .limit(20)
        )
    )
    return {
        "model_name": "product_pricing",
        "model_version": MODEL_VERSION,
        "product_count": len(products),
        "priced_product_count": len(priced),
        "actual_cost_count": len(completed),
        "factor_coverage_count": len(with_factors),
        "ready": bool(priced),
        "message": (
            "Fiyat önerisi için geçmiş kayıt var."
            if priced
            else "İlk fiyat önerisi için en az bir fiyatlandırılmış ürün girin."
        ),
        "product_types": [
            {"product_type": key, "priced_count": value}
            for key, value in sorted(types.items(), key=lambda item: (-item[1], item[0]))
        ],
        "latest_manual_indices": [
            {
                "id": row.id,
                "factor_key": row.factor_key,
                "label": row.label,
                "material_id": row.material_id,
                "recorded_on": row.recorded_on,
                "unit_price_kurus": row.unit_price_kurus,
                "source": row.source,
            }
            for row in latest_indices
        ],
    }
