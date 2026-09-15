# Las suites en seco, con una linea por suite.
#
#     powershell -NoProfile -File pruebas.ps1
#     powershell -NoProfile -File pruebas.ps1 -Python C:\ruta\a\python.exe
#
# POR POWERSHELL Y NO POR BASH, y no es una preferencia: Edge headless devuelve
# codigo 0 y no escribe el PNG cuando se lanza desde un shell sandboxeado, asi
# que prueba_pasos_visuales falla con "Edge no genero ...png" sin que nada este
# roto. El mismo Edge y el mismo interprete van bien desde aqui.
#
# Tres cosas mas que ahorran perseguir fallos que no existen:
#   - prueba_pasos_visuales REUTILIZA %TEMP%\estudio_prueba_visual entre
#     ejecuciones; si una pasada se corta a medias, la siguiente falla por el
#     estado sucio. Se borra sola aqui abajo.
#   - prueba_pasos_voz sale a la API de Cartesia de verdad: puede fallar por
#     como venga su catalogo ese dia, o quedarse sin clave y decirlo.
#   - prueba_login llama al CLI de claude de verdad y sale a la pagina de
#     acceso de Anthropic (sin autenticar nada). Es la unica que comprueba que
#     el CLI sigue dejando entrar sin terminal y sin abrir navegador.
#
# NINGUNA PAGA UNA IMAGEN. `prueba_piezas` deja el motor de imagen sin `generar`
# antes de empezar (ver su cabecera), asi que una firma de cache que deje de
# acertar sale como un fallo con su traza y no como una factura.

param(
  [string]$Python = ""
)

$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot

if (-not $Python) {
  $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $Python) {
  Write-Output "no encuentro python: pasalo con -Python C:\ruta\a\python.exe"
  exit 2
}
Write-Output ("interprete: {0}" -f $Python)

# Y SE DICE SI NO SE PUEDE BORRAR. Con -ErrorAction SilentlyContinue a secas, un
# Edge zombi de otra tanda reteniendo un PNG dejaba la carpeta a medias y la
# suite reventaba despues con un PermissionError dentro de shutil.rmtree, que no
# se parece en nada a la causa.
$sucio = "$env:TEMP\estudio_prueba_visual"
Remove-Item -Recurse -Force $sucio -ErrorAction SilentlyContinue
if (Test-Path $sucio) {
  Write-Output ("AVISO  no se ha podido borrar $sucio (algo lo tiene abierto): " +
                "prueba_pasos_visuales puede fallar por estado sucio y no por el codigo. " +
                "Mira si queda algun msedge headless de una tanda anterior.")
}

# EL HISTORICO DE TIEMPOS, A UNA COPIA, para TODA la tanda. Cada suite lo
# redirige tambien por su cuenta --se corren sueltas-- y esto es el cinturon: el
# historico guarda 30 muestras por paso, asi que una suite que se olvide EXPULSA
# las reales por antiguedad, y con ellas se va lo unico que hace que `cadencia` y
# la barra dejen de usar la tabla escrita y usen lo medido de esta maquina.
$env:ESTUDIO_ESTADISTICAS = Join-Path $env:TEMP 'estudio_pruebas_estadisticas.json'
Remove-Item -Force $env:ESTUDIO_ESTADISTICAS -ErrorAction SilentlyContinue

$suites = @(
  'prueba_api.py', 'prueba_coste_capturas.py',
  'nucleo\prueba_nucleo.py', 'nucleo\prueba_adversarial.py',
  'nucleo\prueba_manifiestos.py',
  'pasos\prueba_ajustes.py', 'pasos\prueba_login.py',
  'pasos\prueba_asistente.py', 'pasos\prueba_salud_cli.py',
  'pasos\prueba_enrutar_estilo.py',
  'pasos\prueba_p1.py', 'pasos\prueba_p2.py', 'pasos\prueba_p3.py',
  'pasos\prueba_cta.py',
  'pasos\prueba_pasos_guion.py', 'pasos\prueba_marcas_tts.py',
  'pasos\prueba_pasos_voz.py', 'pasos\prueba_pasos_visuales.py',
  'pasos\prueba_repaso.py',
  'pasos\prueba_piezas.py', 'pasos\prueba_conservar.py',
  'pasos\prueba_encuadres.py', 'pasos\prueba_presets.py',
  'pasos\prueba_presets_light.py'
)

$fallos = 0
foreach ($s in $suites) {
  $salida = & $Python $s 2>&1 | Out-String
  if ($LASTEXITCODE -eq 0) {
    # El resumen es la ULTIMA linea con cifras: cada suite lo escribe a su
    # manera ('OK: 284 comprobaciones pasan', '157 comprobaciones correctas'),
    # y si no casa ninguna se deja en blanco. Antes esto reventaba con «You
    # cannot call a method on a null-valued expression» y la suite que pasaba
    # desaparecia del resumen -- se leia como si no hubiera corrido.
    $linea = ($salida -split "`n" | Where-Object { $_ -match 'comprobaciones|pasan' } | Select-Object -Last 1)
    if ($null -eq $linea) { $linea = '' }
    Write-Output ("OK    {0,-32} {1}" -f $s, $linea.Trim())
  } elseif ($LASTEXITCODE -eq 3) {
    # CODIGO_SIN_CUPO (pasos\cli_claude.py): la suite no ha podido correr
    # porque se acabo el cupo de la suscripcion, y eso no es nada roto.
    # Se dice y NO se cuenta: un rojo que no significa nada ensena a
    # ignorar el rojo.
    $linea = ($salida -split "`n" | Where-Object { $_ -match 'CUPO' } | Select-Object -First 1)
    if ($null -eq $linea) { $linea = 'sin cupo de suscripcion' }
    Write-Output ("CUPO  {0,-32} {1}" -f $s, $linea.Trim())
  } else {
    $fallos++
    Write-Output ("FALLA {0,-32}" -f $s)
    ($salida -split "`n" | Select-Object -Last 14) | ForEach-Object { Write-Output ("        " + $_.TrimEnd()) }
  }
}

# Y LAS HERRAMIENTAS DE ANALISIS, que no son suites pero cantan lo mismo: una
# llamada a algo que ya no existe y una funcion que nadie puede alcanzar son
# fallos que ninguna prueba ve porque nadie ejecuta esa linea.
Write-Output ""
foreach ($h in @('herramientas\indefinidos_py.py', 'herramientas\indefinidos_js.py',
                 'herramientas\huerfanas_js.py', 'herramientas\sin_llamar_js.py',
                 'herramientas\alcanzables_js.py', 'herramientas\atributos_py.py',
                 'herramientas\css_sin_usar.py')) {
  if (-not (Test-Path $h)) { continue }
  $salida = & $Python $h 2>&1 | Out-String
  $resumen = ($salida -split "`n" | Where-Object { $_ -match ':|NO |NADIE|SOSPECHOSAS' } | Select-Object -First 1)
  if ($null -eq $resumen) { $resumen = 'sin nada que decir' }
  Write-Output ("ANAL  {0,-32} {1}" -f $h, $resumen.Trim())
}

Write-Output ""
if ($fallos -gt 0) {
  Write-Output ("{0} suite(s) EN ROJO" -f $fallos)
  exit 1
}
Write-Output "todas las suites en verde"
exit 0
