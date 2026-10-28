# Bilinen riskler

- Kurulum paketi ticari kod imzalama sertifikasıyla imzalanmadı; Windows yayıncı uyarısı gösterebilir.
- Farklı bir Windows bilgisayarda gerçek kurulum ve etkileşimli arayüz kabul testi yapılmadı. Bu makinede installer yapısı ve paketli sidecar doğrulandı.
- Starlette TestClient, httpx ile ilgili bir deprecation uyarısı veriyor; test sonucu ve çalışma akışı etkilenmedi.
