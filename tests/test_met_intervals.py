"""Regression tests for mixed 1h / 6h MET Norway forecast periods."""
from datetime import date
from unittest.mock import patch
import json
import importlib.util
from pathlib import Path
import sys
spec = importlib.util.spec_from_file_location("met_interval_engine", Path(__file__).resolve().parents[1] / "android" / "mushroom_forecast.py")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

class Response:
    def __enter__(self): return self
    def __exit__(self, *args): return False

def test_mixed_intervals_and_midnight():
    # Hourly 23-00 and 00-01; six-hour period 23-05 overlaps both.
    entries = []
    for hour in (23,):
        entries.append({'time':'2026-10-10T23:00:00Z', 'data': {
            'instant':{'details':{'air_temperature':10}},
            'next_1_hours':{'details':{'precipitation_amount':1}},
            'next_6_hours':{'details':{'precipitation_amount':6}}}})
    entries.append({'time':'2026-10-11T00:00:00Z','data':{
        'instant':{'details':{'air_temperature':11}},
        'next_1_hours':{'details':{'precipitation_amount':2}}}})
    entries.append({'time':'2026-10-11T06:00:00Z','data':{
        'instant':{'details':{'air_temperature':12}}}})
    class MockResponse(Response):
        def read(self): return json.dumps({'properties':{'timeseries':entries}}).encode()
    with patch.object(mod.urllib.request, 'urlopen', return_value=MockResponse()):
        # json.load reads from .read() and returns decoded dict.
        out = mod._met_norway_forecast(55.75,37.62)
    assert abs(out[date(2026,10,10)]['precip'] - 1) < 1e-8
    # 2 mm hourly + 4 mm remaining of six-hour total (6 * 4/6)
    assert abs(out[date(2026,10,11)]['precip'] - 6) < 1e-8
