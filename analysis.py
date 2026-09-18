"""
analysis.py

Отвечает за второй вопрос ТЗ: "выделение проблемных зон и отклонений от нормы сезона".

Подход (простой и объяснимый жюри — это плюс, не минус):
  1. "Норма сезона" = среднее значение NDVI по всем точкам временного ряда
     этого же поля за этот же сезон (baseline). В расширенной версии сюда
     можно подставить среднее за несколько ПРОШЛЫХ сезонов по этому полю —
     тогда сравнение будет честнее (см. README, раздел "что улучшить").
  2. Отклонение = (текущее значение - норма) / норма.
  3. Если отклонение ниже порога (ANOMALY_THRESHOLD) — точка помечается
     как "проблемная".

Это не ML-модель, а прозрачное статистическое правило — на защите такое
проще объяснить и сложнее "завалить" вопросом жюри, чем чёрный ящик.
"""

from statistics import mean

from config import ANOMALY_THRESHOLD


def compute_seasonal_norm(timeseries: list[dict], field: str = "ndvi_mean") -> float:
    """Считает среднее значение индекса по всему ряду — это и есть 'норма сезона'."""
    values = [point[field] for point in timeseries if point.get(field) is not None]
    return round(mean(values), 4) if values else 0.0


def detect_anomalies(timeseries: list[dict], field: str = "ndvi_mean",
                      threshold: float = ANOMALY_THRESHOLD) -> tuple[list[dict], float]:
    """
    Помечает каждую точку временного ряда флагом is_anomaly и добавляет
    относительное отклонение от нормы сезона (deviation_pct).

    Возвращает: (обогащённый временной ряд, норма сезона)
    """
    norm = compute_seasonal_norm(timeseries, field)
    if norm == 0:
        return timeseries, norm

    enriched = []
    for point in timeseries:
        value = point.get(field)
        deviation = (value - norm) / norm if value is not None else 0
        enriched.append({
            **point,
            "deviation_pct": round(deviation * 100, 1),
            "is_anomaly": deviation <= threshold,
        })

    return enriched, norm


def summarize(enriched_timeseries: list[dict]) -> dict:
    """Короткая сводка для карточек в интерфейсе и для отчёта."""
    total = len(enriched_timeseries)
    anomalies = [p for p in enriched_timeseries if p.get("is_anomaly")]

    return {
        "total_periods": total,
        "anomaly_periods": len(anomalies),
        "anomaly_share_pct": round(100 * len(anomalies) / total, 1) if total else 0,
        "worst_point": min(enriched_timeseries, key=lambda p: p.get("deviation_pct", 0))
        if enriched_timeseries else None,
        "latest_point": enriched_timeseries[-1] if enriched_timeseries else None,
    }
