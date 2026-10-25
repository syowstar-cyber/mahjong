// 早川麻雀研究会 点数 API（Google Apps Script ウェブアプリ）
// Halu杯の受け口（halu-cup リポの gas/Code.gs）とは別のプロジェクトとして置く。データを混ぜない。
// ドライブは使わない。スクリプト プロパティに JSON を持つ。配置手順は hayakawa/gas/README.md。
//
// 書き込み（POST・本文は JSON・キーなし）:
//   {round:'1'..'6', seats:['東家','南家','西家','北家'], scores:{名前: 点棒, ...}}   … 1半荘ぶんを記録（記録済みの半荘は上書きしない＝error 'exists'）
//   {action:'clear', round:'1'..'6'}   … その半荘を取り消す

const PLAYERS = ['早川さん', '志村さん', '祐輝君', 'ショウタロウ'];
const ROUNDS = ['1', '2', '3', '4', '5', '6'];
const LOG_MAX = 100;

function props_() { return PropertiesService.getScriptProperties(); }

function load_() {
  const p = props_();
  let rounds, log;
  try { rounds = JSON.parse(p.getProperty('ROUNDS') || '{}'); } catch (e) { rounds = {}; }
  try { log = JSON.parse(p.getProperty('LOG') || '[]'); } catch (e) { log = []; }
  return { updated: p.getProperty('UPDATED') || null, rounds: rounds || {}, log: log || [] };
}

function save_(d) {
  const p = props_();
  p.setProperty('ROUNDS', JSON.stringify(d.rounds));
  p.setProperty('LOG', JSON.stringify(d.log.slice(-LOG_MAX)));
  p.setProperty('UPDATED', d.updated || '');
}

function out_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}

function now_() {
  return Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd HH:mm:ss');
}

function doGet(e) {
  return out_({ ok: true, data: load_() });
}

function doPost(e) {
  let body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return out_({ ok: false, error: 'bad_json' }); }
  const round = String(body.round || '');
  if (ROUNDS.indexOf(round) < 0) return out_({ ok: false, error: 'round' });

  let entry = null;
  if (body.action !== 'clear') {
    const seats = body.seats;
    if (!Array.isArray(seats) || seats.length !== 4) return out_({ ok: false, error: 'seats' });
    for (let i = 0; i < 4; i++) {
      if (PLAYERS.indexOf(seats[i]) < 0 || seats.indexOf(seats[i]) !== i) return out_({ ok: false, error: 'seats' });
    }
    const scores = {};
    for (let i = 0; i < PLAYERS.length; i++) {
      const v = Number((body.scores || {})[PLAYERS[i]]);
      if (!Number.isInteger(v) || v < -200000 || v > 300000) return out_({ ok: false, error: 'score' });
      scores[PLAYERS[i]] = v;
    }
    entry = { seats: seats.slice(), scores: scores };
  }

  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const d = load_();
    if (entry && d.rounds[round]) return out_({ ok: false, error: 'exists', data: d });
    if (entry) d.rounds[round] = entry; else delete d.rounds[round];
    d.updated = now_();
    d.log.push({ ts: d.updated, round: round, clear: !entry, scores: entry ? entry.scores : null });
    save_(d);
    return out_({ ok: true, data: d });
  } finally {
    lock.releaseLock();
  }
}

// 全消去（エディタから手で実行する用。次の会を始める前に使う）
function resetAll() {
  const p = props_();
  p.deleteProperty('ROUNDS');
  p.deleteProperty('LOG');
  p.deleteProperty('UPDATED');
}
