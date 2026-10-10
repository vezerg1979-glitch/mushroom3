import json
from datetime import date, timedelta
from unittest.mock import patch
from android import mushroom_forecast as mod


def test_nasa_history_parsing_and_missing_values():
    today = date(2026, 10, 10)
    d1 = (today - timedelta(days=2)).strftime('%Y%m%d')
    d2 = (today - timedelta(days=1)).strftime('%Y%m%d')
    payload = {'properties': {'parameter': {
        'PRECTOTCORR': {d1: 9.36, d2: -999},
        'T2M': {d1: 13.79, d2: 11},
        'T2M_MAX': {d1: 17.31, d2: 15},
        'T2M_MIN': {d1: 11.08, d2: 7}}}}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, *args): return json.dumps(payload).encode()
    with patch.object(mod.urllib.request, 'urlopen', return_value=Response()):
        history = mod._nasa_power_history(55.75, 37.62, today)
    assert len(history) == 1
    assert history[today - timedelta(days=2)].precip == 9.36
    assert today - timedelta(days=1) not in history


def test_met_uses_nasa_history_not_neutral():
    today = date.today()
    previous = today - timedelta(days=1)
    observed = mod.Day(previous, 20, 10, 15, 12, 2)
    met = {today: {'temps': [10, 12], 'rhs': [80], 'precip': 3.0}}
    days = mod._met_to_days(met, 7, history={previous: observed})
    assert next(x for x in days if x.d == previous) == observed
    assert next(x for x in days if x.d == today).precip == 3.0
