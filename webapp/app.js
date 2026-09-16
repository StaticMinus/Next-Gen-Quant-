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
let activeRadarAsset = 'GLD'; // 'GLD', 'QQQ', 'SPY', 'AAPL', 'NVDA', 'MSFT', 'META'
let radarAnimId = null;
let radarPulsePhase = 0;
const navHistory = ['radar'];

const ASSETS_LIST = ['GLD', 'QQQ', 'SPY', 'AAPL', 'NVDA', 'MSFT', 'META'];

let telemetryData = {
  capital: 6000.0, equity: 5997.47, buffer: 360.0, daily_buffer: 180.0,
  strategy_name: '7-Asset Quantitative Opportunity Engine',
  gld_price: 4332.46, gld_mean: 4340.00, gld_dip: 4330.00, gld_dist: 2.26, gld_dist_pct: 0.05,
  qqq_price: 704.54, qqq_mean: 707.20, qqq_dip: 704.68, qqq_dist: 0.00, qqq_dist_pct: 0.00,
  spy_price: 764.29, spy_mean: 764.13, spy_dip: 758.45, spy_dist: 5.84, spy_dist_pct: 0.76,
  aapl_price: 331.34, aapl_mean: 330.50, aapl_dip: 318.50, aapl_dist: 12.84, aapl_dist_pct: 3.90,
  nvda_price: 212.17, nvda_mean: 212.00, nvda_dip: 210.27, nvda_dist: 1.90, nvda_dist_pct: 0.90,
  msft_price: 495.20, msft_mean: 494.80, msft_dip: 486.50, msft_dist: 8.70, msft_dist_pct: 1.75,
  active_positions: [
    {
      position_id: 3069593,
      symbol_id: 41,
      symbol_name: 'XAUUSD',
      display_name: 'Spot Gold',
      trade_side: 'BUY',
      lots: 0.01,
      entry_price: 4334.99,
      current_price: 4272.89,
      take_profit: 4443.38,
      stop_loss: 4204.95,
      floating_pnl: -62.10
    },
    {
      position_id: 3071210,
      symbol_id: 112,
      symbol_name: 'NDX100',
      display_name: 'Nasdaq 100 Index',
      trade_side: 'BUY',
      lots: 0.1,
      entry_price: 29118.12,
      current_price: 28966.02,
      take_profit: 29552.37,
      stop_loss: 28242.17,
      floating_pnl: -15.21
    }
  ],
  payout_days: 5,
};

const MAX_RADAR_POINTS = 32;
const assetHistories = {
  GLD: [], QQQ: [], SPY: [], AAPL: [], NVDA: [], MSFT: [], META: []
};

function pushAssetTick(asset, price) {
  if (!assetHistories[asset]) assetHistories[asset] = [];
  assetHistories[asset].push(price);
  if (assetHistories[asset].length > MAX_RADAR_POINTS) assetHistories[asset].shift();
}

// Seed initial historical trajectory for all 7 assets
(function seedRadar() {
  const synthOffsets = [-1.5, -1.2, -0.9, -0.6, -0.8, -0.4, -0.2, 0.3, -0.1, -0.3, 0];
  ASSETS_LIST.forEach(t => {
    const p = telemetryData[`${t.toLowerCase()}_price`] || 500;
    synthOffsets.forEach(off => pushAssetTick(t, p + (off * (p * 0.003))));
  });
})();

function switchRadarAsset(asset) {
  if (!ASSETS_LIST.includes(asset)) return;
  activeRadarAsset = asset;
  triggerHaptic('selection');

  ASSETS_LIST.forEach(t => {
    document.getElementById(`pill-${t.toLowerCase()}`)?.classList.toggle('active', t === asset);
    document.getElementById(`card-spec-${t.toLowerCase()}`)?.classList.toggle('highlight', t === asset);
  });

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

  // Dynamic 7-Asset Selection
  const assetKey = activeRadarAsset.toLowerCase();
  const history = assetHistories[activeRadarAsset] || [];
  const curPrice = telemetryData[`${assetKey}_price`] || 500;
  const dipPrice = telemetryData[`${assetKey}_dip`] || (curPrice * 0.985);
  const meanPrice = telemetryData[`${assetKey}_mean`] || (curPrice * 1.015);
  const targetPrice = activeRadarAsset === 'GLD' ? 4443.38 : meanPrice;

  const pricePoints = history.length >= 3 ? [...history] : [curPrice * 0.997, curPrice * 0.999, curPrice];

  const minP = Math.min(...pricePoints, dipPrice) * 0.998;
  const maxP = Math.max(...pricePoints, targetPrice) * 1.002;
  const range = Math.max(0.01, maxP - minP);

  const getX = (i) => (i / (pricePoints.length - 1)) * (w - 24) + 12;
  const getY = (p) => h - 22 - ((p - minP) / range) * (h - 42);

  // Mean / Target Guideline
  const yTarget = getY(targetPrice);
  ctx.save();
  ctx.strokeStyle = colors.meanLine;
  ctx.lineWidth = 0.8;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(12, yTarget);
  ctx.lineTo(w - 12, yTarget);
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
  if (badgeTarget) {
    badgeTarget.textContent = activeRadarAsset === 'GLD'
      ? `GLD Profit Goal: $4,443.38`
      : `${activeRadarAsset} Target: $${meanPrice.toFixed(2)}`;
  }
  if (badgeEntry) {
    badgeEntry.textContent = activeRadarAsset === 'GLD'
      ? `GLD Bought at: $4,334.99`
      : `${activeRadarAsset} Dip Trigger: $${dipPrice.toFixed(2)}`;
  }
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

// Real-Time Radar Micro-Drift for all 7 assets
function tickRadarMicroDrift() {
  ASSETS_LIST.forEach(asset => {
    const key = asset.toLowerCase();
    const history = assetHistories[asset];
    const lastPrice = history && history.length > 0 ? history[history.length - 1] : (telemetryData[`${key}_price`] || 100);
    const meanPrice = telemetryData[`${key}_mean`] || lastPrice;
    const dipPrice = telemetryData[`${key}_dip`] || (meanPrice * 0.985);

    // Natural subtle price jitter with soft mean-reversion
    const jitterScale = lastPrice > 1000 ? 0.25 : (lastPrice > 300 ? 0.12 : 0.08);
    const drift = (meanPrice - lastPrice) * 0.02 + (Math.random() - 0.49) * jitterScale;
    const newPrice = Math.round((lastPrice + drift) * 100) / 100;

    pushAssetTick(asset, newPrice);
    telemetryData[`${key}_price`] = newPrice;
    telemetryData[`${key}_dist`] = Math.max(0, newPrice - dipPrice);
    telemetryData[`${key}_dist_pct`] = (telemetryData[`${key}_dist`] / newPrice) * 100;
  });

  // Update Matrix Readout Cards and Active Trades Card
  updateMatrixUI();
  updateActiveTradesUI();
}

function updateActiveTradesUI() {
  const container = document.getElementById('trades-container');
  const chipEl = document.getElementById('trades-count-text');
  const heroChip = document.getElementById('hero-chip');
  const activeList = telemetryData.active_positions || [];
  
  if (!container) return;
  
  if (activeList.length === 0) {
    if (chipEl) chipEl.textContent = '0 POSITIONS • 100% CASH';
    if (heroChip) {
      heroChip.innerHTML = '<span class="chip-dot"></span><span>100% CASH</span>';
      heroChip.className = 'apple-chip chip-emerald';
    }
    container.innerHTML = `
      <div class="empty-trades-state" style="padding: 24px; text-align: center; color: var(--text-secondary);">
        <div style="font-size: 32px; margin-bottom: 8px;">🟢</div>
        <div style="font-weight: 600; font-size: 15px; color: var(--text-primary); margin-bottom: 4px;">All Clear — 100% in Cash</div>
        <div style="font-size: 13px; line-height: 1.4;">Automated bot is scanning for market dips. Zero open exposure right now.</div>
      </div>
    `;
    return;
  }
  
  const totalCount = activeList.length;
  if (chipEl) chipEl.textContent = `${totalCount} POSITION${totalCount > 1 ? 'S' : ''} OPEN`;
  if (heroChip) {
    heroChip.innerHTML = `<span class="chip-dot"></span><span>${totalCount} ACTIVE TRADE${totalCount > 1 ? 'S' : ''}</span>`;
    heroChip.className = 'apple-chip chip-amber';
  }
  
  let html = '';
  activeList.forEach(pos => {
    const sym = (pos.symbol_name || pos.symbolName || 'XAUUSD').toUpperCase();
    const dname = pos.display_name || (sym === 'XAUUSD' ? 'Spot Gold' : (sym === 'NDX100' ? 'Nasdaq 100 Index' : sym));
    const posId = pos.position_id || pos.positionId;
    const side = pos.trade_side || pos.tradeSide || 'BUY';
    const lots = pos.lots || 0.01;
    const entry = Number(pos.entry_price || pos.entryPrice || 0).toFixed(2);
    const curr = Number(pos.current_price || pos.entry_price || entry).toFixed(2);
    const pnl = Number(pos.floating_pnl !== undefined ? pos.floating_pnl : (pos.profit || 0));
    const pnlPrefix = pnl >= 0 ? '+$' : '-$';
    const pnlClass = pnl >= 0 ? 'val-green' : 'val-red';
    const icon = (sym.includes('XAU') || sym.includes('GOLD')) ? '🟡' : (sym.includes('NDX') ? '⚡' : '📈');
    const tpText = pos.take_profit ? `$${Number(pos.take_profit).toFixed(2)}` : (pos.takeProfit ? `$${Number(pos.takeProfit).toFixed(2)}` : 'N/A');
    const slText = pos.stop_loss ? `$${Number(pos.stop_loss).toFixed(2)}` : (pos.stopLoss ? `$${Number(pos.stopLoss).toFixed(2)}` : 'Protected');
    
    html += `
      <div class="trade-item-card" id="trade-item-${posId}" style="margin-bottom: 14px; border: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.02); border-radius: 14px; padding: 14px;">
        <div class="trade-item-header" style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
          <div class="trade-sym-badge" style="display: flex; gap: 10px; align-items: center;">
            <span class="trade-icon" style="font-size: 22px;">${icon}</span>
            <div>
              <div class="trade-sym-title" style="font-weight: 700; font-size: 15px; color: var(--text-primary);">${dname} (${sym})</div>
              <div class="trade-sym-sub" style="font-size: 12px; color: var(--text-secondary);">Trade #${posId} • ${lots} lot • ${side}</div>
            </div>
          </div>
          <div class="trade-pnl-block" style="text-align: right;">
            <span class="trade-pnl-val ${pnlClass}" style="font-weight: 700; font-size: 15px; display: block;">${pnlPrefix}${Math.abs(pnl).toFixed(2)} USD</span>
            <span class="trade-pnl-sub" style="font-size: 11px; color: var(--text-secondary);">${pnl >= 0 ? 'in profit!' : 'market wiggle'}</span>
          </div>
        </div>

        <div class="trade-details-grid" style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; background: rgba(0,0,0,0.15); padding: 10px; border-radius: 10px; margin-bottom: 12px;">
          <div class="trade-grid-cell">
            <span class="cell-lbl" style="font-size: 11px; color: var(--text-secondary); display: block;">Bought at</span>
            <span class="cell-val font-mono" style="font-size: 13px; font-weight: 600;">$${entry}</span>
          </div>
          <div class="trade-grid-cell">
            <span class="cell-lbl" style="font-size: 11px; color: var(--text-secondary); display: block;">Current Market</span>
            <span class="cell-val font-mono" style="font-size: 13px; font-weight: 600; color: #64d2ff;">$${curr}</span>
          </div>
          <div class="trade-grid-cell">
            <span class="cell-lbl" style="font-size: 11px; color: var(--text-secondary); display: block;">Profit Goal (TP)</span>
            <span class="cell-val font-mono val-green" style="font-size: 13px; font-weight: 600;">${tpText}</span>
          </div>
          <div class="trade-grid-cell">
            <span class="cell-lbl" style="font-size: 11px; color: var(--text-secondary); display: block;">Safety Stop (SL)</span>
            <span class="cell-val font-mono val-cyan" style="font-size: 13px; font-weight: 600;">${slText}</span>
          </div>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center; pt-1;">
          <span style="font-size: 11px; color: var(--text-secondary);">🛡️ Auto-Risk Protected</span>
          <div class="multitap-close-container" id="multitap-box-${posId}">
            <button class="btn-close-trade" onclick="handleWebMultiTap(${posId}, '${dname}', 2)" 
              style="background: rgba(255, 69, 58, 0.12); color: #ff453a; border: 1px solid rgba(255, 69, 58, 0.3); border-radius: 8px; padding: 6px 14px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s;">
              ❌ Close Position (Tap 1/3)
            </button>
          </div>
        </div>
      </div>
    `;
  });
  
  container.innerHTML = html;
}

let webMultiTapTimers = {};

function handleWebMultiTap(posId, symName, step) {
  const box = document.getElementById(`multitap-box-${posId}`);
  if (!box) return;
  
  if (webMultiTapTimers[posId]) {
    clearTimeout(webMultiTapTimers[posId]);
  }
  
  if (step === 2) {
    box.innerHTML = `
      <div style="display: flex; gap: 8px; align-items: center; justify-content: flex-end;">
        <button onclick="handleWebMultiTap(${posId}, '${symName}', 3)" 
          style="background: #ff9f0a; color: #000; border: none; border-radius: 8px; padding: 7px 14px; font-size: 12px; font-weight: 800; cursor: pointer; box-shadow: 0 0 12px rgba(255, 159, 10, 0.4);">
          ⚠️ Confirm Close? (Tap 2/3)
        </button>
        <button onclick="handleWebMultiTapCancel(${posId}, '${symName}')" 
          style="background: rgba(255,255,255,0.12); color: #fff; border: 1px solid rgba(255,255,255,0.25); border-radius: 8px; padding: 7px 12px; font-size: 12px; cursor: pointer;">
          ↩️ Cancel
        </button>
      </div>
    `;
    webMultiTapTimers[posId] = setTimeout(() => {
      handleWebMultiTapCancel(posId, symName);
    }, 12000);
  } else if (step === 3) {
    box.innerHTML = `
      <div style="display: flex; gap: 8px; align-items: center; justify-content: flex-end;">
        <button onclick="executeWebClose(${posId}, '${symName}')" 
          style="background: #ff453a; color: #fff; border: none; border-radius: 8px; padding: 7px 14px; font-size: 12px; font-weight: 800; cursor: pointer; box-shadow: 0 0 16px rgba(255, 69, 58, 0.6);">
          🚨 FINAL TAP: EXECUTE CLOSE (3/3)
        </button>
        <button onclick="handleWebMultiTapCancel(${posId}, '${symName}')" 
          style="background: rgba(255,255,255,0.12); color: #fff; border: 1px solid rgba(255,255,255,0.25); border-radius: 8px; padding: 7px 12px; font-size: 12px; cursor: pointer;">
          ↩️ Cancel
        </button>
      </div>
    `;
    webMultiTapTimers[posId] = setTimeout(() => {
      handleWebMultiTapCancel(posId, symName);
    }, 12000);
  }
}

function handleWebMultiTapCancel(posId, symName) {
  const box = document.getElementById(`multitap-box-${posId}`);
  if (!box) return;
  if (webMultiTapTimers[posId]) {
    clearTimeout(webMultiTapTimers[posId]);
    delete webMultiTapTimers[posId];
  }
  box.innerHTML = `
    <button onclick="handleWebMultiTap(${posId}, '${symName}', 2)" 
      style="background: rgba(255, 69, 58, 0.12); color: #ff453a; border: 1px solid rgba(255, 69, 58, 0.3); border-radius: 8px; padding: 6px 14px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.2s;">
      ❌ Close Position (Tap 1/3)
    </button>
  `;
}

function executeWebClose(posId, symName) {
  const box = document.getElementById(`multitap-box-${posId}`);
  if (box) {
    box.innerHTML = `<span style="font-size: 12px; color: #ff9f0a; font-weight: 600;">⚡ Closing on cTrader...</span>`;
  }
  
  // 1. If running inside Telegram WebApp
  if (window.Telegram?.WebApp && typeof window.Telegram.WebApp.sendData === 'function') {
    try {
      window.Telegram.WebApp.sendData(JSON.stringify({
        action: "close_position",
        position_id: posId,
        symbol: symName
      }));
      return;
    } catch (e) {
      console.warn("Telegram sendData failed", e);
    }
  }

  // 2. HTTP POST API
  fetch('/api/close_position', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({position_id: posId, client: 'david'})
  })
  .then(r => r.json())
  .then(data => {
    if (data.status === 'success') {
      if (box) box.innerHTML = `<span style="font-size: 12px; color: #30d158; font-weight: 700;">✅ Closed Successfully!</span>`;
      setTimeout(() => {
        telemetryData.active_positions = (telemetryData.active_positions || []).filter(p => (p.position_id || p.positionId || p.id) !== posId);
        updateActiveTradesUI();
      }, 1500);
    } else {
      alert(`Could not close: ${data.error || 'Server error'}`);
      handleWebMultiTapCancel(posId, symName);
    }
  })
  .catch(err => {
    // 3. Deep link fallback
    if (window.Telegram?.WebApp?.openTelegramLink) {
      window.Telegram.WebApp.openTelegramLink(`https://t.me/Nextgeneration9_bot?start=close_${posId}`);
    } else {
      window.location.href = `https://t.me/Nextgeneration9_bot?start=close_${posId}`;
    }
  });
}

function updateMatrixUI() {
  ASSETS_LIST.forEach(asset => {
    const key = asset.toLowerCase();
    const priceEl = document.getElementById(`${key}-price`);
    const distEl = document.getElementById(`${key}-dip-dist`);
    const targetEl = document.getElementById(`${key}-dip-target`);
    const badgeEl = document.getElementById(`${key}-status-badge`);

    const curPrice = telemetryData[`${key}_price`] || 0;
    const dipPrice = telemetryData[`${key}_dip`] || 0;
    const dist = telemetryData[`${key}_dist`] || 0;
    const distPct = telemetryData[`${key}_dist_pct`] || 0;

    if (priceEl) priceEl.textContent = `$${curPrice.toFixed(2)}`;

    if (asset === 'GLD') {
      if (distEl) distEl.textContent = 'In Trade (Holding)';
      if (badgeEl) {
        badgeEl.textContent = 'HOLDING';
        badgeEl.className = 'status-badge badge-active';
      }
    } else {
      if (distEl) {
        distEl.textContent = `+$${dist.toFixed(2)} (+${distPct.toFixed(2)}%)`;
      }
      if (badgeEl) {
        if (distPct <= 0.05) {
          badgeEl.textContent = 'AT DIP';
          badgeEl.className = 'status-badge badge-active';
        } else {
          badgeEl.textContent = 'WAITING';
          badgeEl.className = 'status-badge badge-waiting';
        }
      }
    }
  });
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
    if (params.has('eq')) {
      const eq = parseFloat(params.get('eq'));
      if (!isNaN(eq) && eq > 0) telemetryData.equity = eq;
    }
    if (params.has('trades')) {
      try {
        const rawTrades = params.get('trades');
        let trades;
        try {
          trades = JSON.parse(rawTrades);
        } catch (e1) {
          trades = JSON.parse(decodeURIComponent(rawTrades));
        }
        if (Array.isArray(trades) && trades.length > 0) {
          telemetryData.active_positions = trades.map(t => ({
            position_id: t.id || t.position_id,
            symbol_name: t.sym || t.symbol_name,
            display_name: t.name || t.display_name,
            trade_side: t.side || t.trade_side || 'BUY',
            lots: t.lots || 0.01,
            entry_price: t.entry || t.entry_price,
            current_price: t.curr || t.current_price,
            floating_pnl: t.pnl !== undefined ? t.pnl : t.floating_pnl,
            take_profit: t.tp || t.take_profit,
            stop_loss: t.sl || t.stop_loss
          }));
        }
      } catch (err) {
        console.warn("Could not parse trades parameter", err);
      }
    }
    updateActiveTradesUI();
  } catch (e) {}
}

async function syncTelemetry() {
  let data = null;
  // 1. Try local/tunnel api
  try {
    const res = await fetch('/api/telemetry', { cache: 'no-store' });
    if (res.ok) data = await res.json();
  } catch (e) {}

  // 2. Try static telemetry.json on GitHub Pages
  if (!data) {
    try {
      const res = await fetch('telemetry.json?t=' + Date.now(), { cache: 'no-store' });
      if (res.ok) data = await res.json();
    } catch (e) {}
  }

  if (!data) return;
  try {
    telemetryData = { ...telemetryData, ...data };

    ASSETS_LIST.forEach(asset => {
      const key = asset.toLowerCase();
      if (data[`${key}_price`]) {
        pushAssetTick(asset, data[`${key}_price`]);
      }
    });

    const balEl = document.getElementById('balance-val');
    const buffEl = document.getElementById('buffer-val');
    if (balEl && data.capital) balEl.textContent = `$${Number(data.capital).toFixed(2)}`;
    if (buffEl && data.buffer) buffEl.textContent = `$${Number(data.buffer).toFixed(2)}`;

    updateMatrixUI();
    updateActiveTradesUI();

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

  // 8. Telemetry polling (every 5s for real-time trade vision)
  syncTelemetry();
  setInterval(syncTelemetry, 5000);
});

window.addEventListener('resize', () => {
  if (currentTab === 'radar') renderRadarChart();
});
