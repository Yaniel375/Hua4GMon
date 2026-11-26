"""NetMonster-style presentation helpers (pure logic, no Kivy).

Hua4GMon talks to a Huawei router, not to the phone modem, so the data
here comes only from what the modem reports: the serving Snapshot,
the session's best cells (SignalState.top_cells) and the survey
observations (Survey.ranked). Nothing is invented: a neighbour cell
appears only if the modem reported it.

All user-visible strings go through core.i18n.t() (Russian keys), so
EN/ES translations in core/i18n.py must cover them.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from core.i18n import t
from core.models import Snapshot
from core.scanner import Observation
from core.signal_analysis import curve_score, evaluate_signal
from core.state import CellStats

LTE_PARAMS = ('rsrp', 'sinr', 'rsrq', 'rssi')
NR_PARAMS = ('nr_rsrp', 'nr_sinr')


@dataclass(frozen=True)
class SignalBar:
    """One metric row for the Monitor screen."""
    param: str
    title: str
    value: float | None
    unit: str
    pct: int
    status: str  # Russian label; the UI translates it with t()
    color: str
    explain: str  # already translated by _explain()


def _explain(param: str) -> str:
    """Short plain-language explanation of what a metric means."""
    if param == 'rsrp':
        return t("Мощность принимаемого сигнала: чем выше (ближе к нулю), тем лучше.")
    if param == 'sinr':
        return t("Отношение сигнал/шум: чем выше, тем чище сигнал.")
    if param == 'rsrq':
        return t("Качество и загрузка соты: чем выше, тем свободнее сота.")
    if param == 'rssi':
        return t("Общая мощность в канале, включая шум и помехи.")
    if param == 'cqi':
        return t("Оценка качества канала модемом: 0-15, чем выше, тем быстрее.")
    if param == 'nr_rsrp':
        return t("Мощность сигнала 5G: чем выше (ближе к нулю), тем лучше.")
    if param == 'nr_sinr':
        return t("Отношение сигнал/шум 5G: чем выше, тем чище сигнал.")
    return t("Нет данных")


def _cqi_status(cqi: int) -> tuple[str, str]:
    """Status label and colour for a CQI codeword value (0-15)."""
    if cqi >= 12:
        return "Отличный", "#00b894"
    if cqi >= 8:
        return "Хороший", "#2ecc71"
    if cqi >= 5:
        return "Средний", "#fdcb6e"
    return "Плохой", "#d63031"


def signal_bars(snap: Snapshot) -> list[SignalBar]:
    """Signal bars for RSRP/SINR/RSRQ/RSSI, CQI and NR metrics (when 5G).

    Percentage is the continuous curve score for RSRP/SINR and the
    threshold percentage from evaluate_signal() for the rest.
    """
    bars: list[SignalBar] = []
    for param in LTE_PARAMS:
        value = snap.metric(param)
        unit = "dBm" if param in ('rsrp', 'rssi') else "dB"
        if value is None:
            status, color, pct = "Нет данных", "gray", 0
        else:
            status, color, eval_pct = evaluate_signal(param, value)
            pct = int(round(curve_score(param, value))) \
                if param in ('rsrp', 'sinr') else eval_pct
        bars.append(SignalBar(param, param.upper(), value, unit, pct,
                              status, color, _explain(param)))
    if snap.cqi0 is not None:
        status, color = _cqi_status(snap.cqi0)
        bars.append(SignalBar('cqi', 'CQI', float(snap.cqi0), '',
                              round(snap.cqi0 / 15 * 100), status, color,
                              _explain('cqi')))
    if snap.has_nr:
        for param in NR_PARAMS:
            value = snap.metric(param)
            base = param.removeprefix('nr_')
            unit = "dBm" if base == 'rsrp' else "dB"
            if value is None:
                status, color, pct = "Нет данных", "gray", 0
            else:
                status, color, eval_pct = evaluate_signal(base, value)
                pct = int(round(curve_score(base, value))) \
                    if base == 'sinr' else eval_pct
            bars.append(SignalBar(param, 'NR ' + base.upper(), value, unit,
                                  pct, status, color, _explain(param)))
    return bars


def _num(value: float | int | None) -> str:
    if value is None:
        return "-"
    return str(value) if isinstance(value, int) else f"{value:g}"


def serving_cell_rows(snap: Snapshot) -> list[tuple[str, str]]:
    """(label, value) rows for the serving-cell card.

    Labels reuse the strings already used on the Info screen, so no
    new translation keys are needed for them. Only rows the modem
    actually reported are returned.
    """
    if not snap.registered:
        return []
    rows: list[tuple[str, str]] = []
    if snap.plmn:
        rows.append(("Оператор (PLMN)",
                     f"{snap.plmn} ({snap.operator})" if snap.operator else snap.plmn))
    if snap.rat:
        from core.rf import RAT_LABELS
        rows.append(("Технология", t(RAT_LABELS.get(snap.rat, snap.rat))))
    if snap.band_label and snap.band_label != '-':
        rows.append(("Рабочий Band (LTE)", snap.band_label))
    if snap.freq_mhz:
        rows.append(("Частота DL", f"{snap.freq_mhz:g}"))
    if snap.earfcn_raw:
        rows.append(("EARFCN (канал DL)", snap.earfcn_raw))
    if snap.ca is not None:
        rows.append(("Агрегация (CA)", t("Активна") if snap.ca else t("Нет")))
    bandwidth = snap.dl_bandwidth or snap.nr_bandwidth
    if bandwidth:
        rows.append(("Ширина канала", bandwidth))
    if snap.pci is not None:
        rows.append(("Сектор антенны (PCI)", _num(snap.pci)))
    if snap.cell_id is not None:
        rows.append(("Cell ID (ECI)", _num(snap.cell_id)))
    if snap.enodeb is not None:
        rows.append(("eNodeB (Вышка)", _num(snap.enodeb)))
    if snap.sector is not None:
        rows.append(("Cell (Локальный сектор)", _num(snap.sector)))
    if snap.tac:
        rows.append(("TAC (зона)", snap.tac))
    if snap.has_nr:
        rows.append(("5G NR", snap.nr_summary()))
    return rows


def carrier_lines(snap: Snapshot, mhz: str) -> list[str]:
    """One line per LTE carrier: 'B7 · EARFCN 2850 · 20 МГц'."""
    return [f"B{c.band} · EARFCN {c.earfcn} · {c.bandwidth:g} {mhz}"
            for c in snap.lte_carriers]


GOOD_THRESHOLD: dict[str, float] = {
    # 'Good' boundary per metric (second SIGNAL_THRESHOLDS rule):
    # the dashed threshold line in the Charts tab.
    'rsrp': -90, 'sinr': 13, 'rssi': -75, 'rsrq': -15,
    'nr_rsrp': -90, 'nr_sinr': 13,
}


def good_threshold(param: str) -> float | None:
    """'Good' boundary for a metric, or None if the metric has none."""
    return GOOD_THRESHOLD.get(param)


def format_plmn(plmn: str) -> str:
    """'25002' -> '250 02' (MCC + MNC), as in the NetMonster header."""
    digits = ''.join(ch for ch in plmn if ch.isdigit())
    if len(digits) in (5, 6):
        return f"{digits[:3]} {digits[3:]}"
    return plmn


def _band_freq_mhz(band: int, earfcn: int | None) -> str:
    """Band nominal frequency label ('1800', '2600'), as NetMonster shows."""
    from core.constants import LTE_BAND_TABLE
    name = LTE_BAND_TABLE.get(band, ('', '', 0.0, 0, 0))[0]
    return name.split()[0] if name else ''


def rat_line(snap: Snapshot) -> str:
    """'4G | LTE 1800 + 1800' / '5G NSA | NR n78' — NetMonster subheader."""
    rat = snap.rat
    if rat in ('nr_nsa', 'nr_sa'):
        gen = '5G'
        tech = f"NR {snap.nr_band_label}" if snap.nr_band_label else 'NR'
    elif rat in ('lte', 'lte_ca'):
        gen = '4G'
        freqs: list[str] = []
        if snap.lte_carriers:
            for carrier in snap.lte_carriers:
                freq = _band_freq_mhz(carrier.band, carrier.earfcn)
                if freq and freq not in freqs:
                    freqs.append(freq)
        elif snap.bands:
            for band in snap.bands:
                freq = _band_freq_mhz(band, snap.earfcn if band == snap.bands[0] else None)
                if freq and freq not in freqs:
                    freqs.append(freq)
        tech = 'LTE ' + ' + '.join(freqs) if freqs else 'LTE'
    elif rat == '3g':
        gen = '3G'
        if snap.bands:
            tech = _band_freq_mhz(snap.bands[0], None) or 'UMTS'
        elif snap.freq_mhz:
            tech = f"{snap.freq_mhz:g}"
        else:
            tech = 'UMTS'
    elif rat == '2g':
        gen, tech = '2G', 'GSM'
    else:
        return '-'
    return f"{gen} | {tech}"


def trend_arrow(values: list[float]) -> tuple[str, str]:
    """Trend vs the previous sample: ('▲', green) / ('▼', red) / ('', gray).

    All metrics shown here are better when higher (RSRP, RSSI, RSRQ,
    SINR), so up is good.
    """
    if len(values) < 2:
        return '', 'gray'
    last, prev = values[-1], values[-2]
    if last is None or prev is None or last == prev:
        return '', 'gray'
    return ('▲', '#00b894') if last > prev else ('▼', '#d63031')


def net_rows(snap: Snapshot) -> dict[str, tuple[str, str, str]]:
    """NetMonster two-column grid, keyed by row id.

    Left column: CI, eNb:CID, TAC, PCI. Right column: EARFCN, RSSI,
    RSRP, RSRQ, SNR (= SINR), CQI. Labels are ASCII, no translation
    needed. TA is intentionally absent: the router does not report
    timing advance.
    """
    cell_id = snap.cell_id if snap.cell_id is not None else snap.nci
    enb_cid = '-'
    if snap.enodeb is not None:
        enb_cid = f"{snap.enodeb}:{_num(snap.sector)}"
    cqi = '-'
    if snap.cqi0 is not None:
        cqi = _num(snap.cqi0)
        if snap.cqi1 is not None:
            cqi += f" / {_num(snap.cqi1)}"
    return {
        'ci': ('CI', _num(cell_id), ''),
        'enb': ('eNb:CID', enb_cid, ''),
        'tac': ('TAC', snap.tac or '-', ''),
        'pci': ('PCI', _num(snap.pci), ''),
        'earfcn': ('EARFCN', _num(snap.earfcn), ''),
        'rssi': ('RSSI', _num(snap.rssi), 'dBm'),
        'rsrp': ('RSRP', _num(snap.rsrp), 'dBm'),
        'rsrq': ('RSRQ', _num(snap.rsrq), 'dB'),
        'snr': ('SNR', _num(snap.sinr), 'dB'),
        'cqi': ('CQI', cqi, ''),
    }


def net_rows_3g(snap: Snapshot) -> dict[str, tuple[str, str, str] | None]:
    """NetMonster 3G grid, same row ids as the LTE grid.

    Left: CI / CID / RNC / LAC / PSC. Right: UARFCN / RSSI / RSCP / Ec/No.
    The router API does not report UARFCN, RSCP, Ec/No, LAC or PSC, so
    those stay '-'; CID and RNC are derived from the 3G CI
    (CI = RNC * 65536 + CID). The CQI row is hidden (None).
    """
    ci = snap.cell_id
    return {
        'ci': ('CI', _num(ci), ''),
        'enb': ('CID', _num(ci & 0xFFFF) if ci is not None else '-', ''),
        'tac': ('RNC', _num(ci >> 16) if ci is not None else '-', ''),
        'pci': ('LAC', '-', ''),
        'earfcn': ('PSC', '-', ''),
        'rssi': ('RSSI', _num(snap.rssi), 'dBm'),
        'rsrp': ('UARFCN', '-', ''),
        'rsrq': ('RSCP', '-', 'dBm'),
        'snr': ('Ec/No', '-', 'dB'),
        'cqi': None,
    }


def format_log_time(iso: str) -> str:
    """ISO datetime -> '2:47 a.m.' / '5:11 p.m.' (NetMonster log time)."""
    try:
        dt = datetime.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d} {'a.m.' if dt.hour < 12 else 'p.m.'}"


def format_log_identity(snap: Snapshot) -> str:
    """'413017:3 | 4222 | 369' (LTE) / '5:1091 | — | —' (3G, LAC/PSC
    unknown) / 'n78 · NCI … | PCI …' (NR) / 'CI 12345' (2G)."""
    if snap.rat in ('nr_nsa', 'nr_sa'):
        nci = _num(snap.nci)
        pci = _num(snap.nr_pci)
        return f"{snap.nr_band_label} · NCI {nci} | PCI {pci}"
    if snap.rat == '3g':
        ci = snap.cell_id
        if ci is None:
            return '-'
        return f"{ci >> 16}:{ci & 0xFFFF} | — | —"
    if snap.rat == '2g':
        return f"CI {_num(snap.cell_id)}"
    enb = f"{snap.enodeb}:{_num(snap.sector)}" if snap.enodeb is not None else '-'
    return f"{enb} | {snap.tac or '-'} | {_num(snap.pci)}"


def format_duration(seconds: float | None) -> str:
    """Approximate time on a band: '1:23:05', '12:34' or '0:07'."""
    if seconds is None or seconds < 0:
        return '-'
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_log_datetime(iso: str) -> str:
    """ISO datetime -> '2026-11-26 02:47' (language-neutral)."""
    try:
        dt = datetime.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return dt.strftime('%Y-%m-%d %H:%M')


def _metric_stats(obs: Observation, key: str) -> tuple[float | None, float | None, float | None]:
    """(min, median, max) of a metric over the observation, or Nones."""
    values = obs.levels.get(key, [])
    if not values:
        return None, None, None
    return obs.minima.get(key), obs.median(key), obs.maxima.get(key)


def detail_log(obs: Observation) -> dict[str, Any]:
    """Detailed per-band/per-cell log row from a real Observation.

    Everything comes from the router data already stored in the
    observation: first/last seen, band and frequency, EARFCN, identity,
    technology, sample count, min/median/max per metric, and the
    approximate duration on that band (last - first). Nothing invented:
    metrics the router never reported stay None.
    """
    snap = obs.snap
    rat = snap.rat
    tech = ('4G' if rat in ('lte', 'lte_ca') else
            '5G' if rat in ('nr_nsa', 'nr_sa') else
            '3G' if rat == '3g' else '2G' if rat == '2g' else '-')
    freq, _color = band_chip(snap)
    try:
        first_dt = datetime.datetime.fromisoformat(obs.first)
        last_dt = datetime.datetime.fromisoformat(obs.last)
        duration = (last_dt - first_dt).total_seconds()
    except ValueError:
        duration = None
    return {
        'tech': tech,
        'band': snap.band_label,
        'band_no': snap.bands[0] if snap.bands else (snap.nr_band or ''),
        'freq': freq,
        'earfcn': snap.earfcn if snap.earfcn is not None else snap.nr_arfcn,
        'identity': format_log_identity(snap),
        'enb_cid': (f"{snap.enodeb}:{snap.sector}"
                    if snap.enodeb is not None else '-'),
        'tac': snap.tac or '-',
        'pci': snap.pci if snap.pci is not None else snap.nr_pci,
        'operator': snap.operator or '-',
        'plmn': format_plmn(snap.plmn) if snap.plmn else '-',
        'first': format_log_datetime(obs.first),
        'last': format_log_datetime(obs.last),
        'duration': format_duration(duration),
        'duration_s': duration,
        'samples': obs.samples,
        'rsrp': _metric_stats(obs, 'rsrp'),
        'sinr': _metric_stats(obs, 'sinr'),
        'rsrq': _metric_stats(obs, 'rsrq'),
        'rssi': _metric_stats(obs, 'rssi'),
        'nr_rsrp': _metric_stats(obs, 'nr_rsrp'),
        'nr_sinr': _metric_stats(obs, 'nr_sinr'),
    }


def band_chip(snap: Snapshot) -> tuple[str, str]:
    """(freq label, colour) for the band chip: '900' green, others blue."""
    if not snap.bands:
        return '', '#0984e3'
    freq = _band_freq_mhz(snap.bands[0], None)
    return freq, '#00b894' if freq == '900' else '#0984e3'


def format_neighbour(cell: CellStats, current: bool = False) -> str:
    """One neighbour/best-cell line, from data the modem reported."""
    prefix = "▶ " if current else ""
    return (f"{prefix}{cell.operator_label} · {cell.band_label} · "
            f"Cell ID {_num(cell.cell_id)} · PCI {_num(cell.key.pci)} · "
            f"SINR {_num(cell.best_sinr)} · RSRP {_num(cell.best_rsrp)} · "
            f"n={cell.samples}")


def format_observation(obs: Observation) -> list[str]:
    """History lines for one survey observation (no invented cells)."""
    snap = obs.snap
    cell_id = snap.cell_id if snap.cell_id is not None else snap.nci
    head = (f"{snap.operator or snap.plmn or '-'} · "
            f"Cell ID {_num(cell_id)} · "
            f"PCI {_num(snap.pci if snap.pci is not None else snap.nr_pci)} · "
            f"{snap.band_label} · EARFCN {_num(snap.earfcn)}")
    lines = [head]
    for metric in ('sinr', 'rsrp', 'rsrq', 'rssi', 'nr_sinr', 'nr_rsrp'):
        values = obs.levels.get(metric)
        if not values:
            continue
        median = obs.median(metric)
        lines.append(
            f"{metric.upper()} med {_num(median)} "
            f"[{_num(obs.minima.get(metric))} … {_num(obs.maxima.get(metric))}]")
    lines.append(
        t("Источник: {source}; измерений: {n}; {first} — {last}").format(
            source=obs.source, n=obs.samples, first=obs.first, last=obs.last))
    return lines
