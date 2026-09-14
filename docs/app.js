/**
 * AgentQuant Pro Terminal v6.3 — Minimalist Controller
 * Dual-Asset Radar (SPY + QQQ) • Custom P2P Converter • Dark/Light Theme • Telegram WebApp SDK
 */

const tg = window.Telegram ? window.Telegram.WebApp : null;
let LIVE_P2P_RATE = 1518.40;

// =========================================================================
// THEME SYSTEM (Dark / Light)
// =========================================================================

function getPreferredTheme() {
  try {
    const saved = localStorage.getItem('agentquant_theme');
    if (saved === 'light' || saved === 'dark') return saved;
  } catch (e) {}
  if (tg && tg.colorScheme) return tg.colorScheme;
  return 'dark';
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const btn = document.getElementById('theme-toggle');
  if (btn) btn.textContent = theme === 'dark' ? '🌙' : '☀️';

  if (tg && tg.setHeaderColor) {
    const bg = theme === 'dark' ? '#000000' : '#F2F2F7';
    tg.setHeaderColor(bg);
    tg.setBackgroundColor(bg);
  }

  try { localStorage.setItem('agentquant_theme', theme); } catch (e) {}
  if (currentTab === 'radar') renderRadarChart();
}

function toggleTheme() {
  triggerHaptic('light');
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  applyTheme(current === 'dark' ? 'light' : 'dark');
}

// =========================================================================
// MULTI-PROVIDER LIVE P2P RATE FETCHER (Binance + CryptoCompare + CoinGecko)
// =========================================================================

async function fetchLiveBinanceRate() {
  let newRate = null;

  // Provider 1: Binance Official USDT/NGN
  try {
    const res = await fetch('https://api.binance.com/api/v3/ticker/price?symbol=USDTNGN', { cache: 'no-store' });
    if (res.ok) {
      const data = await res.json();
      if (data && data.price) {
        const p = parseFloat(data.price);
        if (!isNaN(p) && p > 500) newRate = p;
      }
    }
  } catch (e) {}

  // Provider 2: CryptoCompare USDT -> NGN
  if (!newRate) {
    try {
      const res = await fetch('https://min-api.cryptocompare.com/data/price?fsym=USDT&tsyms=NGN', { cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        if (data && data.NGN) {
          const p = parseFloat(data.NGN);
          if (!isNaN(p) && p > 500) newRate = p;
        }
      }
    } catch (e) {}
  }

  // Provider 3: CoinGecko Tether -> NGN
  if (!newRate) {
    try {
      const res = await fetch('https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=ngn', { cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        if (data && data.tether && data.tether.ngn) {
          const p = parseFloat(data.tether.ngn);
          if (!isNaN(p) && p > 500) newRate = p;
        }
      }
    } catch (e) {}
  }

  // Provider 4: Local Telemetry Endpoint (if running with webapp_server)
  if (!newRate) {
    try {
      const res = await fetch('/api/telemetry');
      if (res.ok) {
        const data = await res.json();
        if (data && data.live_p2p_rate) {
          const p = parseFloat(data.live_p2p_rate);
          if (!isNaN(p) && p > 500) newRate = p;
        }
      }
    } catch (e) {}
  }

  if (newRate) {
    LIVE_P2P_RATE = newRate;
    const subEl = document.getElementById('p2p-rate-subtitle');
    if (subEl) {
      const nowStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      subEl.textContent = `Live Market Rate: 1 USDT = ₦${newRate.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})} • ${nowStr}`;
    }
    const input = document.getElementById('p2p-custom-input');
    const curVal = input ? parseFloat(input.value) : 600;
    updateP2P(curVal);
  }
}

// =========================================================================
// APPLICATION STATE & DUAL-ASSET RADAR BUFFERS
// =========================================================================

let currentTab = 'radar';
let activeRadarAsset = 'SPY'; // 'SPY' or 'QQQ'
const navHistory = ['radar'];

let telemetryData = {
  capital: 6000.0, equity: 6000.0, buffer: 360.0,
  strategy_name: 'Dual-Asset Scalper (SPY + QQQ)',
  win_rate: '72.4%', trades_per_mo: '3.14 / mo', profit_10y: '+$6,438.11',
  spy_price: 764.29, spy_mean: 764.13, spy_dip: 758.45, spy_dist: 5.84, spy_dist_pct: 0.76,
  qqq_price: 714.88, qqq_mean: 715.44, qqq_dip: 710.30, qqq_dist: 4.58, qqq_dist_pct: 0.64,
  payout_days: 5,
};

const MAX_RADAR_POINTS = 32;
let spyHistory = [];
let qqqHistory = [];
let radarAnimId = null;
let radarPulsePhase = 0;

function pushSpyTick(price) {
  spyHistory.push(price);
  if (spyHistory.length > MAX_RADAR_POINTS) spyHistory.shift();
}

function pushQqqTick(price) {
  qqqHistory.push(price);
  if (qqqHistory.length > MAX_RADAR_POINTS) qqqHistory.shift();
}

// Seed initial historical trajectory for both SPY and QQQ
(function seedRadar() {
  const synthSpy = [-10.09, -8.70, -7.49, -5.19, -6.79, -4.30, -2.99, -1.80, -0.89, -2.50, -4.19, -2.80, -1.49, 0.91, -0.40, -1.19, -1.79, 0];
  synthSpy.forEach(d => pushSpyTick(telemetryData.spy_price + d));

  const synthQqq = [-8.50, -7.10, -6.20, -4.90, -5.40, -3.20, -2.10, -3.50, -1.80, -0.90, 0.80, -0.40, -1.20, -2.20, -0.80, 0];
  synthQqq.forEach(d => pushQqqTick(telemetryData.qqq_price + d));
})();

function switchRadarAsset(asset) {
  if (activeRadarAsset === asset) return;
  activeRadarAsset = asset;
  triggerHaptic('selection');

  document.getElementById('pill-spy')?.classList.toggle('active', asset === 'SPY');
  document.getElementById('pill-qqq')?.classList.toggle('active', asset === 'QQQ');

  document.getElementById('card-spec-spy')?.classList.toggle('highlight', asset === 'SPY');
  document.getElementById('card-spec-qqq')?.classList.toggle('highlight', asset === 'QQQ');

  renderRadarChart();
}

// =========================================================================
// TELEGRAM SDK
// =========================================================================

function initTelegram() {
  if (tg) {
    tg.ready();
    tg.expand();
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
    } else if (type === 'selection') {
      tg.HapticFeedback.selectionChanged();
    } else {
      tg.HapticFeedback.impactOccurred(type);
    }
  }
}

function handleAndroidBack() {
  triggerHaptic('light');
  if (navHistory.length > 1) {
    navHistory.pop();
    const prevTab = navHistory.pop();
    switchTab(prevTab, false);
  } else {
    if (tg) tg.close();
  }
}

// =========================================================================
// GSAP ENTRANCE & TAB SWITCHING
// =========================================================================

function initGSAPAnimations() {
  if (typeof gsap === 'undefined') return;
  gsap.from('.top-nav, .hero-widget, .segmented-control, .views-wrapper, .bottom-bar', {
    opacity: 0, y: 16, duration: 0.5, stagger: 0.06, ease: 'power3.out',
  });
  animateBalance(6000.0);
}

function animateBalance(targetValue) {
  if (typeof gsap === 'undefined') {
    const el = document.getElementById('equity-val');
    if (el) el.textContent = targetValue.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return;
  }
  const obj = { val: 0 };
  gsap.to(obj, {
    val: targetValue, duration: 0.9, ease: 'power2.out',
    onUpdate: () => {
      const el = document.getElementById('equity-val');
      if (el) el.textContent = obj.val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
  });
}

function switchTab(tabName, pushToHistory = true) {
  if (tabName === currentTab) return;
  const targetView = document.getElementById(`view-${tabName}`);
  const currentView = document.getElementById(`view-${currentTab}`);
  if (!targetView) return;

  triggerHaptic('medium');

  const tabIndexMap = { radar: 0, sentinel: 1, payouts: 2, p2p: 3 };
  const targetIndex = tabIndexMap[tabName] ?? 0;

  const slider = document.getElementById('segment-slider');
  if (slider) slider.style.transform = `translateX(${targetIndex * 100}%)`;

  document.querySelectorAll('.segment-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });

  if (typeof gsap !== 'undefined' && currentView) {
    gsap.to(currentView, {
      opacity: 0, y: -6, duration: 0.12, ease: 'power2.in',
      onComplete: () => {
        currentView.classList.remove('active');
        currentView.style.display = 'none';
        targetView.style.display = 'block';
        targetView.classList.add('active');
        gsap.fromTo(targetView,
          { opacity: 0, y: 8 },
          { opacity: 1, y: 0, duration: 0.22, ease: 'power2.out' }
        );
        if (tabName === 'radar') renderRadarChart();
        else if (tabName === 'sentinel') animateActivityRing();
      }
    });
  } else {
    if (currentView) currentView.classList.remove('active');
    targetView.classList.add('active');
    if (tabName === 'radar') renderRadarChart();
  }

  currentTab = tabName;
  if (pushToHistory) navHistory.push(tabName);
}

function setupSegmentedNav() {
  document.querySelectorAll('.segment-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      switchTab(btn.dataset.tab, true);
    });
  });
}

// =========================================================================
// LIVE RADAR CHART (Theme-Aware, Animated Beacon Loop)
// =========================================================================

function getChartColors() {
  const style = getComputedStyle(document.documentElement);
  return {
    line: style.getPropertyValue('--chart-line').trim(),
    fillTop: style.getPropertyValue('--chart-fill-top').trim(),
    fillBottom: style.getPropertyValue('--chart-fill-bottom').trim(),
    meanLine: style.getPropertyValue('--chart-mean-line').trim(),
    dipLine: style.getPropertyValue('--chart-dip-line').trim(),
    dot: style.getPropertyValue('--chart-dot').trim(),
    dotGlow: style.getPropertyValue('--chart-dot-glow').trim(),
  };
}

function renderRadarChart(pulsePhase = 0) {
  const canvas = document.getElementById('radarChart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;

  const rect = canvas.getBoundingClientRect();
  if (canvas.width !== rect.width * dpr || canvas.height !== rect.height * dpr) {
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
  }
  ctx.save();
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;
  ctx.clearRect(0, 0, w, h);

  const colors = getChartColors();

  // Pick dataset based on active asset
  const isSpy = activeRadarAsset === 'SPY';
  const history = isSpy ? spyHistory : qqqHistory;
  const curPrice = isSpy ? telemetryData.spy_price : telemetryData.qqq_price;
  const dipPrice = isSpy ? (telemetryData.spy_dip || 758.45) : (telemetryData.qqq_dip || 710.30);
  const meanPrice = isSpy ? (telemetryData.spy_mean || 764.13) : (telemetryData.qqq_mean || 715.44);

  const pricePoints = history.length >= 3 ? [...history] : [curPrice - 3, curPrice - 1, curPrice];

  const minP = Math.min(...pricePoints, dipPrice) - 1.5;
  const maxP = Math.max(...pricePoints, meanPrice) + 1.5;
  const range = Math.max(0.01, maxP - minP);

  const getX = (i) => (i / (pricePoints.length - 1)) * (w - 24) + 12;
  const getY = (p) => h - 22 - ((p - minP) / range) * (h - 42);

  // Mean Target Guideline
  const yMean = getY(meanPrice);
  ctx.save();
  ctx.strokeStyle = colors.meanLine;
  ctx.lineWidth = 0.8;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(12, yMean);
  ctx.lineTo(w - 12, yMean);
  ctx.stroke();
  ctx.restore();

  // Dip Trigger Guideline
  const yDip = getY(dipPrice);
  ctx.save();
  ctx.strokeStyle = colors.dipLine;
  ctx.lineWidth = 0.8;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(12, yDip);
  ctx.lineTo(w - 12, yDip);
  ctx.stroke();
  ctx.restore();

  // Smooth Bezier Curve Path
  const curvePath = new Path2D();
  curvePath.moveTo(getX(0), getY(pricePoints[0]));
  for (let i = 1; i < pricePoints.length; i++) {
    const px = getX(i - 1), py = getY(pricePoints[i - 1]);
    const cx = getX(i), cy = getY(pricePoints[i]);
    const mx = (px + cx) / 2;
    curvePath.bezierCurveTo(mx, py, mx, cy, cx, cy);
  }

  // Gradient Area Fill
  const areaPath = new Path2D(curvePath);
  areaPath.lineTo(getX(pricePoints.length - 1), h - 6);
  areaPath.lineTo(getX(0), h - 6);
  areaPath.closePath();

  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, colors.fillTop);
  grad.addColorStop(1, colors.fillBottom);
  ctx.fillStyle = grad;
  ctx.fill(areaPath);

  // Line Stroke
  ctx.strokeStyle = colors.line;
  ctx.lineWidth = 1.8;
  ctx.lineCap = 'round';
  ctx.stroke(curvePath);

  // Animated Beacon Ripple Ring on Latest Point
  const lastX = getX(pricePoints.length - 1);
  const lastY = getY(pricePoints[pricePoints.length - 1]);

  const rippleR = 3.5 + Math.sin(pulsePhase) * 5.5;
  const rippleAlpha = Math.max(0, 0.45 * (1 - (rippleR - 3.5) / 5.5));
  ctx.save();
  ctx.strokeStyle = colors.line;
  ctx.globalAlpha = rippleAlpha;
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.arc(lastX, lastY, Math.max(3.5, rippleR), 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();

  // Core Price Dot
  ctx.save();
  ctx.shadowColor = colors.dotGlow;
  ctx.shadowBlur = 8;
  ctx.fillStyle = colors.dot;
  ctx.beginPath();
  ctx.arc(lastX, lastY, 3.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  ctx.restore();

  // Dynamic Badges
  const badgeTarget = document.getElementById('badge-target');
  const badgeEntry = document.getElementById('badge-entry');
  if (badgeTarget) badgeTarget.textContent = `${activeRadarAsset} 5d Target: $${meanPrice.toFixed(2)}`;
  if (badgeEntry) badgeEntry.textContent = `${activeRadarAsset} Dip Trigger: $${dipPrice.toFixed(2)}`;
}

// Continuous Radar Animation Loop (Pulsing Ripple Beacon)
function startRadarLoop() {
  function loop() {
    if (currentTab === 'radar') {
      radarPulsePhase = (radarPulsePhase + 0.06) % (Math.PI * 2);
      renderRadarChart(radarPulsePhase);
    }
    radarAnimId = requestAnimationFrame(loop);
  }
  if (radarAnimId) cancelAnimationFrame(radarAnimId);
  radarAnimId = requestAnimationFrame(loop);
}

// Real-Time Radar Micro-Drift for BOTH SPY and QQQ
function tickRadarMicroDrift() {
  // 1. SPY micro-jitter
  const lastSpy = spyHistory.length > 0 ? spyHistory[spyHistory.length - 1] : telemetryData.spy_price;
  const meanSpy = telemetryData.spy_mean || 764.13;
  const driftSpy = (meanSpy - lastSpy) * 0.025 + (Math.random() - 0.49) * 0.10;
  const newSpy = Math.round((lastSpy + driftSpy) * 100) / 100;
  pushSpyTick(newSpy);
  telemetryData.spy_price = newSpy;
  telemetryData.spy_dist = Math.max(0, newSpy - (telemetryData.spy_dip || 758.45));
  telemetryData.spy_dist_pct = (telemetryData.spy_dist / newSpy) * 100;

  // 2. QQQ micro-jitter
  const lastQqq = qqqHistory.length > 0 ? qqqHistory[qqqHistory.length - 1] : telemetryData.qqq_price;
  const meanQqq = telemetryData.qqq_mean || 715.44;
  const driftQqq = (meanQqq - lastQqq) * 0.025 + (Math.random() - 0.49) * 0.12;
  const newQqq = Math.round((lastQqq + driftQqq) * 100) / 100;
  pushQqqTick(newQqq);
  telemetryData.qqq_price = newQqq;
  telemetryData.qqq_dist = Math.max(0, newQqq - (telemetryData.qqq_dip || 710.30));
  telemetryData.qqq_dist_pct = (telemetryData.qqq_dist / newQqq) * 100;

  // Update Matrix Readout Cards
  updateMatrixUI();
}

function updateMatrixUI() {
  const spyEl = document.getElementById('spy-price');
  const spyDistEl = document.getElementById('spy-dip-dist');
  const spyTargetEl = document.getElementById('spy-dip-target');

  const qqqEl = document.getElementById('qqq-price');
  const qqqDistEl = document.getElementById('qqq-dip-dist');
  const qqqTargetEl = document.getElementById('qqq-dip-target');

  if (spyEl) spyEl.textContent = `$${telemetryData.spy_price.toFixed(2)}`;
  if (spyDistEl) spyDistEl.textContent = `+$${telemetryData.spy_dist.toFixed(2)} (+${telemetryData.spy_dist_pct.toFixed(2)}%)`;
  if (spyTargetEl) spyTargetEl.textContent = `$${(telemetryData.spy_dip || 758.45).toFixed(2)}`;

  if (qqqEl) qqqEl.textContent = `$${telemetryData.qqq_price.toFixed(2)}`;
  if (qqqDistEl) qqqDistEl.textContent = `+$${telemetryData.qqq_dist.toFixed(2)} (+${telemetryData.qqq_dist_pct.toFixed(2)}%)`;
  if (qqqTargetEl) qqqTargetEl.textContent = `$${(telemetryData.qqq_dip || 710.30).toFixed(2)}`;
}

// =========================================================================
// REAL-TIME SESSION COUNTDOWN CLOCK (WAT Timezone)
// =========================================================================

function updateSessionCountdown() {
  const el = document.getElementById('session-countdown');
  if (!el) return;

  const now = new Date();
  const utcMs = now.getTime() + (now.getTimezoneOffset() * 60000);
  const watDate = new Date(utcMs + (1 * 3600000)); // WAT is UTC+1

  const day = watDate.getDay(); // 0 = Sun, 6 = Sat
  const hours = watDate.getHours();
  const mins = watDate.getMinutes();
  const secs = watDate.getSeconds();
  const currentMins = hours * 60 + mins;

  // US Regular Trading: 14:30 - 21:00 WAT (870 to 1260 mins)
  // US Pre-Market: 09:00 - 14:30 WAT (540 to 870 mins)
  const isWeekend = (day === 0) || (day === 6) || (day === 5 && currentMins >= 1260);

  if (isWeekend) {
    el.innerHTML = `Weekend • Markets Closed (Opens Monday 2:30 PM WAT)`;
    return;
  }

  if (currentMins >= 870 && currentMins < 1260) {
    const diffSecs = (1260 * 60) - (currentMins * 60 + secs);
    const h = Math.floor(diffSecs / 3600);
    const m = Math.floor((diffSecs % 3600) / 60);
    const s = diffSecs % 60;
    el.innerHTML = `🟢 Regular Session • Closes in ${h}h ${m}m ${s}s (9:00 PM WAT)`;
  } else if (currentMins >= 540 && currentMins < 870) {
    const diffSecs = (870 * 60) - (currentMins * 60 + secs);
    const h = Math.floor(diffSecs / 3600);
    const m = Math.floor((diffSecs % 3600) / 60);
    const s = diffSecs % 60;
    el.innerHTML = `🟡 Pre-Market • Opens in ${h}h ${m}m ${s}s (2:30 PM WAT)`;
  } else {
    el.innerHTML = `⚪ Overnight Session • Pre-Market Opens at 9:00 AM WAT`;
  }
}

// =========================================================================
// ACTIVITY RING
// =========================================================================

function animateActivityRing() {
  const ring = document.getElementById('ring-guard');
  if (!ring) return;
  const circumference = 427.26;
  ring.style.strokeDasharray = circumference;
  if (typeof gsap !== 'undefined') {
    gsap.fromTo(ring,
      { strokeDashoffset: circumference },
      { strokeDashoffset: 0, duration: 0.9, ease: 'power2.out' }
    );
  } else {
    ring.style.strokeDashoffset = 0;
  }
}

// =========================================================================
// P2P CALCULATOR (Dual-Mode: Slider + Custom Number Input)
// =========================================================================

function setupP2PCalculator() {
  const slider = document.getElementById('p2p-slider');
  const customInput = document.getElementById('p2p-custom-input');

  if (slider) {
    slider.addEventListener('input', (e) => {
      const val = parseFloat(e.target.value);
      updateP2P(val, false);
      highlightChip(val);
      triggerHaptic('light');
    });
  }

  if (customInput) {
    customInput.addEventListener('input', (e) => {
      let val = parseFloat(e.target.value);
      if (isNaN(val) || val < 0) val = 0;
      updateP2P(val, true);
      if (slider && val >= 50 && val <= 3000) slider.value = val;
      highlightChip(val);
    });

    customInput.addEventListener('focus', () => {
      highlightChip('custom');
    });
  }
}

function focusCustomInput() {
  triggerHaptic('medium');
  const input = document.getElementById('p2p-custom-input');
  if (input) {
    input.focus();
    input.select();
  }
  highlightChip('custom');
}

function highlightChip(val) {
  document.querySelectorAll('.chip-preset').forEach(chip => {
    if (val === 'custom') {
      chip.classList.toggle('active', chip.id === 'chip-custom');
    } else {
      chip.classList.toggle('active', chip.textContent.includes(`$${val}`) && chip.id !== 'chip-custom');
    }
  });
}

function setSlider(val) {
  const slider = document.getElementById('p2p-slider');
  const customInput = document.getElementById('p2p-custom-input');
  if (slider && val <= 3000) slider.value = val;
  if (customInput) customInput.value = val;
  updateP2P(val, false);
  highlightChip(val);
  triggerHaptic('medium');
}

function updateP2P(usd, fromInput = false) {
  const customInput = document.getElementById('p2p-custom-input');
  const nairaEl = document.getElementById('p2p-naira-display');

  if (!fromInput && customInput && document.activeElement !== customInput) {
    customInput.value = usd;
  }

  const naira = usd * LIVE_P2P_RATE;
  if (nairaEl) nairaEl.textContent = `₦${Math.round(naira).toLocaleString()}`;
}

function copyWallet() {
  const addressEl = document.getElementById('wallet-address-display');
  const address = addressEl ? addressEl.textContent.trim() : '';
  const hint = document.getElementById('copy-hint');

  if (!address || address.includes('NO WALLET') || address.includes('TX8aKq9Z')) {
    triggerHaptic('notification');
    if (hint) {
      hint.textContent = '⚠️ Set wallet first (/setwallet)';
      hint.style.color = 'var(--accent-amber)';
      setTimeout(() => { hint.textContent = 'Tap to Copy'; hint.style.color = 'var(--accent-cyan)'; }, 3500);
    }
    const msg = "⚠️ No Binance TRC20 wallet linked yet!\n\nOpen your chat with @NextGenQuantBot and type:\n/setwallet <YOUR_BINANCE_TRC20_ADDRESS>\n\nto safely connect your payout destination.";
    if (tg && tg.showAlert) tg.showAlert(msg);
    else alert(msg);
    return;
  }

  if (navigator.clipboard) navigator.clipboard.writeText(address);
  triggerHaptic('notification');
  if (hint) {
    hint.textContent = 'Copied!';
    hint.style.color = 'var(--accent-green)';
    setTimeout(() => { hint.textContent = 'Tap to Copy'; hint.style.color = 'var(--accent-cyan)'; }, 2000);
  }
}

function toggleAccordion(id) {
  triggerHaptic('light');
  const el = document.getElementById(id);
  if (el) el.classList.toggle('expanded');
}

// =========================================================================
// URL PARAMETERS & LIVE TELEMETRY SYNC
// =========================================================================

function parseQueryParams() {
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.has('rate')) {
      const r = parseFloat(params.get('rate'));
      if (!isNaN(r) && r > 500) {
        LIVE_P2P_RATE = r;
        const subEl = document.getElementById('p2p-rate-subtitle');
        if (subEl) subEl.textContent = `Live Market Rate: 1 USDT = ₦${r.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
      }
    }
    if (params.has('wallet')) {
      const w = params.get('wallet').trim();
      if (w && w.startsWith('T') && w.length === 34) {
        const walletEl = document.getElementById('wallet-address-display');
        if (walletEl) walletEl.textContent = w;
        localStorage.setItem('agentquant_trc20_wallet', w);
      }
    }
    if (params.has('spy')) {
      const s = parseFloat(params.get('spy'));
      if (!isNaN(s) && s > 100) {
        telemetryData.spy_price = s;
        pushSpyTick(s);
      }
    }
    if (params.has('qqq')) {
      const q = parseFloat(params.get('qqq'));
      if (!isNaN(q) && q > 100) {
        telemetryData.qqq_price = q;
        pushQqqTick(q);
      }
    }
    if (params.has('cap')) {
      const c = parseFloat(params.get('cap'));
      if (!isNaN(c) && c > 0) telemetryData.capital = c;
    }
  } catch (e) {}
}

async function syncTelemetry() {
  try {
    const res = await fetch('/api/telemetry');
    if (!res.ok) return;
    const data = await res.json();
    telemetryData = { ...telemetryData, ...data };

    if (data.spy_price) pushSpyTick(data.spy_price);
    if (data.qqq_price) pushQqqTick(data.qqq_price);

    const balEl = document.getElementById('balance-val');
    const buffEl = document.getElementById('buffer-val');
    if (balEl) balEl.textContent = `$${data.capital.toFixed(2)}`;
    if (buffEl) buffEl.textContent = `$${data.buffer.toFixed(2)}`;

    updateMatrixUI();

    if (data.live_p2p_rate && !isNaN(data.live_p2p_rate)) {
      LIVE_P2P_RATE = parseFloat(data.live_p2p_rate);
      const subEl = document.getElementById('p2p-rate-subtitle');
      if (subEl) subEl.textContent = `Live Market Rate: 1 USDT = ₦${LIVE_P2P_RATE.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
      const input = document.getElementById('p2p-custom-input');
      const curVal = input ? parseFloat(input.value) : 600;
      updateP2P(curVal);
    }

    if (data.wallet_address) {
      const walletEl = document.getElementById('wallet-address-display');
      if (walletEl) walletEl.textContent = data.wallet_address;
      try { localStorage.setItem('agentquant_trc20_wallet', data.wallet_address); } catch (e) {}
    }

    if (currentTab === 'radar') renderRadarChart();
  } catch (e) {
    // Offline fallback
  }
}

// =========================================================================
// INITIALIZATION
// =========================================================================

window.addEventListener('DOMContentLoaded', () => {
  // 1. Apply theme
  applyTheme(getPreferredTheme());

  // 2. Parse URL params
  parseQueryParams();

  // 3. Init UI and SDK
  initTelegram();
  setupSegmentedNav();
  setupP2PCalculator();
  initGSAPAnimations();

  // 4. Initial Matrix & Radar Render
  updateMatrixUI();
  startRadarLoop();
  updateSessionCountdown();
  setInterval(updateSessionCountdown, 1000);
  setInterval(tickRadarMicroDrift, 3000);

  // 5. Hydrate saved wallet
  try {
    const saved = localStorage.getItem('agentquant_trc20_wallet');
    const el = document.getElementById('wallet-address-display');
    if (saved && el && !saved.includes('NO WALLET') && !saved.includes('TX8aKq9Z')) {
      el.textContent = saved;
    }
  } catch (e) {}

  // 6. Live Rates polling (every 30s)
  fetchLiveBinanceRate();
  setInterval(fetchLiveBinanceRate, 30000);

  // 7. Radar manual refresh button
  const btnRefresh = document.getElementById('btn-refresh-radar');
  if (btnRefresh) {
    btnRefresh.addEventListener('click', () => {
      triggerHaptic('medium');
      fetchLiveBinanceRate();
      syncTelemetry();
    });
  }

  // 8. Telemetry polling (every 30s)
  syncTelemetry();
  setInterval(syncTelemetry, 30000);
});

window.addEventListener('resize', () => {
  if (currentTab === 'radar') renderRadarChart();
});
