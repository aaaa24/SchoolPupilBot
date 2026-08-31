#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from cloud_logging import create_sdk


def load_secrets(secret_id):
    from yandex.cloud.lockbox.v1.payload_service_pb2 import GetPayloadRequest
    from yandex.cloud.lockbox.v1.payload_service_pb2_grpc import PayloadServiceStub

    payload = create_sdk().client(PayloadServiceStub).Get(GetPayloadRequest(secret_id=secret_id))
    return {entry.key: entry.text_value for entry in payload.entries if entry.text_value}


def main():
    if len(sys.argv) < 2:
        raise SystemExit('Использование: bootstrap.py <команда> [аргументы]')

    secret_id = os.getenv('LOCKBOX_SECRET_ID')
    if not secret_id:
        raise SystemExit('Не задана переменная окружения LOCKBOX_SECRET_ID')

    secrets = load_secrets(secret_id)
    for key, value in secrets.items():
        os.environ.setdefault(key, value)
    print(f'Из Lockbox получено значений: {len(secrets)}', file=sys.stderr)

    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == '__main__':
    main()
