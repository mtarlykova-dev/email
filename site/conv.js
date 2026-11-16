/* Блок «Конверсии»: сопоставление выгрузки бэк-офиса с контактами по письмам.
 *
 * Файл выгрузки обрабатывается только в браузере и никуда не отправляется.
 * В данных отчёта нет адресов: только хэши (HMAC-SHA256 с ключом из пароля отчёта),
 * поэтому email, логин и ID из файла хэшируются тем же способом и сравниваются по хэшам.
 *
 * Правило: для каждого участника цепочки берём первое целевое действие ПОСЛЕ первого
 * письма цепочки. Если до него в пределах окна был клик по письму этой цепочки — действие
 * засчитывается последнему такому письму («после клика»); если клика не было, но было
 * открытие — «после открытия»; иначе — «сами».
 */
(function (root) {
  "use strict";

  const EVENT_ALIASES = [
    [/^kyc/, "kyc_passed"], [/^kyb/, "kyb_passed"],
    [/^card_?issued|выпуск.*карт|карт.*выпущ|first_card$/, "card_issued"],
    [/^card_?top_?up|пополн.*карт|карт.*пополн/, "card_topup"],
    [/^deposit|пополн|депозит/, "deposit"],
    [/^transaction|транзакц|плат[её]ж|выплат|payout|payment/, "transaction"],
    [/kyc/, "kyc_passed"], [/kyb/, "kyb_passed"],
  ];
  const HEADERS = {
    email: ["email", "e-mail", "почта", "емейл", "имейл", "mail"],
    login: ["login", "логин"],
    bo: ["id_back_office", "id back office", "back_office_id", "bo_id", "id бэк-офиса", "id бэкофиса", "id_bo", "id"],
    product: ["product", "продукт"],
    event: ["event", "событие", "тип события", "event_type", "действие"],
    dt: ["event_datetime", "datetime", "дата и время", "дата", "date", "event_date", "время"],
    amount: ["amount", "сумма"],
  };
  const DEST = ["Сайт / ЛК", "Telegram", "Другое (соцсети)"];

  function normEvent(v, known) {
    const s = String(v || "").trim().toLowerCase();
    if (!s) return null;
    if (known && known[s]) return s;
    for (const [re, k] of EVENT_ALIASES) if (re.test(s)) return k;
    if (known) for (const [k, label] of Object.entries(known)) if (label.toLowerCase() === s) return k;
    return null;
  }

  // ---------- Разбор файла ----------
  function parseCSV(text) {
    text = text.replace(/^﻿/, "");
    const first = text.split(/\r?\n/, 1)[0] || "";
    const delim = [";", "\t", ","].map(d => [d, first.split(d).length]).sort((a, b) => b[1] - a[1])[0][0];
    const rows = []; let row = [], cell = "", q = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (q) {
        if (ch === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; }
        else cell += ch;
      } else if (ch === '"' && cell === "") q = true;
      else if (ch === delim) { row.push(cell); cell = ""; }
      else if (ch === "\n" || ch === "\r") {
        if (ch === "\r" && text[i + 1] === "\n") i++;
        row.push(cell); cell = ""; if (row.some(c => c.trim() !== "")) rows.push(row); row = [];
      } else cell += ch;
    }
    row.push(cell); if (row.some(c => c.trim() !== "")) rows.push(row);
    return rows;
  }

  function mapHeader(head) {
    const idx = {};
    head.forEach((h, i) => {
      const n = String(h || "").trim().toLowerCase().replace(/\s+/g, " ");
      for (const [k, al] of Object.entries(HEADERS)) if (idx[k] == null && al.includes(n)) idx[k] = i;
    });
    return idx;
  }

  const EPOCH = Date.UTC(2026, 0, 1, 0, 0) - 3 * 3600e3; // 01.01.2026 00:00 МСК
  // Дата/время из файла (МСК) -> минуты от 01.01.2026 МСК. {t, noTime} или null.
  function parseDT(v) {
    if (v == null || v === "") return null;
    if (typeof v === "number" || /^\d{5}(\.\d+)?$/.test(String(v).trim())) { // серийная дата Excel
      // Excel хранит «настенное» время (МСК) в днях от 30.12.1899.
      const wall = Math.round((+v - 25569) * 864e5);
      const noTime = Number.isInteger(+v);
      const ms = (noTime ? wall + (23 * 60 + 59) * 6e4 : wall) - 3 * 3600e3;
      return { t: Math.round((ms - EPOCH) / 6e4), noTime };
    }
    const s = String(v).trim();
    let m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::\d{2}(?:\.\d+)?)?)?/);
    let Y, M, D, h, mi;
    if (m) [, Y, M, D, h, mi] = m;
    else {
      m = s.match(/^(\d{1,2})[./](\d{1,2})[./](\d{4})(?:,?\s+(\d{1,2}):(\d{2})(?::\d{2})?)?/);
      if (!m) return null;
      [, D, M, Y, h, mi] = m;
    }
    const noTime = h == null;
    const ms = Date.UTC(+Y, +M - 1, +D, noTime ? 23 : +h, noTime ? 59 : +mi) - 3 * 3600e3;
    if (!isFinite(ms)) return null;
    return { t: Math.round((ms - EPOCH) / 6e4), noTime };
  }
  function fmtT(t) {
    const d = new Date(EPOCH + t * 6e4 + 3 * 3600e3);
    const p = n => String(n).padStart(2, "0");
    return `${p(d.getUTCDate())}.${p(d.getUTCMonth() + 1)}.${d.getUTCFullYear()} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
  }
  function fmtDay(t) { return fmtT(t).slice(0, 10); }

  // rows: массив массивов (первая строка — заголовок). -> {events, problems, head}
  function readRows(rows, eventsDict) {
    const res = { events: [], problems: [], missing: [] };
    if (!rows.length) { res.missing.push("файл пустой"); return res; }
    const idx = mapHeader(rows[0]);
    if (idx.event == null) res.missing.push("event (тип события)");
    if (idx.dt == null) res.missing.push("event_datetime (дата и время)");
    if (idx.email == null && idx.login == null && idx.bo == null) res.missing.push("email, login или id_back_office");
    if (res.missing.length) return res;
    const g = (r, k) => idx[k] == null ? "" : String(r[idx[k]] ?? "").trim();
    for (let i = 1; i < rows.length; i++) {
      const r = rows[i];
      const raw = { line: i + 1, email: g(r, "email"), login: g(r, "login"), bo: g(r, "bo"), product: g(r, "product"),
        eventRaw: g(r, "event"), dtRaw: idx.dt == null ? "" : r[idx.dt], amount: g(r, "amount") };
      const ev = normEvent(raw.eventRaw, eventsDict);
      const dt = parseDT(raw.dtRaw);
      if (!raw.email && !raw.login && !raw.bo) { res.problems.push(Object.assign({ why: "нет email, логина и ID" }, raw)); continue; }
      if (!ev) { res.problems.push(Object.assign({ why: `неизвестный тип события «${raw.eventRaw}»` }, raw)); continue; }
      if (!dt) { res.problems.push(Object.assign({ why: `не разобрать дату «${raw.dtRaw}»` }, raw)); continue; }
      res.events.push(Object.assign(raw, { event: ev, t: dt.t, noTime: dt.noTime }));
    }
    return res;
  }

  // ---------- Хэши ----------
  async function makeHasher(password, subtle) {
    subtle = subtle || (root.crypto && root.crypto.subtle);
    const enc = new TextEncoder();
    const raw = await subtle.digest("SHA-256", enc.encode("conv-match-v1:" + (password || "")));
    const key = await subtle.importKey("raw", raw, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    const cache = new Map();
    return async (kind, value) => {
      const v = String(value || "").trim().toLowerCase();
      if (!v) return "";
      const k = kind + ":" + v;
      if (cache.has(k)) return cache.get(k);
      const sig = new Uint8Array(await subtle.sign("HMAC", key, enc.encode(k)));
      const hex = Array.from(sig.slice(0, 8), b => b.toString(16).padStart(2, "0")).join("");
      cache.set(k, hex);
      return hex;
    };
  }

  // ---------- Сопоставление ----------
  async function match(C, parsed, hasher, opts) {
    opts = opts || {};
    const byEmail = new Map(), byLogin = new Map(), byBo = new Map();
    C.people.forEach(([e, l, b], i) => { if (e) byEmail.set(e, i); if (l) byLogin.set(l, i); if (b) byBo.set(b, i); });

    // Люди из файла -> индекс получателя в Sendsay
    const evBy = new Map(); // pi -> [events]
    const unmatched = [];
    const how = { email: 0, login: 0, bo: 0 };
    for (const ev of parsed.events) {
      let pi = null;
      if (ev.email) { const h = await hasher("email", ev.email); if (byEmail.has(h)) { pi = byEmail.get(h); how.email++; } }
      if (pi == null && ev.login) { const h = await hasher("login", ev.login); if (byLogin.has(h)) { pi = byLogin.get(h); how.login++; } }
      if (pi == null && ev.bo) { const h = await hasher("bo", ev.bo); if (byBo.has(h)) { pi = byBo.get(h); how.bo++; } }
      if (pi == null) { unmatched.push(ev); continue; }
      if (!evBy.has(pi)) evBy.set(pi, []);
      evBy.get(pi).push(ev);
    }
    for (const list of evBy.values()) list.sort((a, b) => a.t - b.t);

    const tMin = parsed.events.length ? Math.min(...parsed.events.map(e => e.t)) : null;
    const tMax = parsed.events.length ? Math.max(...parsed.events.map(e => e.t)) : null;
    const covFrom = opts.from != null ? opts.from : tMin;
    const covTo = opts.to != null ? opts.to : tMax;

    // Контакты по людям, сгруппированные по цепочке
    const L = C.letters; // [seq, key, label, step, lang]
    const group = (rows) => {
      const m = new Map();
      for (const r of rows) {
        const seq = L[r[1]][0];
        const k = seq + "|" + r[0];
        if (!m.has(k)) m.set(k, []);
        m.get(k).push(r);
      }
      return m;
    };
    const D = group(C.d), O = group(C.o), K = group(C.c);

    const result = { coverage: [covFrom, covTo], how, unmatched, problems: parsed.problems, chains: [], afterGoal: [] };
    for (const [seq, goal] of Object.entries(C.goals)) {
      const W = (goal.window_days || 7) * 1440;
      const tgt = new Set(goal.target || []), sec = new Set(goal.secondary || []);
      const ch = {
        seq, goal, participants: 0, clickers: 0, before: 0,
        total: 0, viaClick: 0, viaOpen: 0, self: 0, nonClickersConv: 0,
        secTotal: 0, secViaClick: 0, recent: 0, kept: 0,
        letters: new Map(), dest: [0, 0, 0].map(() => ({ clickers: 0, conv: 0 })),
      };
      const letterRow = li => {
        if (!ch.letters.has(li)) ch.letters.set(li, { li, got: 0, clicked: 0, viaClick: 0, viaOpen: 0 });
        return ch.letters.get(li);
      };
      for (const [k, dl] of D) {
        const [s, piS] = k.split("|"); if (s !== seq) continue;
        const pi = +piS;
        const entry = dl[0][2];
        if (covFrom != null && (entry < covFrom || entry > covTo)) continue;
        ch.participants++;
        const gotLetters = new Set(dl.map(r => r[1]));
        gotLetters.forEach(li => letterRow(li).got++);
        const cl = K.get(k) || [], op = O.get(k) || [];
        if (cl.length) ch.clickers++;
        new Set(cl.map(r => r[1])).forEach(li => letterRow(li).clicked++);
        const destSeen = new Set(cl.map(r => r[3]));
        destSeen.forEach(d => ch.dest[d].clickers++);
        if (covTo != null && covTo - entry < W) ch.recent++;

        const evs = evBy.get(pi) || [];
        if (evs.some(e => tgt.has(e.event) && e.t < entry)) ch.before++;
        const attribute = (e) => {
          const c = cl.filter(r => r[2] <= e.t && e.t - r[2] <= W).pop();
          if (c) return ["click", c];
          const o = op.filter(r => r[2] <= e.t && e.t - r[2] <= W).pop();
          if (o) return ["open", o];
          return ["self", null];
        };
        const first = evs.find(e => tgt.has(e.event) && e.t >= entry);
        if (first) {
          ch.total++;
          const [kind, r] = attribute(first);
          if (kind === "click") { ch.viaClick++; letterRow(r[1]).viaClick++; ch.dest[r[3]].conv++; }
          else if (kind === "open") { ch.viaOpen++; letterRow(r[1]).viaOpen++; }
          else ch.self++;
          if (!cl.length) ch.nonClickersConv++;
          // Сверка: человек продолжал получать письма цепочки после целевого действия.
          const after = dl.filter(r => r[2] > first.t);
          if (after.length) {
            ch.kept++;
            result.afterGoal.push({ seq, chain: goal.name, ev: first, letters: after.length, lastLetter: L[after[after.length - 1][1]][2], lastAt: after[after.length - 1][2] });
          }
        }
        const s2 = evs.find(e => sec.has(e.event) && e.t >= entry);
        if (s2) { ch.secTotal++; if (attribute(s2)[0] === "click") ch.secViaClick++; }
      }
      ch.letters = [...ch.letters.values()].sort((a, b) => (L[a.li][4] || "").localeCompare(L[b.li][4] || "") || L[a.li][3] - L[b.li][3]);
      result.chains.push(ch);
    }
    return result;
  }

  // ---------- Выгрузки результата ----------
  function toCSV(rows) {
    const q = v => { const s = v == null ? "" : String(v); return /[;"\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    return "﻿" + rows.map(r => r.map(q).join(";")).join("\n") + "\n";
  }
  function summaryRows(C, res) {
    const out = [["Цепочка", "Письмо", "Целевое действие", "Получили", "Кликнули", "Целевое действие всего", "После клика", "После открытия", "Сами", "Конверсия кликнувших", "Конверсия некликнувших"]];
    const pc = (a, b) => b ? (a / b * 100).toFixed(1).replace(".", ",") + "%" : "";
    for (const ch of res.chains) {
      out.push([ch.goal.name, "Вся цепочка", ch.goal.target_label, ch.participants, ch.clickers, ch.total, ch.viaClick, ch.viaOpen, ch.self,
        pc(ch.viaClick, ch.clickers), pc(ch.nonClickersConv, ch.participants - ch.clickers)]);
      for (const l of ch.letters) out.push([ch.goal.name, C.letters[l.li][2], ch.goal.target_label, l.got, l.clicked, "", l.viaClick, l.viaOpen, "", pc(l.viaClick, l.clicked), ""]);
    }
    return out;
  }
  function issueRows(res) {
    const out = [["Что не так", "Строка файла", "email", "login", "id_back_office", "Событие", "Дата и время", "Подробности"]];
    for (const e of res.unmatched) out.push(["Нет в рассылках Sendsay за период", e.line, e.email, e.login, e.bo, e.eventRaw, fmtT(e.t), ""]);
    for (const e of res.problems) out.push(["Строка не разобрана", e.line, e.email, e.login, e.bo, e.eventRaw, e.dtRaw, e.why]);
    for (const a of res.afterGoal) out.push(["Получал письма цепочки после целевого действия", a.ev.line, a.ev.email, a.ev.login, a.ev.bo, a.ev.eventRaw, fmtT(a.ev.t),
      `${a.chain}: ещё ${a.letters} писем, последнее ${a.lastLetter} ${fmtT(a.lastAt)}`]);
    return out;
  }

  const api = { parseCSV, readRows, parseDT, fmtT, fmtDay, makeHasher, match, toCSV, summaryRows, issueRows, normEvent, DEST };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CONV = api;
})(typeof self !== "undefined" ? self : this);
