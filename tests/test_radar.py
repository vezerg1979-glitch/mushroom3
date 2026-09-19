import os, sys
from datetime import date, timedelta
from types import SimpleNamespace
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP
sys.path.insert(0, APP)
import radar

def days(n=10):
    d=date(2026,9,18)
    return [SimpleNamespace(d=d+timedelta(days=i)) for i in range(n)]

def test_phase_cycle():
    assert radar.phase([5, 8, 12, 40, 60], 1) == 'зарождение'
    assert radar.phase([10, 25, 45, 65], 1) == 'рост'
    assert radar.phase([55, 70, 72, 68], 2) == 'пик'
    assert radar.phase([75, 60, 40, 20], 1) == 'спад'

def test_rows_sorted_by_best_week_value():
    rr=radar.rows(days(), {'A':[10,20,30,40], 'B':[20,70,30,20]}, 0)
    assert rr[0]['name']=='B' and rr[0]['best']==70

def test_text_has_species_dates_and_legend():
    s=radar.text(days(), {'Белый':[20,40,72,60], 'Лисичка':[10,15,20,25]}, 0)
    assert 'Грибной радар' in s and 'Белый' in s and '20.09' in s and '++' in s
