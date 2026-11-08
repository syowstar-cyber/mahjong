// Haluリーグ（個人戦のリーグ）の受け口（Google Apps Script ウェブアプリ）
// Halu杯 普段の回の受け口（kai/gas/）とは別のプロジェクト。配置手順は league/gas/README.md を見る。
// ドライブは使わない。スクリプト プロパティ（このスクリプト専用の保存領域）に、シーズン（season）ごとの JSON を持つ:
//   S_<season>_<回戦> = {"<卓>": {p:['P1','P5','P8','P9'], raw:[32100,28400,22000,17500], d:'YYYY-MM-DD', ts:'…'}}
//     p と raw は対戦カードの並び（席の順ではない。席は卓で決める）。d は打った日、ts は受け口が入れた時刻（JST）
//   R_<season> = {"P1": "名前", …}   名簿。名前はここにだけ置く（公開リポにはファイルとして置かない）
//   A_<season>_<P番号> = {"YYYY-MM-DD": "o", …}   調整表の予定の印（o＝○・t＝△・x＝×。付けていない日は持たない）
//   U_<season> = 点数か名簿の最終更新の時刻（JST）。予定の印では動かさない（Halu杯の打ち上げの出欠と同じ）
//   LOG = 送信履歴の直近 LOG_MAX 件（1件＝'MMDDHHmmss|season|操作|回戦|卓か人'）
// シーズンを替えても消す作業は要らない（season が違えば置き場が別）。古いシーズンを消すのはエディタの purgeSeason。
//
// 受け口（URL は1つ。キーなし＝Halu杯と同じ。範囲だけ検査し、送信履歴に時刻を残す）:
//   GET  ?season=<season>                                                        … そのシーズンの点数・名簿・予定・最終更新
//   POST {action:'score', season, round, table, p:[…], raw:[…], d:'YYYY-MM-DD'}  … 1卓ぶん（3人か4人）。同じ卓は上書き
//   POST {action:'clear', season, round, table}                                 … 1卓ぶんを消す
//   POST {action:'avail', season, p:'P3', marks:{'YYYY-MM-DD':'o'|'t'|'x'|''}}   … 1人ぶんの予定。日ごとに上書きし、'' は消す
//   POST {action:'roster', season, names:{P1:'名前', …}}                         … 名簿（渡したキーだけ直す。'' で消す）
//   round は '1'〜'99'、table は 1〜TABLE_MAX。d は今日（JST）まで。
//   返事は {ok:true, data:{season, rounds, roster, avail, updated}} か {ok:false, error:'…'}。
//   同じ回戦のほかの卓に入っている人を送ると error:'dup'（players に該当者）で断る（卓の取り違え）

const SEASON_RE = /^[0-9a-z-]{1,24}$/;   // ページと同じ形。'_' は置き場の名前の区切りに使うので入れない
const ROUND_RE = /^[1-9][0-9]?$/;
const PLAYER_RE = /^P([1-9]|[1-9][0-9])$/;
const TABLE_MAX = 10;
const RAW_MIN = -200000, RAW_MAX = 999900;   // Halu杯と同じ（トビ終了なし・箱下あり）
const NAME_MAX = 20;
const MARKS_MAX = 200;    // 1回に送れる日数
const MARKS_KEEP = 400;   // 1人が持てる日数（1つの置き場は9KBまで。400日で7KBほど）
const MARK_VALUES = ['o', 't', 'x', ''];
const LOG_MAX = 100;

// スクリプト プロパティは1日の読み書きの回数に上限がある（無料アカウントは1日5万回）。
// 1回の実行では getProperties() を1回だけ呼んで写し（SNAP）を作り、読むのはそこから（Halu杯と同じ）。
// 書くときは本物に書いて、写しも同じに直す。写しを作るのは GET の頭と、POST でロックを取った後だけ
let SNAP = null;
function snap_() { SNAP = PropertiesService.getScriptProperties().getProperties(); }
function get_(k) { return Object.prototype.hasOwnProperty.call(SNAP, k) ? SNAP[k] : null; }
function json_(k, dflt) {
  try { const v = JSON.parse(get_(k) || 'null'); return v === null ? dflt : v; } catch (e) { return dflt; }
}
function set_(k, v) { PropertiesService.getScriptProperties().setProperty(k, v); SNAP[k] = String(v); }
function del_(k) { PropertiesService.getScriptProperties().deleteProperty(k); delete SNAP[k]; }

function out_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
function now_() {
  return Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd HH:mm:ss');
}
// 'YYYY-MM-DD' で、実在する日付で、2020-01-01〜2099-12-31
function validDate_(s) {
  if (typeof s !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const y = Number(s.slice(0, 4)), m = Number(s.slice(5, 7)), d = Number(s.slice(8, 10));
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return false;
  return s >= '2020-01-01' && s <= '2099-12-31';
}

// そのシーズンの全部（点数は回戦ごと、名簿、予定は人ごと、最終更新）
function data_(season) {
  const pre = 'S_' + season + '_', apre = 'A_' + season + '_', rounds = {}, avail = {};
  Object.keys(SNAP).forEach(function (k) {
    if (k.indexOf(pre) === 0) {
      const r = k.slice(pre.length);
      if (ROUND_RE.test(r)) rounds[r] = json_(k, {});
    } else if (k.indexOf(apre) === 0) {
      const p = k.slice(apre.length);
      if (PLAYER_RE.test(p)) avail[p] = json_(k, {});
    }
  });
  return { season: season, rounds: rounds, roster: json_('R_' + season, {}), avail: avail, updated: get_('U_' + season) };
}

function log_(season, act, round, what) {
  const log = json_('LOG', []);
  log.push(now_().slice(5).replace(/[-: ]/g, '') + '|' + season + '|' + act + '|' + (round || '') + '|' + (what || ''));
  set_('LOG', JSON.stringify(log.slice(-LOG_MAX)));
}

// 書き込みはロックの中で。打ち終わりの送信が重なっても待てるよう30秒（Halu杯と同じ）
function withLock_(fn) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) return out_({ ok: false, error: 'busy' });
  try {
    snap_();
    return fn();
  } finally {
    SNAP = null;
    lock.releaseLock();
  }
}

// 読み取り: GET（誰でも）
function doGet(e) {
  const season = String((e && e.parameter && e.parameter.season) || '');
  if (!SEASON_RE.test(season)) return out_({ ok: false, error: 'season' });
  snap_();
  try {
    return out_({ ok: true, data: data_(season) });
  } finally {
    SNAP = null;
  }
}

// 書き込み: POST（本文は JSON。ページは Content-Type を付けずに送る＝事前確認の要らない送り方）
function doPost(e) {
  let b;
  try { b = JSON.parse(e.postData.contents); } catch (err) { return out_({ ok: false, error: 'bad_json' }); }
  if (!b || typeof b !== 'object' || Array.isArray(b)) return out_({ ok: false, error: 'bad_json' });
  const season = String(b.season || '');
  if (!SEASON_RE.test(season)) return out_({ ok: false, error: 'season' });
  if (b.action === 'avail') return avail_(season, b.p, b.marks);
  if (b.action === 'roster') return roster_(season, b.names);
  if (b.action !== 'score' && b.action !== 'clear') return out_({ ok: false, error: 'action' });

  const round = String(b.round || ''), table = Number(b.table);
  if (!ROUND_RE.test(round)) return out_({ ok: false, error: 'round' });
  if (!Number.isInteger(table) || table < 1 || table > TABLE_MAX) return out_({ ok: false, error: 'table' });
  let p = null, raw = null, d = '';
  if (b.action === 'score') {
    if (!Array.isArray(b.p) || (b.p.length !== 3 && b.p.length !== 4)) return out_({ ok: false, error: 'player' });
    p = b.p.map(String);
    if (p.some(function (x, i) { return !PLAYER_RE.test(x) || p.indexOf(x) !== i; })) return out_({ ok: false, error: 'player' });
    if (!Array.isArray(b.raw) || b.raw.length !== p.length) return out_({ ok: false, error: 'score' });
    raw = b.raw.map(Number);
    if (raw.some(function (v) { return !Number.isInteger(v) || v % 100 !== 0 || v < RAW_MIN || v > RAW_MAX; })) return out_({ ok: false, error: 'score' });
    // 打った日。今日（JST）より後は断る（ページも断る）
    d = String(b.d || '');
    if (!validDate_(d) || d > now_().slice(0, 10)) return out_({ ok: false, error: 'date' });
  }

  return withLock_(function () {
    const key = 'S_' + season + '_' + round, t = String(table);
    const cur = json_(key, {});
    if (b.action === 'score') {
      const dup = p.filter(function (x) {
        return Object.keys(cur).some(function (k) { return k !== t && cur[k] && Array.isArray(cur[k].p) && cur[k].p.indexOf(x) >= 0; });
      });
      if (dup.length) return out_({ ok: false, error: 'dup', players: dup, data: data_(season) });
      cur[t] = { p: p, raw: raw, d: d, ts: now_() };
    } else {
      delete cur[t];
    }
    if (Object.keys(cur).length) set_(key, JSON.stringify(cur)); else if (get_(key) !== null) del_(key);
    set_('U_' + season, now_());
    log_(season, b.action, round, t);
    return out_({ ok: true, data: data_(season) });
  });
}

// 調整表の予定の印。marks = {'YYYY-MM-DD': 'o'|'t'|'x'|''}。日ごとに上書きし、'' は消す。
// 点数ではないので、最終更新（U_）は動かさない
function avail_(season, player, marks) {
  player = String(player || '');
  if (!PLAYER_RE.test(player)) return out_({ ok: false, error: 'player' });
  if (!marks || typeof marks !== 'object' || Array.isArray(marks)) return out_({ ok: false, error: 'mark' });
  const days = Object.keys(marks);
  if (!days.length || days.length > MARKS_MAX) return out_({ ok: false, error: 'mark' });
  for (let i = 0; i < days.length; i++) {
    if (!validDate_(days[i])) return out_({ ok: false, error: 'date' });
    if (MARK_VALUES.indexOf(marks[days[i]]) < 0) return out_({ ok: false, error: 'mark' });
  }
  return withLock_(function () {
    const key = 'A_' + season + '_' + player, cur = json_(key, {});
    days.forEach(function (d) { if (marks[d]) cur[d] = marks[d]; else delete cur[d]; });
    if (Object.keys(cur).length > MARKS_KEEP) return out_({ ok: false, error: 'mark' });
    if (Object.keys(cur).length) set_(key, JSON.stringify(cur)); else if (get_(key) !== null) del_(key);
    log_(season, 'avail', '', player);
    return out_({ ok: true, data: data_(season) });
  });
}

// 名簿。names = {P1:'名前', …}。渡したキーだけ直し、'' は消す（Halu杯と同じ）
function roster_(season, names) {
  if (!names || typeof names !== 'object' || Array.isArray(names)) return out_({ ok: false, error: 'names' });
  const keys = Object.keys(names);
  if (!keys.length || keys.some(function (k) { return !PLAYER_RE.test(k); })) return out_({ ok: false, error: 'player' });
  const vals = {};
  for (let i = 0; i < keys.length; i++) {
    const v = String(names[keys[i]] === null || names[keys[i]] === undefined ? '' : names[keys[i]]).trim();
    if (v.length > NAME_MAX || /[\u0000-\u001f<>]/.test(v)) return out_({ ok: false, error: 'name' });
    vals[keys[i]] = v;
  }
  return withLock_(function () {
    const r = json_('R_' + season, {});
    keys.forEach(function (k) { if (vals[k]) r[k] = vals[k]; else delete r[k]; });
    if (Object.keys(r).length) set_('R_' + season, JSON.stringify(r)); else if (get_('R_' + season) !== null) del_('R_' + season);
    set_('U_' + season, now_());
    log_(season, 'roster', '', String(keys.length));
    return out_({ ok: true, data: data_(season) });
  });
}

// ---- ここから下はエディタで動かす（受け口からは呼べない） ----

// 置いてあるシーズンの一覧（点数の卓数・名簿の人数・予定を付けた人数・最終更新）をログに出す
function listSeasons() {
  snap_();
  try {
    const seasons = {};
    Object.keys(SNAP).forEach(function (k) {
      const m = /^([SRAU])_([0-9a-z-]+)(?:_(.+))?$/.exec(k);
      if (!m) return;
      const o = seasons[m[2]] || (seasons[m[2]] = { tables: 0, names: 0, avail: 0, updated: '' });
      if (m[1] === 'S') o.tables += Object.keys(json_(k, {})).length;
      if (m[1] === 'R') o.names = Object.keys(json_(k, {})).length;
      if (m[1] === 'A') o.avail += 1;
      if (m[1] === 'U') o.updated = get_(k);
    });
    Logger.log(JSON.stringify(seasons, null, 1));
    Logger.log('保存領域の使用: 約' + Math.round(JSON.stringify(SNAP).length / 1024) + 'KB / 500KB');
  } finally {
    SNAP = null;
  }
}

// PURGE にシーズンの名前を入れて動かすと、そのシーズンの点数・名簿・予定・最終更新を消す（終わったら '' に戻す）
const PURGE = '';
function purgeSeason() {
  if (!SEASON_RE.test(PURGE)) { Logger.log('PURGE にシーズンの名前を入れてください'); return; }
  const props = PropertiesService.getScriptProperties();
  const keys = Object.keys(props.getProperties()).filter(function (k) {
    return k === 'R_' + PURGE || k === 'U_' + PURGE || k.indexOf('S_' + PURGE + '_') === 0 || k.indexOf('A_' + PURGE + '_') === 0;
  });
  keys.forEach(function (k) { props.deleteProperty(k); });
  Logger.log(PURGE + ' を消しました（' + keys.length + '項目）');
}

// 全部を消す（すべてのシーズンと送信履歴）
function resetAll() {
  PropertiesService.getScriptProperties().deleteAllProperties();
  Logger.log('全部を消しました');
}
