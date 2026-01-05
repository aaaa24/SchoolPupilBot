from datetime import datetime
import os
import time

from dotenv import load_dotenv
from flask import Flask, request, jsonify

load_dotenv('.env')

from index import handler

app = Flask(__name__)


@app.route('/webhook', methods=['POST'])
def webhook():
    body_str = request.get_data(as_text=True)

    headers = {}
    multi_value_headers = {}

    for key, value in request.headers:
        headers[key] = value
        multi_value_headers[key] = [value]

    event = {
        'httpMethod': request.method,
        'headers': headers,
        'url': '/?',
        'params': {},
        'multiValueParams': {},
        'pathParams': {},
        'multiValueHeaders': multi_value_headers,
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
        'body': body_str,
        'isBase64Encoded': False,
        'path': '/'
    }

    for key, value in event['headers'].items():
        if key in multi_value_headers and multi_value_headers[key] != [value]:
            multi_value_headers[key] = [value]
        elif key not in multi_value_headers:
            multi_value_headers[key] = [value]

    return jsonify(handler(event, {}))


if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.getenv('LOCAL_PORT', 8080)),
        debug=True
    )
