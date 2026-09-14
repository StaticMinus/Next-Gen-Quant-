/**
 * AgentQuant Pro Terminal — Apple-Style Minimalist UI Controller
 * Powered by GreenSock Animation Platform (GSAP) & Telegram WebApp SDK
 */

const tg = window.Telegram ? window.Telegram.WebApp : null;
let LIVE_P2P_RATE = 1518.40;

async function fetchLiveBinanceRate() {
  try {
    const res = await fetch('https://api.binance.com/api/v3/ticker/price?symbol=USDTNGN', { cache: 'no-store' });
    if (!res.ok) throw new Error('Binance HTTP ' + res.status);
    const data = await res.json();
    if (data && data.price) {
      const price = parseFloat(data.price);
      if (!isNaN(price) && price > 500) {
        LIVE_P2P_RATE = price;
        const subEl = document.getElementById('p2p-rate-subtitle');
        if (subEl) {
          subEl.textContent = `Live Binance Rate: 1 USDT = ₦${price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
        }
        const slider = document.getElementById('p2p-slider');
        if (slider) {
          updateP2P(parseFloat(slider.value));
        }
      }
    }
  } catch (err) {
    console.warn('Binance direct fetch fallback to cached/telemetry rate:', err);
  }
}

// Application State
let currentTab = 'radar';
const navHistory = ['radar'];
let telemetryData = {
  capital: 6000.0,
  equity: 6000.0,
  buffer: 360.0,
  strategy_name: 'Dual-Asset Scalper (SPY + QQQ)',
  win_rate: '72.4%',
  trades_per_mo: '3.14 / mo',
  profit_10y: '+$6,438.11',
  spy_price: 764.29,
  spy_mean: 764.13,
  spy_dip: 758.45,
  spy_dist: 5.84,
  qqq_price: 508.15,
  qqq_mean: 509.30,
  qqq_dip: 503.40,
  qqq_dist: 4.75,
  payout_days: 5,
};

// =========================================================================
// 1. TELEGRAM SDK INITIALIZATION & ANDROID HARDWARE BACK BUTTON HOOK
// =========================================================================

function initTelegram() {
  if (tg) {
    tg.ready();
    tg.expand();

    // Set Apple-style dark OLED chrome
    if (tg.setHeaderColor) {
      tg.setHeaderColor('#000000');
      tg.setBackgroundColor('#000000');
    }

    // Android Hardware & Top-Left Back Button Hook
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
    if (tg) tg.close();
  }
}

// =========================================================================
// 2. GSAP ENTRANCE & TAB SWITCHING SYSTEM
// =========================================================================

function initGSAPAnimations() {
  if (typeof gsap === 'undefined') return;

  // Staggered Entrance of Shell Elements
  gsap.from('.top-nav, .hero-widget, .segmented-control, .views-wrapper, .bottom-bar', {
    opacity: 0,
    y: 20,
    duration: 0.7,
    stagger: 0.08,
    ease: 'power3.out',
  });

  // Animate initial balance count-up
  animateBalance(6000.0);
}

function animateBalance(targetValue) {
  if (typeof gsap === 'undefined') {
    document.getElementById('equity-val').textContent = targetValue.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return;
  }

  const obj = { val: 0 };
  gsap.to(obj, {
    val: targetValue,
    duration: 1.2,
    ease: 'power2.out',
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

  // 1. Move the Segmented Indicator Slider
  const slider = document.getElementById('segment-slider');
  if (slider) {
    slider.style.transform = `translateX(${targetIndex * 100}%)`;
  }

  // 2. Update button active classes
  document.querySelectorAll('.segment-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });

  // 3. GSAP Cross-fade & slide transition between views
  if (typeof gsap !== 'undefined' && currentView) {
    gsap.to(currentView, {
      opacity: 0,
      y: -10,
      duration: 0.18,
      ease: 'power2.in',
      onComplete: () => {
        currentView.classList.remove('active');
        currentView.style.display = 'none';

        targetView.style.display = 'block';
        targetView.classList.add('active');
        gsap.fromTo(targetView, 
          { opacity: 0, y: 14, scale: 0.985 },
          { opacity: 1, y: 0, scale: 1, duration: 0.3, ease: 'power2.out' }
        );

        if (tabName === 'radar') {
          requestAnimationFrame(renderRadarChart);
        } else if (tabName === 'sentinel') {
          animateActivityRing();
        }
      }
    });
  } else {
    if (currentView) currentView.classList.remove('active');
    targetView.classList.add('active');
    if (tabName === 'radar') requestAnimationFrame(renderRadarChart);
  }

  currentTab = tabName;
  if (pushToHistory) {
    navHistory.push(tabName);
  }
}

function setupSegmentedNav() {
  document.querySelectorAll('.segment-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      switchTab(tab, true);
    });
  });
}

// =========================================================================
// 3. APPLE STOCKS MINIMALIST CANVAS CHART (SPY RADAR)
// =========================================================================

function renderRadarChart() {
  const canvas = document.getElementById('radarChart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;

  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;

  // Clear canvas
  ctx.clearRect(0, 0, w, h);

  // 12-day SPY synthetic path ending at current price
  const basePrice = telemetryData.spy_price || 764.29;
  const dipPrice = telemetryData.spy_dip || 758.45;
  const meanPrice = telemetryData.spy_mean || 764.13;

  const pricePoints = [
    754.20, 756.80, 759.10, 757.50, 761.30, 
    763.40, 760.10, 762.80, 765.20, 763.10, 
    762.50, basePrice
  ];

  const minP = Math.min(...pricePoints, dipPrice) - 3.0;
  const maxP = Math.max(...pricePoints, meanPrice) + 3.0;
  const range = maxP - minP;

  const getX = (index) => (index / (pricePoints.length - 1)) * (w - 30) + 15;
  const getY = (price) => h - 25 - ((price - minP) / range) * (h - 45);

  // 1. Draw Subtle Mean Target Dashed Line
  const yMean = getY(meanPrice);
  ctx.save();
  ctx.strokeStyle = 'rgba(100, 210, 255, 0.4)';
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(15, yMean);
  ctx.lineTo(w - 15, yMean);
  ctx.stroke();
  ctx.restore();

  // 2. Draw Dip Entry Trigger Dashed Line
  const yDip = getY(dipPrice);
  ctx.save();
  ctx.strokeStyle = 'rgba(48, 209, 88, 0.5)';
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(15, yDip);
  ctx.lineTo(w - 15, yDip);
  ctx.stroke();
  ctx.restore();

  // 3. Draw Gradient Area Fill under price curve
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, 'rgba(100, 210, 255, 0.25)');
  grad.addColorStop(1, 'rgba(100, 210, 255, 0.00)');

  ctx.beginPath();
  ctx.moveTo(getX(0), getY(pricePoints[0]));
  for (let i = 1; i < pricePoints.length; i++) {
    const prevX = getX(i - 1);
    const prevY = getY(pricePoints[i - 1]);
    const currX = getX(i);
    const currY = getY(pricePoints[i]);
    const midX = (prevX + currX) / 2;
    ctx.bezierCurveTo(midX, prevY, midX, currY, currX, currY);
  }
  ctx.lineTo(getX(pricePoints.length - 1), h - 10);
  ctx.lineTo(getX(0), h - 10);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // 4. Draw Main Price Stroke Line
  ctx.beginPath();
  ctx.moveTo(getX(0), getY(pricePoints[0]));
  for (let i = 1; i < pricePoints.length; i++) {
    const prevX = getX(i - 1);
    const prevY = getY(pricePoints[i - 1]);
    const currX = getX(i);
    const currY = getY(pricePoints[i]);
    const midX = (prevX + currX) / 2;
    ctx.bezierCurveTo(midX, prevY, midX, currY, currX, currY);
  }
  ctx.strokeStyle = '#64D2FF';
  ctx.lineWidth = 2.5;
  ctx.lineCap = 'round';
  ctx.stroke();

  // 5. Draw Glowing Current Price Dot
  const lastX = getX(pricePoints.length - 1);
  const lastY = getY(basePrice);

  ctx.save();
  ctx.shadowColor = '#64D2FF';
  ctx.shadowBlur = 12;
  ctx.fillStyle = '#FFFFFF';
  ctx.beginPath();
  ctx.arc(lastX, lastY, 4.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

// =========================================================================
// 4. APPLE WATCH ACTIVITY RING ANIMATION
// =========================================================================

function animateActivityRing() {
  const ring = document.getElementById('ring-guard');
  if (!ring) return;

  const circumference = 427.26; // 2 * pi * 68
  ring.style.strokeDasharray = circumference;

  if (typeof gsap !== 'undefined') {
    gsap.fromTo(ring, 
      { strokeDashoffset: circumference },
      { strokeDashoffset: 0, duration: 1.0, ease: 'power2.out' }
    );
  } else {
    ring.style.strokeDashoffset = 0;
  }
}

// =========================================================================
// 5. BINANCE P2P NAIRA CALCULATOR (APPLE PAY CASH INSPIRED)
// =========================================================================

function setupP2PCalculator() {
  const slider = document.getElementById('p2p-slider');
  if (!slider) return;

  slider.addEventListener('input', (e) => {
    updateP2P(parseFloat(e.target.value));
    triggerHaptic('light');
  });
}

function setSlider(val) {
  const slider = document.getElementById('p2p-slider');
  if (slider) {
    slider.value = val;
    updateP2P(val);
    triggerHaptic('medium');

    document.querySelectorAll('.chip-preset').forEach(chip => {
      chip.classList.toggle('active', chip.textContent.includes(`$${val}`));
    });
  }
}

function updateP2P(usd) {
  const usdEl = document.getElementById('p2p-usd-display');
  const nairaEl = document.getElementById('p2p-naira-display');

  if (usdEl) usdEl.textContent = Math.round(usd).toLocaleString();
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
      hint.textContent = '⚠️ Set wallet first in Telegram (/setwallet)';
      hint.style.color = '#FF9F0A';
      setTimeout(() => {
        hint.textContent = 'Tap to Copy';
        hint.style.color = '#64D2FF';
      }, 3500);
    }
    const alertMsg = "⚠️ No Binance TRC20 wallet linked yet!\n\nPlease open your chat with @NextGenQuantBot and type:\n/setwallet <YOUR_BINANCE_TRC20_ADDRESS>\n\nto safely link your real payout destination.";
    if (tg && tg.showAlert) {
      tg.showAlert(alertMsg);
    } else {
      alert(alertMsg);
    }
    return;
  }

  if (navigator.clipboard) {
    navigator.clipboard.writeText(address);
  }
  triggerHaptic('notification');
  if (hint) {
    hint.textContent = 'Copied to Clipboard!';
    hint.style.color = '#30D158';
    setTimeout(() => {
      hint.textContent = 'Tap to Copy';
      hint.style.color = '#64D2FF';
    }, 2000);
  }
}

function toggleAccordion(id) {
  triggerHaptic('light');
  const el = document.getElementById(id);
  if (el) el.classList.toggle('expanded');
}

// =========================================================================
// 6. LIVE TELEMETRY SYNC
// =========================================================================

async function syncTelemetry() {
  try {
    const res = await fetch('/api/telemetry');
    if (!res.ok) return;
    const data = await res.json();
    telemetryData = { ...telemetryData, ...data };

    // Update hero values
    const balEl = document.getElementById('balance-val');
    const buffEl = document.getElementById('buffer-val');
    const spyEl = document.getElementById('spy-price');
    const qqqEl = document.getElementById('qqq-price');
    const dipDistEl = document.getElementById('dip-dist');

    if (balEl) balEl.textContent = `$${data.capital.toFixed(2)}`;
    if (buffEl) buffEl.textContent = `$${data.buffer.toFixed(2)}`;
    if (spyEl) spyEl.textContent = `$${data.spy_price.toFixed(2)}`;
    if (qqqEl) qqqEl.textContent = `$${data.qqq_price.toFixed(2)}`;
    if (dipDistEl) dipDistEl.textContent = `+$${data.spy_dist.toFixed(2)}`;

    // Sync P2P Rate if provided by telemetry
    if (data.live_p2p_rate && !isNaN(data.live_p2p_rate)) {
      LIVE_P2P_RATE = parseFloat(data.live_p2p_rate);
      const subEl = document.getElementById('p2p-rate-subtitle');
      if (subEl) {
        subEl.textContent = `Live Binance Rate: 1 USDT = ₦${LIVE_P2P_RATE.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
      }
      const slider = document.getElementById('p2p-slider');
      if (slider) updateP2P(parseFloat(slider.value));
    }

    // Sync Wallet address if provided by telemetry
    if (data.wallet_address) {
      const walletEl = document.getElementById('wallet-address-display');
      if (walletEl) {
        walletEl.textContent = data.wallet_address;
      }
      try {
        localStorage.setItem('agentquant_trc20_wallet', data.wallet_address);
      } catch (e) {}
    }

    renderRadarChart();
  } catch (e) {
    // Graceful offline fallback
  }
}

// =========================================================================
// 7. INITIALIZATION
// =========================================================================

window.addEventListener('DOMContentLoaded', () => {
  initTelegram();
  setupSegmentedNav();
  setupP2PCalculator();
  initGSAPAnimations();
  requestAnimationFrame(renderRadarChart);

  // Load saved wallet from localStorage if available
  try {
    const savedWallet = localStorage.getItem('agentquant_trc20_wallet');
    const walletEl = document.getElementById('wallet-address-display');
    if (savedWallet && walletEl && !savedWallet.includes('NO WALLET') && !savedWallet.includes('TX8aKq9Z')) {
      walletEl.textContent = savedWallet;
    }
  } catch (e) {}

  // Fetch initial live Binance rate immediately & keep fresh every 30s
  fetchLiveBinanceRate();
  setInterval(fetchLiveBinanceRate, 30000);

  // Sync button listener
  const btnRefresh = document.getElementById('btn-refresh-radar');
  if (btnRefresh) {
    btnRefresh.addEventListener('click', () => {
      triggerHaptic('medium');
      fetchLiveBinanceRate();
      syncTelemetry();
    });
  }

  // Poll telemetry every 30s
  syncTelemetry();
  setInterval(syncTelemetry, 30000);
});

window.addEventListener('resize', () => {
  if (currentTab === 'radar') {
    requestAnimationFrame(renderRadarChart);
  }
});
