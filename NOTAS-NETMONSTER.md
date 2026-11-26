# Rediseño estilo NetMonster (Opción C) — Hua4GMon 1.5.0

Rama local: `netmonster-ui` (desde `043492e`). No hay push, PR ni APK
todavía: la compilación se hace con el CI del proyecto (GitHub Actions),
como siempre. Todo el texto nuevo está en español con claves i18n en
ES/EN/RU (366 claves, mismos conjuntos en los tres idiomas).

## Qué se cambió

### En vivo (Monitor) — estilo captura CUBACEL 4G
- Fondo oscuro degradado verde-negro, operador en grande con subrayado
  verde, PLMN (`368 01`) arriba a la derecha.
- Línea con ancla: `4G | LTE 1800 + 1800` (o `3G | 900`, `5G NSA | NR n78`).
- Cuadrícula de dos columnas: izquierda CI, eNb:CID, TAC, PCI (en 3G:
  CI, CID, RNC, LAC, PSC); derecha EARFCN, RSSI, RSRP, RSRQ, SNR, CQI —
  con flechas de tendencia ▲/▼ según las dos últimas muestras.
- Barras por métrica (RSRP, SINR, RSRQ, RSSI, CQI y NR RSRP/SINR con 5G)
  con color, valor, porcentaje y una explicación corta de qué significa.
- Desglose de agregación de portadoras (CA) por portadora: banda, EARFCN,
  ancho de banda. Botones Herramientas y Bloqueo de bandas.
- Se conservan salud general, gráfico de señal, consejos y los botones
  de sonido/picos/menú que ya existían.

### Gráficos
- Cabecera operador + RAT + identidad + chip de banda.
- Tarjetas en 2 columnas (RSSI, RSRP, RSRQ, SNR, NR RSRP, NR SINR) con
  punto de color por calidad, minigráfico con área rellena y línea de
  umbral punteada (verde/amarillo/rojo según calidad).

### Registro (Celdas)
- Lista HOY estilo NetMonster: chip de tecnología (2G/3G/4G/5G),
  identidad (`eNb:CID | TAC | PCI` en 4G, `RNC:CID | LAC | PSC` en 3G),
  operador y hora, chip de banda, número de mediciones. Botón Filtros
  (todas → 4G → 3G → 5G → por banda observada, p. ej. B3, n78).
- **Registro detallado por banda** (nuevo): por cada banda/celda, primera
  y última vez, duración, muestras, EARFCN, eNb:CID, TAC, PCI y
  RSRP/SINR/RSRQ/RSSI como mediana [mín … máx]. Botón Exportar CSV
  (copia el CSV detallado al portapapeles; mismo formato `;` y coma
  decimal que el resto de la app en español).
- Tocar una fila abre el **detalle de celda**: secciones IDENTIDAD,
  CANAL y OPERADOR (y SEÑAL) con encabezados verdes, valores grandes y
  botón Copiar por fila.

### Bloqueo de bandas (hoja inferior)
- Título con trazo verde, pestañas Recientes / Rutinas, lista de
  bloqueos recientes (`4G B3 | 1800`, `B8 | 900`…), Crear un nuevo
  bloqueo y Desbloquear todo. Reaplica bloqueos recientes y usa el
  Band Lock por API del router, como antes. Rutinas aún no existe.

### Mapa
- Explica que el router no entrega GPS y lista las celdas observadas
  sin coordenadas. No se inventan ubicaciones.

### Ajustes (nueva pantalla, estilo NetMonster)
- Flecha atrás, título grande, sección PREFERENCIAS en verde, filas con
  icono verde en cuadrado oscuro.
- **Monitorización en segundo plano** (interruptor): con él activado
  (por defecto) el worker sigue sondeando al minimizar la app; con él
  apagado, al minimizar se pausa el sondeo y se reanuda al volver.
- **General**: abre Información (datos de celdas).
- **Notificaciones**: activa/desactiva los avisos sonoros (el único
  canal de alertas de la app; no hay notificación persistente de
  Android — haría falta un servicio en primer plano).
- **Tema**: abre el selector de tema (Predeterminado / Oscuro) y lo
  aplica a toda la app al momento. Predeterminado es el verde de
  NetMonster (fondo verde oscuro a negro, el tema con el que arranca
  la app); Oscuro es negro cristalino (fondo negro puro, tarjetas
  negro brillante, acento verde). El acento de los dos temas es el
  verde NetMonster (antes el Predeterminado usaba el azul original de
  la app, así que los botones principales ahora son verdes en los dos
  temas). El selector solo se abre desde la fila «Tema» de Ajustes: el
  Menú ya no lleva botón de tema y En Vivo no lleva botones de tema.
  La paleta blanca «Sol» sigue definida en el código para el contraste
  a pleno sol, pero ya no se ofrece en el selector.
- **El tema cambia la app completa**: fondos, tarjetas, textos,
  botones, interruptores, gráficos, barra inferior (botón activo),
  chip de banda, líneas y separadores verdes, tarjetas de iconos de
  Ajustes y separadores de los menús emergentes siguen el tema
  (`app.c_bg`, `c_card`, `c_text`, `c_sub`, `c_accent`, `c_button2`,
  `c_grid`, `c_graph_bg`). Al cambiar de tema, Ajustes se reconstruye
  al momento (antes sus tarjetas y textos quedaban con el tema
  anterior hasta volver a entrar). Comprobado con el test
  `test_themes_change_whole_app`: para cada tema verifica los colores
  de la app, el fondo de la ventana, la barra inferior, la cabecera y
  las tarjetas de Ajustes, el chip y el fondo de Gráficos, y la
  tarjeta y el separador del Menú.
- **Idioma**: abre el selector (Español / English / Русский) y aplica
  el idioma a toda la app al momento.
- Se abre desde el Menú (nueva opción Ajustes). No tiene barra
  inferior: se vuelve con la flecha atrás o con el botón Atrás.

### Menú y navegación inferior
- El Menú original se conserva completo (Información, Gráficos, Mapa,
  Celdas, Escáner, Red, Ajustes, Desconectar) solo con el estilo
  NetMonster (tarjeta oscura, separador verde). Los temas no están en
  el Menú: solo se eligen desde la fila «Tema» de Ajustes.
- Barra inferior fija tipo píldora (Gráficos, Mapa, En vivo, Registro,
  Menú), siempre visible abajo, con el botón activo en verde oscuro.
  El botón Gráficos lleva su icono en cuadrado redondeado con ↗.
- La altura del menú se corrigió: antes los 8 botones desbordaban la
  tarjeta (caja de 389 dp para 504 dp de botones); ahora caben los 9.

## Funciones de NetMonster copiadas
Monitoreo en vivo con identificadores y métricas, barras de señal con
explicación, desglose de CA, gráficos con umbral, registro de celdas con
exportación, bloqueo de bandas recientes, detalle de celda, ajustes con
tema/idioma/segundo plano.

## Lo que NO se pudo copiar (y por qué)
- **Mapa de torres con ubicación real**: el router Huawei no entrega
  GPS ni hay base de datos de torres. No se inventan coordenadas ni
  distancias (las capturas de NetMonster muestran `± 1.6 mi` y
  coordenadas; aquí esas líneas no existen).
- **Datos del módem del teléfono**: Hua4GMon habla con el router por
  Wi-Fi, no con el módem del teléfono; solo se muestra lo que el router
  entrega por su API.
- **Bloqueo por root**: no aplica; el Band Lock ya existe por API del
  router y es mejor.
- **TA (timing advance), UARFCN/RSCP/Ec/No, LAC/PSC, tarjeta Ec/No en
  4G**: el router no los entrega; se muestran en `-` o se derivan
  (CID/RNC desde el CI) sin inventar valores.
- **Notificación persistente**: requeriría un servicio en primer plano
  de Android; la fila Notificaciones controla los avisos sonoros.
- **Iconos de campana y globo**: la fuente DejaVu Sans no tiene 🔔 ni
  🌐. La campana se dibuja con canvas; el globo se representa con ⊕
  y el tema con ◐ (mitad lleno). El resto de glifos (◎ ⚙ ↗ › ←) sí
  están en la fuente, lo verifica `test_android_text_fits_bundled_font`.

## Archivos
- `android_main.py`: tema verde-negro, pantallas En vivo / Gráficos /
  Mapa / Registro / Ajustes, barra inferior fija, hoja de bloqueo,
  detalle de celda, menú.
- `core/netmonster.py` (nuevo): lógica pura — filas de celda, barras,
  CA, ranking de vecinas, formato de registro, registro detallado.
- `core/scanner.py`: `Survey.band_log_csv()` (CSV detallado por banda).
- `core/i18n.py`: claves nuevas en EN/ES (RU es la clave misma).
- `core/__init__.py`: exporta la lógica NetMonster.
- `tests/test_netmonster_ui.py` (nuevo): 17 tests de lógica pura.
- `tests/test_android_ui.py`: tests de UI nuevos (En vivo 4G/3G,
  Gráficos, Mapa, Registro + detalle + CSV + filtro por banda, hoja de
  bloqueo, menú, barra fija, Ajustes, idioma, pausa en segundo plano).

## Cómo probarlo
```sh
python3 -m py_compile android_main.py core/*.py
PYTHONPATH=/tmp/pytest-pkgs:$PYTHONPATH xvfb-run -a python3 -m pytest \
  tests/test_android_ui.py tests/test_netmonster_ui.py \
  tests/test_project.py tests/test_core.py tests/test_network_export.py -q
```
En este equipo faltan `huawei-lte-api` y el certifi fijado, así que
fallan solo por entorno (ya fallaban antes del rediseño):
`test_library_version_matches_pin`,
`test_third_party_notices_generated_from_installed_packages`,
`test_band_lock_restore_and_antenna`, `test_reboot_reconnects`.
En el CI del proyecto esos tests sí tienen sus dependencias.
La suite de UI es pesada: si el equipo se queda sin memoria, correrla
en trozos con `-k` (p. ej. `-k "settings or menu"`), nunca toda de una
vez con otros procesos grandes a la vez.

## Pendiente (fuera de esta rama)
- Descargar la APK del PR #1 (artefacto `Hua4GMon-Android`, run
  45781113518) desde un dispositivo con sesión de GitHub, y/o volver a
  correr el job test (3.13) cancelado del run 45781113502 para poder
  unir el PR #1 y que `main` genere la APK en español.
