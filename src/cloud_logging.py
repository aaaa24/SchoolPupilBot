import atexit
import json
import logging
import os
import queue
import sys
import threading
import time

DEFAULT_RECORD_KEYS = {
    'name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename', 'module',
    'exc_info', 'exc_text', 'stack_info', 'lineno', 'funcName', 'created', 'msecs',
    'relativeCreated', 'thread', 'threadName', 'processName', 'process', 'message',
    'asctime', 'taskName'
}

RESOURCE_TYPE = 'bot-server'

LEVELS = {'DEBUG': 'DEBUG', 'INFO': 'INFO', 'WARNING': 'WARN', 'ERROR': 'ERROR', 'CRITICAL': 'FATAL'}

_sdk = None
_sdk_lock = threading.Lock()


def create_sdk():
    global _sdk
    import yandexcloud

    with _sdk_lock:
        if _sdk is None:
            key_file = os.getenv('YC_SERVICE_ACCOUNT_KEY_FILE')
            if key_file:
                with open(key_file, encoding='utf-8') as file:
                    _sdk = yandexcloud.SDK(service_account_key=json.load(file))
            else:
                _sdk = yandexcloud.SDK()
    return _sdk


def get_resource_id(context=None):
    resource_id = os.getenv('LOG_RESOURCE_ID')
    if resource_id:
        return resource_id
    return context.function_name if context is not None else None


def extra_fields(record):
    return {
        key: value for key, value in record.__dict__.items()
        if key not in DEFAULT_RECORD_KEYS and not key.startswith('_')
    }


class CloudLoggingHandler(logging.Handler):
    def __init__(self, log_group_id, resource_id, batch_size=100, flush_interval=2):
        super().__init__()
        self.log_group_id = log_group_id
        self.resource_id = resource_id
        self.batch_size = batch_size
        self.flush_interval = flush_interval

        self._queue = queue.Queue(maxsize=10000)
        self._pending = 0
        self._condition = threading.Condition()
        self._flush_now = threading.Event()
        self._stub = None

        self._thread = threading.Thread(target=self._run, name='cloud-logging', daemon=True)
        self._thread.start()
        atexit.register(self.flush)

    def emit(self, record):
        try:
            entry = self._build_entry(record)
        except Exception:
            self.handleError(record)
            return

        with self._condition:
            try:
                self._queue.put_nowait(entry)
            except queue.Full:
                return
            self._pending += 1

    def flush(self, timeout=10):
        self._flush_now.set()
        with self._condition:
            self._condition.wait_for(lambda: self._pending == 0, timeout)
        self._flush_now.clear()

    def _run(self):
        while True:
            entries = self._collect()
            try:
                self._write(entries)
            except Exception as error:
                print(f'Не удалось отправить логи в Cloud Logging: {error}', file=sys.stderr)
            finally:
                with self._condition:
                    self._pending -= len(entries)
                    self._condition.notify_all()

    def _collect(self):
        entries = [self._queue.get()]
        deadline = time.monotonic() + self.flush_interval
        while len(entries) < self.batch_size:
            if self._flush_now.is_set():
                try:
                    entries.append(self._queue.get_nowait())
                except queue.Empty:
                    break
                continue

            timeout = deadline - time.monotonic()
            if timeout <= 0:
                break
            try:
                entries.append(self._queue.get(timeout=timeout))
            except queue.Empty:
                break
        return entries

    def _build_entry(self, record):
        from google.protobuf.struct_pb2 import Struct
        from google.protobuf.timestamp_pb2 import Timestamp
        from yandex.cloud.logging.v1.log_entry_pb2 import IncomingLogEntry, LogLevel

        payload = Struct()
        fields = extra_fields(record)
        if fields:
            payload.update(json.loads(json.dumps(fields, default=str, ensure_ascii=False)))

        timestamp = Timestamp()
        timestamp.FromMilliseconds(int(record.created * 1000))

        return IncomingLogEntry(
            timestamp=timestamp,
            level=LogLevel.Level.Value(LEVELS.get(record.levelname, 'INFO')),
            message=self.format(record),
            json_payload=payload
        )

    def _write(self, entries):
        from yandex.cloud.logging.v1.log_entry_pb2 import Destination
        from yandex.cloud.logging.v1.log_ingestion_service_pb2 import WriteRequest
        from yandex.cloud.logging.v1.log_ingestion_service_pb2_grpc import LogIngestionServiceStub
        from yandex.cloud.logging.v1.log_resource_pb2 import LogEntryResource

        if self._stub is None:
            self._stub = create_sdk().client(LogIngestionServiceStub)

        self._stub.Write(WriteRequest(
            destination=Destination(log_group_id=self.log_group_id),
            resource=LogEntryResource(type=RESOURCE_TYPE, id=self.resource_id),
            entries=entries
        ))


def build_handler():
    if os.getenv('LOG_INGEST') != 'cloud':
        return None

    log_group_id = os.getenv('LOG_GROUP_ID')
    resource_id = get_resource_id()
    if not log_group_id or not resource_id:
        raise ValueError('Для LOG_INGEST=cloud нужны LOG_GROUP_ID и LOG_RESOURCE_ID')

    return CloudLoggingHandler(log_group_id, resource_id)
