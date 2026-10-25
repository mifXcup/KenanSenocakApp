# Kenan Şenocak Yönetim Core

Yerel masaüstü uygulamasının FastAPI + SQLite veri çekirdeği.

## Geliştirme kurulumu

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Çalıştırma

Geliştirmede token ve veri dizinini açıkça verin:

```powershell
$env:KS_DATA_DIR = "$PWD\.local-data"
$env:KS_SIDECAR_TOKEN = "yalnizca-gelistirme-icin-token"
.\.venv\Scripts\python.exe -m uvicorn ks_yonetim.main:app --host 127.0.0.1 --port 8765
```

Üretimde token Electron main tarafından her açılışta rastgele üretilir. Renderer'a genel ağ veya dosya sistemi yetkisi verilmez.

## Doğrulama

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest
```

Migration:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```
