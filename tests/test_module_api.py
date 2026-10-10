# -*- coding: utf-8 -*-
"""Сторож против обращений к тому, чего в модуле нет.

Появился по конкретной поломке. Правка, добавлявшая выбор файла в backup.py,
случайно затёрла заголовок соседней функции: её тело осталось лежать
недостижимым куском внутри новой, а сама функция из модуля исчезла. Все 754
теста прошли — потому что вызывается она только на Android, из окна
резервной копии, и на сборочной машине этот путь не исполняется никогда.
Человек узнал об этом из окна с трассировкой, нажав кнопку.

Здесь то же самое проверяется чтением, а не исполнением: во всех модулях
приложения ищутся обращения вида `модуль.имя`, и для своих модулей
проверяется, что такое имя в них определено. Ни Kivy, ни Android для этого
не нужны — разбирается текст.

Опечатки в именах атрибутов эта проверка ловит заодно, но главная её цель
другая: код, который на компьютере не исполняется, но на телефоне
исполняется обязательно.
"""

import ast
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apppath import APP  # noqa: E402

ROOT = APP

#: Имена, которых в модуле действительно нет, и это нормально.
#: Пусто и должно оставаться пустым: каждая запись здесь — дыра в проверке,
#: поэтому у любой обязана быть причина в комментарии.
ALLOWED = {
    # ("модуль", "имя"): "почему",
}


def _local_modules():
    return {f[:-3] for f in os.listdir(ROOT) if f.endswith(".py")}


def _tree(name):
    with open(os.path.join(ROOT, name + ".py"), encoding="utf-8") as f:
        return ast.parse(f.read(), filename=name + ".py")


def _defined(tree):
    """Имена верхнего уровня модуля.

    Обход спускается в if/try/with — там объявляют то, что зависит от
    наличия Kivy или Android, — но не внутрь функций и классов: их
    локальные имена снаружи не видны.
    """
    names = set()

    def walk(body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        names.add(t.id)
                    elif isinstance(t, (ast.Tuple, ast.List)):
                        names.update(e.id for e in t.elts
                                     if isinstance(e, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target,
                                                               ast.Name):
                names.add(node.target.id)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    names.add(a.asname or a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    names.add(a.asname or a.name)
            for field in ("body", "orelse", "finalbody"):
                inner = getattr(node, field, None)
                if inner and not isinstance(node, (ast.FunctionDef,
                                                   ast.AsyncFunctionDef,
                                                   ast.ClassDef)):
                    walk(inner)
            for handler in getattr(node, "handlers", []):
                walk(handler.body)

    walk(tree.body)
    return names


def _aliases(tree, local):
    """Псевдоним -> имя своего модуля. Чужие библиотеки не проверяются."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                base = a.name.split(".")[0]
                if base in local:
                    out[a.asname or base] = base
    return out


def _uses(tree, aliases):
    """Обращения вида «псевдоним.имя» с номерами строк."""
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in aliases):
            out.append((aliases[node.value.id], node.attr, node.lineno))
    return out


MODULES = sorted(_local_modules())


@pytest.mark.parametrize("name", MODULES)
def test_module_attributes_exist(name):
    local = _local_modules()
    tree = _tree(name)
    aliases = _aliases(tree, local)
    if not aliases:
        return
    known = {mod: _defined(_tree(mod)) for mod in set(aliases.values())}
    bad = []
    for mod, attr, line in _uses(tree, aliases):
        if attr.startswith("__") or (mod, attr) in ALLOWED:
            continue
        if attr not in known[mod]:
            bad.append(f"{name}.py:{line}: {mod}.{attr} — такого имени нет")
    assert not bad, "\n".join(bad)


def test_the_guard_would_have_caught_the_real_break(tmp_path):
    """Проверка самой проверки на том случае, ради которого она написана."""
    mod = tmp_path / "тихо.py"
    mod.write_text("def pick():\n    return 1\n", encoding="utf-8")
    caller = ast.parse("import тихо\nтихо.share(1)\n")
    defined = _defined(ast.parse(mod.read_text(encoding="utf-8")))
    aliases = _aliases(caller, {"тихо"})
    uses = _uses(caller, aliases)
    assert uses == [("тихо", "share", 2)]
    assert "share" not in defined
    assert "pick" in defined


# --------------------------------------------------------------------------- #
#  Аргументы вызовов
# --------------------------------------------------------------------------- #
#
# Существование имени — половина дела. Вторая половина: вызвать его можно
# с теми аргументами, которые написаны на месте вызова. Для кода, который
# исполняется только на телефоне, это опять же нечем проверить, кроме
# чтения: неверное число аргументов там всплывёт трассировкой в руках у
# человека, а не падением теста.

def _signature(node):
    """(обязательные, всего, есть ли *args/**kwargs, имена именованных)."""
    a = node.args
    positional = [p.arg for p in a.posonlyargs + a.args]
    required = len(positional) - len(a.defaults)
    keywords = {p.arg for p in a.args + a.kwonlyargs}
    star = bool(a.vararg or a.kwarg)
    return required, len(positional), star, keywords


def _functions(tree):
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = _signature(node)
    return out


@pytest.mark.parametrize("name", MODULES)
def test_module_calls_match_signatures(name):
    local = _local_modules()
    tree = _tree(name)
    aliases = _aliases(tree, local)
    if not aliases:
        return
    sigs = {mod: _functions(_tree(mod)) for mod in set(aliases.values())}
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                and f.value.id in aliases):
            continue
        mod = aliases[f.value.id]
        sig = sigs[mod].get(f.attr)
        if sig is None:
            continue                      # не функция или нет её — другой тест
        required, total, star, keywords = sig
        if star:
            continue
        if any(isinstance(a, ast.Starred) for a in node.args):
            continue                      # вызов через *кортеж — счёт неизвестен
        given = len(node.args)
        named = {k.arg for k in node.keywords if k.arg}
        if any(k.arg is None for k in node.keywords):
            continue                      # вызов через **словарь — не считаем
        if given > total:
            bad.append(f"{name}.py:{node.lineno}: {mod}.{f.attr} — "
                       f"{given} аргументов, принимает {total}")
        elif given + len(named & keywords) < required:
            bad.append(f"{name}.py:{node.lineno}: {mod}.{f.attr} — "
                       f"не хватает обязательных аргументов")
        unknown = named - keywords
        if unknown:
            bad.append(f"{name}.py:{node.lineno}: {mod}.{f.attr} — "
                       f"нет таких параметров: {', '.join(sorted(unknown))}")
    assert not bad, "\n".join(bad)


# --------------------------------------------------------------------------- #
#  Забытый импорт
# --------------------------------------------------------------------------- #

def _module_names(tree):
    """Имена, которые в модуле точно есть: импорты, объявления, присваивания."""
    return _defined(tree)


def _args_of(a):
    names = set()
    if a is None:
        return names
    for arg in a.posonlyargs + a.args + a.kwonlyargs:
        names.add(arg.arg)
    for extra in (a.vararg, a.kwarg):
        if extra:
            names.add(extra.arg)
    return names


def _locals_of(node):
    """Имена, живущие внутри функции: параметры, присваивания, циклы, with.

    Считаются и параметры вложенных функций: у слушателей координат
    аргумент называется location — как модуль location.py, — и без этого
    проверка ругалась на совершенно исправный код. Ложное срабатывание
    здесь опаснее пропуска: сторож, который кричит зря, отключают.
    """
    names = _args_of(getattr(node, "args", None))
    for inner in ast.walk(node):
        if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.Lambda)):
            names |= _args_of(inner.args)
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Store):
            names.add(inner.id)
        elif isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef,
                                ast.ClassDef)):
            names.add(inner.name)
        elif isinstance(inner, (ast.Import, ast.ImportFrom)):
            for al in inner.names:
                names.add(al.asname or al.name.split(".")[0])
        elif isinstance(inner, ast.ExceptHandler) and inner.name:
            names.add(inner.name)
        elif isinstance(inner, ast.comprehension):
            for t in ast.walk(inner.target):
                if isinstance(t, ast.Name):
                    names.add(t.id)
    return names


@pytest.mark.parametrize("name", MODULES)
def test_used_modules_are_imported(name):
    """Обращение к незаимпортированному модулю падает только при нажатии.

    Ровно так и вышло с `os.path.basename` в карточке похода: модуль читался,
    импортировался и проходил все тесты, потому что строка исполняется
    только по кнопке «Выгрузить» на телефоне.
    """
    local = _local_modules()
    tree = _tree(name)
    top = _module_names(tree)
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        inside = _locals_of(node)
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Attribute)
                    and isinstance(sub.value, ast.Name)
                    and isinstance(sub.value.ctx, ast.Load)):
                used = sub.value.id
                if used in local | {"os", "sys", "json", "time", "math", "re"}:
                    if used not in top and used not in inside:
                        bad.append(f"{name}.py:{sub.lineno}: {used} "
                                   f"используется, но не импортирован")
    assert not bad, "\n".join(sorted(set(bad)))


# --------------------------------------------------------------------------- #
#  Где сами тесты ищут исходники
# --------------------------------------------------------------------------- #
#
# Повод. Все тесты вычисляли путь к android/ как «каталог этого файла плюс
# ../android». Пока pytest запускали из корня проекта, это работало; в
# релизной сборке он запускается иначе, и путь превратился в каталог за
# пределами проекта. Сборка встала на сборе тестов, не дойдя ни до одной
# проверки — то есть релиз ломался ровно там, где должен был проверяться.

def test_no_test_computes_the_app_path_by_hand():
    """Путь к исходникам берётся из apppath, а не собирается заново.

    Собранный вручную путь зависит от того, откуда запущен pytest, и
    разваливается молча: половина тестов начинает проверять пустоту.
    """
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    bad = []
    for name in sorted(os.listdir(tests_dir)):
        if not name.endswith(".py") or name == "apppath.py":
            continue
        with open(os.path.join(tests_dir, name), encoding="utf-8") as f:
            lines = f.read().splitlines()
        # Ищется именно сборка пути, а не упоминание строки: иначе проверка
        # спотыкается о собственный текст и о пояснение в apppath. Образец
        # склеивается из кусков по той же причине — целиком он попал бы в
        # этот файл и сделал бы проверку самоедской.
        pattern = '"..", ' + '"android"'
        alt = "'..', " + "'android'"
        if any("os.path" in line and (pattern in line or alt in line)
               for line in lines):
            bad.append(name)
    assert not bad, "путь собирается вручную: " + ", ".join(bad)


def test_app_path_is_found_from_anywhere(tmp_path):
    """Поиск идёт от файла вверх, а не от рабочего каталога."""
    import apppath

    nested = tmp_path / "а" / "б" / "в"
    nested.mkdir(parents=True)
    assert apppath.find_app(str(os.path.abspath(__file__))) == apppath.APP
    with pytest.raises(RuntimeError):
        apppath.find_app(str(nested / "чужой.py"))


def test_app_path_checks_what_it_found(tmp_path):
    """Каталог с именем android, но без исходников, — не исходники.

    Такой лежит внутри .buildozer, и приняв его за проект, тесты молча
    проверяли бы копию, отставшую на сборку.
    """
    import apppath

    fake = tmp_path / "проект" / "android"
    fake.mkdir(parents=True)
    (fake / "main.py").write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError):
        apppath.find_app(str(tmp_path / "проект" / "тест.py"))


def test_no_stray_copies_of_tests_outside_the_tests_folder():
    """Копия файла тестов вне tests/ — источник тихой путаницы.

    Такие копии остаются от старой раскладки. Голый pytest собирал их
    наравне с настоящими, а отстав на несколько правок, они падали ещё до
    первой проверки — и сборка вставала на файлах, которых в tests/ уже нет.
    Настройка testpaths убрала это из сбора, но сам файл никуда не делся:
    человек может открыть его, поправить и не понять, почему ничего не
    меняется. Поэтому о нём говорится вслух.

    Смотрим на то, что реально закоммичено, а не на всё, что лежит на диске.
    Первая версия этой проверки обходила файловую систему и один раз
    выдала в «страйках» весь каталог tests/ целиком — оказалось, она
    цепляла нетронутый мусор вроде виртуального окружения или распакованного
    рядом архива, который pytest никогда не собирает и трогать не будет.
    Пугать человека несуществующей проблемой хуже, чем смолчать о ней:
    списку с git ls-files доверять можно, списку с диска — нет.
    """
    import subprocess

    tests_dir = os.path.dirname(os.path.abspath(__file__))
    project = os.path.dirname(tests_dir)
    ours = {n for n in os.listdir(tests_dir) if n.endswith(".py")}

    try:
        result = subprocess.run(["git", "ls-files"], cwd=project,
                                capture_output=True, text=True, timeout=10,
                                check=True)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git недоступен — нечем отличить закоммиченный "
                    "файл от постороннего мусора на диске")

    tracked = result.stdout.splitlines()
    strays = [f for f in tracked
             if not f.startswith("tests/")
             and os.path.basename(f) in ours
             and os.path.basename(f) != "__init__.py"]
    assert not strays, ("закоммичены копии файлов тестов вне tests/ — "
                        "удалите их: " + ", ".join(sorted(strays)))


# --------------------------------------------------------------------------- #
#  Чем запускаются тесты
# --------------------------------------------------------------------------- #

def test_core_tests_run_without_third_party_packages():
    """Ядро должно проверяться на голом Python.

    Настольная версия рассчитана ровно на это: человек скачивает скрипт и
    запускает его без установки чего бы то ни было. Если модель начнёт
    требовать pytest, узнать об этом надо здесь.
    """
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    for name in ("test_model.py", "test_markup.py"):
        with open(os.path.join(tests_dir, name), encoding="utf-8") as f:
            src = f.read()
        assert "import pytest" not in src, f"{name} перестал быть самостоятельным"


def test_ci_runs_the_suite_with_pytest():
    """Каталог тестов прогоняется тем, чем он написан.

    В рабочем процессе стоял `unittest discover` по всему каталогу, и с
    некоторых пор он не столько проверял, сколько падал: pytest на том шаге
    ещё не установлен, а без него из двадцати семи файлов импортируются
    два. APK при этом собирался, и красным горел шаг, который ничего не
    успевал проверить.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, ".github", "workflows", "tests.yml"),
              encoding="utf-8") as f:
        wf = f.read()
    шаги = [l for l in wf.splitlines()
            if l.strip().startswith("run:") or l.startswith("          ")]
    assert not any("unittest discover" in l for l in шаги), (
        "discover не умеет запускать pytest-тесты")
    assert "python -m pytest tests -q" in wf
    assert "unittest tests.test_model" in wf, "ядро на голом Python не проверяется"


def test_no_test_imports_kivy_before_the_skip():
    """Kivy наверху файла ломает сбор тестов на машине без него.

    Падает при этом не один модуль, а весь прогон: pytest не может собрать
    файл и прекращает работу. Машина без графики после этого не проверяет
    даже то, что окон не требует. На своей машине с Kivy такую строку не
    заметишь — она уже уезжала в CI.
    """
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    плохие = []
    for name in sorted(os.listdir(tests_dir)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(tests_dir, name), encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        # Граница — importorskip: до него Kivy трогать нельзя, после можно.
        граница = src.find('importorskip("kivy"')
        for node in tree.body:          # только верхний уровень модуля
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            имена = ([a.name for a in node.names]
                     if isinstance(node, ast.Import) else [node.module or ""])
            if not any(n.split(".")[0] == "kivy" for n in имена):
                continue
            позиция = sum(len(l) + 1 for l in src.splitlines()[:node.lineno - 1])
            if граница < 0 or позиция < граница:
                плохие.append(f"{name}:{node.lineno}")
    assert not плохие, "Kivy импортируется до пропуска: " + ", ".join(плохие)


def test_smoke_file_is_skipped_wholesale_without_kivy():
    """Падение на сборе прекращает весь прогон — этого нельзя допускать.

    Внутри дымового файла стоит importorskip, но он срабатывает, только
    если исполнение до него дошло. Один импорт Kivy выше по файлу — и
    pytest не может собрать модуль, а машина без графики перестаёт
    проверять даже то, для чего окна не нужны. Дважды так вставала
    релизная сборка. Поэтому файл отсекается на уровень выше, в conftest.
    """
    import conftest

    assert "smoke_ui_test.py" in conftest.NEEDS_KIVY
    assert conftest.pytest_ignore_collect.__doc__

    class Путь:
        def __init__(self, имя):
            self.имя = имя

        def __str__(self):
            return "/где-то/" + self.имя

    было = conftest.HAS_KIVY
    try:
        conftest.HAS_KIVY = False
        assert conftest.pytest_ignore_collect(Путь("smoke_ui_test.py"), None)
        assert not conftest.pytest_ignore_collect(Путь("test_model.py"), None)
        conftest.HAS_KIVY = True
        assert not conftest.pytest_ignore_collect(Путь("smoke_ui_test.py"), None)
    finally:
        conftest.HAS_KIVY = было
