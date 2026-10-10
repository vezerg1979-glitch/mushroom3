import importlib.util
from pathlib import Path
from datetime import date
import urllib.error
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('weather_fallback_test', ROOT/'android'/'mushroom_forecast.py')
mod = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv('MUSHROOM_CACHE_DIR', str(tmp_path))
    days = [mod.Day(date.today(), 20, 10, 15, 5, 2, 70, 12, .25)]
    mod._cache_write(55.75, 37.62, days)
    restored, timestamp = mod._cache_read(55.75, 37.62)
    assert restored == days
    assert timestamp > 0

def test_cached_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv('MUSHROOM_CACHE_DIR', str(tmp_path))
    place = mod.Place('test', 55.75, 37.62)
    expected = [mod.Day(date.today(), 20, 10, 15, 5, 2)]
    mod._cache_write(place.lat, place.lon, expected)
    def offline(*args):
        raise urllib.error.URLError('refused')
    monkeypatch.setattr(mod, 'probe_soil_keys', offline)
    monkeypatch.setattr(mod, '_met_norway_forecast', lambda *args: (_ for _ in ()).throw(AssertionError('MET Norway must not be called when cache is valid')))
    assert mod.fetch_weather(place, 7) == expected
    assert 'Кэш' in mod.LAST_WEATHER_SOURCE

def test_no_fabricated_history(tmp_path, monkeypatch):
    monkeypatch.setenv('MUSHROOM_CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(mod, 'probe_soil_keys', lambda *args: (_ for _ in ()).throw(urllib.error.URLError('refused')))
    monkeypatch.setattr(mod, '_met_norway_forecast', lambda *args: {date.today(): {'temps':[10], 'precip':0, 'rhs':[], 'winds':[]}})
    days = mod.fetch_weather(mod.Place('test', 55.75, 37.62), 7)
    assert len(days) == mod.PAST_DAYS + 1
    assert 'ограниченный' in mod.LAST_WEATHER_SOURCE
    assert all(d.soil_w is None for d in days)
