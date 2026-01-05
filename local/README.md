## Локальное тестирование

1. Скопировать файл .env.example в файл .env и заполнить его данными
2. Установить зависимости:
   - `pip install -r local/requirements.txt`
3. Запустить туннель до локального сервера:
   - `ngrok http 8080`
   - `lt --port 8080`
   - или другой аналогичный сервис
4. Настроить вызовы webhook в Telegram:
   - `curl https://api.telegram.org/bot<token>/setWebhook?url=https://<url>/webhook`
5. Установить переменную окружения `PYTHONPATH=src`:
   - _cmd_: `set PYTHONPATH=src`
   - _bash_: `export PYTHONPATH=src`
6. Запустить локальный сервер:
   - `python local/local_server.py`
