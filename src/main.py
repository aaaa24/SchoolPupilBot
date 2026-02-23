from time import time

t0 = time()

import logging
from pythonjsonlogger import jsonlogger


class YcLoggingFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super(YcLoggingFormatter, self).add_fields(log_record, record, message_dict)
        log_record['level'] = str.replace(str.replace(record.levelname, "WARNING", "WARN"), "CRITICAL", "FATAL")


logHandler = logging.StreamHandler()
logHandler.setFormatter(YcLoggingFormatter('%(message)s %(level)s'))

logger = logging.getLogger('schoolpupil')
logger.propagate = False
logger.addHandler(logHandler)
logger.setLevel(logging.DEBUG)

logger.debug('Создан logger', extra={'time_since_launch': time() - t0})

t1 = time()

import os

from telebot import TeleBot
import ydb

import db
from messenger_context import get_users_table
from messengers import TelegramMessengerClient
from router import text_handling, callback_handling, commands, list_func, admin_commands

logger.debug('Завершён импорт', extra={'time_since_launch': time() - t0, 'duration': time() - t1})

t1 = time()
bot = TeleBot(os.getenv('BOT_TOKEN'))
telegram_client = TelegramMessengerClient(bot)

driver = db.create_driver()
driver.wait(fail_fast=True, timeout=5)

logger.debug('Созданы bot и driver', extra={'time_since_launch': time() - t0, 'duration': time() - t1})


def user_verif(m, session, messenger='telegram'):
    t1 = time()
    logger.debug('Запущена функция user_verif', extra={'time_since_launch': t1 - t0})

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

        if messenger == 'telegram':
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




def process_command_message(m, bot_instance, messenger='telegram'):
    session, number_attempts = set_connect(1000)
    if session is None:
        bot_instance.send_message(m.chat.id, 'Произошла какая-то ошибка. Отправьте команду заново')
        return

    user = user_verif(m, session, messenger=messenger)

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
        logger.debug('Запуск функции по команде', extra={'command': command, 'messenger': messenger})
        list_func[commands[command]](m, user, bot_instance, session, logger=logger, context=m.context, messenger=messenger)
        log_info['result'] = 'command'
    else:
        log_info['result'] = 'unknown_command'

    session.closing()
    logger.info('Ответ пользователю отправлен', extra={'type_event': 'command', 'info': log_info, 'messenger': messenger})


def process_text_message(m, bot_instance, messenger='telegram'):
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

    user = user_verif(m, session, messenger=messenger)

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
    process_command_message(m, bot, messenger='telegram')


@bot.message_handler(content_types=['text', 'photo'])
@event_decorator
def answer(m):
    process_text_message(m, bot, messenger='telegram')


@bot.callback_query_handler(func=lambda c: True)
@event_decorator
def callback_inline_btn(callback_query):
    session, number_attempts = set_connect(1000)
    if session is None:
        bot.answer_callback_query(callback_query.id, text='Ошибка. Нажмите кнопку ещё раз', show_alert=False)
        return

    bot.answer_callback_query(callback_query.id)
    user = user_verif(callback_query, session, messenger='telegram')

    callback_handling(callback_query, user, bot, session, logger=logger, context=callback_query.context, messenger='telegram')
    session.closing()
