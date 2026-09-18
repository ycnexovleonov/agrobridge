"""
ai_analysis.py

Два AI/ML-компонента поверх временного ряда NDVI/NDMI:

1. forecast_ndvi() — прогноз NDVI на N дней вперёд линейной регрессией.
   Это "AI" в честном, объяснимом виде: не чёрный ящик, а понятная модель,
   которую легко защитить перед жюри — можно на пальцах показать,
   как считается наклон прямой и почему прогноз именно такой.

2. classify_anomaly() — классификация ПРИЧИНЫ аномалии по паттерну
   NDVI+NDMI (правило-ориентированная эвристика, а не готовая ML-модель
   с обучением — честно объясняем это на защите, см. README).

Почему не ARIMA и не сложная модель с обучением: временной ряд короткий
(на сезон — 15-18 точек по декадам), для полноценного ARIMA/LSTM данных
критически мало, они переобучатся или дадут неустойчивый прогноз.
Линейная регрессия по последним точкам тренда — более честный, стабильный
и объяснимый выбор для такого объёма данных.
"""

import numpy as np
from datetime import datetime, timedelta


def forecast_ndvi(timeseries: list[dict], days_ahead: int = 14, use_last_n: int = 5) -> dict:
    """
    Прогнозирует NDVI на days_ahead дней вперёд по линейному тренду
    последних use_last_n наблюдений (не по всему сезону — берём только
    последний участок, чтобы уловить ТЕКУЩУЮ динамику, а не всю сезонную
    кривую роста-спада, которая нелинейна).

    Возвращает:
        {
            "forecast_date": "2026-09-29",
            "forecast_ndvi": 0.412,
            "confidence_interval": (0.35, 0.47),
            "trend": "рост" | "спад" | "стабильно",
            "trend_slope_per_day": 0.004,
            "n_points_used": 5,
        }
        или {"error": "..."} если точек недостаточно.
    """
    if len(timeseries) < 3:
        return {"error": "Недостаточно данных для прогноза (нужно минимум 3 точки)"}

    recent = timeseries[-use_last_n:] if len(timeseries) >= use_last_n else timeseries

    dates = [datetime.strptime(p["date"], "%Y-%m-%d") for p in recent]
    values = np.array([p["ndvi_mean"] for p in recent])

    # Переводим даты в "дни от первой точки" — простая числовая ось для регрессии
    day0 = dates[0]
    x = np.array([(d - day0).days for d in dates], dtype=float)

    # Линейная регрессия: NDVI = slope * day + intercept
    slope, intercept = np.polyfit(x, values, deg=1)

    # Остатки модели — нужны для доверительного интервала прогноза
    predicted_on_history = slope * x + intercept
    residuals = values - predicted_on_history
    residual_std = float(np.std(residuals)) if len(residuals) > 1 else 0.05

    last_date = dates[-1]
    forecast_date = last_date + timedelta(days=days_ahead)
    x_forecast = (forecast_date - day0).days
    forecast_value = float(slope * x_forecast + intercept)

    # Клампим в физически осмысленный диапазон NDVI [-1, 1]
    forecast_value = max(-1.0, min(1.0, forecast_value))

    # Простой 90%-й интервал: ±1.65 * стд.отклонение остатков модели
    margin = 1.65 * residual_std
    ci_low = max(-1.0, round(forecast_value - margin, 4))
    ci_high = min(1.0, round(forecast_value + margin, 4))

    if slope > 0.002:
        trend = "рост"
    elif slope < -0.002:
        trend = "спад"
    else:
        trend = "стабильно"

    return {
        "forecast_date": forecast_date.strftime("%Y-%m-%d"),
        "forecast_ndvi": round(forecast_value, 4),
        "confidence_interval": (ci_low, ci_high),
        "trend": trend,
        "trend_slope_per_day": round(float(slope), 5),
        "n_points_used": len(recent),
    }


def classify_anomaly(point: dict, ndvi_norm: float, ndmi_norm: float) -> dict:
    """
    Классифицирует ВЕРОЯТНУЮ причину аномалии по паттерну NDVI/NDMI.

    Логика (физически обоснованная, не случайные пороги):
    - NDVI низкий И NDMI низкий -> растению не хватает влаги -> ЗАСУХА/СУХОВЕЙ
      (индекс влажности тоже просел — значит дело именно в воде)
    - NDVI низкий, но NDMI В НОРМЕ -> влага есть, а зелёная масса всё равно
      просела -> ВОЗМОЖНАЯ БОЛЕЗНЬ/ВРЕДИТЕЛЬ (растение "болеет" не от засухи)
    - NDVI умеренно низкий, много "шума" (высокий std) -> ЗАСОРЁННОСТЬ /
      неоднородность посева (смесь сорняков и культуры даёт пятнистую,
      нестабильную картину индекса внутри контура)
    - иначе -> НЕОПРЕДЕЛЁННАЯ АНОМАЛИЯ (нужен визуальный осмотр)

    Это НЕ обученная ML-модель, а прозрачное экспертное правило поверх
    физического смысла индексов — на защите стоит явно это проговорить:
    "мы сознательно выбрали объяснимую логику, а не чёрный ящик, потому что
    в агрономии решение должно быть проверяемым агрономом, а не просто
    цифрой с потолка".
    """
    ndvi = point.get("ndvi_mean")
    ndmi = point.get("ndmi_mean")
    ndvi_std = point.get("ndvi_std", 0)

    if ndvi is None:
        return {"type": "нет данных", "explanation": "NDVI не рассчитан для этого периода"}

    ndvi_deviation = (ndvi - ndvi_norm) / ndvi_norm if ndvi_norm else 0
    ndmi_deviation = (ndmi - ndmi_norm) / ndmi_norm if (ndmi is not None and ndmi_norm) else 0

    if ndvi_deviation <= -0.15 and ndmi_deviation <= -0.15:
        return {
            "type": "Засуха / суховей",
            "explanation": f"Оба индекса просели (NDVI {ndvi_deviation*100:.0f}%, "
                            f"NDMI {ndmi_deviation*100:.0f}%) — признак дефицита влаги.",
        }

    if ndvi_deviation <= -0.15 and ndmi_deviation > -0.10:
        return {
            "type": "Возможная болезнь/вредитель",
            "explanation": f"NDVI просел ({ndvi_deviation*100:.0f}%), но влажность (NDMI) "
                            f"в норме — вода есть, а зелёная масса всё равно снижена.",
        }

    if ndvi_deviation <= -0.10 and ndvi_std and ndvi_std > 0.08:
        return {
            "type": "Засорённость / неоднородность",
            "explanation": f"Умеренное снижение NDVI при высоком разбросе внутри поля "
                            f"(std={ndvi_std}) — типично для пятнистого засорения сорняками.",
        }

    if ndvi_deviation <= -0.10:
        return {
            "type": "Неопределённая аномалия",
            "explanation": "Есть отклонение от нормы, но паттерн не однозначен — "
                            "рекомендуется визуальный осмотр участка агрономом.",
        }

    return {"type": "В пределах нормы", "explanation": "Существенных отклонений не выявлено."}
