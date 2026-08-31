# Развёртывание Telegram-части на сервере

Telegram работает на выделенном сервере, MAX остаётся в Cloud Functions.
Кодовая база общая, разделение задаёт переменная `MESSENGERS`.

Ниже `SERVER_ADDRESS` — IP-адрес сервера (или домен, если выбран запасной вариант).
Пользователь деплоя — `deploy`, его имя уходит в секрет `SERVER_USER`.

Вручную настраивается только машина: пользователи, каталоги, venv, сертификат, nginx и юниты.
Код, зависимости и файл окружения экземпляра выкладывает CD.

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

## 2. Пользователи и каталоги

Код на сервер CD выкладывает через `rsync`, он должен быть на машине:

```bash
sudo apt install -y rsync
```

Службы работают от системного пользователя `schoolpupilbot` и только читают код,
а пишет в каталоги отдельный пользователь `deploy`. Обычный аккаунт с полным `sudo`
для деплоя не годится: утечка ключа из GitHub означала бы полный доступ к серверу.

```bash
sudo useradd --system --home-dir /opt/schoolpupilbot --shell /usr/sbin/nologin schoolpupilbot
sudo useradd --create-home --shell /bin/bash deploy

sudo mkdir -p /opt/schoolpupilbot/{prod,preprod} /etc/schoolpupilbot /var/www/certbot
sudo chown -R deploy:schoolpupilbot /opt/schoolpupilbot
sudo chmod -R g+rX,o-rwx /opt/schoolpupilbot
sudo find /opt/schoolpupilbot -type d -exec chmod g+s {} +

sudo cp authorized_key.json /etc/schoolpupilbot/
sudo chown schoolpupilbot:schoolpupilbot /etc/schoolpupilbot/authorized_key.json
sudo chmod 600 /etc/schoolpupilbot/authorized_key.json
```

Бит `g+s` на каталогах обязателен: без него всё, что создаёт `deploy` (код, venv,
файл окружения), получает группу `deploy`, и служба под `schoolpupilbot` не может это прочитать.

Ключ сервисного аккаунта — единственное, что кладётся на сервер руками.
Файл окружения `/opt/schoolpupilbot/<экземпляр>/env` собирает CD из секретов GitHub,
а секреты приложения `bootstrap.py` берёт из Lockbox при каждом запуске службы.
Образец файла — `env.example`, он нужен только для запуска сервера без деплоя.

## 3. Python 3.14 и venv

Системный интерпретатор Debian 13 не трогаем. Всё — от имени `deploy` (`sudo -u deploy -i`),
он же ставит зависимости в CD.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Интерпретатор ставится в `/opt/python`, а не в домашний каталог: в юнитах включён
`ProtectHome=true`, и служба не увидела бы `/home/deploy` — запуск падал бы
с `status=203/EXEC`. Эта команда — от `admin`:

```bash
sudo env UV_PYTHON_INSTALL_DIR=/opt/python /home/deploy/.local/bin/uv python install 3.14
sudo chmod -R a+rX /opt/python
```

Окружения создаёт `deploy`, он же ставит в них зависимости при деплое:

```bash
export UV_PYTHON_INSTALL_DIR=/opt/python

for env in prod preprod; do
    uv venv --seed --python 3.14 /opt/schoolpupilbot/$env/venv
done
```

`--seed` обязателен: без него `uv venv` создаёт окружение без `pip`, а зависимости
на сервере ставит именно он.

Зависимости ставятся первым же деплоем, вручную их устанавливать не нужно.

## 4. nginx

```bash
sudo apt install nginx
```

Полный конфиг не поднимется без сертификата, а сертификат не выпустить, пока никто не
отвечает на 80-м порту. Поэтому сначала — только ACME-часть:

```bash
sudo tee /etc/nginx/sites-available/schoolpupilbot << 'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
}
EOF
sudo ln -sf /etc/nginx/sites-available/schoolpupilbot /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

AmneziaVPN занимает 8443/TCP и 49435/UDP, порты 80 и 443 свободны.

## 5. Сертификат

Шаги этого раздела выполняются от администратора, а не от `deploy`: у того нет ни sudo, ни пароля.

Сертификаты Let's Encrypt на IP-адрес выдаются только короткими, на шесть дней,
поэтому нужен certbot не ниже 5.4 — из репозитория Debian 13 он старый.
Ставим свежий в отдельное окружение и кладём ссылку в `/usr/local/bin`, чтобы он был
виден `sudo` (в `secure_path` домашних каталогов нет):

Системного `python3` для этого может не хватить: certbot 5.x требует Python 3.10,
а в старых Debian это 3.9. Берём тот же 3.14, что и для бота, — uv уже стоит у `deploy`:

```bash
sudo /home/deploy/.local/bin/uv venv --python 3.14 /opt/certbot/venv
sudo /home/deploy/.local/bin/uv pip install --python /opt/certbot/venv/bin/python certbot
sudo ln -sf /opt/certbot/venv/bin/certbot /usr/local/bin/certbot
certbot --version
```

Адрес передаётся флагом `--ip-address`, а не `-d`: на `-d` с IP certbot отвечает
«will not issue certificates for a bare IP address», не дойдя до сервера. Флаг появился
в certbot 5.3, а вместе с `--webroot` работает с 5.4.

Сначала пробный выпуск на тестовом сервере Let's Encrypt:

```bash
sudo certbot certonly --staging \
    --preferred-profile shortlived \
    --webroot --webroot-path /var/www/certbot \
    --ip-address SERVER_ADDRESS
```

Если прошло — боевой выпуск:

```bash
sudo certbot certonly \
    --preferred-profile shortlived \
    --webroot --webroot-path /var/www/certbot \
    --ip-address SERVER_ADDRESS \
    --deploy-hook "systemctl reload nginx"
```

Профиль `shortlived` для сертификатов на IP обязателен, другого срока Let's Encrypt
для них не выдаёт. Плагины `nginx` и `apache` с IP пока не работают — только
`webroot`, `standalone` и `manual`.

Пакетного `certbot.timer` здесь нет — certbot поставлен не из apt, поэтому продление
включается своим таймером на шаге 7. Параметры выпуска certbot запоминает
в `/etc/letsencrypt/renewal/`, так что `certbot renew` повторяет их сам.

Если выпуск на IP не получится, вариант с доменом: направить A-запись на сервер и
выпустить обычный сертификат без `--preferred-profile`, дальше всё без изменений.

Теперь можно подключить полный конфиг — это файл `deploy/nginx.conf` из репозитория.
После первого деплоя он лежит на сервере в `/opt/schoolpupilbot/prod/deploy/nginx.conf`,
а до него копируется с рабочей машины:

```bash
scp deploy/nginx.conf admin@SERVER_ADDRESS:~
```

Дальше на сервере (`http2 on;` требует nginx 1.25.1, на более старом заменить
на `listen 443 ssl http2;` и убрать строку `http2 on;`):

```bash
nginx -v
sudo sed 's/SERVER_ADDRESS/<адрес>/g' ~/nginx.conf \
    | sudo tee /etc/nginx/sites-available/schoolpupilbot > /dev/null
sudo nginx -t && sudo systemctl reload nginx
```

Проксировать пока некуда, службы поднимутся на шаге 7 — до этого на `/health` будет 502.

Это единственная установка конфига руками: дальше его обновляет CD на ветке `main`
(шаг «Обновить конфиг nginx»), поэтому правки маршрутов достаточно закоммитить.

## 6. Деплой из GitHub

Секреты репозитория (общие): `SERVER_HOST`, `SERVER_USER`, `SERVER_SSH_KEY`.
Секреты окружений `prod` и `preprod` — те же, что у функции, плюс те, что раньше
уходили только в облако: `TELEGRAM_SUPERADMIN`, `TELEGRAM_TECHNO_INFO`, `CHANNEL_PERVYE`,
`LOCKBOX_ID`, `LOG_GROUP_ID`, `YDB_DATABASE`, `YDB_ENDPOINT`, `VK_APP_ID`, `VK_DOMAIN`,
`YOOKASSA_ACCOUNT_ID`, `AWS_ACCESS_KEY_ID`, `AWS_REGION`, `S3_ENDPOINT_URL`, `BUCKET_NAME`.

Отдельно — `SERVER_WEBHOOK_URL`: адрес экземпляра сервера, на который функция пересылает
уведомления об оплате. В `prod` это `https://SERVER_ADDRESS`, в `preprod` —
`https://SERVER_ADDRESS/preprod`. Пустым его оставить нельзя: Cloud Functions отклоняет
версию с пустым значением переменной окружения.

Из них CD собирает `/opt/schoolpupilbot/<экземпляр>/env` и кладёт его рядом с кодом
(см. шаг «Выгрузить файл окружения» в `.github/workflows/cd.yml`). Изменил секрет —
перезапустил workflow, файл на сервере перезапишется.

Ключ для доступа по SSH (без пароля, приватная часть уходит в `SERVER_SSH_KEY`):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/schoolpupilbot_deploy -C github-actions -N ''
sudo install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
sudo tee /home/deploy/.ssh/authorized_keys < ~/.ssh/schoolpupilbot_deploy.pub
sudo chown deploy:deploy /home/deploy/.ssh/authorized_keys
sudo chmod 600 /home/deploy/.ssh/authorized_keys
```

Пользователю деплоя разрешить только перезапуск служб и установку конфига nginx.
Без `NOPASSWD` деплой упадёт: по SSH терминала нет и ввести пароль некому.

```bash
sudo tee /etc/sudoers.d/schoolpupilbot << 'EOF'
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart schoolpupilbot@prod, /usr/bin/systemctl restart schoolpupilbot@preprod, /usr/bin/systemctl reload nginx, /usr/sbin/nginx -t, /usr/bin/install -m 644 -o root -g root /opt/schoolpupilbot/prod/nginx.rendered /etc/nginx/sites-available/schoolpupilbot
EOF
sudo chmod 440 /etc/sudoers.d/schoolpupilbot
sudo visudo -c
```

Первый деплой (push в `develop` или `main`) выгрузит код, поставит зависимости
и создаст файл окружения — до него службы запускать нечем.

Конфиг nginx тоже обновляет CD, но только на ветке `main`: nginx один на машину
и обслуживает оба экземпляра, поэтому менять вход прода пушем в `develop` нельзя.
Шаг подставляет адрес сервера вместо `SERVER_ADDRESS`, проверяет конфиг через
`nginx -t` и перезагружает nginx; при ошибке проверки деплой падает, а работающий
nginx продолжает жить со старым конфигом. Правки маршрутов preprod доезжают
на сервер вместе со слиянием в `main`.

## 7. Службы и таймеры

Юниты берутся из выгруженной деплоем копии репозитория:

```bash
cd /opt/schoolpupilbot/preprod/deploy
sudo cp schoolpupilbot@.service schoolpupilbot-trigger@.service \
        schoolpupilbot-cert-check.service certbot-renew.service \
        *.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now schoolpupilbot@preprod
```

Экземпляр prod и таймеры включаются после деплоя ветки `main` — до него нет ни кода,
ни файла окружения в `/opt/schoolpupilbot/prod`, а все таймеры работают только с prod:

```bash
sudo systemctl enable --now schoolpupilbot@prod
sudo systemctl enable --now schoolpupilbot-trigger@mailing_newsletter.timer \
    schoolpupilbot-trigger@mailing_changes_tt.timer \
    schoolpupilbot-trigger@daily_statistics.timer \
    schoolpupilbot-cert-check.timer certbot-renew.timer
```

`certbot-renew.timer` пробует продлить сертификат каждые шесть часов: при сроке жизни
в шесть дней окно продления открывается примерно за двое суток до конца, и редких
попыток не хватило бы. `schoolpupilbot-cert-check.timer` — независимая проверка,
что продление действительно происходит: если до конца срока меньше двух дней,
в технический чат приходит предупреждение.

Таймеры обращаются к уже работающему процессу, а не поднимают новый: иначе каждый
запуск это ещё одно обращение в Lockbox и новое подключение к базе.

## 8. Вебхуки

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

## 9. Проверка

```bash
curl -s https://SERVER_ADDRESS/health
curl -s https://SERVER_ADDRESS/preprod/health
systemctl status schoolpupilbot@prod
journalctl -u schoolpupilbot@prod -f
systemctl list-timers 'schoolpupilbot*' certbot-renew.timer
sudo -u schoolpupilbot openssl x509 -in /etc/letsencrypt/live/SERVER_ADDRESS/cert.pem -noout -enddate
```

Последняя команда проверяет, что проверку срока сертификата видит и служба:
`schoolpupilbot-cert-check` работает не от root, а certbot в некоторых версиях
закрывает `/etc/letsencrypt/live` от посторонних. Если доступа нет:

```bash
sudo chmod 755 /etc/letsencrypt/live /etc/letsencrypt/archive
```
