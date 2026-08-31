# Развёртывание Telegram-части на сервере

Telegram работает на выделенном сервере, MAX остаётся в Cloud Functions.
Кодовая база общая, разделение задаёт переменная `MESSENGERS`.

Ниже `SERVER_ADDRESS` — IP-адрес сервера (или домен, если выбран запасной вариант).

## 1. Подготовка в Yandex Cloud

1. Создать сервисный аккаунт `bot-server` с ролями: `ydb.editor` на базу,
   `storage.uploader` и `storage.viewer` на бакеты, `logging.writer`, `logging.reader`,
   `lockbox.payloadViewer` на оба секрета.
2. Скачать ключ в `authorized_key.json`.
3. Добавить в оба секрета Lockbox (prod и preprod) ключи `WEBHOOK_SECRET_TOKEN`
   и `PROXY_SECRET`. Значения — только ASCII, они уходят в HTTP-заголовки:

   ```bash
   openssl rand -hex 32
   ```

4. Разделить указатель рассылки в таблице `app` (по одному запросу):

   ```sql
   UPSERT INTO app (key, value) VALUES ("mailing_has_been_sent_telegram", "<текущее значение>");
   UPSERT INTO app (key, value) VALUES ("mailing_has_been_sent_max", "<текущее значение>");
   ```

   Строку `mailing_has_been_sent` удалить после успешного перехода.

## 2. Пользователь и каталоги

```bash
sudo useradd --system --home-dir /opt/schoolpupilbot --shell /usr/sbin/nologin schoolpupilbot
sudo mkdir -p /opt/schoolpupilbot/{prod,preprod} /etc/schoolpupilbot /var/www/certbot
sudo chown -R schoolpupilbot:schoolpupilbot /opt/schoolpupilbot

sudo cp authorized_key.json /etc/schoolpupilbot/
sudo chown schoolpupilbot:schoolpupilbot /etc/schoolpupilbot/authorized_key.json
sudo chmod 600 /etc/schoolpupilbot/authorized_key.json
```

Заполнить `/etc/schoolpupilbot/prod.env` и `/etc/schoolpupilbot/preprod.env`
по образцу `env.example` (у preprod `PORT=8081`, `WORKERS=1`,
`LOG_RESOURCE_ID=bot-server-preprod`, свои лог-группа и бакет).

## 3. Python 3.14 и зависимости

Системный интерпретатор Debian 13 не трогаем.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.14

for env in prod preprod; do
    sudo -u schoolpupilbot uv venv --python 3.14 /opt/schoolpupilbot/$env/venv
    sudo -u schoolpupilbot /opt/schoolpupilbot/$env/venv/bin/pip install \
        -r /opt/schoolpupilbot/$env/server/requirements.txt
done
```

## 4. Сертификат

Сертификаты Let's Encrypt на IP-адрес выдаются только короткими, на шесть дней,
поэтому нужен certbot с поддержкой профилей ACME — из репозитория Debian 13 он старый.

```bash
uv tool install certbot
```

Сначала пробный выпуск на тестовом сервере Let's Encrypt:

```bash
sudo certbot certonly --webroot -w /var/www/certbot -d SERVER_ADDRESS \
    --preferred-profile shortlived --staging
```

Если прошло — боевой выпуск:

```bash
sudo certbot certonly --webroot -w /var/www/certbot -d SERVER_ADDRESS \
    --preferred-profile shortlived \
    --deploy-hook "systemctl reload nginx"
sudo systemctl enable --now certbot.timer
```

Если выпуск на IP не получится, вариант с доменом: направить A-запись на сервер и
выпустить обычный сертификат без `--preferred-profile`, дальше всё без изменений.

## 5. nginx

```bash
sudo apt install nginx
sudo sed 's/SERVER_ADDRESS/<адрес>/g' nginx.conf | sudo tee /etc/nginx/sites-available/schoolpupilbot
sudo ln -sf /etc/nginx/sites-available/schoolpupilbot /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

AmneziaVPN занимает 8443/TCP и 49435/UDP, порты 80 и 443 свободны.

## 6. Службы и таймеры

```bash
sudo cp schoolpupilbot@.service schoolpupilbot-trigger@.service \
        schoolpupilbot-cert-check.service *.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now schoolpupilbot@prod schoolpupilbot@preprod
sudo systemctl enable --now schoolpupilbot-trigger@mailing_newsletter.timer \
    schoolpupilbot-trigger@mailing_changes_tt.timer \
    schoolpupilbot-trigger@daily_statistics.timer \
    schoolpupilbot-cert-check.timer
```

Таймеры обращаются к уже работающему процессу, а не поднимают новый: иначе каждый
запуск это ещё одно обращение в Lockbox и новое подключение к базе.

## 7. Вебхуки

`setWebhook` вызывать с самого сервера — из России `api.telegram.org` недоступен.

```bash
TOKEN=<токен бота>
SECRET=<WEBHOOK_SECRET_TOKEN из Lockbox>
curl -fsS "https://api.telegram.org/bot$TOKEN/setWebhook" \
    -d "url=https://SERVER_ADDRESS/telegram" \
    -d "secret_token=$SECRET" \
    -d "max_connections=40"
curl -s "https://api.telegram.org/bot$TOKEN/getWebhookInfo"
```

Для preprod адрес `https://SERVER_ADDRESS/preprod/telegram` и свой токен.

## 8. Права для деплоя

Отдельному пользователю деплоя разрешить только перезапуск служб:

```
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart schoolpupilbot@prod, \
    /usr/bin/systemctl restart schoolpupilbot@preprod
```

## 9. Проверка

```bash
curl -s https://SERVER_ADDRESS/health
curl -s https://SERVER_ADDRESS/preprod/health
systemctl status schoolpupilbot@prod
journalctl -u schoolpupilbot@prod -f
systemctl list-timers 'schoolpupilbot*'
```
