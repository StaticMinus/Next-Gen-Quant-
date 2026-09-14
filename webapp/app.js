/**
 * AgentQuant Pro Terminal — Telegram Mini App (v5.2)
 * Full Android Hardware Back Button Hook & Haptic Feedback Engine
 */

const tg = window.Telegram ? window.Telegram.WebApp : null;
const LIVE_P2P_RATE = 1665.0;

// State
let currentTab = 'radar';
const navHistory = ['radar'];
let telemetryData = {
  capital: 6000.0,
  equity: 6000.0,
  buffer: 360.0,
  spy_price: 764.29,
  spy_mean: 764.13,
  spy_dip: 758.45,
  spy_dist: 5.84,
  qqq_price: 714.88,
  qqq_mean: 715.44,
  qqq_dip: 704.16,
  payout_days: 5,
};

// =========================================================================
// 1. TELEGRAM WEBAPP SDK INITIALIZATION & ANDROID BACK BUTTON HOOK
// =========================================================================

function initTelegram() {
  if (tg) {
    tg.ready();
    tg.expand();

    // Configure header color to dark OLED
    if (tg.setHeaderColor) {
      tg.setHeaderColor('#07090e');
      tg.setBackgroundColor('#07090e');
    }

    // Android Hardware / Swipe Back Button Integration
    if (tg.BackButton) {
      tg.BackButton.show();
      tg.BackButton.onClick(handleAndroidBack);
    }
  }
}

function triggerHaptic(type = 'medium') {
  if (tg && tg.HapticFeedback) {
    if (type === 'notification') {
      tg.HapticFeedback.notificationOccurred('success');
    } else {
      tg.HapticFeedback.impactOccurred(type);
    }
  }
}

function handleAndroidBack() {
  triggerHaptic('light');
  if (navHistory.length > 1) {
    navHistory.pop(); // remove current
    const prevTab = navHistory.pop(); // get previous
    switchTab(prevTab, false);
  } else {
    // Already at root tab (radar), close WebApp
    if (tg) tg.close();
  }
}

// =========================================================================
// 2. TAB NAVIGATION SYSTEM
// =========================================================================

function switchTab(tabName, pushToHistory = true) {
  if (!document.getElementById(`tab-${tabName}`)) return;
  triggerHaptic('medium');

  // Update tabs
  document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.tab === tabName);
  });

  // Update panels
  document.querySelectorAll('.tab-content').forEach(panel => {
    panel.classList.toggle('active', panel.id === `tab-${tabName}`);
  });

  currentTab = tabName;
  if (pushToHistory) {
    navHistory.push(tabName);
  }

  // If radar tab, redraw canvas chart
  if (tabName === 'radar') {
    requestAnimationFrame(renderRadarChart);
  }
}

function setupNavTabs() {
  document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const targetTab = tab.dataset.tab;
      if (targetTab !== currentTab) {
        switchTab(targetTab, true);
      }
    });
  });

  // Overview quick button in footer
  const btnOverview = document.getElementById('btn-quick-overview');
  if (btnOverview) {
    btnOverview.addEventListener('click', () => {
      triggerHaptic('medium');
      if (tg) {
        tg.sendData(JSON.stringify({ action: 'cmd_overview' }));
        tg.close();
      } else {
        alert("In Telegram, this returns directly to the In-Chat Terminal.");
      }
    });
  }

  // Refresh radar button
  const btnRefresh = document.getElementById('btn-refresh-radar');
  if (btnRefresh) {
    btnRefresh.addEventListener('click', () => {
      triggerHaptic('light');
      btnRefresh.textContent = '⏳ Scanning...';
      fetchTelemetry().then(() => {
        btnRefresh.textContent = '⚡ Refresh';
      });
    });
  }

  // Killswitch
  const btnKill = document.getElementById('btn-killswitch');
  if (btnKill) {
    btnKill.addEventListener('click', () => {
      triggerHaptic('notification');
      const confirmed = confirm("⚠️ CONFIRM EMERGENCY KILL SWITCH:\nHalt all automated trading and preserve 100% Cash?");
      if (confirmed) {
        if (tg) {
          tg.sendData(JSON.stringify({ action: 'cmd_execute_kill_switch' }));
        }
        alert("🛑 EMERGENCY KILL SWITCH ACTIVATED.\nAccount locked in 100% Cash.");
      }
    });
  }
}

// =========================================================================
// 3. INTERACTIVE CANVAS CANDLESTICK & DIP RADAR CHART
// =========================================================================

function renderRadarChart() {
  const canvas = document.getElementById('radar-chart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  
  // Set real pixel resolution for high DPI displays
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const width = rect.width;
  const height = rect.height;

  // Clear
  ctx.clearRect(0, 0, width, height);

  // Simulated 15-day price series around SPY
  const days = 15;
  const basePrice = 756.0;
  const prices = [
    752.4, 754.1, 755.8, 757.2, 759.0,
    758.3, 761.5, 760.2, 763.4, 762.1,
    765.8, 764.0, 766.2, 765.1, telemetryData.spy_price
  ];

  // Calculate 5-day moving average and 1.25 sigma lower band
  const means = [];
  const lowerBands = [];
  for (let i = 0; i < prices.length; i++) {
    const start = Math.max(0, i - 4);
    const slice = prices.slice(start, i + 1);
    const mean = slice.reduce((a, b) => a + b, 0) / slice.length;
    means.push(mean);
    // standard deviation
    const variance = slice.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / slice.length;
    const std = Math.sqrt(variance) || 1.8;
    lowerBands.push(mean - 1.25 * std);
  }

  // Bounds
  const allVals = [...prices, ...means, ...lowerBands];
  const minVal = Math.min(...allVals) - 1.5;
  const maxVal = Math.max(...allVals) + 1.5;

  const padX = 25;
  const padY = 20;
  const plotW = width - padX * 2;
  const plotH = height - padY * 2;

  const getX = (idx) => padX + (idx / (days - 1)) * plotW;
  const getY = (val) => padY + plotH - ((val - minVal) / (maxVal - minVal)) * plotH;

  // 1. Draw horizontal grid lines
  ctx.strokeStyle = 'rgba(51, 65, 85, 0.25)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = padY + (plotH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(padX, y);
    ctx.lineTo(width - padX, y);
    ctx.stroke();
  }

  // 2. Shaded Dip Buy Zone (between lowerBand and mean)
  ctx.fillStyle = 'rgba(16, 185, 129, 0.08)';
  ctx.beginPath();
  for (let i = 0; i < days; i++) {
    const x = getX(i);
    const y = getY(means[i]);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  for (let i = days - 1; i >= 0; i--) {
    const x = getX(i);
    const y = getY(lowerBands[i]);
    ctx.lineTo(x, y);
  }
  ctx.closePath();
  ctx.fill();

  // 3. Draw 5-Day Mean Line (Amber neon dashed)
  ctx.strokeStyle = '#f59e0b';
  ctx.lineWidth = 2;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  for (let i = 0; i < days; i++) {
    const x = getX(i);
    const y = getY(means[i]);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
  ctx.setLineDash([]); // reset

  // 4. Draw 1.25σ Lower Band (Emerald neon solid)
  ctx.strokeStyle = '#10b981';
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let i = 0; i < days; i++) {
    const x = getX(i);
    const y = getY(lowerBands[i]);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // 5. Draw Price Line (Bright white / cyan gradient)
  ctx.strokeStyle = '#00f0ff';
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  for (let i = 0; i < days; i++) {
    const x = getX(i);
    const y = getY(prices[i]);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // 6. Draw dots on price line
  for (let i = 0; i < days; i++) {
    const x = getX(i);
    const y = getY(prices[i]);
    const isLatest = i === days - 1;
    ctx.fillStyle = isLatest ? '#00f0ff' : '#94a3b8';
    ctx.beginPath();
    ctx.arc(x, y, isLatest ? 5 : 2.5, 0, Math.PI * 2);
    ctx.fill();

    if (isLatest) {
      // Latest price badge
      ctx.fillStyle = '#00f0ff';
      ctx.font = 'bold 11px JetBrains Mono';
      ctx.textAlign = 'right';
      ctx.fillText(`$${prices[i].toFixed(2)}`, x - 8, y - 8);
    }
  }
}

// =========================================================================
// 4. INTERACTIVE BINANCE P2P NAIRA CONVERTER
// =========================================================================

function setupP2PConverter() {
  const input = document.getElementById('usdt-input');
  const slider = document.getElementById('usdt-slider');
  const output = document.getElementById('calc-naira-output');

  function updateNaira(val) {
    const amount = parseFloat(val) || 0;
    const naira = amount * LIVE_P2P_RATE;
    output.textContent = `₦${naira.toLocaleString('en-US', { maximumFractionDigits: 0 })} NGN`;
  }

  if (input && slider && output) {
    input.addEventListener('input', (e) => {
      const val = parseFloat(e.target.value) || 0;
      slider.value = val;
      updateNaira(val);
    });

    slider.addEventListener('input', (e) => {
      triggerHaptic('light');
      const val = parseFloat(e.target.value) || 0;
      input.value = val;
      updateNaira(val);
    });
  }
}

// =========================================================================
// 5. LIVE TELEMETRY INGESTION & UI BINDINGS
// =========================================================================

async function fetchTelemetry() {
  try {
    const res = await fetch('/api/telemetry');
    if (res.ok) {
      const data = await res.json();
      telemetryData = { ...telemetryData, ...data };
      updateUI();
    }
  } catch (e) {
    // If running offline/static demo, use mock defaults
    updateUI();
  }
}

function updateUI() {
  // Balance & Equity
  const eqEl = document.getElementById('equity-val');
  const balEl = document.getElementById('balance-val');
  const bufEl = document.getElementById('buffer-val');
  const nEl = document.getElementById('naira-val');

  if (eqEl) eqEl.textContent = `$${telemetryData.equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
  if (balEl) balEl.textContent = `$${telemetryData.capital.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
  if (bufEl) bufEl.textContent = `$${telemetryData.buffer.toFixed(2)}`;
  if (nEl) {
    const nVal = telemetryData.equity * LIVE_P2P_RATE;
    nEl.textContent = `~₦${nVal.toLocaleString('en-US', { maximumFractionDigits: 0 })} NGN`;
  }

  // SPY & QQQ
  const spyPrice = document.getElementById('spy-price');
  const spyMean = document.getElementById('spy-mean');
  const spyDip = document.getElementById('spy-dip');
  const spyDist = document.getElementById('spy-dist');

  if (spyPrice) spyPrice.textContent = `$${telemetryData.spy_price.toFixed(2)}`;
  if (spyMean) spyMean.textContent = `$${telemetryData.spy_mean.toFixed(2)}`;
  if (spyDip) spyDip.textContent = `$${telemetryData.spy_dip.toFixed(2)}`;
  if (spyDist) {
    const d = telemetryData.spy_price - telemetryData.spy_dip;
    const pct = (d / telemetryData.spy_price) * 100;
    spyDist.textContent = `+$${d.toFixed(2)} (${pct.toFixed(2)}%)`;
  }

  renderRadarChart();
}

// =========================================================================
// 6. INITIALIZATION
// =========================================================================

document.addEventListener('DOMContentLoaded', () => {
  initTelegram();
  setupNavTabs();
  setupP2PConverter();
  fetchTelemetry();
  setInterval(fetchTelemetry, 25000);
});
