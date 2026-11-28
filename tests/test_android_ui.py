"""Сквозной тест Android-интерфейса (Kivy) в тестовом режиме.

Запускается, если установлен Kivy и есть дисплей (локально:
xvfb-run pytest). Платформенные вызовы Android (pyjnius) на десктопе
отключаются сами — проверяется вся логика UI поверх core.
"""
import os
import sys
import time

import pytest

if sys.platform != "win32" and not os.environ.get("DISPLAY"):
    pytest.skip("нет дисплея для Kivy", allow_module_level=True)
os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")
os.environ.setdefault("KIVY_LOG_MODE", "PYTHON")
pytest.importorskip("kivy")

import core  # noqa: E402
import core.demo as demo_mod  # noqa: E402
import core.router as router_mod  # noqa: E402


@pytest.fixture(scope="module")
def app():
    patches = [(router_mod, "RECONNECT_DELAY_INITIAL", 0.05),
               (router_mod, "RECONNECT_DELAY_MAX", 0.1),
               (demo_mod, "REBOOT_SECONDS", 0.5),
               (demo_mod, "REREGISTER_SECONDS", 0.1)]
    saved = [(m, n, getattr(m, n)) for m, n, _ in patches]
    for m, n, v in patches:
        setattr(m, n, v)
    import android_main
    core.set_language("ru")
    a = android_main.Hua4GMonApp()
    a._run_prepare()
    a.confirm = lambda title, msg, yes, on_yes: on_yes()   # «Да» в диалогах
    yield a
    a.disconnect()
    a.stop()
    for m, n, v in saved:
        setattr(m, n, v)
    core.set_language("ru")


def pump(cond, timeout=10.0):
    from kivy.base import EventLoop
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        EventLoop.idle()
        if cond():
            return True
        time.sleep(0.02)
    return False


def ensure_online(app):
    if app.link != 'online':
        app.start_demo()
    assert pump(lambda: app.link == 'online' and len(app.state.log) >= 3)


def test_starts_on_connection_screen(app):
    assert app.sm.current == 'connection'


def test_invalid_ip_shows_error(app):
    scr = app.sm.get_screen('connection')
    scr.ids.ip_input.text = "300.1.1.1"
    scr.on_connect()
    assert app.worker is None
    assert "300.1.1.1" in scr.ids.status_lbl.text


def test_monitor_shows_live_data(app):
    """La pestaña Señal nueva muestra los datos reales del demo."""
    ensure_online(app)
    scr = app.sm.get_screen('monitor')
    ids = scr.ids
    assert app.sm.current == 'monitor'
    # Cabecera del operador.
    assert ids.op_name_lbl.text == 'MegaFon'
    assert ids.plmn_lbl.text == '250 02'
    assert ids.op_sub_lbl.text == 'ОПЕРАТОР · RU · DEMO'  # D6: modo de prueba
    import android_main
    assert ids.tech_chip_lbl.text == android_main._tech_chip(app.state.last.rat)
    assert scr.anchor_visible and 'LTE 1800' in ids.anchor_lbl.text
    # INFORMACIÓN LTE con los datos del demo.
    assert ids.ci_row.value == '46111500'
    assert ids.enb_row.value == '180123:12'
    assert ids.tac_row.value == '12345'
    assert ids.pci_row.value == '287'
    assert ids.earfcn_row.value == '1300'
    assert ids.banda_row.value != '—'
    assert ids.ancho_row.value != '—'
    assert ids.modo_row.value in ('FDD', 'TDD')
    # Fila en vivo: en el demo dice DEMO.
    assert ids.live_lbl.text == core.t(
        "Тестовый режим · демонстрационные данные").upper()
    # Tarjetas de métricas y SALUD DE SEÑAL con valores reales.
    for param in ('sinr', 'rsrp', 'rsrq', 'rssi'):
        card = ids[f'{param}_card']
        assert card.m_value != '—'
        assert card.m_status.startswith('●')
        assert 0 < card.m_pct <= 100
        assert card.m_peak
    assert ids.health_ring.pct_text.endswith('%')
    assert ids.health_ring.pct == int(ids.health_ring.pct_text.rstrip('%'))
    assert ids.health_lbl.text
    # El demo no entrega portadoras: la sección CA no se inventa.
    assert not scr.ca_visible


def test_graph_param_changes_graph(app):
    """El selector de parámetro cambia el gráfico de tendencia."""
    ensure_online(app)
    ids = app.sm.get_screen('monitor').ids
    app.set_graph_param('rsrp')
    assert app.state.trend_param == 'rsrp'
    assert ids.signal_graph._param == 'rsrp'
    app.set_graph_param('sinr')
    assert app.state.trend_param == 'sinr'
    assert ids.signal_graph._param == 'sinr'


def _nav_items(app, screen):
    """Accesos de la barra inferior de una pantalla, por destino."""
    bar = app.sm.get_screen(screen).ids.nav_bar
    return {item.target: item for item in bar.children}


def test_signal_screen_has_no_sound_button(app):
    """La pantalla Señal ya no tiene botón de sonido: solo Picos y la barra.

    Etapa 5: la píldora Menú se fue a la barra inferior; Picos queda
    como única píldora y el acceso Menú vive en la barra.
    """
    from kivy.uix.button import Button
    ensure_online(app)
    scr = app.sm.get_screen('monitor')
    texts = [w.text for w in scr.walk() if isinstance(w, Button)]
    assert not any('Звук' in text for text in texts)
    assert any('Пики' in text for text in texts)
    assert not hasattr(scr, 'lbl_sound')
    assert _nav_items(app, 'monitor')['menu'].label == 'Меню'


def test_bottom_nav_present_on_main_screens(app):
    """Etapa 5: barra inferior en Señal, Información y Red; no en Conexión."""
    from kivy.metrics import dp
    ensure_online(app)
    for name, section in (('monitor', 'monitor'), ('info', 'info'),
                          ('tools', 'tools')):
        bar = app.sm.get_screen(name).ids.get('nav_bar')
        assert bar is not None, name
        assert bar.section == section
        assert bar.height == dp(64)
        # Margen inferior de 8 dp (área segura) igual en las tres.
        assert bar.y == pytest.approx(dp(8))
    assert 'nav_bar' not in app.sm.get_screen('connection').ids


def test_bottom_nav_items_navigate(app):
    """Etapa 5: cada acceso navega a su pantalla; Menú abre la hoja."""
    from kivy.core.window import Window
    from kivy.uix.popup import Popup
    ensure_online(app)
    app.go('monitor')
    items = _nav_items(app, 'monitor')
    assert sorted(items) == ['info', 'menu', 'monitor', 'tools']
    assert [items[t].label for t in ('monitor', 'info', 'tools', 'menu')] == [
        'Сигнал', 'Информация', 'Сеть', 'Меню']
    items['info'].dispatch('on_release')
    assert app.sm.current == 'info'
    _nav_items(app, 'info')['tools'].dispatch('on_release')
    assert app.sm.current == 'tools'
    _nav_items(app, 'tools')['monitor'].dispatch('on_release')
    assert app.sm.current == 'monitor'
    _nav_items(app, 'monitor')['menu'].dispatch('on_release')
    popup = next(w for w in Window.children if isinstance(w, Popup))
    assert popup is not None
    popup.dismiss()


def test_bottom_nav_selected_indicator(app):
    """Etapa 5: el acceso activo es el de la pantalla visible; Menú nunca."""
    ensure_online(app)
    for screen, active in (('monitor', 'monitor'), ('info', 'info'),
                           ('tools', 'tools')):
        app.go(screen)
        items = _nav_items(app, screen)
        for target, item in items.items():
            assert item.active == (target == active), (screen, target)
        assert not items['menu'].active


def test_bottom_nav_does_not_cover_content(app):
    """Etapa 5: la barra no tapa contenido ni botones en ninguna pantalla."""
    from kivy.uix.button import Button
    ensure_online(app)
    mon = app.sm.get_screen('monitor')
    bar = mon.ids.nav_bar
    peaks = next(w for w in mon.walk()
                 if isinstance(w, Button) and 'Пики' in w.text)
    assert peaks.y >= bar.top
    for name in ('info', 'tools'):
        scr = app.sm.get_screen(name)
        assert scr.ids.content_scroll.y >= scr.ids.nav_bar.top


def test_signal_screen_has_no_spectrum(app):
    """La pantalla Señal ya no tiene la interfaz de espectro."""
    from kivy.uix.button import Button
    ensure_online(app)
    scr = app.sm.get_screen('monitor')
    ids = scr.ids
    assert not hasattr(scr, 'signal_tab')
    assert 'spec_pane' not in ids and 'sig_pane' not in ids
    assert 'spectrum_graph' not in ids and 'spec_info_lbl' not in ids
    texts = [w.text for w in scr.walk() if isinstance(w, Button)]
    assert not any('СПЕКТР' in text or 'ESPECTRO' in text for text in texts)
    # El contenido nuevo se ve directo, sin pestañas.
    assert 'MegaFon' in ids.op_name_lbl.text
    assert ids.ci_row.value == '46111500'
    assert ids.tac_row.value == '12345'
    assert scr.lbl_info_lte == 'ИНФОРМАЦИЯ LTE'
    assert scr.lbl_health == 'ЗДОРОВЬЕ СИГНАЛА'
    assert scr.lbl_ca == 'АГРЕГАЦИЯ НЕСУЩИХ'


def test_signal_metric_cards_use_range_position(app):
    """Cada tarjeta de métrica marca la posición del valor en su
    rango, con la palabra de calidad existente (sin cambiar cálculos)."""
    from core.signal_analysis import evaluate_signal
    ensure_online(app)
    ids = app.sm.get_screen('monitor').ids
    # Snapshot fijo: el demo cambia con el tiempo y la tarjeta se dibuja
    # con el valor del último render, no con el valor actual.
    snap = core.Snapshot(registration='registered', connection=901,
                         data_enabled=True, rsrp=-89, sinr=20, rsrq=-10,
                         rssi=-60, pci=287, cell_id=46111500, enodeb=180123,
                         sector=12, tac='12345', operator='MegaFon',
                         plmn='25002', rat='lte', earfcn=1300, bands=(3,))
    app._render(snap)
    for param, lo, hi, val, unit in (('rsrp', -140.0, -44.0, -89, 'dBm'),
                                     ('sinr', -20.0, 30.0, 20, 'dB'),
                                     ('rsrq', -30.0, -3.0, -10, 'dB'),
                                     ('rssi', -110.0, -40.0, -60, 'dBm')):
        label, _color, _pct = evaluate_signal(param, val)
        card = ids[f'{param}_card']
        assert card.m_pct == pytest.approx((val - lo) / (hi - lo) * 100)
        assert card.m_status == f"● {core.t(label)}"
        assert card.m_value == f"{val} {unit}"


def test_signal_ca_section_lists_real_carriers(app):
    """CARRIER AGGREGATION lista las portadoras reales del Snapshot:
    dos portadoras (PCC/SCC con total), una sola (solo PCC) y ninguna
    (la sección no se muestra, no se inventa)."""
    from core.carriers import LTECarrier
    ensure_online(app)
    scr = app.sm.get_screen('monitor')
    ids = scr.ids

    def render(**kw):
        snap = core.Snapshot(registration='registered', connection=901,
                             data_enabled=True, rsrp=-86, sinr=13, bands=(3, 1),
                             freq_mhz=1815, cell_id=46111500, pci=287,
                             enodeb=180123, sector=12, tac='12345',
                             operator='MegaFon', plmn='25002', rat='lte_ca',
                             earfcn=1300, dl_bandwidth='20MHz', **kw)
        app._render(snap)
        return snap

    render(lte_carriers=(LTECarrier(3, 1300, 20.0), LTECarrier(1, 300, 20.0)))
    assert scr.ca_visible
    rows = list(ids.ca_rows.children)
    assert {row.tag for row in rows} == {'PCC', 'SCC'}
    assert any('B3' in row.band and '1800' in row.band for row in rows)
    assert any('B1' in row.band and '2100' in row.band for row in rows)
    assert ids.ca_count_lbl.text == '2 несущих активны'
    assert '40' in ids.ca_total_lbl.text
    render(lte_carriers=(LTECarrier(3, 1300, 20.0),))
    assert scr.ca_visible
    assert [row.tag for row in ids.ca_rows.children] == ['PCC']
    assert ids.ca_count_lbl.text == '1 несущая активна'
    assert '20' in ids.ca_total_lbl.text
    render(lte_carriers=())
    assert not scr.ca_visible


def test_signal_health_segments_light_up(app):
    """La barra de SALUD DE SEÑAL enciende tantos segmentos como el
    porcentaje de salud existente."""
    ensure_online(app)
    ids = app.sm.get_screen('monitor').ids
    segs = list(reversed(ids.segbar.children))
    assert len(segs) == 20
    score = ids.health_ring.pct
    assert ids.health_ring.pct_text == f"{score}%"
    lit = sum(1 for seg in segs if seg.lit)
    assert lit == round(score / 100 * 20)


def test_signal_graph_fill_mesh_has_no_vcolor(app):
    """El relleno del gráfico usa 4 números por vértice (sin vColor).

    Con vColor el relleno salía invisible o como un triángulo gigante
    fuera del gráfico con mucho historial.
    """
    from kivy.graphics import Mesh
    ensure_online(app)
    app.worker.pause()
    try:
        pump(lambda: False, 0.15)
        app.refresh_graph()
        pump(lambda: False, 0.15)
        graph = app.sm.get_screen('monitor').ids.signal_graph
        meshes = [c for c in graph.canvas.children if isinstance(c, Mesh)]
        assert meshes
        segs = graph.viewport.segments(False)
        assert segs
        for mesh in meshes:
            assert len(mesh.vertices) == (len(segs) + 1) * 2 * 4
            assert len(mesh.indices) == len(segs) * 6
    finally:
        app.worker.resume()


def test_band_lock_restore_and_antenna(app):
    ensure_online(app)
    modem = app.demo_modem
    app.go('tools')
    assert pump(lambda: "AUTO" in app._tools().lock_state)
    assert sorted(app.band_vars) == sorted(demo_mod.DEMO_SUPPORTED_BANDS)
    app.mark_current_bands()
    assert {b for b, cb in app.band_vars.items() if cb.active} == set(app.state.last.bands)
    for b, cb in app.band_vars.items():
        cb.active = b == 20
    app.apply_bands()
    assert pump(lambda: not app._busy)
    assert modem.lte_mask == 1 << 19 and modem.network_mode == '03'
    app.restore_bands()
    assert pump(lambda: not app._busy)
    assert modem.lte_mask == core.constants.LTE_ALL_MASK and modem.network_mode == '00'
    app.apply_antenna("Внешняя")
    assert pump(lambda: not app._busy)
    assert modem.antenna == 1


def test_back_key_navigation(app):
    from kivy.core.window import Window
    ensure_online(app)
    app.go('info')
    assert app._on_keyboard(Window, 27) is True and app.sm.current == 'monitor'
    assert app._on_keyboard(Window, 13) is False


def test_info_screen_live(app):
    ensure_online(app)
    app.go('info')
    ids = app.sm.get_screen('info').ids

    def rows_text(box):
        return " ".join(w.row_value for w in box.children
                        if hasattr(w, 'row_value'))

    assert pump(lambda: "MegaFon" in rows_text(ids.tower_rows))
    assert "PCI" in ids.cells_block.text and "(25002)" in ids.cells_block.text
    assert "B636" in rows_text(ids.sim_rows)
    app.go('monitor')


def test_pause_stops_polling_and_resume_continues(app):
    ensure_online(app)
    app.on_pause()
    time.sleep(0.3)
    pump(lambda: False, 0.3)
    n = len(app.state.log)
    pump(lambda: False, 1.2)
    assert len(app.state.log) <= n + 1
    app.on_resume()
    assert pump(lambda: len(app.state.log) > n + 1)


def test_sun_theme(app):
    app.apply_theme('sun')
    assert app.c_bg == [1, 1, 1, 1]
    app.apply_theme('dark')
    assert app.c_bg[0] < 0.2
    # Piel NetMonster: fondo casi negro y acento verde de marca.
    # Los flotantes son int/255 exactos: el hex renderizado es #111411
    # y #0CA663 (antes [0.07, 0.08, 0.07] y [0.05, 0.65, 0.39]
    # se veían #111411 y #0CA563 por el truncado de Kivy).
    assert app.c_bg == [17 / 255, 20 / 255, 17 / 255, 1]
    assert app.c_accent == [12 / 255, 166 / 255, 99 / 255, 1]


def test_palette_renders_exact_design_hex():
    """Etapa 3: cada clave de THEMES renderiza EXACTAMENTE el hex de
    diseño de PALETTE_HEX (Kivy trunca int(v*255))."""
    import android_main

    for theme_name, palette in android_main.PALETTE_HEX.items():
        for key, design_hex in palette.items():
            value = android_main.THEMES[theme_name][key]
            rendered = "#{:02X}{:02X}{:02X}".format(
                *(int(c * 255) for c in value[:3]))
            assert rendered == design_hex.upper(), (theme_name, key,
                                                    rendered, design_hex)


def test_theme_keys_applied(app):
    """Etapa 3: apply_theme aplica TODAS las claves de la paleta (salvo
    las del gráfico, que se leen del dict en _redraw)."""
    import android_main

    # Claves que se leen del dict THEMES en Python (gráfico), no como
    # propiedades de la app.
    dict_only = {'c_graph_bg', 'c_graph_line', 'c_graph_nr', 'c_peak'}
    for name in ('dark', 'sun'):
        app.apply_theme(name)
        for key, value in android_main.THEMES[name].items():
            if key in dict_only:
                continue
            assert hasattr(app, key), (name, key)
            assert list(getattr(app, key)) == list(value), (name, key)
    app.apply_theme('dark')


def test_scrollbars_use_theme_colors(app):
    """Etapa 3: ningún ScrollView usa el gris por defecto de Kivy
    ([0.7, 0.7, 0.7, 0.9]); todos llevan c_sub / c_sep del tema."""
    from kivy.uix.scrollview import ScrollView

    for name in ('connection', 'monitor', 'info', 'tools'):
        scr = app.sm.get_screen(name)
        found = [w for w in scr.walk() if isinstance(w, ScrollView)]
        assert found, name
        for sv in found:
            assert list(sv.bar_color) == list(app.c_sub), name
            assert list(sv.bar_inactive_color)[:3] == list(app.c_sep)[:3], name
            assert sv.bar_inactive_color[3] == 0.25, name


def test_font_scale_single_source(app):
    """Etapa 3: la tipografía sale de FONT (un solo sitio): los roles
    existen y los componentes los usan."""
    from kivy.factory import Factory
    from kivy.metrics import sp

    import android_main

    assert android_main.FONT == {
        'display': 38, 'operator': 30, 'title': 22, 'hero': 34,
        'big': 18, 'menu': 17, 'value': 16, 'body': 15, 'hint': 13,
        'label': 12, 'small': 11.5, 'tiny': 10.5,
    }
    # Los valores por defecto de las reglas (no un widget con tamaño
    # propio en una pantalla).
    assert Factory.PrimaryButton().font_size == sp(android_main.FONT['value'])
    assert Factory.FlatButton().font_size == sp(android_main.FONT['value'])
    assert Factory.AutoLabel().font_size == sp(android_main.FONT['body'])
    assert Factory.HintLabel().font_size == sp(android_main.FONT['hint'])
    assert Factory.InfoLabel().font_size == sp(android_main.FONT['value'])


def test_themed_checkbox_uses_theme(app):
    """Etapa 3: las casillas de bandas son BandCheckBox (sin el atlas
    blanco por defecto de Kivy) y su estado sigue funcionando."""
    from kivy.factory import Factory

    ensure_online(app)
    app.go('tools')
    assert pump(lambda: bool(app.band_vars), 5)
    for cb in app.band_vars.values():
        assert isinstance(cb, Factory.BandCheckBox)
        assert cb.background_checkbox_normal == ''
        assert cb.background_checkbox_down == ''
    first = next(iter(app.band_vars.values()))
    was = first.active
    first.active = not was
    assert first.active != was
    first.active = was


def test_status_hex_palette():
    """Etapa 3: los colores de estado salen de STATUS_HEX (un verde,
    un ámbar, un rojo, un azul y un gris) y renderizan exactos."""
    import android_main

    assert set(android_main.STATUS_HEX) == {
        'good', 'warn', 'error', 'info', 'nodata',
    }
    for key, design_hex in android_main.STATUS_HEX.items():
        value = android_main.hex_to_rgba(design_hex)
        rendered = "#{:02X}{:02X}{:02X}".format(
            *(int(c * 255) for c in value[:3]))
        assert rendered == design_hex.upper(), (key, rendered)


def test_sun_theme_status_colors_readable(app):
    """В «Солнце» цвета статусов читаются на светлой карточке (≥ 4,5:1);
    в тёмной теме остаются исходными."""
    import android_main
    for color in ('#00b894', '#2ecc71', '#fdcb6e', '#d63031', 'gray', 'orange', '#e68033',
                  '#0CA663', '#EAB308', '#EF4444'):
        r, g, b, _ = android_main.hex_to_rgba(color, sun=True)
        sun_hex = "#{:02x}{:02x}{:02x}".format(*(round(c * 255) for c in (r, g, b)))
        assert core.contrast_ratio(sun_hex, core.SUN_CARD_BG) >= 4.5, color
    assert android_main.hex_to_rgba('#fdcb6e') == [0xfd / 255, 0xcb / 255, 0x6e / 255, 1.0]


def test_reboot_reconnects(app):
    ensure_online(app)
    app.confirm_reboot()
    assert pump(lambda: app.link == 'reconnecting', 10)
    assert pump(lambda: app.link == 'online', 15)


def test_diagnostics_to_clipboard(app, monkeypatch):
    ensure_online(app)
    copied = {}
    from kivy.core import clipboard
    monkeypatch.setattr(clipboard.Clipboard, "copy", lambda text: copied.setdefault('t', text))
    app.copy_diagnostics()
    assert pump(lambda: not app._busy and 't' in copied)
    assert '"app_version"' in copied['t'] and "860000000000001" not in copied['t']


def test_english_texts(app):
    ensure_online(app)
    core.set_language("en")
    try:
        app.refresh_all_texts()
        scr = app.sm.get_screen('monitor')
        assert app.lbl_nav_signal == "Signal"
        assert app.lbl_nav_menu == "Menu"
        assert scr.lbl_info_lte == "LTE INFORMATION"
        assert scr.lbl_health == "SIGNAL HEALTH"
        assert scr.ids.op_sub_lbl.text == "OPERATOR · RU · DEMO"  # D6
    finally:
        core.set_language("ru")
        app.refresh_all_texts()


def test_beep_interval():
    import android_main
    assert android_main.beep_interval(None) == 1.5
    assert android_main.beep_interval(0) == pytest.approx(0.12)
    assert android_main.beep_interval(-50) == pytest.approx(1.42)
    assert android_main.hex_to_rgba('#ffffff') == [1.0, 1.0, 1.0, 1.0]
    assert android_main.hex_to_rgba('garbage') == [0.5, 0.5, 0.5, 1.0]


def test_skin_signal_colors():
    """La piel NetMonster traduce los colores de señal del núcleo."""
    import android_main
    assert android_main.skin_hex('#00b894') == '#0CA663'
    assert android_main.skin_hex('#2ecc71') == '#0CA663'
    assert android_main.skin_hex('#fdcb6e') == '#EAB308'
    assert android_main.skin_hex('#e68033') == '#EAB308'
    assert android_main.skin_hex('#d63031') == '#EF4444'
    assert android_main.skin_hex('green') == '#0CA663'
    assert android_main.skin_hex('#123456') == '#123456'


def test_double_back_disconnects(app):
    from kivy.core.window import Window
    ensure_online(app)
    app.go('monitor')
    assert app._on_keyboard(Window, 27) is True and app.link == 'online'
    assert app._on_keyboard(Window, 27) is True
    assert app.link == 'offline' and app.sm.current == 'connection'


def test_beeper_survives_reconnect(app):
    """Во время переподключения звук молчит, но не выключается навсегда."""
    ensure_online(app)
    beeps = []
    app.beeper.beep = beeps.append
    app.sound_on = True
    app.link = 'reconnecting'
    app._beep_tick(0)
    assert not beeps and app._beep_ev is not None
    app.link = 'online'
    app._stop_beeps()
    app._beep_tick(0)
    assert beeps and app._beep_ev is not None
    app.sound_on = False
    app._stop_beeps()


def test_error_line_cleared_after_recovery(app):
    ensure_online(app)
    ev = app.sm.get_screen('monitor').ids.event_lbl
    app._on_status('reconnecting', 1.0, ConnectionError("x"))
    assert ev.text
    app._on_status('connected', None, None)
    expected = app._event_text(app.state.events[-1]) if app.state.events else ""
    assert ev.text == expected


def test_new_session_clears_old_error_line(app):
    ensure_online(app)
    ev = app.sm.get_screen('monitor').ids.event_lbl
    ev.text = "Роутер не отвечает"               # осталось от прошлой сессии
    app._on_connected({})
    expected = app._event_text(app.state.events[-1]) if app.state.events else ""
    assert ev.text == expected


def test_band_labels_follow_theme(app):
    from kivy.factory import Factory
    from kivy.uix.label import Label

    ensure_online(app)
    app.go('tools')
    app.build_band_checkboxes()
    grid = app._tools().ids.bands_grid
    app.apply_theme('sun')
    try:
        cards = [w for w in grid.children if isinstance(w, Factory.BandCard)]
        assert cards
        labels = [w for card in cards for w in card.walk()
                  if isinstance(w, Label) and w.text == card.name]
        assert labels and all(list(lb.color) == list(app.c_text) for lb in labels)
    finally:
        app.apply_theme('dark')
        app.go('monitor')


def test_bold_font_is_bundled():
    import android_main
    assert os.path.exists(android_main._FONT_BOLD_PATH)


@pytest.mark.parametrize("start", [
    lambda a: a.discover(""),
    lambda a: a.whitelist_check(),
], ids=["discover", "whitelist"])
def test_repeated_tap_does_not_start_second_probe(app, monkeypatch, start):
    """Повторное нажатие, пока идёт поиск/проверка, не запускает вторую
    (результат первой мог бы прийти последним и затереть вторую)."""
    calls = []
    monkeypatch.setattr(app, "_run_bg", lambda work, done, fail: calls.append((done, fail)))
    start(app)
    start(app)
    assert len(calls) == 1
    _done, fail = calls[0]
    fail(OSError("network down"))          # проверка закончилась — можно снова
    start(app)
    assert len(calls) == 2
    calls[1][1](OSError("network down"))


def test_fullscreen_zoom_and_removed_arrow(app):
    from kivy.core.window import Window
    from kivy.uix.popup import Popup
    ensure_online(app)
    assert 'dir_lbl' not in app.sm.get_screen('monitor').ids
    app.open_fullscreen_graph()
    graph = app._fs_graph
    graph.zoom('time', 0.5)
    graph.zoom('level', 0.5)
    seconds, levels = graph.viewport.seconds, graph.viewport.levels
    n = len(app.state.log)
    assert pump(lambda: len(app.state.log) > n)
    assert graph.viewport.seconds == seconds and graph.viewport.levels == levels
    graph.auto()
    assert graph.viewport.seconds is None and graph.viewport.levels is None
    for child in list(Window.children):
        if isinstance(child, Popup):
            child.dismiss()
    assert pump(lambda: app._fs_graph is None)


@pytest.mark.parametrize('name', ['info', 'tools'])
def test_pages_open_at_top_without_poll_reset(app, name):
    ensure_online(app)
    app.go(name)
    screen = app.sm.get_screen(name)
    assert pump(lambda: not app.sm.transition.is_active)
    pump(lambda: False, 0.2)
    scroll = screen.ids.content_scroll
    assert scroll.scroll_y == 1
    scroll.scroll_y = 0.4
    n = len(app.state.log)
    assert pump(lambda: len(app.state.log) > n)
    assert abs(scroll.scroll_y - 0.4) < 0.01
    app.go('monitor')
    assert pump(lambda: not app.sm.transition.is_active)
    app.go(name)
    assert pump(lambda: not app.sm.transition.is_active and scroll.scroll_y == 1)
    app.go('monitor')


def test_new_session_has_no_demo_settings(app, monkeypatch):
    import android_main
    ensure_online(app)
    app.build_band_checkboxes()
    for cb in app.band_vars.values():
        cb.active = True
    app._tools().antenna_text = 'Внешняя'
    app._tools().net_msg = 'demo'
    app.disconnect()
    monkeypatch.setattr(android_main.SessionWorker, 'start', lambda self: None)
    session = core.RouterSession('192.168.8.1', '')
    app._start_session(session)
    assert not any(cb.active for cb in app.band_vars.values())
    assert app._tools().antenna_text == core.t('Не прочитано')
    assert app._tools().antenna_selected == ''
    assert app._tools().net_msg == ''
    assert app.state.last is None
    assert app.sm.get_screen('monitor').ids.ci_row.value == '—'
    app.disconnect()


def test_signal_info_columns_equal_and_centered_actions(app):
    ensure_online(app)
    ids = app.sm.get_screen('monitor').ids
    pump(lambda: False, 0.2)
    # Las dos columnas de INFORMACIÓN LTE tienen el mismo ancho.
    assert ids.ci_row.parent.width == pytest.approx(ids.earfcn_row.parent.width)
    assert ids.rsrp_card and ids.sinr_card and ids.rsrq_card and ids.rssi_card
    app.go('tools')
    assert pump(lambda: not app.sm.transition.is_active)
    from kivy.factory import Factory
    for name in ('connection', 'tools'):
        actions = [w for w in app.sm.get_screen(name).walk()
                   if isinstance(w, Factory.PrimaryButton)]
        assert actions
        for button in actions:
            assert button.center_x == pytest.approx(button.parent.center_x)
            assert button.halign == 'center' and button.valign == 'middle'
    assert 'не гарантируются' not in app._tools().hint_router
    app.go('monitor')


def test_pinch_through_rotated_popup_and_auto(app):
    from kivy.core.window import Window
    from kivy.tests.common import UnitTestTouch
    from kivy.uix.button import Button
    from kivy.uix.popup import Popup
    ensure_online(app)
    app.worker.pause()
    app.open_fullscreen_graph()
    pump(lambda: False, 0.3)
    graph = app._fs_graph
    popup = next(w for w in Window.children if isinstance(w, Popup))
    graph.set_data([0, 5, 10], 'sinr', 10, False, [0, 50, 100])

    def point(x, y):
        return graph.to_window(graph.x + graph.width * x, graph.y + graph.height * y)

    first = UnitTestTouch(*point(0.4, 0.4))
    second = UnitTestTouch(*point(0.6, 0.6))
    first.touch_down()
    second.touch_down()
    assert len(graph._fingers) == 2
    original = graph.viewport.y_range()
    second.touch_move(*point(0.8, 0.8))
    assert graph.viewport.seconds < 100
    lo, hi = graph.viewport.y_range()
    assert hi - lo < original[1] - original[0]
    zoomed = graph.viewport.seconds
    second.touch_move(*point(0.6, 0.6))
    assert graph.viewport.seconds > zoomed
    first.touch_up()
    second.touch_up()
    assert not graph._fingers
    buttons = [w for w in popup.walk() if isinstance(w, Button)]
    assert {b.text for b in buttons} == {core.t('Авто'), core.t('← Назад')}
    auto = next(b for b in buttons if b.text == core.t('Авто'))
    tap = UnitTestTouch(*auto.to_window(*auto.center))
    tap.touch_down()
    tap.touch_up()
    assert graph.viewport.seconds is None and graph.viewport.levels is None
    first = UnitTestTouch(*point(0.5, 0.5))
    first.touch_down()
    popup.dismiss()
    assert pump(lambda: app._fs_graph is None)
    assert not graph._fingers and not first.grab_list
    first.touch_up()
    app.worker.resume()


def test_foreign_network_hidden_and_survey_copy(app, monkeypatch):
    from kivy.core.clipboard import Clipboard
    from kivy.core.window import Window
    from kivy.uix.popup import Popup
    ensure_online(app)
    app.worker.pause()
    pump(lambda: False, 0.15)
    app.open_survey()
    app._start_survey()
    bad = core.build_snapshot({'ServiceStatus': '1', 'ConnectionStatus': '902',
                               'rsrp': '-89dBm', 'sinr': '20dB', 'Numeric': '25035',
                               'earfcn': '1276', 'pci': '15'})
    peak = app.state.peaks['rsrp']
    app._on_snapshot(bad)
    monitor = app.sm.get_screen('monitor')
    assert 'Нет регистрации' in monitor.ids.op_name_lbl.text
    assert monitor.ids.ci_row.value == '—'
    assert monitor.ids.rsrp_card.m_value == '—'
    assert app.state.peaks['rsrp'] == peak
    assert 'Мотив' in app._survey_text.text
    copied = []
    monkeypatch.setattr(Clipboard, 'copy', copied.append)
    app._stop_survey()
    app._copy_survey()
    assert '25035' in copied[0]
    for widget in list(Window.children):
        if isinstance(widget, Popup):
            widget.dismiss()
    pump(lambda: False, 0.1)
    app.worker.resume()


def test_survey_search_in_demo(app):
    """Etapa 7 (§9.9): «Поиск операторов» в демо завершается без ошибок.

    Демо не отдаёт plmn_list/cell_info, но discover_networks собирает
    ошибки по точкам, поиск заканчивается, а сбор продолжается."""
    from kivy.core.window import Window
    from kivy.uix.popup import Popup
    ensure_online(app)
    app.open_survey()
    try:
        app._start_survey()
        assert pump(lambda: app.survey.running)
        app._search_survey()
        assert pump(lambda: not getattr(app, '_survey_searching', False), 20)
        assert app.survey.running
        assert app._survey_text is not None
    finally:
        app._stop_survey()
        for widget in list(Window.children):
            if isinstance(widget, Popup):
                widget.dismiss()
        pump(lambda: False, 0.1)


@pytest.mark.parametrize('size', [(140, 100), (165, 140), (280, 120)])
@pytest.mark.parametrize('language', ['ru', 'en', 'es'])
def test_metric_captions_fit_small_cards(app, size, language):
    from kivy.factory import Factory
    from kivy.uix.label import Label
    core.set_language(language)
    card = Factory.MetricCard(size_hint=(None, None), size=size)
    card.m_name = 'RSRP'
    card.m_value = '-119.5'
    card.m_status = core.t('Нет данных')
    card.m_peak = core.t('Пик: {v} (Δ {d})').format(v='-109.5', d='-10.25')
    # La barra de calidad es un Widget sin texto: solo importan las etiquetas.
    labels = [c for c in card.children if isinstance(c, Label)]
    try:
        assert pump(lambda: all(label.text and label.texture_size[0] <= label.width + 1
                               and label.texture_size[1] <= label.height + 1
                               for label in labels))
        assert card.ids.peak_label.text.replace('\n', ' ') == card.m_peak
        for label in labels:
            assert label.x >= card.x and label.right <= card.right
            assert label.y >= card.y and label.top <= card.top
    finally:
        core.set_language('ru')


def test_network_summary_only_warns_on_problem(app):
    """La pantalla Señal solo avisa cuando hay un problema de red: el
    ancla muestra las bandas sin advertencias y los avisos salen en la
    línea de consejos o en el nombre del operador."""
    from dataclasses import replace

    from core.models import Snapshot
    snap = Snapshot(registration='registered', connection=901, data_enabled=True,
                    bands=(3,), band_label='B3', pci=114)
    assert app._anchor_text(snap) == 'LTE 1800'
    assert 'В сети' not in app._anchor_text(snap)
    app._render(snap)
    ids = app.sm.get_screen('monitor').ids
    assert 'нет мобильного' not in ids.advice_lbl.text
    assert 'Нет регистрации' not in ids.op_name_lbl.text
    app._render(replace(snap, connection=902))
    assert 'нет мобильного' in ids.advice_lbl.text
    app._render(replace(snap, registration='unregistered'))
    assert 'Нет регистрации' in ids.op_name_lbl.text


def test_original_mejorado_style_everywhere(app):
    """Estilo 1 en toda la app: encabezados de sección verdes con línea,
    botones con esquinas redondeadas y menú/diálogos con el mismo lenguaje."""
    from kivy.core.window import Window
    from kivy.factory import Factory
    from kivy.graphics import RoundedRectangle
    from kivy.uix.button import Button
    from kivy.uix.label import Label
    from kivy.uix.popup import Popup

    ensure_online(app)
    # Conexión: tarjeta con encabezado verde y línea bajo el título.
    app.go('connection')
    conn = app.sm.get_screen('connection')
    heads = [w for w in conn.walk() if isinstance(w, Factory.SectionHead)]
    assert heads and heads[0].text == core.t("Подключение")
    assert any(isinstance(w, Factory.GreenRule) for w in conn.walk())
    actions = [w for w in conn.walk() if isinstance(w, Factory.PrimaryButton)]
    assert actions
    for btn in actions:
        assert any(isinstance(c, RoundedRectangle) for c in btn.canvas.before.children)
    # Señal: línea verde bajo el estado y títulos de sección en verde.
    app.go('monitor')
    scr = app.sm.get_screen('monitor')
    assert any(isinstance(w, Factory.GreenRule) for w in scr.walk())
    # Información y Red: encabezados de sección verdes con línea.
    for name in ('info', 'tools'):
        app.go(name)
        screen = app.sm.get_screen(name)
        heads = [w for w in screen.walk() if isinstance(w, Factory.SectionHead)]
        assert heads, name
        for head in heads:
            label = next(c for c in head.children if isinstance(c, Label))
            assert list(label.color) == list(app.c_accent)
        assert any(isinstance(w, Factory.GreenRule) for w in screen.walk())
    # Menú: hoja inferior con 5 ítems y separador verde en el popup.
    app.go('monitor')
    app.open_menu()
    popup = next(w for w in Window.children if isinstance(w, Popup))
    assert list(popup.separator_color) == list(app.c_accent)
    menu_items = [w for w in popup.walk() if isinstance(w, Factory.MenuItem)]
    assert len(menu_items) == 5
    popup.dismiss()
    # Confirmación: botón «No» plano y botón «Sí» de acción verde.
    type(app).confirm(app, "Título", "Mensaje", "Sí", lambda: None)
    popup = next(w for w in Window.children if isinstance(w, Popup))
    dialog_buttons = [w for w in popup.walk() if isinstance(w, Button)]
    assert any(isinstance(b, Factory.FlatButton) for b in dialog_buttons)
    assert any(isinstance(b, Factory.PrimaryButton) for b in dialog_buttons)
    popup.dismiss()
    app.go('monitor')


def test_lte_nr_graphs_main_and_fullscreen(app):
    from kivy.core.window import Window
    from kivy.uix.popup import Popup
    ensure_online(app)
    app.worker.pause()
    pump(lambda: False, 0.15)
    try:
        app.state.reset()
        app.state.trend_param = 'sinr'
        for now in range(3):
            app.state.ingest(core.Snapshot(registration='registered', sinr=5 + now,
                                           nr_sinr=20 + now), float(now))
        app.refresh_graph()
        app.open_fullscreen_graph()
        pump(lambda: False, 0.15)
        for graph in (app.sm.get_screen('monitor').ids.signal_graph, app._fs_graph):
            assert graph.viewport.has_comparison
            assert len(graph.viewport.segments(True)) == 2
            labels = [key[0] for key in graph._tex]
            assert any(label.startswith('LTE: 7') for label in labels)
            assert any(label.startswith('NR: 22') for label in labels)
        app.state.ingest(core.Snapshot(registration='registered', sinr=8), 3.0)
        app.refresh_graph()
        assert app._fs_graph.viewport.latest_value(True) is None
        for theme in ('sun', 'dark'):
            app.apply_theme(theme)
            app.refresh_graph(stale=True)
        app.set_graph_param('nr_rsrq')
        assert app._fs_graph.viewport.param == 'nr_rsrq'
    finally:
        for widget in list(Window.children):
            if isinstance(widget, Popup):
                widget.dismiss()
        pump(lambda: False, 0.1)
        app.set_graph_param('sinr')
        app.worker.resume()


def test_confirm_dialog_buttons_have_touch_area(app):
    """D1: el diálogo de confirmación tiene los dos botones con tamaño
    táctil real y sin el bucle textura↔ancho (ni avisos de Clock)."""
    import logging

    from kivy.core.window import Window
    from kivy.factory import Factory
    from kivy.metrics import dp
    from kivy.uix.button import Button
    from kivy.uix.popup import Popup

    ensure_online(app)
    seen: list[str] = []

    class _H(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    handler = _H()
    logging.getLogger("kivy").addHandler(handler)
    try:
        type(app).confirm(app, "Título", "Mensaje", "Sí", lambda: None)
        assert pump(lambda: any(isinstance(w, Popup) for w in Window.children))
        popup = next(w for w in Window.children if isinstance(w, Popup))
        buttons = [w for w in popup.walk() if isinstance(w, Button)]
        assert len(buttons) == 2
        for btn in buttons:
            assert btn.width > 100, (btn.text, btn.width)
            assert btn.height == pytest.approx(dp(52))
            assert btn.x >= popup.x - 1 and btn.right <= popup.right + 1
        assert any(isinstance(b, Factory.PrimaryButton) for b in buttons)
        assert any(isinstance(b, Factory.FlatButton) for b in buttons)
        pump(lambda: False, 1.0)
        assert not any("too much iteration" in m for m in seen)
    finally:
        logging.getLogger("kivy").removeHandler(handler)
        for widget in list(Window.children):
            if isinstance(widget, Popup):
                widget.dismiss()
        pump(lambda: False, 0.2)


def test_menu_items_fit_and_theme_label_is_action(app):
    """D2: todos los ítems del Menú caben (nombre y descripción sin
    cortar). D5: el ítem de tema nombra la acción (cambiar/volver),
    no el estado. La hoja inferior queda abajo, no centrada."""
    from kivy.core.text import Label as CoreLabel
    from kivy.core.window import Window
    from kivy.factory import Factory
    from kivy.metrics import dp, sp
    from kivy.uix.popup import Popup

    import android_main

    ensure_online(app)
    app.apply_theme('dark')
    app.open_menu()
    assert pump(lambda: any(isinstance(w, Popup) for w in Window.children))
    pump(lambda: False, 0.4)
    popup = next(w for w in Window.children if isinstance(w, Popup))
    assert popup.y == pytest.approx(0)
    assert popup.height == pytest.approx(dp(374))
    items = [w for w in popup.walk() if isinstance(w, Factory.MenuItem)]
    assert len(items) == 5
    for item in items:
        col = next(w for w in item.children if type(w).__name__ == 'BoxLayout')
        for text, fsize, bold in (
                (item.name, android_main.FONT['body'], True),
                (item.desc, android_main.FONT['small'], False)):
            probe = CoreLabel(text=text, font_size=sp(fsize), bold=bold,
                              font_name='Roboto')
            probe.refresh()
            assert probe.texture.width <= col.width, (item.name, text)
    assert any(i.name == core.t("Включить солнце") for i in items)
    assert any(i.danger and i.name == core.t("Отключиться") for i in items)
    popup.dismiss()
    pump(lambda: False, 0.2)
    app.apply_theme('sun')
    try:
        app.open_menu()
        assert pump(lambda: any(isinstance(w, Popup) for w in Window.children))
        popup = next(w for w in Window.children if isinstance(w, Popup))
        items = [w for w in popup.walk() if isinstance(w, Factory.MenuItem)]
        assert any(i.name == core.t("Вернуться к тёмной теме") for i in items)
        popup.dismiss()
        pump(lambda: False, 0.2)
    finally:
        app.apply_theme('dark')


def test_spinners_and_survey_text_use_theme(app):
    """D3: el Spinner de idioma usa la piel del tema (fondo, texto y
    opciones) y el informe del escáner ya no es blanco con texto
    oscuro; la antena y el gráfico usan controles segmentados."""
    from kivy.core.window import Window
    from kivy.factory import Factory
    from kivy.uix.popup import Popup
    from kivy.uix.textinput import TextInput

    ensure_online(app)
    lang = app.sm.get_screen('connection').ids.lang_spinner
    assert isinstance(lang, Factory.ThemedSpinner)
    assert list(lang.background_color) == [0, 0, 0, 0]
    assert list(lang.color) == list(app.c_text)
    assert lang.option_cls in ('ThemedSpinnerOption', Factory.ThemedSpinnerOption)
    assert 'graph_param' not in app.sm.get_screen('monitor').ids
    assert 'antenna_spinner' not in app.sm.get_screen('tools').ids
    graph_segs = [w for w in app.sm.get_screen('monitor').walk()
                  if isinstance(w, Factory.SegButton)]
    assert {s.param for s in graph_segs} >= {'sinr', 'rsrp', 'rsrq', 'rssi'}
    ant_segs = [w for w in app.sm.get_screen('tools').walk()
                if isinstance(w, Factory.SegButton)]
    assert ant_segs and all(s.group == 'antenna' for s in ant_segs)
    app.open_survey()
    assert pump(lambda: any(isinstance(w, Popup) for w in Window.children))
    popup = next(w for w in Window.children if isinstance(w, Popup))
    field = next(w for w in popup.walk() if isinstance(w, TextInput))
    assert list(field.background_color) == list(app.c_card)
    assert list(field.foreground_color) == list(app.c_text)
    popup.dismiss()
    pump(lambda: False, 0.2)


def test_info_labels_translated_to_spanish(app):
    """D4: las etiquetas de Información tienen traducción al español."""
    ensure_online(app)
    core.set_language("es")
    try:
        app.refresh_all_texts()
        app.refresh_info_screen()
        info = app.sm.get_screen('info')

        def row_keys(box):
            return [w.row_key for w in box.children if hasattr(w, 'row_key')]

        assert "ID de celda (ECI)" in row_keys(info.ids.tower_rows)
        assert "5G NR" in row_keys(info.ids.tower_rows)
        assert "IMSI (SIM)" in row_keys(info.ids.sim_rows)
        assert "MIMO" in row_keys(info.ids.status_rows)
        assert "RRC" in row_keys(info.ids.status_rows)
    finally:
        core.set_language("ru")
        app.refresh_all_texts()


def test_demo_mode_labelled_on_signal_screen(app):
    """D6: en modo de prueba la Señal indica DEMO en la cabecera."""
    ensure_online(app)
    ids = app.sm.get_screen('monitor').ids
    assert ids.op_sub_lbl.text.endswith("· DEMO")


def test_stale_data_warning_is_red_and_clears(app):
    """D7: el aviso de datos obsoletos sale en rojo y se quita con
    datos frescos."""
    import android_main

    ensure_online(app)
    ids = app.sm.get_screen('monitor').ids
    app.worker.pause()
    try:
        assert pump(lambda: "устарели" in ids.event_lbl.text, 10)
        assert list(ids.event_lbl.color) == list(
            android_main.hex_to_rgba('#EF4444', False))
    finally:
        app.worker.resume()
    assert pump(lambda: ids.event_lbl.text == "", 10)
    assert list(ids.event_lbl.color) == list(app.c_sub)


def test_health_percent_ring_fits_100(app):
    """D8: el «100%» cabe dentro del anillo de salud (86 dp) con margen."""
    from kivy.core.text import Label as CoreLabel
    from kivy.metrics import dp, sp

    ensure_online(app)
    ring = app.sm.get_screen('monitor').ids.health_ring
    assert ring.size[0] == pytest.approx(dp(86))
    label = CoreLabel(text='100%', font_size=sp(21), bold=True,
                      font_name='Roboto')
    label.refresh()
    assert label.texture.width <= ring.width


def test_help_popup_shows_all_content(app):
    """D10: el popup de Ayuda mide todo el texto (sin cortar la última
    línea) y tiene botón «← Atrás» fijo que lo cierra."""
    from kivy.core.window import Window
    from kivy.factory import Factory
    from kivy.uix.label import Label
    from kivy.uix.popup import Popup
    from kivy.uix.scrollview import ScrollView

    app.go('connection')
    app.sm.get_screen('connection').on_help()
    assert pump(lambda: any(isinstance(w, Popup) for w in Window.children))
    popup = next(w for w in Window.children if isinstance(w, Popup))
    sv = next(w for w in popup.walk() if isinstance(w, ScrollView))
    lbl = next(w for w in sv.children[0].walk() if isinstance(w, Label))
    assert lbl.text.endswith("без роутера.")
    assert lbl.height == pytest.approx(lbl.texture_size[1])
    back = next(w for w in popup.walk()
                if isinstance(w, Factory.FlatButton)
                and w.text == core.t("← Назад"))
    back.dispatch('on_release')
    assert pump(lambda: not any(isinstance(w, Popup) for w in Window.children))
    pump(lambda: False, 0.2)
