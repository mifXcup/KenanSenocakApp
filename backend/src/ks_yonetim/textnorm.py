"""Eşleştirme anahtarı üretimi (birim, ürün türü): Türkçe harf farklarına duyarsız."""

from __future__ import annotations

import re

# `str.casefold()` Türkçe "İ" harfini "i̇" (i + birleşik nokta) yapar ve "I" ile "ı"yı ayrı tutar;
# "Lİtre", "LITRE" ve "litre" üç ayrı birim sayılırdı. Gruplama anahtarında Türkçe harfler sadeleştirilir.
_FOLD = str.maketrans(
    {
        "İ": "i", "I": "i", "ı": "i",
        "Ç": "c", "ç": "c", "Ğ": "g", "ğ": "g",
        "Ö": "o", "ö": "o", "Ş": "s", "ş": "s",
        "Ü": "u", "ü": "u",
    }
)


def match_key(value: str | None) -> str:
    """Büyük/küçük harf, Türkçe aksan ve fazla boşluktan bağımsız karşılaştırma anahtarı."""
    return re.sub(r"\s+", " ", (value or "").translate(_FOLD).strip()).casefold()
