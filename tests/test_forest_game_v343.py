"""Checks for offline forest game additions without a graphical runtime."""
import ast
from pathlib import Path

GAME = Path(__file__).resolve().parents[1] / 'android' / 'forest_game.py'

def test_game_modes_and_hints_exist():
    tree = ast.parse(GAME.read_text(encoding='utf-8'))
    game = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ForestGame')
    methods = {n.name for n in game.body if isinstance(n, ast.FunctionDef)}
    assert {'set_mode', 'hint', 'next_clearing', 'restart', 'stop'} <= methods

def test_forest_notes_and_offline_only():
    src = GAME.read_text(encoding='utf-8')
    assert 'FOREST_NOTES' in src
    assert 'urllib' not in src and 'requests' not in src
