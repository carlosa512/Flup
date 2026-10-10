/* Flup: renders data/latest.json. Shows the last saved copy instantly, then
   checks for newer data in the background. */
(function () {
  'use strict';

  const DATA_URL = 'data/latest.json';
  // Keyed by path so the main site and /preview/ don't share saved data
  const DATA_KEY = 'flup:data:' + location.pathname;
  const UI_KEY = 'flup:ui:' + location.pathname;
  const DATA_VERSION = 3;  // the data format this app reads
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
  let view = 'lineup';  // the app always opens on the lineup
  let index = new Map();  // player id -> player
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
    const setLine = setOk === set.length
      ? `League settings match what you told me (${setOk} of ${set.length})`
      : (set.length - setOk === 1 ? "1 league setting doesn't" : `${set.length - setOk} league settings don't`) + ' match what you told me';
    const scoringLine = scoringOk
      ? `Points here match Sleeper's official scoring (${matched} of ${checked})`
      : (checked - matched === 1 ? "1 player's points don't" : `${checked - matched || 'Some'} players' points don't`) + " match Sleeper's official scoring";

    let html = `<details class="check"><summary>${mark(setOk === set.length)} ${esc(setLine)}</summary>
      <table class="checks"><thead><tr><th>Setting</th><th class="n">You said</th><th class="n">Sleeper</th><th class="n"></th></tr></thead><tbody>
      ${set.map((c) => `<tr><td>${esc(c.label)}</td><td class="n">${esc(c.expected)}</td><td class="n">${esc(c.actual == null ? '?' : c.actual)}</td><td class="n">${mark(c.ok)}</td></tr>`).join('')}
      </tbody></table></details>`;

    html += `<details class="check"><summary>${mark(scoringOk)} ${esc(scoringLine)}</summary>
      <p>For ${esc(range)}, every rostered player's real stats were rescored with your league's settings and compared to the points Sleeper actually gave him.</p>
      ${weeks.map((w) => `<p>${mark(!w.misses.length)} Week ${w.week}: ${w.matched} of ${w.checked}</p>`).join('')}
      ${weeks.flatMap((w) => w.misses.map((m) => `<p class="warn">Week ${w.week}: ${esc(m.name)} (${esc(m.pos)}) here ${num(m.ours)}, Sleeper ${num(m.official)}</p>`)).join('')}
      ${data.checks.scoring.filter((x) => x.error).map((x) => `<p class="warn">${esc(x.error)}</p>`).join('')}
      </details>`;

    html += `<details class="check"><summary>${mark(sourcesOk)} ${sourcesOk ? 'Data sources loaded' : "A data source didn't load"}</summary>
      ${data.sources.map((s) => `<p>${mark(s.ok)} <b>${esc(s.label)}</b>: ${esc(s.detail)}${s.updated ? `. Updated ${esc(when(s.updated))}` : ''}</p>`).join('')}
      </details>`;

    html += `<details class="check"><summary>How tiers work</summary>
      <p>Going down each position, a new tier starts at a big drop: a gap more than ${t.gap_multiplier}× the usual gap between nearby players.
      Tiers keep at least ${t.min_tier_size} players unless the drop is ${t.always_break_gap}+ points. Players in the same tier are close enough to treat as even.</p>
      </details>`;
    return { html, ok: setOk === set.length && scoringOk && sourcesOk };
  }

  function renderStatus() {
    const issues = problems();
    const checks = checksBody();
    // Old data has its own red box above; the badge only reflects the checks
    let html = issues.map((t) => `<p class="warn">${esc(t)}</p>`).join('');
    html += `<details class="health"><summary>
        <span>Data from ${esc(when(data.generated))} (${esc(ago(data.generated))})</span>
        <span class="badge ${checks.ok ? 'ok' : 'bad'}">${checks.ok ? '✓ All checks pass' : "✗ Something's off, tap to see"}</span>
      </summary><div class="health-body">${checks.html}</div></details>`;
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
        <span class="pts">${pts(p.score)}</span>
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
    let shown = null;
    for (const [tier, players] of groups) {
      const b = breaks[tier];
      // A filter can hide whole tiers; the drop only reads right right under the tier it's from
      const gap = b && shown === tier - 1 ? `<p class="tier-gap">▼ ${pts(b.gap)} pt drop from tier ${tier - 1} (${b.ratio}× the nearby gaps)</p>` : '';
      html += `${gap}<div class="tier"><div class="tier-num" aria-label="Tier ${tier}">${tier}</div>
        <ul class="players">${players.map(playerRow).join('')}</ul></div>`;
      shown = tier;
    }
    if (below.length) {
      const cut = data.settings.positions[ui.pos];
      html += `<p class="below">Below the top ${cut} (not tiered)</p><div class="tier flat"><ul class="players">${below.map(playerRow).join('')}</ul></div>`;
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

  // Field goals by distance read better as one line; a TE's catch bonus
  // is shown as part of his catches
  function merged(parts) {
    const out = new Map();
    for (const [stat, value, , points] of parts) {
      const key = /^fgm_/.test(stat) ? 'fgm' : stat === 'bonus_rec_te' ? 'rec' : stat;
      const m = out.get(key) || { stat: key, value: 0, points: 0 };
      if (stat !== 'bonus_rec_te') m.value += value;  // same catches, counted once
      m.points += points;
      out.set(key, m);
    }
    return [...out.values()];
  }

  function phrase(s) {
    const name = SHORT[s.stat] || statName(s.stat).toLowerCase();
    const delta = (s.points >= 0 ? '+' : '−') + Math.abs(s.points).toFixed(1);
    if (s.stat === 'pts_allow') return `about ${Math.round(s.value)} ${name} (${delta})`;
    if (/_td$|int$/.test(s.stat)) return `${name} (${delta})`;  // "0.4 TDs" reads oddly
    const amount = /_yd$/.test(s.stat) ? String(Math.round(s.value)) : s.value.toFixed(1);
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
    let text = `Sleeper projects <b>${pts(p.proj)}</b> in your scoring`;
    if (picks.length) text += ', mostly from ' + andList(picks.map(phrase));
    if (penalty) text += ', minus ' + phrase(penalty);
    return text + '.';
  }

  function signedPts(n) {
    return (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(n).toFixed(1);
  }

  // Lines worth showing on their own: half a point or more, plus injury
  // and return yards (real points). Smaller tweaks fold into one line.
  const BIG = 0.5;
  function adjRow(a) {
    return `<li><span class="adj-pts ${a.pts > 0 ? 'up' : 'down'}">${signedPts(a.pts)}</span>
      <span><b>${esc(a.label)}</b><small>${esc(a.why)}</small></span></li>`;
  }

  function myScore(p) {
    const r = p.range;
    const out = p.flag && p.flag !== 'Doubtful';
    if (out) {
      return `<p class="warn">${esc(p.flag)}${p.injury_detail ? ' (' + esc(p.injury_detail) + ')' : ''}: not playing. Start someone else.</p>`
        + (r ? `<p class="muted">If he were playing: ${pts(r.floor)}–${pts(r.ceiling)}</p>` : '');
    }
    if (p.note) return `<p>${esc(p.note)}.</p>`;
    let html = `<div class="score-head"><b class="big">${pts(p.score)}</b>`;
    if (r) html += `<span>${r.if_plays ? 'If he plays: ' : ''}Floor ${pts(r.floor)} · Ceiling ${pts(r.ceiling)}</span>`;
    html += '</div>';
    if (p.flag === 'Doubtful') html += '<p class="warn">Doubtful: likely sits. Have a backup ready.</p>';
    const c = p.cons;
    let start = p.proj > 0 ? `Projection ${pts(p.proj)}` : 'No projection';
    if (c && c.pts != null) start += ` · Experts ${esc(p.pos)}${c.rank} (${pts(c.pts)})`;
    html += `<p class="muted">${start} → ${pts(p.base)}</p>`;
    const big = p.adj.filter((a) => Math.abs(a.pts) >= BIG || a.key === 'injury' || a.key === 'returns');
    const small = p.adj.filter((a) => !big.includes(a));
    if (big.length) html += '<ul class="adj">' + big.map(adjRow).join('') + '</ul>';
    if (small.length) {
      const sum = small.reduce((n, a) => n + a.pts, 0);
      html += `<details class="every"><summary>${signedPts(sum)} from ${small.length} small tweak${small.length > 1 ? 's' : ''}</summary>
        <ul class="adj">${small.map(adjRow).join('')}</ul></details>`;
    }
    return html;
  }

  function detail(p) {
    const block = data.positions[p.pos];
    const rows = p.parts.map(([stat, value, weight, points]) => {
      const calc = weight == null ? `${num(value)} → bracket blend` : `${num(value)} × ${num(weight)}`;
      return `<tr><td>${esc(statName(stat))}</td><td class="n x">${esc(calc)}</td><td class="n">${signed(points)}</td></tr>`;
    }).join('');
    let html = `<div class="detail"><h3>My Score</h3>${myScore(p)}`;
    if (p.parts.length) {
      html += `<details class="every"><summary>How the projection adds up</summary>
          <p>${projectionSentence(p)}</p>
          <table class="math"><tbody>${rows}</tbody></table>
        </details>`;
    }

    html += '<h3>Game</h3>';
    html += `<p>${esc(gameText(p))}${p.kickoff ? ' · ' + esc(when(p.kickoff)) : ''}${gameState(p) ? ' · ' + gameState(p) : ''}</p>`;
    if (p.implied != null) {
      html += `<p>${esc(p.team)} ${p.spread > 0 ? '+' : ''}${num(p.spread)}, total ${num(p.implied * 2 + p.spread)} → implied for <b>${num(p.implied)}</b> pts</p>`;
    } else if (!gameState(p)) {
      html += '<p>No Vegas line posted yet.</p>';
    }

    if (p.tier != null) {
      html += `<h3>Tier</h3><p>Tier ${p.tier} of ${block.breaks.length + 1} · rank ${p.rank} at ${esc(p.pos)}</p>`;
    }
    return html + '</div>';
  }

  // ---------- lineup ----------

  const MODE = {
    favored: { word: 'Favored', line: 'playing it safe', cls: 'fav' },
    underdog: { word: 'Underdog', line: 'swinging for upside', cls: 'dog' },
    even: { word: 'Close matchup', line: 'going with My Score', cls: 'even' },
  };
  const SLOT_SHORT = { SUPER_FLEX: 'SF', WRRB_FLEX: 'W/R', REC_FLEX: 'W/T' };
  const SINGLE = new Set(['QB', 'RB', 'WR', 'TE', 'K', 'DEF']);
  const pct = (x) => Math.round(x * 100) + '%';
  const nameOf = (id) => (index.get(id) || {}).name || 'Unknown player';

  function lineupRow(e, side) {
    const multi = !SINGLE.has(e.slot);
    const p0 = e.id ? index.get(e.id) : null;
    const slot = multi && p0
      ? `<span class="slot flex"><small>${esc(SLOT_SHORT[e.slot] || e.slot)}</small>${esc(p0.pos)}</span>`
      : `<span class="slot">${esc(SLOT_SHORT[e.slot] || e.slot)}</span>`;
    if (!e.id) {
      const why = side === 'me' ? 'No healthy player with a game for this slot.' : 'Nobody in this slot.';
      return `<li class="player empty-slot"><div class="row lu">${slot}<span class="nm">Empty</span>
        <span class="pts">${pts(0)}</span><span class="sub">${why}</span></div></li>`;
    }
    const p = index.get(e.id);
    if (!p) {
      return `<li class="player"><div class="row lu">${slot}<span class="nm">Unknown player</span>
        <span class="pts">${pts(e.pts)}</span><span class="sub">Not in this week's projections</span></div></li>`;
    }
    const inj = p.injury ? `<span class="inj ${injClass(p.injury)}" title="${esc(p.injury)}">${esc(injShort(p.injury))}</span>` : '';
    const state = e.state === 'final' ? 'Played' : e.state === 'live' ? 'Live' : '';
    const sub = [
      `<span>${esc(gameText(p))}</span>`,
      state ? `<span class="played">${state}</span>` : (p.kickoff ? `<span>${esc(when(p.kickoff))}</span>` : ''),
      e.new ? '<span class="chip new">New</span>' : '',
    ].join('');
    let why = side === 'me' ? e.why || '' : '';
    if (side !== 'me' && e.state === 'live') why = `${pts(e.actual)} so far, ${Math.round(e.left * 100)}% of the game left`;
    const isOpen = open.has(p.id);
    return `<li class="player ${e.new ? 'new' : ''}" data-id="${esc(p.id)}">
      <button type="button" class="row lu" aria-expanded="${isOpen}">
        ${slot}
        <span class="nm">${esc(p.name)}${inj}</span>
        <span class="pts">${pts(e.pts)}</span>
        <span class="sub">${sub}</span>
        ${why ? `<span class="why">${esc(why)}</span>` : ''}
      </button>${isOpen ? detail(p) : ''}</li>`;
  }

  function lineupMath(L) {
    const me = L.me, opp = L.opp, f = L.first;
    const diff = me.total - opp.total;
    const comb = Math.sqrt(me.sd * me.sd + opp.sd * opp.sd);
    const lean = Math.round(L.lean * 100) + '%';
    let html = `<p>Each starter counts his expected points: My Score if his game hasn't started,
      points so far plus My Score for the part of the game left if it's live, and his actual points once it's over.</p>`;
    html += `<p>You <b>${pts(me.total)}</b> (give or take ${pts(me.sd)}) vs them <b>${pts(opp.total)}</b>
      (give or take ${pts(opp.sd)}). Their lineup is counted exactly as set in Sleeper.</p>`;
    if (comb > 0) {
      html += `<p>Win % is the chance your total ends up higher: ${signedPts(diff)} ÷ √(${pts(me.sd)}² + ${pts(opp.sd)}²)
        = ${signedPts(diff)} ÷ ${pts(comb)} = ${(diff < 0 ? '−' : '') + Math.abs(diff / comb).toFixed(2)} on the bell curve → <b>${pct(L.win)}</b>.</p>`;
    }
    if (L.mode === 'even') {
      html += `<p>Your best lineup by My Score wins ${pct(f.win)} of the time. That's between ${pct(L.underdog)} and
        ${pct(L.favored)}, so players are ranked by My Score as is.</p>`;
    } else {
      const dog = L.mode === 'underdog';
      html += `<p>Your best lineup by My Score wins ${pct(f.win)} of the time. That's ${dog ? 'under ' + pct(L.underdog) + ': underdog' : pct(L.favored) + ' or more: favored'}.
        So players are ranked by <b>${dog ? 'upside score' : 'safe score'}</b>: My Score moved ${lean} of the way
        ${dog ? 'up to his ceiling, which favors boom-or-bust players' : 'down to his floor, which favors steady players'}.
        Final lineup: ${pct(L.win)}.</p>`;
      if (L.win < f.win) {
        html += `<p>The bell curve above rates that a bit lower (${pct(L.win)} vs ${pct(f.win)}): it only sees averages and
          spread, not the ${dog ? 'long upside tail a ceiling measures' : 'protection a high floor gives'}.</p>`;
      }
    }
    html += `<p class="muted">This treats every player as scoring on his own. Teammates (a QB and his receivers)
      really boom or bust together, so the true chance can be a few points higher or lower.</p>`;
    return html;
  }

  function verdict(L) {
    const opp = data.league.teams[data.league.opp_rid];
    if (!L.opp || L.win == null) {
      return `<div class="verdict"><p class="mode-line">No opponent found this week</p>
        <div class="totals"><div><span class="lbl">You</span><b>${pts(L.me.total)}</b></div></div></div>`;
    }
    const m = MODE[L.mode] || MODE.even;
    return `<div class="verdict ${m.cls}">
      <p class="mode-line"><b>${m.word} ${pct(L.win)}</b>: ${m.line}</p>
      <div class="winbar" role="img" aria-label="${pct(L.win)} chance to win"><span style="width:${(L.win * 100).toFixed(1)}%"></span></div>
      <div class="totals">
        <div><span class="lbl">You</span><b>${pts(L.me.total)}</b></div>
        <div class="them"><span class="lbl">${esc(opp ? opp.name : 'Them')}</span><b>${pts(L.opp.total)}</b></div>
      </div>
      <details class="every" data-k="math"><summary>How this is worked out</summary><div class="math-text">${lineupMath(L)}</div></details>
    </div>`;
  }

  function changesBox(L) {
    const moves = L.moves || [];
    if (!L.changes.length && !moves.length) return '<p class="note done">✓ Your Sleeper lineup already matches.</p>';
    // Slides first: they open up the slot a newcomer goes into
    const items = moves.map((m) => `Move <b>${esc(nameOf(m.id))}</b> to ${esc(m.to)}`).concat(L.changes.map((c) => {
      if (c.in && c.out) return `Start <b>${esc(nameOf(c.in))}</b> for ${esc(nameOf(c.out))}`;
      if (c.in) return `Start <b>${esc(nameOf(c.in))}</b> in the empty ${esc(c.slot)} slot`;
      return `Bench ${esc(nameOf(c.out))}: no healthy player to put in`;
    }));
    const n = items.length;
    return `<div class="note todo"><b>Make ${n} change${n > 1 ? 's' : ''} in Sleeper</b>
      <ul>${items.map((t) => `<li>${t}</li>`).join('')}</ul></div>`;
  }

  function lateSwapTip(L) {
    const t = L.late_swap;
    // Gone once the first player it moves has kicked off (Sleeper has locked him)
    if (!t || !t.moves.length || (t.deadline && Date.now() >= new Date(t.deadline).getTime())) return '';
    const moves = t.moves.map((m) => `<b>${esc(nameOf(m.id))}</b> to ${esc(m.to)}`);
    return `<div class="note tip"><b>Late-swap tip</b>
      <p>Move ${andList(moves)}${t.deadline ? ` before ${esc(when(t.deadline))}` : ''}. Your points stay the same.
      ${esc(nameOf(t.latest))} plays ${esc(when(t.kickoff))}, so with him in FLEX a late scratch can be swapped for any
      RB, WR or TE who hasn't played yet, free agents included.</p></div>`;
  }

  function callSide(p, verb, value, reasons, measure) {
    const extra = measure !== 'My Score' ? ` · ${pts(value)} ${esc(measure)}` : '';
    const list = reasons.length
      ? reasons.map((r) => `<li>${esc(r)}</li>`).join('')
      : '<li class="muted">Nothing stands out</li>';
    return `<div class="call-side"><p class="call-head">${verb} <b>${esc(p.name)}</b>
      <span>${pts(p.score)} pts${extra}</span></p><ul>${list}</ul></div>`;
  }

  function closeCalls(L) {
    const calls = (L.close_calls || []).filter((c) => index.get(c.start) && index.get(c.bench));
    if (!calls.length) return '';
    const how = {
      'upside score': 'My Score moved halfway up to the ceiling, because you\'re the underdog',
      'safe score': 'My Score moved halfway down to the floor, because you\'re favored',
    };
    const items = calls.map((c) => {
      const s = index.get(c.start), b = index.get(c.bench);
      const lean = how[c.measure] ? ` (${how[c.measure].replace('halfway', Math.round(L.lean * 100) + '% of the way')})` : '';
      return `<details class="call" data-k="call-${esc(c.start)}-${esc(c.bench)}"><summary>
          <span class="call-names"><b>${esc(s.name)}</b> <span class="vs">over</span> ${esc(b.name)}</span>
          <span class="call-gap">${pts(c.gap)} apart</span></summary>
        <div class="call-body">
          ${callSide(s, 'Start', c.values[0], c.for_start, c.measure)}
          ${callSide(b, 'Or', c.values[1], c.for_bench, c.measure)}
          <p class="muted">${pts(c.gap)} apart on ${esc(c.measure)}${lean}. A close call is anything under ${pts(L.close_call)}.</p>
        </div></details>`;
    });
    return `<h2 class="section">Close calls</h2><div class="calls">${items.join('')}</div>`;
  }

  // ---------- bench and free agents ----------

  function bigCount(n) {
    if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
    if (n >= 1e3) return Math.round(n / 1e3) + 'k';
    return String(n);
  }
  function labelChip(l) {
    if (l === 'Boom') return '<span class="chip label boom" title="Ceiling well above usual for his position">▲ Boom</span>';
    if (l === 'Steady') return '<span class="chip label steady" title="Floor well above usual for his position">◆ Steady</span>';
    return '';
  }

  function pickRow(item, why, extra) {
    const p = index.get(item.id);
    if (!p) return '';
    const inj = p.injury ? `<span class="inj ${injClass(p.injury)}" title="${esc(p.injury)}">${esc(injShort(p.injury))}</span>` : '';
    const state = gameState(p);
    const sub = [
      `<span>${esc(gameText(p))}</span>`,
      state ? `<span class="played">${state}</span>` : (p.kickoff ? `<span>${esc(when(p.kickoff))}</span>` : ''),
      labelChip(item.label), extra || '',
    ].join('');
    const isOpen = open.has(p.id);
    return `<li class="player" data-id="${esc(p.id)}">
      <button type="button" class="row lu" aria-expanded="${isOpen}">
        <span class="slot">${esc(p.pos)}</span>
        <span class="nm">${esc(p.name)}${inj}</span>
        <span class="pts">${pts(p.score)}</span>
        <span class="sub">${sub}</span>
        <span class="why">${esc(why)}</span>
      </button>${isOpen ? detail(p) : ''}</li>`;
  }

  function pickups(L) {
    let html = '';
    const bench = L.bench_flex || [];
    if (bench.length) {
      html += `<h2 class="section">Bench options for FLEX</h2><ul class="players lineup">${bench.map((b) =>
        pickRow(b, b.why)).join('')}</ul>`;
    }
    const fas = L.free_agents || [];
    if (fas.length) {
      const me = data.league.teams[data.league.my_rid];
      const faab = me && me.faab_left != null ? `<span class="faab">$${esc(me.faab_left)} FAAB left</span>` : '';
      html += `<h2 class="section">Free agents ${faab}</h2><ul class="players lineup">${fas.map((f) => {
        let extra = '';
        if (f.dropped) extra += `<span class="chip" title="Dropped ${esc(when(f.dropped))}">Maybe on waivers</span>`;
        if (f.trending) extra += `<span>${bigCount(f.trending)} adds in 2 days</span>`;
        return pickRow(f, f.why, extra);
      }).join('')}</ul>`;
    }
    return html;
  }

  function renderLineup() {
    const L = data.lineup;
    if (!L) {
      $('#lineup').innerHTML = '<p class="warn">Couldn\'t find your team in this league, so there\'s no lineup.</p>';
      return;
    }
    let html = '';
    if (L.times_known === false) {
      html += '<p class="warn">ESPN didn\'t load, so game times are guessed from Sleeper: anyone with points this week counts as played. Check locked players in Sleeper.</p>';
    }
    html += verdict(L) + changesBox(L) + lateSwapTip(L);
    html += `<h2 class="section">Your lineup</h2><ul class="players lineup">${L.me.starters.map((e) => lineupRow(e, 'me')).join('')}</ul>`;
    html += closeCalls(L);
    html += pickups(L);
    if (L.opp) {
      html += `<details class="their" data-k="their"><summary>Their lineup, as set in Sleeper <b>${pts(L.opp.total)}</b></summary>
        <ul class="players lineup">${L.opp.starters.map((e) => lineupRow(e, 'opp')).join('')}</ul></details>`;
    }
    // Re-rendering (a player tapped open) keeps the open sections open
    const kept = [...document.querySelectorAll('#lineup details[data-k]')].filter((d) => d.open).map((d) => d.dataset.k);
    $('#lineup').innerHTML = html;
    for (const k of kept) {
      const d = document.querySelector(`#lineup details[data-k="${k}"]`);
      if (d) d.open = true;
    }
  }

  // ---------- render ----------

  function renderView() {
    for (const b of document.querySelectorAll('[data-view]')) b.setAttribute('aria-selected', String(b.dataset.view === view));
    $('#view-lineup').hidden = view !== 'lineup';
    $('#view-tiers').hidden = view !== 'tiers';
    if (view === 'lineup') renderLineup();
    else { renderTabs(); renderTiers(); }
  }

  function render() {
    if (!data) return;
    index = new Map();
    for (const block of Object.values(data.positions)) for (const p of block.players) index.set(p.id, p);
    renderHeader();
    renderStatus();
    renderView();
  }

  document.addEventListener('click', (e) => {
    const t = e.target.closest('button');
    if (!t) return;
    if (t.dataset.view) { view = t.dataset.view; if (data) renderView(); window.scrollTo(0, 0); return; }
    if (t.dataset.pos) { ui.pos = t.dataset.pos; saveUi(); renderTabs(); renderTiers(); return; }
    if (t.dataset.filter) { ui.filter = t.dataset.filter; saveUi(); renderTabs(); renderTiers(); return; }
    if (t.classList.contains('row')) {
      const id = t.closest('.player').dataset.id;
      if (open.has(id)) open.delete(id); else open.add(id);
      renderView();
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
      if (fresh.version !== DATA_VERSION) {
        updateApp();
        return;
      }
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

  // New data needs a newer app: fetch it and reload once
  function updateApp() {
    try {
      if (sessionStorage.getItem('flup:reloaded')) return;
      sessionStorage.setItem('flup:reloaded', '1');
    } catch (e) { return; }
    toast('Updating the app…');
    const reg = navigator.serviceWorker && navigator.serviceWorker.getRegistration();
    Promise.resolve(reg).then((r) => r && r.update()).catch(() => {}).then(() => location.reload());
  }

  $('#refresh-btn').addEventListener('click', () => refresh(true));
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && data && hoursOld(data.generated) > 0.5) refresh(false);
  });

  data = read(DATA_KEY);
  if (data && data.version !== DATA_VERSION) data = null;
  render();
  refresh(false);

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => { navigator.serviceWorker.register('sw.js').catch(() => {}); });
  }
})();
