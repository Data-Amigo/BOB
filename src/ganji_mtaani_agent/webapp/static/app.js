/* BOB Mini App — client-side logic */

// ── Telegram Web App ──────────────────────────────────────────────────────────
const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }

const tgUser = tg?.initDataUnsafe?.user || null;

// ── State ─────────────────────────────────────────────────────────────────────
let slipsData      = {};
let activeSport    = 'football';
let activeTab      = 'slips';
let currentUser    = null;
let stake          = 500;
let selectedTiers  = new Set();   // tiers the user has tapped to bet
let historyDays    = 7;
let analyticsDays  = 30;
let analyticsSport = 'all';

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

// ── Boot ──────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  renderDate();
  initTabs();
  initSportTabs();
  initHistoryFilter();
  initAnalyticsFilter();
  initPicksBar();
  initUploadModal();
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
  const name   = currentUser?.display_name || '';
  const handle = currentUser?.username ? `@${currentUser.username}` : '';
  $('headerUser').textContent = name + (handle ? ` · ${handle}` : '');
}

// ── Onboarding ────────────────────────────────────────────────────────────────
function showOnboarding() {
  const overlay   = $('onboardingOverlay');
  const nickInput = $('nickInput');
  const doneBtn   = $('onboardingDone');
  const shareBtn  = $('sharePhoneBtn');

  nickInput.value  = currentUser?.first_name || '';
  doneBtn.disabled = !nickInput.value.trim();
  overlay.classList.remove('hidden');

  nickInput.addEventListener('input', () => { doneBtn.disabled = !nickInput.value.trim(); });

  shareBtn.addEventListener('click', () => {
    if (tg?.requestContact) {
      tg.requestContact(contact => {
        if (contact?.phone_number) $('phoneInput').value = contact.phone_number;
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
    updatePicksBar();
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
      updatePicksBar();
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
  const proj  = $('stakeProjection');
  const tiers = slipsData[activeSport];
  if (!tiers?.length || !stake) {
    proj.textContent = stake ? 'Loading slip data…' : 'Enter a stake to see projected earnings';
    return;
  }
  const lines = tiers.map(t => {
    const p = (t.combined_odds * stake).toFixed(0);
    const sel = selectedTiers.size > 0 && !selectedTiers.has(t.tier) ? '<span style="opacity:.4">' : '<span>';
    return `${sel}${t.emoji} ${t.tier}: KES ${fmt(stake)} → <strong>~KES ${fmt(p)}</strong></span>`;
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

      if (activeTab === 'history')   loadHistory();
      if (activeTab === 'analytics') loadAnalytics();
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

// ── History date filter ───────────────────────────────────────────────────────
function initHistoryFilter() {
  $('historyFilterBar').addEventListener('click', e => {
    const chip = e.target.closest('.filter-chip');
    if (!chip) return;
    $('historyFilterBar').querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    historyDays = parseInt(chip.dataset.days);
    loadHistory();
    loadUserStats(historyDays, analyticsSport);
  });
}

// ── Analytics period + sport filters ─────────────────────────────────────────
function initAnalyticsFilter() {
  $('analyticsFilterBar').addEventListener('click', e => {
    const chip = e.target.closest('.filter-chip');
    if (!chip) return;
    $('analyticsFilterBar').querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    analyticsDays = parseInt(chip.dataset.days);
    loadAnalytics();
    loadUserStats(analyticsDays, analyticsSport);
  });

  $('analyticsSportTabs').addEventListener('click', e => {
    const btn = e.target.closest('.sport-tab');
    if (!btn) return;
    $('analyticsSportTabs').querySelectorAll('.sport-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    analyticsSport = btn.dataset.sport;
    loadAnalytics();
    loadUserStats(historyDays, analyticsSport);
  });
}

// ── Picks bar (slip selection) ────────────────────────────────────────────────
function initPicksBar() {
  $('picksClose').addEventListener('click', () => {
    selectedTiers.clear();
    renderSlips();
    updateProjection();
    updatePicksBar();
  });
}

function toggleTier(tierName) {
  if (selectedTiers.has(tierName)) {
    selectedTiers.delete(tierName);
  } else {
    selectedTiers.add(tierName);
  }
  renderSlips();
  updateProjection();
  updatePicksBar();
}

function updatePicksBar() {
  const bar = $('picksBar');
  if (selectedTiers.size === 0) {
    bar.classList.add('hidden');
    return;
  }
  bar.classList.remove('hidden');

  const tiers = slipsData[activeSport] || [];
  const picked = tiers.filter(t => selectedTiers.has(t.tier));
  let combinedOdds = 1.0;
  const tierLabels = [];
  picked.forEach(t => {
    combinedOdds *= t.combined_odds;
    tierLabels.push(`${t.emoji} ${t.tier}`);
  });

  $('picksDetail').textContent = tierLabels.join(' + ');
  $('picksOdds').textContent   = combinedOdds.toFixed(2) + 'x';
  $('picksPayout').textContent = stake > 0 ? `~KES ${fmt((combinedOdds * stake).toFixed(0))}` : '';
}

// ── Load data ─────────────────────────────────────────────────────────────────
async function loadSlips() {
  try {
    const uid = tgUser?.id ? `?telegram_user_id=${tgUser.id}` : '';
    const res = await fetch(`/api/today-slips${uid}`);
    slipsData = await res.json();
    renderSlips();
    updateProjection();
  } catch {
    $('slipsContainer').innerHTML = errorMsg('Could not load slips. Is the BOB server running?');
  }
}

async function loadUserStats(days = historyDays, sport = analyticsSport) {
  if (!tgUser?.id) return;
  try {
    const sportParam = sport !== 'all' ? `&sport=${sport}` : '';
    const res = await fetch(`/api/user/${tgUser.id}/stats?days=${days}${sportParam}`);
    const stats = await res.json();
    renderUserStats(stats, days, sport);
  } catch {}
}

async function loadHistory() {
  if (!tgUser?.id) {
    $('historyContainer').innerHTML = noDataMsg('Sign in via Telegram to see your history.');
    return;
  }
  $('historyContainer').innerHTML = loadingHtml('Loading your slips…');
  try {
    const res = await fetch(`/api/user/${tgUser.id}/slips?days=${historyDays}&limit=100`);
    const slips = await res.json();
    renderHistory(slips);
  } catch {
    $('historyContainer').innerHTML = errorMsg('Could not load history.');
  }
}

async function loadAnalytics() {
  if (!tgUser?.id) {
    $('analyticsContainer').innerHTML = noDataMsg('Sign in via Telegram to see analytics.');
    return;
  }
  $('analyticsContainer').innerHTML = loadingHtml('Loading analytics…');
  try {
    const sportParam = analyticsSport !== 'all' ? `&sport=${analyticsSport}` : '';
    const teamsParam = analyticsSport !== 'all' ? `&sport=${analyticsSport}` : '';
    const [analyticsRes, teamsRes] = await Promise.all([
      fetch(`/api/user/${tgUser.id}/analytics?days=${analyticsDays}${sportParam}`),
      fetch(`/api/successful-teams?days=${analyticsDays}${teamsParam}`),
    ]);
    const analytics = await analyticsRes.json();
    const teams     = await teamsRes.json();
    renderAnalytics(analytics, teams);
  } catch {
    $('analyticsContainer').innerHTML = errorMsg('Could not load analytics.');
  }
}

// ── Render user stats ─────────────────────────────────────────────────────────
function renderUserStats(stats, days = historyDays, sport = analyticsSport) {
  const periodSuffix = days >= 365 ? '' : ` (${days}d)`;
  const sportEmoji   = sport === 'football' ? ' ⚽' : sport === 'basketball' ? ' 🏀' : '';
  const suffix       = sportEmoji + periodSuffix;
  $('statSlipsToday').textContent = stats.total ?? '0';
  $('statTotalLabel').textContent = `Slips${suffix}`;
  $('statWon').textContent        = stats.won   ?? '0';
  $('statWonLabel').textContent   = `Won${suffix}`;
  $('statLost').textContent       = stats.lost  ?? '0';
  $('statLostLabel').textContent  = `Lost${suffix}`;
  $('statWinRate').textContent    = stats.win_rate != null ? stats.win_rate + '%' : '—';

  const pnl = stats.net_pnl_kes;
  if (pnl != null && (stats.won > 0 || stats.lost > 0)) {
    const sign  = pnl >= 0 ? '+' : '';
    const color = pnl >= 0 ? '#4caf82' : '#ef5350';
    $('stakeEarned').innerHTML = `<span style="color:${color}">${sign}KES ${fmt(Math.abs(pnl))} net${suffix}</span>`;
  } else {
    $('stakeEarned').textContent = '';
  }
}

// ── Render slips ──────────────────────────────────────────────────────────────
function renderSlips() {
  const tiers     = slipsData[activeSport];
  const container = $('slipsContainer');
  if (!tiers?.length) {
    container.innerHTML = noDataMsg(`No ${activeSport} slips at 70%+ right now.`);
    return;
  }
  container.innerHTML = '<div class="slips-container" style="padding:0">' +
    tiers.map(renderTierCard).join('') + '</div>';
}

function renderTierCard(tier) {
  const tierClass  = tier.tier.toLowerCase();
  const isSelected = selectedTiers.has(tier.tier);
  const payout     = stake > 0 ? `~KES ${fmt((tier.combined_odds * stake).toFixed(0))}` : '';
  const payoutLine = payout
    ? `<span class="payout-text">KES ${fmt(stake)} → ${payout}</span>` : '';
  const selLabel   = isSelected ? '✓ Selected' : 'Select';
  const selClass   = isSelected ? 'select-btn selected' : 'select-btn';

  const legs = tier.legs.map(leg => {
    const timeTag = leg.time  ? `<span class="leg-time">🕐 ${leg.time}</span>` : '';
    const oddsTag = leg.odds
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
  <div class="tier-card${isSelected ? ' tier-card-selected tier-card-selected-' + tierClass : ''}" id="tier-${tierClass}">
    <div class="tier-header">
      <div class="tier-header-left">
        <span class="tier-badge tier-${tierClass}">${tier.emoji} ${tier.tier}</span>
        <span class="tier-range">${tier.range}</span>
      </div>
      <div class="tier-header-right">
        <span class="tier-games-count">${tier.games} pick${tier.games !== 1 ? 's' : ''}</span>
        <button class="${selClass}" onclick="toggleTier('${tier.tier}')">${selLabel}</button>
      </div>
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
    $('historyContainer').innerHTML = noDataMsg('No slips in this period. Ask BOB for slips in the chat first!');
    return;
  }

  const OUTCOME = { '1': 'Home Win', '2': 'Away Win', 'X': 'Draw' };
  const TIER_EMOJIS = { Gold: '🥇', Silver: '🥈', Bronze: '🥉' };

  const html = slips.map(s => {
    const statusClass = `status-${s.status || 'pending'}`;
    const statusLabel = { won: '✅ Won', lost: '❌ Lost', pending: '⏳ Pending' }[s.status] || s.status;

    const tierBadge = s.tier
      ? `<span class="tier-badge tier-${s.tier.toLowerCase()} tier-badge-sm">${TIER_EMOJIS[s.tier] || ''} ${s.tier}</span>`
      : '';

    const legs = (s.legs || []).map(l => {
      let legIcon = '';
      if (l.won === true)  legIcon = '<span class="leg-won">✅</span>';
      else if (l.won === false) legIcon = '<span class="leg-lost">❌</span>';
      else if (s.status !== 'pending') legIcon = '<span class="leg-pending">⏳</span>';

      return `<div class="history-leg">
        <span>${legIcon} ${esc(l.home_team)} vs ${esc(l.away_team)}</span>
        <span class="history-leg-pick">${OUTCOME[l.pred_outcome] || l.pred_outcome} · ${l.pred_probability ? Math.round(l.pred_probability) : '—'}%</span>
      </div>`;
    }).join('');

    const payoutLine = s.payout_kes
      ? `<span class="payout-won">+KES ${fmt(s.payout_kes)}</span>`
      : `<span>KES ${fmt(s.stake_kes)} staked</span>`;

    const dateLabel = s.event_date || (s.created_at ? s.created_at.slice(0, 10) : '');

    return `
    <div class="history-card">
      <div class="history-header">
        <div class="history-header-left">
          <div class="history-sport">${capitalize(s.sport || '')} · ${s.slip_size}-leg</div>
          <div class="history-date">${dateLabel}</div>
        </div>
        <div class="history-header-right">
          ${tierBadge}
          <span class="status-badge ${statusClass}">${statusLabel}</span>
        </div>
      </div>
      <div class="history-legs">${legs}</div>
      <div class="history-footer">
        ${payoutLine}
        <span>Odds: ${s.total_combined_odds ? parseFloat(s.total_combined_odds).toFixed(2) + 'x' : '—'}</span>
      </div>
    </div>`;
  }).join('');

  $('historyContainer').innerHTML = `<div style="padding:12px 16px;display:flex;flex-direction:column;gap:10px">${html}</div>`;
}

// ── Render analytics ──────────────────────────────────────────────────────────
function renderAnalytics(analytics, teams) {
  const tiers = analytics?.tiers || [];
  const hasData = tiers.some(t => t.total > 0);

  // Tier performance table
  let tiersHtml = '';
  if (!hasData) {
    tiersHtml = noDataMsg('No resolved slips yet in this period. Results appear after games are settled.');
  } else {
    const maxEarned = Math.max(...tiers.map(t => t.earned_kes), 1);
    tiersHtml = tiers.map(t => {
      const barW = t.total > 0 ? Math.round(t.win_rate) : 0;
      const earnBar = t.earned_kes > 0 ? Math.round((t.earned_kes / maxEarned) * 100) : 0;
      const tierClass = t.tier.toLowerCase();
      return `
      <div class="analytics-tier-card tier-analytics-${tierClass}">
        <div class="analytics-tier-header">
          <span class="tier-badge tier-${tierClass}">${t.emoji} ${t.tier}</span>
          <span class="analytics-count">${t.total} slip${t.total !== 1 ? 's' : ''}</span>
        </div>
        <div class="analytics-stats">
          <div class="analytics-stat">
            <span class="analytics-stat-label">Win Rate</span>
            <div class="analytics-bar-wrap">
              <div class="analytics-bar analytics-bar-${tierClass}" style="width:${barW}%"></div>
            </div>
            <span class="analytics-stat-val">${barW}%</span>
          </div>
          <div class="analytics-stat">
            <span class="analytics-stat-label">Record</span>
            <span class="analytics-stat-val"><span class="won-text">${t.won}W</span> / <span class="lost-text">${t.lost}L</span></span>
          </div>
          <div class="analytics-stat">
            <span class="analytics-stat-label">Estimated Earnings</span>
            <div class="analytics-bar-wrap">
              <div class="analytics-bar analytics-bar-earn" style="width:${earnBar}%"></div>
            </div>
            <span class="analytics-stat-val earned-text">KES ${fmt(t.earned_kes)}</span>
          </div>
        </div>
      </div>`;
    }).join('');
  }

  // Top teams
  let teamsHtml = '';
  if (!teams?.length) {
    teamsHtml = `<p style="color:var(--hint);font-size:13px;text-align:center;padding:16px">No team data yet for this period.</p>`;
  } else {
    teamsHtml = teams.map(t => `
    <div class="team-row">
      <div class="team-name">${esc(t.team)}</div>
      <div class="team-bar-wrap"><div class="team-bar" style="width:${t.win_rate}%"></div></div>
      <div class="team-rate">${t.win_rate}%</div>
    </div>`).join('');
  }

  $('analyticsContainer').innerHTML = `
  <div style="padding:16px;display:flex;flex-direction:column;gap:16px">
    <div>
      <h3 class="section-title">📊 Performance by Tier</h3>
      <div style="display:flex;flex-direction:column;gap:10px">${tiersHtml}</div>
    </div>
    <div>
      <h3 class="section-title">🏆 Top Winning Teams</h3>
      <div class="teams-list">${teamsHtml}</div>
    </div>
  </div>`;
}

// ── Upload modal ──────────────────────────────────────────────────────────────
function initUploadModal() {
  $('uploadSlipBtn').addEventListener('click', () => {
    $('uploadOverlay').classList.remove('hidden');
    $('uploadStatus').classList.add('hidden');
    $('uploadFileInput').value  = '';
    $('uploadNoteInput').value  = '';
    $('uploadSubmitBtn').disabled = true;
  });

  $('uploadCancelBtn').addEventListener('click', () => {
    $('uploadOverlay').classList.add('hidden');
  });

  $('uploadFileInput').addEventListener('change', () => {
    $('uploadSubmitBtn').disabled = !$('uploadFileInput').files?.length;
  });

  $('uploadSubmitBtn').addEventListener('click', async () => {
    const file = $('uploadFileInput').files?.[0];
    if (!file) return;

    const uid = String(tgUser?.id || currentUser?.user_id || 'anon');
    const fd  = new FormData();
    fd.append('telegram_user_id', uid);
    fd.append('note',  $('uploadNoteInput').value.trim());
    fd.append('file',  file);

    $('uploadSubmitBtn').disabled = true;
    $('uploadSubmitBtn').textContent = 'Uploading…';

    const status = $('uploadStatus');
    status.classList.remove('hidden', 'upload-ok', 'upload-err');
    try {
      const res  = await fetch('/api/slips/upload-image', { method: 'POST', body: fd });
      const data = await res.json();
      if (data.status === 'ok') {
        status.textContent = '✅ Uploaded! Your slip is saved.';
        status.classList.add('upload-ok');
        setTimeout(() => $('uploadOverlay').classList.add('hidden'), 1800);
      } else {
        throw new Error(data.detail || 'Upload failed');
      }
    } catch (err) {
      status.textContent = `⚠️ ${err.message || 'Upload failed. Try again.'}`;
      status.classList.add('upload-err');
      $('uploadSubmitBtn').disabled = false;
    }
    $('uploadSubmitBtn').textContent = 'Upload';
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt(n)        { return Number(n).toLocaleString('en-KE'); }
function capitalize(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : ''; }
function esc(str) {
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
