## Локальное тестирование

### 1. Копирование файла окружения

Скопировать файл `.env.example` в файл `.env` и заполнить его необходимыми данными.

### 2. Установить зависимости:

```bash
pip install -r local/requirements.txt
```

### 3. Запустить туннель до локального сервера одним из способов:

- **ngrok**: `ngrok http 8080`
- **localtunnel**: `lt --port 8080`
- или использовать другой аналогичный сервис

### 4. Настроить вызовы webhook:

- **Telegram**:
  ```bash
  curl https://api.telegram.org/bot<token>/setWebhook?url=https://<domain>/telegram
  ```

- **MAX**:
  ```bash
  curl -X POST "https://platform-api.max.ru/subscriptions" -H "Authorization: <token>" -H "Content-Type: application/json" -d "{\"url\": \"https://<domain>/max\"}"
  ```

### 5. Установить переменную окружения `PYTHONPATH=src`:

- **Windows (cmd)**:
  ```cmd
  set PYTHONPATH=src
  ```

- **Linux/macOS (bash)**:
  ```bash
  export PYTHONPATH=src
  ```

### 6. Запустить локальный сервер:

```bash
python local/local_server.py
```

### 7. Запустить рассылку или статистику вручную (эмуляция триггеров Cloud Functions):

```bash
curl -X POST http://localhost:8080/trigger/mailing_newsletter
curl -X POST http://localhost:8080/trigger/mailing_changes_tt
curl -X POST http://localhost:8080/trigger/daily_statistics
```

---

### Настройка в PyCharm

Вместо установки переменной окружения `PYTHONPATH` рекомендуется пометить директорию `src` как корень проекта:

1. Нажать правой кнопкой мыши на директорию `src`
2. Выбрать **Mark Directory as** → **Sources Root**
