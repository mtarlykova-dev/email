#!/usr/bin/env python3
"""Забирает из Sendsay API статистику массовых рассылок — выпусков без сценария.

Одна строка = один выпуск за всё время (открытия и клики по рассылке копятся днями,
поэтому каждый запуск перезапрашивает весь период с campaigns.start_date).
Только агрегаты уровня выпуска (issue.*), адреса не запрашиваются.

Переменные окружения: SENDSAY_LOGIN, SENDSAY_APIKEY (как у fetch_sendsay.py).
Запуск:  python scripts/fetch_campaigns.py [--debug]
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import CAMPAIGNS_FILE, METRICS, load_config  # noqa: E402
from fetch_sendsay import SendsayError, call  # noqa: E402

PAGE = 5000
FIELDS = [
    ("id", "issue.id"),
    ("dt", "issue.dt"),
    ("name", "issue.name"),
    ("subject", "issue.subject"),
    ("sent", "sum(issue.members)"),
    ("delivered", "sum(issue.deliv_ok)"),
    ("bounced", "sum(issue.deliv_bad)"),
    ("opens", "sum(issue.readed)"),
    ("u_opens", "sum(issue.u_readed)"),
    ("clicks", "sum(issue.clicked)"),
    ("u_clicks", "sum(issue.u_clicked)"),
    ("unsubs", "sum(issue.unsubed)"),
]


def main():
    debug = "--debug" in sys.argv
    login = os.environ.get("SENDSAY_LOGIN", "").strip()
    apikey = os.environ.get("SENDSAY_APIKEY", "").strip()
    if not login or not apikey:
        sys.exit("Нет SENDSAY_LOGIN / SENDSAY_APIKEY.")

    cfg = load_config()
    c = cfg.get("campaigns", {})
    since = c.get("start_date") or cfg["start_date"]
    flt = [
        {"a": "issue.dt:YD", "op": ">=", "v": since},
        {"a": "issue.sequence.id", "op": "is_null"},
    ]
    raw, skip = [], 0
    while True:
        req = {"action": "stat.uni", "select": [api for _, api in FIELDS], "filter": flt,
               "order": ["issue.dt"], "skip": skip, "first": PAGE}
        data = call(login, apikey, req, debug)
        page = data.get("list")
        if page is None:
            raise SendsayError(f"В ответе нет поля list: {list(data.keys())}")
        raw.extend(page)
        if len(page) < PAGE:
            break
        skip += PAGE

    # Выпуск может прийти несколькими строками (например, если у него несколько дат) — склеиваем по ID.
    acc = {}
    for r in raw:
        r = dict(zip([k for k, _ in FIELDS], r)) if not isinstance(r, dict) else {k: r.get(a) for k, a in FIELDS}
        iid = str(r["id"] or "")
        if not iid or not r["dt"]:
            continue
        row = acc.setdefault(iid, {"id": iid, "dt": str(r["dt"])[:16], "name": (r["name"] or "").strip(),
                                   "subject": (r["subject"] or "").strip(), **{m: 0 for m in METRICS}})
        row["dt"] = min(row["dt"], str(r["dt"])[:16])
        for m in METRICS:
            row[m] += int(float(r[m] or 0))
    rows = sorted(acc.values(), key=lambda x: (x["dt"], x["id"]))

    CAMPAIGNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with open(CAMPAIGNS_FILE, "w", encoding="utf-8") as f:
        f.write('{"generated_at":%s,"since":%s,"rows":[\n' % (json.dumps(now), json.dumps(since)))
        f.write(",\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows))
        f.write("\n]}\n")
    big = [r for r in rows if r["sent"] >= int(c.get("min_sent", 0))]
    print(f"Массовых рассылок с {since}: {len(rows)} (от {c.get('min_sent', 0)} получателей: {len(big)}), "
          f"отправлено писем: {sum(r['sent'] for r in rows)}")


if __name__ == "__main__":
    try:
        main()
    except SendsayError as e:
        sys.exit(f"Ошибка Sendsay API: {e}")
