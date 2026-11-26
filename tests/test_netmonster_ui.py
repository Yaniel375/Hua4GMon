"""Pure-logic tests for the NetMonster-style presentation helpers.

No Kivy, no display: these cover core/netmonster.py only. The visual
layout (Monitor redesign, Cells screen) is deliberately NOT tested
here — it is paused until the user picks a style variant.
"""
import pytest

import core
from core.carriers import LTECarrier
from core.i18n import EN, ES, set_language, t
from core.models import CellKey, Snapshot
from core.netmonster import (
    band_chip,
    carrier_lines,
    detail_log,
    format_duration,
    format_log_datetime,
    format_log_identity,
    format_log_time,
    format_neighbour,
    format_observation,
    format_plmn,
    good_threshold,
    net_rows,
    net_rows_3g,
    rat_line,
    serving_cell_rows,
    signal_bars,
    trend_arrow,
)
from core.scanner import Observation, Survey
from core.scanner import Survey
from core.state import CellStats

EXPLANATIONS = (
    'Мощность принимаемого сигнала: чем выше (ближе к нулю), тем лучше.',
    'Отношение сигнал/шум: чем выше, тем чище сигнал.',
    'Качество и загрузка соты: чем выше, тем свободнее сота.',
    'Общая мощность в канале, включая шум и помехи.',
    'Оценка качества канала модемом: 0-15, чем выше, тем быстрее.',
    'Мощность сигнала 5G: чем выше (ближе к нулю), тем лучше.',
    'Отношение сигнал/шум 5G: чем выше, тем чище сигнал.',
)


@pytest.fixture(autouse=True)
def _ru():
    set_language('ru')
    yield
    set_language('ru')


def _serving(**kw):
    base = dict(registration='registered', connection=901, data_enabled=True,
                plmn='25002', operator='MegaFon', rat='lte_ca',
                bands=(3, 7), band_label='B3+B7', earfcn_raw='1300',
                earfcn=1300, freq_mhz=1815.0, pci=114, cell_id=123456,
                enodeb=482, sector=0, tac='12345', dl_bandwidth='20MHz',
                ca=True)
    base.update(kw)
    return Snapshot(**base)


def test_serving_cell_rows_from_snapshot():
    rows = dict(serving_cell_rows(_serving()))
    assert rows['eNodeB (Вышка)'] == '482'
    assert rows['Cell ID (ECI)'] == '123456'
    assert rows['Сектор антенны (PCI)'] == '114'
    assert rows['TAC (зона)'] == '12345'
    assert rows['EARFCN (канал DL)'] == '1300'
    assert rows['Частота DL'] == '1815'
    assert rows['Рабочий Band (LTE)'] == 'B3+B7'
    assert rows['Агрегация (CA)'] == 'Активна'
    assert '5G NR' not in rows


def test_serving_cell_rows_5g_and_unregistered():
    snap = _serving(rat='nr_nsa', nr_rsrp=-95, nr_sinr=9, nr_arfcn=627264,
                    nr_pci=501, nr_band='78', nr_bandwidth='100MHz')
    rows = dict(serving_cell_rows(snap))
    assert rows['5G NR'].startswith('n78')
    assert '627264' in rows['5G NR']
    assert serving_cell_rows(Snapshot(registration='unregistered')) == []


def test_signal_bars_lte_and_cqi():
    snap = _serving(rsrp=-85, sinr=15, rsrq=-10, rssi=-70, cqi0=12, cqi1=11)
    bars = {b.param: b for b in signal_bars(snap)}
    assert set(bars) == {'rsrp', 'sinr', 'rsrq', 'rssi', 'cqi'}
    assert bars['rsrp'].value == -85 and bars['rsrp'].unit == 'dBm'
    assert 0 < bars['rsrp'].pct <= 100
    assert bars['sinr'].status == 'Хороший'
    assert bars['cqi'].pct == 80 and bars['cqi'].status == 'Отличный'
    for bar in bars.values():
        assert bar.explain and bar.color


def test_signal_bars_nr_only_with_5g_and_missing_values():
    snap = _serving(rsrp=None, sinr=None, rsrq=None, rssi=None)
    bars = {b.param: b for b in signal_bars(snap)}
    assert 'nr_rsrp' not in bars
    assert all(b.pct == 0 and b.status == 'Нет данных' for b in bars.values())
    snap5g = _serving(rsrp=-90, sinr=10, rsrq=-12, rssi=-80,
                      nr_rsrp=-95, nr_sinr=9)
    bars5g = {b.param: b for b in signal_bars(snap5g)}
    assert bars5g['nr_rsrp'].value == -95
    assert bars5g['nr_sinr'].value == 9


def test_signal_explanations_translated():
    for lang in ('en', 'es'):
        set_language(lang)
        snap = _serving(rsrp=-85, sinr=15, rsrq=-10, rssi=-70, cqi0=12)
        explains = [b.explain for b in signal_bars(snap)]
        assert len(explains) == 5
        assert all(e and e not in EXPLANATIONS for e in explains), explains
    for key in EXPLANATIONS:
        assert key in EN and key in ES
        assert EN[key] != key and ES[key] != key


def test_carrier_lines():
    snap = _serving(lte_carriers=(LTECarrier(7, 2850, 20.0),
                                  LTECarrier(3, 1300, 10.0)))
    lines = carrier_lines(snap, t('МГц'))
    assert lines == ['B7 · EARFCN 2850 · 20 МГц', 'B3 · EARFCN 1300 · 10 МГц']
    assert carrier_lines(_serving(), t('МГц')) == []


def test_neighbour_ranking_and_format():
    survey = Survey()
    survey.start()
    weak = Snapshot(registration='registered', plmn='25002', cell_id=111,
                    earfcn=1300, pci=1, sinr=2, rsrp=-115, rsrq=-16)
    strong = Snapshot(registration='registered', plmn='25002', cell_id=222,
                      earfcn=1300, pci=2, sinr=18, rsrp=-85, rsrq=-9)
    survey.observe(weak)
    survey.observe(strong)
    ranked = survey.ranked()
    assert ranked[0].snap.cell_id == 222
    assert ranked[0].median('sinr') == 18
    lines = format_observation(ranked[0])
    assert 'Cell ID 222' in lines[0] and 'PCI 2' in lines[0]
    assert any(l.startswith('SINR med 18') for l in lines)
    assert any('Источник:' in l and 'измерений: 1' in l for l in lines)


def test_format_neighbour_marks_current_cell():
    cell = CellStats(key=CellKey(1300, 114, 123456), band_label='B3',
                     enodeb=482, sector=0, plmn='25002', operator='MegaFon',
                     best_sinr=18, best_rsrp=-85, samples=5, cell_id=123456)
    text = format_neighbour(cell, current=True)
    assert text.startswith('▶ ')
    assert 'Cell ID 123456' in text and 'PCI 114' in text
    assert 'SINR 18' in text and 'RSRP -85' in text and 'n=5' in text
    assert not format_neighbour(cell).startswith('▶ ')


def test_netmonster_helpers_are_exported_from_core():
    assert core.signal_bars is signal_bars
    assert core.serving_cell_rows is serving_cell_rows
    assert core.carrier_lines is carrier_lines


def test_format_plmn_and_rat_line():
    assert format_plmn('36801') == '368 01'
    assert format_plmn('25002') == '250 02'
    assert format_plmn('') == ''
    assert rat_line(_serving()) == '4G | LTE 1800 + 2600'
    single = _serving(bands=(3,), band_label='B3')
    assert rat_line(single) == '4G | LTE 1800'
    ca = _serving(lte_carriers=(LTECarrier(3, 1300, 20.0),
                                LTECarrier(7, 2850, 20.0)))
    assert rat_line(ca) == '4G | LTE 1800 + 2600'
    nr = _serving(rat='nr_nsa', nr_rsrp=-95, nr_band='78')
    assert rat_line(nr) == '5G | NR n78'
    assert rat_line(Snapshot()) == '-'


def test_net_rows_screenshot_layout():
    rows = net_rows(_serving(rsrp=-77, rssi=-51, rsrq=-10, sinr=10,
                             cqi0=12, cqi1=11))
    assert rows['ci'] == ('CI', '123456', '')
    assert rows['enb'] == ('eNb:CID', '482:0', '')
    assert rows['tac'] == ('TAC', '12345', '')
    assert rows['pci'] == ('PCI', '114', '')
    assert rows['earfcn'] == ('EARFCN', '1300', '')
    assert rows['rssi'] == ('RSSI', '-51', 'dBm')
    assert rows['rsrp'] == ('RSRP', '-77', 'dBm')
    assert rows['rsrq'] == ('RSRQ', '-10', 'dB')
    assert rows['snr'] == ('SNR', '10', 'dB')
    assert rows['cqi'] == ('CQI', '12 / 11', '')
    assert 'ta' not in rows  # the router does not report timing advance


def test_net_rows_3g_and_log_helpers():
    snap = Snapshot(rat='3g', cell_id=328771, rssi=-113)
    rows = net_rows_3g(snap)
    assert rows['ci'] == ('CI', '328771', '')
    assert rows['enb'] == ('CID', '1091', '')
    assert rows['tac'] == ('RNC', '5', '')
    assert rows['pci'] == ('LAC', '-', '')
    assert rows['earfcn'] == ('PSC', '-', '')
    assert rows['rssi'] == ('RSSI', '-113', 'dBm')
    assert rows['rsrp'] == ('UARFCN', '-', '')
    assert rows['rsrq'] == ('RSCP', '-', 'dBm')
    assert rows['snr'] == ('Ec/No', '-', 'dB')
    assert rows['cqi'] is None  # no CQI in 3G: row hidden
    assert format_log_identity(_serving()) == '482:0 | 12345 | 114'
    assert format_log_identity(snap) == '5:1091 | — | —'
    assert format_log_time('2026-11-26T02:47:00') == '2:47 a.m.'
    assert format_log_time('2026-11-26T17:11:00') == '5:11 p.m.'
    assert format_log_time('not-a-date') == 'not-a-date'
    assert band_chip(_serving(bands=(8,))) == ('900', '#00b894')
    assert band_chip(_serving(bands=(3,))) == ('1800', '#0984e3')
    assert band_chip(Snapshot()) == ('', '#0984e3')


def test_trend_arrow():
    assert trend_arrow([-90, -85]) == ('▲', '#00b894')
    assert trend_arrow([-85, -90]) == ('▼', '#d63031')
    assert trend_arrow([-85]) == ('', 'gray')
    assert trend_arrow([-85, -85]) == ('', 'gray')


def test_good_threshold():
    assert good_threshold('rsrp') == -90
    assert good_threshold('sinr') == 13
    assert good_threshold('rssi') == -75
    assert good_threshold('rsrq') == -15
    assert good_threshold('nr_rsrp') == -90
    assert good_threshold('cqi') is None


def _obs_lte():
    base = dict(registration='registered', rat='lte', cell_id=123456,
                enodeb=482, sector=0, tac='12345', pci=114, earfcn=1300,
                bands=(3,), band_label='B3', operator='CUBACEL CU',
                plmn='36801', connection=901, data_enabled=True)
    first = Snapshot(**base, rsrp=-100, sinr=5, rsrq=-12, rssi=-80)
    obs = Observation(first, 'device/signal',
                      '2026-11-26T01:00:00', '2026-11-26T01:00:00')
    obs.add(Snapshot(**base, rsrp=-90, sinr=10, rsrq=-10, rssi=-70),
            '2026-11-26T01:30:00')
    obs.add(Snapshot(**base, rsrp=-80, sinr=15, rsrq=-8, rssi=-60),
            '2026-11-26T02:00:00')
    return obs


def test_detail_log_lte():
    d = detail_log(_obs_lte())
    assert d['tech'] == '4G'
    assert d['band'] == 'B3'
    assert d['band_no'] == 3
    assert d['freq'] == '1800'
    assert d['earfcn'] == 1300
    assert d['identity'] == '482:0 | 12345 | 114'
    assert d['enb_cid'] == '482:0'
    assert d['tac'] == '12345'
    assert d['pci'] == 114
    assert d['operator'] == 'CUBACEL CU'
    assert d['plmn'] == '368 01'
    assert d['first'] == '2026-11-26 01:00'
    assert d['last'] == '2026-11-26 02:00'
    assert d['duration'] == '1:00:00'
    assert d['duration_s'] == 3600.0
    assert d['samples'] == 2
    assert d['rsrp'] == (-90, -85.0, -80)
    assert d['sinr'] == (10, 12.5, 15)
    assert d['rsrq'] == (-10, -9.0, -8)
    assert d['rssi'] == (-70, -65.0, -60)
    assert d['nr_rsrp'] == (None, None, None)


def test_detail_log_3g_2g_and_durations():
    snap3g = Snapshot(rat='3g', cell_id=328771, rssi=-113, bands=(8,),
                      band_label='B8', operator='CUBACEL CU', plmn='36801')
    obs = Observation(snap3g, 'device/signal',
                      '2026-11-26T02:00:00', '2026-11-26T02:00:00')
    d = detail_log(obs)
    assert d['tech'] == '3G'
    assert d['identity'] == '5:1091 | — | —'
    assert d['rsrp'] == (None, None, None)  # the router reports no RSCP
    assert d['rssi'] == (None, None, None)  # levels fill only via add()
    assert d['duration'] == '0:00'
    assert format_log_identity(Snapshot(rat='2g', cell_id=12345)) == 'CI 12345'
    assert format_duration(3661) == '1:01:01'
    assert format_duration(754) == '12:34'
    assert format_duration(7) == '0:07'
    assert format_duration(None) == '-'
    assert format_duration(-5) == '-'
    assert format_log_datetime('2026-11-26T02:47:00') == '2026-11-26 02:47'
    assert format_log_datetime('bad') == 'bad'


def test_band_log_csv():
    survey = Survey()
    survey.running = True
    base = dict(registration='registered', rat='lte', cell_id=123456,
                enodeb=482, sector=0, tac='12345', pci=114, earfcn=1300,
                bands=(3,), band_label='B3', operator='CUBACEL CU',
                plmn='36801', connection=901, data_enabled=True)
    for rsrp, sinr in ((-100, 5), (-90, 10), (-80, 15)):
        survey.observe(Snapshot(**base, rsrp=rsrp, sinr=sinr,
                                rsrq=-10, rssi=-70))
    csv = survey.band_log_csv('es')
    lines = csv.splitlines()
    header = lines[0].split(';')
    for col in ('tech', 'band', 'freq_mhz', 'earfcn', 'identity', 'enb_cid',
                'tac', 'pci', 'operator', 'plmn', 'first', 'last',
                'duration_s', 'samples', 'rsrp_min', 'rsrp_median',
                'rsrp_max', 'sinr_min', 'sinr_median', 'sinr_max'):
        assert col in header, col
    assert len(lines) == 2
    row = lines[1]
    assert '4G' in row and 'B3' in row and '1800' in row
    assert '482:0 | 12345 | 114' in row
    assert 'CUBACEL CU' in row
    assert '36801' in row or '368 01' in row
    assert '-90' in row  # RSRP median of -100, -90, -80
