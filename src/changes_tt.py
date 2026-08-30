import time
from re import search

import ydb
from telebot import types

import album_ui
import constants
from album_ui import callback_data, send_album
from constants import Phrase
from messenger_context import get_messenger_from_kwargs, get_users_table
from photo_album import ChangesAlbum
from utils import edit_level, send_text

SECTION = album_ui.sections['chtt']


def _album(session, date_format):
    return ChangesAlbum(session, date_format)


def _has_changes(date_format, session):
    return not _album(session, date_format).is_empty()


def _send_changes(bot, mm, chat_id, date_format, text, inline_kb, session, logger, messenger):
    return send_album(bot, mm, chat_id, _album(session, date_format), text, inline_kb, messenger, logger)


def mailing_changes_tt(clients, session, logger, *args, **kwargs):
    start_time = time.time()
    logger.debug('Запущена функция mailing_changes_tt')
    log_info = {
        'flag': None, 'date': None,
        'sql_date': None, 'mailing_has_already_been_sent': None,
        'count_files': None, 'is_sent': False,
        'total_count': None, 'final_count': None
    }

    request = session.transaction().execute(
        'SELECT * FROM app WHERE key = "mailing_has_been_sent";',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )
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

    changes = _album(session, sql_date).items()
    log_info['date'] = date
    log_info['sql_date'] = sql_date
    log_info['flag'] = flag
    log_info['count_files'] = len(changes)

    if flag == 'today' and mailing_has_already_been_sent:
        session.transaction().execute(
            'UPSERT INTO app (key, value) VALUES ("mailing_has_been_sent", "false");',
            commit_tx=True,
            settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
        )
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
            request = session.transaction().execute(
                f'SELECT id FROM {get_users_table(messenger)} WHERE send_changes_tt = true;',
                commit_tx=True,
                settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
            )
            users = [row['id'] for row in request[0].rows]
            total_count += len(users)
            for user_id in users:
                try:
                    _send_changes(bot, None, user_id, sql_date, text, inline_kb, session, logger, messenger)
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
                session.transaction().execute(
                    'UPSERT INTO app (key, value) VALUES ("mailing_has_been_sent", "true");',
                    commit_tx=True,
                    settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
                )

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
        session.transaction().execute(
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
        session.transaction().execute(
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
                          year=time_date.tm_year
                          )

    else:
        text = Phrase.ERROR_DATE
        f = 0

    list_inline_btn = []
    if f:
        if user['admin']:
            if f == 1:
                list_inline_btn.append(('Редактировать на этот день', callback_data(SECTION, date, 'ed', 1)))
            if f == 2:
                list_inline_btn.append(('Добавить на этот день', callback_data(SECTION, date, 'add')))
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
            _send_changes(bot, copy_m, m.chat.id, date_format, text, inline_kb, session, kwargs['logger'],
                          get_messenger_from_kwargs(kwargs))
        edit_level(copy_m, 'menu', session)
    else:
        send_text(bot, copy_m, text, inline_kb)


def find_date(text):
    text = text.replace('/', '.').replace('\\', '.')

    months = [i['abb_name'].replace(".", "") for i in constants.months] + [i['dec'] for i in constants.months]
    if not (s1 := search(r'\d{1,2}\.\d{2}\.\d{4}', text)) is None:
        date = s1[0]
    elif not (s2 := search(r'\d{1,2}\.\d{2}\.\d{2}', text)) is None:
        date = s2[0][:-2] + '20' + s2[0][-2:]
    elif not (s3 := search(r'\d{1,2}\.\d{2}', text)) is None:
        date = s3[0] + '.' + time.strftime('%Y', time.localtime(time.time() + 10800))
    elif not (s4 := search('\\d{1,2} ' + f'({"|".join(months)})' + ' \\d{4}', text)) is None:
        sp = s4[0].split()
        for m in constants.months:
            if sp[1] == m['dec'] or sp[1] in m['abb_name']:
                mon = ('0' + str(m['num']))[-2:]
        date = sp[0] + '.' + mon + '.' + sp[2]
    elif not (s5 := search('\\d{1,2} ' + f'({"|".join(months)})', text)) is None:
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
            return None, None
    elif int(sp[1]) in (4, 6, 9, 11):
        if not 1 <= int(sp[0]) <= 30:
            return None, None
    elif int(sp[1]) == 2:
        if int(sp[2]) % 4 == 0 and int(sp[2]) % 400 != 0 and not 1 <= int(sp[0]) <= 29:
            return None, None
        elif (int(sp[2]) % 4 != 0 or int(sp[2]) % 400 == 0) and not 1 <= int(sp[0]) <= 28:
            return None, None
    else:
        return None, None

    try:
        time.strptime(date, '%d.%m.%Y')
    except ValueError:
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
                    list_inline_btn += [('Редактировать на сегодня', callback_data(SECTION, date_today, 'ed', 1))]
                else:
                    list_inline_btn += [('Добавить на сегодня', callback_data(SECTION, date_today, 'add'))]
            if flag == 1:
                list_inline_btn += [('Добавить на завтра' if time_now.tm_wday != 5 else 'Добавить на послезавтра',
                                     callback_data(SECTION, date_tomorrow, 'add'))]
            elif flag == 2:
                list_inline_btn += [
                    ('Редактировать на завтра' if time_now.tm_wday != 5 else 'Редактировать на послезавтра',
                     callback_data(SECTION, date_tomorrow, 'ed', 1))]
        else:
            list_inline_btn += [('Редактировать на завтра' if time_now.tm_wday != 5 else 'Редактировать на послезавтра',
                                 callback_data(SECTION, date_tomorrow, 'ed', 1))]
            if time_now.tm_wday != 6:
                list_inline_btn += [('Редактировать на сегодня', callback_data(SECTION, date_today, 'ed', 1))]

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
        _send_changes(bot, mm, m.chat.id, target_date, text, inline_kb, session, kwargs['logger'],
                      get_messenger_from_kwargs(kwargs))
    if user['level'] != 'menu':
        edit_level(mm, 'menu', session)
