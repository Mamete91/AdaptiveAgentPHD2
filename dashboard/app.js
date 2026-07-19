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
    setCondition('STAR_LOST', '⭕', '🌕 Stella persa');
  } else if (msg.type === 'start_guiding') {
    setCondition('NOMINAL', '🌟', 'Guida avviata');
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
  el('dry-run-switch').checked = isDryRun;
  el('mode-badge').textContent = isDryRun ? 'MODALITÀ TEST' : 'LIVE CONTROL';
  el('mode-badge').classList.toggle('live', !isDryRun);
  
  if (ctrl.ai_find_enabled !== undefined) {
    el('ai-find-switch').checked = ctrl.ai_find_enabled;
  }

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
  NOMINAL:         { icon: '🌟', color: '#00d68f', label: 'Nominale' },
  DEGRADED_SEEING: { icon: '🌪', color: '#ff9a3c', label: 'Seeing Degradato' },
  OSCILLATING:     { icon: '〰️', color: '#ffd66b', label: 'Oscillazione' },
  LOW_SNR:         { icon: '🌫', color: '#8a9cc0', label: 'SNR Basso' },
  STAR_LOST:       { icon: '❌', color: '#ff5555', label: 'Stella Persa' },
  UNKNOWN:         { icon: '🌙', color: '#4d5f7a', label: 'In attesa…' },
};

function setCondition(key, iconOverride, labelOverride) {
  const cfg = CONDITION_MAP[key] || CONDITION_MAP.UNKNOWN;
  el('condition-icon').textContent = iconOverride || cfg.icon;
  el('condition-name').textContent = labelOverride || cfg.label;
  el('condition-name').style.color = cfg.color;
}

function setConditionFromName(condName, desc) {
  const cfg = CONDITION_MAP[condName] || CONDITION_MAP.UNKNOWN;
  el('condition-icon').textContent = cfg.icon;
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
  CLEAR: { icon: '🌌', color: '#4ade80', label: 'CIELO LIMPIDO' },
  HAZE:  { icon: '🌫️', color: '#fbbf24', label: 'VELATURE' },
  CLOUD: { icon: '☁️', color: '#f87171', label: 'NUVOLE' },
};

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
  const cfg = TRANSP_STATE[t.state] || { icon: '🌌', color: '#9ca3af', label: t.state || '—' };
  el('transp-icon').textContent = cfg.icon;
  el('transp-state').textContent = cfg.label;
  el('transp-state').style.color = cfg.color;
  const dpct = (t.deficit_pct != null) ? t.deficit_pct : 0;
  el('transp-index-desc').textContent = dpct > 0
    ? `−${dpct}% vs cielo limpido recente`
    : 'al livello del cielo limpido recente';
  el('transp-stars').textContent = (t.star_count != null && t.base_stars != null)
    ? `${Math.round(t.star_count)}/${Math.round(t.base_stars)}` : '—';
  el('transp-index').textContent = t.index != null ? t.index.toFixed(2) : '—';
  el('transp-filter').textContent = t.filter || '—';

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
    el('recovery-icon').textContent = '🌤️';
    stateEl.textContent = 'CIELO IN RECUPERO?';
    stateEl.style.color = '#34d399';
  } else {
    el('recovery-icon').textContent = '⏳';
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

el('dry-run-switch').addEventListener('change', async function () {
  const enabled = this.checked;
  try {
    await fetch(`${API_BASE}/config/dry_run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
    el('mode-badge').textContent = enabled ? 'MODALITÀ TEST' : 'LIVE CONTROL';
    el('mode-badge').classList.toggle('live', !enabled);
  } catch (e) {
    console.error('Errore aggiornamento dry_run:', e);
    // rollback toggle visivo
    this.checked = !enabled;
  }
});

el('ai-find-switch').addEventListener('change', async function () {
  const enabled = this.checked;
  try {
    await fetch(`${API_BASE}/config/ai_find`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
  } catch (e) {
    console.error('Errore aggiornamento ai_find:', e);
    this.checked = !enabled;
  }
});

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
  connectWS();

  // Poll status ogni 5s come fallback se il WS non manda aggiornamenti
  setInterval(fetchStatus, 5000);
});
