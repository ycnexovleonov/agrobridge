"""
mock_data.py

Зачем это нужно: во время живого демо на защите интернет может быть плохим,
лимиты бесплатного Sentinel Hub аккаунта могут кончиться, а сервис — тормозить.
Этот модуль генерирует правдоподобный временной ряд NDVI/NDMI, чтобы:
  1) можно было разрабатывать интерфейс, не дожидаясь настоящих запросов;
  2) иметь запасной "Demo mode" на защите, если реальный API подведёт.

Это НЕ подмена реальных данных в финальном отчёте — это переключатель
в интерфейсе, который явно подписан "демо-данные", чтобы не вводить жюри
в заблуждение.
"""

import random
from datetime import datetime, timedelta


def generate_mock_timeseries(date_from: str, date_to: str, aggregation_days: int = 10,
                              with_anomaly: bool = True, seed: int = 42):
    """Генерирует реалистичную сезонную кривую NDVI/NDMI с ростом и спадом."""
    rng = random.Random(seed)

    start = datetime.strptime(date_from, "%Y-%m-%d")
    end = datetime.strptime(date_to, "%Y-%m-%d")

    dates = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=aggregation_days)

    n = len(dates)
    results = []
    for i, date in enumerate(dates):
        # Сезонная кривая: рост -> пик -> спад (типичная динамика вегетации)
        progress = i / max(n - 1, 1)
        seasonal_curve = 0.15 + 0.65 * (1 - abs(2 * progress - 1) ** 1.5)

        noise = rng.uniform(-0.03, 0.03)
        ndvi = round(max(0.05, min(0.9, seasonal_curve + noise)), 4)
        ndmi = round(max(0.0, min(0.6, ndvi * 0.5 + rng.uniform(-0.02, 0.02))), 4)

        # Искусственная аномалия в середине сезона — имитирует засуху/вредителя
        if with_anomaly and 0.35 < progress < 0.55:
            ndvi = round(ndvi * 0.55, 4)
            ndmi = round(ndmi * 0.6, 4)

        results.append({
            "date": date.strftime("%Y-%m-%d"),
            "ndvi_mean": ndvi,
            "ndvi_std": round(rng.uniform(0.02, 0.08), 4),
            "ndmi_mean": ndmi,
            "ndmi_std": round(rng.uniform(0.02, 0.05), 4),
            "valid_pixels": rng.randint(200, 900),
        })

    return results
