from time import time

t0 = time()

import logging
import os

from pythonjsonlogger import jsonlogger


class YcLoggingFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super(YcLoggingFormatter, self).add_fields(log_record, record, message_dict)
        log_record['level'] = str.replace(str.replace(record.levelname, 'WARNING', 'WARN'), 'CRITICAL', 'FATAL')


class LocalLoggingFormatter(logging.Formatter):
    def format(self, record):
        timestamp = self.formatTime(record, self.datefmt)
        parts = [f'[{timestamp}]', f'[{record.levelname}]', record.getMessage()]

        default_keys = {
            'name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename', 'module',
            'exc_info', 'exc_text', 'stack_info', 'lineno', 'funcName', 'created', 'msecs',
            'relativeCreated', 'thread', 'threadName', 'processName', 'process', 'message',
            'asctime', 'taskName'
        }
        extra_fields = {
            key: value for key, value in record.__dict__.items()
            if key not in default_keys and not key.startswith('_')
        }
        if extra_fields:
            parts.append(f'extra={extra_fields}')

        if record.exc_info:
            parts.append(self.formatException(record.exc_info))

        return ' '.join(parts)


def get_logging_mode():
    mode = os.getenv('LOG_MODE', 'cloud')
    if mode not in ('cloud', 'local'):
        raise ValueError('Unknown LOG_MODE')
    return mode


def build_log_formatter(logging_mode):
    if logging_mode == 'local':
        return LocalLoggingFormatter(datefmt='%Y-%m-%d %H:%M:%S')

    return YcLoggingFormatter('%(message)s %(level)s', json_ensure_ascii=False)


logHandler = logging.StreamHandler()
logging_mode = get_logging_mode()
logHandler.setFormatter(build_log_formatter(logging_mode))

logger = logging.getLogger('schoolpupil')
logger.propagate = False
logger.addHandler(logHandler)
logger.setLevel(logging.DEBUG)

logger.debug('Создан logger', extra={'time_since_launch': time() - t0, 'log_mode': logging_mode})

t1 = time()

from telebot import TeleBot
import ydb

import db
from messenger_context import get_users_table
from messengers import Messenger, TelegramMessengerClient
from router import text_handling, callback_handling, commands, list_func, admin_commands

logger.debug('Завершён импорт', extra={'time_since_launch': time() - t0, 'duration': time() - t1})

t1 = time()
bot = TeleBot(os.getenv('TELEGRAM_BOT_TOKEN'))
telegram_client = TelegramMessengerClient(bot)

driver = db.create_driver()
driver.wait(fail_fast=True, timeout=5)

logger.debug('Созданы bot и driver', extra={'time_since_launch': time() - t0, 'duration': time() - t1})


def user_verif(m, session):
    t1 = time()
    logger.debug('Запущена функция user_verif', extra={'time_since_launch': t1 - t0})

    messenger = m.messenger
    user = m.json['from']
    users_table = get_users_table(messenger)
    result = session.transaction().execute(
        f'SELECT * FROM {users_table} WHERE id = {user["id"]};',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    if result[0].rows == []:
        request = session.transaction().execute(
            f'UPSERT INTO {users_table} (id, level, admin, send_news, send_changes_tt) VALUES ({user["id"]}, "menu", False, False, False);',
            commit_tx=True,
            settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
        )
        text = f'Новый пользователь\nID: <code>{user["id"]}</code>\nИмя: {user["first_name"]}' + \
               (f'\nФамилия: {user["last_name"]}' if 'last_name' in user else '') + \
               (f'\nНик: {"@" if user["username"] else ""}{user["username"]}' if 'username' in user else '')
        from_ = None
        if hasattr(m, 'text') and m.text.startswith('/start'):
            if 'fromSchoolCoach' in m.text.split():
                text += '\n\nПереход из бота «Школьный тренер»'
                from_ = 'fromSchoolCoach'
            if 'fromSchoolQR' in m.text.split():
                text += '\n\nПереход с QR-кода в школе'
                from_ = 'fromSchoolQR'

        if messenger is Messenger.TELEGRAM:
            user_info = bot.get_chat(user['id'])
            user_id = f'<code>{user_info.id}</code>' if user_info.has_private_forwards else f'<a href="tg://user?id={user_info.id}">{user_info.id}</a>'
            text = text.replace(f'<code>{user["id"]}</code>', user_id)
            bot.send_message(int(os.getenv('TECHNO_INFO')), text, parse_mode='HTML', disable_notification=True)

        result = {'admin': False, 'id': user['id'], 'level': 'menu', 'send_news': False, 'send_changes_tt': False}
        new_user = {
            'id': user['id'], 'first_name': user['first_name'],
            'last_name': user['last_name'] if 'last_name' in user else None,
            'username': user['username'] if 'username' in user else None,
            'from': from_
        }
        logger.info('Новый пользователь', extra={'user': new_user})

    else:
        result = dict(result[0].rows[0])

    logger.info('Получена информация о пользователе', extra={'user': result})
    logger.debug('Завершена функция user_verif', extra={'time_since_launch': time() - t0, 'duration': time() - t1})
    return result


def set_connect(max_number_attempts):
    number_attempts = 0
    while True:
        try:
            session = driver.table_client.session().create()
        except ydb.issues.ConnectionLost as e:
            number_attempts += 1
            if number_attempts == max_number_attempts:
                logger.warning('Ошибка в подключении к базе данных', extra={'number_attempts': number_attempts})
                return (None, number_attempts)
        else:
            logger.debug('Выполнено подключение к базе данных', extra={'number_attempts': number_attempts})
            return (session, number_attempts)


def process_max_callback(max_message, max_client):
    session, number_attempts = set_connect(1000)
    if session is None:
        max_client.answer_callback_query(max_message.id, notification='Ошибка. Нажмите кнопку ещё раз')
        return

    max_client.begin_callback(max_message.id, max_message.message.reply_markup)
    user = user_verif(max_message, session)
    callback_handling(max_message, user, max_client, session, logger=logger,
                      context=max_message.context, messenger=max_message.messenger)
    max_client.answer_callback_query(max_message.id)
    session.closing()


def process_command_message(m, bot_instance):
    session, number_attempts = set_connect(1000)
    if session is None:
        bot_instance.send_message(m.chat.id, 'Произошла какая-то ошибка. Отправьте команду заново')
        return

    messenger = m.messenger
    user = user_verif(m, session)

    command = None
    if hasattr(m, 'entities') and m.entities:
        for entity in m.entities:
            if entity.type == 'bot_command':
                command = m.text[entity.offset + 1:entity.length]
                break
    elif hasattr(m, 'text') and isinstance(m.text, str) and m.text.startswith('/'):
        command = m.text.split()[0][1:].split('@')[0]

    log_info = {
        'user_id': m.from_user.id, 'level': user['level'],
        'text': m.text,
        'command': command, 'result': None
    }

    if command in admin_commands and not user['admin']:
        bot_instance.send_message(m.chat.id, 'К сожалению, эта команда только для администраторов...')
        log_info['result'] = 'only_for_admins'
    elif command in commands:
        logger.debug('Запуск функции по команде', extra={'command': command, 'messenger': messenger.value})
        list_func[commands[command]](m, user, bot_instance, session, logger=logger, context=m.context,
                                     messenger=messenger)
        log_info['result'] = 'command'
    else:
        log_info['result'] = 'unknown_command'

    session.closing()
    logger.info('Ответ пользователю отправлен',
                extra={'type_event': 'command', 'info': log_info, 'messenger': messenger.value})


def process_text_message(m, bot_instance):
    if m.text is None:
        if not m.caption is None:
            m.text = m.caption
            m.is_edit_text = True
        else:
            m.text = ''
            m.is_edit_text = False
    else:
        m.is_edit_text = False

    session, number_attempts = set_connect(1000)
    if session is None:
        bot_instance.send_message(m.chat.id, 'Произошла какая-то ошибка. Отправьте сообщение заново')
        return

    messenger = m.messenger
    user = user_verif(m, session)

    text_handling(m, user, bot_instance, session, logger=logger, context=m.context, messenger=messenger)
    session.closing()


def event_decorator(func):
    def event(m):
        t1 = time()
        logger.debug(f'Запущена функция {func.__name__}', extra={'time_since_launch': t1 - t0})
        try:
            if hasattr(m, 'chat') and m.chat.type != 'private' and m.chat.id != int(os.getenv('TECHNO_INFO')) or \
                    hasattr(m, 'message') and m.message.chat.type != 'private' and m.message.chat.id != int(
                os.getenv('TECHNO_INFO')):
                logger.debug('Событие не обрабатывается')
                logger.debug(
                    f'Завершена функция {func.__name__}',
                    extra={'time_since_launch': time() - t0, 'duration': time() - t1}
                )
            else:
                func(m)
        except:
            import traceback
            logger.error(traceback.format_exc().replace('\n', '\r'))

        logger.debug(
            f'Завершена функция {func.__name__}',
            extra={'time_since_launch': time() - t0, 'duration': time() - t1}
        )

    return event


@bot.message_handler(commands=['id', 'ID', 'Id', 'iD'])
@event_decorator
def my_id(m):
    logger.info(f'ID пользователя {m.from_user.id}')
    bot.reply_to(m, f'Ваш ID: `{m.from_user.id}`', parse_mode='MarkdownV2')


@bot.message_handler(commands=list(commands.keys()))
@event_decorator
def cmd(m):
    process_command_message(m, bot)


@bot.message_handler(content_types=['text', 'photo'])
@event_decorator
def answer(m):
    process_text_message(m, bot)


@bot.callback_query_handler(func=lambda c: True)
@event_decorator
def callback_inline_btn(callback_query):
    session, number_attempts = set_connect(1000)
    if session is None:
        bot.answer_callback_query(callback_query.id, text='Ошибка. Нажмите кнопку ещё раз', show_alert=False)
        return

    bot.answer_callback_query(callback_query.id)
    user = user_verif(callback_query, session)

    callback_handling(callback_query, user, bot, session, logger=logger, context=callback_query.context,
                      messenger=callback_query.messenger)
    session.closing()
