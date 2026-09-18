"""
test_connection.py

Запустите ЭТО ПЕРВЫМ, до streamlit run app.py — если что-то не так
с credentials, контуром поля или доступом к API, ошибка будет видна
в чистом виде в консоли, а не спрятана в интерфейсе Streamlit.

Запуск:
    python test_connection.py
"""

from config import DEFAULT_FIELD_GEOJSON, SEASON_START, SEASON_END

print("1) Проверяю импорт и авторизацию...")
try:
    from sentinel_client import get_config, fetch_ndvi_ndmi_timeseries
    config = get_config()
    print(f"   Client ID: {config.sh_client_id[:8]}... (OK, загружен)")
except Exception as e:
    print(f"   ОШИБКА на этапе импорта/конфига: {e}")
    raise SystemExit(1)

print("\n2) Отправляю тестовый запрос к Sentinel Hub Statistical API...")
print(f"   Поле: тестовый контур рядом с Кокшетау")
print(f"   Период: {SEASON_START} — {SEASON_END}")

try:
    result = fetch_ndvi_ndmi_timeseries(
        DEFAULT_FIELD_GEOJSON,
        SEASON_START,
        SEASON_END,
        aggregation_days=10,
    )
    print(f"\n✅ Успех! Получено {len(result)} периодов наблюдения.\n")
    for point in result[:5]:
        print(f"   {point['date']}: NDVI={point['ndvi_mean']}, "
              f"NDMI={point['ndmi_mean']}, валидных пикселей={point['valid_pixels']}")
    if len(result) > 5:
        print(f"   ... и ещё {len(result) - 5} периодов")

except Exception as e:
    import traceback
    print(f"\n❌ ОШИБКА при запросе к API:")
    print(f"   {type(e).__name__}: {e}")
    print("\n--- Полный traceback (для диагностики) ---")
    traceback.print_exc()
    print("--- конец traceback ---\n")
    print("   Частые причины:")
    print("   - Неверный client_id/client_secret (проверьте config.py)")
    print("   - Истёк срок жизни OAuth-клиента (пересоздайте в Dashboard)")
    print("   - Слишком строгий max_cloud_coverage — за весь период всё в облаках")
    print("   - Контур поля некорректен (проверьте порядок координат: [lon, lat])")
    raise SystemExit(1)
