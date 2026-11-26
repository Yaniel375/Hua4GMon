"""
Hua4GMon — Android-версия (Kivy).

Использует тот же пакет ``core/``, что и Windows-версия (main.py):
сессия с роутером (RouterSession/SessionWorker), разбор данных
(Snapshot), состояние (SignalState), Band Lock, RF-аналитика, переводы.
Здесь только UI-слой на Kivy.

Экраны:
    * Подключение — автопоиск роутера, пароль, язык, подсказка, тестовый режим;
    * Монитор — крупная выбранная метрика и «Δ до пика»,
      RSRP/SINR/RSRQ/RSSI, строка вышки, события смены соты, советы,
      график; нижняя панель: звук-парктроник, сброс пиков, меню;
    * Информация — вышка, лучшие соты сессии, SIM/устройство, состояние
      (обновляется в реальном времени);
    * Сеть — Band Lock, антенна, перезагрузка, переподключение связи,
      диагностика, белые списки (РФ).

Жизненный цикл: на паузе опрос приостанавливается, экран не гаснет
только во время мониторинга, «Назад» ведёт к монитору.
Сборка APK — Buildozer (buildozer.spec).
"""
from __future__ import annotations

import datetime
import importlib
import importlib.abc
import importlib.util
import logging
import math
import os
import platform as py_platform
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

# --- Android crypto-совместимость (ДО первого обращения к huawei_lte_api) ---
# huawei-lte-api требует pycryptodomex (неймспейс Cryptodome), но у него
# нет рецепта python-for-android, и его нативные .so не грузятся на
# Android. Зато pycryptodome (неймспейс Crypto) рецепт имеет. Код пакетов
# идентичен — перенаправляем Cryptodome.* -> Crypto.*. На десктопе, где
# настоящий Cryptodome есть, алиас не включается.


class _CryptodomeAliasFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    PREFIX = 'Cryptodome'

    def find_spec(self, fullname, path=None, target=None):
        if fullname == self.PREFIX or fullname.startswith(self.PREFIX + '.'):
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec):
        real_name = 'Crypto' + spec.name[len(self.PREFIX):]
        module = importlib.import_module(real_name)
        sys.modules[spec.name] = module
        return module

    def exec_module(self, module):
        pass


try:
    import Cryptodome  # noqa: F401  (есть на десктопе — pycryptodomex)
except ImportError:
    sys.meta_path.insert(0, _CryptodomeAliasFinder())

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.widget import Widget
from kivy.utils import escape_markup, platform

from core import (
    ANTENNA_MODES,
    DISCOVERY_CANDIDATES,
    GRAPH_HISTORY,
    LANGUAGES,
    MIMO_LABELS,
    RAT_LABELS,
    REGION_BANDS,
    SUN_CARD_BG,
    UPLINK_LABELS,
    DemoModem,
    RouterSession,
    SessionWorker,
    SignalState,
    Snapshot,
    __version__,
    advice,
    build_diagnostics,
    calculate_overall_health,
    configure_library_logging,
    current_language,
    demo_angle_hint,
    demo_factory,
    diagnostics_json,
    discover_router,
    evaluate_signal,
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
    format_bytes_mb,
    format_mimo,
    format_modulation,
    format_rank,
    format_rate_mbps,
    humanize_error,
    is_valid_ip,
    library_version,
    lock_warnings,
    lockable_bands,
    lte_band_label,
    mimo_status,
    parse_antenna_value,
    readable_on,
    run_whitelist_check,
    set_language,
    t,
    uplink_status,
)
from core.graph import GestureViewport, GraphViewport, comparison_param, radio_label
from core.scanner import SURVEY_HELP, Survey

APP_NAME = "Hua4GMon"

# Логи видны в logcat (adb logcat | grep python).
logging.basicConfig(level=logging.INFO, format="%(name)s [%(levelname)s] %(message)s")
configure_library_logging()
logger = logging.getLogger(APP_NAME)

LTE_PARAMS = ['sinr', 'rsrp', 'rsrq', 'rssi']
NR_PARAMS = ['nr_sinr', 'nr_rsrp', 'nr_rsrq']
PARAM_TITLES = {'rsrp': 'RSRP', 'rssi': 'RSSI', 'sinr': 'SINR', 'rsrq': 'RSRQ',
                'nr_rsrp': 'NR RSRP', 'nr_sinr': 'NR SINR', 'nr_rsrq': 'NR RSRQ'}

# Шрифт с символами навигации, ⚠, Δ: встроенный Roboto в Kivy их не содержит.
# Kivy не подменяет недостающие символы другим шрифтом, а цветных эмодзи
# (🔊 🧪 ✅ …) в DejaVu Sans нет — они рисуются квадратом. Все подписи
# Android используют только символы этого шрифта; это проверяет
# tests/test_project.py::test_android_text_fits_bundled_font.
_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
_FONT_PATH = os.path.join(_ASSETS, 'DejaVuSans.ttf')
# Жирное начертание — для крупных значений и заголовков (читаемость на солнце).
_FONT_BOLD_PATH = os.path.join(_ASSETS, 'DejaVuSans-Bold.ttf')

THEMES: dict[str, dict[str, list[float]]] = {
    'dark': {
        # NetMonster-style dark green-black (see the CUBACEL screenshot).
        'c_bg': [0.04, 0.08, 0.06, 1], 'c_card': [0.09, 0.13, 0.10, 1],
        'c_text': [0.92, 0.94, 0.96, 1], 'c_sub': [0.62, 0.67, 0.72, 1],
        'c_accent': [0.04, 0.47, 0.84, 1], 'c_button2': [0.2, 0.24, 0.3, 1],
        'c_graph_bg': [0.06, 0.10, 0.08, 1], 'c_grid': [0.16, 0.20, 0.17, 1],
    },
    # «Солнце»: максимальный контраст для экрана под прямым солнцем.
    'sun': {
        'c_bg': [1, 1, 1, 1], 'c_card': [0.92, 0.93, 0.94, 1],
        'c_text': [0, 0, 0, 1], 'c_sub': [0.2, 0.2, 0.2, 1],
        'c_accent': [0.0, 0.3, 0.7, 1], 'c_button2': [0.8, 0.82, 0.85, 1],
        'c_graph_bg': [1, 1, 1, 1], 'c_grid': [0.8, 0.8, 0.8, 1],
    },
}


def unit_of(param: str) -> str:
    return "dBm" if param.endswith(('rsrp', 'rssi')) else "dB"


def fmt_num(value: float | None) -> str:
    """Число для подписи: целые — как есть (eNB 1048575, а не 1.04858e+06)."""
    if value is None or not math.isfinite(value):
        return "-"
    return str(value) if isinstance(value, int) else f"{value:g}"


def hex_to_rgba(color: str, sun: bool = False) -> list[float]:
    """'#00b894' или 'gray' → RGBA.

    В режиме «Солнце» (светлый фон) цвет затемняется до контраста не ниже
    4,5:1 с карточкой (core.readable_on); тёмная тема — исходные цвета.
    """
    named = {'gray': '#808080', 'green': '#33cc66', 'orange': '#e68033', 'red': '#d93333'}
    h = named.get(color, color)
    try:
        if sun:
            h = readable_on(h, SUN_CARD_BG)
        h = h.lstrip('#')
        rgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    except (ValueError, IndexError):
        rgb = [0.5, 0.5, 0.5]
    return [*rgb, 1.0]


def beep_interval(delta: float | None) -> float:
    """Пауза между сигналами парктроника: у пика — часто, далеко — редко."""
    if delta is None:
        return 1.5
    return 0.12 + min(1.3, abs(delta) * 0.12)


# =========================================================
# Платформенные сервисы Android (pyjnius)
# =========================================================

def set_keep_screen_on(on: bool) -> None:
    """Экран не гаснет, пока идёт мониторинг (FLAG_KEEP_SCREEN_ON).

    Флаг окна не требует разрешения WAKE_LOCK и снимается системой, когда
    приложение уходит в фон. Hardware validation required.
    """
    if platform != 'android':
        return
    try:
        from android.runnable import run_on_ui_thread
        from jnius import autoclass
    except ImportError:
        logger.warning("pyjnius/android недоступны — keep-screen-on пропущен")
        return

    @run_on_ui_thread
    def apply() -> None:
        activity = autoclass('org.kivy.android.PythonActivity').mActivity
        flag = autoclass('android.view.WindowManager$LayoutParams').FLAG_KEEP_SCREEN_ON
        window = activity.getWindow()
        if on:
            window.addFlags(flag)
        else:
            window.clearFlags(flag)
    apply()


class ToneBeeper:
    """Короткие сигналы через android.media.ToneGenerator.

    Hardware validation required: громкость и задержка на устройстве.
    """

    def __init__(self) -> None:
        self._tone: Any = None
        self._tone_id = 0
        if platform != 'android':
            return
        try:
            from jnius import autoclass
            tone_cls = autoclass('android.media.ToneGenerator')
            audio = autoclass('android.media.AudioManager')
            self._tone = tone_cls(audio.STREAM_MUSIC, 80)
            self._tone_id = tone_cls.TONE_PROP_BEEP
        except Exception:
            logger.warning("ToneGenerator недоступен", exc_info=True)

    @property
    def available(self) -> bool:
        return self._tone is not None

    def beep(self, ms: int = 60) -> None:
        if self._tone is not None:
            self._tone.startTone(self._tone_id, ms)

    def release(self) -> None:
        if self._tone is not None:
            self._tone.release()
            self._tone = None


# =========================================================
# График на Kivy canvas
# =========================================================

class CardLabel(Label):
    """Fit the complete caption inside its share of a metric card."""
    caption = StringProperty('')
    base_size = NumericProperty(sp(14))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._fit_trigger = Clock.create_trigger(self._fit, 0)
        self.bind(size=self._fit_trigger, caption=self._fit_trigger,
                  base_size=self._fit_trigger, font_name=self._fit_trigger,
                  bold=self._fit_trigger)
        self._fit_trigger()

    def _fit(self, *_args):
        from kivy.core.text import Label as CoreLabel
        text = self.caption
        probe = CoreLabel(text=text, font_size=self.base_size,
                          font_name=self.font_name, bold=self.bold)
        probe.refresh()
        width, height = probe.texture.size
        available = max(1, self.width - dp(2))
        if width > available and ' (Δ ' in text:
            text = text.replace(' (Δ ', '\n(Δ ', 1)
            probe.text = text
            probe.refresh()
            width, height = probe.texture.size
        self.text = text
        self.font_size = self.base_size * min(
            1, available / max(1, width), max(1, self.height - dp(2)) / max(1, height))


class SignalGraph(Widget):
    """Линейный график: автомасштаб, линия пика, признак устаревания.

    Размеры — в dp/sp; текстуры подписей кэшируются (подписи оси почти
    не меняются, а создание текстуры — самая дорогая часть отрисовки).
    """

    _TEX_CACHE_MAX = 96

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.viewport = GraphViewport()
        self._values: list[float] = []
        self._peak: float | None = None
        self._param = 'sinr'
        self._stale = False
        self._tex: dict[tuple, Any] = {}
        self.bind(pos=lambda *a: self._redraw(), size=lambda *a: self._redraw())

    def set_data(self, values: list[float], param: str, peak: float | None,
                 stale: bool, times: list[float] | None = None,
                 comparison_values: list[float] | None = None,
                 comparison_times: list[float] | None = None) -> None:
        self._values = list(values)
        self._param = param
        self._peak = peak
        self._stale = stale
        self.viewport.update(self._values, times or [], param, peak,
                             comparison_values, comparison_times)
        self._redraw()

    def _texture(self, text: str, size: float, color: tuple, bold: bool = False) -> Any:
        key = (text, size, color, bold)
        tex = self._tex.get(key)
        if tex is None:
            from kivy.core.text import Label as CoreLabel
            lbl = CoreLabel(text=text, font_size=size, bold=bold, color=color)
            lbl.refresh()
            tex = lbl.texture
            if len(self._tex) >= self._TEX_CACHE_MAX:
                self._tex.clear()
            self._tex[key] = tex
        return tex

    def zoom(self, axis: str, factor: float) -> None:
        self.viewport.zoom(axis, factor)
        self._redraw()

    def auto(self) -> None:
        self.viewport.reset()
        self._redraw()

    def _y_range(self) -> tuple[float, float]:
        return self.viewport.y_range()

    def _redraw(self) -> None:
        from kivy.graphics import Color, Ellipse, Line, Mesh, Rectangle
        app = App.get_running_app()
        theme = THEMES[app.theme_name] if app else THEMES['dark']
        text_col = tuple(theme['c_sub'])
        self.canvas.clear()
        w, h = self.width, self.height
        pl, pr, pt, pb = dp(44), dp(10), dp(44), dp(20)
        plot_w, plot_h = w - pl - pr, h - pt - pb
        if plot_w <= dp(20) or plot_h <= dp(20):
            return
        x0, y0 = self.x + pl, self.y + pb
        y_min, y_max = self._y_range()
        rng = y_max - y_min

        def y_of(v: float) -> float:
            return y0 + plot_h * (max(y_min, min(y_max, v)) - y_min) / rng

        with self.canvas:
            Color(*theme['c_graph_bg'])
            Rectangle(pos=self.pos, size=self.size)
            for i in range(5):
                gy = y0 + plot_h * i / 4
                Color(*theme['c_grid'])
                Line(points=[x0, gy, x0 + plot_w, gy], width=1)
                tex = self._texture(f"{y_min + rng * i / 4:.0f}", sp(11), text_col)
                Color(1, 1, 1, 1)
                Rectangle(texture=tex, pos=(x0 - tex.width - dp(4), gy - tex.height / 2),
                          size=tex.size)
            title = PARAM_TITLES.get(self._param, self._param.upper())
            tex = self._texture(f"{title} ({unit_of(self._param)})", sp(13),
                                tuple(theme['c_text']), True)
            Color(1, 1, 1, 1)
            Rectangle(texture=tex, pos=(x0, self.y + h - dp(19)), size=tex.size)
            start, end = self.viewport.x_range()
            if self.viewport.times and end < self.viewport.times[-1]:
                latest = self.viewport.times[-1]
                time_label = t("От {a:.0f} до {b:.0f} с назад").format(
                    a=latest - start, b=latest - end)
            else:
                time_label = t("Последние {s:.0f} с").format(s=end - start)
            tex = self._texture(time_label, sp(10), text_col)
            Rectangle(texture=tex, pos=(x0 + (plot_w - tex.width) / 2, self.y + dp(3)),
                      size=tex.size)

            if self._peak is not None and y_min <= self._peak <= y_max:
                py = y_of(self._peak)
                Color(0.0, 0.72, 0.58, 1)
                Line(points=[x0, py, x0 + plot_w, py], width=1, dash_length=dp(4),
                     dash_offset=dp(3))
            # NetMonster-style dashed "good" threshold line.
            thr = good_threshold(self._param)
            if thr is not None and y_min <= thr <= y_max:
                ty = y_of(thr)
                Color(0.75, 0.75, 0.75, 0.9)
                Line(points=[x0, ty, x0 + plot_w, ty], width=1,
                     dash_length=dp(4), dash_offset=dp(3))
            paired = self.viewport.has_comparison
            for comparison in ((False, True) if paired else (False,)):
                param = comparison_param(self._param) if comparison else self._param
                is_nr = param.startswith('nr_')
                sun = app is not None and app.theme_name == 'sun'
                latest = self.viewport.latest_value(comparison)
                if self._stale:
                    line_col = (0.6, 0.6, 0.6, 1)
                elif latest is not None:
                    # Line colour follows the latest value's quality
                    # (green / yellow / red), as in NetMonster Charts.
                    base = param[3:] if is_nr else param
                    _st, col, _pc = evaluate_signal(base, latest)
                    line_col = tuple(hex_to_rgba(col, sun))
                elif is_nr:
                    line_col = (0.65, 0.30, 0.0, 1) if sun else (1.0, 0.65, 0.2, 1)
                else:
                    line_col = (0.0, 0.40, 0.65, 1) if sun else (0.0, 0.70, 1.0, 1)
                segs = self.viewport.segments(comparison)
                if segs:
                    # Filled area under the line (translucent quality colour).
                    pts = [(segs[0][0], segs[0][1])] + [(s[2], s[3]) for s in segs]
                    verts = [x0 + plot_w * pts[0][0], y0, 0, 0]
                    for px, py in pts:
                        verts += [x0 + plot_w * px, y0 + plot_h * py, 0, 0]
                    verts += [x0 + plot_w * pts[-1][0], y0, 0, 0]
                    Color(line_col[0], line_col[1], line_col[2], 0.22)
                    Mesh(vertices=verts, indices=list(range(len(verts) // 4)),
                         mode='triangle_fan')
                Color(*line_col)
                for x1, y1, x2, y2 in segs:
                    Line(points=[x0 + plot_w * x1, y0 + plot_h * y1,
                                 x0 + plot_w * x2, y0 + plot_h * y2], width=dp(1.5),
                         dash_length=dp(6) if is_nr else 0,
                         dash_offset=dp(3) if is_nr else 0)
                point = self.viewport.last_point(comparison)
                if point is not None:
                    lx, ly, r = x0 + plot_w * point[0], y0 + plot_h * point[1], dp(3)
                    Ellipse(pos=(lx - r, ly - r), size=(2 * r, 2 * r))
                name = radio_label(param) if comparison_param(param) else PARAM_TITLES.get(param, param)
                label = f"{name}: {fmt_num(self.viewport.latest_value(comparison))} {unit_of(param)}"
                tex = self._texture(label, sp(11), line_col, True)
                Color(1, 1, 1, 1)
                Rectangle(texture=tex,
                          pos=(x0 + (plot_w / 2 if comparison else 0), self.y + h - dp(38)),
                          size=tex.size)
            if self._stale:
                tex = self._texture(t("нет свежих данных"), sp(13), text_col, True)
                Color(1, 1, 1, 1)
                Rectangle(texture=tex, pos=(x0 + (plot_w - tex.width) / 2,
                                           y0 + plot_h / 2), size=tex.size)



class PinchGraph(SignalGraph):
    """Fullscreen touch graph inside the rotated layout.

    Hardware validation required: two-finger gestures on an Android touchscreen.
    Kivy transforms grabbed events through Scatter into the graph's parent space.
    """

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.viewport = GestureViewport()
        self._fingers: dict[Any, tuple[Any, tuple[float, float]]] = {}

    def release_touches(self) -> None:
        for touch, _pos in self._fingers.values():
            touch.ungrab(self)
        self._fingers.clear()

    def on_touch_down(self, touch: Any) -> bool:
        if not self.collide_point(*touch.pos) or getattr(touch, 'is_mouse_scrolling', False):
            return super().on_touch_down(touch)
        if len(self._fingers) < 2:
            self._fingers[touch.uid] = (touch, touch.pos)
            touch.grab(self)
        return True

    def on_touch_move(self, touch: Any) -> bool:
        if touch.uid not in self._fingers:
            return super().on_touch_move(touch)
        if touch.grab_current is not self:
            return True
        old = [pos for _finger, pos in self._fingers.values()]
        self._fingers[touch.uid] = (touch, touch.pos)
        new = [pos for _finger, pos in self._fingers.values()]
        width, height = self.width - dp(54), self.height - dp(64)
        if width <= 0 or height <= 0:
            return True
        def center(points: list[tuple[float, float]]) -> tuple[float, float]:
            return (sum(p[0] for p in points) / len(points),
                    sum(p[1] for p in points) / len(points))
        before, after = center(old), center(new)
        factor = 1.0
        if len(old) == 2:
            from math import hypot
            def distance(points: list[tuple[float, float]]) -> float:
                return hypot(points[1][0] - points[0][0], points[1][1] - points[0][1])
            previous, current = distance(old), distance(new)
            if min(previous, current) < dp(8):
                return True
            factor = previous / current
        anchor = ((before[0] - self.x - dp(44)) / width,
                  (before[1] - self.y - dp(20)) / height)
        shift = ((after[0] - before[0]) / width, (after[1] - before[1]) / height)
        self.viewport.transform(factor, anchor, shift)
        self._redraw()
        return True

    def on_touch_up(self, touch: Any) -> bool:
        if touch.uid not in self._fingers:
            return super().on_touch_up(touch)
        touch.ungrab(self)
        del self._fingers[touch.uid]
        return True


class RotatedBox(Widget):
    """Показывает вложенный layout повёрнутым на 90° (альбомно).

    Scatter, а не голый Rotate по canvas: Scatter применяет ту же
    трансформацию к касаниям, поэтому кнопка внутри остаётся кликабельной.
    """

    def __init__(self, inner: Widget, **kw: Any) -> None:
        super().__init__(**kw)
        from kivy.uix.scatter import Scatter
        self._inner = inner
        inner.size_hint = (None, None)
        self._scatter = Scatter(do_rotation=False, do_scale=False,
                                do_translation=False, size_hint=(None, None))
        self._scatter.add_widget(inner)
        self.add_widget(self._scatter)
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *a: Any) -> None:
        land = (self.height, self.width)
        self._scatter.size = land
        self._inner.size = land
        self._scatter.rotation = 90
        self._scatter.center = self.center


# =========================================================
# KV-разметка
# =========================================================

KV = """
#:import dp kivy.metrics.dp
#:import sp kivy.metrics.sp

<ActionButton@Button>:
    size_hint_x: 0.9
    pos_hint: {'center_x': 0.5}
    text_size: self.size
    halign: 'center'
    valign: 'middle'
    background_normal: ''
    background_color: app.c_accent
    color: 1, 1, 1, 1
    font_size: sp(16)
    size_hint_y: None
    height: dp(52)

<FlatButton@Button>:
    background_normal: ''
    background_color: app.c_button2
    color: app.c_text
    font_size: sp(16)

<SectionCard@BoxLayout>:
    orientation: 'vertical'
    size_hint_y: None
    height: self.minimum_height
    padding: dp(12)
    spacing: dp(8)
    canvas.before:
        Color:
            rgba: app.c_card
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]

<SectionTitle@Label>:
    font_size: sp(19)
    bold: True
    color: app.c_text
    size_hint_y: None
    height: dp(34)
    text_size: self.width, None
    halign: 'left'
    valign: 'middle'

<AutoLabel@Label>:
    font_size: sp(15)
    color: app.c_text
    size_hint_y: None
    height: self.texture_size[1] + dp(6)
    text_size: self.width, None
    halign: 'left'
    valign: 'top'

<HintLabel@AutoLabel>:
    font_size: sp(13)
    color: app.c_sub

<InfoLabel@AutoLabel>:
    font_size: sp(16)
    line_height: 1.3
    markup: True

<MetricCard@BoxLayout>:
    orientation: 'vertical'
    m_name: ''
    m_value: '-'
    m_status: ''
    m_peak: ''
    m_color: 0.5, 0.5, 0.5, 1
    value_size: sp(34)
    padding: dp(6)
    spacing: dp(1)
    canvas.before:
        Color:
            rgba: app.c_card
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10)]
    CardLabel:
        caption: root.m_name
        base_size: sp(14)
        color: app.c_sub
        size_hint_y: 0.15
    CardLabel:
        caption: root.m_value
        base_size: root.value_size
        bold: True
        color: root.m_color
        size_hint_y: 0.45
    CardLabel:
        caption: root.m_status
        base_size: sp(13)
        color: root.m_color
        size_hint_y: 0.15
    CardLabel:
        id: peak_label
        caption: root.m_peak
        base_size: sp(14)
        color: app.c_sub
        halign: 'center'
        size_hint_y: 0.25

<SignalBarRow@BoxLayout>:
    orientation: 'vertical'
    bar_name: ''
    bar_value: ''
    bar_status: ''
    bar_hint: ''
    bar_pct: 0
    bar_color: 0.5, 0.5, 0.5, 1
    size_hint_y: None
    height: dp(76)
    spacing: dp(2)
    BoxLayout:
        size_hint_y: None
        height: dp(24)
        spacing: dp(6)
        Label:
            text: root.bar_name
            font_size: sp(14)
            color: app.c_sub
            halign: 'left'
            valign: 'middle'
            text_size: self.size
            size_hint_x: 0.55
        Label:
            text: root.bar_value
            font_size: sp(20)
            bold: True
            color: root.bar_color
            halign: 'right'
            valign: 'middle'
            text_size: self.size
            size_hint_x: 0.45
    BoxLayout:
        size_hint_y: None
        height: dp(10)
        canvas.before:
            Color:
                rgba: app.c_button2
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(5)]
        Widget:
            size_hint_x: None
            width: max(0, (self.parent.width - dp(2)) * root.bar_pct / 100.0)
            canvas.before:
                Color:
                    rgba: root.bar_color
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(5)]
    Label:
        text: root.bar_status if not root.bar_hint else root.bar_status + ' - ' + root.bar_hint
        font_size: sp(12)
        color: app.c_sub
        halign: 'left'
        valign: 'top'
        text_size: self.width, None
        size_hint_y: None
        height: dp(18) if self.text else 0

<NetRow@BoxLayout>:
    orientation: 'horizontal'
    n_label: ''
    n_value: '-'
    n_unit: ''
    n_trend: ''
    n_trend_color: 0.5, 0.5, 0.5, 1
    size_hint_y: None
    height: dp(36)
    spacing: dp(4)
    Label:
        text: root.n_label
        font_size: sp(17)
        color: app.c_sub
        halign: 'left'
        valign: 'middle'
        text_size: self.size
        size_hint_x: 0.38
    Label:
        text: root.n_value
        font_size: sp(20)
        bold: True
        color: app.c_text
        halign: 'right'
        valign: 'middle'
        text_size: self.size
        size_hint_x: 0.34
    Label:
        text: root.n_unit
        font_size: sp(13)
        color: app.c_sub
        halign: 'left'
        valign: 'bottom'
        text_size: self.size
        size_hint_x: 0.16
    Label:
        text: root.n_trend
        font_size: sp(15)
        color: root.n_trend_color
        halign: 'center'
        valign: 'middle'
        text_size: self.size
        size_hint_x: 0.12

<ChipLabel>:
    chip_color: 1, 1, 1, 1
    bold: True
    font_size: sp(15)
    color: root.chip_color
    size_hint_x: None
    width: self.texture_size[0] + dp(16)
    size_hint_y: None
    height: dp(26)
    canvas.before:
        Color:
            rgba: root.chip_color
        Line:
            rounded_rectangle: self.x, self.y, self.width, self.height, dp(6)
            width: dp(1.2)

<LogRow>:
    orientation: 'vertical'
    size_hint_y: None
    height: dp(64)
    padding: dp(4), dp(2)
    spacing: dp(2)
    canvas.after:
        Color:
            rgba: app.c_grid
        Line:
            points: self.x, self.y, self.right, self.y
            width: dp(1)

<BandLockSheet>:
    sheet_title: ''
    tab_recent_text: ''
    tab_routines_text: ''
    new_lock_text: ''
    unlock_all_text: ''
    orientation: 'vertical'
    padding: dp(16)
    spacing: dp(10)
    canvas.before:
        Color:
            rgba: app.c_card
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(24), dp(24), 0, 0]
    Widget:
        size_hint_y: None
        height: dp(5)
        size_hint_x: None
        width: dp(48)
        pos_hint: {'center_x': 0.5}
        canvas.before:
            Color:
                rgba: app.c_button2
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(3)]
    Label:
        text: root.sheet_title
        font_size: sp(22)
        bold: True
        color: app.c_text
        halign: 'left'
        valign: 'middle'
        text_size: self.size
        size_hint_y: None
        height: dp(32)
    Widget:
        size_hint_y: None
        height: dp(6)
        size_hint_x: 0.5
        canvas.before:
            Color:
                rgba: 0, 0.72, 0.58, 1
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(3)]
    BoxLayout:
        size_hint_y: None
        height: dp(44)
        spacing: dp(8)
        FlatButton:
            id: tab_recent
            text: root.tab_recent_text
            font_size: sp(16)
            on_release: app.set_lock_sheet_tab('recent')
        FlatButton:
            id: tab_routines
            text: root.tab_routines_text
            font_size: sp(16)
            on_release: app.set_lock_sheet_tab('routines')
    BoxLayout:
        id: sheet_body
        orientation: 'vertical'
        spacing: dp(2)
    BoxLayout:
        size_hint_y: None
        height: dp(52)
        spacing: dp(8)
        FlatButton:
            text: root.new_lock_text
            font_size: sp(16)
            on_release: app.new_band_lock()
        FlatButton:
            text: root.unlock_all_text
            font_size: sp(16)
            on_release: app.unlock_all_bands()

<NavButton>:
    orientation: 'vertical'
    spacing: 0
    padding: dp(2), dp(4)
    canvas.before:
        Color:
            rgba: (0.08, 0.33, 0.18, 1) if root.active else (0, 0, 0, 0)
        RoundedRectangle:
            pos: self.x + dp(3), self.y + dp(5)
            size: self.width - dp(6), self.height - dp(10)
            radius: [dp(14)]
    AnchorLayout:
        anchor_x: 'center'
        anchor_y: 'center'
        size_hint_y: 0.58
        Label:
            text: root.nav_icon
            font_size: sp(18) if root.nav_icon_box else sp(22)
            color: (1, 1, 1, 1) if root.active else app.c_sub
            halign: 'center'
            valign: 'middle'
            text_size: self.size
            size_hint: None, None
            size: dp(32), dp(30)
            canvas.before:
                Color:
                    rgba: ((1, 1, 1, 1) if root.active else app.c_sub) if root.nav_icon_box else (0, 0, 0, 0)
                Line:
                    rounded_rectangle: self.x, self.y, self.width, self.height, dp(7)
                    width: dp(1.5)
    Label:
        text: root.nav_text
        font_size: sp(13)
        bold: root.active
        color: (1, 1, 1, 1) if root.active else app.c_sub
        halign: 'center'
        valign: 'middle'
        text_size: self.size
        size_hint_y: 0.42

<BottomNav@BoxLayout>:
    size_hint_y: None
    height: dp(64)
    spacing: dp(2)
    canvas.before:
        Color:
            rgba: app.c_button2
        RoundedRectangle:
            pos: self.x + dp(6), self.y + dp(4)
            size: self.width - dp(12), self.height - dp(8)
            radius: [dp(24)]
        Color:
            rgba: app.c_grid
        Line:
            rounded_rectangle: self.x + dp(6), self.y + dp(4), self.width - dp(12), self.height - dp(8), dp(24)
            width: dp(1)
    NavButton:
        nav_icon: '↗'
        nav_text: app.nav_charts
        nav_target: 'charts'
        nav_icon_box: True
        on_release: app.go('charts')
    NavButton:
        nav_icon: '▦'
        nav_text: app.nav_map
        nav_target: 'map'
        on_release: app.go('map')
    NavButton:
        nav_icon: '◎'
        nav_text: app.nav_monitor
        nav_target: 'monitor'
        on_release: app.go('monitor')
    NavButton:
        nav_icon: '▤'
        nav_text: app.nav_cells
        nav_target: 'cells'
        on_release: app.go('cells')
    NavButton:
        nav_icon: '☰'
        nav_text: app.nav_menu
        nav_target: 'menu'
        on_release: app.open_menu()

<Header@BoxLayout>:
    title: ''
    size_hint_y: None
    height: dp(52)
    padding: dp(8), dp(4)
    spacing: dp(8)
    FlatButton:
        text: app.lbl_back
        size_hint_x: None
        width: dp(110)
        on_release: app.go('monitor')
    Label:
        text: root.title
        font_size: sp(18)
        bold: True
        color: app.c_text

ScreenManager:
    ConnectionScreen:
    MonitorScreen:
    ChartsScreen:
    MapScreen:
    CellsScreen:
    InfoScreen:
    ToolsScreen:
    SettingsScreen:

<ConnectionScreen>:
    name: 'connection'
    canvas.before:
        Color:
            rgba: app.c_bg
        Rectangle:
            pos: self.pos
            size: self.size
    ScrollView:
        bar_width: dp(8)
        scroll_type: ['bars', 'content']
        BoxLayout:
            orientation: 'vertical'
            size_hint_y: None
            height: self.minimum_height
            padding: dp(24)
            spacing: dp(12)
            Label:
                text: 'Hua4GMon'
                font_size: sp(38)
                bold: True
                color: app.c_text
                size_hint_y: None
                height: dp(64)
            Label:
                text: root.subtitle
                font_size: sp(15)
                color: app.c_sub
                size_hint_y: None
                height: dp(26)
            AutoLabel:
                text: root.lbl_ip
            BoxLayout:
                size_hint_y: None
                height: dp(50)
                spacing: dp(8)
                TextInput:
                    id: ip_input
                    text: '192.168.8.1'
                    multiline: False
                    font_size: sp(18)
                FlatButton:
                    text: root.lbl_find
                    size_hint_x: 0.45
                    font_size: sp(15)
                    on_release: root.on_find()
            AutoLabel:
                text: root.lbl_pw
            TextInput:
                id: pw_input
                password: True
                multiline: False
                font_size: sp(18)
                size_hint_y: None
                height: dp(50)
                on_text_validate: root.on_connect()
            ActionButton:
                text: root.lbl_connect
                on_release: root.on_connect()
            AutoLabel:
                id: status_lbl
                text: ''
                font_size: sp(15)
                color: root.status_color
                halign: 'center'
            FlatButton:
                text: root.lbl_demo
                size_hint_y: None
                height: dp(48)
                on_release: app.start_demo()
            FlatButton:
                text: root.lbl_help
                size_hint_y: None
                height: dp(44)
                on_release: root.on_help()
            BoxLayout:
                size_hint_y: None
                height: dp(44)
                spacing: dp(8)
                Label:
                    text: root.lbl_lang
                    color: app.c_sub
                    font_size: sp(14)
                    size_hint_x: None
                    width: dp(80)
                Spinner:
                    id: lang_spinner
                    text: root.lang_name
                    values: root.lang_values
                    font_size: sp(14)
                    on_text: root.on_language(self.text)

<MonitorScreen>:
    name: 'monitor'
    canvas.before:
        Color:
            rgba: app.c_bg
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        orientation: 'vertical'
        padding: dp(8)
        spacing: dp(6)
        ScrollView:
            id: monitor_scroll
            bar_width: dp(8)
            scroll_type: ['bars', 'content']
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: dp(2)
                spacing: dp(8)
                Label:
                    id: status_lbl
                    text: ''
                    font_size: sp(15)
                    bold: True
                    color: root.status_color
                    size_hint_y: None
                    height: self.texture_size[1] + dp(2)
                    text_size: self.width, None
                    halign: 'center'
                BoxLayout:
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    spacing: dp(2)
                    BoxLayout:
                        size_hint_y: None
                        height: dp(52)
                        Label:
                            id: operator_lbl
                            text: '-'
                            font_size: sp(36)
                            bold: True
                            color: app.c_text
                            halign: 'left'
                            valign: 'middle'
                            text_size: self.size
                            size_hint_x: 0.65
                        Label:
                            id: plmn_lbl
                            text: '-'
                            font_size: sp(22)
                            color: app.c_text
                            halign: 'right'
                            valign: 'middle'
                            text_size: self.size
                            size_hint_x: 0.35
                    Widget:
                        size_hint_y: None
                        height: dp(6)
                        size_hint_x: 0.45
                        canvas.before:
                            Color:
                                rgba: 0, 0.72, 0.58, 1
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(3)]
                    Label:
                        id: rat_lbl
                        text: '-'
                        font_size: sp(20)
                        color: app.c_text
                        halign: 'left'
                        valign: 'middle'
                        text_size: self.size
                        size_hint_y: None
                        height: dp(30)
                BoxLayout:
                    size_hint_y: None
                    height: self.minimum_height
                    spacing: dp(12)
                    BoxLayout:
                        orientation: 'vertical'
                        size_hint_y: None
                        height: self.minimum_height
                        spacing: dp(2)
                        NetRow:
                            id: net_ci
                        NetRow:
                            id: net_enb
                        NetRow:
                            id: net_tac
                        NetRow:
                            id: net_pci
                    BoxLayout:
                        orientation: 'vertical'
                        size_hint_y: None
                        height: self.minimum_height
                        spacing: dp(2)
                        NetRow:
                            id: net_earfcn
                        NetRow:
                            id: net_rssi
                        NetRow:
                            id: net_rsrp
                        NetRow:
                            id: net_rsrq
                        NetRow:
                            id: net_snr
                        NetRow:
                            id: net_cqi
                Label:
                    id: tower_lbl
                    text: '—'
                    font_size: sp(15)
                    bold: True
                    color: app.c_text
                    size_hint_y: None
                    height: self.texture_size[1] + dp(2)
                    text_size: self.width, None
                    halign: 'center'
                Label:
                    id: event_lbl
                    text: ''
                    font_size: sp(13)
                    color: app.c_sub
                    size_hint_y: None
                    height: self.texture_size[1] if self.text else 0
                    text_size: self.width, None
                    halign: 'center'
                SectionCard:
                    SignalBarRow:
                        id: health_bar
                GridLayout:
                    id: metrics_grid
                    cols: 2
                    rows: 2
                    spacing: dp(6)
                    size_hint_y: None
                    height: dp(320)
                    MetricCard:
                        id: primary_box
                    MetricCard:
                        id: secondary_box
                    MetricCard:
                        id: small1_box
                    MetricCard:
                        id: small2_box
                Label:
                    id: advice_lbl
                    text: ''
                    font_size: sp(13)
                    color: root.advice_color
                    size_hint_y: None
                    height: self.texture_size[1] if self.text else 0
                    text_size: self.width, None
                    halign: 'left'
                SectionCard:
                    SectionTitle:
                        text: root.lbl_bars_title
                    SignalBarRow:
                        id: bar_rsrp
                    SignalBarRow:
                        id: bar_sinr
                    SignalBarRow:
                        id: bar_rsrq
                    SignalBarRow:
                        id: bar_rssi
                    SignalBarRow:
                        id: bar_cqi
                    SignalBarRow:
                        id: bar_nr_rsrp
                    SignalBarRow:
                        id: bar_nr_sinr
                BoxLayout:
                    size_hint_y: None
                    height: dp(42)
                    spacing: dp(6)
                    Spinner:
                        id: graph_param
                        text: 'sinr'
                        values: root.graph_values
                        size_hint_x: 0.5
                        font_size: sp(15)
                        on_text: app.set_graph_param(self.text)
                    FlatButton:
                        text: root.lbl_fullscreen
                        size_hint_x: 0.5
                        font_size: sp(14)
                        on_release: app.open_fullscreen_graph()
                SignalGraph:
                    id: signal_graph
                    size_hint_y: None
                    height: dp(180)
                SectionCard:
                    SectionTitle:
                        text: root.lbl_ca_title
                    InfoLabel:
                        id: ca_lbl
                        text: ''
                BoxLayout:
                    size_hint_y: None
                    height: dp(52)
                    spacing: dp(8)
                    FlatButton:
                        text: root.lbl_tools
                        font_size: sp(15)
                        on_release: app.go('tools')
                    FlatButton:
                        text: root.lbl_band_lock
                        font_size: sp(15)
                        on_release: app.open_band_lock_sheet()
                BoxLayout:
                    size_hint_y: None
                    height: dp(56)
                    spacing: dp(6)
                    FlatButton:
                        text: root.lbl_sound
                        background_color: app.c_accent if app.sound_on else app.c_button2
                        color: (1, 1, 1, 1) if app.sound_on else app.c_text
                        on_release: app.toggle_sound()
                    FlatButton:
                        text: root.lbl_peaks
                        on_release: app.reset_peaks()
                    FlatButton:
                        text: root.lbl_menu
                        on_release: app.open_menu()
                Widget:
                    size_hint_y: None
                    height: dp(16)
        BottomNav:
            id: bottom_nav

<ChartsScreen>:
    name: 'charts'
    canvas.before:
        Color:
            rgba: app.c_bg
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        orientation: 'vertical'
        Header:
            title: root.lbl_title
        ScrollView:
            id: content_scroll
            bar_width: dp(8)
            scroll_type: ['bars', 'content']
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: dp(10)
                spacing: dp(10)
                BoxLayout:
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    spacing: dp(2)
                    BoxLayout:
                        size_hint_y: None
                        height: dp(40)
                        Label:
                            id: charts_operator
                            text: '-'
                            font_size: sp(28)
                            bold: True
                            color: app.c_text
                            halign: 'left'
                            valign: 'middle'
                            text_size: self.size
                            size_hint_x: 0.6
                        Label:
                            id: charts_rat
                            text: '-'
                            font_size: sp(18)
                            color: app.c_text
                            halign: 'right'
                            valign: 'middle'
                            text_size: self.size
                            size_hint_x: 0.4
                    Widget:
                        size_hint_y: None
                        height: dp(6)
                        size_hint_x: 0.45
                        canvas.before:
                            Color:
                                rgba: 0, 0.72, 0.58, 1
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(3)]
                    Label:
                        id: charts_cell
                        text: '-'
                        font_size: sp(18)
                        color: app.c_text
                        halign: 'left'
                        valign: 'middle'
                        text_size: self.size
                        size_hint_y: None
                        height: dp(28)
                    BoxLayout:
                        size_hint_y: None
                        height: dp(30)
                        spacing: dp(8)
                        ChipLabel:
                            id: charts_chip
                            chip_color: 0, 0.72, 0.58, 1
                GridLayout:
                    cols: 2
                    spacing: dp(10)
                    size_hint_y: None
                    height: self.minimum_height
                    SectionCard:
                        BoxLayout:
                            size_hint_y: None
                            height: dp(24)
                            Label:
                                text: 'RSSI'
                                font_size: sp(16)
                                bold: True
                                color: app.c_text
                                halign: 'left'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.45
                            Label:
                                id: chart_rssi_lbl
                                text: '-'
                                font_size: sp(18)
                                bold: True
                                color: app.c_text
                                halign: 'right'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.45
                            Label:
                                id: chart_rssi_dot
                                text: '•'
                                font_size: sp(16)
                                color: app.c_sub
                                halign: 'center'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.1
                        SignalGraph:
                            id: chart_rssi
                            size_hint_y: None
                            height: dp(140)
                    SectionCard:
                        BoxLayout:
                            size_hint_y: None
                            height: dp(24)
                            Label:
                                text: 'RSRP'
                                font_size: sp(16)
                                bold: True
                                color: app.c_text
                                halign: 'left'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.45
                            Label:
                                id: chart_rsrp_lbl
                                text: '-'
                                font_size: sp(18)
                                bold: True
                                color: app.c_text
                                halign: 'right'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.45
                            Label:
                                id: chart_rsrp_dot
                                text: '•'
                                font_size: sp(16)
                                color: app.c_sub
                                halign: 'center'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.1
                        SignalGraph:
                            id: chart_rsrp
                            size_hint_y: None
                            height: dp(140)
                    SectionCard:
                        BoxLayout:
                            size_hint_y: None
                            height: dp(24)
                            Label:
                                text: 'RSRQ'
                                font_size: sp(16)
                                bold: True
                                color: app.c_text
                                halign: 'left'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.45
                            Label:
                                id: chart_rsrq_lbl
                                text: '-'
                                font_size: sp(18)
                                bold: True
                                color: app.c_text
                                halign: 'right'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.45
                            Label:
                                id: chart_rsrq_dot
                                text: '•'
                                font_size: sp(16)
                                color: app.c_sub
                                halign: 'center'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.1
                        SignalGraph:
                            id: chart_rsrq
                            size_hint_y: None
                            height: dp(140)
                    SectionCard:
                        BoxLayout:
                            size_hint_y: None
                            height: dp(24)
                            Label:
                                text: 'SNR'
                                font_size: sp(16)
                                bold: True
                                color: app.c_text
                                halign: 'left'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.45
                            Label:
                                id: chart_sinr_lbl
                                text: '-'
                                font_size: sp(18)
                                bold: True
                                color: app.c_text
                                halign: 'right'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.45
                            Label:
                                id: chart_sinr_dot
                                text: '•'
                                font_size: sp(16)
                                color: app.c_sub
                                halign: 'center'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.1
                        SignalGraph:
                            id: chart_sinr
                            size_hint_y: None
                            height: dp(140)
                    SectionCard:
                        BoxLayout:
                            size_hint_y: None
                            height: dp(24)
                            Label:
                                text: 'NR RSRP'
                                font_size: sp(16)
                                bold: True
                                color: app.c_text
                                halign: 'left'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.45
                            Label:
                                id: chart_nr_rsrp_lbl
                                text: '-'
                                font_size: sp(18)
                                bold: True
                                color: app.c_text
                                halign: 'right'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.45
                            Label:
                                id: chart_nr_rsrp_dot
                                text: '•'
                                font_size: sp(16)
                                color: app.c_sub
                                halign: 'center'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.1
                        SignalGraph:
                            id: chart_nr_rsrp
                            size_hint_y: None
                            height: dp(140)
                    SectionCard:
                        BoxLayout:
                            size_hint_y: None
                            height: dp(24)
                            Label:
                                text: 'NR SINR'
                                font_size: sp(16)
                                bold: True
                                color: app.c_text
                                halign: 'left'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.45
                            Label:
                                id: chart_nr_sinr_lbl
                                text: '-'
                                font_size: sp(18)
                                bold: True
                                color: app.c_text
                                halign: 'right'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.45
                            Label:
                                id: chart_nr_sinr_dot
                                text: '•'
                                font_size: sp(16)
                                color: app.c_sub
                                halign: 'center'
                                valign: 'middle'
                                text_size: self.size
                                size_hint_x: 0.1
                        SignalGraph:
                            id: chart_nr_sinr
                            size_hint_y: None
                            height: dp(140)
                Widget:
                    size_hint_y: None
                    height: dp(16)
        BottomNav:
            id: bottom_nav

<MapScreen>:
    name: 'map'
    canvas.before:
        Color:
            rgba: app.c_bg
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        orientation: 'vertical'
        Header:
            title: root.lbl_title
        ScrollView:
            id: content_scroll
            bar_width: dp(8)
            scroll_type: ['bars', 'content']
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: dp(10)
                spacing: dp(10)
                SectionCard:
                    InfoLabel:
                        id: map_note_lbl
                        text: ''
                SectionCard:
                    SectionTitle:
                        text: root.lbl_cells_title
                    InfoLabel:
                        id: map_cells_lbl
                        text: ''
                Widget:
                    size_hint_y: None
                    height: dp(16)
        BottomNav:
            id: bottom_nav

<CellsScreen>:
    name: 'cells'
    canvas.before:
        Color:
            rgba: app.c_bg
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        orientation: 'vertical'
        padding: dp(8)
        spacing: dp(6)
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)
            Label:
                id: log_day_lbl
                text: ''
                font_size: sp(24)
                bold: True
                color: app.c_text
                halign: 'left'
                valign: 'middle'
                text_size: self.size
                size_hint_x: 0.8
            FlatButton:
                text: '⋮'
                font_size: sp(22)
                size_hint_x: 0.2
                on_release: app.open_menu()
        Widget:
            size_hint_y: None
            height: dp(6)
            size_hint_x: 0.25
            canvas.before:
                Color:
                    rgba: 0, 0.72, 0.58, 1
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(3)]
        ScrollView:
            id: content_scroll
            bar_width: dp(8)
            scroll_type: ['bars', 'content']
            BoxLayout:
                id: cells_content
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                spacing: dp(8)
                BoxLayout:
                    id: log_list
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    spacing: dp(2)
                BoxLayout:
                    size_hint_y: None
                    height: dp(48)
                    spacing: dp(8)
                    Label:
                        text: root.lbl_detail_title
                        font_size: sp(18)
                        bold: True
                        color: app.c_text
                        halign: 'left'
                        valign: 'middle'
                        text_size: self.size
                        size_hint_x: 0.6
                    FlatButton:
                        text: root.lbl_export_csv
                        font_size: sp(14)
                        size_hint_x: 0.4
                        on_release: app.export_detail_csv()
                BoxLayout:
                    id: detail_list
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    spacing: dp(8)
                Widget:
                    size_hint_y: None
                    height: dp(16)
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            spacing: dp(8)
            FlatButton:
                id: filter_btn
                text: root.lbl_filter
                font_size: sp(15)
                on_release: app.cycle_cells_filter()
            FlatButton:
                text: root.lbl_copy_log
                font_size: sp(15)
                on_release: app.copy_cells_log()
            FlatButton:
                text: root.lbl_survey
                font_size: sp(15)
                on_release: app.open_survey()
        BottomNav:
            id: bottom_nav

<SettingsScreen>:
    name: 'settings'
    canvas.before:
        Color:
            rgba: app.c_bg
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        orientation: 'vertical'
        padding: dp(8)
        spacing: dp(6)
        BoxLayout:
            size_hint_y: None
            height: dp(56)
            spacing: dp(8)
            FlatButton:
                text: '←'
                font_size: sp(28)
                size_hint_x: None
                width: dp(56)
                on_release: app.go('monitor')
            Label:
                text: ''
        Label:
            text: root.lbl_title
            font_size: sp(36)
            bold: True
            color: app.c_text
            halign: 'left'
            valign: 'middle'
            text_size: self.size
            size_hint_y: None
            height: dp(56)
        ScrollView:
            id: content_scroll
            bar_width: dp(8)
            scroll_type: ['bars', 'content']
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                spacing: dp(4)
                Label:
                    text: root.lbl_prefs
                    font_size: sp(16)
                    bold: True
                    color: 0, 0.72, 0.58, 1
                    halign: 'left'
                    valign: 'middle'
                    text_size: self.size
                    size_hint_y: None
                    height: dp(36)
                BoxLayout:
                    id: settings_rows
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    spacing: dp(4)
                Widget:
                    size_hint_y: None
                    height: dp(16)

<SettingsRow>:
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(84)
    padding: dp(4), dp(4)
    spacing: dp(12)

<InfoScreen>:
    name: 'info'
    canvas.before:
        Color:
            rgba: app.c_bg
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        orientation: 'vertical'
        Header:
            title: root.lbl_title
        ScrollView:
            id: content_scroll
            bar_width: dp(8)
            scroll_type: ['bars', 'content']
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: dp(10)
                spacing: dp(10)
                SectionCard:
                    SectionTitle:
                        text: root.lbl_tower_title
                    InfoLabel:
                        id: tower_block
                        text: ''
                SectionCard:
                    SectionTitle:
                        text: root.lbl_cells_title
                    InfoLabel:
                        id: cells_block
                        text: ''
                SectionCard:
                    SectionTitle:
                        text: root.lbl_sim_title
                    InfoLabel:
                        id: sim_block
                        text: ''
                SectionCard:
                    SectionTitle:
                        text: root.lbl_status_title
                    InfoLabel:
                        id: status_block
                        text: ''
                Widget:
                    size_hint_y: None
                    height: dp(16)
        BottomNav:
            id: bottom_nav

<ToolsScreen>:
    name: 'tools'
    canvas.before:
        Color:
            rgba: app.c_bg
        Rectangle:
            pos: self.pos
            size: self.size
    BoxLayout:
        orientation: 'vertical'
        Header:
            title: root.lbl_title
        ScrollView:
            id: content_scroll
            bar_width: dp(8)
            scroll_type: ['bars', 'content']
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: dp(10)
                spacing: dp(12)
                AutoLabel:
                    text: root.net_msg
                    color: root.net_msg_color
                    bold: True
                    height: (self.texture_size[1] + dp(6)) if self.text else 0
                SectionCard:
                    SectionTitle:
                        text: root.lbl_bandlock
                    HintLabel:
                        text: root.hint_bandlock
                    AutoLabel:
                        text: root.lock_state
                        bold: True
                    GridLayout:
                        id: bands_grid
                        cols: 2
                        size_hint_y: None
                        height: self.minimum_height
                        spacing: dp(4)
                    FlatButton:
                        text: root.lbl_mark_current
                        size_hint_y: None
                        height: dp(48)
                        on_release: app.mark_current_bands()
                    ActionButton:
                        text: root.lbl_apply_bands
                        on_release: app.apply_bands()
                    BoxLayout:
                        size_hint_y: None
                        height: dp(52)
                        spacing: dp(8)
                        FlatButton:
                            text: root.lbl_reset_auto
                            on_release: app.reset_bands()
                        FlatButton:
                            text: root.lbl_restore
                            on_release: app.restore_bands()
                SectionCard:
                    SectionTitle:
                        text: root.lbl_antenna
                    Spinner:
                        id: antenna_spinner
                        text: root.antenna_text
                        values: root.antenna_values
                        font_size: sp(16)
                        size_hint_y: None
                        height: dp(48)
                    ActionButton:
                        text: root.lbl_apply_antenna
                        on_release: app.apply_antenna(antenna_spinner.text)
                SectionCard:
                    SectionTitle:
                        text: root.lbl_router
                    HintLabel:
                        text: root.hint_router
                    FlatButton:
                        text: root.lbl_reattach
                        size_hint_y: None
                        height: dp(52)
                        on_release: app.confirm_reattach()
                    FlatButton:
                        text: root.lbl_reboot
                        size_hint_y: None
                        height: dp(52)
                        on_release: app.confirm_reboot()
                    FlatButton:
                        text: root.lbl_diag
                        size_hint_y: None
                        height: dp(52)
                        on_release: app.copy_diagnostics()
                SectionCard:
                    SectionTitle:
                        text: root.lbl_whitelist
                    HintLabel:
                        text: root.hint_whitelist
                    ActionButton:
                        text: root.lbl_wl_check
                        on_release: app.whitelist_check()
                    AutoLabel:
                        text: root.wl_verdict
                        font_size: sp(16)
                        bold: True
                        color: root.wl_color
                    AutoLabel:
                        text: root.wl_detail
                        font_size: sp(13)
                Widget:
                    size_hint_y: None
                    height: dp(16)
        BottomNav:
            id: bottom_nav
"""


# =========================================================
# ЭКРАНЫ
# =========================================================

class ConnectionScreen(Screen):
    subtitle = StringProperty("")
    lbl_ip = StringProperty("")
    lbl_pw = StringProperty("")
    lbl_find = StringProperty("")
    lbl_connect = StringProperty("")
    lbl_lang = StringProperty("")
    lbl_demo = StringProperty("")
    lbl_help = StringProperty("")
    lang_name = StringProperty("")
    lang_values = ListProperty([])
    status_color = ListProperty([0.9, 0.5, 0.2, 1])

    def on_pre_enter(self, *args: Any) -> None:
        self.refresh_texts()

    def refresh_texts(self) -> None:
        self.subtitle = t("Портативный монитор LTE/5G Huawei")
        self.lbl_ip = t("IP адрес:")
        self.lbl_pw = t("Пароль:")
        self.lbl_find = t("Найти")
        self.lbl_connect = t("Подключиться")
        self.lbl_lang = t("Язык:")
        self.lbl_demo = t("Тестовый режим (без модема)")
        self.lbl_help = t("Подсказка")
        self.lang_values = list(LANGUAGES.values())
        self.lang_name = LANGUAGES.get(current_language(), "Русский")

    def set_status(self, text: str, color: list[float]) -> None:
        lbl = self.ids.get('status_lbl')
        if lbl is not None:
            lbl.text = text
        self.status_color = color

    def on_language(self, name: str) -> None:
        App.get_running_app().apply_language(name)

    def on_help(self) -> None:
        App.get_running_app().show_popup(t("Подключение и частые ошибки"), t(
            "IP по умолчанию: 192.168.8.1 (для B315/B525 — 192.168.1.1 или "
            "192.168.3.1) — кнопка «Найти» проверит их сама. Логин: admin, "
            "пароль — на наклейке роутера.\n\n"
            "Частые ошибки и что делать:\n"
            "• 108006 — неверный логин или пароль.\n"
            "• 108007 — слишком много неудачных попыток: роутер временно "
            "заблокировал вход. Подождите несколько минут.\n"
            "• 108003 — уже выполнен вход с другого устройства. Закройте "
            "веб-интерфейс роутера.\n"
            "• 100002 — функция не поддерживается этой моделью или "
            "прошивкой. Часть возможностей будет недоступна — это нормально.\n"
            "• 100003 / 125002 / 125003 — истекла сессия. Программа войдёт "
            "заново сама.\n"
            "• Нет ответа — проверьте, что телефон подключён к Wi-Fi именно "
            "этого роутера и IP введён верно.\n\n"
            "Тестовый режим показывает работу программы без роутера."))

    def on_find(self) -> None:
        ip_input = self.ids.get('ip_input')
        entered = ip_input.text.strip() if ip_input is not None else ''
        App.get_running_app().discover(entered)

    def on_connect(self) -> None:
        ip_input, pw_input = self.ids.get('ip_input'), self.ids.get('pw_input')
        if ip_input is None or pw_input is None:
            return
        ip = ip_input.text.strip()
        if not is_valid_ip(ip):
            self.set_status(t("Неверный IP-адрес: {ip}\nПример: 192.168.8.1").format(ip=ip),
                            [0.9, 0.3, 0.3, 1])
            return
        App.get_running_app().connect(ip, pw_input.text)


class NavButton(ButtonBehavior, BoxLayout):
    """Bottom pill-bar button: icon above, label below, green when active."""
    nav_icon = StringProperty("")
    nav_text = StringProperty("")
    nav_target = StringProperty("")
    nav_icon_box = BooleanProperty(False)
    active = BooleanProperty(False)


class ChipLabel(Label):
    """Bordered chip label (RAT / band) used in the Log and Charts tabs."""
    chip_color = ListProperty([1, 1, 1, 1])


class LogRow(ButtonBehavior, BoxLayout):
    """One Registro row: identity line + band/samples line, thin divider.

    Pressable: opens the cell detail popup for that observation."""


class BandLockSheet(BoxLayout):
    """Bottom sheet for Band Lock (Recientes / Rutinas)."""
    sheet_title = StringProperty("")
    tab_recent_text = StringProperty("")
    tab_routines_text = StringProperty("")
    new_lock_text = StringProperty("")
    unlock_all_text = StringProperty("")


class MonitorScreen(Screen):
    lbl_fullscreen = StringProperty("")
    lbl_sound = StringProperty("")
    lbl_peaks = StringProperty("")
    lbl_menu = StringProperty("")
    lbl_tools = StringProperty("")
    lbl_band_lock = StringProperty("")
    lbl_bars_title = StringProperty("")
    lbl_ca_title = StringProperty("")
    graph_values = ListProperty(list(LTE_PARAMS))
    status_color = ListProperty([0.2, 0.8, 0.4, 1])
    advice_color = ListProperty([0.95, 0.62, 0.25, 1])

    def on_pre_enter(self, *args: Any) -> None:
        self.refresh_texts()

    def refresh_texts(self) -> None:
        self.lbl_fullscreen = t("Во весь экран")
        self.lbl_sound = t("♪ Звук")
        self.lbl_peaks = t("⟲ Пики")
        self.lbl_menu = t("☰ Меню")
        self.lbl_tools = t("Инструменты")
        self.lbl_band_lock = t("Блокировка бэндов")
        self.lbl_bars_title = t("Сигнал по метрикам")
        self.lbl_ca_title = t("Агрегация (CA)")


class TopScrollScreen(Screen):
    """Reset once on entry, after dynamic text/layout has settled."""

    def on_enter(self, *args: Any) -> None:
        Clock.schedule_once(self._scroll_top, 0)

    def _scroll_top(self, _dt: float) -> None:
        if self.manager is not None and self.manager.current == self.name:
            self.ids.content_scroll.scroll_y = 1


class InfoScreen(TopScrollScreen):
    lbl_title = StringProperty("")
    lbl_tower_title = StringProperty("")
    lbl_cells_title = StringProperty("")
    lbl_sim_title = StringProperty("")
    lbl_status_title = StringProperty("")

    def on_pre_enter(self, *args: Any) -> None:
        self.refresh_texts()
        App.get_running_app().refresh_info_screen()

    def refresh_texts(self) -> None:
        self.lbl_title = t("Информация")
        self.lbl_tower_title = t("Информация о станции")
        self.lbl_cells_title = t("Лучшие соты за сессию")
        self.lbl_sim_title = t("SIM / Устройство")
        self.lbl_status_title = t("Состояние")


class ChartsScreen(TopScrollScreen):
    """NetMonster-style Charts tab: one mini-graph card per metric."""
    lbl_title = StringProperty("")

    def on_pre_enter(self, *args: Any) -> None:
        self.refresh_texts()
        App.get_running_app().refresh_charts_screen()

    def refresh_texts(self) -> None:
        self.lbl_title = t("Графики")


class MapScreen(TopScrollScreen):
    """NetMonster-style Map tab — without GPS there are no tower positions.

    The router never reports coordinates, so this screen explains that
    and lists the observed cells (no locations invented).
    """
    lbl_title = StringProperty("")
    lbl_cells_title = StringProperty("")

    def on_pre_enter(self, *args: Any) -> None:
        self.refresh_texts()
        App.get_running_app().refresh_map_screen()

    def refresh_texts(self) -> None:
        self.lbl_title = t("Карта")
        self.lbl_cells_title = t("Соседние соты")


class CellsScreen(TopScrollScreen):
    """NetMonster-style Log tab (Registro): observed cells, today first."""
    lbl_filter = StringProperty("")
    lbl_survey = StringProperty("")
    lbl_copy_log = StringProperty("")
    lbl_detail_title = StringProperty("")
    lbl_export_csv = StringProperty("")

    def on_pre_enter(self, *args: Any) -> None:
        self.refresh_texts()
        App.get_running_app().refresh_cells_screen()

    def refresh_texts(self) -> None:
        self.lbl_filter = App.get_running_app().filter_label()
        self.lbl_survey = t("Сканер наблюдений · Beta")
        self.lbl_copy_log = t("Копировать журнал")
        self.lbl_detail_title = t("Подробный журнал по бэндам")
        self.lbl_export_csv = t("Экспорт CSV")


class BellIcon(Widget):
    """Bell drawn with canvas: DejaVu Sans has no bell glyph (🔔)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        from kivy.graphics import Color, Ellipse, Line
        with self.canvas:
            Color(0, 0.72, 0.58, 1)
            self._dome = Ellipse(angle_start=0, angle_end=180)
            self._flare = Line(width=dp(2))
            self._clapper = Ellipse()
            self._knob = Ellipse()
        self.bind(pos=self._draw, size=self._draw)

    def _draw(self, *_: Any) -> None:
        w, h = self.size
        cx = self.x + w / 2
        dome_w, dome_h = w * 0.62, h * 0.52
        dome_x = cx - dome_w / 2
        dome_y = self.y + h * 0.30
        self._dome.pos = (dome_x, dome_y)
        self._dome.size = (dome_w, dome_h)
        self._flare.points = [cx - dome_w * 0.62, dome_y + dp(1),
                              cx + dome_w * 0.62, dome_y + dp(1)]
        cl = dp(5)
        self._clapper.pos = (cx - cl / 2, dome_y - cl - dp(1))
        self._clapper.size = (cl, cl)
        knob = dp(5)
        self._knob.pos = (cx - knob / 2, dome_y + dome_h - dp(2))
        self._knob.size = (knob, knob)


class SettingsRow(ButtonBehavior, BoxLayout):
    """One Ajustes row: icon tile + title/subtitle + trailing widget."""


class SettingsScreen(TopScrollScreen):
    """NetMonster-style Ajustes screen: preferences rows."""
    lbl_title = StringProperty("")
    lbl_prefs = StringProperty("")

    def on_pre_enter(self, *args: Any) -> None:
        self.refresh_texts()
        App.get_running_app().refresh_settings_screen()

    def refresh_texts(self) -> None:
        self.lbl_title = t("Настройки")
        self.lbl_prefs = t("Предпочтения").upper()


class ToolsScreen(TopScrollScreen):
    lbl_title = StringProperty("")
    lbl_bandlock = StringProperty("")
    hint_bandlock = StringProperty("")
    lock_state = StringProperty("")
    lbl_mark_current = StringProperty("")
    lbl_apply_bands = StringProperty("")
    lbl_reset_auto = StringProperty("")
    lbl_restore = StringProperty("")
    lbl_antenna = StringProperty("")
    lbl_apply_antenna = StringProperty("")
    antenna_text = StringProperty("")
    antenna_values = ListProperty([])
    lbl_router = StringProperty("")
    hint_router = StringProperty("")
    lbl_reattach = StringProperty("")
    lbl_reboot = StringProperty("")
    lbl_diag = StringProperty("")
    lbl_whitelist = StringProperty("")
    hint_whitelist = StringProperty("")
    lbl_wl_check = StringProperty("")
    wl_verdict = StringProperty("")
    wl_detail = StringProperty("")
    wl_color = ListProperty([0.5, 0.5, 0.5, 1])
    net_msg = StringProperty("")
    net_msg_color = ListProperty([0.5, 0.5, 0.5, 1])

    def on_pre_enter(self, *args: Any) -> None:
        self.refresh_texts()
        app = App.get_running_app()
        app.build_band_checkboxes()
        app.load_router_config()

    def refresh_texts(self) -> None:
        self.lbl_title = t("Сеть")
        self.lbl_bandlock = t("Фиксация частот (Band Lock)")
        self.hint_bandlock = t(
            "Список взят из модема; замеченные в эфире бэнды — первыми. "
            "Меняются только LTE-бэнды; «Как было» восстановит настройки, "
            "прочитанные при подключении.")
        self.lbl_mark_current = t("Отметить текущие")
        self.lbl_apply_bands = t("Применить Band Lock")
        self.lbl_reset_auto = t("Все (AUTO)")
        self.lbl_restore = t("↩ Как было")
        self.lbl_antenna = t("Переключение антенн")
        self.lbl_apply_antenna = t("Применить")
        self.antenna_values = [t(k) for k in ANTENNA_MODES]
        if not self.antenna_text:
            self.antenna_text = t("Не прочитано")
        self.lbl_router = t("Управление роутером")
        self.hint_router = t(
            "«Переподключить связь» выключает и включает мобильные данные. "
            "Интернет временно пропадёт. После перезагрузки программа переподключится сама.")
        self.lbl_reattach = t("Переподключить связь")
        self.lbl_reboot = t("Перезагрузить роутер")
        self.lbl_diag = t("Скопировать диагностику")
        self.lbl_whitelist = t("Белые списки (РФ)")
        self.hint_whitelist = t(
            "⚠ Телефон должен быть подключён к Wi-Fi именно этого "
            "роутера — иначе тест измерит чужой канал. Применимо только для РФ.")
        self.lbl_wl_check = t("Проверить сейчас")


# =========================================================
# ПРИЛОЖЕНИЕ
# =========================================================

class Hua4GMonApp(App):
    theme_name = StringProperty('dark')
    c_bg = ListProperty(THEMES['dark']['c_bg'])
    c_card = ListProperty(THEMES['dark']['c_card'])
    c_text = ListProperty(THEMES['dark']['c_text'])
    c_sub = ListProperty(THEMES['dark']['c_sub'])
    c_accent = ListProperty(THEMES['dark']['c_accent'])
    c_button2 = ListProperty(THEMES['dark']['c_button2'])
    c_grid = ListProperty(THEMES['dark']['c_grid'])
    sound_on = BooleanProperty(False)
    background_monitoring = BooleanProperty(True)
    lbl_back = StringProperty("")
    nav_monitor = StringProperty("")
    nav_charts = StringProperty("")
    nav_map = StringProperty("")
    nav_cells = StringProperty("")
    nav_menu = StringProperty("")
    nav_info = StringProperty("")
    nav_tools = StringProperty("")

    # ---------- запуск и жизненный цикл ----------

    def build(self) -> ScreenManager:
        from kivy.core.window import Window
        Window.clearcolor = tuple(self.c_bg)
        Window.softinput_mode = 'below_target'
        Window.bind(on_keyboard=self._on_keyboard)
        if os.path.exists(_FONT_PATH):
            bold = _FONT_BOLD_PATH if os.path.exists(_FONT_BOLD_PATH) else _FONT_PATH
            LabelBase.register(name='Roboto', fn_regular=_FONT_PATH, fn_bold=bold)
        self.title = f"{APP_NAME} v{__version__}"
        # Журнал сессии нужен только для экспорта CSV, которого на Android нет.
        self.survey = Survey()
        self.state = SignalState(track_trend=False, trend_param='sinr', log_max=GRAPH_HISTORY)
        self.session: RouterSession | None = None
        self.worker: SessionWorker | None = None
        self.demo_modem: DemoModem | None = None
        self.link = 'offline'
        self.interval = 1.0
        self.band_vars: dict[int, Any] = {}
        self._band_list: list[int] = list(REGION_BANDS)
        self._bands_shown: list[int] = []
        self._busy = False
        self._discovering = False       # идёт автопоиск роутера
        self._wl_running = False        # идёт проверка белых списков
        self._fs_graph: SignalGraph | None = None
        self._last_back = 0.0
        self._beep_ev: Any = None
        self.beeper = ToneBeeper()
        self.cells_filter = 'all'  # Registro filter: all / 4g / 3g / 5g
        self._recent_locks: list[tuple[int, ...]] = []
        self._lock_sheet: Any = None
        self._lock_sheet_tab = 'recent'
        self.lbl_back = t("← Назад")
        self.nav_monitor = t("Монитор")
        self.nav_charts = t("Графики")
        self.nav_map = t("Карта")
        self.nav_cells = t("Соты")
        self.nav_menu = t("Меню")
        self.nav_info = t("Информация")
        self.nav_tools = t("Сеть")
        self.sm: ScreenManager = Builder.load_string(KV)
        Clock.schedule_interval(self._tick, 0.5)
        return self.sm

    def on_pause(self) -> bool:
        """Свернули приложение: без фонового мониторинга опрос на паузу."""
        if not self.background_monitoring and self.worker is not None:
            self.worker.pause()
        self._stop_beeps()
        return True

    def on_resume(self) -> None:
        if self.worker is not None:
            self.worker.resume()
        if self.sound_on:
            self._schedule_beep()

    def on_stop(self) -> None:
        worker = self.worker
        if worker is not None:
            worker.stop()
            worker.join(timeout=2.0)       # дать отправить logout
        self.beeper.release()
        set_keep_screen_on(False)

    # ---------- тема, тексты, навигация ----------

    def apply_theme(self, name: str) -> None:
        from kivy.core.window import Window
        self.theme_name = name
        for key, value in THEMES[name].items():
            if hasattr(self, key):
                setattr(self, key, value)
        Window.clearcolor = tuple(self.c_bg)
        self._bands_shown = []          # подписи бэндов — заново, в цвете темы
        self.build_band_checkboxes()
        self.refresh_nav_highlight()
        if self.state.last is not None:
            self._render(self.state.last)
        else:
            self.refresh_graph()

    def refresh_all_texts(self) -> None:
        self._bands_shown = []
        self.build_band_checkboxes()
        self.lbl_back = t("← Назад")
        self.nav_monitor = t("Монитор")
        self.nav_charts = t("Графики")
        self.nav_map = t("Карта")
        self.nav_cells = t("Соты")
        self.nav_menu = t("Меню")
        self.nav_info = t("Информация")
        self.nav_tools = t("Сеть")
        for name in ('connection', 'monitor', 'charts', 'map', 'cells', 'info', 'tools', 'settings'):
            self.sm.get_screen(name).refresh_texts()
        self.refresh_nav_highlight()
        self._render_link_state()
        if self.state.last is not None:
            self._render(self.state.last)

    def go(self, screen: str) -> None:
        self.sm.current = screen
        self.refresh_nav_highlight()

    def refresh_nav_highlight(self) -> None:
        """Active tab in the bottom pill gets the dark-green background."""
        if getattr(self, 'sm', None) is None:
            return
        current = self.sm.current
        for scr in self.sm.screens:
            for btn in scr.walk():
                if btn.__class__.__name__ == 'NavButton':
                    btn.active = (btn.nav_target == current)

    def _on_keyboard(self, window: Any, key: int, *args: Any) -> bool:
        """Системная «Назад» (Esc на десктопе).

        Hardware validation required: жест «Назад» Android 13+ на устройстве.
        """
        if key != 27:
            return False
        if any(isinstance(w, ModalView) for w in window.children):
            return False            # открытый диалог закроется сам
        current = self.sm.current
        if current in ('info', 'tools', 'cells', 'charts', 'map', 'settings'):
            self.sm.current = 'monitor'
            return True
        if current == 'monitor':
            now = time.monotonic()
            if now - self._last_back < 2.0:
                self.disconnect()
            else:
                self._last_back = now
                self.toast(t("Нажмите «Назад» ещё раз, чтобы отключиться"))
            return True
        return False                # экран подключения — стандартный выход

    # ---------- подключение ----------

    def _conn_screen(self) -> ConnectionScreen:
        return self.sm.get_screen('connection')

    def discover(self, entered: str) -> None:
        # Повторное нажатие во время поиска игнорируется: иначе результат
        # первого поиска мог бы прийти последним и затереть второй.
        if self._discovering:
            return
        self._discovering = True
        scr = self._conn_screen()
        scr.set_status(t("Ищу роутер…"), [0.3, 0.6, 0.95, 1])
        candidates = ([entered] if is_valid_ip(entered) else []) + list(DISCOVERY_CANDIDATES)

        def done(found: Any) -> None:
            self._discovering = False
            if found is None:
                scr.set_status(t("Роутер не найден. Проверьте подключение к его Wi-Fi/USB."),
                               [0.9, 0.3, 0.3, 1])
                return
            ip_input = scr.ids.get('ip_input')
            if ip_input is not None:
                ip_input.text = found.ip
            scr.set_status(t("Найден роутер {model} на {ip}").format(
                model=found.model or "Huawei", ip=found.ip), [0.2, 0.75, 0.45, 1])
        binder = None
        if platform == 'android':
            from core.local_transport import bind_android_socket
            binder = bind_android_socket
        self._run_bg(lambda: discover_router(candidates, socket_binder=binder),
                     done, lambda e: done(None))

    def connect(self, ip: str, password: str) -> None:
        if self.worker is not None:
            return
        self.demo_modem = None
        self._conn_screen().set_status(t("Подключение..."), [0.9, 0.6, 0.2, 1])
        factory = None
        if platform == 'android':
            from functools import partial

            from core.local_transport import bind_android_socket
            from core.router import huawei_client_factory
            factory = partial(huawei_client_factory, socket_binder=bind_android_socket)
        self._start_session(RouterSession(ip, password, factory=factory))

    def start_demo(self) -> None:
        if self.worker is not None:
            return
        self.demo_modem = DemoModem()
        self._start_session(RouterSession("demo", "", factory=demo_factory(self.demo_modem)))

    def _start_session(self, session: RouterSession) -> None:
        self.survey = Survey()
        self._survey_searching = False
        self.state.reset()
        self.session = session
        for cb in self.band_vars.values():
            cb.active = False
        self._band_list = list(REGION_BANDS)
        self._bands_shown = []
        self.build_band_checkboxes()
        tools = self._tools()
        tools.antenna_text = t("Не прочитано")
        tools.lock_state = t("Сейчас на модеме: не прочитано")
        tools.net_msg = tools.wl_verdict = tools.wl_detail = ""
        self._wl_running = False
        monitor = self.sm.get_screen('monitor')
        monitor.graph_values = list(LTE_PARAMS)
        if self.state.trend_param not in LTE_PARAMS:
            monitor.ids.graph_param.text = 'sinr'
            self.state.set_trend_param('sinr')
        monitor.ids.signal_graph.auto()
        self._render(Snapshot())
        self._show_last_event()
        self.refresh_info_screen()
        self.refresh_cells_screen()
        self.refresh_charts_screen()
        self.refresh_map_screen()
        worker: SessionWorker | None = None

        def mine(fn: Callable[..., None]) -> Callable[..., None]:
            """Событие фонового потока → главный поток, только для текущей сессии."""
            def post(*args: Any) -> None:
                def call(_dt: float) -> None:
                    if worker is self.worker:
                        fn(*args)
                Clock.schedule_once(call)
            return post

        worker = SessionWorker(
            session, interval=lambda: self.interval,
            on_connected=mine(self._on_connected), on_snapshot=mine(self._on_snapshot),
            on_metadata=mine(self._on_metadata),
            on_status=mine(self._on_status), on_fatal=mine(self._on_fatal))
        self.worker = worker
        self.link = 'connecting'
        worker.start()

    def disconnect(self) -> None:
        """Мгновенно для UI: выход из роутера выполняет фоновый поток."""
        self.survey.stop()
        if self.worker is not None:
            self.worker.stop()
        self.worker = None
        self.session = None
        self.demo_modem = None
        self.link = 'offline'
        self._wl_token = None
        self._wl_running = False
        self._survey_searching = False
        self._busy = False
        self._stop_beeps()
        set_keep_screen_on(False)
        self._conn_screen().set_status("", [0.5, 0.5, 0.5, 1])
        self.sm.current = 'connection'

    def _on_connected(self, info: dict[str, Any]) -> None:
        self.link = 'online'
        session = self.session
        if session is not None:
            self._band_list = lockable_bands(session.supported_bands, self.state.observed_bands)
        self._conn_screen().set_status("", [0.5, 0.5, 0.5, 1])
        self.sm.current = 'monitor'
        set_keep_screen_on(True)
        self._render_link_state()
        self._show_last_event()         # не текст ошибки прошлой сессии
        if self.sound_on:
            self._schedule_beep()

    def _on_metadata(self, info: dict[str, Any]) -> None:
        if self.session is not None:
            self._band_list = lockable_bands(self.session.supported_bands, self.state.observed_bands)
            self.build_band_checkboxes()
            self.refresh_info_screen()

    def _show_last_event(self) -> None:
        ev = self.sm.get_screen('monitor').ids.get('event_lbl')
        if ev is not None:
            ev.text = self._event_text(self.state.events[-1]) if self.state.events else ""

    def _on_status(self, status: str, delay: float | None, exc: BaseException | None) -> None:
        recovered = self.link == 'reconnecting' and status != 'reconnecting'
        self.link = 'reconnecting' if status == 'reconnecting' else 'online'
        self._render_link_state(humanize_error(exc) if exc is not None else "")
        if recovered:
            # Строка событий показывала ошибку связи — возвращаем последнее событие.
            self._show_last_event()

    def _on_fatal(self, exc: BaseException) -> None:
        self.disconnect()
        self._conn_screen().set_status(humanize_error(exc), [0.9, 0.3, 0.3, 1])

    @staticmethod
    def _event_text(change: Any) -> str:
        return t("{at} смена соты: {old} → {new}").format(
            at=change.at, old=change.old_label, new=change.new_label)

    def _render_link_state(self, detail: str = "") -> None:
        scr = self.sm.get_screen('monitor')
        lbl = scr.ids.get('status_lbl')
        if lbl is None:
            return
        sun = self.theme_name == 'sun'
        if self.link == 'reconnecting':
            lbl.text = t("Нет связи с роутером — переподключаюсь…")
            scr.status_color = hex_to_rgba('#e68033', sun)
            ev = scr.ids.get('event_lbl')
            if detail and ev is not None:
                ev.text = detail
        elif self.demo_modem is not None:
            lbl.text = t("Тестовый режим")
            scr.status_color = hex_to_rgba('#e68033', sun)

    # ---------- данные ----------

    def _on_snapshot(self, snap: Snapshot) -> None:
        if getattr(self, '_survey_searching', False):
            return
        self.survey.observe(snap)
        if self.survey.running and '_survey_cells' in snap.raw:
            self.survey.accept_cells(snap.raw['_survey_cells'])
        if self.survey.running:
            for source, data in snap.raw.get('_extra_cells', {}).items():
                self.survey.accept_cells(data, source)
            for source, error in snap.raw.get('_extra_cell_errors', {}).items():
                message = source + ': ' + error
                if message not in self.survey.messages:
                    self.survey.messages.append(message)
        if self.survey.running and snap.raw.get('_survey_error'):
            message = str(snap.raw['_survey_error'])
            if message not in self.survey.messages:
                self.survey.messages.append(message)
        if self.survey.running:
            self._refresh_survey()
        change = self.state.ingest(snap, time.monotonic())
        scr = self.sm.get_screen('monitor')
        if change is not None:
            ev = scr.ids.get('event_lbl')
            if ev is not None:
                ev.text = self._event_text(change)
        if snap.has_nr and 'nr_sinr' not in scr.graph_values:
            scr.graph_values = LTE_PARAMS + NR_PARAMS
        if any(b not in self._band_list for b in snap.bands) and self.session is not None:
            self._band_list = lockable_bands(self.session.supported_bands,
                                             self.state.observed_bands)
        self._render(snap)

    def _tick(self, _dt: float) -> None:
        """Каждые 0.5 с: признак устаревших данных."""
        if self.link not in ('online', 'reconnecting') or self.state.last is None:
            return
        now = time.monotonic()
        if self.state.is_stale(now, self.interval):
            scr = self.sm.get_screen('monitor')
            lbl = scr.ids.get('status_lbl')
            if lbl is not None:
                lbl.text = t("⚠ Данные устарели — нет ответа {s:.0f} с").format(
                    s=self.state.age(now) or 0)
                scr.status_color = hex_to_rgba('#d63031', self.theme_name == 'sun')
            self.refresh_graph(stale=True)

    def _metric_card(self, card: Any, param: str) -> None:
        val = self.state.current(param)
        label, color, _ = evaluate_signal(param.replace('nr_', ''), val)
        card.m_name = PARAM_TITLES.get(param, param.upper())
        card.m_value = fmt_num(val)
        card.m_status = t(label)
        card.m_color = hex_to_rgba(color, self.theme_name == 'sun')
        peak, delta = self.state.peaks.get(param), self.state.delta_to_peak(param)
        card.m_peak = "" if peak is None or delta is None else \
            t("Пик: {v} (Δ {d})").format(v=fmt_num(peak), d=f"{delta:+g}")

    def _layout_params(self) -> list[str]:
        """Крупно — выбранная метрика, рядом RSRP (или SINR), мелко — остальные."""
        primary = self.state.trend_param
        secondary = 'rsrp' if primary not in ('rsrp', 'nr_rsrp') else 'sinr'
        rest = [p for p in LTE_PARAMS if p not in (primary, secondary)][:2]
        return [primary, secondary, *rest]

    def _render(self, snap: Snapshot) -> None:
        snap = snap.display()
        scr = self.sm.get_screen('monitor')
        ids = scr.ids
        if not ids:
            return
        sun = self.theme_name == 'sun'
        score, summary, color = calculate_overall_health(snap.rsrp, snap.sinr)
        if not snap.registered:
            score, summary, color = 0, snap.network_message, 'gray'
        health = ('LTE · ' if snap.registered else '') + t(summary).format(pct=score)
        if self.demo_modem is not None:
            health = t("ДЕМО · азимут {a}").format(
                a=demo_angle_hint(self.demo_modem)) + " · " + health
        ids.status_lbl.text = health
        scr.status_color = hex_to_rgba(color, sun)
        ids.tower_lbl.text = self._tower_summary(snap)
        self._update_netmonster(snap, score, summary, color)
        cards = (ids.primary_box, ids.secondary_box, ids.small1_box, ids.small2_box)
        for card, param in zip(cards, self._layout_params(), strict=True):
            self._metric_card(card, param)

        mimo = mimo_status(snap.cqi0, snap.cqi1)
        up = uplink_status(snap.pusch_dbm)
        tips = advice(rsrp=snap.rsrp, sinr=snap.sinr, rsrq=snap.rsrq,
                      jitter=self.state.jitter(), mimo=mimo, uplink=up)
        if not snap.registered:
            tips = []
        elif snap.connection != 901 or snap.data_enabled is False:
            tips.insert(0, snap.network_message)
        ids.advice_lbl.text = "\n".join("• " + t(tip) for tip in tips[:2])
        scr.advice_color = hex_to_rgba('#e68033', sun)
        self.refresh_graph()
        if self.sm.current == 'info':
            self.refresh_info_screen()
        if self.sm.current == 'cells':
            self.refresh_cells_screen()
        if self.sm.current == 'charts':
            self.refresh_charts_screen()

    def _tower_summary(self, snap: Snapshot) -> str:
        snap = snap.display()
        parts = [] if snap.registered and snap.connection == 901 and snap.data_enabled is not False else [t(snap.network_message)]
        if len(snap.lte_carriers) > 1:
            parts.append(snap.band_label)
        elif snap.bands:
            freq = f" · {snap.freq_mhz:g} {t('МГц')}" if snap.freq_mhz else ""
            parts.append(f"B{snap.bands[0]}{freq}")
            if len(snap.bands) > 1:
                parts.append("CA " + "+".join(f"B{b}" for b in snap.bands[1:]))
        if snap.cell_id is not None:
            parts.append(f"Cell ID {snap.cell_id}")
        if snap.pci is not None:
            parts.append(f"PCI {snap.pci}")
        if snap.rat:
            parts.append(t(RAT_LABELS.get(snap.rat, snap.rat)))
        return " · ".join(parts) if parts else "—"

    # ---------- NetMonster-style presentation ----------

    def _update_netmonster(self, snap: Snapshot, score: int, summary: str,
                           color: str) -> None:
        """Fill the Live (En vivo) NetMonster header, grid, bars and CA."""
        scr = self.sm.get_screen('monitor')
        ids = scr.ids
        if not ids:
            return
        sun = self.theme_name == 'sun'
        ids['operator_lbl'].text = snap.operator or (
            snap.plmn or t("Оператор неизвестен"))
        ids['plmn_lbl'].text = format_plmn(snap.plmn) if snap.plmn else '-'
        line = rat_line(snap)
        ids['rat_lbl'].text = f"⚓ {line}" if line != '-' else '-'
        rows = net_rows_3g(snap) if snap.rat == '3g' else net_rows(snap)
        trends = {'rssi': 'rssi', 'rsrp': 'rsrp', 'rsrq': 'rsrq', 'snr': 'sinr'}
        for key, spec in rows.items():
            row = ids.get(f'net_{key}')
            if row is None:
                continue
            if spec is None:  # 3G: no CQI row
                row.height = 0
                row.opacity = 0
                continue
            label, value, unit = spec
            row.n_label = label
            row.n_value = value
            row.n_unit = unit
            row.height = dp(36)
            row.opacity = 1
            param = trends.get(key)
            if param is not None:
                arrow, arrow_color = trend_arrow(
                    [float(v) for v in self.state.history.get(param, [])])
                row.n_trend = arrow
                row.n_trend_color = hex_to_rgba(arrow_color, sun)
            else:
                row.n_trend = ''
        bar = ids.get('health_bar')
        if bar is not None:
            bar.bar_name = t("Здоровье сигнала")
            bar.bar_value = f"{score}%"
            bar.bar_status = (t(summary).format(pct=score) if snap.registered
                              else t(summary))
            bar.bar_hint = ''
            bar.bar_pct = score
            bar.bar_color = hex_to_rgba(color, sun)
        bars = {b.param: b for b in signal_bars(snap)}
        for key in ('rsrp', 'sinr', 'rsrq', 'rssi', 'cqi', 'nr_rsrp', 'nr_sinr'):
            row = ids.get(f'bar_{key}')
            if row is None:
                continue
            b = bars.get(key)
            if b is None:
                row.height = 0
                row.opacity = 0
                continue
            row.height = dp(76)
            row.opacity = 1
            row.bar_name = b.title
            row.bar_value = (f"{b.value:g} {b.unit}"
                             if b.value is not None else '-')
            row.bar_status = t(b.status) if b.status else ''
            row.bar_hint = b.explain
            row.bar_pct = b.pct
            row.bar_color = hex_to_rgba(b.color, sun)
        ca = ids.get('ca_lbl')
        if ca is not None:
            lines = carrier_lines(snap, t('МГц'))
            if lines:
                text = "\n".join(lines)
                if snap.ca is not None:
                    text += (f"\n{t('Агрегация (CA)')}: "
                             f"{t('Активна') if snap.ca else t('Нет')}")
                ca.text = text
            elif snap.ca is not None:
                ca.text = (f"{t('Агрегация (CA)')}: "
                           f"{t('Активна') if snap.ca else t('Нет')}")
            else:
                ca.text = t("Нет данных")

    # ---------- Registro (Log tab) ----------

    def filter_label(self) -> str:
        if self.cells_filter == 'all':
            return f"{t('Фильтры')}: {t('Все')}"
        return f"{t('Фильтры')}: {self.cells_filter.upper()}"

    def _filter_options(self) -> list[str]:
        options = ['all', '4g', '3g', '5g']
        for o in self.survey.ranked():
            band = (o.snap.band_label or '').strip()
            if band and band not in options:
                options.append(band)
        return options

    def cycle_cells_filter(self) -> None:
        options = self._filter_options()
        idx = options.index(self.cells_filter) if self.cells_filter in options else -1
        self.cells_filter = options[(idx + 1) % len(options)]
        scr = self.sm.get_screen('cells')
        scr.lbl_filter = self.filter_label()
        self.refresh_cells_screen()

    def _obs_matches_filter(self, obs: Any) -> bool:
        rat = obs.snap.rat
        if self.cells_filter == 'all':
            return True
        if self.cells_filter == '4g':
            return rat in ('lte', 'lte_ca')
        if self.cells_filter == '3g':
            return rat == '3g'
        if self.cells_filter == '5g':
            return rat in ('nr_nsa', 'nr_sa')
        return (obs.snap.band_label or '') == self.cells_filter

    def _log_row(self, obs: Any) -> Any:
        """One Registro row: RAT chip + identity, operator | time, band chip."""
        from kivy.uix.boxlayout import BoxLayout
        snap = obs.snap
        rat = snap.rat
        gen = ('4G' if rat in ('lte', 'lte_ca') else
               '5G' if rat in ('nr_nsa', 'nr_sa') else
               '3G' if rat == '3g' else '2G' if rat == '2g' else '?')
        row = Factory.LogRow()
        line1 = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(8))
        line1.add_widget(Factory.ChipLabel(
            text=gen, chip_color=(0.87, 0.89, 0.91, 1)))
        line1.add_widget(Label(
            text=format_log_identity(snap), font_size=sp(17), bold=True,
            color=self.c_text, halign='left', valign='middle',
            text_size=(0, 0)))
        operator = snap.operator or (
            format_plmn(snap.plmn) if snap.plmn else '-')
        line1.add_widget(Label(
            text=f"{operator} | {format_log_time(obs.last) or '-'}",
            font_size=sp(15), color=self.c_text, halign='right',
            valign='middle', text_size=(0, 0)))
        line1.add_widget(Label(
            text='›', font_size=sp(20), color=self.c_sub, halign='right',
            valign='middle', text_size=(0, 0),
            size_hint_x=None, width=dp(16)))
        row.add_widget(line1)
        line2 = BoxLayout(size_hint_y=None, height=dp(26), spacing=dp(8))
        freq, color = band_chip(snap)
        if freq:
            line2.add_widget(Factory.ChipLabel(
                text=freq, chip_color=hex_to_rgba(color, False)))
        line2.add_widget(Label(
            text=t('измерений: {n}').format(n=obs.samples),
            font_size=sp(14), color=self.c_sub, halign='left',
            valign='middle', text_size=(0, 0)))
        row.add_widget(line2)
        row.bind(on_release=lambda *_: self.open_cell_detail(obs))
        return row

    def refresh_cells_screen(self) -> None:
        scr = self.sm.get_screen('cells')
        ids = scr.ids
        if not ids:
            return
        day_lbl = ids.get('log_day_lbl')
        if day_lbl is not None:
            day_lbl.text = t("Сегодня").upper()
        log = ids.get('log_list')
        if log is None:
            return
        log.clear_widgets()
        obs = [o for o in self.survey.ranked()
               if self._obs_matches_filter(o)]
        obs.sort(key=lambda o: o.last or '', reverse=True)
        if not obs:
            log.add_widget(Label(
                text=t("Нет сот в журнале: включите сканер наблюдений."),
                font_size=sp(15), color=self.c_sub, halign='left',
                valign='top', text_size=(log.width - dp(8), None),
                size_hint_y=None, height=dp(48)))
            self._refresh_detail_list(ids, [])
            return
        today = datetime.date.today().isoformat()
        groups: dict[str, list] = {}
        for o in obs:
            groups.setdefault((o.last or '')[:10], []).append(o)
        for day in sorted(groups, reverse=True):
            header = t("Сегодня").upper() if day == today else day
            log.add_widget(Label(
                text=header, font_size=sp(18), bold=True, color=self.c_text,
                halign='left', valign='middle',
                text_size=(log.width - dp(8), None), size_hint_y=None,
                height=dp(30)))
            for o in groups[day]:
                log.add_widget(self._log_row(o))
        self._refresh_detail_list(ids, obs)

    def _cells_log_text(self) -> str:
        parts = ["\n".join(format_observation(o))
                 for o in self.survey.ranked()]
        text = "\n\n".join(parts)
        if self.survey.rows:
            text += "\n\n" + self.survey.report()
        return text

    def copy_cells_log(self) -> None:
        from kivy.core.clipboard import Clipboard
        text = self._cells_log_text()
        if not text.strip():
            self.toast(t("Нет сот в журнале: включите сканер наблюдений."))
            return
        Clipboard.copy(text)
        self.toast(t("Журнал скопирован"))

    def _refresh_detail_list(self, ids: Any, obs: list) -> None:
        detail = ids.get('detail_list')
        if detail is None:
            return
        detail.clear_widgets()
        for o in obs:
            detail.add_widget(self._detail_card(o))

    def _detail_card(self, obs: Any) -> Any:
        """One detailed per-band card: times, duration, identity, metrics."""
        from kivy.uix.label import Label
        d = detail_log(obs)
        freq = f" · {d['freq']} MHz" if d['freq'] else ''
        lines = [f"[b]{d['band']}{freq} · {d['tech']}[/b]  {d['identity']}"]
        lines.append(
            f"{t('Первый раз')}: {d['first']}  ·  "
            f"{t('Последний раз')}: {d['last']}")
        lines.append(
            f"{t('Длительность')}: {d['duration']}  ·  "
            f"{t('Измерения')}: {d['samples']}")
        earfcn = d['earfcn'] if d['earfcn'] is not None else '-'
        pci = d['pci'] if d['pci'] is not None else '-'
        lines.append(
            f"EARFCN: {earfcn}  ·  eNb:CID: {d['enb_cid']}  ·  "
            f"TAC: {d['tac']}  ·  PCI: {pci}")
        for key, unit in (('rsrp', 'dBm'), ('sinr', 'dB'), ('rsrq', 'dB'),
                          ('rssi', 'dBm')):
            minimum, median, maximum = d[key]
            if median is None:
                continue
            lines.append(
                f"{key.upper()}: {median:g} [{minimum:g} … {maximum:g}] {unit}")
        card = Factory.SectionCard()
        lbl = Label(text="\n".join(lines), markup=True, font_size=sp(14),
                    color=self.c_text, halign='left', valign='top',
                    text_size=(600, None), size_hint_y=None)
        lbl.bind(texture_size=lambda *_: setattr(
            lbl, 'height', lbl.texture_size[1] + dp(8)))
        card.bind(width=lambda *_: setattr(
            lbl, 'text_size', (card.width - dp(24), None)))
        card.add_widget(lbl)
        return card

    def export_detail_csv(self) -> None:
        from kivy.core.clipboard import Clipboard
        if not self.survey.rows:
            self.toast(t("Нет сот в журнале: включите сканер наблюдений."))
            return
        Clipboard.copy(self.survey.band_log_csv(current_language()))
        self.toast(t("Подробный CSV скопирован"))

    def _copy_value(self, value: str) -> None:
        from kivy.core.clipboard import Clipboard
        Clipboard.copy(value)
        self.toast(t("Скопировано"))

    def _detail_section(self, title: str,
                        rows: list[tuple[str, str]]) -> Any:
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        box = BoxLayout(orientation='vertical', size_hint_y=None,
                        spacing=dp(4))
        box.height = dp(30) + len(rows) * dp(52)
        box.add_widget(Label(text=title, font_size=sp(16), bold=True,
                             color=(0, 0.72, 0.58, 1), halign='left',
                             valign='middle', text_size=(0, 0),
                             size_hint_y=None, height=dp(30)))
        for label, value in rows:
            row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
            row.add_widget(Label(text=label, font_size=sp(15),
                                 color=self.c_sub, halign='left',
                                 valign='middle', text_size=(0, 0),
                                 size_hint_x=0.35))
            row.add_widget(Label(text=value, font_size=sp(20), bold=True,
                                 color=self.c_text, halign='left',
                                 valign='middle', text_size=(0, 0),
                                 size_hint_x=0.45))
            copy_btn = Factory.FlatButton(text=t("Копировать"),
                                          font_size=sp(12), size_hint_x=0.2)
            copy_btn.bind(on_release=lambda _b, v=value: self._copy_value(v))
            row.add_widget(copy_btn)
            box.add_widget(row)
        return box

    def open_cell_detail(self, obs: Any) -> None:
        """NetMonster-style cell detail popup: identity / channel / operator."""
        from kivy.graphics import Color, RoundedRectangle
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.scrollview import ScrollView
        d = detail_log(obs)
        snap = obs.snap
        box = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(8))
        with box.canvas.before:
            Color(*self.c_card)
            rect = RoundedRectangle(pos=box.pos, size=box.size,
                                    radius=[dp(16)])
        box.bind(pos=lambda *_: setattr(rect, 'pos', box.pos),
                 size=lambda *_: setattr(rect, 'size', box.size))
        popup = Popup(title=d['identity'], content=box,
                      size_hint=(0.92, None), height=dp(560), background='',
                      title_color=(1, 1, 1, 1),
                      separator_color=(0, 0.72, 0.58, 1),
                      separator_height=dp(3))
        scroll = ScrollView(bar_width=dp(8), scroll_type=['bars', 'content'])
        content = BoxLayout(orientation='vertical', size_hint_y=None,
                            spacing=dp(12), padding=dp(4))
        ci = snap.cell_id if snap.cell_id is not None else snap.nci
        is_3g = snap.rat == '3g'
        if is_3g and ci is not None:
            rnc_cid = f"{ci >> 16}:{ci & 0xffff}"
        else:
            rnc_cid = d['enb_cid']
        pci = d['pci'] if d['pci'] is not None else '-'
        content.add_widget(self._detail_section(
            t('Идентичность').upper(), [
                ('CI', str(ci) if ci is not None else '-'),
                ('RNC:CID' if is_3g else 'eNb:CID', rnc_cid),
                ('LAC' if is_3g else 'TAC', str(d['tac'])),
                ('PSC' if is_3g else 'PCI', str(pci)),
            ]))
        arfcn_label = ('UARFCN' if is_3g else 'NR-ARFCN'
                       if snap.rat in ('nr_nsa', 'nr_sa') else 'ARFCN'
                       if snap.rat == '2g' else 'EARFCN')
        content.add_widget(self._detail_section(
            t('Канал').upper(), [
                (arfcn_label, str(d['earfcn'])
                 if d['earfcn'] is not None else '-'),
                (t('Номер бэнда'), str(d['band_no']) if d['band_no'] else '-'),
                (t('Название бэнда'),
                 f"{d['freq']} MHz" if d['freq'] else '-'),
            ]))
        content.add_widget(self._detail_section(
            t('Оператор').upper(), [
                ('PLMN', str(d['plmn'])),
                (t('Имя'), str(d['operator'])),
            ]))
        signal_rows = [
            (t('Первый раз'), str(d['first'])),
            (t('Последний раз'), str(d['last'])),
            (t('Длительность'), str(d['duration'])),
            (t('Измерения'), str(d['samples'])),
        ]
        for key, unit in (('rsrp', 'dBm'), ('sinr', 'dB'), ('rsrq', 'dB')):
            minimum, median, maximum = d[key]
            if median is None:
                continue
            signal_rows.append(
                (key.upper(), f"{median:g} [{minimum:g} … {maximum:g}] {unit}"))
        content.add_widget(self._detail_section(
            t('Сигнал').upper(), signal_rows))
        content.height = content.minimum_height
        scroll.add_widget(content)
        box.add_widget(scroll)
        popup.open()

    # ---------- Gráficos (Charts tab) ----------

    def refresh_charts_screen(self) -> None:
        scr = self.sm.get_screen('charts')
        ids = scr.ids
        if not ids:
            return
        snap = self.state.last or Snapshot()
        ids['charts_operator'].text = snap.operator or (
            snap.plmn or t("Оператор неизвестен"))
        line = rat_line(snap)
        ids['charts_rat'].text = line if line != '-' else ''
        ids['charts_cell'].text = (format_log_identity(snap)
                                   if snap.registered else '-')
        chip = ids.get('charts_chip')
        if chip is not None:
            gen = line.split(' | ')[0] if line != '-' else '-'
            freq, _color = band_chip(snap)
            chip.text = f"{gen} | {freq}" if freq else gen
        units = {'rssi': 'dBm', 'rsrp': 'dBm', 'rsrq': 'dB', 'sinr': 'dB',
                 'nr_rsrp': 'dBm', 'nr_sinr': 'dB'}
        sun = self.theme_name == 'sun'
        for param, unit in units.items():
            lbl = ids.get(f'chart_{param}_lbl')
            dot = ids.get(f'chart_{param}_dot')
            value = snap.metric(param)
            if lbl is not None:
                lbl.text = f"{value:g} {unit}" if value is not None else '-'
            if dot is not None:
                # Quality dot next to the value (green / yellow / red).
                base = param[3:] if param.startswith('nr_') else param
                _st, col, _pc = evaluate_signal(base, value)
                dot.color = hex_to_rgba(col, sun)
        self._update_chart_graphs()

    def _update_chart_graphs(self) -> None:
        scr = self.sm.get_screen('charts')
        ids = scr.ids
        if not ids:
            return
        stale = self.state.is_stale(time.monotonic(), self.interval)
        for param in ('rssi', 'rsrp', 'rsrq', 'sinr', 'nr_rsrp', 'nr_sinr'):
            graph = ids.get(f'chart_{param}')
            if graph is None:
                continue
            graph.set_data(
                list(self.state.history.get(param, [])), param,
                self.state.peaks.get(param), stale,
                list(self.state.history_times.get(param, [])),
                list(self.state.history.get(comparison_param(param), [])),
                list(self.state.history_times.get(
                    comparison_param(param), [])))

    # ---------- Mapa (Map tab, no GPS) ----------

    def refresh_map_screen(self) -> None:
        scr = self.sm.get_screen('map')
        ids = scr.ids
        if not ids:
            return
        note = ids.get('map_note_lbl')
        if note is not None:
            note.text = (
                t("Роутер не отдаёт GPS-координаты, поэтому соты нельзя "
                  "показать на карте.")
                + "\n" + t("Соты без координат: список ниже — только то, "
                           "что сообщил модем."))
        cells = ids.get('map_cells_lbl')
        if cells is not None:
            obs = sorted(self.survey.ranked(),
                         key=lambda o: o.last or '', reverse=True)
            if not obs:
                cells.text = t(
                    "Нет сот в журнале: включите сканер наблюдений.")
            else:
                lines = []
                for o in obs[:50]:
                    op = o.snap.operator or (
                        format_plmn(o.snap.plmn) if o.snap.plmn else '-')
                    lines.append(
                        f"{format_log_identity(o.snap)} · {op} · "
                        f"{format_log_time(o.last) or '-'}")
                cells.text = "\n".join(lines)

    # ---------- Band Lock sheet (Recientes / Rutinas) ----------

    def _record_recent_lock(self, bands: tuple[int, ...]) -> None:
        bands = tuple(sorted(set(bands)))
        if not bands:
            return
        if bands in self._recent_locks:
            self._recent_locks.remove(bands)
        self._recent_locks.insert(0, bands)
        del self._recent_locks[5:]

    def open_band_lock_sheet(self) -> None:
        content = Factory.BandLockSheet(
            sheet_title=t("Блокировка бэндов и каналов").upper(),
            tab_recent_text=t("Недавние").upper(),
            tab_routines_text=t("Рутины").upper(),
            new_lock_text="+ " + t("Создать новый блок"),
            unlock_all_text=t("Разблокировать всё"))
        sheet = ModalView(size_hint=(1, None), height=dp(560),
                          pos_hint={'center_x': 0.5, 'y': 0},
                          auto_dismiss=True)
        sheet.add_widget(content)
        self._lock_sheet = content
        self._lock_sheet_tab = 'recent'
        self._render_lock_sheet()
        sheet.bind(on_dismiss=lambda *_: setattr(self, '_lock_sheet', None))
        sheet.open()

    def set_lock_sheet_tab(self, tab: str) -> None:
        self._lock_sheet_tab = tab
        self._render_lock_sheet()

    def _render_lock_sheet(self) -> None:
        if self._lock_sheet is None:
            return
        body = self._lock_sheet.ids.sheet_body
        body.clear_widgets()
        tab = self._lock_sheet_tab
        recent = self._lock_sheet.ids.tab_recent
        routines = self._lock_sheet.ids.tab_routines
        recent.background_color = (self.c_accent if tab == 'recent'
                                   else self.c_button2)
        recent.color = (1, 1, 1, 1) if tab == 'recent' else self.c_text
        routines.background_color = (self.c_accent if tab == 'routines'
                                     else self.c_button2)
        routines.color = (1, 1, 1, 1) if tab == 'routines' else self.c_text
        if tab == 'routines':
            body.add_widget(Label(
                text=t("Рутины пока недоступны в этой версии."),
                font_size=sp(15), color=self.c_sub, halign='left',
                valign='top', text_size=(body.width - dp(8), None),
                size_hint_y=None, height=dp(40)))
            return
        if not self._recent_locks:
            body.add_widget(Label(
                text=t("Нет недавних блокировок: примените одну с экрана "
                       "Сеть."),
                font_size=sp(15), color=self.c_sub, halign='left',
                valign='top', text_size=(body.width - dp(8), None),
                size_hint_y=None, height=dp(48)))
            return
        from kivy.uix.button import Button
        from core.constants import LTE_BAND_TABLE
        for bands in self._recent_locks:
            freqs = []
            for b in bands:
                name = LTE_BAND_TABLE.get(b, ('', '', 0.0, 0, 0))[0]
                freqs.append(name.split()[0] if name else f"B{b}")
            label = ", ".join(f"B{b}" for b in bands)
            freq_text = ", ".join(freqs)
            sub = t("Только бэнд") if len(bands) == 1 else t("Только бэнды")
            btn = Button(
                text=(f"[b]4G  {label} | {freq_text}   ›[/b]\n"
                      f"[size=13][color=999999]{sub}[/color][/size]"),
                markup=True, font_size=sp(17), halign='left',
                valign='middle', text_size=(body.width - dp(16), None),
                size_hint_y=None, height=dp(56), background_normal='',
                background_color=(0, 0, 0, 0), color=self.c_text)
            btn.bind(on_release=lambda _btn, b=bands:
                     self._apply_recent_lock(b))
            body.add_widget(btn)

    def _dismiss_lock_sheet(self) -> None:
        sheet = self._lock_sheet
        self._lock_sheet = None
        if sheet is not None and sheet.parent is not None:
            sheet.parent.dismiss()

    def _apply_recent_lock(self, bands: tuple[int, ...]) -> None:
        self._dismiss_lock_sheet()
        for b, cb in self.band_vars.items():
            cb.active = b in bands
        self.go('tools')
        self.apply_bands()

    def new_band_lock(self) -> None:
        self._dismiss_lock_sheet()
        self.go('tools')

    def unlock_all_bands(self) -> None:
        self._dismiss_lock_sheet()
        self.reset_bands()

    def set_graph_param(self, param: str) -> None:
        self.state.set_trend_param(param)
        if self.state.last is not None:
            self._render(self.state.last)
        else:
            self.refresh_graph()

    def refresh_graph(self, stale: bool = False) -> None:
        param = self.state.trend_param
        values = list(self.state.history.get(param, []))
        peak = self.state.peaks.get(param)
        graph = self.sm.get_screen('monitor').ids.get('signal_graph')
        for target in (graph, self._fs_graph):
            if target is not None:
                target.set_data(values, param, peak, stale,
                                list(self.state.history_times.get(param, [])),
                                list(self.state.history.get(comparison_param(param), [])),
                                list(self.state.history_times.get(comparison_param(param), [])))
        self._update_chart_graphs()

    def reset_peaks(self) -> None:
        self.state.reset_peaks()
        if self.state.last is not None:
            self._render(self.state.last)
        self.toast(t("Пики сброшены"))

    # ---------- звук-парктроник ----------

    def toggle_sound(self) -> None:
        if not self.beeper.available:
            self.toast(t("Звук недоступен на этом устройстве"))
            return
        self.sound_on = not self.sound_on
        if self.sound_on:
            self._schedule_beep()
        else:
            self._stop_beeps()

    def _schedule_beep(self) -> None:
        self._stop_beeps()
        delta = self.state.delta_to_peak(self.state.trend_param)
        self._beep_ev = Clock.schedule_once(self._beep_tick, beep_interval(delta))

    def _beep_tick(self, _dt: float) -> None:
        self._beep_ev = None
        if not self.sound_on or self.link == 'offline':
            return
        # Во время переподключения молчим, но цикл не прерываем — иначе звук
        # не вернулся бы после перезагрузки роутера или обрыва Wi-Fi.
        if (self.link == 'online' and self.state.last is not None
                and self.state.last.registered
                and not self.state.is_stale(time.monotonic(), self.interval)):
            self.beeper.beep(50)
        self._schedule_beep()

    def _stop_beeps(self) -> None:
        if self._beep_ev is not None:
            self._beep_ev.cancel()
            self._beep_ev = None

    # ---------- меню и диалоги ----------

    def open_survey(self) -> None:
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.button import Button
        from kivy.uix.textinput import TextInput
        box = BoxLayout(orientation='vertical', spacing=dp(6), padding=dp(6))
        for items in (((t('Старт'), self._start_survey), (t('Стоп'), self._stop_survey)),
                      ((t('Поиск операторов'), self._search_survey),
                       (t('Копировать результат'), self._copy_survey))):
            bar = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
            for title, action in items:
                button = Button(text=title, font_size=sp(14))
                button.bind(on_release=lambda _b, fn=action: fn())
                bar.add_widget(button)
            box.add_widget(bar)
        self._survey_text = TextInput(readonly=True, font_size=sp(14), multiline=True)
        box.add_widget(self._survey_text)
        popup = Popup(title=t('Сканер наблюдений · Beta'), content=box, size_hint=(0.97, 0.95))
        close = Button(text=t('← Назад'), size_hint_y=None, height=dp(46))
        close.bind(on_release=lambda _b: popup.dismiss())
        box.add_widget(close)
        popup.bind(on_dismiss=lambda _p: setattr(self, '_survey_text', None))
        self._refresh_survey()
        popup.open()

    def _refresh_survey(self) -> None:
        widget = getattr(self, '_survey_text', None)
        if widget is not None:
            scroll = widget.scroll_y
            widget.text = self.survey.report()
            widget.scroll_y = scroll

    def _start_survey(self) -> None:
        if self.session is None or self.link != 'online' or self._busy:
            self.toast(t('Сначала подключитесь к роутеру.'))
            return
        def start() -> None:
            self.survey.start()
            session = self.session
            if session is not None:
                session.survey_enabled = True
            self._refresh_survey()
        if self.survey.rows:
            self.confirm(t('Сканер наблюдений · Beta'),
                         t('Начать новый сбор? Предыдущий результат будет очищен.'), t('Старт'), start)
        else:
            start()

    def _stop_survey(self) -> None:
        if self.session is not None:
            self.session.survey_enabled = False
        self.survey.stop()
        self.survey.messages = [m for m in self.survey.messages if m != t('Поиск операторов…')]
        self._refresh_survey()

    def _search_survey(self) -> None:
        session = self.session
        if session is None or self._busy:
            return
        if not self.survey.running:
            self.toast(t('Сначала нажмите Старт.'))
            return
        survey = self.survey
        generation = survey.generation
        def done(result: Any) -> None:
            self._survey_searching = False
            if survey is self.survey and survey.running and survey.generation == generation:
                survey.accept_discovery(*result)
                self._refresh_survey()
        def search() -> None:
            if session is not self.session or self._busy or self.link != 'online':
                return
            self._survey_searching = True
            pending = Snapshot()
            self.state.ingest(pending, time.monotonic(), preserve_cell=True)
            self._render(pending)
            survey.messages = [t('Поиск операторов…')]
            self._refresh_survey()
            self._net_action(session.discover_networks, done, t('Поиск операторов…'))
        self.confirm(t('Поиск операторов'), t(SURVEY_HELP), t('Продолжить'), search)

    def _copy_survey(self) -> None:
        from kivy.core.clipboard import Clipboard
        Clipboard.copy(self.survey.report())
        self.toast(t('Результат скопирован'))

    # ---------- Ajustes (Settings screen) ----------

    def apply_language(self, name: str) -> None:
        code = {v: k for k, v in LANGUAGES.items()}.get(name)
        if code and code != current_language():
            set_language(code)
            self.refresh_all_texts()
            self.refresh_settings_screen()

    def cycle_theme(self) -> None:
        self.apply_theme('dark' if self.theme_name == 'sun' else 'sun')
        self.refresh_settings_screen()

    def open_language_picker(self) -> None:
        from kivy.graphics import Color, RoundedRectangle
        from kivy.uix.boxlayout import BoxLayout
        box = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(8))
        with box.canvas.before:
            Color(*self.c_card)
            rect = RoundedRectangle(pos=box.pos, size=box.size,
                                    radius=[dp(16)])
        box.bind(pos=lambda *_: setattr(rect, 'pos', box.pos),
                 size=lambda *_: setattr(rect, 'size', box.size))
        popup = Popup(title=t("Язык"), content=box, size_hint=(0.85, None),
                      height=dp(260), background='',
                      title_color=(1, 1, 1, 1),
                      separator_color=(0, 0.72, 0.58, 1),
                      separator_height=dp(3))
        for name in LANGUAGES.values():
            btn = Factory.FlatButton(text=name, font_size=sp(17),
                                     size_hint_y=None, height=dp(56))
            btn.bind(on_release=lambda _b, n=name: (
                popup.dismiss(), self.apply_language(n)))
            box.add_widget(btn)
        popup.open()

    def toggle_notifications_sound(self) -> None:
        """Notifications row: the app's alert channel is sound.

        A persistent Android notification needs a foreground service,
        which this app does not have; the row toggles sound alerts.
        """
        if not self.beeper.available:
            self.toggle_sound()  # toasts that sound is unavailable
            return
        self.toggle_sound()
        self.toast(t("Звук включён") if self.sound_on
                   else t("Звук выключен"))
        self.refresh_settings_screen()

    def _settings_icon_tile(self, icon: str | None) -> Any:
        from kivy.graphics import Color, RoundedRectangle
        from kivy.uix.anchorlayout import AnchorLayout
        from kivy.uix.label import Label
        tile = AnchorLayout(size_hint=(None, None), size=(dp(56), dp(56)),
                            anchor_x='center', anchor_y='center')
        with tile.canvas.before:
            Color(0.07, 0.15, 0.10, 1)
            rect = RoundedRectangle(pos=tile.pos, size=tile.size,
                                    radius=[dp(14)])
        tile.bind(pos=lambda *_: setattr(rect, 'pos', tile.pos),
                  size=lambda *_: setattr(rect, 'size', tile.size))
        if icon is None:
            tile.add_widget(Factory.BellIcon(size_hint=(None, None),
                                             size=(dp(34), dp(34))))
        else:
            tile.add_widget(Label(text=icon, font_size=sp(26),
                                  color=(0, 0.72, 0.58, 1), halign='center',
                                  valign='middle', text_size=(0, 0),
                                  size_hint=(None, None), size=(dp(34), dp(34))))
        return tile

    def _trailing_state(self, text: str, icon: str) -> Any:
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        box = BoxLayout(spacing=dp(8), size_hint_x=None, width=dp(110))
        if text:
            box.add_widget(Label(text=text, font_size=sp(16),
                                 color=self.c_sub, halign='right',
                                 valign='middle', text_size=(0, 0)))
        else:
            box.add_widget(Label(text='', size_hint_x=1))
        box.add_widget(Label(text=icon, font_size=sp(24), color=self.c_sub,
                             halign='center', valign='middle', text_size=(0, 0),
                             size_hint_x=None, width=dp(24)))
        return box

    def _settings_row(self, icon: str | None, title: str, subtitle: str,
                      trailing: Any | None,
                      on_press: Any | None) -> Any:
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        row = Factory.SettingsRow()
        row.add_widget(self._settings_icon_tile(icon))
        texts = BoxLayout(orientation='vertical', spacing=dp(2))
        texts.add_widget(Label(text=title, font_size=sp(19), bold=True,
                               color=self.c_text, halign='left',
                               valign='middle', text_size=(0, 0),
                               size_hint_y=None, height=dp(28)))
        sub = Label(text=subtitle, font_size=sp(14), color=self.c_sub,
                    halign='left', valign='top', size_hint_y=None,
                    height=dp(44))
        sub.bind(width=lambda *_: setattr(sub, 'text_size', (sub.width, None)))
        texts.add_widget(sub)
        row.add_widget(texts)
        if trailing is not None:
            row.add_widget(trailing)
        if on_press is not None:
            row.bind(on_release=lambda *_: on_press())
        return row

    def refresh_settings_screen(self) -> None:
        from kivy.uix.switch import Switch
        if getattr(self, 'sm', None) is None:
            return
        scr = self.sm.get_screen('settings')
        ids = scr.ids
        if not ids:
            return
        rows_box = ids.get('settings_rows')
        if rows_box is None:
            return
        rows_box.clear_widgets()
        sw = Switch(active=self.background_monitoring,
                    size_hint=(None, None), size=(dp(64), dp(36)))
        sw.bind(active=lambda _i, v: setattr(
            self, 'background_monitoring', v))
        rows_box.add_widget(self._settings_row(
            '◎', t('Мониторизация в фоновом режиме'),
            t('Продолжать мониторинг, когда приложение свёрнуто'),
            sw, None))
        rows_box.add_widget(self._settings_row(
            '⚙', t('Общие'), t('Данные сот, журнал и вид карты'),
            self._trailing_state('', '›'), lambda: self.go('info')))
        rows_box.add_widget(self._settings_row(
            None, t('Уведомления'),
            t('Постоянное уведомление и неизвестные соты'),
            None, self.toggle_notifications_sound))
        theme_name = (t('Солнце') if self.theme_name == 'sun'
                      else t('Тёмная'))
        rows_box.add_widget(self._settings_row(
            '◐', t('Тема'), theme_name,
            self._trailing_state('', '›'), self.cycle_theme))
        lang_name = LANGUAGES.get(current_language(), 'Español')
        rows_box.add_widget(self._settings_row(
            '⊕', t('Язык'), lang_name,
            self._trailing_state('', '↗'), self.open_language_picker))

    def open_menu(self) -> None:
        """Original menu, all options kept — NetMonster styling only:
        dark green-black card, white title, green separator, flat buttons."""
        from kivy.graphics import Color, RoundedRectangle
        from kivy.uix.boxlayout import BoxLayout
        box = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(8))
        with box.canvas.before:
            Color(*self.c_card)
            rect = RoundedRectangle(pos=box.pos, size=box.size,
                                    radius=[dp(16)])
        box.bind(pos=lambda *_: setattr(rect, 'pos', box.pos),
                 size=lambda *_: setattr(rect, 'size', box.size))
        popup = Popup(title=t("Меню"), content=box, size_hint=(0.85, None),
                      height=dp(575), background='',
                      title_color=(1, 1, 1, 1),
                      separator_color=(0, 0.72, 0.58, 1),
                      separator_height=dp(3))
        sun = self.theme_name == 'sun'
        items = [
            (t("ℹ Информация"), lambda: self.go('info')),
            (t("Графики"), lambda: self.go('charts')),
            (t("Карта"), lambda: self.go('map')),
            (t("Соты"), lambda: self.go('cells')),
            (t('Сканер наблюдений · Beta'), self.open_survey),
            (t("⚙ Сеть"), lambda: self.go('tools')),
            (t("☀ Солнце: выкл") if sun else t("☀ Солнце: вкл"),
             lambda: self.apply_theme('dark' if sun else 'sun')),
            (t("Настройки"), lambda: self.go('settings')),
            (t("⏏ Отключиться"), self.confirm_disconnect),
        ]
        for text, action in items:
            btn = Factory.FlatButton(text=text, font_size=sp(17),
                                     size_hint_y=None, height=dp(48))
            btn.bind(on_release=lambda _b, a=action: (popup.dismiss(), a()))
            box.add_widget(btn)
        popup.open()

    def confirm(self, title: str, message: str, yes_text: str,
                on_yes: Callable[[], None]) -> None:
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.button import Button
        from kivy.uix.label import Label
        content = BoxLayout(orientation='vertical', spacing=dp(10), padding=dp(10))
        msg = Label(text=message, halign='center', valign='middle', font_size=sp(15))
        msg.bind(size=lambda i, v: setattr(i, 'text_size', v))
        content.add_widget(msg)
        btns = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(10))
        popup = Popup(title=title, content=content, size_hint=(0.92, 0.55))
        no = Button(text=t("← Назад"), font_size=sp(16))
        yes = Button(text=yes_text, font_size=sp(16), background_color=(0.8, 0.4, 0.15, 1))
        no.bind(on_release=lambda *a: popup.dismiss())
        yes.bind(on_release=lambda *a: (popup.dismiss(), on_yes()))
        btns.add_widget(no)
        btns.add_widget(yes)
        content.add_widget(btns)
        popup.open()

    def confirm_disconnect(self) -> None:
        self.confirm(t("Подтверждение"), t("Отключиться от роутера?"),
                     t("Отключиться"), self.disconnect)

    def show_popup(self, title: str, message: str) -> None:
        from kivy.uix.label import Label
        from kivy.uix.scrollview import ScrollView
        lbl = Label(text=message, halign='left', valign='top', size_hint_y=None,
                    font_size=sp(14))
        lbl.bind(width=lambda i, w: setattr(i, 'text_size', (w, None)),
                 texture_size=lambda i, ts: setattr(i, 'height', ts[1]))
        sv = ScrollView()
        sv.add_widget(lbl)
        Popup(title=title, content=sv, size_hint=(0.92, 0.8)).open()

    def toast(self, text: str, seconds: float = 2.0) -> None:
        from kivy.core.window import Window
        from kivy.graphics import Color, RoundedRectangle
        from kivy.uix.label import Label
        lbl = Label(text=text, font_size=sp(15), size_hint=(None, None), color=(1, 1, 1, 1))
        lbl.texture_update()
        lbl.size = (lbl.texture_size[0] + dp(24), lbl.texture_size[1] + dp(16))
        lbl.pos = ((Window.width - lbl.width) / 2, dp(80))
        with lbl.canvas.before:
            Color(0, 0, 0, 0.8)
            RoundedRectangle(pos=lbl.pos, size=lbl.size, radius=[dp(8)])
        Window.add_widget(lbl)
        Clock.schedule_once(lambda dt: Window.remove_widget(lbl), seconds)

    def open_fullscreen_graph(self) -> None:
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.button import Button
        inner = BoxLayout(orientation='vertical', spacing=dp(6), padding=dp(8))
        graph = PinchGraph()
        close = Button(text=t("← Назад"), size_hint_y=None, height=dp(48))
        inner.add_widget(graph)
        controls = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(4))
        auto = Button(text=t("Авто"), font_size=sp(14))
        auto.bind(on_release=lambda *a: graph.auto())
        controls.add_widget(auto)
        controls.add_widget(close)
        inner.add_widget(controls)
        self._fs_graph = graph
        popup = Popup(title='', separator_height=0, content=RotatedBox(inner),
                      size_hint=(0.98, 0.96))
        def dismissed(*_args: Any) -> None:
            graph.release_touches()
            self._fs_graph = None
        popup.bind(on_dismiss=dismissed)
        close.bind(on_release=lambda *a: popup.dismiss())
        popup.open()
        self.refresh_graph()

    # ---------- экран «Информация» ----------

    def refresh_info_screen(self) -> None:
        ids = self.sm.get_screen('info').ids
        if not ids:
            return
        snap = (self.state.last or Snapshot()).display()
        nd = t("Нет данных")
        mhz = t('МГц')

        def row(name: str, value: Any) -> str:
            # Строки от роутера — без разметки Kivy: «[» и «]» в них не теги.
            text = escape_markup(str(value)) if value not in (None, '', '-') else nd
            return f"[b]{t(name)}:[/b] {text}"

        ca = {True: t("Активна"), False: t("Нет"), None: None}[snap.ca]
        nr = snap.nr_summary() if snap.has_nr else None
        dl, ul = snap.dl_bandwidth, snap.ul_bandwidth
        tower = [
            row('Оператор (PLMN)', f"{snap.plmn} ({snap.operator or t('Неизвестный оператор')})"
                if snap.plmn else None),
            row('Технология', t(RAT_LABELS.get(snap.rat, snap.rat)) if snap.rat else None),
            row('Рабочий Band (LTE)', snap.band_label.replace('МГц', mhz)),
            row('Частота DL', f"{snap.freq_mhz:g} {mhz}" if snap.freq_mhz else None),
            row('EARFCN (канал DL)', snap.earfcn_raw),
            row('Агрегация (CA)', ca),
            row('Ширина канала', f"DL {dl} / UL {ul}" if ul else dl),
            row('Сектор антенны (PCI)', fmt_num(snap.pci)),
            row('Cell ID (ECI)', snap.cell_id),
            row('eNodeB (Вышка)', fmt_num(snap.enodeb) if snap.enodeb is not None else
                (f"NCI {snap.nci}" if snap.nci else None)),
            row('Cell (Локальный сектор)', fmt_num(snap.sector)),
            row('TAC (зона)', snap.tac),
            row('5G NR', nr),
        ]
        cells = [
            escape_markup(f"{'▶ ' if self.state.is_current_cell(c) else ''}{c.operator_label}"
                          f" · {c.band_label.replace('МГц', mhz)}"
                          f" · Cell ID {c.cell_id if c.cell_id is not None else '-'}"
                          f" · PCI {fmt_num(c.key.pci)} · SINR {fmt_num(c.best_sinr)}"
                          f" · RSRP {fmt_num(c.best_rsrp)}")
            for c in self.state.top_cells()]
        info = self.session.device_info if self.session is not None else {}
        sim = [row(name, info.get(key)) for key, name in (
            ('Imei', 'IMEI (роутер)'), ('Imsi', 'IMSI (SIM)'), ('Iccid', 'ICCID (SIM-карта)'),
            ('Msisdn', 'Номер телефона'), ('SerialNumber', 'Серийный номер'),
            ('DeviceName', 'Модель'), ('SoftwareVersion', 'Прошивка'))]
        mimo = mimo_status(snap.cqi0, snap.cqi1)
        up = uplink_status(snap.pusch_dbm)
        mods = [f"{d} {m}" for d, m in (("DL", format_modulation(snap.dl_mcs)),
                                        ("UL", format_modulation(snap.ul_mcs, uplink=True))) if m]
        cqi = None
        if snap.cqi0 is not None:
            cqi = f"{snap.cqi0}" + (f" / {snap.cqi1}" if snap.cqi1 is not None else "") + \
                (f" — {t(MIMO_LABELS[mimo])}" if mimo else "")
        tx = (snap.txpower + (f" — {t(UPLINK_LABELS[up])}" if up else "")) or None
        st = self.state

        def minmax(p: str) -> str | None:
            lo, hi = st.session_min.get(p), st.session_max.get(p)
            return None if lo is None else f"{fmt_num(lo)} / {fmt_num(hi)} {unit_of(p)}"

        month = None
        if snap.month_dl is not None or snap.month_ul is not None:
            month = f"{format_bytes_mb(snap.month_dl or 0)} / {format_bytes_mb(snap.month_ul or 0)}"
        status = [
            row('Время сессии', str(datetime.timedelta(seconds=snap.connect_time))
                if snap.connect_time else None),
            row('Температура чипа', snap.temperature),
            row('Мобильные данные', {True: t("включены"), False: t("ВЫКЛЮЧЕНЫ"),
                                     None: None}[snap.data_enabled]),
            row('Скорость (Download)', format_rate_mbps(snap.dl_rate)),
            row('Скорость (Upload)', format_rate_mbps(snap.ul_rate)),
            row('Скачано за сессию', format_bytes_mb(snap.total_dl)),
            row('Отдано за сессию', format_bytes_mb(snap.total_ul)),
            row('Трафик за месяц (↓/↑)', month),
            row('Модуляция DL / UL', " / ".join(mods) if mods else None),
            row('Режим передачи (TM)' , format_mimo(snap.transmode) if snap.transmode else None),
            row('MIMO', snap.mimo_matrix or None),
            row('Ранг MIMO LTE', t('Нет подтверждённых данных')),
            row('Ранг MIMO NR', format_rank(snap.nr_rank)),
            row('CQI кодовых слов', cqi),
            row('Мощность передатчика', tx),
            row('RRC', snap.rrc),
            row('RSRP мин / макс', minmax('rsrp')),
            row('SINR мин / макс', minmax('sinr')),
        ]
        for key, lines in (('tower_block', tower), ('cells_block', cells or [nd]),
                           ('sim_block', sim), ('status_block', status)):
            ids[key].text = "\n".join(lines)

    # ---------- экран «Сеть» ----------

    def _tools(self) -> ToolsScreen:
        return self.sm.get_screen('tools')

    def _net_msg(self, text: str, color: str) -> None:
        tools = self._tools()
        tools.net_msg = text
        tools.net_msg_color = hex_to_rgba(color, self.theme_name == 'sun')

    def build_band_checkboxes(self) -> None:
        grid = self._tools().ids.get('bands_grid')
        if grid is None or self._bands_shown == self._band_list:
            return
        from kivy.uix.checkbox import CheckBox
        from kivy.uix.label import Label
        checked = {b for b, cb in self.band_vars.items() if cb.active}
        grid.clear_widgets()
        self.band_vars = {}
        row_h = dp(44)
        for band in self._band_list:
            cb = CheckBox(size_hint=(None, None), width=dp(40), height=row_h,
                          active=band in checked)
            lbl = Label(text=lte_band_label(band, t("МГц")), color=self.c_text,
                        halign='left', valign='middle', size_hint_y=None, height=row_h)
            lbl.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
            grid.add_widget(cb)
            grid.add_widget(lbl)
            self.band_vars[band] = cb
        self._bands_shown = list(self._band_list)

    def _run_bg(self, work: Callable[[], Any], done: Callable[[Any], None],
                fail: Callable[[BaseException], None]) -> None:
        """Выполнить work в фоне, результат/ошибку — в главном потоке."""
        def task() -> None:
            try:
                result = work()
            except Exception as exc:
                logger.exception("Background task failed")
                Clock.schedule_once(lambda dt, err=exc: fail(err))
            else:
                Clock.schedule_once(lambda dt: done(result))
        threading.Thread(target=task, daemon=True).start()

    def _net_action(self, work: Callable[[], Any], done: Callable[[Any], None],
                    busy_text: str) -> None:
        """Команда роутеру: повторное нажатие до ответа игнорируется."""
        if self.session is None or self.link != 'online':
            self._net_msg(t("Сначала подключитесь к роутеру."), '#d63031')
            return
        if self._busy:
            return
        self._busy = True
        self._net_msg(busy_text, '#3399ff')
        session = self.session

        def finish(result: Any) -> None:
            if session is not self.session:
                return          # ответ прошлой сессии: её состояние уже сброшено
            self._busy = False
            done(result)

        def failed(exc: BaseException) -> None:
            if session is not self.session:
                return
            self._survey_searching = False
            self._busy = False
            self._net_msg(t("Команда не выполнена: {err}").format(
                err=humanize_error(exc)), '#d63031')
        self._run_bg(work, finish, failed)

    def load_router_config(self) -> None:
        """Читает текущий Band Lock и антенну (только чтение)."""
        session = self.session
        if session is None:
            return
        self._tools().antenna_text = t("Не прочитано")
        for cb in self.band_vars.values():
            cb.active = False
        unread = t("Сейчас на модеме: не прочитано")
        # Пока не прочитано — не показываем состояние прошлой сессии.
        self._tools().lock_state = unread

        def done(cfg: Any) -> None:
            if session is not self.session:
                return
            tools = self._tools()
            if cfg.locked is None:
                tools.lock_state = t("Сейчас на модеме: не прочитано")
            elif not cfg.locked:
                tools.lock_state = t("Сейчас на модеме: AUTO (все бэнды)")
                for cb in self.band_vars.values():
                    cb.active = False
            else:
                tools.lock_state = t("Сейчас на модеме: {bands}").format(
                    bands=", ".join(f"B{b}" for b in cfg.locked))
                extra = [b for b in cfg.locked if b not in self._band_list]
                if extra:
                    self._band_list += extra
                    self.build_band_checkboxes()
                for b, cb in self.band_vars.items():
                    cb.active = b in cfg.locked
            if cfg.antenna is not None:
                for label, code in ANTENNA_MODES.items():
                    if code == cfg.antenna:
                        tools.antenna_text = t(label)

        def failed(_exc: BaseException) -> None:
            if session is self.session:
                self._tools().lock_state = unread
        self._run_bg(session.read_config, done, failed)

    def mark_current_bands(self) -> None:
        snap = self.state.last
        if (self.link != 'online' or snap is None or not snap.registered
                or self.state.is_stale(time.monotonic(), self.interval)):
            self._net_msg(t("Текущий бэнд ещё не определён."), '#d63031')
            return
        bands = [b for b in snap.bands if 1 <= b <= 63 and b in self.band_vars]
        if not bands:
            self._net_msg(t("Текущий бэнд ещё не определён."), '#d63031')
            return
        for b, cb in self.band_vars.items():
            cb.active = b in bands
        self._net_msg(t("Отмечены текущие бэнды: {bands}").format(
            bands=", ".join(f"B{b}" for b in bands)), '#3399ff')

    def apply_bands(self) -> None:
        session = self.session
        selected = [b for b, cb in self.band_vars.items() if cb.active]
        if session is None or self.link != 'online':
            self._net_msg(t("Сначала подключитесь к роутеру."), '#d63031')
            return
        if not selected:
            self._net_msg(t("Выберите хотя бы один диапазон!"), '#d63031')
            return
        names = ", ".join(f"B{b}" for b in selected)
        lines = [t("Зафиксировать бэнды: {bands}?").format(bands=names)]
        lines += lock_warnings(selected, self.state.last)
        def confirm_plan(plan):
            lines.append(t("Режим сети после записи: {mode}").format(mode=plan.networkmode))

            def apply():
                if self.session is session:
                    self._record_recent_lock(tuple(selected))
                    self._net_action(lambda: session.apply_plan(plan),
                                     lambda ok: self._after_write(ok, t("Band Lock применён: {bands}.").format(bands=names)),
                                     t("Применяю Band Lock…"))

            self.confirm(t("Подтверждение"), "\n\n".join(lines), t("Применить"), apply)

        self._net_action(lambda: session.plan_band_lock(selected), confirm_plan, t("Чтение настроек сети…"))

    def reset_bands(self) -> None:
        session = self.session
        if session is None:
            self._net_msg(t("Сначала подключитесь к роутеру."), '#d63031')
            return
        self._net_action(lambda: session.apply_plan(session.plan_all_bands()),
                         lambda ok: self._after_write(ok, t("Включены все бэнды (AUTO).")),
                         t("Включаю все бэнды…"))

    def restore_bands(self) -> None:
        session = self.session
        if session is None:
            self._net_msg(t("Сначала подключитесь к роутеру."), '#d63031')
            return
        plan = session.plan_restore_original()
        if plan is None:
            self._net_msg(t("Исходные настройки не прочитаны — роутер не отдал net-mode."),
                          '#d63031')
            return
        self._net_action(lambda: session.apply_plan(plan),
                         lambda ok: self._after_write(ok, t(
                             "Восстановлены настройки, прочитанные при подключении.")),
                         t("Восстанавливаю настройки…"))

    def _after_write(self, verified: bool, success_text: str) -> None:
        if verified:
            self._net_msg(success_text + " " + t(
                "Модем перерегистрируется в сети (до ~30 с)."), '#00b894')
        else:
            self._net_msg(t("Команда отправлена, но роутер не подтвердил запись — "
                            "проверьте строку «Сейчас на модеме»."), '#e68033')
        self.load_router_config()

    def apply_antenna(self, label: str) -> None:
        session = self.session
        rev = {t(k): k for k in ANTENNA_MODES}
        code = parse_antenna_value(rev.get(label, label))
        if session is None:
            self._net_msg(t("Сначала подключитесь к роутеру."), '#d63031')
            return
        if code is None:
            self._net_msg(t("Неизвестный режим антенны."), '#d63031')
            return

        def work() -> int | None:
            return session.apply_antenna(code)

        def done(read_back: int | None) -> None:
            if read_back == code:
                self._net_msg(t("Тип антенны изменён: {mode}").format(mode=label), '#00b894')
            elif read_back is None:
                self._net_msg(t("Команда отправлена, но режим антенны не подтверждён."), '#e68033')
            else:
                self._net_msg(t("Роутер принял команду, но сообщает другой режим антенны."),
                              '#e68033')
        self._net_action(work, done, t("Переключаю антенну…"))

    def confirm_reattach(self) -> None:
        session = self.session
        if session is None:
            self._net_msg(t("Сначала подключитесь к роутеру."), '#d63031')
            return

        def done(ok: bool) -> None:
            if ok:
                self._net_msg(t("Связь переподключена."), '#00b894')
            else:
                self._net_msg(t("Не удалось включить мобильные данные — включите их в "
                                "веб-интерфейсе роутера."), '#d63031')
        self.confirm(t("Подтверждение"), t(
            "Переподключить мобильную связь?\n\nМобильные данные будут выключены и включены. Интернет временно пропадёт (обычно на 5–10 секунд). Смена соты и улучшение сигнала не гарантируются."), t("Переподключить"),
            lambda: self._net_action(session.reattach, done, t("Переподключаю связь…")))

    def confirm_reboot(self) -> None:
        session, worker = self.session, self.worker
        if session is None or worker is None:
            self._net_msg(t("Сначала подключитесь к роутеру."), '#d63031')
            return

        def done(_: Any) -> None:
            self._net_msg(t("Роутер перезагружается — переподключусь автоматически."),
                          '#3399ff')
        self.confirm(t("Подтверждение"), t(
            "Перезагрузить роутер?\n\nСоединение с интернетом прервётся "
            "на 1–2 минуты. Программа переподключится автоматически."),
            t("Перезагрузить роутер"),
            lambda: self._net_action(session.reboot, done, t("Отправляю команду перезагрузки…")))

    def copy_diagnostics(self) -> None:
        """Диагностика (JSON) в буфер обмена: удобно вставить в issue/мессенджер.

        Hardware validation required: вставка из буфера на Android 12+.
        """
        session = self.session
        if session is None:
            self._net_msg(t("Сначала подключитесь к роутеру."), '#d63031')
            return

        def work() -> str:
            dumps, errors = session.collect_diagnostics()
            report = build_diagnostics(
                app_version=__version__, library_version=library_version(),
                platform=f"{platform} / Python {py_platform.python_version()}",
                dumps=dumps, errors=errors)
            return diagnostics_json(report)

        def done(text: str) -> None:
            from kivy.core.clipboard import Clipboard
            Clipboard.copy(text)
            self._net_msg(t("Диагностика скопирована в буфер обмена. Личные номера "
                            "замаскированы."), '#00b894')
        self._net_action(work, done, t("Собираю диагностику…"))

    def whitelist_check(self) -> None:
        if self._wl_running:
            return                      # проверка уже идёт
        self._wl_running = True
        token = self._wl_token = object()
        session = self.session
        tools = self._tools()
        tools.wl_verdict = t("Проверка…")
        tools.wl_color = hex_to_rgba('#e68033', self.theme_name == 'sun')
        tools.wl_detail = t("Проверка занимает несколько секунд.")

        def done(report: Any) -> None:
            if session is not self.session or token is not self._wl_token:
                return
            self._wl_running = False
            tools.wl_verdict = report.title
            tools.wl_color = hex_to_rgba(report.color, self.theme_name == 'sun')
            lines = [report.detail, ""]
            for title, results in ((t("В белых списках:"), report.white),
                                   (t("Нейтральные:"), report.neutral)):
                lines.append(title)
                lines += [f"{'✔' if r.ok else '✘'} {r.host} — {r.detail}" for r in results]
            tools.wl_detail = "\n".join(lines)

        def failed(exc: BaseException) -> None:
            if session is not self.session or token is not self._wl_token:
                return
            self._wl_running = False
            tools.wl_verdict = t("Ошибка")
            tools.wl_detail = humanize_error(exc)
        def work():
            if platform != 'android':
                return run_whitelist_check()
            if session is None:
                raise OSError('No router session for network selection')
            from core.local_transport import android_probe_connection
            return run_whitelist_check(create_connection=android_probe_connection(session.ip))
        self._run_bg(work, done, failed)


def main() -> None:
    Hua4GMonApp().run()


if __name__ == "__main__":
    main()
