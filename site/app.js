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

  // A game day: a game with a starter (mine or theirs) today, Eastern
  // time, that isn't over yet. Old data matters more then.
  const eastern = (t) => new Date(t).toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
  function gameDay() {
    const L = data.lineup;
    const teams = L ? new Set([...L.me.starters, ...((L.opp || {}).starters || [])]
      .map((e) => (index.get(e.id) || {}).team).filter(Boolean)) : null;
    const today = eastern(Date.now());
    return (data.games || []).some((g) => g.kickoff && eastern(g.kickoff) === today
      && Date.now() < Date.parse(g.kickoff) + 4.5 * 3600000
      && (!teams || teams.has(g.home) || teams.has(g.away)));
  }

  function problems() {
    const out = [];
    const stale = gameDay() ? data.settings.stale_game_day_hours || 3 : data.settings.stale_hours || 36;
    if (hoursOld(data.generated) > stale) {
      const next = nextRun();
      out.push(`This data is ${ago(data.generated).replace(' ago', '')} old. `
        + (next ? `Next update: ${when(next.toISOString())}. ` : '') + 'To update now: tap the data line below, then "Run it now".');
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
    const line = updateLine();
    html += `<details class="health"><summary>
        <span>Data from ${esc(when(data.generated))} (${esc(ago(data.generated))})</span>
        <span class="badge ${checks.ok ? 'ok' : 'bad'}">${checks.ok ? '✓ All checks pass' : "✗ Something's off, tap to see"}</span>
      </summary><div class="health-body">${line ? `<p class="muted">${line}</p>` : ''}${checks.html}</div></details>`;
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

  // Once he has played (or while he plays) the big number is his real
  // score, with My Score small underneath; before that, My Score
  function scoreCell(p) {
    const a = gameState(p) && p.actual;
    if (!a) return `<span class="pts">${pts(p.score)}</span>`;
    return `<span class="pts real">${pts(realPts(p))}<small>My Score ${pts(p.score)}</small></span>`;
  }

  // Live: his stat line (Sleeper's matchup points can lag it by a play or
  // two). Final: Sleeper's official points.
  function realPts(p) {
    const a = p.actual;
    return gameState(p) === 'Live' || a.official == null ? a.pts : a.official;
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
        ${scoreCell(p)}
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

  // real: counts from an actual game (whole numbers), not a projection
  function phrase(s, real) {
    let name = SHORT[s.stat] || statName(s.stat).toLowerCase();
    if (real && s.value === 1 && !/^pts_allow/.test(s.stat)) name = name.replace(/ies$/, 'y').replace(/ches$/, 'ch').replace(/([^us])s$/, '$1');  // "1 fumble"
    const delta = (s.points >= 0 ? '+' : '−') + Math.abs(s.points).toFixed(1);
    if (s.stat === 'pts_allow') return `about ${Math.round(s.value)} ${name} (${delta})`;
    if (real && /^pts_allow_/.test(s.stat)) return `${name.replace(/^allowed/, 'allowing')} (${delta})`;
    if (/_td$|int$/.test(s.stat)) return real ? `${num(s.value)} ${name} (${delta})` : `${name} (${delta})`;  // "0.4 TDs" reads oddly
    const amount = /_yd$/.test(s.stat) || (real && Number.isInteger(s.value)) ? String(Math.round(s.value)) : s.value.toFixed(1);
    return `${amount} ${name} (${delta})`;
  }

  function andList(items) {
    return items.length < 2 ? items.join('') : items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1];
  }

  // One plain sentence: the 2-3 stats that make up most of the projection,
  // plus the biggest penalty if it costs a point or more.
  // "mostly from X, Y and Z, minus W": the 2-3 stats that make up most of
  // the total, plus the biggest penalty if it costs a point or more
  function partsPhrase(parts, total, real) {
    const all = merged(parts);
    const gains = all.filter((s) => s.points > 0).sort((a, b) => b.points - a.points);
    const picks = [];
    let covered = 0;
    for (const s of gains) {
      if (picks.length === 3 || (picks.length >= 2 && covered >= 0.7 * total)) break;
      picks.push(s);
      covered += s.points;
    }
    const penalty = all.filter((s) => s.points <= -1).sort((a, b) => a.points - b.points)[0];
    let text = '';
    if (picks.length) text += ', mostly from ' + andList(picks.map((x) => phrase(x, real)));
    if (penalty) text += ', minus ' + phrase(penalty, real);
    return text;
  }

  function projectionSentence(p) {
    return `Sleeper projects <b>${pts(p.proj)}</b> in your scoring${partsPhrase(p.parts, p.proj)}.`;
  }

  function partsTable(parts, real) {
    return parts.map(([stat, value, weight, points]) => {
      const calc = weight == null ? `${num(value)} → bracket blend` : real && /^pts_allow_/.test(stat) ? 'bracket' : `${num(value)} × ${num(weight)}`;
      return `<tr><td>${esc(statName(stat))}</td><td class="n x">${esc(calc)}</td><td class="n">${signed(points)}</td></tr>`;
    }).join('');
  }

  // Once he has played (or while he plays): his real points first
  function actualBlock(p) {
    const a = p.actual;
    if (!a) return '';
    const live = gameState(p) === 'Live';
    const shown = realPts(p);
    let html = `<h3>${live ? 'So far' : 'Scored'}</h3>
      <div class="score-head"><b class="big">${pts(shown)}</b><span>My Score was ${pts(p.score)} (${signedPts(shown - p.score)})</span></div>`;
    if (a.parts.length) {
      html += `<p class="muted">${live ? 'So far' : 'His points came'}${partsPhrase(a.parts, a.pts, true).replace(/^, mostly/, ' mostly') || ': nothing yet'}.</p>
        <details class="every"><summary>How his points add up</summary>
        <table class="math"><tbody>${partsTable(a.parts, true)}</tbody></table></details>`;
    }
    if (a.official != null && Math.abs(a.official - a.pts) > 0.05) {
      html += live
        ? `<p class="muted">Sleeper's matchup score still shows ${pts(a.official)}; it usually catches up within minutes.</p>`
        : `<p class="muted">Sleeper shows ${pts(a.official)}; his stat line here adds up to ${pts(a.pts)}. Sleeper may still be correcting a stat.</p>`;
    }
    return html;
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

  // Questionable/Doubtful, and no news about him (Sleeper's or the links
  // here) in the last day before kickoff: his status may still change.
  // Returns when the last news was, or null.
  function quietInjury(p) {
    if (!p || !/^(Questionable|Doubtful)$/.test(p.injury) || !p.kickoff || gameState(p)) return null;
    const kick = Date.parse(p.kickoff), day = (data.settings.injury_news_hours || 24) * 3600000;
    if (Date.now() >= kick || Date.now() < kick - day) return null;
    const times = [p.news_at, ...(p.news || []).map((n) => n.date)].filter(Boolean).map(Date.parse);
    if (!times.length) return 'never';
    const last = Math.max(...times);
    return last < kick - day ? new Date(last).toISOString() : null;
  }

  function newsBlock(p) {
    const quiet = quietInjury(p);
    let html = quiet ? `<p class="warn">No news about him${quiet === 'never' ? '' : ' since ' + esc(when(quiet))}. He's ${esc(p.injury)}: check the inactives (out about 90 min before kickoff).</p>` : '';
    if (!p.news) return html;
    if (!p.news.length) return html + '<h3>News</h3><p class="muted">Nothing in the last week.</p>';
    const web = (u) => /^https?:\/\//.test(u || '');
    return html + `<h3>News</h3><ul class="news">${p.news.map((n) => `<li>
        ${web(n.url) ? `<a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a>` : `<b>${esc(n.title)}</b>`}
        <span class="muted">${esc(n.source)} · ${n.tag === 'beat reporter' ? 'beat reporter' : 'aggregator'} · ${esc(ago(n.date))}${n.paywall ? ' · 🔒 paywall' : ''}</span></li>`).join('')}</ul>`;
  }

  // Claude's write-up (from /writeups) when there is one, else the template
  function writeupBlock(p) {
    const c = p.claude;
    if (!c) return p.writeup ? `<p class="writeup">${esc(p.writeup)}</p>` : '';
    const changed = c.changed ? ` · written before his status changed (${esc(c.changed.replace('->', '→'))})` : '';
    return `<p class="writeup">${esc(c.text)}</p><p class="muted">Claude's take, ${esc(when(c.written))}${changed}</p>`;
  }

  function detail(p) {
    const block = data.positions[p.pos];
    const rows = partsTable(p.parts);
    let html = `<div class="detail">${actualBlock(p)}${writeupBlock(p)}
      <h3>${p.actual ? 'My Score (before the game)' : 'My Score'}</h3>${myScore(p)}`;
    if (p.parts.length) {
      html += `<details class="every"><summary>How the projection adds up</summary>
          <p>${projectionSentence(p)}</p>
          <table class="math"><tbody>${rows}</tbody></table>
        </details>`;
    }
    html += newsBlock(p);

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
    html += `<button type="button" class="copy-btn" data-copy="player" data-id="${esc(p.id)}">Copy for Claude</button>`;
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

  // The data is a snapshot. Between updates, a player whose kickoff has
  // passed is locked in Sleeper even though the data says "not started".
  function startedSince(p) {
    return !!(p && p.kickoff && !gameState(p) && Date.now() >= Date.parse(p.kickoff));
  }
  const startedId = (id) => startedSince(index.get(id));
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
    const state = e.state === 'final' ? 'Played' : e.state === 'live' ? 'Live' : startedSince(p) ? 'Started' : '';
    const sub = [
      `<span>${esc(gameText(p))}</span>`,
      state ? `<span class="played">${state}</span>` : (p.kickoff ? `<span>${esc(when(p.kickoff))}</span>` : ''),
      e.new ? '<span class="chip new">New</span>' : '',
      side === 'me' && quietInjury(p) ? `<span class="stale">${quietInjury(p) === 'never' ? 'No news' : 'No news since ' + esc(when(quietInjury(p)).split(' ')[0])}</span>` : '',
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

  function lineupMath(L, liveShown) {
    const me = L.me, opp = L.opp, f = L.first;
    const diff = me.total - opp.total;
    const comb = Math.sqrt(me.sd * me.sd + opp.sd * opp.sd);
    const lean = Math.round(L.lean * 100) + '%';
    let html = '';
    if (liveShown) {
      html += `<h4>The lineup advice (data from ${esc(when(data.generated))})</h4>
        <p>Then: you ${pts(me.total)} vs them ${pts(opp.total)}, ${pct(L.win)} to win. That set the mode the lineup below uses.</p>`;
    } else {
      html += `<p>Each starter counts his expected points: My Score if his game hasn't started,
        points so far plus My Score for the part of the game left if it's live, and his actual points once it's over.</p>`;
      html += `<p>You <b>${pts(me.total)}</b> (give or take ${pts(me.sd)}) vs them <b>${pts(opp.total)}</b>
        (give or take ${pts(opp.sd)}). Their lineup is counted exactly as set in Sleeper.</p>`;
    }
    if (comb > 0 && !liveShown) {
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
        html += `<p>The bell curve rates that a bit lower (${pct(L.win)} vs ${pct(f.win)}): it only sees averages and
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
    // During games: the live numbers from Sleeper (both lineups as set now)
    const lv = live && live.opp ? live : null;
    const win = lv ? lv.win : L.win;
    const sofar = (s) => {
      if (!lv) return '';
      const left = s.rows.filter((r) => r.state === 'pre' || r.state === 'live').length;
      return `<span class="sofar">${pts(s.now)} so far · ${left ? left + ' to play' : 'all done'}</span>`;
    };
    return `<div class="verdict ${m.cls}">
      ${lv ? `<p class="live-head"><span class="live-dot"></span> Live from Sleeper, ${esc(when(lv.at))}</p>` : ''}
      <p class="mode-line"><b>${m.word} ${pct(win)}</b>: ${m.line}</p>
      <div class="winbar" role="img" aria-label="${pct(win)} chance to win"><span style="width:${(win * 100).toFixed(1)}%"></span></div>
      <div class="totals">
        <div><span class="lbl">You</span><b>${pts(lv ? lv.me.total : L.me.total)}</b>${sofar(lv && lv.me)}</div>
        <div class="them"><span class="lbl">${esc(opp ? opp.name : 'Them')}</span><b>${pts(lv ? lv.opp.total : L.opp.total)}</b>${sofar(lv && lv.opp)}</div>
      </div>
      <details class="every" data-k="math"><summary>How this is worked out</summary><div class="math-text">${lv ? liveMath(lv) : ''}${lineupMath(L, !!lv)}</div></details>
    </div>`;
  }

  function changesBox(L) {
    const moves = L.moves || [];
    if (!L.changes.length && !moves.length) return '<p class="note done">✓ Your Sleeper lineup already matches.</p>';
    // Slides first: they open up the slot a newcomer goes into
    const locked = (text, ids) => (ids.some(startedId)
      ? `<s>${text}</s> <span class="gone">game started, Sleeper has locked it</span>` : text);
    const items = moves.map((m) => locked(`Move <b>${esc(nameOf(m.id))}</b> to ${esc(m.to)}`, [m.id])).concat(L.changes.map((c) => {
      const ids = [c.in, c.out].filter(Boolean);
      if (c.in && c.out) return locked(`Start <b>${esc(nameOf(c.in))}</b> for ${esc(nameOf(c.out))}`, ids);
      if (c.in) return locked(`Start <b>${esc(nameOf(c.in))}</b> in the empty ${esc(c.slot)} slot`, ids);
      return locked(`Bench ${esc(nameOf(c.out))}: no healthy player to put in`, ids);
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
    const calls = (L.close_calls || []).filter((c) => index.get(c.start) && index.get(c.bench)
      && !startedId(c.start) && !startedId(c.bench));
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
          <span class="call-gap">${c.doubtful ? 'Doubtful' : pts(c.gap) + ' apart'}</span></summary>
        <div class="call-body">
          ${callSide(s, 'Start', c.values[0], c.for_start, c.measure)}
          ${callSide(b, 'Or', c.values[1], c.for_bench, c.measure)}
          <p class="muted">${c.doubtful
            ? `${esc(b.name)} is Doubtful, so he isn't started for you. If he's active (inactives come out about 90 min before kickoff), he's ${pts(c.values[1] - c.values[0])} ${c.values[1] >= c.values[0] ? 'better' : 'behind'} on ${esc(c.measure)}${lean}.`
            : `${pts(c.gap)} apart on ${esc(c.measure)}${lean}. A close call is anything under ${pts(L.close_call)}.`}</p>
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
        ${scoreCell(p)}
        <span class="sub">${sub}</span>
        <span class="why">${esc(why)}</span>
      </button>${isOpen ? detail(p) : ''}</li>`;
  }

  function pickups(L) {
    let html = '';
    const bench = L.bench_flex || [];
    const fas = L.free_agents || [];
    if (bench.length) {
      const avail = bench.filter((b) => !startedId(b.id));
      if (avail.length) {
        html += `<h2 class="section"><span class="dot bench"></span>Bench options</h2><ul class="players lineup grp-bench">${avail.map((b) =>
          pickRow(b, b.why)).join('')}</ul>`;
      }
    }
    if (fas.length) {
      const me = data.league.teams[data.league.my_rid];
      const faab = me && me.faab_left != null ? `<span class="faab">$${esc(me.faab_left)} FAAB left</span>` : '';
      html += `<h2 class="section"><span class="dot fa"></span>Free agents ${faab}</h2><ul class="players lineup grp-fa">${fas.map((f) => {
        let extra = '';
        if (f.dropped) {
          const day = new Date(f.dropped).toLocaleDateString(undefined, { weekday: 'short' });
          extra += `<span class="chip drop">Dropped ${esc(day)}: maybe on waivers</span>`;
        }
        const adds = Number(f.trending) || 0;
        if (adds) extra += `<span>${esc(bigCount(adds))} adds in 2 days</span>`;
        return pickRow(f, startedId(f.id) ? 'His game has started: one to grab for later weeks' : f.why, extra);
      }).join('')}</ul>`;
    }
    // Phones can't show hover tips, so the labels are explained once in words
    if (bench.concat(fas).some((x) => x.label)) {
      html += `<p class="legend"><b>▲ Boom</b>: ceiling well above the usual for his position.
        <b>◆ Steady</b>: floor well above the usual.</p>`;
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
    const ids = L.me.starters.concat(L.opp ? L.opp.starters : []).map((e) => e.id)
      .concat((L.bench_flex || []).map((b) => b.id), (L.free_agents || []).map((f) => f.id));
    if (ids.some(startedId)) {
      html += `<p class="note">Games have started since this data (from ${esc(when(data.generated))}).
        Totals and win % are as of then. Sleeper has locked those players, so any moves for them are crossed out.</p>`;
    }
    html += verdict(L) + changesBox(L) + lateSwapTip(L);
    html += `<h2 class="section"><span class="dot me"></span>Your lineup</h2><ul class="players lineup grp-me">${L.me.starters.map((e) => lineupRow(e, 'me')).join('')}</ul>`;
    html += closeCalls(L);
    html += pickups(L);
    if (L.opp) {
      html += `<details class="their" data-k="their"><summary><span class="dot opp"></span>Their lineup, as set in Sleeper <b>${pts(L.opp.total)}</b></summary>
        <ul class="players lineup grp-opp">${L.opp.starters.map((e) => lineupRow(e, 'opp')).join('')}</ul></details>`;
    }
    html += '<button type="button" class="copy-btn" data-copy="lineup">Copy my matchup for Claude</button>';
    // Re-rendering (a player tapped open) keeps the open sections open
    const kept = [...document.querySelectorAll('#lineup details[data-k]')].filter((d) => d.open).map((d) => d.dataset.k);
    $('#lineup').innerHTML = html;
    for (const k of kept) {
      const d = document.querySelector(`#lineup details[data-k="${k}"]`);
      if (d) d.open = true;
    }
  }

  // ---------- when the data updates itself ----------

  function cronMatches(spec, v) {
    return spec.split(',').some((part) => {
      const [range, stepText] = part.split('/');
      const step = stepText ? Number(stepText) : 1;
      let lo, hi;
      if (range === '*') { lo = 0; hi = 99; } else if (range.includes('-')) { [lo, hi] = range.split('-').map(Number); } else { lo = Number(range); hi = stepText ? 99 : lo; }
      return v >= lo && v <= hi && (v - lo) % step === 0;
    });
  }
  // The next scheduled run (cron times are UTC), or null
  function nextRun() {
    const r = data.refresh;
    if (!r || !r.scheduled || !(r.crons || []).length) return null;
    const crons = r.crons.map((c) => c.trim().split(/\s+/)).filter((f) => f.length === 5);
    const start = Math.floor(Date.now() / 60000) * 60000;
    for (let i = 1; i <= 8 * 24 * 60; i++) {
      const d = new Date(start + i * 60000);
      const v = [d.getUTCMinutes(), d.getUTCHours(), d.getUTCDate(), d.getUTCMonth() + 1, d.getUTCDay()];
      if (crons.some((f) => f.every((spec, k) => cronMatches(spec, v[k])))) return d;
    }
    return null;
  }
  function runLink() {
    const r = data.refresh || {};
    return r.repo ? `https://github.com/${r.repo}/actions/workflows/update.yml` : null;
  }
  function updateLine() {
    const next = nextRun(), link = runLink();
    const when_ = next ? `Next update: ${esc(when(next.toISOString()))} (GitHub runs can start up to 30 min late).`
      : (data.refresh && !data.refresh.scheduled ? 'This preview only updates when a run is started by hand.' : '');
    return `${when_}${link ? ` <a href="${esc(link)}" target="_blank" rel="noopener">Run it now</a> (Run workflow, branch main).` : ''}`;
  }

  // ---------- live scores in the browser (Sleeper and ESPN both allow it) ----------
  // The same math as pipeline/lineup.py: a live starter counts his points so
  // far plus My Score x the share of his game left; win % from the totals.

  let live = null;  // {at, me, opp, win}
  const BELL = (z) => {  // standard normal CDF (Abramowitz-Stegun 7.1.26)
    const t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2);
    const e = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-z * z / 2);
    return z >= 0 ? (1 + e) / 2 : (1 - e) / 2;
  };
  const healthyScore = (p) => p.score - (p.adj || []).filter((a) => a.key === 'injury').reduce((n, a) => n + a.pts, 0);
  function fullSd(p) {
    const r = p.range;
    if (!r) return 0;
    let sd = Math.abs(r.sd);
    if (r.if_plays) {
      const h = healthyScore(p), q = h > 0 ? Math.max(0, Math.min(1, p.score / h)) : 0;
      sd = Math.sqrt(q * sd * sd + q * (1 - q) * h * h);
    }
    return sd;
  }
  function phaseOf(g, now) {
    if (!g) return ['unknown', 1];
    if (/POSTPONED|CANCELED/.test(g.status || '')) return ['none', 0];
    if (g.completed || g.state === 'post') return ['final', 0];
    const kick = Date.parse(g.kickoff);
    if (g.state !== 'in' && (isNaN(kick) || now < kick)) return ['pre', 1];
    if (g.state !== 'in' || !(g.period >= 1)) return ['live', 1];
    if (g.period > 4) return ['live', 0];
    return ['live', Math.max(0, Math.min(1, ((4 - g.period) * 900 + (g.clock || 0)) / 3600))];
  }
  function smoothBracket(x) {
    const t = data.league.def_brackets || [];
    if (!t.length) return 0;
    if (x <= t[0][0]) return t[0][1];
    if (x >= t[t.length - 1][0]) return t[t.length - 1][1];
    for (let i = 1; i < t.length; i++) {
      const [x0, y0] = t[i - 1], [x1, y1] = t[i];
      if (x <= x1) return x1 === x0 ? y0 : y0 + (y1 - y0) * (x - x0) / (x1 - x0);
    }
    return 0;
  }
  // Points for the bracket x (points allowed) falls in, as Sleeper scores it
  function bracketPoints(x) {
    for (const [k, v] of Object.entries(data.league.scoring || {})) {
      const m = k.match(/^pts_allow_(\d+)(?:_(\d+)|(p))?$/);
      if (!m) continue;
      const lo = Number(m[1]);
      if (m[3] ? x >= lo : m[2] ? x >= lo && x <= Number(m[2]) : x === lo) return v;
    }
    return 0;
  }
  function liveDef(p, g, got, rest, left, line) {
    let allowedProj = null, bracketProj = 0;
    for (const [stat, value, , pts_] of p.parts || []) {
      if (stat === 'pts_allow' || stat.startsWith('pts_allow_')) { bracketProj += pts_; if (stat === 'pts_allow') allowedProj = value; }
    }
    const restNo = rest - bracketProj;
    const allowedNow = g ? (g.home === p.team ? g.score_away : g.score_home) : null;
    // The bracket inside his points so far: from his own stat line, else
    // (no line) the one for the score now if he has points at all
    const sc = data.league.scoring || {};
    const counted = line
      ? Object.entries(line).filter(([k]) => k.startsWith('pts_allow_')).reduce((n, [k, v]) => n + v * (sc[k] || 0), 0)
      : got && allowedNow != null ? bracketPoints(allowedNow) : 0;
    if (allowedNow == null || allowedProj == null) return got + restNo * left;
    return got - counted + restNo * left + smoothBracket(allowedNow + allowedProj * left);
  }
  function liveRow(id, got, g, now, defLine) {
    const p = index.get(id);
    if (!p) return { id, pts: got, sd: 0, state: 'unknown', got, left: 0 };
    // No ESPN game for his team: points this week mean he has played
    const [state, left] = g ? phaseOf(g, now) : (got ? ['final', 0] : ['pre', 1]);
    if (state === 'final') return { id, pts: got, sd: 0, state, got, left: 0 };
    if (state === 'none') return { id, pts: 0, sd: 0, state, got: 0, left: 0 };
    if (state === 'pre' || state === 'unknown') return { id, pts: p.score, sd: fullSd(p), state: 'pre', got: 0, left: 1 };
    let rest = p.score, sd = fullSd(p);
    if (got && healthyScore(p) > p.score) { rest = healthyScore(p); sd = Math.abs((p.range || {}).sd || sd); }
    let pts_ = got + rest * left;
    if (p.pos === 'DEF') pts_ = liveDef(p, g, got, rest, left, defLine);
    return { id, pts: pts_, sd: sd * Math.sqrt(left), state, got, left };
  }

  async function fetchLive() {
    const lg = data.league;
    const get = (url) => fetch(url, { cache: 'no-store' }).then((r) => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
    const [mu, sb, defs] = await Promise.all([
      get(`https://api.sleeper.app/v1/league/${lg.id}/matchups/${data.week}`),
      get(`https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?seasontype=2&week=${data.week}&dates=${data.season}`),
      get(`https://api.sleeper.app/stats/nfl/${data.season}/${data.week}?season_type=regular&position[]=DEF`).catch(() => []),
    ]);
    const games = {};
    for (const ev of sb.events || []) {
      const c = (ev.competitions || [{}])[0], st = c.status || ev.status || {}, kind = st.type || {};
      const side = {}, score = {};
      for (const t of c.competitors || []) {
        const abbr = t.team && (t.team.abbreviation === 'WSH' ? 'WAS' : t.team.abbreviation);
        side[t.homeAway] = abbr;
        score[t.homeAway] = t.score == null ? null : Number(t.score);
      }
      const g = { home: side.home, away: side.away, kickoff: c.date || ev.date, status: kind.name, state: kind.state,
        completed: !!kind.completed, period: st.period || 0, clock: typeof st.clock === 'number' ? st.clock : 0,
        score_home: score.home, score_away: score.away };
      games[g.home] = g; games[g.away] = g;
    }
    const defLines = {};
    for (const r of defs || []) if (r && r.stats && (r.stats.gp || 0) > 0) defLines[String(r.player_id)] = r.stats;
    const sc = lg.scoring || {};
    const now = Date.now();
    const side = (rid) => {
      const m = (mu || []).find((x) => x.roster_id === rid);
      if (!m) return null;
      const rows = (m.starters || []).filter((id) => id && id !== '0').map((id) => {
        const p = index.get(id), line = defLines[id];
        // A defense's points come from his own stat line, so the bracket in
        // them matches the one taken back
        const got = p && p.pos === 'DEF' && line
          ? Object.entries(line).reduce((n, [k, v]) => n + (typeof v === 'number' ? v * (sc[k] || 0) : 0), 0)
          : Number((m.players_points || {})[id] || 0);
        return liveRow(id, got, p ? games[p.team] : null, now, line);
      });
      return { rows, now: rows.reduce((n, r) => n + r.got, 0), total: rows.reduce((n, r) => n + r.pts, 0),
        sd: Math.sqrt(rows.reduce((n, r) => n + r.sd * r.sd, 0)) };
    };
    const me = side(lg.my_rid), opp = side(lg.opp_rid);
    if (!me) throw new Error('my team is not in the matchups');
    const comb = opp ? Math.sqrt(me.sd * me.sd + opp.sd * opp.sd) : 0;
    const win = !opp ? null : comb > 0 ? BELL((me.total - opp.total) / comb) : (me.total > opp.total ? 1 : me.total < opp.total ? 0 : 0.5);
    return { at: new Date().toISOString(), me, opp, win };
  }

  // Games on now (or just over) with a starter from either side
  function gamesOn() {
    const L = data.lineup;
    if (!L) return false;
    const teams = new Set([...L.me.starters, ...((L.opp || {}).starters || [])].map((e) => (index.get(e.id) || {}).team).filter(Boolean));
    const now = Date.now();
    return (data.games || []).some((g) => (teams.has(g.home) || teams.has(g.away))
      && now >= Date.parse(g.kickoff) && now < Date.parse(g.kickoff) + 4.5 * 3600000);
  }

  let liveBusy = false;
  async function refreshLive(manual) {
    if (!data || !data.lineup || liveBusy || (!manual && !gamesOn())) return;
    liveBusy = true;
    try {
      live = await fetchLive();
      if (view === 'lineup') renderLineup();
    } catch (err) {
      if (manual) toast("Live scores didn't load (" + err.message + ').');
    } finally {
      liveBusy = false;
    }
  }

  function liveMath(lv) {
    const name = (id) => (index.get(id) || {}).name || 'Unknown player';
    const word = { final: 'final', none: 'no game' };
    const rowsOf = (s) => s.rows.map((r) => `<li>${esc(name(r.id))}: ${
      r.state === 'live' ? `<b>${pts(r.got)}</b> so far, ${Math.round(r.left * 100)}% of the game left → ${pts(r.pts)}`
        : r.state === 'pre' ? `${pts(r.pts)} (not started)` : `<b>${pts(r.got)}</b> (${word[r.state] || r.state})`}</li>`).join('');
    const opp = data.league.teams[data.league.opp_rid];
    const diff = lv.me.total - lv.opp.total, comb = Math.sqrt(lv.me.sd ** 2 + lv.opp.sd ** 2);
    let html = `<p><b>Live:</b> both lineups as set in Sleeper right now. Each starter counts his points so far
      plus My Score for the part of his game left; one who hasn't started counts My Score. Points so far are
      Sleeper's matchup points, which can trail a play by a few minutes. Updates every 2 minutes.</p>
      <p>You <b>${pts(lv.me.total)}</b> (give or take ${pts(lv.me.sd)}) vs them <b>${pts(lv.opp.total)}</b> (give or take ${pts(lv.opp.sd)})`;
    html += comb > 0 ? `: ${signedPts(diff)} ÷ ${pts(comb)} = ${(diff < 0 ? '−' : '') + Math.abs(diff / comb).toFixed(2)} on the bell curve → <b>${pct(lv.win)}</b>.</p>` : '.</p>';
    html += `<details class="every" data-k="liveplayers"><summary>Player by player</summary>
      <h4>You</h4><ul class="live-rows">${rowsOf(lv.me)}</ul>
      <h4>${esc(opp ? opp.name : 'Them')}</h4><ul class="live-rows">${rowsOf(lv.opp)}</ul></details>`;
    return html;
  }

  // ---------- Copy for Claude: a ready-to-paste prompt with every input ----------

  const SCORING_WORDS = [['pass_td', 'pass TD'], ['pass_yd', 'per pass yd'], ['pass_int', 'INT'],
    ['rush_td', 'rush TD'], ['rush_yd', 'per rush yd'], ['rec', 'per catch'], ['bonus_rec_te', 'TE bonus per catch'],
    ['rec_td', 'rec TD'], ['rec_yd', 'per rec yd'], ['fum', 'fumble'], ['fum_lost', 'fumble lost (extra)'],
    ['kr_yd', 'per kick return yd'], ['pr_yd', 'per punt return yd']];
  const plain = (n) => (n < 0 ? '-' : '') + Math.abs(n).toFixed(1);
  const sgn = (n) => (n >= 0 ? '+' : '-') + Math.abs(n).toFixed(1);

  function promptHeader() {
    const lg = data.league, L = data.lineup, sc = lg.scoring || {};
    const me = lg.teams[lg.my_rid] || {}, opp = lg.teams[lg.opp_rid];
    let zone = '';
    try { zone = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) { /* ignore */ }
    const lines = [`Fantasy football, ${lg.name}, ${data.season} week ${data.week}. Data from ${when(data.generated)}`
      + (zone ? ` (times are ${zone})` : '') + '.',
      'Scoring (from Sleeper): ' + SCORING_WORDS.filter(([k]) => sc[k]).map(([k, w]) => `${w} ${num(sc[k])}`).join(', ') + '.'];
    if (L && L.opp && opp) {
      lines.push(`My team: ${me.name} (${me.wins}-${me.losses}) vs ${opp.name} (${opp.wins}-${opp.losses}). `
        + `Projected ${pts(L.me.total)} (sd ${pts(L.me.sd)}) vs ${pts(L.opp.total)} (sd ${pts(L.opp.sd)}): `
        + `win chance ${pct(L.win)}, so the dashboard is in "${(MODE[L.mode] || MODE.even).word}" mode `
        + `(players ranked ${L.mode === 'underdog' ? 'toward their ceiling' : L.mode === 'favored' ? 'toward their floor' : 'by My Score'}).`);
    }
    const b = data.settings.blend || {}, fc = data.settings.floor_ceiling || {};
    const share = (x) => Math.round(100 * x / ((b.projection || 0) + (b.consensus || 0) || 1));
    lines.push(`My Score = ${share(b.projection)}% Sleeper projection (rescored in my scoring) + ${share(b.consensus)}% FantasyPros consensus rank turned into points, `
      + `plus small capped adjustments. Floor/ceiling = ${fc.floor_pct}th/${fc.ceiling_pct}th percentile of his weekly scores, scaled to this week.`);
    return lines.join('\n');
  }

  function roleOf(p) {
    const L = data.lineup;
    if (L) {
      const mine = L.me.starters.find((e) => e.id === p.id);
      if (mine) return `my starter at ${mine.slot}`;
      const theirs = L.opp && L.opp.starters.find((e) => e.id === p.id);
      if (theirs) return `opponent's starter at ${theirs.slot}`;
    }
    const o = owner(p);
    return o.kind === 'mine' ? 'on my bench' : o.kind === 'fa' ? 'free agent' : o.kind === 'opp' ? "on opponent's bench" : `on ${o.team}`;
  }

  function playerText(p, withNews) {
    const out = [];
    const inj = p.injury ? `, ${p.injury}${p.injury_detail ? ' (' + p.injury_detail + ')' : ''}` : '';
    out.push(`${p.name} (${p.pos}, ${gameText(p)}${p.kickoff ? ', ' + when(p.kickoff) : ''}${inj}): ${roleOf(p)}.`);
    if (p.note) { out.push(`  ${p.note}.`); return out.join('\n'); }
    const r = p.range;
    out.push(`  My Score ${plain(p.score)}` + (r ? ` (floor ${plain(r.floor)}, ceiling ${plain(r.ceiling)}${r.if_plays ? ', if he plays' : ''})` : '')
      + (p.tier != null ? `, tier ${p.tier}, rank ${p.rank} at ${p.pos}` : '') + '.');
    out.push(`  Sleeper projection ${plain(p.proj)}` + (p.cons ? `; experts ${p.pos}${p.cons.rank}${p.cons.pts != null ? ' (about ' + plain(p.cons.pts) + ')' : ''}` : '')
      + ` -> ${plain(p.base)} (${p.blend}).`);
    if (p.adj && p.adj.length) out.push('  Adjustments: ' + p.adj.map((a) => `${a.label} ${sgn(a.pts)} (${a.why})`).join('; ') + '.');
    if (p.implied != null) out.push(`  Vegas: ${p.team} ${p.spread > 0 ? '+' : ''}${num(p.spread)}, implied ${num(p.implied)} pts.`);
    if (p.actual) out.push(`  ${gameState(p) === 'Live' ? 'So far' : 'Scored'}: ${plain(realPts(p))} pts.`);
    if (withNews && p.news && p.news.length) {
      out.push('  News:');
      for (const n of p.news) out.push(`  - ${n.title} (${n.source}, ${n.tag}, ${new Date(n.date).toLocaleDateString()}) ${n.url}`);
    }
    return out.join('\n');
  }

  function playerPrompt(p) {
    const L = data.lineup;
    const calls = ((L && L.close_calls) || []).filter((c) => c.start === p.id || c.bench === p.id);
    const extra = calls.map((c) => `Close call (${c.measure}): ${nameOf(c.start)} ${plain(c.values[0])} starting vs ${nameOf(c.bench)} ${plain(c.values[1])} on the bench.`);
    const others = calls.map((c) => index.get(c.start === p.id ? c.bench : c.start)).filter(Boolean);
    return [promptHeader(), '', playerText(p, true), ...others.map((o) => playerText(o, true)), ...extra, '',
      `Should I ${roleOf(p).startsWith('my starter') ? 'keep starting' : 'start or pick up'} ${p.name} this week? `
      + 'Answer in 3-4 sentences using these numbers and anything you know about him; say what would change your mind.'].join('\n');
  }

  function lineupPrompt() {
    const L = data.lineup;
    const parts = [promptHeader(), '', 'MY LINEUP (as the dashboard recommends):'];
    for (const e of L.me.starters) {
      const p = index.get(e.id);
      parts.push(p ? playerText(p, true) : `${e.slot}: empty`);
    }
    if (L.changes.length) {
      parts.push('', 'Changes from my current Sleeper lineup: ' + L.changes.map((c) =>
        (c.in ? `start ${nameOf(c.in)}` : '') + (c.in && c.out ? ' for ' : '') + (c.out ? `bench ${nameOf(c.out)}` : '')).join('; ') + '.');
    }
    if ((L.close_calls || []).length) {
      parts.push('', 'Close calls: ' + L.close_calls.map((c) => `${nameOf(c.start)} ${plain(c.values[0])} vs ${nameOf(c.bench)} ${plain(c.values[1])} (${c.measure})`).join('; ') + '.');
    }
    const bench = (L.bench_flex || []).map((b) => index.get(b.id)).filter(Boolean);
    if (bench.length) parts.push('', 'BENCH OPTIONS:', ...bench.map((p) => playerText(p, false)));
    const fas = (L.free_agents || []).map((f) => index.get(f.id)).filter(Boolean);
    if (fas.length) parts.push('', `FREE AGENTS (instant adds; $${(data.league.teams[data.league.my_rid] || {}).faab_left} FAAB left):`, ...fas.map((p) => playerText(p, false)));
    if (L.opp) {
      parts.push('', "THEIR LINEUP (as set in Sleeper): " + L.opp.starters.map((e) => {
        const p = index.get(e.id);
        return `${e.slot} ${p ? p.name : 'empty'} ${plain(e.pts)}`;
      }).join('; ') + '.');
    }
    parts.push('', 'Review my lineup. Is anything worth changing (starts, FLEX, a free agent)? '
      + 'Keep it short: the moves, one line each on why, using these numbers and anything you know.');
    return parts.join('\n');
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (e2) { /* ignore */ }
      ta.remove();
      return ok;
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
    if (t.dataset.copy) {
      const p = t.dataset.copy === 'player' ? index.get(t.dataset.id) : null;
      const text = p ? playerPrompt(p) : lineupPrompt();
      copyText(text).then((ok) => toast(ok ? 'Copied. Paste it into the Claude app.' : "Couldn't copy on this device."));
      return;
    }
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
      if (changed) { live = null; render(); }
      if (gamesOn()) {
        await refreshLive(manual);
        if (manual && live) toast('Live scores updated' + (changed ? ', and new data loaded' : ''));
      } else if (manual) {
        const next = nextRun();
        toast(changed ? 'New data loaded' : 'Up to date: data from ' + when(fresh.generated) + (next ? '. Next update ' + when(next.toISOString()) : ''));
      }
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
  // While games with our starters are on: live scores every 2 minutes
  setInterval(() => { if (document.visibilityState === 'visible') refreshLive(false); }, 120000);
  // Kickoffs pass while the page is open: redraw the lineup when one does
  let startedCount = -1;
  setInterval(() => {
    if (!data || !data.lineup || view !== 'lineup' || document.visibilityState !== 'visible') return;
    const n = [...index.values()].filter(startedSince).length;
    if (n !== startedCount) { startedCount = n; renderLineup(); }
  }, 60000);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible' || !data) return;
    if (hoursOld(data.generated) > 0.5) refresh(false);
    else refreshLive(false);
  });

  data = read(DATA_KEY);
  if (data && data.version !== DATA_VERSION) data = null;
  render();
  refresh(false);

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => { navigator.serviceWorker.register('sw.js').catch(() => {}); });
  }
})();
