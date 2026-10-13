# Отчёт по триггерным рассылкам Capitalist и CardsPro

Дашборд по сценариям Sendsay: воронка по каждому письму цепочки, динамика по неделям, алерты и сравнение Capitalist / CardsPro × ru / en.

Каждый день в 06:47 МСК GitHub Actions забирает статистику из Sendsay API, сохраняет её в `data/daily.json` (коммитом — так в истории git видно, как менялись цифры) и публикует страницу на GitHub Pages.

В репозиторий попадают только агрегаты по письмам: сколько отправлено, доставлено, открыто, кликнуто, отписалось. Адресов и других персональных данных нет.

## Первый запуск

1. **Settings → Secrets and variables → Actions → New repository secret**
   - `SENDSAY_LOGIN` — логин аккаунта Sendsay
   - `SENDSAY_APIKEY` — API-ключ (Sendsay → Настройки → API-ключи). Ключу достаточно прав на чтение статистики.
2. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. **Actions → «Обновить отчёт» → Run workflow**.

Через пару минут отчёт будет по адресу `https://mtarlykova-dev.github.io/email/`.

## Как поменять сценарии

Файл `config.json`:

```json
"scenarios": {
  "41276": { "name": "Welcome Capitalist", "product": "Capitalist", "lang": "auto" }
}
```

- ключ — ID сценария в Sendsay (он же в конце имени выгрузки `stat_uni_…_41276.csv`);
- `product` — `Capitalist` или `CardsPro`, по нему работает фильтр и сравнение;
- `lang` — `ru`, `en` или `auto` (язык определяется по теме письма: кириллица → ru).

Сценарии, которых нет в конфиге, всё равно появятся в отчёте как «Сценарий #ID», пока `auto_discover: true`. Чтобы убрать сценарий, добавьте его ID в `exclude_scenarios`.

Пороги алертов — в блоке `alerts`:

| Параметр | Что значит |
|---|---|
| `silence_days` | Срочный алерт, если сценарий не отправил ни одного письма за столько дней, хотя за 4 недели до этого отправлял |
| `volume_drop_ratio` | Объём за неделю упал ниже этой доли от обычного |
| `bounce_rate_max` | Ошибки доставки письма за 7 дней выше порога |
| `unsub_rate_max` | Отписки письма за 7 дней выше порога |
| `or_drop_ratio` | OR письма за 2 недели упал ниже этой доли от OR за 8 недель до этого |

## Загрузить данные вручную

Если API недоступен или нужна история до `start_date`: выгрузите «Экспорт» из сценария в Sendsay и загрузите zip/csv в папку `imports/` через GitHub (Add file → Upload files). Workflow сам разберёт файл, добавит данные и переложит его в `imports/done/`.

## Как устроено

```
config.json                  сценарии и пороги алертов
scripts/fetch_sendsay.py     Sendsay API (stat.uni) → data/daily.json
scripts/import_csv.py        ручные выгрузки → data/daily.json
scripts/build.py             алерты + сборка _site/ для Pages
site/index.html              сама страница
data/daily.json              агрегаты: день × сценарий × письмо
data/alerts.json             алерты на дату последней сборки
.github/workflows/report.yml расписание, коммит данных, публикация
```

Посмотреть страницу локально на выдуманных данных:

```
python scripts/demo_data.py
python scripts/build.py --data data/demo.json
python -m http.server -d _site 8000
```
