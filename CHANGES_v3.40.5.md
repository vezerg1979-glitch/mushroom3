# v3.40.5 — NASA POWER historical weather fallback

- Open-Meteo remains primary; cached forecast remains preferred when current.
- MET Norway forecast is combined with NASA POWER daily historical precipitation and temperatures (up to 31 previous days).
- NASA sentinel -999, missing dates, and invalid readings are excluded rather than interpreted as zero rainfall.
- Previously cached Open-Meteo historical days take priority where available.
- When history is incomplete, the existing neutral initialization remains for missing days and the forecast is explicitly labeled limited.
- No changes to maps, calendar, radar, or mushroom scoring formulas.
- Added offline unit tests for NASA parsing and MET history merge.
- APK not built or device-tested; live NASA API connection not validated in this environment.
