/* Flup: renders data/latest.json. Shows the last saved copy instantly, then
   checks for newer data in the background. */
(function () {
  'use strict';

  const DATA_URL = 'data/latest.json';
  const DATA_KEY = 'flup:data';
  const UI_KEY = 'flup:ui';
  const FILTERS = [['all', 'All'], ['mine', 'My team'], ['fa', 'Free agents'], ['matchup', 'My matchup']];
  const EMPTY = {
    all: 'No projections at this position yet.',
    mine: 'None of your players are projected here this week.',
    fa: 'No free agents rank here this week.',
    matchup: 'Neither team in your matchup has a player here this week.',
  };
  const STAT_NAMES = {
    pass_yd: 'Passing yards', pass_td: 'Passing TDs', pass_int: 'Interceptions thrown',
    pass_2pt: 'Passing 2-pt', rush_yd: 'Rushing yards', rush_td: 'Rushing TDs', rush_2pt: 'Rushing 2-pt',
    rec: 'Catches', bonus_rec_te: 'TE bonus per catch', rec_yd: 'Receiving yards', rec_td: 'Receiving TDs',
    rec_2pt: 'Receiving 2-pt', fum: 'Fumbles', fum_lost: 'Fumbles lost', fum_rec_td: 'Fumble return TD',
    kr_yd: 'Kick return yards', pr_yd: 'Punt return yards', st_td: 'Return TD',
    xpm: 'Extra points made', xpmiss: 'Extra points missed', fgmiss: 'Field goals missed',
    fgm_0_19: 'FG made 0-19', fgm_20_29: 'FG made 20-29', fgm_30_39: 'FG made 30-39',
    fgm_40_49: 'FG made 40-49', fgm_50p: 'FG made 50+',
    sack: 'Sacks', int: 'Interceptions', fum_rec: 'Fumble recoveries', ff: 'Forced fumbles',
    def_td: 'Defensive TDs', def_st_td: 'Return TDs', def_st_ff: 'ST forced fumbles',
    def_st_fum_rec: 'ST fumble recoveries', st_ff: 'ST forced fumbles', st_fum_rec: 'ST fumble recoveries',
    safe: 'Safeties', blk_kick: 'Blocked kicks', def_4_and_stop: '4th-down stops',
    pts_allow: 'Points allowed (avg)', yds_allow: 'Yards allowed (avg)',
  };

  let data = null;
  let ui = Object.assign({ pos: 'QB', filter: 'all' }, read(UI_KEY) || {});
  const open = new Set();

  // ---------- small helpers ----------

  function read(key) {
    try { return JSON.parse(localStorage.getItem(key)); } catch (e) { return null; }
  }
  function write(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode */ }
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  const $ = (sel) => document.querySelector(sel);
  const pts = (n) => (n == null ? '–' : Number(n).toFixed(1));
  function num(n) {
    return n == null ? '–' : String(Math.round(n * 100) / 100);
  }
  function signed(n) { return n > 0 ? '+' + num(n) : num(n); }
  function when(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' });
  }
  function ago(iso) {
    const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (mins < 2) return 'just now';
    if (mins < 60) return mins + ' min ago';
    const h = Math.round(mins / 60);
    if (h < 36) return h + ' h ago';
    return Math.round(h / 24) + ' days ago';
  }
  function hoursOld(iso) { return (Date.now() - new Date(iso).getTime()) / 3600000; }
  function statName(key) {
    if (STAT_NAMES[key]) return STAT_NAMES[key];
    const m = key.match(/^pts_allow_(.+)$/);
    if (m) return 'Allowed ' + m[1].replace('_', '-').replace('p', '+') + ' pts';
    return key.replace(/_/g, ' ');
  }
  function toast(text) {
    const el = $('#toast');
    el.textContent = text;
    el.hidden = false;
    clearTimeout(toast.t);
    toast.t = setTimeout(() => { el.hidden = true; }, 3200);
  }
  function saveUi() { write(UI_KEY, ui); }

  // ---------- who owns a player ----------

  function owner(p) {
    const lg = data.league;
    if (p.roster == null) return { cls: 'fa', label: 'Free agent', kind: 'fa' };
    if (p.roster === lg.my_rid) return { cls: 'mine', label: 'You', kind: 'mine' };
    const team = (lg.teams[p.roster] || {}).name || 'Team ' + p.roster;
    if (p.roster === lg.opp_rid) return { cls: 'opp', label: 'Opponent', kind: 'opp', team };
    return { cls: '', label: team, kind: 'owned', team };
  }
  function injClass(s) {
    if (!s) return '';
    return /^(questionable)$/i.test(s) ? 'q' : 'out';
  }
  function injShort(s) {
    const m = { Questionable: 'Q', Doubtful: 'D', Out: 'OUT', IR: 'IR', PUP: 'PUP', Sus: 'SUS', NA: 'NA' };
    return m[s] || s;
  }
  function gameState(p) {
    const s = p.game_status || '';
    if (s === 'STATUS_FINAL') return 'Played';
    if (/IN_PROGRESS|HALFTIME|END_PERIOD/.test(s)) return 'Live';
    return '';
  }
  function gameText(p) {
    if (!p.opp) return p.team;
    return p.team + (p.home === false ? ' @ ' : ' vs ') + p.opp;
  }

  // ---------- header and status ----------

  function renderHeader() {
    const lg = data.league;
    $('#title').textContent = 'Week ' + data.week;
    $('#league-line').textContent = lg.name + ' · ' + data.season;
    const me = lg.teams[lg.my_rid];
    const opp = lg.teams[lg.opp_rid];
    const rec = (t) => `<span class="rec">${t.wins}-${t.losses}${t.ties ? '-' + t.ties : ''}</span>`;
    let html = '';
    if (me) html += `<span class="chip mine">${esc(me.name)}</span> ${rec(me)}`;
    if (opp) html += ` <span class="vs">vs</span> <span class="chip opp">${esc(opp.name)}</span> ${rec(opp)}`;
    else if (me) html += ' <span class="vs">no opponent found this week</span>';
    $('#matchup').innerHTML = html;
    document.title = 'Week ' + data.week + ' · Flup';
  }

  function problems() {
    const out = [];
    const stale = data.settings.stale_hours || 36;
    if (hoursOld(data.generated) > stale) {
      out.push(`This data is ${ago(data.generated).replace(' ago', '')} old. Tap refresh, or run "Update data" in GitHub Actions.`);
    }
    for (const s of data.sources) {
      if (!s.ok) out.push(`${s.label} didn't load: ${s.detail}`);
    }
    const bad = data.checks.settings.filter((c) => !c.ok);
    if (bad.length) {
      out.push('League settings differ from what you expected: ' +
        bad.map((c) => `${c.label} is ${c.actual} (expected ${c.expected})`).join('; ') + '.');
    }
    const misses = data.checks.scoring.reduce((n, w) => n + ((w.misses || []).length) + (w.error ? 1 : 0), 0);
    if (misses) out.push(`Scoring check found ${misses} mismatch${misses > 1 ? 'es' : ''} with Sleeper's official points. Tap the checks line for details.`);
    return out;
  }

  // ---------- status line + checks (collapsed) ----------

  const mark = (ok) => `<span class="${ok ? 'ok' : 'bad'}">${ok ? '✓' : '✗'}</span>`;

  function checksBody() {
    const set = data.checks.settings;
    const setOk = set.filter((c) => c.ok).length;
    const weeks = data.checks.scoring.filter((w) => w.week);
    const matched = weeks.reduce((n, w) => n + w.matched, 0);
    const checked = weeks.reduce((n, w) => n + w.checked, 0);
    const scoringOk = matched === checked && !data.checks.scoring.some((w) => w.error);
    const sourcesOk = data.sources.every((s) => s.ok);
    const range = weeks.length ? `Week${weeks.length > 1 ? 's' : ''} ${weeks[0].week}${weeks.length > 1 ? '–' + weeks[weeks.length - 1].week : ''}` : 'no finished weeks yet';
    const t = data.settings.tiers;

    let html = `<details class="check"><summary>${mark(setOk === set.length)} League settings match what you told me (${setOk} of ${set.length})</summary>
      <table class="checks"><thead><tr><th>Setting</th><th class="n">You said</th><th class="n">Sleeper</th><th class="n"></th></tr></thead><tbody>
      ${set.map((c) => `<tr><td>${esc(c.label)}</td><td class="n">${esc(c.expected)}</td><td class="n">${esc(c.actual == null ? '?' : c.actual)}</td><td class="n">${mark(c.ok)}</td></tr>`).join('')}
      </tbody></table></details>`;

    html += `<details class="check"><summary>${mark(scoringOk)} Points here match Sleeper's official scoring (${matched} of ${checked})</summary>
      <p>For ${esc(range)}, every rostered player's real stats were rescored with your league's settings and compared to the points Sleeper actually gave him.</p>
      ${weeks.map((w) => `<p>${mark(!w.misses.length)} Week ${w.week}: ${w.matched} of ${w.checked}</p>`).join('')}
      ${weeks.flatMap((w) => w.misses.map((m) => `<p class="warn">Week ${w.week}: ${esc(m.name)} (${esc(m.pos)}) here ${num(m.ours)}, Sleeper ${num(m.official)}</p>`)).join('')}
      ${data.checks.scoring.filter((x) => x.error).map((x) => `<p class="warn">${esc(x.error)}</p>`).join('')}
      </details>`;

    html += `<details class="check"><summary>${mark(sourcesOk)} Data sources loaded</summary>
      ${data.sources.map((s) => `<p>${mark(s.ok)} <b>${esc(s.label)}</b>: ${esc(s.detail)}${s.updated ? `. Updated ${esc(when(s.updated))}` : ''}</p>`).join('')}
      </details>`;

    html += `<details class="check"><summary>How tiers work</summary>
      <p>Going down each position, a new tier starts at a big drop: a gap more than ${t.gap_multiplier}× the usual gap between nearby players.
      Tiers keep at least ${t.min_tier_size} players unless the drop is ${t.always_break_gap}+ points. Players in the same tier are close enough to treat as even.</p>
      </details>`;
    return html;
  }

  function renderStatus() {
    const issues = problems();
    let html = issues.map((t) => `<p class="warn">${esc(t)}</p>`).join('');
    html += `<details class="health"><summary>
        <span>Data from ${esc(when(data.generated))} (${esc(ago(data.generated))})</span>
        <span class="${issues.length ? 'bad' : 'ok'}">${issues.length ? '✗ Checks' : '✓ All checks pass'}</span>
      </summary><div class="health-body">${checksBody()}</div></details>`;
    $('#status').innerHTML = html;
  }

  // ---------- tiers ----------

  function renderTabs() {
    const positions = Object.keys(data.positions);
    if (!positions.includes(ui.pos)) ui.pos = positions[0];
    $('#pos-tabs').innerHTML = positions.map((pos) =>
      `<button type="button" role="tab" data-pos="${pos}" aria-selected="${pos === ui.pos}">${pos}</button>`).join('');
    $('#filters').innerHTML = FILTERS.map(([key, label]) =>
      `<button type="button" data-filter="${key}" aria-pressed="${key === ui.filter}">${label}</button>`).join('');
  }

  function keep(p) {
    const kind = owner(p).kind;
    if (ui.filter === 'all') return true;
    if (ui.filter === 'matchup') return kind === 'mine' || kind === 'opp';
    return kind === ui.filter;
  }

  function playerRow(p) {
    const o = owner(p);
    const inj = p.injury ? `<span class="inj ${injClass(p.injury)}" title="${esc(p.injury)}">${esc(injShort(p.injury))}</span>` : '';
    const state = gameState(p);
    const isOpen = open.has(p.id);
    const sub = [
      `<span>${esc(gameText(p))}</span>`,
      state ? `<span class="played">${state}</span>` : (p.kickoff ? `<span>${esc(when(p.kickoff))}</span>` : ''),
      `<span class="chip ${o.cls}" title="${esc(o.team || o.label)}">${esc(o.label)}</span>`,
    ].join('');
    return `<li class="player ${o.kind === 'mine' || o.kind === 'opp' ? o.kind : ''}" data-id="${esc(p.id)}">
      <button type="button" class="row" aria-expanded="${isOpen}">
        <span class="rk">${p.rank}</span>
        <span class="nm">${esc(p.name)}${inj}</span>
        <span class="pts">${pts(p.proj)}</span>
        <span class="sub">${sub}</span>
      </button>${isOpen ? detail(p) : ''}</li>`;
  }

  function renderTiers() {
    const block = data.positions[ui.pos];
    const breaks = {};
    block.breaks.forEach((b, i) => { breaks[i + 2] = b; });
    const groups = new Map();
    const below = [];
    for (const p of block.players) {
      if (!keep(p)) continue;
      if (p.tier == null) below.push(p);
      else {
        if (!groups.has(p.tier)) groups.set(p.tier, []);
        groups.get(p.tier).push(p);
      }
    }
    let html = '';
    for (const [tier, players] of groups) {
      const b = breaks[tier];
      const gap = b ? `<p class="tier-gap">▼ ${pts(b.gap)} pt drop from tier ${tier - 1} (${b.ratio}× the nearby gaps)</p>` : '';
      html += `<div class="tier">${gap}<div class="tier-num" aria-label="Tier ${tier}">${tier}</div>
        <ul class="players">${players.map(playerRow).join('')}</ul></div>`;
    }
    if (below.length) {
      const cut = data.settings.positions[ui.pos];
      html += `<p class="below">Below the top ${cut} (not tiered)</p><ul class="players">${below.map(playerRow).join('')}</ul>`;
    }
    $('#tiers').innerHTML = html || `<p class="empty">${EMPTY[ui.filter]}</p>`;
  }

  // ---------- player detail ----------

  const SHORT = {
    pass_yd: 'passing yards', pass_td: 'passing TDs', pass_int: 'interceptions',
    rush_yd: 'rushing yards', rush_td: 'rushing TDs', rec: 'catches', rec_yd: 'receiving yards',
    rec_td: 'receiving TDs', bonus_rec_te: 'TE catch bonus', kr_yd: 'kick return yards',
    pr_yd: 'punt return yards', fgm: 'field goals', xpm: 'extra points', fgmiss: 'missed field goals',
    sack: 'sacks', int: 'interceptions', fum_rec: 'fumble recoveries', ff: 'forced fumbles',
    def_td: 'defensive TDs', pts_allow: 'points allowed', safe: 'safeties', blk_kick: 'blocked kicks',
    fum: 'fumbles', fum_lost: 'lost fumbles',
  };

  // Field goals by distance read better as one line
  function merged(parts) {
    const out = new Map();
    for (const [stat, value, , points] of parts) {
      const key = /^fgm_/.test(stat) ? 'fgm' : stat;
      const m = out.get(key) || { stat: key, value: 0, points: 0 };
      m.value += value;
      m.points += points;
      out.set(key, m);
    }
    return [...out.values()];
  }

  function phrase(s) {
    const name = SHORT[s.stat] || statName(s.stat).toLowerCase();
    const delta = (s.points >= 0 ? '+' : '−') + Math.abs(s.points).toFixed(1);
    if (s.stat === 'bonus_rec_te') return `the ${name} (${delta})`;
    if (s.stat === 'pts_allow') return `about ${Math.round(s.value)} ${name} (${delta})`;
    const amount = /_yd$/.test(s.stat) ? Math.round(s.value) : Math.round(s.value * 10) / 10;
    return `${amount} ${name} (${delta})`;
  }

  function andList(items) {
    return items.length < 2 ? items.join('') : items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1];
  }

  // One plain sentence: the 2-3 stats that make up most of the projection,
  // plus the biggest penalty if it costs a point or more.
  function projectionSentence(p) {
    const all = merged(p.parts);
    const gains = all.filter((s) => s.points > 0).sort((a, b) => b.points - a.points);
    const picks = [];
    let covered = 0;
    for (const s of gains) {
      if (picks.length === 3 || (picks.length >= 2 && covered >= 0.7 * p.proj)) break;
      picks.push(s);
      covered += s.points;
    }
    const penalty = all.filter((s) => s.points <= -1).sort((a, b) => a.points - b.points)[0];
    let text = `<b>${pts(p.proj)} pts</b> in your scoring`;
    if (picks.length) text += ', mostly from ' + andList(picks.map(phrase));
    if (penalty) text += ', minus ' + phrase(penalty);
    return text + '.';
  }

  function detail(p) {
    const block = data.positions[p.pos];
    const rows = p.parts.map(([stat, value, weight, points]) => {
      const calc = weight == null ? `${num(value)} → bracket blend` : `${num(value)} × ${num(weight)}`;
      return `<tr><td>${esc(statName(stat))}</td><td class="n x">${esc(calc)}</td><td class="n">${signed(points)}</td></tr>`;
    }).join('');
    let html = `<div class="detail">
      <h3>Projection</h3>
      <p>${projectionSentence(p)}</p>
      <details class="every"><summary>See every stat</summary>
        <table class="math"><tbody>${rows}</tbody></table>
      </details>`;

    html += '<h3>Game</h3>';
    html += `<p>${esc(gameText(p))}${p.kickoff ? ' · ' + esc(when(p.kickoff)) : ''}${gameState(p) ? ' · ' + gameState(p) : ''}</p>`;
    if (p.implied != null) {
      html += `<p>${esc(p.team)} ${p.spread > 0 ? '+' : ''}${num(p.spread)}, total ${num(p.implied * 2 + p.spread)} → implied for <b>${num(p.implied)}</b> pts</p>`;
    } else if (!gameState(p)) {
      html += '<p>No Vegas line posted yet.</p>';
    }

    if (p.injury) {
      html += `<h3>Injury</h3><p><b>${esc(p.injury)}</b>${p.injury_detail ? ' (' + esc(p.injury_detail) + ')' : ''}</p>`;
    }

    if (p.tier != null) {
      const total = block.breaks.length + 1;
      const b = block.breaks[p.tier - 2];
      html += '<h3>Tier</h3>';
      html += `<p>Tier ${p.tier} of ${total}, rank ${p.rank} at ${esc(p.pos)}.`;
      if (b) {
        html += ` This tier starts after a ${pts(b.gap)} pt gap; nearby gaps are about ${num(b.local_median)} pts (${b.ratio}×)`;
        html += b.big_gap ? ', big enough to split on its own.' : '.';
      }
      html += '</p>';
    }
    return html + '</div>';
  }

  // ---------- render ----------

  function render() {
    if (!data) return;
    renderHeader();
    renderStatus();
    renderTabs();
    renderTiers();
  }

  document.addEventListener('click', (e) => {
    const t = e.target.closest('button');
    if (!t) return;
    if (t.dataset.pos) { ui.pos = t.dataset.pos; saveUi(); renderTabs(); renderTiers(); return; }
    if (t.dataset.filter) { ui.filter = t.dataset.filter; saveUi(); renderTabs(); renderTiers(); return; }
    if (t.classList.contains('row')) {
      const id = t.closest('.player').dataset.id;
      if (open.has(id)) open.delete(id); else open.add(id);
      renderTiers();
    }
  });

  $('#theme-btn').addEventListener('click', () => {
    const root = document.documentElement;
    root.dataset.theme = root.dataset.theme === 'light' ? 'dark' : 'light';
    try { localStorage.setItem('flup:theme', root.dataset.theme); } catch (e) { /* ignore */ }
    document.querySelector('meta[name=theme-color]').content = root.dataset.theme === 'light' ? '#F7F9F8' : '#121815';
  });

  // ---------- data loading ----------

  async function refresh(manual) {
    const btn = $('#refresh-btn');
    btn.classList.add('spin');
    try {
      const resp = await fetch(DATA_URL + '?t=' + Date.now(), { cache: 'no-store' });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const fresh = await resp.json();
      const changed = !data || fresh.generated !== data.generated;
      data = fresh;
      write(DATA_KEY, fresh);
      if (changed) render();
      if (manual) toast(changed ? 'New data loaded' : 'Up to date: data from ' + when(fresh.generated));
    } catch (err) {
      if (data) {
        if (manual) toast("Couldn't reach the site. Showing saved data.");
      } else {
        $('#status').innerHTML = `<p class="warn">Couldn't load the data (${esc(err.message)}). Check your connection and tap refresh.</p>`;
      }
    } finally {
      btn.classList.remove('spin');
    }
  }

  $('#refresh-btn').addEventListener('click', () => refresh(true));
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && data && hoursOld(data.generated) > 0.5) refresh(false);
  });

  data = read(DATA_KEY);
  if (data && data.version !== 1) data = null;
  render();
  refresh(false);

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => { navigator.serviceWorker.register('sw.js').catch(() => {}); });
  }
})();
