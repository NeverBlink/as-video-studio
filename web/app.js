/* Estudio de Video — interfaz.
 *
 * HTML/CSS/JS a pelo. Todo lo que la interfaz sabe del servidor esta en el
 * objeto API de aqui abajo; si un endpoint cambia de forma, se cambia ahi y
 * nada mas.
 *
 * LA API ENTERA VIVE EN docs/API.md, sacada del propio app.py: los 126
 * endpoints con lo que hace cada uno. Aqui habia una lista a mano de 52 de esos
 * 126 y nadie la completaba al anadir uno -- una lista a medias de una API es
 * peor que ninguna, porque parece completa. Lo que queda aqui abajo es el mapa
 * de rutas que se USAN, que es lo unico que este fichero tiene que saber.
 *
 * Y tres formas que valen para toda la API, para no ir a buscarlas:
 *
 *   - lo que tarda devuelve 202 con {trabajo_id}, y se sigue por
 *     GET /api/trabajos/{tid} o por SSE en .../eventos (eventos 'progreso' y 'fin');
 *   - los errores llegan como {error:{codigo,mensaje,detalle}} y el `mensaje`
 *     es la frase en castellano que se le ensena a una persona;
 *   - no hay endpoint de guardar-y-confirmar: PUT guarda, y pasar de paso es
 *     aprobar (ver docs/INTERFAZ.md).
 */

/* ------------------------------------------------------------------ DOM */

function h(etiqueta, props, ...hijos) {
  const n = document.createElement(etiqueta);
  /* `value` va por PROPIEDAD y no por atributo, y no es un detalle: un
     <textarea> NO TIENE atributo value —su contenido es su nodo de texto—, así
     que `setAttribute('value', x)` no da error, no hace nada y deja el campo
     vacío. Costó una tanda entera: la dirección de los 45 planos se guardaba
     bien en el servidor y la pantalla los pintaba en blanco, que se lee como
     «no se ha generado nada». En un <input> el atributo sí funciona, y por eso
     el fallo sólo aparece en los textarea — o sea, justo donde no se busca.
     Se aplica DESPUÉS de meter los hijos porque un <select> necesita tener sus
     <option> dentro antes de poder elegir uno. */
  let valorDiferido;
  for (const [clave, valor] of Object.entries(props || {})) {
    if (valor === null || valor === undefined || valor === false) continue;
    if (clave === 'clase') n.className = valor;
    else if (clave === 'texto') n.textContent = valor;
    else if (clave === 'datos') Object.assign(n.dataset, valor);
    else if (clave === 'estilo') n.setAttribute('style', valor);
    else if (clave.startsWith('on')) n.addEventListener(clave.slice(2), valor);
    else if (clave === 'value' && 'value' in n) valorDiferido = valor;
    else if (valor === true) n.setAttribute(clave, '');
    else n.setAttribute(clave, valor);
  }
  meter(n, hijos);
  if (valorDiferido !== undefined) n.value = valorDiferido;
  return n;
}

function meter(nodo, hijos) {
  for (const hijo of hijos.flat(4)) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    nodo.appendChild(hijo instanceof Node ? hijo : document.createTextNode(String(hijo)));
  }
  return nodo;
}

const $ = sel => document.querySelector(sel);

function vaciar(nodo) { while (nodo.firstChild) nodo.removeChild(nodo.firstChild); return nodo; }

/* ------------------------------------------------------------------ formato */

function reloj(segundos) {
  const s = Math.max(0, Number(segundos) || 0);
  const m = Math.floor(s / 60);
  return `${m}:${(s % 60).toFixed(1).padStart(4, '0')}`;
}

/* 780 -> '13:00'. Para duraciones de video, donde la decima no dice nada. */
function mmss(segundos) {
  const total = Math.max(0, Math.round(Number(segundos) || 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

function duracionCorta(segundos) {
  const s = Math.round(Number(segundos) || 0);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
}

function fechaCorta(iso) {
  if (!iso) return '';
  return String(iso).replace('T', ' ').slice(0, 19);
}

/* Anotaciones de voz para el TTS: <break/>, <speed/>, <volume/>, <emotion/>,
 * <spell>. Van dentro del texto del bloque a propósito —se ven y se editan como
 * parte del guion— pero NO se locutan, así que aquí no cuentan como palabras.
 * El gemelo de esto en el backend es `pasos/marcas_tts.limpiar`, y tiene que
 * decir lo MISMO: de esta cuenta sale el reparto de las marcas de palabra entre
 * bloques, y una palabra de más desplaza todo lo que va detrás.
 *
 * `<spell>` es la excepción y no un detalle: su contenido se pega a lo que tenga
 * al lado, sin espacio. Aquí se sustituía por un espacio como cualquier otra
 * etiqueta, así que «<spell>VPN</spell>s» daba DOS palabras («VPN» y «s») donde
 * Cartesia devuelve una marca, y «<spell>MEGA</spell>.» otras dos. Medido en el
 * vídeo real: 716 palabras pintadas contra 713 marcas, y las últimas
 * palabras de esos bloques se quedaban sin iluminar en el karaoke. */
const MARCA_TTS = /<[^<>]*>/g;
const SPELL_TTS = /<spell>\s*([^<>]+?)\s*<\/spell>/gi;

function sinMarcasTts(texto) {
  return String(texto || '').replace(SPELL_TTS, '$1').replace(MARCA_TTS, ' ');
}

/* Palabras que se OYEN. Importa más allá del contador: en la línea de tiempo,
 * las marcas de palabra de la toma se reparten entre bloques contando esto, y
 * una etiqueta contada de más desplazaría todos los bloques siguientes. */
function palabrasDe(texto) {
  return (sinMarcasTts(texto).trim().match(/\S+/g) || []).length;
}

function miles(numero) {
  const valor = Number(numero);
  if (!Number.isFinite(valor)) return '—';
  return valor.toLocaleString('es-ES');
}

/* 312000 -> '312k', 41200 -> '41.2k'. La misma escala que usa nucleo/coste. */
function corto(numero) {
  const valor = Math.round(Number(numero) || 0);
  if (valor < 1000) return String(valor);
  if (valor < 100000) return `${(valor / 1000).toFixed(1)}k`;
  if (valor < 1000000) return `${Math.round(valor / 1000)}k`;
  return `${(valor / 1000000).toFixed(1)}M`;
}

/* ------------------------------------------------------------------ datos que faltan
 * Regla de la casa: en la pantalla nunca aparece 'undefined'. Un dato ausente
 * se ve como un hueco ('—') y un recuento ausente no se inventa.
 *
 * Las salidas grandes de un paso llegan resumidas ({_resumido, elementos}): el
 * servicio sustituye cualquier bloque enorme antes de sellar la version. Ese
 * objeto es 'truthy', asi que sin comprobarlo la interfaz creia tener la lista
 * y pintaba 'undefined de 338' en vez de caer al fichero de la version.
 */

function esResumido(valor) {
  return !!valor && typeof valor === 'object' && valor._resumido === true;
}

/* Recuento de algo que puede venir como numero, como lista o como resumen. */
function numeroDe(valor) {
  if (typeof valor === 'number' && Number.isFinite(valor)) return valor;
  if (Array.isArray(valor)) return valor.length;
  if (esResumido(valor) && typeof valor.elementos === 'number') return valor.elementos;
  if (typeof valor === 'string' && valor.trim() !== '' && Number.isFinite(Number(valor))) {
    return Number(valor);
  }
  return null;
}

function cifra(valor, hueco) {
  const numero = numeroDe(valor);
  return numero === null ? (hueco === undefined ? '—' : hueco) : miles(numero);
}

/* Lista de verdad, o null si lo que hay es un resumen (o no es una lista). */
function listaDe(valor) {
  return Array.isArray(valor) ? valor : null;
}

function oHueco(valor, hueco) {
  if (valor === undefined || valor === null || valor === '') {
    return hueco === undefined ? '—' : hueco;
  }
  return String(valor);
}

/* ------------------------------------------------------------------ errores
 * El backend devuelve mensajes en castellano que explican que ha pasado y que
 * hacer. Lo que llega por 'error' es "TipoDeError: mensaje" y puede arrastrar
 * el volcado de un subproceso. Se ensena la frase util y el volcado se queda
 * plegado: accesible, pero sin tapar lo que hay que leer.
 */

const TIPO_ERROR = /^([A-Za-z_][A-Za-z0-9_.]*)\s*:\s*/;
const VOLCADO_PROCESO = /Command\s+'[\s\S]*?'\s+returned non-zero exit status\s+(\d+)/i;

function partirError(crudo) {
  const bruto = String(crudo === undefined || crudo === null ? '' : crudo).trim();
  if (!bruto) return { titular: 'ha fallado sin decir por qué', tipo: '', detalle: '' };

  let resto = bruto;
  let tipo = '';
  const encaje = bruto.match(TIPO_ERROR);
  // 'ValueError: falta la URL' -> el nombre de la clase no le dice nada a quien
  // mira la pantalla; se aparta y se ensena como dato tecnico
  if (encaje && bruto.slice(encaje[0].length).trim()) {
    tipo = encaje[1];
    resto = bruto.slice(encaje[0].length).trim();
  }

  const proceso = resto.match(VOLCADO_PROCESO);
  let titular;
  if (proceso) {
    titular = `Un programa externo ha terminado con error (código ${proceso[1]}). `
      + 'El volcado completo está en el detalle técnico.';
  } else {
    titular = resto.split(/\n{2,}/)[0].trim();
    if (titular.length > 600) titular = `${titular.slice(0, 600)}…`;
  }
  return {
    titular: titular || bruto.slice(0, 300),
    tipo,
    // solo hay 'detalle' si de verdad dice algo mas que el titular
    detalle: resto === titular ? '' : bruto,
  };
}

function cajaError(crudo, clase) {
  const { titular, tipo, detalle } = partirError(crudo);
  return h('div', { clase: clase || 'caja-error' },
    h('div', { clase: 'titular' }, titular),
    detalle ? h('details', { clase: 'detalle-tecnico' },
      h('summary', {}, `detalle técnico${tipo ? ` (${tipo})` : ''}`),
      h('pre', {}, detalle))
      : (tipo ? h('div', { clase: 'meta', estilo: 'margin-top:6px' }, tipo) : null));
}

/* ------------------------------------------------------------------ normalizadores
 * Las salidas de un paso llegan en varias formas segun quien las escribiera
 * (la lista entera, el nombre del fichero que la contiene, un mapa de unidades).
 * Aqui se reducen todas a la misma, que es lo unico que sabe pintar la interfaz.
 */

const CLAVES_LISTA_BLOQUES = ['bloques', 'guion', 'escenas', 'segmentos', 'partes'];
const CLAVES_TEXTO = ['texto', 'narracion', 'texto_narracion', 'contenido', 'text'];

function textoDe(registro) {
  for (const clave of CLAVES_TEXTO) {
    const valor = registro[clave];
    if (typeof valor === 'string' && valor.trim()) return valor.trim();
  }
  // Un bloque puede venir solo con sus marcas de palabra (meta del motor de voz).
  if (Array.isArray(registro.palabras) && registro.palabras.length
      && typeof registro.palabras[0] === 'object') {
    return registro.palabras.map(p => p.w).join(' ');
  }
  return '';
}

function esMapaDeUnidades(objeto) {
  const claves = Object.keys(objeto);
  if (!claves.length) return false;
  if (!claves.every(c => /^[A-Za-z]+\d+$/.test(c) || /^(escena|asset):/.test(c))) return false;
  return claves.every(c => typeof objeto[c] === 'string'
    ? objeto[c].trim() : (objeto[c] && typeof objeto[c] === 'object' && textoDe(objeto[c])));
}

function normalizarBloques(crudo) {
  let lista = null;
  if (Array.isArray(crudo)) lista = crudo;
  else if (crudo && typeof crudo === 'object') {
    for (const clave of CLAVES_LISTA_BLOQUES) {
      if (Array.isArray(crudo[clave])) { lista = crudo[clave]; break; }
    }
    if (!lista && esMapaDeUnidades(crudo)) {
      lista = Object.keys(crudo).sort().map(clave => (
        typeof crudo[clave] === 'string'
          ? { id: clave, texto: crudo[clave] }
          : Object.assign({ id: clave }, crudo[clave])));
    }
  } else if (typeof crudo === 'string') {
    lista = crudo.split(/\n\s*\n/).map(t => t.trim()).filter(Boolean);
  }
  if (!Array.isArray(lista)) return [];

  const bloques = [];
  lista.forEach((elemento, posicion) => {
    const numero = `B${String(posicion + 1).padStart(2, '0')}`;
    if (typeof elemento === 'string') {
      if (elemento.trim()) bloques.push({ id: numero, texto: elemento.trim() });
      return;
    }
    if (!elemento || typeof elemento !== 'object') return;
    const texto = textoDe(elemento);
    if (!texto) return;
    bloques.push({
      id: String(elemento.id || elemento.bloque_id || numero),
      texto,
      palabras: Array.isArray(elemento.palabras) && typeof elemento.palabras[0] === 'object'
        ? elemento.palabras : null,
      n_palabras: typeof elemento.palabras === 'number' ? elemento.palabras : null,
      t_in: elemento.t_in, t_out: elemento.t_out,
    });
  });
  return bloques;
}

/* Bloques + marcas de palabra de una toma, vengan como vengan. */
/* Una salida SELLADA no siempre trae sus datos: el núcleo sustituye lo grande
   por un resumen —{_resumido:true, elementos:367}— antes de guardar la versión,
   porque si no el panel recibiría el guion entero en cada petición. Ese resumen
   es un objeto, o sea TRUTHY, y ahí estaba el fallo: `salidas.palabras` parecía
   traer las marcas, no se miraba el audio_meta.json, y las 367 marcas de palabra
   se quedaban en cero. Sin marcas no hay karaoke, no se puede pinchar una
   palabra para saltar y el texto queda de adorno. */
function esResumen(valor) {
  return !!valor && typeof valor === 'object' && !Array.isArray(valor) && valor._resumido;
}

function datosDeVerdad(deSalidas, deMeta) {
  return (deSalidas && !esResumen(deSalidas)) ? deSalidas : (deMeta || null);
}

function normalizarAudio(salidas, meta) {
  salidas = salidas || {};
  meta = meta || {};
  /* Cada pieza se busca por su cuenta: una salida puede tener los bloques
     enteros y las marcas resumidas, o al revés, según de qué tamaño fueran. */
  let bloques = normalizarBloques(
    datosDeVerdad(salidas.bloques, meta.bloques)
    || datosDeVerdad(salidas.escenas, meta.escenas)
    || datosDeVerdad(salidas.guion, meta.guion) || []);
  if (!bloques.length) bloques = normalizarBloques(meta.escenas || meta.bloques || []);

  const crudas = datosDeVerdad(salidas.palabras, meta.palabras);
  const globales = Array.isArray(crudas) && typeof (crudas[0] || {}) === 'object'
    ? crudas : null;
  let cursor = 0;
  for (const bloque of bloques) {
    if (!bloque.palabras && globales) {
      const cuantas = bloque.n_palabras || palabrasDe(bloque.texto);
      bloque.palabras = globales.slice(cursor, cursor + cuantas);
      cursor += cuantas;
    }
    if (bloque.palabras && bloque.palabras.length) {
      if (bloque.t_in === undefined) bloque.t_in = bloque.palabras[0].s;
      if (bloque.t_out === undefined) bloque.t_out = bloque.palabras[bloque.palabras.length - 1].e;
    }
  }
  return {
    bloques,
    /* LAS SECCIONES, que es la unidad de REGRABADO (`p4_voz.regrabar_seccion`).
       Se quedaban fuera de aquí, así que `panelRevision` nunca las encontraba y
       caía siempre a su respaldo —UNA sección con todos los bloques—: el guion
       se pintaba de una pieza y «Regrabar SB001» volvía a grabar la toma
       entera. Están en `audio_meta.json` desde que existen; lo que faltaba era
       traerlas. */
    secciones: datosDeVerdad((salidas || {}).secciones, (meta || {}).secciones) || [],
    duracion: (salidas || {}).duracion || (meta || {}).duracion || 0,
    controles: (salidas || {}).controles || (meta || {}).controles || null,
  };
}

/* ------------------------------------------------------------------ API */

/* Prefijo del que cuelga el Estudio. Detras del proxy la interfaz se sirve en
   /estudio/, y una ruta absoluta como '/api/proyectos' resuelve contra la raiz
   del dominio: acaba pegando al panel de control, que responde 404 y deja el
   Estudio en blanco con un 'Not Found' que no es suyo. Se deduce de donde se
   sirvio la pagina, asi que funciona igual en :8020 que bajo cualquier prefijo. */
const BASE = location.pathname.replace(/\/[^/]*$/, '').replace(/\/$/, '');

const API = {
  proyectos: () => `${BASE}/api/proyectos`,
  proyecto: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}`,
  paso: (pid, paso) => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/pasos/${paso}`,
  params: (pid, paso) => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/pasos/${paso}/params`,
  ejecutar: (pid, paso) => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/pasos/${paso}/ejecutar`,
  revertir: (pid, paso) => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/pasos/${paso}/revertir`,
  bitacora: (pid, paso) => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/bitacora`
    + (paso ? `?paso=${paso}&limite=300` : '?limite=300'),
  previsualizar: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/voz/previsualizar`,
  voces: (idioma, nativas) => `${BASE}/api/voces?idioma=${idioma || ''}&nativas=${nativas ? 1 : 0}`,
  presets: () => `${BASE}/api/presets`,
  trabajo: tid => `${BASE}/api/trabajos/${tid}`,
  eventos: tid => `${BASE}/api/trabajos/${tid}/eventos`,
  cancelar: tid => `${BASE}/api/trabajos/${tid}/cancelar`,
  archivo: (pid, ruta) => `${BASE}/a/${encodeURIComponent(pid)}/${String(ruta).split('\\').join('/')
    .split('/').map(encodeURIComponent).join('/')}`,
  coste: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/coste`,
  costePorPaso: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/coste/por-paso`,
  costePresupuesto: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/coste/presupuesto`,
  capturas: (pid, consulta) => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/capturas`
    + (consulta ? `?${consulta}` : ''),
  captura: (pid, cid) => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/capturas/${encodeURIComponent(cid)}`,
  aplicarCapturas: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/capturas/aplicar`,
  contextoCaptura: (pid, consulta) => `${BASE}/api/proyectos/${encodeURIComponent(pid)}`
    + `/capturas/contexto?${consulta}`,
  ajustesCLI: () => `${BASE}/api/ajustes-cli`,
  claves: () => `${BASE}/api/claves`,
  ajustes: () => `${BASE}/api/ajustes`,
  cuentasCLI: refrescar => `${BASE}/api/claves/cli${refrescar ? '?refrescar=1' : ''}`,
  entrarCLI: cid => `${BASE}/api/claves/cli/${encodeURIComponent(cid)}/entrar`,
  codigoCLI: cid => `${BASE}/api/claves/cli/${encodeURIComponent(cid)}/codigo`,
  salirCLI: cid => `${BASE}/api/claves/cli/${encodeURIComponent(cid)}/salir`,
  asistente: () => `${BASE}/api/asistente`,
  charlas: () => `${BASE}/api/asistente/charlas`,
  charla: cid => `${BASE}/api/asistente/charlas/${encodeURIComponent(cid)}`,
  mensajesAsistente: cid => `${BASE}/api/asistente/charlas/${encodeURIComponent(cid)}/mensajes`,
  cancelarAsistente: cid => `${BASE}/api/asistente/charlas/${encodeURIComponent(cid)}/cancelar`,
  probarAsistente: () => `${BASE}/api/asistente/probar`,
  probarCLI: cid => `${BASE}/api/claves/cli/${encodeURIComponent(cid)}/probar`,
  probarClaves: () => `${BASE}/api/claves/probar`,
  recetas: () => `${BASE}/api/recetas`,
  receta: rid => `${BASE}/api/recetas/${encodeURIComponent(rid)}`,
  pestana: (pid, pestana) => `${BASE}/api/proyectos/${encodeURIComponent(pid)}`
    + `/pestanas/${encodeURIComponent(pestana)}`,
  generarPestana: (pid, pestana) => `${BASE}/api/proyectos/${encodeURIComponent(pid)}`
    + `/pestanas/${encodeURIComponent(pestana)}/generar`,
  estadisticas: pares => `${BASE}/api/estadisticas`
    + (pares && Object.keys(pares).length ? `?${consulta(pares)}` : ''),
  valoracion: () => `${BASE}/api/estadisticas/valoracion`,
  apartar: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}`,
  duplicar: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/duplicar`,
  papelera: () => `${BASE}/api/proyectos/papelera`,
  papeleraFicha: carpeta => `${BASE}/api/proyectos/papelera/${encodeURIComponent(carpeta)}`,
  restaurar: carpeta => `${BASE}/api/proyectos/papelera/${encodeURIComponent(carpeta)}/restaurar`,
  tono: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/tono`,
  estilo: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/estilo`,
  estiloExtraer: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/estilo/extraer`,
  estiloSeleccion: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/estilo/seleccion`,
  estiloGuia: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/estilo/guia`,
  tarifas: () => `${BASE}/api/coste/tarifas`,
  disenoCallouts: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/callouts/diseno`,
  planCallouts: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/callouts/plan`,
  // Cartelas: planos de texto sobre negro. Van en ASSETS y no en Rótulos porque
  // cambian el plan (ese plano deja de generar imagen), así que hay que
  // decidirlas antes de generar o se paga una imagen para tirarla.
  cartelas: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/cartelas`,
  cartelasPlan: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/cartelas/plan`,
  cartelaVista: (pid, plano) => `${BASE}/api/proyectos/${encodeURIComponent(pid)}`
    + `/cartelas/vista?plano=${encodeURIComponent(plano)}`,
  calloutVista: (pid, plano) => `${BASE}/api/proyectos/${encodeURIComponent(pid)}`
    + `/callouts/vista?plano=${encodeURIComponent(plano)}`,
  transiciones: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/transiciones`,
  sonido: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/sonido`,
  efectos: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/sonido/efectos`,
  sonidoArco: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/sonido/arco`,
  sonidoBanda: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/sonido/banda`,
  sonidoVetados: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/sonido/vetados`,
  direccion: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/direccion`,
  direccionProponer: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/direccion/proponer`,
  notasMontaje: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/montaje/notas`,
  enlaces: () => `${BASE}/api/enlaces`,
  enlace: eid => `${BASE}/api/enlaces/${encodeURIComponent(eid)}`,
  catalogo: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/catalogo`,
  catalogoProponer: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/catalogo/proponer`,
  conservacion: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/conservacion`,
  conservacionAnalizar: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}`
    + `/conservacion/analizar`,
  conservacionAplicar: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}`
    + `/conservacion/aplicar`,
  // referencias de estilo dibujadas a proposito, en el banco global del canal
  moodboard: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/moodboard`,
  moodboardAprobar: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}`
    + `/moodboard/aprobar`,
  // Un clic: deduce los sitios del guion y construye los que falten
  escenarios: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/escenarios`,
  reales: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/reales`,
  realesTraer: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/reales/traer`,
  frames: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/frames`,
  framesEtiquetar: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/frames/etiquetar`,
  framesProponer: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/frames/proponer`,
  framesSeleccion: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/frames/seleccion`,
  // Presets de canal: lo que se decide una vez por canal y se repite en cada
  // video. No son los presets de voz de /api/presets, que estan escritos en el
  // codigo y no se pueden ni crear ni borrar.
  regrabarSeccion: (pid, sid) => `${BASE}/api/proyectos/${encodeURIComponent(pid)}`
    + `/voz/secciones/${encodeURIComponent(sid)}/regrabar`,
  vozDescribir: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/voz/describir`,
  trabajosVivos: () => `${BASE}/api/trabajos`,
  /* `ligero` deja fuera el prompt de cada plano: son ~17 KB por plano, 3,74 MB
     de los 3,88 MB de la respuesta en un vídeo de 232. Lo pide quien solo va a
     contar y ordenar (el marco de light durante la tanda, que pregunta una vez
     por imagen generada); quien pinta el botón de «ver el prompt» no lo pasa. */
  planosHechos: (pid, ligero) => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/assets/hechos`
    + (ligero ? '?ligero=1' : ''),
  presetsCanal: () => `${BASE}/api/presets-canal`,
  presetCanal: id => `${BASE}/api/presets-canal/${encodeURIComponent(id)}`,
  /* CON EL SELLO DEL `modificado`, por lo mismo que las muestras sueltas:
     rehacer una parte deja el MISMO nombre de fichero apuntando a otra imagen, y
     sin el sello el navegador sigue enseñando la de antes. Se notó al recomponer
     las muestras: la ficha ya tenía las seis y la tarjeta seguía con el 2×2. */
  presetCanalMiniatura: (id, sello) => `${BASE}/api/presets-canal/${encodeURIComponent(id)}`
    + `/miniatura${sello ? `?v=${encodeURIComponent(sello)}` : ''}`,
  personajes: pid => `${BASE}/api/proyectos/${pid}/personajes`,
  personajeHoja: pid => `${BASE}/api/proyectos/${pid}/personajes/hoja`,
  personaje: (pid, id) => `${BASE}/api/proyectos/${pid}/personajes/${encodeURIComponent(id)}`,
  presetCanalFichero: (id, archivo) => `${BASE}/api/presets-canal/${encodeURIComponent(id)}`
    + `/fichero/${String(archivo).split('/').map(encodeURIComponent).join('/')}`,
  presetCanalPapelera: id => `${BASE}/api/presets-canal/papelera/${encodeURIComponent(id)}`,
  presetCanalRestaurar: id => `${BASE}/api/presets-canal/papelera/${encodeURIComponent(id)}/restaurar`,
  presetCanalAplicar: (pid, id) => `${BASE}/api/proyectos/${encodeURIComponent(pid)}`
    + `/presets-canal/${encodeURIComponent(id)}/aplicar`,
  // La cuenta de segundos a palabras, planos y dolares. Sin proyecto: se
  // pregunta antes de que exista ninguno.
  estimacion: () => `${BASE}/api/estimacion`,
  // modo light: la galeria de presets de canal
  presetsLight: () => `${BASE}/api/presets-light`,
  presetLight: id => `${BASE}/api/presets-light/${encodeURIComponent(id)}`,
  presetLightPlan: () => `${BASE}/api/presets-light/plan`,
  presetLightRegenerar: id => `${BASE}/api/presets-light/${encodeURIComponent(id)}/regenerar`,
  // el buzón donde esperan las imágenes de apoyo antes de que exista el taller
  // EL REPASO: lo que se escribe MIRANDO el vídeo montado. Las notas viven en
  // su fichero y no en los params (comentar no puede dejar el vídeo obsoleto);
  // lo que toca las firmas es `repasoAplicar`.
  repaso: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}/repaso`,
  repasoNota: (pid, nid) => `${BASE}/api/proyectos/${encodeURIComponent(pid)}`
    + `/repaso/${encodeURIComponent(nid)}`,
  imagenesRepaso: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}`
    + `/repaso/imagenes`,
  imagenRepaso: (pid, nombre) => `${BASE}/api/proyectos/${encodeURIComponent(pid)}`
    + `/repaso/imagenes/${encodeURIComponent(nombre)}`,
  repasoAplicar: pid => `${BASE}/api/proyectos/${encodeURIComponent(pid)}`
    + `/repaso/aplicar`,
  imagenesLight: () => `${BASE}/api/presets-light/imagenes`,
  imagenLight: nombre => `${BASE}/api/presets-light/imagenes/${encodeURIComponent(nombre)}`,
};

function consulta(pares) {
  return Object.entries(pares)
    .filter(([, valor]) => valor !== undefined && valor !== null && valor !== '')
    .map(([clave, valor]) => `${encodeURIComponent(clave)}=${encodeURIComponent(valor)}`)
    .join('&');
}

async function pedir(url, opciones) {
  const cfg = Object.assign({ headers: {} }, opciones || {});
  if (cfg.cuerpo !== undefined) {
    /* UN FormData VIAJA TAL CUAL. Serializarlo a JSON da «{}» —sus campos no
       son propiedades— así que el fichero se perdía en silencio y el servidor
       recibía un cuerpo vacío. Y la cabecera la pone el navegador: escribirla a
       mano deja el multipart sin su `boundary`. */
    if (cfg.cuerpo instanceof FormData) {
      cfg.body = cfg.cuerpo;
    } else {
      cfg.body = JSON.stringify(cfg.cuerpo);
      cfg.headers['Content-Type'] = 'application/json';
    }
    delete cfg.cuerpo;
  }
  let respuesta;
  try {
    respuesta = await fetch(url, cfg);
  } catch (e) {
    throw new Error(`no hay respuesta del servidor (${url}): ${e.message}`);
  }
  const crudo = await respuesta.text();
  let datos = null;
  if (crudo) {
    try { datos = JSON.parse(crudo); } catch (e) { datos = null; }
  }
  if (!respuesta.ok) {
    const detalle = (datos && (datos.error || datos.mensaje)) || crudo.slice(0, 400)
      || `HTTP ${respuesta.status}`;
    throw new Error(detalle);
  }
  if (datos && datos.error) throw new Error(datos.error);
  return datos === null ? {} : datos;
}

/* Ficheros del proyecto (plan.json, guion.json, capas svg...). Se cachean por
   URL: llevan la version en la ruta, asi que una version nueva es otra URL. */
const CACHE_ARCHIVOS = new Map();

/* ------------------------------------------------------------------ estado */

/* Los `id` son los del grafo del servidor y NO se tocan (ingesta, callouts...):
   renombrarlos invalidaria el estado de todos los proyectos guardados. El
   `nombre` es lo unico que ve el usuario, y va alineado con su pestana para que
   la misma cosa no tenga dos nombres en pantalla: el paso 'ingesta' se ENSEÑA
   como «Origen» y el paso 'callouts' como «Rotulos», que es como se llama todo
   lo que hay dentro de su pantalla. */
const PASOS_BASE = [
  { id: 'ingesta', nombre: 'Origen', depende_de: [] },
  { id: 'brief', nombre: 'Brief', depende_de: ['ingesta'] },
  { id: 'guion', nombre: 'Guion', depende_de: ['ingesta', 'brief'] },
  { id: 'voz', nombre: 'Voz', depende_de: ['guion'] },
  { id: 'revision_audio', nombre: 'Revisión', depende_de: ['voz'] },
  { id: 'assets', nombre: 'Vídeo', depende_de: ['guion', 'voz'] },
  { id: 'callouts', nombre: 'Subtítulos', depende_de: ['assets'] },
  { id: 'render', nombre: 'Render', depende_de: ['callouts'] },
];

/* LAS CINCO PESTAÑAS SON LAS PARADAS DEL MODO LIGHT, con la voz aparte
 * (02-09-2026). El modo editor recorría otra tubería —Origen
 * con un vídeo de YouTube, el guion sin material, el render en su pestaña— y
 * se había quedado viejo respecto al modo light, que es el que se usa. Ahora
 * las dos pantallas recorren LAS MISMAS TANDAS del servidor (`TANDAS_LIGHT`
 * en app.py: guion, voz, video, render), en el mismo orden; lo que las
 * distingue es que aquí cada tanda se desglosa en sus tareas y cada tarea en
 * sus ajustes.
 *
 *     encargo    lo que se decide antes de escribir: estilo, duración, material
 *                                      → pie: «Generar el guion»    (tanda guion)
 *     guion      el texto, bloque a bloque, y las tareas que lo escriben
 *                                      → pie: «Generar el audio»    (tanda voz)
 *     voz        la toma y su revisión por secciones
 *                                      → pie: «Generar las imágenes» (tanda video)
 *     imagenes   reparto, estilo, cartelas, dirección, piezas, planos, y las
 *                imágenes una a una    → pie: «Montar el vídeo»     (tanda render)
 *     video      subtítulos, grafismo y sonido, el MP4 y el repaso
 *
 * Agrupan pasos del grafo SIN tocar sus identificadores (siguen siendo ingesta,
 * brief, guion...). La numeracion que se ve es la de esta lista; el desbloqueo
 * sigue siendo el del grafo, paso a paso.
 *
 * 'pasos' son los que se PINTAN, con su cabecera y su panel. 'tambien' son
 * pasos que la pestana necesita vivos -- se leen sus fichas, se siguen sus
 * trabajos, cuentan para el estado -- pero que no tienen pantalla propia. El
 * brief y la ingesta viven en el Encargo, que es un panel propio (`panel`) y
 * no la cabecera de ningún paso: sus mandos son las decisiones del vídeo, y la
 * ingesta es una tarjeta más —el vídeo de origen— que se rellena sola con el
 * enlace de YouTube que haya entre el material. `callouts` va en el Vídeo como
 * la primera tarjeta del montaje, porque es lo primero que se pone encima de
 * los planos; el paso sigue existiendo en el grafo, se sella aparte y
 * conserva su version y su conservar.
 *
 * `receta` es la pestaña del servidor cuyas tareas opcionales se ajustan aquí,
 * `tanda` la que genera el contenido de ESTA pestaña, y `siguiente` la que se
 * lanza desde el pie para pasar a la parada siguiente, igual que en el light.
 *
 * Lo que NO se ha hecho, a proposito: borrar el paso 'brief' del grafo. Su
 * firma encadena la del guion, asi que quitarlo obsoletaria el guion de TODOS
 * los proyectos guardados en cascada hasta el render. Mover la pantalla no
 * cuesta nada; mover el paso es una tanda entera con migracion. */
const PESTANAS = [
  { id: 'encargo', nombre: 'Encargo', pasos: [], tambien: ['ingesta', 'brief'],
    receta: null, tanda: null,
    siguiente: { tanda: 'guion', pestana: 'guion', texto: 'Generar el guion' } },
  { id: 'guion', nombre: 'Guion', pasos: ['guion'], tambien: ['brief'],
    receta: 'guion', tanda: 'guion',
    siguiente: { tanda: 'voz', pestana: 'voz', texto: 'Generar el audio' } },
  // Voz y Revision son la misma decision partida en dos: generas la toma, la
  // escuchas, y o la das por buena o la comentas. Los PASOS siguen siendo dos
  // (sellar sin regrabar depende de eso), pero la pantalla es una.
  { id: 'voz', nombre: 'Voz', pasos: ['voz', 'revision_audio'],
    receta: 'voz', tanda: 'voz',
    siguiente: { tanda: 'video', pestana: 'imagenes', texto: 'Generar las imágenes' } },
  /* IMÁGENES = la tanda 'video' del modo light: todo lo que hace falta para
     MIRAR el vídeo sin montarlo, y la pantalla para mirarlo escena a escena.
     Los subtítulos ('callouts') ya no están aquí: en Imágenes se mira el
     DIBUJO y nada más, y lo que se monta encima es del Vídeo (ver
     TANDAS_LIGHT en app.py). */
  { id: 'imagenes', nombre: 'Imágenes', pasos: ['assets'],
    receta: 'video', tanda: 'video',
    siguiente: { tanda: 'render', pestana: 'video', texto: 'Montar el vídeo' } },
  /* VÍDEO = la tanda 'render': pone al día los subtítulos, trae la música y
     los efectos y monta el MP4. Después, el repaso sobre el vídeo montado. */
  { id: 'video', nombre: 'Vídeo', pasos: ['render'], tambien: ['callouts'],
    receta: 'render', tanda: 'render', siguiente: null },
];

/* El id de pestana viaja en el hash de la URL. Los ids de antes —'origen',
   'assets', 'render' y el '#callouts' de hasta el 20-08— siguen valiendo: un
   enlace guardado o el boton de atras del telefono no pueden caer en el
   Encargo sin decir nada. */
const PESTANAS_VIEJAS = {
  origen: 'encargo', callouts: 'video', assets: 'imagenes', render: 'video',
};

function pestanaDe(id) { return PESTANAS.find(p => p.id === id) || PESTANAS[0]; }

/* Todos los pasos que viven en una pestana, se pinten o no. */
function pasosDe(pestana) {
  return (pestana.pasos || []).concat(pestana.tambien || []);
}

/* Estado de una pestana: el del peor de sus pasos. Con ingesta y brief juntos,
   la pestana no puede decir 'listo' mientras al brief le falte correr. */
const GRAVEDAD = ['error', 'ejecutando', 'obsoleto', 'bloqueado', 'pendiente', 'listo'];

/* Estados de un paso que NO tiñen su pestaña, porque no son trabajo del
   usuario: la revision de audio se sella SOLA (y gratis) al pasar a Assets, asi
   que su 'obsoleto' tras regrabar la voz encendia un punto naranja sobre una
   pestaña donde no habia nada que hacer. Sus errores y su 'ejecutando' si
   cuentan: eso si hay que verlo. */
const NO_TINE_PESTANA = {
  revision_audio: ['obsoleto', 'pendiente', 'bloqueado'],
  /* Y los rótulos, desde que comparten pestaña con los planos: rehacer UN plano
     deja su escena obsoleta en callouts por cascada, así que la pestaña Vídeo
     viviría en naranja permanente mientras se repasan los planos —que es
     exactamente cuando no hay nada que hacer todavía en los rótulos—. Su
     'obsoleto' se dice DENTRO, en su tarjeta, que es donde se arregla. Sus
     errores y su 'ejecutando' sí tiñen: eso sí hay que verlo. */
  callouts: ['obsoleto', 'pendiente', 'bloqueado'],
};

function estadoPestana(pestana) {
  const estados = pasosDe(pestana)
    .map(p => [p, pasoDe(p).estado || 'pendiente'])
    .filter(([p, e]) => !(NO_TINE_PESTANA[p] || []).includes(e))
    .map(([, e]) => e);
  for (const nivel of GRAVEDAD) {
    if (estados.includes(nivel)) return nivel;
  }
  return estados[0] || 'pendiente';
}

/* EL SEMAFORO DE TODA LA INTERFAZ, al nivel que sea (pestaña, tarjeta,
   plegable): verde = hecho y al dia · naranja = obsoleto o a medias ·
   rojo = error · gris = aun sin generar. Un unico sitio, para que ninguna
   pantalla invente su propia paleta de estados — y ningun aviso de «falta X»
   se pinta salvo que de verdad haya algo a medias u obsoleto. */
function pastillaEstado(estado, texto) {
  const clase = { ok: 'ok', parcial: 'obsoleto', error: 'error' }[estado] || '';
  const defecto = { ok: 'hecho', parcial: 'a medias', error: 'error' }[estado]
    || 'sin generar';
  return h('span', { clase: `pastilla ${clase}`.trim() }, texto || defecto);
}

const APP = {
  pid: null,
  proyecto: null,
  proyectos: [],
  pasos: PASOS_BASE.map(p => Object.assign({ estado: 'bloqueado' }, p)),
  activa: 'encargo',       // id de PESTANAS, no de paso
  fichas: {},        // paso -> ficha completa
  borrador: {},      // paso -> params en edicion
  sucio: {},         // paso -> hay cambios sin guardar
  sub: {},           // paso -> subpestana activa
  trabajos: {},      // paso -> {id,estado,progreso,mensaje,t0,error}
  seguimientos: {},  // paso -> {fuente, sondeo, tic}
  voces: null,
  presets: null,
  vista: {},         // estado volatil de cada panel (busquedas, seleccion...)
  cli: null,         // catalogo de /api/ajustes-cli: modelos, esfuerzos, factores
  comparativas: {},  // paso -> comparativa del servidor para el ultimo tamano pedido
};

// Duraciones observadas: alimentan la estimacion de tiempo de cada boton.
const ESTIMACION_BASE = {
  ingesta: 150, brief: 2, guion: 70, voz: 60, revision_audio: 110,
  assets: 300, callouts: 90, render: 240,
};

/* Historial local en localStorage. Habia DOS historiales que no se hablaban: el
   del servidor (por paso, por tamano de entrada y por combinacion de modelo y
   esfuerzo, con todos los proyectos dentro) y este, que mete en la misma mediana
   la ingesta de un video de 5 minutos y la de uno de 40.
   Ahora este SOLO cubre los pasos que no usan el CLI (ingesta, voz, assets,
   render...), donde el tiempo no depende de ningun ajuste elegible y sirve como
   plan B mientras el servidor no dice nada. Todo lo que usa el CLI se estima con
   el backend, que es quien conoce el ajuste y el historico entero. */
function historialDuraciones() {
  try { return JSON.parse(localStorage.getItem('estudio.duraciones') || '{}'); }
  catch (e) { return {}; }
}

function anotarDuracion(paso, segundos) {
  if (!(segundos > 0)) return;
  // los pasos con CLI ya los anota el servidor al terminar, con su ajuste y su
  // tamano: duplicarlos aqui solo crearia una segunda verdad peor informada
  if (usaCLI(paso)) return;
  const todas = historialDuraciones();
  const lista = (todas[paso] || []).concat(Math.round(segundos)).slice(-8);
  todas[paso] = lista;
  localStorage.setItem('estudio.duraciones', JSON.stringify(todas));
}

function estimacion(paso) {
  // en los pasos con CLI manda la cifra del servidor para el ajuste elegido
  const delServidor = filaAjusteActual(paso);
  if (delServidor && delServidor.segundos > 0) return delServidor.segundos;
  const lista = (historialDuraciones()[paso] || []).slice().sort((a, b) => a - b);
  if (!lista.length) return ESTIMACION_BASE[paso] || 60;
  return lista[Math.floor(lista.length / 2)];
}

function pasoDe(id) { return APP.pasos.find(p => p.id === id) || { id, nombre: id, depende_de: [] }; }

function descendientesDe(id) {
  const directos = APP.pasos.filter(p => (p.depende_de || []).includes(id)).map(p => p.id);
  const vistos = new Set();
  const cola = directos.slice();
  while (cola.length) {
    const actual = cola.shift();
    if (vistos.has(actual)) continue;
    vistos.add(actual);
    APP.pasos.filter(p => (p.depende_de || []).includes(actual)).forEach(p => cola.push(p.id));
  }
  return APP.pasos.filter(p => vistos.has(p.id)).map(p => p.id);
}

function nombreDe(id) {
  // el agente de capturas y la guia de estilo no son pasos del grafo pero si
  // lanzan trabajos, y salen por su nombre en avisos y en el faro
  return NOMBRES_FUERA_DEL_GRAFO[id] || pasoDe(id).nombre || id;
}

/* ------------------------------------------------------------------ avisos */

let relojToast = null;

function toast(texto, malo) {
  const n = $('#toast');
  n.textContent = texto;
  n.classList.toggle('malo', !!malo);
  n.classList.add('ver');
  clearTimeout(relojToast);
  relojToast = setTimeout(() => n.classList.remove('ver'), malo ? 6000 : 3000);
}

/* Todo fallo acaba aqui: se ve en la propia pestana, no solo en consola. En la
   caja va la frase en castellano que manda el servicio y el volcado queda
   plegado detras de 'detalle tecnico'; el aviso flotante solo lleva la frase,
   que es lo unico que cabe leer de reojo. */
/* EL MOTIVO DE UN FALLO SOBREVIVE AL REPINTADO.
   Lo que pasaba: al fallar un trabajo, `seguirTrabajo` pintaba el motivo en el
   hueco del botón pulsado y acto seguido llamaba a `refrescarTodo()`, que
   repinta el panel entero — o sea que borraba lo que se acababa de escribir. Lo
   único que quedaba era la cabecera del paso, arriba del todo, así que la barra
   decía «el motivo, aquí debajo» y el motivo salía a una pantalla de distancia.
   Es el mismo motivo por el que la ranura de la barra vive fuera del DOM
   (RANURAS): el panel se rehace bajo los pies. */
const ERRORES = {};

function mostrarError(paso, error) {
  const crudo = error && error.message ? error.message : String(error);
  ERRORES[paso] = crudo;
  pintarError(paso);
  toast(partirError(crudo).titular, true);
  console.error(error);
}

/* Vuelve a poner el motivo en el hueco del botón que se pulsó. Se llama al
   fallar y DESPUÉS de cada repintado del panel. */
function pintarError(paso) {
  const crudo = ERRORES[paso];
  if (!crudo) return;
  const caja = huecoDeError(paso);
  if (!caja) return;
  vaciar(caja);
  caja.appendChild(cajaError(crudo));
  caja.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

/* Dónde se pinta el motivo de un fallo: junto al botón que se pulsó.
   Un paso puede tener varios lanzadores repartidos por la pantalla (en Assets
   hay uno por tarjeta) y el primero del documento casi nunca es el que has
   tocado. Se busca dentro del mismo lanzador que la barra activa; si no hay
   ninguno —trabajo reenganchado tras recargar—, el de la cabecera del paso. */
function huecoDeError(paso) {
  const ranura = ranuraActiva(paso);
  const cerca = ranura && ranura.parentElement
    && ranura.parentElement.querySelector(`[data-error="${paso}"]`);
  return cerca || $('#panel').querySelector(`[data-error="${paso}"]`);
}

function limpiarError(paso) {
  delete ERRORES[paso];
  // TODOS: si no, un fallo anterior se queda pintado en otro lanzador del mismo
  // paso mientras el de aquí arranca, y se lee como si acabara de fallar
  $('#panel').querySelectorAll(`[data-error="${paso}"]`).forEach(vaciar);
}

/* ------------------------------------------------------------------ trabajos */

/* `alAvanzar` se llama en CADA actualizacion del trabajo, no solo al acabar.
   Es lo que permite que una pantalla se vaya rellenando mientras el trabajo
   corre -- los planos segun se generan --
   en vez de estar en blanco varios minutos y aparecer todos de golpe. */
/* CUÁNDO EMPEZÓ A CONTAR el reloj de un trabajo. -> ms
 *
 * Se CONSERVA el arranque que ya teníamos, y sólo si es de ESTE trabajo:
 *
 *   - al retomar uno que venía corriendo (otra pestaña del navegador, o una
 *     recarga a media ejecución), `reengancharTrabajos` ya dedujo el arranque
 *     de los segundos que lleva. Pisarlo reiniciaba el reloj a cero y hacía que
 *     un paso de media hora dijera «lleva 3s».
 *   - la espera del clic (`esperando`) ocupa la ranura con `id: null` antes de
 *     que el servidor conteste con el suyo. Es el MISMO trabajo, y el reloj
 *     tiene que arrancar en el clic: lo que llevas esperando es desde que
 *     pulsaste, no desde que el servidor se dio por enterado.
 *
 * Y SE TIRA SI ES DE OTRO, que es lo que faltaba. Sin comparar el id, el
 * segundo trabajo de un mismo paso heredaba el reloj del primero: se lanzaba
 * una regeneración y la pantalla decía «3m 51s» recién pulsada, porque contaba
 * desde el cambio anterior. Se vio en el modo light, que es donde más se nota
 * —`preset_light` es UNA ranura fija por la que pasan todos sus trabajos, uno
 * detrás de otro— pero le pasaba a cualquier paso que se lance dos veces. */
function arranqueDe(antes, tid) {
  const previo = (antes || {}).inicio;
  if (!previo) return Date.now();
  const suyo = (antes || {}).id;
  const esDeEste = suyo === tid || suyo === null || suyo === undefined;
  return esDeEste ? previo : Date.now();
}

function seguirTrabajo(paso, tid, alTerminar, alAvanzar) {
  soltarSeguimiento(paso);
  const seguimiento = {};
  APP.seguimientos[paso] = seguimiento;
  APP.trabajos[paso] = Object.assign({
    id: tid, estado: 'ejecutando', progreso: 0, mensaje: 'lanzando…',
  }, APP.trabajos[paso], {
    id: tid, estado: 'ejecutando',
    inicio: arranqueDe(APP.trabajos[paso], tid),
  });
  pintarTrabajo(paso);

  seguimiento.tic = setInterval(() => pintarTrabajo(paso), 500);

  const aplicar = datos => {
    if (!datos || APP.seguimientos[paso] !== seguimiento) return;
    const actual = APP.trabajos[paso] || {};
    APP.trabajos[paso] = Object.assign({}, actual, datos,
      { id: tid, inicio: actual.inicio, muestras: actual.muestras });
    anotarAvance(paso, datos.progreso);
    pintarTrabajo(paso);
    // lo que se esta produciendo se ve mientras se produce
    if (alAvanzar) { try { alAvanzar(datos); } catch (e) { console.error(e); } }
    // el medidor de la cabecera se mueve con el mismo flujo que la barra: lo
    // que se esta gastando se ve mientras se gasta, no al terminar
    refrescarCoste();
    if (['listo', 'error', 'cancelado'].includes(datos.estado)) terminar(datos);
  };

  const terminar = async datos => {
    soltarSeguimiento(paso);
    refrescarCoste(true);
    const segundos = datos.segundos || (Date.now() - (APP.trabajos[paso].inicio || Date.now())) / 1000;
    if (datos.estado === 'listo') {
      anotarDuracion(paso, segundos);
      // LO PUBLICO, no el mensaje interno del paso: lo que se dice en el
      // aviso es lo mismo que dice la barra mientras corre.
      const dicho = avancePublico(datos) || 'terminado';
      toast(`${nombreDe(paso)}: ${dicho} (${duracionCorta(segundos)})`);
    } else if (datos.estado === 'error') {
      mostrarError(paso, datos.error || datos.mensaje || 'el trabajo ha fallado');
    } else {
      toast(`${nombreDe(paso)}: cancelado`, true);
    }
    try {
      if (alTerminar) await alTerminar(datos);
      else await refrescarTodo();
    } catch (e) { mostrarError(paso, e); }
  };

  // SSE si se puede; si el navegador o el servidor no lo sirven, sondeo.
  let vivo = false;
  try {
    const fuente = new EventSource(API.eventos(tid));
    seguimiento.fuente = fuente;
    const recibir = ev => {
      vivo = true;
      try { aplicar(JSON.parse(ev.data)); } catch (e) { /* latido sin cuerpo */ }
    };
    // el servicio nombra sus eventos ('progreso' y 'fin'), y un evento con
    // nombre NO llega a onmessage: hay que escucharlos ademas por su nombre
    fuente.onmessage = recibir;
    fuente.addEventListener('progreso', recibir);
    fuente.addEventListener('fin', recibir);
    fuente.onerror = () => {
      if (APP.seguimientos[paso] !== seguimiento) return;
      fuente.close();
      seguimiento.fuente = null;
      if (!seguimiento.sondeo) arrancarSondeo();
    };
  } catch (e) {
    arrancarSondeo();
  }
  // Red de seguridad: si en 4 s el SSE no ha dicho nada, se sondea igualmente.
  setTimeout(() => { if (!vivo && APP.seguimientos[paso] === seguimiento) arrancarSondeo(); }, 4000);

  function arrancarSondeo() {
    if (seguimiento.sondeo || APP.seguimientos[paso] !== seguimiento) return;
    seguimiento.sondeo = setInterval(async () => {
      try { aplicar(await pedir(API.trabajo(tid))); }
      catch (e) { /* el servidor puede tardar en publicar el trabajo */ }
    }, 1000);
  }
}

function soltarSeguimiento(paso) {
  const s = APP.seguimientos[paso];
  if (!s) return;
  if (s.fuente) s.fuente.close();
  if (s.sondeo) clearInterval(s.sondeo);
  if (s.tic) clearInterval(s.tic);
  delete APP.seguimientos[paso];
}

function trabajando(paso) {
  const t = APP.trabajos[paso];
  return !!t && ['pendiente', 'ejecutando'].includes(t.estado);
}

/* '3 min 20 s' -> 200. Es como escribe los tiempos pasos/estadisticas.py. */
function segundosDeTexto(crudo) {
  const texto = String(crudo || '');
  const minutos = texto.match(/(\d+)\s*min/);
  const segundos = texto.match(/(\d+)\s*s\b/);
  if (!minutos && !segundos) return null;
  return (minutos ? Number(minutos[1]) * 60 : 0) + (segundos ? Number(segundos[1]) : 0);
}

/* El backend manda en el mensaje del trabajo su propia estimacion y de donde
   sale ('... 1 min 20 s de 3 min 20 s (estimacion, no medida: historial de 5
   ejecuciones)'). Aqui se separa para poder ensenarla como lo que es y no como
   una cuenta atras que parece medida. */
function leerAvance(crudo) {
  const texto = String(crudo || '');
  // el sello va al final y su contenido lleva parentesis dentro ('7
  // ejecucion(es)'), asi que se corta hasta el ultimo cierre, no hasta el primero
  const marca = texto.match(/\s*\(estimaci[oó]n,\s*no medida:\s*([\s\S]*)\)\s*$/i);
  const prevision = texto.match(/(?:\bde\b|se estimaron)\s+((?:\d+\s*min)(?:\s*\d+\s*s)?|\d+\s*s)\b/);
  let mensaje = (marca ? texto.slice(0, marca.index) : texto).trim();
  /* El backend mete el reloj DENTRO del mensaje («…; 6 s de 42 s») y la barra
     lo volvía a pintar debajo, y otra vez en la frase de la estimación: el
     mismo dato tres veces en un recuadro de cinco líneas. Aquí se le quita al
     mensaje, que se queda con lo único que no dice nadie más —QUÉ está
     haciendo—, y el tiempo lo pinta la barra una sola vez. */
  mensaje = mensaje.replace(
    /\s*[;·]\s*(?:lleva\s[\s\S]*|\d+\s*(?:min|s)\b[\s\S]*?\bde\s[\s\S]*)$/i, '').trim();
  return {
    mensaje,
    origen: marca ? marca[1].trim() : '',
    previsto: prevision ? segundosDeTexto(prevision[1]) : null,
  };
}

/* LO MISMO, PERO PARA ENSEÑAR. El modo light se graba y se publica, y la barra
   decía «3 de 7 · Los planos — plano S035 · 41 de 44»: eso es el plano de obra
   del Estudio y no tiene por qué salir en el vídeo. El servidor manda DOS
   mensajes por trabajo —`mensaje`, el de casa, y `publico`, el mismo tramo
   contado sin la cocina (`recetas.PUBLICO`)— y esto lee el segundo.

   NUNCA CAE EN EL PRIMERO. Si el servidor no manda `publico` —una versión
   vieja, una tarea que nadie ha dado de alta en la tabla— se dice «Trabajando…»
   y se calla: un enmascarado que falla tiene que fallar tapando de más, no
   destapando. Ese es todo el motivo de que esto no sea `x.publico || x.mensaje`. */
function avancePublico(trabajo) {
  const ficha = trabajo || {};
  const texto = String(ficha.publico || '').trim();
  if (texto) return texto;
  return ['pendiente', 'ejecutando'].includes(ficha.estado) ? 'Trabajando…' : '';
}

/* ---------------------------------------------------- proyeccion del restante
   Pasos cuya fraccion de progreso cuenta UNIDADES DE VERDAD: planos terminados,
   palabras sintetizadas, clips renderizados. En ellos el tiempo que falta se
   puede proyectar desde la propia ejecucion, que es una medida, no una
   estimacion: transcurrido / fraccion.

   En guion y guia_estilo NO: ahi la barra es un reloj sintetico
   (estadisticas.Avance) que interpola contra la estimacion previa, asi que
   proyectar desde ella devolveria esa misma estimacion. Seria circular, y ademas
   sonaria a medida cuando no lo es: una llamada al CLI es opaca hasta que
   contesta. */
;

/* Muestras de avance que se guardan. Con seis, el ritmo se calcula sobre un
   tramo reciente y no arrastra el de hace media hora. */
const MUESTRAS_PROYECCION = 6;

/* Se anota cada avance para poder proyectar con el ritmo RECIENTE y no con el
   medio: en assets el tramo de sets y el de planos no cuestan lo mismo, asi que
   un ritmo calculado desde el principio arrastra el tramo anterior. */
function anotarAvance(paso, fraccion) {
  const t = APP.trabajos[paso];
  if (!t) return;
  const valor = Number(fraccion);
  if (!(valor > 0)) return;
  if (!Array.isArray(t.muestras)) t.muestras = [];
  const ultima = t.muestras[t.muestras.length - 1];
  if (ultima && valor <= ultima.f) return;      // sin avance no hay muestra
  t.muestras.push({ t: Date.now(), f: valor });
  if (t.muestras.length > MUESTRAS_PROYECCION) t.muestras.shift();
}

/* Segundos que faltan segun esta ejecucion, o null si todavia no se puede
   decir con cara seria.

   SIEMPRE por diferencias, nunca dividiendo la fraccion entre el tiempo total.
   Al RETOMAR una generacion cortada, la fraccion incluye lo que se hizo en la
   pasada anterior pero el reloj arranca de cero: "van 57% en 1m 07s" daba un
   total de 1m 43s para algo que llevaba media hora hecha. Lo unico que se puede
   medir de esta pasada es lo que ha avanzado DESDE QUE MIRAMOS, asi que hasta
   tener dos muestras no se proyecta nada y manda la estimacion del historico. */
function pintarTrabajo(paso) {
  pintarFaro();
  /* NO HAY RANURA: la barra de un trabajo vive dentro de la pantalla que lo
     lanzo. Esto lo llama un temporizador cada medio segundo para que el reloj
     se mueva, asi que se refresca SOLO lo vivo --la barra y el coste-- y no la
     pantalla entera, que es lo que la hacia parpadear mientras generaba. */
  refrescarVivosLight();
}



async function cancelar(paso) {
  const t = APP.trabajos[paso];
  if (!t) return;
  try { await pedir(API.cancelar(t.id), { method: 'POST' }); toast('cancelación pedida'); }
  catch (e) { mostrarError(paso, e); }
}

/* En qué pestaña vive la barra de un trabajo. Los que no son un paso del grafo
   se lanzan desde la pestaña de su paso: los escenarios y el moodboard desde
   Assets, regrabar una sección desde Voz. */
const PESTANA_DE_TRABAJO = {
  escenarios: 'imagenes', catalogo_visual: 'imagenes',
  moodboard: 'imagenes', estilo: 'imagenes', guia_estilo: 'imagenes',
  regrabar_seccion: 'voz', voz_descrita: 'voz',
  etiquetar_frames: 'guion', proponer_frames: 'guion', tono: 'encargo',
  fuentes: 'guion',
  capturas_agente: 'imagenes', conservacion: 'imagenes',
  // Estos cuatro faltaban y por eso el faro los enseñaba como texto muerto:
  // sabías que algo iba por el 40% y no había forma de llegar a su barra.
  plan_callouts: 'video', plan_cartelas: 'imagenes',
  banda_sonora: 'video', efectos: 'video',
};

function pestanaDeTrabajo(paso) {
  // la tanda vive en la pestaña desde la que se lanzó (o se reenganchó)
  if (paso === CLAVE_RECETA) return TANDA_EN_MARCHA.pestana || null;
  if (PESTANA_DE_TRABAJO[paso]) return PESTANA_DE_TRABAJO[paso];
  const pestana = PESTANAS.find(p => (pasosDe(p) || []).includes(paso));
  return pestana ? pestana.id : null;
}

/* El faro es lo único que se ve desde CUALQUIER pestaña mientras algo corre, y
   ahora además lleva a donde está la barra. Antes era texto muerto: sabías que
   Assets iba por el 54% y tenías que acordarte de en qué pestaña mirarlo. */
function pintarFaro() {
  const activos = Object.entries(APP.trabajos).filter(([paso]) => trabajando(paso));
  const faro = vaciar($('#faro'));
  if (!activos.length) return;
  faro.append('⏳ ');
  activos.forEach(([paso, t], indice) => {
    const destino = pestanaDeTrabajo(paso);
    const texto = `${nombreDe(paso)} ${Math.round((t.progreso || 0) * 100)}%`;
    if (indice) faro.append(' · ');
    faro.appendChild(destino
      ? h('button', {
        clase: 'mini fantasma', title: `ir a ${nombreDe(paso)} y ver cómo va`,
        onclick: () => irA(destino),
      }, texto)
      : h('span', {}, texto));
  });
}

/* ------------------------------------------------------------------ acciones */

async function guardarParams(paso, silencioso) {
  limpiarError(paso);
  try {
    const datos = await pedir(API.params(APP.pid, paso), {
      method: 'PUT', cuerpo: { params: borradorDe(paso) },
    });
    APP.sucio[paso] = false;
    if (!silencioso) {
      const cambio = datos.cambiado !== undefined ? datos.cambiado : datos.cambio;
      const obsoletos = (datos.afectados || datos.obsoletos
        || (cambio ? descendientesDe(paso) : [])).filter(otro => otro !== paso);
      toast(cambio === false
        ? 'sin cambios que guardar'
        : `guardado${obsoletos.length ? ` · quedan obsoletos: ${obsoletos.map(nombreDe).join(', ')}` : ''}`);
      await refrescarTodo();
    } else {
      // Guardado SILENCIOSO (autoguardado): sin repintar el panel, que aqui se
      // esta tecleando y repintar tira el foco del campo. La ficha local se
      // pone al dia a mano y el siguiente repintado natural cuadra el resto.
      if (APP.fichas[paso]) {
        APP.fichas[paso].params = JSON.parse(JSON.stringify(borradorDe(paso)));
      }
      $('#panel').querySelectorAll(`[data-sucio="${paso}"]`)
        .forEach(nodo => nodo.classList.add('limpio'));
    }
    /* LO QUE EL MATERIAL DECIDE POR SU CUENTA, reflejado aquí. El servidor
       enruta un enlace de YouTube del material a la ingesta y la prosa escrita
       detrás al prompt general (`_origen_del_material`); la pantalla que acaba
       de guardarlo tiene que enseñarlo sin volver a leer el proyecto, o la
       tarjeta del origen seguiría diciendo «sin URL». */
    if (paso === 'guion' && datos && typeof datos.origen === 'string') {
      (datos.avisos || []).forEach(a => toast(a, true));
      if (datos.origen && APP.fichas.ingesta && !APP.sucio.ingesta) {
        APP.fichas.ingesta.params = Object.assign({}, APP.fichas.ingesta.params,
                                                  { url: datos.origen });
        if (APP.borrador.ingesta) APP.borrador.ingesta.url = datos.origen;
        const campo = $('#panel').querySelector('[data-campo="ingesta-url"]');
        if (campo && campo.value !== datos.origen) campo.value = datos.origen;
      }
      const servidos = (datos.params || {}).prompt_general;
      if (servidos && APP.fichas.guion && !borradorDe('guion').prompt_general) {
        borradorDe('guion').prompt_general = servidos;
        APP.fichas.guion.params.prompt_general = servidos;
      }
    }
    return datos;
  } catch (e) {
    mostrarError(paso, e);
    throw e;
  }
}

/* AUTOGUARDADO: la edicion ES la decision. Aqui no se confirma nada -- el paso
   siguiente usa siempre la ultima version --, asi que cada paso sucio se guarda
   solo al dejar de teclear. Lanzar un paso y Ctrl+S lo adelantan, y cerrar la
   pestana hace un ultimo intento con keepalive. */
const AUTOGUARDADO = { relojes: {}, espera_ms: 1200 };

/* Vuelca todos los pasos sucios menos `excepto` (el que se va a lanzar: sus
   params viajan en el cuerpo del POST). Un fallo no corta el volcado de los
   demas; queda pintado en la caja de error de su paso. */
async function guardarSucios(excepto) {
  for (const paso of Object.keys(APP.sucio)) {
    if (paso === excepto || !APP.sucio[paso]) continue;
    clearTimeout(AUTOGUARDADO.relojes[paso]);
    try { await guardarParams(paso, true); } catch (e) { /* ya pintado */ }
  }
}

function borradorDe(paso) {
  if (!APP.borrador[paso]) {
    const ficha = APP.fichas[paso] || {};
    APP.borrador[paso] = JSON.parse(JSON.stringify(ficha.params || {}));
  }
  return APP.borrador[paso];
}

/* Lo que hay que REHACER de verdad: lo obsoleto sin contar lo que no se ha
   generado nunca. Las dos cosas llegan juntas en unidades_obsoletas —son las dos
   trabajo pendiente— pero no se ofrecen igual: rehacer es volver a pagar algo
   que ya existe, y generar por primera vez ya tiene su propio botón. */
/* ============================================================ LOS DOS VERBOS
 *
 * TODO lo que produce algo se llama GENERAR o REGENERAR, y nada mas. Antes
 * habia 26 nomenclaturas repartidas en 54 botones — Montar, Planificar,
 * Decidir, Proponer, Dibujar, Construir, Traer, Colocar, Rehacer, Volver a…—
 * y encima la barra de la pestaña decia una cosa donde el boton decia otra:
 * «Grabar la locución» arriba y «Generar toma completa» abajo, para la misma
 * accion. Quien no se sabia el vocabulario tenia que aprenderselo dos veces.
 *
 * QUE SE LLAMA COMO. Salen de dos conjuntos que el nucleo ya sirve en la ficha
 * de cada paso, y de su resta:
 *
 *     S = unidades_sin_hacer     nunca se han producido
 *     O = unidades_obsoletas     estan sucias (S va DENTRO de O)
 *     V = O \ S                 producidas y ahora obsoletas  (obsoletasDe)
 *
 *   nunca hecho          S = todo        Generar
 *   hecho a medias       S parcial       Generar lo que falta (N)
 *   hecho y obsoleto     V > 0           Regenerar lo obsoleto (N)
 *   hecho y al dia       nada            Regenerar
 *
 * Y «lo que falta» NO se llama «lo obsoleto», que es la trampa facil: el propio
 * `unidades_sin_hacer` del nucleo lo dice por escrito —decir «ha quedado
 * obsoleto» de un plano que nunca se genero manda a buscar un cambio aguas
 * arriba que no ha habido—. Por eso son cuatro estados y no dos.
 */
/* LO QUE VA A COSTAR, CON LA CIFRA DELANTE.
 *
 * «lo que falta cuesta dinero» no permite decidir: la diferencia entre 0,04 $ y
 * 1,50 $ es exactamente la que hace pulsar o no pulsar, y era la unica que la
 * pantalla no daba.
 *
 * La cuenta sale de lo MEDIDO, no de la tabla por imagen: el gasto de verdad de
 * este pipeline son los tokens de ENTRADA (las referencias de estilo, de
 * reparto y de continuidad que lleva cada plano), y la tabla solo cubre la
 * imagen devuelta. Medido sobre un video real: 0,031 $ por plano contra los
 * 0,006 de la tabla, un factor de cinco. Por eso la
 * constante se llama MEDIDO y no PRECIO.
 */
const USD_POR_PLANO_MEDIDO = 0.031;

/* LOS CUATRO ESTADOS de un botón de trabajo, que es la regla de los dos verbos
   . Vivían aquí dentro de un `verboDe(ficha, opciones)` que no
   llamaba nadie: cada botón arma su texto con sus propios datos, que es lo que
   de verdad corre. Se retiró el ayudante y se deja escrita la tabla, que es lo
   que hay que respetar al añadir uno nuevo:

     S = unidades_sin_hacer      O = unidades_obsoletas (ver obsoletasDe)

     nunca hecho        Generar
     hecho a medias     Generar lo que falta (S)
     hecho y obsoleto   Regenerar lo obsoleto (O)
     hecho y al día     Regenerar

   El tercero y el cuarto NO se funden: el núcleo dice por escrito que llamar
   «obsoleto» a un plano que nunca se generó manda a buscar un cambio aguas
   arriba que no ha habido. */
/* ------------------------------------------------------------------ carga */

async function cargarProyectos() {
  const datos = await pedir(API.proyectos());
  APP.proyectos = datos.proyectos || datos || [];
  pintarBotonProyecto();
  if (!APP.proyectos.length) {
    // NO HACE FALTA NINGUN PROYECTO: se entra por la galeria de estilos y el
    // proyecto lo crea el propio encargo. Decirle «crea un proyecto» a quien
    // acaba de entrar seria pedirle el paso que la pantalla ya da por el.
    pintarLight();
    return;
  }
  const guardado = localStorage.getItem('estudio.pid');
  const elegido = APP.proyectos.find(p => p.id === guardado) || APP.proyectos[0];
  await abrirProyecto(elegido.id);
}

/* El proyecto abierto no se ensena en un <select>: cada fila lleva su propio
   boton de apartar, y eso un desplegable nativo no lo puede hacer. Ver
   abrirMenuProyectos. */
function pintarBotonProyecto() {
  const boton = $('#btn-proyecto');
  const abierto = APP.proyectos.find(p => p.id === APP.pid);
  vaciar(boton).append(
    h('span', { clase: 'nombre' },
      abierto ? (abierto.nombre || abierto.id) : 'sin proyecto'),
    h('span', { clase: 'flecha' }, '▾'));
}

async function abrirProyecto(pid) {
  APP.pid = pid;
  localStorage.setItem('estudio.pid', pid);
  pintarBotonProyecto();
  APP.fichas = {}; APP.borrador = {}; APP.sucio = {}; APP.vista = {};
  // la ranura elegida es de ESTE panel: en otro proyecto no significa nada
  Object.keys(RANURAS).forEach(paso => delete RANURAS[paso]);
  CACHE_ARCHIVOS.clear();
  Object.keys(APP.seguimientos).forEach(soltarSeguimiento);
  APP.trabajos = {};
  COSTE.datos = null;
  COSTE.ultima = 0;
  olvidarTandas();
  TANDA_EN_MARCHA.tanda = '';
  TANDA_EN_MARCHA.pestana = '';
  // las diapositivas y la cola de imagenes son de ESTE video: una nota en cola
  // de otro proyecto se dibujaria aqui
  pararPrevia();
  PREVIA.ficha = null;
  PREVIA.i = 0;
  COLA_IMG.espera = [];
  COLA_IMG.corriendo = [];
  COLA_IMG.fallo = {};
  pintarCoste();
  await refrescarTodo();
  await cargarBitacora();
}

async function refrescarTodo() {
  const datos = await pedir(API.proyecto(APP.pid));
  APP.proyecto = datos.proyecto || datos;
  const pasos = datos.pasos || (APP.proyecto && APP.proyecto.pasos) || [];
  if (pasos.length) {
    APP.pasos = pasos.map(p => Object.assign(
      { depende_de: (PASOS_BASE.find(b => b.id === p.id) || {}).depende_de || [] }, p));
  }
  const nombre = (APP.proyecto && (APP.proyecto.nombre || APP.proyecto.id)) || APP.pid;
  $('#meta-proyecto').innerHTML = '';
  $('#meta-proyecto').append(
    h('b', {}, nombre),
    ` · ${APP.pasos.filter(p => p.estado === 'listo').length}/${APP.pasos.length} pasos listos`);
  pintarPestanas();
  // La barra de la pestaña dice qué falta, así que se relee con el estado: sin
  // esto seguiría diciendo «3 sin hacer» después de haberlas hecho a mano. Y
  // el plan de cada tanda, por lo mismo.
  olvidarPestanas();
  olvidarTandas();
  await refrescarPestana(APP.activa);
  llenarFiltroBitacora();
  refrescarCoste(true);
  // lo que siguiera corriendo cuando se cerro la pestana vuelve a seguirse
  reengancharTrabajos();
}

/* LO QUE CORRE EN EL SERVIDOR NO SE PIERDE AL RECARGAR.
 *
 * Los trabajos viven en hilos del servicio, no en el navegador: cerrar la
 * pestaña o recargar no los mata. Lo que se perdía era el SEGUIMIENTO —la barra,
 * el relleno progresivo y lo que hay que hacer al terminar—, que sí vivía en
 * memoria del cliente. El efecto era exactamente el de haber perdido el proceso:
 * el trabajo seguía gastando y la pantalla no se enteraba de nada.
 *
 * Había un reenganche por paso, pero con dos agujeros: se llamaba SIN callbacks
 * —así que al volver no había relleno progresivo ni refresco al acabar— y
 * buscaba por `paso`, mientras que los trabajos que no son un paso del grafo
 * (escenarios, regrabar una sección, elegir voz) se registran con nombre propio
 * y su barra se pinta bajo ese nombre.
 *
 * Esto se engancha a la LISTA de trabajos vivos, que es la única fuente que los
 * conoce a todos, y le devuelve a cada uno los callbacks que tenía. */
const AL_REENGANCHAR = {
  escenarios: () => ({
    alTerminar: async () => { await refrescarTodo(); },
  }),
  // LA TANDA (la clave es CLAVE_RECETA, escrita en crudo porque ese const se
  // declara mas abajo y este objeto se evalua al cargar el fichero). La sigue
  // su propia ranura dentro de la pantalla (`reengancharTandaLight`), asi que
  // al terminar aqui solo hay que releer.
  receta: () => ({
    alTerminar: async () => {
      TANDA_EN_MARCHA.tanda = '';
      await refrescarTodo();
    },
  }),
  assets: () => ({ alTerminar: alTerminarAssets, alAvanzar: avanceAssets() }),
  regrabar_seccion: () => ({
    alTerminar: async () => { delete APP.vista.audio_revision; await refrescarTodo(); },
  }),
};

/* ¿ES UNA REGENERACION DE PLANOS? Lo dice el trabajo: `assets` y todas sus
   unidades son planos. Un `assets` completo no trae unidades, y uno de otra
   cosa --un personaje, un set-- no las trae de tipo escena, asi que ninguno de
   los dos se cuela aqui. */
function retomarColaDeImagenes(t) {
  const suyas = (t.unidades || []).filter(u => String(u).startsWith('escena:'));
  if (t.paso !== 'assets' || !suyas.length
      || suyas.length !== (t.unidades || []).length) return false;
  if (APP.seguimientos[CLAVE_VIDEO_LIGHT]) return true;   // ya se sigue
  // sin nota: de un trabajo vivo solo se sabe que planos lleva
  COLA_IMG.corriendo = suyas.map(u => ({ sid: String(u).slice('escena:'.length), nid: '' }));
  APP.trabajos[CLAVE_VIDEO_LIGHT] = Object.assign({}, t,
    { inicio: Date.now() - (t.segundos || 0) * 1000 });
  seguirTrabajo(CLAVE_VIDEO_LIGHT, t.id, async trabajo => {
    const tanda = COLA_IMG.corriendo.slice();
    /* AQUI NO SE MARCA NADA COMO HECHO. Al retomar tras una recarga solo se
       sabe QUE PLANOS lleva el trabajo, no de que nota salieron, y el visto es
       de la nota. Lo pone `refrescarLoDibujado` al releer el repaso: el
       servidor ya guardo el `regenerado` de cada una. */
    if (trabajo.estado === 'error') {
      tanda.forEach(sid => { COLA_IMG.fallo[sid] = trabajo.error || 'fallo'; });
    }
    if (trabajo.estado !== 'ejecutando') {
      COLA_IMG.corriendo = [];
      await refrescarLoDibujado();
      repintarVideo();
      soltarCola();
    }
  }, () => repintarVideo());
  return true;
}

async function reengancharTrabajos() {
  let vivos = [];
  try {
    vivos = listaDe((await pedir(API.trabajosVivos())).trabajos) || [];
  } catch (e) { return; }        // sin lista no se reengancha, pero no se rompe
  for (const t of vivos) {
    if (t.proyecto && t.proyecto !== APP.pid) continue;
    if (!['pendiente', 'ejecutando'].includes(t.estado)) continue;
    /* UNA REGENERACION DE IMAGENES SE RETOMA COMO LO QUE ES. Es un trabajo de
       `assets` como otro cualquiera, pero la pantalla de Imagenes lo enseña en
       la tarjeta de cada plano, no en la barra del paso: si se reengancha por
       su nombre, al recargar a media regeneracion el trabajo seguia corriendo
       en el servidor y la tarjeta volvia a decir «Regenerar imagen». */
    if (retomarColaDeImagenes(t)) continue;
    let clave = t.nombre || t.paso;
    /* LA TANDA SE RETOMA EN SU RANURA. El servidor la nombra por las pestañas
       que recorre ('generar:video+render'); la barra del editor vive en la
       ranura de la receta, y sin esto al recargar la tanda seguía corriendo
       en el servidor y la pestaña no la enseñaba en ningún sitio. */
    if (String(clave).startsWith('generar:')) {
      TANDA_EN_MARCHA.tanda = tandaDeNombre(clave);
      const suya = PESTANAS.find(p => p.tanda === TANDA_EN_MARCHA.tanda);
      TANDA_EN_MARCHA.pestana = suya ? suya.id : APP.activa;
      clave = CLAVE_RECETA;
    }
    if (!clave || APP.seguimientos[clave]) continue;
    APP.trabajos[clave] = Object.assign({}, t,
      { inicio: Date.now() - (t.segundos || 0) * 1000 });
    const ganchos = (AL_REENGANCHAR[clave] || (() => ({})))();
    seguirTrabajo(clave, t.id, ganchos.alTerminar, ganchos.alAvanzar);
  }
}

/* Pestanas que necesitan la ficha de OTRO paso para pintarse: el reproductor de
   callouts saca los planos de assets y el audio de voz, por ejemplo. */
const FICHAS_EXTRA = {
  // el Encargo escribe el MATERIAL en los params del paso «Origen», y
  // la duracion en los del brief: sin esas dos fichas no hay donde escribir
  ingesta: ['guion', 'assets'],
  // ingesta hace falta para saber cuantas palabras de transcript entran al CLI:
  // es la unidad con la que el servidor mide y estima este paso. Y assets,
  // porque el preset de ritmo lleva tambien la duracion de plano y la calidad,
  // que son params suyos: sin su ficha, guardar el preset dejaria fuera la
  // mitad de lo que dice llevar. Y la voz, porque «Cambiar con una frase» en
  // un bloque regraba SU seccion cuando ya hay toma.
  guion: ['brief', 'ingesta', 'assets', 'voz'],
  // brief no es opcional aqui: idiomaVideo() lee SU ficha para heredar el
  // idioma del video. Sin ella, entrar directo a Voz pedia el catalogo en 'es'
  // con un guion en ingles -- el bug exacto que la herencia vino a arreglar.
  voz: ['guion', 'brief'],
  revision_audio: ['voz', 'guion'],
  // assets y callouts comparten pestana desde el 20-08: cada uno sigue pidiendo
  // lo suyo, y el union lo hace pasosDe() al pintar
  assets: ['guion', 'voz'],
  callouts: ['assets', 'voz', 'revision_audio'],
  render: ['callouts', 'assets', 'voz', 'revision_audio'],
};

async function traerFicha(paso) {
  const ficha = await pedir(API.paso(APP.pid, paso));
  APP.fichas[paso] = ficha;
  if (!APP.sucio[paso]) delete APP.borrador[paso];
  /* El reenganche por paso vivia aqui y se ha ido a reengancharTrabajos():
     este miraba `ficha.trabajo`, que va por PASO, y registraba bajo esa clave.
     Un trabajo con nombre propio -- escenarios, regrabar una seccion -- se
     registraba entonces como 'assets' o 'voz' y su barra, que se pinta bajo su
     nombre, no aparecia nunca. Y se llamaba sin callbacks, asi que al volver de
     una recarga no habia relleno progresivo ni refresco al terminar. */
  return ficha;
}

/* Una pestana puede llevar mas de un paso (Origen = ingesta + brief) y ademas
   necesita las fichas de otros pasos para pintarse. */
async function refrescarPestana(id) {
  const pasos = pasosDe(pestanaDe(id));
  const extras = new Set();
  for (const paso of pasos) {
    for (const otro of FICHAS_EXTRA[paso] || []) {
      if (!pasos.includes(otro)) extras.add(otro);
    }
  }
  await Promise.all([...extras].map(async otro => {
    try { APP.fichas[otro] = await pedir(API.paso(APP.pid, otro)); }
    catch (e) { /* si falta, la pestana lo dice a su manera */ }
  }));
  for (const paso of pasos) {
    try {
      await traerFicha(paso);
    } catch (e) {
      APP.fichas[paso] = APP.fichas[paso] || null;
      toast(`no se ha podido leer el paso ${nombreDe(paso)}: ${e.message}`, true);
    }
  }
  pintarPanel();
}

/* ===================================================================== RECETAS
 *
 * «Entro en la pestaña, relleno, y genero en un solo clic.»
 *
 * Cada pestaña sabe hacer TODO lo suyo de una tirada: sus tareas en orden, y en
 * paralelo las que no dependen unas de otras. El orden no es estético — las
 * cartelas se deciden ANTES de generar los planos o se paga una imagen para
 * tirarla, y los rótulos DESPUÉS o el agente no tiene imágenes que mirar—, así
 * que lo lleva el servidor (pasos/recetas.py) y no esta pantalla.
 *
 * Dos botones y no uno, porque son dos intenciones distintas:
 *
 *   Generar lo que falta   se salta lo que ya está hecho y al día. Es el de
 *                          después de haber tocado tres cosas a mano: termina
 *                          la pestaña sin volver a pagar lo que ya estaba.
 *   Rehacer todo           lo hace todo otra vez, cueste lo que cueste. Se dice
 *                          lo que cuesta ANTES de pulsar.
 *
 * Y lo de siempre sigue estando: cada tarea conserva su botón, su ficha y su
 * revisión más abajo. Una receta no esconde nada, adelanta trabajo.
 */

const CLAVE_RECETA = 'receta';        // la ranura donde va la barra de la tanda

/* El CATÁLOGO de recetas es GLOBAL: qué tareas tiene cada pestaña y qué recetas
   hay guardadas no depende del vídeo abierto. Por eso vive aquí y no en
   APP.vista, que se vacía entero al cambiar de proyecto — ahí se perdía nada
   más arrancar, porque abrir el último proyecto es lo primero que pasa. */
const RECETAS = { catalogo: null, pidiendo: false };

function estadoRecetas() {
  if (!APP.vista.recetas) APP.vista.recetas = { porPestana: {}, pedido: {} };
  // el catálogo se lee del global; lo de la pestaña sí es de ESTE vídeo
  return Object.assign(APP.vista.recetas, { catalogo: RECETAS.catalogo });
}

async function cargarCatalogoRecetas() {
  if (RECETAS.catalogo || RECETAS.pidiendo) return RECETAS.catalogo;
  RECETAS.pidiendo = true;
  try {
    RECETAS.catalogo = await pedir(API.recetas());
  } catch (e) {
    // La interfaz nueva aguanta un backend viejo: sin este endpoint la pestaña
    // sigue funcionando entera, solo que sin el botón de una tirada.
    RECETAS.catalogo = { pestanas: [], recetas: [], por_defecto: {}, error: e.message };
  } finally {
    RECETAS.pidiendo = false;
  }
  return RECETAS.catalogo;
}

function olvidarPestanas() {
  const vista = estadoRecetas();
  vista.porPestana = {};
}

/* ==========================================================================
   LAS LLAMADAS A LA ACCIÓN: la presentación y los dos momentos en que se pide
   ==========================================================================

   Tres casillas independientes, y cada una con lo mismo dentro: una caja de
   texto donde se dice qué quieres que se diga. Se marcan las que se quieran:
   sólo la presentación, sólo el cierre, las tres o ninguna.

   LO QUE SE ESCRIBE ES UNA INDICACIÓN, no el texto final. El guion lo redacta
   con las palabras de ESTE vídeo, que es lo que hace que la misma indicación
   valga para todos y no suene calcada en dos seguidos.

   SON DEL VÍDEO, NO DEL PERSONAJE. Vivieron un rato dentro de la tarjeta del
   personaje y estaba mal: un canal sin personaje —que es la mayoría— se quedaba
   sin poder pedir nada. La voz en off pide igual aunque no haya nadie dibujado
   diciéndolo. Si el canal SÍ tiene personaje, es él quien las dice y esos
   bloques van marcados con `personaje: true`; eso no se pregunta, el personaje
   ES la voz.

   Y SE CONFIGURAN VÍDEO POR VÍDEO, no en el preset del canal. Es la decisión
   que más cambia entre dos vídeos del mismo canal —uno manda a una web, el
   siguiente pide una suscripción, el de después no pide nada— y guardarla en el
   estilo obligaba a acordarse de cambiarla en cada encargo. Las tres vienen
   apagadas: un vídeo no pide nada mientras nadie lo marque. */

const CTA_MOMENTOS = [
  { id: 'presentacion',
    nombre: 'Se presenta justo después de la intro',
    pista: 'en el primer bloque después del gancho, nunca en el gancho',
    etiqueta: 'Cómo quieres que se presente',
    ejemplo: 'di quién soy y que en este vídeo se va a ver cómo se hace esto; '
      + 'si les gusta, que le den al like, y empezamos',
    ayuda: 'Es el patrón, no el texto: el guion lo reescribe con lo que se '
      + 'enseñe en cada vídeo. Sencillo —quién eres y qué se va a ver—, sin '
      + 'currículum ni «emprendedor y creador de contenido».' },
  { id: 'cta_medio',
    nombre: 'Llamada a la acción a mitad del vídeo',
    pista: 'en el corte entre dos tramos, después de haber contado algo',
    etiqueta: 'Qué quieres que pida',
    ejemplo: 'que entre en mi web, donde tiene más información sobre esto' },
  { id: 'cta_final',
    nombre: 'Llamada a la acción al final',
    pista: 'en el último bloque, como despedida',
    etiqueta: 'Qué quieres que pida',
    ejemplo: 'que le dé a like y se suscriba, y que vea el vídeo de la semana '
      + 'pasada sobre lo mismo' },
];

/* LAS TRES VIENEN APAGADAS. Un vídeo no se presenta ni pide nada mientras nadie
   lo marque. */
function ctaPorDefecto() {
  return {
    presentacion: { puesto: false, texto: '' },
    cta_medio: { puesto: false, texto: '' },
    cta_final: { puesto: false, texto: '' },
  };
}

/* LA TARJETA, la misma en los tres sitios donde se decide: la ficha del estilo
   (el canal), el encargo de un vídeo nuevo y el Encargo del editor. Una decisión
   escrita en tres pantallas distintas se separa; escrita una vez, no.

   `alCambiar` avisa de que hay algo que guardar; `repintar` vuelve a dibujar la
   pantalla que la contiene, y sólo lo llaman la casilla y el desplegable —los
   dos cambian lo que se ve—. La caja de texto no repinta: repintar mientras se
   escribe se come el foco. */
function bloqueCTA(ficha, opciones) {
  const op = opciones || {};
  const alCambiar = op.alCambiar || (() => {});
  const repintar = op.repintar || (() => {});
  const caja = h('div', { clase: 'cta-bloque' });

  CTA_MOMENTOS.forEach(m => {
    if (!ficha[m.id]) ficha[m.id] = { puesto: false, texto: '' };
    const ranura = ficha[m.id];
    const tarjeta = h('div', { clase: 'cta-ranura' + (ranura.puesto ? '' : ' apagada') });
    tarjeta.appendChild(h('label', { clase: 'plano' },
      h('input', {
        type: 'checkbox', checked: !!ranura.puesto,
        onchange: ev => { ranura.puesto = ev.target.checked; alCambiar(); repintar(); },
      }),
      h('b', {}, m.nombre)));
    tarjeta.appendChild(h('div', { clase: 'pista' }, m.pista));
    if (ranura.puesto) {
      tarjeta.appendChild(campoArea(m.etiqueta, ranura.texto,
        v => { ranura.texto = v; alCambiar(); }, m.ejemplo, `cta-${m.id}`));
      if (m.ayuda) tarjeta.appendChild(h('div', { clase: 'pista' }, m.ayuda));
    }
    caja.appendChild(tarjeta);
  });
  caja.appendChild(h('div', { clase: 'pista' },
    'Cada uno es un bloque más del guion —misma voz, mismo tono—, no una cuña '
    + 'pegada al final. Se le dicen al redactor ANTES de escribir para que el '
    + 'bloque anterior los prepare. Lo que escribas es una indicación, no el '
    + 'texto final: lo redacta con las palabras de ESTE vídeo.'));
  return caja;
}

/* ===================================================================== TANDAS
 *
 * LAS MISMAS CUATRO QUE EL MODO LIGHT, y por el mismo camino del servidor
 * (`GET/POST /api/proyectos/{pid}/generar?tanda=`). Hasta el 02-09 cada pestaña
 * lanzaba SU receta (`/pestanas/{p}/generar`), que no es lo mismo: la del guion
 * no bajaba el vídeo de origen ni reunía el material, la de Vídeo montaba los
 * subtítulos que el light deja para el montaje, y la dirección de cada plano
 * venía apagada. El plan de una tanda dice ADEMÁS lo que tarda y lo que
 * cuesta, medido en esta máquina, y eso es lo que se lee al lado del botón
 * antes de pulsarlo. */

const TANDAS = { planes: {}, pidiendo: {} };

//: Qué tanda está corriendo y desde qué pestaña se lanzó: es donde el faro
//: lleva al pulsar, y lo que decide qué se vuelve a leer al terminar.
const TANDA_EN_MARCHA = { tanda: '', pestana: '' };

function olvidarTandas() {
  TANDAS.planes = {};
}

/* 'generar:origen+guion' -> 'guion'. Es como el servidor NOMBRA el trabajo de
   una tanda: por las pestañas que recorre. */
function tandaDeNombre(nombre) {
  const pestanas = String(nombre || '').replace(/^generar:/, '').split('+');
  if (pestanas.includes('render')) return 'render';
  if (pestanas.includes('video')) return 'video';
  if (pestanas.includes('voz')) return 'voz';
  return 'guion';
}

;
/* UNA TANDA ES UN TRABAJO, y corre en el servidor: encadenar en el navegador
   se rompe al recargar la página, justo en un flujo pensado para dejarlo
   generando y mirarlo desde el móvil. Es la misma llamada que hace el modo
   light (`lanzarTandaLight`); aquí la barra vive en la ranura de la receta,
   que está en la barra de la pestaña y en su pie.

   `opciones.pestana` es la parada a la que se va ANTES de lanzar: el pie del
   Encargo dice «Generar el guion» y lo que se quiere ver mientras corre es
   el guion, no el encargo. */
/* ------------------------------------------------------------------ pestanas */

function pintarPestanas() {
  const barra = $('#pestanas');
  if (!barra) return;          // no hay barra de pasos: una sola pantalla
  const nav = vaciar(barra);
  PESTANAS.forEach((pestana, indice) => {
    const estado = estadoPestana(pestana);
    const fichas = pasosDe(pestana).map(pasoDe);
    const obsoletas = fichas.reduce((s, f) => s + (f.unidades_obsoletas || []).length, 0);
    const detalle = fichas.map(f => `${f.nombre || f.id}: ${f.estado || 'pendiente'}`).join(' · ');
    const faltan = fichas.filter(f => f.estado === 'bloqueado')
      .flatMap(f => f.depende_de || []).filter(d => !pasosDe(pestana).includes(d));
    nav.appendChild(h('button', {
      clase: 'pestana' + (pestana.id === APP.activa ? ' activa' : ''),
      datos: { estado, pestana: pestana.id },
      title: faltan.length
        ? `${detalle}\nBloqueado: antes hay que ejecutar ${faltan.map(nombreDe).join(', ')}`
        : detalle,
      onclick: () => irA(pestana.id),
    },
      h('span', { clase: 'orden' }, String(indice + 1)),
      h('span', { clase: `punto ${estado}` }),
      pestana.nombre,
      obsoletas ? h('span', { clase: 'pastilla obsoleto' }, `${obsoletas}`) : null));
  });
  aLaVista(nav, nav.children[PESTANAS.findIndex(p => p.id === APP.activa)]);
}

async function irA(pestana, sinHistorial) {
  APP.activa = pestana;
  // La pestana viaja en la URL. Recargar dejaba de perder el sitio (en el movil
  // el navegador descarga la pagina cada dos por tres al cambiar de app), y el
  // boton de atras del telefono pasa a hacer lo que se espera: la pestana
  // anterior, en vez de salirse del Estudio.
  if (!sinHistorial && location.hash.slice(1) !== pestana) {
    history.pushState({ pestana }, '', `#${pestana}`);
  }
  pintarPestanas();
  $('#panel').scrollTop = 0;
  await refrescarPestana(pestana);
}

/* ------------------------------------------------------------------ panel */

;

/* LA PANTALLA. Existe como funcion --y no como una llamada directa a
   `pintarLight`-- porque es el UNICO sitio donde se decide que se pinta: las
   veinte funciones que repintan algo entran por aqui, y con eso basta que haya
   un solo sitio que sepa como se llama la pantalla. */
function pintarPanel() {
  pintarLight();
}

async function revertir(paso, version) {
  const ficha = APP.fichas[paso] || {};
  const activa = (ficha.versiones || []).find(v => v.activa);
  if (activa && activa.n === version) { toast('esa versión ya es la activa'); return; }
  const abajo = descendientesDe(paso);
  const texto = `Revertir ${nombreDe(paso)} a la v${version}.\n\n`
    + 'No se borra nada: solo se mueve el puntero de la versión activa.\n'
    + (abajo.length
      ? `Quedarán obsoletos (habrá que rehacerlos): ${abajo.map(nombreDe).join(', ')}.`
      : 'No hay pasos aguas abajo.');
  if (!window.confirm(texto)) return;
  limpiarError(paso);
  try {
    await pedir(API.revertir(APP.pid, paso), { method: 'POST', cuerpo: { version } });
    delete APP.borrador[paso];
    APP.sucio[paso] = false;
    CACHE_ARCHIVOS.clear();
    toast(`${nombreDe(paso)} revertido a v${version}`);
    await refrescarTodo();
  } catch (e) { mostrarError(paso, e); }
}

/* ------------------------------------------------------------------ piezas comunes */

/* Bloque que se pliega.
 *
 * Casi todo lo que ocupa una pantalla se decide UNA vez y despues estorba: los
 * ajustes de una ingesta que ya corrio, el catalogo de 300 voces cuando ya hay
 * una elegida, la ficha tecnica de una generacion. Plegarlo es lo que hace que
 * quepa el trabajo de verdad, y en un movil es la diferencia entre poder usar
 * la pantalla y no poder.
 *
 * La regla que lo hace honesto: el summary lleva SIEMPRE un resumen de lo que
 * hay dentro. Plegar sin resumen no es ordenar, es esconder, y esta interfaz ya
 * tiene una norma para eso ("ninguna cifra se ensena sin decir que es").
 *
 *   titulo    el <h2> de siempre
 *   opciones  {abierto, resumen, pastilla, clase}
 *   contenido lo que va dentro
 *
 * Devuelve el nodo con .ponerResumen(texto|nodo) para refrescar el resumen sin
 * repintar el panel (perderia foco, scroll y reproductor).
 */
function plegable(titulo, opciones, ...contenido) {
  const op = opciones || {};
  const resumen = h('span', { clase: 'resumen' });
  const ponerResumen = valor => {
    vaciar(resumen);
    if (valor === null || valor === undefined || valor === '') return;
    meter(resumen, [valor]);
  };
  ponerResumen(typeof op.resumen === 'function' ? op.resumen() : op.resumen);
  const caja = h('details', {
    clase: `bloque plegable${op.clase ? ` ${op.clase}` : ''}`,
  },
    h('summary', {},
      h('span', { clase: 'flecha' }, '▶'),
      h('h2', {}, titulo),
      resumen,
      op.pastilla || null),
    h('div', { clase: 'cuerpo-plegable' }, ...contenido));
  recordarPlegado(caja, op.clave || titulo, !!op.abierto);
  caja.ponerResumen = ponerResumen;
  return caja;
}

/* Lo que abre o cierra una persona no lo vuelve a cerrar un repintado.
 *
 * pintarPanel() rehace el DOM entero muchas veces —al cambiar de sub-pestana,
 * al terminar un trabajo, al llegar la ficha de un paso— y sin esto cada
 * repintado devolvia todos los plegables a su estado por defecto: abrias la
 * ficha tecnica, terminaba un trabajo y se te cerraba en la cara.
 *
 * Solo se recuerda lo que se ha tocado A MANO. Si nadie lo ha tocado manda el
 * valor por defecto, que depende del estado del paso y tiene que poder cambiar
 * (los ajustes de ingesta se pliegan solos en cuanto la ingesta termina). */
const PLEGADOS = {};

function recordarPlegado(nodo, clave, porDefecto) {
  const recordado = PLEGADOS[clave];
  nodo.open = recordado === undefined ? porDefecto : recordado;
  nodo.addEventListener('toggle', () => { PLEGADOS[clave] = nodo.open; });
  return nodo;
}

/* Un textarea que se ajusta a lo que tiene dentro, sin scroll propio.
 *
 * Un cuadro de altura fija dentro de una pagina que ya hace scroll es dos
 * scrolls anidados, y en un movil es peor todavia: el dedo no sabe cual de los
 * dos va a mover. Aqui el texto manda y el cuadro cede.
 *
 * Se mide en dos tiempos —altura a 'auto' y luego scrollHeight— porque si no se
 * resetea antes, el cuadro solo puede crecer: al borrar texto se quedaria con
 * el alto de cuando estaba lleno. */
function ajustarAlto(area) {
  if (!area) return area;
  area.style.height = 'auto';
  area.style.height = `${area.scrollHeight}px`;
  return area;
}

function crecerConElTexto(area) {
  area.classList.add('crece');
  // Al crearlo todavia no esta en el DOM y scrollHeight es 0: se mide cuando ya
  // esta pintado. Y se vuelve a medir al cambiar de tamano la ventana, porque
  // al girar el movil el mismo texto ocupa otro numero de lineas.
  const medir = () => { if (area.isConnected) ajustarAlto(area); };
  setTimeout(medir, 0);
  window.addEventListener('resize', medir);
  return area;
}

/* Trae un boton a la vista dentro de su tira horizontal. Solo mueve la tira, y
   solo si de verdad desborda: scrollIntoView a secas arrastra tambien el panel
   entero y te deja mirando otra cosa. */
function aLaVista(tira, boton) {
  if (!boton) return;
  setTimeout(() => {
    if (!tira.isConnected || tira.scrollWidth <= tira.clientWidth + 2) return;
    const centro = boton.offsetLeft - (tira.clientWidth - boton.offsetWidth) / 2;
    tira.scrollTo({ left: Math.max(0, centro), behavior: 'smooth' });
  }, 0);
}

/* ================================================== opciones avanzadas
 *
 * La regla, y vale para TODA la interfaz: lo que se decide en cada video va
 * fuera; lo que tiene un valor normal que casi nunca se toca va dentro de un
 * plegable. Umbrales, reintentos, techos de tiempo, tamanos, modelo y esfuerzo
 * del CLI, calidad y margenes son siempre "dentro".
 *
 * Dos cosas lo hacen honesto, y sin ellas esconder seria ocultar:
 *
 *   1. El resumen dice lo que hay dentro sin abrirlo, como ya hacia «Mandos
 *      finos» con «sonic-3.5 · en · normal · sin color · aire 0.9s».
 *   2. Un ajuste FUERA de su valor por defecto se marca desde fuera. Esconder
 *      un mando tocado es como se acaba depurando media hora un parametro que
 *      alguien cambio hace tres semanas.
 *
 * `mandos` es la lista de lo que hay dentro: {etiqueta, valor, defecto}. Con
 * eso se calcula solo el resumen y la marca.
 */
function opcionesAvanzadas(opciones, ...contenido) {
  const op = opciones || {};
  const mandos = (op.mandos || []).filter(Boolean);
  const tocados = mandos.filter(m => {
    if (m.defecto === undefined) return false;
    return JSON.stringify(normalizarMando(m.valor)) !== JSON.stringify(normalizarMando(m.defecto));
  });
  const resumen = op.resumen !== undefined ? op.resumen
    : (mandos.map(m => `${m.corto || m.etiqueta}: ${textoDeMando(m.valor)}`).join(' · ')
      || 'nada que tocar');
  return plegable(op.titulo || 'Opciones avanzadas', {
    clave: op.clave,
    abierto: !!op.abierto,
    resumen,
    // La marca va en el summary, o sea visible con el plegable cerrado: es
    // justo el caso que tiene que verse sin abrir nada.
    pastilla: tocados.length ? h('span', {
      clase: 'pastilla obsoleto',
      title: 'fuera de su valor por defecto: '
        + tocados.map(m => `${m.etiqueta} = ${textoDeMando(m.valor)} `
          + `(por defecto ${textoDeMando(m.defecto)})`).join(' · '),
    }, `${tocados.length} tocado${tocados.length > 1 ? 's' : ''}`) : null,
  },
    ...contenido,
    tocados.length ? h('div', { clase: 'pista' },
      'Fuera de su valor por defecto: '
      + tocados.map(m => `${m.etiqueta} (${textoDeMando(m.valor)} en vez de `
        + `${textoDeMando(m.defecto)})`).join(', ') + '.') : null);
}

/* Un numero escrito en una casilla llega como cadena: '3' y 3 son el mismo
   ajuste y no puede salir marcado como tocado por haberlo reescrito igual. */
function normalizarMando(valor) {
  if (valor === null || valor === undefined) return '';
  if (typeof valor === 'string' && valor.trim() !== '' && !Number.isNaN(Number(valor))) {
    return Number(valor);
  }
  return valor;
}

function textoDeMando(valor) {
  if (valor === null || valor === undefined || valor === '') return '—';
  if (Array.isArray(valor)) return valor.length ? valor.join(', ') : 'ninguno';
  if (typeof valor === 'boolean') return valor ? 'sí' : 'no';
  return String(valor);
}

/* ================================================== presets de canal
 *
 * Un canal tiene un idioma, un estilo grafico, una cadencia y una voz, y esas
 * cuatro cosas son las MISMAS en todos sus videos. Sin presets hay que volver a
 * decidirlas en cada proyecto: pegar la URL del video de estilo, extraer 80
 * fotogramas, elegir ocho, escribir la guia, buscar la voz entre 864.
 *
 * Aplicar COPIA los valores a los params, no guarda el nombre del preset en
 * ningun sitio. Por eso borrar un preset no puede romper un video terminado.
 * Ver pasos/presets_canal.py, que es donde vive la regla de que clave va a que
 * paso: repartirla entre los dos lados es como se acaba con dos versiones que
 * se contradicen.
 */

const PRESETS_CANAL = { datos: null, cargando: false, error: '', pedido: false };

const NOMBRES_PRESET = {
  guion: 'guion', estilo: 'estilo gráfico', voz: 'voz',
  rotulos: 'rótulos', canal: 'canal',
};

// «+ Nuevo voz…» no se puede leer: el articulo va escrito, no deducido.
;

/* Renombrar no toca lo que el preset guarda: va por PATCH y sólo cambia el
   nombre y la nota. Con el POST de guardar habría que reenviarle los datos, y
   en un preset de estilo eso vuelve a sembrar su carpeta del banco —borrar y
   recopiar trece fotogramas para corregir una errata. */
/* Renombrar un preset se hace sobreescribiendolo con otro nombre desde su
   tarjeta (formularioPreset con `sobre`); el PATCH del servidor sigue
   existiendo para quien lo quiera por API. */

;

;

/* ------------------------------------------------- atajos de los reproductores
   Las mismas teclas en los cuatro sitios donde hay audio o video, para que no
   haya que aprenderse un juego por pantalla. Son las de siempre (las de
   YouTube), que ademas caen directas en el teclado espanol:

     espacio o k   play / pausa        j / l   -10 s / +10 s
     < y >         mas lento / rapido  0..9    saltar al 0%..90%

   Dos reglas que separan un atajo util de uno que estorba:

   1. Solo actua sobre el reproductor QUE SE ESTA VIENDO. Si estas en Callouts,
      espacio no puede darle al play al audio de la Revision.
   2. Nunca dispara con el foco en un campo de texto. Esta interfaz esta llena
      de cuadros de comentario, y escribir "k" ahi no puede pausar nada. */

const VELOCIDADES_REPRODUCTOR = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 3];
let ultimoReproductor = null;

/* Se marca al darle al play, no al crearlo: lo que manda es con cual estas
   interactuando, no cual se pinto antes. */
function registrarReproductor(medio) {
  medio.addEventListener('play', () => {
    /* SOLO UNO SUENA A LA VEZ. Desde que los planos y los rotulos comparten la
       pestana Video hay DOS repasos del montaje en la misma pantalla, cada uno
       con su locucion: darle al play en el segundo sin parar el primero pone
       las dos voces encima. Se paran las demas al arrancar esta, que ademas es
       lo que ya se hacia a mano en la lista de candidatos de musica. */
    $('#panel').querySelectorAll('audio, video').forEach(otro => {
      if (otro !== medio && !otro.paused) otro.pause();
    });
    ultimoReproductor = medio;
  });
  return medio;
}

function reproductorVisible(medio) {
  // offsetParent null = no esta pintado (pestana distinta, display:none)
  return !!medio && medio.isConnected && medio.offsetParent !== null;
}

function reproductorActivo() {
  if (reproductorVisible(ultimoReproductor)) return ultimoReproductor;
  return [...$('#panel').querySelectorAll('audio, video')].find(reproductorVisible) || null;
}

/* Se miran los DOS: el destino del evento y el foco real. Con una tecla de
   verdad son el mismo, pero no siempre (un evento disparado sobre document deja
   el destino en document), y equivocarse aqui significa pausar el audio mientras
   alguien escribe un comentario. */
function escribiendo(destino) {
  return [destino, document.activeElement].some(nodo => !!nodo
    && (nodo.isContentEditable
      || ['INPUT', 'TEXTAREA', 'SELECT'].includes(nodo.tagName)));
}

function cambiarVelocidad(medio, salto) {
  const actual = medio.playbackRate || 1;
  let indice = VELOCIDADES_REPRODUCTOR.findIndex(v => Math.abs(v - actual) < 0.01);
  if (indice < 0) indice = VELOCIDADES_REPRODUCTOR.indexOf(1);
  const siguiente = VELOCIDADES_REPRODUCTOR[
    Math.max(0, Math.min(VELOCIDADES_REPRODUCTOR.length - 1, indice + salto))];
  medio.playbackRate = siguiente;
  // Sin decirlo, la toma se queda a 1,5x y acabas preguntandote por que suena
  // rara. El tono no se toca: los navegadores lo conservan por defecto.
  toast(`velocidad ×${siguiente}`);
}

function atajosDeReproductor(ev) {
  if (ev.ctrlKey || ev.altKey || ev.metaKey) return;
  if (escribiendo(ev.target)) return;
  const medio = reproductorActivo();
  if (!medio) return;
  const tecla = ev.key;

  if (tecla === ' ' || tecla === 'k' || tecla === 'K') {
    if (medio.paused) medio.play(); else medio.pause();
  } else if (tecla === 'j' || tecla === 'J') {
    medio.currentTime = Math.max(0, medio.currentTime - 10);
  } else if (tecla === 'l' || tecla === 'L') {
    medio.currentTime = Math.min(medio.duration || Infinity, medio.currentTime + 10);
  } else if (tecla === '<' || (tecla === ',' && ev.shiftKey)) {
    cambiarVelocidad(medio, -1);
  } else if (tecla === '>' || (tecla === '.' && ev.shiftKey)) {
    cambiarVelocidad(medio, 1);
  } else if (/^[0-9]$/.test(tecla) && medio.duration) {
    medio.currentTime = medio.duration * (Number(tecla) / 10);
  } else {
    return;
  }
  ev.preventDefault();
}

/* -------------------------------------------------------------- caja de campo
   `cajaCampo` envuelve una entrada YA construida. Es solo maquetacion --el
   `<div>` que hace que el input o el textarea ocupen el ancho de su hueco, con
   `.linea` o `.area` segun cual sea-- y existe como funcion, y no como una
   clase escrita en cada formulario, porque son dos docenas de campos y la
   anchura de un campo de texto no es una decision que se tome dos docenas de
   veces. */
function cajaCampo(entrada, opciones) {
  const op = opciones || {};
  return h('div', { clase: 'caja-campo' + (op.clase ? ` ${op.clase}` : '') },
    entrada);
}


function campoTexto(etiqueta, valor, alCambiar, opciones) {
  const op = opciones || {};
  const entrada = h(op.filas ? 'textarea' : 'input', {
    value: op.filas ? undefined : (valor === undefined || valor === null ? '' : valor),
    rows: op.filas,
    type: op.filas ? undefined : (op.tipo || 'text'),
    step: op.paso,
    min: op.min,
    max: op.max,
    placeholder: op.pista || '',
    oninput: ev => alCambiar(op.tipo === 'number' ? Number(ev.target.value) : ev.target.value),
  });
  if (op.filas) entrada.value = valor === undefined || valor === null ? '' : valor;
  if (!op.filas) entrada.style.width = op.ancho || '100%';
  // un numero o una fecha no necesitan el hueco entero: van a su ancho
  const cuerpo = (op.tipo && op.tipo !== 'text') ? entrada
    : cajaCampo(entrada, { clase: op.filas ? 'area' : 'linea' });
  return h('div', { clase: 'campo' },
    h('label', {}, etiqueta), cuerpo,
    op.ayuda ? h('div', { clase: 'pista' }, op.ayuda) : null);
}

/* ------------------------------------------------------------- bloc de enlaces
 * Ideas de video apuntadas para luego, y referencias visuales.
 *
 * Viven en el SERVIDOR y no en el navegador: una idea apuntada hoy se convierte
 * en un video dentro de tres semanas, sobrevive a los proyectos, y se apunta
 * desde donde uno este (muchas veces el movil). localStorage las ataria a un
 * navegador concreto.
 */

;

/* ============================================================== CONFIGURACION
 *
 * Las claves de API y las cuentas. Vive en la barra de arriba y no en una
 * pestaña porque no es de este vídeo: es de la máquina, y se toca una vez cada
 * muchos vídeos.
 *
 * TRES REGLAS, y las tres tienen su porqué en el servidor (pasos/claves.py):
 *
 *   1. Una clave NUNCA baja al navegador. Lo que llega es la etiqueta y los
 *      cuatro últimos caracteres. Para poder editar el correo de una cuenta sin
 *      tener su clave delante, lo que se manda de vuelta es el marcador
 *      CONSERVAR — «deja la que ya había».
 *   2. Las de OpenAI son TANTAS COMO QUIERAS. El repartidor las contempla
 *      todas, cada una con su propio límite por minuto, así que añadir una
 *      cuenta es literalmente generar más rápido. La etiqueta es el correo de
 *      la cuenta: sin ella, «cuenta 3 sin crédito» no dice dónde recargar.
 *   3. La cuenta de Claude NO es una clave: es un LOGIN. Por eso lo que se pide
 *      es una CARPETA de configuración del CLI, no un secreto. Meter aquí una
 *      clave de API convertiría todo el Estudio en pago por uso sin que nadie
 *      se enterase.
 */

const CONSERVAR_CLAVE = '__CONSERVAR__';

function estadoConfig() {
  if (!APP.vista.config) {
    APP.vista.config = { ficha: null, cargando: false, error: '',
      /* Las cuentas del CLI van APARTE de `ficha` porque se piden aparte: su
         estado de sesión sale de lanzar `claude auth status`, y eso no puede
         colgar de abrir el cajón para mirar cualquier otra cosa. */
      cli: null,
      /* Los ajustes van APARTE de `ficha` por lo mismo que las cuentas del
         CLI: se piden en otra llamada, y ademas traen la tabla de costes,
         que se lee de las tarifas y no del almacen de claves. */
      ajustes: null,
      /* Lo que se está tecleando en cada caja de código. Vive aquí y no en el
         DOM porque `pintarConfig()` vacía y reconstruye la pantalla entera
         después de CADA guardado: sin esto, guardar una etiqueta borraría el
         código a medio pegar de otra cuenta. */
      codigos: {}, latiendo: false };
  }
  return APP.vista.config;
}

function conmutarConfig(abrir) {
  const cajon = $('#config');
  const quiero = abrir === undefined ? cajon.classList.contains('plegado') : !!abrir;
  cajon.classList.toggle('plegado', !quiero);
  if (quiero) cargarClaves().then(repintarClaves);
  /* Al cerrar el cajón se para el latido: un sondeo que sigue corriendo detrás
     de una pantalla que nadie mira es una llamada por segundo para siempre. */
  if (!quiero) estadoConfig().latiendo = false;
}

async function cargarClaves() {
  const vista = estadoConfig();
  vista.cargando = true;
  try {
    vista.ficha = await pedir(API.claves());
    vista.error = '';
  } catch (e) {
    vista.ficha = null;
    vista.error = e.message;
  } finally {
    vista.cargando = false;
  }
  cargarCuentasCLI();
  cargarAjustes();
  return vista.ficha;
}

/* Las cuentas del CLI, en su propia llamada y sin bloquear el resto del cajón.
   Se pide DESPUÉS de pintar: preguntarle a `claude auth status` por cada cuenta
   son unas décimas cada una, y el cajón tiene que abrirse ya. */
async function cargarCuentasCLI(refrescar) {
  const vista = estadoConfig();
  try {
    vista.cli = await pedir(API.cuentasCLI(refrescar));
  } catch (e) {
    vista.cli = { error: e.message, cuentas: [] };
  }
  repintarClaves();
  latirCLI();
  return vista.cli;
}

/* EL ESTADO DE UN ACCESO VIVE EN EL SERVIDOR, no aquí: recargar la página o
   cambiar de vídeo tienen que reencontrarlo donde estaba. Mientras haya uno a
   medias se vuelve a preguntar; cuando no queda ninguno, el latido se para
   solo. */
function latirCLI() {
  const vista = estadoConfig();
  const vivo = (vista.cli && vista.cli.cuentas || []).some(
    c => c.intento && ['abriendo', 'enlace', 'probando'].includes(c.intento.estado));
  if (!vivo || vista.latiendo) { if (!vivo) vista.latiendo = false; return; }
  vista.latiendo = true;
  const tic = async () => {
    const v = estadoConfig();
    const cajon = $('#config');
    if (!v.latiendo || !cajon || (cajon.classList.contains('plegado') && !INICIO.abierta)) {
      v.latiendo = false; return;
    }
    try { v.cli = await pedir(API.cuentasCLI()); } catch (e) { /* se reintenta */ }
    repintarClaves();
    const sigue = (v.cli && v.cli.cuentas || []).some(
      c => c.intento && ['abriendo', 'enlace', 'probando'].includes(c.intento.estado));
    if (sigue && v.latiendo) setTimeout(tic, 2000);
    else v.latiendo = false;
  };
  setTimeout(tic, 2000);
}

/* Repinta lo que esté enseñando las claves: el cajón de Configuración si está
   abierto y la guía de inicio si está abierta. Las dos leen el mismo estado
   (`estadoConfig()`), así que guardar una clave desde una tiene que verse en
   la otra sin que ninguna sepa de la existencia de la otra. */
function repintarClaves() {
  const cajon = $('#config');
  if (cajon && !cajon.classList.contains('plegado')) pintarConfig();
  if (INICIO.abierta) pintarInicio();
}

function pintarConfig() {
  const caja = vaciar($('#cuerpo-config'));
  const vista = estadoConfig();
  if (vista.error) {
    caja.appendChild(h('div', { clase: 'vacio' },
      'esta parte necesita una versión más nueva del servidor'));
    return;
  }
  const ficha = vista.ficha;
  if (!ficha) {
    caja.appendChild(h('div', { clase: 'cargando' }, 'leyendo las claves…'));
    return;
  }
  caja.appendChild(bloquePruebaClaves());
  caja.appendChild(seccionOpenAI(ficha));
  caja.appendChild(seccionCalidadImagen());
  caja.appendChild(seccionCartesia(ficha));
  caja.appendChild(seccionCLI());
  caja.appendChild(seccionOtrasClaves(ficha));
  caja.appendChild(h('div', { clase: 'fila' },
    h('button', {
      clase: 'mini fantasma',
      title: 'Las tarjetas de la primera vez: qué hace falta y dónde se consigue',
      onclick: () => { conmutarConfig(false); abrirInicio(0); },
    }, 'Volver a ver la guía de inicio')));
  caja.appendChild(h('div', { clase: 'meta', estilo: 'margin-top:14px' },
    `Se guardan en ${ficha.fichero}, fuera del repositorio. No hace falta `
    + 'reiniciar: el motor de imagen recoge las cuentas nuevas solo, y el CLI '
    + 'lee la suya en cada llamada.'));
}

async function cargarAjustes() {
  const vista = estadoConfig();
  try {
    vista.ajustes = await pedir(API.ajustes());
  } catch (e) {
    vista.ajustes = null;
  }
  repintarClaves();
}


async function guardarCalidadImagen(calidad) {
  const vista = estadoConfig();
  try {
    const r = await pedir(API.ajustes(),
                          { method: 'PUT', cuerpo: { calidad_imagen: calidad } });
    vista.ajustes = { ...(vista.ajustes || {}), ajustes: r.ajustes, costes: r.costes };
  } catch (e) {
    vista.error = e.message;
  }
  repintarClaves();
}


/* LA CALIDAD DE LAS IMAGENES, con lo que cuesta DE VERDAD.
 *
 * Aqui no se ensena el precio de OpenAI: se ensena la factura. La tabla de
 * OpenAI habla de la imagen DEVUELTA, y a cada plano se le adjuntan ademas sus
 * referencias de estilo, de reparto y de continuidad, que se pagan como tokens
 * de entrada y son casi todo el gasto en la calidad baja. Con el precio de
 * OpenAI delante, subir a `medium` parece multiplicar por 6,8; con la factura
 * delante, multiplica por 1,7. Elegir con el numero equivocado es no elegir, y
 * por eso se ensenan LOS DOS: el real grande y el aparente al lado.
 *
 * Y ES EL PUNTO DE PARTIDA DE LOS VIDEOS NUEVOS, no un interruptor general.
 * Cambiarlo no toca ni un video hecho: la calidad entra en la firma de cada
 * imagen, asi que un cambio retroactivo las dejaria todas obsoletas y
 * regenerarlas se paga. */
function seccionCalidadImagen() {
  const vista = estadoConfig();
  const datos = vista.ajustes;
  const caja = h('section', { clase: 'bloque-config' },
    h('div', { clase: 'fila' },
      h('h3', {}, 'Calidad de las imagenes'),
      h('span', { clase: 'crece' }),
      datos ? pastillaEstado('ok', datos.ajustes.calidad_imagen) : null));
  if (!datos) {
    caja.appendChild(h('div', { clase: 'cargando' }, 'leyendo los costes...'));
    return caja;
  }

  const base = datos.costes[0] || {};
  const porcentaje = base.usd_total
    ? Math.round(100 * base.usd_referencias / base.usd_total) : 0;
  caja.appendChild(h('div', { clase: 'pista' },
    'Lo que se ve aqui NO es el precio de OpenAI: es lo que cuesta el plano '
    + 'entero. A cada imagen se le adjuntan sus referencias de estilo, reparto y '
    + `continuidad, y esas se pagan aparte — en la calidad baja son el ${porcentaje} % `
    + 'del gasto. Por eso subir de calidad cuesta bastante menos de lo que '
    + 'parece si solo se mira la tabla de precios.'));

  const elegida = datos.ajustes.calidad_imagen;
  datos.costes.forEach(fila => {
    const puesta = fila.calidad === elegida;
    caja.appendChild(h('button', {
      clase: 'fila-calidad' + (puesta ? ' elegida' : ''),
      disabled: puesta,
      title: puesta ? 'es la que esta puesta'
        : `los videos nuevos empezaran en ${fila.calidad}`,
      onclick: () => guardarCalidadImagen(fila.calidad),
    },
      h('span', { clase: 'nombre' }, fila.calidad),
      h('span', { clase: 'precio' },
        `${fila.usd_total.toFixed(3)} $ por imagen`),
      h('span', { clase: 'meta desglose' },
        `${fila.usd_imagen.toFixed(3)} la imagen + ${fila.usd_referencias.toFixed(3)} `
        + 'las referencias'),
      h('span', { clase: 'meta veces' }, fila.veces_total > 1
        ? `×${fila.veces_total} de coste real, no ×${fila.veces_imagen}`
        : 'la mas barata')));
  });

  caja.appendChild(h('div', { clase: 'meta' },
    'Es el punto de partida de los videos NUEVOS. Los que ya existen se quedan '
    + 'con la suya: se cambia por vídeo desde su propia ficha.'));
  return caja;
}


/* Las cuentas de OpenAI: N, cada una con el correo de la suya. */
function seccionOpenAI(ficha) {
  const vivas = ficha.cuentas_imagen && ficha.cuentas_imagen.length
    ? ficha.cuentas_imagen : null;
  const porCola = {};
  (vivas || []).forEach(c => { porCola[c.cola] = c; });

  const puesta = ficha.openai.length > 0;
  const cuenta = puesta ? ficha.openai[0] : null;
  const viva = cuenta ? porCola[cuenta.cola] : null;
  const campo = h('input', {
    type: 'password',
    placeholder: puesta ? `puesta (${cuenta.cola})` : 'sk-…',
  });

  const caja = h('section', { clase: 'bloque-config' },
    h('div', { clase: 'fila' },
      h('h3', {}, 'OpenAI — imágenes'),
      h('span', { clase: 'crece' }),
      (viva && viva.sin_saldo
        ? pastillaEstado('error', 'sin crédito')
        : pastillaEstado(puesta ? 'ok' : 'vacio',
          puesta ? cuenta.cola : 'sin poner'))),
    h('div', { clase: 'pista' },
      'La clave con la que se generan las imágenes. Imprescindible, como la de '
      + 'Cartesia y la cuenta de Claude: sin ella no hay planos que montar.'),
    h('div', { clase: 'fila-clave' }, campo,
      h('button', {
        clase: 'mini',
        onclick: () => {
          if (!campo.value.trim()) { toast('escribe la clave', true); return; }
          guardarClaves({ openai: [{ etiqueta: '', clave: campo.value.trim(),
            activa: true }] });
          campo.value = '';
        },
      }, 'Cambiar'),
      (puesta ? h('button', {
        clase: 'mini fantasma peligro',
        onclick: () => {
          if (!window.confirm('¿Quitar la clave de OpenAI? Sin ella no se '
            + 'pueden generar imágenes.')) return;
          guardarClaves({ openai: [] });
        },
      }, 'Quitar') : null)));

  /* EL RITMO MEDIDO, si el motor ya ha generado algo con ella. Es el límite de
     imágenes por minuto que la cuenta admite de verdad, y sale de haberlo
     probado: la barra de una tanda lo usa para decir cuánto queda. */
  if (viva && viva.limite_por_minuto) {
    caja.appendChild(h('div', { clase: 'meta' },
      `${viva.limite_por_minuto} imágenes/min`
      + (viva.medido ? ' (medido en tus tandas)' : ' (según el plan)')));
  }
  return caja;
}

function seccionCartesia(ficha) {
  const campo = h('input', {
    type: 'password',
    placeholder: ficha.cartesia.puesta ? `puesta (${ficha.cartesia.cola})` : 'sin poner',
  });
  return h('section', { clase: 'bloque-config' },
    h('div', { clase: 'fila' },
      h('h3', {}, 'Cartesia — voz'),
      h('span', { clase: 'crece' }),
      pastillaEstado(ficha.cartesia.puesta ? 'ok' : 'vacio',
        ficha.cartesia.puesta ? ficha.cartesia.cola : 'sin poner')),
    h('div', { clase: 'pista' },
      'Una sola, y no se reparte: la locución se sintetiza de una tirada.'),
    h('div', { clase: 'fila-clave' }, campo,
      h('button', {
        clase: 'mini',
        onclick: () => {
          if (!campo.value.trim()) { toast('escribe la clave', true); return; }
          guardarClaves({ cartesia: { clave: campo.value.trim() } });
          campo.value = '';
        },
      }, 'Cambiar')));
}

/* Las cuentas del CLI: una LISTA ORDENADA, y se entra desde aquí.
 *
 * Lo que había antes era un par fijo —«Principal» y «Respaldo»— con un campo
 * para pegar la ruta de una carpeta, y un texto de ayuda que era un manual de
 * tres pasos con una consola dentro. El día que hace falta —el cupo se agotó a
 * mitad de una tanda— es el peor momento para abrir una consola.
 *
 * Ahora cada cuenta tiene su botón de Entrar: sale un enlace, se entra en el
 * navegador que se esté usando (que muchas veces es el del móvil, por Tailscale)
 * y se pega el código. El servidor NO abre ningún navegador: ver
 * `login_cli.BROWSER=none`.
 */
function seccionCLI() {
  const vista = estadoConfig();
  const cli = vista.cli;
  const cuentas = (cli && cli.cuentas) || [];
  const dentro = cuentas.filter(c => c.sesion && c.sesion.conectada).length;
  const caja = h('section', { clase: 'bloque-config' },
    h('div', { clase: 'fila' },
      h('h3', {}, 'Claude CLI — guion, catálogo, rótulos…'),
      h('span', { clase: 'crece' }),
      pastillaEstado(dentro ? 'ok' : 'error',
        !cli ? 'mirando…' : (dentro ? `${dentro} con sesión` : 'sin sesión'))),
    h('div', { clase: 'pista' },
      'Aquí no va una clave: va una CUENTA. Se gasta la suscripción con '
      + 'la que el CLI esté logueado, y eso no se puede cambiar con una clave de '
      + 'API sin convertir cada paso en pago por uso.'),
    h('div', { clase: 'pista' },
      'Mandan POR ORDEN: la primera es la que se usa siempre, y las de abajo '
      + 'entran una a una cuando la de arriba falla o se queda sin cupo. Un '
      + 'plazo agotado NO baja a la siguiente, a propósito: volvería a vencer.'),
    h('div', { clase: 'pista' },
      'El nombre de cada una es sólo para ti —«la mía», «la del curro»— y se '
      + 'puede dejar en blanco: es lo que sale en el aviso cuando una se queda '
      + 'sin cupo y entra la siguiente.'));

  if (!cli) {
    caja.appendChild(h('div', { clase: 'cargando' }, 'mirando las cuentas…'));
    return caja;
  }
  if (cli.error) {
    caja.appendChild(h('div', { clase: 'vacio' }, cli.error));
    return caja;
  }
  cuentas.forEach((cuenta, indice) => caja.appendChild(
    tarjetaCuentaCLI(cuenta, indice, cuentas)));

  if (cuentas.length < (cli.max || 6)) {
    const nueva = h('input', { type: 'text', placeholder: 'correo@de-la-cuenta.com' });
    caja.appendChild(h('div', { clase: 'fila-clave nueva' }, nueva,
      h('button', {
        clase: 'mini primario',
        onclick: () => guardarCuentasCLI(
          cuentas.map(c => ({ id: c.id, etiqueta: c.etiqueta }))
            .concat([{ etiqueta: nueva.value.trim() }])),
      }, 'Añadir cuenta')));
  } else {
    caja.appendChild(h('div', { clase: 'meta' },
      `${cli.max} es el tope: la cadena se recorre en serie cuando falla, y `
      + 'cada cuenta de más es una espera más antes de rendirse.'));
  }
  return caja;
}

function tarjetaCuentaCLI(cuenta, indice, cuentas) {
  const sesion = cuenta.sesion || {};
  const intento = cuenta.intento;
  const abierto = intento && ['abriendo', 'enlace', 'probando'].includes(intento.estado);
  const orden = h('div', { clase: 'cli-orden' },
    h('span', { clase: 'cli-puesto' }, cuenta.manda ? 'manda' : `${indice + 1}.ª`),
    h('button', {
      clase: 'mini fantasma', title: 'Subir: la de arriba se usa antes',
      disabled: indice === 0,
      onclick: () => moverCuentaCLI(cuentas, indice, -1),
    }, '↑'),
    h('button', {
      clase: 'mini fantasma', title: 'Bajar',
      disabled: indice >= cuentas.length - 1,
      onclick: () => moverCuentaCLI(cuentas, indice, 1),
    }, '↓'));

  /* El nombre es SOLO para ti, y por eso el hueco vacío enseña el correo de su
     sesión: cuando la cuenta ya está dentro, el correo la identifica de sobra y
     ponerle nombre es opcional. Hace falta de verdad ANTES de entrar —cuando
     todavía no hay correo que enseñar— y en el aviso de la cadena, que dice «la
     del curro falló; se sigue con la mía» en vez de «la 2.ª». */
  const etiqueta = h('input', {
    type: 'text', value: cuenta.etiqueta,
    title: 'Un nombre para ti: es el que sale en el aviso cuando esta cuenta '
      + 'falla y entra la siguiente',
    placeholder: sesion.correo || 'ponle un nombre: «la mía», «la del curro»…',
    /* Autoguardado al salir del campo: escribir el nombre de una cuenta no
       necesita un botón. */
    onchange: () => guardarCuentasCLI(cuentas.map(
      (c, i) => ({ id: c.id, etiqueta: i === indice ? etiqueta.value.trim() : c.etiqueta }))),
  });

  const tarjeta = h('div', { clase: 'cli-cuenta' + (cuenta.manda ? ' manda' : '') },
    h('div', { clase: 'fila' }, orden, etiqueta,
      pastillaEstado(sesion.conectada ? 'ok' : 'error',
        sesion.conectada
          ? (sesion.correo || 'con sesión') + (sesion.plan ? ` · ${sesion.plan}` : '')
          : 'sin sesión'),
      sesion.conectada ? pastillaSalud(cuenta.salud) : null,
      h('span', { clase: 'crece' }),
      sesion.conectada ? h('button', {
        clase: 'mini fantasma', disabled: abierto || estadoConfig().probando === cuenta.id,
        title: 'Le habla con una llamada mínima: es lo que distingue «con sesión» de «funciona»',
        onclick: () => probarCuentaCLI(cuenta.id),
      }, estadoConfig().probando === cuenta.id ? 'probando…' : 'Probar') : null,
      h('button', {
        clase: sesion.conectada ? 'mini' : 'primario mini', disabled: abierto,
        onclick: () => entrarCuentaCLI(cuenta.id),
      }, sesion.conectada ? 'Volver a entrar' : 'Entrar'),
      cuenta.propia && sesion.conectada ? h('button', {
        clase: 'mini fantasma', title: 'Cerrar la sesión de esta cuenta',
        onclick: () => salirCuentaCLI(cuenta),
      }, 'Salir') : null,
      h('button', {
        clase: 'mini fantasma', title: 'Quitar esta cuenta de la lista',
        onclick: () => {
          if (!window.confirm(`¿Quitar ${cuenta.etiqueta || 'esta cuenta'} de la `
            + 'lista? La sesión no se borra: se puede volver a añadir.')) return;
          guardarCuentasCLI(cuentas.filter((_, i) => i !== indice)
            .map(c => ({ id: c.id, etiqueta: c.etiqueta })));
        },
      }, '×')));

  if (sesion.error) tarjeta.appendChild(h('div', { clase: 'meta' }, sesion.error));
  if (sesion.conectada) {
    const aviso = avisoSalud(cuenta.salud);
    if (aviso) tarjeta.appendChild(aviso);
  }
  if (intento) tarjeta.appendChild(pasoDelAcceso(cuenta, intento));
  return tarjeta;
}

/* LA SALUD DE UNA CUENTA: lo último que pasó al hablarle (pasos/salud_cli.py).
   «Con sesión» no es «funciona»: una cuenta logueada con el cupo agotado
   pintaba verde hasta que alguien preguntaba algo. Va al lado de la sesión,
   en los tres sitios donde se ve una cuenta. */
const SALUD_PASTILLA = {
  ok: ['ok', 'funciona'],
  cupo: ['error', 'sin cupo'],
  sesion: ['error', 'sesión caducada'],
  tiempo: ['parcial', 'no contesta'],
  error: ['error', 'falla'],
};

function pastillaSalud(salud) {
  if (!salud || !SALUD_PASTILLA[salud.estado]) {
    return pastillaEstado('', 'sin probar');
  }
  const [estado, texto] = SALUD_PASTILLA[salud.estado];
  return pastillaEstado(estado, texto);
}

/* El motivo, cuando lo hay. Con el cupo agotado el mensaje del CLI lleva la
   fecha en que se renueva, que es lo único que importa leer. */
function avisoSalud(salud) {
  if (!salud || salud.estado === 'ok') return null;
  return h('div', { clase: salud.estado === 'tiempo' ? 'caja-aviso' : 'caja-error' },
    salud.mensaje || 'la última llamada a esta cuenta falló');
}

async function probarCuentaCLI(cid) {
  const vista = estadoConfig();
  vista.probando = cid;
  repintarClaves();
  try {
    const r = await pedir(API.probarCLI(cid), { method: 'POST' });
    vista.cli = Object.assign({}, vista.cli, { cuentas: r.cuentas });
    const salud = r.salud || {};
    if (salud.estado === 'ok') toast('la cuenta contesta');
    else toast(salud.mensaje || 'la cuenta no contesta', true);
  } catch (e) {
    toast(e.message, true);
  } finally {
    vista.probando = '';
  }
  repintarClaves();
  refrescarEstadoAsistente();
}

/* PROBAR TODAS LAS CLAVES contra su servicio (pasos/comprobar_claves.py):
   OpenAI, Cartesia, Jamendo, FreeSound y las cuentas de Claude, con llamadas
   que no cuestan dinero. Es el mismo bloque en Configuración y en la última
   tarjeta de la guía. */
const NOMBRES_PROVEEDOR = {
  openai: 'OpenAI — imágenes', cartesia: 'Cartesia — voz', jamendo: 'Jamendo — música',
  freesound: 'FreeSound — efectos', claude: 'Claude',
};

function bloquePruebaClaves() {
  const vista = estadoConfig();
  const caja = h('section', { clase: 'bloque-config' },
    h('div', { clase: 'fila' },
      h('h3', {}, 'Comprobar que funcionan'),
      h('span', { clase: 'crece' }),
      h('button', {
        clase: 'primario mini', disabled: !!vista.probandoTodas,
        onclick: () => probarTodasLasClaves(),
      }, vista.probandoTodas ? 'probando…' : 'Probar todas las claves')),
    h('div', { clase: 'pista' },
      '«Puesta» no es «funciona». Esto le habla a cada servicio con una llamada '
      + 'que no cuesta dinero y dice cuál autentica y cuál no. Lo único que no '
      + 'puede saber es si OpenAI tiene saldo: eso se mira en su Billing.'));
  const pruebas = vista.pruebas;
  if (pruebas) {
    pruebas.forEach(p => {
      const estado = { ok: 'ok', mal: 'error', sin_clave: '', sin_red: 'parcial' }[p.estado] || '';
      const texto = { ok: 'funciona', mal: 'falla', sin_clave: 'sin poner', sin_red: 'sin red' }[p.estado] || p.estado;
      caja.appendChild(h('div', { clase: 'prueba-clave' },
        h('div', { clase: 'fila' },
          h('b', {}, NOMBRES_PROVEEDOR[p.proveedor] || p.proveedor),
          h('span', { clase: 'crece' }),
          pastillaEstado(estado, texto)),
        h('div', { clase: 'meta' }, p.mensaje)));
    });
  }
  return caja;
}

async function probarTodasLasClaves() {
  const vista = estadoConfig();
  vista.probandoTodas = true;
  repintarClaves();
  try {
    const r = await pedir(API.probarClaves(), { method: 'POST', cuerpo: { claude: true } });
    vista.pruebas = r.pruebas || [];
    const sinPoner = vista.pruebas.filter(p => p.estado === 'sin_clave').length;
    toast(!r.todo_bien ? 'alguna clave falla: mira el detalle'
      : (sinPoner ? `las claves puestas funcionan; ${sinPoner} sin poner` : 'todas las claves funcionan'),
    !r.todo_bien);
  } catch (e) {
    toast(e.message, true);
  } finally {
    vista.probandoTodas = false;
  }
  cargarCuentasCLI();
  refrescarEstadoAsistente();
  repintarClaves();
}

/* El acceso, paso a paso. Los estados los pone el servidor
   (`login_cli.Intento`): abriendo · enlace · probando · dentro · fallo. */
function pasoDelAcceso(cuenta, intento) {
  const vista = estadoConfig();
  if (intento.estado === 'abriendo') {
    return h('div', { clase: 'cli-acceso' },
      h('div', { clase: 'cargando' }, 'pidiéndole el enlace al CLI…'));
  }
  if (intento.estado === 'dentro') {
    return h('div', { clase: 'cli-acceso ok' },
      h('div', { clase: 'meta' }, '✓ dentro. Ya cuenta para la cadena.'));
  }
  if (intento.estado === 'fallo') {
    return h('div', { clase: 'cli-acceso mal' },
      h('div', { clase: 'meta' }, intento.mensaje || 'no se ha podido entrar'),
      h('button', { clase: 'mini', onclick: () => entrarCuentaCLI(cuenta.id) },
        'Probar otra vez'));
  }
  /* 'enlace' y 'probando': lo mismo, con el botón bloqueado mientras comprueba. */
  const caja = h('textarea', {
    rows: 2, placeholder: 'pega aquí el código que te dé la página',
    value: vista.codigos[cuenta.id] || '',
    oninput: e => { vista.codigos[cuenta.id] = e.target.value; },
  });
  const mandar = () => mandarCodigoCLI(cuenta.id, caja.value.trim());
  return h('div', { clase: 'cli-acceso' },
    h('div', { clase: 'meta' },
      '1 · Abre este enlace y entra con la cuenta que quieras usar. Vale desde '
      + 'el móvil: el servidor no abre ningún navegador aquí.'),
    h('a', { clase: 'cli-enlace', href: intento.enlace, target: '_blank',
      rel: 'noopener noreferrer' }, 'Abrir la página de acceso'),
    h('div', { clase: 'fila' },
      h('button', {
        clase: 'mini fantasma',
        onclick: () => { navigator.clipboard.writeText(intento.enlace)
          .then(() => toast('enlace copiado'), () => toast('no se ha podido copiar', true)); },
      }, 'Copiar el enlace'),
      h('span', { clase: 'meta' }, `caduca en ${Math.ceil(intento.caduca_en / 60)} min`)),
    h('div', { clase: 'meta' },
      '2 · Si la página te da un código, pégalo aquí entero — incluido todo lo '
      + 'que va detrás de la almohadilla.'),
    caja,
    intento.mensaje ? h('div', { clase: 'meta aviso' }, intento.mensaje) : null,
    h('div', { clase: 'fila' },
      h('button', { clase: 'mini primario', disabled: intento.estado === 'probando',
        onclick: mandar },
        intento.estado === 'probando' ? 'comprobando…' : 'Entrar con este código'),
      h('button', { clase: 'mini fantasma',
        onclick: () => cancelarCuentaCLI(cuenta.id) }, 'Dejarlo')));
}

function moverCuentaCLI(cuentas, indice, salto) {
  const lista = cuentas.map(c => ({ id: c.id, etiqueta: c.etiqueta }));
  const destino = indice + salto;
  if (destino < 0 || destino >= lista.length) return;
  const [movida] = lista.splice(indice, 1);
  lista.splice(destino, 0, movida);
  guardarCuentasCLI(lista);
}

async function guardarCuentasCLI(cuentas) {
  try {
    estadoConfig().ficha = await pedir(API.claves(), {
      method: 'PUT', cuerpo: { claude_cli: { cuentas } },
    });
    await cargarCuentasCLI();
    toast('cuentas guardadas');
    refrescarEstadoAsistente();
  } catch (e) {
    toast(e.message, true);
  }
}

async function entrarCuentaCLI(cid) {
  try {
    const r = await pedir(API.entrarCLI(cid), { method: 'POST' });
    estadoConfig().cli = Object.assign({}, estadoConfig().cli, { cuentas: r.cuentas });
    estadoConfig().codigos[cid] = '';
    repintarClaves();
    latirCLI();
  } catch (e) {
    toast(e.message, true);
  }
}

async function mandarCodigoCLI(cid, codigo) {
  if (!codigo) { toast('pega el código que te ha dado la página', true); return; }
  const vista = estadoConfig();
  try {
    const r = await pedir(API.codigoCLI(cid), { method: 'POST', cuerpo: { codigo } });
    vista.cli = Object.assign({}, vista.cli, { cuentas: r.cuentas });
    if (r.intento && r.intento.estado === 'dentro') {
      vista.codigos[cid] = '';
      toast('cuenta dentro');
      // y se le habla una vez: entrar no es lo mismo que poder contestar
      probarCuentaCLI(cid);
    }
    repintarClaves();
    latirCLI();
  } catch (e) {
    toast(e.message, true);
  }
}

async function cancelarCuentaCLI(cid) {
  try {
    const r = await pedir(API.entrarCLI(cid), { method: 'DELETE' });
    estadoConfig().cli = Object.assign({}, estadoConfig().cli, { cuentas: r.cuentas });
    estadoConfig().codigos[cid] = '';
    repintarClaves();
  } catch (e) {
    toast(e.message, true);
  }
}

async function salirCuentaCLI(cuenta) {
  if (!window.confirm(`¿Cerrar la sesión de ${cuenta.etiqueta || 'esta cuenta'}? `
    + 'Habrá que volver a entrar para poder usarla.')) return;
  try {
    const r = await pedir(API.salirCLI(cuenta.id), { method: 'POST' });
    estadoConfig().cli = Object.assign({}, estadoConfig().cli, { cuentas: r.cuentas });
    repintarClaves();
    toast('sesión cerrada');
    refrescarEstadoAsistente();
  } catch (e) {
    toast(e.message, true);
  }
}

/* LA MÚSICA Y LOS EFECTOS. Dos claves, y se escriben AQUÍ.
 *
 * Antes se editaban a mano en el .env y esta pantalla sólo decía si estaban
 * puestas. Una pantalla que se llama «Configuración» y para una de sus claves
 * te manda a abrir un fichero con un editor de texto no está configurando
 * nada: está documentando dónde hacerlo.
 *
 * Sin ellas el vídeo se monta igual, sólo que en silencio: el paso de sonido
 * no busca nada y lo dice. Por eso son las únicas dos que pueden estar vacías
 * sin que nada se pare. */
function seccionOtrasClaves(ficha) {
  const caja = h('section', { clase: 'bloque-config' },
    h('h3', {}, 'Música y efectos'),
    h('div', { clase: 'pista' },
      'Dos catálogos con licencia libre. Sin ellas el vídeo se monta igual, '
      + 'pero sin banda sonora ni efectos.'));
  [['jamendo', 'Jamendo — música', 'el Client ID de tu aplicación en '
    + 'developer.jamendo.com'],
   ['freesound', 'FreeSound — efectos', 'la API key de tu cuenta en '
    + 'freesound.org/apiv2/apply']].forEach(([id, titulo, pista]) => {
    const puesta = ((ficha[id] || {}).puesta) || false;
    const cola = (ficha[id] || {}).cola || '';
    const campo = h('input', {
      type: 'password',
      placeholder: puesta ? `puesta (${cola})` : 'sin poner',
    });
    caja.appendChild(h('div', { clase: 'fila' },
      h('b', {}, titulo),
      h('span', { clase: 'crece' }),
      pastillaEstado(puesta ? 'ok' : 'vacio', puesta ? cola : 'sin poner')));
    caja.appendChild(h('div', { clase: 'pista' }, pista));
    caja.appendChild(h('div', { clase: 'fila-clave' }, campo,
      h('button', {
        clase: 'mini',
        onclick: () => {
          if (!campo.value.trim()) { toast('escribe la clave', true); return; }
          guardarClaves({ [id]: { clave: campo.value.trim() } });
          campo.value = '';
        },
      }, 'Cambiar'),
      (puesta ? h('button', {
        clase: 'mini fantasma peligro',
        onclick: () => guardarClaves({ [id]: { clave: '' } }),
      }, 'Quitar') : null)));
  });
  return caja;
}

async function guardarClaves(cambios) {
  try {
    estadoConfig().ficha = await pedir(API.claves(), {
      method: 'PUT', cuerpo: cambios,
    });
    repintarClaves();
    toast('claves guardadas');
  } catch (e) {
    toast(e.message, true);
  }
}

function campoSelect(etiqueta, valor, opciones, alCambiar, ayuda) {
  const sel = h('select', { onchange: ev => alCambiar(ev.target.value) });
  for (const op of opciones) {
    const v = typeof op === 'string' ? op : op.valor;
    const n = typeof op === 'string' ? op : op.nombre;
    sel.appendChild(h('option', { value: v }, n));
  }
  sel.value = valor === undefined || valor === null ? '' : String(valor);
  return h('div', { clase: 'campo' },
    h('label', {}, etiqueta), sel,
    ayuda ? h('div', { clase: 'pista' }, ayuda) : null);
}

/* ------------------------------------------------- donde se pinta el progreso
   La barra sale DEBAJO del boton que se ha pulsado, no en la cabecera del paso.
   Un paso puede tener varios botones que lo lanzan ("Generar todo", "Rehacer
   solo lo obsoleto", "Aplicar comentarios"...) y mirar arriba para ver que hace
   el que acabas de pulsar es justo lo que no quieres estar haciendo.

   Como pintarTrabajo() busca por [data-trabajo], basta con marcar cual de las
   ranuras manda: la del ultimo boton pulsado. */

/* Las ranuras de un paso que son de un mando, en orden de pantalla. La de
   respaldo de la cabecera queda fuera: no es de nadie, es el sitio al que va la
   barra cuando no hay boton al que colgarla. */
function ranurasDe(paso) {
  return [...$('#panel').querySelectorAll(`[data-trabajo="${paso}"]:not([data-respaldo])`)];
}

/* Que ranura manda, guardado FUERA del DOM.
   Vivia en el propio nodo (un data-activo) y no podia durar: lanzar() repinta el
   panel en la linea siguiente a arrancar el trabajo, y el avance de assets lo
   repinta otra vez en cada plano. La marca se perdia siempre, el buscador caia
   al primer hueco del documento y la barra de «Generar las escenas» acababa
   invariablemente dentro de la tarjeta de Assets, diciendo que Assets estaba
   generando planos.
   Se guarda la POSICION y no el nodo, porque tras repintar el nodo es otro
   objeto; el panel lo rehace el mismo codigo, asi que la ranura n-esima sigue
   siendo el mismo mando. Y vive en RANURAS, de modulo, y no en APP.vista: el
   boton de refrescar vacia APP.vista, y refrescar a media generacion es
   justamente lo que se hace cuando se lleva un rato esperando. Se limpia al
   cambiar de proyecto, que es cuando deja de significar nada. */
const RANURAS = {};

/* Si un nodo está dentro de una tarjeta plegada. Un `<details>` cerrado
   conserva sus hijos en el DOM, así que una barra pintada ahí existe y no se
   ve, que es la peor de las dos cosas. */
function estaPlegado(nodo) {
  for (let n = nodo; n && n !== document.body; n = n.parentElement) {
    if (n.tagName === 'DETAILS' && !n.open) return true;
  }
  return false;
}

/* La ranura donde toca pintar, por este orden: la del último botón pulsado si
   sigue en pantalla; la única que haya, si el paso tiene un solo mando; la
   última que esté DESPLEGADA; y si no, la de respaldo de la cabecera.
 *
 * Ese tercer escalón es nuevo y es el que arregla «al recargar pierdo la barra
 * de progreso». Cuando un trabajo se reengancha tras una recarga no hay ningún
 * botón pulsado, así que se caía directamente al respaldo de la cabecera —
 * arriba del todo, encima de las cuatro tarjetas—. Con las tarjetas
 * desplegadas eso queda a pantallas de distancia de donde estás mirando, y la
 * barra parecía no existir: seguía generando y la pantalla no lo decía en
 * ningún sitio donde se pudiera leer.
 *
 * Se coge la ÚLTIMA desplegada porque las tarjetas van en orden de trabajo y lo
 * que está corriendo es siempre lo más avanzado que se pudo lanzar. */
function ranuraActiva(paso) {
  const panel = $('#panel');
  const huecos = ranurasDe(paso);
  const visibles = huecos.filter(n => !estaPlegado(n));
  return huecos[RANURAS[paso]]
    || (huecos.length === 1 ? huecos[0] : null)
    || visibles[visibles.length - 1]
    || panel.querySelector(`[data-trabajo="${paso}"][data-respaldo]`)
    || huecos[0]
    || panel.querySelector(`[data-trabajo="${paso}"]`);
}

function versionDe(ficha) {
  return ficha.version
    || ((ficha.versiones || []).find(x => x.activa) || {}).n
    || (ficha.versiones || []).length;
}

function lupa(url, detalle) {
  const capa = h('div', {
    id: 'lupa',
    onclick: ev => { if (!detalle || ev.target === capa) capa.remove(); },
  }, h('img', { src: url }),
    // La ficha va DENTRO de la lupa y no debajo de la miniatura: en la
    // cuadrícula lo que se compara es el encuadre, y una tabla por miniatura
    // convierte seis vistas en una pared de texto que nadie lee.
    detalle ? h('div', { clase: 'ficha-lupa' }, detalle) : null);
  document.body.appendChild(capa);
}

/* ------------------------------------------------------------- ajustes del CLI
 * Varios pasos llaman por debajo al CLI de Claude y en todos ellos se puede
 * elegir MODELO y ESFUERZO de razonamiento. Las dos listas salen de
 * /api/ajustes-cli y de ningun otro sitio: mientras estuvieron escritas a mano
 * aqui, la interfaz ofrecia tres esfuerzos y el backend aceptaba cinco. Dos
 * listas en dos sitios se desincronizan solas.
 *
 * El tiempo de cada combinacion lo da /api/estadisticas, que guarda el historico
 * real de TODOS los proyectos. Regla que no se negocia: ninguna cifra de tiempo
 * se ensena sin decir si esta medida o estimada y de donde sale.
 */

/* En que claves de params guarda cada paso su ajuste. En revision_audio 'modelo'
   YA significa el modelo de voz de Cartesia, asi que el del CLI se llama
   'modelo_texto' y su esfuerzo 'esfuerzo_texto'. */
const CLAVES_CLI = {
  guion: { modelo: 'modelo', esfuerzo: 'esfuerzo' },
  revision_audio: { modelo: 'modelo_texto', esfuerzo: 'esfuerzo_texto' },
};

;

/* Paso de las estadisticas que corresponde al agente de capturas: las lanza
   callouts o render, pero el CLI que corre por debajo se mide como uno solo. */
const PASO_CAPTURAS = 'capturas_agente';

async function cargarAjustesCLI() {
  APP.cli = await pedir(API.ajustesCLI());
  return APP.cli;
}

function usaCLI(paso) {
  return (listaDe((APP.cli || {}).pasos) || []).includes(paso);
}

function nombreCLI(lista, id) {
  const ficha = (listaDe(lista) || []).find(x => x.id === id);
  return (ficha && ficha.nombre) || oHueco(id);
}

function nombreModelo(id) { return nombreCLI((APP.cli || {}).modelos, id); }
function nombreEsfuerzo(id) { return nombreCLI((APP.cli || {}).esfuerzos, id); }

/* Comparativas pedidas al servidor, una por paso: la del ultimo tamano pedido,
   que es la que se esta ensenando. Las peticiones en vuelo se comparten para que
   tres bloques de la misma pantalla no pidan lo mismo tres veces. */
const COMPARATIVAS_EN_VUELO = {};

async function pedirComparativa(paso, tamano, forzar) {
  const talla = Math.max(0, Math.round(Number(tamano) || 0));
  const guardada = APP.comparativas[paso];
  if (!forzar && guardada && guardada.tamano === talla) return guardada;
  const clave = `${paso}|${talla}`;
  if (!forzar && COMPARATIVAS_EN_VUELO[clave]) return COMPARATIVAS_EN_VUELO[clave];

  const promesa = pedir(API.estadisticas({ paso, tamano: talla })).then(datos => {
    const comparativa = datos.comparativa || {};
    const lista = listaDe(comparativa.ajustes) || [];
    const filas = {};
    for (const fila of lista) filas[fila.clave || `${fila.modelo}|${fila.esfuerzo}`] = fila;
    const ficha = {
      paso, tamano: talla, lista, filas,
      unidad: comparativa.unidad || 'unidades',
      aviso: comparativa.aviso || '',
      recomendacion: datos.recomendacion || null,
      historial: listaDe(datos.historial) || [],
    };
    APP.comparativas[paso] = ficha;
    return ficha;
  });
  COMPARATIVAS_EN_VUELO[clave] = promesa;
  promesa.catch(() => null).then(() => { delete COMPARATIVAS_EN_VUELO[clave]; });
  return promesa;
}

/* El ajuste por defecto de UN paso, que no es el general.
 *
 * El servidor sirve los dos en /api/ajustes-cli: `por_defecto` (sonnet/bajo,
 * el del CLI a secas) y `por_fase`, que es la tabla razonada de cli_claude —
 * opus/alto para la guía de estilo,
 * haiku/bajo para reescribir un bloque de audio. Esta pantalla sólo miraba el
 * general, así que la guía de estilo se anunciaba como «Sonnet · esfuerzo
 * Bajo» cuando lo que iba a ejecutar el backend era Opus con esfuerzo alto:
 * dos cifras distintas para la misma llamada, y la que se leía era la falsa.
 * Con esto, lo que pone la pantalla es lo que se ejecuta. */
function ajusteRecomendado(paso) {
  const catalogo = APP.cli || {};
  const fase = (catalogo.por_fase || {})[paso];
  return fase || catalogo.por_defecto || {};
}

/* Ajuste elegido ahora mismo en un paso que lo guarda en params. */
function ajusteElegido(paso) {
  const defecto = ajusteRecomendado(paso);
  const claves = CLAVES_CLI[paso];
  // borradorDe() crea el borrador si no existe; sin ficha cargada eso guardaria
  // un borrador vacio que luego taparia los params de verdad
  const params = claves && APP.fichas[paso] ? borradorDe(paso) : {};
  return {
    modelo: (claves && params[claves.modelo]) || defecto.modelo || '',
    esfuerzo: (claves && params[claves.esfuerzo]) || defecto.esfuerzo || '',
  };
}

/* Fila de la comparativa que corresponde a lo que hay elegido, si ya se pidio. */
function filaAjusteActual(paso) {
  const guardada = APP.comparativas[paso];
  if (!guardada || !CLAVES_CLI[paso]) return null;
  const ajuste = ajusteElegido(paso);
  return guardada.filas[`${ajuste.modelo}|${ajuste.esfuerzo}`] || null;
}

function tiempoDeFila(fila) {
  if (!fila) return '—';
  return fila.reloj || duracionCorta(fila.segundos);
}

/* Sello de honestidad de una cifra. Un tiempo sin esta etiqueta no se pinta. */
function selloCifra(fila) {
  if (!fila) return null;
  if (fila.medida) {
    return h('span', { clase: 'sello-cifra medida', title: fila.origen || '' },
      `medida · ${cifra(fila.ejecuciones, '0')} ejecución(es)`);
  }
  return h('span', { clase: 'sello-cifra', title: fila.origen || '' }, 'estimación, no medida');
}

/* Lo que se sabe de una combinacion mas alla del tiempo: cuantas veces salio
   bien, cuantas se valoraron y como. Es lo que distingue «rapida» de «buena». */
function detalleFila(fila) {
  if (!fila) return '';
  const trozos = [];
  if (fila.ejecuciones) {
    trozos.push(`${cifra(fila.correctas, '0')} de ${cifra(fila.ejecuciones, '0')} terminaron bien`);
    if (fila.fiabilidad !== undefined && fila.fiabilidad !== null) {
      trozos.push(`fiabilidad ${Math.round(fila.fiabilidad * 100)}%`);
    }
    if (fila.sin_reintento !== undefined && fila.sin_reintento !== null) {
      trozos.push(`a la primera ${Math.round(fila.sin_reintento * 100)}%`);
    }
    if (fila.aceptacion !== undefined && fila.aceptacion !== null) {
      trozos.push(`aceptación ${Math.round(fila.aceptacion * 100)}%`);
    }
  }
  if (fila.valorada_bien || fila.valorada_mal) {
    trozos.push(`valorada ${fila.valorada_bien} bien / ${fila.valorada_mal} mal`);
  } else if (fila.ejecuciones) {
    trozos.push('nadie ha valorado todavía el resultado');
  }
  if (fila.tokens_salida) trozos.push(`${corto(fila.tokens_salida)} tokens de salida`);
  return trozos.join(' · ');
}

async function valorarAjuste(paso, valoracion, modelo, esfuerzo) {
  const datos = await pedir(API.valoracion(), {
    method: 'POST',
    cuerpo: { paso, valoracion, modelo, esfuerzo, proyecto: APP.pid || undefined },
  });
  const ajuste = (datos.recomendacion || {}).ajuste || {};
  toast(`valoración anotada · ahora se recomienda ${nombreModelo(ajuste.modelo)}`
    + ` con esfuerzo ${nombreEsfuerzo(ajuste.esfuerzo)}`);
  return datos;
}

/* ================================================================== 1 INGESTA */

;

/* EL MATERIAL. Calcado del encargo del modo light: una lista de cajas donde
 * cabe cualquier cosa que sea texto —un enlace de YouTube, una página, una
 * noticia, tres, un artículo pegado, una frase con la idea o tu propio guion—.
 * El TIPO lo deduce el servidor (`fuentes.clasificar`); lo que se pregunta es
 * el USO, con una casilla: «esto YA es el guion, respétalo palabra por
 * palabra». Eso no se puede deducir mirando el texto, y de hecho intentarlo
 * fue el error del detector de copias que se retiró.
 *
 * Va a `params.guion.fuentes`, que es el mismo cajón que rellena el light al
 * crear el vídeo, y se guarda solo. Un enlace de YouTube entre el material es
 * ADEMÁS el vídeo de origen: lo enruta el servidor al guardar
 * (`_origen_del_material`), y la tarjeta de abajo lo enseña. */
const YOUTUBE_JS = /^https?:\/\/(www\.|m\.)?(youtube\.com|youtu\.be)\//i;
const ENLACE_JS = /^https?:\/\/\S+$/i;

/* ================================================================== 1 INGESTA */

/* Un canal se compone de presets que ya existen: eliges el idioma, el estilo,
   el ritmo y la voz de entre los guardados y eso es el canal.
   Se hace asi, y no leyendo los params del proyecto abierto, por dos razones:
   la pestana de Origen no tiene cargadas las fichas de brief, voz ni assets
   —pedirlas solo para esto son tres peticiones por visita—, y sobre todo
   porque un canal se define una vez con las piezas ya decididas, no con lo que
   este puesto en el video que tengas abierto ahora mismo.

   Lo que se guarda son los VALORES, copiados en el momento: cambiar despues el
   preset de voz no cambia el canal, y borrarlo no lo rompe. */
/* ================================================================== 2 BRIEF */

/* LA CADENCIA LA DA EL SERVIDOR, no una tabla de aquí.
 *
 * Aquí hubo una copia de `p2_brief.PALABRAS_POR_SEGUNDO` (2,3 y 2,6) para poder
 * enseñar la horquilla sin llamar a nadie. Era la TERCERA copia de la misma
 * cuenta —brief, modo simulado de la voz y esto— y además la que menos sabía:
 * ignoraba la velocidad de la voz y el aire entre bloques, que es la mitad de lo
 * que mueve el reloj. Ahora la pide a `/api/estimacion`, que es el mismo sitio
 * del que sale el coste y el número de planos, y mientras llega se enseña «…».
 */
const TOLERANCIA_BRIEF = 0.30;         // +-30%, el tope que admite el paso

/* La estimación, cacheada por lo que se le pregunta. La misma pantalla la pide
   al mover el deslizador y al repintar, y sin caché eso es una llamada por
   repintado para una cuenta que no ha cambiado. */
const CACHE_ESTIMACION = new Map();

async function estimacionDe(peticion) {
  const clave = JSON.stringify(peticion);
  if (CACHE_ESTIMACION.has(clave)) return CACHE_ESTIMACION.get(clave);
  const promesa = pedir(API.estimacion(), { method: 'POST', cuerpo: peticion });
  CACHE_ESTIMACION.set(clave, promesa);
  try {
    return await promesa;
  } catch (e) {
    CACHE_ESTIMACION.delete(clave);   // un fallo de red no se cachea
    throw e;
  }
}

/* La línea que se lee debajo de la duración. Dice las tres cosas que hacen falta
   para decidirla: cuántas palabras, entre qué dos duraciones REALES va a caer el
   vídeo, y de dónde sale la cadencia. Lo último no es un adorno: «estimado»
   significa que todavía no hay ninguna toma de ese idioma que medir. */
function textoDeEstimacion(ficha) {
  const pal = ficha.palabras || {};
  const seg = ficha.segundos || {};
  return `${mmss(ficha.duracion_objetivo_s)} · ≈${miles(pal.objetivo)} palabras `
    + `(${miles(pal.minimo)}–${miles(pal.maximo)}) · saldrá entre `
    + `${mmss(Math.round(seg.minimo))} y ${mmss(Math.round(seg.maximo))}`;
}

// Suelo TECNICO, no editorial: lo justo para que haya algo que segmentar. Aqui
// habia 600 s porque "un video del estudio dura al menos 10 minutos", que es una
// decision de linea editorial y no una regla del sistema. Un corto de 40 s vale.
const DURACION_MINIMA_S = 10;
// Tope del deslizador. Se puede pasar de largo escribiendo en la casilla: el
// deslizador es para lo comodo, no para lo posible.
const DURACION_SLIDER_MIN_S = 30;

;

;

/* UN VÍDEO, UN IDIOMA (24-08-2026). Aquí había chips arrastrables con el
   principal marcado con una estrella: el guion se redactaba en el principal y se
   adaptaba al resto conservando los ids. Se retiró el eje entero — hacer el
   mismo vídeo en otro idioma es otro proyecto, y de un guion cuelgan una toma de
   voz, una imagen por plano y unos subtítulos que no se comparten.

   La clave vieja se sigue LEYENDO para que un proyecto guardado con ella se abra
   en su idioma y no en castellano; lo que se escribe es `idioma_salida`. */
;
/* ================================================================== 3 GUION */

/* AQUÍ VIVÍA «Otros idiomas»: un plegable que leía las adaptaciones del guion
   a los idiomas secundarios. Se fue con el eje de idiomas el 24-08-2026: un
   vídeo se hace en uno, y el mismo vídeo en otro es otro proyecto. */

/* ================================================================== 4 VOZ */

/* EL VOCABULARIO DE LA VOZ. Son los valores que entiende Cartesia, y el gemelo
   exacto de `p4_voz.VELOCIDADES` y compania: si aqui sobra o falta uno, la
   pantalla ofrece algo que el servidor rechaza, o esconde algo que si acepta.

   Se fueron por delante el 24-08-2026, en la retirada del eje de idiomas: el
   corte se llevo de rebote el bloque entero --las cuatro listas y los dos
   ayudantes de emociones-- porque estaba pegado a lo que si sobraba. Y no se
   noto, porque JavaScript no se queja de un nombre que no existe hasta que
   alguien PINTA esa pantalla: el panel de Voz y el paso de voz del modo light
   morian con «VELOCIDADES is not defined» y el resto de la interfaz seguia
   tan tranquila. */
;
const VELOCIDADES = ['slowest', 'slow', 'normal', 'fast', 'fastest'];
const EMOCIONES = ['anger', 'curiosity', 'positivity', 'sadness', 'surprise'];
;

async function regrabarSeccion(sid, peticion) {
  limpiarError('regrabar_seccion');
  try {
    const datos = await pedir(API.regrabarSeccion(APP.pid, sid), {
      method: 'POST', cuerpo: { peticion },
    });
    const tid = datos.trabajo_id || (datos.trabajo || {}).id;
    if (!tid) throw new Error('el servidor no ha devuelto ningún trabajo');
    seguirTrabajo('regrabar_seccion', tid, async trabajo => {
      if (trabajo.estado === 'listo') {
        const cambiados = (trabajo.resultado || {}).bloques_cambiados || [];
        toast(cambiados.length
          ? `${sid} regrabada · texto cambiado en ${cambiados.join(', ')} `
            + '(también en el guion)'
          : `${sid} regrabada`);
        delete APP.vista.audio_revision;
        await refrescarTodo();
      }
      pintarPanel();
    });
    pintarPanel();
  } catch (e) { mostrarError('regrabar_seccion', e); }
}

/* El paso devuelve una ruta de disco o una url; aqui se acepta cualquiera de
   las dos para no atarse a como la sirva el servidor. */
function urlDeResultado(resultado) {
  if (!resultado) return null;
  if (typeof resultado === 'object') {
    return urlDeResultado(resultado.url || resultado.ruta || resultado.pista || resultado.archivo);
  }
  const texto = String(resultado);
  // Una ruta que ya venga absoluta hay que prefijarla igual: el servicio la
  // genera sin saber tras que prefijo lo esta sirviendo el proxy.
  if (texto.startsWith('http')) return texto;
  if (texto.startsWith('/a/')) return BASE + texto;
  const limpio = texto.split('\\').join('/');
  const corte = limpio.indexOf('/previsualizaciones/');
  if (corte >= 0) return API.archivo(APP.pid, limpio.slice(corte + 1));
  return API.archivo(APP.pid, limpio);
}

/* ================================================================== 5 REVISION */

/* ------------------------------------ referencias reales del video original
 * Los fotogramas de la ingesta, etiquetados con lo que se narraba en su
 * segundo, sirven para que el dibujo de una persona o un sitio CONCRETO se
 * parezca al original en vez de a lo que el modelo se imagine.
 *
 * Se aprueban AQUI, leyendo el guion, porque la decision es sobre un trozo de
 * narracion y no sobre una imagen suelta: verla anclada al texto es verla en su
 * contexto. Pero se GUARDAN en los params de assets, porque lo unico que cambia
 * si tocas esto son las imagenes -- ni el texto ni la voz --, y meterlo en el
 * guion obligaria a reescribir los dos por una decision que no les afecta. */

/* Aqui vivieron el «seleccionar y comentar» (sustituido por el regrabado POR
   SECCION) y despues la pantalla de aprobar referencias del video original
   (etiquetar, proponer, aprobar). Las dos se retiraron enteras de la interfaz;
   los endpoints /frames/* siguen en el servidor y p6 usa las referencias
   aprobadas si existen. Ver docs/REFERENCIAS-REALES.md. */


/* ================================================================== 6 ASSETS */

;

/* ---------------------------------------------------------------- cartelas
 * Planos que son TEXTO SOBRE NEGRO en vez de una imagen generada.
 *
 * Viven en Assets y no en Rótulos aunque sean grafismo, y el motivo es el
 * dinero: una cartela cambia el PLAN —ese plano deja de generar imagen—, así
 * que tiene que estar decidida antes de generar. Decidirla en Rótulos, que va
 * después, sería pagar una imagen para tirarla.
 *
 * Las muestras las dibuja el servidor con el MISMO código que monta la cartela
 * de verdad (cartelas.svg_carta), así que lo que se ve aquí es lo que va a
 * salir. Una maqueta hecha aparte se desincroniza en cuanto alguien toca una
 * plantilla, y entonces esta pantalla ofrece cartelas que ya no existen.
 */

;

;

/* AQUÍ VIVÍA «mirar»: el agente que abría los PNG uno a uno y decía cuál tenía
 * manos raras, el logo equivocado o una escena que no era la pedida. Se retiró
 * el 24-08-2026 por decisión del canal, con su módulo, su endpoint y su banda
 * encima de la rejilla. Señalaba y no cambiaba nada de lo que salía; lo que
 * hace que una imagen salga bien se decide ANTES de generarla, y eso sigue:
 * la guía de estilo, las referencias y la dirección de cada plano. */

/* ------------------------------------------------------------ catalogo visual
 * Quien sale, donde ocurre cada tramo y con que tono.
 *
 * Es lo que alimenta el reparto de sets y encuadres de p6_assets. Sin el, el
 * paso no fallaba: dejaba los 174 planos sin sitio, sin camara y sin personajes,
 * y el modelo acababa devolviendo el plano anterior con un cambio pequeno. Ahora
 * el paso se niega a generar sin catalogo, y esto es donde se consigue.
 *
 * Proponer NO es aprobar: el agente lee el guion entero y devuelve una
 * propuesta; lo que entra en los params es lo que se guarda desde aqui.
 */

;

;

;

/* Un clic para todos los escenarios: deduce los sitios del guion y construye
   los que falten, uno detrás de otro, en un solo trabajo.

   Va como trabajo único y no como una tanda de llamadas desde aquí por dos
   razones. La primera es que si se corta a mitad —cerrar la pestaña, un móvil
   que se bloquea— lo que ya estaba construido sigue construido y lo que faltaba
   sigue faltando, en vez de quedarse a medias con la interfaz creyendo otra
   cosa. La segunda es que un escenario que no valida no puede tumbar los demás:
   cada uno es una llamada larga, y perder cinco porque el sexto falla sería lo
   peor posible. Lo que falle se dice al final, por su nombre. */
/* ------------------------------------------------------- imagenes de estilo
 * Las referencias de estilo son las imagenes que se le adjuntan al generador
 * en CADA escena y definen como se dibuja. Se sacan de un video de YouTube
 * cuyo look guste, que normalmente NO es el video de referencia del proyecto:
 * uno aporta el contenido y el otro el estilo.
 *
 * Elegirlas es del usuario, y a proposito: se intento automatizarlo y no
 * funciona con dibujo plano (el detector de caras da casi cero en personajes de
 * trazo y el de texto marca paisajes limpios como si tuvieran rotulos). Lo
 * unico que se descarta solo son los fotogramas casi negros.
 *
 * Sin al menos 3 imagenes esta pantalla no es un adorno: la llamada a la API de
 * imagen sale SIN adjuntos y la rechaza con "Unsupported content type", que es
 * el error incomprensible que costo una tarde. */

/* El prompt de estilo escrito a mano fue el primer intento de fijar el estilo,
   y lo sustituyo la guia escrita: la guia dice lo mismo pero MIRANDO los
   fotogramas elegidos, con paleta en hexadecimales y todo. Tener los dos es
   tener dos fuentes de verdad que se contradicen.

   El campo ya no se ofrece, pero el parametro sigue existiendo y sigue entrando
   en el prompt de cada imagen (`p6_assets`), asi que en un proyecto antiguo hay
   que ENSENARLO y dar la manera de quitarlo. Borrarlo por las bravas cambiaria
   el dibujo de un proyecto en marcha sin avisar. */
/* ---------------------------------------------- moodboard de estilo

   Las referencias de estilo son fotogramas de OTRO vídeo, y cubren lo que ese
   vídeo resultó tener. Si no hay un primer plano de cara, el generador nunca ve
   cómo se resuelve una cara en ese estilo — y una hoja de personaje se juzga por
   la cara. Aquí se dibujan a propósito los ejes que el pipeline necesita.

   Con una persona en medio, y no por trámite: estas láminas las dibuja el mismo
   modelo que después las imita. Medido en la primera prueba, de cuatro ejes dos
   salieron clavados y dos derivaron (un sofá con sombreado suave, una taza con
   degradado). Por eso se miran, se corrigen POR EJE y solo entonces entran. */

;
;
/* Los planos aparecen segun se generan, no todos al final.
   Una tanda de assets son varios minutos y hasta ahora la rejilla se quedaba
   igual todo ese rato: no habia forma de ver si estaba saliendo lo que querias
   hasta que ya estaba pagado entero. Se refresca cuando cambia la CUENTA de
   unidades hechas, no en cada latido, porque cada refresco es una peticion. */
/* Cada escenario que termina se enseña YA. El backend dice por cuál va
   («escenario 2 de 5»).
   Se refresca al cambiar la CUENTA y no en cada latido, porque cada refresco es
   una petición. */
function avanceAssets() {
  let ultimo = '';
  return trabajo => {
    const hechas = (leerAvance(trabajo.mensaje).mensaje.match(/(\d+)\s*(?:de|\/)\s*\d+/) || [])[1];
    if (!hechas || hechas === ultimo) return;
    ultimo = hechas;
    delete APP.vista.datos_assets;
    // los planos que ya están en disco: es lo ÚNICO que se mueve durante la
    // tanda, porque las unidades no se sellan hasta que el paso termina
    cargarPlanosHechos(true);
    pintarPanel();
  };
}

async function alTerminarAssets() {
  delete APP.vista.datos_assets;
  delete APP.vista.montaje;
  CACHE_ARCHIVOS.clear();
  cargarPlanosHechos(true);
  await refrescarTodo();
}

;

/* QUE PLANOS HAY GENERADOS AHORA MISMO, preguntandoselo al servidor.
 *
 * Las unidades no se sellan hasta que el paso TERMINA, asi que durante una
 * tanda de cinco minutos la ficha no dice nada nuevo. La rejilla se llenaba
 * porque construia la ruta de cada imagen a partir del id del plano, y eso
 * traia el problema de al lado: los ids son posicionales y se heredan entre
 * planes, la carpeta de trabajo conserva lo de la version anterior, y un plano
 * SIN GENERAR ensenaba tan tranquilo la imagen de otro que se llamo asi antes.
 *
 * Este endpoint lee la ficha que el generador deja junto a cada imagen. Con
 * ella se pueden hacer las dos cosas bien: ensenar lo que va saliendo, y no
 * ensenar lo que no es de ese plano. */
function estadoPlanosHechos() {
  if (!APP.vista.planos_hechos) {
    APP.vista.planos_hechos = { mapa: {}, cargando: false, pedido: '' };
  }
  return APP.vista.planos_hechos;
}

function cargarPlanosHechos(forzar) {
  const vista = estadoPlanosHechos();
  if (vista.cargando) return;
  if (!forzar && vista.pedido === APP.pid) return;
  vista.cargando = true;
  vista.pedido = APP.pid;
  pedir(API.planosHechos(APP.pid))
    .then(datos => {
      const antes = Object.keys(vista.mapa).length;
      vista.mapa = datos.planos || {};
      // solo se repinta si hay algo nuevo: durante una tanda esto se pide cada
      // pocos segundos y repintar por costumbre tira el foco de las cajas
      if (Object.keys(vista.mapa).length !== antes) pintarPanel();
    })
    // un servidor viejo no tiene la ruta: se sigue sin previsualizacion viva
    .catch(() => {})
    .then(() => { vista.cargando = false; });
}

/* Lo que el plan sabe de sí mismo y antes moría dentro de plan.json.

   Son las dos formas de que el vídeo salga peor sin que nada chille: un plano
   que se traga dos ideas —«...sus propios sistemas. España, mayo de 2024.» en
   un solo plano— y dos sitios distintos rodados en la misma habitación. Las dos
   se saben al planificar y las dos se veían solo mirando el vídeo terminado. */
/* Los encuadres de un set, en cuadrícula, con el mismo patrón que la tarjeta de
   un escenario 3D. Devuelve null si el asset no es un set con cámaras, y
   entonces la tarjeta pinta su imagen de siempre.

   Se enseñan hasta seis: dos filas caben en la tarjeta, y el pie dice cuántos
   hay en total. Enseñar uno era decir que un set es una imagen —y lo que se
   revisa aquí es justamente si el sitio da suficientes ángulos distintos—. */
/* ================================================================== 7 CALLOUTS */

/* ------------------------------------------------------- qué rótulos entran
 * No todos los vídeos quieren el mismo grafismo: hay montajes que piden
 * cabeceras de sitio y nada más, y otros donde una cifra a tamaño de titular
 * cada poco es justo lo que los hace.
 *
 * Se eligen MIRÁNDOLOS. La muestra de cada uno la dibuja el mismo código que
 * dibuja la capa de verdad (p7.muestra_de), así que lo que se ve aquí es lo
 * que va a salir; una maqueta hecha aparte se desincroniza en cuanto alguien
 * toca una forma y entonces esta pantalla ofrece rótulos que ya no existen. */



/* El plan: qué rótulo lleva cada plano, decidido por una IA mirando la imagen.
   Va dentro de la misma caja pero plegado: es la única parte que cuesta dinero
   y que no se toca hasta tener los planos generados. */

;


/* ================================================================== 8 RENDER */

/* ------------------------------------------------------------ transiciones
 * El catálogo de shaders de hyperframes, elegido MIRÁNDOLO.
 *
 * La muestra corre EL MISMO GLSL que el render: el servidor manda el fragment
 * shader de cada transición y aquí se compila en un canvas. Una maqueta hecha
 * aparte —un gif, una animación CSS que «se parezca»— se desincroniza en
 * cuanto cambie un shader, y entonces se elige una cosa y sale otra. Es la
 * misma regla que las muestras de arquetipo y las de cartela.
 *
 * Los dos fotogramas de la muestra son dibujados y no planos del vídeo, a
 * propósito: lo que hay que ver de una transición es SU FORMA —por dónde entra,
 * qué deforma, cuánto dura—, y eso se lee mejor sobre dos imágenes que no se
 * parecen en nada. Van con los colores de la guía de estilo del vídeo, que es
 * de donde salen también los tres uniformes de acento.
 */

/* UN SHADER DE TRANSICIÓN, COMPILADO Y LISTO PARA PINTAR UN PROGRESO.

   Partido en dos a propósito. Compilar un programa de WebGL y subir dos
   texturas cuesta; pintar un fotograma no. La muestra del catálogo compila una
   vez y pinta en bucle, y el repaso del montaje compila al llegar al corte y
   pinta el progreso que le toca a ese instante del vídeo. Antes las dos cosas
   estaban cosidas dentro del bucle de la muestra, así que el reproductor no
   podía usar el shader de verdad y enseñaba una aproximación en CSS —un
   destello y un encadenado— que no es lo que va a salir en el vídeo.

   Devuelve null si el navegador no da WebGL o si el shader no compila: quien
   llame decide qué enseñar en su lugar. */
/* EL RECUENTO, EN EL RESUMEN DE LA SECCIÓN. Vivía dentro del plegable interior
   («6 puesta(s) · las de fábrica»), o sea que para leerlo había que abrir la
   tarjeta, abrir el plegable, y entonces cerrar los dos. Un resumen sirve
   justamente para no tener que abrir nada (PENDIENTE 31).

   Las dos frases caben juntas: qué es esto y cuántas hay puestas. */
/* --------------------------------------------------------- música y efectos
 * Dos momentos separados, y en la pantalla se nota: aquí se BUSCA y se ELIGE,
 * con la red delante; renderizar no sale a la red — coge del banco lo que digan
 * los params. Una búsqueda en Jamendo devuelve cosas distintas cada semana, y
 * el mismo plan tiene que dar el mismo vídeo.
 *
 * El banco de efectos es del CANAL, no de este vídeo: un golpe de transición
 * que sirve para uno sirve para el siguiente. Por eso «Traer efectos» se pulsa
 * una vez y ya vale para todos.
 */

/* EL VETO DE UN EFECTO. Es del CANAL y no del vídeo: un sonido que no gusta no
   gusta en el siguiente tampoco. Y no borra el fichero del banco, porque
   borrarlo sólo conseguiría que la próxima búsqueda lo bajase otra vez —
   Freesound ordena por descargas, así que devuelve los mismos a todo el mundo.

   No hace falta volver a surtir: `sonido.elegir` respeta el veto sobre el
   surtido que ya hay, así que deja de sonar en cuanto se vuelva a montar el
   MP4 — y eso no recodifica ni un clip, la banda se mezcla al muxear. */
/* LA BANDA SONORA NO SE ELIGE, SE MONTA. Aquí no hay lista de canciones ni
   botón de escuchar: el ritmo del montaje decide los tramos, cada tramo pide su
   ánimo y de los candidatos se queda el que mejor deja libre la banda de la voz
   —graves llenos, medios flojos—, medido con una FFT en vez de a oído.

   Lo que queda para una persona es mirar el resultado, no producirlo. */
/* ================================================================== CAPTURAS
 * Captura anotable de los pasos 7 y 8. La unidad de feedback aqui no es la
 * escena: es (escena, segundo exacto). Un plano con un zoom lento puede estar
 * bien al empezar y mal al acabar, y eso con feedback por escena solo se puede
 * describir con palabras.
 *
 * El fotograma lo compone el NAVEGADOR:
 *   - callouts: no vale capturar la pantalla. Se reconstruye con la misma
 *     matematica del render -- el hyperframe recortado por la ventana de zoom
 *     de ese instante (la calcula el servicio con p7.ventana_en, no se
 *     recalcula aqui) mas la capa vectorial encima.
 *   - render: se dibuja el <video> en un canvas en su currentTime, que es
 *     exacto por construccion.
 */

;
;
/* Detras del fotograma compuesto, por si la imagen no llena el lienzo entero.
   Es el mismo fondo del Estudio: asi la captura se ve como lo que se estaba
   mirando, no como un recorte sobre un negro cualquiera. */
const FONDO_CAPTURA = '#0a0b0e';
const REFRESCO_CAPTURAS = {};

async function aplicarCapturas(paso, modo, ajuste) {
  limpiarError(paso);
  // El backend valida el ajuste SIEMPRE, tambien en modo 'directo', aunque solo
  // lo use el agente: asi un ajuste imposible se ve ahora y no la proxima vez.
  const cuerpo = { modo };
  if (ajuste && ajuste.modelo) cuerpo.modelo = ajuste.modelo;
  if (ajuste && ajuste.esfuerzo) cuerpo.esfuerzo = ajuste.esfuerzo;
  try {
    const datos = await pedir(API.aplicarCapturas(APP.pid), { method: 'POST', cuerpo });
    const aplazados = Object.entries(datos.aplazados || {})
      .map(([otro, unidades]) => `${nombreDe(otro)} (${unidades.length})`);
    toast(`aplicando ${(datos.grupos || []).length} grupo(s) en ${nombreDe(datos.paso)}`
      + (aplazados.length ? ` · quedan para después: ${aplazados.join(', ')}` : ''));
    seguirTrabajo(datos.paso, datos.trabajo_id, async () => {
      delete APP.vista.montaje;
      CACHE_ARCHIVOS.clear();
      await refrescarTodo();
    });
    pintarTrabajo(datos.paso);
    if (REFRESCO_CAPTURAS[paso]) REFRESCO_CAPTURAS[paso]();
  } catch (e) {
    mostrarError(paso, e);
  }
}

/* ================================================================== COSTE
 * Medidor de la cabecera. No estima: cada motor reporta lo que consumio y aqui
 * solo se suma y se pinta. Los importes que salen de la tabla de tarifas se
 * marcan distinto de los medidos, y Claude sale sin importe porque va contra la
 * suscripcion: un dolar inventado ahi seria peor que un hueco.
 */

const COSTE = { datos: null, pasos: null, abierto: false, ultima: 0, cita: null };

function refrescarCoste(forzar) {
  if (!APP.pid) return;
  const desde = Date.now() - COSTE.ultima;
  // el flujo de progreso late muchas veces por segundo: sin freno, cada latido
  // seria una peticion mas
  if (!forzar && desde < 1500) {
    if (!COSTE.cita) COSTE.cita = setTimeout(() => { COSTE.cita = null; refrescarCoste(true); }, 1500);
    return;
  }
  COSTE.ultima = Date.now();
  const pid = APP.pid;
  pedir(API.coste(pid))
    .then(datos => {
      if (APP.pid !== pid) return;
      COSTE.datos = datos;
      pintarCoste();
      if (COSTE.abierto) pintarDesgloseCoste();
    })
    .catch(e => {
      COSTE.datos = null;
      $('#coste').textContent = 'coste: no disponible';
      $('#coste').title = e.message;
    });
}

/* Ficha de un proveedor con sus huecos rellenos: el agregado puede no traer un
   proveedor que todavia no ha gastado nada. */
function proveedorDe(agregado, nombre) {
  const ficha = ((agregado || {}).proveedores || {})[nombre] || {};
  return Object.assign({ usd: null, eventos: 0 }, ficha, {
    tokens: Object.assign({ entrada: 0, salida: 0, cache: 0, total: 0 }, ficha.tokens),
    cantidad: Object.assign({ imagenes: 0, caracteres: 0 }, ficha.cantidad),
  });
}

function importeCoste(ficha, hueco) {
  if (!ficha) return h('span', { clase: 'meta' }, '—');
  // sin un solo evento no hay importe que ensenar: un '$0.00' ahi se lee como
  // 'esto no cuesta nada', cuando lo cierto es que todavia no se ha usado
  if (hueco && !ficha.eventos) return h('span', { clase: 'meta' }, '—');
  if (ficha.sin_tarifa && !ficha.usd) {
    return h('span', { clase: 'sin-tarifa', title: 'falta la tarifa por carácter en tarifas.json' },
      'sin tarifa');
  }
  if (ficha.usd === null || ficha.usd === undefined) {
    return h('span', { clase: 'meta', title: 'va contra la suscripción: no tiene importe' }, '—');
  }
  return h('span', {
    clase: ficha.usd_estimado ? 'usd derivado' : 'usd medido',
    title: ficha.usd_estimado
      ? 'importe derivado de la tabla de tarifas (tarifas.json), no de una factura'
      : 'importe medido',
  }, `$${Number(ficha.usd).toFixed(2)}`);
}

function pintarCoste() {
  const nodo = $('#coste');
  vaciar(nodo);
  const datos = COSTE.datos;
  if (!datos) { nodo.textContent = 'coste: —'; return; }
  const abierto = proveedorDe(datos, 'openai');
  const voz = proveedorDe(datos, 'tts');
  const cli = proveedorDe(datos, 'claude_cli');

  nodo.appendChild(h('span', { clase: 'prov' }, h('b', {}, 'OpenAI'), importeCoste(abierto),
    h('span', { clase: 'meta' }, `${corto(abierto.tokens.total)} tok`)));
  nodo.appendChild(h('span', { clase: 'prov' }, h('b', {}, 'TTS'), importeCoste(voz),
    h('span', { clase: 'meta' }, `${corto(voz.cantidad.caracteres)} car`)));
  // Claude va sin importe y no entra en el TOTAL
  nodo.appendChild(h('span', { clase: 'prov' }, h('b', {}, 'Claude'),
    h('span', { clase: 'meta', title: 'va contra la suscripción: no suma al total' },
      `${corto(cli.tokens.total)} tok`)));
  nodo.appendChild(h('span', { clase: 'prov total' }, h('b', {}, 'TOTAL'),
    h('span', { clase: 'usd' }, `$${Number(datos.total_usd || 0).toFixed(2)}`)));

  if (datos.presupuesto_usd) {
    const fraccion = Math.min(1, Number(datos.fraccion_presupuesto) || 0);
    nodo.appendChild(h('span', {
      clase: 'presupuesto' + (datos.aviso_presupuesto ? ' aviso' : ''),
      title: `presupuesto ${datos.presupuesto_usd} $ · consumido ${Math.round(fraccion * 100)}%`,
    }, h('i', { estilo: `width:${(fraccion * 100).toFixed(0)}%` })));
  }
  nodo.classList.toggle('aviso', !!datos.aviso_presupuesto);
}

/* La tarifa del TTS es el unico numero de la tabla que no se puede saber desde
   aqui: Cartesia cobra por caracter a un precio que depende del plan contratado.
   Mientras este vacio el medidor cuenta caracteres y marca el importe como «sin
   tarifa», que es un hueco visible en vez de un numero inventado. Esto es el
   sitio donde escribirlo cuando se tenga la factura, para no tener que editar
   tarifas.json a mano ni llamar a la API. */
function seccionTarifaTTS(datos) {
  const voz = proveedorDe(datos, 'tts');
  const actual = datos.tarifa_caracter;
  const puesta = actual !== null && actual !== undefined;
  if (!puesta && !voz.sin_tarifa && !voz.eventos) return null;

  const entrada = h('input', {
    type: 'number', step: '0.000001', min: '0', estilo: 'width:130px',
    placeholder: '0.000025',
    value: puesta ? String(actual) : '',
  });
  const guardar = async valor => {
    try {
      const salida = await pedir(API.tarifas(), {
        method: 'PUT', cuerpo: { usd_por_caracter: valor },
      });
      toast(valor === null ? 'tarifa del TTS quitada'
        : `tarifa fijada en ${salida.usd_por_caracter} $ por carácter`);
      // refrescarCoste repinta el desglose el solo cuando esta abierto: llamarlo
      // aqui ademas ensenaria un instante la cifra vieja
      refrescarCoste(true);
    } catch (e) { toast(partirError(e.message).titular, true); }
  };

  return h('div', { clase: puesta ? 'caja-info' : 'caja-aviso', estilo: 'margin-top:10px' },
    h('b', {}, puesta ? `Tarifa del TTS: ${actual} $ por carácter. `
      : 'El TTS sale «sin tarifa». '),
    puesta
      ? 'Cartesia factura por carácter, y en Sonic un crédito es un carácter. Lo que se '
        + 'anota es el coste marginal (el precio del crédito de más), no el prorrateo de '
        + 'la cuota mensual: los créditos incluidos ya están pagados, y repartirlos haría '
        + 'que el mismo vídeo costara distinto según cuánto se hubiera usado antes.'
      : 'Cartesia factura por carácter a un precio que depende del plan contratado, así que '
        + 'el medidor cuenta los caracteres reales y deja el importe en blanco antes que '
        + 'inventarlo. Escribe aquí el número de tu factura y empezará a sumar.',
    h('div', { clase: 'fila', estilo: 'margin-top:8px' },
      h('label', { estilo: 'margin:0' }, '$ por carácter'), entrada,
      h('button', {
        clase: 'mini primario',
        onclick: () => {
          const texto = entrada.value.trim();
          if (!texto) { toast('escribe el precio por carácter, o usa «Quitar»', true); return; }
          const valor = Number(texto);
          if (!(valor > 0)) { toast('el precio por carácter tiene que ser un número mayor que 0', true); return; }
          guardar(valor);
        },
      }, 'Guardar'),
      puesta ? h('button', { clase: 'mini', onclick: () => guardar(null) }, 'Quitar') : null,
      voz.eventos ? h('span', { clase: 'meta' },
        `${corto(voz.cantidad.caracteres)} caracteres locutados en este vídeo`) : null),
    h('div', { clase: 'pista' },
      'Se guarda en tarifas.json y vale para todos los proyectos. Los eventos ya anotados no se '
      + 'reescriben, así que lo que se locutó antes seguirá saliendo «sin tarifa»: cambiarlo '
      + 'haría que el gasto declarado de un vídeo se moviera después de haberlo pagado.'));
}

async function pintarDesgloseCoste() {
  const caja = $('#coste-detalle');
  const datos = COSTE.datos;
  if (!datos) {
    vaciar(caja).appendChild(h('div', { clase: 'vacio' },
      'todavía no se ha podido leer el coste de este vídeo'));
    return;
  }
  vaciar(caja);
  caja.appendChild(h('div', { clase: 'cargando' }, 'leyendo el desglose…'));
  let porPaso = null;
  try { porPaso = await pedir(API.costePorPaso(APP.pid)); }
  catch (e) { porPaso = null; }
  if (!COSTE.abierto) return;
  vaciar(caja);

  const fila = ficha => {
    const abierto = proveedorDe(ficha, 'openai');
    const voz = proveedorDe(ficha, 'tts');
    const cli = proveedorDe(ficha, 'claude_cli');
    return [
      h('td', {}, importeCoste(abierto, true)),
      h('td', { clase: 'numerico meta' },
        abierto.eventos ? `${corto(abierto.cantidad.imagenes)} img` : ''),
      h('td', {}, importeCoste(voz, true)),
      h('td', { clase: 'numerico meta' },
        voz.eventos ? `${corto(voz.cantidad.caracteres)} car` : ''),
      h('td', { clase: 'numerico meta' },
        cli.eventos ? `${corto(cli.tokens.total)} tok` : ''),
      h('td', { clase: 'numerico' }, `$${Number(ficha.total_usd || 0).toFixed(3)}`),
    ];
  };

  const tabla = h('table', { clase: 'tabla coste-pasos' },
    h('tr', {}, h('th', {}, 'Paso'), h('th', {}, 'OpenAI'), h('th', {}, ''),
      h('th', {}, 'TTS'), h('th', {}, ''), h('th', {}, 'Claude'), h('th', {}, 'Total')));
  for (const ficha of (porPaso && listaDe(porPaso.pasos)) || []) {
    if (!ficha.eventos) continue;
    tabla.appendChild(h('tr', {}, h('th', {}, ficha.nombre || ficha.paso || 'sin paso'), fila(ficha)));
  }
  if (tabla.children.length === 1) {
    tabla.appendChild(h('tr', {}, h('th', {}, 'sin gasto'),
      h('td', { colspan: '6', clase: 'meta' }, 'este vídeo todavía no ha consumido nada')));
  }

  const limite = h('input', {
    type: 'number', step: '0.5', min: '0', estilo: 'width:110px',
    placeholder: 'sin límite',
    value: datos.presupuesto_usd === null || datos.presupuesto_usd === undefined
      ? '' : String(datos.presupuesto_usd),
  });

  const ausente = ((datos.instrumentacion || {}).ausente) || [];

  caja.appendChild(h('div', { clase: 'contenido-coste' },
    h('div', { clase: 'fila' },
      h('h2', {}, `Coste de ${oHueco(datos.nombre, datos.proyecto)}`),
      h('span', { clase: 'crece' }),
      h('span', { clase: 'meta' }, `${cifra(datos.eventos, '0')} evento(s)`
        + (datos.ultimo ? ` · último ${fechaCorta(datos.ultimo)}` : ''))),
    tabla,
    h('div', { clase: 'fila', estilo: 'margin-top:12px' },
      h('label', { estilo: 'margin:0' }, 'Presupuesto del vídeo ($)'), limite,
      h('button', {
        clase: 'mini',
        onclick: async () => {
          const valor = limite.value.trim() === '' ? null : Number(limite.value);
          try {
            COSTE.datos = await pedir(API.costePresupuesto(APP.pid), {
              method: 'PUT', cuerpo: { usd: valor },
            });
            pintarCoste();
            pintarDesgloseCoste();
            toast(valor === null ? 'presupuesto quitado' : `presupuesto fijado en ${valor} $`);
          } catch (e) { toast(partirError(e.message).titular, true); }
        },
      }, 'Guardar'),
      datos.presupuesto_usd
        ? h('span', { clase: datos.aviso_presupuesto ? 'pastilla obsoleto' : 'meta' },
          `consumido ${Math.round((datos.fraccion_presupuesto || 0) * 100)}%`)
        : null),
    datos.aviso_presupuesto ? h('div', { clase: 'caja-aviso', estilo: 'margin-top:10px' },
      'Se ha superado el 80% del presupuesto de este vídeo.') : null,
    seccionTarifaTTS(datos),
    ausente.length ? h('div', { clase: 'caja-aviso', estilo: 'margin-top:10px' },
      `El medidor no está enganchado a: ${ausente.join(', ')}. Lo que gaste eso no se cuenta.`) : null,
    h('div', { clase: 'pista', estilo: 'margin-top:10px' },
      h('span', { clase: 'usd derivado' }, '$0.00'), ' importe derivado de la tabla de tarifas · ',
      h('span', { clase: 'usd medido' }, '$0.00'), ' importe medido · ',
      'Claude se mide solo en tokens y no suma al TOTAL: va contra la suscripción.')));
}

function conmutarCoste() {
  COSTE.abierto = !COSTE.abierto;
  $('#coste-detalle').classList.toggle('plegado', !COSTE.abierto);
  $('#coste').classList.toggle('abierto', COSTE.abierto);
  if (COSTE.abierto) pintarDesgloseCoste();
}

/* ============================================================== RENDIMIENTO
 * Historico de tiempos del CLI. Es pantalla propia y no subpestana de un paso a
 * proposito: lo que ensena NO es de este video, es de TODOS los proyectos.
 * Colgado del panel de un paso se leeria como «lo que ha tardado este», que es
 * justo lo contrario de lo que dice.
 */

const RENDIMIENTO = { paso: null, panorama: null };

/* Nombre legible tambien de los pasos que no son pestanas: el agente de capturas
   y el catalogo visual no estan en el grafo, pero miden tiempo igual. Sin esto
   salian en crudo ('capturas_agente') junto a los demas ya con su nombre. */
const NOMBRES_FUERA_DEL_GRAFO = {
  capturas_agente: 'Agente de capturas',
  catalogo_visual: 'Catálogo visual',
  conservacion: 'Qué se puede conservar',
  guia_estilo: 'Guía de estilo',
  etiquetar_frames: 'Etiquetar fotogramas',
  proponer_frames: 'Proponer referencias',
  moodboard: 'Moodboard de estilo',
  // No es un paso del grafo ni vive en ninguna pestaña: es el trabajo del modo
  // light, que monta un estilo entero. Sin el nombre, el faro y los avisos
  // decían «preset_light».
  preset_light: 'Estilo del canal',
  // la tanda del modo editor: las mismas cuatro que el light, en su ranura
  receta: 'La tanda',
  fuentes: 'El material',
  // Y los dos del vídeo del modo light, por lo mismo y con más motivo: esos dos
  // salen en el faro de la barra mientras se graba, y decían 'video_light'.
  video_light: 'El vídeo',
  voz_light: 'La voz',
};

function nombrePasoCLI(id) {
  const enGrafo = APP.pasos.find(p => p.id === id);
  if (enGrafo) return enGrafo.nombre || id;
  return NOMBRES_FUERA_DEL_GRAFO[id] || String(id || '').split('_').join(' ');
}

/* Pulgares. Son la unica senal de calidad que no es un proxy: sin ellos el
   recomendador solo sabe recomendar lo mas rapido, que es una tautologia. */
function botonesValoracion(paso, fila, alTerminar) {
  const hay = !!(fila && fila.ejecuciones);
  const motivo = hay
    ? `valora la ÚLTIMA ejecución de ${nombrePasoCLI(paso)} con ${fila.modelo}/${fila.esfuerzo}`
    : 'todavía no hay ninguna ejecución con esta combinación que valorar';
  const votar = valoracion => async ev => {
    ev.stopPropagation();
    try {
      await valorarAjuste(paso, valoracion, fila.modelo, fila.esfuerzo);
      if (alTerminar) await alTerminar();
    } catch (e) { toast(partirError(e.message).titular, true); }
  };
  return h('span', { clase: 'fila votos' },
    h('button', { clase: 'mini', disabled: !hay, title: motivo, onclick: votar('bien') }, '👍'),
    h('button', { clase: 'mini', disabled: !hay, title: motivo, onclick: votar('mal') }, '👎'),
    (fila && (fila.valorada_bien || fila.valorada_mal))
      ? h('span', { clase: 'meta', title: 'valorada bien / mal' },
        `${fila.valorada_bien}/${fila.valorada_mal}`) : null);
}

function tablaPanorama(panorama) {
  const pasos = (panorama || {}).pasos || {};
  const enGrafo = APP.pasos.map(p => p.id);
  const claves = Object.keys(pasos).sort((a, b) => {
    const ia = enGrafo.indexOf(a) === -1 ? 99 : enGrafo.indexOf(a);
    const ib = enGrafo.indexOf(b) === -1 ? 99 : enGrafo.indexOf(b);
    return ia - ib || a.localeCompare(b);
  });
  const tabla = h('table', { clase: 'tabla' },
    h('tr', {}, h('th', {}, 'Paso'), h('th', {}, 'CLI'), h('th', {}, 'Ejecuciones'),
      h('th', {}, 'Bien'), h('th', {}, 'Proyectos'), h('th', {}, 'Mediana'),
      h('th', {}, 'Unidad'), h('th', {}, 'Última'), h('th', {}, '')));
  for (const clave of claves) {
    const ficha = pasos[clave] || {};
    tabla.appendChild(h('tr', { clase: ficha.usa_cli ? 'con-cli' : '' },
      h('th', {}, nombrePasoCLI(clave)),
      h('td', {}, ficha.usa_cli ? h('span', { clase: 'pastilla ok' }, 'sí') : h('span', { clase: 'meta' }, 'no')),
      h('td', { clase: 'numerico' }, cifra(ficha.ejecuciones, '0')),
      h('td', { clase: 'numerico' }, cifra(ficha.correctas, '0')),
      h('td', { clase: 'numerico' }, cifra(ficha.proyectos, '0')),
      h('td', { clase: 'numerico' }, ficha.ejecuciones
        ? oHueco(ficha.mediana, duracionCorta(ficha.mediana_s)) : '—'),
      h('td', { clase: 'meta' }, oHueco(ficha.unidad, '')),
      h('td', { clase: 'meta' }, ficha.ultima ? fechaCorta(ficha.ultima) : '—'),
      h('td', {}, ficha.usa_cli
        ? h('button', { clase: 'mini fantasma', onclick: () => pintarRendimiento(clave) }, 'ver')
        : null)));
  }
  return tabla;
}

function vistaPasoRendimiento(paso, ficha, datos, recargar) {
  const rec = datos.recomendacion || {};
  const ajusteRec = rec.ajuste || {};
  const claveRec = ajusteRec.modelo ? `${ajusteRec.modelo}|${ajusteRec.esfuerzo}` : '';

  const tabla = h('table', { clase: 'tabla comparativa-cli' },
    h('tr', {}, h('th', {}, 'Modelo'), h('th', {}, 'Esfuerzo'), h('th', {}, 'Tiempo'),
      h('th', {}, 'Qué es esa cifra'), h('th', {}, 'Lo que se sabe'),
      h('th', {}, 'De dónde sale'), h('th', {}, '¿Salió bien?')));
  for (const fila of datos.lista) {
    const clave = fila.clave || `${fila.modelo}|${fila.esfuerzo}`;
    tabla.appendChild(h('tr', { clase: clave === claveRec ? 'recomendada' : '' },
      h('td', {}, nombreModelo(fila.modelo)),
      h('td', {}, nombreEsfuerzo(fila.esfuerzo)),
      h('td', { clase: 'numerico' }, tiempoDeFila(fila)),
      h('td', {}, selloCifra(fila)),
      h('td', { clase: 'meta' }, detalleFila(fila)),
      h('td', { clase: 'meta' }, fila.origen || ''),
      h('td', {}, botonesValoracion(paso, fila, recargar))));
  }

  const historial = h('table', { clase: 'tabla' },
    h('tr', {}, h('th', {}, 'Cuándo'), h('th', {}, 'Tardó'), h('th', {}, 'Tamaño'),
      h('th', {}, 'Ajuste'), h('th', {}, 'Terminó'), h('th', {}, 'Valoración')));
  for (const registro of datos.historial.slice().reverse()) {
    const detalle = registro.detalle && !esResumido(registro.detalle) ? registro.detalle : {};
    historial.appendChild(h('tr', {},
      h('td', { clase: 'meta' }, fechaCorta(registro.fecha)),
      h('td', { clase: 'numerico' }, duracionCorta(registro.segundos)),
      h('td', { clase: 'numerico meta' }, cifra(registro.tamano, '—')),
      h('td', { clase: 'meta' }, `${oHueco(detalle.modelo)} / ${oHueco(detalle.esfuerzo)}`),
      h('td', {}, registro.ok === false
        ? h('span', { clase: 'pastilla error' }, 'error')
        : h('span', { clase: 'pastilla ok' }, 'bien')),
      h('td', { clase: 'meta' }, oHueco(registro.valoracion, '—'))));
  }

  return h('div', {},
    h('div', { clase: 'fila' },
      h('h2', {}, nombrePasoCLI(paso)),
      h('span', { clase: 'meta' },
        `${cifra(ficha.ejecuciones, '0')} ejecución(es) · ${cifra(ficha.correctas, '0')} terminaron bien`
        + ` · ${cifra(ficha.proyectos, '0')} proyecto(s)`),
      ficha.ejecuciones
        ? h('span', { clase: 'meta' }, `mediana ${oHueco(ficha.mediana, duracionCorta(ficha.mediana_s))}`)
        : null,
      h('span', { clase: 'crece' }),
      h('span', { clase: 'meta' }, datos.tamano
        ? `comparativa para ${miles(datos.tamano)} ${datos.unidad}`
        : `comparativa sin tamaño de entrada (${datos.unidad})`)),

    h('div', { clase: 'caja-info recomendacion-cli', estilo: 'margin:10px 0' },
      h('div', { clase: 'fila' },
        h('b', {}, `Recomendado: ${nombreModelo(ajusteRec.modelo)}`
          + ` · esfuerzo ${nombreEsfuerzo(ajusteRec.esfuerzo)}`),
        rec.reloj ? h('span', { clase: 'meta' }, `≈ ${rec.reloj}`) : null,
        h('span', { clase: `pastilla confianza ${rec.confianza || 'ninguna'}` },
          `confianza ${rec.confianza || 'ninguna'}`)),
      h('div', { clase: 'pista' }, rec.motivo || ''),
      (listaDe(rec.descartadas) || []).length
        ? h('div', { clase: 'pista' },
          `Descartadas por poco fiables: ${rec.descartadas.join(' · ')}`) : null),

    h('div', { clase: 'tabla-cli' }, tabla),
    datos.aviso ? h('div', { clase: 'pista' }, datos.aviso) : null,
    h('div', { clase: 'pista' },
      'Los pulgares valoran la ÚLTIMA ejecución que hubo con esa combinación. Es la única '
      + 'señal de calidad que tiene el recomendador: sin ellos solo puede recomendar lo más '
      + 'rápido, que no es lo mismo que lo mejor.'),

    h('h2', { estilo: 'margin-top:18px' }, 'Últimas ejecuciones'),
    datos.historial.length ? historial
      : h('div', { clase: 'vacio' }, 'este paso todavía no ha corrido nunca'));
}

async function pintarRendimiento(paso) {
  const capa = document.getElementById('rendimiento');
  if (!capa) return;
  const elegido = paso || null;      // 'sin paso' es null, nunca undefined
  RENDIMIENTO.paso = elegido;
  const nav = vaciar(capa.querySelector('.nav-rendimiento'));
  const cuerpo = vaciar(capa.querySelector('.cuerpo'));
  cuerpo.appendChild(h('div', { clase: 'cargando' }, 'leyendo el histórico…'));

  const conCLI = (listaDe((APP.cli || {}).pasos) || []);
  nav.appendChild(h('button', {
    clase: 'subpestana' + (RENDIMIENTO.paso ? '' : ' activa'),
    onclick: () => pintarRendimiento(null),
  }, 'Todos los pasos'));
  for (const otro of conCLI) {
    nav.appendChild(h('button', {
      clase: 'subpestana' + (RENDIMIENTO.paso === otro ? ' activa' : ''),
      onclick: () => pintarRendimiento(otro),
    }, nombrePasoCLI(otro)));
  }

  try {
    if (!RENDIMIENTO.panorama) RENDIMIENTO.panorama = await pedir(API.estadisticas({}));
    const panorama = RENDIMIENTO.panorama;
    if (!document.getElementById('rendimiento')) return;
    vaciar(cuerpo);
    if (!RENDIMIENTO.paso) {
      cuerpo.append(
        tablaPanorama(panorama),
        h('div', { clase: 'pista' },
          `Fichero del histórico: ${oHueco(panorama.fichero)} · se guardan hasta `
          + `${cifra(panorama.muestras_por_ajuste, '?')} muestras por combinación. `
          + 'Las medianas son de todos los proyectos juntos.'));
      return;
    }
    // se reaprovecha el tamano que ya se pidio para ese paso, para no dejar en el
    // cache una comparativa de otro tamano que luego el panel tendria que rehacer
    const talla = (APP.comparativas[RENDIMIENTO.paso] || {}).tamano || 0;
    const datos = await pedirComparativa(RENDIMIENTO.paso, talla, true);
    // si mientras tanto se ha cambiado de subpestana, esto ya no es lo que se mira
    if (!document.getElementById('rendimiento') || RENDIMIENTO.paso !== elegido) return;
    vaciar(cuerpo);
    cuerpo.appendChild(vistaPasoRendimiento(
      RENDIMIENTO.paso, (panorama.pasos || {})[RENDIMIENTO.paso] || {}, datos,
      async () => {
        RENDIMIENTO.panorama = null;
        await pintarRendimiento(RENDIMIENTO.paso);
      }));
  } catch (e) {
    vaciar(cuerpo).appendChild(cajaError(e.message));
  }
}

function abrirRendimiento(paso) {
  const viejo = document.getElementById('rendimiento');
  if (viejo) viejo.remove();
  RENDIMIENTO.panorama = null;
  const capa = h('div', {
    id: 'rendimiento',
    onclick: ev => { if (ev.target === capa) capa.remove(); },
  }, h('div', { clase: 'cuadro' },
    h('div', { clase: 'cab' },
      h('b', {}, 'Rendimiento del CLI'),
      h('span', { clase: 'meta' }, 'histórico de TODOS los proyectos, no solo del abierto'),
      h('span', { clase: 'crece' }),
      h('button', { clase: 'mini fantasma', onclick: () => capa.remove() }, '×')),
    h('div', { clase: 'subpestanas nav-rendimiento' }),
    h('div', { clase: 'cuerpo' })));
  document.body.appendChild(capa);
  pintarRendimiento(paso || null);
}

/* ============================================================== PROYECTOS
 * Apartar no es borrar: la carpeta entera se mueve a proyectos/_papelera/ y se
 * puede devolver. Borrar de verdad SOLO se puede hacer desde la papelera, con
 * confirmacion y diciendo cuantos ficheros y cuantos megas se pierden.
 */

function cerrarMenuProyectos() {
  $('#menu-proyectos').classList.add('plegado');
}

function conmutarMenuProyectos() {
  const menu = $('#menu-proyectos');
  if (!menu.classList.contains('plegado')) { cerrarMenuProyectos(); return; }
  vaciar(menu);
  for (const proyecto of APP.proyectos) {
    const nombre = proyecto.nombre || proyecto.id;
    menu.appendChild(h('div', {
      clase: 'fila-proyecto' + (proyecto.id === APP.pid ? ' abierto' : ''),
    },
      h('button', {
        clase: 'abrir', title: `abrir «${nombre}»`,
        onclick: () => { cerrarMenuProyectos(); if (proyecto.id !== APP.pid) abrirProyecto(proyecto.id); },
      }, h('span', { clase: 'nombre' }, nombre),
        h('span', { clase: 'meta' }, proyecto.id)),
      /* DUPLICAR va aquí, al lado de apartar, y no en el pie: las dos son
         acciones sobre ESE proyecto, no sobre la lista. */
      h('button', {
        clase: 'mini fantasma', title: `duplicar «${nombre}» tal y como está hoy`,
        onclick: () => { cerrarMenuProyectos(); duplicarProyecto(proyecto.id, nombre); },
      }, '⧉'),
      h('button', {
        clase: 'mini fantasma apartar', title: `apartar «${nombre}» (no lo borra)`,
        onclick: () => { cerrarMenuProyectos(); apartarProyecto(proyecto.id, nombre); },
      }, '🗑')));
  }
  if (!APP.proyectos.length) {
    menu.appendChild(h('div', { clase: 'vacio', estilo: 'padding:8px 12px' },
      'no hay ningún proyecto'));
  }
  menu.appendChild(h('div', { clase: 'pie-menu' },
    h('button', { clase: 'mini', onclick: () => { cerrarMenuProyectos(); nuevoProyecto(); } },
      '+ nuevo'),
    h('button', { clase: 'mini fantasma', onclick: () => { cerrarMenuProyectos(); abrirPapelera(); } },
      'Papelera'),
    h('span', { clase: 'crece' }),
    h('button', {
      clase: 'mini fantasma', title: 'Tiempos reales del CLI en todos los proyectos',
      onclick: () => { cerrarMenuProyectos(); abrirRendimiento(); },
    }, 'Rendimiento')));
  menu.classList.remove('plegado');
}

/* DUPLICAR UN PROYECTO: repetir un vídeo con algo cambiado sin volver a pagar
   las imágenes y sin tocar el original.

   Lo que se dice antes de pulsar, porque es lo que la gente pregunta: qué se
   copia (lo que hay puesto HOY, no el historial de cómo se llegó) y qué NO se
   copia. Un proyecto son varias horas y varios euros; una copia que se lleva
   11 GB de versiones viejas sin avisar es una sorpresa cara. */
async function duplicarProyecto(pid, nombre) {
  if (!pid) { toast('no hay ningún proyecto que duplicar', true); return; }
  const propuesto = `Copia ${nombre || pid}`;
  const elegido = window.prompt(
    `Duplicar «${nombre || pid}».\n\n`
    + 'Se copia lo que el proyecto tiene puesto HOY: la versión activa de cada '
    + 'paso, con sus imágenes y su locución. El historial de versiones se queda '
    + 'en el original.\n\n'
    + 'Nombre de la copia:', propuesto);
  if (elegido === null) return;
  const nombreCopia = String(elegido).trim() || propuesto;
  toast(`copiando «${nombre || pid}»…`);
  try {
    const datos = await pedir(API.duplicar(pid), {
      method: 'POST', cuerpo: { nombre: nombreCopia },
    });
    const copia = (datos.proyecto || {}).id;
    await cargarProyectos();
    toast(`copia hecha: «${nombreCopia}»`);
    if (copia) abrirProyecto(copia);
  } catch (e) {
    toast(`no se ha podido duplicar: ${partirError(e.message).titular}`, true);
  }
}

async function apartarProyecto(pid, nombre) {
  if (!pid) { toast('no hay ningún proyecto que apartar', true); return; }
  if (!window.confirm(`Apartar «${nombre || pid}».\n\n`
    + 'NO se borra nada. La carpeta entera se mueve a la papelera y el proyecto deja de '
    + 'salir en la lista. Se puede devolver cuando quieras desde la papelera.\n\n'
    + 'Si tiene algún trabajo en marcha, el servidor lo rechazará: cancélalo antes.')) return;
  try {
    const datos = await pedir(API.apartar(pid), { method: 'DELETE' });
    toast(`«${nombre || pid}» apartado · ${datos.aviso || 'sigue entero en la papelera'}`);
    if (pid === APP.pid) {
      localStorage.removeItem('estudio.pid');
      Object.keys(APP.seguimientos).forEach(soltarSeguimiento);
      APP.pid = null;
    }
    await cargarProyectos();
    if (!APP.proyectos.length) {
      APP.pid = null;
      APP.proyecto = null;
      $('#meta-proyecto').textContent = '';
      pintarBotonProyecto();
      vaciar($('#panel')).appendChild(h('div', { clase: 'contenido' },
        h('div', { clase: 'caja-info' },
          'No queda ningún proyecto. Crea uno con «+ nuevo», o devuelve uno desde la papelera.')));
    }
  } catch (e) { toast(partirError(e.message).titular, true); }
}

/* ------------------------------------------------------------- conservacion
 * Un cambio aguas arriba ya no significa rehacerlo todo. Aquí se ve qué se
 * salva, por qué, y se aplica.
 *
 * La pantalla enseña las tres cosas por separado y en este orden, porque es el
 * orden en el que se decide: qué le ha pasado al guion, qué planos se salvan y
 * cuáles no, y qué va a costar lo que queda. Un botón que dijera solo
 * "conservar 168 de 174" sin poder mirar cuáles sería pedir un acto de fe. */

;

;

function abrirPapelera() {
  const viejo = document.getElementById('papelera');
  if (viejo) viejo.remove();
  const cuerpo = h('div', { clase: 'cuerpo' });
  const capa = h('div', {
    id: 'papelera',
    onclick: ev => { if (ev.target === capa) capa.remove(); },
  }, h('div', { clase: 'cuadro' },
    h('div', { clase: 'cab' },
      h('b', {}, 'Papelera'),
      h('span', { clase: 'meta' }, 'lo apartado sigue entero en el disco'),
      h('span', { clase: 'crece' }),
      h('button', { clase: 'mini fantasma', onclick: () => capa.remove() }, '×')),
    cuerpo));
  document.body.appendChild(capa);

  const marcadas = new Set();

  const pintar = async () => {
    vaciar(cuerpo).appendChild(h('div', { clase: 'cargando' }, 'leyendo la papelera…'));
    // Los presets apartados van en la MISMA papelera, con su propia etiqueta:
    // lo que se pierde al vaciarla no se parece en nada (un proyecto son gigas
    // de imagenes pagadas, un preset son unos fotogramas y un parrafo), asi que
    // cada fila dice lo que es. Si el endpoint no existe todavia, esta parte no
    // sale y la de proyectos funciona igual.
    let presetsApartados = [];
    try { presetsApartados = listaDe((await pedir(API.presetsCanal())).papelera) || []; }
    catch (e) { presetsApartados = []; }
    try {
      const datos = await pedir(API.papelera());
      if (!document.getElementById('papelera')) return;
      const lista = listaDe(datos.papelera) || [];
      // una carpeta que ya no esta no puede seguir marcada
      const vivas = new Set(lista.map(f => f.carpeta));
      [...marcadas].forEach(c => { if (!vivas.has(c)) marcadas.delete(c); });
      vaciar(cuerpo);
      if (!lista.length && !presetsApartados.length) {
        cuerpo.appendChild(h('div', { clase: 'vacio' }, 'la papelera está vacía'));
        cuerpo.appendChild(h('div', { clase: 'pista' }, `Carpeta: ${oHueco(datos.raiz)}`));
        return;
      }
      if (!lista.length) {
        cuerpo.appendChild(h('div', { clase: 'vacio' }, 'no hay ningún proyecto apartado'));
        cuerpo.appendChild(tablaPresetsPapelera(presetsApartados, pintar));
        return;
      }

      const contador = h('span', { clase: 'meta' });
      const botonBorrar = h('button', { clase: 'peligro' }, 'Borrar definitivamente');
      const refrescarMandos = () => {
        contador.textContent = marcadas.size
          ? `${marcadas.size} marcado(s) de ${lista.length}`
          : `ninguno marcado (${lista.length} en la papelera)`;
        botonBorrar.disabled = !marcadas.size;
        cuerpo.querySelectorAll('tr[data-carpeta]').forEach(fila => {
          fila.classList.toggle('marcada', marcadas.has(fila.dataset.carpeta));
        });
      };

      const tabla = h('table', { clase: 'tabla' },
        h('tr', {}, h('th', {}, ''), h('th', {}, 'Qué es'), h('th', {}, 'Proyecto'),
          h('th', {}, 'Apartado'), h('th', {}, 'Creado'), h('th', {}, '')));
      for (const ficha of lista) {
        const marca = h('input', {
          type: 'checkbox', checked: marcadas.has(ficha.carpeta),
          title: 'marcar para borrarlo definitivamente',
          onchange: ev => {
            if (ev.target.checked) marcadas.add(ficha.carpeta);
            else marcadas.delete(ficha.carpeta);
            refrescarMandos();
          },
        });
        tabla.appendChild(h('tr', { datos: { carpeta: ficha.carpeta } },
          h('td', {}, marca),
          h('td', {}, h('span', { clase: 'tag-papelera proyecto' }, 'proyecto')),
          h('th', {}, oHueco(ficha.nombre, ficha.id), h('div', { clase: 'meta' }, oHueco(ficha.id, ''))),
          h('td', { clase: 'meta' }, oHueco(ficha.apartado)),
          h('td', { clase: 'meta' }, fechaCorta(ficha.creado)),
          h('td', {}, h('button', {
            clase: 'mini',
            title: `devolver ${ficha.carpeta} a la lista de proyectos`,
            onclick: async () => {
              try {
                const salida = await pedir(API.restaurar(ficha.carpeta), { method: 'POST' });
                const pid = salida.restaurado || (salida.proyecto || {}).id;
                toast(`«${(salida.proyecto || {}).nombre || pid}» devuelto a la lista`);
                if (pid) localStorage.setItem('estudio.pid', pid);
                await cargarProyectos();
                await pintar();
              } catch (e) { toast(partirError(e.message).titular, true); }
            },
          }, 'Devolver'))));
      }
      cuerpo.appendChild(tabla);

      botonBorrar.addEventListener('click', () => borrarMarcadas([...marcadas], lista, pintar));
      cuerpo.appendChild(h('div', { clase: 'fila', estilo: 'margin-top:12px' },
        h('button', {
          clase: 'mini fantasma',
          onclick: () => {
            const todas = marcadas.size !== lista.length;
            marcadas.clear();
            if (todas) lista.forEach(f => marcadas.add(f.carpeta));
            cuerpo.querySelectorAll('input[type=checkbox]').forEach(c => { c.checked = todas; });
            refrescarMandos();
          },
        }, 'Marcar / desmarcar todos'),
        botonBorrar,
        contador));
      refrescarMandos();

      cuerpo.appendChild(h('div', { clase: 'pista' },
        `Carpeta: ${oHueco(datos.raiz)}. Devolver es reversible; borrar definitivamente NO: `
        + 'se lleva el guion, las tomas de voz, las imágenes generadas y el render, o sea '
        + 'todo lo que se pagó por generar. El servidor dice cuántos ficheros y cuántos megas '
        + 'son antes de tocar nada.'));

      cuerpo.appendChild(tablaPresetsPapelera(presetsApartados, pintar));
    } catch (e) {
      vaciar(cuerpo).appendChild(cajaError(e.message));
    }
  };
  pintar();
}

/* Los presets apartados, en la misma papelera y con su etiqueta.
   Se listan aparte de los proyectos a proposito: se devuelven y se borran de
   uno en uno, y lo que se pierde al borrarlos no tiene nada que ver. */
function tablaPresetsPapelera(lista, alTerminar) {
  if (!lista.length) return null;
  const tabla = h('table', { clase: 'tabla' },
    h('tr', {}, h('th', {}, 'Qué es'), h('th', {}, 'Preset'), h('th', {}, 'Apartado'),
      h('th', {}, '')));
  for (const ficha of lista) {
    tabla.appendChild(h('tr', {},
      h('td', {}, h('span', { clase: 'tag-papelera preset' },
        `preset · ${NOMBRES_PRESET[ficha.tipo] || ficha.tipo}`)),
      h('th', {}, oHueco(ficha.nombre, ficha.id),
        h('div', { clase: 'meta' }, oHueco(ficha.resumen, ''))),
      h('td', { clase: 'meta' }, fechaCorta(ficha.apartado)),
      h('td', { clase: 'fila' },
        h('button', {
          clase: 'mini',
          onclick: async () => {
            try {
              const salida = await pedir(API.presetCanalRestaurar(ficha.id), { method: 'POST' });
              PRESETS_CANAL.datos = salida;
              toast(`«${ficha.nombre}» devuelto a la lista`);
              await alTerminar();
            } catch (e) { toast(partirError(e.message).titular, true); }
          },
        }, 'Devolver'),
        h('button', {
          clase: 'mini peligro',
          onclick: () => borrarPresetDeVerdad(ficha, alTerminar),
        }, 'Borrar'))));
  }
  return h('div', {},
    h('h3', { estilo: 'margin:18px 0 6px' }, 'Presets apartados'),
    tabla,
    h('div', { clase: 'pista' },
      'Un preset borrado no puede romper ningún vídeo: lo que los vídeos llevan dentro '
      + 'son sus valores copiados, no su nombre. Lo que se pierde es el preset en sí — '
      + 'sus fotogramas de estilo y su guía escrita.'));
}

/* Igual que con los proyectos: primero se pregunta al servidor QUE hay dentro y
   solo despues de ensenar esa cifra se pide confirmacion. */
async function borrarPresetDeVerdad(ficha, alTerminar) {
  let peso = {};
  try { peso = await pedir(API.presetCanalPapelera(ficha.id)); }
  catch (e) { toast(`no se ha podido mirar qué hay dentro: ${partirError(e.message).titular}`, true); return; }
  if (!window.confirm(
    `Borrar DEFINITIVAMENTE el preset «${ficha.nombre}».\n\n`
    + `Son ${peso.ficheros || 0} ficheros, ${peso.megas || 0} MB`
    + (ficha.tipo === 'estilo' ? ' (sus fotogramas de estilo).' : '.')
    + '\n\nESTO NO SE PUEDE DESHACER. Los vídeos que ya lo tengan aplicado no se '
    + 'ven afectados: llevan sus valores copiados.')) return;
  try {
    const salida = await pedir(`${API.presetCanalPapelera(ficha.id)}?confirmar=1`,
      { method: 'DELETE' });
    PRESETS_CANAL.datos = salida;
    toast(`preset «${ficha.nombre}» borrado`);
    await alTerminar();
  } catch (e) { toast(partirError(e.message).titular, true); }
}

/* Borrado definitivo: dos pasadas a proposito. Primero se pregunta al servidor
   QUE hay dentro (ficheros y megas) y solo despues de ensenar esa cifra se pide
   confirmacion y se borra con confirmar=true. Asi el aviso no es una frase
   generica, es el peso real de lo que se va a perder. */
async function borrarMarcadas(carpetas, lista, alTerminar) {
  if (!carpetas.length) return;
  const nombreDeCarpeta = c => {
    const ficha = lista.find(f => f.carpeta === c);
    return (ficha && (ficha.nombre || ficha.id)) || c;
  };
  let ficheros = 0, bytes = 0;
  try {
    const pesos = await Promise.all(carpetas.map(c => pedir(API.papeleraFicha(c))));
    ficheros = pesos.reduce((s, f) => s + (Number(f.ficheros) || 0), 0);
    bytes = pesos.reduce((s, f) => s + (Number(f.bytes) || 0), 0);
  } catch (e) {
    toast(`no se ha podido mirar qué hay dentro: ${partirError(e.message).titular}`, true);
    return;
  }
  const megas = (bytes / (1024 * 1024)).toFixed(1);
  if (!window.confirm(
    `Borrar DEFINITIVAMENTE ${carpetas.length} proyecto(s):\n\n`
    + carpetas.map(c => `  · ${nombreDeCarpeta(c)}`).join('\n')
    + `\n\nSon ${ficheros} ficheros, ${megas} MB: el guion, las tomas de voz, las imágenes `
    + 'generadas y el render.\n\nESTO NO SE PUEDE DESHACER. No hay copia en ningún sitio.')) return;

  const fallos = [];
  for (const carpeta of carpetas) {
    try {
      await pedir(`${API.papeleraFicha(carpeta)}?confirmar=true`, { method: 'DELETE' });
    } catch (e) {
      fallos.push(`${nombreDeCarpeta(carpeta)}: ${partirError(e.message).titular}`);
    }
  }
  if (fallos.length) toast(`no se han podido borrar ${fallos.length}: ${fallos[0]}`, true);
  else toast(`${carpetas.length} proyecto(s) borrados (${megas} MB liberados)`);
  await alTerminar();
}

/* La cabecera vive en index.html; aqui solo se le atan los mandos. Todo lo que
   antes eran botones sueltos (nuevo, apartar, papelera, rendimiento) vive ahora
   dentro del menu del proyecto: en la barra no cabian en una linea, y 'apartar'
   como boton suelto actuaba sobre el proyecto abierto en vez de sobre el que
   quisieras apartar. */
function ponerMandosDeCabecera() {
  $('#btn-proyecto').addEventListener('click', ev => {
    ev.stopPropagation();
    conmutarMenuProyectos();
  });
  document.addEventListener('click', ev => {
    const menu = $('#menu-proyectos');
    if (menu.classList.contains('plegado')) return;
    if (menu.contains(ev.target) || $('#btn-proyecto').contains(ev.target)) return;
    cerrarMenuProyectos();
  });
  // Lo mismo para el de presets. No puede cerrarse con el de proyectos porque
  // vive dentro del panel y se repinta con el: el estado de abierto esta en
  // APP.vista, no en una clase del DOM que el repintado se llevaria por delante.
  document.addEventListener('click', ev => {
    const vista = APP.vista && APP.vista.presets;
    if (!vista || !vista.abierto) return;
    if (ev.target.closest && ev.target.closest('.selector-preset')) return;
    vista.abierto = null;
    pintarPanel();
  });
}

/* ------------------------------------------------------------------ bitacora */

/* En pantalla ancha el lateral es una columna; en estrecha, un cajon con velo.
   El velo se maneja aqui y no en cada sitio para que no puedan descuadrarse. */
async function cargarBitacora() {
  const cajon = $('#bitacora');
  if (!cajon) return;          // no hay cajon de bitacora en esta pantalla
  const filtro = ($('#filtro-bitacora') || {}).value || '';
  const caja = vaciar(cajon);
  caja.appendChild(h('div', { clase: 'cargando' }, 'cargando…'));
  try {
    const datos = await pedir(API.bitacora(APP.pid, filtro && filtro !== 'todos' ? filtro : ''));
    const eventos = datos.eventos || datos || [];
    vaciar(caja);
    if (!eventos.length) { caja.appendChild(h('div', { clase: 'vacio' }, 'sin eventos')); return; }
    for (const ev of eventos.slice().reverse()) {
      caja.appendChild(h('div', { clase: 'evento' },
        h('div', { clase: 'cab' },
          h('span', { clase: 'fecha' }, fechaCorta(ev.fecha).slice(5)),
          h('span', { clase: 'nombre' }, ev.evento),
          h('span', { clase: 'paso' }, ev.paso || ''),
          ev.unidad ? h('span', { clase: 'pastilla' }, ev.unidad) : null),
        ev.datos && Object.keys(ev.datos).length
          ? h('div', { clase: 'datos' }, resumirDatos(ev.datos)) : null));
    }
  } catch (e) {
    vaciar(caja);
    caja.appendChild(h('div', { clase: 'caja-error' }, e.message));
  }
}

function resumirDatos(datos) {
  return Object.entries(datos).map(([clave, valor]) => {
    let texto = typeof valor === 'object' ? JSON.stringify(valor) : String(valor);
    if (texto.length > 90) texto = `${texto.slice(0, 90)}…`;
    return `${clave}: ${texto}`;
  }).join(' · ');
}

function llenarFiltroBitacora() {
  const sel = $('#filtro-bitacora');
  if (!sel) return;            // no hay cajon de bitacora en esta pantalla
  const previo = sel.value;
  vaciar(sel);
  sel.appendChild(h('option', { value: 'todos' }, 'todos los pasos'));
  for (const paso of APP.pasos) sel.appendChild(h('option', { value: paso.id }, paso.nombre));
  sel.value = previo || 'todos';
}

/* ------------------------------------------------------------------ arranque */

async function nuevoProyecto() {
  const nombre = window.prompt('Nombre del vídeo nuevo:');
  if (!nombre) return;
  try {
    const datos = await pedir(API.proyectos(), { method: 'POST', cuerpo: { nombre } });
    const proyecto = datos.proyecto || datos;
    await cargarProyectos();
    if (proyecto && proyecto.id) await abrirProyecto(proyecto.id);
    toast(`proyecto «${nombre}» creado`);
  } catch (e) { toast(`no se ha podido crear: ${e.message}`, true); }
}

function arrancar() {
  ponerMandosDeCabecera();
  /* LA CLASE DEL <body>, ANTES QUE NADA. Hay cosas que se esconden con CSS y
     no con JS --el medidor de coste del vídeo y el botón de proyecto no
     significan nada mientras no haya un vídeo abierto--, y si esto llegara
     después de pintar se verían un instante y desaparecerían. */
  document.body.classList.add('modo-light');
  // La pestana de la URL manda al arrancar, y el boton de atras la devuelve.
  const enLaUrl = PESTANAS_VIEJAS[location.hash.slice(1)] || location.hash.slice(1);
  if (PESTANAS.some(p => p.id === enLaUrl)) APP.activa = enLaUrl;
  window.addEventListener('popstate', () => {
    const pedida = location.hash.slice(1) || PESTANAS[0].id;
    if (PESTANAS.some(p => p.id === pedida) && pedida !== APP.activa) irA(pedida, true);
  });
  $('#btn-config').addEventListener('click', () => conmutarConfig());
  $('#btn-salir').addEventListener('click', () => salirDeStudio());
  cargarCuenta();
  montarAsistente();
  $('#btn-cerrar-config').addEventListener('click', () => conmutarConfig(false));
  // El catalogo de recetas se pide una vez al arrancar: de el salen la barra de
  // cada pestana y el ajuste RECORDADO de cada fase del CLI, asi que sin el los
  // desplegables saldrian con el defecto de fabrica y no con lo que hay puesto.
  cargarCatalogoRecetas();
  $('#coste').addEventListener('click', conmutarCoste);
  document.addEventListener('click', ev => {
    if (!COSTE.abierto) return;
    if ($('#coste').contains(ev.target) || $('#coste-detalle').contains(ev.target)) return;
    conmutarCoste();
  });
  /* Con el dedo, acertar una casilla de 22px es una loteria. El texto de al
     lado hace de mando: en '.campo.plano' la etiqueta va suelta (ni envuelve al
     input ni lleva 'for'), asi que se conecta aqui una vez por delegacion en
     vez de tocar los diez sitios donde hay una casilla. */
  document.addEventListener('click', ev => {
    const etiqueta = ev.target.closest && ev.target.closest('.campo.plano > label');
    if (!etiqueta) return;
    const casilla = etiqueta.parentNode.querySelector('input[type=checkbox]');
    if (!casilla || casilla.disabled) return;
    casilla.checked = !casilla.checked;
    casilla.dispatchEvent(new Event('change', { bubbles: true }));
  });
  // Un solo vigilante de la seleccion para toda la vida de la pagina: el panel
  // se repinta constantemente y engancharlo en cada pintado dejaria cientos de
  // oyentes vivos sobre nodos que ya no existen.
  // Las teclas del reproductor van ANTES que el resto de atajos, pero solo
  // actuan si hay un reproductor a la vista y el foco no esta en un campo.
  document.addEventListener('keydown', atajosDeReproductor);
  document.addEventListener('keydown', ev => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === 's') {
      // el autoguardado ya corre solo; Ctrl+S lo adelanta para quien lo tenga
      // en los dedos, volcando TODO lo sucio de golpe
      ev.preventDefault();
      guardarSucios().then(() => toast('guardado'));
    }
    if (ev.key === 'Escape') {
      ['lupa', 'capturador', 'rendimiento', 'papelera', 'conservacion',
       'cuadro-texto']
        .map(id => document.getElementById(id))
        .forEach(nodo => { if (nodo) nodo.remove(); });
      cerrarMenuProyectos();
      if (INICIO.abierta) cerrarInicio(true);
      if (ASISTENTE.abierto) conmutarAsistente(false);
      if (!$('#config').classList.contains('plegado')) conmutarConfig(false);
      if (COSTE.abierto) conmutarCoste();
    }
  });
  // Ultimo intento al cerrar o recargar: keepalive deja el PUT en vuelo aunque
  // la pagina muera. Con el autoguardado de 1,2 s casi nunca queda nada, pero
  // «casi nunca» no es una garantia y esto lo es (hasta donde da el navegador).
  window.addEventListener('pagehide', () => {
    if (!APP.pid) return;
    for (const paso of Object.keys(APP.sucio)) {
      if (!APP.sucio[paso]) continue;
      fetch(API.params(APP.pid, paso), {
        method: 'PUT', keepalive: true,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ params: borradorDe(paso) }),
      }).catch(() => {});
    }
  });

  // El catalogo de modelos y esfuerzos se pide ANTES que los proyectos: es lo
  // que decide si un paso ofrece el selector del CLI, y sin el la interfaz
  // volveria a inventarse una lista. Si falla, el Estudio sigue funcionando y
  // cada selector lo dice en su sitio.
  cargarAjustesCLI()
    .catch(e => {
      console.error(e);
      toast(`no se ha podido leer el catálogo del CLI: ${e.message}`, true);
    })
    .then(cargarProyectos)
    // la guia de inicio se decide con la pantalla ya pintada debajo
    .then(decidirOnboarding)
    .catch(e => {
      vaciar($('#panel')).appendChild(h('div', { clase: 'contenido' },
        h('div', { clase: 'caja-error' },
          `No se ha podido hablar con el servidor: ${e.message}\n\n`
          + 'Arranca el servidor y recarga esta página.')));
    });
}

/* ==================================================================== MODO
 *
 * DOS MODOS, Y EL SELECTOR VIVE EN LA BARRA porque no es de este vídeo: es de
 * cómo se trabaja, igual que las claves o la bitácora.
 *
 *   editor   la pantalla de siempre, entera y sin tocar: cinco pestañas, cada
 *            decisión con su tarjeta, su versión y su coste delante.
 *   light    tu estilo en cuatro campos. No hay pestañas, no hay pasos y no hay
 *            proyecto: hay ESTILOS, y se crean de una tirada.
 *
 * «Estilo» y no «canal», que es como se llamó al principio: lo que se guarda
 * es la estética, la forma de contar, la voz y el idioma —y eso es un estilo—.
 * Una misma persona puede tener tres para el mismo canal. El TIPO de preset
 * del servidor se sigue llamando 'canal' porque es la clave con la que están
 * guardados en disco, y renombrarla dejaría huérfano lo que ya hay: lo que
 * cambia es lo que se lee, no lo que se almacena.
 *
 * El modo se guarda en localStorage y no en el servidor a propósito: es de esta
 * pantalla, no del canal. Desde el móvil se puede estar en light mientras el
 * ordenador está en editor mirando un vídeo a medias.
 *
 * Toda la conmutación pasa por UN sitio (`pintarPanel` delega en `pintarLight`)
 * en vez de por un `if` en cada función: con dos caminos de pintado repartidos
 * por el fichero, uno de los dos se queda viejo. */



/* ============================================================= MODO LIGHT
 *
 * Una pantalla, cuatro vistas, y ninguna de ellas necesita un proyecto abierto:
 *
 *   galeria     las tarjetas de tus estilos, como una parrilla de vídeos. Sin
 *               ninguno, una sola tarjeta con un «+».
 *   crear       los cuatro campos. Es el único formulario de todo el modo.
 *   generando   la barra, con el paso por el que va y su tiempo real.
 *   preset      un estilo abierto: su miniatura, su idioma y las TRES cosas que
 *               se pueden pedir de otra manera.
 *
 * Por qué la ficha de un preset no se «desglosa»: lo que se enseña son cuatro
 * elementos —estilo gráfico, tono, voz e idioma— y ni uno más. Todo lo que hay
 * debajo (la guía escrita, los fotogramas, la paleta, el set de dibujo, la
 * velocidad de la voz) existe y se puede tocar, pero en el modo editor. Aquí
 * corregir es escribir una frase. */

const CLAVE_LIGHT = 'preset_light';
// La escucha de una voz es OTRO trabajo: comparte seguimiento con el de
// generar y una escucha de doce segundos borraria la barra de una
// generacion de nueve minutos.
const CLAVE_VOZ_LIGHT = 'voz_light';

APP.light = {
  vista: 'galeria',
  datos: null,          // lo que devuelve /api/presets-light
  cargando: false,
  error: '',
  abierto: null,        // id del preset abierto en la vista 'preset'
  plan: null,           // el plan de la generacion en marcha
  taller: null,         // el taller de la tanda en marcha, para poder retomarla
  encargo: null,        // el formulario a medio rellenar
  feedback: {},         // parte -> lo escrito en su caja
  escuchas: {},         // preset -> url de su ultima escucha de voz
};

function encargoLight() {
  if (!APP.light.encargo) {
    APP.light.encargo = {
      nombre: '', idioma: 'es',
      // EL ESTILO GRAFICO SON IMAGENES. Se adjuntan las que ya tengan el
      // aspecto que se quiere --{nombre, origen, bytes} tal y como las
      // devuelve el buzon del servidor-- y lo escrito las acompana: es el
      // «esto pero mas frio» que una imagen no puede decir sola.
      estilo_imagenes: [], estilo_prompt: '',
      // EL TONO SE ESCRIBE. Un parrafo sobre como se cuenta una historia basta
      // para escribir las instrucciones: no hay nada que copiar, hay algo que
      // decidir.
      tono_prompt: '',
      voz_prompt: '',
      // la voz elegida a mano (normalmente una clonada); vacía, la elige el
      // agente por la descripción
      voz_id: '',
      ritmo: '',            // lo pone el servidor al cargar la galería
    };
  }
  return APP.light.encargo;
}

/* Lo que viaja de un personaje: sus textos, sus casillas y los NOMBRES de sus
   fotos en el buzon (o las rutas que ya tenia, si es uno guardado). */
function personajeParaServidor(p) {
  return {
    id: p.id || undefined,
    nombre: String(p.nombre || '').trim(),
    descripcion: String(p.descripcion || '').trim(),
    comportamiento: String(p.comportamiento || '').trim(),
    imagenes: (p.imagenes || []).map(x => x.nombre),
    referencias: p.referencias || [],
    hoja: p.hoja || '',
  };
}

/* Lo que se manda al servidor: los cuatro campos, sin los mandos de la pantalla.
   El servidor valida otra vez (`presets_light.validar_encargo`) y es el que
   manda: esta función solo elige QUÉ viaja. */
function encargoParaServidor() {
  const e = encargoLight();
  return {
    nombre: e.nombre,
    idioma: e.idioma,
    estilo_imagenes: (e.estilo_imagenes || []).map(x => x.nombre),
    estilo_prompt: e.estilo_prompt,
    tono_prompt: e.tono_prompt,
    voz_prompt: e.voz_prompt,
    voz_id: e.voz_id || '',
    ritmo: e.ritmo || ritmoPorDefecto(),
  };
}

async function cargarGaleriaLight(forzar) {
  if (APP.light.datos && !forzar) { pintarLight(); return; }
  APP.light.cargando = true;
  APP.light.error = '';
  // El catálogo de recetas del canal, que es donde vive la tarea de las
  cargarCatalogoRecetas().then(() => pintarLight());
  pintarLight();
  try {
    APP.light.datos = await pedir(API.presetsLight());
    // Y los vídeos hechos con este modo, que viven en la lista de proyectos de
    // siempre: son proyectos normales, así que no hay un almacén aparte que
    // pudiera desincronizarse con el de verdad.
    try {
      const proyectos = await pedir(API.proyectos());
      APP.light.datos.videos = (proyectos.proyectos || [])
        .filter(p => p.video_light)
        .sort((a, b) => String(b.actualizado || '').localeCompare(String(a.actualizado || '')));
    } catch (e) { APP.light.datos.videos = []; }
    // el ritmo de fábrica lo dice el servidor, no esta pantalla
    if (APP.light.encargo && !APP.light.encargo.ritmo) {
      APP.light.encargo.ritmo = ritmoPorDefecto();
    }
  } catch (e) {
    APP.light.error = e.message;
  }
  APP.light.cargando = false;
  pintarLight();
}

function presetsLight() { return (APP.light.datos || {}).presets || []; }

function fichaLight(id) { return presetsLight().find(p => p.id === id) || null; }

/* Los idiomas los sirve el servidor (`presets_light.IDIOMAS`), que es quien
   sabe cuáles entiende la voz y el guion. El respaldo son LOS MISMOS SEIS y no
   solo el castellano: cuando la lista no llegaba —servidor viejo, red caída— el
   desplegable se quedaba con una sola opción y parecía que el Estudio solo
   hablaba español, que es una avería disfrazada de decisión. */
const IDIOMAS_LIGHT = [
  { valor: 'es', nombre: 'Español' }, { valor: 'en', nombre: 'Inglés' },
  { valor: 'pt', nombre: 'Portugués' }, { valor: 'fr', nombre: 'Francés' },
  { valor: 'it', nombre: 'Italiano' }, { valor: 'de', nombre: 'Alemán' },
];

function idiomasLight() {
  const servidos = (APP.light.datos || {}).idiomas;
  return (servidos && servidos.length) ? servidos : IDIOMAS_LIGHT;
}

/* EL RITMO. La tabla la sirve el servidor (`presets_light.RITMOS`), con el plano
   medio y el coste por minuto ya calculados: son las dos únicas cifras que este
   deslizador enseña, y las dos salen de medidas reales (la media de plano, del
   plan de un vídeo real; el coste, del registro de gasto). Calcularlas aquí sería
   inventarse una segunda verdad.

   Lo que el deslizador NO enseña, a propósito: el mínimo, el máximo y el umbral
   de rótulos. Son tres campos del modo editor y ahí siguen, editables uno a uno.
   Aquí lo que se decide es el ritmo; los tres números son su consecuencia. */
function ritmosLight() { return (APP.light.datos || {}).ritmos || []; }

function ritmoPorDefecto() {
  return (APP.light.datos || {}).ritmo_por_defecto || 'medio';
}

/* «Rápido · plano medio ~2,0 s · ~0,99 $/min» y nada más. */
function resumenRitmo(ficha) {
  if (!ficha) return '';
  // toFixed(1) y no el número pelado: «~2 s» y «~2,8 s» uno debajo del otro
  // saltan de ancho al mover el deslizador, y lo que se lee es una cifra que
  // cambia de forma además de de valor.
  return `${ficha.nombre} · plano medio ~${ficha.media_s.toFixed(1).replace('.', ',')} s`
    + ` · ~${ficha.usd_por_minuto.toFixed(2).replace('.', ',')} $/min`;
}

/* El deslizador. Cinco posiciones y una sola línea debajo: sin números de
   mínimo, máximo ni umbral, que es lo que se pidió. Repinta SOLO su línea —no el
   formulario— porque arrastrar y que se repinte el panel entero suelta el
   deslizador a media pasada. */
function sliderRitmo(valor, alCambiar) {
  const lista = ritmosLight();
  if (!lista.length) return h('div', { clase: 'pista' }, 'cargando los ritmos…');
  const indice = Math.max(0, lista.findIndex(r => r.id === (valor || ritmoPorDefecto())));
  const linea = h('div', { clase: 'ritmo-linea' }, resumenRitmo(lista[indice]));
  const barra = h('input', {
    type: 'range', min: 0, max: lista.length - 1, step: 1, value: indice,
    clase: 'ritmo',
  });
  const mover = () => {
    const ficha = lista[Number(barra.value)] || lista[0];
    vaciar(linea).append(resumenRitmo(ficha));
    alCambiar(ficha.id);
  };
  barra.addEventListener('input', mover);
  return h('div', { clase: 'campo' }, barra,
    h('div', { clase: 'topes' }, ...lista.map((r, i) => h('span', {
      clase: i === indice ? 'puesto' : '',
    }, r.nombre))),
    linea);
}

/* ==================================================== QUIEN ESTA DENTRO
 *
 * Studio no sabe de cuentas: el login vive DELANTE, en su propio servicio, y
 * nginx enruta a el /api/me, /api/csrf y /api/logout. Aqui no se replica nada
 * de eso -- se le pregunta.
 *
 * Y SI NO CONTESTA, NO PASA NADA. En local se entra sin cuenta y esas rutas no
 * existen: la pastilla se queda oculta y la barra se ve como siempre. Por eso
 * el fallo no se ensena en ningun sitio; que no haya login no es un error.
 */
async function cargarCuenta() {
  try {
    const r = await fetch('/api/me', { credentials: 'same-origin' });
    if (!r.ok) return;
    const d = await r.json();
    const nombre = ((d || {}).user || {}).username;
    if (!nombre) return;
    $('#cuenta-nombre').textContent = nombre;
    $('#cuenta').classList.remove('oculto');
  } catch (e) { /* sin login delante: nada que ensenar */ }
}


async function salirDeStudio() {
  /* Salir SI se pregunta, y es la excepcion de «editar es decidir»: no es una
     edicion, es irse. Un roce en el movil que te tira la sesion en mitad de un
     repaso obliga a volver a entrar para nada. */
  if (!window.confirm('¿Cerrar la sesion? Habra que volver a entrar con la '
                      + 'contrasena.')) return;
  const boton = $('#btn-salir');
  if (boton) boton.disabled = true;
  try {
    const c = await fetch('/api/csrf', { credentials: 'same-origin' });
    const token = ((await c.json()) || {}).csrfToken;
    const r = await fetch('/api/logout', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
      body: '{}',
    });
    await r.json().catch(() => ({}));
    /* A SU login, no al de la raiz. El servicio del login contesta `/login` a
       secas porque no sabe por cual de las dos versiones se le esta llamando;
       quien si lo sabe es esta pagina, y lo tiene en BASE. */
    window.location.href = `${BASE}/login`;
  } catch (e) {
    if (boton) boton.disabled = false;
    toast(`no se ha podido cerrar la sesion: ${e.message}`, true);
  }
}

/* ============================================ LA BARRA DE ABAJO (modo light)
 *
 * LOS CINCO SITIOS, SIEMPRE EN EL MISMO SITIO.
 *
 * Moverse por el modo light era ir encontrando botones: «‹ Volver» arriba a la
 * izquierda, «El vídeo ›» en una cabecera, «‹ Las diapositivas» en otra. Cada
 * uno en un borde distinto y ninguno diciendo DÓNDE ESTABAS de los pasos. Con
 * la barra, el sitio de navegar es uno y enseña el camino entero:
 * estilos → encargo → guion → diapositivas → vídeo, que es el orden real de
 * las cosas.
 *
 * EL ENCARGO ES UNA PARADA PROPIA (10-09-2026). Antes lo que se le pidió al
 * redactor —el material, la duración, el formato, las indicaciones, las
 * llamadas a la acción— sólo se veía en el formulario de crear el vídeo, y en
 * cuanto había guion ese formulario no se volvía a alcanzar: para cambiar una
 * indicación había que abrir el modo editor. Ahora se vuelve a él igual que se
 * vuelve a un estilo: se lee lo GUARDADO, se corrige ahí mismo con
 * autoguardado, y el pie ofrece regenerar el guion con lo que ha cambiado.
 *
 * VA ABAJO porque esto se repasa desde el móvil, y arriba no llega el pulgar.
 *
 * LO QUE NO SE PUEDE PISAR SE APAGA, no se esconde: un paso que desaparece no
 * dice que aún no toca, dice que no existe. Apagado con su motivo en el title
 * enseña el camino completo desde el primer día.
 */
const ICONOS_NAV = {
  estilos: 'M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h6v6h-6z',
  encargo: 'M9 3h6v3H9z M7 5h10v16H7z M10 11h5 M10 15h4',
  guion: 'M6 3h12v18H6z M9 8h6 M9 12h6 M9 16h4',
  diapositivas: 'M3 6h18v12H3z M8 6v12 M16 6v12',
  video: 'M3 5h18v14H3z M10 9l5 3-5 3z',
};


/* `h` crea con createElement y un <svg> así no dibuja nada: necesita su espacio
   de nombres. Es lo unico que hace esta funcion. */
function iconoNav(d) {
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.6');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS(NS, 'path');
  p.setAttribute('d', d);
  svg.appendChild(p);
  return svg;
}


/* Lo que va anclado abajo ADEMAS de la barra de pasos, si la pantalla de turno
   lo pone. Se vacia en cada pintado: una barra que sobrevive a un cambio de
   pantalla se queda ahi conduciendo escenas de una vista que ya no se ve. */
const BARRA_INFERIOR = { nodo: null };


function navLight() {
  const v = APP.light.video;
  const dentro = APP.light.vista === 'elegido' && !!v.pid;
  const sub = dentro ? v.vista : '';
  const hayGuion = dentro && !!v.guion;
  const hayPlanos = dentro && !!versionDe(v.fichas.assets || {});
  const hayVideo = dentro && (!!v.audio || hayMp4Light());

  const paradas = [
    { id: 'estilos', texto: 'Estilos', puede: true, activa: !dentro,
      porque: 'tus estilos y tus vídeos',
      ir: () => { pararPrevia(); recordarVideoLight(''); irALight('galeria'); } },
    /* EL ENCARGO: lo que se le pidió al redactor, tal cual está guardado en el
       vídeo abierto, y editable. Sin vídeo abierto no hay nada que revisar (el
       formulario de crear uno es otra pantalla, `vistaElegidoLight`). Cuenta
       como «aquí» también en ese formulario: es el encargo de un vídeo que
       todavía no existe, y la barra tiene que decir en qué parada estás. */
    { id: 'encargo', texto: 'Encargo', puede: dentro,
      activa: dentro && (sub === 'encargo_video' || sub === 'encargo'),
      porque: dentro ? 'lo que se pidió para el guion: se lee y se cambia aquí'
        : 'abre un vídeo primero',
      ir: () => { pararPrevia(); v.vista = 'encargo_video'; pintarLight(); } },
    /* Antes, sin guion, este botón caía en el formulario de crear un vídeo
       NUEVO —con uno ya abierto—. Ahora va siempre al guion: si no lo hay
       todavía, esa pantalla lo dice y manda al encargo, que es donde se genera. */
    { id: 'guion', texto: 'Guion', puede: dentro,
      activa: dentro && sub === 'guion',
      porque: dentro ? (hayGuion ? 'el texto y la voz' : 'todavía no hay guion')
        : 'abre un vídeo primero',
      ir: () => { pararPrevia(); v.vista = 'guion'; pintarLight(); } },
    { id: 'diapositivas', texto: 'Imágenes', puede: hayPlanos,
      activa: sub === 'previa',
      porque: hayPlanos ? 'la imagen de cada plano, sola'
        : 'todavía no hay imágenes que mirar',
      ir: () => { v.vista = 'previa'; pintarLight(); } },
    { id: 'video', texto: 'Vídeo', puede: hayVideo, activa: sub === 'video',
      porque: hayVideo ? 'el montaje y el repaso' : 'todavía no hay nada montado',
      ir: () => { pararPrevia(); v.vista = 'video'; pintarLight(); } },
  ];

  const barra = h('nav', { clase: 'nav-light', 'aria-label': 'Pasos del vídeo' });
  paradas.forEach(parada => {
    const boton = h('button', {
      clase: 'parada' + (parada.activa ? ' activa' : ''),
      disabled: !parada.puede,
      title: parada.porque,
      'aria-current': parada.activa ? 'page' : null,
      onclick: () => { if (!parada.activa) parada.ir(); },
    });
    boton.appendChild(iconoNav(ICONOS_NAV[parada.id]));
    boton.appendChild(h('span', { clase: 'etiqueta' }, parada.texto));
    barra.appendChild(boton);
  });
  return barra;
}


/* ---------------------------------------------------- el foco sobrevive al pintado
 *
 * `pintarLight` vacía el panel y lo vuelve a construir, así que cada campo de
 * texto es un nodo NUEVO y el foco se pierde. Y la pantalla se repinta sola:
 * cada 1,5 s por el refresco del coste, y en cada tic de una tanda en marcha.
 *
 * O sea que escribiendo el feedback de un plano se te iba el cursor solo, y las
 * teclas siguientes ya no iban al campo sino al documento -- donde espacio
 * reproduce la escena y las flechas pasan de plano --. Los atajos SÍ miraban si
 * estabas escribiendo; lo que fallaba es que, en ese instante, ya no lo estabas.
 *
 * Se identifica el campo con `data-foco`, que es un nombre estable (el plano o
 * la nota), no una posición: después del pintado el nodo es otro, pero el sitio
 * al que pertenece es el mismo.
 */
function recordarFoco() {
  const nodo = document.activeElement;
  if (!nodo || !nodo.dataset || !nodo.dataset.foco) return null;
  if (!['INPUT', 'TEXTAREA'].includes(nodo.tagName)) return null;
  return {
    foco: nodo.dataset.foco,
    ini: nodo.selectionStart,
    fin: nodo.selectionEnd,
  };
}


function devolverFoco(guardado) {
  if (!guardado) return;
  const nodo = document.querySelector(`[data-foco="${guardado.foco}"]`);
  if (!nodo) return;                    // ese campo ya no está: no se fuerza
  try {
    nodo.focus({ preventScroll: true });
    if (guardado.ini != null) nodo.setSelectionRange(guardado.ini, guardado.fin);
  } catch (e) { /* un campo que no admite selección no es un error */ }
}

function pintarLight() {
  const foco = recordarFoco();
  try {
    pintarLightAhora();
  } finally {
    devolverFoco(foco);
  }
}


/* --------------------------------------------- lo que cambia solo, y solo eso
 *
 * `pintarLight` VACIA EL PANEL Y LO VUELVE A CONSTRUIR, y mientras una tanda
 * corre eso pasaba dos veces por segundo: un tic por cada imagen generada mas
 * el refresco del coste cada 1,5 s. En cada pasada TODO es un nodo nuevo -- la
 * imagen grande del plano se vuelve a cargar, los botones se rehacen debajo del
 * puntero y el cuadro de feedback se destruye mientras escribes --, asi que la
 * pantalla parpadeaba, se comia clics y a ratos no dejaba editar.
 *
 * Entre tic y tic lo unico que cambia de verdad es el PROGRESO y el COSTE. Se
 * pintan dentro de una caja que se recuerda --`enVivo`-- y refrescar es volver
 * a pintar SOLO esas cajas. El panel no se toca.
 *
 * La caja va con `display: contents`, o sea que no existe para la maquetacion:
 * lo de dentro sigue siendo hijo directo de la fila donde estaba.
 *
 * El registro se vacia en cada pintado completo: sus cajas ya no estan en el
 * documento y volver a pintarlas seria escribir en un panel que se tiro. */
const VIVOS = [];

function enVivo(pinta) {
  const caja = h('div', { clase: 'vivo' });
  VIVOS.push({ caja, pinta });
  const dentro = pinta();
  if (dentro) caja.appendChild(dentro);
  return caja;
}

/* Vuelve a pintar lo vivo y nada mas. Sin nada marcado --el modo editor, o una
   pantalla que todavia no se ha pintado-- no hace nada: quien quiera el panel
   entero llama a `pintarLight`. */
function refrescarVivosLight() {
  if (!VIVOS.length) return;
  const foco = recordarFoco();
  try {
    VIVOS.forEach(({ caja, pinta }) => {
      if (!caja.isConnected) return;
      /* NO SE LE QUITA EL SITIO A LO QUE SE ESTA USANDO. Si el foco esta
         dentro de la caja, se deja como esta hasta el siguiente pintado
         completo: refrescar por debajo del cursor es el fallo que esto
         viene a arreglar, no uno que pueda permitirse repetir. */
      if (caja.contains(document.activeElement)) return;
      const dentro = pinta();
      vaciar(caja);
      if (dentro) caja.appendChild(dentro);
    });
  } finally {
    devolverFoco(foco);
  }
}


function pintarLightAhora() {
  // lo vivo de la pantalla anterior se va con ella: sus cajas ya no estan en
  // el documento (ver `refrescarVivosLight`)
  VIVOS.length = 0;
  /* LA BARRA DE ABAJO ES DE LA PANTALLA QUE SE PINTA, asi que se olvida al
     empezar. Sin esto la barra de una pantalla sobrevivia al cambio: los
     mandos de una diapositiva se quedaban conduciendo escenas desde el
     guion, donde no hay ninguna que conducir. */
  BARRA_INFERIOR.nodo = null;
  // Se pide la galería sola la primera vez. Este pintado lo dispara cualquier
  // cosa (arrancar, abrir un proyecto, cambiar de modo), así que engancharlo a
  // uno solo de esos caminos dejaba la pantalla en «cargando…» para siempre
  // cuando entraba por otro.
  if (!APP.light.datos && !APP.light.cargando && !APP.light.error) {
    cargarGaleriaLight(true);
    return;
  }
  const contenedor = vaciar($('#panel'));
  const contenido = h('div', { clase: 'contenido light' });
  contenedor.appendChild(contenido);
  if (APP.light.cargando && !APP.light.datos) {
    contenido.appendChild(h('div', { clase: 'cargando' }, 'cargando tus estilos…'));
    return;
  }
  // UN FALLO NO SE PINTA COMO UN CATALOGO VACIO. Sin este `return`, no poder
  // leer la lista enseñaba el error arriba y debajo «todavía ninguno» con el
  // «+» de crear el primero, que es exactamente lo contrario de lo que pasa:
  // los que hay no se sabe cuáles son. Y decía «Not Found» a secas, que es lo
  // que contesta el servidor viejo -- el que sirve esta pantalla desde el disco
  // pero todavía no tiene el endpoint --, así que el aviso lo dice.
  if (APP.light.error) {
    contenido.appendChild(cajaError(
      `No se ha podido leer la lista de estilos: ${APP.light.error}`
      + (/not found/i.test(APP.light.error)
        ? '\n\nEsta pantalla es nueva y el servidor todavía no la conoce: '
          + 'reinícialo (start.ps1 estudio) y vuelve a cargar.'
        : '')));
    contenido.appendChild(h('div', { clase: 'fila' },
      h('button', {
        clase: 'primario',
        onclick: () => { APP.light.error = ''; cargarGaleriaLight(true); },
      }, 'Reintentar')));
    return;
  }
  try {
    if (APP.light.vista === 'crear') contenido.appendChild(vistaCrearLight());
    else if (APP.light.vista === 'generando') contenido.appendChild(vistaGenerandoLight());
    else if (APP.light.vista === 'preset') contenido.appendChild(vistaPresetLight());
    else if (APP.light.vista === 'elegido') {
      /* TRES VISTAS DENTRO DE «elegido», y la elige LO QUE HAY: el encargo
         mientras no haya vídeo, el guion en cuanto lo hay, y el vídeo cuando se
         está montando o ya está. Un menú de tres pestañas aquí sería pedirle a
         quien mira que elija en cuál de los tres momentos está. */
      const sub = APP.light.video.vista;
      if (APP.light.video.cargando) {
        contenido.appendChild(h('div', { clase: 'cargando' }, 'abriendo el vídeo…'));
      } else if (APP.light.video.error) {
        contenido.appendChild(cajaError(APP.light.video.error));
      } else if (sub === 'video') contenido.appendChild(vistaVideoLight());
      else if (sub === 'previa') contenido.appendChild(vistaPreviaLight());
      else if (sub === 'guion') contenido.appendChild(vistaGuionLight());
      else if (sub === 'encargo_video') contenido.appendChild(vistaEncargoVideoLight());
      else contenido.appendChild(vistaElegidoLight());
    }
    else contenido.appendChild(vistaGaleriaLight());
  } catch (e) {
    contenido.appendChild(cajaError(`fallo pintando el modo light: ${e.message}`));
    console.error(e);
  }
  /* FUERA DE `contenido`, pegadas al panel: dentro se irían con el scroll del
     documento y dejarían de estar donde se las busca. Y fuera pueden ir de
     borde a borde, que dentro no: la columna tiene ancho maximo. */
  if (BARRA_INFERIOR.nodo) contenedor.appendChild(BARRA_INFERIOR.nodo);
  contenedor.appendChild(navLight());
}

function irALight(vista, extra) {
  APP.light.vista = vista;
  Object.assign(APP.light, extra || {});
  $('#panel').scrollTop = 0;
  pintarLight();
}

/* ------------------------------------------------------------- la galería */

function vistaGaleriaLight() {
  const caja = h('div', {});
  const fichas = presetsLight();
  caja.appendChild(h('div', { clase: 'light-cab' },
    h('h2', {}, 'Tus estilos'),
    h('span', { clase: 'meta' }, fichas.length
      ? `${fichas.length} estilo${fichas.length === 1 ? '' : 's'}`
      : 'una estética, un tono, una voz y un idioma')));

  const rejilla = h('div', { clase: 'galeria-estilos' });
  fichas.forEach(ficha => rejilla.appendChild(tarjetaEstiloLight(ficha)));
  rejilla.appendChild(tarjetaNuevoEstilo(fichas.length));
  caja.appendChild(rejilla);

  /* TUS VÍDEOS, debajo de los estilos. Aquí es donde se aterriza al volver —de
     una recarga, del móvil, de otro día— y sin esta lista un vídeo a medio
     generar no tenía desde dónde retomarse: seguía corriendo en el servidor y
     no había ningún camino hasta él. */
  const videos = videosLight();
  if (videos.length) {
    caja.appendChild(h('div', { clase: 'light-cab' },
      h('h2', {}, 'Tus vídeos'),
      h('span', { clase: 'meta' }, `${videos.length} con este modo`)));
    const lista = h('div', { clase: 'videos-light' });
    videos.forEach(video => lista.appendChild(h('div', { clase: 'video-light' },
      h('button', {
        clase: 'abrir', title: 'Seguir con este vídeo',
        onclick: () => abrirVideoLight(video.id),
      },
        h('span', { clase: 'nombre' }, video.nombre || video.id),
        h('span', { clase: 'meta' }, fechaCorta(video.actualizado) || '')),
      /* EL LAPIZ VA FUERA DEL BOTON DE ABRIR. Un boton dentro de otro no es
         HTML valido y el clic acabaria abriendo el video en vez de renombrarlo
         — la misma razon por la que la tarjeta de un estilo es un div con un
         boton grande dentro y no un boton entero. */
      h('button', {
        clase: 'mini fantasma renombrar', title: 'Cambiar el nombre',
        'aria-label': `Cambiar el nombre de ${video.nombre || video.id}`,
        onclick: () => renombrarVideoLight(video),
      }, '✏️'),
      h('button', {
        clase: 'mini fantasma peligro', title: 'A la papelera de proyectos',
        onclick: () => apartarVideoLight(video),
      }, 'Apartar'))));
    caja.appendChild(lista);
  }

  /* LOS INTENTOS A MEDIAS. Un taller nace antes que su estilo, así que una
     generación que falla deja una carpeta de cientos de megas sin nadie que la
     borre. En vez de barrerla sola por reloj —borrar por su cuenta lo que quizá
     ibas a retomar— se enseña con sus dos salidas. Misma regla que la papelera:
     nada se pierde sin que alguien lo diga. */
  const sueltos = (APP.light.datos || {}).sueltos || [];
  if (sueltos.length) {
    const aviso = h('div', { clase: 'sueltos' },
      h('b', {}, sueltos.length === 1 ? 'Un intento a medias'
        : `${sueltos.length} intentos a medias`),
      h('span', { clase: 'meta' }, sueltos.length === 1
        ? ' — se quedó sin terminar y todavía no es ningún estilo.'
        : ' — se quedaron sin terminar y todavía no son ningún estilo.'));
    sueltos.forEach(taller => aviso.appendChild(h('div', { clase: 'fila' },
      h('span', { clase: 'meta crece' },
        `${taller.nombre} · ${fechaCorta(taller.actualizado) || ''}`),
      h('button', {
        clase: 'mini',
        onclick: () => irALight('crear', { taller: taller.id }),
      }, 'Retomar'),
      h('button', {
        clase: 'mini peligro', onclick: () => descartarTallerLight(taller),
      }, 'Descartar'))));
    caja.appendChild(aviso);
  }
  return caja;
}

/* PULSAR UNA TARJETA LA ELIGE Y PASA AL SIGUIENTE PASO, no la abre. Lo que se
   hace con un estilo el 95 % de las veces es usarlo para un vídeo; editarlo es
   lo raro, y por eso vive en el menú de los tres puntos junto a duplicarlo. */
function tarjetaEstiloLight(ficha) {
  const vinetas = ficha.vinetas || [];
  return h('div', { clase: 'ficha-estilo' },
    h('button', {
      clase: 'cara-y-cuerpo', title: 'Usar este estilo',
      onclick: () => elegirEstiloLight(ficha),
    },
      h('div', { clase: 'cara' }, ficha.hay_miniatura
        ? h('img', { src: API.presetCanalMiniatura(ficha.id, ficha.modificado), alt: '', loading: 'lazy' })
        : h('div', { clase: 'sin-cara' }, 'sin muestras')),
      h('div', { clase: 'cuerpo' },
        h('div', { clase: 'nombre' }, ficha.nombre || ficha.id),
        h('ul', { clase: 'vinetas' },
          // el icono lo manda el servidor con cada línea (`presets_canal.vinetas_de`):
          // aquí no hay forma de saber cuál es el idioma y cuál la voz sin deducirlo
          // del orden, y el orden se rompe en cuanto una línea no sale
          ...vinetas.map(v => h('li', {},
            h('span', { clase: 'ico' }, v.icono || '·'), v.texto || v))))),
    menuDeEstilo(ficha));
}

function tarjetaNuevoEstilo(cuantos) {
  return h('button', {
    clase: 'ficha-estilo nuevo', title: 'Crear un estilo nuevo',
    onclick: () => irALight('crear'),
  },
    h('div', { clase: 'cara' }, h('span', { clase: 'mas' }, '+')),
    h('div', { clase: 'cuerpo' },
      h('div', { clase: 'nombre' }, cuantos ? 'Otro estilo' : 'Tu primer estilo'),
      h('div', { clase: 'pista' }, 'unas imágenes y cómo suena')));
}

/* Los vídeos hechos con este modo, del más reciente al más antiguo. Los sirve
   `GET /api/proyectos` con su marca (`video_light`): son proyectos normales y
   se ven también en el modo editor, que es lo que son. */
function videosLight() {
  return ((APP.light.datos || {}).videos || []).slice();
}

/* CAMBIAR EL NOMBRE DE UN VIDEO. Sirve `PUT /api/proyectos/{pid}`, que cambia
   la ETIQUETA y no la carpeta: el id es la clave de todo lo demas (ver el
   docstring de `renombrar_proyecto` en app.py). Por eso se puede llamar sobre un
   video terminado sin dejar obsoleta ni una imagen. */
async function renombrarVideoLight(video) {
  const antes = video.nombre || video.id;
  const puesto = window.prompt('¿Cómo se llama este vídeo?', antes);
  if (puesto === null) return;                       // cancelar no es renombrar
  const nombre = puesto.trim();
  if (!nombre || nombre === antes) return;
  try {
    const datos = await pedir(API.proyecto(video.id),
      { method: 'PUT', cuerpo: { nombre } });
    const ahora = (datos.proyecto || {}).nombre || nombre;
    /* SI ES EL VIDEO ABIERTO, tambien se le cambia aqui: `APP.light.video.nombre`
       es una copia que se hizo al abrirlo, y sin esto la cabecera seguiria
       diciendo el nombre viejo hasta la proxima recarga. */
    if (APP.light.video && APP.light.video.pid === video.id) {
      APP.light.video.nombre = ahora;
    }
    await cargarGaleriaLight(true);
    toast(`ahora se llama «${ahora}»`);
  } catch (e) { toast(`no se ha podido renombrar: ${e.message}`, true); }
}

async function apartarVideoLight(video) {
  if (!window.confirm(`¿Apartar «${video.nombre}»?

`
    + 'Va a la papelera, no se borra del todo.')) return;
  try {
    await pedir(API.apartar(video.id), { method: 'DELETE' });
    if (videoLightGuardado() === video.id) recordarVideoLight('');
    await cargarGaleriaLight(true);
    toast('vídeo apartado');
  } catch (e) { toast(`no se ha podido apartar: ${e.message}`, true); }
}

async function descartarTallerLight(taller) {
  if (!window.confirm(`¿Descartar «${taller.nombre}»?

`
    + 'Va a la papelera, no se borra del todo.')) return;
  try {
    await pedir(`${API.presetsLight()}/talleres/${encodeURIComponent(taller.id)}`,
      { method: 'DELETE' });
    if (APP.light.taller === taller.id) APP.light.taller = null;
    await cargarGaleriaLight(true);
    toast('intento descartado');
  } catch (e) {
    toast(`no se ha podido descartar: ${e.message}`, true);
  }
}

/* Los tres puntos. Va fuera del botón de la tarjeta —un botón dentro de otro no
   es HTML válido y el clic acabaría eligiendo el estilo— y por eso la tarjeta es
   un div con un botón grande dentro. */
function menuDeEstilo(ficha) {
  const menu = h('div', { clase: 'menu-estilo plegado' },
    h('button', { clase: 'mini fantasma', onclick: () => editarEstiloLight(ficha) }, 'Editar'),
    h('button', { clase: 'mini fantasma', onclick: () => duplicarEstiloLight(ficha) }, 'Duplicar'));
  const puntos = h('button', {
    clase: 'puntos', title: 'Más opciones',
    onclick: ev => {
      ev.stopPropagation();
      const abierto = menu.classList.contains('plegado');
      document.querySelectorAll('.menu-estilo').forEach(m => m.classList.add('plegado'));
      menu.classList.toggle('plegado', !abierto);
    },
  }, '⋯');
  return h('div', { clase: 'esquina' }, puntos, menu);
}

function editarEstiloLight(ficha) {
  irALight('preset', { abierto: ficha.id, feedback: {} });
}

async function duplicarEstiloLight(ficha) {
  toast(`duplicando «${ficha.nombre}»…`);
  try {
    const datos = await pedir(`${API.presetLight(ficha.id)}/duplicar`,
      { method: 'POST', cuerpo: {} });
    await cargarGaleriaLight(true);
    irALight('preset', { abierto: (datos.preset || {}).id, feedback: {} });
    toast('copia lista');
  } catch (e) {
    toast(`no se ha podido duplicar: ${e.message}`, true);
  }
}

/* Elegir un estilo es el principio de hacer un vídeo con él. El paso siguiente
   —el guion— todavía no existe, y esta pantalla lo dice en vez de fingir que sí:
   un botón que no lleva a ninguna parte se prueba una vez y no se vuelve a
   pulsar nunca. La elección SÍ se guarda, así que el día que exista el paso ya
   está tomada. */
function elegirEstiloLight(ficha) {
  localStorage.setItem('estudio.light.estilo', ficha.id);
  // se empieza en el ENCARGO: elegir un estilo es el principio de un vídeo
  // nuevo. Si había uno a medias, la propia pantalla lo ofrece.
  APP.light.video.vista = 'encargo';
  irALight('elegido', { abierto: ficha.id });
}

function estiloElegido() {
  return fichaLight(localStorage.getItem('estudio.light.estilo'));
}

/* ============================================ EL VÍDEO DEL MODO LIGHT
 *
 * La segunda mitad del modo light: elegido un ESTILO, hacer un vídeo con él.
 *
 * TRES PARADAS, NO CINCO PESTAÑAS. En el modo editor cada pestaña es una parada
 * porque cada una tiene decisiones dentro. Aquí las decisiones son tres, y
 * coinciden con las tres cosas que se pueden MIRAR antes de seguir:
 *
 *     encargo   duración y material               →  Generar
 *     guion     se lee, se corrige y se escucha  →  Generar Audio / Generar Vídeo
 *     video     se ve                            →  (fin)
 *
 * Y con el vídeo ya empezado, el encargo se vuelve a abrir desde la barra de
 * abajo («Encargo», vista 'encargo_video'): lo guardado en los params, editable,
 * con «Regenerar el guion» en el pie. Ver `vistaEncargoVideoLight`.
 *
 * Y no hay ninguna decisión entre «los planos» y «el MP4»: lo que sale del
 * render es el vídeo que ya se decidió, así que las dos pestañas van juntas en
 * una sola tanda (`POST /api/proyectos/{pid}/generar`, tanda 'video').
 *
 * EL FOOTER SÍ PERSIGUE EL SCROLL, y eso es lo contrario de lo que se decidió
 * para el formulario de crear un estilo. No es una
 * contradicción: allí el botón está DESPUÉS del último campo porque un
 * formulario se rellena de arriba abajo y se termina abajo. Aquí lo que hay es
 * un documento largo que se lee, y la acción no es «he terminado de rellenar»
 * sino «esto que estoy leyendo, dale». Un botón al final de un guion de nueve
 * minutos es un botón que hay que ir a buscar.
 *
 * LAS ETIQUETAS DEL TTS NO SE VEN AQUÍ. El guion sale con `<break time="900ms"/>`
 * y compañía metidos en el texto (ver marcas_tts), y en el modo editor se
 * enseñan a propósito: allí se decide dónde para el relato. Aquí no: se enseña
 * lo que se va a OÍR. El texto crudo se guarda entero y viaja tal cual — lo que
 * se oculta es la vista, no el dato. */

const CLAVE_VIDEO_LIGHT = 'video_light';

APP.light.video = {
  pid: '',              // el proyecto de este vídeo
  vista: 'encargo',     // encargo | guion | video
  cargando: false,
  error: '',
  estilo: '',           // el preset con el que se creó
  nombre: '',
  fichas: {},           // paso -> ficha del paso, tal cual la sirve la API
  guion: null,          // {titulo, bloques:[{id,texto}]}
  audio: null,          // {bloques con marcas, secciones, url, duracion}
  plan: null,           // lo que va a hacer la próxima tanda, con su coste
  planDe: '',           // ...y de QUÉ trabajo es ese previsto (ver restanteTandaLight)
  /* EL PLAN DE CADA TANDA, cacheado. Lo pedia `barraTandaLight` para escribir
     una linea de texto y lo tiraba; guardado, ademas APAGA el boton cuando no
     queda nada que hacer. Un boton que se puede pulsar y contesta «no queda
     nada por generar» es un boton que miente. */
  planes: {},           // tanda -> lo que devuelve ?tanda=<id>
  coste: null,          // lo que YA se ha gastado, tal cual lo sirve la API
  estimacion: null,     // palabras/planos/dólares de la duración elegida
  prompts: {},          // bid -> lo escrito en la caja de ese bloque
  promptGeneral: '',
  abierto: '',          // el bloque con la caja de prompt abierta
  editando: '',         // el bloque que se está editando a mano con la toma hecha
  velocidad: 1,         // ×1..×5 del reproductor
  planos: [],           // los planos que van cayendo durante el render
  encargo: null,        // el formulario de crear un vídeo NUEVO
  pedido: null,         // la copia editable del encargo del vídeo ABIERTO
};

function encargoVideoLight() {
  const v = APP.light.video;
  if (!v.encargo) {
    v.encargo = {
      nombre: '',
      duracion_objetivo_s: 240,
      // horizontal 16:9 o vertical 9:16. Se decide AQUI, con la duracion, y
      // todo lo de abajo lo respeta: las imagenes se piden en ese tamano y
      // el video sale en esa resolucion (`pasos/comun.FORMATOS`).
      formato: 'horizontal',
      // EL MATERIAL: un texto y nada mas. Va al paso «Origen», que es donde
      // vive con su version y su firma.
      material: '',
      // si lo pegado YA es el guion, el redactor no reescribe: respeta
      guion_propio: false,
      // COMO contarlo, aparte de los hechos: «no fuerces una historia de
      // personaje», «no incluyas la entrevista»
      indicaciones: '',
      // LAS LLAMADAS A LA ACCION son de ESTE video: se deciden aqui y no en el
      // estilo, porque un video puede querer mandar a la web y el siguiente
      // solo pedir un comentario.
      cta: ctaPorDefecto(),
    };
  }
  return v.encargo;
}

/* El vídeo abierto sobrevive a una recarga: se está generando durante minutos y
   se mira desde el móvil mientras corre. Igual que el estilo elegido. */
function recordarVideoLight(pid) {
  if (pid) localStorage.setItem('estudio.light.video', pid);
  else localStorage.removeItem('estudio.light.video');
  APP.light.video.pid = pid || '';
}

function videoLightGuardado() {
  return localStorage.getItem('estudio.light.video') || '';
}

/* --------------------------------------------------------------- lecturas */

/* Un fichero de la versión activa de un paso de ESTE vídeo. `leerArchivo` no
   vale: mira `APP.pid`, que es el proyecto del modo editor y aquí no hay
   ninguno abierto. Leen el vídeo abierto por `videoAbierto()`, que en el light
   es exactamente `APP.light.video`: la URL del MP4 la piden también las
   pestañas del editor. */
async function archivoDeVideoLight(paso, nombre) {
  const ficha = videoAbierto().fichas[paso];
  if (!ficha) return null;
  const version = ficha.version
    || ((ficha.versiones || []).find(x => x.activa) || {}).n
    || (ficha.versiones || []).length;
  if (!version) return null;
  const carpeta = (videoAbierto().trabajando || {})[paso] ? 'trabajo' : `v${version}`;
  const url = API.archivo(videoAbierto().pid, ['pasos', paso, carpeta, nombre].join('/'));
  const respuesta = await fetch(url);
  if (!respuesta.ok) return null;
  return respuesta.json();
}

function urlDeVideoLight(paso, nombre) {
  const ficha = videoAbierto().fichas[paso];
  if (!ficha) return '';
  const version = ficha.version
    || ((ficha.versiones || []).find(x => x.activa) || {}).n
    || (ficha.versiones || []).length;
  if (!version) return '';
  return API.archivo(videoAbierto().pid, ['pasos', paso, `v${version}`, nombre].join('/'));
}

/* Todo lo que la pantalla necesita de este vídeo, de una vez. Se pide entero y
   no paso a paso porque lo que decide qué vista se pinta es el conjunto: hay
   guion o no, hay audio o no, hay MP4 o no. */
async function cargarVideoLight(pid) {
  const v = APP.light.video;
  v.cargando = true;
  v.error = '';
  pintarLight();
  try {
    const proyecto = await pedir(API.proyecto(pid));
    v.pid = pid;
    v.nombre = (proyecto.proyecto || {}).nombre || pid;
    v.estilo = ((proyecto.proyecto || {}).config || {}).estilo_light || '';
    v.fichas = {};
    for (const ficha of (proyecto.pasos || [])) v.fichas[ficha.id] = ficha;
    // la copia del encargo se rehace de los params que acaban de llegar: lo
    // que haya cambiado por otro camino tiene que verse (ver pedidoDelVideoLight)
    v.pedido = null;
    v.guion = await leerGuionLight();
    v.audio = await leerAudioLight();
    v.plan = null;
    v.planDe = '';
    // el coste es de ESTE vídeo: arrastrar el del anterior seria enseñar la
    // cifra de otro proyecto mientras llega la buena
    v.coste = null;
    // y las escenas del previsualizador, por lo mismo: son las de otro vídeo
    pararPrevia();
    PREVIA.ficha = null;
    await reengancharTandaLight(pid);
    // La vista la decide LO QUE HAY, no lo que se pulsó: al volver de una
    // recarga, un vídeo con guion tiene que abrirse en el guion.
    if (v.vista === 'encargo' || !v.vista) {
      if (hayMp4Light()) v.vista = 'video';
      // CON PLANOS DIBUJADOS Y SIN MP4, lo que toca es MIRARLOS.
      //
      // Se pregunta si HAY una versión de assets, no si está al día. Preguntar
      // por 'listo' dejaba fuera justo el caso para el que existe esta
      // pantalla: retocas dos palabras del audio, assets queda OBSOLETO, y al
      // volver se caía al guion con un botón de Generar — como si no hubiera
      // 222 planos dibujados esperando a que alguien los mire. Mirar algo un
      // poco viejo es exactamente lo que se quiere antes de decidir si se
      // regenera.
      else if (versionDe(v.fichas.assets || {})) v.vista = 'previa';
      else if (v.guion) v.vista = 'guion';
      // SIN NADA GENERADO, lo que hay que mirar es el encargo GUARDADO de este
      // vídeo. Antes caía en el formulario de crear otro («Un vídeo nuevo»),
      // con un vídeo ya abierto debajo.
      else v.vista = 'encargo_video';
    }
  } catch (e) {
    v.error = e.message;
  }
  v.cargando = false;
  pintarLight();
}

/* SI LA TANDA SE CAYÓ MIENTRAS NO ESTABAS, se dice.
 *
 * `reengancharTandaLight` solo mira los trabajos VIVOS, así que una tanda que
 * reventó con la pestaña cerrada no dejaba ni rastro: al volver, la pantalla se
 * veía exactamente igual que si nunca hubieras pulsado Generar. Pasó el 27-08
 * —Edge se cayó en un plano y se llevó la tanda por delante— y desde fuera se
 * lee como que el botón no hizo nada, que es lo peor que puede leerse.
 *
 * Se mira el último trabajo de generación del proyecto y, si acabó en error, se
 * enseña. No se relanza nada: qué hacer con un fallo lo decide quien mira. */
async function contarLaTandaQueMurio(pid) {
  if (ERRORES[CLAVE_VIDEO_LIGHT]) return;      // ya hay un error a la vista
  try {
    const datos = await pedir(
      `${API.trabajosVivos()}?proyecto=${encodeURIComponent(pid)}`);
    const generaciones = (datos.trabajos || [])
      .filter(t => String(t.nombre || '').startsWith('generar:'));
    const ultimo = generaciones[generaciones.length - 1];
    if (!ultimo || ultimo.estado !== 'error') return;
    mostrarError(CLAVE_VIDEO_LIGHT, new Error(
      `la última generación se cortó: ${ultimo.error || 'sin motivo'}`));
  } catch (e) { /* no poder mirarlo no puede tumbar la pantalla */ }
}


/* SI YA VENÍA CORRIENDO, la barra se vuelve a enganchar.
   El trabajo vive en el SERVIDOR, así que sobrevive a cerrar la pestaña, a
   recargar y a mirarlo desde el móvil — pero sin esto, al volver se veía un
   vídeo a medias con los botones apagados y ninguna señal de que algo estuviera
   pasando, que es exactamente lo contrario de lo que la pantalla promete. */
async function reengancharTandaLight(pid) {
  if ((APP.trabajos[CLAVE_VIDEO_LIGHT] || {}).estado === 'ejecutando') return;
  try {
    const datos = await pedir(`${API.trabajosVivos()}?proyecto=`
      + `${encodeURIComponent(pid)}&activos=1`);
    const vivo = (datos.trabajos || []).find(
      t => String(t.nombre || '').startsWith('generar:'));
    if (!vivo) { await contarLaTandaQueMurio(pid); return; }
    /* DE QUE TANDA ES EL TRABAJO QUE YA VENIA CORRIENDO.
     *
     * El nombre es «generar:» y las pestañas que recorre (`_correr_cadena` en
     * app.py), así que la del MP4 se llama `generar:video+render` y la de las
     * imágenes `generar:video`. Esto decía que un nombre con «render» dentro
     * era la tanda 'video', y de ahí salían tres cosas mal a la vez al volver a
     * la pantalla con el montaje en marcha: se caía en las diapositivas en vez
     * de en el vídeo, no se refrescaba nada de lo que se estaba montando, y la
     * cuenta atrás pedía el previsto de OTRA tanda —el de dibujar los planos,
     * cuatro horas y media— y decía «quedan ~261m» a los veinte minutos de
     * haber pulsado «Montar el vídeo». Visto en un vídeo de catorce minutos.
     *
     * El orden importa: 'render' se mira ANTES que 'video' porque su nombre
     * lleva las dos pestañas dentro. */
    const nombre = String(vivo.nombre);
    const tanda = nombre.includes('render') ? 'render'
      : (nombre.includes('video') ? 'video'
        : (nombre.includes('voz') ? 'voz' : 'guion'));
    // la tanda de las imágenes acaba en el previsualizador; la del MP4, en el vídeo
    if (tanda === 'video') APP.light.video.vista = 'previa';
    else if (tanda === 'render') APP.light.video.vista = 'video';
    // EL PREVISTO, TAMBIÉN AL REENGANCHAR. Sin esto, volver a la pantalla con
    // la tanda ya corriendo —que es el caso normal cuando se mira desde el
    // móvil— dejaba la barra sin cuenta atrás hasta que terminase.
    try {
      APP.light.video.plan = (await pedir(
        `${API.proyecto(pid)}/generar?tanda=${tanda}`)) || null;
      APP.light.video.planDe = vivo.id;
    } catch (e) { /* sin previsto se pinta sin cuenta atrás */ }
    seguirTrabajo(CLAVE_VIDEO_LIGHT, vivo.id, async trabajo => {
      if (trabajo.estado === 'listo') await cargarVideoLight(pid);
      pintarLight();
    }, () => {
      if (tanda === 'video') refrescarPlanosLight();
      refrescarVivosLight();
    });
  } catch (e) { /* no poder mirar los trabajos no puede tumbar la pantalla */ }
}

async function leerGuionLight() {
  const documento = await archivoDeVideoLight('guion', 'guion.json');
  if (!documento) return null;
  const bloques = (documento.guion || documento.bloques || [])
    .map(b => ({ id: b.id, texto: b.texto || '' }));
  if (!bloques.length) return null;
  return {
    titulo: documento.titulo || '',
    palabras: documento.palabras || 0,
    avisos: documento.avisos || [],
    bloques,
  };
}

async function leerAudioLight() {
  const ficha = APP.light.video.fichas.voz;
  if (!ficha || !(ficha.versiones || []).length || ficha.estado === 'bloqueado') return null;
  const salidas = ficha.salidas || {};
  const meta = await archivoDeVideoLight('voz', salidas.meta || 'audio_meta.json');
  if (!meta) return null;
  const normal = normalizarAudio(salidas, meta);
  if (!normal.bloques.length) return null;
  return Object.assign(normal, {
    url: urlDeVideoLight('voz', salidas.archivo || 'narracion.wav'),
    obsoleto: ficha.estado === 'obsoleto',
  });
}

/* EL VÍDEO SE HA QUEDADO VIEJO. Regenerar el guion o el audio NO rehace el
   vídeo —rehacer una cosa rehace ESA cosa— así que el MP4 que
   hay sigue diciendo lo de antes. El núcleo ya lo sabe: deja `obsoleto` todo lo
   que viene después. Aquí sólo se lee y se enseña, que es la contrapartida
   obligatoria de no generar en cascada: una etiqueta que no se puede accionar
   es peor que no tenerla, y el botón está justo al lado.

   Se miran los tres pasos y no sólo el render porque el guion entra por arriba:
   con un guion nuevo lo primero que queda viejo son los planos. */
function videoObsoletoLight() {
  const v = videoAbierto();
  if (!hayMp4Light()) return false;
  return ['assets', 'callouts', 'render']
    .some(paso => (v.fichas[paso] || {}).estado === 'obsoleto');
}

function pastillaObsoletoLight() {
  if (!videoObsoletoLight()) return null;
  return h('span', {
    clase: 'pastilla obsoleto',
    title: 'has cambiado el guion o el audio después de montarlo, así que el '
      + 'vídeo que hay no dice lo de ahora. Al generarlo se rehace SOLO lo que '
      + 'ha cambiado: lo que siga valiendo no se vuelve a pagar.',
  }, 'Obsoleto');
}

function hayMp4Light() {
  const ficha = videoAbierto().fichas.render;
  return !!(ficha && (ficha.versiones || []).length && (ficha.salidas || {}).mp4);
}

function urlMp4Light() {
  const ficha = videoAbierto().fichas.render || {};
  const salidas = ficha.salidas || {};
  const nombre = String(salidas.mp4 || 'video.mp4').split('\\').join('/').split('/').pop();
  return urlDeVideoLight('render', nombre);
}

/* El TEXTO que se enseña de un bloque: el editado a mano si lo hay, y el del
   guion si no. Las dos cosas viven donde ya vivían (`params.guion.bloques` y
   `guion.json`), así que una edición hecha aquí se ve igual en el modo editor. */
function textoDeBloqueLight(bloque) {
  const editados = ((APP.light.video.fichas.guion || {}).params || {}).bloques || {};
  const ficha = editados[bloque.id];
  const texto = ficha && typeof ficha === 'object' ? ficha.texto : ficha;
  return (typeof texto === 'string' && texto.trim()) ? texto : bloque.texto;
}

/* «EDITADO» ES UNA COSA PENDIENTE, NO UNA CICATRIZ.
 *
 * Marcaba para siempre todo bloque cuyo texto se hubiera tocado a mano, y eso
 * sobra en cuanto la voz ya lo dice: un bloque reescrito Y grabado esta al
 * mismo nivel que los demas, y dejarlo marcado convierte la pantalla en un
 * historial de ediciones en vez de una lista de lo que falta.
 *
 * La voz sintetiza LA TOMA ENTERA, asi que hay un solo dato que responde a
 * «¿estan mis cambios en el audio?»: si a la tanda de voz no le queda nada por
 * hacer, estan. Mientras conteste que si queda, la etiqueta avisa de que eso
 * todavia no se oye. */
function bloqueEditadoLight(bloque) {
  /* MIENTRAS NO SE SABE, NO SE ACUSA. `quedaTandaLight` devuelve `null` hasta
     que llega el plan, y preguntando por `=== false` ese `null` se colaba: al
     entrar salian los sesenta y ocho marcados «editado» y desaparecian solos un
     instante despues, cuando contestaba el servidor. Una etiqueta que aparece y
     se va sola no es informacion, es ruido. Se marca solo cuando se SABE que
     queda voz por grabar. */
  if (quedaTandaLight('voz') !== true) return false;
  return textoDeBloqueLight(bloque) !== bloque.texto;
}

/* --------------------------------------------------------------- el encargo */

/* LA PRIMERA PANTALLA: las tres decisiones del vídeo, y ninguna más.
 *
 * Duración y material. Todo lo demás —el estilo gráfico, el tono, la
 * voz, el ritmo, la calidad, el grafismo— lo trae el ESTILO, que es justamente
 * lo que un estilo es. Preguntarlo otra vez aquí sería no haberlo elegido. */
function vistaElegidoLight() {
  const ficha = fichaLight(APP.light.abierto) || estiloElegido();
  const e = encargoVideoLight();
  const caja = h('div', { clase: 'light-form' });
  caja.appendChild(h('div', { clase: 'light-cab' },
    /* VOLVER A LA GALERIA. La barra de abajo ya tiene «Estilos», pero hace otra
       cosa: OLVIDA el vídeo empezado (`recordarVideoLight('')`), que es lo que
       hay que hacer al salir de uno y no al arrepentirse de empezar otro. Este
       solo vuelve, y por eso el aviso de «Tienes un vídeo empezado» sigue ahí
       cuando entras otra vez. */
    h('button', {
      clase: 'mini fantasma volver', title: 'Volver a tus estilos y tus vídeos',
      onclick: () => { pararPrevia(); irALight('galeria'); },
    }, '← Volver'),
    h('h2', {}, 'Un vídeo nuevo'),
    h('span', { clase: 'meta' }, ficha ? `con «${ficha.nombre}»` : 'sin estilo')));

  if (!ficha) {
    caja.appendChild(cajaError('No se sabe con qué estilo hacer este vídeo. '
      + 'Vuelve a la galería y elige uno.'));
    return caja;
  }

  // Un vídeo a medias tiene prioridad sobre empezar otro: se generó durante
  // minutos y se está mirando desde el móvil.
  const guardado = videoLightGuardado();
  if (guardado && guardado !== APP.light.video.pid) {
    caja.appendChild(h('div', { clase: 'sueltos' },
      h('b', {}, 'Tienes un vídeo empezado'),
      h('span', { clase: 'meta' }, ' — se quedó a medias o está generándose.'),
      h('div', { clase: 'fila' },
        h('button', {
          clase: 'mini', onclick: () => abrirVideoLight(guardado),
        }, 'Seguir con él'),
        h('button', {
          clase: 'mini fantasma',
          onclick: () => { recordarVideoLight(''); pintarLight(); },
        }, 'Empezar otro'))));
  }

  caja.appendChild(bloqueLight('El vídeo', 'cómo se llama y cuánto dura',
    campoTexto('Nombre', e.nombre,
      v => { e.nombre = v; },
      { pista: 'La crisis del agua en el sur', ayuda: 'Es el nombre del proyecto y '
        + 'lo que el documentalista lee como «de qué va este vídeo».' }),
    duracionLight(e),
    selectorFormato(e.formato, v => { e.formato = v; })));

  caja.appendChild(bloqueLight('El material',
    'de dónde salen los hechos que se van a contar',
    materialLight(e)));

  /* LAS INDICACIONES, detrás del material y en su propio bloque: los hechos son
     una cosa y CÓMO contarlos es otra. Cuando iban en la misma caja, lo escrito
     detrás del material lo leía el documentalista y no el guionista: salía un
     guion que no hacía caso a algo que nadie le había dicho. */
  caja.appendChild(bloqueLight('Las indicaciones',
    'cómo quieres que se cuente (opcional)',
    campoArea('', e.indicaciones, v => { e.indicaciones = v; },
      'céntrate en el mecanismo, no en las personas; no fuerces una historia '
      + 'de personaje')));

  /* LAS LLAMADAS A LA ACCIÓN son de ESTE vídeo y se deciden aquí. No viajan en
     el estilo a propósito: si viajaran, elegir un estilo pisaría lo que acabas
     de escribir para este vídeo. */
  if (!e.cta) e.cta = ctaPorDefecto();
  caja.appendChild(bloqueLight('Las llamadas a la acción',
    'cuándo se presenta y qué le pides a quien lo ve',
    bloqueCTA(e.cta, { repintar: pintarLight })));

  const aviso = h('div', { clase: 'pista' });
  const boton = h('button', {
    clase: 'primario grande',
    onclick: () => crearYGenerarLight(ficha),
  }, 'Generar el guion');
  caja.appendChild(h('div', { clase: 'fila cierre' }, boton, aviso));
  pintarCosteDelEncargoLight(e, aviso);
  return caja;
}

/* HORIZONTAL O VERTICAL. Dos botones y no un desplegable: son dos, y se ven.
   Lo comparten el encargo del light y el brief del editor. */
const FORMATOS_VIDEO = [
  { id: 'horizontal', nombre: 'Horizontal 16:9', pista: 'YouTube, pantalla' },
  { id: 'vertical', nombre: 'Vertical 9:16', pista: 'Shorts, Reels, TikTok' },
];

function selectorFormato(valor, alCambiar) {
  const actual = valor === 'vertical' ? 'vertical' : 'horizontal';
  const tira = h('div', { clase: 'tira-modos formatos' });
  FORMATOS_VIDEO.forEach(f => {
    tira.appendChild(h('button', {
      clase: 'mini' + (f.id === actual ? ' activo' : ''), title: f.pista,
      onclick: () => {
        tira.querySelectorAll('button').forEach(b => b.classList.toggle('activo', b.dataset.id === f.id));
        alCambiar(f.id);
      },
      'data-id': f.id,
    }, (f.id === 'vertical' ? '▯ ' : '▭ ') + f.nombre));
  });
  return h('div', { clase: 'campo' }, h('label', {}, 'Formato'), tira);
}

/* El formato del vídeo abierto, para que los marcos de la previa y del vídeo
   tengan la proporción del vídeo de verdad y no siempre 16:9. */
function formatoDelVideo() {
  const previa = (PREVIA.ficha || {}).formato;
  if (previa) return previa === 'vertical' ? 'vertical' : 'horizontal';
  const v = videoAbierto() || {};
  const brief = ((v.fichas || {}).brief || {}).params || {};
  return brief.formato === 'vertical' ? 'vertical' : 'horizontal';
}

/* `estilo` es el del vídeo cuando ya existe (el encargo de un vídeo abierto);
   sin él se estima con el estilo elegido en la galería, que es el de un vídeo
   que se está creando. */
function duracionLight(e, estilo) {
  const linea = h('div', { clase: 'ritmo-linea' }, '…');
  const numero = h('input', {
    type: 'number', min: 30, max: 3600, step: 10, value: e.duracion_objetivo_s,
    clase: 'duracion-num',
  });
  const barra = h('input', {
    type: 'range', min: 60, max: 1800, step: 30, value: e.duracion_objetivo_s,
    clase: 'ritmo',
  });
  const mover = valor => {
    e.duracion_objetivo_s = Math.max(30, Math.round(Number(valor) || 0));
    numero.value = e.duracion_objetivo_s;
    barra.value = Math.min(1800, Math.max(60, e.duracion_objetivo_s));
    refrescarEstimacionLight(e, linea, estilo);
  };
  barra.addEventListener('input', () => mover(barra.value));
  numero.addEventListener('input', () => mover(numero.value));
  refrescarEstimacionLight(e, linea, estilo);
  return h('div', { clase: 'campo' },
    h('label', {}, 'Duración objetivo'),
    h('div', { clase: 'fila' }, barra, numero, h('span', { clase: 'meta' }, 'segundos')),
    linea);
}

/* La línea de debajo de la duración: palabras, horquilla REAL de vuelta y de
   dónde sale la cadencia. La cuenta la hace el servidor (`/api/estimacion`),
   que es el único sitio donde vive: aquí hubo una tabla de palabras por segundo
   y era la tercera copia de la misma cuenta. */
async function refrescarEstimacionLight(e, nodo, estiloDado) {
  const estilo = estiloDado || fichaLight(APP.light.abierto) || estiloElegido() || {};
  const datos = (estilo.datos || {});
  const voz = datos.voz || {};
  try {
    const ficha = await estimacionDe({
      duracion_objetivo_s: e.duracion_objetivo_s,
      idioma: estilo.idioma || 'es',
      velocidad: voz.velocidad || 'normal',
      // la voz entra en la cuenta: la cadencia no es solo del idioma
      voz: voz.voz_id || '',
      hueco_minimo: voz.hueco_minimo,
      min_s: (datos.estilo || {}).min_s,
      max_s: (datos.estilo || {}).max_s,
      calidad: (datos.estilo || {}).calidad,
    });
    APP.light.video.estimacion = ficha;
    vaciar(nodo).append(textoDeEstimacion(ficha));
  } catch (err) {
    vaciar(nodo).append(`no se ha podido estimar: ${err.message}`);
  }
}

/* Y EL COSTE DEL VÍDEO ENTERO, al lado del botón de generar. Se dice ANTES de
   pulsar porque es la única forma de que sirva: una cifra que aparece cuando ya
   se está gastando no es un aviso, es un recibo.

   SE LLAMABA `refrescarCosteLight`, igual que la del medidor de un vídeo YA
   empezado, y en JavaScript la segunda declaración de un nombre se lleva la
   primera por delante: esta no corría nunca y el hueco de al lado del botón se
   quedaba vacío para siempre. No daba ningún error --la que sí existe acepta un
   argumento y lo trata como «forzar»-- y por eso llevaba así desde que se
   escribió. Con nombre propio, la cifra vuelve a salir. */
async function pintarCosteDelEncargoLight(e, nodo) {
  const estilo = fichaLight(APP.light.abierto) || estiloElegido() || {};
  const datos = (estilo.datos || {});
  try {
    const ficha = await estimacionDe({
      duracion_objetivo_s: e.duracion_objetivo_s,
      idioma: estilo.idioma || 'es',
      velocidad: (datos.voz || {}).velocidad || 'normal',
      voz: (datos.voz || {}).voz_id || '',
      hueco_minimo: (datos.voz || {}).hueco_minimo,
      min_s: (datos.estilo || {}).min_s,
      max_s: (datos.estilo || {}).max_s,
      calidad: (datos.estilo || {}).calidad,
    });
    vaciar(nodo).append(`El vídeo entero: ${textoDeCoste(ficha)}. `
      + 'Puede salir algo más corto o más largo que el objetivo.');
  } catch (err) { vaciar(nodo).append(''); }
}

/* Los planos, las imágenes que se pagan y el dólar. `imagenes_hechas` sale
   cuando el vídeo ya tiene parte generada: entonces se dice lo que falta por
   pagar y, aparte, lo que costaría rehacerlo entero -- son dos cifras
   distintas y confundirlas es la diferencia entre seguir y empezar de cero. */
function textoDeCoste(ficha) {
  const c = ficha.coste || {};
  const pl = ficha.planos || {};
  if (c.imagenes_hechas) {
    return `${pl.total} planos · ${c.imagenes_por_generar} imágenes `
      + `(${c.imagenes_hechas} ya hechas) · ≈ ${Number(c.usd_por_generar || 0).toFixed(2)} $ `
      + `· hasta ${Number(c.usd_total || 0).toFixed(2)} $ si hay que rehacerlas`;
  }
  return `${pl.total} planos · ${c.imagenes} imágenes · ≈ ${Number(c.usd_total || 0).toFixed(2)} $`;
}

/* EL MATERIAL. Una lista de cajas: cada una es un enlace o un texto, y el
   servidor deduce cuál es (`fuentes.clasificar`). Lo que NO se deduce es el
   `uso` —si eso es documentación o si ES el guion—, y por eso se pregunta: ese
   fue exactamente el error del detector de copias que se retiró. */
/* EL MATERIAL: UNA CAJA, Y LO QUE HAY EN ELLA ES TODO.
 *
 * De aquí salen los hechos del guion, y de ningún otro sitio: no se abren
 * enlaces, no se busca en internet y no hay una segunda caja que rellenar. Es
 * deliberado —lo que se ve es lo que se cuenta—, y hace que un guion que dice
 * algo raro se explique mirando un solo campo.
 *
 * Las INDICACIONES van aparte, en su propio bloque: los hechos son una cosa y
 * cómo contarlos es otra. Mezclarlos en la misma caja hacía que lo escrito
 * detrás de un enlace lo leyera el documentalista y no el guionista.
 *
 * La casilla de «esto ya es el guion» cambia la regla del redactor: con ella
 * puesta no reescribe, respeta. */
function materialLight(e) {
  const caja = h('div', { clase: 'campo' });
  const area = h('textarea', {
    rows: 8, placeholder: 'Pega o escribe de qué va este vídeo: los hechos, las '
      + 'fechas, los nombres, el orden en que pasaron…',
    oninput: ev => { e.material = ev.target.value; },
  });
  // con nombre estable: el encargo de un vídeo abierto se repinta al cambiar
  // el plan del guion, y sin esto el cursor se iba del material a medio pegar
  area.dataset.foco = 'encargo-material';
  area.value = e.material || '';
  caja.appendChild(h('div', { clase: 'fuente-light' }, h('div', { clase: 'area' }, area)));
  caja.appendChild(h('label', { clase: 'plano' },
    h('input', {
      type: 'checkbox', checked: !!e.guion_propio,
      onchange: ev => { e.guion_propio = ev.target.checked; pintarLight(); },
    }),
    h('span', {}, 'Esto YA es el guion: respétalo palabra por palabra')));
  caja.appendChild(h('div', { clase: 'pista' }, e.guion_propio
    ? 'Con esto marcado el redactor NO reescribe: reparte tu texto en bloques, '
      + 'lo mide y lo deja como está.'
    : 'Se trabaja exclusivamente con lo que pongas aquí: no se sale a internet '
      + 'ni se abre ningún enlace.'));
  return caja;
}

/* Crear el proyecto y lanzar la primera tanda, en un gesto. Son dos llamadas
   —el proyecto tiene que existir antes de poder generar nada en él— pero UNA
   decisión, así que un botón. */
async function crearYGenerarLight(estilo) {
  const e = encargoVideoLight();
  if (!String(e.material || '').trim()) {
    toast('No hay material: escribe o pega de qué va este vídeo', true);
    return;
  }
  toast('creando el vídeo…');
  try {
    const datos = await pedir(`${API.presetLight(estilo.id)}/video`, {
      method: 'POST',
      cuerpo: {
        nombre: e.nombre || `Vídeo de ${estilo.nombre || estilo.id}`,
        duracion_objetivo_s: e.duracion_objetivo_s,
        formato: e.formato || 'horizontal',
        material: e.material,
        guion_propio: !!e.guion_propio,
        indicaciones: e.indicaciones,
        cta: e.cta,
      },
    });
    const pid = (datos.proyecto || {}).id;
    if (!pid) throw new Error('el servidor no ha devuelto ningún proyecto');
    recordarVideoLight(pid);
    APP.light.video.nombre = (datos.proyecto || {}).nombre || pid;
    APP.light.video.estilo = estilo.id;
    (datos.avisos || []).forEach(a => toast(a, true));
    await cargarVideoLight(pid);
    APP.light.video.vista = 'guion';
    await lanzarTandaLight('guion');
  } catch (err) {
    toast(`no se ha podido crear el vídeo: ${err.message}`, true);
  }
}

async function abrirVideoLight(pid) {
  recordarVideoLight(pid);
  APP.light.video.vista = '';
  irALight('elegido');
  await cargarVideoLight(pid);
}

/* ============================================ EL ENCARGO DE UN VÍDEO YA EMPEZADO
 *
 * La parada «Encargo» de la barra de abajo, con un vídeo abierto. Es lo mismo
 * que abrir un estilo para corregirlo: se enseña LO GUARDADO y se corrige ahí
 * mismo, con autoguardado y sin botón de confirmar.
 *
 * NO HAY UN ALMACÉN DEL ENCARGO. Lo que se pidió al crear el vídeo se repartió
 * en los params de tres pasos del grafo (`_sembrar_video_light` en app.py) y
 * ahí es donde vive, con su versión y su firma:
 *
 *     el material                 ingesta.texto
 *     la duración y el formato    brief.duracion_objetivo_s, brief.formato
 *     «esto ya es el guion»       guion.guion_propio
 *     las indicaciones            guion.prompt_general
 *     las llamadas a la acción    guion.cta
 *     el nombre                   la etiqueta del proyecto; no entra en ninguna firma
 *
 * Esta pantalla LEE de esos params y ESCRIBE en esos params, y por eso la
 * obsolescencia sale sola: cambiar el material deja obsoleto el guion y, en
 * cascada, la voz y las imágenes. No hay nada que marcar a mano.
 *
 * SÓLO SE ESCRIBE LO QUE SE HA TOCADO, y es la regla de la casa (CLAUDE.md):
 * la firma de un paso se calcula sobre los params guardados, así que escribir
 * al abrir la pantalla un `formato: 'horizontal'` que el brief nunca tuvo
 * movería la firma y dejaría obsoleto el vídeo entero sin que nadie hubiera
 * pedido nada. Se edita una COPIA (`pedido.copia`) frente a una FOTO de lo
 * guardado (`pedido.guardado`) y al volcar viaja, por paso, sólo la clave que
 * difiere. Mover la duración y devolverla a donde estaba no escribe nada.
 */

/* Cada campo de la copia, y en qué param de qué paso vive. */
const CAMPOS_ENCARGO = [
  { clave: 'material', paso: 'ingesta', param: 'texto' },
  { clave: 'duracion_objetivo_s', paso: 'brief', param: 'duracion_objetivo_s' },
  { clave: 'formato', paso: 'brief', param: 'formato' },
  { clave: 'guion_propio', paso: 'guion', param: 'guion_propio' },
  { clave: 'indicaciones', paso: 'guion', param: 'prompt_general' },
  { clave: 'cta', paso: 'guion', param: 'cta' },
];

/* Las tres ranuras completas a partir de lo guardado, que puede faltar entero
   o a medias. `bloqueCTA` rellena lo que falte al pintar, y si la copia y la
   foto no tuvieran la misma forma desde el principio ese relleno contaría como
   un cambio y se escribiría un `cta` que nadie ha tocado. */
function ctaLeida(crudo) {
  const ficha = ctaPorDefecto();
  if (!crudo || typeof crudo !== 'object') return ficha;
  CTA_MOMENTOS.forEach(m => {
    const ranura = crudo[m.id];
    if (!ranura || typeof ranura !== 'object') return;
    ficha[m.id] = { puesto: !!ranura.puesto, texto: String(ranura.texto || '') };
  });
  return ficha;
}

/* La copia editable del encargo del vídeo abierto, hecha de sus params. Se
   construye una vez por vídeo y `cargarVideoLight` la tira al releer el
   proyecto: lo que haya cambiado por otro camino (el prompt general escrito
   desde el guion, un param tocado en el editor) vuelve a leerse. */
function pedidoDelVideoLight() {
  const v = APP.light.video;
  if (v.pedido && v.pedido.pid === v.pid) return v.pedido;
  const params = paso => ((v.fichas[paso] || {}).params || {});
  const copia = {
    nombre: v.nombre || '',
    material: String(params('ingesta').texto || ''),
    duracion_objetivo_s: Number(params('brief').duracion_objetivo_s) || 240,
    formato: params('brief').formato === 'vertical' ? 'vertical' : 'horizontal',
    guion_propio: !!params('guion').guion_propio,
    indicaciones: String(params('guion').prompt_general || ''),
    cta: ctaLeida(params('guion').cta),
  };
  v.pedido = {
    pid: v.pid,
    copia,
    guardado: JSON.parse(JSON.stringify(copia)),
    reloj: null,
  };
  return v.pedido;
}

function vistaEncargoVideoLight() {
  const v = APP.light.video;
  const estilo = fichaLight(v.estilo);
  const e = pedidoDelVideoLight().copia;
  const caja = h('div', { clase: 'light-form light-encargo' });
  caja.appendChild(h('div', { clase: 'light-cab' },
    h('h2', {}, 'El encargo'),
    h('span', { clase: 'meta' },
      estilo ? `con «${estilo.nombre}»` : (v.estilo ? `con «${v.estilo}»` : '')),
    h('span', { clase: 'crece' }),
    costeLight()));

  const error = ERRORES[CLAVE_VIDEO_LIGHT];
  if (error) caja.appendChild(cajaError(error));

  caja.appendChild(h('div', { clase: v.guion ? 'caja-aviso' : 'caja-info' }, v.guion
    ? 'Esto es lo que se le pidió al redactor, y de aquí salió el guion que hay. '
      + 'Lo que cambies se guarda solo y deja el guion obsoleto: el pie ofrece '
      + 'regenerarlo, y con él se rehacen después la voz y las imágenes que ya '
      + 'no cuadren; lo que siga valiendo no se vuelve a pagar. El nombre se '
      + 'cambia sin regenerar nada. El formato rehace TODAS las imágenes.'
    : 'Lo que se le va a pedir al redactor. Se guarda solo; cuando esté, '
      + '«Generar el guion» abajo.'));

  /* TODO LO QUE SE TECLEA O SE MARCA AQUÍ DENTRO PROGRAMA UN VOLCADO. Por
     delegación y no campo a campo: la duración y el material se pintan con las
     mismas funciones que el formulario de crear, que escriben en `e` y no
     avisan a nadie. Lo que no dispara `input` ni `change` --el formato, que
     son botones-- avisa por su cuenta. */
  caja.addEventListener('input', programarGuardadoEncargo);
  caja.addEventListener('change', programarGuardadoEncargo);

  const nombre = campoTexto('Nombre', e.nombre, valor => { e.nombre = valor; },
    { pista: 'La crisis del agua en el sur',
      ayuda: 'Es la etiqueta del vídeo en la lista. Cambiarla no regenera nada.' });
  const entradaNombre = nombre.querySelector('input');
  if (entradaNombre) entradaNombre.dataset.foco = 'encargo-nombre';
  caja.appendChild(bloqueLight('El vídeo', 'cómo se llama y cuánto dura',
    nombre,
    duracionLight(e, estilo),
    selectorFormato(e.formato, valor => { e.formato = valor; programarGuardadoEncargo(); })));

  caja.appendChild(bloqueLight('El material',
    'de dónde salen los hechos que se van a contar',
    materialLight(e)));

  caja.appendChild(bloqueLight('Las indicaciones',
    'cómo quieres que se cuente (opcional)',
    campoArea('', e.indicaciones, valor => { e.indicaciones = valor; },
      'céntrate en el mecanismo, no en las personas; no fuerces una historia '
      + 'de personaje', 'encargo-indicaciones')));

  caja.appendChild(bloqueLight('Las llamadas a la acción',
    'cuándo se presenta y qué le pides a quien lo ve',
    bloqueCTA(e.cta, { alCambiar: programarGuardadoEncargo, repintar: pintarLight })));

  BARRA_INFERIOR.nodo = pieDeEncargo();
  return caja;
}

/* El pie del encargo: generar el guion, o regenerarlo con lo que ha cambiado.
   Mira el PLAN de la tanda 'guion' y no el estado de los pasos, igual que los
   botones del guion: un botón encendido que contesta «no queda nada por
   generar» es un botón que miente. */
function pieDeEncargo() {
  const v = APP.light.video;
  const corriendo = !!trabajoVideoLight();
  refrescarPlanLight('guion');
  const queda = quedaTandaLight('guion');
  const hayGuion = !!v.guion;
  return h('div', { clase: 'pie-guion pie-encargo' },
    conAyuda(unirAyuda(ayudaEncargo(hayGuion, queda), textoDelPlan('guion')),
      h('button', {
        clase: 'primario',
        disabled: corriendo || queda === false,
        /* 'pendientes' y no 'todo': REHACER UNA COSA REHACE ESA COSA. Lo que
           se ha tocado aquí ya ha dejado obsoleto lo suyo, y eso es lo que
           entra; lo que sigue al día se salta. */
        onclick: () => lanzarTandaLight('guion', 'pendientes'),
      }, hayGuion ? 'Regenerar el guion' : 'Generar el guion')),
    corriendo ? barraTandaLight('guion') : h('span', { clase: 'crece' }),
    corriendo ? conAyuda(
      'Corta la tanda donde esté. Lo que ya se ha generado se queda hecho y no '
      + 'hay que volver a pagarlo.',
      h('button', {
        clase: 'mini peligro', onclick: () => cancelar(CLAVE_VIDEO_LIGHT),
      }, 'Parar')) : null,
    (!corriendo && hayGuion && queda) ? h('span', {
      clase: 'pastilla obsoleto',
      title: 'has cambiado el encargo después de escribir el guion, así que el '
        + 'guion que hay no dice lo de ahora.',
    }, 'Guion obsoleto') : null);
}

function ayudaEncargo(hayGuion, queda) {
  if (queda === false) {
    return 'El guion ya recoge todo lo que hay en este encargo. No queda nada '
      + 'que redactar: para cambiarlo, toca algo aquí o escribe qué cambiarías '
      + 'en la pantalla del guion.';
  }
  return hayGuion
    ? 'Vuelve a redactar el guion con el encargo de ahora. La voz y las '
      + 'imágenes que dependan de lo que cambie quedan obsoletas y se rehacen '
      + 'después, desde su propia pantalla.'
    : 'Lee el material y redacta el guion con el estilo del vídeo. No dibuja '
      + 'nada todavía.';
}

/* Repinta SOLO el pie, como `repintarPieDeEstilo`: el formulario no se puede
   rehacer mientras se escribe en él. */
function repintarPieDeEncargo() {
  const viejo = document.querySelector('.pie-encargo');
  if (!viejo || APP.light.video.vista !== 'encargo_video') return;
  const nuevo = pieDeEncargo();
  viejo.replaceWith(nuevo);
  BARRA_INFERIOR.nodo = nuevo;
}

/* AUTOGUARDADO: 900 ms después del último toque, la misma espera que el estilo. */
function programarGuardadoEncargo() {
  const pedido = APP.light.video.pedido;
  if (!pedido) return;
  clearTimeout(pedido.reloj);
  pedido.reloj = setTimeout(() => volcarEncargoLight(pedido), 900);
}

/* Vuelca lo que difiere entre la copia y la foto, por paso y en el orden del
   grafo, y pone la foto al día con lo confirmado. Recibe el `pedido` y no lo
   busca: si mientras tanto se ha abierto otro vídeo, lo que había a medio
   escribir sigue siendo de ESTE. */
async function volcarEncargoLight(pedido) {
  clearTimeout(pedido.reloj);
  pedido.reloj = null;
  const { pid, copia, guardado } = pedido;
  const igual = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const porPaso = {};
  for (const campo of CAMPOS_ENCARGO) {
    if (igual(copia[campo.clave], guardado[campo.clave])) continue;
    porPaso[campo.paso] = porPaso[campo.paso] || {};
    porPaso[campo.paso][campo.param] = JSON.parse(JSON.stringify(copia[campo.clave]));
  }
  const nombre = String(copia.nombre || '').trim();
  const renombrar = !!nombre && nombre !== guardado.nombre;
  if (!Object.keys(porPaso).length && !renombrar) return;
  try {
    for (const paso of ['ingesta', 'brief', 'guion']) {
      if (!porPaso[paso]) continue;
      await pedir(API.params(pid, paso),
        { method: 'PUT', cuerpo: { params: porPaso[paso] } });
      for (const campo of CAMPOS_ENCARGO) {
        if (campo.paso === paso && campo.param in porPaso[paso]) {
          guardado[campo.clave] = JSON.parse(JSON.stringify(copia[campo.clave]));
        }
      }
    }
    if (renombrar) {
      const datos = await pedir(API.proyecto(pid), { method: 'PUT', cuerpo: { nombre } });
      const ahora = (datos.proyecto || {}).nombre || nombre;
      guardado.nombre = ahora;
      if (APP.light.video.pid === pid) APP.light.video.nombre = ahora;
      // la lista de «Tus vídeos» de la galería es una copia: se pone al día
      ((APP.light.datos || {}).videos || []).forEach(video => {
        if (video.id === pid) video.nombre = ahora;
      });
    }
    if (APP.light.video.pid !== pid) return;
    /* Los estados de los pasos han cambiado en cascada y la pantalla los lee
       de las fichas: se vuelven a pedir, sin repintar el formulario (se está
       escribiendo en él). El pie sí, que es lo que cambia a la vista. */
    await refrescarFichasLight();
    refrescarPlanLight('guion', true);
    repintarPieDeEncargo();
  } catch (e) {
    toast(`no se ha podido guardar el encargo: ${e.message}`, true);
  }
}

/* Las fichas de los pasos del vídeo abierto, otra vez, y nada más: ni el guion
   ni el audio ni la vista. Es lo que `cargarVideoLight` hace de más cuando lo
   único que ha cambiado es un estado. */
async function refrescarFichasLight() {
  const v = APP.light.video;
  const pid = v.pid;
  if (!pid) return;
  const proyecto = await pedir(API.proyecto(pid));
  if (APP.light.video.pid !== pid) return;
  for (const ficha of (proyecto.pasos || [])) v.fichas[ficha.id] = ficha;
}

/* -------------------------------------------------------------- las tandas */

/* UNA TANDA ES UN TRABAJO. La cadena entera corre en el servidor
   (`POST /api/proyectos/{pid}/generar`), no encadenada desde aquí: encadenar en
   el navegador se rompe al recargar la página, justo en un flujo pensado para
   dejarlo generando y mirarlo desde el móvil. */
async function lanzarTandaLight(tanda, modo) {
  const v = APP.light.video;
  if (!v.pid) return;
  limpiarError(CLAVE_VIDEO_LIGHT);
  try {
    const datos = await pedir(`${API.proyecto(v.pid)}/generar`, {
      method: 'POST',
      cuerpo: { tanda, modo: modo || 'pendientes' },
    });
    v.plan = datos.plan || null;
    const tid = datos.trabajo_id || (datos.trabajo || {}).id;
    if (!tid) throw new Error('el servidor no ha devuelto ningún trabajo');
    // DE QUE TRABAJO ES ESE PREVISTO. La misma ranura la ocupan tambien las
    // regeneraciones de un plano suelto (`soltarCola`), y sin esto la cuenta
    // atras de una imagen se pintaba con el previsto de la ultima tanda.
    v.planDe = tid;
    if (tanda === 'video') v.planos = [];
    seguirTrabajo(CLAVE_VIDEO_LIGHT, tid, async trabajo => {
      if (trabajo.estado === 'listo') {
        await cargarVideoLight(v.pid);
        // LA TANDA DE VIDEO YA NO ACABA EN EL MP4, acaba en el
        // previsualizador: es la parada nueva y es lo que hay que mirar antes
        // de gastar el render (ver TANDAS_LIGHT en app.py).
        if (tanda === 'video') { PREVIA.ficha = null; v.vista = 'previa'; }
        else if (tanda === 'render') v.vista = 'video';
        // regenerado desde el encargo, lo que toca mirar es el guion nuevo;
        // desde cualquier otra pantalla no se mueve a nadie
        else if (tanda === 'guion' && v.vista === 'encargo_video') v.vista = 'guion';
      }
      pintarLight();
    }, () => {
      // lo que se está produciendo se ve mientras se produce, PERO SIN REHACER
      // LA PANTALLA: en un tic solo cambia el progreso, y repintarlo todo
      // doscientas veces es lo que hacía parpadear los textos y comerse las
      // teclas (ver `refrescarVivosLight`).
      if (tanda === 'video') refrescarPlanosLight();
      refrescarVivosLight();
    });
    pintarLight();
  } catch (err) {
    mostrarError(CLAVE_VIDEO_LIGHT, err);
    pintarLight();
  }
}

/* Los planos que hay generados AHORA. Es la única señal que existe mientras la
   tanda corre: las unidades no se sellan hasta que el paso termina. */
async function refrescarPlanosLight() {
  const v = APP.light.video;
  if (!v.pid || v.pidiendoPlanos) return;
  v.pidiendoPlanos = true;
  try {
    // LIGERO: de cada plano aquí solo se miran `id`, `ruta` y `sello`. Pedirlo
    // entero traía además el prompt de los 232, 3,88 MB por vuelta, y esto se
    // pregunta una vez por imagen generada: unos 900 MB por tanda para acabar
    // comparando `planos.length`.
    const datos = await pedir(API.planosHechos(v.pid, true));
    /* Llega como {S001: {ruta, sello, ...}} y se filtra por el PLAN de ahora:
       la carpeta de trabajo conserva lo de pasadas anteriores —es lo que
       permite retomar una tanda cortada— así que ahí hay PNG de planos que este
       vídeo ya no tiene. Sin filtrar, el marco enseñaba «S105» en un vídeo cuyo
       último plano es el S098.

       Y se ordena por CUÁNDO se escribió, que es el orden en que se están
       generando: así el grande del marco es el que acaba de salir. */
    const delPlan = new Set(datos.plan || []);
    const planos = Object.entries(datos.planos || {})
      .filter(([id]) => !delPlan.size || delPlan.has(id))
      .map(([id, ficha]) => Object.assign({ id }, ficha))
      .sort((a, b) => (a.sello || 0) - (b.sello || 0));
    if (planos.length !== v.planos.length) {
      v.planos = planos;
      /* SOLO LA PANTALLA DEL VIDEO LOS ENSENA (el plano grande y el «N
         planos»). Desde las diapositivas esto corre mientras se aplican las
         notas, y repintar ahi por cada imagen nueva se llevaba por delante lo
         que estuvieras escribiendo sin cambiar nada de lo que se ve. */
      if (v.vista === 'video') pintarLight(); else refrescarVivosLight();
    }
  } catch (e) { /* mientras corre, un fallo puntual no es noticia */ }
  v.pidiendoPlanos = false;
}

function trabajoVideoLight() {
  const trabajo = APP.trabajos[CLAVE_VIDEO_LIGHT] || {};
  return trabajo.estado === 'ejecutando' ? trabajo : null;
}

/* La barra: a la derecha del botón y ocupando el resto de la franja. Dice por
   dónde va y cuánto queda, con el tiempo REAL medido de esta máquina.

   Y lo dice EN PÚBLICO (`avancePublico`): el desglose sigue entero —el tanto
   por ciento, qué tarea de cuántas y en qué anda esa tarea— pero contado sin
   enseñar cómo está hecho el Estudio. Esta pantalla se graba. */
/* ¿Queda algo por hacer en esta tanda? `null` mientras no se sabe: con eso el
   boton se deja como estaba en vez de parpadear de apagado a encendido cada vez
   que se repinta antes de que conteste el servidor. */
function quedaTandaLight(tanda) {
  const plan = (APP.light.video.planes || {})[tanda];
  return plan ? Number(plan.tareas) > 0 : null;
}


/* LA BARRA ES SOLO PROGRESO, y solo mientras algo corre.

   Llevaba tambien la frase del plan --«al dia: no queda nada por generar»-- al
   lado de cada boton, y con dos botones en la barra eso eran dos frases
   repetidas ocupando el sitio del progreso. La frase se fue al tooltip del
   boton, que es donde se pregunta «que va a hacer esto»; aqui queda lo que solo
   se puede ver mientras pasa.

   `tanda` se sigue pidiendo para refrescar su plan de fondo: es el mismo
   momento en el que hace falta y ahorra un sondeo aparte. */
function barraTandaLight(tanda) {
  // VIVA: es lo unico que cambia entre tic y tic, asi que se refresca sola sin
  // volver a pintar la pantalla entera (ver `enVivo`).
  return enVivo(() => barraTandaLightAhora(tanda));
}

function barraTandaLightAhora(tanda) {
  const trabajo = APP.trabajos[CLAVE_VIDEO_LIGHT] || {};
  const corriendo = trabajo.estado === 'ejecutando';
  if (!corriendo) {
    if (tanda) refrescarPlanLight(tanda);
    return null;
  }
  const avance = Math.max(0, Math.min(1, Number(trabajo.progreso) || 0));
  const relleno = h('div', { clase: 'relleno' });
  relleno.style.width = `${(avance * 100).toFixed(1)}%`;
  return h('div', { clase: 'barra-light' },
    h('div', { clase: 'carril' }, relleno),
    h('div', { clase: 'meta' },
      [`${Math.round(avance * 100)} %`, avancePublico(trabajo),
       restanteTandaLight(trabajo, avance)].filter(Boolean).join(' · ')));
}

/* Lo que falta, con los tiempos MEDIDOS de esta máquina.

   Sale de `previsto - transcurrido` y NO de proyectar la fracción, y la
   diferencia importa: una tanda mezcla tareas que avanzan por unidades reales
   —216 planos dibujados uno a uno— con llamadas al CLI, que son opacas hasta
   que contestan y cuya "fracción" es un reloj sintético. Proyectar el ritmo
   reciente sobre lo que queda daría una cifra que salta cada vez que se cambia
   de tarea. El previsto del plan ya viene repartido por tarea desde el
   historial de esta máquina (`_segundos_de_tarea`), que es la única medida que
   cubre la mezcla entera.

   Se calla cuando se pasa del previsto: decir "quedan 0 s" durante diez minutos
   es peor que no decir nada. */
function restanteTandaLight(trabajo, avance) {
  const v = APP.light.video;
  // EL PREVISTO TIENE QUE SER EL DE ESTE TRABAJO. Por esta misma ranura pasan
  // las tandas y las regeneraciones de un plano suelto, y contar hacia atras
  // desde el previsto de otra cosa es peor que no decir nada.
  if (!v.planDe || v.planDe !== trabajo.id) return '';
  const previsto = Number((v.plan || {}).segundos) || 0;
  if (!previsto || !trabajo.inicio || avance >= 1) return '';
  const restante = previsto - (Date.now() - trabajo.inicio) / 1000;
  return restante > 5 ? `quedan ~${duracionCorta(restante)}` : '';
}

/* Lo que va a hacer la próxima tanda: cuántas tareas, cuánto tarda y cuánto
   cuesta. Lo dice el servidor (`GET .../generar`), que NO lanza nada: una cifra
   inventada en la pantalla y otra distinta durante la generación serían dos
   mentiras, y la segunda tardando diez minutos en descubrirse. */
/* LO QUE VA A HACER UNA TANDA, EN UNA FRASE.
 *
 * Estaba dentro de `refrescarPlanLight`, que lo escribia en un nodo del DOM.
 * Ahora lo piden dos sitios --el tooltip del boton y la barra mientras corre--
 * y una frase que se arma en dos lados se separa en cuanto alguien toque una:
 * la de la barra diria «3 tareas» y la del tooltip «tres tareas». Se arma aqui
 * y se reparte. */
function textoDelPlan(tanda) {
  const plan = (APP.light.video.planes || {})[tanda];
  if (!plan) return '';
  if (!plan.tareas) return 'al día: no queda nada por generar';
  const coste = plan.coste || {};
  const partes = [`${plan.tareas} ${plan.tareas === 1 ? 'tarea' : 'tareas'}`];
  if (plan.segundos) partes.push(`~${duracionCorta(plan.segundos)}`);
  /* LO QUE YA ESTA HECHO, DELANTE DEL PRECIO. Una tanda cortada en el plano
     211 de 216 se volvia a ofrecer como «216 imagenes · 7,13 $», que es lo que
     cuesta el video entero y no lo que falta: con esa cifra delante, lo
     razonable es no pulsar. Se ensenan los dos numeros porque los dos son
     verdad -- lo probable y el techo si algo aguas arriba cambia y la cache
     del banco falla. */
  if (coste.imagenes) {
    partes.push(coste.imagenes_hechas
      ? `${coste.imagenes_por_generar} imágenes (${coste.imagenes_hechas} ya hechas)`
      : `${coste.imagenes} imágenes`);
  }
  if (coste.usd_total) {
    partes.push(coste.imagenes_hechas
      ? `≈ ${Number(coste.usd_por_generar).toFixed(2)} $ · hasta ${Number(coste.usd_total).toFixed(2)} $ si hay que rehacerlas`
      : `≈ ${Number(coste.usd_total).toFixed(2)} $`);
  }
  return partes.join(' · ');
}


/* SOLO PIDE Y GUARDA. Antes ademas escribia la frase en un nodo del DOM que le
   pasaban; ahora la frase la arma `textoDelPlan` a partir de lo guardado, y
   quien la quiera se la pide. */
//: Cada cuanto se vuelve a preguntar por el plan de una tanda. Esto se llama
//: DESDE EL PINTADO, y la pantalla se repinta sola cada segundo y medio: sin
//: freno serian dos peticiones por repintado para contestar lo mismo.
const PLANES_LIGHT = { ultima: {} };


async function refrescarPlanLight(tanda, forzar) {
  const v = APP.light.video;
  if (!v.pid || !tanda) return;
  const clave = `${v.pid}:${tanda}`;
  if (!forzar && Date.now() - (PLANES_LIGHT.ultima[clave] || 0) < 3000) return;
  PLANES_LIGHT.ultima[clave] = Date.now();
  try {
    const plan = await pedir(`${API.proyecto(v.pid)}/generar?tanda=${tanda}`);
    /* Se repinta SOLO si el numero de tareas ha cambiado: repintar siempre
       desde aqui seria un bucle, porque esto se llama durante el pintado. */
    const antes = (v.planes[tanda] || {}).tareas;
    v.planes[tanda] = plan;
    if (antes !== plan.tareas) setTimeout(pintarLight, 0);
  } catch (e) { /* sin plan: los botones se quedan como estaban */ }
}

/* ------------------------------------------------- lo que llevamos gastado
 *
 * EL MISMO MEDIDOR QUE LA CABECERA DEL MODO EDITOR, y comparte hasta el CSS a
 * proposito: son la misma cifra del mismo vídeo mirada desde dos pantallas, y
 * dos maquetaciones distintas es la forma de que una se quede vieja.
 *
 * No estima nada: cada motor reporta lo que consumio (`nucleo/coste`) y aqui
 * solo se pinta. Claude va aparte y sin importe porque va contra la
 * suscripcion, y un dolar inventado ahi seria peor que un hueco.
 *
 * El desglose por paso NO esta aqui. Esta pantalla es de tres paradas: lo que
 * hace falta mientras generas es saber cuanto llevas, y en que se ha ido se
 * mira en el modo editor, que es donde ya vive esa tabla.
 */

const COSTE_LIGHT = { ultima: 0, cita: null, pid: '' };

function refrescarCosteLight(forzar) {
  const v = APP.light.video;
  if (!v.pid) return;
  const corriendo = (APP.trabajos[CLAVE_VIDEO_LIGHT] || {}).estado === 'ejecutando';
  const mismo = COSTE_LIGHT.pid === v.pid;
  // YA SE SABE Y NO ESTA PASANDO NADA: no hay nada nuevo que preguntar. Sin
  // esta linea el bucle se cierra solo -- se pinta, se pide, la respuesta
  // repinta, y el repintado vuelve a pedir -- y la pantalla quieta estaria
  // haciendo una peticion cada segundo y medio para siempre.
  if (!forzar && mismo && v.coste && !corriendo) return;
  // Y mientras SI pasa algo, con freno: el progreso late muchas veces por
  // segundo y esto se pinta en cada latido.
  if (!forzar && mismo && Date.now() - COSTE_LIGHT.ultima < 1500) {
    if (!COSTE_LIGHT.cita) {
      COSTE_LIGHT.cita = setTimeout(() => {
        COSTE_LIGHT.cita = null;
        refrescarCosteLight(true);
      }, 1500);
    }
    return;
  }
  COSTE_LIGHT.ultima = Date.now();
  COSTE_LIGHT.pid = v.pid;
  const pid = v.pid;
  pedir(API.coste(pid))
    .then(datos => {
      if (APP.light.video.pid !== pid) return;
      APP.light.video.coste = datos;
      refrescarVivosLight();
    })
    .catch(() => { /* no poder leer el coste no puede tumbar la pantalla */ });
}

/* La pastilla de la cabecera. Se pinta con lo ultimo que se sabe y pide lo
   siguiente, asi que nunca se queda en blanco esperando una respuesta. */
function costeLight() {
  // VIVA por lo mismo que la barra: mientras se gasta, la cifra se mueve sola
  // y el resto de la cabecera no tiene por que rehacerse con ella.
  return enVivo(costeLightAhora);
}

function costeLightAhora() {
  refrescarCosteLight();
  const datos = APP.light.video.coste;
  const caja = h('span', {
    clase: 'coste-light' + (datos && datos.aviso_presupuesto ? ' aviso' : ''),
    title: 'Lo que llevas gastado en este vídeo. El desglose por paso está en '
      + 'el modo editor.',
  });
  if (!datos) { caja.appendChild(h('span', { clase: 'meta' }, 'coste: —')); return caja; }
  const abierto = proveedorDe(datos, 'openai');
  const voz = proveedorDe(datos, 'tts');
  const cli = proveedorDe(datos, 'claude_cli');
  caja.appendChild(h('span', { clase: 'prov' }, h('b', {}, 'Imágenes'),
    importeCoste(abierto, true),
    // el recuento solo cuando hay alguna: un «0» al lado del hueco se lee como
    // «cero dolares» en vez de «todavia ninguna»
    abierto.cantidad.imagenes
      ? h('span', { clase: 'meta' }, `${corto(abierto.cantidad.imagenes)}`)
      : null));
  caja.appendChild(h('span', { clase: 'prov' }, h('b', {}, 'Voz'),
    importeCoste(voz, true)));
  // Claude va sin importe y no entra en el TOTAL
  caja.appendChild(h('span', { clase: 'prov' }, h('b', {}, 'Claude'),
    h('span', { clase: 'meta', title: 'va contra la suscripción: no suma al total' },
      `${corto(cli.tokens.total)} tok`)));
  caja.appendChild(h('span', { clase: 'prov total' }, h('b', {}, 'Total'),
    h('span', { clase: 'usd' }, `$${Number(datos.total_usd || 0).toFixed(2)}`)));
  if (datos.presupuesto_usd) {
    const fraccion = Math.min(1, Number(datos.fraccion_presupuesto) || 0);
    caja.appendChild(h('span', {
      clase: 'presupuesto' + (datos.aviso_presupuesto ? ' aviso' : ''),
      title: `presupuesto ${datos.presupuesto_usd} $ · consumido ${Math.round(fraccion * 100)}%`,
    }, h('i', { estilo: `width:${(fraccion * 100).toFixed(0)}%` })));
  }
  return caja;
}

/* --------------------------------------------------------------- el guion */

function vistaGuionLight() {
  const v = APP.light.video;
  const caja = h('div', { clase: 'light-guion' });
  caja.appendChild(h('div', { clase: 'light-cab' },
    h('h2', {}, (v.guion || {}).titulo || v.nombre || 'El guion'),
    h('span', { clase: 'meta' }, v.guion
      ? `${v.guion.bloques.length} bloques · ${miles(v.guion.palabras)} palabras`
      : ''),
    h('span', { clase: 'crece' }),
    costeLight()));

  const error = ERRORES[CLAVE_VIDEO_LIGHT];
  if (error) caja.appendChild(cajaError(error));

  if (!v.guion) {
    const corriendo = !!trabajoVideoLight();
    caja.appendChild(h('div', { clase: 'caja-info' },
      corriendo
        ? 'Reuniendo el material y escribiendo el guion. Puedes cerrar esto: '
          + 'sigue corriendo en el servidor.'
        : 'Todavía no hay guion. Se genera desde el encargo, que es donde está '
          + 'lo que se le pide al redactor. ',
      /* Sin guion y sin nada corriendo --la tanda se cayó, o se paró-- esta
         pantalla no tenía ningún camino: el pie ofrece el audio, que sin guion
         no se puede. El camino es el encargo. */
      corriendo ? null : h('button', {
        clase: 'mini', onclick: () => { v.vista = 'encargo_video'; pintarLight(); },
      }, 'Ir al encargo')));
    BARRA_INFERIOR.nodo = pieLight();
    return caja;
  }

  (v.guion.avisos || []).slice(0, 6).forEach(aviso => {
    caja.appendChild(h('div', { clase: 'caja-aviso' }, aviso));
  });

  // EL REPRODUCTOR VIVE EN LA BARRA DE ABAJO (ver `pieLight`). Estaba arriba
  // del guion para que los mandos no se fueran con el scroll; la barra fija lo
  // cumple mejor -- no se va nunca -- y de paso el texto empieza donde toca.

  /* EL PLAN DE LA VOZ, ANTES DE PINTAR LOS BLOQUES. Cada bloque pregunta si
     sus cambios ya estan grabados (`bloqueEditadoLight`), y eso sale del plan
     de la tanda de voz. Pedirlo despues --lo pide el pie, que va al final--
     hacia que la PRIMERA pasada los marcara todos «editado» y solo se
     corrigiera al repintar. Va con freno, asi que no es una peticion mas. */
  refrescarPlanLight('voz');
  caja.appendChild(promptGeneralLight());
  caja.appendChild(bloquesLight());
  BARRA_INFERIOR.nodo = pieLight();
  return caja;
}

/* EL PROMPT GENERAL: una frase que reescribe el guion entero. Con audio hecho
   además lo regraba, y por eso el botón lo dice: es la misma regla que los
   bloques, «rehacer una cosa rehace ESA cosa» con su precio delante. */
function promptGeneralLight() {
  const v = APP.light.video;
  const area = h('textarea', {
    rows: 2, placeholder: 'Qué cambiarías del guion entero: «más directo», '
      + '«quita los tecnicismos», «empieza por el robo»…',
    oninput: ev => { v.promptGeneral = ev.target.value; },
  });
  area.value = v.promptGeneral || '';
  return h('div', { clase: 'prompt-general' },
    cajaCampo(area, { clase: 'area' }),
    h('div', { clase: 'fila' },
      h('button', {
        clase: 'mini', disabled: !!trabajoVideoLight(),
        onclick: () => reescribirGuionLight(),
      }, v.audio ? 'Regenerar el guion y el audio' : 'Regenerar el guion'),
      h('span', { clase: 'meta' }, v.audio
        ? 'vuelve a redactar y a grabar la toma entera'
        : 'vuelve a redactar con esa instrucción delante')));
}

async function reescribirGuionLight() {
  const v = APP.light.video;
  const texto = String(v.promptGeneral || '').trim();
  if (!texto) { toast('escribe qué cambiarías', true); return; }
  try {
    await pedir(API.params(v.pid, 'guion'), {
      method: 'PUT', cuerpo: { params: { prompt_general: texto } },
    });
    v.promptGeneral = '';
    // 'pendientes' y no 'todo': REHACER UNA COSA REHACE ESA COSA. Escribir el
    // prompt general deja el guion obsoleto —es un param suyo—, así que ya
    // entra; el material sigue al día y se salta. Con 'todo'
    // esto volvería a salir a internet seis minutos para reescribir una frase.
    await lanzarTandaLight('guion', 'pendientes');
  } catch (err) { toast(`no se ha podido: ${err.message}`, true); }
}

/* LOS BLOQUES. Cada uno se edita a mano en su sitio (autoguardado: editar es
   decidir) y lleva su caja de prompt plegada. Sin audio son los bloques del
   guion; con audio se agrupan por SECCIÓN, que es la unidad que se regraba
   —para el usuario eso no se dice: los botones hablan de «este bloque». */
function bloquesLight() {
  const v = APP.light.video;
  const lista = h('div', { clase: 'bloques-light' });
  const porBloque = {};
  for (const bloque of ((v.audio || {}).bloques || [])) porBloque[bloque.id] = bloque;
  const seccionDe = {};
  for (const sec of ((v.audio || {}).secciones || [])) {
    for (const bid of (sec.bloques || [])) seccionDe[bid] = sec;
  }

  for (const bloque of v.guion.bloques) {
    const texto = textoDeBloqueLight(bloque);
    const conAudio = porBloque[bloque.id];
    const ficha = h('div', {
      clase: 'parrafo-guion'
        + (bloqueEditadoLight(bloque) ? ' tocado' : ''),
      datos: { bloque: bloque.id },
    });
    /* CON AUDIO EL TEXTO SE LEE, PERO SIGUE SIENDO EDITABLE.
       Son dos vistas del mismo dato y no un capricho: una palabra pulsable
       tiene que ser un nodo propio y un <textarea> no tiene nodos dentro. Así
       que con toma hecha el bloque se pinta palabra a palabra —para el karaoke—
       y «Editar a mano» lo cambia a un área para ese bloque y solo ese. */
    const editando = v.editando === bloque.id;
    const hayAudio = !!(conAudio && (conAudio.palabras || []).length);
    ficha.appendChild(h('div', { clase: 'cabecera' },
      h('span', { clase: 'id' }, bloque.id),
      bloqueEditadoLight(bloque) ? h('span', { clase: 'pastilla tocado' }, 'editado') : null,
      h('span', { clase: 'crece' }),
      hayAudio ? h('button', {
        clase: 'mini fantasma',
        onclick: () => {
          v.editando = editando ? '' : bloque.id;
          pintarLight();
        },
      }, editando ? 'Hecho' : 'Editar a mano') : null,
      h('button', {
        clase: 'mini fantasma',
        onclick: () => {
          v.abierto = v.abierto === bloque.id ? '' : bloque.id;
          pintarLight();
        },
      }, v.abierto === bloque.id ? 'Cerrar' : 'Cambiar con una frase')));

    if (hayAudio && !editando) {
      ficha.appendChild(parrafoKaraokeLight(bloque, conAudio, texto));
    } else {
      const visible = textoVisibleLight(texto);
      const area = h('textarea', {
        rows: Math.max(2, Math.ceil(visible.length / 90)),
        clase: 'texto-bloque',
        oninput: ev => guardarBloqueLight(bloque.id, ev.target.value, texto),
      });
      area.value = visible;
      ficha.appendChild(area);
    }

    if (v.abierto === bloque.id) ficha.appendChild(mandosBloqueLight(bloque, seccionDe));
    lista.appendChild(ficha);
  }
  return lista;
}

/* Lo que se LEE de un bloque: su texto sin las anotaciones del TTS.
 *
 * Se parte del texto YA LIMPIO y no de los tokens crudos, y eso resuelve dos
 * cosas a la vez. La primera es un fallo que se vio en un vídeo montado:
 * saltarse los tokens que llevan ángulos se comía la palabra pegada a ellos
 * —«all you want.<break time="900ms"/>» desaparecía entero— y el guion salía con
 * frases cortadas. La segunda es que así las palabras que se pintan son
 * EXACTAMENTE las que cuenta `palabrasDe`, que es como se repartieron las marcas
 * de tiempo de la toma: contar de otra forma desplaza el karaoke desde ahí. */
function textoVisibleLight(texto) {
  return sinMarcasTts(texto).replace(/\s+/g, ' ').trim();
}

/* El párrafo con sus palabras pulsables: mover el audio pinchando en el texto
   es lo que convierte el guion en el mando del reproductor. Es el mismo
   mecanismo que el repaso del modo editor (`panelRevision`), con una
   diferencia: aquí las anotaciones del TTS NO se pintan. */
function parrafoKaraokeLight(bloque, conAudio, texto) {
  const marcas = conAudio.palabras || [];
  const parrafo = h('p', { clase: 'texto-bloque karaoke', datos: { bloque: bloque.id } });
  const palabras = textoVisibleLight(conAudio.texto || texto).match(/\S+/g) || [];
  palabras.forEach((palabra, indice) => {
    const marca = marcas[indice];
    parrafo.appendChild(h('span', {
      clase: 'palabra',
      datos: { s: marca ? String(marca.s) : '', e: marca ? String(marca.e) : '' },
      onclick: ev => {
        const s = Number(ev.target.dataset.s);
        const audio = $('#panel').querySelector('audio.light');
        if (audio && s >= 0) { audio.currentTime = s; audio.play(); }
      },
    }, palabra));
    parrafo.appendChild(document.createTextNode(' '));
  });
  return parrafo;
}

/* Guardar un bloque editado a mano. AUTOGUARDADO y sin confirmar: editar es
   decidir. Va a `params.guion.bloques`, que es el mismo cajón que usa el modo
   editor y el que `p4_voz` aplica al grabar — así una corrección a mano llega
   al audio sin volver a pedirle el guion entero al modelo. */
let _guardadoBloqueLight = null;
function guardarBloqueLight(bid, texto, original) {
  const v = APP.light.video;
  const ficha = v.fichas.guion || {};
  ficha.params = ficha.params || {};
  ficha.params.bloques = ficha.params.bloques || {};
  /* SI NO HA CAMBIADO NADA, NO SE GUARDA NADA. Lo que se enseña es el texto sin
     las anotaciones del TTS, así que guardarlo tal cual por haber puesto el
     cursor encima le quitaría sus pausas a un bloque que nadie ha tocado. Si de
     verdad se edita sí se pierden, y eso es lo que se pidió: una frase
     reescrita ya no tiene las pausas donde las tenía. */
  if (original !== undefined && texto === textoVisibleLight(original)) {
    delete ficha.params.bloques[bid];
  } else {
    ficha.params.bloques[bid] = { texto };
  }
  clearTimeout(_guardadoBloqueLight);
  _guardadoBloqueLight = setTimeout(async () => {
    try {
      await pedir(API.params(v.pid, 'guion'), {
        method: 'PUT', cuerpo: { params: { bloques: ficha.params.bloques } },
      });
    } catch (err) { toast(`no se ha podido guardar: ${err.message}`, true); }
  }, 700);
}

/* Los mandos de un bloque. Los DOS verbos de la casa, y el botón dice qué
   rehace: con audio, cambiar un bloque rehace su audio también, y eso se dice
   antes de pulsar. */
function mandosBloqueLight(bloque, seccionDe) {
  const v = APP.light.video;
  const sec = seccionDe[bloque.id];
  const area = h('textarea', {
    rows: 2, placeholder: '«se traba en “on record”, cambia esa frase», «suena '
      + 'plano, dale más aire», «di la cifra en cifra»…',
    oninput: ev => { v.prompts[bloque.id] = ev.target.value; },
  });
  area.value = v.prompts[bloque.id] || '';
  const tocado = bloqueEditadoLight(bloque);
  return h('div', { clase: 'mandos-bloque' },
    cajaCampo(area, { clase: 'area' }),
    h('div', { clase: 'fila' },
      h('button', {
        clase: 'mini', disabled: !!trabajoVideoLight(),
        onclick: () => cambiarBloqueLight(bloque, sec),
      }, v.audio ? 'Regenerar bloque y audio' : 'Regenerar bloque'),
      h('span', { clase: 'meta' }, v.audio
        ? (sec ? 'reescribe la frase y vuelve a grabar solo este tramo'
          : 'reescribe la frase y vuelve a grabar')
        : 'reescribe este bloque cambiando lo mínimo')),
    /* Y SIN PEDIR NADA, cuando ya lo has escrito tú. Editar a mano deja el
       audio de ese bloque diciendo la frase vieja; esto vuelve a grabar SU
       tramo con lo que hayas escrito, sin pasar por el modelo. */
    (v.audio && sec && tocado) ? h('div', { clase: 'fila' },
      h('button', {
        clase: 'mini', disabled: !!trabajoVideoLight(),
        onclick: () => cambiarBloqueLight(bloque, sec, true),
      }, 'Solo regrabar lo que he escrito'),
      h('span', { clase: 'meta' },
        'graba este tramo con tu texto, sin reescribirlo')) : null);
}

async function cambiarBloqueLight(bloque, sec, soloGrabar) {
  const v = APP.light.video;
  const peticion = soloGrabar ? '' : String(v.prompts[bloque.id] || '').trim();
  if (!peticion && !soloGrabar) {
    toast('escribe qué cambiarías de este bloque', true);
    return;
  }
  limpiarError(CLAVE_VIDEO_LIGHT);
  try {
    /* EL MISMO GESTO, DOS CAMINOS, y lo que los separa es si hay toma: sin
       audio se reescribe el bloque y ya; con audio se reescribe Y se regraba su
       tramo. Por dentro el que reescribe es el mismo (`p4_voz.reescribir_bloques`),
       así que el prompt no puede quedarse viejo en uno de los dos. */
    const datos = (!v.audio || !sec)
      ? await pedir(`${API.proyecto(v.pid)}/guion/bloques/reescribir`, {
        method: 'POST', cuerpo: { bloque: bloque.id, peticion },
      })
      : await pedir(API.regrabarSeccion(v.pid, sec.id), {
        method: 'POST', cuerpo: { peticion },
      });
    v.editando = '';
    const tid = datos.trabajo_id || (datos.trabajo || {}).id;
    if (!tid) throw new Error('el servidor no ha devuelto ningún trabajo');
    v.prompts[bloque.id] = '';
    seguirTrabajo(CLAVE_VIDEO_LIGHT, tid, async trabajo => {
      if (trabajo.estado === 'listo') await cargarVideoLight(v.pid);
      pintarLight();
    });
    pintarLight();
  } catch (err) { mostrarError(CLAVE_VIDEO_LIGHT, err); pintarLight(); }
}

/* EL REPRODUCTOR. Barra propia y ×1..×5 en un desplegable: revisar una toma de
   nueve minutos a velocidad normal es nueve minutos, y lo que se busca aquí es
   pillar el sitio donde suena mal. */
/* EL MISMO ELEMENTO ENTRE REPINTADOS. Un <audio> nuevo empieza en cero, y aquí
   se repinta por cosas que pasan MIENTRAS escuchas —abrir la caja de un bloque,
   que llegue un aviso—: crear otro paraba la escucha y te devolvía al principio
   de una toma de cinco minutos. Se reutiliza mientras suene lo mismo. */
let _audioLight = null;

function reproductorLight() {
  const v = APP.light.video;
  if (!_audioLight || _audioLight.dataset.src !== v.audio.url) {
    _audioLight = registrarReproductor(h('audio', {
      clase: 'light', controls: true, preload: 'metadata', src: v.audio.url,
      datos: { src: v.audio.url },
    }));
  }
  const audio = _audioLight;
  audio.playbackRate = v.velocidad || 1;
  const velocidad = h('select', {
    clase: 'velocidad',
    onchange: ev => {
      v.velocidad = Number(ev.target.value);
      audio.playbackRate = v.velocidad;
    },
  }, ...[1, 2, 3, 4, 5].map(n => h('option', {
    value: String(n), selected: (v.velocidad || 1) === n,
  }, `×${n}`)));

  // El karaoke: lo ya leído a plena luz y lo que falta atenuado, y la palabra
  // que suena marcada. Se mueve solo el TRAMO que cambia — con repintado
  // completo el navegador se arrastra en un guion largo.
  let sonando = null, hasta = -1;
  const enganchar = () => {
    const marcadas = [...$('#panel').querySelectorAll('.bloques-light .palabra')]
      .filter(s => s.dataset.s !== '');
    const alInstante = t => {
      let indice = -1;
      for (let i = 0; i < marcadas.length; i++) {
        if (Number(marcadas[i].dataset.s) <= t) indice = i; else break;
      }
      return indice;
    };
    const pintarAvance = () => {
      const indice = alInstante(audio.currentTime);
      if (indice !== hasta) {
        const desde = Math.min(hasta, indice) + 1;
        const hastaAqui = Math.max(hasta, indice);
        for (let i = desde; i <= hastaAqui; i++) {
          if (marcadas[i]) marcadas[i].classList.toggle('leida', i <= indice);
        }
        hasta = indice;
      }
      const candidata = indice >= 0 ? marcadas[indice] : null;
      if (candidata === sonando) return;
      if (sonando) sonando.classList.remove('sonando');
      if (candidata) candidata.classList.add('sonando');
      sonando = candidata;
    };
    // el elemento se reutiliza entre repintados, así que sus oyentes también:
    // sin soltar el anterior se acumularían uno por repintado y cada tic
    // recorrería el guion tantas veces como veces se hubiera pintado
    if (audio._karaoke) {
      audio.removeEventListener('timeupdate', audio._karaoke);
      audio.removeEventListener('seeked', audio._karaoke);
    }
    audio._karaoke = pintarAvance;
    audio.addEventListener('timeupdate', pintarAvance);
    audio.addEventListener('seeked', pintarAvance);
    pintarAvance();          // al repintar, lo ya leído vuelve a su sitio
  };
  // el guion se pinta DESPUÉS que esto, así que las palabras todavía no están
  setTimeout(enganchar, 0);

  return h('div', { clase: 'reproductor-light' },
    audio, velocidad,
    h('span', { clase: 'meta' },
      `${mmss(v.audio.duracion)}`
      + (v.audio.obsoleto ? ' · la toma no corresponde al guion de ahora' : '')));
}

/* EL PIE. «Generar Audio» a la izquierda del todo y la barra ocupando el resto;
   «Generar Vídeo» a la derecha, desbloqueado en cuanto hay audio completo.
   Y debajo de la barra, LO QUE VA A HACER Y LO QUE CUESTA — dicho antes de
   pulsar, que es la única forma de que sirva (lo sucio se
   acciona con su cuenta y su precio delante). */
/* LA AYUDA DE CADA BOTON ES CONTEXTUAL Y VIVE EN UN TOOLTIP.
 *
 * Estaba escrita a pie de barra, siempre visible y siempre la misma: ocupaba
 * cuatro renglones y contaba lo que pasa cuando hay algo que hacer aunque no
 * hubiera nada. Un texto que no cambia con el estado se deja de leer al tercer
 * dia, y entonces ya no explica nada.
 *
 * Ahora cada boton lleva la suya en `data-ayuda` y sale al pasar por encima
 * medio segundo (el retardo lo pone el CSS). Y dice DOS cosas distintas segun
 * quede trabajo o no: con algo pendiente, que va a hacer y que cuesta; al dia,
 * por que no hay nada que pulsar. */
/* UN BOTON APAGADO NO RECIBE EVENTOS DE RATON, asi que su `:hover` no dispara
   y el cartel no saldria justo donde mas falta hace -- «por que no puedo
   pulsar esto». Se envuelve: el `:hover` va en el envoltorio, que si los
   recibe, y el boton se queda dentro tal cual. */
/* LA AYUDA Y EL PLAN, EN UN SOLO CARTEL Y SIN DECIR DOS VECES LO MISMO.
   Cuando no queda nada por hacer, la ayuda YA lo explica («el audio ya recoge
   todo lo que has escrito») y el plan lo repetiria con otras palabras («al dia:
   no queda nada por generar»). Ahi se calla el plan. Cuando si queda, el plan
   es lo que no se puede deducir --cuantas tareas, cuanto tarda, cuanto cuesta--
   y va detras. */
function unirAyuda(ayuda, plan) {
  if (!plan || /^al día/.test(plan)) return ayuda;
  return `${ayuda}

→ ${plan}`;
}


function conAyuda(texto, boton) {
  if (!boton) return null;
  if (!texto) return boton;
  return h('span', { clase: 'ayuda-de', 'data-ayuda': texto }, boton);
}


function ayudaAudio(hayAudio, queda) {
  if (queda === false) {
    return 'El audio ya recoge todo lo que has escrito, incluidas las '
      + 'ediciones a mano. No queda nada que grabar.';
  }
  return hayAudio
    ? 'Vuelve a grabar la toma con la voz del estilo. Se sintetiza el texto de '
      + 'ahora; lo que no haya cambiado sale de la cache y no se vuelve a pagar.'
    : 'Sintetiza la toma completa con la voz del estilo y la alinea con el '
      + 'texto, que es lo que despues coloca los subtitulos.';
}


function ayudaDiapositivas(hayVideo, obsoleto, queda) {
  if (queda === false) {
    return 'Las diapositivas ya recogen el guion y el audio de ahora. Para '
      + 'verlas, «Diapositivas» en la barra de abajo: no cuesta nada.';
  }
  if (hayVideo && obsoleto) {
    return 'Vuelve a partir los subtitulos con los tiempos del audio de ahora y '
      + 'redibuja las capas de los planos afectados. Una imagen solo se vuelve '
      + 'a pagar si el cambio altera su prompt; cambiar una palabra suelta no '
      + 'lo hace. No monta el MP4: eso es «Montar el video», despues de mirarlo.';
  }
  return 'Dibuja los planos, les monta los subtitulos y las cartelas y prepara '
    + 'la musica. Para ahi, en las diapositivas, para que lo mires antes de '
    + 'gastar el render: no monta ningun MP4.';
}


function pieLight() {
  const v = APP.light.video;
  const corriendo = !!trabajoVideoLight();
  /* Los dos botones necesitan saber si a SU tanda le queda algo, y quien lo
     pregunta era la barra de cada una. Ahora la barra es una sola, asi que el
     plan de la otra se pide aqui. Como efecto y no como hijo: es `async`, y
     ponerla en el arbol pintaba «[object Promise]» en mitad de la barra. */
  refrescarPlanLight('video');
  const hayGuion = !!v.guion;
  const hayAudio = !!v.audio;
  const hayVideo = hayMp4Light();
  const obsoleto = videoObsoletoLight();
  /* SE PIDEN LOS DOS PLANES SIEMPRE, no solo mientras algo corre.

     `quedaTandaLight` devuelve `null` mientras no se sabe, y el unico sitio que
     los pedia era la barra de progreso -- que solo se pinta si hay algo
     corriendo --. O sea que con la pantalla parada no se sabia nunca, y
     `bloqueEditadoLight` se quedaba marcando «editado» para siempre bloques que
     ya estaban grabados. Van con freno (`PLANES_LIGHT`), asi que llamarlas en
     cada repintado no son dos peticiones por segundo. */
  refrescarPlanLight('voz');
  refrescarPlanLight('video');
  const quedaVoz = quedaTandaLight('voz');
  const quedaVideo = quedaTandaLight('video');
  return h('div', { clase: 'pie-guion' },
    conAyuda(unirAyuda(ayudaAudio(hayAudio, quedaVoz), textoDelPlan('voz')),
      h('button', {
        clase: 'primario',
        disabled: corriendo || !hayGuion || quedaVoz === false,
        onclick: () => lanzarTandaLight('voz', hayAudio ? 'todo' : 'pendientes'),
      }, hayAudio ? 'Regenerar Audio' : 'Generar Audio')),
    /* EN MEDIO Y A TODO EL HUECO QUE SOBRE: es lo unico de la barra que cambia
       solo, y entre los dos botones se ve sin buscarla. Cuando no corre nada no
       se pinta y los botones se quedan uno a cada lado.

       Y ES UNA, NO DOS. Los dos botones comparten el mismo trabajo
       (`CLAVE_VIDEO_LIGHT`), asi que pintar la barra de cada tanda daba dos
       barras identicas avanzando a la vez. El plan de la otra tanda se sigue
       refrescando -- lo necesitan los botones para apagarse -- pero sin pintar
       nada. */
    /* EN MEDIO: mientras algo corre, el progreso; el resto del tiempo, el
       reproductor. Los dos ocupan el mismo hueco porque nunca hacen falta a la
       vez -- mientras se graba la toma, la que hay ya no es la que va a
       quedar. */
    /* UNO SOLO EN MEDIO, Y ES EL QUE CRECE. Iban dos `crece` vacios haciendo
       de cuna, asi que el hueco se repartia en tres y el reproductor se
       quedaba con su ancho de fabrica en el centro. Ahora crece el de en
       medio, y cuando no hay nada que poner ahi el hueco lo llena un `crece`
       vacio -- que es lo que deja los dos botones en los extremos. */
    corriendo ? barraTandaLight('voz')
      : (hayAudio ? reproductorLight() : h('span', { clase: 'crece' })),
    corriendo ? conAyuda(
      'Corta la tanda donde este. Lo que ya se ha generado se queda hecho y no '
      + 'hay que volver a pagarlo.',
      h('button', {
        clase: 'mini peligro', onclick: () => cancelar(CLAVE_VIDEO_LIGHT),
      }, 'Parar')) : null,
    conAyuda(!hayAudio
      ? 'Primero hace falta el audio: los subtitulos se colocan con sus '
        + 'tiempos, asi que sin voz no hay donde ponerlos.'
      : unirAyuda(ayudaDiapositivas(hayVideo, obsoleto, quedaVideo),
                  textoDelPlan('video')),
      h('button', {
        clase: 'primario',
        disabled: corriendo || !hayAudio || (hayVideo && !obsoleto)
                  || quedaVideo === false,
        onclick: () => lanzarTandaLight('video'),
      }, (hayVideo && obsoleto) ? 'Poner al día las imágenes'
         : 'Generar imágenes')),
    /* LA PASTILLA SOLO SI ESTE BOTON TIENE ALGO QUE HACER.
       Miraba el estado de los pasos y el boton mira el PLAN, y no son lo
       mismo: regenerar las capas deja el MP4 viejo --y eso es verdad-- pero la
       tanda de aqui no monta el MP4, asi que salia «Obsoleto» al lado de un
       boton apagado que decia «no queda nada por generar». Lo viejo era el
       MP4, y esa pastilla vive en la pantalla del video, que es donde se
       acciona. */
    quedaVideo === false ? null : pastillaObsoletoLight());
}

/* --------------------------------------------------------------- el vídeo */

/* UN RECTÁNGULO Y UNA BARRA. Por el rectángulo van pasando los planos según se
   generan —es el mismo sitio donde después se ve el vídeo montado, y eso es
   deliberado: lo que se mira mientras se genera y lo que se mira al terminar
   son la misma cosa en el mismo marco. */
/* ============================================ EL VÍDEO ABIERTO, EN LOS DOS MODOS
 *
 * El previsualizador, el repaso y la cola de imágenes se escribieron para el
 * modo light y leían `APP.light.video` y repintaban con `pintarLight()`. Desde
 * el 02-09 los usan también las pestañas Imágenes y Vídeo del editor
 * con el MISMO código: una segunda copia se habría separado
 * de la primera en cuanto alguien tocara una de las dos. Lo que cambia es de
 * dónde sale el vídeo abierto y cómo se repinta:
 *
 *   light    APP.light.video, y pintarLight() rehace la pantalla entera
 *   editor   el proyecto abierto (APP.pid, APP.fichas), y se repintan SOLO los
 *            bloques marcados con data-repinta —la previa y el repaso— y el
 *            pie: repintar la pestaña entera por cada escena tiraría la
 *            rejilla de doscientos planos y el foco del cuadro de feedback.
 *
 * En el modo light NADA cambia: las tres funciones devuelven exactamente lo
 * que las llamadas de antes tenían escrito a mano. */
function videoAbierto() {
  return APP.light.video;
}

//: Los bloques del editor que se repintan solos: por su `data-repinta`.
;

function repintarVideo() {
  pintarLight();
}

/* Volver a leer el vídeo entero tras un trabajo que lo cambia (aplicar el
   repaso). */
async function recargarVideoAbierto() {
  await cargarVideoLight(APP.light.video.pid);
}

/* Si las diapositivas están en pantalla: es lo que decide que las flechas del
   teclado pasen de escena. */
function previaALaVista() {
  return APP.light.video.vista === 'previa';
}

/* ================================================ EL PREVISUALIZADOR
 *
 * VER EL VÍDEO ANTES DE MONTARLO, escena a escena y al ritmo de quien mira.
 *
 * Aquí vivía la revisión de los planos con IA: abría los PNG con un modelo,
 * decidía cuáles contradecían el relato y rehacía ésos. Miraba bien, pero se
 * comía el reloj —treinta y seis llamadas en un vídeo normal— y sobre todo
 * decidía sola sobre lo único que no debería decidir sola: qué se ve.
 *
 * Lo que hay ahora no es otro agente, es una pantalla. Y NO RENDERIZA NADA:
 * monta cada escena en el navegador con las piezas sueltas que da
 * `GET .../previsualizacion` —la imagen, su capa de rótulos y los subtítulos
 * con sus tiempos—, y el audio es la toma entera con `currentTime` puesto donde
 * empieza la escena. Montar un MP4 de quince minutos para poder mirarlo son
 * minutos de máquina y una decisión que todavía no está tomada.
 *
 * LO QUE NO SE VE AQUÍ, y es la mitad del encargo: ni el zoom, ni el movimiento
 * de cámara, ni las transiciones. Se mira UNA imagen quieta con su audio. Eso
 * se ve en el MP4, que es donde importa.
 */

/* La escena que se está mirando y cómo suena. Vive fuera de videoAbierto()
   porque el <audio> es UN elemento que sobrevive a los repintados: crear otro
   en cada pintado cortaría el sonido cada vez que escribes una letra en el
   cuadro de feedback. */
const PREVIA = {
  ficha: null,        // lo que devolvió el endpoint
  i: 0,               // la escena que se mira
  cargando: false,
  error: '',
  audio: null,        // <audio> de la narración, reutilizado
  musica: null,       // <audio> de la cama, solo para el play seguido
  efectos: null,
  seguido: false,     // ¿está sonando el play de todo?
  sonando: false,
  t: 0,               // segundo del vídeo, para el subtítulo que toca
  notas: [],          // las del repaso, para pintar las de cada escena
  adjuntos: {},       // escena -> imágenes subidas para la nota a medio escribir
  guardando: false,
  borrador: {},       // id de escena -> lo escrito y sin enviar
  editando: '',       // id de la nota que se está corrigiendo, si hay alguna
};

async function cargarPreviaLight() {
  const v = videoAbierto();
  if (!v.pid || PREVIA.cargando) return;
  PREVIA.cargando = true;
  PREVIA.error = '';
  repintarVideo();
  try {
    PREVIA.ficha = await pedir(`${API.proyecto(v.pid)}/previsualizacion`);
    PREVIA.i = 0;
    PREVIA.t = 0;
    await refrescarNotasPrevia();
    prebufferPrevia();
  } catch (err) {
    PREVIA.error = err.message;
  }
  PREVIA.cargando = false;
  repintarVideo();
}

/* TODO LO QUE DEVUELVE EL REPASO SE GUARDA POR AQUI, Y SOLO POR AQUI.
 *
 * La respuesta trae las notas Y cuantas quedan por aplicar. Habia cuatro sitios
 * que guardaban `PREVIA.notas` --apuntar, editar, borrar y refrescar-- y solo
 * uno tocaba el contador, asi que el boton seguia diciendo «Aplicar 3 cambios»
 * con ocho apuntados: la lista de debajo se actualizaba y el numero no. Solo
 * cuadraban despues de recargar.
 *
 * Un contador que se actualiza en un camino de cuatro esta roto en tres. */
/* De que pantalla son las notas que toca mirar. Un solo cuaderno en disco, dos
   lecturas: en Imagenes se anota sobre el dibujo y en Video sobre lo que se
   monta encima. Contarlas juntas hacia que las ocho de una salieran en la otra.
   Las escritas antes de la separacion no llevan marca y son del video. */
function pantallaDeNota(nota) {
  const p = String((nota || {}).pantalla || '');
  return p === 'imagenes' ? 'imagenes' : 'video';
}


function cuadernoDeAhora() {
  return videoAbierto().vista === 'previa' ? 'imagenes' : 'video';
}


/* LA ULTIMA QUE ESCRIBISTE, ARRIBA. El servidor las ordena por SEGUNDO DE VIDEO
   --que es lo que necesita para aplicarlas-- y aqui eso es el orden equivocado:
   la que acabas de escribir aparecia enterrada en mitad de doscientas, asi que
   para comprobar que se habia apuntado habia que buscarla. Lo que se mira en
   esta lista es lo RECIENTE: lo pendiente de aplicar y lo recien aplicado.

   Se ordena por `fecha`, que la escribe el servidor al apuntarla. Las de antes
   de que existiera ese campo no la llevan: se quedan al final, en el orden en
   que vinieron, que es donde estaban.

   Y NO SE ORDENA EN EL SERVIDOR: `repaso.leer` es la que usa el enrutador para
   repartir las notas contra los cortes del montaje, y ahi el orden de video SI
   significa algo. Esto es como se MIRAN, que es otra cosa. */
function notasDeAhora() {
  const cual = cuadernoDeAhora();
  const mias = (estadoRepaso().notas || []).filter(
    n => pantallaDeNota(n) === cual);
  return mias
    .map((nota, i) => ({ nota, i }))
    .sort((a, b) => {
      const fa = String(a.nota.fecha || '');
      const fb = String(b.nota.fecha || '');
      if (fa && fb && fa !== fb) return fb < fa ? -1 : 1;
      if (fa !== fb) return fa ? -1 : 1;      // con fecha, por delante
      return a.i - b.i;
    })
    .map(x => x.nota);
}


/* ------------------------------------------- lo aplicado que nadie ha mirado
 *
 * Aplicar una nota no es acabarla: falta ver si lo que salio vale. Con la lista
 * apagando las aplicadas en cuanto lo estaban, una tanda de ocho dejaba ocho
 * notas grises indistinguibles de las de la semana pasada y no habia forma de
 * saber cuales tocaba repasar.
 *
 * Se marcan en azul hasta que se pulsa SU boton de ir al plano --«S064» en las
 * diapositivas, el minuto en el video--, que es el gesto con el que se mira. Se
 * apunta EN MEMORIA y a proposito: es «lo que has visto en este rato», no un
 * dato del video, y sobrevivir a una recarga haria que volver manana dejara la
 * lista entera en gris otra vez sin haber mirado nada.
 *
 * La clave lleva el TEXTO dentro porque los ids de nota se reciclan --borra
 * R001 y la siguiente vuelve a llamarse R001--: sin eso, una nota nueva
 * heredaria el «ya visto» de una borrada y nacería en gris. */
const REVISADAS = { pid: '', vistas: new Set() };

function claveDeNota(nota) {
  const n = nota || {};
  return JSON.stringify([n.id, n.estado, n.regenerado || '', n.texto || '']);
}

/* LO QUE YA ESTABA APLICADO AL ABRIR EL VIDEO NO SE MARCA, y esa es la mitad
   del invento. Sin esto, entrar en un video con cincuenta notas viejas ya
   aplicadas las pintaria las cincuenta en azul: «pendiente de revisar» dejaria
   de significar nada el mismo dia. Lo que se marca es lo que se aplica MIENTRAS
   miras, que es lo que se pidio.

   Se siembra la primera vez que alguien pregunta por este video, y para
   entonces las notas ya han llegado: la lista solo se pinta cuando las hay. */
function notasVistas() {
  const pid = videoAbierto().pid || '';
  if (REVISADAS.pid !== pid) {
    REVISADAS.pid = pid;
    REVISADAS.vistas = new Set(
      (estadoRepaso().notas || []).filter(estaAplicada).map(claveDeNota));
  }
  return REVISADAS.vistas;
}

function estaAplicada(nota) {
  return (nota || {}).estado === 'aplicado'
    || estadoDeImagen((nota || {}).plano, nota) === 'hecha';
}

function sinRevisar(nota) {
  return estaAplicada(nota) && !notasVistas().has(claveDeNota(nota));
}

function darPorRevisada(nota) {
  if (estaAplicada(nota)) notasVistas().add(claveDeNota(nota));
}


function pendientesDeAhora() {
  return notasDeAhora().filter(n => n.estado !== 'aplicado').length;
}


function guardarRepaso(datos) {
  const d = datos || {};
  /* LO QUE SE GUARDA EN MEMORIA NO PUEDE SOBREVIVIR A SU NOTA. Los ids se
     reciclan --borra R001 y la siguiente vuelve a llamarse R001--, asi que un
     fallo apuntado contra una nota que ya no existe se lo quedaria la proxima
     que herede el numero. */
  const vivos = new Set((d.notas || []).map(n => n.id));
  Object.keys(COLA_IMG.fallo).forEach(nid => {
    if (!vivos.has(nid)) delete COLA_IMG.fallo[nid];
  });
  PREVIA.notas = d.notas || [];
  const r = estadoRepaso();
  r.notas = d.notas || [];
  r.cortes = d.cortes || r.cortes;
  r.pendientes = typeof d.pendientes === 'number'
    ? d.pendientes
    : (d.notas || []).filter(n => n.estado !== 'aplicado').length;
  r.catalogo = d.catalogo || r.catalogo;
  r.cargado = true;
}


async function refrescarNotasPrevia() {
  try {
    guardarRepaso(await pedir(API.repaso(videoAbierto().pid)));
  } catch (e) { PREVIA.notas = []; }
}

function escenaPrevia() {
  const escenas = (PREVIA.ficha || {}).escenas || [];
  return escenas[Math.max(0, Math.min(PREVIA.i, escenas.length - 1))] || null;
}

/* LAS SIGUIENTES, PEDIDAS ANTES DE QUE HAGAN FALTA. Sin esto, cada flecha
   derecha era una espera con el cuadro en blanco mientras bajaba un PNG de
   1920×1080. Se piden en miniatura (`?mini=1024`, que el servidor cachea) y se
   dejan en la caché del navegador; el <img> de después las encuentra puestas.

   Cuatro por delante y una por detrás: hacia delante se va casi siempre, y la
   de atrás es para que volver sobre lo que acabas de ver sea instantáneo. */
const PREBUFFER_ADELANTE = 4;

function prebufferPrevia() {
  const escenas = (PREVIA.ficha || {}).escenas || [];
  const pid = videoAbierto().pid;
  for (let d = -1; d <= PREBUFFER_ADELANTE; d += 1) {
    const e = escenas[PREVIA.i + d];
    if (!e || !e.imagen) continue;
    const img = new Image();
    img.src = `${API.archivo(pid, e.imagen)}?mini=1024`;
  }
}

/* ------------------------------------------------------------- el sonido */

function audioPrevia() {
  if (!PREVIA.audio) {
    PREVIA.audio = new Audio();
    PREVIA.audio.preload = 'auto';
    PREVIA.audio.addEventListener('timeupdate', alSonarPrevia);
    PREVIA.audio.addEventListener('ended', () => { pararPrevia(); repintarVideo(); });
  }
  const url = API.archivo(videoAbierto().pid, (PREVIA.ficha || {}).audio || '');
  if ((PREVIA.ficha || {}).audio && PREVIA.audio.dataset.url !== url) {
    PREVIA.audio.src = url;
    PREVIA.audio.dataset.url = url;
  }
  return PREVIA.audio;
}

/* EL RELOJ MANDA SOBRE QUÉ ESCENA SE VE, y no al revés. Escena a escena el
   audio se para al llegar al final de la escena; en el play seguido no se para
   y lo que hace el reloj es ir cambiando la escena que se pinta. Las dos cosas
   salen del mismo sitio para que no puedan discrepar. */
function alSonarPrevia() {
  const audio = PREVIA.audio;
  const e = escenaPrevia();
  if (!audio || !e) return;
  PREVIA.t = audio.currentTime;
  if (!PREVIA.seguido) {
    if (audio.currentTime >= e.t_out - 0.02) {
      audio.pause();
      PREVIA.sonando = false;
      PREVIA.t = e.t_out;
    }
    return;
  }
  const escenas = (PREVIA.ficha || {}).escenas || [];
  if (audio.currentTime >= e.t_out && PREVIA.i < escenas.length - 1) {
    // la que toque por reloj, no «la siguiente»: si el navegador se salta un
    // tic el índice se queda atrás y la imagen deja de cuadrar con la voz
    let j = PREVIA.i;
    while (j < escenas.length - 1 && audio.currentTime >= escenas[j].t_out) j += 1;
    PREVIA.i = j;
    prebufferPrevia();
    repintarVideo();
    return;
  }
}


function sonarEscenaPrevia() {
  const e = escenaPrevia();
  if (!e) return;
  const audio = audioPrevia();
  PREVIA.seguido = false;
  pararCamaPrevia();
  audio.currentTime = e.t_in;
  PREVIA.t = e.t_in;
  audio.play().then(() => { PREVIA.sonando = true; repintarVideo(); })
    .catch(() => { PREVIA.sonando = false; });
}

function pararPrevia() {
  if (PREVIA.audio) PREVIA.audio.pause();
  PREVIA.sonando = false;
  PREVIA.seguido = false;
  pararCamaPrevia();
}

/* LA MÚSICA Y LOS EFECTOS SOLO EN EL PLAY SEGUIDO. Escena a escena se oye la
   VOZ y nada más: lo que se está juzgando ahí es si la imagen cuadra con lo que
   se dice, y una cama debajo es justo lo que tapa esa pregunta. */
function camaPrevia(clave) {
  const ruta = (PREVIA.ficha || {})[clave];
  if (!ruta) return null;
  if (!PREVIA[clave]) {
    PREVIA[clave] = new Audio(API.archivo(videoAbierto().pid, ruta));
    PREVIA[clave].preload = 'auto';
    PREVIA[clave].volume = clave === 'musica' ? 0.35 : 0.6;
  }
  return PREVIA[clave];
}

function pararCamaPrevia() {
  for (const clave of ['musica', 'efectos']) {
    if (PREVIA[clave]) { PREVIA[clave].pause(); }
  }
}

function reproducirTodoPrevia() {
  const audio = audioPrevia();
  const e = escenaPrevia();
  if (!e) return;
  PREVIA.seguido = true;
  audio.currentTime = e.t_in;
  for (const clave of ['musica', 'efectos']) {
    const pista = camaPrevia(clave);
    if (pista) { pista.currentTime = e.t_in; pista.play().catch(() => {}); }
  }
  audio.play().then(() => { PREVIA.sonando = true; repintarVideo(); })
    .catch(() => { PREVIA.sonando = false; });
}

/* ------------------------------------------------------------ moverse */

function irAEscenaPrevia(salto) {
  const escenas = (PREVIA.ficha || {}).escenas || [];
  const j = Math.max(0, Math.min(escenas.length - 1, PREVIA.i + salto));
  if (j === PREVIA.i) return;
  PREVIA.i = j;
  prebufferPrevia();
  repintarVideo();
  sonarEscenaPrevia();
}


/* EL SWIPE, que en el móvil es LO NORMAL y no un extra.
 *
 * Este vídeo se revisa desde el teléfono —por Tailscale, mientras el ordenador
 * genera— y ahí no hay flechas de teclado ni ganas de acertarle a un botón
 * doscientas veces. Arrastrar a la izquierda es «la siguiente», que es
 * exactamente el gesto de pasar página.
 *
 * TRES GUARDAS, y las tres salen de que esto convive con una página que se
 * puede desplazar:
 *   · un mínimo de recorrido, o cualquier toque torpe cambiaría de escena;
 *   · más horizontal que vertical, o bajar por la pantalla pasaría de escena;
 *   · y un tope de tiempo: un dedo apoyado medio minuto y luego movido no es
 *     un swipe, es otra cosa.
 */
const SWIPE_MINIMO_PX = 55;
const SWIPE_MAXIMO_MS = 800;

function engancharSwipePrevia(nodo) {
  let x0 = 0;
  let y0 = 0;
  let t0 = 0;
  nodo.addEventListener('touchstart', ev => {
    const dedo = ev.changedTouches[0];
    x0 = dedo.clientX; y0 = dedo.clientY; t0 = Date.now();
  }, { passive: true });
  nodo.addEventListener('touchend', ev => {
    const dedo = ev.changedTouches[0];
    const dx = dedo.clientX - x0;
    const dy = dedo.clientY - y0;
    if (Date.now() - t0 > SWIPE_MAXIMO_MS) return;
    if (Math.abs(dx) < SWIPE_MINIMO_PX || Math.abs(dx) <= Math.abs(dy)) return;
    irAEscenaPrevia(dx < 0 ? 1 : -1);
  }, { passive: true });
}

/* ------------------------------------------------------------- la pantalla */

/* ------------------------------------------------ el dibujo que ya no es de aquí
 *
 * OBSOLETO NO ES PENDIENTE, y la diferencia es de dinero. Cuando el texto de un
 * plano cambia --se reescribe el guion, o se regraba la voz y la narración se
 * vuelve a cortar-- el dibujo que hay debajo sigue siendo el de la frase de
 * antes. Rehacerlo por si acaso son 5 céntimos por plano que nadie ha pedido
 * gastar, y tirarlo es peor: casi siempre sigue valiendo.
 *
 * Así que no se toca nada y se DICE. La tarjeta sale encima del campo de
 * feedback, que ya está ahí esperando: si el dibujo no vale, se escribe qué
 * cambiar y se rehace ESE plano. Y si vale, se quita la tarjeta.
 */
/* El recuento, y solo cuando hay alguna: un contador a cero es una cosa más que
   leer en una cabecera que ya tiene tres. */
function obsoletasEnLaCabecera(escenas) {
  const cuantas = escenas.filter(x => x.obsoleta).length;
  if (!cuantas) return null;
  return h('button', {
    clase: 'pastilla obsoleto',
    title: 'planos cuyo dibujo se hizo para otra frase — pulsa para ir al primero',
    onclick: irAPrimeraObsoleta,
  }, cuantas === 1 ? '1 obsoleta' : `${cuantas} obsoletas`);
}

function avisoImagenObsoleta(escena) {
  const v = videoAbierto();
  return h('div', { clase: 'aviso-obsoleta' },
    h('div', { clase: 'fila' },
      h('span', { clase: 'pastilla obsoleto' }, 'Obsoleto'),
      h('span', { clase: 'meta' }, 'este dibujo se hizo para otra frase'),
      h('span', { clase: 'crece' }),
      h('button', {
        clase: 'mini fantasma',
        title: 'quitar el aviso: el dibujo vale para lo que dice ahora',
        onclick: async () => {
          try {
            await pedir(`${API.proyecto(v.pid)}/escenas/${escena.id}/vale`,
                        { method: 'POST' });
            delete escena.obsoleta;
            repintarVideo();
          } catch (fallo) { toast(fallo.message, true); }
        },
      }, 'Me vale')),
    h('div', { clase: 'meta' },
      `se dibujó para: «${escena.dibujada_para || ''}»`),
    h('div', { clase: 'meta' }, `y aquí ahora se dice: «${escena.narracion}»`));
}


/* Cuántas hay y cómo llegar a la primera. Con doscientos planos, un aviso que
   solo se ve al pasar por encima del plano que lo lleva no se ve nunca. */
function irAPrimeraObsoleta() {
  const escenas = (PREVIA.ficha || {}).escenas || [];
  const i = escenas.findIndex(x => x.obsoleta);
  if (i >= 0) { PREVIA.i = i; PREVIA.t = 0; repintarVideo(); }
}

function vistaPreviaLight() {
  const v = videoAbierto();
  const caja = h('div', { clase: 'light-previa' });
  const escenas = (PREVIA.ficha || {}).escenas || [];
  const e = escenaPrevia();

  caja.appendChild(h('div', { clase: 'light-cab' },
    h('h2', {}, 'Las imágenes, una a una'),
    h('span', { clase: 'meta' },
      escenas.length ? `escena ${PREVIA.i + 1} de ${escenas.length}` : ''),
    obsoletasEnLaCabecera(escenas),
    h('span', { clase: 'crece' }),
    costeLight()));

  if (PREVIA.error) { caja.appendChild(cajaError(PREVIA.error)); return caja; }
  if (!PREVIA.ficha) {
    // SE PIDE DESPUES DE PINTAR, no en mitad del pintado: `cargarPreviaLight`
    // llama a `pintarLight` para enseñar el «cargando», y hacerlo desde dentro
    // del propio pintado deja el nodo que estamos armando colgando de un panel
    // que ya se ha reemplazado.
    if (!PREVIA.cargando) setTimeout(cargarPreviaLight, 0);
    caja.appendChild(h('div', { clase: 'cargando' }, 'preparando las escenas…'));
    return caja;
  }
  if (!e) {
    caja.appendChild(h('div', { clase: 'vacio' },
      'no hay ninguna escena que mirar todavía'));
    return caja;
  }

  /* EL PLANO: la imagen, su capa de rótulos encima y el subtítulo debajo del
     todo. Las tres en el MISMO cuadro y en el orden en el que se dibujan en el
     vídeo, que es lo que hace que esto se parezca al resultado y no a una
     previsualización de otra cosa. */
  const marco = h('div', { clase: 'previa-marco' });
  /* EL CUADRO YA COMPUESTO CUANDO LO HAY, y si no la imagen sola.
     `callouts` deja un PNG por plano con la MISMA composición que renderiza el
     render —la imagen dentro del transform de cámara, la capa móvil con ella y
     el subtítulo fuera a 1:1—, así que ahí ya vienen las cartelas colocadas. Lo
     que se hacía antes era juntar la imagen con `capas/{id}.svg` aquí encima, y
     esa capa vive en el espacio del lienzo de generación: estirada sobre un
     cuadro 16:9 descoloca las cartelas. */
  /* LA IMAGEN SOLA, SIN NADA ENCIMA.
     Aqui se revisa el DIBUJO: que hay, quien sale, que hace. Los subtitulos y
     las cartelas se miran -- y se corrigen -- en la pantalla del video, que es
     donde se ven en movimiento y con su sonido. Ensenarlos aqui mezclaba dos
     revisiones distintas en la misma pantalla y hacia dudar de si una nota era
     del dibujo o del texto de encima. */
  marco.classList.add(formatoDelVideo());
  const fondo = e.imagen;
  if (fondo) {
    marco.appendChild(h('img', {
      // en miniatura ancha: se ve igual en pantalla y entra en la caché que
      // ya ha llenado el prebuffer, así que la flecha derecha es instantánea
      src: `${API.archivo(v.pid, fondo)}?mini=1024`,
      alt: e.id,
    }));
  }
  /* NI SUBTITULO NI SELLO DE CARTELA: aqui se mira el DIBUJO y nada mas.
     Los dos se revisan -- y se corrigen -- en la pantalla del video, que es
     donde se ven en movimiento y con su sonido. Tenerlos aqui mezclaba dos
     revisiones en una pantalla y hacia dudar de si una nota era del dibujo o
     del texto de encima. */
  engancharSwipePrevia(marco);
  caja.appendChild(marco);

  /* LOS MANDOS. La flecha derecha es el gesto principal —pasar de escena y
     oírla— así que va grande y también en el teclado. */
  /* LA FILA DE MANDOS SE MONTA AQUI PERO SE CUELGA LA ULTIMA.
     Anclada al fondo tiene que ser el ultimo elemento del flujo o taparia lo
     que venga detras -- el cuadro de feedback y el boton de aplicar --, que es
     justo lo que se le pide que no haga. */
  const mandos = h('div', { clase: 'previa-mandos' },
    h('button', {
      clase: 'mini', disabled: PREVIA.i === 0,
      onclick: () => irAEscenaPrevia(-1), title: 'La anterior (←)',
    }, '‹'),
    h('button', {
      clase: 'mini',
      onclick: () => (PREVIA.sonando && !PREVIA.seguido ? (pararPrevia(), repintarVideo())
        : sonarEscenaPrevia()),
      title: 'Oír esta escena otra vez',
    }, PREVIA.sonando && !PREVIA.seguido ? '❚❚ Parar' : '♪ Oírla'),
    /* MIRAR A LA IZQUIERDA, ACTUAR A LA DERECHA. «Todo seguido» estaba con las
       acciones y es lo mismo que «Oírla»: una forma de mirar esto. Juntos se
       leen de un vistazo y el lado derecho se queda para lo que cambia algo. */
    h('button', {
      clase: PREVIA.seguido ? 'mini peligro' : 'mini',
      onclick: () => (PREVIA.seguido ? (pararPrevia(), repintarVideo())
        : reproducirTodoPrevia()),
      title: 'Todo seguido, con música y efectos (sin zoom ni transiciones)',
    }, PREVIA.seguido ? '❚❚ Parar' : '▶ Todo seguido'),
    h('span', { clase: 'meta' },
      `${e.id} · ${e.duracion.toFixed(1)} s`
      + (e.bloque ? ` · ${e.bloque}` : '')),
    h('span', { clase: 'crece' }),
    h('button', {
      clase: 'primario', disabled: PREVIA.i >= escenas.length - 1,
      onclick: () => irAEscenaPrevia(1), title: 'La siguiente (→)',
    }, 'Siguiente ›'));

  /* AQUI NO SE AVISA DE LO QUE FALTA POR MONTAR, Y ES A PROPOSITO.
   *
   * Habia un aviso --«los subtítulos ya se ven, pero las cartelas y los rótulos
   * todavía no»-- que se quedo de cuando esta pantalla pintaba el subtitulo
   * encima de la imagen. Ya no: aqui se mira el DIBUJO y nada mas (ver el
   * comentario del marco), asi que la primera mitad de la frase era mentira --
   * los subtitulos NO se ven-- y la segunda avisaba de algo que no falta: es
   * que no toca todavia.
   *
   * Los rotulos, las cartelas y los subtitulos se miran --y se corrigen-- en la
   * pantalla del video, que es donde estan puestos, en movimiento y con su
   * sonido; el repaso de alli reparte cada nota en su cambio (`cartela_texto`,
   * `subtitulo_texto`, `subtitulo_tam`... en `pasos/repaso.py`). */

  if (e.obsoleta) caja.appendChild(avisoImagenObsoleta(e));
  caja.appendChild(cuadroFeedbackEscena(e));

  /* LA LISTA ENTERA DE NOTAS, LA MISMA QUE EN EL VIDEO.
     Antes aqui solo salian las de la escena que estabas mirando, asi que para
     saber que llevabas apuntado en las otras doscientas habia que pasarlas una
     a una o irse al video. Es el MISMO componente --`listaDeNotas`--, no una
     copia: una segunda lista se separa de la primera en cuanto alguien toque
     una de las dos. Pulsando el plano se salta a esa diapositiva. */
  if (notasDeAhora().length) caja.appendChild(listaDeNotas());

  /* APLICAR TAMBIEN SE PUEDE DESDE AQUI, y no solo con el video ya montado.
   *
   * Las notas se escriben MIRANDO las diapositivas -- es para lo que existe
   * esta pantalla --, pero el boton de aplicarlas vivia unicamente en el panel
   * de repaso, que solo aparece cuando ya hay MP4. O sea que para arreglar algo
   * que ya sabes que esta mal habia que montar antes el video que sabes que
   * esta mal. Eso es justo al reves de aplicar lo mas barato.
   *
   * Es el MISMO pie, no otro camino: mismo contador, misma llamada y el mismo
   * reparto en el servidor, que sigue eligiendo el cambio mas barato que
   * resuelve cada nota. Un segundo boton que 'aplicara' por su cuenta se
   * quedaria viejo el dia que alguien tocara ese reparto. */
  /* UNA SOLA BARRA ABAJO, Y ES LA DE ESTA PANTALLA.
     El aplicar iba en su propio pie dentro del contenido y quedaban tres
     franjas apiladas al fondo. Va DENTRO de los mandos, a la derecha con el
     resto de acciones; a la izquierda queda lo de moverse por la escena.

     No se cuelga aqui sino en `BARRA_INFERIOR`: dentro del contenido no puede
     ir de borde a borde --la columna tiene ancho maximo y va centrada-- y una
     barra anclada mas corta que la de abajo se lee como un fallo. */
  /* LAS ACCIONES, DELANTE DE «Siguiente ›» Y NUNCA DETRAS. Esa flecha se pulsa
     doscientas veces y su sitio -- el extremo derecho -- no puede moverse
     porque haya notas sin aplicar o porque el video se haya quedado viejo.

     Aqui abajo y no en la cabecera: en las otras dos pantallas todas las
     acciones estan en esta barra y la cabecera solo informa. Tenerla ahi
     arriba dejaba a las diapositivas siendo la unica que no seguia la regla. */
  /* «APLICAR» TAMBIEN AQUI, pero haciendo lo de aqui: encolar todas las notas
     de esta pantalla. Cada tarjeta tiene ademas el suyo para ir una a una. */
  const ultima = () => mandos.children[mandos.children.length - 1] || null;
  const aplicar = botonAplicarRepaso();
  if (aplicar) mandos.insertBefore(aplicar, ultima());
  const montar = botonRenderizarLight();
  if (montar) mandos.insertBefore(montar, ultima());
  BARRA_INFERIOR.nodo = mandos;
  return caja;
}

/* EL SUBTÍTULO QUE TOCA AHORA. Sus tiempos vienen en el reloj DEL PLANO, así
   que se compara con lo que lleva sonando de esta escena. Parado se enseña el
   primero: un cuadro sin subtítulo no se parece al vídeo. */
/* Si el aparato se maneja con el dedo. Se pregunta por el PUNTERO y no por el
   ancho: una tableta con teclado es ancha y se toca, y un navegador de
   escritorio estrecho no. */
function esTactil() {
  try { return window.matchMedia('(pointer: coarse)').matches; }
  catch (e) { return false; }
}


/* ------------------------------------------------- el feedback de la escena
 *
 * NO ES UN CAJÓN NUEVO: entra por el MISMO repaso que ya recoge las notas del
 * vídeo montado (`POST .../repaso`), anclado al segundo en el que empieza la
 * escena y a su plano. Y por eso al aplicarlo elige el cambio MÁS BARATO que
 * resuelve la nota —redibujar ese plano, reescribir su subtítulo, cambiar la
 * cartela o regrabar su bloque— en vez de dar por hecho que todo se arregla
 * dibujando otra vez. Un segundo camino se habría quedado viejo el día que
 * alguien tocara esa elección.
 */
function cuadroFeedbackEscena(escena) {
  /* LAS APLICADAS NO SE ENSEÑAN. Una nota es algo que PIDES; en cuanto está
     hecha deja de ser una petición y pasa a ser historia, y dejarla ahí hace
     que la lista crezca sola y que no se distinga lo que falta de lo que ya
     está. El repaso ya marca el estado, y editar una aplicada la devuelve a
     pendiente (`repaso.editar`), así que rectificar sigue siendo posible desde
     la pantalla de repaso. */
  const mias = PREVIA.notas.filter(
    n => (n.plano || '') === escena.id && n.estado !== 'aplicado');
  const caja = h('div', { clase: 'previa-feedback' });
  caja.appendChild(campoArea(
    `¿Qué cambiarías de ${escena.id}?`,
    PREVIA.borrador[escena.id] || '',
    valor => { PREVIA.borrador[escena.id] = valor; },
    'lo que ves y no cuadra con lo que se oye',
    `feedback:${escena.id}`));
  /* Una referencia dibuja más que una frase: «el ordenador tiene que ser
     como ESTE». Va con la nota y el corrector la adjunta al generador con la
     etiqueta [adjunta] (p6_assets._adjuntos_de_la_nota), igual que las del
     repaso del vídeo montado. */
  caja.appendChild(zonaDeImagenes(`adjuntos-${escena.id}`, {
    leer: () => PREVIA.adjuntos[escena.id] || [],
    escribir: nombres => { PREVIA.adjuntos[escena.id] = nombres; },
  }));
  caja.appendChild(h('div', { clase: 'fila' },
    h('button', {
      clase: 'mini primario', disabled: PREVIA.guardando,
      onclick: () => guardarNotaEscena(escena),
    }, PREVIA.guardando ? 'guardando…' : 'Apuntar'),
    h('span', { clase: 'meta' },
      mias.length ? `${mias.length} nota(s) en esta imagen`
        : 'cada nota trae su botón para rehacer ESA imagen: el corrector lee la nota, '
          + 'mira las imágenes del vídeo (este plano, los vecinos, las hojas, las láminas) '
          + 'y adjunta al generador lo que la nota pide')));
  if (esTactil()) {
    caja.appendChild(h('div', { clase: 'meta previa-pista' },
      'desliza sobre la imagen para pasar de escena'));
  }
  return caja;
}

/* UNA NOTA SE EDITA Y SE BORRA, sin preguntar. Lo que se escribe aquí es una
   petición a medio pensar —la escribes mirando el plano y a la escena siguiente
   la matizas—, así que corregirla tiene que costar un clic. Sin diálogo de
   confirmación: es la misma regla que el resto del Estudio, editar es decidir.

   Al editar, `repaso.editar` la devuelve a 'pendiente' por su cuenta: una nota
   retocada es una petición nueva aunque la anterior ya se hubiera aplicado. */
function filaNotaEscena(nota) {
  if (PREVIA.editando === nota.id) {
    const area = h('textarea', { rows: 2 });
    area.dataset.foco = `nota:${nota.id}`;
    area.value = nota.texto || '';
    crecerConElTexto(area);
    return h('div', { clase: 'previa-nota editando' },
      area,
      h('div', { clase: 'fila' },
        h('button', {
          clase: 'mini primario',
          onclick: () => guardarNotaEditada(nota, area.value),
        }, 'Guardar'),
        h('button', {
          clase: 'mini fantasma',
          onclick: () => { PREVIA.editando = ''; repintarVideo(); },
        }, 'Cancelar')));
  }
  const adjuntas = (nota.imagenes || []).length
    ? h('span', { clase: 'nota-adjuntas' }, nota.imagenes.map(nombre => h('img', {
      src: API.imagenRepaso(videoAbierto().pid, nombre), alt: '', loading: 'lazy',
      title: 'referencia adjunta a la nota',
      onclick: () => lupa(API.imagenRepaso(videoAbierto().pid, nombre)),
    })))
    : null;
  return h('div', { clase: 'previa-nota' },
    h('span', { clase: 'meta' }, nota.id),
    h('span', { clase: 'texto' }, nota.texto || ''),
    adjuntas,
    h('button', {
      clase: 'mini fantasma', title: 'Cambiar esta nota',
      onclick: () => { PREVIA.editando = nota.id; repintarVideo(); },
    }, '✎'),
    h('button', {
      clase: 'mini fantasma', title: 'Quitar esta nota',
      onclick: () => borrarNotaEscena(nota),
    }, '✕'));
}

async function guardarNotaEditada(nota, texto) {
  const limpio = String(texto || '').trim();
  if (!limpio) { toast('una nota vacía no dice qué hacer', true); return; }
  try {
    const datos = await pedir(`${API.repaso(videoAbierto().pid)}/${nota.id}`, {
      method: 'PUT', cuerpo: { texto: limpio },
    });
    /* CAMBIAR LA NOTA LA DEVUELVE A PENDIENTE. El visto se apaña solo --
       `regenerado` se queda con el texto viejo y deja de coincidir--; lo que
       hay que quitar a mano es el fallo, que no tiene copia en el servidor. */
    delete COLA_IMG.fallo[nota.id];
    guardarRepaso(datos);
    PREVIA.editando = '';
  } catch (err) { mostrarError(CLAVE_VIDEO_LIGHT, err); }
  repintarVideo();
}

async function borrarNotaEscena(nota) {
  try {
    const datos = await pedir(`${API.repaso(videoAbierto().pid)}/${nota.id}`,
                              { method: 'DELETE' });
    guardarRepaso(datos);
  } catch (err) { mostrarError(CLAVE_VIDEO_LIGHT, err); }
  repintarVideo();
}

async function guardarNotaEscena(escena) {
  const texto = String(PREVIA.borrador[escena.id] || '').trim();
  if (!texto) { toast('escribe qué cambiarías de esta escena', true); return; }
  PREVIA.guardando = true;
  repintarVideo();
  try {
    const datos = await pedir(API.repaso(videoAbierto().pid), {
      method: 'POST',
      /* De Imagenes: se anota sobre el DIBUJO. No entra en el repaso del
         video, que arregla lo que se monta encima y lo que se oye.

         Y viaja el ANCLA -- lo que se dice en ese plano --, que es lo que
         permite volver a encontrarlo si manana se regraba la voz y los planos
         se renumeran (ver `repaso.reanclar`). */
      cuerpo: {
        texto, t: escena.t_in, plano: escena.id, pantalla: 'imagenes',
        ancla: escena.narracion || '',
        imagenes: PREVIA.adjuntos[escena.id] || [],
      },
    });
    guardarRepaso(datos);
    PREVIA.borrador[escena.id] = '';
    PREVIA.adjuntos[escena.id] = [];
  } catch (err) {
    mostrarError(CLAVE_VIDEO_LIGHT, err);
  }
  PREVIA.guardando = false;
  repintarVideo();
}

/* Montar el MP4 es lo que se hace CUANDO YA HAS MIRADO, así que el botón vive
   aquí y no en la tanda anterior (ver TANDAS_LIGHT en app.py). */
/* IR AL VIDEO. Y MONTARLO SOLO SI HACE FALTA.
 *
 * A esta pantalla se llega de dos maneras desde que el video tiene marcha
 * atras: de ida --antes de montar, y entonces hay que montar-- y de vuelta
 * desde el video ya hecho, para volver a mirar lo que se monto. En el segundo
 * caso montar otra vez son siete minutos de maquina para acabar con el mismo
 * MP4: mirar no puede costar un render. Asi que con el video hecho y al dia
 * esto solo cambia de vista, y lo dice el propio boton.
 *
 * Obsoleto SI monta, porque ahi si queda trabajo: exactamente el que el guion
 * o el audio han dejado viejo. */
/* MONTAR EL MP4 CON LO QUE ACABAS DE MIRAR.
 *
 * AL DIA NO HAY BOTON. Decia «El video ›» y entonces solo cambiaba de
 * pantalla, que es exactamente lo que hace la pestaña «Vídeo» de la barra de
 * abajo: dos sitios para el mismo gesto, y uno de ellos con pinta de ir a
 * montar algo. Cuando no queda nada que montar, desaparece.
 *
 * Y SIN FLECHA. Vive al lado de «Siguiente ›», que es la flecha de verdad --la
 * escena siguiente--; dos chevrones seguidos apuntando a sitios distintos se
 * leen como el mismo gesto. Aqui la etiqueta ya dice lo que hace. */
function botonRenderizarLight() {
  if (hayMp4Light() && !videoObsoletoLight()) return null;
  const corriendo = (APP.trabajos[CLAVE_VIDEO_LIGHT] || {}).estado === 'ejecutando';
  /* CON NOTAS SIN APLICAR, ESTE BOTON HACE MENOS que el de al lado: «Aplicar»
     reparte las notas, redibuja lo que toquen y DESPUES monta; esto solo monta,
     o sea que gasta el render entero para dejarte el video sin tus notas. Es la
     misma regla que en la pantalla del video. Apagado y con el motivo puesto,
     no escondido: desaparecer no explica nada. */
  const notasSinAplicar = estadoRepaso().pendientes > 0;
  return conAyuda(
    notasSinAplicar
      ? 'Tienes notas del repaso sin aplicar. Esto solo montaria el MP4 y '
        + 'saldria sin ellas. Usa «Aplicar», que aplica y monta de una vez.'
      : unirAyuda('Encadena los planos que acabas de mirar, con sus transiciones, '
        + 'la voz y la musica, y saca el MP4. No genera ninguna imagen: no cuesta '
        + 'dinero, cuesta tiempo de maquina.', textoDelPlan('render')),
    h('button', {
      clase: notasSinAplicar ? 'mini' : 'avisa',
      disabled: corriendo || notasSinAplicar,
      onclick: () => {
        pararPrevia();
        videoAbierto().vista = 'video';
        repintarVideo();
        lanzarTandaLight('render');
      },
    }, 'Montar el vídeo'));
}

/* LAS FLECHAS DEL TECLADO. Pasar de escena es el gesto que se repite
   doscientas veces: pedirlo con el ratón cada vez es la diferencia entre
   revisar un vídeo y no revisarlo. Se ignoran cuando el foco está escribiendo,
   o escribir «→» en el feedback saltaría de escena. */
document.addEventListener('keydown', ev => {
  if (!previaALaVista()) return;
  /* SE MIRAN LAS DOS COSAS: a donde va la tecla y donde esta el foco. Aqui se
     miraba solo el foco, y con un teclado de verdad son lo mismo... salvo
     justo despues de un repintado, que es cuando esto fallaba. Es la misma
     comprobacion que usa `atajosDeReproductor`, y ahora la comparten. */
  if (escribiendo(ev.target)) return;
  if (ev.key === 'ArrowRight') { ev.preventDefault(); irAEscenaPrevia(1); }
  else if (ev.key === 'ArrowLeft') { ev.preventDefault(); irAEscenaPrevia(-1); }
  else if (ev.key === ' ') {
    ev.preventDefault();
    if (PREVIA.sonando) { pararPrevia(); repintarVideo(); } else sonarEscenaPrevia();
  }
});


function vistaVideoLight() {
  const v = videoAbierto();
  const caja = h('div', { clase: 'light-video' });
  /* ATRAS VA A LAS DIAPOSITIVAS, NO AL GUION. Del video montado se sale hacia
     atras para MIRAR otra vez lo que se monto --cada escena con su imagen, su
     capa y sus subtitulos--, no para releer el texto. El guion sigue a un paso
     de distancia, detras de esa pantalla, que es el orden en que se hicieron
     las cosas. Si no hay planos no hay nada que mirar y se va al guion, que es
     de donde se venia. */
  caja.appendChild(h('div', { clase: 'light-cab' },
    h('h2', {}, v.nombre || 'El vídeo'),
    h('span', { clase: 'crece' }),
    costeLight()));

  const error = ERRORES[CLAVE_VIDEO_LIGHT];
  if (error) caja.appendChild(cajaError(error));

  const marco = h('div', { clase: `marco-video ${formatoDelVideo()}` });
  if (hayMp4Light() && !trabajoVideoLight()) {
    marco.appendChild(videoLight());
  } else if (v.planos.length) {
    // el último que ha caído, grande: es lo que se acaba de generar
    const ultimo = v.planos[v.planos.length - 1];
    marco.appendChild(h('img', {
      src: API.archivo(v.pid, ultimo.ruta || ''), alt: ultimo.id || '',
    }));
    marco.appendChild(h('div', { clase: 'sello' },
      `${ultimo.id || ''} · ${v.planos.length} planos`));
  } else {
    marco.appendChild(h('div', { clase: 'vacio' },
      trabajoVideoLight() ? 'montando los planos…' : 'todavía no hay vídeo'));
  }
  caja.appendChild(marco);

  /* LA TIRA DE VINETAS SOLO MIENTRAS SE GENERA.
     Con el video ya montado esta pantalla es para VERLO y comentarlo, y
     cuarenta miniaturas debajo del reproductor empujan el repaso fuera de
     pantalla y repiten lo que ya se mira mejor en las diapositivas. Mientras
     se genera si valen: son lo unico que ensena que algo esta pasando. */
  if (v.planos.length && trabajoVideoLight()) {
    const tira = h('div', { clase: 'tira-planos' });
    v.planos.slice(-40).forEach(plano => tira.appendChild(h('img', {
      src: API.archivo(v.pid, plano.ruta || ''), alt: plano.id || '',
      loading: 'lazy', title: plano.id || '',
    })));
    caja.appendChild(tira);
  }

  /* AQUI SE MONTA EL MP4, ASI QUE LA TANDA ES 'render' Y NO 'video'.
   *
   * Lanzaba 'video', que lleva `sin: ['render']` y por tanto NO monta ningun
   * MP4: en la pantalla del video, el boton que dice «Regenerar Vídeo» no
   * regeneraba el video. Y de ahi salia el mensaje contradictorio de al lado
   * --«Obsoleto» junto a «al día: no queda nada por generar»--: las dos frases
   * eran ciertas y hablaban de tandas distintas. Medido: 'video' 0 tareas,
   * 'render' 1.
   *
   * EL MODO. Con el video obsoleto va 'pendientes': lo obsoleto es exactamente
   * lo que ha quedado viejo, y 'todo' volveria a rehacer los clips de un video
   * entero por haber cambiado una frase. 'todo' se queda para cuando no hay
   * nada obsoleto y aun asi quieres otro: ahi si lo estas pidiendo. */
  const notasSinAplicar = estadoRepaso().pendientes > 0;
  const pie = h('div', { clase: 'pie-guion' },
    /* CON NOTAS SIN APLICAR ESTE BOTON SOBRA, y no por repetirse: es que hace
       MENOS. «Aplicar» reparte las notas, redibuja lo que toquen y despues
       monta el MP4; esto solo monta el MP4, o sea que gasta un render entero
       para dejarte el mismo video sin tus notas. Se queda, apagado y con el
       motivo puesto, en vez de esconderse: desaparecer no explica nada. */
    conAyuda(notasSinAplicar
      ? 'Tienes notas del repaso sin aplicar. Esto solo volveria a montar el MP4 '
        + 'y saldria igual, sin ellas. Usa «Aplicar los cambios» de abajo: '
        + 'aplica y monta, en un solo trabajo.'
      : (quedaTandaLight('render') === false
        ? 'El MP4 esta al dia con los planos y el audio de ahora. Volver a '
          + 'montarlo daria el mismo fichero.'
        : unirAyuda('Encadena los planos que ya has visto, con sus transiciones, '
          + 'la voz y la musica, y saca el MP4. No genera ninguna imagen: no '
          + 'cuesta dinero, cuesta tiempo de maquina.', textoDelPlan('render'))),
      h('button', {
        clase: notasSinAplicar ? 'mini' : 'primario',
        disabled: !!trabajoVideoLight() || notasSinAplicar
                  || quedaTandaLight('render') === false,
        onclick: () => lanzarTandaLight('render',
          (hayMp4Light() && !videoObsoletoLight()) ? 'todo' : 'pendientes'),
      }, hayMp4Light() ? 'Regenerar Vídeo' : 'Generar Vídeo')),
    quedaTandaLight('render') === false ? null : pastillaObsoletoLight(),
    h('span', { clase: 'crece' }),
    barraTandaLight('render'),
    trabajoVideoLight() ? conAyuda(
      'Corta el montaje donde este. Los clips ya encadenados se quedan hechos.',
      h('button', {
        clase: 'mini peligro', onclick: () => cancelar(CLAVE_VIDEO_LIGHT),
      }, 'Parar')) : null,
    /* EL MISMO ORDEN QUE EN EL GUION: a la izquierda lo que se le hace al
       video, en medio lo que esta pasando, y a la derecha lo que se hace CON el
       video ya montado. Estaba mezclado --boton, pastilla, progreso, aplicar,
       una frase suelta y descargar-- y no habia forma de leer los grupos. */
    h('span', { clase: 'crece' }),
    botonAplicarRepaso(),
    hayMp4Light() ? conAyuda(
      'Baja el MP4 tal y como esta ahora mismo.',
      h('a', {
        clase: 'boton mini', href: urlMp4Light(), download: '',
      }, 'Descargar')) : null);
  BARRA_INFERIOR.nodo = pie;

  /* EL REPASO VA DEBAJO DEL VÍDEO Y SOLO CUANDO HAY VÍDEO. Antes de eso no hay
     nada que comentar, y una caja de texto vacía debajo de una barra de
     progreso invita a escribir sobre algo que todavía no existe. */
  if (hayMp4Light() && !trabajoVideoLight()) caja.appendChild(panelRepaso());
  return caja;
}
/* ==========================================================================
   EL REPASO: escribir sobre el vídeo montado, y aplicarlo

   ES LA ÚLTIMA PANTALLA DEL SISTEMA Y LA PRIMERA QUE ES DE UNA PERSONA. Todo lo
   demás decide ANTES de ver el resultado; aquí se decide DESPUÉS, con el MP4
   delante, y de ahí salen sus dos reglas:

     · SE PAUSA Y SE ESCRIBE, y la nota se queda anclada AL SEGUNDO. No se elige
       un plano de una lista: se dice «aquí», y el servidor resuelve qué plano
       era contra los cortes de ESE montaje.
     · EL TEXTO ES OBLIGATORIO Y LA IMAGEN NO. Una referencia visual sin una
       frase no dice qué hay que hacer con ella — ¿el estilo?, ¿la
       composición?, ¿el objeto? — y adivinarlo es como se acaba regenerando lo
       que no había que tocar.

   Y una cosa que NO hace, a propósito: escribir una nota no deja el vídeo
   obsoleto. Las notas viven en su fichero (`repaso.json`), no en los params.
   Lo que toca las firmas es APLICAR, que es otro gesto y trae su coste. */

/* EL REPRODUCTOR DEL VÍDEO SOBREVIVE A UN REPINTADO, igual que el del guion y
   por un motivo más fuerte: aquí la pantalla se repinta cada vez que se abre la
   caja de una nota, se guarda una o se borra otra. Con un <video> nuevo en cada
   repintado, escribir una nota en el minuto tres te devolvía al segundo cero —o
   sea, justo el gesto que esta pantalla existe para hacer.

   Se reutiliza MIENTRAS SEA EL MISMO MP4: al regenerar, la URL cambia (lleva la
   versión) y entonces sí hace falta uno nuevo. */
let _videoLight = null;

function videoLight() {
  const url = urlMp4Light();
  if (!_videoLight || _videoLight.dataset.src !== url) {
    _videoLight = registrarReproductor(h('video', {
      controls: true, preload: 'metadata', src: url, datos: { src: url },
    }));
  }
  return _videoLight;
}

function estadoRepaso() {
  const v = videoAbierto();
  if (!v.repaso) {
    v.repaso = {
      notas: [], cortes: [], pendientes: 0, catalogo: null,
      cargando: false, texto: '', imagenes: [], t: 0, plano: '',
      abierto: false, editando: null,
    };
  }
  return v.repaso;
}

async function cargarRepaso(forzar) {
  const v = videoAbierto();
  const r = estadoRepaso();
  if (!v.pid || r.cargando || (r.cargado && !forzar)) return;
  r.cargando = true;
  try {
    const datos = await pedir(API.repaso(v.pid));
    r.notas = datos.notas || [];
    r.cortes = datos.cortes || [];
    r.pendientes = datos.pendientes || 0;
    r.catalogo = datos.catalogo || null;
    r.cargado = true;
  } catch (err) {
    /* que no se pueda leer el repaso no puede tapar el vídeo: se queda vacío */
    r.notas = [];
    r.cargado = true;
  }
  r.cargando = false;
  repintarVideo();
}

/* El plano que está en pantalla en ese segundo. Se calcula también aquí —el
   servidor lo vuelve a hacer al guardar— porque la tarjeta lo enseña ANTES de
   guardar: saber de qué plano estás hablando es la mitad de poder escribirlo. */
function planoEnRepaso(segundo) {
  const cortes = estadoRepaso().cortes || [];
  for (const corte of cortes) {
    if (Number(corte.t_in) <= segundo && segundo < Number(corte.t_out)) {
      return String(corte.id || '');
    }
  }
  return cortes.length ? String(cortes[cortes.length - 1].id || '') : '';
}

/* El <video> del repaso. Se guarda la referencia para poder pausarlo, saber por
   dónde va y saltar al segundo de una tarjeta. */
function videoDelRepaso() {
  return document.querySelector('.marco-video video');
}

function panelRepaso() {
  const v = videoAbierto();
  const r = estadoRepaso();
  if (!r.cargado && !r.cargando) cargarRepaso();

  const caja = h('div', { clase: 'repaso' });
  caja.appendChild(h('div', { clase: 'repaso-cab' },
    h('h3', {}, 'El repaso'),
    h('span', { clase: 'meta' },
      r.notas.length
        ? `${r.notas.length} ${r.notas.length === 1 ? 'nota' : 'notas'}`
          + (r.pendientes ? ` · ${r.pendientes} sin aplicar` : ' · todas aplicadas')
        : 'pausa donde algo no encaje y escríbelo')));

  caja.appendChild(botonComentar());
  if (r.abierto) caja.appendChild(cajaDeNota());
  if (r.notas.length) caja.appendChild(listaDeNotas());
  /* SIN PIE PROPIO: el boton de aplicar vive en la barra de abajo, que es la
     misma en las tres pantallas. Tenerlo aqui tambien eran dos botones para
     lo mismo a dos dedos de distancia. */
  return caja;
}

function botonComentar() {
  const r = estadoRepaso();
  return h('div', { clase: 'fila' },
    h('button', {
      clase: r.abierto ? 'mini' : 'primario',
      onclick: () => {
        const video = videoDelRepaso();
        if (video && !video.paused) video.pause();
        r.t = video ? video.currentTime : 0;
        r.plano = planoEnRepaso(r.t);
        r.abierto = !r.abierto;
        r.editando = null;
        repintarVideo();
      },
    }, r.abierto ? 'Cerrar' : '✎ Comentar este momento'),
    r.abierto ? null : h('span', { clase: 'meta' },
      'pausa el vídeo donde quieras y pulsa aquí'));
}

/* La caja de escribir: el texto (obligatorio) y las imágenes que se arrastren
   encima. Es el mismo gesto que en los estilos —arrastrar o pulsar— porque son
   la misma cosa: enseñar una referencia. */
function cajaDeNota() {
  const r = estadoRepaso();
  const caja = h('div', { clase: 'repaso-nueva' });
  caja.appendChild(h('div', { clase: 'meta' },
    `en ${mmss(r.t)}` + (r.plano ? ` · plano ${r.plano}` : '')));

  const area = h('textarea', {
    rows: 3, placeholder: 'qué no encaja aquí, en una frase',
    oninput: ev => { r.texto = ev.target.value; },
  });
  area.dataset.foco = 'nota-video';
  area.value = r.texto || '';
  caja.appendChild(cajaCampo(area));

  caja.appendChild(zonaImagenesRepaso());

  const guardar = h('button', { clase: 'primario', onclick: () => guardarNota() },
    r.editando ? 'Guardar' : 'Añadir la nota');
  caja.appendChild(h('div', { clase: 'fila' }, guardar,
    r.editando ? h('button', {
      clase: 'mini fantasma',
      onclick: () => { r.editando = null; r.texto = ''; r.imagenes = []; repintarVideo(); },
    }, 'Cancelar') : null));
  /* EL FOCO VA AL AREA, no al boton: se abre para escribir. Pero SOLO si no lo
     tiene ya: esto corre en cada pintado, y la pantalla se repinta sola cada
     segundo y medio, asi que forzarlo siempre devolvia el cursor al final de lo
     escrito en mitad de una frase. */
  setTimeout(() => {
    try {
      if (document.activeElement !== area) area.focus();
    } catch (e) { /* da igual */ }
  }, 0);
  return caja;
}

function zonaImagenesRepaso() {
  const r = estadoRepaso();
  return zonaDeImagenes('repaso-imagenes', {
    leer: () => r.imagenes || [],
    escribir: nombres => { r.imagenes = nombres; },
  });
}

/* UNA ZONA DE ADJUNTAR IMÁGENES A UNA NOTA, la misma en el vídeo montado y en
   el feedback de cada imagen: se sueltan o se eligen, se suben al momento
   (`/repaso/imagenes`, a la carpeta del proyecto) y quedan como miniaturas
   con su aspa. `lista.leer` y `lista.escribir` dicen dónde vive la lista de
   nombres (van en un objeto y no sueltos: el analizador de huérfanas no ve
   los parámetros del medio y daba `leer()` por una llamada a nada). */
function zonaDeImagenes(id, lista) {
  const v = videoAbierto();
  const caja = h('div', { clase: 'campo aportadas' });
  const tira = h('div', { clase: 'tira-aportadas' });

  const pintar = () => {
    vaciar(tira);
    lista.leer().forEach(nombre => {
      tira.appendChild(h('div', { clase: 'aportada' },
        h('img', { src: API.imagenRepaso(v.pid, nombre), alt: '', loading: 'lazy' }),
        h('button', {
          clase: 'quitar', title: 'quitar esta imagen',
          onclick: () => { lista.escribir(lista.leer().filter(x => x !== nombre)); pintar(); },
        }, '×')));
    });
  };
  const subir = ficheros => subirImagenesDeNota(ficheros).then(nombres => {
    if (nombres.length) { lista.escribir(lista.leer().concat(nombres)); pintar(); }
  });

  const entrada = h('input', {
    type: 'file', accept: 'image/png,image/jpeg,image/webp', multiple: true,
    clase: 'oculto', id,
    onchange: ev => {
      const ficheros = [...(ev.target.files || [])];
      ev.target.value = '';
      subir(ficheros);
    },
  });
  const suelta = h('label', { clase: 'zona-suelta', for: id },
    h('span', { clase: 'icono' }, '🖼'),
    h('span', {}, 'Arrastra una referencia aquí (opcional)'));
  ['dragenter', 'dragover'].forEach(ev => suelta.addEventListener(ev, evento => {
    evento.preventDefault();
    suelta.classList.add('encima');
  }));
  ['dragleave', 'drop'].forEach(ev => suelta.addEventListener(ev, evento => {
    evento.preventDefault();
    suelta.classList.remove('encima');
  }));
  suelta.addEventListener('drop', evento => {
    const ficheros = [...((evento.dataTransfer || {}).files || [])];
    if (ficheros.length) subir(ficheros);
  });

  caja.appendChild(suelta);
  caja.appendChild(entrada);
  caja.appendChild(tira);
  pintar();
  return caja;
}

/* Sube las imágenes de una nota y devuelve sus nombres en el servidor. */
async function subirImagenesDeNota(ficheros) {
  const v = videoAbierto();
  const imagenes = ficheros.filter(f => /^image\//.test(f.type || ''));
  if (!imagenes.length) {
    toast('Solo imágenes', true);
    return [];
  }
  const cuerpo = new FormData();
  imagenes.forEach(f => cuerpo.append('imagenes', f));
  try {
    const datos = await pedir(API.imagenesRepaso(v.pid), { method: 'POST', cuerpo });
    (datos.avisos || []).forEach(aviso => toast(aviso, true));
    return (datos.imagenes || []).map(i => i.nombre);
  } catch (fallo) {
    toast(`no se han podido subir: ${fallo.message}`, true);
    return [];
  }
}

async function guardarNota() {
  const r = estadoRepaso();
  const v = videoAbierto();
  const texto = String(r.texto || '').trim();
  if (!texto) {
    toast('Escribe qué no encaja: una imagen sola no dice qué hacer con ella', true);
    return;
  }
  try {
    const datos = r.editando
      ? await pedir(API.repasoNota(v.pid, r.editando), {
        method: 'PUT', cuerpo: { texto, imagenes: r.imagenes },
      })
      : await pedir(API.repaso(v.pid), {
        method: 'POST',
        cuerpo: { texto, t: r.t, plano: r.plano, imagenes: r.imagenes },
      });
    r.notas = datos.notas || [];
    r.pendientes = datos.pendientes || 0;
    r.texto = '';
    r.imagenes = [];
    r.editando = null;
    r.abierto = false;
    repintarVideo();
  } catch (fallo) {
    toast(fallo.message, true);
  }
}

/* Las tarjetas, EN ORDEN DE VÍDEO. No en orden de escritura: el repaso se lee
   con el vídeo delante, y una lista que salta de 4:10 a 0:30 no se puede
   seguir. Pulsar el minuto salta ahí. */
/* IR AL MOMENTO DE UNA NOTA, DESDE DONDE SEA.
 *
 * La misma lista se ensena en las dos pantallas y «ese momento» no es lo mismo
 * en cada una: en el video es un SEGUNDO del reproductor y en las diapositivas
 * es una ESCENA. La nota guarda las dos cosas --`t` y `plano`--, asi que no hay
 * que elegir al escribirla: se elige al pulsar, segun donde estes.
 *
 * Si la nota no dice de que plano es --se anclo al segundo y el servidor no
 * resolvio ninguno-- desde las diapositivas no hay a donde ir, y se avisa en vez
 * de saltar a una escena cualquiera. */
/* ============================== REGENERAR UNA IMAGEN, DE UNA EN UNA
 *
 * Escribes que falla en un plano y ESA imagen se rehace ya, sin esperar a
 * juntar diez notas. La siguiente que pidas se pone en cola detras.
 *
 * LA COLA ES DE UNA EN UNA Y NO ES UNA ELECCION DE ESTILO: el servidor
 * contesta 409 a un segundo trabajo del MISMO paso (ver `ejecutar_paso` en
 * app.py), asi que lanzar dos a la vez seria lanzar una y perder la otra. Se
 * encolan aqui y se sueltan segun se libera el sitio.
 *
 * Y NO PASA POR EL ENRUTADOR. En esta pantalla una nota significa siempre lo
 * mismo -- «redibuja este plano» -- asi que no hay nada que clasificar: el
 * texto se escribe en el feedback de esa unidad y se relanza `assets` sobre
 * ella. El enrutador se queda para el repaso del video, donde una nota puede
 * ser de la cartela, del subtitulo, de la musica o del guion.
 */
/* CUANTAS A LA VEZ. Tres, que son las claves de imagen que hay: por debajo se
   desaprovechan y por encima solo se hacen colas dentro del cubo de ritmo del
   motor (ver MAX_CADENAS en p6_assets).

   Van en UN trabajo, no en tres: el servidor no admite dos tandas del mismo
   paso a la vez --y hace bien, las dos escribirian el mismo plan y la misma
   carpeta-- pero el paso SI dibuja en paralelo por dentro, una cadena por
   sitio. Asi que el paralelismo se pide mandando los tres planos juntos. */
const A_LA_VEZ = 3;

/* `corriendo` es una LISTA, no un plano: son los que van en la tanda de ahora.
   Y `espera` guarda {sid, texto}, asi que se busca por su sid -- preguntando
   `espera.includes(sid)` no casaba NUNCA, que es lo que hacia que pulsar un
   segundo boton no pareciera hacer nada: la nota entraba en la cola y el boton
   seguia diciendo «Regenerar imagen». */
/* `corriendo` guarda {sid, nid}: QUE plano y DE QUE nota. Iba solo con el
   plano, y entonces dos notas del mismo plano se creian las dos en marcha --
   la que ya estaba hecha volvia a decir «Regenerando». Lo que se ocupa es la
   imagen, pero lo que se cuenta es la peticion.

   Y NO HAY MAPA DE «HECHAS»: el visto lo dice la nota (`regenerado`), que la
   escribe el servidor nada mas terminar. Un mapa en memoria por id era una
   trampa, porque los ids DE NOTA SE RECICLAN --borra R001 y la siguiente vuelve
   a llamarse R001-- y el visto de una nota borrada se lo quedaba la nueva: una
   nota recien escrita salia «Regenerada ✓» sin haberse dibujado nunca. */
const COLA_IMG = { espera: [], corriendo: [], fallo: {} };


/* EL ✓ LO DICE LA NOTA, Y LO ESCRIBE EL SERVIDOR (`regenerado`: contra qué
   texto se redibujó). Así sobrevive a recargar, y si luego cambias la nota deja
   de coincidir ella sola -- que es lo que se quiere: hay una petición nueva que
   nadie ha atendido.

   Aquí hubo dos intentos peores. Un mapa por PLANO hacía que, en cuanto S064 se
   redibujaba una vez, cualquier nota sobre S064 saliera con el visto. Y un mapa
   por id de NOTA tampoco vale: los ids se reciclan --borra R001 y la siguiente
   vuelve a llamarse R001--, así que cada nota nueva heredaba el visto de una
   borrada y salía «Regenerada ✓» sin haberse dibujado nunca. */
function estadoDeImagen(sid, nota) {
  const nid = (nota || {}).id || '';
  if (nid && COLA_IMG.corriendo.some(x => x.nid === nid)) return 'corriendo';
  if (nid && COLA_IMG.espera.some(x => x.nid === nid)) return 'en cola';
  if (nid && COLA_IMG.fallo[nid]) return 'fallo';
  if (nota && nota.regenerado && nota.regenerado === nota.texto) return 'hecha';
  /* AL RETOMAR TRAS RECARGAR solo se sabe que PLANO lleva el trabajo, no de que
     nota salio. Se pinta como en marcha la que NO esta hecha, que es la unica
     que puede ser: la de arriba ya devolvio 'hecha'. */
  if (COLA_IMG.corriendo.some(x => !x.nid && x.sid === sid)) return 'corriendo';
  return '';
}


/* TODAS LAS DE ESTA PANTALLA, DE UNA VEZ. Es el mismo gesto que pulsar el boton
   de cada tarjeta, repetido: entran en la misma cola y salen de una en una. */
function encolarTodasLasImagenes() {
  notasDeAhora()
    .filter(n => n.estado !== 'aplicado' && n.plano)
    .forEach(n => encolarImagen(n.plano, n.texto, n.id));
}


function encolarImagen(sid, texto, nid) {
  if (!sid) return;
  /* NO SE REPITE LA MISMA NOTA. Antes se miraba el plano, asi que una segunda
     nota sobre la misma imagen no entraba en la cola y pulsarla no hacia nada.
     Dos notas del mismo plano son dos peticiones: entran las dos y salen una
     detras de otra (ver el reparto de tandas en `soltarCola`). */
  if (nid && (COLA_IMG.corriendo.some(x => x.nid === nid)
              || COLA_IMG.espera.some(x => x.nid === nid))) return;
  if (nid) delete COLA_IMG.fallo[nid];
  COLA_IMG.espera.push({ sid, texto: String(texto || ''), nid: nid || '' });
  repintarVideo();
  soltarCola();
}


/* LO QUE SE ACABA DE DIBUJAR, PUESTO EN SU SITIO. Y NADA MAS.
 *
 * Aqui se llamaba a `cargarVideoLight`, que recarga el proyecto ENTERO: vuelve
 * a pedir las fichas de los pasos, el guion, el audio, para la reproduccion
 * (`pararPrevia`) y tira la previa (`PREVIA.ficha = null`), asi que la pantalla
 * se quedaba en «preparando las escenas…» cada vez que acababa UNA imagen. Si
 * estabas escribiendo el feedback del plano siguiente, te lo llevaba por
 * delante.
 *
 * Lo unico que de verdad cambia al terminar es la RUTA de las imagenes --cada
 * tanda publica una version nueva y las imagenes viven dentro de ella-- y el
 * estado del paso. Se piden esas dos cosas y se escriben ENCIMA de lo que ya
 * hay, sin vaciar nada: la escena que estabas mirando sigue donde estaba, el
 * borrador que llevabas escrito sigue ahi y el audio no se corta.
 */
async function refrescarLoDibujado() {
  const v = videoAbierto();
  if (!v.pid) return;
  const pid = v.pid;
  try {
    const fresca = await pedir(`${API.proyecto(pid)}/previsualizacion`);
    if (videoAbierto().pid !== pid) return;      // se cambio de video mientras
    if (!PREVIA.ficha) PREVIA.ficha = fresca;
    else {
      const suyas = {};
      (fresca.escenas || []).forEach(e => { suyas[e.id] = e; });
      const mismas = (PREVIA.ficha.escenas || []).length === (fresca.escenas || []).length
        && (PREVIA.ficha.escenas || []).every(e => suyas[e.id]);
      /* SI EL CORTE HA CAMBIADO no se parchea plano a plano: se cambia la ficha
         entera. Parchear dejaria la mitad de una lista y la mitad de la otra,
         que es peor que recargar. Tampoco se vacia antes, asi que no aparece el
         «preparando las escenas…». */
      if (!mismas) PREVIA.ficha = fresca;
      else {
        (PREVIA.ficha.escenas || []).forEach(e => {
          const suya = suyas[e.id];
          e.imagen = suya.imagen;
          if (suya.obsoleta) { e.obsoleta = true; e.dibujada_para = suya.dibujada_para; }
          else { delete e.obsoleta; delete e.dibujada_para; }
        });
        PREVIA.ficha.con_cartelas = fresca.con_cartelas;
      }
    }
  } catch (err) { /* sin previa nueva se sigue viendo la de antes */ }
  /* Y la ficha del paso, que es la que sabe si el video quedo obsoleto: sin
     esto «Montar el vídeo» seguiria diciendo que esta al dia. Es una llamada,
     no las seis de recargar el proyecto. */
  try {
    const ficha = await pedir(API.paso(pid, 'assets'));
    if (videoAbierto().pid === pid) videoAbierto().fichas.assets = ficha;
  } catch (err) { /* igual: no poder leerla no puede tumbar la pantalla */ }
}

/* SE ESCRIBE EN LA NOTA QUE SU IMAGEN YA SE REHIZO, y con qué texto. Es lo que
   hace que el «Regenerada ✓» siga ahí mañana. Va después del trabajo, no antes:
   si la tanda falla, la nota tiene que seguir pidiendo lo suyo. */
async function apuntarRegeneradas(tanda) {
  const v = videoAbierto();
  let ultima = null;
  for (const x of tanda) {
    if (!x.nid) continue;
    try {
      ultima = await pedir(API.repasoNota(v.pid, x.nid), {
        method: 'PUT', cuerpo: { regenerado: x.texto },
      });
    } catch (err) { /* no poder marcarla no puede tirar la cola */ }
  }
  if (ultima) guardarRepaso(ultima);
}

async function soltarCola() {
  if (COLA_IMG.corriendo.length || !COLA_IMG.espera.length) return;
  const v = videoAbierto();
  /* UN PLANO, UNA VEZ POR TANDA. Dos notas de la misma imagen son dos
     peticiones, pero no pueden ir en el mismo trabajo: la segunda pisaria el
     feedback de la primera y se dibujaria una sola vez. La que sobra se queda
     en la cola y sale en la tanda siguiente. */
  const tanda = [];
  const puestos = new Set();
  while (tanda.length < A_LA_VEZ) {
    const i = COLA_IMG.espera.findIndex(x => !puestos.has(x.sid));
    if (i < 0) break;
    puestos.add(COLA_IMG.espera[i].sid);
    tanda.push(COLA_IMG.espera.splice(i, 1)[0]);
  }
  if (!tanda.length) return;
  COLA_IMG.corriendo = tanda.map(x => ({ sid: x.sid, nid: x.nid || '' }));
  repintarVideo();
  try {
    /* EL TEXTO VA AL FEEDBACK DE ESA UNIDAD, que es el cajon que ya lee quien
       dibuja (`_ajustes_unidad` en p6_assets). Ni un cajon nuevo.

       Los de la tanda van en UNA sola llamada: son params del mismo paso, y
       mandarlos de uno en uno son tres escrituras del estado que se pisan el
       cerrojo entre ellas para decir lo mismo. */
    const conTexto = tanda.filter(x => x.texto);
    if (conTexto.length) {
      const unidades = {};
      conTexto.forEach(x => { unidades[`escena:${x.sid}`] = { feedback: x.texto }; });
      await pedir(API.params(v.pid, 'assets'), {
        method: 'PUT', cuerpo: { params: { unidades } },
      });
    }
    /* `rehacer: true` a proposito: aqui SI lo estas pidiendo, y con el mismo
       prompt la cache devolveria la imagen que acabas de rechazar. */
    const datos = await pedir(API.ejecutar(v.pid, 'assets'), {
      method: 'POST',
      cuerpo: { unidades: tanda.map(x => `escena:${x.sid}`), rehacer: true },
    });
    const tid = datos.trabajo_id || (datos.trabajo || {}).id;
    if (!tid) throw new Error('el servidor no ha devuelto ningún trabajo');
    seguirTrabajo(CLAVE_VIDEO_LIGHT, tid, async trabajo => {
      if (trabajo.estado === 'listo') {
        await apuntarRegeneradas(tanda);
      } else if (trabajo.estado === 'error') {
        tanda.forEach(x => { if (x.nid) COLA_IMG.fallo[x.nid] = trabajo.error || 'fallo'; });
      }
      if (trabajo.estado !== 'ejecutando') {
        COLA_IMG.corriendo = [];
        await refrescarLoDibujado();
        repintarVideo();
        soltarCola();
      }
    }, () => refrescarVivosLight());
  } catch (err) {
    tanda.forEach(x => { if (x.nid) COLA_IMG.fallo[x.nid] = err.message; });
    COLA_IMG.corriendo = [];
    repintarVideo();
    soltarCola();
  }
}


function irAlMomentoDeLaNota(nota) {
  const v = videoAbierto();
  if (v.vista === 'previa') {
    const escenas = (PREVIA.ficha || {}).escenas || [];
    const i = escenas.findIndex(e => e.id === nota.plano);
    if (i < 0) {
      toast('esa nota no esta anclada a ninguna escena', true);
      return;
    }
    pararPrevia();
    PREVIA.i = i;
    repintarVideo();
    return;
  }
  const video = videoDelRepaso();
  if (video) { video.currentTime = Number(nota.t) || 0; video.pause(); }
}


function listaDeNotas() {
  const r = estadoRepaso();
  const v = videoAbierto();
  const lista = h('div', { clase: 'repaso-notas' });
  const enPrevia = v.vista === 'previa';
  notasDeAhora().forEach(nota => {
    /* EDITANDO Y EN LAS DIAPOSITIVAS, manda el editor EN LINEA que ya existe
       (`filaNotaEscena`). El boton de editar de esta lista abre el panel del
       repaso, y ese panel solo se pinta en la pantalla del video: desde aqui
       habria dejado la nota «en edicion» sin ninguna caja donde escribirla. */
    if (enPrevia && PREVIA.editando === nota.id) {
      lista.appendChild(filaNotaEscena(nota));
      return;
    }
    const aplicada = nota.estado === 'aplicado';
    /* HECHA Y SIN MIRAR: se queda encendida y en azul hasta que se pulsa el
       botón de ir a su plano. Ver `sinRevisar`. */
    const porMirar = sinRevisar(nota);
    const tarjeta = h('div', {
      clase: 'repaso-nota' + (aplicada ? ' aplicada' : '')
        + (porMirar ? ' sin-revisar' : ''),
    });
    tarjeta.appendChild(h('div', { clase: 'fila' },
      h('button', {
        clase: 'mini fantasma',
        title: (porMirar ? 'ya está hecha: ' : '')
          + (videoAbierto().vista === 'previa'
            ? 'ir a esa diapositiva' : 'ir a ese momento del vídeo'),
        onclick: () => { darPorRevisada(nota); irAlMomentoDeLaNota(nota); },
      }, videoAbierto().vista === 'previa' && nota.plano
         ? nota.plano : mmss(nota.t)),
      nota.plano ? h('span', { clase: 'meta' }, nota.plano) : null,
      porMirar ? h('span', {
        clase: 'sin-ver',
        title: 'ya se ha aplicado y todavía no la has mirado. Pulsa el plano '
          + 'de la izquierda para verla; ahí deja de marcarse.',
      }, 'sin revisar') : null,
      aplicada ? h('span', { clase: 'meta' }, '· aplicada') : null,
      /* SE DICE CUANDO UNA NOTA SE HA MOVIDO O SE HA PERDIDO. Al regrabar la
         voz los planos se renumeran y una nota puede acabar senalando otro:
         el servidor la vuelve a colocar por lo que decia, y si no encuentra
         donde, lo dice en vez de dejarla apuntando a cualquier sitio. */
      nota.reanclada ? h('span', {
        clase: 'meta', title: `estaba en ${nota.reanclada}: los planos se han `
          + 'renumerado y se ha vuelto a colocar por lo que se dice en él',
      }, '· recolocada') : null,
      /* «SIN PLANO» DECÍA OTRA COSA. La nota SÍ tiene plano y ese plano existe;
         lo que no se ha podido comprobar es que siga diciendo lo mismo. Con la
         etiqueta anterior, una nota perfectamente sana parecía rota. */
      nota.descolgada ? h('span', {
        clase: 'pastilla aviso',
        title: 'lo que se decía en este plano cuando escribiste la nota ya no '
          + 'está en el vídeo, así que no se ha podido comprobar que siga '
          + 'siendo el suyo. La imagen y el plano están bien; mírala antes de '
          + 'aplicarla.',
      }, 'el texto cambió') : null,
      h('span', { clase: 'crece' }),
      /* REGENERAR ESTA IMAGEN, YA. Solo en la pantalla de Imagenes: en el
         repaso del video las notas no tocan dibujos. El estado se ensena en el
         propio boton porque es donde se mira despues de pulsarlo. */
      /* VIVO: es lo unico de la tarjeta que cambia mientras la imagen se
         rehace («Regenerando 42 %»). Repintar la lista entera en cada tic era
         repintar el cuadro de feedback que se esta usando. */
      enPrevia ? enVivo(() => {
        const est = estadoDeImagen(nota.plano, nota);
        const trabajo = APP.trabajos[CLAVE_VIDEO_LIGHT] || {};
        const pct = Math.round((Number(trabajo.progreso) || 0) * 100);
        return conAyuda(
          est === 'hecha'
            ? 'Ya se ha vuelto a dibujar. Pulsa el plano de la izquierda para '
              + 'verla.'
            : est === 'en cola'
              ? 'Esperando turno. Entra en cuanto acabe alguna de las que van '
                + 'ahora.'
              : 'Vuelve a dibujar SOLO este plano con lo que has escrito. Se '
                + 'hacen hasta tres a la vez; si pides mas, esperan turno.',
          h('button', {
            clase: est === 'hecha' ? 'mini' : 'mini avisa',
            disabled: !nota.plano || est === 'corriendo' || est === 'en cola',
            onclick: () => encolarImagen(nota.plano, nota.texto, nota.id),
          }, est === 'corriendo' ? `Regenerando ${pct} %`
             : est === 'en cola' ? 'En cola'
             : est === 'hecha' ? 'Regenerada ✓'
             : est === 'fallo' ? 'Reintentar'
             : 'Regenerar imagen'));
      }) : null,
      h('button', {
        clase: 'mini fantasma', title: 'editar',
        onclick: () => {
          if (enPrevia) { PREVIA.editando = nota.id; repintarVideo(); return; }
          r.editando = nota.id;
          r.texto = nota.texto;
          r.imagenes = (nota.imagenes || []).slice();
          r.t = Number(nota.t) || 0;
          r.plano = nota.plano || '';
          r.abierto = true;
          repintarVideo();
        },
      }, '✎'),
      h('button', {
        clase: 'mini peligro', title: 'borrar',
        onclick: () => borrarNota(nota.id),
      }, '×')));
    tarjeta.appendChild(h('div', { clase: 'texto' }, nota.texto));
    if ((nota.imagenes || []).length) {
      const tira = h('div', { clase: 'tira-aportadas' });
      nota.imagenes.forEach(nombre => tira.appendChild(h('img', {
        src: API.imagenRepaso(v.pid, nombre), alt: '', loading: 'lazy',
      })));
      tarjeta.appendChild(tira);
    }
    lista.appendChild(tarjeta);
  });
  return lista;
}

async function borrarNota(nid) {
  const r = estadoRepaso();
  const v = videoAbierto();
  try {
    const datos = await pedir(API.repasoNota(v.pid, nid), { method: 'DELETE' });
    r.notas = datos.notas || [];
    r.pendientes = datos.pendientes || 0;
    repintarVideo();
  } catch (fallo) {
    toast(fallo.message, true);
  }
}

/* El pie: UN botón. Lo que hace por dentro son tres cosas —repartir las notas
   en cambios, escribirlos y volver a generar lo justo— y desde aquí es un
   gesto, porque encadenarlas en el navegador se rompe al recargar. */
/* EL BOTON DE APLICAR. Mismo sitio y misma pinta en las dos pantallas, pero NO
   hace lo mismo, porque no son el mismo cuaderno:

     Imagenes  encola todas sus notas y va rehaciendo esas imagenes, una a una.
               No hay nada que clasificar: aqui una nota siempre significa
               «redibuja este plano».

     Video     se las pasa al enrutador, que reparte cada una en su cambio --
               cartela, subtitulo, transicion, musica o efectos -- y despues
               monta el MP4. */
function botonAplicarRepaso() {
  const pend = pendientesDeAhora();
  if (!pend) return null;
  const corriendo = (APP.trabajos[CLAVE_VIDEO_LIGHT] || {}).estado === 'ejecutando';
  return conAyuda(
    (videoAbierto().vista === 'previa'
      ? 'Pone en cola todas las notas de esta pantalla y va rehaciendo esas '
        + 'imagenes, una a una. Puedes seguir mirando mientras: cada tarjeta '
        + 'dice por donde va la suya.'
      : 'Se aplica lo mas barato que resuelve cada nota: bajar la musica vuelve '
        + 'a mezclar el audio, cambiar una cartela redibuja una capa, y solo se '
        + 'repaga una imagen si de verdad hay que volver a dibujar ese plano. '
        + 'Al terminar, monta el MP4 con los cambios dentro.'),
    h('button', {
      clase: 'avisa', disabled: corriendo,
      onclick: () => (cuadernoDeAhora() === 'imagenes'
        ? encolarTodasLasImagenes() : aplicarRepaso()),
    }, `Aplicar ${pend} ${pend === 1 ? 'cambio' : 'cambios'}`));
}


async function aplicarRepaso() {
  const v = videoAbierto();
  const r = estadoRepaso();
  if (!v.pid) return;
  limpiarError(CLAVE_VIDEO_LIGHT);
  try {
    /* DESDE LAS DIAPOSITIVAS SE APLICA Y SE PARA. Lo que se acaba de arreglar
       se mira ahi mismo, que es donde se escribio la nota; montar el MP4 es el
       paso siguiente y el caro. Desde la pantalla del video no: alli aplicar y
       montar son el mismo gesto, porque lo que se mira ES el montaje. */
    const datos = await pedir(API.repasoAplicar(v.pid), {
      method: 'POST', cuerpo: { sin_montar: v.vista === 'previa' },
    });
    const tid = datos.trabajo_id || (datos.trabajo || {}).id;
    if (!tid) throw new Error('el servidor no ha devuelto ningún trabajo');
    seguirTrabajo(CLAVE_VIDEO_LIGHT, tid, async trabajo => {
      if (trabajo.estado === 'listo') {
        await recargarVideoAbierto();
        await cargarRepaso(true);
        /* LAS DIAPOSITIVAS SE VUELVEN A PEDIR. Aplicar puede haber redibujado
           un plano, y si se aplica DESDE esa pantalla lo primero que se hace
           al terminar es mirarla: dejarla con la imagen de antes ensenaria la
           nota como aplicada encima del dibujo que la motivo. */
        PREVIA.ficha = null;
        await refrescarNotasPrevia();
        const ficha = trabajo.resultado || {};
        (ficha.avisos || []).forEach(aviso => toast(aviso, true));
      }
      repintarVideo();
    }, () => {
      refrescarPlanosLight();
      refrescarVivosLight();
    });
    r.abierto = false;
    repintarVideo();
  } catch (err) {
    mostrarError(CLAVE_VIDEO_LIGHT, err);
    repintarVideo();
  }
}


/* ------------------------------------------------------- crear un estilo */

/* CUATRO CAJAS, UNA DEBAJO DE OTRA Y A TODO EL ANCHO.
 *
 * Estuvo en una columna de 640 px con un párrafo debajo de cada campo: cuatro
 * pantallas de scroll con media pantalla vacía al lado para decir cuatro cosas.
 * Ahora cada caja ocupa el ancho entero y se parte en dos DENTRO: a la
 * izquierda qué es (en media línea), a la derecha el campo. Se lee en
 * diagonal y cabe todo el encargo sin scroll.
 *
 * Y el botón NO va pegado al scroll. Una barra que persigue tapa justo lo que
 * estás rellenando; abajo del todo, después de la última caja, es donde se
 * espera encontrarlo cuando has terminado. */
function vistaCrearLight() {
  const e = encargoLight();
  const caja = h('div', { clase: 'light-form' });
  caja.appendChild(h('div', { clase: 'light-cab' },
    h('button', {
      clase: 'mini fantasma', title: 'Volver a tus estilos',
      onclick: () => irALight('galeria'),
    }, '‹ Volver'),
    h('h2', {}, 'Un estilo nuevo')));

  caja.appendChild(campoTexto('Nombre', e.nombre,
    v => { e.nombre = v; tocarEncargoLight(); },
    { pista: 'Cartoon' }));

  const cajas = h('div', {});

  cajas.appendChild(bloqueLight('🎨 Estilo gráfico',
    'las imágenes, las cartelas y los subtítulos', camposEstiloLight()));

  /* EL TONO SE ESCRIBE, y con eso basta: no hay nada que copiar de ningún
     sitio, hay algo que decidir. De este párrafo salen las instrucciones con
     las que se redacta cada guion del canal, así que cuanto más concreto sea
     menos se lo inventa. */
  cajas.appendChild(bloqueLight('🗣️ Tono del guion', 'cómo se cuenta, nunca de qué',
    campoArea('', e.tono_prompt, v => { e.tono_prompt = v; tocarEncargoLight(); },
      'como quien te lo cuenta en la barra de un bar y del tema sabe más que tú: '
      + 'frases cortas, sin adjetivos de relleno, los datos hablan solos')));

  /* EL RITMO VA ANTES QUE LA VOZ, y no es orden estético: el ritmo entra en la
     decisión de la voz —«el montaje va a planos de 2 s»— y además le rellena la
     velocidad si tú no la pides. Decidirlo después sería decidirlo al revés. */
  cajas.appendChild(bloqueLight('⏱️ Ritmo', 'cada cuánto corta el vídeo',
    sliderRitmo(e.ritmo, v => { e.ritmo = v; tocarEncargoLight(); })));

  cajas.appendChild(bloqueLight('🎙️ Voz', 'quién lo locuta',
    campoArea('', e.voz_prompt, v => { e.voz_prompt = v; tocarEncargoLight(); },
      'grave, pausada, sin sonar a locutor de anuncio'),
    selectorVozPropiaLight(e)));

  cajas.appendChild(bloqueLight('🌐 Idioma', 'se cambia luego sin regenerar nada',
    campoSelect('', e.idioma,
      idiomasLight().map(i => ({ valor: i.valor, nombre: i.nombre })),
      v => { e.idioma = v; tocarEncargoLight(); })));

  caja.appendChild(cajas);
  caja.appendChild(pieDeCreacion());
  return caja;
}

/* Una caja: a la izquierda QUÉ es, a la derecha el campo. Las dos columnas son
   de la caja y no de la pantalla — la pantalla es una sola columna a todo el
   ancho — y en vertical se apilan solas. */
function bloqueLight(titulo, porque, ...contenido) {
  return h('div', { clase: 'bloque-light' },
    h('div', { clase: 'titulo' },
      h('h3', {}, titulo),
      porque ? h('span', { clase: 'meta' }, porque) : null),
    h('div', { clase: 'mandos' }, ...contenido));
}

/* HASTA CINCO VÍDEOS PARA EL TONO, y la razón de que sean varios no es
   «cuantos más mejor»: con uno solo lo que se describe es cómo estaba ese día
   quien lo narró. Con cuatro o cinco, lo que el modelo puede describir es lo
   que TIENEN EN COMÚN, que es justamente el tono del canal.

   Y hay una segunda razón, que es nueva: las transcripciones ya no se tiran
   después de leerlas. Se guardan en el banco del canal y viajan con el estilo,
   así que el guionista de CADA vídeo las lee enteras. La guía de tono dice cómo
   se habla en un párrafo; esto es oírlo.

   Una fila por vídeo, con su papelera, y el «+ Otro vídeo» en cuanto la última
   fila tiene algo. El botón se refresca EN SITIO y no repintando el formulario:
   escribir dispara `input` en cada tecla, y repintar ahí tira el foco del campo
   donde estás pegando — que es exactamente por lo que nunca aparecía.

   Las mismas filas sirven para CREAR y para CAMBIAR LA FUENTE al editar
   (`fuenteDeTonoLight`): por eso reciben el objeto dueño y la clave, en vez de
   leer el encargo ellas mismas. */
/* EL ESTILO GRÁFICO NO SE DESCRIBE: SE COPIA DE ALGO.
 *
 * Un vídeo o unas imágenes, y una de las dos hace falta. De un párrafo solo, la
 * guía se inventa todo lo que el párrafo no diga —que es casi todo—, así que
 * describirlo a secas dejó de ser un camino.
 *
 * Lo escrito se queda, pero en su sitio: OPCIONAL y en los dos caminos, para lo
 * que el material no puede decir por sí solo («este canal pero más frío»,
 * «esto pero sin personajes»). Va después del material a propósito: es una
 * indicación sobre lo que se ve, no la fuente. */
/* EL ESTILO GRÁFICO: LAS IMÁGENES MANDAN Y LO ESCRITO ACOMPAÑA.
 *
 * Se adjuntan imágenes que YA tengan el aspecto que se quiere y la guía se
 * escribe mirándolas. Las indicaciones son opcionales y sirven para lo que una
 * imagen no puede decir sola —«esto pero más frío»—, no para sustituirlas: de
 * un párrafo suelto se inventa todo lo que el párrafo no diga, y eso se paga
 * en cada plano del vídeo. */
function camposEstiloLight() {
  const e = encargoLight();
  const caja = h('div', {});
  caja.appendChild(imagenesDeApoyoLight(e, tocarEncargoLight));
  caja.appendChild(campoArea('Indicaciones (opcional)', e.estilo_prompt,
    v => { e.estilo_prompt = v; tocarEncargoLight(); },
    'igual pero más frío, con menos detalle en los fondos'));
  return caja;
}

/* LAS IMÁGENES QUE ACOMPAÑAN A LA DESCRIPCIÓN.
 *
 * El camino del vídeo le da a la guía veinticuatro fotogramas que mirar; el
 * descrito le daba un párrafo y nada más. Aquí se pueden adjuntar hasta las
 * MISMAS veinticuatro —el tope lo dice el servidor, que es donde vive— como
 * material de apoyo: manda lo escrito y esto lo concreta.
 *
 * Se suben AL ELEGIRLAS y no al pulsar «Generar»: el taller no existe hasta
 * entonces, así que esperan en un buzón del servidor y lo que se guarda aquí es
 * el nombre con el que quedaron. Subirlas al final habría dejado el botón
 * pensando mientras viajan diez megas. */
function imagenesDeApoyoLight(e, alCambiar, idHueco, opciones) {
  // `clave` es la lista de `e` que se llena: las del estilo por defecto, las
  // fotos de un personaje cuando se pide (ver editorDePersonajesLight)
  const op = opciones || {};
  const clave = op.clave || 'estilo_imagenes';
  e[clave] = e[clave] || [];
  alCambiar = alCambiar || (() => {});
  // el <label for> necesita un id UNICO: con dos bloques en la misma pantalla
  // --el de crear y el de editar-- el segundo abriria el selector del primero
  const id = idHueco || 'aportadas-estilo';
  const tope = op.tope || (APP.light.datos || {}).max_imagenes_estilo || 24;
  const caja = h('div', { clase: 'campo aportadas' });
  const tira = h('div', { clase: 'tira-aportadas' });
  const estado = h('span', { clase: 'meta' });

  const pintar = () => {
    vaciar(tira);
    e[clave].forEach(ficha => {
      tira.appendChild(h('div', { clase: 'aportada', title: ficha.origen || '' },
        h('img', { src: API.imagenLight(ficha.nombre), alt: '', loading: 'lazy' }),
        h('button', {
          clase: 'quitar', title: 'quitar esta imagen',
          onclick: () => quitarImagenLight(e, ficha, pintar, alCambiar, clave),
        }, '×')));
    });
    estado.textContent = e[clave].length
      ? `${e[clave].length} de ${tope}`
      : `hasta ${tope}`;
    // llena: el input deshabilitado ya impide que el <label> abra el
    // explorador, pero sin decirlo la zona seguiría invitando a pulsarla
    const llena = e[clave].length >= tope;
    if (entrada) entrada.disabled = llena;
    if (suelta) suelta.classList.toggle('llena', llena);
  };

  const entrada = h('input', {
    type: 'file', accept: 'image/png,image/jpeg,image/webp', multiple: true,
    clase: 'oculto', id: id,
    onchange: ev => subirImagenesLight(ev.target, e, tope, pintar, alCambiar, clave),
  });

  /* UNA ZONA DE ARRASTRE, y el <label for> la convierte en botón sin una línea
     de JS: pulsarla abre el explorador con selección múltiple. Se sueltan
     ficheros encima o se pulsa; son el mismo gesto y llevan al mismo sitio. */
  const suelta = h('label', { clase: 'zona-suelta', for: id },
    h('span', { clase: 'icono' }, '🖼'),
    h('span', {}, 'Arrastra imágenes aquí, o pulsa para buscarlas'),
    estado);
  ['dragenter', 'dragover'].forEach(ev => suelta.addEventListener(ev, evento => {
    evento.preventDefault();
    suelta.classList.add('encima');
  }));
  ['dragleave', 'drop'].forEach(ev => suelta.addEventListener(ev, evento => {
    evento.preventDefault();
    suelta.classList.remove('encima');
  }));
  suelta.addEventListener('drop', evento => {
    const ficheros = [...((evento.dataTransfer || {}).files || [])];
    if (ficheros.length) subirFicherosLight(ficheros, e, tope, pintar, alCambiar, clave);
  });

  caja.appendChild(h('label', {}, op.etiqueta || 'Imágenes de referencia'));
  caja.appendChild(suelta);
  caja.appendChild(entrada);
  caja.appendChild(tira);
  pintar();
  return caja;
}

function subirImagenesLight(entrada, e, tope, pintar, alCambiar, clave) {
  const ficheros = [...(entrada.files || [])];
  entrada.value = '';                       // para poder elegir la misma otra vez
  return subirFicherosLight(ficheros, e, tope, pintar, alCambiar, clave);
}

/* El camino común del explorador y del arrastre: los dos acaban con una lista
   de ficheros y no hay ninguna razón para que hagan cosas distintas. */
async function subirFicherosLight(ficheros, e, tope, pintar, alCambiar, clave) {
  clave = clave || 'estilo_imagenes';
  const imagenes = ficheros.filter(f => /^image\//.test(f.type || ''));
  if (imagenes.length < ficheros.length) {
    toast('Solo imágenes: lo demás se ha ignorado', true);
  }
  if (!imagenes.length) return;
  const hueco = tope - e[clave].length;
  if (imagenes.length > hueco) {
    toast(hueco > 0 ? `Caben ${hueco} más: se suben las ${hueco} primeras`
      : `Ya están las ${tope} que caben`, true);
    if (hueco <= 0) return;
  }
  const cuerpo = new FormData();
  imagenes.slice(0, Math.max(0, hueco)).forEach(f => cuerpo.append('imagenes', f));
  try {
    const datos = await pedir(API.imagenesLight(), { method: 'POST', cuerpo });
    e[clave] = e[clave].concat(datos.imagenes || []);
    (datos.avisos || []).forEach(aviso => toast(aviso, true));
    pintar();
    alCambiar();
  } catch (fallo) {
    toast(`no se han podido subir: ${fallo.message}`, true);
  }
}

async function quitarImagenLight(e, ficha, pintar, alCambiar, clave) {
  clave = clave || 'estilo_imagenes';
  e[clave] = e[clave].filter(x => x.nombre !== ficha.nombre);
  pintar();
  alCambiar();
  // el borrado en el servidor va DESPUÉS de quitarla de la lista: lo que manda
  // es lo que se ve, y un fallo de red no puede dejarla puesta en la pantalla
  try {
    await pedir(API.imagenLight(ficha.nombre), { method: 'DELETE' });
  } catch (fallo) { /* se queda en el buzón; no viaja al encargo y da igual */ }
}

/* El pie: el único verbo de esta pantalla, con lo que va a tardar y lo que va a
   gastar al lado.

   La cuenta la hace el SERVIDOR (`/api/presets-light/plan`), que es el mismo que
   después reparte la barra y el que sabe los tiempos medidos de esta máquina.
   Una cifra inventada aquí y otra distinta durante la generación serían dos
   mentiras, y la segunda encima tardando diez minutos en descubrirse.

   Y se vuelve a pedir MIENTRAS SE ESCRIBE, no una sola vez al pintar: sin eso el
   botón se quedaba apagado con «ponle un nombre» aunque acabaras de ponerlo,
   porque nadie repintaba el pie. Repintar el formulario entero tampoco vale
   —tira el foco del campo donde estás escribiendo—, así que lo que se repinta
   es el pie y nada más. */
function pieDeCreacion() {
  const caja = h('div', { clase: 'pie-light' });
  const aMedias = APP.light.taller;
  const boton = h('button', {
    clase: 'primario', disabled: true,
    onclick: () => lanzarPresetLight(aMedias || undefined),
  }, aMedias ? 'Retomar' : 'Generar');
  const nota = h('span', { clase: 'meta' }, 'comprobando…');
  caja.appendChild(h('div', { clase: 'fila' }, boton, nota));
  if (aMedias) {
    caja.appendChild(h('div', { clase: 'pista' },
      'Se salta lo que ya salió bien y sigue por donde iba. ',
      h('button', {
        clase: 'mini fantasma',
        onclick: () => { APP.light.taller = null; pintarLight(); },
      }, 'Empezar de cero')));
  }

  const comprobar = () => {
    pedir(API.presetLightPlan(), { method: 'POST', cuerpo: encargoParaServidor() })
      .then(datos => {
        const plan = datos.plan || {};
        const imagenes = Number(plan.imagenes) || 0;
        vaciar(nota).append(
          `unos ${duracionCorta(plan.segundos || 0)}`,
          imagenes ? ` · ${imagenes} imágenes` : '');
        boton.disabled = false;
      })
      .catch(err => {
        boton.disabled = true;
        vaciar(nota).append(h('span', { clase: 'aviso' }, err.message));
      });
  };
  APP.light.comprobar = comprobar;
  comprobar();
  return caja;
}

/* Se ha tocado un campo del formulario: se vuelve a preguntar qué falta y
   cuánto va a tardar. Con espera, porque si no sería una llamada por tecla. */
function tocarEncargoLight() {
  clearTimeout(APP.light.tic);
  APP.light.tic = setTimeout(() => {
    if (APP.light.vista === 'crear' && APP.light.comprobar) APP.light.comprobar();
  }, 500);
}

async function lanzarPresetLight(taller) {
  try {
    const datos = await pedir(API.presetsLight(), {
      method: 'POST',
      // con `taller` se RETOMA: se salta lo que ya salió bien y sigue. Es lo que
      // convierte un 403 de YouTube en volver a pulsar, en vez de en rehacer el
      // tono y la voz que ya estaban escritos.
      cuerpo: Object.assign(encargoParaServidor(),
        taller ? { taller } : {}),
    });
    irALight('generando', {
      plan: datos.plan || null, abierto: null, taller: datos.taller || null,
    });
    seguirTrabajo(CLAVE_LIGHT, datos.trabajo_id, alTerminarLight, () => pintarLight());
  } catch (e) {
    toast(`no se ha podido lanzar: ${e.message}`, true);
  }
}

async function alTerminarLight(datos) {
  const nuevo = ((datos || {}).resultado || {}).preset || null;
  /* LO QUE EL MOTOR DECIDIÓ, DICHO. Un ahorro que no se ve no se lee como que
     el motor acertó: se lee como que la pantalla mintió antes. La pantalla de
     generando ya lo enseña —lista las tareas del subconjunto con sus
     imágenes— pero un reparto de dos tareas dura segundos y pasa volando. */
  const tocado = APP.light.reparto;
  if (tocado && (datos || {}).estado === 'listo') toast(tocado);
  APP.light.reparto = null;
  await cargarGaleriaLight(true);
  // ¿quedaba otra parte pedida? se lanza ahora, no antes: dos generaciones a la
  // vez sobre el mismo taller se pisarían los params
  const cola = APP.light.cola || [];
  if ((datos || {}).estado === 'listo' && cola.length) {
    const ficha = fichaLight(nuevo || APP.light.abierto);
    APP.light.cola = cola.slice(1);
    if (ficha) { await regenerarParteLight(ficha, cola[0]); return; }
  }
  APP.light.cola = [];
  if ((datos || {}).estado === 'listo') {
    APP.light.encargo = null;      // el formulario ya no vale para nada
    // A LA MISMA PANTALLA que si lo estuvieras editando, que es la gracia:
    // un estilo recien hecho es uno que estas editando por primera vez.
    irALight('preset', { abierto: nuevo || APP.light.abierto, taller: null,
      feedback: {} });
  } else {
    // El taller se CONSERVA: ahí está lo que sí salió bien, y el formulario
    // vuelve con su botón de retomar. Perderlo obligaría a rehacer el tono y la
    // voz por un 403 de YouTube que se arregla volviendo a pulsar.
    irALight(APP.light.abierto ? 'preset' : 'crear');
  }
}

/* --------------------------------------------------------- la generación */

function vistaGenerandoLight() {
  const trabajo = APP.trabajos[CLAVE_LIGHT] || {};
  const plan = APP.light.plan || {};
  const caja = h('div', { clase: 'light-generando' });
  caja.appendChild(h('h2', {}, APP.light.abierto ? 'Rehaciendo' : 'Montando el estilo'));

  const fraccion = Math.max(0, Math.min(1, Number(trabajo.progreso) || 0));
  const transcurrido = (Date.now() - (trabajo.inicio || Date.now())) / 1000;
  const previsto = Number(plan.segundos) || 0;
  const barra = h('div', { clase: 'barra grande' }, h('i', {}));
  barra.firstChild.style.width = `${(fraccion * 100).toFixed(1)}%`;
  caja.appendChild(barra);

  // Lo de abajo es UNA línea: por dónde va. La cuenta atrás sale del plan del
  // servidor, que reparte por TIEMPO MEDIDO y no por número de tareas, así que
  // avanza a velocidad parecida de principio a fin.
  const restante = previsto > 0 ? Math.max(0, previsto - transcurrido) : 0;
  caja.appendChild(h('div', { clase: 'paso-actual' },
    avancePublico(trabajo) || 'arrancando…'));
  caja.appendChild(h('div', { clase: 'meta' },
    `${duracionCorta(transcurrido)} de unos ${duracionCorta(previsto)}`
    + (restante > 5 ? ` · quedan ~${duracionCorta(restante)}` : '')));

  // La lista de tareas, con la que va marcada. No es decoración: es lo que
  // permite entender por qué esto tarda diez minutos, y qué se está pagando.
  const hechas = fraccion * (Number(plan.segundos) || 1);
  const lista = h('ol', { clase: 'tareas-light' });
  (plan.tareas || []).forEach(tarea => {
    const acabada = Number(tarea.desde) + Number(tarea.tanda_segundos || 0) <= hechas;
    const enMarcha = !acabada && Number(tarea.desde) <= hechas;
    lista.appendChild(h('li', {
      clase: acabada ? 'hecha' : (enMarcha ? 'ahora' : ''),
      title: tarea.porque || '',
    },
      h('span', { clase: 'marca' }, acabada ? '✓' : (enMarcha ? '›' : '·')),
      tarea.publico || tarea.nombre,
      tarea.imagenes ? h('span', { clase: 'pastilla' }, `${tarea.imagenes} imágenes`) : null));
  });
  caja.appendChild(lista);

  caja.appendChild(h('div', { clase: 'fila' },
    h('button', {
      clase: 'mini peligro',
      onclick: async () => { await cancelar(CLAVE_LIGHT); },
    }, 'Cancelar'),
    h('span', { clase: 'meta' },
      'Puedes cerrar esta pestaña: sigue corriendo en el servidor.')));
  return caja;
}

/* ------------------------------------------------------ un estilo abierto
 *
 * LA MISMA PANTALLA RECIÉN GENERADO Y AL EDITAR, y no es una casualidad: es una
 * sola función. Un estilo recién hecho es un estilo que estás editando por
 * primera vez, y tener dos pantallas parecidas garantiza que una se quede vieja.
 *
 * Cada bloque lleva LO SUYO junto: el estilo gráfico, sus muestras; el tono, su
 * descripción; la voz, su escucha. Y debajo de cada uno, la caja de «qué le
 * cambiarías» con su Regenerar — corregir una cosa se hace mirándola, no en un
 * apartado aparte. */

function vistaPresetLight() {
  const ficha = fichaLight(APP.light.abierto);
  if (!ficha) {
    return h('div', { clase: 'caja-info' }, 'ese estilo ya no está. ',
      h('button', { clase: 'mini', onclick: () => irALight('galeria') }, 'Volver'));
  }
  const datos = ficha.datos || {};
  const origen = datos.origen || {};
  const caja = h('div', { clase: 'light-preset' });
  caja.appendChild(h('div', { clase: 'light-cab' },
    h('button', {
      clase: 'mini fantasma', onclick: () => irALight('galeria'),
      title: 'Volver a tus estilos',
    }, '‹ Volver'),
    h('h2', {}, ficha.nombre || ficha.id),
    h('span', { clase: 'crece' }),
    h('button', {
      clase: 'mini peligro', title: 'Mandar este estilo a la papelera',
      onclick: () => borrarPresetLight(ficha),
    }, 'Borrar')));

  // 🎨 el estilo gráfico, con sus muestras en fila
  const grafico = h('div', {});
  grafico.appendChild(bannerMuestras(ficha));
  /* SIN caja de «qué le cambiarías»: la de indicaciones es esa caja. Eran dos
     campos de texto seguidos preguntando lo mismo, y encima el de arriba se
     guardaba con el estilo y el de abajo no. Se queda el que se guarda: una
     indicación que sobrevive se vuelve a aplicar la próxima vez que regeneres,
     y un feedback que se evapora hay que volver a escribirlo. */
  grafico.appendChild(fuenteDeEstiloLight(ficha));
  caja.appendChild(bloqueLight('🎨 Estilo gráfico',
    'las imágenes, las cartelas y los subtítulos', grafico));

  /* 🗣️ EL TONO, ENTERO Y EDITABLE.
     Aquí se enseñaba `tono_resumen`: cuatro líneas cortadas con «…». La guía
     que hay debajo son casi dos mil palabras, así que la pantalla la hacía
     parecer «muy corta» y a medias cuando el problema estaba en otro sitio.
     Ahora se enseña LA GUÍA COMPLETA —el párrafo más los rasgos, que es
     exactamente lo que se le pega al redactor— y se puede corregir a mano ahí
     mismo: autoguardado, como todo lo demás, sin botón de confirmar. */
  const tono = h('div', {});
  const guiaTono = (datos.guion || {}).instrucciones || '';
  if (guiaTono) {
    grafico.dataset.tiene = '1';
    tono.appendChild(h('div', { clase: 'meta' },
      `${cifra(String(guiaTono).split(/\s+/).filter(Boolean).length)} palabras`
      + (origen.tono_resumen
        ? ` · ${String(origen.tono_resumen).split('\n')[0]}` : '')));
    tono.appendChild(campoTexto('', guiaTono,
      v => guardarPresetLight(ficha.id, { instrucciones: v }),
      { filas: 16,
        ayuda: 'Es lo que lee el redactor, tal cual. Se guarda solo; '
             + 'regenerar el tono lo reescribe entero.' }));
  } else {
    tono.appendChild(h('div', { clase: 'pista' }, 'sin instrucciones todavía'));
  }
  tono.appendChild(fuenteDeTonoLight(ficha));
  tono.appendChild(cajaDeRehacer(ficha, 'tono'));
  caja.appendChild(bloqueLight('🗣️ Tono del guion',
    'cómo se cuenta, nunca de qué', tono));

  // ⏱️ el ritmo: se cambia y ya, no rehace nada
  caja.appendChild(bloqueLight('⏱️ Ritmo', 'cada cuánto corta el vídeo',
    sliderRitmo((ficha.origen_ritmo || ritmoPorDefecto()),
      v => guardarPresetLight(ficha.id, { ritmo: v }))));

  // 🎙️ la voz, con su escucha
  const voz = h('div', {});
  voz.appendChild(escuchaDeVoz(ficha));
  voz.appendChild(cajaDeRehacer(ficha, 'voz'));
  caja.appendChild(bloqueLight('🎙️ Voz', 'quién lo locuta', voz));

  // 🌐 lo que se cambia a mano. Autoguardado, como todo lo demás.
  caja.appendChild(bloqueLight('🌐 Nombre e idioma', 'se cambian sin regenerar nada',
    campoTexto('', ficha.nombre, v => guardarPresetLight(ficha.id, { nombre: v })),
    campoSelect('', ficha.idioma || 'es',
      idiomasLight().map(i => ({ valor: i.valor, nombre: i.nombre })),
      v => guardarPresetLight(ficha.id, { idioma: v }, true))));

  caja.appendChild(pieDeEstilo(ficha));
  return caja;
}

/* Si hay algo de los personajes que haya que DIBUJAR: fotos nuevas en alguno,
   o uno sin hoja todavia. Editar el texto no lo es: se guarda solo. */
function personajesCambiadosLight(ficha) {
  const estado = APP.light.personajes;
  if (!estado || estado.preset !== ficha.id) return false;
  return estado.personajes.some(p => String(p.nombre || '').trim()
    && ((p.imagenes || []).length || !p.hoja));
}

function personajesParaServidor(ficha) {
  const estado = APP.light.personajes || { personajes: [] };
  return estado.personajes
    .filter(p => String(p.nombre || '').trim() || String(p.descripcion || '').trim())
    .map(personajeParaServidor);
}

/* LAS REFERENCIAS, UNA SOLA FILA Y CON SU CARTELA PUESTA.
 *
 * Son las mismas láminas que copia cada plano del vídeo, con una cartela y un
 * subtítulo de ejemplo dibujados encima por el código que monta el vídeo. Aquí
 * había DOS filas —cuatro planos generados a propósito arriba y las seis
 * referencias limpias debajo— y sobraba una: lo que se juzga de un estilo es
 * cómo queda el texto sobre SU dibujo, y eso se ve mejor sobre las seis que
 * sobre cuatro planos hechos aparte.
 *
 * LO QUE VIAJA AL GENERADOR ES LA LIMPIA, no esta: los rótulos que lleva encima
 * son grafismo del Estudio y el generador los copiaría como si fueran del dibujo.
 * La limpia sigue intacta en `estilo.referencias` y no se pinta: es fontanería
 * del motor, no una decisión de nadie.
 *
 * En fila y no en cuadrícula: en 2×2 cada plano se ve a un cuarto de ancho y el
 * subtítulo deja de leerse, que es justo lo que hay que juzgar. La cuadrícula se
 * queda donde sirve, en la tarjeta de la galería, donde hace falta UNA imagen. */
function bannerMuestras(ficha) {
  const datos = ficha.datos || {};
  const sueltas = (datos.origen || {}).muestras || [];
  const caja = h('div', { clase: 'banner-muestras' });

  if (sueltas.length) {
    caja.appendChild(tiraDeImagenes(ficha, sueltas));
    caja.appendChild(h('div', { clase: 'pista una-linea' },
      `Las ${sueltas.length} referencias que copia cada plano, con el texto que `
      + 'llevarían en el vídeo. Al generador van sin nada encima.'));
  } else {
    caja.appendChild(h('div', { clase: 'pista' },
      'Este estilo no tiene muestras todavía.'));
  }
  return caja;
}

/* Una fila de imágenes servidas desde la carpeta del estilo. El sello del
   `modificado` va en la URL porque rehacer una parte deja el mismo nombre de
   fichero apuntando a otra imagen, y sin él el navegador enseña la vieja. */
function tiraDeImagenes(ficha, nombres) {
  const tira = h('div', { clase: 'tira' });
  nombres.forEach(nombre => {
    const url = `${API.presetCanalFichero(ficha.id, nombre)}?v=${ficha.modificado || ''}`;
    tira.appendChild(h('img', {
      src: url, alt: '', loading: 'lazy', onclick: () => lupa(url),
    }));
  });
  return tira;
}

/* La escucha de la voz. Sintetiza doce segundos con los mandos que tiene puestos
   el estilo, en el taller — que es un proyecto y por eso puede hacerlo con el
   mismo código que el modo editor. */
function escuchaDeVoz(ficha) {
  const voz = (ficha.datos || {}).voz || {};
  const caja = h('div', { clase: 'bloque-voz' });
  const nombre = voz.voz_nombre || voz.voz_id || '';
  caja.appendChild(h('div', { clase: 'resumen-voz' },
    h('b', {}, nombre || 'sin voz elegida'),
    ...[voz.velocidad, (voz.emociones || []).join(', '),
      voz.hueco_minimo ? `aire ${voz.hueco_minimo}s` : '']
      .filter(Boolean).map(x => h('span', { clase: 'meta' }, ` · ${x}`))));
  caja.appendChild(mandosDeVozLight(ficha, voz));

  /* LA ESCUCHA GENERAL, abajo y con la voz que está puesta. Es EL MISMO botón
     que lleva cada voz de la cuadrícula de arriba —una sola función—, así que no
     hay forma de que uno se quede viejo respecto del otro. */
  caja.appendChild(h('div', { clase: 'fila' },
    botonEscuchaVoz(ficha, { etiqueta: 'Escuchar', impedido: !voz.voz_id }),
    h('span', { clase: 'meta' }, voz.voz_id
      ? 'doce segundos con esta voz y estos mandos'
      : 'este estilo todavía no tiene voz elegida')));
  return caja;
}

/* LOS MANDOS FINOS, plegados. La voz se elige describiendo cómo quieres que
   suene —eso es el modo light— y esto es la vuelta de tuerca de después: cambiar
   la voz concreta, la velocidad, el color o el aire sin volver a escribir nada.
   Plegado porque en el 95 % de las veces no se toca, y visible porque cuando
   hace falta, buscarlo en el modo editor es cruzar media aplicación.

   EL CATÁLOGO SIGUE AL IDIOMA: se piden las voces NATIVAS del idioma que tenga
   puesto el estilo ahora mismo, así que cambiarlo abajo cambia esta lista. Una
   lista de voces inglesas en un canal en portugués no es una opción, es una
   trampa. */
function mandosDeVozLight(ficha, voz) {
  const caja = h('div', {});
  const dentro = h('div', {});
  const avanzadas = opcionesAvanzadas({
    clave: `voz-light-${ficha.id}`,
    resumen: 'la voz concreta, la velocidad, el color y el aire',
  }, dentro);
  caja.appendChild(avanzadas);

  const guardar = cambios => apuntarVozLight(ficha, cambios);

  const idioma = ficha.idioma || 'es';
  const lista = vocesLight(idioma);
  if (!lista) {
    dentro.appendChild(h('div', { clase: 'pista' },
      `cargando las voces de ${nombreIdiomaLight(idioma)}…`));
  } else {
    dentro.appendChild(selectorVozLight(ficha, voz, lista, guardar));
  }

  dentro.appendChild(campoSelect('Velocidad', voz.velocidad || 'normal',
    VELOCIDADES.map(v => ({ valor: v, nombre: v })),
    valor => guardar({ velocidad: valor })));

  /* Las emociones son de CERO a DOS, y el orden importa: el modelo de voz
     aplica una sola, así que la primera manda. Se enseñan como casillas y no
     como un desplegable múltiple porque hay cinco y caben. */
  const puestas = (voz.emociones || []).map(x => String(x).split(':')[0]);
  const fila = h('div', { clase: 'herramientas' });
  EMOCIONES.forEach(emocion => {
    const marcada = puestas.includes(emocion);
    fila.appendChild(h('button', {
      clase: 'mini' + (marcada ? ' activo' : ''),
      onclick: () => {
        const nuevas = marcada ? puestas.filter(x => x !== emocion)
          : puestas.concat([emocion]).slice(-2);
        guardar({ emociones: nuevas });
        repintarBloqueVoz(ficha);
      },
    }, emocion));
  });
  dentro.appendChild(h('div', { clase: 'campo' },
    h('label', {}, 'Color'), fila,
    h('div', { clase: 'pista' },
      'De cero a dos, y ninguna es una respuesta válida: el tono neutro deja '
      + 'que hablen los hechos. Manda la primera.')));

  dentro.appendChild(campoTexto('Aire entre bloques (s)',
    voz.hueco_minimo === undefined ? 1 : voz.hueco_minimo,
    valor => guardar({ hueco_minimo: valor }),
    { tipo: 'number', paso: 0.1, min: 0.3, max: 1.6, ancho: '110px',
      ayuda: 'Lo pone el ritmo; aquí se afina.' }));
  return caja;
}

function nombreIdiomaLight(codigo) {
  const ficha = idiomasLight().find(i => i.valor === codigo);
  return ficha ? ficha.nombre.toLowerCase() : codigo;
}

/* LA FICHA EN MEMORIA, AL DÍA ANTES DE QUE CONTESTE EL PUT. El autoguardado sale
   900 ms después del último toque, así que sin esto la pantalla se repinta
   leyendo lo de antes: tocar una emoción no la marcaba hasta el siguiente
   repintado, y elegir una voz y darle al play de abajo escuchaba la anterior.
   Lo que vuelva del servidor sustituye a esto en cuanto llegue. */
function apuntarVozLight(ficha, cambios) {
  ficha.datos = Object.assign({}, ficha.datos || {});
  ficha.datos.voz = Object.assign({}, ficha.datos.voz || {}, cambios);
  guardarPresetLight(ficha.id, { voz: cambios }, false);
}

/* Repinta SOLO el bloque de la voz, como `repintarPieDeEstilo` hace con el pie.
   Un `pintarLight()` entero deja el panel arriba del todo —al vaciarlo, el
   navegador se lleva el desplazamiento por delante— y la voz vive al final de
   la ficha: elegir una y aparecer en la cabecera es perder el sitio en cada
   clic. Aquí basta con la caja que cambia. */
function repintarBloqueVoz(ficha) {
  const viejo = document.querySelector('.light-preset .bloque-voz');
  if (viejo) viejo.replaceWith(escuchaDeVoz(ficha));
}

/* ------------------------------------------------- la cuadrícula de voces
 *
 * UN DESPLEGABLE PROPIO Y NO UN <select>. El del navegador enseña una voz por
 * línea en una columna de un dedo de ancho: con 417 voces inglesas, elegir era
 * bajar por una lista de nombres que no dicen nada («Cory - Relaxed Voice») sin
 * poder oír ninguna hasta haberla elegido — y elegir GUARDA, así que comparar
 * seis dejaba puesta la sexta.
 *
 * Aquí caben varias por fila, cada una dice de dónde es, y cada una lleva su
 * propio play que la escucha SIN elegirla, con la velocidad, el color y el aire
 * que tenga el estilo puesto ahora mismo. Comparar dos voces es darle a dos
 * plays, y lo único que cambia entre ellas es la voz.
 *
 * Con buscador porque un <select> al menos deja teclear las primeras letras, y
 * quitarlo sin poner nada a cambio sería cambiar un problema por otro. */
/* EL CATÁLOGO DE VOCES DEL LIGHT, UNA VEZ POR IDIOMA. Devuelve la lista si ya
   está, y si no la pide y devuelve null: quien pinta enseña «cargando» y se
   repinta solo cuando llega. Lo comparten la ficha del estilo y el formulario
   de crear, que es lo que hace que la voz clonada aparezca en los dos. */
function vocesLight(idioma) {
  idioma = idioma || 'es';
  const catalogo = APP.light.voces || {};
  if (catalogo.idioma === idioma) return catalogo.lista || [];
  if (!catalogo.pidiendo || catalogo.pidiendo !== idioma) {
    APP.light.voces = { idioma: catalogo.idioma, pidiendo: idioma,
      lista: catalogo.lista || [] };
    pedir(API.voces(idioma, true))
      .then(datos => {
        APP.light.voces = { idioma, lista: datos.voces || [], pidiendo: null };
        if (['preset', 'crear'].includes(APP.light.vista)) pintarLight();
      })
      .catch(() => { APP.light.voces = { idioma, lista: [], pidiendo: null }; });
  }
  return null;
}

/* Las voces PROPIAS de la cuenta (clonadas): un desplegable aparte de la
   descripción. Con una elegida, la descripción sigue mandando la velocidad y el
   color, pero la voz es esa. Sin ninguna en la cuenta se dice, en una línea,
   que no hay: es la forma de que nadie busque en el catálogo lo que no está. */
function selectorVozPropiaLight(e) {
  const lista = vocesLight(e.idioma);
  const caja = h('div', { clase: 'campo' });
  if (!lista) {
    caja.appendChild(h('div', { clase: 'pista' }, 'cargando tus voces…'));
    return caja;
  }
  const propias = lista.filter(v => v.publica === false);
  if (!propias.length) {
    caja.appendChild(h('div', { clase: 'pista' },
      'No hay voces clonadas en esta cuenta de Cartesia: la voz se elige por la '
      + 'descripción de arriba. Si clonas una, aparecerá aquí.'));
    return caja;
  }
  if (e.voz_id && !propias.some(v => v.id === e.voz_id)) e.voz_id = '';
  caja.appendChild(h('label', {}, 'Tus voces (clonadas)'));
  caja.appendChild(h('select', {
    onchange: ev => { e.voz_id = ev.target.value; tocarEncargoLight(); },
  },
    h('option', { value: '', selected: !e.voz_id },
      '— que la elija por la descripción —'),
    ...propias.map(v => h('option', { value: v.id, selected: e.voz_id === v.id },
      `${v.nombre || v.id}${v.descripcion ? ` · ${v.descripcion}` : ''}`))));
  caja.appendChild(h('div', { clase: 'pista' },
    'Con una elegida, la descripción de arriba solo decide la velocidad y el '
    + 'color; la voz es esta y se queda en el estilo.'));
  return caja;
}

function selectorVozLight(ficha, voz, voces, guardar) {
  const estado = (APP.light.picker && APP.light.picker.preset === ficha.id)
    ? APP.light.picker
    : (APP.light.picker = { preset: ficha.id, abierto: false, busca: '' });
  const idioma = ficha.idioma || 'es';

  /* LA VOZ PUESTA, AUNQUE NO ESTÉ EN LA LISTA. Si el estilo cambió de idioma, la
     que tiene no es nativa del nuevo: se sigue enseñando la primera y marcada,
     en vez de perderla en silencio. */
  const dentro = voces.some(v => v.id === voz.voz_id);
  const forastera = (!dentro && voz.voz_id)
    ? { id: voz.voz_id, nombre: voz.voz_nombre || voz.voz_id, idioma: '', pais: '' }
    : null;

  const rejilla = h('div', { clase: 'rejilla-voces' });
  const cuenta = h('span', { clase: 'meta' });
  const elegir = v => {
    estado.abierto = false;
    guardar({ voz_id: v.id, voz_nombre: v.nombre || '' });
    // el bloque entero y no la pantalla: el rótulo de arriba, la cuadrícula y
    // el botón de escuchar de abajo dicen los tres cuál es la voz puesta
    repintarBloqueVoz(ficha);
  };
  const pintarRejilla = () => {
    vaciar(rejilla);
    const filtro = estado.busca.trim().toLowerCase();
    const visibles = voces.filter(v => !filtro
      || `${v.nombre} ${v.descripcion || ''} ${v.id}`.toLowerCase().includes(filtro));
    const TOPE = 240;
    // Nada se recorta sin decir cuánto falta: una rejilla cortada en seco se lee
    // como «esto es lo que hay».
    cuenta.textContent = `${visibles.length} de ${voces.length} nativas de `
      + `${nombreIdiomaLight(idioma)}`
      + (visibles.length > TOPE ? ` · se pintan ${TOPE}, afina la búsqueda` : '');
    // la de otro idioma va la primera y solo sin filtro: es la que tienes
    // puesta, no un resultado de la búsqueda
    if (forastera && !filtro) {
      rejilla.appendChild(celdaVozLight(ficha, forastera, voz, elegir));
    }
    if (!visibles.length) {
      rejilla.appendChild(h('div', { clase: 'vacio' }, 'ninguna voz coincide'));
      return;
    }
    // LAS PROPIAS APARTE Y PRIMERO: son las que se buscan y son dos o tres
    // entre cientos. Con rótulo, para que se vea que son otra cosa.
    const propias = visibles.filter(v => v.publica === false);
    const catalogo = visibles.filter(v => v.publica !== false);
    if (propias.length) {
      rejilla.appendChild(h('div', { clase: 'grupo-voces' }, 'Tus voces (clonadas)'));
      propias.forEach(v => rejilla.appendChild(celdaVozLight(ficha, v, voz, elegir)));
      if (catalogo.length) {
        rejilla.appendChild(h('div', { clase: 'grupo-voces' }, 'Catálogo de Cartesia'));
      }
    }
    catalogo.slice(0, TOPE).forEach(v =>
      rejilla.appendChild(celdaVozLight(ficha, v, voz, elegir)));
  };

  const puesta = forastera || voces.find(v => v.id === voz.voz_id) || null;
  const flecha = h('span', { clase: 'flecha' });
  const disparo = h('button', { clase: 'desplegable-voz' },
    h('span', { clase: 'nombre' },
      puesta ? (puesta.nombre || puesta.id) : 'sin voz elegida'),
    h('span', { clase: 'meta' }, puesta ? procedenciaDeVoz(puesta, idioma) : ''),
    flecha);

  const buscador = h('input', {
    clase: 'buscar-voz', placeholder: 'buscar por nombre o descripción…',
    value: estado.busca,
    oninput: ev => { estado.busca = ev.target.value; pintarRejilla(); },
  });
  const panel = h('div', { clase: 'panel-voces' },
    h('div', { clase: 'fila' }, buscador, cuenta), rejilla);
  const pista = h('div', { clase: 'pista' },
    `${voces.length} voces nativas de ${nombreIdiomaLight(idioma)}, `
    + 'cada una con su escucha');

  /* ABRIR NO REPINTA LA PANTALLA. Vaciar el panel para volver a pintarlo se
     lleva por delante el desplazamiento, y la voz vive al final de la ficha:
     abrir la lista y aparecer arriba del todo hace inservible la lista. */
  const aplicar = () => {
    disparo.classList.toggle('abierto', estado.abierto);
    vaciar(flecha).append(estado.abierto ? '▲' : '▼');
    panel.hidden = !estado.abierto;
    pista.hidden = estado.abierto;
    if (estado.abierto) { pintarRejilla(); buscador.focus(); }
  };
  disparo.addEventListener('click', () => {
    estado.abierto = !estado.abierto;
    aplicar();
  });
  const campo = h('div', { clase: 'campo campo-voz' },
    h('label', {}, 'Voz'), disparo, panel, pista);
  aplicar();
  return campo;
}

/* Una celda: su play, su nombre y de dónde es. El play NO elige —darle es
   audicionarla— y el resto de la celda sí: son dos gestos distintos, y por eso
   son dos botones y no uno con una zona mágica dentro. */
function celdaVozLight(ficha, v, voz, elegir) {
  const marcada = v.id === voz.voz_id;
  return h('div', {
    clase: `voz-ficha${marcada ? ' sel' : ''}`, title: v.descripcion || '',
  },
    botonEscuchaVoz(ficha, { voz: () => v.id, titulo: `escuchar ${v.nombre || v.id}` }),
    h('button', { clase: 'elegir-voz', onclick: () => elegir(v) },
      h('span', { clase: 'nombre' }, v.nombre || v.id),
      h('span', { clase: 'meta' }, (v.publica === false ? 'voz clonada · tuya · ' : '')
        + procedenciaDeVoz(v, ficha.idioma || 'es'))));
}

/* DE DÓNDE ES LA VOZ: su idioma nativo y su país. El catálogo de Cartesia trae
   los dos en código («en», «GB») y los nombres los pone el navegador, que ya
   tiene esa tabla dentro: mantener aquí una lista de idiomas y otra de países
   sería copiar algo que el sistema sabe mejor y que además envejece. */
const NOMBRES_DEL_NAVEGADOR = (() => {
  try {
    return { idioma: new Intl.DisplayNames(['es'], { type: 'language' }),
      pais: new Intl.DisplayNames(['es'], { type: 'region' }) };
  } catch (e) { return null; }
})();

function nombreDelNavegador(tipo, codigo) {
  if (!codigo || !NOMBRES_DEL_NAVEGADOR) return codigo || '';
  try {
    const texto = NOMBRES_DEL_NAVEGADOR[tipo].of(codigo) || codigo;
    return texto.charAt(0).toUpperCase() + texto.slice(1);
  } catch (e) { return codigo; }
}

function procedenciaDeVoz(v, idiomaEstilo) {
  if (!v.idioma) return 'de otro idioma';
  const propio = idiomasLight().find(i => i.valor === v.idioma);
  const nombre = propio ? propio.nombre : nombreDelNavegador('idioma', v.idioma);
  const pais = v.pais ? nombreDelNavegador('pais', v.pais) : '';
  // Un canal en inglés con una voz española NO es un fallo —el acento puede ser
  // justo lo que buscas—, pero sí es algo que hay que ver sin abrir nada.
  const ajena = idiomaEstilo && v.idioma !== idiomaEstilo ? ' · de otro idioma' : '';
  return `${nombre}${pais ? ` · ${pais}` : ''}${ajena}`;
}

/* ------------------------------------------------------------ escuchar
 *
 * UN SOLO BOTÓN, Y EL MISMO EN LOS DOS SITIOS. Aquí había dos cosas pegadas: un
 * «▶ Escuchar» que sintetizaba y, al lado, la barra nativa del navegador con SU
 * propio play, su volumen, su tiempo y su menú de tres puntos. Dos botones de
 * play uno junto a otro para una sola cosa, y el segundo con cuatro mandos que
 * no pintan nada en una escucha de doce segundos.
 *
 * Ahora es un botón con tres estados —▶ escuchar, ⋯ sintetizando, ■ parar— y el
 * <audio> sigue siendo quien suena, pero sin controles y sin verse. Sigue
 * registrado (`registrarReproductor`), que es lo que hace que arrancar una
 * escucha pare la que estuviera sonando: con una voz por celda, eso pasa a cada
 * clic.
 *
 *   op.voz        función que devuelve el id de la voz a escuchar. Sin ella, la
 *                 que tenga puesta el estilo.
 *   op.etiqueta   texto junto al icono. Sin ella queda el icono solo, que es lo
 *                 que cabe en una celda de la cuadrícula.
 */
function botonEscuchaVoz(ficha, op) {
  op = op || {};
  const boton = h('button', {
    clase: `mini escuchar${op.etiqueta ? '' : ' solo-icono'}`,
  });
  const caja = h('span', { clase: 'escucha-voz' }, boton);
  let audio = null;
  let pidiendo = false;

  const pintar = () => {
    const sonando = !!audio && !!audio.src && !audio.paused && !audio.ended;
    boton.disabled = pidiendo || !!op.impedido;
    boton.classList.toggle('sonando', sonando);
    boton.title = op.titulo || (sonando ? 'parar' : 'escuchar doce segundos');
    vaciar(boton).append(pidiendo ? '⋯' : (sonando ? '■' : '▶'));
    if (op.etiqueta) {
      boton.append(` ${pidiendo ? 'sintetizando…' : (sonando ? 'Parar' : op.etiqueta)}`);
    }
  };

  /* EL <audio> SE CREA AL PRIMER PLAY. Con uno por celda eran 241 elementos de
     medios en la pantalla, todos vacíos, para que sonara como mucho uno. */
  const sonador = () => {
    if (audio) return audio;
    audio = registrarReproductor(h('audio', { preload: 'none' }));
    ['play', 'pause', 'ended'].forEach(ev => audio.addEventListener(ev, pintar));
    caja.appendChild(audio);
    return audio;
  };

  const soltar = () => { pidiendo = false; pintar(); };
  boton.addEventListener('click', async () => {
    if (audio && audio.src && !audio.paused) {
      audio.pause();
      audio.currentTime = 0;
      return;
    }
    const vozId = op.voz ? op.voz() : '';
    const clave = claveEscucha(ficha, vozId);
    const guardada = (APP.light.escuchas || {})[clave];
    if (guardada) {
      sonador().src = guardada;
      audio.play().catch(() => {});
      return;
    }
    /* La anterior vuelve a su sitio. `seguirTrabajo` sigue UN trabajo por clave,
       así que lanzar otra escucha deja a la de antes sin quien la avise y su
       botón se quedaría en «sintetizando…» para siempre. */
    if (abandonarEscucha) abandonarEscucha();
    abandonarEscucha = soltar;
    pidiendo = true;
    pintar();
    try {
      const url = await pedirEscuchaVoz(ficha, vozId);
      APP.light.escuchas = Object.assign({}, APP.light.escuchas, { [clave]: url });
      sonador().src = url;
      audio.play().catch(() => { /* el navegador puede negarse; el botón queda listo */ });
    } catch (e) {
      toast(`no se ha podido escuchar: ${e.message}`, true);
    }
    if (abandonarEscucha === soltar) abandonarEscucha = null;
    soltar();
  });
  pintar();
  return caja;
}

let abandonarEscucha = null;

/* LA HUELLA DE UNA ESCUCHA: la voz Y los mandos. El servidor cachea la síntesis
   por esa misma firma, así que volver a una ya oída no vuelve a pagar; pero si
   la clave de aquí no llevara dentro la velocidad o el color, subir un mando y
   darle al play devolvería el fichero de antes desde el navegador y parecería
   que el mando no hace nada. */
function claveEscucha(ficha, vozId) {
  const v = (ficha.datos || {}).voz || {};
  return JSON.stringify([ficha.id, vozId || v.voz_id || '', v.velocidad || '',
    (v.emociones || []).join(','), v.hueco_minimo,
    v.idioma || ficha.idioma || '']);
}

/* Doce segundos, en el taller. Con `voz_id` se escucha una voz SIN elegirla, que
   es lo que hace el play de cada celda de la cuadrícula. */
async function pedirEscuchaVoz(ficha, vozId) {
  /* LO PENDIENTE PRIMERO. El autoguardado sale 900 ms después del último toque y
     el servidor sintetiza con lo que tenga GUARDADO el estilo: sin esto, subir
     la velocidad y darle al play escuchaba la de antes. */
  await volcarPresetLight();
  const datos = await pedir(`${API.presetLight(ficha.id)}/voz/previsualizar`,
    { method: 'POST', cuerpo: { segundos: 12, voz_id: vozId || '' } });
  const tid = datos.trabajo_id || (datos.trabajo || {}).id;
  if (!tid) throw new Error('el servidor no ha devuelto ningún trabajo');
  return new Promise((salir, fallar) => {
    seguirTrabajo(CLAVE_VOZ_LIGHT, tid, fin => {
      const url = urlDeResultado(fin.resultado);
      if (fin.estado !== 'listo' || !url) {
        fallar(new Error(fin.error || fin.mensaje || 'no ha salido ninguna escucha'));
        return;
      }
      salir(url);
    });
  });
}

/* ------------------------------------------- cambiar la FUENTE del estilo
 *
 * La caja de «qué le cambiarías» corrige lo que hay: rehace la guía con los
 * MISMOS fotogramas. Esto es la otra cosa, y hasta ahora no se podía: cambiar
 * de dónde sale el estilo —otro vídeo, u otra descripción con otras imágenes—
 * conservando el tono, la voz, el ritmo y el idioma.
 *
 * El caso que lo pide: «los mismos vídeos, pero en fotográfico». Antes eso era
 * un estilo nuevo desde cero y volver a escribir el tono y la voz.
 *
 * Con un vídeo nuevo hay que bajarlo y volver a elegir sus fotogramas; con una
 * descripción no. Esa lista la decide el servidor a partir del encargo nuevo
 * (`presets_light.tareas_de_estilo`), no esta pantalla. */
function fuenteDeEstiloLight(ficha) {
  const origen = (ficha.datos || {}).origen || {};
  const f = (APP.light.fuente && APP.light.fuente.preset === ficha.id)
    ? APP.light.fuente
    : (APP.light.fuente = {
      preset: ficha.id,
      prompt: origen.estilo_prompt || '',
      estilo_imagenes: [],
    });

  const caja = h('div', { clase: 'fuente-estilo' });
  caja.appendChild(h('div', { clase: 'meta' },
    'Otras imágenes a las que parecerse. Rehace el dibujo entero y deja el '
    + 'tono, la voz y el ritmo como están; las de ahora siguen puestas hasta '
    + 'que pulses Regenerar.'));
  caja.appendChild(imagenesDeApoyoLight(f, repintarPieDeEstilo,
    `aportadas-${ficha.id}`));
  caja.appendChild(campoArea('Indicaciones (opcional)', f.prompt,
    v => { f.prompt = v; repintarPieDeEstilo(); },
    'igual pero más frío y con menos detalle en los fondos'));
  caja.appendChild(h('div', { clase: 'meta' },
    'Lo que el material no dice por sí solo. Reescribe la guía y rehace las '
    + 'muestras; se guarda con el estilo y se vuelve a aplicar si lo regeneras.'));
  return caja;
}

/* Si lo que hay escrito arriba pide de verdad rehacer el estilo. Escribir la
   MISMA URL que ya tenía no es un cambio: sería pagar seis imágenes por pulsar
   un botón sin haber pedido nada. */
function fuenteCambiadaLight(ficha) {
  const f = APP.light.fuente;
  if (!f || f.preset !== ficha.id) return false;
  const origen = (ficha.datos || {}).origen || {};
  if (String(f.prompt || '').trim() !== (origen.estilo_prompt || '')) return true;
  return (f.estilo_imagenes || []).length > 0;
}

/* Lo que viaja al servidor cuando la fuente ha cambiado. Las dos claves
   SIEMPRE, aunque una vaya vacía: el servidor distingue «no me manda imágenes»
   de «me manda una lista vacía», y sólo la segunda dice «quítalas». */
function fuenteParaServidor(_ficha) {
  const f = APP.light.fuente || {};
  return {
    estilo_prompt: String(f.prompt || '').trim(),
    estilo_imagenes: (f.estilo_imagenes || []).map(x => x.nombre),
  };
}

/* --------------------------------------- volver a escribir la GUÍA DE TONO
 *
 * El gemelo de `fuenteDeEstiloLight`, y existe por lo mismo: la caja de «qué le
 * cambiarías» corrige la guía que HAY, y esto la reescribe entera desde otras
 * indicaciones. Se usa cuando lo que salió no es lo que se quería, no cuando le
 * falta un matiz.
 *
 * AQUÍ HUBO UN SELECTOR de «Vídeos | Descríbelo», y se fue con los vídeos: el
 * tono se escribe, así que no hay de dónde elegir. Lo que mandaba la otra mitad
 * —unos `tono_urls`— es justo lo que `presets_light.validar_encargo` rechaza. */
function fuenteDeTonoLight(ficha) {
  const origen = (ficha.datos || {}).origen || {};
  const f = (APP.light.fuenteTono && APP.light.fuenteTono.preset === ficha.id)
    ? APP.light.fuenteTono
    : (APP.light.fuenteTono = {
      preset: ficha.id,
      prompt: origen.tono_prompt || '',
    });

  const caja = h('div', { clase: 'fuente-estilo' });
  caja.appendChild(h('div', { clase: 'meta' },
    'Cómo quieres que suene, escrito de nuevo. Al pulsar Regenerar reescribe '
    + 'las instrucciones enteras —no cuesta ninguna imagen—; la guía de ahora '
    + 'sigue puesta hasta entonces.'));
  caja.appendChild(campoArea('', f.prompt,
    v => { f.prompt = v; repintarPieDeEstilo(); },
    'serio pero cercano, sin dramatismo, frases cortas'));
  return caja;
}

/* Si lo escrito arriba pide de verdad rehacer el tono: LO MISMO que ya tenía no
   es un cambio, igual que con el estilo. Sin esto, pulsar Regenerar sin haber
   tocado nada reescribiría la guía por gusto. */
function fuenteTonoCambiadaLight(ficha) {
  const f = APP.light.fuenteTono;
  if (!f || f.preset !== ficha.id) return false;
  const origen = (ficha.datos || {}).origen || {};
  const prompt = String(f.prompt || '').trim();
  return !!prompt && prompt !== (origen.tono_prompt || '');
}

function fuenteTonoParaServidor() {
  return { tono_prompt: String((APP.light.fuenteTono || {}).prompt || '').trim() };
}

/* La caja de «qué le cambiarías» con su verbo. Va DENTRO del bloque de la cosa
   que corrige: se pide mirándola. */
function cajaDeRehacer(ficha, parte) {
  /* SOLO EL TONO Y LA VOZ. El estilo gráfico tenía la suya y se fue: lo que se
     le pide se escribe en sus «Indicaciones», que es lo mismo pero se guarda
     con el estilo en vez de evaporarse al regenerar. */
  const pistas = {
    tono: 'menos solemne, y que no abra con una pregunta',
    voz: 'una voz algo más joven y un poco más rápida',
    personajes: 'más joven, sin gafas, y que la sudadera sea roja',
  };
  const notas = {
    tono: 'solo las instrucciones del guion',
    voz: 'solo la voz y sus mandos',
    personajes: 'redibuja las hojas de todos los personajes, una imagen cada una',
  };
  /* SIN BOTÓN PROPIO. Lo que se escribe aquí lo aplica el botón de abajo, que
     es UNO para toda la pantalla: escribe solo en la caja de la voz y solo se
     rehace la voz. Tres botones de «Regenerar» repartidos por la ficha eran
     tres sitios donde pulsar para lo mismo, y ninguno decía lo que iba a costar
     el conjunto. */
  const caja = h('div', { clase: 'rehacer' });
  caja.appendChild(campoArea('', APP.light.feedback[parte] || '',
    v => { APP.light.feedback[parte] = v; repintarPieDeEstilo(); },
    pistas[parte]));
  caja.appendChild(h('div', { clase: 'meta' }, notas[parte]));
  return caja;
}

/* EL PIE: UN BOTÓN CON DOS VERBOS, y el verbo lo decide lo que hayas escrito.
 *
 *   Regenerar   hay algo pedido en alguna caja de «qué le cambiarías». Rehace
 *               ESAS partes y nada más: si solo has escrito en la voz, solo se
 *               rehace la voz, y el botón lo dice antes de pulsarlo.
 *   Guardar     no hay nada pedido. Adelanta el autoguardado y vuelve.
 *
 * Es el mismo botón porque es el mismo gesto: «he terminado con esta pantalla».
 * Lo que cambia es si dejaste algo pedido o no.
 *
 * Y es el mismo recién generado que al editar, como toda esta ficha. */
function partesPedidas(ficha) {
  const pedidas = Object.keys((APP.light.datos || {}).partes || {})
    .filter(parte => String(APP.light.feedback[parte] || '').trim());
  // cambiar la FUENTE (del estilo o del tono) también es pedirlo, aunque no
  // haya escrito nada en la caja de «qué le cambiarías»: son dos formas de
  // lo mismo
  if (ficha && fuenteCambiadaLight(ficha) && !pedidas.includes('estilo')) {
    pedidas.unshift('estilo');
  }
  if (ficha && fuenteTonoCambiadaLight(ficha) && !pedidas.includes('tono')) {
    pedidas.push('tono');
  }
  // y fotos nuevas o un personaje sin hoja: hay que dibujar
  if (ficha && personajesCambiadosLight(ficha) && !pedidas.includes('personajes')) {
    pedidas.push('personajes');
  }
  return pedidas;
}

/* LO QUE VA A COSTAR, sumado por el servidor. Aquí ponía «10 imágenes» escrito a
   mano —seis referencias más cuatro muestras— y el día que las muestras dejaron
   de dibujarse el número se quedó mintiendo. El precio sale de donde está el
   precio (`presets_light.imagenes_de_parte`). */
function imagenesDePartes(pedidas) {
  const tabla = (APP.light.datos || {}).imagenes_por_parte || {};
  const total = pedidas.reduce((suma, p) => suma + (Number(tabla[p]) || 0), 0);
  return total ? `${total} ${total === 1 ? 'imagen' : 'imágenes'}`
    : 'sin gastar imágenes';
}

function pieDeEstilo(ficha) {
  const pedidas = partesPedidas(ficha);
  const partes = (APP.light.datos || {}).partes || {};
  const caja = h('div', { clase: 'pie-light' });
  if (pedidas.length) {
    const plan = imagenesDePartes(pedidas);
    caja.appendChild(h('div', { clase: 'fila' },
      h('button', {
        clase: 'primario', onclick: () => regenerarPedidasLight(ficha, pedidas),
      }, 'Regenerar'),
      h('span', { clase: 'meta' },
        `${pedidas.map(p => partes[p] || p).join(' y ')} · ${plan}`
        + ((fuenteCambiadaLight(ficha) || fuenteTonoCambiadaLight(ficha))
          ? ' · desde la fuente nueva' : ''))));
    /* CON EL ESTILO, ESA CIFRA ES UN TECHO Y NO UN PRECIO, y hay que decirlo:
       el motor lee lo que has escrito y decide qué hace falta rehacer, así que
       lo normal es que gaste menos. Decir el precio antes de pulsar es la regla
       de la casa; una cifra que el motor va a desmentir hacia abajo miente
       igual que una que se queda corta. Es la misma forma en que el repaso
       enuncia su política antes de aplicar. */
    if (pedidas.includes('estilo') && !fuenteCambiadaLight(ficha)) {
      caja.appendChild(h('div', { clase: 'meta' },
        'Es un techo, no un precio: el motor lee lo que has escrito y rehace '
        + 'sólo lo que haga falta. Si basta con el texto en pantalla —el '
        + 'tamaño del subtítulo, su caja, la familia de los rótulos— no se '
        + 'dibuja ninguna imagen.'));
    }
  } else {
    caja.appendChild(h('div', { clase: 'fila' },
      h('button', {
        clase: 'primario',
        onclick: async () => {
          await volcarPresetLight();
          await cargarGaleriaLight(true);
          irALight('galeria');
          toast(`«${ficha.nombre}» guardado`);
        },
      }, 'Guardar'),
      h('span', { clase: 'meta' },
        'lo que cambias se guarda solo; esto lo adelanta y vuelve a tus estilos')));
  }
  return caja;
}

/* Repinta SOLO el pie. El formulario entero no se puede repintar mientras
   escribes: tira el foco del campo, que es la misma razón por la que el
   autoguardado tampoco repinta (ver INTERFAZ.md). */
function repintarPieDeEstilo() {
  const viejo = document.querySelector('.light-preset .pie-light');
  if (!viejo) return;
  const ficha = fichaLight(APP.light.abierto);
  if (!ficha) return;
  viejo.replaceWith(pieDeEstilo(ficha));
}

/* Rehacer varias partes es lanzarlas una detrás de otra: cada una es su propio
   trabajo en el servidor, y encadenarlas aquí sería el error que las recetas ya
   corrigieron —un encadenado en el navegador se rompe al recargar—. Así que se
   lanza la primera y las demás quedan pedidas para cuando termine. */
async function regenerarPedidasLight(ficha, pedidas) {
  APP.light.cola = pedidas.slice(1);
  await regenerarParteLight(ficha, pedidas[0]);
}

/* AUTOGUARDADO, con lo pendiente a la vista para poder adelantarlo. Los
   cambios se acumulan --el nombre y el idioma se tocan seguidos-- y salen en un
   solo PUT 900 ms después del último toque, que es la misma regla del resto de
   la interfaz. `volcarPresetLight` es lo que hace que el botón «Guardar» no sea
   decorativo: escribe YA lo que quedara sin escribir. */
function guardarPresetLight(id, cambios, repintar) {
  APP.light.pendiente = Object.assign({}, APP.light.pendiente, cambios, { id });
  clearTimeout(APP.light.guardando);
  APP.light.guardando = setTimeout(() => volcarPresetLight(repintar), 900);
}

async function volcarPresetLight(repintar) {
  clearTimeout(APP.light.guardando);
  const pendiente = APP.light.pendiente;
  if (!pendiente) return;
  APP.light.pendiente = null;
  const { id, ...cambios } = pendiente;
  try {
    const datos = await pedir(API.presetLight(id),
      { method: 'PUT', cuerpo: cambios });
    const nueva = datos.preset;
    if (nueva && APP.light.datos) {
      APP.light.datos.presets = presetsLight().map(p => (p.id === id ? nueva : p));
    }
    /* CAMBIAR EL IDIOMA ADAPTA, y el servidor devuelve el trabajo. No cuesta
       ninguna imagen —se reescriben las instrucciones y se vuelve a componer el
       texto sobre los planos limpios— pero tarda su medio minuto, así que se
       enseña como lo que es. */
    if (datos.trabajo_id) {
      irALight('generando', { plan: datos.plan || null, abierto: id });
      seguirTrabajo(CLAVE_LIGHT, datos.trabajo_id, alTerminarLight,
        () => pintarLight());
      return;
    }
    if (datos.aviso) toast(datos.aviso, true);
    if (repintar) pintarLight();
  } catch (e) {
    toast(`no se ha podido guardar: ${e.message}`, true);
  }
}

async function regenerarParteLight(ficha, parte) {
  const peticion = String(APP.light.feedback[parte] || '').trim();
  const cuerpo = { parte, peticion };
  // la fuente solo viaja si de verdad ha cambiado: mandarla siempre haria que
  // corregir con una frase volviera a bajar el video
  if (parte === 'estilo' && fuenteCambiadaLight(ficha)) {
    cuerpo.origen = fuenteParaServidor(ficha);
  }
  if (parte === 'tono' && fuenteTonoCambiadaLight(ficha)) {
    cuerpo.origen = fuenteTonoParaServidor();
  }
  // los personajes viajan ENTEROS cuando la pantalla los tiene: el servidor
  // casa por id y las fotos nuevas (del buzon) sustituyen a las de antes
  if (parte === 'personajes' && APP.light.personajes
      && APP.light.personajes.preset === ficha.id) {
    cuerpo.origen = { personajes: personajesParaServidor(ficha) };
  }
  try {
    const datos = await pedir(API.presetLightRegenerar(ficha.id),
      { method: 'POST', cuerpo });
    APP.light.feedback = Object.assign({}, APP.light.feedback, { [parte]: '' });
    // la fuente ya está lanzada: dejarla puesta haría que al volver la pantalla
    // siguiera diciendo «cambiada» y el botón pidiera rehacerla otra vez
    if (cuerpo.origen && parte === 'estilo') APP.light.fuente = null;
    if (cuerpo.origen && parte === 'tono') APP.light.fuenteTono = null;
    if (parte === 'personajes') APP.light.personajes = null;
    /* «ESTO NO TIENE MANDO» ES UNA RESPUESTA, no un fallo: el motor ha leído la
       frase y no hay nada que rehacer con ella. Se dice y no se lanza nada —
       lanzar un trabajo vacío la enseñaría como un cambio aplicado, que es el
       fallo mudo que este reparto viene a cerrar. */
    if (datos.sin_cambios || !datos.trabajo_id) {
      toast(datos.aviso || 'no hay nada que rehacer con eso', true);
      pintarLight();
      return;
    }
    APP.light.reparto = (datos.reparto || {}).resumen || null;
    ((datos.reparto || {}).avisos || []).forEach(a => toast(a, true));
    irALight('generando', { plan: datos.plan || null, abierto: ficha.id });
    seguirTrabajo(CLAVE_LIGHT, datos.trabajo_id, alTerminarLight, () => pintarLight());
  } catch (e) {
    toast(`no se ha podido rehacer: ${e.message}`, true);
  }
}

async function borrarPresetLight(ficha) {
  if (!window.confirm(`¿Mandar el estilo «${ficha.nombre}» a la papelera?\n\n`
    + 'Se puede recuperar desde la papelera.')) return;
  try {
    await pedir(API.presetLight(ficha.id), { method: 'DELETE' });
    toast(`«${ficha.nombre}» apartado`);
    await cargarGaleriaLight(true);
    irALight('galeria', { abierto: null });
  } catch (e) {
    toast(`no se ha podido borrar: ${e.message}`, true);
  }
}

/* Un textarea que crece con el texto. Es campoTexto pero de varias líneas: los
   campos de este modo son párrafos, no palabras. Sin etiqueta si el bloque que
   lo contiene ya dice lo que es -- que es el caso de las cuatro cajas. */
function campoArea(etiqueta, valor, alCambiar, pista, foco) {
  const area = h('textarea', { rows: 2, placeholder: pista || '' });
  // el nombre con el que se le devuelve el foco despues de repintar
  if (foco) area.dataset.foco = foco;
  area.value = valor || '';
  area.addEventListener('input', () => { alCambiar(area.value); });
  crecerConElTexto(area);
  return h('div', { clase: 'campo' },
    etiqueta ? h('label', {}, etiqueta) : null,
    cajaCampo(area, { clase: 'area' }));
}

/* ============================================================ LA GUÍA DE INICIO
 *
 * Lo primero que se ve al entrar por primera vez: una tarjeta detrás de otra
 * pidiendo lo que hace falta para que el Estudio pueda hacer algo, con los
 * pasos para conseguir cada cosa y el enlace a donde se consigue. Es la misma
 * pantalla de Configuración, contada en orden y de una en una: lo que se guarda
 * aquí se guarda en el mismo sitio (`/api/claves`) y se cambia luego desde el
 * engranaje.
 *
 * EL ORDEN NO ES CASUAL. Claude va la primera porque es un LOGIN y no una clave
 * —sale un enlace, se entra, se pega un código— y porque con ella entra en
 * juego el asistente de la burbuja, que a partir de ahí puede ayudar con el
 * resto. Después OpenAI (los planos) y Cartesia (la voz), que hacen falta las
 * dos; y las de música y efectos las últimas, porque son las únicas que se
 * pueden dejar: si no están, el Estudio lo ve y no las pide.
 *
 * SE VE UNA VEZ POR INSTALACIÓN, no por navegador: la marca (`onboarding_visto`)
 * vive en los ajustes del servidor. Desde el móvil no hay que volver a pasar
 * por ella. Y «Saltar por ahora» también la marca: una guía que reaparece en
 * cada carga hasta que se rellene todo es una pantalla que se aprende a
 * cerrar sin leer.
 */

const INICIO = { abierta: false, paso: 0, arrancando: false, accesoFallido: '' };

/* Las paradas de la guía. Cada una pinta su cuerpo con lo que haya cargado en
   `estadoConfig()` (las claves y las cuentas del CLI, que son las mismas que
   ve Configuración). */
const TARJETAS_INICIO = [
  { id: 'bienvenida', titulo: 'Bienvenido a AS Video Studio', pinta: tarjetaBienvenidaInicio },
  { id: 'claude', titulo: '1 · Tu cuenta de Claude', pinta: tarjetaClaudeInicio },
  { id: 'openai', titulo: '2 · La clave de OpenAI (imágenes)', pinta: tarjetaOpenAIInicio },
  { id: 'cartesia', titulo: '3 · La clave de Cartesia (voz)', pinta: tarjetaCartesiaInicio },
  { id: 'jamendo', titulo: '4 · La clave de Jamendo (música, opcional)', pinta: tarjetaJamendoInicio },
  { id: 'freesound', titulo: '5 · La clave de FreeSound (efectos, opcional)', pinta: tarjetaFreeSoundInicio },
  { id: 'listo', titulo: 'Todo listo', pinta: tarjetaFinalInicio },
];

/* Se decide DESPUÉS de cargar los proyectos: la guía se pinta encima de la
   pantalla de verdad, no encima de un «cargando…». Un servidor sin la marca
   (una versión anterior) no la enseña nunca. */
async function decidirOnboarding() {
  try {
    const r = await pedir(API.ajustes());
    if (r.ajustes && r.ajustes.onboarding_visto === false) abrirInicio(0);
  } catch (e) { /* sin ajustes no hay guía, y no pasa nada */ }
}

function abrirInicio(paso) {
  INICIO.abierta = true;
  INICIO.paso = Math.max(0, Math.min(TARJETAS_INICIO.length - 1, paso || 0));
  if (!$('#inicio')) {
    document.body.appendChild(h('div', { id: 'inicio' }, h('div', { clase: 'cuadro' })));
  }
  pintarInicio();
  // las claves y las cuentas se piden aparte y repintan al llegar
  cargarClaves();
  refrescarEstadoAsistente();
}

function cerrarInicio(marcarVisto) {
  INICIO.abierta = false;
  const capa = $('#inicio');
  if (capa) capa.remove();
  if (marcarVisto) {
    pedir(API.ajustes(), { method: 'PUT', cuerpo: { onboarding_visto: true } })
      .catch(e => console.error(e));
  }
}

function irAInicio(paso) {
  INICIO.paso = Math.max(0, Math.min(TARJETAS_INICIO.length - 1, paso));
  pintarInicio();
}

function pintarInicio() {
  const capa = $('#inicio');
  if (!capa || !INICIO.abierta) return;
  const cuadro = vaciar(capa.querySelector('.cuadro'));
  const n = INICIO.paso;
  const tarjeta = TARJETAS_INICIO[n];
  const ultima = n === TARJETAS_INICIO.length - 1;

  cuadro.appendChild(h('div', { clase: 'inicio-cab' },
    h('span', { clase: 'paso-de' }, `guía de inicio · ${n + 1} de ${TARJETAS_INICIO.length}`),
    h('span', { clase: 'crece' }),
    h('div', { clase: 'inicio-puntos' },
      TARJETAS_INICIO.map((t, i) => h('span', {
        clase: i < n ? 'hecho' : (i === n ? 'actual' : ''),
        title: t.titulo,
      }))),
    h('button', {
      clase: 'mini fantasma', title: 'Cerrar la guía; todo esto está en Configuración',
      onclick: () => cerrarInicio(true),
    }, 'Saltar por ahora')));

  const cuerpo = h('div', { clase: 'inicio-cuerpo' }, h('h2', {}, tarjeta.titulo));
  meter(cuerpo, [tarjeta.pinta()]);
  cuadro.appendChild(cuerpo);

  cuadro.appendChild(h('div', { clase: 'inicio-pie' },
    n > 0 ? h('button', { clase: 'mini fantasma', onclick: () => irAInicio(n - 1) }, '‹ Atrás') : null,
    h('span', { clase: 'crece' }),
    ultima
      ? h('button', { clase: 'primario', onclick: () => cerrarInicio(true) }, 'Empezar')
      : h('button', { clase: 'primario', onclick: () => irAInicio(n + 1) },
        n === 0 ? 'Vamos' : 'Siguiente ›')));
}

/* Un enlace que se abre aparte: la guía sigue debajo esperando la clave. */
function enlaceInicio(texto, url) {
  return h('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, texto);
}

/* «Puesta» o «sin poner», con lo que hay guardado. La clave nunca baja al
   navegador: se enseña la cola, como en Configuración. */
function estadoClaveInicio(puesta, cola) {
  return h('div', { clase: 'inicio-hecho' },
    pastillaEstado(puesta ? 'ok' : 'error', puesta ? `puesta (${cola})` : 'sin poner'),
    h('span', { clase: 'meta' }, puesta
      ? 'Ya está. Puedes cambiarla aquí mismo o seguir.'
      : 'Pégala aquí cuando la tengas.'));
}

/* El campo de una clave con su botón. `guardar` recibe la clave y devuelve la
   promesa de `guardarClaves`, que repinta esta tarjeta al terminar. */
function campoClaveInicio(placeholder, guardar) {
  const campo = h('input', { type: 'password', placeholder, autocomplete: 'off' });
  const mandar = () => {
    if (!campo.value.trim()) { toast('pega la clave primero', true); return; }
    guardar(campo.value.trim());
    campo.value = '';
  };
  campo.addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); mandar(); } });
  return h('div', { clase: 'fila-clave' }, campo,
    h('button', { clase: 'primario mini', onclick: mandar }, 'Guardar'));
}

function tarjetaBienvenidaInicio() {
  return [
    h('div', { clase: 'pista' },
      'Esto convierte lo que escribas —unas notas, un artículo, tu propio guion— '
      + 'en un vídeo de animación narrada, en varios pasos con revisión entre '
      + 'ellos. Para que pueda hacerlo necesita hablar con cinco servicios, y '
      + 'cada uno pide su llave. Esta guía te lleva a por ellas una a una, con el '
      + 'enlace de cada sitio.'),
    h('ol', { clase: 'inicio-pasos' },
      h('li', {}, h('b', {}, 'Claude'), ': tu cuenta, no una clave. Escribe el guion, el '
        + 'catálogo visual y los rótulos, y mueve al asistente de la burbuja.'),
      h('li', {}, h('b', {}, 'OpenAI'), ': con ella se dibujan los planos.'),
      h('li', {}, h('b', {}, 'Cartesia'), ': la voz que narra.'),
      h('li', {}, h('b', {}, 'Jamendo y FreeSound'), ': música y efectos. Son las dos únicas que se '
        + 'pueden dejar para luego; las otras tres hacen falta.')),
    h('div', { clase: 'caja-info' },
      'Abajo a la derecha hay una burbuja: es el asistente. Sabe cómo funciona '
      + 'todo esto y ve lo que está pasando en tu Estudio, así que cuando algo '
      + 'falle o no sepas seguir, pregúntale. Contesta con tu propia cuenta de '
      + 'Claude, que es lo primero que vamos a dejar puesto.'),
    h('div', { clase: 'meta' },
      'Todo lo que pongas aquí se cambia después desde Configuración, el '
      + 'engranaje de arriba a la derecha.'),
  ];
}

/* LA CUENTA DE LA GUÍA ES UNA. La cadena de cuentas de respaldo sigue en
 * Configuración para quien la necesite; aquí se entra con una y ya: la
 * primera de la lista (la que manda) o, si no hay ninguna, se crea sola.
 *
 * Y EN EL MÍNIMO DE CLICS. Sin sesión, el acceso ARRANCA SOLO al abrir la
 * tarjeta: el enlace ya está esperando, no hay un botón de «Entrar» que
 * pulsar antes. Después son dos gestos: abrir el enlace y pegar el código,
 * que se envía en cuanto se pega. Con sesión, se entra directamente en el
 * estado de la cuenta y, si la última llamada falló (cupo agotado, sesión
 * caducada), se dice aquí mismo. */
function cuentaDeLaGuia() {
  const cuentas = ((estadoConfig().cli || {}).cuentas) || [];
  return cuentas[0] || null;
}

function tarjetaClaudeInicio() {
  const cli = estadoConfig().cli;
  const estado = ASISTENTE.estado;
  const partes = [
    h('div', { clase: 'pista' },
      'Con Claude no va una clave: va tu SESIÓN. El Estudio gasta tu '
      + 'suscripción de Claude, nunca pago por uso, y el asistente contesta con '
      + 'ella. Hace falta una suscripción (Pro o Max): si no la tienes, se '
      + 'contrata en '),
  ];
  partes[0].appendChild(enlaceInicio('claude.ai', 'https://claude.ai/'));
  partes[0].appendChild(document.createTextNode('.'));
  if (!cli) {
    partes.push(h('div', { clase: 'cargando' }, 'mirando la cuenta…'));
    return partes;
  }
  if (cli.error) {
    partes.push(h('div', { clase: 'caja-error' }, cli.error));
    return partes;
  }
  const cuenta = cuentaDeLaGuia();
  const sesion = (cuenta && cuenta.sesion) || {};
  const intento = cuenta && cuenta.intento;
  const abierto = !!(intento && ['abriendo', 'enlace', 'probando'].includes(intento.estado));
  // Lo que manda es con qué contestaría el Estudio (/api/asistente): la
  // cuenta de la lista si tiene sesión, o la sesión por defecto del CLI si no
  // hay ninguna usable. Una cuenta añadida y abandonada a medias no tapa una
  // sesión por defecto que funciona.
  const buena = estado && estado.listo ? estado.cuenta : null;
  const candidata = ((estado && estado.cuentas) || []).find(c => !c.motivo) || null;
  const dentro = !!buena || !!sesion.conectada;
  const salud = (cuenta && sesion.conectada && cuenta.salud) || (candidata && candidata.salud) || null;
  const correo = (buena && buena.correo) || sesion.correo;
  const plan = (buena && buena.plan) || sesion.plan;
  const probable = cuenta && sesion.conectada ? cuenta.id : '';

  if (dentro && !abierto) {
    partes.push(h('div', { clase: 'inicio-hecho' },
      pastillaEstado('ok', 'con sesión'),
      pastillaSalud(salud),
      h('span', { clase: 'meta' },
        `Entrado como ${correo || 'tu cuenta'}${plan ? ` (${plan})` : ''}.`)));
    const aviso = avisoSalud(salud);
    if (aviso) partes.push(aviso);
    partes.push(h('div', { clase: 'fila' },
      h('button', {
        clase: 'mini', disabled: !!(estadoConfig().probando || ASISTENTE.probando),
        onclick: () => (probable ? probarCuentaCLI(probable) : probarAsistente().then(repintarClaves)),
      }, (estadoConfig().probando || ASISTENTE.probando) ? 'probando…' : 'Probar que contesta'),
      h('button', {
        clase: 'mini fantasma',
        onclick: () => arrancarAccesoGuia(cuenta),
      }, 'Entrar con otra cuenta')));
    return partes;
  }

  partes.push(h('ol', { clase: 'inicio-pasos' },
    h('li', {}, 'Abre el enlace de abajo —vale desde el móvil— y entra con tu cuenta.'),
    h('li', {}, 'Copia el código que te dé la página y pégalo aquí: se envía solo.')));

  if (INICIO.accesoFallido) {
    partes.push(h('div', { clase: 'caja-error' }, INICIO.accesoFallido));
    partes.push(h('div', { clase: 'fila' }, h('button', {
      clase: 'primario mini',
      onclick: () => { INICIO.accesoFallido = ''; arrancarAccesoGuia(cuenta); },
    }, 'Volver a intentarlo')));
    return partes;
  }
  if (!abierto) {
    // el acceso arranca solo: sin botón que pulsar antes del enlace
    if (!INICIO.arrancando) arrancarAccesoGuia(cuenta);
    partes.push(h('div', { clase: 'cargando' }, 'pidiéndole el enlace a Claude…'));
    return partes;
  }
  partes.push(pasoDelAccesoGuia(cuenta, intento));
  return partes;
}

/* Arranca el acceso de la cuenta de la guía, creándola si no existe. Una sola
   vez por pantalla: la tarjeta se repinta con cada cambio y sin el candado
   pediría un enlace nuevo en cada repintado. */
async function arrancarAccesoGuia(cuenta) {
  if (INICIO.arrancando) return;
  INICIO.arrancando = true;
  try {
    let id = cuenta && cuenta.id;
    if (!id) {
      const vista = estadoConfig();
      vista.ficha = await pedir(API.claves(), {
        method: 'PUT', cuerpo: { claude_cli: { cuentas: [{ etiqueta: '' }] } },
      });
      id = vista.ficha.claude_cli.cuentas[0].id;
      await cargarCuentasCLI();
    }
    const r = await pedir(API.entrarCLI(id), { method: 'POST' });
    estadoConfig().cli = Object.assign({}, estadoConfig().cli, { cuentas: r.cuentas });
    estadoConfig().codigos[id] = '';
    if (r.intento && r.intento.estado === 'fallo') {
      INICIO.accesoFallido = r.intento.mensaje || 'no se ha podido pedir el enlace';
    }
  } catch (e) {
    INICIO.accesoFallido = e.message;
  } finally {
    INICIO.arrancando = false;
  }
  repintarClaves();
  latirCLI();
}

/* El acceso en la guía: el enlace como botón grande y el código que se envía
   al pegarlo. Los estados son los del servidor (`login_cli.Intento`). */
function pasoDelAccesoGuia(cuenta, intento) {
  const vista = estadoConfig();
  if (intento.estado === 'abriendo') {
    return h('div', { clase: 'cli-acceso' },
      h('div', { clase: 'cargando' }, 'pidiéndole el enlace a Claude…'));
  }
  const caja = h('textarea', {
    rows: 2, placeholder: 'pega aquí el código: se envía solo',
    value: vista.codigos[cuenta.id] || '',
    disabled: intento.estado === 'probando',
    oninput: e => { vista.codigos[cuenta.id] = e.target.value; },
  });
  const mandar = () => mandarCodigoCLI(cuenta.id, caja.value.trim());
  // al PEGAR se manda solo: el evento llega antes de que el texto esté en el
  // campo, así que se espera al siguiente tic
  caja.addEventListener('paste', () => setTimeout(mandar, 0));
  caja.addEventListener('keydown', ev => {
    if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); mandar(); }
  });
  return h('div', { clase: 'cli-acceso' },
    h('a', { clase: 'cli-enlace grande', href: intento.enlace, target: '_blank',
      rel: 'noopener noreferrer' }, '1 · Abrir la página de acceso'),
    h('div', { clase: 'fila' },
      h('button', {
        clase: 'mini fantasma',
        onclick: () => { navigator.clipboard.writeText(intento.enlace)
          .then(() => toast('enlace copiado'), () => toast('no se ha podido copiar', true)); },
      }, 'Copiar el enlace'),
      h('span', { clase: 'meta' }, `caduca en ${Math.ceil(intento.caduca_en / 60)} min`)),
    h('div', { clase: 'meta' }, '2 · Pega el código entero, incluido lo que va detrás de la almohadilla:'),
    caja,
    intento.mensaje ? h('div', { clase: 'meta aviso' }, intento.mensaje) : null,
    intento.estado === 'probando' ? h('div', { clase: 'cargando' }, 'comprobando el código…') : null,
    intento.estado === 'fallo' ? h('div', { clase: 'fila' },
      h('button', { clase: 'mini primario', onclick: () => arrancarAccesoGuia(cuenta) },
        'Pedir otro enlace')) : null);
}

function tarjetaOpenAIInicio() {
  const ficha = estadoConfig().ficha;
  const puesta = !!(ficha && ficha.openai && ficha.openai.length);
  return [
    h('div', { clase: 'pista' },
      'Con esta clave se dibujan los planos: sin ella no hay vídeo. Cada imagen '
      + 'se paga; un vídeo de cuatro minutos son unos 4,4 $ en calidad baja.'),
    h('ol', { clase: 'inicio-pasos' },
      h('li', {}, 'Entra en ', enlaceInicio('platform.openai.com', 'https://platform.openai.com/'),
        ' y crea una cuenta si no la tienes.'),
      h('li', {}, 'Carga saldo en ',
        enlaceInicio('Billing', 'https://platform.openai.com/settings/organization/billing/overview'),
        ' («Add to credit balance»). Sin saldo la clave existe pero no genera nada.'),
      h('li', {}, 'Ve a ', enlaceInicio('API keys', 'https://platform.openai.com/api-keys'),
        ' → «Create new secret key». Cópiala entera (empieza por sk-) y pégala aquí: '
        + 'OpenAI sólo la enseña una vez.')),
    ficha ? estadoClaveInicio(puesta, puesta ? ficha.openai[0].cola : '')
      : h('div', { clase: 'cargando' }, 'leyendo las claves…'),
    campoClaveInicio('sk-…', clave => guardarClaves({
      openai: [{ etiqueta: '', clave, activa: true }] })),
  ];
}

function tarjetaCartesiaInicio() {
  const ficha = estadoConfig().ficha;
  const puesta = !!(ficha && ficha.cartesia && ficha.cartesia.puesta);
  return [
    h('div', { clase: 'pista' },
      'Cartesia pone la voz que narra el vídeo: sin ella no hay locución. Una '
      + 'sola clave, y la locución se sintetiza de una tirada.'),
    h('ol', { clase: 'inicio-pasos' },
      h('li', {}, 'Crea una cuenta en ', enlaceInicio('play.cartesia.ai', 'https://play.cartesia.ai/'),
        '. El plan gratuito da para probar.'),
      h('li', {}, 'En el menú de la izquierda, ',
        enlaceInicio('API Keys', 'https://play.cartesia.ai/keys'), ' → «Create API key».'),
      h('li', {}, 'Cópiala y pégala aquí.')),
    ficha ? estadoClaveInicio(puesta, puesta ? ficha.cartesia.cola : '')
      : h('div', { clase: 'cargando' }, 'leyendo las claves…'),
    campoClaveInicio('la clave de Cartesia', clave => guardarClaves({ cartesia: { clave } })),
  ];
}

function tarjetaJamendoInicio() {
  const ficha = estadoConfig().ficha;
  const jamendo = (ficha && ficha.jamendo) || {};
  return [
    h('div', { clase: 'pista' },
      'Jamendo es un catálogo de música con licencia libre: de ahí sale la banda '
      + 'sonora. Es una de las dos que se pueden dejar: si no está, el Estudio lo '
      + 've y monta el vídeo sin música, sin pedirla. Se puede poner otro día '
      + 'desde Configuración.'),
    h('ol', { clase: 'inicio-pasos' },
      h('li', {}, 'Crea una cuenta de desarrollador en ',
        enlaceInicio('devportal.jamendo.com', 'https://devportal.jamendo.com/'), '.'),
      h('li', {}, 'En ', enlaceInicio('Applications', 'https://devportal.jamendo.com/admin/applications'),
        ' → «New application»: vale con cualquier nombre y descripción.'),
      h('li', {}, 'Copia el ', h('b', {}, 'Client ID'), ' de la aplicación y pégalo aquí.')),
    ficha ? estadoClaveInicio(!!jamendo.puesta, jamendo.cola || '')
      : h('div', { clase: 'cargando' }, 'leyendo las claves…'),
    campoClaveInicio('el Client ID de Jamendo', clave => guardarClaves({ jamendo: { clave } })),
  ];
}

function tarjetaFreeSoundInicio() {
  const ficha = estadoConfig().ficha;
  const freesound = (ficha && ficha.freesound) || {};
  return [
    h('div', { clase: 'pista' },
      'FreeSound es un catálogo de efectos de sonido con licencia libre. Es la '
      + 'otra que se puede dejar: sin ella el vídeo se monta sin efectos, y el '
      + 'Estudio no los pide. Se puede poner otro día desde Configuración.'),
    h('ol', { clase: 'inicio-pasos' },
      h('li', {}, 'Crea una cuenta en ', enlaceInicio('freesound.org', 'https://freesound.org/home/register/'), '.'),
      h('li', {}, 'Pide una clave en ', enlaceInicio('freesound.org/apiv2/apply', 'https://freesound.org/apiv2/apply'),
        ': vale con cualquier nombre y descripción, y se concede al momento.'),
      h('li', {}, 'En la tabla de tus credenciales, copia la columna ',
        h('b', {}, 'Client secret/Api key'), ' y pégala aquí. El Client id no hace falta: '
        + 'es para el acceso OAuth, que el Estudio no usa.')),
    ficha ? estadoClaveInicio(!!freesound.puesta, freesound.cola || '')
      : h('div', { clase: 'cargando' }, 'leyendo las claves…'),
    campoClaveInicio('la API key de FreeSound', clave => guardarClaves({ freesound: { clave } })),
  ];
}

function tarjetaFinalInicio() {
  const ficha = estadoConfig().ficha || {};
  const cli = estadoConfig().cli;
  const estado = ASISTENTE.estado;
  const cuentas = (cli && cli.cuentas) || [];
  const claude = cuentas.some(c => c.sesion && c.sesion.conectada) || !!(estado && estado.listo);
  const fila = (nombre, puesta, opcional) => h('div', { clase: 'inicio-hecho' },
    pastillaEstado(puesta ? 'ok' : (opcional ? 'parcial' : 'error'),
      puesta ? 'puesta' : (opcional ? 'para luego' : 'sin poner')),
    h('span', {}, nombre));
  const faltan = [!claude, !(ficha.openai && ficha.openai.length), !(ficha.cartesia && ficha.cartesia.puesta)]
    .filter(Boolean).length;
  return [
    fila('Claude — guion, catálogo, rótulos y el asistente', claude),
    fila('OpenAI — imágenes', !!(ficha.openai && ficha.openai.length)),
    fila('Cartesia — voz', !!(ficha.cartesia && ficha.cartesia.puesta)),
    fila('Jamendo — música', !!(ficha.jamendo && ficha.jamendo.puesta), true),
    fila('FreeSound — efectos', !!(ficha.freesound && ficha.freesound.puesta), true),
    faltan
      ? h('div', { clase: 'caja-aviso' },
        `Falta${faltan > 1 ? 'n' : ''} ${faltan} de las tres que hacen falta para un vídeo `
        + '(Claude, OpenAI y Cartesia). Sin ellas no sale el vídeo entero: se '
        + 'ponen desde Configuración, el engranaje de arriba a la derecha.')
      : h('div', { clase: 'caja-info' },
        'Está todo. Lo siguiente es crear un estilo (cómo se dibuja y cómo se '
        + 'cuenta) y, con él, el primer vídeo.'),
    bloquePruebaClaves(),
    h('div', { clase: 'meta' },
      'Y si algo no cuadra en cualquier momento, la burbuja de abajo a la derecha '
      + 'es el asistente: pregúntale.'),
  ];
}

/* ================================================================ EL ASISTENTE
 *
 * La burbuja de abajo a la derecha. Es un chat con el CLI de Claude que tiene
 * delante la documentación del producto, el código y una foto del estado del
 * Estudio en el momento de cada pregunta: qué claves hay, qué vídeo está
 * abierto, qué paso está parado y con qué error. Lo que sabe y lo que no puede
 * tocar está en `pasos/asistente.py`.
 *
 * ESTÁ DESDE EL PRIMER DÍA, sin ninguna clave: si el CLI no tiene sesión la
 * burbuja lo dice y manda a entrar (a la tarjeta de Claude de la guía). No se
 * esconde, porque justo la persona que aún no tiene nada puesto es la que más
 * preguntas tiene.
 *
 * LA CHARLA VIVE EN EL SERVIDOR y aquí sólo se guarda su id: recargar la página
 * o cambiar de vídeo a mitad de una respuesta tiene que reencontrarla donde
 * estaba. Si el servicio se reinicia la charla se pierde y se abre otra sin
 * hacer ruido. La respuesta se sigue PREGUNTANDO cada segundo y medio, no con
 * una petición larga: detrás de un proxy una petición de un minuto se corta a
 * los sesenta segundos sin decir por qué.
 */

const ASISTENTE = {
  abierto: false,
  estado: null,        // /api/asistente: {listo, motivo, cuenta}
  charla: null,        // la ficha de la charla, tal como la da el servidor
  latiendo: false,
  arranque: 0,         // cuándo se mandó la última pregunta, para el «pensando… N s»
  sinLeer: false,      // llegó una respuesta con el cajón cerrado
};

const CLAVE_CHARLA = 'estudio.asistente.charla';

function montarAsistente() {
  const burbuja = $('#burbuja-asistente');
  if (!burbuja) return;
  burbuja.addEventListener('click', () => conmutarAsistente());
  $('#btn-cerrar-asistente').addEventListener('click', () => conmutarAsistente(false));
  $('#btn-nueva-charla').addEventListener('click', () => nuevaCharla());
  $('#btn-enviar-asistente').addEventListener('click', () => enviarAlAsistente());
  $('#btn-cancelar-asistente').addEventListener('click', () => cancelarAsistente());
  const campo = $('#asistente-texto');
  // Enter manda; con mayúsculas, salto de línea. Es lo que hace cualquier chat.
  campo.addEventListener('keydown', ev => {
    if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); enviarAlAsistente(); }
  });
  refrescarEstadoAsistente();
}

async function refrescarEstadoAsistente() {
  try {
    ASISTENTE.estado = await pedir(API.asistente());
  } catch (e) {
    ASISTENTE.estado = { listo: false, motivo: e.message, viejo: true };
  }
  pintarAsistente();
  // Una cuenta con sesión de la que no se sabe nada se prueba SOLA, una vez
  // por página: es lo que hace que el cupo agotado se vea antes de preguntar.
  if (ASISTENTE.estado.sin_probar && !ASISTENTE.probado && !ASISTENTE.probando) {
    ASISTENTE.probado = true;
    probarAsistente();
  }
}

async function probarAsistente() {
  if (ASISTENTE.probando) return;
  ASISTENTE.probando = true;
  pintarAsistente();
  try {
    ASISTENTE.estado = await pedir(API.probarAsistente(), { method: 'POST' });
  } catch (e) {
    toast(e.message, true);
  } finally {
    ASISTENTE.probando = false;
  }
  pintarAsistente();
  if (estadoConfig().cli) cargarCuentasCLI();
}

function conmutarAsistente(abrir) {
  const cajon = $('#asistente');
  if (!cajon) return;
  const quiero = abrir === undefined ? cajon.classList.contains('plegado') : !!abrir;
  cajon.classList.toggle('plegado', !quiero);
  ASISTENTE.abierto = quiero;
  $('#burbuja-asistente').classList.toggle('abierta', quiero);
  if (!quiero) return;
  ASISTENTE.sinLeer = false;
  refrescarEstadoAsistente();
  recuperarCharla().then(() => {
    const campo = $('#asistente-texto');
    if (campo && !campo.disabled) campo.focus();
  });
}

/* La charla de la última vez, si el servidor la recuerda. */
async function recuperarCharla() {
  const id = localStorage.getItem(CLAVE_CHARLA);
  if (id && (!ASISTENTE.charla || ASISTENTE.charla.id !== id)) {
    try {
      ASISTENTE.charla = await pedir(API.charla(id));
    } catch (e) {
      ASISTENTE.charla = null;
      localStorage.removeItem(CLAVE_CHARLA);
    }
  }
  pintarAsistente();
  latirAsistente();
}

async function asegurarCharla() {
  if (ASISTENTE.charla) return ASISTENTE.charla;
  ASISTENTE.charla = await pedir(API.charlas(), { method: 'POST' });
  localStorage.setItem(CLAVE_CHARLA, ASISTENTE.charla.id);
  return ASISTENTE.charla;
}

function nuevaCharla() {
  const vieja = ASISTENTE.charla;
  if (vieja) pedir(API.charla(vieja.id), { method: 'DELETE' }).catch(() => {});
  ASISTENTE.charla = null;
  ASISTENTE.latiendo = false;
  localStorage.removeItem(CLAVE_CHARLA);
  pintarAsistente();
  const campo = $('#asistente-texto');
  if (campo && !campo.disabled) campo.focus();
}

/* Lo que la pantalla tiene delante y el servidor no puede saber: en qué
   parada está, y los errores que hay a la vista (ERRORES, los mismos que se
   pintan junto al botón que falló). Es lo que hace que «me ha dado este
   error» se pueda preguntar sin pegar nada. */
function fotoDePantalla() {
  const errores = {};
  Object.keys(ERRORES).forEach(paso => { if (ERRORES[paso]) errores[paso] = String(ERRORES[paso]); });
  return { pestana: APP.activa, url: location.hash, errores };
}

async function enviarAlAsistente(reintento) {
  const campo = $('#asistente-texto');
  const texto = campo.value.trim();
  if (!texto) return;
  if (!ASISTENTE.estado || !ASISTENTE.estado.listo) {
    toast('el asistente necesita una sesión de Claude para contestar', true);
    return;
  }
  if (ASISTENTE.charla && ASISTENTE.charla.ocupada) {
    toast('espera a que termine la respuesta anterior', true);
    return;
  }
  campo.disabled = true;
  try {
    const charla = await asegurarCharla();
    ASISTENTE.arranque = Date.now();
    ASISTENTE.charla = await pedir(API.mensajesAsistente(charla.id), {
      method: 'POST',
      cuerpo: { texto, proyecto: APP.pid || '', pantalla: fotoDePantalla() },
    });
    campo.value = '';
    pintarAsistente();
    latirAsistente();
  } catch (e) {
    // El servicio se reinició y la charla ya no está: se abre otra y se
    // vuelve a mandar, una sola vez.
    if (!reintento && /ninguna charla/.test(e.message)) {
      ASISTENTE.charla = null;
      localStorage.removeItem(CLAVE_CHARLA);
      campo.disabled = false;
      return enviarAlAsistente(true);
    }
    toast(e.message, true);
    campo.disabled = false;
    pintarAsistente();
  }
}

async function cancelarAsistente() {
  const charla = ASISTENTE.charla;
  if (!charla) return;
  try {
    const r = await pedir(API.cancelarAsistente(charla.id), { method: 'POST' });
    ASISTENTE.charla = r.charla || ASISTENTE.charla;
    pintarAsistente();
  } catch (e) {
    toast(e.message, true);
  }
}

/* Mientras el último turno esté pensando se vuelve a pedir la charla. Sigue
   aunque el cajón se cierre: la respuesta tiene que estar cuando se vuelva a
   abrir, y la burbuja avisa de que llegó. */
function latirAsistente() {
  const charla = ASISTENTE.charla;
  if (!charla || !charla.ocupada || ASISTENTE.latiendo) return;
  ASISTENTE.latiendo = true;
  const tic = async () => {
    if (!ASISTENTE.latiendo || !ASISTENTE.charla) { ASISTENTE.latiendo = false; return; }
    try {
      ASISTENTE.charla = await pedir(API.charla(ASISTENTE.charla.id));
    } catch (e) {
      // un fallo puntual se reintenta; si la charla ya no existe, se suelta
      if (/ninguna charla/.test(e.message)) {
        ASISTENTE.charla = null;
        localStorage.removeItem(CLAVE_CHARLA);
        ASISTENTE.latiendo = false;
        pintarAsistente();
        return;
      }
    }
    pintarAsistente();
    if (ASISTENTE.charla && ASISTENTE.charla.ocupada) setTimeout(tic, 1500);
    else {
      ASISTENTE.latiendo = false;
      if (!ASISTENTE.abierto) { ASISTENTE.sinLeer = true; pintarAsistente(); }
    }
  };
  setTimeout(tic, 1500);
}

function pintarAsistente() {
  const cajon = $('#asistente');
  const burbuja = $('#burbuja-asistente');
  if (!cajon || !burbuja) return;
  const estado = ASISTENTE.estado;
  const listo = !!(estado && estado.listo);
  const charla = ASISTENTE.charla;
  const ocupada = !!(charla && charla.ocupada);

  burbuja.classList.toggle('sin-sesion', !listo);
  burbuja.classList.toggle('pensando', ocupada);
  burbuja.classList.toggle('aviso', ASISTENTE.sinLeer && !ocupada);
  burbuja.title = listo
    ? 'Asistente: pregunta lo que sea del Estudio'
    : 'Asistente: necesita que entres con tu cuenta de Claude';
  if (cajon.classList.contains('plegado')) return;

  const pastilla = vaciar($('#asistente-estado'));
  const cuentas = (estado && estado.cuentas) || [];
  const conCupoAgotado = cuentas.some(c => c.salud && c.salud.estado === 'cupo');
  const conSesion = cuentas.some(c => c.sesion);
  pastilla.appendChild(pastillaEstado(listo ? 'ok' : 'error',
    !estado ? 'mirando…'
      : ASISTENTE.probando ? 'comprobando…'
        : (listo ? ((estado.cuenta || {}).correo || 'con sesión')
          : (conCupoAgotado ? 'sin cupo' : (conSesion ? 'no contesta' : 'sin sesión')))));

  const cuerpo = vaciar($('#asistente-cuerpo'));
  if (estado && !listo) cuerpo.appendChild(puertaDelAsistente(estado));
  if (!charla || !(charla.turnos || []).length) {
    if (listo) cuerpo.appendChild(vacioDelAsistente());
  } else {
    charla.turnos.forEach(turno => cuerpo.appendChild(burbujaDeTurno(turno)));
  }
  cuerpo.scrollTop = cuerpo.scrollHeight;

  const campo = $('#asistente-texto');
  campo.disabled = !listo || ocupada;
  campo.placeholder = listo
    ? 'Pregunta lo que quieras: un error, un paso parado, dónde está algo…'
    : 'Entra con tu cuenta de Claude para poder preguntar';
  $('#btn-enviar-asistente').disabled = !listo || ocupada;
  $('#btn-cancelar-asistente').hidden = !ocupada;
  $('#btn-nueva-charla').disabled = ocupada || !charla;
}

/* Sin cuenta que conteste no hay asistente, y se dice POR QUÉ con el camino
   para arreglarlo: sin sesión, entrar; con el cupo agotado, la fecha en que se
   renueva y probar otra cuenta; con la sesión caducada, volver a entrar. */
function puertaDelAsistente(estado) {
  const cuentas = estado.cuentas || [];
  const conSesion = cuentas.filter(c => c.sesion);
  if (ASISTENTE.probando) {
    return h('div', { clase: 'asistente-puerta' },
      h('div', { clase: 'cargando' }, 'comprobando que tu cuenta de Claude contesta…'));
  }
  if (!conSesion.length) {
    return h('div', { clase: 'asistente-puerta' },
      h('div', { clase: 'caja-aviso' },
        'Para poder ayudarte necesito que entres primero con tu cuenta de Claude: '
        + 'contesto con tu propia suscripción, sin ninguna clave aparte. Hasta '
        + 'entonces no te puedo responder.'),
      estado.motivo ? h('div', { clase: 'meta' }, estado.motivo) : null,
      h('div', { clase: 'fila' },
        h('button', { clase: 'primario mini', onclick: () => abrirInicio(1) }, 'Entrar con Claude'),
        h('button', { clase: 'mini fantasma', onclick: () => refrescarEstadoAsistente() },
          'Ya he entrado: vuelve a mirar')));
  }
  return h('div', { clase: 'asistente-puerta' },
    h('div', { clase: 'caja-error' },
      'Tu cuenta de Claude tiene sesión pero ahora mismo no puede contestar.'),
    conSesion.map(c => h('div', { clase: 'fila' },
      h('b', {}, c.etiqueta || c.correo || 'la cuenta'),
      pastillaSalud(c.salud),
      h('span', { clase: 'meta' }, c.motivo || ''))),
    h('div', { clase: 'fila' },
      h('button', { clase: 'primario mini', onclick: () => probarAsistente() }, 'Volver a probar'),
      h('button', { clase: 'mini fantasma', onclick: () => abrirInicio(1) }, 'Entrar con otra cuenta')));
}

/* Una charla vacía: qué se le puede preguntar, y tres preguntas que se pulsan. */
function vacioDelAsistente() {
  const ejemplos = [
    '¿Qué me falta por configurar para hacer un vídeo?',
    '¿Por qué hay un paso en naranja y qué tengo que rehacer?',
    '¿Cuánto me va a costar generar las imágenes de este vídeo?',
  ];
  return h('div', { clase: 'asistente-vacio' },
    'Sé cómo funciona el Estudio y veo lo que está pasando en el tuyo: las '
    + 'claves, el vídeo abierto, los pasos parados y los errores. Pregúntame '
    + 'lo que sea, o empieza por una de estas:',
    ejemplos.map(texto => h('button', {
      clase: 'mini fantasma ejemplo',
      onclick: () => { $('#asistente-texto').value = texto; enviarAlAsistente(); },
    }, texto)));
}

function burbujaDeTurno(turno) {
  if (turno.quien === 'tu') {
    return h('div', { clase: 'turno tu' }, turno.texto);
  }
  if (turno.estado === 'pensando') {
    const segundos = Math.max(0, Math.round((Date.now() - (ASISTENTE.arranque || Date.now())) / 1000));
    return h('div', { clase: 'turno asistente pensando' },
      `pensando… ${ASISTENTE.arranque ? `${segundos} s` : ''}`.trim());
  }
  if (turno.estado === 'error' || turno.estado === 'cancelado') {
    return h('div', { clase: `turno asistente ${turno.estado}` },
      turno.estado === 'cancelado' ? 'parado' : cajaError(turno.texto));
  }
  const pie = [];
  if (turno.segundos) pie.push(`${turno.segundos} s`);
  if (turno.cuenta) pie.push(turno.cuenta);
  return h('div', { clase: 'turno asistente' },
    textoConFormato(turno.texto),
    pie.length ? h('div', { clase: 'pie-turno' }, pie.join(' · ')) : null);
}

/* Lo poco de Markdown que escribe un asistente —párrafos, listas, bloques de
   código, negritas y código en línea— pintado como nodos, sin innerHTML. */
function textoConFormato(texto) {
  const salida = h('div', { clase: 'md' });
  const lineas = String(texto || '').replace(/\r/g, '').split('\n');
  const esLista = l => /^\s*([-*•]|\d+[.)])\s+/.test(l);
  const esTitulo = l => /^#{1,6}\s/.test(l);
  let i = 0;
  while (i < lineas.length) {
    const linea = lineas[i];
    if (/^\s*\x60\x60\x60/.test(linea)) {
      const buf = [];
      i++;
      while (i < lineas.length && !/^\s*\x60\x60\x60/.test(lineas[i])) buf.push(lineas[i++]);
      i++;
      salida.appendChild(h('pre', {}, buf.join('\n')));
      continue;
    }
    if (!linea.trim()) { i++; continue; }
    if (esLista(linea)) {
      const lista = h(/^\s*\d/.test(linea) ? 'ol' : 'ul', {});
      while (i < lineas.length && esLista(lineas[i])) {
        lista.appendChild(h('li', {}, enLinea(lineas[i].replace(/^\s*([-*•]|\d+[.)])\s+/, ''))));
        i++;
      }
      salida.appendChild(lista);
      continue;
    }
    if (esTitulo(linea)) {
      salida.appendChild(h('div', { clase: 'titulo' }, enLinea(linea.replace(/^#+\s*/, ''))));
      i++;
      continue;
    }
    const parrafo = [];
    while (i < lineas.length && lineas[i].trim() && !esLista(lineas[i])
           && !esTitulo(lineas[i]) && !/^\s*\x60\x60\x60/.test(lineas[i])) {
      parrafo.push(lineas[i++]);
    }
    salida.appendChild(h('p', {}, enLinea(parrafo.join(' '))));
  }
  return salida;
}

function enLinea(texto) {
  const nodos = [];
  // \x60 es el acento grave, y va escrito asi y no a pelo a proposito: las
  // herramientas de herramientas/ trocean las plantillas por el acento y se
  // tragarian el resto del fichero como si fuera una cadena
  const trozos = /(\x60[^\x60]+\x60|\*\*[^*]+\*\*)/g;
  let ultimo = 0;
  let m;
  while ((m = trozos.exec(texto))) {
    if (m.index > ultimo) nodos.push(texto.slice(ultimo, m.index));
    const t = m[0];
    nodos.push(t.charCodeAt(0) === 96 ? h('code', {}, t.slice(1, -1)) : h('b', {}, t.slice(2, -2)));
    ultimo = m.index + t.length;
  }
  if (ultimo < texto.length) nodos.push(texto.slice(ultimo));
  return nodos;
}

/* ARRANCA AQUI, Y ESTA LINEA VA LA ULTIMA DEL FICHERO A PROPOSITO.
   `arrancar` lee el modo puesto, y el modo vive en `MODOS`, que es un
   const de mas abajo: llamar antes de esa linea revienta con «Cannot
   access 'MODOS' before initialization» y deja la pantalla en blanco.
   Las funciones se izan; los const no. */
arrancar();
