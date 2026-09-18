"""
export.py — формирует отчёт в трёх форматах, как требует ТЗ трека.
"""

import csv
import io
import json


def export_csv(enriched_timeseries: list[dict]) -> bytes:
    """CSV с временным рядом и отклонениями — удобно открыть в Excel."""
    buffer = io.StringIO()
    if not enriched_timeseries:
        return b""

    fieldnames = list(enriched_timeseries[0].keys())
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(enriched_timeseries)
    return buffer.getvalue().encode("utf-8")


def export_geojson(field_geojson: dict, summary: dict, field_name: str = "Поле №1") -> bytes:
    """
    GeoJSON с контуром поля и сводкой в properties — можно сразу открыть
    в QGIS или любой ГИС-программе, как и требует ТЗ ("выгрузка векторных контуров").
    """
    feature = {
        "type": "Feature",
        "geometry": field_geojson,
        "properties": {
            "field_name": field_name,
            "anomaly_share_pct": summary.get("anomaly_share_pct"),
            "anomaly_periods": summary.get("anomaly_periods"),
            "total_periods": summary.get("total_periods"),
            "latest_ndvi": summary.get("latest_point", {}).get("ndvi_mean")
            if summary.get("latest_point") else None,
            "latest_date": summary.get("latest_point", {}).get("date")
            if summary.get("latest_point") else None,
        },
    }
    feature_collection = {"type": "FeatureCollection", "features": [feature]}
    return json.dumps(feature_collection, ensure_ascii=False, indent=2).encode("utf-8")


def export_pdf_report(field_name: str, summary: dict, norm: float, enriched_timeseries: list[dict]) -> bytes:
    """Короткий текстовый PDF-отчёт — для распечатки/приложения к заявке на выезд агронома."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import cm

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 2 * cm
    c.setFont("Helvetica-Bold", 16)
    c.drawString(2 * cm, y, "Отчёт мониторинга всходов — Agrobridge")
    y -= 1 * cm

    c.setFont("Helvetica", 11)
    lines = [
        f"Поле: {field_name}",
        f"Норма NDVI за сезон: {norm}",
        f"Всего периодов наблюдения: {summary.get('total_periods')}",
        f"Периодов с аномалией: {summary.get('anomaly_periods')} "
        f"({summary.get('anomaly_share_pct')}%)",
    ]
    if summary.get("latest_point"):
        lp = summary["latest_point"]
        lines.append(f"Последнее наблюдение: {lp['date']}, NDVI = {lp['ndvi_mean']}, "
                      f"отклонение {lp.get('deviation_pct')}%")

    for line in lines:
        c.drawString(2 * cm, y, line)
        y -= 0.7 * cm

    y -= 0.5 * cm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2 * cm, y, "Периоды с отклонением ниже нормы:")
    y -= 0.8 * cm
    c.setFont("Helvetica", 10)

    for point in enriched_timeseries:
        if point.get("is_anomaly"):
            c.drawString(2 * cm, y, f"{point['date']}: NDVI={point['ndvi_mean']} "
                                     f"(отклонение {point['deviation_pct']}%)")
            y -= 0.6 * cm
            if y < 2 * cm:
                c.showPage()
                y = height - 2 * cm

    c.save()
    buffer.seek(0)
    return buffer.read()
