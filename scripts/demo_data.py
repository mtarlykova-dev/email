#!/usr/bin/env python3
"""Генерирует ВЫДУМАННЫЕ данные для локальной проверки страницы (data/demo.json, не коммитится).

Запуск:
  python scripts/demo_data.py
  python scripts/build.py --data data/demo.json
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
    ("41276", "WC ru 1", "Добро пожаловать в Capitalist", 0, .23, .073, .004, .03),
    ("41276", "WC ru 2", "Агентство, команда или фрилансер?", 2, .19, .016, .023, .03),
    ("41276", "WC ru 3", "Тарифы без сюрпризов и карты без очередей", 5, .14, .019, .013, .03),
    ("41276", "WC en 1", "Welcome to Capitalist", 0, .21, .061, .005, .04),
    ("41276", "WC en 2", "Agency, team or freelancer?", 2, .16, .014, .018, .04),
    ("95958", "CP en 1", "Welcome to CardsPro", 0, .25, .087, .004, .09),
    ("95958", "CP en 2", "Have you issued your first card yet?", 2, .06, .015, .006, .066),
    ("95958", "CP en 3", "What if your customers could pay with your cards?", 4, .035, .0045, .008, .065),
    ("95958", "CP en 4", "CardsPro for teams", 7, .052, .0053, .007, .061),
    ("95958", "CP ru 1", "Добро пожаловать в CardsPro", 0, .27, .09, .004, .02),
    ("72097", "(1) Регистрация", "Остался один шаг до полного функционала", 0, .17, .019, .017, .02),
    ("72097", "(2) Регистрация", "Криптовалюта, кошельки и карты CardsPro", 4, .09, .007, .015, .02),
    ("72097", "(3) Регистрация", "Свой карт-сервис под брендом", 6, .12, .008, .014, .02),
    ("88001", "After KYB ru", "Верификация пройдена — что дальше", 0, .31, .11, .003, .01),
    ("88001", "After KYB en", "You're verified — what's next", 0, .28, .09, .003, .01),
]
VOLUME = {"41276": 14, "95958": 9, "72097": 11, "88001": 6}


def main():
    today = dt.date.today()
    start = today - dt.timedelta(days=160)
    rows = []
    for seq, name, subj, lag, or_, ctr, uns, bad in LETTERS:
        for i in range(160):
            day = start + dt.timedelta(days=i + lag)
            if day >= today:
                break
            if seq == "88001" and (today - day).days <= 5:  # триггер «замолчал»
                continue
            base = VOLUME[seq] * (0.55 if " en" in name else 1)
            sent = max(0, int(random.gauss(base, base * 0.35)))
            if sent == 0:
                continue
            o = or_ * (0.6 if seq == "41276" and "ru 2" in name and (today - day).days < 20 else 1)
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


if __name__ == "__main__":
    main()
