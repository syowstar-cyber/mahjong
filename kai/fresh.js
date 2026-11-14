// 古いページを出さない（2026-11-14 主催「前のページが表示されないようにして」）。トップ・点数入力・対戦表・幹部用・会のルールと早見表が <head> で読む。
// GitHub Pages はページを端末に10分まで置いてよい（Cache-Control: max-age=600）ので、直した直後は前のページが出ることがある。
// 開いたときと裏から戻ったときに、出ているページの日時（document.lastModified）と、サーバーのいまの日時（HEAD。手元の写しは使わない）を比べる。
// 新しい版があれば、手元の写しを取り直して開き直す。このページで何か入れた後は勝手に開き直さず、一番上に知らせを出す（打ちかけの点数などを消さない）。
// 同じ版への自動の開き直しは、このタブで1回だけ（取り直しても古いままのときに繰り返さない）。試験の写し（KAI_CONF_DIR）では使わない
(() => {
  if (window.KAI_CONF_DIR !== undefined || !window.fetch) return;
  const m = /^(\d\d)\/(\d\d)\/(\d{4}) (\d\d):(\d\d):(\d\d)$/.exec(document.lastModified || '');
  if (!m) return;
  const shown = new Date(+m[3], m[1] - 1, +m[2], +m[4], +m[5], +m[6]).getTime();
  const url = location.href.split('#')[0], key = 'halukai:fresh:' + location.pathname + location.search;
  let typed = false, busy = false, last = 0;
  ['input', 'change'].forEach(t => document.addEventListener(t, () => { typed = true; }, true));
  const refresh = () => fetch(url, { cache: 'reload' }).catch(() => {}).then(() => location.reload());
  function notice() {
    if (document.getElementById('freshbar')) return;
    const b = document.createElement('button');
    b.type = 'button'; b.id = 'freshbar';
    b.textContent = 'このページの新しい版があります。押すと開き直します。';
    b.style.cssText = 'position:sticky;top:0;z-index:20;display:block;width:100%;margin:0 0 8px;padding:10px 12px;border:2px solid var(--accent,#7a1a1a);border-radius:8px;background:var(--soft,#faf3e3);color:var(--accent,#7a1a1a);font:inherit;font-weight:700;text-align:left;cursor:pointer';
    b.addEventListener('click', refresh);
    const w = document.querySelector('.wrap') || document.body;
    w.insertBefore(b, w.firstChild);
  }
  function check() {
    if (busy || Date.now() - last < 60000) return;
    busy = true; last = Date.now();
    fetch(url, { method: 'HEAD', cache: 'no-store' }).then(r => {
      const lm = Date.parse(r.headers.get('last-modified') || '');
      if (!r.ok || !(lm > shown + 1000)) return;
      let again = true;
      try { again = sessionStorage.getItem(key) === String(lm); if (!again) sessionStorage.setItem(key, String(lm)); } catch (e) { again = true; }
      if (typed || again) notice(); else refresh();
    }).catch(() => {}).then(() => { busy = false; });
  }
  check();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) check(); });
  window.addEventListener('pageshow', e => { if (e.persisted) check(); });
})();
