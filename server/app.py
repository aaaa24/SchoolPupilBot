import os
import time
from datetime import datetime
from hmac import compare_digest

from flask import Flask, request

from index import PROXY_SECRET_HEADER, handler
from main import logger

TELEGRAM_SECRET_HEADER = 'X-Telegram-Bot-Api-Secret-Token'

app = Flask(__name__)


def _build_event(path, body):
    headers = dict(request.headers)
    return {
        'httpMethod': request.method,
        'headers': headers,
        'url': '/?',
        'params': {},
        'multiValueParams': {},
        'pathParams': {},
        'multiValueHeaders': {key: [value] for key, value in headers.items()},
        'queryStringParameters': {},
        'multiValueQueryStringParameters': {},
        'requestContext': {
            'identity': {
                'sourceIp': request.remote_addr,
                'userAgent': request.user_agent.string if request.user_agent else ''
            },
            'httpMethod': request.method,
            'requestId': headers.get('X-Request-Id', ''),
            'requestTime': datetime.now().strftime('%d/%b/%Y:%H:%M:%S +0000'),
            'requestTimeEpoch': int(time.time())
        },
        'body': body,
        'isBase64Encoded': False,
        'path': path
    }


def _secret_matches(header, expected):
    if not expected:
        return False
    return compare_digest(request.headers.get(header, '').encode(), expected.encode())


@app.route('/telegram', methods=['POST'])
def telegram():
    if not _secret_matches(TELEGRAM_SECRET_HEADER, os.getenv('WEBHOOK_SECRET_TOKEN')):
        logger.warning('Отклонён запрос без секрета вебхука')
        return '', 403

    try:
        handler(_build_event('/telegram', request.get_data(as_text=True)), None)
    except Exception:
        logger.exception('Ошибка при обработке события Telegram')
    return '!', 200


@app.route('/internal/yookassa', methods=['POST'])
def yookassa():
    if not _secret_matches(PROXY_SECRET_HEADER, os.getenv('PROXY_SECRET')):
        logger.warning('Отклонено уведомление об оплате без секрета')
        return '', 403

    result = handler(_build_event('/yookassa', request.get_data(as_text=True)), None)
    return '!', result['statusCode']


@app.route('/internal/trigger/<payload>', methods=['POST'])
def trigger(payload):
    if request.remote_addr not in ('127.0.0.1', '::1'):
        return '', 403
    if not _secret_matches(PROXY_SECRET_HEADER, os.getenv('PROXY_SECRET')):
        return '', 403

    handler({'details': {'payload': payload}}, None)
    return '!', 200


@app.route('/health', methods=['GET'])
def health():
    return {'status': 'ok', 'messengers': os.getenv('MESSENGERS', '')}, 200
