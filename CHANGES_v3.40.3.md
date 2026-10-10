# v3.40.3 — MET Norway precipitation parser

- Fixed mixed 1-hour and 6-hour precipitation intervals: overlapping forecasts are not counted twice.
- Split forecast precipitation across UTC day boundaries when needed.
- Preserved fallback order Open-Meteo → fresh cache → MET Norway and visible limited-data label.
- Kept existing map, radar, calendar and mushroom scoring algorithms unchanged.
- Added regression test for mixed intervals spanning midnight.

Note: APK was not built or tested on a physical Android device. A browser response from MET Norway does not guarantee that the installed APK can connect; User-Agent, Android network and UI handling should be checked on device.
