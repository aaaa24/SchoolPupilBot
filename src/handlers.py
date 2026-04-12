from telebot import types

from constants import Phrase
from messenger_context import get_messenger_from_kwargs, get_nice_name_of_messenger_from_kwargs, get_users_table
from utils import create_inline_kb, send_text, edit_level


def cancel(m, user, bot, session, *args, **kwargs):
    bot.delete_message(m.message.chat.id, m.message.message_id)

    if '$del' in m.data:
        message_ids = m.data[m.data.index('$del') + 4:].split('$')[0].split(',')
        for message_id in message_ids:
            bot.delete_message(m.message.chat.id, message_id)

    if user['level'] != 'menu':
        edit_level(m, 'menu', session)


def info(m, user, bot, session, *args, **kwargs):
    text = Phrase.BOT_INFO.format(messenger=get_nice_name_of_messenger_from_kwargs(kwargs))

    inline_kb = types.InlineKeyboardMarkup()
    inline_kb.row(types.InlineKeyboardButton('💬 Обратная связь', callback_data='fback'))
    inline_kb.row(
        types.InlineKeyboardButton('🎓 Бот «Школьный тренер»', url='https://t.me/SchoolCoachBot?start=fromSchoolPupil'))
    inline_kb.row(types.InlineKeyboardButton('🏠 В меню', callback_data='menu'))

    send_text(bot, m, text, inline_kb)
    if user['level'] != 'menu':
        edit_level(m, 'menu', session)


def auth_user(m, user, bot, session, *args, **kwargs):
    import os

    list_inline_btn = [
        [('🗓 Расписание', 'tt'), ('🎓 Классы', 'cl')],
        ('📝 Изменения в расписании', 'chtt'),
        ('🔔 Подписка на новости', 'news'),
        ('👨‍🏫 Учителя', 'tea'),
        ('💳 Поддержать разработчика', 'pay'),
        ('ℹ️ Информация', 'inf')
    ]
    if m.from_user.id == int(os.getenv('SUPERADMIN')):
        list_inline_btn.append(('👥 Пользователи', 'users'))
    inline_kb = create_inline_kb(list_inline_btn)

    send_text(bot, m, Phrase.START.format(messenger=get_nice_name_of_messenger_from_kwargs(kwargs)), inline_kb)
    edit_level(m, 'menu', session)


def is_send_news(m, user, bot, session, *args, **kwargs):
    import ydb

    request = session.transaction().execute(
        f'UPSERT INTO {get_users_table(get_messenger_from_kwargs(kwargs))} (id, send_news) VALUES ({m.json["from"]["id"]}, {not user["send_news"]});',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )
    if hasattr(m, 'message'):
        m = m.message
    bot.send_message(m.chat.id, 'Подписка на новости школы включена' if not user[
        'send_news'] else 'Подписка на новости школы отключена')


def list_of_cmds(m, user, bot, session, *args, **kwargs):
    text = '''Список команд:
/commands – список команд;
/main – переход в главное меню;
/timetable – расписание уроков;
/classes – информация о классах;
/changes_tt – изменения в расписании;
/teachers – информация об учителях;
/teachers_schedule – расписание учителей;
/news – подписка на новости школы;
/feedback – обратная связь;
/info – информация о боте.'''

    bot.send_message(m.chat.id, text)


def to_menu(m, user, bot, session, *args, **kwargs):
    import os

    list_inline_btn = [
        [('🗓 Расписание', 'tt'), ('🎓 Классы', 'cl')],
        ('📝 Изменения в расписании', 'chtt'),
        ('🔔 Подписка на новости', 'news'),
        ('👨‍🏫 Учителя', 'tea'),
        ('💳 Поддержать разработчика', 'pay'),
        ('ℹ️ Информация', 'inf')
    ]
    if m.from_user.id == int(os.getenv('SUPERADMIN')):
        list_inline_btn.append(('👥 Пользователи', 'users'))
    inline_kb = create_inline_kb(list_inline_btn)

    send_text(bot, m, Phrase.MENU, inline_kb)
    if user['level'] != 'menu':
        edit_level(m, 'menu', session)
