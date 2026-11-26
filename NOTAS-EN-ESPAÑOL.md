# Hua4GMon en español — qué se hizo

Versión base: 1.5.0, del repositorio https://github.com/Yaniel375/Hua4GMon
Fecha de esta versión en español: 2026-11-26

## Lo más importante

La interfaz de la app **ya venía en español por defecto** en esta versión.
En `core/i18n.py` el idioma por defecto es `"es"`, y hay 316 textos
traducidos al español, los mismos 316 que en inglés. Por eso no hizo
falta reescribir toda la app ni tocar su lógica.

Ejemplos que ya salen en español al abrirla:
- 🚀 Conectar, 📈 Monitor, 🗼 Torre, 🎛️ Red, 📊 Estado
- Aplicar Band Lock, Marcar actuales, Reconectar enlace
- Escáner de observaciones · Beta, Iniciar / Detener

Si al abrirla la ves en ruso o en inglés, cambia el idioma en la
propia app: en Windows, en la barra superior, en el desplegable de
idioma elige **Español**; en Android, en Menú > Idioma, elige **Español**.

## Qué se cambió en esta versión

Solo 4 archivos, sin tocar la lógica de conexión, Band Lock, ni el
análisis de señal. Son los textos que todavía salían en ruso:

1. `main.py` — ayuda de la línea de comandos (`python main.py --help`):
   - Descripción: "monitor portátil LTE/5G para Huawei"
   - `--ip`: "IP del router (por defecto 192.168.8.1)"
   - `--password`: "Contraseña (si se indica, conecta automáticamente)"
   - `--demo`: "Modo de prueba sin router"
   - `--verbose`: "Registro detallado en stderr"
   - `--self-test`: "Comprobar la aplicación sin router y salir (informe en ARCHIVO)"
   - Los nombres de las opciones (`--ip`, `--demo`, etc.) no cambian.

2. `packaging/splash_rthook.py` — texto de la pantalla de inicio del .exe
   de Windows: "Cargando la aplicación…" (antes en ruso).

3. `core/export.py` — exportación a CSV para Excel en español:
   - Ahora en español usa separador `;` y coma decimal, como en ruso,
     para que Excel en español lo abra por columnas. Antes usaba `,` y
     punto, que es el formato inglés.
   - El valor por defecto al exportar es ahora español, igual que el
     idioma por defecto de la app.
   - No cambia el nombre de las columnas ni los datos.

4. `tests/test_network_export.py` — se añadió una prueba que fija ese
   comportamiento en español, para que no se pierda en el futuro.

## Qué NO se cambió

- No se tocó `core/i18n.py`: no se borró el ruso ni el inglés, porque
  la app los necesita para cambiar de idioma y para que sus propias
  pruebas pasen. Borrarlos habría roto el funcionamiento.
- No se tocaron identificadores, nombres de bandas, comandos del
  router, ni los valores RSRP / SINR / RSRQ.
- No se cambió el nombre de la app, el icono, ni las versiones.

## Verificación hecha

- `python -m py_compile main.py android_main.py core/i18n.py core/export.py packaging/splash_rthook.py` — correcto.
- Idioma por defecto: `es`. Traducción de ejemplo: "🚀 Подключиться" → "🚀 Conectar".
- `python main.py --help` — ya muestra la ayuda en español.
- Pruebas de traducción: 5 pasaron
  (`test_every_ui_string_has_translation`, `test_no_dead_translations`,
  `test_es_matches_en_keys`, `test_translation_placeholders_match`,
  `test_android_text_fits_bundled_font`).
- Pruebas de CSV: 4 pasaron, incluida la nueva en español.
- Pruebas de `test_project.py`, `test_network_export.py` y
  `test_core.py`: 180 pasaron y 2 fallaron por el entorno de este
  equipo, no por estos cambios: falta `huawei-lte-api` instalado y
  la versión de `certifi` del sistema no coincide con la fijada.
  En el CI del proyecto esas dos pruebas pasan con sus dependencias
  instaladas.

## Cómo usar esta versión

### Si solo quieres usarla
Descarga la versión oficial 1.5.0 de GitHub Releases (.exe para
Windows o APK para Android). Ya viene en español por defecto. Esta
carpeta es el código fuente con los cambios de arriba; no es un
APK ni un .exe ya compilado.

### Si quieres compilarla desde este código
- Windows: sigue el flujo de `.github/workflows/build.yml`
  (PyInstaller con `packaging/windows.spec`).
- Android: sigue el flujo de `.github/workflows/build-android.yml`
  (Buildozer). No se compiló un APK en este equipo porque esa
  compilación necesita el entorno Android completo.

### Si quieres subirla a tu GitHub
Copia estos 4 archivos modificados sobre tu repositorio, o sube
toda esta carpeta como una rama nueva, y deja que el CI compile
el .exe y el APK. No subas contraseñas ni claves de firma.
