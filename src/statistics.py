from telebot import types

from funcs import send_text
from var import Phrase


def daily_statistics(bot, context, logger, *args, **kwargs):
    from time import time
    import os

    t = time()
    logger.debug('Запущена функция daily_statistics')

    text_filter = 'type_event EXISTS'
    since = get_timestamp(offset=300, flag='since_day')
    until = get_timestamp()
    logs = get_logs(os.getenv('LOG_GROUP_ID'), context.function_name, text_filter, since=since, until=until)

    parts_text = create_stat_from_logs(logs)
    for text in parts_text:
        bot.send_message(os.getenv('TECHNO_INFO'), text, parse_mode='HTML', disable_notification=True)
    logger.debug('Статистика отправлена', extra={'duration': time() - t})


def create_stat_from_logs(logs):
    users, commands, datas, levels, user_commands, user_datas, user_levels = {}, {}, {}, {}, {}, {}, {}

    list_types = {
        'command': ('command', commands, user_commands),
        'callback_query': ('type_query', datas, user_datas),
        'message': ('type_level', levels, user_levels)
    }

    for log in logs:
        info_type_event = list_types[log.json_payload['type_event']]
        key, stat_event, stat_user = info_type_event

        data = log.json_payload['info'][key]
        plus_count(stat_event, data)

        user_id = int(log.json_payload['info']['user_id'])
        plus_count(stat_user, user_id)
        plus_count(users, user_id)

    parts_text = create_stat_text(len(logs), users, commands, datas, levels, user_commands, user_datas, user_levels)
    return parts_text


def plus_count(obj, key):
    if key in obj:
        obj[key] += 1
    else:
        obj[key] = 1


def get_timestamp(offset=0, flag=None):
    from time import time, localtime, mktime
    from google.protobuf import timestamp_pb2
    if flag:
        mark = list(localtime())
        if flag == 'since_minute':
            mark[5] = 0
        elif flag == 'since_hour':
            mark[4:6] = [0, 0]
        elif flag == 'since_day':
            mark[3:6] = [0, 0, 0]
        elif flag == 'since_weak':
            mark[2] -= mark[6]
            mark[3:8] = [0] * 5
        elif flag == 'since_month':
            mark[2:8] = [1] + [0] * 5
        elif flag == 'since_year':
            mark[1:8] = [1] * 2 + [0] * 5
        elif flag == 'minute':
            mark[4] -= 1
        elif flag == 'hour':
            mark[3] -= 1
        elif flag == 'day':
            mark[2] -= 1
        elif flag == 'weak':
            mark[2] -= 7
        elif flag == 'month':
            mark[1] -= 1
        elif flag == 'year':
            mark[1] -= 1
        seconds = int(mktime(tuple(mark)) - offset)
        seconds -= 10800
    else:
        seconds = int(time() - offset)
    timestamp = timestamp_pb2.Timestamp(seconds=seconds)
    return timestamp


def get_filter_with_timestamp(text_filter, start=None, end=None):
    text_filter = f'({text_filter})'
    if start:
        text_filter += f' AND timestamp >= {start}'
    if end:
        text_filter += f' AND timestamp <= {end}'
    return text_filter


def get_logs(log_group_id, function_id, text_filter, since=None, until=None):
    import yandexcloud
    from yandex.cloud.logging.v1.log_reading_service_pb2 import ReadRequest
    from yandex.cloud.logging.v1.log_reading_service_pb2 import Criteria
    from yandex.cloud.logging.v1.log_reading_service_pb2_grpc import LogReadingServiceStub

    cloud_logging_service = yandexcloud.SDK().client(LogReadingServiceStub)
    criteria = Criteria(
        log_group_id=log_group_id,
        resource_ids=[function_id],
        filter=text_filter,
        since=since,
        until=until
    )
    read_request = ReadRequest(criteria=criteria)
    logs = cloud_logging_service.Read(read_request)

    entries = []

    while logs.entries:
        entries.extend(list(logs.entries))
        read_request = ReadRequest(page_token=logs.previous_page_token)
        logs = cloud_logging_service.Read(read_request)

    return entries


def call(m, user, bot, session, *args, **kwargs):
    import os
    context = kwargs['context']

    text = Phrase.CREATING_STAT
    inline_kb = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton('Поддержать', callback_data='123'))
    creating = send_text(bot, m, text, inline_kb)

    text_filter = 'type_event EXISTS'
    since = get_timestamp(flag='since_day')
    until = get_timestamp()
    logs = get_logs(os.getenv('LOG_GROUP_ID'), context.function_name, text_filter, since=since, until=until)

    parts_text = create_stat_from_logs(logs)
    if len(parts_text) == 1:
        list_inline_btn = [('← Назад', 'users'), ('🏠 В меню', 'menu')]
        inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
        inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

        bot.edit_message_text(
            parts_text[0], creating.chat.id, creating.message_id,
            reply_markup=inline_kb if hasattr(m, 'message') else None, parse_mode='HTML'
        )
    else:
        del_messages = []
        first_mess = bot.edit_message_text(parts_text[0], creating.chat.id, creating.message_id, parse_mode='HTML')
        del_messages.append(str(first_mess.id))
        for text in parts_text[1:-1]:
            mess = send_text(bot, m, text, None, new_message=True, parse_mode='HTML')
            del_messages.append(str(mess.id))
        suffix = '$del' + ','.join(del_messages)
        if len(suffix) >= 58:
            suffix = suffix[:suffix.rindex(',', 0, 59)]

        list_inline_btn = [('← Назад', f'users{suffix}'), ('🏠 В меню', f'menu{suffix}')]
        inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
        inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

        send_text(bot, m, text, inline_kb if hasattr(m, 'message') else None, new_message=True, parse_mode='HTML')


def create_stat_text(count, users, commands, datas, levels, user_commands, user_datas, user_levels, date1=None,
                     date2=None):
    if date1 is None:
        from time import localtime, strftime
        date1 = strftime('%d.%m.%Y', localtime())
    if date2 is None:
        text = f'<b>Статистика за {date1}</b>'
    else:
        text = f'<b>Статистика за {date1}–{date2}</b>'

    text += f'\n\n<b>Общая статистика</b>\n\nВсего событий: {count}\nВсего пользователей: {len(users)}'
    sort_items = lambda d: sorted(d.items(), key=(lambda t: (-t[1], t[0])))

    if users:
        text += '\n\nПользователи:\n'
        text += '\n'.join([f'<code>{key}</code> – {value}' for key, value in sort_items(users)])

    if count:
        text += '\n\n<b>По событиям</b>'
    if commands:
        text += '\n\nИспользование команд:\n'
        text += '\n'.join([f'/{key} – {value}' for key, value in sort_items(commands)])
    if datas:
        text += '\n\nНажатие кнопок:\n'
        text += '\n'.join([f'<code>{key}</code> – {value}' for key, value in sort_items(datas)])
    if levels:
        text += '\n\nОтправка сообщений:\n'
        text += '\n'.join([f'<code>{key}</code> – {value}' for key, value in sort_items(levels)])

    if count:
        text += '\n\n<b>По пользователям</b>'
    if user_commands:
        text += '\n\nИспользование команд:\n'
        text += '\n'.join([f'<code>{key}</code> – {value}' for key, value in sort_items(user_commands)])
    if user_datas:
        text += '\n\nНажатие кнопок:\n'
        text += '\n'.join([f'<code>{key}</code> – {value}' for key, value in sort_items(user_datas)])
    if user_levels:
        text += '\n\nОтправка сообщений:\n'
        text += '\n'.join([f'<code>{key}</code> – {value}' for key, value in sort_items(user_levels)])

    parts = split_text(text)
    return parts


def split_text(text):
    parts = []
    while len(text) > 4096:
        ind = text[:4096].rfind('\n\n')
        if ind == -1:
            ind = 4096
        parts.append(text[:ind])
        text = text[ind + 1:].strip()
    parts.append(text)
    return parts
