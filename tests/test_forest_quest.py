import ast
from pathlib import Path
p=Path(__file__).resolve().parents[1]/"android/forest_quest.py"
def test_quest_syntax(): ast.parse(p.read_text(encoding="utf8"))
def test_quest_assets():
 for name in ("trail","spruce","lake","clearing","storm"):
  assert (p.parent/"assets/forest_quest"/(name+".jpg")).is_file()
