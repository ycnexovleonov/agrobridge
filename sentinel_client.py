"""
sentinel_client.py

Отвечает за один вопрос: "дай мне временной ряд NDVI/NDMI по контуру поля".

Как это работает (коротко, для защиты):
1. Sentinel-2 — спутник, который снимает Землю каждые 5 дней в нескольких
   спектральных каналах (не только видимый свет, но и инфракрасный).
2. NDVI = (NIR - RED) / (NIR + RED) — чем зеленее и гуще растительность,
   тем сильнее она отражает ближний инфракрасный (NIR) и поглощает красный (RED).
   Значения от -1 до 1: голая земля ~0.1-0.2, здоровые посевы ~0.6-0.9.
3. NDMI = (NIR - SWIR) / (NIR + SWIR) — похожая идея, но чувствителен
   к влажности растительности (SWIR — коротковолновый инфракрасный).
4. Мы не скачиваем сами снимки (это тяжело), а используем Statistical API
   Sentinel Hub: ему отправляется контур поля и формула расчёта (evalscript),
   а он возвращает уже готовую статистику (среднее, стд.отклонение) по датам.
   Это быстрее и не требует своей инфраструктуры для обработки растров.
"""

from datetime import datetime
from sentinelhub import CRS, DataCollection, Geometry, SentinelHubStatistical, SHConfig

from config import SH_CLIENT_ID, SH_CLIENT_SECRET, SH_BASE_URL, SH_TOKEN_URL


def get_data_collection():
    """
    DataCollection.SENTINEL2_L2A по умолчанию привязан к старому сервису
    services.sentinel-hub.com. Для Copernicus Data Space Ecosystem (CDSE)
    коллекцию нужно явно пересоздать с service_url = sh_base_url —
    иначе запрос уйдёт не туда и вернёт 401, даже если токен верный.
    """
    return DataCollection.SENTINEL2_L2A.define_from(
        "SENTINEL2_L2A_CDSE", service_url=SH_BASE_URL
    )


def get_config() -> SHConfig:
    """Собирает конфиг авторизации для Sentinel Hub / Copernicus Data Space."""
    config = SHConfig()
    config.sh_client_id = SH_CLIENT_ID
    config.sh_client_secret = SH_CLIENT_SECRET
    config.sh_base_url = SH_BASE_URL
    config.sh_token_url = SH_TOKEN_URL  # отдельный identity-сервер, не sh_base_url!
    return config


# Evalscript — маленькая программа на JS, которая выполняется на стороне
# Sentinel Hub для каждого пикселя снимка. Мы просим вернуть NDVI, NDMI
# и маску облачности/валидности данных (dataMask).
EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "B8A", "B11", "SCL", "dataMask"] }],
    output: [
      { id: "ndvi", bands: 1 },
      { id: "ndmi", bands: 1 },
      { id: "dataMask", bands: 1 }
    ]
  };
}

function evaluatePixel(sample) {
  // SCL — Scene Classification Layer. Отсекаем облака, тени, снег.
  let invalid = [8, 9, 10, 11].includes(sample.SCL);
  let mask = invalid ? 0 : sample.dataMask;

  let ndvi = (sample.B08 - sample.B04) / (sample.B08 + sample.B04);
  let ndmi = (sample.B8A - sample.B11) / (sample.B8A + sample.B11);

  return {
    ndvi: [ndvi],
    ndmi: [ndmi],
    dataMask: [mask]
  };
}
"""


def estimate_grid_size(field_geojson: dict, target_resolution_m: int = 10,
                        min_px: int = 8, max_px: int = 250) -> tuple[int, int]:
    """
    Считает размер сетки в ПИКСЕЛЯХ (не в метрах и не в градусах!) под контур поля.

    Почему не resolution в метрах: если геометрия задана в WGS84 (градусы),
    Sentinel Hub интерпретирует число в resolution как градусы, а не метры —
    легко получить всего 1 пиксель на всё поле и вылезти за лимит API
    "1500 м/пиксель". size в пикселях не зависит от системы координат,
    поэтому этой проблемы не будет в принципе.

    Грубая оценка размеров поля в метрах через долготу/широту — точности
    достаточно для выбора сетки, не для картографии.
    """
    from math import cos, radians

    coords = field_geojson["coordinates"][0]
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]

    lon_extent_deg = max(lons) - min(lons)
    lat_extent_deg = max(lats) - min(lats)
    avg_lat = sum(lats) / len(lats)

    width_m = lon_extent_deg * 111_320 * cos(radians(avg_lat))
    height_m = lat_extent_deg * 110_540

    width_px = max(min_px, min(max_px, round(width_m / target_resolution_m)))
    height_px = max(min_px, min(max_px, round(height_m / target_resolution_m)))

    return width_px, height_px


import math


def _safe_stat(value, digits: int = 4):
    """
    Безопасно приводит значение статистики к числу.

    Зачем это нужно: если в контуре мало валидных пикселей или в evalscript
    случилось деление на ноль (например, B08+B04=0 на кромке облака),
    Sentinel Hub Statistical API иногда присылает "mean": "NaN" СТРОКОЙ,
    а не числом. Обычный round() падает на строке с ошибкой
    "type str doesn't define __round__". float(value) корректно
    распознаёт и число, и строку "NaN"/"Infinity", а дальше мы просто
    отбрасываем такие точки как невалидные (как будто там не было данных).
    """
    if value is None:
        return None
    try:
        fval = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(fval) or math.isinf(fval):
        return None
    return round(fval, digits)


def fetch_ndvi_ndmi_timeseries(field_geojson: dict, date_from: str, date_to: str,
                                aggregation_days: int = 10, max_cloud_coverage: float = 0.6):
    """
    Получает временной ряд NDVI/NDMI по контуру поля.

    Параметры:
        field_geojson: контур поля в формате GeoJSON Polygon (координаты WGS84)
        date_from, date_to: границы периода "YYYY-MM-DD"
        aggregation_days: шаг агрегации в днях (10 = по декадам, как в задаче ТЗ)
        max_cloud_coverage: отсекать снимки с облачностью выше этого порога

    Возвращает:
        список словарей вида:
        {"date": "2026-05-01", "ndvi_mean": 0.62, "ndmi_mean": 0.31, "valid_pixels": 843}
    """
    config = get_config()
    geometry = Geometry(field_geojson, crs=CRS.WGS84)

    size = estimate_grid_size(field_geojson)

    aggregation = SentinelHubStatistical.aggregation(
        evalscript=EVALSCRIPT,
        time_interval=(date_from, date_to),
        aggregation_interval=f"P{aggregation_days}D",
        size=size,  # (ширина, высота) в пикселях — не зависит от CRS геометрии
    )

    input_data = SentinelHubStatistical.input_data(
        get_data_collection(),
        maxcc=max_cloud_coverage,
    )

    request = SentinelHubStatistical(
        aggregation=aggregation,
        input_data=[input_data],
        geometry=geometry,
        config=config,
    )

    raw = request.get_data()[0]

    results = []
    for interval in raw.get("data", []):
        date = interval["interval"]["from"][:10]
        outputs = interval.get("outputs", {})

        ndvi_stats = outputs.get("ndvi", {}).get("bands", {}).get("B0", {}).get("stats")
        ndmi_stats = outputs.get("ndmi", {}).get("bands", {}).get("B0", {}).get("stats")

        if not ndvi_stats or ndvi_stats.get("sampleCount", 0) == 0:
            continue  # нет валидных пикселей (например, всё в облаках)

        ndvi_mean = _safe_stat(ndvi_stats.get("mean"))
        if ndvi_mean is None:
            continue  # NDVI не удалось посчитать (NaN/деление на ноль) — пропускаем точку

        results.append({
            "date": date,
            "ndvi_mean": ndvi_mean,
            "ndvi_std": _safe_stat(ndvi_stats.get("stDev"), 4) or 0,
            "ndmi_mean": _safe_stat(ndmi_stats.get("mean")) if ndmi_stats else None,
            "ndmi_std": _safe_stat(ndmi_stats.get("stDev"), 4) if ndmi_stats else None,
            "valid_pixels": ndvi_stats.get("sampleCount", 0),
        })

    return results
