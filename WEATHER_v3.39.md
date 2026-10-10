# v3.39 Weather resilience

- Persist successful Open-Meteo forecasts in a private per-device cache.
- If Open-Meteo is unreachable, use a cached forecast only while its dates still include today; clearly identify the cached source through `LAST_WEATHER_SOURCE`.
- Check the free, keyless MET Norway API for availability as a diagnostic fallback. **Important limitation:** MET Norway's forecast does not include the required 31-day weather history and soil fields, so the current fungal model cannot calculate a scientifically comparable full forecast from MET alone. The app reports this rather than silently inventing inputs.
- No map or forecast mathematics changes. Android APK not built; network access not verified on the user's phone.
