"""Regression: the daily forecast must remain reachable on short screens."""
import ast
from pathlib import Path


def test_portrait_scrolls_entire_page_including_daily_calendar():
    source = (Path(__file__).resolve().parents[1] / "android" / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    arrange = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_arrange")
    portrait = next(n for n in ast.walk(arrange) if isinstance(n, ast.If) and isinstance(n.test, ast.UnaryOp) and isinstance(n.test.op, ast.Not))
    body = ast.get_source_segment(source, portrait)
    assert 'root = ScrollView(' in body
    assert 'content.bind(minimum_height=content.setter("height"))' in body
    assert 'content.add_widget(self.list)' in body
    assert 'root.add_widget(content)' in body
