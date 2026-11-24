#!/usr/bin/env python3
"""Генерирует ВЫДУМАННЫЕ данные для локальной проверки страницы (data/demo.json, не коммитится).

Запуск:
  python scripts/demo_data.py
  python scripts/build.py --data data/demo.json --touch data/touch_demo.json --campaigns data/campaigns_demo.json --amo data/amo_demo.json
  python -m http.server -d _site 8000
"""
import datetime as dt
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import ROOT, make_row  # noqa: E402

random.seed(7)
# (сценарий, письмо, тема, сдвиг в днях, OR, CTR, отписки, ошибки)
LETTERS = [
    ("5", "WC ru 1", "Добро пожаловать в Capitalist", 0, .23, .073, .004, .03),
    ("5", "WC ru 2", "Агентство, команда или фрилансер?", 2, .19, .016, .023, .03),
    ("5", "WC ru 3", "Тарифы без сюрпризов и карты без очередей", 5, .14, .019, .013, .03),
    ("5", "WC en 1", "Welcome to Capitalist", 0, .21, .061, .005, .04),
    ("5", "WC en 2", "Agency, team or freelancer?", 2, .16, .014, .018, .04),
    ("3", "CP en 1", "Welcome to CardsPro", 0, .25, .087, .004, .09),
    ("3", "CP en 2", "Have you issued your first card yet?", 2, .06, .015, .006, .066),
    ("3", "CP en 3", "What if your customers could pay with your cards?", 4, .035, .0045, .008, .065),
    ("3", "CP en 4", "CardsPro for teams", 7, .052, .0053, .007, .061),
    ("3", "CP ru 1", "Добро пожаловать в CardsPro", 0, .27, .09, .004, .02),
    ("1", "(1) Регистрация", "Остался один шаг до полного функционала", 0, .17, .019, .017, .02),
    ("1", "(2) Регистрация", "Криптовалюта, кошельки и карты CardsPro", 4, .09, .007, .015, .02),
    ("1", "(3) Регистрация", "Свой карт-сервис под брендом", 6, .12, .008, .014, .02),
    ("6", "After KYB ru", "Верификация пройдена — что дальше", 0, .31, .11, .003, .01),
    ("8", "1. Your CardsPro account is still available", "Your CardsPro account is still available", 0, .2, .03, .01, .02),
    ("8", "1. Ваш кабинет CardsPro еще доступен", "Ваш кабинет CardsPro еще доступен", 0, .22, .03, .01, .02),
    ("6", "After KYB en", "You're verified — what's next", 0, .28, .09, .003, .01),
]
VOLUME = {"5": 14, "3": 9, "1": 11, "6": 6, "8": 2}


def main():
    today = dt.date.today()
    start = today - dt.timedelta(days=160)
    rows = []
    for seq, name, subj, lag, or_, ctr, uns, bad in LETTERS:
        for i in range(160):
            day = start + dt.timedelta(days=i + lag)
            if day >= today:
                break
            if seq == "6" and (today - day).days <= 5:  # триггер «замолчал»
                continue
            base = VOLUME[seq] * (0.55 if " en" in name else 1)
            sent = max(0, int(random.gauss(base, base * 0.35)))
            if sent == 0:
                continue
            o = or_ * (0.6 if seq == "5" and "ru 2" in name and (today - day).days < 20 else 1)
            deliv = sum(random.random() > bad for _ in range(sent))
            uo = sum(random.random() < o for _ in range(deliv))
            uc = sum(random.random() < ctr for _ in range(deliv))
            un = sum(random.random() < uns for _ in range(deliv))
            rows.append(make_row(day.isoformat(), seq, name, subj, {
                "sent": sent, "delivered": deliv, "bounced": sent - deliv,
                "opens": int(uo * 1.4), "u_opens": uo, "clicks": int(uc * 1.3), "u_clicks": uc, "unsubs": un,
            }))
    out = ROOT / "data" / "demo.json"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "source": "demo", "rows": rows}, f, ensure_ascii=False)
    print(f"Демо-данные: {out} ({len(rows)} строк)")
    demo_touches(today)
    demo_campaigns(today)
    demo_amo()


CAMPAIGN_SUBJECTS = [
    ("Новые тарифы на массовые выплаты с 1 числа", .24, .031, .0035),
    ("CardsPro: карты для рекламных кабинетов теперь с 3D Secure", .21, .026, .004),
    ("Capitalist на конференции Affiliate World — встречаемся?", .18, .012, .003),
    ("New: USDT payouts in 60+ countries", .2, .022, .005),
    ("Дайджест месяца: что нового в Capitalist", .16, .009, .006),
    ("CardsPro White Label: свой карт-сервис за 2 недели", .19, .018, .0045),
    ("Важно: обновление правил верификации", .33, .041, .002),
    ("Monthly digest: what's new in Capitalist", .14, .008, .007),
]


def demo_amo():
    """Выдуманные смены этапов в amo (data/amo_demo.json) для вкладки «Welcome CardsPro → CRP»."""
    t = json.load(open(ROOT / "data" / "touch_demo.json", encoding="utf-8"))
    seq3 = {iid for iid, v in t["issues"].items() if v[0] == "3"}
    fmt = "%Y-%m-%d %H:%M"
    events = []
    clicked = {}
    for email, iid, ct, dest in t["click"]:
        if iid in seq3 and dest == "site":
            clicked.setdefault(email, ct)
    for email, ct in clicked.items():
        if random.random() < .45:
            et = dt.datetime.strptime(ct, fmt) + dt.timedelta(days=random.uniform(.2, 40))
            if et < dt.datetime.now():
                events.append([email, et.strftime(fmt), random.choice([84381634, 84381634, 84327810, 142]), 1])
    for email, iid, dtt in t["deliv"]:
        if iid in seq3 and email not in clicked and random.random() < .04:
            et = dt.datetime.strptime(dtt, fmt) + dt.timedelta(days=random.uniform(1, 20))
            if et < dt.datetime.now():
                events.append([email, et.strftime(fmt), 84381634, 2])
    events.sort(key=lambda e: e[1])
    out = ROOT / "data" / "amo_demo.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "events": events}, f)
    print(f"Демо amo: {out} ({len(events)} смен этапа)")


def demo_campaigns(today):
    """Выдуманные массовые рассылки (data/campaigns_demo.json)."""
    rows = []
    for i in range(34):
        subj, or_, ctr, uns = CAMPAIGN_SUBJECTS[i % len(CAMPAIGN_SUBJECTS)]
        day = today - dt.timedelta(days=4 + i * 5 + random.randint(0, 2))
        sent = random.choice([2200, 3400, 5100, 8600, 12000]) if i % 9 else 25
        deliv = int(sent * random.uniform(.95, .99))
        k = random.uniform(.75, 1.25)
        uo, uc = int(deliv * or_ * k), int(deliv * ctr * k)
        rows.append({"id": str(9000 + i), "dt": f"{day.isoformat()} {random.randint(9, 17):02d}:{random.choice(['00', '30'])}",
                     "name": f"Рассылка {day.strftime('%d.%m')}", "subject": subj,
                     "sent": sent, "delivered": deliv, "bounced": sent - deliv, "opens": int(uo * 1.5), "u_opens": uo,
                     "clicks": int(uc * 1.3), "u_clicks": uc, "unsubs": int(deliv * uns * random.uniform(.5, 1.8))})
    rows.sort(key=lambda r: r["dt"])
    out = ROOT / "data" / "campaigns_demo.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "since": rows[0]["dt"][:10], "rows": rows}, f, ensure_ascii=False)
    print(f"Демо-рассылки: {out} ({len(rows)} выпусков)")


# Цели демо-цепочек (как в config.json) -> какие события генерировать.
DEMO_TARGET = {"5": "kyc_passed", "3": "card_issued", "1": "deposit", "6": "transaction", "8": "card_topup"}


def demo_touches(today):
    """Выдуманные контакты по людям (data/touch_demo.json) и выгрузка бэк-офиса
    (data/demo_backoffice.csv) для проверки блока «Конверсии»."""
    issues, people, deliv, reads, clicks, events = {}, {}, [], [], [], []
    by_seq = {}
    for i, (seq, name, subj, lag, or_, ctr, *_rest) in enumerate(LETTERS):
        by_seq.setdefault(seq, []).append((i, name, subj, lag, or_, ctr))
        issues[str(1000 + i)] = [seq, name, subj]
    n = 0
    for seq, letters in by_seq.items():
        for _ in range(VOLUME[seq] * 9):
            n += 1
            email = f"user{n}@example.com"
            people[email] = [f"login{n}" if n % 2 else "", str(500000 + n) if n % 2 else ""]
            lang = "en" if random.random() < .35 else "ru"
            mine = [l for l in letters if (" en" in l[1] or "Your" in l[1] or "You" in l[1]) == (lang == "en")] or letters
            start = dt.datetime.combine(today - dt.timedelta(days=random.randint(2, 85)), dt.time(random.randint(7, 20), random.randint(0, 59)))
            clicked_at = None
            for i, name, subj, lag, or_, ctr in mine:
                t = start + dt.timedelta(days=lag)
                if t.date() >= today:
                    break
                deliv.append([email, str(1000 + i), t.strftime("%Y-%m-%d %H:%M")])
                if random.random() < or_ * 1.3:
                    ot = t + dt.timedelta(minutes=random.randint(5, 600))
                    reads.append([email, str(1000 + i), ot.strftime("%Y-%m-%d %H:%M")])
                    if random.random() < min(.6, ctr * 4):
                        ct = ot + dt.timedelta(minutes=random.randint(1, 30))
                        dest = random.choice(["site", "site", "tg", "other"])
                        clicks.append([email, str(1000 + i), ct.strftime("%Y-%m-%d %H:%M"), dest])
                        clicked_at = clicked_at or ct
            # Целевое действие: после клика чаще, без клика — реже.
            p = .35 if clicked_at else .07
            if random.random() < p:
                base = clicked_at or start
                et = base + dt.timedelta(hours=random.randint(1, 120))
                if et.date() < today:
                    events.append([email, people[email][0], people[email][1], DEMO_TARGET[seq], et.strftime("%Y-%m-%d %H:%M")])
    # Пара строк, которых нет в Sendsay, и событие до входа в цепочку.
    events.append(["stranger@example.com", "", "", "deposit", (dt.datetime.combine(today, dt.time(9)) - dt.timedelta(days=3)).strftime("%Y-%m-%d %H:%M")])
    out = ROOT / "data" / "touch_demo.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "since": (today - dt.timedelta(days=90)).isoformat(), "issues": issues, "people": people,
                   "deliv": deliv, "read": reads, "click": clicks}, f, ensure_ascii=False)
    bo = ROOT / "data" / "demo_backoffice.csv"
    with open(bo, "w", encoding="utf-8") as f:
        f.write("email;login;id_back_office;product;event;event_datetime;amount\n")
        for email, lg, boid, ev, t in events:
            prod = "CardsPro" if ev.startswith("card") else "Capitalist"
            # Часть строк без email — сопоставление по логину / ID бэк-офиса.
            em = "" if (lg and random.random() < .3) else email
            f.write(f"{em};{lg};{boid};{prod};{ev};{t};\n")
    print(f"Демо-контакты: {out} (людей {len(people)}, кликов {len(clicks)}); выгрузка бэк-офиса: {bo} ({len(events)} строк)")


if __name__ == "__main__":
    main()
