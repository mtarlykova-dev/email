#!/usr/bin/env python3
"""Собирает сайт в _site/: страница + данные + алерты.

Алерты считаются здесь (а не в браузере), чтобы их можно было вывести
в сводку GitHub Actions и увидеть в истории коммитов.

Запуск:  python scripts/build.py [--data путь/к/daily.json]
"""
import datetime as dt
import json
import os
import shutil
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from common import ALERTS_FILE, DATA_FILE, METRICS, ROOT, detect_lang, load_config  # noqa: E402

MSK = dt.timezone(dt.timedelta(hours=3))


def scenario_meta(cfg, seqs):
    meta = {}
    for s in seqs:
        c = cfg.get("scenarios", {}).get(s, {})
        meta[s] = {
            "name": c.get("name") or f"Сценарий #{s}",
            "product": c.get("product") or "Другое",
            "lang": c.get("lang", "auto"),
            "configured": s in cfg.get("scenarios", {}),
        }
    return meta


def row_lang(row, meta):
    lang = meta[row["seq"]]["lang"]
    return lang if lang in ("ru", "en") else detect_lang(row["subject"], row["name"])


def window(rows, start, end):
    return [r for r in rows if start <= r["d"] <= end]


def total(rows):
    t = {m: 0 for m in METRICS}
    for r in rows:
        for m in METRICS:
            t[m] += r[m]
    return t


def pct(x):
    return f"{x * 100:.1f}%".replace(".", ",")


def compute_alerts(rows, meta, cfg, today):
    a = cfg["alerts"]
    D = lambda n: (today - dt.timedelta(days=n)).isoformat()  # noqa: E731
    last_full = D(1)
    alerts = []

    by_seq = defaultdict(list)
    for r in rows:
        by_seq[r["seq"]].append(r)

    for seq, srows in by_seq.items():
        name = meta[seq]["name"]
        # 1. Триггер замолчал: за последние N дней 0 отправок, а раньше письма шли.
        n = a["silence_days"]
        recent = total(window(srows, D(n), last_full))["sent"]
        before = total(window(srows, D(n + 28), D(n + 1)))["sent"]
        if recent == 0 and before >= a["silence_min_prev_sends"]:
            alerts.append({
                "level": "high", "seq": seq, "letter": None, "kind": "silence",
                "title": f"{name}: нет отправок {n} дн.",
                "detail": f"За предыдущие 4 недели ушло {before} писем, за последние {n} дн. — ни одного. "
                          f"Проверьте, что в сценарий приходит вход (событие/триггер).",
            })
            continue

        # 2. Резкое падение объёма: последняя неделя против средней за 4 недели до неё.
        week = total(window(srows, D(7), last_full))["sent"]
        base = total(window(srows, D(35), D(8)))["sent"] / 4
        if base >= a["volume_min_weekly"] and week < base * a["volume_drop_ratio"]:
            alerts.append({
                "level": "medium", "seq": seq, "letter": None, "kind": "volume",
                "title": f"{name}: объём упал до {week} писем/нед",
                "detail": f"Обычно ~{base:.0f} в неделю (среднее за 4 недели до этого).",
            })

        by_letter = defaultdict(list)
        for r in srows:
            by_letter[r["name"] or r["subject"]].append(r)

        for letter, lrows in by_letter.items():
            w = total(window(lrows, D(7), last_full))
            # 3. Ошибки доставки
            if w["sent"] >= a["bounce_min_sent"] and w["bounced"] / w["sent"] > a["bounce_rate_max"]:
                alerts.append({
                    "level": "medium", "seq": seq, "letter": letter, "kind": "bounce",
                    "title": f"{name} · {letter}: ошибки доставки {pct(w['bounced'] / w['sent'])}",
                    "detail": f"{w['bounced']} из {w['sent']} за 7 дней. Порог {pct(a['bounce_rate_max'])}. "
                              f"Проверьте исключение hard bounce и качество базы.",
                })
            # 4. Отписки
            if w["delivered"] >= a["unsub_min_delivered"] and w["unsubs"] / w["delivered"] > a["unsub_rate_max"]:
                alerts.append({
                    "level": "medium", "seq": seq, "letter": letter, "kind": "unsub",
                    "title": f"{name} · {letter}: отписки {pct(w['unsubs'] / w['delivered'])}",
                    "detail": f"{w['unsubs']} из {w['delivered']} доставленных за 7 дней. Порог {pct(a['unsub_rate_max'])}.",
                })
            # 5. Просадка открываемости: 14 дней (без последних 2, открытия ещё копятся) против 8 недель до этого.
            cur = total(window(lrows, D(16), D(3)))
            prev = total(window(lrows, D(72), D(17)))
            if cur["delivered"] >= a["or_min_delivered"] and prev["delivered"] >= a["or_min_delivered"] and prev["u_opens"]:
                cur_or = cur["u_opens"] / cur["delivered"]
                prev_or = prev["u_opens"] / prev["delivered"]
                if cur_or < prev_or * a["or_drop_ratio"]:
                    alerts.append({
                        "level": "low", "seq": seq, "letter": letter, "kind": "open_rate",
                        "title": f"{name} · {letter}: OR упал до {pct(cur_or)}",
                        "detail": f"Было {pct(prev_or)} за 8 недель до этого. Проверьте тему, отправителя и попадание во «Входящие».",
                    })

    order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda x: (order[x["level"]], x["title"]))
    return alerts


def write_summary(alerts, meta, rows, generated_at):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    icon = {"high": "🔴", "medium": "🟠", "low": "🟡"}
    lines = [f"## Триггерные рассылки — данные на {generated_at}", ""]
    lines.append(f"Сценариев: {len(meta)}, строк данных: {len(rows)}")
    lines.append("")
    if alerts:
        lines.append("### Алерты")
        lines += [f"- {icon[a['level']]} **{a['title']}** — {a['detail']}" for a in alerts]
    else:
        lines.append("Алертов нет ✅")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    data_path = DATA_FILE
    if "--data" in sys.argv:
        data_path = ROOT / sys.argv[sys.argv.index("--data") + 1]
    cfg = load_config()
    if data_path.exists():
        with open(data_path, encoding="utf-8") as f:
            payload = json.load(f)
    else:
        payload = {"generated_at": None, "source": None, "rows": []}
    rows = payload["rows"]

    # Порядок: сначала сценарии из config.json в их порядке, затем найденные автоматически.
    configured = list(cfg.get("scenarios", {}))
    discovered = sorted({r["seq"] for r in rows} - set(configured))
    meta = scenario_meta(cfg, configured + discovered)
    for r in rows:
        r["lang"] = row_lang(r, meta)

    today = dt.datetime.now(MSK).date()
    alerts = compute_alerts(rows, meta, cfg, today) if rows else []

    # alerts.json коммитится вместе с данными — в истории git видно, когда что сработало.
    if data_path == DATA_FILE:
        ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump({"date": today.isoformat(), "alerts": alerts}, f, ensure_ascii=False, indent=1)
            f.write("\n")

    site = ROOT / "_site"
    if site.exists():
        shutil.rmtree(site)
    shutil.copytree(ROOT / "site", site)
    report = {
        "generated_at": payload.get("generated_at"),
        "source": payload.get("source"),
        "today": today.isoformat(),
        "scenarios": meta,
        "alerts": alerts,
        "thresholds": {"unsub": cfg["alerts"]["unsub_rate_max"], "bounce": cfg["alerts"]["bounce_rate_max"]},
        "rows": rows,
    }
    with open(site / "report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, separators=(",", ":"))
    (site / ".nojekyll").touch()

    write_summary(alerts, meta, rows, payload.get("generated_at"))
    print(f"Сайт собран: _site/ ({len(rows)} строк, {len(alerts)} алертов)")


if __name__ == "__main__":
    main()
