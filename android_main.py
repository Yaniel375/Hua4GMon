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
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.properties import (
    BooleanProperty,
    ListProperty,
    NumericProperty,
    StringProperty,
)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.checkbox import CheckBox
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
    LTE_BAND_TABLE,
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
    demo_factory,
    diagnostics_json,
    discover_router,
    evaluate_signal,
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

def _rgba(color: str, alpha: float = 1.0) -> list[float]:
    """'#RRGGBB' → [r/255, g/255, b/255, alpha] con el hex EXACTO.

    Kivy trunca int(v*255) al renderizar: el verde #0CA663 escrito como
    [0.05, 0.65, 0.39] se veía #0CA563. Con int/255 el hex renderizado
    es exactamente el de diseño.
    """
    h = color.lstrip('#')
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)] + [alpha]


# Paleta NetMonster Pro (prompt §3): UN SOLO SITIO. Toda la interfaz
# — pantallas, botones, spinners, popups, gráfico — toma sus colores
# de aquí (vía THEMES / app.c_* / STATUS_HEX); no hay hex ni flotantes
# sueltos fuera de este bloque, de SKIN_SIGNAL_COLORS ni de los
# degradados que derivan de STATUS_HEX.
PALETTE_HEX: dict[str, dict[str, str]] = {
    # Piel NetMonster: fondo casi negro, tarjetas apenas más claras
    # y un solo verde de marca #0CA663.
    'dark': {
        'c_bg': '#111411', 'c_card': '#1E1E1E', 'c_text': '#FFFFFF',
        'c_sub': '#99A0A5', 'c_accent': '#0CA663', 'c_button2': '#1E1E1E',
        'c_graph_bg': '#161616', 'c_grid': '#282D28',
        'c_btn_border': '#3A3A3A', 'c_on_accent': '#0A1E16',
        'c_sep': '#282D28', 'c_border': '#3A3A3A', 'c_nodata': '#808080',
        'c_btn_down': '#333333', 'c_accent_down': '#0A7F4C',
        'c_graph_line': '#0CA663', 'c_graph_nr': '#FFA633',
        'c_peak': '#FFFFFF',
    },
    # «Солнце»: máximo contraste para la pantalla bajo el sol directo.
    'sun': {
        'c_bg': '#FFFFFF', 'c_card': '#EBEDEF', 'c_text': '#000000',
        'c_sub': '#333333', 'c_accent': '#004CB2', 'c_button2': '#CCD1D8',
        'c_graph_bg': '#FFFFFF', 'c_grid': '#CCCCCC',
        'c_btn_border': '#000000', 'c_on_accent': '#FFFFFF',
        'c_sep': '#CCCCCC', 'c_border': '#000000', 'c_nodata': '#808080',
        'c_btn_down': '#B3B8BF', 'c_accent_down': '#003D8F',
        'c_graph_line': '#0066A6', 'c_graph_nr': '#A64D00',
        'c_peak': '#333333',
    },
}

THEMES: dict[str, dict[str, list[float]]] = {
    name: {key: _rgba(value) for key, value in theme.items()}
    for name, theme in PALETTE_HEX.items()
}
# En sol los bordes son transparentes (como antes): el hex no lleva alfa.
THEMES['sun']['c_btn_border'] = _rgba('#000000', 0.0)
THEMES['sun']['c_border'] = _rgba('#000000', 0.0)


# Colores de estado (misma paleta: un verde, un ámbar, un rojo, un azul
# y un gris — sin valores sueltos). Se pasan por skin_hex/hex_to_rgba,
# que en tema sol los oscurecen para un contraste ≥ 4,5:1.
STATUS_HEX: dict[str, str] = {
    'good': '#0CA663', 'warn': '#EAB308', 'error': '#EF4444',
    'info': '#3399FF', 'nodata': '#808080',
}


def _hex_rgb(color: str) -> tuple[int, int, int]:
    """'#RRGGBB' → (r, g, b) en 0-255 (para la textura del degradado)."""
    h = color.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# Escala tipográfica única (sp): un solo sitio, roles con nombre.
# Los valores sueltos por pantalla se normalizaron a estos roles
# (10→10,5; 11→11,5; 12,5→13; 14/14,5→15; 15,5→16; 19→18).
FONT: dict[str, float] = {
    'display': 38, 'operator': 30, 'title': 22, 'hero': 34,
    'big': 18, 'menu': 17, 'value': 16, 'body': 15, 'hint': 13,
    'label': 12, 'small': 11.5, 'tiny': 10.5,
}


# Radios del sistema (dp): botones 10, tarjetas 12, chips 6, píldora 16.
RADIUS: dict[str, int] = {'card': 12, 'button': 10, 'chip': 6, 'pill': 16}


def unit_of(param: str) -> str:
    return "dBm" if param.endswith(('rsrp', 'rssi')) else "dB"


def fmt_num(value: float | None) -> str:
    """Число для подписи: целые — как есть (eNB 1048575, а не 1.04858e+06)."""
    if value is None or not math.isfinite(value):
        return "-"
    return str(value) if isinstance(value, int) else f"{value:g}"


# Piel NetMonster: los colores de calidad de señal del núcleo
# (verde/ámbar/rojo de SIGNAL_THRESHOLDS y de la salud general) se
# traducen a la paleta de la piel. La lógica y los umbrales no cambian;
# solo el color que se muestra. Lo no listado pasa tal cual.
SKIN_SIGNAL_COLORS: dict[str, str] = {
    '#00b894': STATUS_HEX['good'], '#2ecc71': STATUS_HEX['good'], '#33cc66': STATUS_HEX['good'],
    'green': STATUS_HEX['good'],
    '#fdcb6e': STATUS_HEX['warn'], '#e68033': STATUS_HEX['warn'], 'orange': STATUS_HEX['warn'],
    '#d63031': STATUS_HEX['error'], '#d93333': STATUS_HEX['error'], 'red': STATUS_HEX['error'],
}


def skin_hex(color: str) -> str:
    """Color de señal del núcleo → color de la piel NetMonster."""
    return SKIN_SIGNAL_COLORS.get(color, SKIN_SIGNAL_COLORS.get(color.lower(), color))


def _theme_rgba(theme: dict[str, list[float]], key: str) -> tuple[float, float, float, float]:
    """Color del tema como tupla RGBA de 4 (para Color/*args de Kivy)."""
    v = theme[key]
    return (v[0], v[1], v[2], v[3])


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


# Original mejorado: MCC → código ISO del país para la cabecera
# («OPERADOR · CU»). Asignaciones ITU; si el MCC no está, solo «OPERADOR».
_MCC_COUNTRY: dict[str, str] = {
    '208': 'FR', '214': 'ES', '222': 'IT', '226': 'RO', '228': 'CH',
    '230': 'CZ', '231': 'SK', '232': 'AT', '234': 'GB', '238': 'DK',
    '242': 'NO', '244': 'FI', '246': 'LT', '247': 'LV', '248': 'EE',
    '250': 'RU', '255': 'UA', '257': 'BY', '260': 'PL', '262': 'DE',
    '268': 'PT', '272': 'IE', '310': 'US', '311': 'US', '312': 'US',
    '334': 'MX', '368': 'CU', '401': 'KZ', '716': 'PE', '722': 'AR',
    '724': 'BR', '730': 'CL', '732': 'CO', '738': 'BO', '740': 'EC',
    '744': 'PY', '746': 'JM',
}


def _operator_sub(plmn: str) -> str:
    """'OPERADOR · CU' — el país sale del MCC del PLMN, si se conoce."""
    cc = _MCC_COUNTRY.get(plmn[:3]) if len(plmn) >= 3 else None
    text = f"{t('Оператор')} · {cc}" if cc else t('Оператор')
    return text.upper()


def _format_plmn(plmn: str) -> str:
    """'36801' → '368 01' (MCC + MNC)."""
    if len(plmn) in (5, 6):
        return f"{plmn[:3]} {plmn[3:]}"
    return plmn


def _tech_chip(rat: str) -> str:
    """Chip de tecnología para la cabecera ('4G LTE', '5G NSA'...)."""
    return {'lte': '4G LTE', 'lte_ca': '4G LTE+', 'nr_nsa': '5G NSA',
            'nr_sa': '5G SA', '3g': '3G', '2g': '2G'}.get(rat, '')


def _band_freq_name(band: int) -> str:
    """Frecuencia nominal del bánd ('1800' para B3) o '' si no se conoce."""
    info = LTE_BAND_TABLE.get(band)
    if info is None:
        return ""
    return info[0].split()[0]


# Rangos de las barras de las tarjetas de métricas (la posición del
# valor en su rango, como las antiguas barras de NIVEL DE SEÑAL;
# RSRQ/RSSI con los rangos del preview).
_METRIC_RANGES: dict[str, tuple[float, float]] = {
    'sinr': (-20.0, 30.0), 'rsrp': (-140.0, -44.0),
    'rsrq': (-30.0, -3.0), 'rssi': (-110.0, -40.0),
}


def _primary_band(snap: Snapshot) -> int | None:
    """Banda principal (la primera de snap.bands) o None si no hay."""
    return snap.bands[0] if snap.bands else None


def _primary_band_label(snap: Snapshot) -> str:
    """'B3 · 1800' para la banda principal, o '—' si no se conoce."""
    band = _primary_band(snap)
    if band is None:
        return "—"
    freq = _band_freq_name(band)
    return f"B{band} · {freq}" if freq else f"B{band}"


def _primary_band_duplex(snap: Snapshot) -> str:
    """'FDD'/'TDD' de la banda principal, o '—' si no se conoce."""
    band = _primary_band(snap)
    if band is None:
        return "—"
    info = LTE_BAND_TABLE.get(band)
    return info[1] if info else "—"


def _dash_num(value: float | int | None) -> str:
    """Número o '—' si falta (las filas de INFORMACIÓN LTE)."""
    text = fmt_num(value)
    return "—" if text == "-" else text


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
    base_size = NumericProperty(sp(FONT['body']))

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


class IconWidget(Widget):
    """Icono vectorial de líneas (sin emojis): se dibuja con canvas.

    Coordenadas relativas al centro y al lado menor del widget, así el
    mismo icono sirve en la tarjeta de Conexión, en el Menú y en los
    botones. Iconos: info, radar, gear, sun, power, router, lock,
    eye, eye_off, expand, check, signal, network, menu.
    """
    icon = StringProperty('')
    icon_color = ListProperty([1, 1, 1, 1])
    line_width = NumericProperty(2)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.bind(icon=self._redraw, icon_color=self._redraw,
                  size=self._redraw, pos=self._redraw)

    def _line(self, points: list[float], width: float | None = None) -> None:
        from kivy.graphics import Line
        Line(points=points, width=width or float(self.line_width),
             cap='round', joint='round')

    def _circle(self, cx: float, cy: float, r: float,
                start: float = 0, end: float = 360) -> None:
        from kivy.graphics import Line
        Line(circle=(cx, cy, r, start, end), width=float(self.line_width),
             cap='round')

    def _dot(self, cx: float, cy: float, r: float) -> None:
        from kivy.graphics import Ellipse
        Ellipse(pos=(cx - r, cy - r), size=(2 * r, 2 * r))

    def _rays(self, cx: float, cy: float, r0: float, r1: float,
              angles: list[float]) -> None:
        import math
        for a in angles:
            rad = math.radians(a)
            self._line([cx + r0 * math.cos(rad), cy + r0 * math.sin(rad),
                        cx + r1 * math.cos(rad), cy + r1 * math.sin(rad)])

    def _redraw(self, *args: Any) -> None:
        from kivy.graphics import Color, Line
        self.canvas.clear()
        if not self.icon or self.width <= 0 or self.height <= 0:
            return
        cx, cy = self.center_x, self.center_y
        r = min(self.width, self.height) / 2
        with self.canvas:
            Color(*self.icon_color)
            if self.icon == 'info':
                self._circle(cx, cy, 0.85 * r)
                self._dot(cx, cy + 0.42 * r, 0.09 * r)
                self._line([cx, cy + 0.12 * r, cx, cy - 0.45 * r])
            elif self.icon == 'radar':
                self._dot(cx, cy, 0.1 * r)
                self._circle(cx, cy, 0.45 * r, 20, 70)
                self._circle(cx, cy, 0.78 * r, 20, 70)
                self._circle(cx, cy, 0.78 * r, 200, 250)
            elif self.icon == 'gear':
                self._circle(cx, cy, 0.34 * r)
                self._rays(cx, cy, 0.46 * r, 0.85 * r,
                           [0, 45, 90, 135, 180, 225, 270, 315])
            elif self.icon == 'sun':
                self._circle(cx, cy, 0.32 * r)
                self._rays(cx, cy, 0.48 * r, 0.82 * r,
                           [0, 45, 90, 135, 180, 225, 270, 315])
            elif self.icon == 'power':
                self._circle(cx, cy, 0.68 * r, 40, 320)
                self._line([cx, cy + 0.88 * r, cx, cy + 0.18 * r])
            elif self.icon == 'router':
                Line(rectangle=(cx - 0.82 * r, cy - 0.38 * r,
                                1.64 * r, 0.76 * r),
                     width=float(self.line_width))
                for dx in (-0.55, -0.18, 0.18, 0.55):
                    self._dot(cx + dx * r, cy, 0.09 * r)
                self._line([cx - 0.4 * r, cy + 0.62 * r,
                            cx + 0.4 * r, cy + 0.62 * r])
            elif self.icon == 'lock':
                self._circle(cx, cy + 0.22 * r, 0.34 * r, 0, 180)
                self._line([cx - 0.34 * r, cy + 0.22 * r,
                            cx - 0.34 * r, cy - 0.08 * r])
                self._line([cx + 0.34 * r, cy + 0.22 * r,
                            cx + 0.34 * r, cy - 0.08 * r])
                Line(rounded_rectangle=(cx - 0.58 * r, cy - 0.78 * r,
                                         1.16 * r, 0.7 * r, 0.12 * r),
                     width=float(self.line_width))
            elif self.icon in ('eye', 'eye_off'):
                Line(ellipse=(cx - 0.85 * r, cy - 0.42 * r,
                              1.7 * r, 0.84 * r),
                     width=float(self.line_width))
                self._circle(cx, cy, 0.28 * r)
                if self.icon == 'eye_off':
                    self._line([cx - 0.68 * r, cy + 0.6 * r,
                                cx + 0.68 * r, cy - 0.6 * r])
            elif self.icon == 'expand':
                for sx, sy in ((-1, 1), (1, 1), (-1, -1), (1, -1)):
                    self._line([cx + sx * 0.82 * r, cy + sy * 0.45 * r,
                                cx + sx * 0.82 * r, cy + sy * 0.82 * r,
                                cx + sx * 0.45 * r, cy + sy * 0.82 * r])
            elif self.icon == 'check':
                self._line([cx - 0.6 * r, cy + 0.02 * r,
                            cx - 0.14 * r, cy - 0.44 * r,
                            cx + 0.62 * r, cy + 0.48 * r])
            elif self.icon == 'signal':
                # Barras de señal ascendentes (barra inferior: Señal).
                for dx, h in ((-0.6, 0.35), (-0.2, 0.6),
                              (0.2, 0.85), (0.6, 1.1)):
                    self._line([cx + dx * r, cy - 0.55 * r,
                                cx + dx * r, cy - 0.55 * r + h * r])
            elif self.icon == 'network':
                # Deslizadores (barra inferior: Red / bandas).
                for dy, dx in ((0.45, -0.3), (0, 0.35), (-0.45, -0.05)):
                    self._line([cx - 0.8 * r, cy + dy * r,
                                cx + 0.8 * r, cy + dy * r])
                    self._dot(cx + dx * r, cy + dy * r, 0.14 * r)
            elif self.icon == 'menu':
                # Hamburguesa (barra inferior: Menú).
                for dy in (0.5, 0, -0.5):
                    self._line([cx - 0.75 * r, cy + dy * r,
                                cx + 0.75 * r, cy + dy * r])


class LiveDot(Widget):
    """Punto verde que late junto a «EN VIVO»: animación de opacidad."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pulse: Any = None

    def start(self) -> None:
        self.stop()
        from kivy.animation import Animation
        self._pulse = Animation(opacity=0.35, d=0.8) + Animation(opacity=1, d=0.8)
        self._pulse.repeat = True
        self._pulse.start(self)

    def stop(self) -> None:
        if self._pulse is not None:
            self._pulse.cancel(self)
            self._pulse = None
        self.opacity = 1


class BandCheckBox(CheckBox):
    """Casilla de banda solo visual: el toque lo gestiona su tarjeta.

    Sin esto, tocar la casilla la cambiaría una vez y la tarjeta otra,
    y el estado quedaría igual. El estado se lee y se escribe igual
    que antes (band_vars: .active), así la lógica no cambia.
    """

    def on_touch_down(self, touch: Any) -> bool:
        return False

    def on_touch_move(self, touch: Any) -> bool:
        return False

    def on_touch_up(self, touch: Any) -> bool:
        return False


class NavItem(ButtonBehavior, BoxLayout):
    """Botón de la barra inferior (Etapa 5): icono de líneas + etiqueta.

    ``target`` es la pantalla a la que navega ('monitor', 'info',
    'tools') o 'menu' para abrir el Menú; ``active`` marca la sección
    seleccionada. La apariencia vive en la regla KV <NavItem>.
    """

    icon = StringProperty('')
    label = StringProperty('')
    target = StringProperty('')
    active = BooleanProperty(False)


class BottomNavBar(BoxLayout):
    """Barra de navegación inferior (Etapa 5): los 4 accesos existentes.

    ``section`` es la pantalla que la contiene ('monitor', 'info' o
    'tools'): cada instancia resalta su propio acceso y el de Menú
    nunca queda seleccionado (abre la hoja, no es una pantalla). La
    pantalla de Conexión no lleva barra. La apariencia vive en la
    regla KV <BottomNavBar>.
    """

    section = StringProperty('')


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
        self._fill_tex: Any = None
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

    def _fill_under_line(self, x0: float, y0: float, plot_w: float, plot_h: float,
                         segs: list[tuple[float, float, float, float]],
                         line_col: tuple[float, float, float, float]) -> None:
        """Relleno degradado bajo la línea principal (piel NetMonster).

        Malla de triángulos entre la línea y la base del gráfico: arriba
        el color de la línea con alfa 0,28 y abajo transparente. Se dibuja
        antes que la línea, dentro del mismo canvas.

        El color va en la instrucción Color y el degradado en una textura
        1×2 (fila de arriba opaca, fila de abajo transparente): el
        atributo vColor en el formato de vértices no se dibuja bien en
        Kivy (el relleno salía invisible o como un triángulo gigante fuera
        del gráfico con mucho historial), así que no se usa.
        """
        from kivy.graphics import Color, Mesh
        from kivy.graphics.texture import Texture
        if self._fill_tex is None:
            self._fill_tex = Texture.create(size=(1, 2))
            self._fill_tex.blit_buffer(b'\xff\xff\xff\x00\xff\xff\xff\xff',
                                       colorfmt='rgba', bufferfmt='ubyte')
        pts = [(x0 + plot_w * segs[0][0], y0 + plot_h * segs[0][1])]
        pts += [(x0 + plot_w * s[2], y0 + plot_h * s[3]) for s in segs]
        verts: list[float] = []
        indices: list[int] = []
        for i, (px, py) in enumerate(pts):
            verts += [px, py, 0, 1, px, y0, 0, 0]
            if i:
                j = 2 * (i - 1)
                indices += [j, j + 1, j + 2, j + 1, j + 3, j + 2]
        Color(line_col[0], line_col[1], line_col[2], 0.28)
        Mesh(texture=self._fill_tex, vertices=verts, indices=indices,
             mode='triangles',
             vertex_format=[('vPosition', 2, 'float'),
                            ('vTexCoords0', 2, 'float')])
        Color(*line_col)

    def _redraw(self) -> None:
        from kivy.graphics import Color, Ellipse, Line, Rectangle
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
                tex = self._texture(f"{y_min + rng * i / 4:.0f}", sp(FONT['small']), text_col)
                Color(1, 1, 1, 1)
                Rectangle(texture=tex, pos=(x0 - tex.width - dp(4), gy - tex.height / 2),
                          size=tex.size)
            title = PARAM_TITLES.get(self._param, self._param.upper())
            tex = self._texture(f"{title} ({unit_of(self._param)})", sp(FONT['hint']),
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
            tex = self._texture(time_label, sp(FONT['tiny']), text_col)
            Rectangle(texture=tex, pos=(x0 + (plot_w - tex.width) / 2, self.y + dp(3)),
                      size=tex.size)

            if self._peak is not None and y_min <= self._peak <= y_max:
                py = y_of(self._peak)
                # El pico se marca con una línea punteada, como el umbral
                # de los gráficos NetMonster.
                Color(*theme['c_peak'])
                Line(points=[x0, py, x0 + plot_w, py], width=1, dash_length=dp(4),
                     dash_offset=dp(3))
            paired = self.viewport.has_comparison
            for comparison in ((False, True) if paired else (False,)):
                param = comparison_param(self._param) if comparison else self._param
                is_nr = param.startswith('nr_')
                if self._stale:
                    line_col = _theme_rgba(theme, 'c_nodata')
                elif is_nr:
                    line_col = _theme_rgba(theme, 'c_graph_nr')
                else:
                    line_col = _theme_rgba(theme, 'c_graph_line')
                Color(*line_col)
                segs = list(self.viewport.segments(comparison))
                if not comparison and not self._stale and segs:
                    self._fill_under_line(x0, y0, plot_w, plot_h, segs, line_col)
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
                tex = self._texture(label, sp(FONT['small']), line_col, True)
                Color(1, 1, 1, 1)
                Rectangle(texture=tex,
                          pos=(x0 + (plot_w / 2 if comparison else 0), self.y + h - dp(38)),
                          size=tex.size)
            if self._stale:
                tex = self._texture(t("нет свежих данных"), sp(FONT['hint']), text_col, True)
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
#:import FONT android_main.FONT
#:import RADIUS android_main.RADIUS
#:import STATUS_HEX android_main.STATUS_HEX
#:import hex_to_rgba android_main.hex_to_rgba

# ¡No renombrar a ActionButton!: ese nombre ya lo registra Kivy
# (kivy.uix.actionbar.ActionButton) y Kivy ignoraría esta regla,
# lo que rompía los diálogos (botón de 10128 px, bucle textura↔ancho).
<PrimaryButton@Button>:
    size_hint_x: 0.9
    pos_hint: {'center_x': 0.5}
    text_size: self.size
    halign: 'center'
    valign: 'middle'
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    color: app.c_on_accent
    font_size: sp(FONT['value'])
    size_hint_y: None
    height: dp(52)
    canvas.before:
        Color:
            rgba: app.c_accent if self.state == 'normal' else app.c_accent_down
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(RADIUS['button'])]

<FlatButton@Button>:
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    color: app.c_text
    font_size: sp(FONT['value'])
    canvas.before:
        Color:
            rgba: app.c_button2 if self.state == 'normal' else app.c_btn_down
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(RADIUS['button'])]
    canvas.after:
        Color:
            rgba: app.c_border
        Line:
            rounded_rectangle: self.x + dp(0.5), self.y + dp(0.5), self.width - dp(1), self.height - dp(1), dp(RADIUS['button'])
            width: dp(1)

# Spinner con la piel del tema (antes usaba el gris claro por defecto
# de Kivy, que rompía con la interfaz oscura): mismo fondo/borde que
# FlatButton, texto del tema y flecha dibujada (el fondo por defecto
# de Kivy trae su propia flecha y no se puede teñir).
<ThemedSpinnerOption@Button>:
    size_hint_y: None
    height: dp(48)
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    color: app.c_text
    font_size: sp(FONT['body'])
    canvas.before:
        Color:
            rgba: app.c_button2 if self.state == 'normal' else app.c_btn_down
        Rectangle:
            pos: self.pos
            size: self.size

<ThemedSpinner@Spinner>:
    background_normal: ''
    background_down: ''
    background_disabled_normal: ''
    background_color: 0, 0, 0, 0
    color: app.c_text
    option_cls: 'ThemedSpinnerOption'
    canvas.before:
        Color:
            rgba: app.c_button2 if self.state == 'normal' else app.c_btn_down
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(RADIUS['button'])]
    canvas.after:
        Color:
            rgba: app.c_border
        Line:
            rounded_rectangle: self.x + dp(0.5), self.y + dp(0.5), self.width - dp(1), self.height - dp(1), dp(RADIUS['button'])
            width: dp(1)
        Color:
            rgba: app.c_sub
        Triangle:
            points: [self.right - dp(24), self.center_y + dp(3), self.right - dp(14), self.center_y + dp(3), self.right - dp(19), self.center_y - dp(4)]

# CheckBox con la piel del tema (el atlas por defecto de Kivy es una
# caja blanca que rompía con la interfaz oscura): borde redondeado del
# tema, relleno verde al activar y marca blanca. Las imágenes del atlas
# se vacían para que el BorderImage por defecto no dibuje nada.
<ThemedCheckBox@CheckBox>:
    background_checkbox_normal: ''
    background_checkbox_down: ''
    background_checkbox_disabled_normal: ''
    background_checkbox_disabled_down: ''
    canvas.after:
        Color:
            rgba: app.c_accent if self.active else app.c_border
        Line:
            rounded_rectangle: self.x + dp(1.5), self.y + dp(1.5), self.width - dp(3), self.height - dp(3), dp(RADIUS['chip'])
            width: dp(1.5)
        Color:
            rgba: app.c_accent if self.active else (0, 0, 0, 0)
        RoundedRectangle:
            pos: self.x + dp(5), self.y + dp(5)
            size: self.width - dp(10), self.height - dp(10)
            radius: [dp(4)]
        Color:
            rgba: app.c_on_accent if self.active else (0, 0, 0, 0)
        Line:
            points: [self.x + dp(11), self.center_y + dp(1), self.center_x - dp(1), self.y + dp(11), self.right - dp(10), self.top - dp(10)]
            width: dp(2)

# Original mejorado: línea fina verde tenue (separador de sección) y
# línea verde sólida de 2 dp (bajo el encabezado, como en la vista previa).
<Hairline@Widget>:
    size_hint_y: None
    height: dp(1)
    canvas:
        Color:
            rgba: app.c_accent[0], app.c_accent[1], app.c_accent[2], 0.35
        Rectangle:
            pos: self.pos
            size: self.size

<GreenRule@Widget>:
    size_hint_y: None
    height: dp(2)
    canvas:
        Color:
            rgba: app.c_accent
        Rectangle:
            pos: self.pos
            size: self.size

# Original mejorado: título de sección en verde, en mayúsculas, con la
# línea fina extendiéndose a la derecha (como «INFORMACIÓN LTE» del preview).
<SectionHead@BoxLayout>:
    text: ''
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(26)
    spacing: dp(10)
    Label:
        text: root.text
        font_size: sp(FONT['hint'])
        bold: True
        color: app.c_accent
        size_hint_x: None
        width: self.texture_size[0]
        halign: 'left'
        valign: 'middle'
    Hairline:
        pos_hint: {'center_y': 0.5}

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
            radius: [dp(RADIUS['card'])]

<AutoLabel@Label>:
    font_size: sp(FONT['body'])
    color: app.c_text
    size_hint_y: None
    height: self.texture_size[1] + dp(6)
    text_size: self.width, None
    halign: 'left'
    valign: 'top'

<HintLabel@AutoLabel>:
    font_size: sp(FONT['hint'])
    color: app.c_sub

<InfoLabel@AutoLabel>:
    font_size: sp(FONT['value'])
    line_height: 1.3
    markup: True

# m_color por defecto es el gris "sin datos" = c_nodata (#808080).
# No se puede poner app.c_nodata aquí: al construir el widget el
# binding aún no se evaluó y m_color llega None al canvas.
<MetricCard@BoxLayout>:
    orientation: 'vertical'
    m_name: ''
    m_value: '-'
    m_status: ''
    m_peak: ''
    m_color: 0.5, 0.5, 0.5, 1
    m_pct: 0
    value_size: sp(FONT['hero'])
    padding: dp(6)
    spacing: dp(1)
    canvas.before:
        Color:
            rgba: app.c_card
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(RADIUS['card'])]
    canvas.after:
        Color:
            rgba: app.c_border
        Line:
            rounded_rectangle: self.x + dp(0.5), self.y + dp(0.5), self.width - dp(1), self.height - dp(1), dp(RADIUS['card'])
            width: dp(1)
    CardLabel:
        caption: root.m_name
        base_size: sp(FONT['label'])
        bold: True
        color: app.c_sub
        size_hint_y: 0.17
    CardLabel:
        caption: root.m_value
        base_size: root.value_size
        bold: True
        color: app.c_text
        size_hint_y: 0.43
    Widget:
        size_hint_y: None
        height: dp(5)
        canvas.before:
            Color:
                rgba: app.c_sep
            Rectangle:
                pos: self.pos
                size: self.size
            Color:
                rgba: root.m_color
            Rectangle:
                pos: self.pos
                size: self.width * root.m_pct / 100, self.height
    # Etapa 6: la fila de estado tenía 0,15 (15,4 dp) y su textura
    # mide 16 px, así que CardLabel la achicaba a 10,9 sp en todos
    # los tamaños; con 0,19 (19,6 dp) cabe a 13 sp sin encoger.
    CardLabel:
        caption: root.m_status
        base_size: sp(FONT['hint'])
        color: root.m_color
        size_hint_y: 0.19
    CardLabel:
        id: peak_label
        caption: root.m_peak
        base_size: sp(FONT['hint'])
        color: app.c_sub
        halign: 'center'
        size_hint_y: 0.21

# Original mejorado: fila etiqueta→valor de INFORMACIÓN LTE
# (etiqueta pequeña gris a la izquierda, valor blanco a la derecha,
# unidad pequeña gris; línea fina entre filas).
<ParamRow@BoxLayout>:
    key: ''
    value: '—'
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(34)
    spacing: dp(8)
    canvas.after:
        Color:
            rgba: app.c_sep
        Rectangle:
            pos: self.pos
            size: self.width, dp(1)

    Label:
        text: root.key
        font_size: sp(FONT['small'])
        bold: True
        color: app.c_sub
        size_hint_x: None
        width: dp(64)
        text_size: self.size
        halign: 'left'
        valign: 'middle'
    Label:
        text: root.value
        font_size: sp(FONT['value'])
        color: app.c_text
        markup: True
        text_size: self.size
        halign: 'right'
        valign: 'middle'
# Original mejorado: un segmento de la barra de salud.
<Seg@Widget>:
    lit: False
    lit_color: 0, 0, 0, 1
    canvas:
        Color:
            rgba: self.lit_color if self.lit else app.c_sep
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(3)]

# Etapa 4: campo de texto con icono y borde que se ilumina al enfocar
# (como en el preview: fondo del tema, borde verde al escribir).
<FieldBox@BoxLayout>:
    focused: False
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(50)
    spacing: dp(4)
    padding: dp(12), 0
    canvas.before:
        Color:
            rgba: app.c_bg
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(RADIUS['button'])]
    canvas.after:
        Color:
            rgba: app.c_accent if self.focused else app.c_border
        Line:
            rounded_rectangle: self.x + dp(0.75), self.y + dp(0.75), self.width - dp(1.5), self.height - dp(1.5), dp(RADIUS['button'])
            width: dp(1.5) if self.focused else dp(1)

# Etapa 4: botón ojo de la contraseña (icono vectorial, sin texto).
<EyeToggle@ButtonBehavior+IconWidget>:
    size_hint: None, None
    size: dp(40), dp(40)
    pos_hint: {'center_y': 0.5}
    line_width: dp(1.8)

# Etapa 4: botón píldora elevada (Picos / Menú): radio grande, mismo
# alto y misma tipografía que en el preview.
<PillButton@Button>:
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    color: app.c_text
    font_size: sp(FONT['value'])
    bold: True
    canvas.before:
        Color:
            rgba: app.c_button2 if self.state == 'normal' else app.c_btn_down
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(28)]
    canvas.after:
        Color:
            rgba: app.c_border
        Line:
            rounded_rectangle: self.x + dp(0.5), self.y + dp(0.5), self.width - dp(1), self.height - dp(1), dp(28)
            width: dp(1)

# Etapa 4: botón de un control segmentado (parámetro del gráfico,
# modo de antena): verde al estar activo, plano si no.
<SegButton@ToggleButton>:
    param: ''
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    color: app.c_on_accent if self.state == 'down' else app.c_text
    font_size: sp(FONT['hint'])
    bold: True
    canvas.before:
        Color:
            rgba: app.c_accent if self.state == 'down' else app.c_button2
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(8)]

# Etapa 5: un acceso de la barra inferior: icono de líneas arriba y
# etiqueta debajo; activo con pastilla verde al 16 % e icono y texto
# en verde, inactivo en gris. El toque lo gestiona ButtonBehavior.
<NavItem>:
    orientation: 'vertical'
    spacing: dp(2)
    padding: dp(2), dp(7)
    canvas.before:
        Color:
            rgba: (app.c_accent[0], app.c_accent[1], app.c_accent[2], 0.16) if root.active else (0, 0, 0, 0)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(RADIUS['button'])]
    IconWidget:
        icon: root.icon
        icon_color: app.c_accent if root.active else app.c_sub
        size_hint: None, None
        size: dp(24), dp(24)
        pos_hint: {'center_x': 0.5}
        line_width: dp(1.8)
    Label:
        text: root.label
        font_size: sp(FONT['small'])
        bold: root.active
        color: app.c_accent if root.active else app.c_sub
        size_hint_y: None
        height: dp(16)
        text_size: self.size
        halign: 'center'
        valign: 'middle'
        shorten: True
        shorten_from: 'right'

# Etapa 5: barra de navegación inferior: píldora flotante con los 4
# accesos existentes (Señal, Información, Red, Menú). Cada pantalla
# lleva su propia instancia con section fijo, así el acceso activo
# es siempre el de la pantalla que se está viendo; Menú nunca queda
# seleccionado porque abre la hoja, no es una pantalla. La Conexión
# no lleva barra. El margen inferior de 8 dp es el área segura.
<BottomNavBar>:
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(64)
    padding: dp(4)
    spacing: dp(4)
    canvas.before:
        Color:
            rgba: app.c_card
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(RADIUS['pill'])]
    canvas.after:
        Color:
            rgba: app.c_border
        Line:
            rounded_rectangle: self.x + dp(0.5), self.y + dp(0.5), self.width - dp(1), self.height - dp(1), dp(RADIUS['pill'])
            width: dp(1)
    NavItem:
        icon: 'signal'
        label: app.lbl_nav_signal
        target: 'monitor'
        active: root.section == 'monitor'
        on_release: app.go(self.target)
    NavItem:
        icon: 'info'
        label: app.lbl_nav_info
        target: 'info'
        active: root.section == 'info'
        on_release: app.go(self.target)
    NavItem:
        icon: 'network'
        label: app.lbl_nav_tools
        target: 'tools'
        active: root.section == 'tools'
        on_release: app.go(self.target)
    NavItem:
        icon: 'menu'
        label: app.lbl_nav_menu
        target: 'menu'
        active: False
        on_release: app.open_menu()

# Etapa 4: anillo de salud: arco de fondo gris + arco de color según
# el porcentaje (0-100 %), con el % en el centro.
<HealthRing@FloatLayout>:
    pct: 0
    pct_text: '0%'
    ring_color: 0.5, 0.5, 0.5, 1
    size_hint: None, None
    size: dp(86), dp(86)
    canvas:
        Color:
            rgba: app.c_sep
        Line:
            circle: self.center_x, self.center_y, dp(36), 0, 360
            width: dp(8)
            cap: 'round'
        Color:
            rgba: root.ring_color
        Line:
            circle: self.center_x, self.center_y, dp(36), 90 - root.pct * 3.6, 90
            width: dp(8)
            cap: 'round'
    Label:
        text: root.pct_text
        font_size: sp(21)
        bold: True
        color: app.c_text
        size_hint: 1, 1
        # Sin pos_hint, un hijo de FloatLayout queda en (0, 0) de la
        # ventana: en Kivy las coordenadas se comparten con el padre.
        pos_hint: {'center_x': 0.5, 'center_y': 0.5}
        text_size: self.size
        halign: 'center'
        valign: 'middle'

# Etapa 4: punto verde que late junto a «EN VIVO».
<LiveDot>:
    size_hint: None, None
    size: dp(12), dp(12)
    canvas:
        Color:
            rgba: app.c_accent
        Ellipse:
            pos: self.center_x - dp(4), self.center_y - dp(4)
            size: dp(8), dp(8)

# Etapa 4: fila etiqueta→valor de Información (etiqueta en negrita,
# valor normal; «Sin datos» en gris; el valor envuelve si es largo).
<InfoRow@BoxLayout>:
    row_key: ''
    row_value: ''
    row_nodata: False
    orientation: 'horizontal'
    size_hint_y: None
    height: max(dp(30), value_lbl.texture_size[1] + dp(10))
    spacing: dp(8)
    Label:
        text: root.row_key + ':'
        font_size: sp(FONT['value'])
        bold: True
        color: app.c_text
        size_hint: None, None
        size: self.texture_size
        pos_hint: {'center_y': 0.5}
    Label:
        id: value_lbl
        text: root.row_value
        font_size: sp(FONT['value'])
        color: app.c_nodata if root.row_nodata else app.c_text
        text_size: self.width, None
        halign: 'left'
        valign: 'middle'

# Etapa 4: separador fino entre filas de Información.
<SepLine@Widget>:
    size_hint_y: None
    height: dp(1)
    canvas:
        Color:
            rgba: app.c_sep
        Rectangle:
            pos: self.pos
            size: self.size

# Etapa 4: casilla de banda de 24 dp, dibujada a escala (la regla
# ThemedCheckBox usa medidas absolutas para 40 dp).
<BandCheckBox>:
    background_checkbox_normal: ''
    background_checkbox_down: ''
    background_checkbox_disabled_normal: ''
    background_checkbox_disabled_down: ''
    canvas.after:
        Color:
            rgba: app.c_accent if self.active else app.c_border
        Line:
            rounded_rectangle: self.x + dp(1.5), self.y + dp(1.5), self.width - dp(3), self.height - dp(3), dp(6)
            width: dp(1.5)
        Color:
            rgba: app.c_accent if self.active else (0, 0, 0, 0)
        RoundedRectangle:
            pos: self.x + self.width * 0.2, self.y + self.height * 0.2
            size: self.width * 0.6, self.height * 0.6
            radius: [dp(3)]
        Color:
            rgba: app.c_on_accent if self.active else (0, 0, 0, 0)
        Line:
            points: [self.x + self.width * 0.24, self.center_y, self.center_x - self.width * 0.06, self.y + self.height * 0.24, self.right - self.width * 0.2, self.top - self.height * 0.2]
            width: dp(2)

# Etapa 4: banda como tarjeta tocable de 60 dp (casilla integrada):
# toda la tarjeta cambia la casilla, no solo el cuadradito.
<BandCard@ButtonBehavior+BoxLayout>:
    band: 0
    name: ''
    sub: ''
    # Activa o no: la casilla es solo visual; el estado vive aquí y
    # el canvas lo lee (en canvas no se puede usar ids.cb: al evaluar
    # las instrucciones la casilla aún no está en ids).
    active: False
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(60)
    spacing: dp(10)
    padding: dp(10), 0
    on_press: self.active = not self.active
    canvas.before:
        Color:
            rgba: (app.c_accent[0], app.c_accent[1], app.c_accent[2], 0.16) if root.active else app.c_bg
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(RADIUS['card'])]
    canvas.after:
        Color:
            rgba: app.c_accent if root.active else app.c_border
        Line:
            rounded_rectangle: self.x + dp(0.75), self.y + dp(0.75), self.width - dp(1.5), self.height - dp(1.5), dp(RADIUS['card'])
            width: dp(1.5)
    BandCheckBox:
        id: cb
        active: root.active
        size_hint: None, None
        size: dp(24), dp(24)
        pos_hint: {'center_y': 0.5}
    BoxLayout:
        orientation: 'vertical'
        Label:
            text: root.name
            font_size: sp(FONT['value'])
            bold: True
            color: app.c_text
            size_hint_y: 0.55
            text_size: self.size
            halign: 'left'
            valign: 'middle'
        Label:
            text: root.sub
            font_size: sp(FONT['small'])
            color: app.c_sub
            size_hint_y: 0.45
            text_size: self.size
            halign: 'left'
            valign: 'middle'

# Etapa 4: ítem del Menú como tarjeta (icono en pastilla verde,
# nombre + descripción, flecha): como la hoja inferior del preview.
<MenuItem@ButtonBehavior+BoxLayout>:
    icon: ''
    name: ''
    desc: ''
    danger: False
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(58)
    spacing: dp(10)
    padding: dp(10), dp(6)
    canvas.before:
        Color:
            rgba: app.c_card
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(14)]
    canvas.after:
        Color:
            rgba: app.c_border
        Line:
            rounded_rectangle: self.x + dp(0.5), self.y + dp(0.5), self.width - dp(1), self.height - dp(1), dp(14)
            width: dp(1)
    FloatLayout:
        size_hint: None, None
        size: dp(38), dp(38)
        pos_hint: {'center_y': 0.5}
        canvas.before:
            Color:
                rgba: hex_to_rgba(STATUS_HEX['error'], app.theme_name == 'sun')[:3] + [0.14] if root.danger else (app.c_accent[0], app.c_accent[1], app.c_accent[2], 0.16)
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(11)]
        IconWidget:
            icon: root.icon
            icon_color: hex_to_rgba(STATUS_HEX['error'], app.theme_name == 'sun') if root.danger else app.c_accent
            size_hint: None, None
            size: dp(20), dp(20)
            pos_hint: {'center_x': 0.5, 'center_y': 0.5}
            line_width: dp(1.8)
    BoxLayout:
        orientation: 'vertical'
        Label:
            text: root.name
            font_size: sp(FONT['body'])
            bold: True
            color: hex_to_rgba(STATUS_HEX['error'], app.theme_name == 'sun') if root.danger else app.c_text
            size_hint_y: 0.55
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            shorten: True
            shorten_from: 'right'
        Label:
            text: root.desc
            font_size: sp(FONT['small'])
            color: app.c_sub
            size_hint_y: 0.45
            text_size: self.size
            halign: 'left'
            valign: 'middle'
            shorten: True
            shorten_from: 'right'
    Label:
        text: '›'
        font_size: sp(FONT['big'])
        color: app.c_sub
        size_hint_x: None
        width: dp(16)
        text_size: self.size
        halign: 'center'
        valign: 'middle'

# Etapa 4: asa de la hoja inferior del Menú.
<SheetGrip@Widget>:
    size_hint_y: None
    height: dp(12)
    canvas:
        Color:
            rgba: app.c_border
        RoundedRectangle:
            pos: self.center_x - dp(21), self.center_y - dp(2)
            size: dp(42), dp(4)
            radius: [dp(2)]

# Original mejorado: una fila de portadora (PCC/SCC) en CARRIER AGGREGATION.
<CaRow@BoxLayout>:
    tag: ''
    band: ''
    earfcn: ''
    bw: ''
    bw_label: ''
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(56)
    spacing: dp(10)
    Label:
        text: root.tag
        font_size: sp(FONT['small'])
        bold: True
        color: app.c_accent if root.tag == 'PCC' else app.c_sub
        size_hint_x: None
        width: dp(44)
        text_size: self.size
        halign: 'center'
        valign: 'middle'
        canvas.before:
            Color:
                rgba: (app.c_accent[0], app.c_accent[1], app.c_accent[2], 0.16) if root.tag == 'PCC' else app.c_button2
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(RADIUS['chip'])]
    BoxLayout:
        orientation: 'vertical'
        Label:
            text: root.band
            font_size: sp(FONT['body'])
            bold: True
            color: app.c_text
            size_hint_y: 0.55
            text_size: self.size
            halign: 'left'
            valign: 'middle'
        Label:
            text: root.earfcn
            font_size: sp(FONT['small'])
            color: app.c_sub
            size_hint_y: 0.45
            text_size: self.size
            halign: 'left'
            valign: 'middle'
    BoxLayout:
        orientation: 'vertical'
        size_hint_x: None
        width: dp(96)
        Label:
            text: root.bw
            font_size: sp(FONT['body'])
            color: app.c_text
            size_hint_y: 0.55
            text_size: self.size
            halign: 'right'
            valign: 'middle'
        Label:
            text: root.bw_label
            font_size: sp(FONT['small'])
            color: app.c_sub
            size_hint_y: 0.45
            text_size: self.size
            halign: 'right'
            valign: 'middle'

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
        font_size: sp(FONT['title'])
        bold: True
        color: app.c_text

ScreenManager:
    ConnectionScreen:
    MonitorScreen:
    InfoScreen:
    ToolsScreen:

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
        bar_color: app.c_sub
        bar_inactive_color: app.c_sep[0], app.c_sep[1], app.c_sep[2], 0.25
        scroll_type: ['bars', 'content']
        BoxLayout:
            orientation: 'vertical'
            size_hint_y: None
            height: self.minimum_height
            padding: dp(24)
            spacing: dp(12)
            CardLabel:
                caption: 'Hua4GMon'
                base_size: sp(FONT['display'])
                bold: True
                color: app.c_text
                size_hint_y: None
                height: dp(64)
                # Etapa 6: CardLabel (autoajuste) en vez de Label fijo:
                # a 216 dp el título no cabía (233 px en 168 dp) y se
                # cortaba; ahora achica la fuente solo si hace falta.
            Label:
                text: root.subtitle
                font_size: sp(FONT['body'])
                color: app.c_sub
                size_hint_y: None
                # Etapa 6: con la fuente del sistema grande el subtítulo
                # no cabe en una línea (347 px en 312 dp) y se cortaba
                # por los lados: envuelve y la altura sigue a la textura.
                height: max(dp(26), self.texture_size[1] + dp(4))
                text_size: self.width, None
                halign: 'center'
                valign: 'middle'
            GreenRule:
            SectionCard:
                SectionHead:
                    text: root.lbl_conn_title
                AutoLabel:
                    text: root.lbl_ip
                    font_size: sp(FONT['label'])
                    bold: True
                    color: app.c_sub
                BoxLayout:
                    size_hint_y: None
                    height: dp(50)
                    spacing: dp(8)
                    FieldBox:
                        id: ip_field
                        IconWidget:
                            icon: 'router'
                            icon_color: app.c_sub
                            size_hint: None, None
                            size: dp(20), dp(20)
                            pos_hint: {'center_y': 0.5}
                            line_width: dp(1.8)
                        TextInput:
                            id: ip_input
                            text: '192.168.8.1'
                            multiline: False
                            font_size: sp(FONT['big'])
                            background_color: 0, 0, 0, 0
                            foreground_color: app.c_text
                            cursor_color: app.c_accent
                            padding: dp(2), dp(12)
                            on_focus: ip_field.focused = args[1]
                    FlatButton:
                        text: root.lbl_find
                        size_hint_x: None
                        width: dp(88)
                        font_size: sp(FONT['body'])
                        on_release: root.on_find()
                AutoLabel:
                    text: root.lbl_pw
                    font_size: sp(FONT['label'])
                    bold: True
                    color: app.c_sub
                FieldBox:
                    id: pw_field
                    IconWidget:
                        icon: 'lock'
                        icon_color: app.c_sub
                        size_hint: None, None
                        size: dp(20), dp(20)
                        pos_hint: {'center_y': 0.5}
                        line_width: dp(1.8)
                    TextInput:
                        id: pw_input
                        password: True
                        multiline: False
                        font_size: sp(FONT['big'])
                        background_color: 0, 0, 0, 0
                        foreground_color: app.c_text
                        cursor_color: app.c_accent
                        padding: dp(2), dp(12)
                        on_focus: pw_field.focused = args[1]
                        on_text_validate: root.on_connect()
                    EyeToggle:
                        id: eye_btn
                        icon: 'eye'
                        on_press: root.on_toggle_password()
            PrimaryButton:
                text: root.lbl_connect
                on_release: root.on_connect()
            AutoLabel:
                id: status_lbl
                text: ''
                font_size: sp(FONT['body'])
                color: root.status_color
                halign: 'center'
            FlatButton:
                text: root.lbl_demo
                size_hint_y: None
                height: dp(48)
                # Etapa 6: en ventanas muy estrechas el texto no cabe en
                # una línea (237 px en 168 dp a 216 dp): envuelve a dos
                # líneas en vez de cortarse.
                text_size: self.width, None
                halign: 'center'
                valign: 'middle'
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
                    font_size: sp(FONT['body'])
                    size_hint_x: None
                    width: dp(80)
                ThemedSpinner:
                    id: lang_spinner
                    text: root.lang_name
                    values: root.lang_values
                    font_size: sp(FONT['body'])
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
        # Cabecera del operador (como en la vista previa).
        BoxLayout:
            size_hint_y: None
            height: dp(58)
            spacing: dp(8)
            BoxLayout:
                orientation: 'vertical'
                Label:
                    id: op_name_lbl
                    text: '—'
                    font_size: sp(FONT['operator'])
                    bold: True
                    color: app.c_text
                    shorten: True
                    shorten_from: 'right'
                    size_hint_y: 0.62
                    text_size: self.size
                    halign: 'left'
                    valign: 'bottom'
                Label:
                    id: op_sub_lbl
                    text: ''
                    font_size: sp(FONT['label'])
                    bold: True
                    color: app.c_sub
                    size_hint_y: 0.38
                    text_size: self.size
                    halign: 'left'
                    valign: 'top'
            BoxLayout:
                orientation: 'vertical'
                size_hint_x: None
                width: dp(110)
                Label:
                    id: plmn_lbl
                    text: ''
                    font_size: sp(FONT['big'])
                    bold: True
                    color: app.c_text
                    size_hint_y: 0.55
                    text_size: self.size
                    halign: 'right'
                    valign: 'bottom'
                BoxLayout:
                    size_hint_y: 0.45
                    Widget:
                    Label:
                        id: tech_chip_lbl
                        text: ''
                        font_size: sp(FONT['label'])
                        bold: True
                        color: app.c_on_accent
                        size_hint: None, None
                        size: dp(84), dp(24)
                        pos_hint: {'center_y': 0.5}
                        text_size: self.size
                        halign: 'center'
                        valign: 'middle'
                        canvas.before:
                            Color:
                                rgba: app.c_accent
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(RADIUS['chip'])]
        GreenRule:
        # Línea de ancla (solo si el router da bandas).
        BoxLayout:
            id: anchor_box
            size_hint_y: None
            height: dp(30) if root.anchor_visible else 0
            opacity: 1 if root.anchor_visible else 0
            Label:
                id: anchor_lbl
                text: ''
                font_size: sp(FONT['body'])
                bold: True
                color: app.c_text
                markup: True
                text_size: self.size
                halign: 'left'
                valign: 'middle'
        # Fila en vivo (punto que late + texto): en modo de prueba dice DEMO.
        BoxLayout:
            size_hint_y: None
            height: dp(22)
            spacing: dp(7)
            LiveDot:
                id: live_dot
                pos_hint: {'center_y': 0.5}
            Label:
                id: live_lbl
                text: ''
                font_size: sp(FONT['label'])
                bold: True
                color: app.c_sub
                text_size: self.size
                halign: 'left'
                valign: 'middle'
        ScrollView:
            bar_width: dp(8)
            bar_color: app.c_sub
            bar_inactive_color: app.c_sep[0], app.c_sep[1], app.c_sep[2], 0.25
            scroll_type: ['bars', 'content']
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                spacing: dp(10)
                # Tarjetas de métricas 2x2 (como en el preview): valor
                # grande, palabra de calidad con su punto, barra fina
                # y el pico de la sesión en la esquina.
                GridLayout:
                    cols: 2
                    size_hint_y: None
                    height: dp(258)
                    spacing: dp(10)
                    MetricCard:
                        id: sinr_card
                        m_name: 'SINR'
                    MetricCard:
                        id: rsrp_card
                        m_name: 'RSRP'
                    MetricCard:
                        id: rsrq_card
                        m_name: 'RSRQ'
                    MetricCard:
                        id: rssi_card
                        m_name: 'RSSI'
                SectionCard:
                    SectionHead:
                        text: root.lbl_health
                    BoxLayout:
                        size_hint_y: None
                        height: dp(86)
                        spacing: dp(16)
                        HealthRing:
                            id: health_ring
                        BoxLayout:
                            orientation: 'vertical'
                            size_hint_y: None
                            height: dp(35)
                            pos_hint: {'center_y': 0.5}
                            spacing: dp(6)
                            Label:
                                id: health_lbl
                                text: ''
                                font_size: sp(FONT['hint'])
                                bold: True
                                color: app.c_sub
                                size_hint_y: None
                                height: dp(20)
                                text_size: self.size
                                halign: 'left'
                                valign: 'middle'
                            BoxLayout:
                                id: segbar
                                size_hint_y: None
                                height: dp(9)
                                spacing: dp(3)
                                Seg:
                                Seg:
                                Seg:
                                Seg:
                                Seg:
                                Seg:
                                Seg:
                                Seg:
                                Seg:
                                Seg:
                                Seg:
                                Seg:
                                Seg:
                                Seg:
                                Seg:
                                Seg:
                                Seg:
                                Seg:
                                Seg:
                                Seg:
                    HintLabel:
                        text: root.lbl_health_note
                SectionHead:
                    text: root.lbl_info_lte
                BoxLayout:
                    size_hint_y: None
                    height: dp(136)
                    spacing: dp(26)
                    BoxLayout:
                        orientation: 'vertical'
                        ParamRow:
                            id: ci_row
                            key: 'CI'
                        ParamRow:
                            id: enb_row
                            key: 'ENB:CID'
                        ParamRow:
                            id: tac_row
                            key: 'TAC'
                        ParamRow:
                            id: pci_row
                            key: 'PCI'
                    BoxLayout:
                        orientation: 'vertical'
                        ParamRow:
                            id: earfcn_row
                            key: 'EARFCN'
                        ParamRow:
                            id: banda_row
                            key: 'BANDA'
                        ParamRow:
                            id: ancho_row
                            key: 'ANCHO'
                        ParamRow:
                            id: modo_row
                            key: 'MODO'
                BoxLayout:
                    id: ca_section
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height if root.ca_visible else 0
                    opacity: 1 if root.ca_visible else 0
                    spacing: dp(4)
                    BoxLayout:
                        id: ca_box
                        orientation: 'vertical'
                        size_hint_y: None
                        height: self.minimum_height
                        padding: dp(6), dp(10)
                        spacing: dp(4)
                        canvas.before:
                            Color:
                                rgba: app.c_card
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(RADIUS['card'])]
                        canvas.after:
                            Color:
                                rgba: app.c_accent
                            Line:
                                rounded_rectangle: self.x + dp(0.5), self.y + dp(0.5), self.width - dp(1), self.height - dp(1), dp(RADIUS['card'])
                                width: dp(1)
                        SectionHead:
                            text: root.lbl_ca
                        BoxLayout:
                            id: ca_rows
                            orientation: 'vertical'
                            size_hint_y: None
                            height: self.minimum_height
                        Hairline:
                        BoxLayout:
                            size_hint_y: None
                            height: dp(32)
                            Label:
                                id: ca_count_lbl
                                text: ''
                                font_size: sp(FONT['hint'])
                                color: app.c_sub
                                text_size: self.size
                                halign: 'left'
                                valign: 'middle'
                            Label:
                                id: ca_total_lbl
                                text: ''
                                font_size: sp(FONT['hint'])
                                color: app.c_sub
                                markup: True
                                text_size: self.size
                                halign: 'right'
                                valign: 'middle'
                # Controles del gráfico: se construyen en Python
                # (_sync_graph_seg): control segmentado + Ampliar.
                BoxLayout:
                    id: graph_controls
                    orientation: 'vertical'
                    size_hint_y: None
                    height: self.minimum_height
                    spacing: dp(8)
                SignalGraph:
                    id: signal_graph
                    size_hint_y: None
                    height: dp(210)
                Label:
                    id: event_lbl
                    text: ''
                    font_size: sp(FONT['hint'])
                    color: app.c_sub
                    size_hint_y: None
                    height: self.texture_size[1] if self.text else 0
                    text_size: self.width, None
                    halign: 'left'
                Label:
                    id: advice_lbl
                    text: ''
                    font_size: sp(FONT['hint'])
                    color: root.advice_color
                    size_hint_y: None
                    height: self.texture_size[1] if self.text else 0
                    text_size: self.width, None
                    halign: 'left'
        PillButton:
            text: root.lbl_peaks
            size_hint_y: None
            height: dp(56)
            on_release: app.reset_peaks()
        # Etapa 5: barra inferior con los 4 accesos. La píldora Menú
        # ya no está aquí: su acceso vive en la barra (sin duplicar).
        BottomNavBar:
            id: nav_bar
            section: 'monitor'

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
        GreenRule:
        ScrollView:
            id: content_scroll
            bar_width: dp(8)
            bar_color: app.c_sub
            bar_inactive_color: app.c_sep[0], app.c_sep[1], app.c_sep[2], 0.25
            scroll_type: ['bars', 'content']
            BoxLayout:
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: dp(10)
                spacing: dp(10)
                SectionCard:
                    SectionHead:
                        text: root.lbl_tower_title
                    BoxLayout:
                        id: tower_rows
                        orientation: 'vertical'
                        size_hint_y: None
                        height: self.minimum_height
                SectionCard:
                    SectionHead:
                        text: root.lbl_cells_title
                    InfoLabel:
                        id: cells_block
                        text: ''
                SectionCard:
                    SectionHead:
                        text: root.lbl_sim_title
                    BoxLayout:
                        id: sim_rows
                        orientation: 'vertical'
                        size_hint_y: None
                        height: self.minimum_height
                SectionCard:
                    SectionHead:
                        text: root.lbl_status_title
                    BoxLayout:
                        id: status_rows
                        orientation: 'vertical'
                        size_hint_y: None
                        height: self.minimum_height
        # Etapa 5: barra inferior. El envoltorio deja el mismo margen
        # de 8 dp que el padding de la raíz de Señal, así la píldora
        # flota igual en las tres pantallas.
        BoxLayout:
            size_hint_y: None
            height: dp(78)
            padding: dp(8), dp(6), dp(8), dp(8)
            BottomNavBar:
                id: nav_bar
                section: 'info'

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
        GreenRule:
        ScrollView:
            id: content_scroll
            bar_width: dp(8)
            bar_color: app.c_sub
            bar_inactive_color: app.c_sep[0], app.c_sep[1], app.c_sep[2], 0.25
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
                    SectionHead:
                        text: root.lbl_bandlock
                    HintLabel:
                        text: root.hint_bandlock
                    AutoLabel:
                        id: lock_state_lbl
                        text: root.lock_state
                        bold: True
                        markup: True
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
                    PrimaryButton:
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
                    SectionHead:
                        text: root.lbl_antenna
                    BoxLayout:
                        id: antenna_seg
                        orientation: 'horizontal'
                        size_hint_y: None
                        height: dp(42)
                        spacing: dp(3)
                    PrimaryButton:
                        text: root.lbl_apply_antenna
                        on_release: app.apply_antenna(root.antenna_selected)
                SectionCard:
                    SectionHead:
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
                    SectionHead:
                        text: root.lbl_whitelist
                    HintLabel:
                        text: root.hint_whitelist
                    PrimaryButton:
                        text: root.lbl_wl_check
                        on_release: app.whitelist_check()
                    AutoLabel:
                        text: root.wl_verdict
                        font_size: sp(FONT['value'])
                        bold: True
                        color: root.wl_color
                    AutoLabel:
                        text: root.wl_detail
                        font_size: sp(FONT['hint'])
        # Etapa 5: barra inferior (mismo envoltorio que Información).
        BoxLayout:
            size_hint_y: None
            height: dp(78)
            padding: dp(8), dp(6), dp(8), dp(8)
            BottomNavBar:
                id: nav_bar
                section: 'tools'
"""


# =========================================================
# ЭКРАНЫ
# =========================================================

class ConnectionScreen(Screen):
    subtitle = StringProperty("")
    lbl_conn_title = StringProperty("")
    lbl_ip = StringProperty("")
    lbl_pw = StringProperty("")
    lbl_find = StringProperty("")
    lbl_connect = StringProperty("")
    lbl_lang = StringProperty("")
    lbl_demo = StringProperty("")
    lbl_help = StringProperty("")
    lang_name = StringProperty("")
    lang_values = ListProperty([])
    status_color = ListProperty(hex_to_rgba(STATUS_HEX['warn']))

    def on_pre_enter(self, *args: Any) -> None:
        self.refresh_texts()

    def refresh_texts(self) -> None:
        self.subtitle = t("Портативный монитор LTE/5G Huawei")
        self.lbl_conn_title = t("Подключение")
        # Original mejorado: etiquetas de campo en mayúsculas, pequeñas y grises.
        self.lbl_ip = t("IP адрес:").upper()
        self.lbl_pw = t("Пароль:").upper()
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
        code = {v: k for k, v in LANGUAGES.items()}.get(name)
        if code and code != current_language():
            set_language(code)
            App.get_running_app().refresh_all_texts()

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
                            hex_to_rgba(STATUS_HEX['error']))
            return
        App.get_running_app().connect(ip, pw_input.text)

    def on_toggle_password(self) -> None:
        """Ojo del campo de contraseña: muestra u oculta lo escrito."""
        pw_input = self.ids.get('pw_input')
        eye = self.ids.get('eye_btn')
        if pw_input is None:
            return
        pw_input.password = not pw_input.password
        if eye is not None:
            eye.icon = 'eye_off' if not pw_input.password else 'eye'


class MonitorScreen(Screen):
    lbl_fullscreen = StringProperty("")
    lbl_peaks = StringProperty("")
    lbl_info_lte = StringProperty("")
    lbl_health = StringProperty("")
    lbl_health_note = StringProperty("")
    lbl_ca = StringProperty("")
    graph_values = ListProperty(list(LTE_PARAMS))
    advice_color = ListProperty(hex_to_rgba(STATUS_HEX['warn']))
    anchor_visible = BooleanProperty(False)
    ca_visible = BooleanProperty(False)

    def on_pre_enter(self, *args: Any) -> None:
        self.refresh_texts()
        dot = self.ids.get('live_dot')
        if dot is not None:
            dot.start()

    def on_pre_leave(self, *args: Any) -> None:
        dot = self.ids.get('live_dot')
        if dot is not None:
            dot.stop()

    def refresh_texts(self) -> None:
        self.lbl_fullscreen = t("Развернуть")
        self.lbl_peaks = t("⟲ Пики")
        self.lbl_info_lte = t("ИНФОРМАЦИЯ LTE")
        self.lbl_health = t("ЗДОРОВЬЕ СИГНАЛА")
        self.lbl_health_note = t(
            "70 % — худший параметр, 30 % — лучший, как считает приложение.")
        self.lbl_ca = t("АГРЕГАЦИЯ НЕСУЩИХ")


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
    antenna_selected = StringProperty("")
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
    wl_color = ListProperty(hex_to_rgba(STATUS_HEX['nodata']))
    net_msg = StringProperty("")
    net_msg_color = ListProperty(hex_to_rgba(STATUS_HEX['nodata']))

    def on_pre_enter(self, *args: Any) -> None:
        self.refresh_texts()
        app = App.get_running_app()
        app.build_band_checkboxes()
        app.build_antenna_seg()
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
        App.get_running_app().build_antenna_seg()
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
    c_btn_border = ListProperty(THEMES['dark']['c_btn_border'])
    c_on_accent = ListProperty(THEMES['dark']['c_on_accent'])
    c_sep = ListProperty(THEMES['dark']['c_sep'])
    c_border = ListProperty(THEMES['dark']['c_border'])
    c_nodata = ListProperty(THEMES['dark']['c_nodata'])
    c_btn_down = ListProperty(THEMES['dark']['c_btn_down'])
    c_accent_down = ListProperty(THEMES['dark']['c_accent_down'])
    sound_on = BooleanProperty(False)
    lbl_back = StringProperty("")
    lbl_nav_signal = StringProperty("")
    lbl_nav_info = StringProperty("")
    lbl_nav_tools = StringProperty("")
    lbl_nav_menu = StringProperty("")

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
        self._bands_shown: Any = []
        self._busy = False
        self._discovering = False       # идёт автопоиск роутера
        self._wl_running = False        # идёт проверка белых списков
        self._fs_graph: SignalGraph | None = None
        self._last_back = 0.0
        self._stale_warned = False   # aviso de datos obsoletos en event_lbl
        self._beep_ev: Any = None
        self.beeper = ToneBeeper()
        self.lbl_back = t("← Назад")
        self._refresh_nav_labels()
        self._ca_signature: Any = None
        self.sm: ScreenManager = Builder.load_string(KV)
        Clock.schedule_interval(self._tick, 0.5)
        return self.sm

    def on_pause(self) -> bool:
        """Свернули приложение: опрос на паузу, звук выключаем."""
        if self.worker is not None:
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
        if self.state.last is not None:
            self._render(self.state.last)
        else:
            self.refresh_graph()

    def _refresh_nav_labels(self) -> None:
        """Etiquetas de la barra inferior (Etapa 5), según el idioma."""
        self.lbl_nav_signal = t("Сигнал")
        self.lbl_nav_info = t("Информация")
        self.lbl_nav_tools = t("Сеть")
        self.lbl_nav_menu = t("Меню")

    def refresh_all_texts(self) -> None:
        self._bands_shown = []
        self.build_band_checkboxes()
        self.lbl_back = t("← Назад")
        self._refresh_nav_labels()
        for name in ('connection', 'monitor', 'info', 'tools'):
            self.sm.get_screen(name).refresh_texts()
        self._render_link_state()
        if self.state.last is not None:
            self._render(self.state.last)

    def go(self, screen: str) -> None:
        self.sm.current = screen

    def _on_keyboard(self, window: Any, key: int, *args: Any) -> bool:
        """Системная «Назад» (Esc на десктопе).

        Hardware validation required: жест «Назад» Android 13+ на устройстве.
        """
        if key != 27:
            return False
        if any(isinstance(w, ModalView) for w in window.children):
            return False            # открытый диалог закроется сам
        current = self.sm.current
        if current in ('info', 'tools'):
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
        scr.set_status(t("Ищу роутер…"), hex_to_rgba(STATUS_HEX['info']))
        candidates = ([entered] if is_valid_ip(entered) else []) + list(DISCOVERY_CANDIDATES)

        def done(found: Any) -> None:
            self._discovering = False
            if found is None:
                scr.set_status(t("Роутер не найден. Проверьте подключение к его Wi-Fi/USB."),
                               hex_to_rgba(STATUS_HEX['error']))
                return
            ip_input = scr.ids.get('ip_input')
            if ip_input is not None:
                ip_input.text = found.ip
            scr.set_status(t("Найден роутер {model} на {ip}").format(
                model=found.model or "Huawei", ip=found.ip), hex_to_rgba(STATUS_HEX['good']))
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
        self._conn_screen().set_status(t("Подключение..."), hex_to_rgba(STATUS_HEX['warn']))
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
        tools.antenna_selected = ""
        self._set_lock_state('unread')
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
        self._conn_screen().set_status("", hex_to_rgba(STATUS_HEX['nodata']))
        self.sm.current = 'connection'

    def _on_connected(self, info: dict[str, Any]) -> None:
        self.link = 'online'
        session = self.session
        if session is not None:
            self._band_list = lockable_bands(session.supported_bands, self.state.observed_bands)
        self._conn_screen().set_status("", hex_to_rgba(STATUS_HEX['nodata']))
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
        self._conn_screen().set_status(humanize_error(exc), hex_to_rgba(STATUS_HEX['error']))

    @staticmethod
    def _event_text(change: Any) -> str:
        return t("{at} смена соты: {old} → {new}").format(
            at=change.at, old=change.old_label, new=change.new_label)

    def _demo_sub(self, sub: str) -> str:
        """Subtítulo de la cabecera: en modo de prueba indica DEMO (D6)."""
        return f"{sub} · DEMO" if self.demo_modem is not None else sub

    def _render_link_state(self, detail: str = "") -> None:
        scr = self.sm.get_screen('monitor')
        sun = self.theme_name == 'sun'
        live = scr.ids.get('live_lbl')
        if self.link == 'reconnecting':
            if live is not None:
                live.text = t("Нет связи с роутером — переподключаюсь…")
                live.color = hex_to_rgba(STATUS_HEX['warn'], sun)
            ev = scr.ids.get('event_lbl')
            if detail and ev is not None:
                ev.text = detail
                # Aviso: ámbar, no el gris normal de los eventos (D7).
                ev.color = hex_to_rgba(STATUS_HEX['warn'], sun)
        elif self.demo_modem is not None and live is not None:
            live.text = t(
                "Тестовый режим · демонстрационные данные").upper()
            live.color = self.c_sub

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
                ev.color = self.c_sub
        elif self._stale_warned:
            # Llegaron datos frescos: se quita el aviso de obsoletos (D7).
            ev = scr.ids.get('event_lbl')
            if ev is not None:
                ev.text = ""
                ev.color = self.c_sub
            self._stale_warned = False
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
            # La pantalla Señal no tiene línea de estado: el aviso de
            # datos obsoletos sale en la línea de eventos.
            ev = scr.ids.get('event_lbl')
            if ev is not None:
                ev.text = t("⚠ Данные устарели — нет ответа {s:.0f} с").format(
                    s=self.state.age(now) or 0)
                # En rojo: que se distinga de un aviso normal (D7).
                ev.color = hex_to_rgba(STATUS_HEX['error'], self.theme_name == 'sun')
                self._stale_warned = True
            self.refresh_graph(stale=True)

    def _anchor_text(self, snap: Snapshot) -> str:
        """'LTE 1800+2100' — frecuencias nominales de los bándos activos.

        Vacío si el router no da bándos: la línea de ancla no se muestra.
        """
        bands = snap.bands or tuple(c.band for c in snap.lte_carriers)
        names = [name for name in (_band_freq_name(b) for b in bands) if name]
        return f"LTE {'+'.join(names)}" if names else ""

    def _render_ca(self, ids: Any, snap: Snapshot) -> None:
        """Sección CARRIER AGGREGATION: una fila por portadora real.

        Sin portadoras (snap.lte_carriers vacío) la sección no se muestra:
        no se inventa. Las filas se reconstruyen solo si cambian las
        portadoras o el idioma.
        """
        from kivy.factory import Factory
        scr = self.sm.get_screen('monitor')
        carriers = snap.lte_carriers
        scr.ca_visible = bool(carriers)
        if not carriers:
            self._ca_signature = None
            return
        sig = (current_language(),
               tuple((c.band, c.earfcn, c.bandwidth) for c in carriers))
        if sig == self._ca_signature:
            return
        self._ca_signature = sig
        rows = ids.ca_rows
        rows.clear_widgets()
        total = 0.0
        for i, c in enumerate(carriers):
            freq = _band_freq_name(c.band)
            band = f"B{c.band}" + (f" · {freq} {t('МГц')}" if freq else "")
            # Las propiedades de la regla KV solo existen tras construir
            # el widget: se asignan después, no como kwargs del constructor.
            row = Factory.CaRow()
            row.tag = 'PCC' if i == 0 else 'SCC'
            row.band = band
            row.earfcn = f"EARFCN {c.earfcn}"
            row.bw = f"{c.bandwidth:g} {t('МГц')}"
            row.bw_label = t("Ширина полосы")
            rows.add_widget(row)
            total += c.bandwidth
        n = len(carriers)
        ids.ca_count_lbl.text = (t("1 несущая активна") if n == 1
                                 else t("{n} несущих активны").format(n=n))
        ids.ca_total_lbl.text = f"{t('Всего')} [b]{total:g} {t('МГц')}[/b]"

    def _render(self, snap: Snapshot) -> None:
        # Pestaña Señal estilo «Original mejorado»: cabecera del operador,
        # INFORMACIÓN LTE en dos columnas, barras de NIVEL DE SEÑAL,
        # SALUD DE SEÑAL con segmentos y CARRIER AGGREGATION. Todos los
        # datos salen del Snapshot; lo que falta se muestra como '—'.
        snap = snap.display()
        scr = self.sm.get_screen('monitor')
        ids = scr.ids
        if not ids:
            return
        sun = self.theme_name == 'sun'
        # --- Cabecera del operador ---
        if snap.registered:
            operator = snap.operator or t("Оператор неизвестен")
            ids.op_name_lbl.text = operator
            ids.plmn_lbl.text = _format_plmn(snap.plmn)
            ids.tech_chip_lbl.text = _tech_chip(snap.rat)
            ids.tech_chip_lbl.opacity = 1 if snap.rat else 0
            ids.op_sub_lbl.text = self._demo_sub(_operator_sub(snap.plmn))
        else:
            ids.op_name_lbl.text = t(snap.network_message)
            ids.plmn_lbl.text = "—"
            ids.tech_chip_lbl.text = ""
            ids.tech_chip_lbl.opacity = 0
            ids.op_sub_lbl.text = self._demo_sub(t("Оператор"))
        # --- Línea de ancla ---
        anchor = self._anchor_text(snap)
        scr.anchor_visible = bool(anchor)
        if anchor:
            accent = '#{:02x}{:02x}{:02x}'.format(
                *(int(v * 255) for v in self.c_accent[:3]))
            ids.anchor_lbl.text = (
                f"{t('Якорь')} [b][color={accent}]{anchor}[/color][/b]")
        # --- Fila en vivo (o DEMO en modo de prueba) ---
        live = ids.get('live_lbl')
        if live is not None:
            if self.demo_modem is not None:
                live.text = t("Тестовый режим · демонстрационные данные").upper()
            else:
                live.text = t("В эфире · обновление каждую секунду").upper()
            live.color = self.c_sub
        # --- Tarjetas de métricas (SINR/RSRP/RSRQ/RSSI) ---
        for param in ('sinr', 'rsrp', 'rsrq', 'rssi'):
            card = ids.get(f'{param}_card')
            if card is None:
                continue
            val = getattr(snap, param)
            label, color, _pct = evaluate_signal(param, val)
            lo, hi = _METRIC_RANGES[param]
            card.m_pct = (0.0 if val is None
                          else max(0.0, min(100.0, (val - lo) / (hi - lo) * 100)))
            card.m_value = '—' if val is None else f"{fmt_num(val)} {unit_of(param)}"
            card.m_status = f"● {t(label)}"
            card.m_color = hex_to_rgba(skin_hex(color), sun)
            peak = self.state.peaks.get(param)
            card.m_peak = t("пик {v}").format(
                v='—' if peak is None else fmt_num(peak))
        # --- INFORMACIÓN LTE ---
        ids.ci_row.value = _dash_num(snap.cell_id)
        ids.enb_row.value = ("—" if snap.enodeb is None or snap.sector is None
                             else f"{fmt_num(snap.enodeb)}:{fmt_num(snap.sector)}")
        ids.tac_row.value = snap.tac or "—"
        ids.pci_row.value = _dash_num(snap.pci)
        ids.earfcn_row.value = _dash_num(snap.earfcn)
        ids.banda_row.value = _primary_band_label(snap)
        ids.ancho_row.value = snap.dl_bandwidth or "—"
        ids.modo_row.value = _primary_band_duplex(snap)
        # --- SALUD DE SEÑAL ---
        score, summary, color = calculate_overall_health(snap.rsrp, snap.sinr)
        if not snap.registered:
            score, summary, color = 0, snap.network_message, 'gray'
        ring = ids.health_ring
        ring.pct = score
        ring.pct_text = f"{score}%"
        ring.ring_color = hex_to_rgba(skin_hex(color), sun)
        # El resumen trae ' ({pct}%)' al final; el porcentaje ya va en grande.
        ids.health_lbl.text = (t(summary).split(" ({")[0] if snap.registered
                               else t(summary))
        segs = list(reversed(ids.segbar.children))
        lit = round(score / 100 * len(segs))
        seg_color = hex_to_rgba(skin_hex(color), sun)
        for i, seg in enumerate(segs):
            seg.lit = i < lit
            seg.lit_color = seg_color
        self._sync_graph_seg()
        # --- CARRIER AGGREGATION ---
        self._render_ca(ids, snap)
        # --- Consejos y gráfico ---
        mimo = mimo_status(snap.cqi0, snap.cqi1)
        up = uplink_status(snap.pusch_dbm)
        tips = advice(rsrp=snap.rsrp, sinr=snap.sinr, rsrq=snap.rsrq,
                      jitter=self.state.jitter(), mimo=mimo, uplink=up)
        if not snap.registered:
            tips = []
        elif snap.connection != 901 or snap.data_enabled is False:
            tips.insert(0, snap.network_message)
        ids.advice_lbl.text = "\n".join("• " + t(tip) for tip in tips[:2])
        scr.advice_color = hex_to_rgba(STATUS_HEX['warn'], sun)
        self.refresh_graph()
        if self.sm.current == 'info':
            self.refresh_info_screen()

    def set_graph_param(self, param: str) -> None:
        self.state.set_trend_param(param)
        if self.state.last is not None:
            self._render(self.state.last)
        else:
            self.refresh_graph()

    def _sync_graph_seg(self) -> None:
        """Control segmentado del gráfico: un botón por parámetro.

        Con 4 parámetros (LTE) va en una fila junto a «Ampliar», como
        en el preview; con NR (7) ocupa dos filas (LTE arriba, NR
        abajo) y «Ampliar» baja a su propia fila. Se reconstruye solo
        si cambia la lista, el parámetro activo o el idioma.
        """
        from kivy.factory import Factory
        from kivy.uix.boxlayout import BoxLayout
        scr = self.sm.get_screen('monitor')
        box = scr.ids.get('graph_controls')
        if box is None:
            return
        sig = (tuple(scr.graph_values), self.state.trend_param,
               scr.lbl_fullscreen)
        if sig == getattr(self, '_graph_seg_sig', None):
            return
        self._graph_seg_sig = sig
        box.clear_widgets()
        values = list(scr.graph_values)
        wide = len(values) > 4
        # Las propiedades de la regla KV solo existen tras construir
        # el widget: se asignan después, no como kwargs del constructor.
        def make_seg(param: str, size: float) -> object:
            btn = Factory.SegButton(
                text=param.upper(), group='graph_param',
                font_size=sp(size))
            btn.param = param
            btn.bind(on_release=lambda _b, p=param: self.set_graph_param(p))
            if param == self.state.trend_param:
                btn.state = 'down'
            return btn
        expand = Factory.FlatButton(text=scr.lbl_fullscreen,
                                    font_size=sp(FONT['body']))
        expand.bind(on_release=lambda *a: self.open_fullscreen_graph())
        if wide:
            # Etapa 6: los 7 botones en una fila cortaban las etiquetas
            # NR (57-62 px de textura en botones de 46 dp a 360 dp, y
            # también a 412 dp): filas de 4, que caben hasta en 320 dp.
            for start in range(0, len(values), 4):
                seg = BoxLayout(orientation='horizontal', size_hint_y=None,
                                height=dp(42), spacing=dp(3))
                for param in values[start:start + 4]:
                    seg.add_widget(make_seg(param, FONT['label']))
                box.add_widget(seg)
            expand.size_hint_y = None
            expand.height = dp(42)
            box.add_widget(expand)
        else:
            seg = BoxLayout(orientation='horizontal', size_hint_y=None,
                            height=dp(42), spacing=dp(3))
            for param in values:
                seg.add_widget(make_seg(param, FONT['hint']))
            row = BoxLayout(orientation='horizontal', size_hint_y=None,
                            height=dp(42), spacing=dp(6))
            row.add_widget(seg)
            expand.size_hint_x = None
            expand.width = dp(110)
            row.add_widget(expand)
            box.add_widget(row)

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

    def _style_popup(self, popup: Popup) -> Popup:
        """Popup con el lenguaje Original mejorado: fondo de tarjeta,
        título en blanco y separador verde (como la línea del encabezado)."""
        popup.background_color = self.c_card
        popup.title_color = self.c_text
        popup.separator_color = self.c_accent
        return popup

    def open_survey(self) -> None:
        from kivy.core.text import Label as CoreLabel
        from kivy.core.window import Window
        from kivy.factory import Factory
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.textinput import TextInput
        box = BoxLayout(orientation='vertical', spacing=dp(6), padding=dp(6))
        # Etapa 6: en ventanas estrechas o con la fuente grande, los
        # botones «Buscar operadores» / «Copiar resultado» no caben de
        # dos en dos (140 px de texto en botones de 134 dp a 320 dp):
        # esa pareja se apila en vertical. Se mide con la fuente real
        # del botón (la regla KV fija 16 sp, no los 15 sp del kwarg).
        content_w = Window.width * 0.97 - dp(24) - dp(12)
        pair_w = (content_w - dp(6)) / 2
        for items in (((t('Старт'), self._start_survey), (t('Стоп'), self._stop_survey)),
                      ((t('Поиск операторов'), self._search_survey),
                       (t('Копировать результат'), self._copy_survey))):
            buttons = []
            for title, action in items:
                button = Factory.FlatButton(text=title, font_size=sp(FONT['body']))
                button.bind(on_release=lambda _b, fn=action: fn())
                buttons.append(button)
            widest = 0.0
            for button in buttons:
                probe = CoreLabel(text=button.text, font_size=button.font_size,
                                  font_name=button.font_name, bold=button.bold)
                probe.refresh()
                widest = max(widest, probe.texture.width)
            if widest > pair_w - dp(4):
                for button in buttons:
                    button.size_hint_y = None
                    button.height = dp(48)
                    box.add_widget(button)
            else:
                bar = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
                for button in buttons:
                    bar.add_widget(button)
                box.add_widget(bar)
        # Campo de informe con la piel del tema (antes fondo blanco con
        # texto oscuro, estilo por defecto de Kivy sin tematizar).
        self._survey_text = TextInput(
            readonly=True, font_size=sp(FONT['body']), multiline=True,
            background_color=self.c_card, foreground_color=self.c_text,
            cursor_color=self.c_accent)
        box.add_widget(self._survey_text)
        popup = self._style_popup(Popup(title=t('Сканер наблюдений · Beta'),
                                        content=box, size_hint=(0.97, 0.95)))
        close = Factory.FlatButton(text=t('← Назад'), size_hint_y=None, height=dp(46))
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

    def open_menu(self) -> None:
        from kivy.animation import Animation
        from kivy.core.window import Window
        from kivy.factory import Factory
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        sun = self.theme_name == 'sun'
        box = BoxLayout(orientation='vertical', spacing=dp(2), padding=dp(10))
        box.add_widget(Factory.SheetGrip())
        title = Label(text=t("Меню"), font_size=sp(FONT['title']), bold=True,
                      color=self.c_text, size_hint_y=None, height=dp(36),
                      halign='left', valign='middle')
        title.bind(size=lambda i, v: setattr(i, 'text_size', v))
        box.add_widget(title)
        box.add_widget(Factory.GreenRule())
        # Etapa 6: en ventanas bajas (horizontal, 360 dp de alto) la
        # hoja de 374 dp no cabe y el asa quedaba cortada arriba: la
        # hoja se acorta y los ítems se compactan para que quepan los
        # 5. En vertical no cambia nada (374 dp, ítems de 58 dp).
        sheet_h = min(dp(374), Window.height - dp(16))
        popup = self._style_popup(Popup(title='', separator_height=0, content=box,
                                        size_hint=(1, None), height=sheet_h))
        # (icono, nombre, descripción, acción, peligro): los nombres ya no
        # llevan glifos de texto (D2/D5); el tema nombra la acción.
        items = [
            ('info', t("Информация"),
             t("Станция, SIM, устройство и состояние"),
             lambda: self.go('info'), False),
            ('radar', t("Сканер наблюдений"),
             t("Beta · наблюдайте соты, поворачивая антенну"),
             self.open_survey, False),
            ('gear', t("Сеть"), t("Бэнды, антенна и управление роутером"),
             lambda: self.go('tools'), False),
            ('sun', t("Вернуться к тёмной теме") if sun else t("Включить солнце"),
             t("Тёмная тема: чёрный фон и зелёный акцент") if sun
             else t("Светлая тема для чтения под прямым солнцем"),
             lambda: self.apply_theme('dark' if sun else 'sun'), False),
            ('power', t("Отключиться"), t("Закрыть сессию с роутером"),
             self.confirm_disconnect, True),
        ]
        item_h = dp(58)
        if sheet_h < dp(374):
            # Fijos de la hoja: padding 20 + asa 12 + título 36 +
            # regla 2 + separaciones 14 = 84 dp, más 4 huecos de 2 dp
            # entre los 5 ítems: el resto se reparte entre los ítems.
            item_h = max(dp(40), (sheet_h - dp(92)) / 5)
        for icon, name, desc, action, danger in items:
            item = Factory.MenuItem()
            item.height = item_h
            item.icon = icon
            item.name = name
            item.desc = desc
            item.danger = danger
            item.bind(on_release=lambda _b, a=action: (popup.dismiss(), a()))
            box.add_widget(item)
        popup.open()
        # ModalView centra el popup al abrirlo y lo recentra al cambiar
        # tamaño/centro: se desvincula y se deja abajo como hoja inferior.
        Window.unbind(on_resize=popup._align_center)
        popup.funbind('center', popup._align_center)
        popup.funbind('size', popup._align_center)
        popup.y = -popup.height
        Animation(y=0, d=0.25, t='out_quad').start(popup)

    def confirm(self, title: str, message: str, yes_text: str,
                on_yes: Callable[[], None]) -> None:
        from kivy.factory import Factory
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        content = BoxLayout(orientation='vertical', spacing=dp(10), padding=dp(10))
        msg = Label(text=message, halign='center', valign='middle', font_size=sp(FONT['body']))
        msg.bind(size=lambda i, v: setattr(i, 'text_size', v))
        content.add_widget(msg)
        btns = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(10))
        popup = self._style_popup(Popup(title=title, content=content,
                                        size_hint=(0.92, 0.55)))
        no = Factory.FlatButton(text=t("← Назад"), font_size=sp(FONT['value']), size_hint_x=1)
        yes = Factory.PrimaryButton(text=yes_text, font_size=sp(FONT['value']), size_hint_x=1)
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
        from kivy.factory import Factory
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.scrollview import ScrollView
        box = BoxLayout(orientation='vertical', spacing=dp(6), padding=dp(6))
        lbl = Label(text=message, halign='left', valign='top', size_hint_y=None,
                    font_size=sp(FONT['body']))
        lbl.bind(width=lambda i, w: setattr(i, 'text_size', (w, None)),
                 texture_size=lambda i, ts: setattr(i, 'height', ts[1]))
        sv = ScrollView(bar_color=self.c_sub,
                        bar_inactive_color=[*self.c_sep[:3], 0.25])
        sv.add_widget(lbl)
        box.add_widget(sv)
        back = Factory.FlatButton(text=t("← Назад"), size_hint_y=None, height=dp(48))
        box.add_widget(back)
        # 0,85 de alto: el texto de Ayuda mide ~459 px y con 0,8 el viewport
        # quedaba en 451 px, así que la última línea se cortaba 8 px.
        popup = self._style_popup(Popup(title=title, content=box,
                                        size_hint=(0.92, 0.85)))
        back.bind(on_release=lambda *a: popup.dismiss())
        popup.open()

    def toast(self, text: str, seconds: float = 2.0) -> None:
        # Aviso flotante: texto blanco sobre velo negro, igual en los dos
        # temas a propósito (en sol, el texto del tema sería negro sobre
        # negro y no se leería). No es un color suelto: es el toast.
        from kivy.core.window import Window
        from kivy.graphics import Color, RoundedRectangle
        from kivy.uix.label import Label
        lbl = Label(text=text, font_size=sp(FONT['body']), size_hint=(None, None), color=(1, 1, 1, 1))
        lbl.texture_update()
        lbl.size = (lbl.texture_size[0] + dp(24), lbl.texture_size[1] + dp(16))
        lbl.pos = ((Window.width - lbl.width) / 2, dp(80))
        with lbl.canvas.before:
            Color(0, 0, 0, 0.8)
            RoundedRectangle(pos=lbl.pos, size=lbl.size, radius=[dp(RADIUS['button'])])
        Window.add_widget(lbl)
        Clock.schedule_once(lambda dt: Window.remove_widget(lbl), seconds)

    def open_fullscreen_graph(self) -> None:
        from kivy.factory import Factory
        from kivy.uix.boxlayout import BoxLayout
        inner = BoxLayout(orientation='vertical', spacing=dp(6), padding=dp(8))
        graph = PinchGraph()
        close = Factory.FlatButton(text=t("← Назад"), size_hint_y=None, height=dp(48))
        inner.add_widget(graph)
        controls = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(4))
        auto = Factory.FlatButton(text=t("Авто"), font_size=sp(FONT['body']))
        auto.bind(on_release=lambda *a: graph.auto())
        controls.add_widget(auto)
        controls.add_widget(close)
        inner.add_widget(controls)
        self._fs_graph = graph
        param = self.state.trend_param
        popup = self._style_popup(Popup(
            title=f"{PARAM_TITLES[param]} ({unit_of(param)})",
            content=RotatedBox(inner), size_hint=(0.98, 0.96)))
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

        def row(name: str, value: Any) -> tuple[str, str, bool]:
            # (etiqueta, valor, es_sin_datos): el valor va sin markup
            # (InfoRow no usa markup) y en gris cuando no hay datos.
            if value in (None, '', '-'):
                return t(name), nd, True
            return t(name), str(value), False

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
            row('ID соты (ECI)', snap.cell_id),
            row('eNodeB (Вышка)', fmt_num(snap.enodeb) if snap.enodeb is not None else
                (f"NCI {snap.nci}" if snap.nci else None)),
            row('Cell (Локальный сектор)', fmt_num(snap.sector)),
            row('TAC (зона)', snap.tac),
            row('Сеть 5G NR', nr),
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
            ('Imei', 'IMEI (роутер)'), ('Imsi', 'IMSI (SIM-карта)'), ('Iccid', 'ICCID (SIM-карта)'),
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
            row('Схема MIMO', snap.mimo_matrix or None),
            row('Ранг MIMO LTE', t('Нет подтверждённых данных')),
            row('Ранг MIMO NR', format_rank(snap.nr_rank)),
            row('CQI кодовых слов', cqi),
            row('Мощность передатчика', tx),
            row('Состояние RRC', snap.rrc),
            row('RSRP мин / макс', minmax('rsrp')),
            row('SINR мин / макс', minmax('sinr')),
        ]
        self._fill_info_rows(ids['tower_rows'], tower)
        ids['cells_block'].text = "\n".join(cells or [nd])
        self._fill_info_rows(ids['sim_rows'], sim)
        self._fill_info_rows(ids['status_rows'], status)

    def _fill_info_rows(self, box: Any,
                        rows: list[tuple[str, str, bool]]) -> None:
        """Rellena una tarjeta de Información con filas InfoRow.

        Cada fila es (etiqueta, valor, es_sin_datos), separadas por
        SepLine; el valor sin datos va en gris (c_nodata).
        """
        from kivy.factory import Factory
        box.clear_widgets()
        for i, (label, value, nodata) in enumerate(rows):
            if i:
                box.add_widget(Factory.SepLine())
            item = Factory.InfoRow()
            item.row_key = label
            item.row_value = value
            item.row_nodata = nodata
            box.add_widget(item)

    # ---------- экран «Сеть» ----------

    def _tools(self) -> ToolsScreen:
        return self.sm.get_screen('tools')

    def _net_msg(self, text: str, color: str) -> None:
        tools = self._tools()
        tools.net_msg = text
        tools.net_msg_color = hex_to_rgba(skin_hex(color), self.theme_name == 'sun')

    def build_band_checkboxes(self) -> None:
        grid = self._tools().ids.get('bands_grid')
        shown = (list(self._band_list), frozenset(self.state.observed_bands))
        if grid is None or self._bands_shown == shown:
            return
        from kivy.factory import Factory
        checked = {b for b, cb in self.band_vars.items() if cb.active}
        grid.clear_widgets()
        self.band_vars = {}
        for band in self._band_list:
            card = Factory.BandCard()
            card.band = band
            card.name = f"B{band}"
            card.sub = self._band_card_sub(band)
            cb = card.ids.cb
            # El estado visual de la tarjeta espeja la casilla.
            cb.bind(active=lambda _i, v, c=card: setattr(c, 'active', v))
            cb.active = band in checked
            grid.add_widget(card)
            self.band_vars[band] = cb
        self._bands_shown = shown

    def _band_card_sub(self, band: int) -> str:
        """Subtítulo de la tarjeta de banda: frecuencia, TDD y si está en el aire."""
        freq = _band_freq_name(band)
        parts = []
        if freq:
            parts.append(f"{freq} {t('МГц')}")
        info = LTE_BAND_TABLE.get(band)
        if info and info[1] == 'TDD':
            parts.append('TDD')
        if band in self.state.observed_bands:
            parts.append(t("в эфире"))
        return " · ".join(parts)

    def _set_lock_state(self, kind: str, bands: str = "") -> None:
        """Línea «Ahora en el módem:» con el valor en negrita y acento.

        kind: 'unread' (valor en gris), 'auto' o 'locked' (en verde).
        """
        tools = self._tools()
        prefix = escape_markup(t("Сейчас на модеме:"))
        accent = '#{:02x}{:02x}{:02x}'.format(
            *(int(v * 255) for v in self.c_accent[:3]))
        if kind == 'unread':
            gray = '#{:02x}{:02x}{:02x}'.format(
                *(int(v * 255) for v in self.c_sub[:3]))
            value = f"[color={gray}]{escape_markup(t('не прочитано'))}[/color]"
        elif kind == 'auto':
            value = (f"[b][color={accent}]"
                     f"{escape_markup(t('AUTO (все бэнды)'))}[/color][/b]")
        else:
            value = f"[b][color={accent}]{escape_markup(bands)}[/color][/b]"
        tools.lock_state = f"{prefix} {value}"

    def build_antenna_seg(self) -> None:
        """Control segmentado de antena: un botón por modo.

        Se reconstruye al cambiar el idioma o el modo leído; sin modo
        leído no hay botón activo (Aplicar avisa, como antes).
        """
        from kivy.factory import Factory
        tools = self._tools()
        box = tools.ids.get('antenna_seg')
        if box is None:
            return
        labels = [t(k) for k in ANTENNA_MODES]
        sig = (tuple(labels), tools.antenna_selected)
        if sig == getattr(self, '_antenna_seg_sig', None):
            return
        self._antenna_seg_sig = sig
        box.clear_widgets()
        for label in labels:
            btn = Factory.SegButton(text=label, group='antenna',
                                    font_size=sp(FONT['hint']))
            btn.param = label
            btn.bind(on_release=lambda _b, lab=label: self._select_antenna(lab))
            if label == tools.antenna_selected:
                btn.state = 'down'
            box.add_widget(btn)

    def _select_antenna(self, label: str) -> None:
        self._tools().antenna_selected = label
        self.build_antenna_seg()

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
            self._net_msg(t("Сначала подключитесь к роутеру."), STATUS_HEX['error'])
            return
        if self._busy:
            return
        self._busy = True
        self._net_msg(busy_text, STATUS_HEX['info'])
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
                err=humanize_error(exc)), STATUS_HEX['error'])
        self._run_bg(work, finish, failed)

    def load_router_config(self) -> None:
        """Читает текущий Band Lock и антенну (только чтение)."""
        session = self.session
        if session is None:
            return
        self._tools().antenna_text = t("Не прочитано")
        for cb in self.band_vars.values():
            cb.active = False
        # Пока не прочитано — не показываем состояние прошлой сессии.
        self._set_lock_state('unread')

        def done(cfg: Any) -> None:
            if session is not self.session:
                return
            tools = self._tools()
            if cfg.locked is None:
                self._set_lock_state('unread')
            elif not cfg.locked:
                self._set_lock_state('auto')
                for cb in self.band_vars.values():
                    cb.active = False
            else:
                self._set_lock_state(
                    'locked', ", ".join(f"B{b}" for b in cfg.locked))
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
                        tools.antenna_selected = t(label)
                        self.build_antenna_seg()

        def failed(_exc: BaseException) -> None:
            if session is self.session:
                self._set_lock_state('unread')
        self._run_bg(session.read_config, done, failed)

    def mark_current_bands(self) -> None:
        snap = self.state.last
        if (self.link != 'online' or snap is None or not snap.registered
                or self.state.is_stale(time.monotonic(), self.interval)):
            self._net_msg(t("Текущий бэнд ещё не определён."), STATUS_HEX['error'])
            return
        bands = [b for b in snap.bands if 1 <= b <= 63 and b in self.band_vars]
        if not bands:
            self._net_msg(t("Текущий бэнд ещё не определён."), STATUS_HEX['error'])
            return
        for b, cb in self.band_vars.items():
            cb.active = b in bands
        self._net_msg(t("Отмечены текущие бэнды: {bands}").format(
            bands=", ".join(f"B{b}" for b in bands)), STATUS_HEX['info'])

    def apply_bands(self) -> None:
        session = self.session
        selected = [b for b, cb in self.band_vars.items() if cb.active]
        if session is None or self.link != 'online':
            self._net_msg(t("Сначала подключитесь к роутеру."), STATUS_HEX['error'])
            return
        if not selected:
            self._net_msg(t("Выберите хотя бы один диапазон!"), STATUS_HEX['error'])
            return
        names = ", ".join(f"B{b}" for b in selected)
        lines = [t("Зафиксировать бэнды: {bands}?").format(bands=names)]
        lines += lock_warnings(selected, self.state.last)
        def confirm_plan(plan):
            lines.append(t("Режим сети после записи: {mode}").format(mode=plan.networkmode))

            def apply():
                if self.session is session:
                    self._net_action(lambda: session.apply_plan(plan),
                                     lambda ok: self._after_write(ok, t("Band Lock применён: {bands}.").format(bands=names)),
                                     t("Применяю Band Lock…"))

            self.confirm(t("Подтверждение"), "\n\n".join(lines), t("Применить"), apply)

        self._net_action(lambda: session.plan_band_lock(selected), confirm_plan, t("Чтение настроек сети…"))

    def reset_bands(self) -> None:
        session = self.session
        if session is None:
            self._net_msg(t("Сначала подключитесь к роутеру."), STATUS_HEX['error'])
            return
        self._net_action(lambda: session.apply_plan(session.plan_all_bands()),
                         lambda ok: self._after_write(ok, t("Включены все бэнды (AUTO).")),
                         t("Включаю все бэнды…"))

    def restore_bands(self) -> None:
        session = self.session
        if session is None:
            self._net_msg(t("Сначала подключитесь к роутеру."), STATUS_HEX['error'])
            return
        plan = session.plan_restore_original()
        if plan is None:
            self._net_msg(t("Исходные настройки не прочитаны — роутер не отдал net-mode."),
                          STATUS_HEX['error'])
            return
        self._net_action(lambda: session.apply_plan(plan),
                         lambda ok: self._after_write(ok, t(
                             "Восстановлены настройки, прочитанные при подключении.")),
                         t("Восстанавливаю настройки…"))

    def _after_write(self, verified: bool, success_text: str) -> None:
        if verified:
            self._net_msg(success_text + " " + t(
                "Модем перерегистрируется в сети (до ~30 с)."), STATUS_HEX['good'])
        else:
            self._net_msg(t("Команда отправлена, но роутер не подтвердил запись — "
                            "проверьте строку «Сейчас на модеме»."), STATUS_HEX['warn'])
        self.load_router_config()

    def apply_antenna(self, label: str) -> None:
        session = self.session
        rev = {t(k): k for k in ANTENNA_MODES}
        code = parse_antenna_value(rev.get(label, label))
        if session is None:
            self._net_msg(t("Сначала подключитесь к роутеру."), STATUS_HEX['error'])
            return
        if code is None:
            self._net_msg(t("Неизвестный режим антенны."), STATUS_HEX['error'])
            return

        def work() -> int | None:
            return session.apply_antenna(code)

        def done(read_back: int | None) -> None:
            if read_back == code:
                self._net_msg(t("Тип антенны изменён: {mode}").format(mode=label), STATUS_HEX['good'])
            elif read_back is None:
                self._net_msg(t("Команда отправлена, но режим антенны не подтверждён."), STATUS_HEX['warn'])
            else:
                self._net_msg(t("Роутер принял команду, но сообщает другой режим антенны."),
                              STATUS_HEX['warn'])
        self._net_action(work, done, t("Переключаю антенну…"))

    def confirm_reattach(self) -> None:
        session = self.session
        if session is None:
            self._net_msg(t("Сначала подключитесь к роутеру."), STATUS_HEX['error'])
            return

        def done(ok: bool) -> None:
            if ok:
                self._net_msg(t("Связь переподключена."), STATUS_HEX['good'])
            else:
                self._net_msg(t("Не удалось включить мобильные данные — включите их в "
                                "веб-интерфейсе роутера."), STATUS_HEX['error'])
        self.confirm(t("Подтверждение"), t(
            "Переподключить мобильную связь?\n\nМобильные данные будут выключены и включены. Интернет временно пропадёт (обычно на 5–10 секунд). Смена соты и улучшение сигнала не гарантируются."), t("Переподключить"),
            lambda: self._net_action(session.reattach, done, t("Переподключаю связь…")))

    def confirm_reboot(self) -> None:
        session, worker = self.session, self.worker
        if session is None or worker is None:
            self._net_msg(t("Сначала подключитесь к роутеру."), STATUS_HEX['error'])
            return

        def done(_: Any) -> None:
            self._net_msg(t("Роутер перезагружается — переподключусь автоматически."),
                          STATUS_HEX['info'])
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
            self._net_msg(t("Сначала подключитесь к роутеру."), STATUS_HEX['error'])
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
                            "замаскированы."), STATUS_HEX['good'])
        self._net_action(work, done, t("Собираю диагностику…"))

    def whitelist_check(self) -> None:
        if self._wl_running:
            return                      # проверка уже идёт
        self._wl_running = True
        token = self._wl_token = object()
        session = self.session
        tools = self._tools()
        tools.wl_verdict = t("Проверка…")
        tools.wl_color = hex_to_rgba(STATUS_HEX['warn'], self.theme_name == 'sun')
        tools.wl_detail = t("Проверка занимает несколько секунд.")

        def done(report: Any) -> None:
            if session is not self.session or token is not self._wl_token:
                return
            self._wl_running = False
            tools.wl_verdict = report.title
            tools.wl_color = hex_to_rgba(skin_hex(report.color), self.theme_name == 'sun')
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
