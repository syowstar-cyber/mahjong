// Halu杯 普段の回（3麻・4麻）点数の受け口（Google Apps Script ウェブアプリ）
// 第20回の受け口（halu-cup リポの gas/）とは別のプロジェクト。配置手順は kai/gas/README.md を見る。
// ドライブは使わない。スクリプト プロパティ（このスクリプト専用の保存領域）に、回（kai）ごとの JSON を持つ:
//   S_<kai>_<半荘> = {"<卓>": {p:['P3','P7','P1'], raw:[41000,35000,29000], ts:'…'}}   p と raw は席の順（東＝起家から）
//   R_<kai> = {"P1": "名前", …}   名簿。名前はここにだけ置く（公開リポにはファイルとして置かない）
//   U_<kai> = その回の最終更新の時刻（JST）
//   B_<kai> = {"P3": "YYYY-MM-DD", …}   生年月日（予選の同点は年齢が上の方が上位。同点のときだけ幹部用ページで入れる。2026-11-01）
//     生年月日そのものは GET でも返事でも返さない。返すのは入れた人どうしの年上からの順 agerank（1 が最年長・同じ日は同じ数）だけ
//   A_<kai> = 締め切った後の agerank（エディタの closeBirth で生年月日を消したとき。順位が元に戻らないように固定する）
//   K_<kai> = {"P3": {choice:'yes', ts:'…'}, …}   打ち上げの出欠（yes＝参加・no＝不参加。参加者ページで本人が答える。第20回の PARTY を P番号で持つ形。2026-11-01）
//   LOG = 送信履歴の直近 LOG_MAX 件（1件＝'MMDDHHmmss|kai|操作|半荘|卓'）
// 回を替えても消す作業は要らない（kai が違えば置き場が別）。古い回を消すのはエディタの purgeKai。
//
// 受け口（URL は1つ。キーなし＝第20回と同じ。範囲だけ検査し、送信履歴に時刻を残す）:
//   GET  ?kai=<kai>                                          … その回の点数・名簿・最終更新・年上からの順・打ち上げの出欠
//   POST {action:'score', kai, round, table, p:[…], raw:[…]} … 1卓ぶん（3人か4人）。同じ卓は上書き
//   POST {action:'clear', kai, round, table}                 … 1卓ぶんを消す
//   POST {action:'roster', kai, names:{P1:'名前', …}}        … 名簿（渡したキーだけ直す。'' で消す）
//   POST {action:'birth', kai, player:'P3', date:'YYYY-MM-DD'|''} … 生年月日（'' で消す。締め切った回は error:'closed'）
//   POST {action:'uchiage', kai, player:'P3', choice:'yes'|'no'|''} … 打ち上げの出欠（同じ人は上書き。'' で消す）
//   round は予選 '1'〜'20'・決勝 'F1'〜'F9'、table は 1〜TABLE_MAX。
//   返事は {ok:true, data:{kai, rounds, roster, updated, agerank, uchiage}} か {ok:false, error:'…'}。
//   同じ半荘のほかの卓に入っている人を送ると error:'dup'（players に該当者）で断る（卓の取り違え）

const KAI_RE = /^[0-9A-Za-z-]{1,24}$/;   // '_' は置き場の名前の区切りに使うので入れない
const ROUND_RE = /^([1-9]|1[0-9]|20|F[1-9])$/;
const PLAYER_RE = /^P([1-9]|[1-9][0-9])$/;
const TABLE_MAX = 40;
const RAW_MIN = -200000, RAW_MAX = 999900;   // 第20回と同じ（トビ終了なし・箱下あり）
const NAME_MAX = 20;
const LOG_MAX = 100;

// スクリプト プロパティは1日の読み書きの回数に上限がある（無料アカウントは1日5万回）。
// 1回の実行では getProperties() を1回だけ呼んで写し（SNAP）を作り、読むのはそこから（第20回 2026-10-24 の学び）。
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

// その回の全部（点数は半荘ごと、名簿、最終更新）
function data_(kai) {
  const pre = 'S_' + kai + '_', rounds = {};
  Object.keys(SNAP).forEach(function (k) {
    if (k.indexOf(pre) !== 0) return;
    const r = k.slice(pre.length);
    if (ROUND_RE.test(r)) rounds[r] = json_(k, {});
  });
  return { kai: kai, rounds: rounds, roster: json_('R_' + kai, {}), updated: get_('U_' + kai), agerank: ageRankOut_(kai), uchiage: json_('K_' + kai, {}) };
}

// 入れた人どうしの年上からの順。早く生まれた人ほど小さい数（1 が最年長）。同じ日は同じ数（第20回と同じ）
function ageRank_(birth) {
  const keys = Object.keys(birth), r = {};
  keys.forEach(function (p) { r[p] = 1 + keys.filter(function (q) { return birth[q] < birth[p]; }).length; });
  return r;
}
// 返す agerank。締め切った回（A_ がある）は、消す前の順を返し続ける
function ageRankOut_(kai) {
  return get_('A_' + kai) !== null ? json_('A_' + kai, {}) : ageRank_(json_('B_' + kai, {}));
}
// 'YYYY-MM-DD' で、実在する日付で、1900-01-01〜今日（JST）
function validBirth_(s) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const y = Number(s.slice(0, 4)), m = Number(s.slice(5, 7)), d = Number(s.slice(8, 10));
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return false;
  return s >= '1900-01-01' && s <= now_().slice(0, 10);
}

function log_(kai, act, round, table) {
  const log = json_('LOG', []);
  log.push(now_().slice(5).replace(/[-: ]/g, '') + '|' + kai + '|' + act + '|' + (round || '') + '|' + (table || ''));
  set_('LOG', JSON.stringify(log.slice(-LOG_MAX)));
}

// 書き込みはロックの中で。半荘の終わりに全卓の送信が重なっても待てるよう30秒（第20回と同じ）
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
  const kai = String((e && e.parameter && e.parameter.kai) || '');
  if (!KAI_RE.test(kai)) return out_({ ok: false, error: 'kai' });
  snap_();
  try {
    return out_({ ok: true, data: data_(kai) });
  } finally {
    SNAP = null;
  }
}

// 書き込み: POST（本文は JSON。ページは Content-Type を付けずに送る＝事前確認の要らない送り方）
function doPost(e) {
  let b;
  try { b = JSON.parse(e.postData.contents); } catch (err) { return out_({ ok: false, error: 'bad_json' }); }
  if (!b || typeof b !== 'object') return out_({ ok: false, error: 'bad_json' });
  const kai = String(b.kai || '');
  if (!KAI_RE.test(kai)) return out_({ ok: false, error: 'kai' });
  if (b.action === 'roster') return roster_(kai, b.names);
  if (b.action === 'birth') return birth_(kai, b.player, b.date);
  if (b.action === 'uchiage') return uchiage_(kai, b.player, b.choice);
  if (b.action !== 'score' && b.action !== 'clear') return out_({ ok: false, error: 'action' });

  const round = String(b.round || ''), table = Number(b.table);
  if (!ROUND_RE.test(round)) return out_({ ok: false, error: 'round' });
  if (!Number.isInteger(table) || table < 1 || table > TABLE_MAX) return out_({ ok: false, error: 'table' });
  let p = null, raw = null;
  if (b.action === 'score') {
    if (!Array.isArray(b.p) || (b.p.length !== 3 && b.p.length !== 4)) return out_({ ok: false, error: 'player' });
    p = b.p.map(String);
    const seen = {};
    for (let i = 0; i < p.length; i++) {
      if (!PLAYER_RE.test(p[i]) || seen[p[i]]) return out_({ ok: false, error: 'player' });
      seen[p[i]] = true;
    }
    if (!Array.isArray(b.raw) || b.raw.length !== p.length) return out_({ ok: false, error: 'score' });
    raw = b.raw.map(Number);
    if (raw.some(function (v) { return !Number.isInteger(v) || v % 100 !== 0 || v < RAW_MIN || v > RAW_MAX; })) return out_({ ok: false, error: 'score' });
  }

  return withLock_(function () {
    const key = 'S_' + kai + '_' + round, t = String(table);
    const cur = json_(key, {});
    if (b.action === 'score') {
      const dup = p.filter(function (x) {
        return Object.keys(cur).some(function (k) { return k !== t && cur[k] && Array.isArray(cur[k].p) && cur[k].p.indexOf(x) >= 0; });
      });
      if (dup.length) return out_({ ok: false, error: 'dup', players: dup, data: data_(kai) });
      cur[t] = { p: p, raw: raw, ts: now_() };
    } else {
      delete cur[t];
    }
    if (Object.keys(cur).length) set_(key, JSON.stringify(cur)); else if (get_(key) !== null) del_(key);
    set_('U_' + kai, now_());
    log_(kai, b.action, round, t);
    return out_({ ok: true, data: data_(kai) });
  });
}

// 名簿。names = {P1:'名前', …}。渡したキーだけ直し、'' は消す
function roster_(kai, names) {
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
    const r = json_('R_' + kai, {});
    keys.forEach(function (k) { if (vals[k]) r[k] = vals[k]; else delete r[k]; });
    if (Object.keys(r).length) set_('R_' + kai, JSON.stringify(r)); else if (get_('R_' + kai) !== null) del_('R_' + kai);
    set_('U_' + kai, now_());
    log_(kai, 'roster', '', String(keys.length));
    return out_({ ok: true, data: data_(kai) });
  });
}

// 生年月日（同点のときだけ幹部用ページで入れる）。date '' で消す。返事の data には agerank だけが入る（生年月日は返さない）
function birth_(kai, player, date) {
  player = String(player || ''); date = String(date || '');
  if (!PLAYER_RE.test(player)) return out_({ ok: false, error: 'player' });
  if (date && !validBirth_(date)) return out_({ ok: false, error: 'date' });
  return withLock_(function () {
    if (get_('A_' + kai) !== null) return out_({ ok: false, error: 'closed' });
    const b = json_('B_' + kai, {});
    if (date) b[player] = date; else delete b[player];
    if (Object.keys(b).length) set_('B_' + kai, JSON.stringify(b)); else if (get_('B_' + kai) !== null) del_('B_' + kai);
    set_('U_' + kai, now_());
    log_(kai, 'birth', '', player);
    return out_({ ok: true, data: data_(kai) });
  });
}

// 打ち上げの出欠（参加者ページで本人が答える）。choice 'yes'＝参加・'no'＝不参加・'' で消す。点数ではないので、最終更新（U_）は動かさない
function uchiage_(kai, player, choice) {
  player = String(player || ''); choice = String(choice || '');
  if (!PLAYER_RE.test(player)) return out_({ ok: false, error: 'player' });
  if (choice !== 'yes' && choice !== 'no' && choice !== '') return out_({ ok: false, error: 'choice' });
  return withLock_(function () {
    const u = json_('K_' + kai, {});
    if (choice) u[player] = { choice: choice, ts: now_() }; else delete u[player];
    if (Object.keys(u).length) set_('K_' + kai, JSON.stringify(u)); else if (get_('K_' + kai) !== null) del_('K_' + kai);
    log_(kai, 'uchiage', '', player);
    return out_({ ok: true, data: data_(kai) });
  });
}

// ---- ここから下はエディタで動かす（受け口からは呼べない） ----

// 置いてある回の一覧（点数の卓数・名簿の人数・最終更新）をログに出す
function listKai() {
  snap_();
  try {
    const kais = {};
    Object.keys(SNAP).forEach(function (k) {
      const m = /^([SRUBAK])_([0-9A-Za-z-]+)(?:_(.+))?$/.exec(k);
      if (!m) return;
      const o = kais[m[2]] || (kais[m[2]] = { tables: 0, names: 0, births: 0, uchiage: 0, closed: false, updated: '' });
      if (m[1] === 'S') o.tables += Object.keys(json_(k, {})).length;
      if (m[1] === 'R') o.names = Object.keys(json_(k, {})).length;
      if (m[1] === 'B') o.births = Object.keys(json_(k, {})).length;
      if (m[1] === 'K') o.uchiage = Object.keys(json_(k, {})).length;
      if (m[1] === 'A') o.closed = true;
      if (m[1] === 'U') o.updated = get_(k);
    });
    Logger.log(JSON.stringify(kais, null, 1));
    Logger.log('保存領域の使用: 約' + Math.round(JSON.stringify(SNAP).length / 1024) + 'KB / 500KB');
  } finally {
    SNAP = null;
  }
}

// PURGE に回の名前を入れて動かすと、その回の点数・名簿・生年月日・打ち上げの出欠・最終更新を消す（終わったら '' に戻す）
const PURGE = '';
function purgeKai() {
  if (!KAI_RE.test(PURGE)) { Logger.log('PURGE に回の名前を入れてください'); return; }
  const props = PropertiesService.getScriptProperties();
  const keys = Object.keys(props.getProperties()).filter(function (k) {
    return k === 'R_' + PURGE || k === 'U_' + PURGE || k === 'B_' + PURGE || k === 'A_' + PURGE || k === 'K_' + PURGE || k.indexOf('S_' + PURGE + '_') === 0;
  });
  keys.forEach(function (k) { props.deleteProperty(k); });
  Logger.log(PURGE + ' を消しました（' + keys.length + '項目）');
}

// CLOSE_BIRTH に回の名前を入れて動かすと、その回の生年月日を消し、消す前の年上からの順だけを残す（大会の後。以後は受け付けない。終わったら '' に戻す）
const CLOSE_BIRTH = '';
function closeBirth() {
  if (!KAI_RE.test(CLOSE_BIRTH)) { Logger.log('CLOSE_BIRTH に回の名前を入れてください'); return; }
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    snap_();
    if (get_('A_' + CLOSE_BIRTH) !== null) { Logger.log(CLOSE_BIRTH + ' は締め切り済みです'); return; }
    set_('A_' + CLOSE_BIRTH, JSON.stringify(ageRank_(json_('B_' + CLOSE_BIRTH, {}))));
    if (get_('B_' + CLOSE_BIRTH) !== null) del_('B_' + CLOSE_BIRTH);
    Logger.log(CLOSE_BIRTH + ' の生年月日を消し、年上からの順だけを残しました');
  } finally {
    SNAP = null;
    lock.releaseLock();
  }
}

// 全部を消す（すべての回と送信履歴）
function resetAll() {
  PropertiesService.getScriptProperties().deleteAllProperties();
  Logger.log('全部を消しました');
}
