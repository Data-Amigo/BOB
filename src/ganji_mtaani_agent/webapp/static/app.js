/* BOB Mini App — client-side logic */

// ── Telegram Web App ──────────────────────────────────────────────────────────
const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }

const tgUser = tg?.initDataUnsafe?.user || null;

// ── State ─────────────────────────────────────────────────────────────────────
let slipsData   = {};
let activeSport = 'football';
let activeTab   = 'slips';
let currentUser = null;
let stake       = 500;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

// ── Boot ──────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  renderDate();
  initTabs();
  initSportTabs();
  await registerUser();
  loadSlips();
});

// ── Date ──────────────────────────────────────────────────────────────────────
function renderDate() {
  const now = new Date();
  $('headerDate').textContent = now.toLocaleDateString('en-GB', { weekday:'short', day:'numeric', month:'short' });
}

// ── User registration ─────────────────────────────────────────────────────────
async function registerUser() {
  const body = {
    telegram_user_id: String(tgUser?.id || 'anon_' + Date.now()),
    first_name:  tgUser?.first_name  || null,
    last_name:   tgUser?.last_name   || null,
    username:    tgUser?.username    || null,
  };

  try {
    const res = await fetch('/api/user/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    currentUser = await res.json();
  } catch {
    currentUser = { display_name: tgUser?.first_name || 'Bettor', is_new: false, daily_stake_kes: 500 };
  }

  stake = currentUser.daily_stake_kes || 500;
  renderUserHeader();
  initStake();

  if (currentUser.is_new) {
    showOnboarding();
  } else {
    loadUserStats();
  }
}

function renderUserHeader() {
  const name = currentUser?.display_name || '';
  const handle = currentUser?.username ? `@${currentUser.username}` : '';
  $('headerUser').textContent = name + (handle ? ` · ${handle}` : '');
}

// ── Onboarding ────────────────────────────────────────────────────────────────
function showOnboarding() {
  const overlay   = $('onboardingOverlay');
  const nickInput = $('nickInput');
  const doneBtn   = $('onboardingDone');
  const shareBtn  = $('sharePhoneBtn');

  // Pre-fill with Telegram name
  nickInput.value = currentUser?.first_name || '';
  doneBtn.disabled = !nickInput.value.trim();

  overlay.classList.remove('hidden');

  nickInput.addEventListener('input', () => {
    doneBtn.disabled = !nickInput.value.trim();
  });

  shareBtn.addEventListener('click', () => {
    if (tg?.requestContact) {
      tg.requestContact(contact => {
        if (contact?.phone_number) {
          $('phoneInput').value = contact.phone_number;
        }
      });
    } else {
      $('phoneInput').focus();
    }
  });

  doneBtn.addEventListener('click', async () => {
    const preferred_name = nickInput.value.trim();
    const phone_number   = $('phoneInput').value.trim() || null;

    await fetch(`/api/user/${currentUser?.telegram_user_id || tgUser?.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preferred_name, phone_number }),
    }).catch(() => {});

    currentUser.display_name   = preferred_name;
    currentUser.preferred_name = preferred_name;
    currentUser.phone_number   = phone_number;
    currentUser.is_new         = false;

    renderUserHeader();
    overlay.classList.add('hidden');
    loadUserStats();
  });
}

// ── Stake ─────────────────────────────────────────────────────────────────────
function initStake() {
  const stakeInput = $('stakeInput');
  stakeInput.value = stake;
  updateProjection();

  stakeInput.addEventListener('input', () => {
    stake = parseFloat(stakeInput.value) || 0;
    document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
    saveStake();
    updateProjection();
    if (activeTab === 'slips') renderSlips();
  });

  document.querySelectorAll('.chip').forEach(btn => {
    btn.addEventListener('click', () => {
      stake = parseInt(btn.dataset.value);
      stakeInput.value = stake;
      document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
      saveStake();
      updateProjection();
      if (activeTab === 'slips') renderSlips();
    });
    if (parseInt(btn.dataset.value) === stake) btn.classList.add('active');
  });
}

async function saveStake() {
  if (!currentUser || !tgUser?.id) return;
  await fetch(`/api/user/${tgUser.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ daily_stake_kes: stake }),
  }).catch(() => {});
}

function updateProjection() {
  const proj = $('stakeProjection');
  const tiers = slipsData[activeSport];
  if (!tiers?.length || !stake) {
    proj.textContent = stake ? 'Loading slip data…' : 'Enter a stake to see projected earnings';
    return;
  }
  const lines = tiers.map(t => {
    const p = (t.combined_odds * stake).toFixed(0);
    return `${t.emoji} ${t.tier}: KES ${fmt(stake)} → <strong>~KES ${fmt(p)}</strong>`;
  });
  proj.innerHTML = lines.join('<br/>');
}

// ── Main tabs ─────────────────────────────────────────────────────────────────
function initTabs() {
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      activeTab = btn.dataset.tab;
      $(`panel${capitalize(activeTab)}`).classList.add('active');
      $('sportTabs').style.display = activeTab === 'slips' ? 'flex' : 'none';

      if (activeTab === 'history') loadHistory();
      if (activeTab === 'teams')   loadTeams();
    });
  });
}

// ── Sport sub-tabs ────────────────────────────────────────────────────────────
function initSportTabs() {
  document.querySelectorAll('.sport-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.sport-tab').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
      activeSport = btn.dataset.sport;
      renderSlips();
      updateProjection();
    });
  });
}

// ── Load data ─────────────────────────────────────────────────────────────────
async function loadSlips() {
  try {
    const res = await fetch('/api/today-slips');
    slipsData = await res.json();
    renderSlips();
    updateProjection();
  } catch {
    $('slipsContainer').innerHTML = errorMsg('Could not load slips. Is the BOB server running?');
  }
}

async function loadUserStats() {
  if (!tgUser?.id) return;
  try {
    const res = await fetch(`/api/user/${tgUser.id}/stats`);
    const stats = await res.json();
    renderUserStats(stats);
  } catch {}
}

async function loadHistory() {
  if (!tgUser?.id) {
    $('historyContainer').innerHTML = noDataMsg('Sign in via Telegram to see your history.');
    return;
  }
  $('historyContainer').innerHTML = loadingHtml('Loading your slips…');
  try {
    const res = await fetch(`/api/user/${tgUser.id}/slips`);
    const slips = await res.json();
    renderHistory(slips);
  } catch {
    $('historyContainer').innerHTML = errorMsg('Could not load history.');
  }
}

async function loadTeams() {
  $('teamsContainer').innerHTML = loadingHtml('Loading top teams…');
  try {
    const res = await fetch('/api/successful-teams');
    const teams = await res.json();
    renderTeams(teams);
  } catch {
    $('teamsContainer').innerHTML = errorMsg('Could not load teams data.');
  }
}

// ── Render user stats ─────────────────────────────────────────────────────────
function renderUserStats(stats) {
  $('statSlipsToday').textContent = stats.total ?? '0';
  $('statWon').textContent        = stats.won   ?? '0';
  $('statWinRate').textContent    = stats.win_rate != null ? stats.win_rate + '%' : '—';

  if (stats.earned_kes > 0) {
    $('stakeEarned').textContent = `+KES ${fmt(stats.earned_kes)} earned`;
  }
}

// ── Render slips ──────────────────────────────────────────────────────────────
function renderSlips() {
  const tiers = slipsData[activeSport];
  const container = $('slipsContainer');
  if (!tiers?.length) {
    container.innerHTML = noDataMsg(`No ${activeSport} slips at 70%+ right now.`);
    return;
  }
  container.innerHTML = '<div class="slips-container" style="padding:0">' +
    tiers.map(renderTierCard).join('') + '</div>';
}

function renderTierCard(tier) {
  const tierClass = tier.tier.toLowerCase();
  const payout = stake > 0 ? `~KES ${fmt((tier.combined_odds * stake).toFixed(0))}` : '';
  const payoutLine = payout
    ? `<span class="payout-text">KES ${fmt(stake)} → ${payout}</span>` : '';

  const legs = tier.legs.map(leg => {
    const timeTag  = leg.time  ? `<span class="leg-time">🕐 ${leg.time}</span>` : '';
    const oddsTag  = leg.odds
      ? `<span class="leg-odds">${parseFloat(leg.odds).toFixed(2)}${leg.bookmaker ? ' via ' + leg.bookmaker : ''}</span>`
      : `<span class="leg-odds">~1.50 (est.)</span>`;
    return `
    <div class="leg-row">
      <div class="leg-teams">${esc(leg.home_team)} vs ${esc(leg.away_team)}</div>
      <div class="leg-meta">
        <span class="leg-pick">✅ ${esc(leg.outcome_label)}</span>
        <span class="leg-prob">${leg.probability}%</span>
        ${oddsTag} ${timeTag}
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

// ── Render history ────────────────────────────────────────────────────────────
function renderHistory(slips) {
  if (!slips?.length) {
    $('historyContainer').innerHTML = noDataMsg('No slips yet. Ask BOB for slips in the chat first!');
    return;
  }
  const OUTCOME = { '1': 'Home Win', '2': 'Away Win', 'X': 'Draw' };
  $('historyContainer').innerHTML = '<div style="padding:16px;display:flex;flex-direction:column;gap:12px">' +
    slips.map(s => {
      const statusClass = `status-${s.status || 'pending'}`;
      const statusLabel = { won:'✅ Won', lost:'❌ Lost', pending:'⏳ Pending' }[s.status] || s.status;
      const legs = (s.legs || []).map(l =>
        `<div class="history-leg">
          <span>${esc(l.home_team)} vs ${esc(l.away_team)}</span>
          <span class="history-leg-pick">${OUTCOME[l.pred_outcome] || l.pred_outcome} · ${l.pred_probability}%</span>
        </div>`
      ).join('');
      const payoutLine = s.payout_kes
        ? `<span class="payout-won">+KES ${fmt(s.payout_kes)}</span>`
        : `<span>KES ${fmt(s.stake_kes)} staked</span>`;
      return `
      <div class="history-card">
        <div class="history-header">
          <div>
            <div class="history-sport">${s.sport?.charAt(0).toUpperCase() + s.sport?.slice(1)} · ${s.slip_size}-leg</div>
            <div class="history-date">${s.event_date || s.created_at?.slice(0,10) || ''}</div>
          </div>
          <span class="status-badge ${statusClass}">${statusLabel}</span>
        </div>
        <div class="history-legs">${legs}</div>
        <div class="history-footer">
          ${payoutLine}
          <span>Odds: ${s.total_combined_odds ? parseFloat(s.total_combined_odds).toFixed(2) + 'x' : '—'}</span>
        </div>
      </div>`;
    }).join('') + '</div>';
}

// ── Render teams ──────────────────────────────────────────────────────────────
function renderTeams(teams) {
  if (!teams?.length) {
    $('teamsContainer').innerHTML = noDataMsg('No resolved slips yet to rank teams. Check back after games are settled.');
    return;
  }
  $('teamsContainer').innerHTML = `
  <div style="padding:16px">
    <h3 style="font-size:15px;font-weight:700;margin-bottom:12px">🏆 Top Winning Teams (7 days)</h3>
    <div class="teams-list">
      ${teams.map(t => `
      <div class="team-row">
        <div class="team-name">${esc(t.team)}</div>
        <div class="team-bar-wrap"><div class="team-bar" style="width:${t.win_rate}%"></div></div>
        <div class="team-rate">${t.win_rate}%</div>
      </div>`).join('')}
    </div>
  </div>`;
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt(n)    { return Number(n).toLocaleString('en-KE'); }
function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
function esc(str)  {
  return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function loadingHtml(msg) {
  return `<div class="loading"><div class="spinner"></div><p>${msg}</p></div>`;
}
function noDataMsg(msg) {
  return `<div class="no-slips"><div class="no-slips-icon">😕</div><p>${msg}</p></div>`;
}
function errorMsg(msg) {
  return `<div class="no-slips"><div class="no-slips-icon">⚠️</div><p>${msg}</p></div>`;
}
