#!/usr/bin/env python3
"""Импорт ручных выгрузок «Экспорт» из сценария Sendsay (stat_uni_*.zip / *.csv).

ID сценария берётся из конца имени файла: stat_uni_20261001190115_41276.csv -> 41276.
Строки этого сценария за даты из выгрузки заменяются, остальное не трогается.

Запуск:  python scripts/import_csv.py imports/stat_uni_*.zip
"""
import csv
import datetime as dt
import io
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(__file__))
from common import load_rows, make_row, save_rows  # noqa: E402

COLS = {
    "Отправлено": "sent", "Доставлено": "delivered", "Ошибки": "bounced",
    "Открытия": "opens", "Уник. открытия": "u_opens", "Клики": "clicks",
    "Уник. клики": "u_clicks", "Отписки": "unsubs",
}
SEQ_RE = re.compile(r"_(\d+)\.csv$", re.I)


def iter_csv_files(paths):
    for p in paths:
        if p.lower().endswith(".zip"):
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    if n.lower().endswith(".csv"):
                        yield os.path.basename(n), z.read(n)
        else:
            with open(p, "rb") as f:
                yield os.path.basename(p), f.read()


def decode(raw):
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")


def parse(name, raw):
    m = SEQ_RE.search(name)
    if not m:
        print(f"Пропуск {name}: не нашёл ID сценария в имени файла")
        return None, []
    seq = m.group(1)
    text = decode(raw)
    dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t")
    rows = []
    for r in csv.DictReader(io.StringIO(text), dialect=dialect):
        day = (r.get("Дата") or "").strip()[:10]
        if not day:
            continue
        if re.match(r"\d{2}\.\d{2}\.\d{4}", day):
            day = dt.datetime.strptime(day, "%d.%m.%Y").date().isoformat()
        values = {k: (r.get(c) or "0").replace(" ", "").replace(",", ".") for c, k in COLS.items()}
        rows.append(make_row(day, seq, r.get("Название выпуска"), r.get("Тема"), values))
    return seq, rows


def main():
    paths = sys.argv[1:]
    if not paths:
        sys.exit(__doc__)
    existing = load_rows()
    for name, raw in iter_csv_files(paths):
        seq, rows = parse(name, raw)
        if not rows:
            continue
        lo, hi = min(r["d"] for r in rows), max(r["d"] for r in rows)
        existing = [r for r in existing if not (r["seq"] == seq and lo <= r["d"] <= hi)] + rows
        print(f"{name}: сценарий {seq}, {len(rows)} строк, {lo} — {hi}")
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    payload = save_rows(existing, "csv-import", now)
    print(f"Всего строк в data/daily.json: {len(payload['rows'])}")


if __name__ == "__main__":
    main()
