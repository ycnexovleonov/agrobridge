"""
app.py — точка входа. Запуск: streamlit run app.py

Что делает приложение (для объяснения жюри в двух предложениях):
"Приложение получает контур поля, запрашивает у Sentinel Hub временной ряд
вегетационных индексов NDVI/NDMI за сезон, сравнивает текущие значения
с нормой сезона по этому же полю и подсвечивает периоды, где растительность
выглядит хуже ожидаемого — это и есть 'проблемные зоны/периоды' из ТЗ."
"""

import json

import folium
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from ai_analysis import classify_anomaly, forecast_ndvi
from analysis import compute_seasonal_norm, detect_anomalies, summarize
from config import DEFAULT_FIELD_GEOJSON, SEASON_END, SEASON_START
from export import export_csv, export_geojson, export_pdf_report
from mock_data import generate_mock_timeseries

st.set_page_config(page_title="Agrobridge — мониторинг всходов", layout="wide")

st.title("🌾 Agrobridge — мониторинг всходов по NDVI/NDMI")
st.caption("Трек 1.1: мониторинг всходов, выделение проблемных зон, отклонение от нормы сезона")

# ---------- Сайдбар: настройки ----------
with st.sidebar:
    st.header("Настройки")

    field_name = st.text_input("Название поля", value="Поле №1 (Акмолинская обл.)")

    data_source = st.radio(
        "Источник данных",
        ["Demo (синтетические данные)", "Реальные данные (Sentinel Hub)"],
        help="Demo — быстро, без интернета/лимитов API, для отладки интерфейса. "
             "Реальные данные — настоящий запрос к Copernicus Data Space.",
    )

    date_from = st.text_input("Начало сезона", value=SEASON_START)
    date_to = st.text_input("Конец сезона", value=SEASON_END)

    uploaded = st.file_uploader("Или загрузите свой контур поля (GeoJSON)", type=["geojson", "json"])

    st.divider()
    run = st.button("🔄 Рассчитать", type="primary", use_container_width=True)

# ---------- Контур поля ----------
if uploaded is not None:
    field_geojson = json.load(uploaded)
    if field_geojson.get("type") == "FeatureCollection":
        field_geojson = field_geojson["features"][0]["geometry"]
else:
    field_geojson = DEFAULT_FIELD_GEOJSON

# ---------- Получение данных ----------
if "timeseries" not in st.session_state or run:
    with st.spinner("Считаем NDVI/NDMI..."):
        if data_source.startswith("Demo"):
            raw_timeseries = generate_mock_timeseries(date_from, date_to)
        else:
            try:
                from sentinel_client import fetch_ndvi_ndmi_timeseries
                raw_timeseries = fetch_ndvi_ndmi_timeseries(field_geojson, date_from, date_to)
                if not raw_timeseries:
                    st.warning("Sentinel Hub не вернул данных (возможно, всё в облаках "
                               "за этот период). Переключаюсь на demo-данные.")
                    raw_timeseries = generate_mock_timeseries(date_from, date_to)
            except Exception as e:
                st.error(f"Ошибка запроса к Sentinel Hub: {e}. Показываю demo-данные.")
                raw_timeseries = generate_mock_timeseries(date_from, date_to)

        enriched, norm = detect_anomalies(raw_timeseries)
        ndmi_norm = compute_seasonal_norm(raw_timeseries, "ndmi_mean")
        summary = summarize(enriched)

        st.session_state["timeseries"] = enriched
        st.session_state["norm"] = norm
        st.session_state["ndmi_norm"] = ndmi_norm
        st.session_state["summary"] = summary
        st.session_state["field_geojson"] = field_geojson

enriched = st.session_state["timeseries"]
norm = st.session_state["norm"]
ndmi_norm = st.session_state["ndmi_norm"]
summary = st.session_state["summary"]
field_geojson = st.session_state["field_geojson"]

# ---------- Верхние метрики ----------
col1, col2, col3, col4 = st.columns(4)
col1.metric("Норма NDVI за сезон", norm)
col2.metric("Периодов наблюдения", summary["total_periods"])
col3.metric("Периодов с аномалией", summary["anomaly_periods"])
col4.metric("Доля проблемных периодов", f"{summary['anomaly_share_pct']}%")

st.divider()

left, right = st.columns([1, 1.3])

# ---------- Карта ----------
with left:
    st.subheader("🗺️ Карта поля")

    coords = field_geojson["coordinates"][0]
    center_lat = sum(c[1] for c in coords) / len(coords)
    center_lon = sum(c[0] for c in coords) / len(coords)

    last_point = enriched[-1] if enriched else None
    is_bad = last_point and last_point.get("is_anomaly")
    color = "#d62728" if is_bad else "#2ca02c"

    m = folium.Map(location=[center_lat, center_lon], zoom_start=14, tiles="CartoDB positron")

    folium.GeoJson(
        field_geojson,
        style_function=lambda feature, color=color: {
            "fillColor": color,
            "color": "#333333",
            "weight": 2,
            "fillOpacity": 0.5,
        },
        tooltip=f"{field_name}: NDVI={last_point['ndvi_mean'] if last_point else '—'}",
    ).add_to(m)

    st_folium(m, width=None, height=420)

    if is_bad:
        st.error(f"⚠️ Последнее наблюдение ({last_point['date']}) ниже нормы сезона "
                  f"на {abs(last_point['deviation_pct'])}%. Рекомендуется выезд агронома.")
    elif last_point:
        st.success(f"✅ Последнее наблюдение ({last_point['date']}) в пределах нормы "
                    f"(отклонение {last_point['deviation_pct']}%).")

# ---------- График временного ряда ----------
with right:
    st.subheader("📈 Динамика NDVI/NDMI за сезон")

    dates = [p["date"] for p in enriched]
    ndvi_values = [p["ndvi_mean"] for p in enriched]
    ndmi_values = [p["ndmi_mean"] for p in enriched]
    anomaly_dates = [p["date"] for p in enriched if p.get("is_anomaly")]
    anomaly_values = [p["ndvi_mean"] for p in enriched if p.get("is_anomaly")]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates, y=ndvi_values, mode="lines+markers", name="NDVI",
                              line=dict(color="#2ca02c")))
    fig.add_trace(go.Scatter(x=dates, y=ndmi_values, mode="lines+markers", name="NDMI",
                              line=dict(color="#1f77b4")))
    fig.add_hline(y=norm, line_dash="dash", line_color="gray",
                  annotation_text="норма сезона (NDVI)")
    fig.add_trace(go.Scatter(x=anomaly_dates, y=anomaly_values, mode="markers",
                              name="Аномалия", marker=dict(color="#d62728", size=12, symbol="x")))

    fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10),
                       legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# ---------- AI: прогноз NDVI и классификация аномалий ----------
st.subheader("🤖 AI-прогноз и классификация аномалий")

ai_col1, ai_col2 = st.columns([1, 1.3])

with ai_col1:
    st.markdown("**Прогноз NDVI на 14 дней вперёд**")
    forecast = forecast_ndvi(enriched, days_ahead=14)

    if "error" in forecast:
        st.info(forecast["error"])
    else:
        trend_emoji = {"рост": "📈", "спад": "📉", "стабильно": "➡️"}[forecast["trend"]]
        st.metric(
            f"Прогноз на {forecast['forecast_date']}",
            forecast["forecast_ndvi"],
            delta=f"{trend_emoji} {forecast['trend']}",
        )
        ci_low, ci_high = forecast["confidence_interval"]
        st.caption(
            f"90% доверительный интервал: [{ci_low}, {ci_high}]  \n"
            f"Модель: линейная регрессия по последним {forecast['n_points_used']} "
            f"наблюдениям, наклон {forecast['trend_slope_per_day']}/день."
        )

with ai_col2:
    st.markdown("**Классификация выявленных аномалий**")
    anomaly_points = [p for p in enriched if p.get("is_anomaly")]

    if not anomaly_points:
        st.success("Аномалий за сезон не выявлено — классифицировать нечего.")
    else:
        for p in anomaly_points:
            result = classify_anomaly(p, norm, ndmi_norm)
            with st.container(border=True):
                st.markdown(f"**{p['date']}** — {result['type']}")
                st.caption(result["explanation"])


st.subheader("📋 Таблица наблюдений и выгрузка отчёта")
st.dataframe(enriched, use_container_width=True)

exp_col1, exp_col2, exp_col3 = st.columns(3)

with exp_col1:
    st.download_button("⬇️ Скачать CSV", data=export_csv(enriched),
                        file_name="ndvi_report.csv", mime="text/csv",
                        use_container_width=True)

with exp_col2:
    st.download_button("⬇️ Скачать GeoJSON", data=export_geojson(field_geojson, summary, field_name),
                        file_name="field_report.geojson", mime="application/geo+json",
                        use_container_width=True)

with exp_col3:
    try:
        pdf_bytes = export_pdf_report(field_name, summary, norm, enriched)
        st.download_button("⬇️ Скачать PDF", data=pdf_bytes,
                            file_name="ndvi_report.pdf", mime="application/pdf",
                            use_container_width=True)
    except Exception as e:
        st.warning(f"PDF пока недоступен: {e}")
