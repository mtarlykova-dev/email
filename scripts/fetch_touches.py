#!/usr/bin/env python3
"""Забирает из Sendsay API контакты по людям для блока «Конверсии»:
кто получил, открыл и кликнул какое письмо сценария и когда.

Нужно, чтобы сопоставить клики с выгрузкой целевых действий из бэк-офиса
(файл загружается на странице отчёта и обрабатывается только в браузере).

Адреса в репозиторий НЕ попадают: data/touch.json в .gitignore, а в отчёт
build.py кладёт только хэши (HMAC от пароля отчёта) внутри зашифрованных данных.
Полные адреса ссылок не сохраняются — только тип перехода (сайт/ЛК, Telegram, другое).

Переменные окружения: SENDSAY_LOGIN, SENDSAY_APIKEY (как у fetch_sendsay.py).
Запуск:  python scripts/fetch_touches.py [--debug]
"""
import datetime as dt
import json
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(__file__))
from common import ROOT, load_config  # noqa: E402
from fetch_sendsay import SendsayError, call  # noqa: E402

TOUCH_FILE = ROOT / "data" / "touch.json"
PAGE = 5000


def dest_of(url):
    """Куда вела ссылка: tg — Telegram, site — сайт или личный кабинет, other — соцсети и прочее."""
    try:
        host = (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return "other"
    if host in ("t.me", "telegram.me") or host.endswith(".t.me"):
        return "tg"
    if any(host == d or host.endswith("." + d) for d in ("capitalist.net", "cardspro.biz", "cardspro.com", "card.club")):
        return "site"
    return "other"


def fetch_all(login, apikey, select, flt, debug):
    out, skip = [], 0
    while True:
        req = {"action": "stat.uni", "select": select, "filter": flt, "skip": skip, "first": PAGE}
        data = call(login, apikey, req, debug)
        page = data.get("list")
        if page is None:
            raise SendsayError(f"В ответе нет поля list: {list(data.keys())}")
        out.extend(page)
        if len(page) < PAGE:
            return out
        skip += PAGE


def main():
    debug = "--debug" in sys.argv
    login = os.environ.get("SENDSAY_LOGIN", "").strip()
    apikey = os.environ.get("SENDSAY_APIKEY", "").strip()
    if not login or not apikey:
        sys.exit("Нет SENDSAY_LOGIN / SENDSAY_APIKEY.")

    cfg = load_config()
    conv = cfg.get("conversions", {})
    days = int(conv.get("days", 90))
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat() + " 00:00:00"
    # Сценарии с целями + те, что в них склеиваются (merge_into).
    goal_seqs = set(conv.get("goals", {}))
    merges = {s: str(c["merge_into"]) for s, c in cfg.get("scenarios", {}).items() if c.get("merge_into")}
    seqs = goal_seqs | {s for s, t in merges.items() if t in goal_seqs}

    deliv = fetch_all(login, apikey, [
        "deliv.member.email", "deliv.member.anketa.custom.login", "deliv.member.anketa.custom.id_back_office",
        "deliv.issue.id", "deliv.issue.dt", "deliv.issue.sequence.id", "deliv.issue.name", "deliv.issue.subject",
    ], [{"a": "deliv.issue.dt", "op": ">=", "v": since}, {"a": "deliv.issue.sequence.id", "op": "!is_null"}], debug)
    reads = fetch_all(login, apikey, ["read.member.email", "read.issue.id", "read.dt", "read.issue.sequence.id"],
                      [{"a": "read.dt", "op": ">=", "v": since}, {"a": "read.issue.sequence.id", "op": "!is_null"}], debug)
    clicks = fetch_all(login, apikey, ["click.member.email", "click.issue.id", "click.dt", "click.issue.sequence.id", "click.link.url"],
                       [{"a": "click.dt", "op": ">=", "v": since}, {"a": "click.issue.sequence.id", "op": "!is_null"}], debug)

    issues, people, d_rows, o_rows, c_rows = {}, {}, [], [], []
    for email, lg, bo, iid, idt, seq, name, subj in deliv:
        seq = str(seq)
        if seq not in seqs or not email:
            continue
        email = email.strip().lower()
        issues[str(iid)] = [seq, (name or "").strip(), (subj or "").strip()]
        p = people.setdefault(email, ["", ""])
        p[0] = p[0] or (lg or "").strip()
        p[1] = p[1] or str(bo or "").strip()
        d_rows.append([email, str(iid), str(idt)[:16]])
    for email, iid, rdt, seq in reads:
        if str(seq) in seqs and email and str(iid) in issues:
            o_rows.append([email.strip().lower(), str(iid), str(rdt)[:16]])
    hosts = {}
    for email, iid, cdt, seq, url in clicks:
        if str(seq) in seqs and email and str(iid) in issues:
            d = dest_of(url)
            c_rows.append([email.strip().lower(), str(iid), str(cdt)[:16], d])
            try:
                h = (urlparse(url or "").hostname or "—").lower()
            except ValueError:
                h = "—"
            hosts[(d, h)] = hosts.get((d, h), 0) + 1
    # Домены ссылок (без адресов людей) — чтобы проверить, что сайт и ЛК распознаются правильно.
    print("Клики по доменам: " + "; ".join(f"{h} → {d}: {n}" for (d, h), n in sorted(hosts.items(), key=lambda x: -x[1])[:15]))

    TOUCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "since": since[:10], "issues": issues, "people": people,
        "deliv": d_rows, "read": o_rows, "click": c_rows,
    }
    with open(TOUCH_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Контакты по людям с {since[:10]}: получателей {len(people)}, доставок {len(d_rows)}, "
          f"открытий {len(o_rows)}, кликов {len(c_rows)} (сценарии: {', '.join(sorted(seqs, key=int))})")


if __name__ == "__main__":
    try:
        main()
    except SendsayError as e:
        sys.exit(f"Ошибка Sendsay API: {e}")
