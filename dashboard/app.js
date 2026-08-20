/**
 * app.js — Dashboard real-time per PHD2 Adaptive Agent
 * Connessione WebSocket + aggiornamento UI + Chart.js
 */

// ===== CONFIG =====
const MAX_CHART_POINTS = 120;  // ultimi N frame nel grafico
const WS_URL = `ws://${location.host}/ws`;
const API_BASE = `${location.protocol}//${location.host}`;

// ===== STATO =====
let wsConn = null;
let frameCount = 0;
let actionCount = 0;
let isDryRun = true;
let exposureMarkerMeta = [];  // parallel to chart labels; null or {dir, old_ms, new_ms, state}
let ninaMarkerMeta = [];      // §46: parallel; null o {penalty, conf_phd2, conf_final, state}

// ===== CHART =====
const chartCtx = document.getElementById('guide-chart').getContext('2d');
const guideChart = new Chart(chartCtx, {
  type: 'line',
  data: {
    labels: [],
    datasets: [
      {
        label: 'RMS RA',
        data: [],
        borderColor: '#5b9cf6',
        backgroundColor: 'rgba(91,156,246,0.08)',
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.35,
        fill: true,
      },
      {
        label: 'RMS Dec',
        data: [],
        borderColor: '#34d399',
        backgroundColor: 'rgba(52,211,153,0.06)',
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.35,
        fill: true,
      },
      {
        label: 'RMS Totale',
        data: [],
        borderColor: '#a78bfa',
        backgroundColor: 'rgba(167,139,250,0.05)',
        borderWidth: 2.5,
        pointRadius: 0,
        pointHoverRadius: 5,
        tension: 0.35,
        fill: false,
        borderDash: [],
      },
      {
        label: 'Exp. Change',
        data: [],
        borderColor: 'transparent',
        backgroundColor: (ctx) => {
          const meta = exposureMarkerMeta[ctx.dataIndex];
          if (!meta) return 'transparent';
          return meta.dir === 'UP' ? 'rgba(255,210,107,0.9)' : 'rgba(0,214,143,0.9)';
        },
        borderWidth: 0,
        showLine: false,
        pointRadius: (ctx) => (exposureMarkerMeta[ctx.dataIndex] ? 8 : 0),
        pointHoverRadius: (ctx) => (exposureMarkerMeta[ctx.dataIndex] ? 10 : 0),
        pointStyle: 'triangle',
      },
      {
        // §46 — marcatore "NINA ha modulato la confidence del SEEING"
        label: 'NINA mod',
        data: [],
        borderColor: 'transparent',
        backgroundColor: 'rgba(167,139,250,0.95)',
        borderWidth: 0,
        showLine: false,
        pointRadius: (ctx) => (ninaMarkerMeta[ctx.dataIndex] ? 7 : 0),
        pointHoverRadius: (ctx) => (ninaMarkerMeta[ctx.dataIndex] ? 9 : 0),
        pointStyle: 'rectRot',
      },
    ],
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 0 },
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        display: true,
        labels: {
          color: '#8a9cc0',
          font: { family: 'Inter', size: 12 },
          usePointStyle: true,
          pointStyleWidth: 10,
          boxHeight: 4,
        },
      },
      tooltip: {
        backgroundColor: '#0d1424',
        borderColor: 'rgba(100,160,255,0.2)',
        borderWidth: 1,
        titleColor: '#e8f0ff',
        bodyColor: '#8a9cc0',
        filter: (item) => {
          if (item.datasetIndex === 3 && !exposureMarkerMeta[item.dataIndex]) return false;
          if (item.datasetIndex === 4 && !ninaMarkerMeta[item.dataIndex]) return false;
          return true;
        },
        callbacks: {
          label: ctx => {
            if (ctx.datasetIndex === 3) {
              const meta = exposureMarkerMeta[ctx.dataIndex];
              if (meta) return ` Exp ${meta.dir}: ${meta.old_ms}ms → ${meta.new_ms}ms`;
              return null;
            }
            if (ctx.datasetIndex === 4) {
              const meta = ninaMarkerMeta[ctx.dataIndex];
              if (meta) return ` NINA: confidence ${meta.conf_phd2}→${meta.conf_final} (trasparenza ${meta.state || ''})`;
              return null;
            }
            return ` ${ctx.dataset.label}: ${ctx.parsed.y.toFixed(3)}″`;
          },
        },
      },
    },
    scales: {
      x: {
        ticks: { display: false },
        grid: { color: 'rgba(100,160,255,0.05)' },
        border: { display: false },
      },
      y: {
        min: 0,
        suggestedMax: 1.2,
        ticks: {
          color: '#4d5f7a',
          font: { family: 'JetBrains Mono', size: 11 },
          callback: v => `${v.toFixed(2)}″`,
        },
        grid: { color: 'rgba(100,160,255,0.07)' },
        border: { display: false },
      },
    },
  },
});

// Soglie orizzontali (linee reference)
const _rmsHighPlugin = {
  id: 'threshLines',
  afterDraw(chart) {
    if (!chart.chartArea || !chart.scales || !chart.scales.y) return;
    const { ctx, chartArea: { left, right }, scales: { y } } = chart;
    const drawLine = (val, color, dash) => {
      const yPx = y.getPixelForValue(val);
      if (yPx === undefined || isNaN(yPx)) return;
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.setLineDash(dash);
      ctx.beginPath();
      ctx.moveTo(left, yPx);
      ctx.lineTo(right, yPx);
      ctx.stroke();
      ctx.restore();
    };
    drawLine(0.80, 'rgba(255,154,60,0.5)', [5, 4]);   // soglia alta
    drawLine(0.35, 'rgba(0,214,143,0.4)', [5, 4]);    // soglia bassa
  },
};
Chart.register(_rmsHighPlugin);


// ===== WEBSOCKET =====
function connectWS() {
  updateConnStatus('reconnecting', 'Connessione…');

  wsConn = new WebSocket(WS_URL);

  wsConn.onopen = () => {
    updateConnStatus('connected', 'Connesso');
    // Carica stato iniziale via REST
    fetchStatus();
  };

  wsConn.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      handleMessage(msg);
    } catch (e) {
      console.warn('WS parse error:', e);
    }
  };

  wsConn.onclose = () => {
    updateConnStatus('disconnected', 'Disconnesso');
    setTimeout(connectWS, 3000);
  };

  wsConn.onerror = () => {
    wsConn.close();
  };
}

function handleMessage(msg) {
  if (msg.type === 'guide_step') {
    updateGuideStep(msg);
  } else if (msg.type === 'status') {
    applyFullStatus(msg);
  } else if (msg.type === 'star_lost') {
    setCondition('STAR_LOST', 'mirinoLost', 'Stella persa');
  } else if (msg.type === 'start_guiding') {
    setCondition('NOMINAL', 'mirino', 'Guida avviata');
  } else if (msg.type === 'guiding_stopped') {
    setCondition('UNKNOWN', '⏸', 'Guida ferma');
  }
  // ping ignorato
}


// ===== REST STATUS =====
async function fetchStatus() {
  try {
    const r = await fetch(`${API_BASE}/status`);
    const data = await r.json();
    applyFullStatus(data);
  } catch (e) { /* nessuna conn */ }
}

function applyFullStatus(data) {
  const ctrl = data.controller || {};
  const an = data.analyzer || {};

  // §63 — ciclo del motore (raccolta dati / valuta senza intervenire / intervento)
  updateEngineCycle(ctrl.engine || {});

  // Aggiorna controller UI
  if (ctrl.guiding_state) {
    updateCtrlState(ctrl.guiding_state);
  }
  if (ctrl.ra) {
    el('ra-aggr').textContent = ctrl.ra.current_aggr?.toFixed(1) ?? '—';
    el('ra-mm').textContent = ctrl.ra.current_minmove?.toFixed(3) ?? '—';
    el('ra-param-name').textContent = ctrl.ra.aggr_param || '—';
  }
  if (ctrl.dec) {
    el('dec-aggr').textContent = ctrl.dec.current_aggr?.toFixed(1) ?? '—';
    el('dec-mm').textContent = ctrl.dec.current_minmove?.toFixed(3) ?? '—';
    el('dec-param-name').textContent = ctrl.dec.aggr_param || '—';
  }
  isDryRun = ctrl.dry_run ?? true;
  // §73 — l'interruttore nell'header non esiste più (sostituito dallo stato del
  // Safety Monitor): la MODALITÀ resta comunque visibile nel badge qui sotto.
  el('mode-badge').textContent = isDryRun ? 'MODALITÀ TEST' : 'LIVE CONTROL';
  el('mode-badge').classList.toggle('live', !isDryRun);
  

  // Aggiorna analyzer UI se disponibile
  if (an.rms_ra !== undefined) {
    updateRmsDisplay(an.rms_ra, an.rms_dec, an.rms_total);
    el('snr-val').textContent = an.snr_avg?.toFixed(1) ?? '—';
    el('hfd-val').textContent = an.hfd_avg?.toFixed(2) ?? '—';
    el('spike-val').textContent = an.spike_score !== undefined
      ? (an.spike_score * 100).toFixed(0) + '%' : '—';
    if (an.condition) {
      setConditionFromName(an.condition, an.condition_description || '');
    }
  }

  // Esposizione dinamica + escalation gate
  if (ctrl.exposure || ctrl.escalation_gate) {
    updateExposureEscalation(ctrl);
  }

  // Auto-calibrazione (pixel scale + soglie RMS adattive)
  if (ctrl.auto_calibration) {
    updateAutoCalibration(ctrl.auto_calibration);
  }

  // §31 — Seeing Diagnostic Engine
  if (ctrl.diagnostic_engine) {
    updateDiagnosticEngine(ctrl.diagnostic_engine);
  }

  // §45 — Transparency Index (NINA, Layer-2)
  updateTransparency(data.nina);
  updateRecoveryHint(data.recovery_hint);
  syncOpsRow();            // §96 — la riga operativa esiste solo se ha contenuto
  updateLevel1(data);      // §81 — include lo slot SESSIONE
  updateLevel2(data);      // §82 — solo in deviazione
  updateSkyStory(data);
  updateDynamicPanels(data);

  // §51 — Adaptive MinMove (cap adattivo)
  updateMinMoveCap(ctrl.minmove_cap);

  // Actions history
  if (ctrl.last_actions?.length) {
    el('action-log').innerHTML = ''; // prevent duplication
    ctrl.last_actions.forEach(a => addActionLog(a));
  }
}


// ===== AGGIORNAMENTO UI =====
function updateGuideStep(msg) {
  frameCount++;
  el('frame-count').textContent = `${frameCount} frame`;

  updateRmsDisplay(msg.rms_ra, msg.rms_dec, msg.rms_total);

  // Grafico — cerca azione esposizione per marker
  let expMarker = null;
  if (msg.actions?.length) {
    const expAction = msg.actions.find(a => a.axis === 'exposure');
    if (expAction) {
      expMarker = {
        dir: expAction.new_value > expAction.old_value ? 'UP' : 'DOWN',
        old_ms: Math.round(expAction.old_value),
        new_ms: Math.round(expAction.new_value),
        state: msg.condition || '',
      };
    }
  }

  // §46 — marcatore quando NINA ha modulato (penalizzato) la confidence del SEEING
  let ninaMarker = null;
  if (msg.nina_mod && msg.nina_mod.penalty > 0) {
    ninaMarker = {
      penalty: msg.nina_mod.penalty,
      conf_phd2: msg.nina_mod.conf_phd2,
      conf_final: msg.nina_mod.conf_final,
      state: msg.nina_mod.state,
    };
  }

  const ts = new Date(msg.ts * 1000).toLocaleTimeString('it-IT', { hour12: false });
  addChartPoint(ts, msg.rms_ra, msg.rms_dec, msg.rms_total, expMarker, ninaMarker);

  // Condizione
  if (msg.condition) {
    setConditionFromName(msg.condition, msg.condition_desc || '');
  }

  // Azioni controller
  if (msg.actions?.length) {
    msg.actions.forEach(a => addActionLog(a));
  }
}

function updateRmsDisplay(ra, dec, tot) {
  // Valori
  setGauge('rms-ra-val', ra, 'bar-ra');
  setGauge('rms-dec-val', dec, 'bar-dec');
  setGauge('rms-total-val', tot, 'bar-total');
}

function setGauge(valId, rms, barId) {
  const valEl = el(valId);
  const barEl = el(barId);
  if (rms === undefined || rms === null) return;

  valEl.textContent = rms.toFixed(3);

  // Classificazione colore
  let cls = 'good';
  let barColor = 'var(--green)';
  if (rms > 0.80) { cls = 'crit'; barColor = 'var(--red)'; }
  else if (rms > 0.60) { cls = 'bad'; barColor = 'var(--orange)'; }
  else if (rms > 0.35) { cls = 'warn'; barColor = 'var(--yellow)'; }

  valEl.className = `gauge-value ${cls}`;

  // Barra: mappa 0–1.5 arcsec in 0–100%
  const pct = Math.min(100, (rms / 1.5) * 100);
  barEl.style.width = pct + '%';
  barEl.style.background = barColor;
}

function addChartPoint(label, ra, dec, tot, expMarker = null, ninaMarker = null) {
  const d = guideChart.data;
  d.labels.push(label);
  d.datasets[0].data.push(ra);
  d.datasets[1].data.push(dec);
  d.datasets[2].data.push(tot);
  // 4th dataset: small y-value at marker points (renders as triangle dot)
  d.datasets[3].data.push(expMarker ? 0.06 : null);
  exposureMarkerMeta.push(expMarker);
  // 5th dataset (§46): marcatore NINA-modulazione, leggermente più in basso
  d.datasets[4].data.push(ninaMarker ? 0.03 : null);
  ninaMarkerMeta.push(ninaMarker);

  if (d.labels.length > MAX_CHART_POINTS) {
    d.labels.shift();
    d.datasets.forEach(ds => ds.data.shift());
    exposureMarkerMeta.shift();
    ninaMarkerMeta.shift();
  }
  guideChart.update('none');
}

// Condizione seeing
const CONDITION_MAP = {
  NOMINAL:         { icon: 'mirino',     color: '#00d68f', label: 'Nominale' },
  DEGRADED_SEEING: { icon: 'diagSeeing', color: '#ff9a3c', label: 'Seeing Degradato' },
  OSCILLATING:     { icon: 'diagOver'  , color: '#ffd66b', label: 'Oscillazione' },
  LOW_SNR:         { icon: 'ondaGiu',    color: '#8a9cc0', label: 'SNR Basso' },
  STAR_LOST:       { icon: 'mirinoLost', color: '#ff5555', label: 'Stella Persa' },
  UNKNOWN:         { icon: 'mirinoOff',  color: '#4d5f7a', label: 'In attesa…' },
};

function setCondition(key, iconOverride, labelOverride) {
  const cfg = CONDITION_MAP[key] || CONDITION_MAP.UNKNOWN;
  setGlyph('condition-icon', iconOverride || cfg.icon);
  el('condition-name').textContent = labelOverride || cfg.label;
  el('condition-name').style.color = cfg.color;
}

function setConditionFromName(condName, desc) {
  const cfg = CONDITION_MAP[condName] || CONDITION_MAP.UNKNOWN;
  setGlyph('condition-icon', cfg.icon);
  el('condition-name').textContent = cfg.label;
  el('condition-name').style.color = cfg.color;
  el('condition-desc').textContent = desc;
}

function updateCtrlState(state) {
  const badge = el('ctrl-state-badge');
  badge.className = `ctrl-state-badge ${state.toLowerCase()}`;
  el('ctrl-state-label').textContent = state.replace('_', ' ');
}

function updateExposureEscalation(ctrl) {
  const exp = ctrl.exposure;
  const gate = ctrl.escalation_gate;

  if (exp) {
    // State badge
    const stateName = exp.state || 'NOMINAL';
    el('exp-state-label').textContent = stateName.replace(/_/g, ' ');
    const badgeEl = el('exp-state-badge');
    badgeEl.className = 'exposure-state-badge';
    if (stateName === 'NOMINAL') badgeEl.classList.add('nominal');
    else if (stateName === 'BOOSTED_FOR_SNR') badgeEl.classList.add('boosted-snr');
    else if (stateName === 'BOOSTED_FOR_SEEING') badgeEl.classList.add('boosted-seeing');

    // Values
    const cur = exp.current_ms;
    const base = exp.base_ms;
    el('exp-current-ms').textContent = cur != null ? `${cur} ms` : '—';
    el('exp-base-ms').textContent = base != null ? `${base} ms` : '—';

    // §95 — la Base e' un riferimento dichiarato o e' stata adottata da PHD2?
    const baseEl = el('exp-base-ms');
    if (baseEl) {
      baseEl.title = exp.target_ms
        ? `Riferimento dichiarato in configurazione: ${exp.target_ms} ms`
        : 'Nessun riferimento dichiarato: base adottata da PHD2 all\'avvio';
    }

    // §95 — cosa espone PHD2 davvero. Se diverge dal valore interno e' un dato
    // diagnostico, non un dettaglio: la notte 17-18/8 l'Agente ragionava su una
    // base che nessuno aveva scelto e dalla dashboard non si poteva vedere.
    const phd2El = el('exp-phd2-ms');
    if (phd2El) {
      const phd2 = exp.phd2_ms;
      const diverge = phd2 != null && cur != null && phd2 !== cur;
      phd2El.textContent = phd2 != null ? `${phd2} ms` : '—';
      phd2El.classList.toggle('divergent', diverge);
      phd2El.title = diverge
        ? `Disallineamento: l'Agente crede ${cur} ms, PHD2 espone ${phd2} ms`
        : "L'esposizione che la camera sta usando davvero, letta da PHD2.";
    }
    el('exp-steps').textContent = exp.steps_above_base != null ? exp.steps_above_base : '—';

    // Cooldown bar
    const residuo = exp.cooldown_residuo_s ?? 0;
    const total = exp.cooldown_total_s ?? 1;
    const pct = total > 0 ? Math.min(100, (residuo / total) * 100) : 0;
    const barEl = el('exp-cooldown-bar');
    barEl.style.width = pct + '%';
    barEl.classList.toggle('hot', pct > 50);
    el('exp-cooldown-text').textContent = pct > 0 ? `${residuo.toFixed(0)}s / ${total}s` : 'pronto';
  }

  if (gate) {
    const enabledBadge = el('gate-enabled-badge');
    const gateOn = gate.enabled === true;
    enabledBadge.textContent = gateOn ? 'ATTIVO' : 'DISATTIVO';
    enabledBadge.classList.toggle('on', gateOn);

    // RA
    const raEl = el('gate-ra-badge');
    raEl.textContent = gate.ra ? 'SATURATE' : 'OK';
    raEl.className = `gate-status-badge ${gate.ra ? 'saturated' : 'ok'}`;

    // DEC
    const decEl = el('gate-dec-badge');
    decEl.textContent = gate.dec ? 'SATURATE' : 'OK';
    decEl.className = `gate-status-badge ${gate.dec ? 'saturated' : 'ok'}`;

    // Note
    const anysat = gate.ra || gate.dec;
    el('gate-note').textContent = anysat
      ? 'Gate aperto: path B può intervenire sull\'esposizione'
      : 'Gate chiuso: leve RA e DEC non ancora al limite';
  }
}

function updateAutoCalibration(ac) {
  // Pixel scale + fonte (PHD2 / TOML fallback)
  const scale = ac.pixel_scale_arcsec;
  el('autocal-scale').textContent = scale != null ? `${scale.toFixed(3)}"/px` : '—';
  const srcEl = el('autocal-source');
  const fromPhd2 = ac.pixel_scale_source === 'phd2';
  srcEl.textContent = fromPhd2 ? 'PHD2' : 'TOML';
  srcEl.className = `gate-status-badge ${fromPhd2 ? 'ok' : 'saturated'}`;

  // Baseline RMS misurata
  el('autocal-baseline').textContent = ac.baseline_rms_arcsec != null
    ? `${ac.baseline_rms_arcsec.toFixed(3)}"` : '—';

  // Progresso baseline (es. "42/60" o "completata")
  el('autocal-progress').textContent = ac.baseline_done
    ? 'completata' : (ac.baseline_progress || '—');

  // Soglie RMS attive (config efficace in memoria)
  el('autocal-rms-high').textContent = ac.rms_high_active != null
    ? `${ac.rms_high_active.toFixed(3)}"` : '—';
  el('autocal-rms-low').textContent = ac.rms_low_active != null
    ? `${ac.rms_low_active.toFixed(3)}"` : '—';

  // §23 — cap rms_high (proporzionale alla pixel scale)
  const capEl = el('autocal-rms-high-cap');
  const capActiveBadge = el('autocal-cap-active-badge');
  if (ac.rms_high_cap_arcsec != null) {
    capEl.textContent = `${ac.rms_high_cap_arcsec.toFixed(2)}"`;
    capActiveBadge.style.display = ac.rms_high_cap_active ? 'inline-block' : 'none';
  } else {
    capEl.textContent = '—';
    capActiveBadge.style.display = 'none';
  }

  // §23 — baseline rifiutata (sessione non rappresentativa)
  el('autocal-baseline-rejected-badge').style.display =
    ac.baseline_rejected ? 'inline-block' : 'none';

  // §25 — refresh ciclico baseline (tightest-wins)
  const refreshEl = el('autocal-refresh-status');
  if (ac.refresh_enabled === false) {
    refreshEl.textContent = 'spento';
  } else if (ac.refresh_in_progress) {
    refreshEl.textContent = 'in corso: ' + (ac.refresh_progress || '0/0');
  } else if (ac.refresh_seconds_to_next != null) {
    const total = Math.max(0, Math.floor(ac.refresh_seconds_to_next));
    const m = Math.floor(total / 60);
    const s = total % 60;
    refreshEl.textContent = `prossimo tra ${m}m ${s.toString().padStart(2, '0')}s`;
  } else {
    refreshEl.textContent = '—';
  }

  const lastBadge = el('autocal-last-refresh-badge');
  if (ac.last_refresh_action === 'applicato') {
    lastBadge.textContent = 'ULTIMO: APPLICATO';
    lastBadge.className = 'gate-status-badge ok';
    lastBadge.style.display = 'inline-block';
  } else if (ac.last_refresh_action === 'rifiutato') {
    lastBadge.textContent = 'ULTIMO: RIFIUTATO';
    lastBadge.className = 'gate-status-badge';   // neutro grigio (palette di default)
    lastBadge.style.display = 'inline-block';
  } else {
    lastBadge.style.display = 'none';
  }
}

// §31 — Seeing Diagnostic Engine
const DIAG_STATE_COLOR = {
  NOMINAL:           '#00d68f',
  SEEING:            '#ffd66b',
  OVERCORRECTION:    '#ff9a3c',
  DRIFT:             '#8b5cf6',
  UNCERTAIN:         '#8a9cc0',
  INSUFFICIENT_DATA: '#4d5f7a',
};
const DIAG_KIND_LABEL = {
  engine: 'azione motore', micro: 'micro-correzione',
  block: 'intervento BLOCK', attenuate: 'intervento ATTENUATE',
};

function fmtDelta(v) {
  if (v === undefined || v === null) return '—';
  return (v > 0 ? '+' : '') + v.toFixed(3);
}

const TRANSP_STATE = {
  CLEAR: { icon: '\u{1F30C}', color: '#4ade80', label: 'CIELO LIMPIDO' },
  HAZE:  { icon: '\u{1F32B}\uFE0F', color: '#fbbf24', label: 'VELATURE' },
  CLOUD: { icon: '\u2601\uFE0F', color: '#f87171', label: 'NUVOLE' },
};

// §96 — una sezione vuota in un contenitore flex con gap lascia comunque un
// buco verticale: la riga operativa va nascosta esplicitamente, non solo svuotata.
function syncOpsRow() {
  const row = el('ops-row');
  if (!row) { return; }
  const qualcosaDaDire = ['transparency-card', 'recovery-card'].some(id => {
    const c = el(id);
    return c && c.style.display !== 'none';
  });
  row.hidden = !qualcosaDaDire;
}

// §45 — card Transparency Index (NINA). Graceful: senza telemetria la card è nascosta.
function updateTransparency(nina) {
  const card = el('transparency-card');
  if (!card) { return; }
  const t = (nina && nina.transparency) || null;
  if (!t || !t.enabled || !t.available || t.index == null) {
    card.style.display = 'none';
    return;
  }
  card.style.display = '';
  const cfg = TRANSP_STATE[t.state] || { icon: '\u2754', color: '#9ca3af', label: t.state || '—' };
  setGlyph('transp-icon', cfg.icon);
  el('transp-state').textContent = cfg.label;
  el('transp-state').style.color = cfg.color;
  const dpct = (t.deficit_pct != null) ? t.deficit_pct : 0;
  el('transp-index-desc').textContent = dpct > 0
    ? `−${dpct}% vs cielo limpido recente`
    : 'al livello del cielo limpido recente';
  // §66 — accanto a stelle/riferimento, il MEGLIO della serata per questo filtro:
  // rende visibile la deriva del riferimento (prima invisibile: "rana bollita").
  el('transp-stars').textContent = (t.star_count != null && t.base_stars != null)
    ? `${Math.round(t.star_count)}/${Math.round(t.base_stars)}`
      + (t.base_stars_session_best != null
         && Math.round(t.base_stars_session_best) > Math.round(t.base_stars)
          ? ` · best ${Math.round(t.base_stars_session_best)}` : '')
    : '—';
  // Deriva significativa (>15%): il metro si è spostato rispetto al meglio della notte.
  const drift = t.ref_drift_pct;
  el('transp-index-desc').title = (drift != null)
    ? `Riferimento ${drift}% sotto il meglio della serata (stesso filtro)` : '';
  el('transp-index').textContent = t.index != null ? t.index.toFixed(2) : '—';
  // §67 — contesto da NINA: filtro + target, e airmass come telemetria osservabile.
  el('transp-filter').textContent = (t.filter || '—')
    + (t.target ? ` · ${t.target}` : '')
    + (t.airmass != null ? ` · X ${t.airmass.toFixed(2)}` : '');

  // §55 (fix N6) — freschezza esplicita: FRESH (verde, età) o STANTIA (rossa,
  // età vs finestra §43). Con telemetria stantia l'indice è CONGELATO all'ultimo
  // valore: renderlo evidente evita di fidarsi di un cielo che non stiamo più vedendo.
  const freshEl = el('transp-fresh');
  if (freshEl) {
    const age = (t.age_s != null) ? Math.round(t.age_s) : null;
    if (t.fresh) {
      freshEl.textContent = age != null ? `FRESH · ${age}s` : 'FRESH';
      freshEl.style.color = '#34d399';
    } else {
      const win = (t.window_s != null) ? Math.round(t.window_s) : null;
      freshEl.textContent = (age != null && win != null)
        ? `STANTIA · ${age}s > ${win}s` : 'STANTIA';
      freshEl.style.color = '#f87171';
    }
  }
}

// §57 — card Recovery: hint SNR-guida (S2, sola osservazione) + ultima sonda (S1/S2).
// Graceful: nascosta se il tracker è spento o non c'è mai stato contesto degradato.
// ---------------------------------------------------------------------------
//  §73 — Stato del monitor Condizioni del Cielo (§78)
//  Il monitor decide nel plugin; qui si RIFLETTE soltanto. Uno stato per volta,
//  quello vero: nessuno stato inventato. La causa dell'UNSAFE è mostrata come
//  stato perché è l'azione operativa distinta ("guarda la camera" ≠ "aspetta la
//  nuvola"); il dettaglio racconta cosa sta facendo il recupero.
// ---------------------------------------------------------------------------
const SAFETY_UI = {
  SAFE: { glyph: 'scudoOk', tone: 'tone-green', title: 'Autorizzata', cause: 'SAFE',
    tip: "SESSIONE AUTORIZZATA\nNessuna condizione di rischio rilevata: la sequenza può procedere normalmente." },
  MERIDIAN_PROTECTION: { glyph: 'scudoFlip', tone: 'tone-blue', title: 'Finestra meridiano', cause: 'FLIP AUTORIZZATO',
    tip: "FINESTRA MERIDIANO\nStato transitorio: autorizza la sola manovra meccanica di meridian flip mentre la valutazione di sicurezza resta internamente invariata. Terminato il flip riprende il controllo normale." },
  STAR_LOST: { glyph: 'scudoAlert', tone: 'tone-red', title: 'Sospesa', cause: 'STELLA PERSA',
    tip: "SOSPESA — STELLA PERSA\nPHD2 ha perso la stella di guida in modo persistente. La sequenza resta sospesa finché la guida non torna operativa." },
  CLOUD: { glyph: 'scudoAlert', tone: 'tone-red', title: 'Sospesa', cause: 'NUBI',
    tip: "SOSPESA — NUBI\nDegrado di trasparenza persistente misurato sul conteggio stelle della camera di ripresa. Il rientro richiede evidenza di cielo realmente tornato limpido." },
  STALE_TELEMETRY: { glyph: 'scudoAlert', tone: 'tone-red', title: 'Sospesa', cause: 'TELEMETRIA FERMA',
    tip: "SOSPESA — TELEMETRIA FERMA\nLa telemetria di NINA si è fermata mentre l'ultimo cielo noto era degradato: senza osservazione affidabile non si dichiara sicuro." },
  AGENT_LOST: { glyph: 'scudoAlert', tone: 'tone-red', title: 'Sospesa', cause: 'AGENTE PERSO',
    tip: "SOSPESA — AGENTE PERSO\nL'Agente è irraggiungibile durante una sessione attiva: perdere l'osservazione è di per sé una condizione di rischio." },
  GUIDE_UNOBSERVABLE: { glyph: 'scudoAlert', tone: 'tone-red', title: 'Sospesa', cause: 'CANALE GUIDA CIECO',
    tip: "SOSPESA — CANALE GUIDA CIECO\nIl canale di guida non fornisce più informazioni affidabili (nessun frame mentre la guida era attesa). Controlla camera di guida, cavo e USB." },
  UNKNOWN: { glyph: 'scudoIgn', tone: '', title: 'Sconosciuta', cause: 'NESSUNA NOTIZIA',
    tip: "STATO SCONOSCIUTO\nIl monitor delle Condizioni del Cielo non sta pubblicando il proprio stato: non è connesso in NINA, oppure il plugin non è attivo. Assenza di notizie non significa 'sicuro'." },
};

// ---------------------------------------------------------------------------
//  §81 — LIVELLO 1. Cinque slot fissi. La regola che li governa: il livello 1
//  non RIASSUME, ELEGGE. Nessuna icona nuova qui sopra — ogni slot mostra una
//  delle icone del vocabolario, promossa perché è quella che adesso conta di
//  più. Così una macro-condizione non diventa mai uno stato inventato (§73).
// ---------------------------------------------------------------------------
const GUIDA_UI = {
  NORMAL:     ['mirino',     'tone-green',  'Stabile'],
  DEGRADED:   ['mirino',     'tone-yellow', 'In degrado'],
  CRITICAL:   ['mirino',     'tone-orange', 'Critico'],
  RECOVERING: ['mirinoRec',  'tone-blue',   'In recupero'],
  STAR_LOST:  ['mirinoLost', 'tone-red',    'Stella persa'],
  INACTIVE:   ['mirinoOff',  '',            'Ferma'],
};
// §94 — emoji, non glifi: il cielo ha un vocabolario che tutti conoscono gia'.
// CLEAR e' la Via Lattea e non un sole: qui si riprende di notte, e "limpido"
// significa stelle visibili.
const CIELO_UI = {
  CLEAR: ['\u{1F30C}', 'tone-green',  'Limpido'],
  HAZE:  ['\u{1F32B}\uFE0F', 'tone-yellow', 'Velatura'],
  CLOUD: ['\u2601\uFE0F', 'tone-orange', 'Coperto'],
};
const DIAG_UI = {
  NOMINAL:           ['diagStabile', 'tone-green'],
  SEEING:            ['diagSeeing',  'tone-yellow'],
  OVERCORRECTION:    ['diagOver',    'tone-orange'],
  DRIFT:             ['diagDrift',   'tone-purple'],
  UNCERTAIN:         ['diagIgn',     ''],
  INSUFFICIENT_DATA: ['diagIgn',     ''],
};
const VERDICT_IT = { CONFIRM: 'confermata', ATTENUATE: 'attenuata', BLOCK: 'bloccata' };

// §81 — scambia il glifo di un contenitore <svg><use>. Un solo punto di
// verita' per tutte le icone della dashboard: il vocabolario e' quello.
function setGlyph(id, glyph) {
  // Due modalità decise dal DOM: contenitore con <use> = icona disegnata,
  // contenitore semplice = emoji come testo. Cosi' il chiamante non deve
  // sapere quale dei due sta usando.
  const u = el(id + '-u');
  if (u) { u.setAttribute('href', '#i-' + glyph); return; }
  const e = el(id);
  if (e) { e.textContent = glyph; }
}

function l1(key, glyph, tone, title, val, tip) {
  const slot = el('l1-' + key);
  if (!slot) { return; }
  slot.className = 'l1-slot' + (key === 'ctrl' ? ' l1-primary' : '') + (tone ? ' ' + tone : '');
  const em = el('l1-' + key + '-e');          // presente solo dove usiamo le emoji
  if (em) { em.textContent = glyph; }
  else { el('l1-' + key + '-u').setAttribute('href', '#i-' + glyph); }
  el('l1-' + key + '-t').textContent = title;
  el('l1-' + key + '-v').textContent = val || '';
  slot.title = tip || '';
}

function hhmm(iso) {
  if (!iso) { return ''; }
  const d = new Date(iso);
  return isNaN(d) ? '' : d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
}

// ---------------------------------------------------------------------------
//  §82 — LIVELLO 2: "perché / cosa sta intervenendo".
//
//  Tre vincoli, tutti e tre posti in revisione e tutti e tre verificabili
//  leggendo questa funzione:
//    1. SOLO campi già esposti su /status — nessuna metrica nuova, nessuno
//       stato sintetico. Ogni voce nasce da un booleano che esiste già.
//    2. SOLO icone del vocabolario (§81). Nessuna forma nuova.
//    3. Compare SOLO in deviazione. Il verde lo mostra il livello 1, che è
//       quello che rassicura; qui si parla solo quando c'è da capire.
//
//  Rapporto col livello 1: lo slot RECUPERO lassù ELEGGE una fase sola.
//  Qui si vede anche ciò che l'elezione ha dovuto lasciare fuori — ed è
//  esattamente il compito del livello: spiegare, non riassumere.
// ---------------------------------------------------------------------------
function escAttr(s) {
  return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
                  .replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

let _l2Signature = null;

function updateLevel2(data) {
  const row = el('l2-row');
  if (!row) { return; }

  const ctrl = data.controller || {};
  const rh = data.recovery_hint || {};
  const gh = data.guide_health || {};
  const de = ctrl.diagnostic_engine || {};
  const chips = [];
  const add = (glyph, tone, label, val, tip) => chips.push([glyph, tone, label, val, tip]);

  // --- COSA RILEVO -------------------------------------------------------
  if (rh.degrading) {
    add('ondaGiu', 'tone-orange', 'Sensore rapido',
        `cielo in peggioramento · ${Math.round(rh.degrade_s || 0)} s`,
        "Il canale di guida vede il segnale della stella calare rispetto al sereno recente" +
        (rh.snr != null && rh.snr_ref != null ? ` (${rh.snr} contro ${rh.snr_ref})` : '') +
        ".\nLa camera di ripresa se ne accorgerebbe solo a fine posa.");
  }
  if (gh.enabled && gh.channel_ready === false) {
    const why = (gh.channel_not_ready_reasons || []).join(', ');
    add('segnaleDebole', 'tone-yellow', 'Canale guida', 'non pronto',
        (why ? why + ".\n\n" : '') +
        "Finché la stella non è tracciata in modo stabile, una posa di verifica misurerebbe " +
        "il nostro problema invece del cielo: le sonde di recupero, se attive, restano differite.");
  }

  // --- COSA STO FACENDO --------------------------------------------------
  const mm = ctrl.minmove_cap || {};
  if (mm.enabled && mm.clamping_active === true) {
    add('bandaStringe', 'tone-yellow', 'Adaptive MinMove', 'sta limitando',
        "La banda morta sta effettivamente trattenendo correzioni: il seeing chiede di non " +
        "inseguire il rumore." +
        (mm.cap_arcsec != null ? `\n\nTetto corrente ${mm.cap_arcsec}"` : '') +
        (mm.winning ? ` (vince il termine ${mm.winning}).` : '.'));
  }
  if (rh.active) {
    add('nubeSu', 'tone-blue', 'Suggerimento recupero', 'possibile schiarita',
        "La stella di guida è risalita vicino al livello del sereno recente" +
        (rh.snr != null && rh.snr_ref != null ? ` (${rh.snr} su ${rh.snr_ref})` : '') +
        ".\nNon è una conferma: a dire se il campo di ripresa è tornato utilizzabile " +
        "può essere solo la posa di verifica.");
  }
  const probes = Array.isArray(rh.probes) ? rh.probes : [];
  if (probes.length) {
    const last = probes[probes.length - 1];
    const ok = last.outcome_state === 'CLEAR';
    add(ok ? 'lenteSi' : 'lenteNo', ok ? 'tone-green' : 'tone-orange',
        'Verifica del campo',
        `${probes.length} · ${ok ? 'campo tornato' : 'ancora chiuso'}`,
        (ok ? "L'ultima posa di verifica ha ritrovato le stelle al livello del sereno recente."
            : "L'ultima posa di verifica ha trovato il campo ancora sotto le nubi.") +
        "\n\nÈ l'esito di una verifica CONCLUSA: la sonda vive nella sequenza di NINA e " +
        "l'Agente ne conosce solo le tracce, mai il momento in cui scatta.");
  }

  // --- COSA HO DECISO ----------------------------------------------------
  // §80 — l'anello che chiude la catena rilevo -> diagnostico -> decido.
  // Solo quando la decisione ha CAMBIATO qualcosa: un CONFIRM è la norma e tace.
  const lv = de.last_verdict;
  if (lv && lv.verdict !== 'CONFIRM') {
    const att = lv.verdict === 'ATTENUATE';
    add(att ? 'gAttenua' : 'gBlocca', att ? 'tone-yellow' : 'tone-red',
        'Ultimo verdetto',
        (att ? `attenuata ×${lv.factor}` : 'bloccata') +
        (lv.context ? ` · ${lv.context}` : ''),
        `L'ultima azione proposta è stata ${att ? 'ridotta' : 'fermata'} prima di toccare la leva` +
        (lv.context ? ` (${lv.context})` : '') +
        (hhmm(lv.ts_utc) ? `, alle ${hhmm(lv.ts_utc)}` : '') + '.' +
        (lv.reason ? `\n\nMotivo: ${lv.reason}` : '') +
        "\n\nÈ l'ultimo verdetto emesso, non lo stato corrente: il Guardian non ha uno stato, " +
        "giudica una azione per volta.");
  }

  // Firma: si ridisegna solo se cambia davvero qualcosa, altrimenti il tooltip
  // aperto sotto il puntatore sparirebbe a ogni refresh.
  const sig = chips.map(c => c.slice(0, 4).join('|')).join('||');
  if (sig === _l2Signature) { return; }
  _l2Signature = sig;

  row.hidden = chips.length === 0;
  row.innerHTML = chips.map(([g, tone, lbl, val, tip]) =>
    `<div class="l2-chip ${tone}" title="${escAttr(tip)}">` +
    `<svg class="l2-ico" aria-hidden="true"><use href="#i-${g}"/></svg>` +
    `<span class="l2-lbl">${lbl}</span>` +
    `<span class="l2-val">${val}</span></div>`).join('');
}

function updateLevel1(data) {
  const ctrl = data.controller || {};

  // --- 1. CONTROLLO ADATTIVO: la DIAGNOSI, cioè la causa. Gli effetti sulle
  //        leve (MinMove che stringe, esposizione alzata, gate saturo) vivono
  //        al livello 2, dove compaiono solo se stanno accadendo.
  const de = ctrl.diagnostic_engine || {};
  if (de.enabled !== true) {
    l1('ctrl', 'diagIgn', '', 'Motore spento', 'v2.3 pura',
       "CONTROLLO ADATTIVO — SPENTO\nIl motore diagnostico è disattivato: le leve seguono le sole regole di base, senza interpretazione del comportamento della guida.");
  } else {
    const [g, tone] = DIAG_UI[de.state] || DIAG_UI.INSUFFICIENT_DATA;
    let tip = (de.label || 'DATI INSUFFICIENTI') + "\n" + (de.suggestion || '');
    const m = de.metrics || {};
    if (m.nina_penalty != null && m.nina_penalty > 0 && m.confidence_phd2 != null) {
      tip += `\n\nConfidenza ${de.confidence}% = PHD2 ${m.confidence_phd2} − NINA ${m.nina_penalty}` +
             " (il cielo degradato abbassa la fiducia nella diagnosi).";
    }
    // §80 — ULTIMO verdetto, non "stato del Guardian": porta istante e leva
    // proprio per non poter essere letto come condizione corrente.
    const lv = de.last_verdict;
    if (lv) {
      tip += `\n\nUltimo verdetto: azione ${VERDICT_IT[lv.verdict] || lv.verdict}` +
             (lv.context ? ` su ${lv.context}` : '') +
             (lv.verdict === 'ATTENUATE' ? ` (ampiezza ×${lv.factor})` : '') +
             (hhmm(lv.ts_utc) ? ` alle ${hhmm(lv.ts_utc)}` : '') +
             (lv.reason ? ` — ${lv.reason}` : '');
    }
    const gc = de.guardian_counts || {};
    if (gc.CONFIRM || gc.ATTENUATE || gc.BLOCK) {
      tip += `\n\nIn questa sessione: ${gc.CONFIRM || 0} confermate, ` +
             `${gc.ATTENUATE || 0} attenuate, ${gc.BLOCK || 0} bloccate.`;
    }
    l1('ctrl', g, tone, de.label || 'DATI INSUFFICIENTI',
       de.confidence != null ? `confidenza ${de.confidence}%` : '', tip);
  }

  // --- 2. GUIDA: stato diretto, nessuna derivazione.
  const gs = ctrl.guiding_state || 'INACTIVE';
  const [gg, gt, gl] = GUIDA_UI[gs] || GUIDA_UI.INACTIVE;
  l1('guida', gg, gt, gl, gs.replace(/_/g, ' '),
     `GUIDA — ${gl.toUpperCase()}\nStato riportato da PHD2: ${gs}.`);

  // --- 3. CIELO: stato diretto. Senza pose non c'è indice, e l'assenza di dati
  //        non è mai "sereno" (stessa disciplina del §55).
  const t = (data.nina || {}).transparency || {};
  if (t.state && CIELO_UI[t.state]) {
    const [cg, ct, cl] = CIELO_UI[t.state];
    const idx = t.index != null ? Number(t.index).toFixed(2) : '—';
    let tip = `CIELO — ${cl.toUpperCase()}\nIndice di trasparenza ${idx}` +
      (t.base_stars != null ? ` sul riferimento di ${t.base_stars} stelle.` : '.');
    if (t.state === 'HAZE') {
      tip += "\nZona neutra: il cielo è calato ma non abbastanza da contare come nube. Non accumula né drena.";
    }
    l1('cielo', cg, ct, cl, `${t.state} · ${idx}`, tip);
  } else {
    // Ignoranza dichiarata: prima ricadeva sull'icona del sereno in grigio,
    // cioe' mostrava "limpido" quando non sappiamo nulla.
    l1('cielo', '\u2754', '', 'Nessuna misura', '—',
       "CIELO — NESSUNA MISURA\nNon arrivano pose da NINA: senza immagini non c'è indice di trasparenza. L'assenza di dati non è mai «sereno».");
  }

  // --- 4. SESSIONE: la CONSEGUENZA operativa. Titolo = cosa accade alla
  //        sequenza; riga sotto = la causa, che è l'azione operativa distinta.
  updateSafetyState(data.safety, data.guide_health);

  // --- 5. RECUPERO: elezione per fase. A riposo resta uno slot muto, non
  //        sparisce: le posizioni fisse sono ciò che rende leggibile la striscia.
  const rh = data.recovery_hint || {};
  const probes = Array.isArray(rh.probes) ? rh.probes : [];
  const last = probes.length ? probes[probes.length - 1] : null;
  if (rh.degrading) {
    l1('recup', 'ondaGiu', 'tone-orange', 'Cielo in peggioramento',
       `${Math.round(rh.degrade_s || 0)} s`,
       "RECUPERO — CIELO IN PEGGIORAMENTO\nIl canale di guida vede il segnale della stella crollare rispetto al sereno recente" +
       (rh.snr != null && rh.snr_ref != null ? ` (${rh.snr} contro ${rh.snr_ref})` : '') +
       ".\nLa camera di ripresa se ne accorgerebbe solo a fine posa: qui si accumula evidenza senza aspettarla.");
  } else if (rh.active) {
    l1('recup', 'nubeSu', 'tone-blue', 'Possibile schiarita',
       rh.snr != null && rh.snr_ref != null ? `${rh.snr} / ${rh.snr_ref}` : '',
       "RECUPERO — POSSIBILE SCHIARITA\nLa stella di guida è risalita vicino al livello del sereno recente: vale la pena verificare.\nNon è una conferma — a dire se il campo di ripresa è tornato utilizzabile può essere solo la posa di controllo.");
  } else if (last) {
    const ok = last.outcome_state === 'CLEAR';
    l1('recup', ok ? 'lenteSi' : 'lenteNo', ok ? 'tone-green' : 'tone-orange',
       ok ? 'Campo tornato' : 'Ancora chiuso',
       `${probes.length} verifiche`,
       (ok ? "RECUPERO — ULTIMA VERIFICA POSITIVA\nLa posa di controllo ha ritrovato le stelle al livello del sereno recente."
           : "RECUPERO — ULTIMA VERIFICA NEGATIVA\nLa posa di controllo ha trovato il campo ancora sotto le nubi. Si riprova al giro successivo.") +
       "\n\nÈ l'esito dell'ultima verifica conclusa: la sonda vive nella sequenza di NINA e l'Agente ne conosce solo le tracce, mai il momento in cui scatta.");
  } else {
    l1('recup', 'nubeFerma', '', 'Nessuno', '—',
       "RECUPERO — NESSUNO IN CORSO\nNessun degrado in atto e nessuna verifica del campo registrata. È lo stato normale di una notte buona.");
  }
}

// ===========================================================================
//  §74 — PANNELLI DINAMICI
//  "L'informazione più importante non è tutto ciò che esiste, ma ciò che sta
//  succedendo adesso." I pannelli che descrivono l'ATTIVITÀ INTERNA del motore
//  restano una barra finché non lavorano davvero; quando intervengono si aprono
//  da soli e si richiudono dopo un periodo di quiete.
//
//  Restano SEMPRE visibili i pannelli di STATO GENERALE (Condizioni del Cielo,
//  Trasparenza, Recovery, grafico guida, stato Agente): sono quelli che
//  l'operatore deve poter consultare in qualsiasi momento.
//
//  Regole (deliberate, per non nascondere mai ciò che conta):
//   1. attività  -> il pannello si APRE sempre, anche se era stato chiuso a
//      mano: un intervento del motore deve attirare l'occhio, è il suo scopo.
//   2. quiete    -> si richiude dopo PANEL_IDLE_MS, MA MAI se l'operatore lo
//      ha aperto lui (pin): una scelta esplicita non viene mai contraddetta.
//   3. da chiuso la barra porta comunque lo STATO (chip), così l'informazione
//      essenziale non sparisce mai — si comprime.
//  Il log decisioni resta la memoria persistente: la chiusura non perde nulla.
// ===========================================================================

const PANEL_IDLE_MS = 120000;   // 2 min di quiete prima di richiudere

const DYNAMIC_PANELS = [
  {
    key: 'controller',
    find: () => document.querySelector('.controller-card'),
    // Attività EVENTO: il motore ha eseguito un'azione (il contatore cresce).
    read: (d) => {
      const ctrl = d.controller || {};
      const eng = ctrl.engine || {};
      const st = ctrl.guiding_state || '—';
      return {
        active: false,
        pulse: eng.actions_total || 0,
        chip: String(st).replace(/_/g, ' '),
        working: st && st !== 'INACTIVE',
      };
    },
  },
  {
    key: 'exposure',
    // La card "Esposizione Dinamica" (l'altra .exposure-card è Adaptive MinMove).
    find: () => document.querySelector('.exposure-card:not(#minmove-cap-card)'),
    // Attività STATO: esposizione sopra la base o cooldown in corso.
    read: (d) => {
      const exp = (d.controller || {}).exposure;
      if (!exp) { return { active: false, chip: '—', working: false }; }
      const steps = exp.steps_above_base || 0;
      const boosted = (exp.state || 'NOMINAL') !== 'NOMINAL';
      const cooling = (exp.cooldown_residuo_s ?? 0) > 0;
      return {
        active: boosted || steps > 0 || cooling,
        chip: boosted ? String(exp.state).replace(/_/g, ' ')
                      : (steps > 0 ? `+${steps} step` : 'NOMINAL'),
        working: boosted || steps > 0,
      };
    },
  },
  {
    key: 'escalation',
    find: () => document.querySelector('.escalation-card'),
    chipTip: "Il cancello autorizza gli interventi più incisivi solo quando le leve "
           + "normali sono esaurite. Chiuso significa che aggressività e MinMove hanno "
           + "ancora margine, e l'Agente preferisce usare quelli.",
    // Attività STATO: un asse è al limite -> il gate è APERTO (path B può agire).
    read: (d) => {
      const g = (d.controller || {}).escalation_gate;
      if (!g) { return { active: false, chip: '—', working: false }; }
      const open = !!(g.ra || g.dec);
      return {
        active: open,
        chip: open ? 'GATE APERTO' : (g.enabled ? 'GATE CHIUSO' : 'DISATTIVO'),
        working: open,
      };
    },
  },
  {
    key: 'minmove',
    find: () => document.getElementById('minmove-cap-card'),
    // Attività STATO. Attenzione ai due flag distinti del controller:
    //   cap_active      = il cap ESISTE (baseline filtrata pronta)
    //   clamping_active = il cap ha davvero TAGLIATO una richiesta (§0-bis)
    // "Occupare spazio in proporzione all'attività" significa il SECONDO:
    // un cap pronto ma che non taglia nulla non sta lavorando.
    read: (d) => {
      const mc = (d.controller || {}).minmove_cap;
      const ready = !!(mc && mc.enabled !== false && mc.cap_active === true);
      const clamping = !!(mc && mc.clamping_active === true);
      return {
        active: clamping,
        chip: clamping ? 'STA LIMITANDO' : (ready ? 'PRONTO' : 'NON ATTIVO'),
        working: clamping,
      };
    },
  },
];

const panelState = {};   // key -> {card, body, chipEl, pinEl, pinned, lastPulse, lastActiveTs}

function setupDynamicPanels() {
  for (const spec of DYNAMIC_PANELS) {
    const card = spec.find();
    if (!card) { continue; }

    // Header = la riga che contiene il titolo (a volte già dentro un wrapper).
    const head = card.querySelector('.diag-header') || card.querySelector('h2');
    if (!head) { continue; }

    // Corpo = tutto ciò che segue l'header, spostato in un contenitore
    // richiudibile. Nessun id viene toccato: le funzioni di update esistenti
    // continuano a trovare i propri elementi esattamente come prima.
    const body = document.createElement('div');
    body.className = 'panel-body';
    let node = head.nextSibling;
    while (node) {
      const next = node.nextSibling;
      body.appendChild(node);
      node = next;
    }
    card.appendChild(body);

    head.classList.add('panel-head');
    const chevron = document.createElement('span');
    chevron.className = 'panel-chevron';
    chevron.textContent = '▼';
    head.insertBefore(chevron, head.firstChild);

    const pin = document.createElement('span');
    pin.className = 'panel-pin';
    pin.textContent = '📌';
    pin.hidden = true;
    head.appendChild(pin);

    // Il chip di stato si aggiunge solo se l'header non ha già un badge suo
    // (Adaptive MinMove ce l'ha): niente informazione duplicata.
    let chip = null;
    if (!head.querySelector('[class*="badge"]')) {
      chip = document.createElement('span');
      chip.className = 'panel-chip';
      chip.textContent = '—';
      if (spec.chipTip) { chip.title = spec.chipTip; }   // §97
      head.appendChild(chip);
    }

    panelState[spec.key] = {
      card, body, chip, pin, pinned: false, lastPulse: null, lastActiveTs: 0,
    };
    card.classList.add('panel-collapsed');   // si parte compatti

    head.addEventListener('click', () => {
      const st = panelState[spec.key];
      const collapsed = card.classList.toggle('panel-collapsed');
      // Aperto a mano = scelta esplicita: l'automatismo non lo richiude più.
      st.pinned = !collapsed;
      st.pin.hidden = !st.pinned;
    });
  }
}

function updateDynamicPanels(data) {
  const now = Date.now();
  for (const spec of DYNAMIC_PANELS) {
    const st = panelState[spec.key];
    if (!st) { continue; }

    let info;
    try {
      info = spec.read(data) || {};
    } catch (e) {
      continue;   // un pannello non deve mai rompere il refresh degli altri
    }

    if (st.chip) {
      st.chip.textContent = info.chip || '—';
      st.chip.classList.toggle('working', !!info.working);
    }

    // Regola 1 — evento (contatore che cresce) o stato attivo: APRE sempre.
    const pulsed = info.pulse != null && st.lastPulse != null && info.pulse > st.lastPulse;
    if (info.pulse != null) { st.lastPulse = info.pulse; }

    if (info.active || pulsed) {
      st.lastActiveTs = now;
      if (st.card.classList.contains('panel-collapsed')) {
        st.card.classList.remove('panel-collapsed');
      }
      continue;
    }

    // Regola 2 — quiete: si richiude, ma mai contro una scelta dell'operatore.
    if (!st.pinned && !st.card.classList.contains('panel-collapsed')
        && st.lastActiveTs > 0 && (now - st.lastActiveTs) > PANEL_IDLE_MS) {
      st.card.classList.add('panel-collapsed');
    }
  }
}

// ===========================================================================
//  §77 — "Condizioni del Cielo": il racconto del recupero
//
//  Il monitor ha DUE osservatori con scale temporali diversissime:
//    • il canale di guida — SNR della stella, ogni ~3 s: velocissimo, ma vede
//      UNA stella. Può testimoniare che il cielo è peggiorato, non che il campo
//      è tornato buono;
//    • la posa di verifica — centinaia di stelle sul campo di ripresa, ma una
//      fotografia ogni 300 s: lentissima, e l'unica che autorizza il ritorno.
//
//  Questa riga NON decide nulla: unisce le due voci e le racconta, così durante
//  una notte vera si capisce PERCHÉ il monitor sta facendo quello che fa —
//  soprattutto nei minuti in cui il veloce ha già capito e il lento sta ancora
//  esponendo. Ordine di precedenza: si racconta il fatto più urgente e più
//  fresco, uno solo alla volta.
// ===========================================================================

function updateSkyStory(data) {
  const box = el('sky-story');
  if (!box) { return; }

  const rh = data.recovery_hint || {};
  const t = ((data.nina || {}).transparency) || {};
  const safety = data.safety || {};
  const state = t.state || null;
  const unsafe = safety.state === 'UNSAFE';

  // §77-bis — DUE righe brevi. Il racconto è dal punto di vista del recupero nel
  // suo insieme, in prima persona: chi legge vuole sapere cosa sta facendo il
  // sistema, non quale sottocomponente ha prodotto quale valore. I nomi interni
  // (hint, sonda, N1, latch) non compaiono mai; i numeri stanno nel tooltip.
  let cls = '', icon = '\u{1F319}';
  let seeing = 'In attesa dei primi dati…';
  let doing = '';
  let detail = '';

  if (rh.degrading) {
    cls = 'worsening'; icon = '\u2601\uFE0F';
    seeing = 'Il cielo sta peggiorando rapidamente.';
    doing = 'Sto accumulando evidenze senza aspettare la prossima posa.';
    detail = `Segnale della stella di guida in calo da ${Math.round(rh.degrade_s || 0)}s` +
             (rh.snr != null && rh.snr_ref != null
               ? ` (${rh.snr} contro ${rh.snr_ref} del cielo sereno recente).` : '.');
  } else if (state === 'CLOUD' || state === 'HAZE') {
    if (rh.active) {
      cls = 'recovering'; icon = '\u{1F324}\uFE0F';
      seeing = 'Vedo un recupero stabile del cielo.';
      doing = 'Attendo la conferma dalla posa di verifica.';
      detail = (rh.snr != null && rh.snr_ref != null
                ? `Stella di guida a ${rh.snr} contro ${rh.snr_ref} del sereno recente. ` : '') +
               'La stella di guida è una sola: a dire se il campo di ripresa è ' +
               'tornato utilizzabile può essere solo la camera di ripresa.';
    } else if (unsafe) {
      cls = 'probing'; icon = '\u{1F50D}';
      seeing = 'Cielo coperto.';
      doing = 'Verifico periodicamente il campo di ripresa.';
      detail = 'Scatto pose di controllo finché il cielo non torna davvero ' +
               'utilizzabile; la sequenza resta sospesa fino ad allora.';
    } else {
      cls = 'clouded'; icon = '\u2601\uFE0F';
      seeing = 'Cielo coperto.';
      doing = 'Il campo di ripresa non è utilizzabile.';
    }
  } else if (state === 'CLEAR') {
    const lastProbe = (Array.isArray(rh.probes) && rh.probes.length)
      ? rh.probes[rh.probes.length - 1] : null;
    if (unsafe && lastProbe && lastProbe.outcome_state === 'CLEAR') {
      cls = 'confirmed'; icon = '\u2705';
      seeing = 'Recupero confermato.';
      doing = 'Completo le verifiche, poi la sequenza riprende.';
      detail = 'La posa di controllo ha ritrovato il campo al livello del sereno ' +
               'recente: servono ancora alcune conferme prima di riautorizzare.';
    } else {
      cls = 'clear'; icon = '\u{1F30C}';
      seeing = 'Cielo limpido.';
      doing = 'Il campo è al livello del sereno recente.';
    }
  }

  box.className = `sky-story ${cls}`;
  el('sky-story-icon').textContent = icon;
  el('sky-story-text').textContent = seeing;
  el('sky-story-action').textContent = doing;
  box.title = detail || `${seeing} ${doing}`.trim();
}

function updateSafetyState(safety, guideHealth) {
  const state = (safety && safety.state) || 'UNKNOWN';
  const cause = (safety && safety.cause) || null;
  // Per l'UNSAFE è la CAUSA a fare lo stato visibile (azione operativa distinta).
  const key = state === 'UNSAFE' ? (SAFETY_UI[cause] ? cause : 'STAR_LOST') : state;
  const ui = SAFETY_UI[key] || SAFETY_UI.UNKNOWN;

  // Dettaglio: il fatto MISURATO dall'Agente dietro la decisione del monitor.
  // Mai affermazioni su ciò che l'Agente non può sapere (§73-bis).
  let detail = (safety && safety.detail) || '';
  if (!detail && state === 'UNSAFE' && guideHealth && guideHealth.enabled) {
    if (guideHealth.channel_ready === false) {
      detail = (guideHealth.channel_not_ready_reasons || [])[0] || 'canale guida non ancora affidabile';
    } else if (guideHealth.channel_ready === true) {
      detail = 'canale guida stabile';
    }
  }

  let tip = ui.tip;
  if (detail) { tip += "\n\n" + detail + "."; }
  // §72 — dentro la finestra il riportato diverge dall'interno: dirlo esplicitamente.
  if (safety && safety.internal_safe === false && state === 'MERIDIAN_PROTECTION') {
    tip += "\n\nValutazione interna: ancora UNSAFE — al termine del flip la sequenza torna sospesa.";
  }
  if (safety && safety.age_s != null && safety.fresh === false) {
    tip += `\n\nUltimo aggiornamento ${Math.round(safety.age_s)} s fa.`;
  }
  l1('sess', ui.glyph, ui.tone, ui.title, ui.cause, tip);
}

function updateRecoveryHint(rh) {
  const card = el('recovery-card');
  if (!card) { return; }
  const hasContext = rh && rh.enabled
    && (rh.snr != null || (rh.probes && rh.probes.length > 0) || rh.active);
  if (!hasContext) {
    card.style.display = 'none';
    return;
  }
  card.style.display = '';
  const stateEl = el('recovery-state');
  if (rh.active) {
    setGlyph('recovery-icon', 'nubeSu');
    stateEl.textContent = 'CIELO IN RECUPERO?';
    stateEl.style.color = '#34d399';
  } else {
    setGlyph('recovery-icon', 'lenteVuota');
    stateEl.textContent = 'IN OSSERVAZIONE';
    stateEl.style.color = '#9ca3af';
  }
  el('recovery-reason').textContent = rh.reason || '';
  el('recovery-snr').textContent =
    (rh.snr != null ? rh.snr.toFixed(1) : '—') + ' / ' +
    (rh.snr_ref != null ? rh.snr_ref.toFixed(1) : '—');
  el('recovery-acc').textContent =
    `${rh.accumulator_s != null ? rh.accumulator_s : '—'}s/${rh.sustained_target_s != null ? rh.sustained_target_s : '—'}s`;
  const probes = rh.probes || [];
  if (probes.length > 0) {
    const p = probes[probes.length - 1];
    const ago = Math.max(0, Math.round((Date.now() / 1000 - p.ts) / 60));
    const trig = p.trigger === 'hint_S2' ? 'S2' : 'S1';
    const idx = p.outcome_index != null ? p.outcome_index.toFixed(2) : '—';
    el('recovery-probe').textContent = `${trig} → ${p.outcome_state || '—'} (${idx}) · ${ago}m fa`;
  } else {
    el('recovery-probe').textContent = '—';
  }
}

// §51 — card "Adaptive MinMove": badge ACTIVE/IDLE (da clamping_active), cap, baseline
// filtrata, termine vincente (GUIDING/IMAGING), MinMove efficace RA/DEC. Graceful: cap
// assente/kill-switch off -> "non attivo" (badge grigio), nessun crash.
function updateMinMoveCap(mc) {
  const badge = el('mmcap-status-badge');
  if (!badge) { return; }
  const winner = el('mmcap-winner-badge');

  // Graceful: blocco assente o cap disabilitato/non pronto.
  if (!mc || mc.enabled === false || mc.cap_active !== true) {
    badge.textContent = 'NON ATTIVO';
    badge.style.background = 'rgba(138,156,192,0.15)';
    badge.style.color = '#8a9cc0';
    badge.title = mc && mc.enabled === false
      ? 'Cap MinMove adattivo disattivato (kill-switch)'
      : 'Cap MinMove adattivo non ancora pronto (baseline filtrata in formazione)';
    el('mmcap-cap').textContent = '—';
    el('mmcap-baseline').textContent = '—';
    el('mmcap-minmove').textContent = '—';
    el('mmcap-params').textContent = '—';
    if (winner) { winner.style.display = 'none'; }
    return;
  }

  // Badge ACTIVE/IDLE — guidato da clamping_active (NON da "MinMove == cap").
  if (mc.clamping_active === true) {
    badge.textContent = 'ACTIVE';
    badge.style.background = 'rgba(251,146,60,0.18)';
    badge.style.color = '#fb923c';
    badge.title = 'Il MinMove richiesto dal controllore è stato limitato dal cap adattivo';
  } else {
    badge.textContent = 'IDLE';
    badge.style.background = 'rgba(74,222,128,0.15)';
    badge.style.color = '#4ade80';
    badge.title = 'Il controllore sta operando senza limitazioni del cap adattivo';
  }

  const capArc = mc.cap_arcsec != null ? mc.cap_arcsec.toFixed(2) : '—';
  const capPx = mc.cap_px != null ? mc.cap_px.toFixed(2) : '—';
  el('mmcap-cap').textContent = `${capArc}″ (${capPx} px)`;
  el('mmcap-baseline').textContent = mc.baseline_filtered_arcsec != null
    ? mc.baseline_filtered_arcsec.toFixed(2) + '″' : '—';
  const ra = mc.minmove_ra_arcsec != null ? mc.minmove_ra_arcsec.toFixed(2) : '—';
  const dec = mc.minmove_dec_arcsec != null ? mc.minmove_dec_arcsec.toFixed(2) : '—';
  el('mmcap-minmove').textContent = `${ra}″ / ${dec}″`;
  el('mmcap-params').textContent = (mc.k != null ? `k=${mc.k}` : 'k=—')
    + (mc.imaging_ceiling_arcsec != null ? ` · imaging ≤ ${mc.imaging_ceiling_arcsec}″` : '');

  if (winner) {
    if (mc.winning === 'guiding' || mc.winning === 'imaging') {
      winner.style.display = '';
      const isGuiding = mc.winning === 'guiding';
      winner.textContent = isGuiding ? 'GUIDING' : 'IMAGING';
      winner.style.background = isGuiding ? 'rgba(91,156,246,0.18)' : 'rgba(167,139,250,0.18)';
      winner.style.color = isGuiding ? '#5b9cf6' : '#a78bfa';
      winner.title = isGuiding
        ? 'Il limite è attualmente determinato dalla baseline di guida'
        : 'Il limite è determinato dal requisito di imaging del setup';
    } else {
      winner.style.display = 'none';
    }
  }
}

// §63 — rende visibile la differenza tra "sta ancora raccogliendo dati", "valuta
// regolarmente ma non c'è motivo di intervenire" e "ha effettuato un intervento".
// Senza questa riga, durante la validazione un motore sano ma quieto sembra fermo.
function updateEngineCycle(eng) {
  const elx = el('engine-cycle');
  if (!elx) return;
  const n = eng.eval_count || 0;
  const fmt = ts => ts ? new Date(ts * 1000).toLocaleTimeString('it-IT') : '—';
  if (n === 0) {
    elx.textContent = 'In raccolta dati — nessuna valutazione ancora';
    elx.style.color = '#e0a800';
  } else if (!eng.actions_total) {
    elx.textContent = `ATTIVO — valuta e non interviene (${n} valutazioni · ultima ${fmt(eng.last_eval_ts)})`;
    elx.style.color = '#34d399';
  } else {
    elx.textContent = `ATTIVO — ${n} valutazioni · ultimo intervento ${fmt(eng.last_action_ts)}: ${eng.last_action || ''}`;
    elx.style.color = '#4a9eff';
  }
}

function updateDiagnosticEngine(de) {
  const enabled = de.enabled === true;

  // Badge modalità (read-only). §54: JITTER è deprecata (fuori dal toggle); se un config
  // legacy la riporta ancora, la mostriamo etichettata "(deprecato)" senza rompere nulla.
  const modeBadge = el('diag-mode-badge');
  const curMode = de.mode || 'guardian';
  modeBadge.textContent = enabled
    ? (curMode === 'jitter' ? 'JITTER (deprecato)' : curMode.toUpperCase())
    : 'OFF';
  modeBadge.className = 'diag-mode-badge ' + (enabled ? ('mode-' + curMode) : 'mode-off');

  // HERO — diagnosi
  const state = de.state || 'INSUFFICIENT_DATA';
  const labelEl = el('diag-label');
  labelEl.textContent = de.label || 'DATI INSUFFICIENTI';
  labelEl.style.color = DIAG_STATE_COLOR[state] || DIAG_STATE_COLOR.INSUFFICIENT_DATA;

  const confEl = el('diag-confidence');
  if (enabled && de.confidence != null) {
    // §46 — decomposizione confidence quando NINA ha modulato il SEEING:
    // "57% (PHD2 76 − NINA 19)". Numeri di confidence, mai conteggi assoluti di stelle.
    const m = de.metrics || {};
    let txt = de.confidence + '%';
    if (m.nina_penalty != null && m.nina_penalty > 0 && m.confidence_phd2 != null) {
      txt += ` (PHD2 ${m.confidence_phd2} − NINA ${m.nina_penalty})`;
    } else if (!de.confidence_calibrated) {
      txt += ' · provvisoria';
    } else if (m.transparency_state) {
      txt += ` · trasparenza ${m.transparency_state}`;
    }
    confEl.textContent = txt;
    confEl.style.display = '';
  } else {
    confEl.style.display = 'none';
  }

  el('diag-suggestion').textContent = de.suggestion
    || (enabled ? '' : 'Motore spento — comportamento identico alla v2.3.');

  // Evidenze (✓ a sostegno / ◦ neutro) — il "perché" senza numeri
  const evEl = el('diag-evidence');
  evEl.innerHTML = '';
  (de.evidence || []).forEach(line => {
    const li = document.createElement('li');
    li.textContent = line;
    li.className = line.trim().startsWith('✓') ? 'ev-yes' : 'ev-neutral';
    evEl.appendChild(li);
  });

  // Azione & esito ultima azione
  const actEl = el('diag-action');
  const lo = de.last_outcome;
  if (!enabled) {
    actEl.textContent = '—';
  } else if (lo) {
    actEl.textContent = (DIAG_KIND_LABEL[lo.action_kind] || lo.action_kind || '') +
      (lo.state ? ' · ' + lo.state : '');
  } else {
    actEl.textContent = 'nessuna azione';
  }

  const outEl = el('diag-outcome');
  if (lo && lo.delta) {
    const lc = (lo.lever_changes && lo.lever_changes.length)
      ? lo.lever_changes.map(c => `${(c.axis || '').toUpperCase()} ${c.param} ${c.old}→${c.new}`).join(', ')
      : (lo.action_kind === 'block' ? 'mossa v2.3 bloccata' : '—');
    const d = lo.delta;
    outEl.innerHTML =
      `<span class="diag-out-leve">${lc}</span>` +
      `<span class="diag-out-delta">ΔRMS ${fmtDelta(d.rms_total)} · Δjitter ${fmtDelta(d.jitter)} · Δspike ${fmtDelta(d.spike_score)}</span>`;
    outEl.style.display = '';
  } else {
    outEl.style.display = 'none';
  }

  // Dettaglio tecnico (numeri grezzi dietro le evidenze)
  const m = de.metrics || {};
  el('diag-m-rms').textContent = m.rms != null ? m.rms.toFixed(3) + '″' : '—';
  el('diag-m-hfd').textContent = m.hfd != null
    ? `${m.hfd.toFixed(2)} (${(m.hfd_ref || 0).toFixed(2)})` : '—';
  el('diag-m-jitter').textContent = m.jitter != null
    ? `${m.jitter.toFixed(3)} (${(m.jitter_ref || 0).toFixed(3)})` : '—';
  el('diag-m-lag1').textContent = m.lag1_ra != null
    ? `${m.lag1_ra.toFixed(2)} / ${(m.lag1_dec ?? 0).toFixed(2)}` : '—';
  el('diag-m-trend').textContent = m.trend_max != null ? m.trend_max.toFixed(3) : '—';
  const gc = de.guardian_counts || {};
  el('diag-m-counts').textContent =
    `${gc.CONFIRM || 0} / ${gc.ATTENUATE || 0} / ${gc.BLOCK || 0} / ${gc.micro || 0}`;

  // Switcher: OFF sempre attivo (kill switch); GUARDIAN gated. §54: JITTER rimossa dal
  // toggle (deprecata/sperimentale, mai validata — scavalca §44/§50/§51/§53).
  const allow = de.allow_dashboard_mode_switch === true;
  ['off', 'guardian'].forEach(mode => {
    const btn = el('diag-btn-' + mode);
    if (!btn) return;
    const active = enabled ? (de.mode === mode) : (mode === 'off');
    btn.classList.toggle('active', active);
    btn.disabled = (mode !== 'off') && !allow;
  });
}

// Log azioni
function addActionLog(action) {
  const logBody = el('action-log');

  // Rimuovi placeholder
  const placeholder = logBody.querySelector('.log-placeholder');
  if (placeholder) placeholder.remove();

  const entry = document.createElement('div');
  entry.className = `log-entry ${action.dry_run ? 'dry' : 'live'}`;

  const time = new Date(action.timestamp * 1000).toLocaleTimeString('it-IT', { hour12: false });
  const isDown = action.new_value < action.old_value;
  const valClass = isDown ? 'down' : '';

  const oldVal = action.old_value !== undefined && action.old_value !== null ? Number(action.old_value).toFixed(1) : '—';
  const newVal = action.new_value !== undefined && action.new_value !== null ? Number(action.new_value).toFixed(1) : '—';

  entry.innerHTML = `
    <span class="log-time">${time}</span>
    <div class="log-content">
      <div>
        <span class="log-axis">${(action.axis || '').toUpperCase()}</span>
        <span class="log-param" style="margin-left:8px">${action.param || ''}</span>
        <span class="log-change" style="margin-left:8px">
          <span class="old-val">${oldVal}</span>
          <span class="arrow">→</span>
          <span class="new-val ${valClass}">${newVal}</span>
        </span>
      </div>
      <div class="log-reason">${action.reason || ''}</div>
    </div>
    <span class="log-badge ${action.dry_run ? 'dry' : 'live'}">${action.dry_run ? 'TEST' : 'LIVE'}</span>
  `;

  logBody.prepend(entry);

  // Mantieni al massimo 50 entry nel DOM
  const entries = logBody.querySelectorAll('.log-entry');
  if (entries.length > 50) {
    entries[entries.length - 1].remove();
  }
}

function updateConnStatus(state, label) {
  const dot = document.querySelector('.status-dot');
  dot.className = `status-dot ${state}`;
  el('conn-label').textContent = label;
}


// ===== CONTROLLI =====
el('btn-clear-chart').addEventListener('click', () => {
  guideChart.data.labels = [];
  guideChart.data.datasets.forEach(ds => ds.data = []);
  exposureMarkerMeta = [];
  ninaMarkerMeta = [];
  guideChart.update();
  frameCount = 0;
  el('frame-count').textContent = '0 frame';
});

el('btn-clear-log').addEventListener('click', () => {
  el('action-log').innerHTML = '<div class="log-placeholder">Log pulito.</div>';
});

// §73 — il toggle MODALITÀ TEST è stato sostituito dall'indicatore di stato del
// Safety Monitor (spazio dell'header, molto più utile sul campo). La modalità resta
// impostabile da config.toml ([control] dry_run) o da CLI (--dry-run), e resta
// visibile nel badge di modalità: si è rimosso l'interruttore, non la funzione.


// §31/§54 — switcher modalità motore. OFF = kill switch (nessuna conferma); attivare
// GUARDIAN richiede conferma (e allow_dashboard_mode_switch lato server). JITTER è
// deprecata e NON esposta qui (guard-rail anche lato backend).
['off', 'guardian'].forEach(mode => {
  const btn = el('diag-btn-' + mode);
  if (!btn) return;
  btn.addEventListener('click', async () => {
    if (btn.disabled) return;
    if (mode === 'guardian' &&
        !confirm('Attivare GUARDIAN? La v2.3 continua a pilotare; il motore conferma/attenua/blocca le sue mosse e fa micro-correzioni nei buchi.')) return;
    try {
      const r = await fetch(`${API_BASE}/config/diagnostic_mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
      });
      const res = await r.json();
      if (res && res.error === 'not_allowed') {
        alert('Attivazione non permessa: allow_dashboard_mode_switch=false nel config.toml.');
      }
    } catch (e) {
      console.error('Errore set diagnostic_mode:', e);
    }
    fetchStatus();
  });
});


// ===== HELPERS =====
function el(id) { return document.getElementById(id); }


// ===== BRANDING (§26): byline + footer da /about (chiamato 1x al load) =====
async function loadBrandInfo() {
  try {
    const resp = await fetch('/about');
    if (!resp.ok) return;
    const a = await resp.json();

    const byline = el('brand-byline');
    if (byline) byline.textContent = `${a.project_name} v${a.version} — by ${a.author}`;

    const footer = el('brand-footer');
    if (footer) {
      // Costruzione sicura: textContent + nodo <a> per il link Telegram
      footer.textContent = '';
      footer.append(`${a.project_name} v${a.version} · by ${a.author} · ${a.copyright} · `);
      const tgLink = document.createElement('a');
      tgLink.href = a.contact_telegram;
      tgLink.textContent = 'Community Telegram';
      tgLink.target = '_blank';
      tgLink.rel = 'noopener noreferrer';
      tgLink.className = 'brand-contact';
      footer.appendChild(tgLink);
    }
  } catch (_e) {
    // silent: branding non critico, la dashboard funziona comunque
  }
}


// ===== AVVIO =====
document.addEventListener('DOMContentLoaded', () => {
  loadBrandInfo();
  setupDynamicPanels();   // §74
  connectWS();

  // Poll status ogni 5s come fallback se il WS non manda aggiornamenti
  setInterval(fetchStatus, 5000);
});
