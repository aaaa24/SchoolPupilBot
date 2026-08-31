#!/bin/sh
set -eu

CERT="${CERT_PATH:-/etc/letsencrypt/live/SERVER_ADDRESS/cert.pem}"
DAYS="${CERT_MIN_DAYS:-2}"

if openssl x509 -in "$CERT" -noout -checkend $((DAYS * 86400)) >/dev/null; then
    exit 0
fi

UNTIL=$(openssl x509 -in "$CERT" -noout -enddate | cut -d= -f2)
TEXT="Сертификат сервера Telegram истекает $UNTIL. Проверьте продление certbot."

if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_TECHNO_INFO:-}" ]; then
    curl -fsS -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
        --data-urlencode "chat_id=$TELEGRAM_TECHNO_INFO" \
        --data-urlencode "text=$TEXT" >/dev/null
fi

echo "$TEXT" >&2
exit 1
