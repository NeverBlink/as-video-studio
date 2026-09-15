#!/usr/bin/env bash
# =============================================================================
#  AS Video Studio — instalador para un VPS con Ubuntu.
#
#  Se pega UNA linea en la consola del servidor y esto deja el estudio montado,
#  con su acceso por contrasena y su HTTPS:
#
#      curl -fsSL https://raw.githubusercontent.com/NeverBlink/as-video-studio/main/instalar.sh -o instalar.sh
#      bash instalar.sh
#
#  Se puede volver a lanzar las veces que haga falta: no repite lo que ya esta
#  hecho y NO toca los datos (los videos, los estilos ni las claves).
#
#  Variables para desviarse de lo normal (casi nunca hacen falta):
#      ASVS_DOMINIO=midominio.com    el nombre por el que se entra
#      ASVS_CORREO=yo@ejemplo.com    para los avisos de caducidad del certificado
#      ASVS_REPO=usuario/repositorio de donde se baja el codigo
#      ASVS_RAMA=main                que rama
#      ASVS_SIN_TLS=1                no pedir certificado (para probar)
# =============================================================================
set -euo pipefail

VERSION_INSTALADOR="1.0.0"

REPO="${ASVS_REPO:-NeverBlink/as-video-studio}"
RAMA="${ASVS_RAMA:-main}"
RAIZ="${ASVS_RAIZ:-/opt/as-video-studio}"
USUARIO="${ASVS_USUARIO:-studio}"
CUENTA="${ASVS_CUENTA:-estudio}"
PUERTO_APP="${ASVS_PUERTO:-8110}"
PUERTO_LOGIN="${ASVS_PUERTO_LOGIN:-3000}"
DOMINIO="${ASVS_DOMINIO:-}"
CORREO="${ASVS_CORREO:-}"
CARPETA_FUENTES="/usr/local/share/fonts/estudio"
REGISTRO="/var/log/as-video-studio-instalacion.log"

# De donde sale el codigo. Si este script esta DENTRO del arbol (junto a app.py)
# se instala lo que hay al lado en vez de bajar nada: es como se prueba una
# version antes de publicarla, y como se instala desde un clon.
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL=0
[ -f "$AQUI/app.py" ] && [ -d "$AQUI/despliegue" ] && LOCAL=1

# ---------------------------------------------------------------- decoracion

if [ -t 1 ]; then
  N=$'\033[0m'; B=$'\033[1m'; VERDE=$'\033[32m'; ROJO=$'\033[31m'; AMBAR=$'\033[33m'; GRIS=$'\033[90m'
else
  N=""; B=""; VERDE=""; ROJO=""; AMBAR=""; GRIS=""
fi

TOTAL_PASOS=13
NUM_PASO=0

paso()  { NUM_PASO=$((NUM_PASO + 1)); printf '\n%s[%2d/%d]%s %s%s%s\n' "$GRIS" "$NUM_PASO" "$TOTAL_PASOS" "$N" "$B" "$*" "$N"; }
bien()  { printf '        %s✓%s %s\n' "$VERDE" "$N" "$*"; }
nota()  { printf '        %s·%s %s\n' "$GRIS" "$N" "$*"; }
aviso() { printf '        %s!%s %s\n' "$AMBAR" "$N" "$*"; }
fallo() { printf '\n%s ✗ %s%s\n\n' "$ROJO" "$*" "$N"; exit 1; }

# Todo lo que sale por pantalla queda ademas en un fichero: cuando algo falla,
# ese fichero es lo unico que hay que mirar (o mandar).
#
# Y ANTES se guarda la pantalla de verdad en los descriptores 3 y 4. Con la
# salida metida en una tuberia, una pregunta hecha con `read -p` se queda en el
# buffer y no aparece: el usuario ve un programa colgado y no una pregunta. Lo
# unico que se pregunta aqui es la contrasena, y va por el 3 y el 4.
exec 3>&1 4>&2
# El registro solo lo lee root: por ahi pasa el nombre de la maquina, las rutas
# y los errores. La contrasena NO pasa por aqui (va por el 3), pero el fichero
# se cierra igual — un log de una instalacion no es lectura publica.
touch "$REGISTRO" 2>/dev/null && chmod 600 "$REGISTRO" 2>/dev/null || true
exec > >(tee -a "$REGISTRO") 2>&1

export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a          # que apt no pare a preguntar por los reinicios

# ------------------------------------------------------------ comprobaciones

comprobaciones() {
  paso "Comprobando la maquina"

  [ "$(id -u)" -eq 0 ] || fallo "Hay que ser root. En la consola del VPS, entra como 'root'."

  . /etc/os-release 2>/dev/null || fallo "No reconozco este sistema operativo."
  case "${ID:-}:${VERSION_ID:-}" in
    ubuntu:24.04|ubuntu:22.04) bien "Ubuntu $VERSION_ID" ;;
    ubuntu:*) aviso "Ubuntu $VERSION_ID no esta probado (van 22.04 y 24.04). Sigo." ;;
    debian:*) aviso "Debian no esta probado; el navegador puede dar guerra. Sigo." ;;
    *) fallo "Esto necesita Ubuntu 22.04 o 24.04. Aqui hay ${PRETTY_NAME:-algo desconocido}." ;;
  esac

  [ "$(uname -m)" = "x86_64" ] || fallo "Hace falta un procesador x86_64 (este es $(uname -m)): el navegador que dibuja los planos no existe para esta arquitectura."

  local nucleos mem_gb disco_gb
  nucleos="$(nproc)"
  mem_gb=$(( $(awk '/MemTotal/{print $2}' /proc/meminfo) / 1024 / 1024 ))
  disco_gb=$(( $(df -P --output=avail /opt 2>/dev/null | tail -1 || df -P --output=avail / | tail -1) / 1024 / 1024 ))

  bien "$nucleos nucleos, ${mem_gb} GB de memoria, ${disco_gb} GB libres"
  [ "$mem_gb" -ge 3 ]    || fallo "Con ${mem_gb} GB de memoria el render se queda sin sitio. Hacen falta 4 GB como minimo, y 8 para ir comodo."
  [ "$disco_gb" -ge 10 ] || fallo "Quedan ${disco_gb} GB libres y hacen falta 15: solo el navegador y las librerias pasan de 2 GB, y despues estan los videos."
  [ "$mem_gb" -ge 7 ]    || aviso "Con menos de 8 GB el render va justo: baja ESTUDIO_LOTES si se queda sin memoria."

  # Sin salida a internet no hay nada que hacer, y es mejor decirlo ahora que a
  # los tres minutos y a medio instalar.
  curl -fsS --max-time 15 -o /dev/null https://deb.nodesource.com/ 2>/dev/null \
    || fallo "Esta maquina no llega a internet (o hay un cortafuegos de salida). Sin eso no se puede instalar nada."
  bien "Hay salida a internet"

  # El nombre por el que se va a entrar. En un VPS de Hostinger el nombre de la
  # maquina (srvXXXXXXX.hstgr.cloud) YA APUNTA AQUI, asi que sirve de dominio
  # gratis y con certificado de verdad, sin comprar nada.
  if [ -z "$DOMINIO" ]; then
    DOMINIO="$(hostname -f 2>/dev/null || hostname)"
  fi
  [ -n "$DOMINIO" ] || fallo "No se que nombre poner al sitio. Lanza esto otra vez con ASVS_DOMINIO=tudominio.com"
  bien "El estudio se servira en: $DOMINIO"
}

# -------------------------------------------------------------- 2. paquetes

paquetes_base() {
  paso "Instalando lo basico (esto tarda un par de minutos)"

  # apt puede estar ocupado por el arranque automatico de la maquina: se espera
  # en vez de fallar con «could not get lock», que es lo que mas asusta.
  local i
  for i in $(seq 1 60); do
    fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || break
    [ "$i" = 1 ] && nota "esperando a que el sistema termine sus propias actualizaciones..."
    sleep 5
  done

  apt-get update -qq
  apt-get install -y -qq \
    ca-certificates curl gnupg rsync sudo tar \
    ffmpeg \
    python3 python3-venv python3-pip \
    nginx certbot python3-certbot-nginx \
    fontconfig cabextract xfonts-utils \
    ufw jq >/dev/null

  command -v ffmpeg  >/dev/null || fallo "ffmpeg no se ha instalado y sin el no hay ni voz ni video."
  command -v ffprobe >/dev/null || fallo "falta ffprobe (viene con ffmpeg)."
  bien "ffmpeg $(ffmpeg -version | head -1 | awk '{print $3}')"
  bien "nginx, certbot y el cortafuegos"
}

# --------------------------------------------------------------- 3. fuentes

# Enlaza el primer candidato que exista con el nombre que espera el estudio.
_enlaza_fuente() {
  local destino="$1"; shift
  local candidato encontrado=""
  for candidato in "$@"; do
    encontrado="$(find /usr/share/fonts /usr/local/share/fonts -iname "$candidato" -type f 2>/dev/null | head -1)"
    [ -n "$encontrado" ] && break
  done
  [ -n "$encontrado" ] || return 1
  ln -sf "$encontrado" "$CARPETA_FUENTES/$destino"
  printf '%s' "$encontrado"
}

# El alias que hace que el NAVEGADOR resuelva un nombre al MISMO fichero que
# abre PIL para medir. Se calcula de lo que haya quedado enlazado, no a mano:
# si se escribe a mano y el enlace cambia, se separan sin avisar.
_alias_fuente() {
  local familia="$1" fichero="$2" real nombre
  real="$(readlink -f "$CARPETA_FUENTES/$fichero" 2>/dev/null || true)"
  [ -n "$real" ] || return 0
  nombre="$(fc-query -f '%{family[0]}' "$real" 2>/dev/null || true)"
  [ -n "$nombre" ] || return 0
  [ "$nombre" = "$familia" ] && return 0      # ya es esa: no hace falta alias
  cat >> /etc/fonts/conf.d/61-as-video-studio.conf <<XML
  <match target="pattern">
    <test qual="any" name="family"><string>$familia</string></test>
    <edit name="family" mode="assign" binding="same"><string>$nombre</string></edit>
  </match>
XML
}

fuentes() {
  paso "Las fuentes (el punto delicado)"

  # POR QUE ESTO IMPORTA: el estudio MIDE el texto con Python y lo DIBUJA con el
  # navegador. Si mide con una fuente y dibuja con otra, la cuenta sale bien y
  # el numero mal: los rotulos se salen de su caja y solo se ve mirando un PNG.
  # Por eso aqui se fuerza que el fichero que mide y el que dibuja sean el mismo.

  # Las fuentes de Microsoft para la web (Verdana, Georgia, Arial) son las que
  # se usaron para medir. Se instalan del paquete oficial de Ubuntu, que las
  # baja con su licencia: NO se distribuyen dentro de este repositorio.
  if ! fc-list 2>/dev/null | grep -qi "verdana"; then
    nota "bajando las fuentes de Microsoft (Verdana, Georgia, Arial)..."
    add-apt-repository -y multiverse >/dev/null 2>&1 || true
    apt-get update -qq || true
    echo ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true | debconf-set-selections
    apt-get install -y -qq ttf-mscorefonts-installer >/dev/null 2>&1 \
      || aviso "no se han podido bajar (suele ser que el servidor de descarga esta caido)."
  fi
  # El repuesto libre, que ademas es lo que se usa para lo que Microsoft no
  # publica (Segoe UI, Tahoma, Consolas).
  apt-get install -y -qq fonts-dejavu-core >/dev/null

  mkdir -p "$CARPETA_FUENTES"
  rm -f /etc/fonts/conf.d/61-as-video-studio.conf
  printf '<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n<fontconfig>\n' \
    > /etc/fonts/conf.d/61-as-video-studio.conf

  local sustituidas=0
  _pareja() {                       # nombre_estudio  candidato_bueno  repuesto
    local destino="$1" bueno="$2" repuesto="$3" usado
    usado="$(_enlaza_fuente "$destino" "$bueno" "$repuesto" || true)"
    [ -n "$usado" ] || fallo "no hay ninguna fuente para $destino y sin fuentes no se puede dibujar nada."
    case "$usado" in *"$(basename "$bueno" .ttf)"*) : ;; *) sustituidas=$((sustituidas + 1)) ;; esac
  }

  _pareja verdana.ttf   Verdana.ttf         DejaVuSans.ttf
  _pareja verdanab.ttf  Verdana_Bold.ttf    DejaVuSans-Bold.ttf
  _pareja georgia.ttf   Georgia.ttf         DejaVuSerif.ttf
  _pareja georgiab.ttf  Georgia_Bold.ttf    DejaVuSerif-Bold.ttf
  _pareja arial.ttf     Arial.ttf           DejaVuSans.ttf
  _pareja arialbd.ttf   Arial_Bold.ttf      DejaVuSans-Bold.ttf
  # Estas tres Microsoft no las publica para la web, asi que van con repuesto
  # libre SIEMPRE. El estudio solo las nombra en su tabla de fuentes; lo que
  # dibuja de verdad es Verdana y Georgia.
  _enlaza_fuente tahoma.ttf    Tahoma.ttf      Verdana.ttf DejaVuSans.ttf       >/dev/null || true
  _enlaza_fuente tahomabd.ttf  Tahoma_Bold.ttf Verdana_Bold.ttf DejaVuSans-Bold.ttf >/dev/null || true
  _enlaza_fuente consola.ttf   Consolas.ttf    DejaVuSansMono.ttf               >/dev/null || true
  _enlaza_fuente consolab.ttf  Consolas_Bold.ttf DejaVuSansMono-Bold.ttf        >/dev/null || true
  _enlaza_fuente segoeui.ttf   Segoe_UI.ttf    DejaVuSans.ttf                   >/dev/null || true
  _enlaza_fuente segoeuib.ttf  Segoe_UI_Bold.ttf DejaVuSans-Bold.ttf            >/dev/null || true

  local f
  for f in "Verdana:verdana.ttf" "Georgia:georgia.ttf" "Arial:arial.ttf" \
           "Tahoma:tahoma.ttf" "Consolas:consola.ttf" "Segoe UI:segoeui.ttf"; do
    _alias_fuente "${f%%:*}" "${f##*:}"
  done
  printf '</fontconfig>\n' >> /etc/fonts/conf.d/61-as-video-studio.conf

  fc-cache -f >/dev/null 2>&1

  # Y la comprobacion de verdad: que el navegador resuelva «Verdana» al MISMO
  # fichero que va a abrir Python.
  local mide dibuja
  mide="$(readlink -f "$CARPETA_FUENTES/verdana.ttf")"
  dibuja="$(readlink -f "$(fc-match Verdana -f '%{file}' 2>/dev/null)" 2>/dev/null || true)"
  if [ "$mide" = "$dibuja" ]; then
    bien "mide y dibuja el mismo fichero ($(basename "$mide"))"
  else
    aviso "«Verdana» se dibuja con $(basename "${dibuja:-nada}") y se mide con $(basename "$mide"): los rotulos pueden salirse de su caja."
  fi
  if [ "$sustituidas" -gt 0 ]; then
    aviso "$sustituidas fuentes van con repuesto libre: los textos se veran con otra letra, pero cuadrados."
  else
    bien "las fuentes originales, las mismas con las que se midio"
  fi
}

# ------------------------------------------------------------- 4. navegador

navegador() {
  paso "El navegador que dibuja cada plano"

  local binario=""
  if command -v microsoft-edge >/dev/null 2>&1; then
    binario="$(command -v microsoft-edge)"
  elif command -v google-chrome >/dev/null 2>&1; then
    binario="$(command -v google-chrome)"
  else
    nota "instalando Microsoft Edge..."
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
      | gpg --dearmor -o /usr/share/keyrings/microsoft-edge.gpg 2>/dev/null
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-edge.gpg] https://packages.microsoft.com/repos/edge stable main" \
      > /etc/apt/sources.list.d/microsoft-edge.list
    apt-get update -qq
    if apt-get install -y -qq microsoft-edge-stable >/dev/null 2>&1; then
      binario="/usr/bin/microsoft-edge"
    else
      aviso "Edge no ha entrado; pruebo con Google Chrome."
      curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg 2>/dev/null
      echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list
      apt-get update -qq
      apt-get install -y -qq google-chrome-stable >/dev/null \
        || fallo "no se ha podido instalar ningun navegador, y sin navegador no se dibuja ningun plano."
      binario="/usr/bin/google-chrome"
    fi
  fi

  sed "s|__NAVEGADOR__|$binario|" "$FUENTE_DESPLIEGUE/estudio-edge" > /usr/local/bin/estudio-edge
  chmod 755 /usr/local/bin/estudio-edge
  bien "$("$binario" --version 2>/dev/null | head -1)"
}

# ---------------------------------------------------- 5. Node y el CLI de Claude

node_y_claude() {
  paso "Node y el CLI de Claude"

  local mayor=0
  command -v node >/dev/null 2>&1 && mayor="$(node -v | sed 's/^v\([0-9]*\).*/\1/')"
  if [ "$mayor" -lt 20 ]; then
    nota "instalando Node 22..."
    curl -fsSL https://deb.nodesource.com/setup_22.x -o /tmp/nodesource.sh
    bash /tmp/nodesource.sh >/dev/null 2>&1
    rm -f /tmp/nodesource.sh
    apt-get install -y -qq nodejs >/dev/null
  fi
  command -v node >/dev/null || fallo "Node no se ha instalado."
  bien "node $(node -v)"

  # El guion, los rotulos y el asistente los escribe TU SUSCRIPCION de Claude a
  # traves de este CLI. No es una clave de API: se entra despues, desde la
  # pantalla de Configuracion del estudio, sin volver a esta consola.
  if ! command -v claude >/dev/null 2>&1; then
    nota "instalando el CLI de Claude..."
    npm install -g @anthropic-ai/claude-code >/dev/null 2>&1 \
      || fallo "no se ha podido instalar el CLI de Claude (npm install -g @anthropic-ai/claude-code)."
  fi
  bien "claude $(claude --version 2>/dev/null | head -1)"
}

# ------------------------------------------------- 6. usuario y carpetas

usuario_y_carpetas() {
  paso "El usuario del servicio y sus carpetas"

  # El estudio NO corre como root: corre como un usuario sin permisos que solo
  # puede escribir en sus datos. Si algun dia una imagen o un video traen algo
  # raro, no hay nada que puedan tocar.
  if ! id -u "$USUARIO" >/dev/null 2>&1; then
    useradd --system --create-home --home-dir "$RAIZ/home" --shell /usr/sbin/nologin "$USUARIO"
  fi

  mkdir -p "$RAIZ"/{app,home,login} \
           "$RAIZ"/datos/{proyectos,secretos,banco/presets} \
           "$RAIZ"/login/datos \
           /root/estudio

  # El navegador escribe su perfil en HOME y se muere con «cannot create
  # directory» si no existe o no es suyo. Es un fallo que no menciona HOME.
  chown -R "$USUARIO:$USUARIO" "$RAIZ"
  chmod 700 "$RAIZ/datos/secretos" "$RAIZ/login/datos" /root/estudio
  bien "usuario '$USUARIO' y $RAIZ"
}

# --------------------------------------------------------- 7. el codigo

descargar_codigo() {
  paso "El codigo del estudio"

  local origen
  if [ "$LOCAL" = 1 ]; then
    origen="$AQUI"
    nota "instalando el arbol que hay junto a este script"
  else
    origen="$(mktemp -d)"
    nota "bajando $REPO ($RAMA)..."
    curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$RAMA" -o "$origen/codigo.tgz" \
      || fallo "no se ha podido bajar el codigo de https://github.com/$REPO (rama $RAMA). Comprueba que el repositorio es publico."
    tar -xzf "$origen/codigo.tgz" -C "$origen" --strip-components=1
    rm -f "$origen/codigo.tgz"
  fi
  [ -f "$origen/app.py" ] || fallo "lo que se ha bajado no es el estudio (no hay app.py)."

  # rsync con --delete y no un tar por encima: un tar SUPERPONE y no borra nada,
  # asi que un fichero que llego ahi por accidente no se va nunca. Los datos
  # viven fuera de app/, asi que aqui no hay nada que conservar salvo la cache.
  rsync -a --delete \
    --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='cache/' --exclude='proyectos/' --exclude='banco/' --exclude='secretos/' \
    "$origen/" "$RAIZ/app/"

  # El login es una aplicacion aparte (Node) y vive fuera del arbol del estudio.
  rsync -a --delete --exclude='node_modules' --exclude='datos' --exclude='.env' \
    "$RAIZ/app/despliegue/login/" "$RAIZ/login/"

  mkdir -p "$RAIZ/app/cache"
  chown -R "$USUARIO:$USUARIO" "$RAIZ/app" "$RAIZ/login"
  [ "$LOCAL" = 1 ] || rm -rf "$origen"
  bien "codigo instalado en $RAIZ/app"
}

# ------------------------------------------------------- 8. entorno Python

entorno_python() {
  paso "Las librerias de Python"

  [ -x "$RAIZ/venv/bin/python" ] || python3 -m venv "$RAIZ/venv"
  "$RAIZ/venv/bin/pip" install --quiet --upgrade pip wheel
  "$RAIZ/venv/bin/pip" install --quiet -r "$RAIZ/app/requirements.txt" \
    || fallo "no se han podido instalar las librerias de Python (mira $REGISTRO)."
  chown -R "$USUARIO:$USUARIO" "$RAIZ/venv"
  bien "$("$RAIZ/venv/bin/python" --version) con fastapi, pillow y numpy"

  # El entorno de la cuenta: donde vive cada cosa. Los datos van FUERA del
  # arbol de codigo, que es lo que permite actualizar sin tocarlos.
  local lotes
  lotes="$(nproc)"
  [ "$lotes" -gt 16 ] && lotes=16
  if [ ! -f "$RAIZ/datos/entorno" ]; then
    cat > "$RAIZ/datos/entorno" <<ENTORNO
# El entorno del estudio. Cada variable manda una cosa a su sitio; los datos
# viven fuera del codigo para que actualizar no los toque.
PUERTO=$PUERTO_APP
ESTUDIO_PROYECTOS=$RAIZ/datos/proyectos
ESTUDIO_PRESETS=$RAIZ/datos/presets.json
ESTUDIO_BANCO=$RAIZ/datos/banco
ESTUDIO_BANCO_PRESETS=$RAIZ/datos/banco/presets
ESTUDIO_SECRETOS=$RAIZ/datos/secretos
ESTUDIO_ENV=$RAIZ/datos/secretos/.env
ESTUDIO_RECETAS=$RAIZ/datos/recetas.json
ESTUDIO_AJUSTES=$RAIZ/datos/ajustes.json
ESTUDIO_TARIFAS=$RAIZ/datos/tarifas.json
ESTUDIO_ESTADISTICAS=$RAIZ/datos/estadisticas.json
ESTUDIO_COSTE_GLOBAL=$RAIZ/datos/coste_global.jsonl
ESTUDIO_BITACORA_GLOBAL=$RAIZ/datos/bitacora_global.jsonl
ESTUDIO_MOTORES=$RAIZ/app/motores
# Las fuentes y el navegador son ficheros del sistema, no datos de nadie. Que
# las fuentes sean LAS MISMAS con las que se midio es el invariante.
ESTUDIO_FUENTES=$CARPETA_FUENTES
ESTUDIO_EDGE=/usr/local/bin/estudio-edge
HOME=$RAIZ/home
# Cuantos planos se rasterizan a la vez. Medido en una maquina de 8 nucleos:
# con 4 procesos van 6,75 fotogramas/s y con 8 van 10,40. La regla automatica
# del estudio pide la mitad de los nucleos y deja media maquina parada.
ESTUDIO_LOTES=$lotes
ENTORNO
    bien "entorno escrito (ESTUDIO_LOTES=$lotes)"
  else
    nota "el entorno ya existia: no se toca"
  fi
  # Las tarifas son del producto (lo que cuesta cada cosa), pero se copian a los
  # datos para que quien quiera pueda ajustarlas sin que un update se las lleve.
  [ -f "$RAIZ/datos/tarifas.json" ] || cp "$RAIZ/app/tarifas.json" "$RAIZ/datos/tarifas.json" 2>/dev/null || true
  chown -R "$USUARIO:$USUARIO" "$RAIZ/datos"
  chmod 600 "$RAIZ/datos/entorno"
}

# ------------------------------------------------------------- 9. el acceso

el_login() {
  paso "El acceso (para que no entre cualquiera)"

  # EL ESTUDIO NO SABE LO QUE ES UN USUARIO, a proposito: se sirve a quien
  # llame. En una maquina con IP publica eso es cualquiera generando imagenes
  # con tus claves, asi que delante va este portero.
  ( cd "$RAIZ/login" && npm install --omit=dev --no-audit --no-fund >/dev/null 2>&1 ) \
    || fallo "no se han podido instalar las librerias del acceso (npm install en $RAIZ/login)."

  if [ ! -f "$RAIZ/login/.env" ]; then
    local secreto id_vps esquema="https"
    secreto="$(openssl rand -hex 48 2>/dev/null || head -c 48 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    # El id del VPS en el panel de Hostinger sale del propio nombre de la
    # maquina (srv1982300.hstgr.cloud -> 1982300). Solo sirve para el enlace de
    # «he olvidado la contrasena»; si no cuadra, el enlace va al listado.
    id_vps="$(hostname | sed -n 's/^srv\([0-9]\{4,\}\).*/\1/p')"
    [ "${ASVS_SIN_TLS:-0}" = "1" ] && esquema="http"
    cat > "$RAIZ/login/.env" <<ENV
NODE_ENV=production
HOST=127.0.0.1
PORT=$PUERTO_LOGIN
APP_URL=$esquema://$DOMINIO
# La lista de nombres por los que se puede entrar. La comprobacion anti-CSRF
# va CONTRA ESTA LISTA y no contra el Host de la peticion, que lo pone quien
# llama. Si anades un dominio, anadelo tambien aqui o el acceso dira «Origen
# no permitido» sin mas explicacion.
APP_ORIGENES=$esquema://$DOMINIO
DATA_DIR=$RAIZ/login/datos
SESSION_SECRET=$secreto
SECURE_COOKIES=true
TRUST_PROXY=1
HOSTINGER_VPS_ID=$id_vps
ENV
    chmod 600 "$RAIZ/login/.env"
    bien "acceso configurado para $DOMINIO"
  else
    nota "el acceso ya estaba configurado: no se toca"
  fi
  chown -R "$USUARIO:$USUARIO" "$RAIZ/login"

  install -m 755 "$FUENTE_DESPLIEGUE/estudio-clave" /usr/local/bin/estudio-clave
}

# ------------------------------------------------------------ 10. servicios

las_unidades() {
  paso "Los dos servicios"

  sed "s|/opt/as-video-studio|$RAIZ|g; s|^User=studio|User=$USUARIO|; s|^Group=studio|Group=$USUARIO|" \
    "$FUENTE_DESPLIEGUE/as-video-studio.service" > /etc/systemd/system/as-video-studio.service
  sed "s|/opt/as-video-studio|$RAIZ|g; s|^User=studio|User=$USUARIO|; s|^Group=studio|Group=$USUARIO|" \
    "$FUENTE_DESPLIEGUE/as-video-login.service" > /etc/systemd/system/as-video-login.service

  systemctl daemon-reload
  systemctl enable --now as-video-login   >/dev/null 2>&1
  systemctl enable --now as-video-studio  >/dev/null 2>&1
  systemctl restart as-video-login as-video-studio

  local i
  for i in $(seq 1 30); do
    curl -fsS --max-time 2 "http://127.0.0.1:$PUERTO_APP/api/salud" >/dev/null 2>&1 && break
    sleep 1
  done
  systemctl is-active --quiet as-video-login \
    || fallo "el acceso no arranca. Mira que dice:  journalctl -u as-video-login -n 40 --no-pager"
  systemctl is-active --quiet as-video-studio \
    || fallo "el estudio no arranca. Mira que dice:  journalctl -u as-video-studio -n 40 --no-pager"
  bien "el estudio y el acceso, arrancados y en marcha al encender la maquina"
}

# ----------------------------------------------------------------- 11. web

el_sitio_web() {
  paso "El servidor web"

  install -m 644 "$FUENTE_DESPLIEGUE/asvs-proxy.conf"       /etc/nginx/snippets/asvs-proxy.conf
  install -m 644 "$FUENTE_DESPLIEGUE/asvs-proxy-largo.conf" /etc/nginx/snippets/asvs-proxy-largo.conf
  sed "s|__DOMINIO__|$DOMINIO|g; s|127\.0\.0\.1:8110|127.0.0.1:$PUERTO_APP|g; s|127\.0\.0\.1:3000|127.0.0.1:$PUERTO_LOGIN|g" \
    "$FUENTE_DESPLIEGUE/nginx-sitio.conf" > /etc/nginx/sites-available/as-video-studio
  ln -sf /etc/nginx/sites-available/as-video-studio /etc/nginx/sites-enabled/as-video-studio
  rm -f /etc/nginx/sites-enabled/default

  nginx -t >/dev/null 2>&1 || fallo "la configuracion de nginx no vale. Mira:  nginx -t"
  systemctl reload nginx || systemctl restart nginx
  bien "nginx sirviendo $DOMINIO"
}

el_certificado() {
  paso "El certificado (el candado del navegador)"

  if [ "${ASVS_SIN_TLS:-0}" = "1" ]; then
    aviso "saltado a peticion (ASVS_SIN_TLS=1). El acceso ira por HTTP."
    _sin_tls
    return
  fi

  # Antes de pedir nada: que el nombre apunte DE VERDAD a esta maquina. Si no,
  # certbot falla, gasta uno de los pocos intentos que permite Let's Encrypt al
  # dia y deja al de enfrente sin entender por que.
  local ips_maquina ips_nombre coincide=0 ip
  ips_maquina="$(hostname -I 2>/dev/null || true)"
  ips_nombre="$(getent ahosts "$DOMINIO" 2>/dev/null | awk '{print $1}' | sort -u)"
  for ip in $ips_nombre; do
    case " $ips_maquina " in *" $ip "*) coincide=1 ;; esac
  done

  if [ "$coincide" = 0 ]; then
    aviso "«$DOMINIO» no apunta a esta maquina todavia, asi que no pido certificado."
    nota "cuando el DNS apunte aqui, lanza:  asvs https"
    _sin_tls
    return
  fi

  local correo=(--register-unsafely-without-email)
  [ -n "$CORREO" ] && correo=(-m "$CORREO")
  if certbot --nginx -d "$DOMINIO" --non-interactive --agree-tos --redirect \
       --keep-until-expiring "${correo[@]}" >/dev/null 2>&1; then
    _http2
    systemctl reload nginx
    bien "HTTPS activo, y se renueva solo"
  else
    aviso "no se ha podido sacar el certificado (mira $REGISTRO). El estudio funciona igual, por HTTP."
    nota "para reintentarlo:  asvs https"
    _sin_tls
  fi
}

# Sin HTTPS, la cookie de sesion NO puede ir marcada como segura: el navegador
# la tiraria y el acceso fallaria siempre, sin decir por que. Se marca aqui para
# que el sitio funcione, y `asvs https` lo devuelve a seguro al sacar el
# certificado.
_sin_tls() {
  sed -i 's|^SECURE_COOKIES=.*|SECURE_COOKIES=false|; s|^APP_URL=https://|APP_URL=http://|; s|^APP_ORIGENES=https://|APP_ORIGENES=http://|' \
    "$RAIZ/login/.env"
  systemctl restart as-video-login
  ESQUEMA="http"
}

# Certbot no pone HTTP/2, y aqui importa: hay decenas de miniaturas por pantalla
# y por HTTP/1.1 el navegador las mete por seis carriles de uno en uno.
_http2() {
  local sitio=/etc/nginx/sites-available/as-video-studio version
  version="$(nginx -v 2>&1 | sed 's/.*\///; s/ .*//')"
  if printf '%s\n1.25.0\n' "$version" | sort -V | head -1 | grep -q '^1\.25\.0$'; then
    grep -q '^\s*http2 on;' "$sitio" || sed -i '0,/listen .*443 ssl/s//&\n    http2 on;/' "$sitio"
  else
    sed -i 's/\(listen .*443 ssl\)\(;\)/\1 http2\2/' "$sitio"
  fi
  nginx -t >/dev/null 2>&1 || sed -i 's/ http2;/;/' "$sitio"
}

# ---------------------------------------------------------- 12. cortafuegos

cortafuegos() {
  paso "El cortafuegos"
  ufw allow OpenSSH >/dev/null 2>&1 || ufw allow 22/tcp >/dev/null
  ufw allow 80/tcp  >/dev/null
  ufw allow 443/tcp >/dev/null
  yes | ufw enable  >/dev/null 2>&1 || true
  bien "solo abiertos el 22 (consola), el 80 y el 443 (la web)"
}

# ------------------------------------------------------------ 13. contrasena

la_contrasena() {
  paso "Tu contrasena"

  local hay
  hay="$( cd "$RAIZ/login" && set -a && . ./.env && set +a && \
          sudo -u "$USUARIO" -E node bin/user.js list 2>/dev/null | grep -c "$CUENTA" || true )"
  if [ "${hay:-0}" -gt 0 ]; then
    nota "ya habia una cuenta: no se toca."
    nota "para cambiar la contrasena:  estudio-clave --nueva"
    return
  fi

  # Con alguien delante se ELIGE; sin nadie (una instalacion automatica) se
  # genera y se guarda. Se elige a proposito: copiar texto desde la consola web
  # del panel es justo lo que peor funciona, y una contrasena elegida no hay
  # que copiarla de ningun sitio.
  #
  # La pregunta va por la pantalla de verdad (3 y 4), no por la tuberia del
  # registro; y se repite si la contrasena es corta, en vez de generar una a
  # espaldas de quien acaba de escribirla.
  if [ -r /dev/tty ]; then
    local intento
    for intento in 1 2 3; do
      if ESTUDIO_LOGIN_APP="$RAIZ/login" estudio-clave --nueva "$CUENTA" \
           </dev/tty >&3 2>&4; then
        return 0
      fi
      printf '        %svuelve a intentarlo (minimo 12 caracteres)%s\n' "$GRIS" "$N" >&3
    done
    aviso "no se ha podido poner la contrasena a mano: genero una."
  fi
  ESTUDIO_LOGIN_APP="$RAIZ/login" estudio-clave --nueva "$CUENTA" </dev/null
}

# ------------------------------------------------------------ comprobacion

comprobacion_final() {
  paso "Comprobando que todo responde"
  local malo=0

  systemctl is-active --quiet as-video-studio && bien "el estudio responde" || { aviso "el estudio esta parado"; malo=1; }
  systemctl is-active --quiet as-video-login  && bien "el acceso responde"  || { aviso "el acceso esta parado";  malo=1; }

  local codigo
  codigo="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -k "$ESQUEMA://$DOMINIO/login" || true)"
  [ "$codigo" = "200" ] && bien "la pantalla de acceso se ve desde fuera" \
                        || { aviso "la pantalla de acceso contesta $codigo"; malo=1; }

  codigo="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -k "$ESQUEMA://$DOMINIO/" || true)"
  [ "$codigo" = "302" ] && bien "sin sesion, manda al acceso (el estudio esta protegido)" \
                        || aviso "la raiz contesta $codigo (se esperaba un 302 al acceso)"

  return $malo
}

despedida() {
  local clave=""
  [ -f "/root/estudio/clave-$CUENTA.txt" ] && clave="$(cat "/root/estudio/clave-$CUENTA.txt")"

  printf '\n%s' "$VERDE"
  printf '  ┌────────────────────────────────────────────────────────────┐\n'
  printf '  │  AS Video Studio esta listo                                │\n'
  printf '  └────────────────────────────────────────────────────────────┘\n'
  printf '%s\n' "$N"
  printf '   Entra aqui:   %s%s://%s%s\n' "$B" "$ESQUEMA" "$DOMINIO" "$N"
  # La contrasena SOLO a la pantalla (descriptor 3): por el camino normal
  # acabaria escrita en el registro de la instalacion.
  [ -n "$clave" ] && printf '   Contrasena:   %s%s%s\n' "$B" "$clave" "$N" >&3
  printf '\n'
  printf '   Lo que falta se hace YA DENTRO, sin volver a esta consola: al entrar\n'
  printf '   sale una guia que pide, una a una, la cuenta de Claude (es un login,\n'
  printf '   no una clave), la clave de OpenAI y la de Cartesia.\n'
  printf '\n'
  printf '   Si alguna vez se te olvida la contrasena, vuelve aqui y escribe:\n'
  printf '      %sestudio-clave%s\n' "$B" "$N"
  printf '   Y para ver como va todo:  %sasvs estado%s\n' "$B" "$N"
  printf '\n'
  [ "$ESQUEMA" = "http" ] && printf '   %s! Vas sin candado (HTTP). Cuando el nombre apunte aqui:  asvs https%s\n\n' "$AMBAR" "$N"
}

# ------------------------------------------------------------------- manos

ESQUEMA="https"

cabecera() {
  printf '\n%s  AS Video Studio%s  ·  instalador %s\n' "$B" "$N" "$VERSION_INSTALADOR"
  printf '%s  Convierte lo que escribas en un video narrado y animado.%s\n' "$GRIS" "$N"
  printf '%s  Esto tarda unos 5 minutos. No hay que hacer nada mientras.%s\n' "$GRIS" "$N"
}

cabecera
comprobaciones
paquetes_base

# A partir de aqui hace falta el arbol de despliegue, que viaja con el codigo.
if [ "$LOCAL" = 1 ]; then FUENTE_DESPLIEGUE="$AQUI/despliegue"; fi
usuario_y_carpetas
descargar_codigo
FUENTE_DESPLIEGUE="$RAIZ/app/despliegue"
[ -d "$FUENTE_DESPLIEGUE" ] || fallo "falta la carpeta despliegue/ en el codigo."

fuentes
navegador
node_y_claude
entorno_python
el_login
las_unidades
el_sitio_web
el_certificado
cortafuegos
la_contrasena
comprobacion_final || true
despedida

# El comando de mantenimiento, que es lo que se pide cuando algo va raro.
install -m 755 "$FUENTE_DESPLIEGUE/asvs" /usr/local/bin/asvs 2>/dev/null || true
