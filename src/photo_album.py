from uuid import uuid4

import ydb

from messengers import MediaItem, Messenger, get_client
from storage import ObjectStorage


def _execute(session, query):
    return session.transaction().execute(
        query,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )


def media_column(messenger):
    return {
        Messenger.TELEGRAM: 'tg_file_id',
        Messenger.MAX: 'max_token',
    }[Messenger(messenger)]


def photos_to_add(m, messenger):
    # В Telegram m.photo — размеры одной фотографии, нужен самый большой,
    # а в MAX одно сообщение содержит все отправленные фотографии
    if not m.photo:
        return []
    if Messenger(messenger) is Messenger.MAX:
        return m.photo
    return [m.photo[-1]]


class PhotoAlbum:
    # Упорядоченный набор фотографий одного экрана: порядок задаёт seq_number (1..N без пропусков),
    # идентификаторы мессенджеров лежат рядом, а резервная копия в S3 нужна,
    # пока фотография не выгружена в оба мессенджера
    table = None
    # Тип колонки seq_number в YDB: арифметика в YQL расширяет его до Int32,
    # поэтому при записи номер приводится обратно явным CAST
    seq_number_type = 'Uint8'

    def __init__(self, session, scope=None):
        self.session = session
        self.scope = scope
        self._storage = None

    def seq(self, expression):
        return f'CAST({expression} AS {self.seq_number_type})'

    @property
    def condition(self):
        return 'true'

    @property
    def extra_columns(self):
        return {}

    @property
    def storage(self):
        if self._storage is None:
            self._storage = ObjectStorage()
        return self._storage

    def items(self):
        result = _execute(self.session,
                          f'SELECT * FROM {self.table} WHERE {self.condition} ORDER BY seq_number;')
        return [dict(row) for row in result[0].rows]

    def count(self):
        result = _execute(self.session,
                          f'SELECT COUNT(*) AS count FROM {self.table} WHERE {self.condition};')
        return result[0].rows[0]['count']

    def is_empty(self):
        return self.count() == 0

    def _set_seq_number(self, row_id, seq_number):
        _execute(self.session,
                 f'UPDATE {self.table} SET seq_number = {self.seq(seq_number)} WHERE id = Uuid("{row_id}");')

    def _renumber(self, rows):
        # Номера переписываются по фактическому порядку строк, по одному запросу на строку:
        # так альбом заодно чинит пропуски и дубликаты, оставшиеся от прежних операций
        for number, row in enumerate(rows, start=1):
            if row.get('seq_number') != number:
                self._set_seq_number(row['id'], number)
                row['seq_number'] = number

    def add(self, bot, photos):
        client = get_client(bot)
        column = media_column(client.platform)

        rows = self.items()
        self._renumber(rows)
        seq_number = len(rows) + 1
        added = 0

        for photo in photos:
            data, content_type = client.download_photo(photo)
            item_id = uuid4()
            s3_file_name = self.storage.upload_photo(data, content_type, filename=str(item_id))

            columns = {
                'id': f'Uuid("{item_id}")',
                'seq_number': self.seq(seq_number),
                column: f'"{photo.file_id}"',
                's3_file_name': f'"{s3_file_name}"',
            }
            columns.update(self.extra_columns)

            try:
                _execute(self.session,
                         f'INSERT INTO {self.table} ({", ".join(columns)}) '
                         f'VALUES ({", ".join(columns.values())});')
            except Exception:
                self.storage.delete_photo(s3_file_name)
                raise

            seq_number += 1
            added += 1

        return added

    def delete(self, position):
        rows = self.items()
        if not 1 <= position <= len(rows):
            return False

        row = rows.pop(position - 1)
        if row.get('s3_file_name'):
            self.storage.delete_photo(row['s3_file_name'])

        _execute(self.session, f'DELETE FROM {self.table} WHERE id = Uuid("{row["id"]}");')
        self._renumber(rows)
        return True

    def delete_all(self):
        rows = self.items()
        for row in rows:
            if row.get('s3_file_name'):
                self.storage.delete_photo(row['s3_file_name'])

        _execute(self.session, f'DELETE FROM {self.table} WHERE {self.condition};')
        return len(rows)

    def move(self, position, delta):
        # Позиция — номер в текущем порядке показа, а не значение seq_number:
        # так перестановка работает и когда номера в базе разъехались
        rows = self.items()
        target = position + delta
        if not (1 <= position <= len(rows) and 1 <= target <= len(rows)):
            return position

        rows[position - 1], rows[target - 1] = rows[target - 1], rows[position - 1]
        self._renumber(rows)
        return target

    def media(self, messenger, logger, rows=None):
        # Возвращает пары (строка, MediaItem): id для текущего мессенджера или байты из резервной копии
        column = media_column(messenger)
        media = []

        for row in (self.items() if rows is None else rows):
            item = MediaItem(id=row.get(column))
            if not item.id:
                filename = row.get('s3_file_name')
                if not filename:
                    logger.error('Не найдена резервная копия фотографии',
                                 extra={'table': self.table, 'photo_id': str(row['id'])})
                    continue
                item.data, item.content_type = self.storage.download_photo(filename)
                item.filename = filename
            media.append((row, item))

        return media

    def save_media(self, messenger, media):
        column = media_column(messenger)

        for row, item in media:
            if row.get(column) or not item.id:
                continue

            _execute(self.session,
                     f'UPDATE {self.table} SET {column} = "{item.id}" WHERE id = Uuid("{row["id"]}");')
            row[column] = item.id

            if row.get('tg_file_id') and row.get('max_token') and row.get('s3_file_name'):
                self.storage.delete_photo(row['s3_file_name'])
                _execute(self.session,
                         f'UPDATE {self.table} SET s3_file_name = NULL WHERE id = Uuid("{row["id"]}");')
                row['s3_file_name'] = None


class ChangesAlbum(PhotoAlbum):
    # scope — дата в формате YYYY-MM-DD
    table = 'changes_tt'

    @property
    def condition(self):
        return f'date = Date("{self.scope}")'

    @property
    def extra_columns(self):
        return {'date': f'Date("{self.scope}")'}


class TimetablePhotoAlbum(PhotoAlbum):
    table = 'timetable_photo'
