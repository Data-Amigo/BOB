/* BOB Mini App — client-side logic */

// ── Telegram Web App init ────────────────────────────────────────────────────
const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

// ── State ────────────────────────────────────────────────────────────────────
let slipsData = {};         // {football: [...tiers], basketball: [...tiers]}
let activeSport = 'football';
let stake = parseFloat(localStorage.getItem('bob_stake') || '500');

// ── DOM refs ─────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const stakeInput = $('stakeInput');
const stakeProjection = $('stakeProjection');
const slipsContainer = $('slipsContainer');
const teamsSection = $('teamsSection');
const teamsList = $('teamsList');

// ── Boot ─────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  renderDate();
  initStake();
  initTabs();
  loadAll();
});

// ── Date header ──────────────────────────────────────────────────────────────
function renderDate() {
  const now = new Date();
  const opts = { weekday: 'short', day: 'numeric', month: 'short' };
  $('headerDate').textContent = now.toLocaleDateString('en-GB', opts);
}

// ── Stake ────────────────────────────────────────────────────────────────────
function initStake() {
  stakeInput.value = stake;
  updateProjection();

  stakeInput.addEventListener('input', () => {
    stake = parseFloat(stakeInput.value) || 0;
    localStorage.setItem('bob_stake', stake);
    updateProjection();
    renderSlips();          // re-render payouts
    // Deactivate all chip highlights
    document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
  });

  document.querySelectorAll('.chip').forEach(btn => {
    btn.addEventListener('click', () => {
      stake = parseInt(btn.dataset.value);
      stakeInput.value = stake;
      localStorage.setItem('bob_stake', stake);
      document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
      updateProjection();
      renderSlips();
    });
  });

  // Highlight matching chip on load
  document.querySelectorAll('.chip').forEach(btn => {
    if (parseInt(btn.dataset.value) === stake) btn.classList.add('active');
  });
}

function updateProjection() {
  if (!slipsData[activeSport] || !slipsData[activeSport].length) {
    stakeProjection.textContent = stake > 0 ? 'Loading slip data…' : 'Enter a stake to see projected earnings';
    return;
  }

  const tiers = slipsData[activeSport];
  if (!tiers.length) {
    stakeProjection.textContent = 'No slips available to project earnings.';
    return;
  }

  const lines = tiers.map(t => {
    const payout = (t.combined_odds * stake).toFixed(0);
    return `${t.emoji} ${t.tier}: KES ${fmt(stake)} → <strong>~KES ${fmt(payout)}</strong>`;
  });

  stakeProjection.innerHTML = lines.join('<br/>');
}

// ── Tabs ─────────────────────────────────────────────────────────────────────
function initTabs() {
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
      activeSport = btn.dataset.sport;
      renderSlips();
      updateProjection();
    });
  });
}

// ── Load all data in parallel ─────────────────────────────────────────────────
async function loadAll() {
  try {
    const [slipsRes, statsRes, teamsRes] = await Promise.all([
      fetch('/api/today-slips'),
      fetch('/api/stats'),
      fetch('/api/successful-teams'),
    ]);
    slipsData = await slipsRes.json();
    const stats  = await statsRes.json();
    const teams  = await teamsRes.json();

    renderStats(stats);
    renderSlips();
    renderTeams(teams);
    updateProjection();
  } catch (err) {
    slipsContainer.innerHTML = `<div class="no-slips">
      <div class="no-slips-icon">⚠️</div>
      <p>Could not load slips. Make sure the BOB server is running.</p>
    </div>`;
    console.error(err);
  }
}

// ── Stats ─────────────────────────────────────────────────────────────────────
function renderStats(stats) {
  $('statSlipsToday').textContent = stats.today_slips ?? '0';
  $('statWon').textContent = stats.won_7d ?? '0';
  $('statWinRate').textContent = stats.win_rate_7d != null ? stats.win_rate_7d + '%' : '—';
}

// ── Slips ─────────────────────────────────────────────────────────────────────
function renderSlips() {
  const tiers = slipsData[activeSport];

  if (!tiers || !tiers.length) {
    slipsContainer.innerHTML = `<div class="no-slips">
      <div class="no-slips-icon">😕</div>
      <p>No ${activeSport} slips at 70%+ right now.<br>Check back after the next data refresh.</p>
    </div>`;
    return;
  }

  slipsContainer.innerHTML = tiers.map(tier => renderTierCard(tier)).join('');
}

function renderTierCard(tier) {
  const tierClass = tier.tier.toLowerCase();   // gold | silver | bronze
  const payout = stake > 0 ? `~KES ${fmt((tier.combined_odds * stake).toFixed(0))}` : '';
  const payoutLine = payout
    ? `<span class="payout-text">KES ${fmt(stake)} → ${payout}</span>`
    : '';

  const legs = tier.legs.map(leg => {
    const timeTag = leg.time ? `<span class="leg-time">🕐 ${leg.time}</span>` : '';
    const oddsTag = leg.odds
      ? `<span class="leg-odds">${parseFloat(leg.odds).toFixed(2)} ${leg.bookmaker ? 'via ' + leg.bookmaker : ''}</span>`
      : `<span class="leg-odds">~1.50 (est.)</span>`;
    return `
    <div class="leg-row">
      <div class="leg-teams">${esc(leg.home_team)} vs ${esc(leg.away_team)}</div>
      <div class="leg-meta">
        <span class="leg-pick">✅ ${esc(leg.outcome_label)}</span>
        <span class="leg-prob">${leg.probability}%</span>
        ${oddsTag}
        ${timeTag}
      </div>
    </div>`;
  }).join('');

  return `
  <div class="tier-card">
    <div class="tier-header">
      <div class="tier-header-left">
        <span class="tier-badge tier-${tierClass}">${tier.emoji} ${tier.tier}</span>
        <span class="tier-range">${tier.range}</span>
      </div>
      <span class="tier-games-count">${tier.games} pick${tier.games !== 1 ? 's' : ''}</span>
    </div>
    <div class="tier-legs">${legs}</div>
    <div class="tier-footer">
      <span class="combined-odds">💎 ${tier.combined_odds}x combined</span>
      ${payoutLine}
    </div>
  </div>`;
}

// ── Teams ─────────────────────────────────────────────────────────────────────
function renderTeams(teams) {
  if (!teams || !teams.length) {
    teamsSection.style.display = 'none';
    return;
  }

  teamsSection.style.display = 'block';
  teamsList.innerHTML = teams.map(t => `
    <div class="team-row">
      <div class="team-name">${esc(t.team)}</div>
      <div class="team-bar-wrap">
        <div class="team-bar" style="width:${t.win_rate}%"></div>
      </div>
      <div class="team-rate">${t.win_rate}%</div>
    </div>
  `).join('');
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt(n) {
  return Number(n).toLocaleString('en-KE');
}

function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
