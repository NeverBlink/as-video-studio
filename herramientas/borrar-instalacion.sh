#!/usr/bin/env bash
# -----------------------------------------------------------------------------
#  borrar-instalacion.sh — deja la maquina como estaba antes de instalar.
#
#  Para PROBAR el instalador: una instalacion que se relanza encima no prueba lo
#  mismo que una de cero, y casi todos los fallos que ha tenido este instalador
#  solo salian en una maquina limpia.
#
#      bash herramientas/borrar-instalacion.sh          dice lo que borraria
#      bash herramientas/borrar-instalacion.sh --si     lo borra
#
#  BORRA TAMBIEN LOS DATOS: los videos, los estilos y las claves. No es un
#  desinstalador amable, es el boton de «como si nunca hubiera pasado».
#
#  Lo que NO toca: los paquetes del sistema (ffmpeg, el navegador, Node), el
#  certificado de Let's Encrypt y la instalacion de nginx. Eso se queda a
#  proposito -- volver a bajarlo en cada prueba son diez minutos de nada.
# -----------------------------------------------------------------------------
set -euo pipefail

RAIZ="${ASVS_RAIZ:-/opt/as-video-studio}"
USUARIO="${ASVS_USUARIO:-studio}"

[ "$(id -u)" -eq 0 ] || { echo "Hay que ser root."; exit 1; }

COSAS=(
  "$RAIZ"
  /root/estudio
  /etc/systemd/system/as-video-studio.service
  /etc/systemd/system/as-video-login.service
  /etc/nginx/sites-enabled/as-video-studio
  /etc/nginx/sites-available/as-video-studio
  /etc/nginx/snippets/asvs-proxy.conf
  /etc/nginx/snippets/asvs-proxy-largo.conf
  /usr/local/bin/asvs
  /usr/local/bin/estudio-clave
  /usr/local/bin/estudio-edge
  /usr/local/share/fonts/estudio
  /etc/fonts/conf.d/61-as-video-studio.conf
  /var/log/as-video-studio-instalacion.log
)

if [ "${1:-}" != "--si" ]; then
  echo
  echo "Esto borraria, CON LOS DATOS DENTRO:"
  for c in "${COSAS[@]}"; do [ -e "$c" ] && echo "  $c"; done
  id -u "$USUARIO" >/dev/null 2>&1 && echo "  el usuario '$USUARIO'"
  echo
  echo "Si es lo que quieres:  bash $0 --si"
  exit 0
fi

systemctl disable --now as-video-studio as-video-login 2>/dev/null || true
rm -rf "${COSAS[@]}"
systemctl daemon-reload
userdel "$USUARIO" 2>/dev/null || true
fc-cache -f >/dev/null 2>&1 || true
systemctl restart nginx 2>/dev/null || true
echo "Borrado. La maquina esta como antes de instalar."
