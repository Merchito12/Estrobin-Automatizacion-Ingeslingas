/* ==========================================================================
   Portal interno de archivos · INGESLINGAS S.A.S.
   Frontend estático sin dependencias. La configuración vive en config.js.
   Todo texto proveniente del servidor se inserta con textContent (nunca innerHTML).
   ========================================================================== */
(() => {
  'use strict';

  /* ---------- Configuración ------------------------------------------------ */
  const ALLOWED_EXT = ['.xls', '.xlsx', '.csv'];
  const HEALTH_TIMEOUT_MS = 75000;     // arranque en frío de Render
  const PROCESS_TIMEOUT_MS = 120000;
  const COLD_NOTICE_MS = 6000;
  const SLOW_BADGE_MS = 4000;

  const MSG = {
    notConfigured: 'El portal de procesamiento todavía no tiene configurado el servidor.',
    httpsRequired: 'La dirección del servidor en config.js debe usar HTTPS.',
    warmingUp: 'Estamos iniciando el servicio de procesamiento. Esto puede tardar unos segundos.',
    network: 'No fue posible comunicarse con el servidor de procesamiento. Intenta nuevamente.',
    timeout: 'El servidor tardó demasiado en responder. Intenta nuevamente.',
    unexpected: (status) => 'El servidor devolvió una respuesta inesperada' + (status ? ' (HTTP ' + status + ')' : '') + '. Intenta nuevamente.',
    expired: 'El archivo ya fue descargado o expiró. Procesa el archivo nuevamente para generar otro.',
    downloadFailed: 'No fue posible descargar el archivo. Intenta nuevamente.',
  };

  const cfg = window.APP_CONFIG || {};
  const MAX_MB = Number(cfg.MAX_UPLOAD_MB) > 0 ? Number(cfg.MAX_UPLOAD_MB) : 25;
  const MAX_BYTES = MAX_MB * 1024 * 1024;
  const API = normalizeApiUrl(cfg.API_URL);
  const configProblem = getConfigProblem(cfg.API_URL, API);

  function normalizeApiUrl(value) {
    if (typeof value !== 'string') return '';
    const v = value.trim().replace(/\/+$/, '');
    if (!/^https?:\/\/[^\s/]+/i.test(v) || /URL-DEL-BACKEND/i.test(v)) return '';
    return v;
  }

  function getConfigProblem(raw, normalized) {
    if (!normalized) return MSG.notConfigured;
    const local = /^http:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/i.test(normalized);
    if (location.protocol === 'https:' && normalized.startsWith('http://') && !local) return MSG.httpsRequired;
    return null;
  }

  /* ---------- Utilidades DOM ----------------------------------------------- */
  const $ = (id) => document.getElementById(id);
  const SVG_NS = 'http://www.w3.org/2000/svg';

  function h(tag, props, ...children) {
    const el = document.createElement(tag);
    if (props) {
      for (const [key, value] of Object.entries(props)) {
        if (value == null || value === false) continue;
        if (key === 'class') el.className = value;
        else if (key === 'text') el.textContent = value;
        else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
        else if (value === true) el.setAttribute(key, '');
        else el.setAttribute(key, String(value));
      }
    }
    for (const child of children.flat(Infinity)) {
      if (child == null || child === false) continue;
      el.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return el;
  }

  function icon(path) {
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    const p = document.createElementNS(SVG_NS, 'path');
    p.setAttribute('d', path);
    p.setAttribute('fill', 'none');
    p.setAttribute('stroke', 'currentColor');
    p.setAttribute('stroke-width', '2.4');
    p.setAttribute('stroke-linecap', 'round');
    p.setAttribute('stroke-linejoin', 'round');
    svg.appendChild(p);
    return svg;
  }
  const ICON_OK = 'M5 12.5l4.2 4.2L19 7';
  const ICON_ALERT = 'M12 5v9M12 18.5v.01';
  const ICON_DOWNLOAD = 'M12 4v11m0 0l-4-4m4 4l4-4M5 19h14';

  /* ---------- Formato ------------------------------------------------------ */
  function groupThousands(digits) {
    return digits.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  }

  function fmtInt(value) {
    const n = Number(value);
    return Number.isFinite(n) ? (n < 0 ? '-' : '') + groupThousands(String(Math.abs(Math.trunc(n)))) : '—';
  }

  /** Formato es-CO exacto a partir de texto decimal ("476641448.08" → "476.641.448,08"). */
  function fmtMoneyText(text) {
    const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(String(text == null ? '' : text).trim());
    if (!match) return '—';
    const decimals = (match[3] || '').padEnd(2, '0');
    return match[1] + groupThousands(match[2]) + ',' + decimals;
  }

  function fmtMoneyNumber(value) {
    const n = Number(value);
    return Number.isFinite(n) ? fmtMoneyText(n.toFixed(2)) : '—';
  }

  function fmtBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1).replace('.', ',') + ' KB';
    return (bytes / 1024 / 1024).toFixed(2).replace('.', ',') + ' MB';
  }

  function capitalize(text) {
    if (!text) return text;
    const lower = String(text).toLowerCase();
    return lower.charAt(0).toUpperCase() + lower.slice(1);
  }

  /* ---------- Referencias y estado ---------------------------------------- */
  const els = {
    form: $('upload-form'),
    dropzone: $('dropzone'),
    pick: $('pick-button'),
    input: $('file-input'),
    fileError: $('file-error'),
    chip: $('file-chip'),
    chipType: $('file-type'),
    chipName: $('file-name'),
    chipMeta: $('file-meta'),
    remove: $('remove-file'),
    portalError: $('portal-error'),
    submit: $('submit-button'),
    submitLabel: $('submit-label'),
    spinner: document.querySelector('#submit-button .spinner'),
    status: $('status-line'),
    result: $('result'),
    steps: $('steps'),
    badge: $('service-badge'),
    badgeText: $('service-badge-text'),
    configNotice: $('config-notice'),
  };

  const state = { file: null, busy: false, expiryTimer: null };

  /* ---------- Insignia de servicio ---------------------------------------- */
  function setBadge(kind, text) {
    els.badge.dataset.state = kind;
    els.badgeText.textContent = text;
  }

  async function checkHealth() {
    if (configProblem) {
      setBadge('error', 'Servidor sin configurar');
      return false;
    }
    setBadge('pending', 'Verificando servicio…');
    const slowTimer = setTimeout(() => setBadge('warn', 'Iniciando servicio…'), SLOW_BADGE_MS);
    try {
      for (let attempt = 0; attempt < 2; attempt += 1) {
        const controller = new AbortController();
        const killer = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
        try {
          const response = await fetch(API + '/api/health', { signal: controller.signal, cache: 'no-store' });
          if (response.ok) {
            const body = await response.json();
            if (body && body.status === 'ok') {
              setBadge('ok', 'Sistema disponible');
              return true;
            }
          }
        } catch (error) {
          /* se reintenta una vez */
        } finally {
          clearTimeout(killer);
        }
        if (attempt === 0) {
          setBadge('warn', 'Iniciando servicio…');
          await new Promise((resolve) => setTimeout(resolve, 4000));
        }
      }
      setBadge('error', 'Servicio no disponible');
      return false;
    } finally {
      clearTimeout(slowTimer);
    }
  }

  /* ---------- Pasos -------------------------------------------------------- */
  function setSteps(upload, validate, download) {
    const map = { upload, validate, download };
    els.steps.querySelectorAll('[data-step]').forEach((item) => {
      item.dataset.state = map[item.dataset.step] || 'idle';
    });
  }

  function stepsForIdle() {
    if (state.file) setSteps('done', 'active', 'idle');
    else setSteps('active', 'idle', 'idle');
  }

  /* ---------- Mensajes ----------------------------------------------------- */
  function showStatus(kind, text) {
    els.status.hidden = false;
    els.status.dataset.kind = kind;
    els.status.textContent = text;
  }

  function clearStatus() {
    els.status.hidden = true;
    els.status.textContent = '';
    delete els.status.dataset.kind;
  }

  function showFileError(text) {
    els.fileError.hidden = false;
    els.fileError.textContent = text;
  }

  function clearFileError() {
    els.fileError.hidden = true;
    els.fileError.textContent = '';
  }

  /* ---------- Selección de archivo ---------------------------------------- */
  function extensionOf(name) {
    const dot = name.lastIndexOf('.');
    return dot >= 0 ? name.slice(dot).toLowerCase() : '';
  }

  function validateFile(file) {
    const ext = extensionOf(file.name || '');
    if (ext === '.pdf') return 'No se admiten archivos PDF. Carga un archivo XLS, XLSX o CSV.';
    if (!ALLOWED_EXT.includes(ext)) return 'Formato no permitido. Carga un archivo XLS, XLSX o CSV.';
    if (file.size === 0) return 'El archivo está vacío.';
    if (file.size > MAX_BYTES) return 'El archivo supera el tamaño máximo permitido (' + MAX_MB + ' MB).';
    return null;
  }

  function updateSubmit() {
    els.submit.disabled = state.busy || !state.file || Boolean(configProblem);
  }

  function renderChip() {
    const file = state.file;
    els.chip.hidden = !file;
    els.dropzone.classList.toggle('has-file', Boolean(file));
    if (!file) return;
    els.chipType.textContent = extensionOf(file.name).replace('.', '').toUpperCase();
    els.chipName.textContent = file.name;
    els.chipMeta.textContent = fmtBytes(file.size);
  }

  function acceptFiles(fileList) {
    if (state.busy) return;
    clearFileError();
    if (!fileList || fileList.length === 0) return;
    if (fileList.length > 1) {
      showFileError('Carga un solo archivo a la vez.');
      return;
    }
    const file = fileList[0];
    const problem = validateFile(file);
    if (problem) {
      showFileError(problem);
      return;
    }
    state.file = file;
    clearResult();
    clearStatus();
    renderChip();
    stepsForIdle();
    updateSubmit();
  }

  function removeFile() {
    if (state.busy) return;
    state.file = null;
    els.input.value = '';
    clearFileError();
    clearResult();
    clearStatus();
    renderChip();
    stepsForIdle();
    updateSubmit();
    els.pick.focus();
  }

  function resetAll() {
    state.file = null;
    els.input.value = '';
    els.portalError.value = '';
    clearFileError();
    clearResult();
    clearStatus();
    renderChip();
    stepsForIdle();
    updateSubmit();
    els.pick.focus();
    els.dropzone.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'center' });
  }

  function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function setBusy(busy) {
    state.busy = busy;
    els.spinner.hidden = !busy;
    els.submitLabel.textContent = busy ? 'Analizando y corrigiendo…' : 'Analizar y corregir archivo';
    els.form.setAttribute('aria-busy', String(busy));
    els.remove.disabled = busy;
    els.pick.disabled = busy;
    els.portalError.readOnly = busy;
    updateSubmit();
  }

  function hasFiles(event) {
    const types = event.dataTransfer && event.dataTransfer.types;
    return Boolean(types) && Array.prototype.indexOf.call(types, 'Files') !== -1;
  }

  /* ---------- Resultado ---------------------------------------------------- */
  function clearResult() {
    clearTimeout(state.expiryTimer);
    state.expiryTimer = null;
    els.result.replaceChildren();
    els.result.removeAttribute('aria-label');
    els.result.removeAttribute('role');
  }

  function showResult(node) {
    els.result.replaceChildren(node);
    els.result.setAttribute('role', 'region');
    els.result.setAttribute('aria-label', 'Resultado del procesamiento');
    els.result.focus({ preventScroll: true });
    els.result.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
  }

  function metric(label, value, sub) {
    return h('div', { class: 'metric' },
      h('span', { class: 'metric__label', text: label }),
      h('span', { class: 'metric__value', text: value }),
      sub ? h('span', { class: 'metric__sub', text: sub }) : null);
  }

  function block(title, ...children) {
    return h('section', { class: 'block' }, h('h3', { class: 'block__title', text: title }), ...children);
  }

  function issueText(issue) {
    const row = issue.row != null ? 'Fila ' + issue.row + ': ' : '';
    return row + issue.message;
  }

  function issueList(issues, kind, total, limit) {
    const shown = issues.slice(0, limit);
    const items = shown.map((issue) => h('li', { class: 'list__item list__item--' + kind },
      issueText(issue),
      issue.column ? [' ', h('span', { class: 'pill', text: issue.column })] : null));
    const hidden = Math.max(total - shown.length, 0);
    return [
      h('ul', { class: 'list' }, items),
      hidden > 0 ? h('p', { class: 'list__more', text: 'Se muestran ' + shown.length + ' de ' + total + '.' }) : null,
    ];
  }

  function hintsBlock(hints, title) {
    if (!hints || hints.length === 0) return null;
    return block(title, h('ul', { class: 'list' }, hints.map((hint) =>
      h('li', { class: 'list__item list__item--hint' },
        h('strong', { text: hint.title }), hint.detail))));
  }

  const METHOD_LABEL = {
    alias: 'Por nombre', exacto: 'Por nombre', similitud: 'Por similitud',
    contenido: 'Por contenido', constante: 'Valor fijo', regla: 'Regla',
  };

  function mappingTable(rows) {
    const body = rows.map((row) => {
      let origin;
      if (row.method === 'constante') origin = 'Valor fijo «' + row.value + '»';
      else if (row.key === 'term') origin = 'Valor fijo: ' + row.value + ' días';
      else if (row.method === 'regla') origin = 'Regla: ' + row.value;
      else origin = row.source + (row.sourceColumn ? ' (col. ' + row.sourceColumn + ')' : '');
      const percent = Math.round(Number(row.confidence) * 100);
      return h('tr', null,
        h('td', { text: origin }),
        h('td', { text: row.target }),
        h('td', { class: 'nowrap' },
          (Number.isFinite(percent) ? percent + '% ' : ''),
          h('span', { class: 'pill', text: METHOD_LABEL[row.method] || row.method })));
    });
    return h('div', { class: 'table-wrap' },
      h('table', { class: 'table' },
        h('thead', null, h('tr', null,
          h('th', { scope: 'col', text: 'Origen' }),
          h('th', { scope: 'col', text: 'Destino' }),
          h('th', { scope: 'col', text: 'Confianza' }))),
        h('tbody', null, body)));
  }

  function mappingBlock(rows, open) {
    if (!rows || rows.length === 0) return null;
    return h('details', { class: 'details', open: open },
      h('summary', { class: 'details__summary', text: 'Columnas identificadas en el archivo' }),
      h('div', { class: 'details__body' }, mappingTable(rows)));
  }

  function previewBlock(rows, total) {
    if (!rows || rows.length === 0) return null;
    const head = ['Factura', 'Cliente', 'NIT', 'Emisión', 'Vencimiento', 'Plazo', 'Valor'];
    const body = rows.map((row) => h('tr', null,
      h('td', { class: 'nowrap', text: row.factura }),
      h('td', { text: row.cliente }),
      h('td', { class: 'nowrap mono', text: row.nit }),
      h('td', { class: 'nowrap', text: row.emision }),
      h('td', { class: 'nowrap', text: row.vencimiento }),
      h('td', { class: 'num', text: row.plazo }),
      h('td', { class: 'num', text: fmtMoneyNumber(row.valor) })));
    return block('Vista previa (' + rows.length + ' de ' + fmtInt(total) + ' registros)',
      h('div', { class: 'table-wrap' },
        h('table', { class: 'table' },
          h('thead', null, h('tr', null, head.map((label, i) =>
            h('th', { scope: 'col', class: i >= 5 ? 'num' : null, text: label })))),
          h('tbody', null, body))));
  }

  function resultHead(kind, stateLabel, title, text) {
    return h('div', { class: 'result__head' },
      h('span', { class: 'result__icon' }, icon(kind === 'ok' ? ICON_OK : ICON_ALERT)),
      h('div', null,
        h('p', { class: 'result__state', text: stateLabel }),
        h('h3', { class: 'result__title', text: title }),
        h('p', { class: 'result__text', text: text })));
  }

  function renderSuccess(data) {
    const summary = data.summary || {};
    const stats = data.stats || {};
    const warnings = data.warnings || [];

    const metrics = h('div', { class: 'metrics' },
      metric('Registros encontrados', fmtInt(data.recordsFound),
        stats.skippedTotalRows ? (stats.skippedTotalRows === 1 ? '1 fila de totales omitida' : fmtInt(stats.skippedTotalRows) + ' filas de totales omitidas') : null),
      metric('Registros válidos', fmtInt(data.validRecords)),
      metric('Valor total', '$ ' + fmtMoneyText(summary.totalValueText != null ? summary.totalValueText : summary.totalValue), 'COP'),
      metric('Periodo', capitalize(summary.period) || '—',
        summary.minDate && summary.maxDate ? summary.minDate + ' – ' + summary.maxDate : null));

    const panel = h('div', { class: 'card result__panel' },
      resultHead('ok', 'ARCHIVO VALIDADO', 'El archivo final está listo',
        'Las validaciones obligatorias fueron completadas correctamente.'),
      metrics,
      hintsBlock(data.portalErrorHints, 'Correcciones aplicadas'),
      warnings.length > 0
        ? block('Advertencias (' + (data.warningCount || warnings.length) + ')',
          ...issueList(warnings, 'warn', data.warningCount || warnings.length, 10))
        : null,
      previewBlock(data.preview, data.recordsFound),
      mappingBlock(data.mapping, false));

    const root = h('div', { class: 'result result--ok' }, panel, downloadPanel(data),
      h('div', { class: 'result__actions' },
        h('button', { class: 'btn btn--ghost', type: 'button', onclick: resetAll, text: 'Procesar otro archivo' })));

    setSteps('done', 'done', 'active');
    showResult(root);
  }

  function renderFailure(data, httpStatus) {
    const errors = data.errors || [];
    const warnings = data.warnings || [];
    const detected = Array.isArray(data.detectedHeaders) ? data.detectedHeaders : [];

    const metrics = h('div', { class: 'metrics' },
      metric('Registros encontrados', fmtInt(data.recordsFound)),
      metric('Registros válidos', fmtInt(data.validRecords)),
      metric('Errores', fmtInt(data.errorCount != null ? data.errorCount : errors.length)),
      metric('Advertencias', fmtInt(data.warningCount != null ? data.warningCount : warnings.length)));

    const serverSide = httpStatus >= 500;
    const panel = h('div', { class: 'card result__panel' },
      resultHead('error', 'REQUIERE REVISIÓN',
        serverSide ? 'No fue posible generar el archivo' : 'No fue seguro generar el archivo',
        serverSide
          ? 'Ocurrió un problema interno. Intenta nuevamente; si se repite, informa al responsable del portal.'
          : 'Corrige los puntos indicados en el archivo de origen y vuelve a cargarlo.'),
      metrics,
      errors.length > 0
        ? block('Errores encontrados', ...issueList(errors, 'error', data.errorCount != null ? data.errorCount : errors.length, 100))
        : null,
      warnings.length > 0
        ? block('Advertencias', ...issueList(warnings, 'warn', data.warningCount != null ? data.warningCount : warnings.length, 10))
        : null,
      hintsBlock(data.portalErrorHints, 'Mensaje de la plataforma interpretado'),
      detected.length > 0
        ? block('Encabezados detectados en el archivo',
          h('ul', { class: 'list' }, h('li', { class: 'list__item' }, detected.join(' · '))))
        : null,
      mappingBlock(data.mapping, true));

    const root = h('div', { class: 'result result--error' }, panel,
      h('div', { class: 'result__actions' },
        h('button', { class: 'btn btn--secondary', type: 'button', onclick: resetAll, text: 'Cargar otro archivo' })));

    setSteps('done', 'error', 'idle');
    showResult(root);
  }

  /* ---------- Descarga ----------------------------------------------------- */
  function filenameFromDisposition(header) {
    if (!header) return null;
    let match = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header);
    if (match) {
      try { return decodeURIComponent(match[1].trim()); } catch (error) { /* continúa */ }
    }
    match = /filename\s*=\s*"([^"]+)"/i.exec(header) || /filename\s*=\s*([^;]+)/i.exec(header);
    return match ? match[1].trim() : null;
  }

  function safeFilename(name, fallback) {
    const cleaned = String(name || '').replace(/[\\/:*?"<>|\u0000-\u001f]+/g, '_').trim();
    return cleaned || fallback;
  }

  function downloadPanel(data) {
    const minutes = Number(data.expiresInMinutes);
    const note = h('p', { class: 'download__note', text:
      'El archivo se elimina automáticamente del servidor después de finalizar la descarga.' +
      (minutes > 0 ? ' Si no se descarga, se elimina a los ' + minutes + ' minutos.' : '') });
    const problem = h('p', { class: 'download__error', role: 'alert', hidden: true });
    const label = h('span', { text: 'Descargar Excel corregido' });
    const button = h('button', { class: 'btn btn--yellow', type: 'button' }, icon(ICON_DOWNLOAD), label);

    const finish = (text, ok) => {
      button.disabled = true;
      label.textContent = ok ? 'Archivo descargado' : 'Archivo no disponible';
      if (ok) {
        note.textContent = 'Descarga completada. El servidor elimina el archivo al finalizar la descarga.';
        problem.hidden = true;
        setSteps('done', 'done', 'done');
      } else {
        problem.hidden = false;
        problem.textContent = text;
      }
    };

    button.addEventListener('click', async () => {
      if (button.disabled) return;
      button.disabled = true;
      label.textContent = 'Preparando descarga…';
      problem.hidden = true;
      try {
        const response = await fetch(API + '/api/download/' + encodeURIComponent(data.jobId), { cache: 'no-store' });
        if (response.status === 404) { finish(MSG.expired, false); return; }
        if (!response.ok) throw new Error('http ' + response.status);
        const blob = await response.blob();
        const name = safeFilename(filenameFromDisposition(response.headers.get('Content-Disposition')), data.outputFilename || 'PlantillaDeclaracionVentas.xlsx');
        const url = URL.createObjectURL(blob);
        const anchor = h('a', { href: url, download: name });
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        setTimeout(() => URL.revokeObjectURL(url), 15000);
        clearTimeout(state.expiryTimer);
        finish('', true);
      } catch (error) {
        button.disabled = false;
        label.textContent = 'Descargar Excel corregido';
        problem.hidden = false;
        problem.textContent = MSG.downloadFailed;
      }
    });

    if (minutes > 0) {
      state.expiryTimer = setTimeout(() => {
        if (!button.disabled) finish(MSG.expired, false);
      }, Math.max(minutes * 60000 - 5000, 1000));
    }

    return h('div', { class: 'download' },
      h('div', { class: 'download__info' },
        h('p', { class: 'download__label', text: 'Archivo final' }),
        h('p', { class: 'download__name', text: data.outputFilename || 'PlantillaDeclaracionVentas.xlsx' }),
        note, problem),
      button);
  }

  /* ---------- Envío -------------------------------------------------------- */
  async function readJson(response) {
    try { return await response.json(); } catch (error) { return null; }
  }

  async function onSubmit(event) {
    event.preventDefault();
    if (state.busy || !state.file) return;
    if (configProblem) {
      showConfigNotice();
      return;
    }

    clearResult();
    clearStatus();
    setBusy(true);
    setSteps('done', 'active', 'idle');

    const coldTimer = setTimeout(() => showStatus('info', MSG.warmingUp), COLD_NOTICE_MS);
    const controller = new AbortController();
    const killer = setTimeout(() => controller.abort(), PROCESS_TIMEOUT_MS);

    try {
      const form = new FormData();
      form.append('file', state.file, state.file.name);
      form.append('portal_error', els.portalError.value.trim());

      const response = await fetch(API + '/api/process', { method: 'POST', body: form, signal: controller.signal });
      const data = await readJson(response);
      clearStatus();

      if (data && typeof data.ok === 'boolean') {
        setBadge('ok', 'Sistema disponible');
        if (data.ok && data.jobId) renderSuccess(data);
        else if (!data.ok) renderFailure(data, response.status);
        else { showStatus('error', MSG.unexpected(response.status)); stepsForIdle(); }
      } else if ([502, 503, 504].includes(response.status)) {
        setBadge('warn', 'Iniciando servicio…');
        showStatus('error', MSG.warmingUp + ' Intenta nuevamente en unos segundos.');
        stepsForIdle();
      } else {
        showStatus('error', MSG.unexpected(response.status));
        stepsForIdle();
      }
    } catch (error) {
      clearStatus();
      const aborted = error && error.name === 'AbortError';
      showStatus('error', aborted ? MSG.timeout : MSG.network);
      setBadge('error', 'Servicio no disponible');
      stepsForIdle();
    } finally {
      clearTimeout(coldTimer);
      clearTimeout(killer);
      setBusy(false);
    }
  }

  function showConfigNotice() {
    els.configNotice.hidden = false;
    els.configNotice.textContent = configProblem;
  }

  /* ---------- Imágenes faltantes ------------------------------------------ */
  function handleMissingImage(img) {
    if (img.dataset.handled) return;
    img.dataset.handled = '1';
    const fallback = img.dataset.fallback;
    if (fallback) {
      img.replaceWith(h('span', { class: 'img-missing', text: fallback }));
    } else {
      const figure = img.closest('figure');
      const container = img.closest('.hero__inner');
      if (figure) figure.hidden = true;
      if (container) container.classList.add('no-mascot');
    }
  }

  function watchImages() {
    document.querySelectorAll('img[data-fallback]').forEach((img) => {
      if (img.complete && img.naturalWidth === 0) handleMissingImage(img);
      else img.addEventListener('error', () => handleMissingImage(img), { once: true });
    });
  }

  /* ---------- Inicio ------------------------------------------------------- */
  function init() {
    const year = $('year');
    if (year) year.textContent = String(new Date().getFullYear());
    watchImages();

    if (configProblem) showConfigNotice();

    // Selección
    els.pick.addEventListener('click', (event) => {
      event.stopPropagation();
      els.input.value = '';
      els.input.click();
    });
    els.input.addEventListener('change', () => acceptFiles(els.input.files));
    els.dropzone.addEventListener('click', (event) => {
      if (event.target.closest('button, input')) return;
      if (state.busy) return;
      els.input.value = '';
      els.input.click();
    });
    els.remove.addEventListener('click', removeFile);

    // Arrastrar y soltar
    let depth = 0;
    els.dropzone.addEventListener('dragenter', (event) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth += 1;
      els.dropzone.classList.add('is-dragover');
    });
    els.dropzone.addEventListener('dragover', (event) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = state.busy ? 'none' : 'copy';
    });
    els.dropzone.addEventListener('dragleave', () => {
      depth = Math.max(depth - 1, 0);
      if (depth === 0) els.dropzone.classList.remove('is-dragover');
    });
    els.dropzone.addEventListener('drop', (event) => {
      event.preventDefault();
      depth = 0;
      els.dropzone.classList.remove('is-dragover');
      acceptFiles(event.dataTransfer && event.dataTransfer.files);
    });
    ['dragover', 'drop'].forEach((type) => {
      window.addEventListener(type, (event) => { if (hasFiles(event)) event.preventDefault(); });
    });

    els.form.addEventListener('submit', onSubmit);

    renderChip();
    stepsForIdle();
    updateSubmit();
    checkHealth();
  }

  init();
})();
