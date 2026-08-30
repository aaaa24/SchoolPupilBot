import time
from re import search
from uuid import uuid4

import ydb
from telebot import types

import constants
from constants import Phrase
from messenger_context import get_messenger_from_kwargs, get_users_table
from messengers import MediaItem, Messenger, ScreenState, force_new_screen, get_client
from storage import ObjectStorage
from utils import edit_level, suffixes


def _execute(session, query):
    return session.transaction().execute(
        query,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )


def _media_column(messenger):
    return {
        Messenger.TELEGRAM: 'tg_file_id',
        Messenger.MAX: 'max_token',
    }[Messenger(messenger)]


def _get_changes(date, session):
    result = _execute(session, f'SELECT * FROM changes_tt WHERE date = Date("{date}")')
    return [dict(row) for row in result[0].rows]


def _has_changes(date, session):
    return bool(_get_changes(date, session))


def _save_media_id(change_id, messenger, media_id, session):
    _execute(
        session,
        f'UPDATE changes_tt SET {_media_column(messenger)} = "{media_id}" WHERE id = Uuid("{change_id}");'
    )


def _screen_state(mm, chat_id):
    if hasattr(mm, 'message'):
        return ScreenState(chat_id=chat_id, message_id=mm.message.id, content_type=mm.message.content_type)
    return ScreenState(chat_id=chat_id)


def _force_new(mm):
    return hasattr(mm, 'data') and force_new_screen(mm.data)


def send_text(bot, mm, text, inline_kb):
    if hasattr(mm, 'message'):
        suffixes(bot, mm, text, inline_kb)
        chat_id = mm.message.chat.id
    else:
        chat_id = mm.chat.id

    client = get_client(bot)
    return client.render_screen(_screen_state(mm, chat_id), text, [], reply_markup=inline_kb,
                                force_new=_force_new(mm))


def _send_changes(bot, mm, chat_id, date, text, inline_kb, session, logger):
    if hasattr(mm, 'message'):
        suffixes(bot, mm, text, inline_kb)

    client = get_client(bot)
    messenger = client.platform
    media_column = _media_column(messenger)
    storage = None

    media = []
    for change in _get_changes(date, session):
        item = MediaItem(id=change.get(media_column))
        if not item.id:
            filename = change.get('s3_file_name')
            if not filename:
                logger.error('Не найдена резервная копия изменения расписания', extra={'change_id': change['id']})
                continue
            storage = storage or ObjectStorage()
            item.data, item.content_type = storage.download_photo(filename)
            item.filename = filename
        media.append((change, item))

    if mm is None:
        result = client.send_message_to_user(chat_id, text, media=[item for _, item in media],
                                             reply_markup=inline_kb)
    else:
        result = client.render_screen(_screen_state(mm, chat_id), text, [item for _, item in media],
                                      reply_markup=inline_kb, force_new=_force_new(mm))

    for change, item in media:
        if change.get(media_column) or not item.id:
            continue
        _save_media_id(change['id'], messenger, item.id, session)
        change[media_column] = item.id
        # резервная копия в S3 нужна, пока фотография не выгружена в оба мессенджера
        if change.get('tg_file_id') and change.get('max_token'):
            storage = storage or ObjectStorage()
            storage.delete_photo(change['s3_file_name'])
            _execute(session, f'UPDATE changes_tt SET s3_file_name = NULL WHERE id = Uuid("{change["id"]}");')

    return result


def edit_changes_tt(m, user, bot, session, *args, **kwargs):
    date = m.data.split('$')[0].split('_')[1]
    time_date = time.strptime(date, '%d.%m.%Y')

    text = Phrase.EDIT_CHANGES_TT.format(acc=constants.weekdays[time_date.tm_wday]['accusative'],
                                         day=time_date.tm_mday,
                                         dec=constants.months[time_date.tm_mon - 1]['dec'],
                                         year=time_date.tm_year
                                         )

    list_inline_btn = [('Добавить на этот день', f'achtt_{date}'), ('Удалить на этот день', f'delchtt_{date}')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    list_inline_btn = [('← Назад', f'chtt_{date}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)


def del_changes_tt(m, user, bot, session, *args, **kwargs):
    date = m.data.split('$')[0].split('_')[1]
    date_format = '-'.join(date.split('.')[::-1])
    time_date = time.strptime(date, '%d.%m.%Y')

    changes = _get_changes(date_format, session)
    filenames = [change['s3_file_name'] for change in changes if change.get('s3_file_name')]
    if filenames:
        storage = ObjectStorage()
        for filename in filenames:
            storage.delete_photo(filename)
    _execute(session, f'DELETE FROM changes_tt WHERE date = Date("{date_format}")')

    text = Phrase.YES_DEL_CHANGES_TT.format(acc=constants.weekdays[time_date.tm_wday]['accusative'],
                                            day=time_date.tm_mday,
                                            dec=constants.months[time_date.tm_mon - 1]['dec'],
                                            year=time_date.tm_year
                                            )

    list_inline_btn = [('Добавить на этот день', f'achtt_{date}'), ('📝 Изменения в расписании', 'chtt'),
                       ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    send_text(bot, m, text, inline_kb)


def confirmation_del_changes_tt(m, user, bot, session, *args, **kwargs):
    date = m.data.split('$')[0].split('_')[1]
    time_date = time.strptime(date, '%d.%m.%Y')

    text = Phrase.CONFIRMATION_OF_DEL_CHANGES_TT.format(acc=constants.weekdays[time_date.tm_wday]['accusative'],
                                                        day=time_date.tm_mday,
                                                        dec=constants.months[time_date.tm_mon - 1]['dec'],
                                                        year=time_date.tm_year
                                                        )

    list_inline_btn = [('Да', f'delchtt_{date}_Да'), ('Нет', f'echtt_{date}')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().row(*inline_buttons)
    inline_kb.row(types.InlineKeyboardButton('🏠 В меню', callback_data='menu'))

    send_text(bot, m, text, inline_kb)


def mailing_changes_tt(clients, session, logger, *args, **kwargs):
    start_time = time.time()
    logger.debug('Запущена функция mailing_changes_tt')
    log_info = {
        'flag': None, 'date': None,
        'sql_date': None, 'mailing_has_already_been_sent': None,
        'count_files': None, 'is_sent': False,
        'total_count': None, 'final_count': None
    }

    request = _execute(session, 'SELECT * FROM app WHERE key = "mailing_has_been_sent";')
    mailing_has_already_been_sent = True if request[0].rows[0]['value'] == 'true' else False
    log_info['mailing_has_already_been_sent'] = mailing_has_already_been_sent

    control_hour = 16
    control_min = 0
    t = time.time() + 10800
    struct_time = time.localtime(t)
    if struct_time.tm_hour < control_hour or struct_time.tm_hour == control_hour and struct_time.tm_min <= control_min:
        flag = 'today'
    else:
        flag = 'tomorrow'
        struct_time = time.localtime(t + 86400)
    date = f'{struct_time.tm_mday}.{struct_time.tm_mon}.{struct_time.tm_year}'
    sql_date = f'{struct_time.tm_year}-{struct_time.tm_mon}-{struct_time.tm_mday}'

    changes = _get_changes(sql_date, session)
    log_info['date'] = date
    log_info['sql_date'] = sql_date
    log_info['flag'] = flag
    log_info['count_files'] = len(changes)

    if flag == 'today' and mailing_has_already_been_sent:
        _execute(session, 'UPSERT INTO app (key, value) VALUES ("mailing_has_been_sent", "false");')
    elif changes:
        text = Phrase.CHANGES_TT_SOON.format(fewd='завтра' if flag == 'tomorrow' else 'сегодня',
                                             weekd=constants.weekdays[struct_time.tm_wday]['name'],
                                             day=struct_time.tm_mday,
                                             dec=constants.months[struct_time.tm_mon - 1]['dec'])

        list_inline_btn = [
            ('🔔 Подписка на изменения', 'subchtt$new'),
            ('🏠 В меню', 'menu$new')
        ]
        inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
        inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

        from main import set_log_messenger

        total_count = 0
        final_count = 0
        for messenger, bot in clients.items():
            set_log_messenger(messenger)
            request = _execute(
                session,
                f'SELECT id FROM {get_users_table(messenger)} WHERE send_changes_tt = true;'
            )
            users = [row['id'] for row in request[0].rows]
            total_count += len(users)
            for user_id in users:
                try:
                    _send_changes(bot, None, user_id, sql_date, text, inline_kb, session, logger)
                except Exception:
                    logger.exception('Не удалось отправить изменения в расписании', extra={'user_id': user_id})
                else:
                    final_count += 1
        set_log_messenger(None)
        log_info['total_count'] = total_count
        log_info['final_count'] = final_count
        log_info['is_sent'] = True

        if flag == 'tomorrow':
            if not mailing_has_already_been_sent:
                _execute(session, 'UPSERT INTO app (key, value) VALUES ("mailing_has_been_sent", "true");')

    logger.debug('Завершена функция mailing_changes_tt', extra={'duration': time.time() - start_time, 'info': log_info})


def subscribe(m, user, bot, session, *args, **kwargs):
    inline_kb = types.InlineKeyboardMarkup()
    if user['send_changes_tt']:
        text = Phrase.SUBSCRIBE_CHANGES_TT.format(onoff='✅', subscr='подписаны на рассылку', text='')
        inline_kb.row(types.InlineKeyboardButton('❌ Отписаться от изменений', callback_data='subchtt_off'))
    else:
        text = Phrase.SUBSCRIBE_CHANGES_TT.format(onoff='❌', subscr='не подписаны на рассылку',
                                                  text='.\n\nВы можете подписаться на рассылку изменений в расписании. В таком случае бот будет присылать изменения в расписании в 20:00 или в 08:00 в зависимости от того, когда изменения были загружены')
        inline_kb.row(types.InlineKeyboardButton('✅ Подписаться на изменения', callback_data='subchtt_on'))

    list_inline_btn = [('← Назад', 'chtt'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    if user['level'] != 'menu':
        edit_level(m, 'menu', session)


def on_subscribe(m, user, bot, session, *args, **kwargs):
    if user['send_changes_tt']:
        text = Phrase.SUBSCRIBE_CHANGES_TT.format(onoff='✅', subscr='уже подписаны на рассылку',
                                                  text='. Изменения будут приходить в 20:00 или в 08:00 в зависимости от того, когда они были загружены')
    else:
        request = session.transaction().execute(
            f'UPSERT INTO {get_users_table(get_messenger_from_kwargs(kwargs))} (id, send_changes_tt) VALUES ({user["id"]}, True);',
            commit_tx=True,
            settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
        )
        text = Phrase.SUBSCRIBE_CHANGES_TT.format(onoff='✅', subscr='успешно подписались на рассылку', text='')

    inline_kb = types.InlineKeyboardMarkup().row(
        types.InlineKeyboardButton('❌ Отписаться от изменений', callback_data='subchtt_off'))
    list_inline_btn = [('← Назад', 'chtt'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)


def off_subscribe(m, user, bot, session, *args, **kwargs):
    if not user['send_changes_tt']:
        text = Phrase.SUBSCRIBE_CHANGES_TT.format(onoff='❌', subscr='уже отписаны от рассылки', text='')
    else:
        request = session.transaction().execute(
            f'UPSERT INTO {get_users_table(get_messenger_from_kwargs(kwargs))} (id, send_changes_tt) VALUES ({user["id"]}, False);',
            commit_tx=True,
            settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
        )
        text = Phrase.SUBSCRIBE_CHANGES_TT.format(onoff='❌', subscr='успешно отписались от рассылки', text='')

    inline_kb = types.InlineKeyboardMarkup().row(
        types.InlineKeyboardButton('✅ Подписаться на изменения', callback_data='subchtt_on'))
    list_inline_btn = [('← Назад', 'chtt'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)


def get_photo(m, user, bot, session, *args, **kwargs):
    if 'date' in kwargs:
        date = kwargs['date']
        time_date = time.strptime(date, '%d.%m.%Y')
        text = Phrase.EDIT_CHANGES_DATE.format(acc=constants.weekdays[time_date.tm_wday]['accusative'],
                                               day=time_date.tm_mday, dec=constants.months[time_date.tm_mon - 1]['dec'],
                                               year=time_date.tm_year)

        message_text = m.message.text
        if message_text is None:
            message_text = m.message.caption
        if search(Phrase.EDIT_CHANGES_TT.replace('(', r'\(').replace(')', r'\)').format(**constants.dict_re),
                  message_text):
            list_inline_btn = [('← Назад', f'echtt_{date}')]
        elif search(Phrase.CHANGES_TT_SOON.replace('(', r'\(').replace(')', r'\)').format(**constants.dict_re),
                    message_text) or \
                search(Phrase.NOT_CHANGES_TT_SOON.replace('(', r'\(').replace(')', r'\)').format(**constants.dict_re),
                       message_text):
            list_inline_btn = [('← Назад', 'chtt')]
        else:
            list_inline_btn = [('← Назад', f'chtt_{date}')]
    else:
        text = Phrase.EDIT_CHANGES_NOT_DATE
        list_inline_btn = [('← Назад', 'chtt')]

    list_inline_btn += [('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    if 'date' in kwargs:
        edit_level(m, f'achtt_{date}', session)
    else:
        edit_level(m, 'achtt', session)


def _photos_to_add(m, messenger):
    # В Telegram m.photo — размеры одной фотографии, нужен самый большой,
    # а в MAX одно сообщение содержит все отправленные фотографии
    if not m.photo:
        return []
    if Messenger(messenger) is Messenger.MAX:
        return m.photo
    return [m.photo[-1]]


def add_changes_tt(m, user, bot, session, *args, **kwargs):
    if args:
        date = args[0]
        date_format = '-'.join(date.split('.')[::-1])
        flag = 1
    else:
        flag = 0

    if m.is_edit_text:
        c_data, c_date_format = find_date(m.text)
        if not c_data is None:
            date, date_format = c_data, c_date_format
            flag = 1
    elif not m.is_edit_text and not m.text and not args:
        text = Phrase.NEED_CAPTION
        flag = 0
    else:
        if not args:
            text = Phrase.EDIT_CHANGES_NOT_DATE
            flag = 0

    if flag:
        time_date = time.strptime(date, '%d.%m.%Y')
        if time_date.tm_wday == 6:
            phr = Phrase.EDIT_IT_IS_SUNDAY
            flag = 0
            list_inline_btn = [('← Назад', 'chtt')]
        else:
            messenger = get_messenger_from_kwargs(kwargs)
            photos = _photos_to_add(m, messenger)
            if not photos:
                phr = Phrase.EDIT_CHANGES_NOT_DATE
                flag = 0
                list_inline_btn = [('← Назад', 'chtt')]
            else:
                client = get_client(bot)
                storage = ObjectStorage()
                for photo in photos:
                    data, content_type = client.download_photo(photo)
                    change_id = uuid4()
                    s3_file_name = storage.upload_photo(data, content_type, filename=str(change_id))
                    _execute(
                        session,
                        f'INSERT INTO changes_tt (id, {_media_column(messenger)}, date, s3_file_name) '
                        f'VALUES (Uuid("{change_id}"), "{photo.file_id}", DATE("{date_format}"), "{s3_file_name}");'
                    )
                phr = Phrase.EDIT_CHANGES_SUCCESSFULL
                list_inline_btn = [('← Назад', f'chtt_{date}')]

        text = phr.format(acc=constants.weekdays[time_date.tm_wday]['accusative'],
                          day=time_date.tm_mday, dec=constants.months[time_date.tm_mon - 1]['dec'],
                          year=time_date.tm_year)
    else:
        list_inline_btn = [('← Назад', 'chtt')]

    list_inline_btn.append(('🏠 В меню', 'menu'))
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=2).add(*inline_buttons)

    bot.send_message(m.chat.id, text, reply_markup=inline_kb)
    if flag:
        edit_level(m, 'menu', session)


def specific_edit_date(m, user, bot, session, *args, **kwargs):
    date = m.data.split('$')[0].split('_')[1]
    kwargs['date'] = date
    kwargs['date_format'] = '-'.join(date.split('.')[::-1])
    get_photo(m, user, bot, session, *args, **kwargs)


def specific_date(m, user, bot, session, *args, **kwargs):
    date = m.data.split('$')[0].split('_')[1]
    kwargs['date'] = date
    kwargs['date_format'] = '-'.join(date.split('.')[::-1])
    send_date(m, user, bot, session, *args, **kwargs)


def send_date(m, user, bot, session, *args, **kwargs):
    copy_m = m
    if 'date' in kwargs:
        date, date_format = kwargs['date'], kwargs['date_format']
        if hasattr(m, 'message'):
            m = m.message
    else:
        text = m.text
        date, date_format = find_date(text)

    if not date is None:
        time_date = time.strptime(date, '%d.%m.%Y')
        if time_date.tm_wday == 6:
            phr = Phrase.IT_IS_SUNDAY
            f = 0
        else:
            has_changes = _has_changes(date_format, session)
            if has_changes:
                phr = Phrase.CHANGES_TT_WEEKDAY
                f = 1
            else:
                phr = Phrase.NOT_CHANGES_TT_WEEKDAY
                f = 2
        text = phr.format(acc=constants.weekdays[time_date.tm_wday]['accusative'],
                          day=time_date.tm_mday, dec=constants.months[time_date.tm_mon - 1]['dec'],
                          year=time_date.tm_year)

    else:
        text = Phrase.ERROR_DATE
        f = 0

    list_inline_btn = []
    if f:
        if user['admin']:
            if f == 1:
                list_inline_btn.append(('Редактировать на этот день', f'echtt_{date}'))
            if f == 2:
                list_inline_btn.append(('Добавить на этот день', f'achtt_{date}'))
        list_inline_btn.append(('Изменения на другой день', 'dchtt'))
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    list_inline_btn = [('← Назад', 'chtt'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    if f:
        if f == 2:
            send_text(bot, copy_m, text, inline_kb)
        else:
            _send_changes(bot, copy_m, m.chat.id, date_format, text, inline_kb, session, kwargs['logger'])
        edit_level(copy_m, 'menu', session)
    else:
        send_text(bot, copy_m, text, inline_kb)


def find_date(text):
    text = text.replace('/', '.').replace('\\', '.')

    months = [i['abb_name'].replace(".", "") for i in constants.months] + [i['dec'] for i in constants.months]
    if not (s1 := search(r'\d{1,2}\.\d{2}\.\d{4}', text)) is None:
        print('Первый вариант даты найден')
        date = s1[0]
    elif not (s2 := search(r'\d{1,2}\.\d{2}\.\d{2}', text)) is None:
        print('Второй вариант даты найден')
        date = s2[0][:-2] + '20' + s2[0][-2:]
    elif not (s3 := search(r'\d{1,2}\.\d{2}', text)) is None:
        print('Третий вариант даты найден')
        date = s3[0] + '.' + time.strftime('%Y', time.localtime(time.time() + 10800))
    elif not (s4 := search('\\d{1,2} ' + f'({"|".join(months)})' + ' \\d{4}', text)) is None:
        print('Четвёртый вариант даты найден')
        sp = s4[0].split()
        for m in constants.months:
            if sp[1] == m['dec'] or sp[1] in m['abb_name']:
                mon = ('0' + str(m['num']))[-2:]
        date = sp[0] + '.' + mon + '.' + sp[2]
    elif not (s5 := search('\\d{1,2} ' + f'({"|".join(months)})', text)) is None:
        print('Пятый вариант даты найден')
        sp = s5[0].split()
        for m in constants.months:
            if sp[1] == m['dec'] or sp[1] in m['abb_name']:
                mon = ('0' + str(m['num']))[-2:]
        date = sp[0] + '.' + mon + '.' + time.strftime('%Y', time.localtime(time.time() + 10800))
    else:
        return None, None

    sp = date.split('.')
    if int(sp[1]) in (1, 3, 5, 7, 8, 10, 12):
        if not 1 <= int(sp[0]) <= 31:
            print(0)
            return None, None
    elif int(sp[1]) in (4, 6, 9, 11):
        if not 1 <= int(sp[0]) <= 30:
            print(1)
            return None, None
    elif int(sp[1]) == 2:
        if int(sp[2]) % 4 == 0 and int(sp[2]) % 400 != 0 and not 1 <= int(sp[0]) <= 29:
            print(2)
            return None, None
        elif (int(sp[2]) % 4 != 0 or int(sp[2]) % 400 == 0) and not 1 <= int(sp[0]) <= 28:
            print(3)
            return None, None
    else:
        print(4)
        return None, None

    try:
        time.strptime(date, '%d.%m.%Y')
    except ValueError:
        print(5)
        return None, None

    if date.index('.') == 1:
        date = '0' + date

    date_format = '-'.join(date.split('.')[::-1])
    return date, date_format


def get_date(m, user, bot, session, *args, **kwargs):
    list_inline_btn = [('← Назад', 'chtt'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

    send_text(bot, m, Phrase.INPUT_DATE, inline_kb)
    edit_level(m, 'dchtt', session)


def call(m, user, bot, session, *args, **kwargs):
    t = time.time() + 10800
    time_now = time.localtime(t)
    sql_today = f'{time_now.tm_year}-{time_now.tm_mon}-{time_now.tm_mday}'
    date_today = f'{time_now.tm_mday}.{time_now.tm_mon}.{time_now.tm_year}'

    if time_now.tm_wday == 5:
        tomorrow = time.localtime(t + 2 * 86400)
    else:
        tomorrow = time.localtime(t + 86400)
    sql_tomorrow = f'{tomorrow.tm_year}-{tomorrow.tm_mon}-{tomorrow.tm_mday}'
    date_tomorrow = f'{tomorrow.tm_mday}.{tomorrow.tm_mon}.{tomorrow.tm_year}'

    control_hour = 16
    control_min = 0

    list_inline_btn = []

    if time_now.tm_hour >= control_hour and time_now.tm_min >= control_min or time_now.tm_wday == 6:
        has_changes = _has_changes(sql_tomorrow, session)
        if has_changes:
            text = Phrase.CHANGES_TT_SOON.format(fewd='завтра' if time_now.tm_wday != 5 else 'послезавтра',
                                                 weekd=constants.weekdays[tomorrow.tm_wday]['name'],
                                                 day=tomorrow.tm_mday, dec=constants.months[tomorrow.tm_mon - 1]['dec'])
            if time_now.tm_wday != 6:
                list_inline_btn += [('Изменения на сегодня', f'chtt_{date_today}')]
            flag = 0
        else:
            flag = 1
    else:
        flag = 2
    if flag:
        if time_now.tm_wday != 6:
            has_changes = _has_changes(sql_today, session)
            if has_changes:
                text = Phrase.CHANGES_TT_SOON.format(fewd='сегодня', weekd=constants.weekdays[time_now.tm_wday]['name'],
                                                     day=time_now.tm_mday,
                                                     dec=constants.months[time_now.tm_mon - 1]['dec'])
            else:
                text = Phrase.NOT_CHANGES_TT_SOON.format(fewd='сегодня',
                                                         weekd=constants.weekdays[time_now.tm_wday]['name'],
                                                         day=time_now.tm_mday,
                                                         dec=constants.months[time_now.tm_mon - 1]['dec'])
            if flag == 2:
                list_inline_btn += [('Изменения на завтра' if time_now.tm_wday != 5 else 'Изменения на послезавтра',
                                     f'chtt_{date_tomorrow}')]
        else:
            text = Phrase.NOT_CHANGES_TT_SOON.format(fewd='завтра', weekd=constants.weekdays[tomorrow.tm_wday]['name'],
                                                     day=tomorrow.tm_mday,
                                                     dec=constants.months[tomorrow.tm_mon - 1]['dec'])

    list_inline_btn += [('Изменения на другой день', 'dchtt')]
    if user['admin']:
        if flag:
            if time_now.tm_wday != 6:
                if has_changes:
                    list_inline_btn += [('Редактировать на сегодня', f'echtt_{date_today}')]
                else:
                    list_inline_btn += [('Добавить на сегодня', f'achtt_{date_today}')]
            if flag == 1:
                list_inline_btn += [('Добавить на завтра' if time_now.tm_wday != 5 else 'Добавить на послезавтра',
                                     f'achtt_{date_tomorrow}')]
            elif flag == 2:
                list_inline_btn += [
                    ('Редактировать на завтра' if time_now.tm_wday != 5 else 'Редактировать на послезавтра',
                     f'echtt_{date_tomorrow}')]
        else:
            list_inline_btn += [('Редактировать на завтра' if time_now.tm_wday != 5 else 'Редактировать на послезавтра',
                                 f'echtt_{date_tomorrow}')]
            if time_now.tm_wday != 6:
                list_inline_btn += [('Редактировать на сегодня', f'echtt_{date_today}')]

    list_inline_btn += [
        ('🔔 Подписка на изменения', 'subchtt'),
        ('🏠 В меню', 'menu')
    ]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    mm = m
    if hasattr(m, 'message'):
        m = m.message

    if not has_changes:
        send_text(bot, mm, text, inline_kb)
    else:
        target_date = sql_tomorrow if not flag else sql_today
        _send_changes(bot, mm, m.chat.id, target_date, text, inline_kb, session, kwargs['logger'])
    if user['level'] != 'menu':
        edit_level(mm, 'menu', session)
