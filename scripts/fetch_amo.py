#!/usr/bin/env python3
"""Забирает из amoCRM смены этапов сделок для вкладок «цепочка → воронка» (config.json → crm_tabs).

Берём события «этап сделки изменён» (lead_status_changed) в воронке каждой вкладки на её целевые
этапы — и email контактов этих сделок.
Сопоставление с кликами Sendsay делает build.py; в отчёт попадают только агрегаты.
data/amo.json содержит адреса — он в .gitignore и в репозиторий не попадает.

Переменные окружения:
  AMO_TOKEN — долгосрочный токен закрытой интеграции amoCRM (секрет GitHub)
Запуск:  python scripts/fetch_amo.py [--debug]
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from common import ROOT, load_config  # noqa: E402

AMO_FILE = ROOT / "data" / "amo.json"
MSK = dt.timezone(dt.timedelta(hours=3))


class AmoError(RuntimeError):
    pass


def get(base, token, path, params=None, debug=False):
    url = f"{base}{path}" + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    for attempt in range(5):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                time.sleep(0.2)  # лимит amo — 7 запросов в секунду
                if resp.status == 204:
                    return {}
                data = json.loads(resp.read().decode("utf-8") or "{}")
                if debug:
                    print(f"[debug] {path} -> {json.dumps(data, ensure_ascii=False)[:800]}", file=sys.stderr)
                return data
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise AmoError("amo отклонил токен (401). Проверьте секрет AMO_TOKEN: токен мог истечь или интеграцию отключили.")
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(3 * (attempt + 1))
                continue
            raise AmoError(f"HTTP {e.code} на {path}: {e.read()[:300]!r}")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 4:
                time.sleep(10 * (attempt + 1))
                continue
            raise AmoError(f"Нет связи с amo: {e}")
    raise AmoError("amo не ответил")


def chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def main():
    debug = "--debug" in sys.argv
    token = os.environ.get("AMO_TOKEN", "").strip()
    if not token:
        sys.exit("Нет AMO_TOKEN — вкладка «Welcome CardsPro → CRP» будет без данных amo.")
    cfg = load_config()
    base = f"https://{cfg['amo']['subdomain']}.amocrm.ru"
    tabs = {k: v for k, v in cfg.get("crm_tabs", {}).items() if not k.startswith("_")}
    days = int(cfg.get("conversions", {}).get("days", 90)) + 2
    since = dt.datetime.now(MSK) - dt.timedelta(days=days)

    events = []
    for key, tab in tabs.items():
        pid = int(tab["pipeline_id"])
        targets = {int(k): v for k, v in tab["statuses"].items()}
        # Проверяем, что этапы с такими ID есть в воронке и называются так же.
        pipe = get(base, token, f"/api/v4/leads/pipelines/{pid}", debug=debug)
        real = {st["id"]: st["name"] for st in pipe.get("_embedded", {}).get("statuses", [])}
        for sid, name in targets.items():
            if sid not in real:
                print(f"::warning::В воронке {pid} нет этапа {sid} ({name}) — проверьте config.json → crm_tabs.{key}.statuses")
            elif real[sid].strip().lower() != name.strip().lower():
                print(f"Воронка {pid}, этап {sid}: в config «{name}», в amo «{real[sid]}»")
        params = {"filter[type]": "lead_status_changed", "filter[created_at][from]": int(since.timestamp()), "limit": 100}
        for i, sid in enumerate(targets):
            params[f"filter[value_after][leads_statuses][{i}][pipeline_id]"] = pid
            params[f"filter[value_after][leads_statuses][{i}][status_id]"] = sid
        page, n0 = 1, len(events)
        while True:
            data = get(base, token, "/api/v4/events", dict(params, page=page), debug)
            batch = data.get("_embedded", {}).get("events", [])
            for e in batch:
                after = (e.get("value_after") or [{}])[0].get("lead_status") or {}
                if int(after.get("pipeline_id") or 0) == pid and int(after.get("id") or 0) in targets:
                    events.append((int(e["entity_id"]), int(e["created_at"]), int(after["id"]), pid))
            if not batch or not data.get("_links", {}).get("next"):
                break
            page += 1
        print(f"amo, воронка {tab.get('pipeline_name', pid)}: смен этапа на целевые с {since.date()}: {len(events) - n0}")

    lead_ids = sorted({e[0] for e in events})
    lead_contacts = {}
    for ch in chunks(lead_ids, 250):
        data = get(base, token, "/api/v4/leads", {"filter[id][]": ch, "with": "contacts", "limit": 250}, debug)
        for ld in data.get("_embedded", {}).get("leads", []):
            lead_contacts[ld["id"]] = [c["id"] for c in ld.get("_embedded", {}).get("contacts", [])]
    contact_ids = sorted({c for cs in lead_contacts.values() for c in cs})
    emails = {}
    for ch in chunks(contact_ids, 250):
        data = get(base, token, "/api/v4/contacts", {"filter[id][]": ch, "limit": 250}, debug)
        for c in data.get("_embedded", {}).get("contacts", []):
            vals = []
            for f in c.get("custom_fields_values") or []:
                if f.get("field_code") == "EMAIL":
                    vals += [str(v.get("value") or "").strip().lower() for v in f.get("values") or []]
            emails[c["id"]] = [v for v in vals if "@" in v]

    out, no_email = [], 0
    for lead, ts, sid, pid in sorted(events, key=lambda x: x[1]):
        addrs = sorted({a for c in lead_contacts.get(lead, []) for a in emails.get(c, [])})
        if not addrs:
            no_email += 1
        t = dt.datetime.fromtimestamp(ts, MSK).strftime("%Y-%m-%d %H:%M")
        for a in addrs:
            out.append([a, t, sid, lead, pid])
    AMO_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(AMO_FILE, "w", encoding="utf-8") as f:
        json.dump({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "since": since.date().isoformat(), "events": out}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"amo всего: смен этапа {len(events)}, сделок {len(lead_ids)}, без email у контакта: {no_email}")


if __name__ == "__main__":
    try:
        main()
    except AmoError as e:
        sys.exit(f"Ошибка amo: {e}")
