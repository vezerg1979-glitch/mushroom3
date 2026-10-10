"""Автоматический аудит физической направленности модели прогноза.

Не подбирает коэффициенты и не обучается по журналу. Модуль прогоняет
синтетические сценарии и ищет парадоксы: немонотонный дождевой отклик,
неправильный температурный максимум, усиление сигнала после засухи и
несогласованный пик лаг-ядра.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import mushroom_forecast as engine


@dataclass(frozen=True)
class AuditIssue:
    species: str
    check: str
    detail: str


def _days(n: int, rain: float, t: float) -> list[engine.Day]:
    start = date(2026, 8, 1)
    return [engine.Day(start + timedelta(days=i), t + 5, t - 5, t, rain,
                       2.5, None, None, None) for i in range(n)]


def audit_species(sp: engine.Species) -> list[AuditIssue]:
    issues: list[AuditIssue] = []

    # 1. Температурная кривая должна иметь максимум около t_opt и плавно
    # ослабевать по обе стороны.
    temps = [sp.t_opt + x for x in (-12, -8, -4, 0, 4, 8, 12)]
    tf = [engine.thermal_factor(sp, 13, [t] * 14) for t in temps]
    if tf[3] + 1e-12 < max(tf):
        issues.append(AuditIssue(sp.name, "temperature_peak",
                                 f"максимум не около t_opt: {tf}"))
    if not all(a <= b + 1e-12 for a, b in zip(tf[:3], tf[1:4])) or \
       not all(a >= b - 1e-12 for a, b in zip(tf[3:], tf[4:])):
        issues.append(AuditIssue(sp.name, "temperature_shape",
                                 f"немонотонные плечи: {tf}"))

    # 2. При одинаковом влагозапасе усиление устойчивого дождя не должно
    # уменьшать дождевой триггер.
    rain_levels = (0, 0.5, 1, 2, 4, 8, 15, 30)
    pulses = []
    for r in rain_levels:
        ds = _days(max(24, sp.rain_memory + 2), r, sp.t_opt)
        m = [sp.m_opt] * len(ds)
        pulses.append(engine.effective_rain_pulse(sp, ds, m)[-1])
    if any(b + 1e-10 < a for a, b in zip(pulses, pulses[1:])):
        issues.append(AuditIssue(sp.name, "rain_monotonicity",
                                 f"дождь усилился, сигнал снизился: {pulses}"))

    # 3. Засуха при одинаковом свежем слабом дожде не должна улучшать сигнал.
    n = max(24, sp.drought_days + 5)
    wet = _days(n, 0.0, sp.t_opt)
    dry = _days(n, 0.0, sp.t_opt)
    # одинаковый свежий импульс в последние двое суток
    for seq in (wet, dry):
        for k in (-2, -1):
            seq[k].precip = 2.0
    m_wet = [sp.m_opt] * n
    m_dry = [max(0.02, sp.m_min * 0.35)] * n
    m_dry[-2:] = [sp.m_min * 0.8, sp.m_min * 0.9]
    pw = engine.effective_rain_pulse(sp, wet, m_wet)[-1]
    pd = engine.effective_rain_pulse(sp, dry, m_dry)[-1]
    if pd > pw + 1e-10:
        issues.append(AuditIssue(sp.name, "drought_direction",
                                 f"после засухи {pd:.3f} > влажного фона {pw:.3f}"))

    # 4. Пик дискретного lag-ядра должен находиться рядом с заданным lag_peak.
    kernel = engine.lag_kernel(sp)
    actual = sp.lag_min + max(range(len(kernel)), key=kernel.__getitem__)
    expected = sp.lag_min + sp.lag_peak * max(1, sp.lag_max - sp.lag_min)
    if abs(actual - expected) > 1.1:
        issues.append(AuditIssue(sp.name, "lag_peak",
                                 f"пик {actual} сут, ожидается около {expected:.1f}"))
    return issues


def run_audit() -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for sp in engine.SPECIES.values():
        issues.extend(audit_species(sp))
    return issues



@dataclass(frozen=True)
class MatrixSummary:
    """Сводка многомерного аудита для одного вида."""
    species: str
    scenarios: int
    min_growth: float
    max_growth: float
    dominance_checks: int


def _combo_growth(sp: engine.Species, temp_offset: float, rain: float,
                  moisture: float, drought: bool) -> float:
    """Отклик закладки для контролируемого сочетания факторов."""
    n = max(28, sp.rain_memory + 4, sp.drought_days + 6)
    ds = _days(n, 0.0, sp.t_opt + temp_offset)
    # Одинаковый свежий дождь; предыстория меняется только флагом drought.
    for k in (-3, -2, -1):
        ds[k].precip = rain / 3.0
    if drought:
        m = [max(0.02, sp.m_min * 0.35)] * n
        m[-3:] = [moisture] * 3
    else:
        m = [moisture] * n
    ts = [sp.t_opt + temp_offset] * n
    return engine.growth_rate(sp, m, ts, ds)[-1]


def audit_matrix_species(sp: engine.Species) -> tuple[list[AuditIssue], MatrixSummary]:
    """Проверяет совместное действие температуры, дождя, влаги и засухи.

    В отличие от осевых тестов ``audit_species`` здесь сравниваются соседние
    точки одной многомерной сетки. Проверяются только отношения доминирования,
    которые должны выполняться независимо от конкретных коэффициентов модели.
    """
    issues: list[AuditIssue] = []
    temp_offsets = (-8.0, -4.0, 0.0, 4.0, 8.0)
    rains = (0.0, sp.rain_trigger_min, sp.rain_trigger_full,
             sp.rain_trigger_full * 1.6)
    moistures = (max(0.03, sp.m_min * 0.75), sp.m_min,
                 (sp.m_min + sp.m_opt) / 2.0, sp.m_opt)
    droughts = (False, True)

    grid: dict[tuple[float, float, float, bool], float] = {}
    for toff in temp_offsets:
        for rain in rains:
            for moisture in moistures:
                for drought in droughts:
                    grid[(toff, rain, moisture, drought)] = _combo_growth(
                        sp, toff, rain, moisture, drought)

    checks = 0
    eps = 1e-10
    # Больше дождя при прочих равных не должно ухудшать закладку.
    for toff in temp_offsets:
        for moisture in moistures:
            for drought in droughts:
                vals = [grid[(toff, r, moisture, drought)] for r in rains]
                checks += len(vals) - 1
                if any(b + eps < a for a, b in zip(vals, vals[1:])):
                    issues.append(AuditIssue(sp.name, "matrix_rain",
                                             f"T={toff:+g}, M={moisture:.2f}: {vals}"))
                    break

    # Влагозапас до оптимума не должен уменьшать отклик.
    for toff in temp_offsets:
        for rain in rains:
            for drought in droughts:
                vals = [grid[(toff, rain, m, drought)] for m in moistures]
                checks += len(vals) - 1
                if any(b + eps < a for a, b in zip(vals, vals[1:])):
                    issues.append(AuditIssue(sp.name, "matrix_moisture",
                                             f"T={toff:+g}, R={rain:g}: {vals}"))
                    break

    # При симметричных отклонениях от оптимума более близкая температура
    # не должна давать меньший отклик.
    for rain in rains:
        for moisture in moistures:
            for drought in droughts:
                for far, near in ((-8.0, -4.0), (8.0, 4.0)):
                    checks += 1
                    if grid[(near, rain, moisture, drought)] + eps < grid[(far, rain, moisture, drought)]:
                        issues.append(AuditIssue(
                            sp.name, "matrix_temperature",
                            f"R={rain:g}, M={moisture:.2f}: |dT|=4 хуже |dT|=8"))

    # Засуха не должна улучшать идентичный свежий сценарий.
    for toff in temp_offsets:
        for rain in rains:
            for moisture in moistures:
                checks += 1
                wet = grid[(toff, rain, moisture, False)]
                dry = grid[(toff, rain, moisture, True)]
                if dry > wet + eps:
                    issues.append(AuditIssue(sp.name, "matrix_drought",
                                             f"T={toff:+g}, R={rain:g}, M={moisture:.2f}: {dry:.4f}>{wet:.4f}"))

    vals = list(grid.values())
    return issues, MatrixSummary(sp.name, len(grid), min(vals), max(vals), checks)


def run_matrix_audit() -> tuple[list[AuditIssue], list[MatrixSummary]]:
    issues: list[AuditIssue] = []
    summaries: list[MatrixSummary] = []
    for sp in engine.SPECIES.values():
        found, summary = audit_matrix_species(sp)
        issues.extend(found)
        summaries.append(summary)
    return issues, summaries


@dataclass(frozen=True)
class SequenceSummary:
    """Сводка аудита временных погодных последовательностей."""
    species: str
    scenarios: int
    checks: int
    peak_lag_days: float


def _sequence(sp: engine.Species, pattern: str) -> tuple[list[engine.Day], list[float], list[float], int]:
    """Строит контролируемую 56-суточную последовательность; event — день 30."""
    n, event = 56, 30
    start = date(2026, 8, 1)
    rain = [0.0] * n
    temp = [sp.t_opt] * n
    moisture = [sp.m_opt * 0.92] * n

    if pattern == "dry_control":
        moisture = [max(0.03, sp.m_min * 0.55)] * n
    elif pattern == "single_shower":
        rain[event] = max(18.0, sp.rain_trigger_full)
    elif pattern == "steady_rain":
        total = max(18.0, sp.rain_trigger_full)
        for j in range(event - 2, event + 3):
            rain[j] = total / 5.0
    elif pattern == "drought_then_rain":
        moisture = [max(0.03, sp.m_min * 0.38)] * n
        for j in range(event - 2, event + 2):
            rain[j] = max(6.0, sp.rain_trigger_full / 3.0)
        for j in range(event, n):
            moisture[j] = min(sp.m_opt, sp.m_min + (j-event+1) * 0.035)
    elif pattern == "rain_then_heat":
        for j in range(event - 1, event + 2):
            rain[j] = max(6.0, sp.rain_trigger_full / 3.0)
        for j in range(event + 1, n):
            temp[j] = sp.t_opt + 10.0
    elif pattern == "rain_then_cool":
        for j in range(event - 1, event + 2):
            rain[j] = max(6.0, sp.rain_trigger_full / 3.0)
        for j in range(event + 1, n):
            temp[j] = sp.t_opt - 7.0
    else:
        raise ValueError(pattern)

    ds = [engine.Day(start + timedelta(days=i), temp[i] + 5, temp[i] - 5,
                     temp[i], rain[i], 2.5, None, None, None) for i in range(n)]
    return ds, moisture, temp, event


def audit_sequences_species(sp: engine.Species) -> tuple[list[AuditIssue], SequenceSummary]:
    """Проверяет причинность и гладкость отклика на реальные погодные цепочки."""
    patterns = ("dry_control", "single_shower", "steady_rain", "drought_then_rain",
                "rain_then_heat", "rain_then_cool")
    curves: dict[str, tuple[list[float], int]] = {}
    issues: list[AuditIssue] = []
    checks = 0
    eps = 1e-10

    for pattern in patterns:
        ds, m, ts, event = _sequence(sp, pattern)
        curve = engine.growth_rate(sp, m, ts, ds)
        curves[pattern] = (curve, event)
        checks += len(curve)
        if any((v != v) or v < -eps or v > 1.0 + eps for v in curve):
            issues.append(AuditIssue(sp.name, "sequence_bounds", pattern))
        # Физический сигнал не должен иметь резких одиночных разрывов.
        jumps = [abs(b-a) for a, b in zip(curve, curve[1:])]
        if jumps and max(jumps) > 0.80:
            issues.append(AuditIssue(sp.name, "sequence_jump",
                                     f"{pattern}: max Δ={max(jumps):.3f}"))

    # После одиночного дождя максимум причинного отклика должен быть после события,
    # а не до него, и лежать в разумном окне биологического лага.
    curve, event = curves["single_shower"]
    lo = event + max(0, sp.lag_min - 2)
    hi = min(len(curve), event + sp.lag_max + 4)
    post_peak = lo + max(range(max(1, hi-lo)), key=lambda k: curve[lo+k])
    checks += 2
    pre = max(curve[max(0, event-8):event] or [0.0])
    if curve[post_peak] + eps < pre:
        issues.append(AuditIssue(sp.name, "sequence_causality",
                                 f"после дождя пик {curve[post_peak]:.3f} < фона {pre:.3f}"))
    if not (event <= post_peak <= event + sp.lag_max + 3):
        issues.append(AuditIssue(sp.name, "sequence_peak_lag",
                                 f"пик через {post_peak-event} сут"))

    # Жара после одинакового дождя не должна усиливать отклик относительно
    # температуры около видового оптимума (single_shower — оптимальный фон).
    hot, _ = curves["rain_then_heat"]
    base, _ = curves["single_shower"]
    window = slice(event + sp.lag_min, min(len(base), event + sp.lag_max + 4))
    checks += 1
    if max(hot[window] or [0.0]) > max(base[window] or [0.0]) + eps:
        issues.append(AuditIssue(sp.name, "sequence_heat",
                                 "жара после дождя усилила отклик"))

    return issues, SequenceSummary(sp.name, len(patterns), checks, float(post_peak-event))


def run_sequence_audit() -> tuple[list[AuditIssue], list[SequenceSummary]]:
    issues: list[AuditIssue] = []
    summaries: list[SequenceSummary] = []
    for sp in engine.SPECIES.values():
        found, summary = audit_sequences_species(sp)
        issues.extend(found)
        summaries.append(summary)
    return issues, summaries


if __name__ == "__main__":
    found = run_audit()
    matrix_found, matrix_summaries = run_matrix_audit()
    sequence_found, sequence_summaries = run_sequence_audit()
    found.extend(matrix_found)
    found.extend(sequence_found)
    if found:
        for x in found:
            print(f"{x.species}: {x.check}: {x.detail}")
        raise SystemExit(1)
    total = sum(x.scenarios for x in matrix_summaries)
    matrix_checks = sum(x.dominance_checks for x in matrix_summaries)
    seq_total = sum(x.scenarios for x in sequence_summaries)
    seq_checks = sum(x.checks for x in sequence_summaries)
    print(f"OK: {len(engine.SPECIES)} видов, {total} комбинаций/{matrix_checks} сравнений, "
          f"{seq_total} временных сценариев/{seq_checks} проверок, парадоксов не обнаружено")
