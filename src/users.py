import ydb
from telebot import types

from constants import Phrase, months
from messenger_context import get_messenger_from_kwargs, get_users_table
from utils import send_text, edit_level


def get_user_photos(m, user, bot, session, *args, **kwargs):
    from re import search
    user_id = search(r'ID: (-?\d+)', m.message.text).group(1)

    photos = bot.get_user_profile_photos(user_id, limit=10)
    if photos.total_count == 0:
        text = 'У пользователя отсутствуют фотографии'
        send_text(bot, m, text, None, reply_to_message_id=m.message.id)
    else:
        media = [types.InputMediaPhoto(photo[-1].file_id) for photo in photos.photos]
        bot.send_media_group(m.message.chat.id, media, reply_to_message_id=m.message.id)


def about_user_cmd(m, user, bot, session, *args, **kwargs):
    user_id = m.text.lstrip('/user').strip()
    about_user(m, user, bot, session, *args, user_id=user_id, **kwargs)


def about_user(m, user, bot, session, *args, **kwargs):
    from re import match, IGNORECASE

    is_found_id = True

    if 'user_id' in kwargs:
        user_id = kwargs['user_id']
    else:
        user_id = m.text

    user_id = match(r'(id)?(-?\d+)', user_id, IGNORECASE)
    if user_id:
        user_id = user_id.group(2)
    else:
        is_found_id = False

    if is_found_id:
        try:
            user_info = bot.get_chat(user_id)
        except:
            if 'user_id' in kwargs:
                text = Phrase.CHAT_NOT_FOUND_CMD.format(u_id=f'<code>{user_id}</code>')
            else:
                text = Phrase.CHAT_NOT_FOUND.format(u_id=f'<code>{user_id}</code>')
            is_found_id = False
        else:
            admin, send_news, send_changes_tt = None, None, None
            if user_info.type == 'private':
                result = session.transaction().execute(
                    f'SELECT * FROM {get_users_table(get_messenger_from_kwargs(kwargs))} WHERE id = {user_id}',
                    commit_tx=True,
                    settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
                )

                if result[0].rows:
                    admin = result[0].rows[0]['admin']
                    send_news = result[0].rows[0]['send_news']
                    send_changes_tt = result[0].rows[0]['send_changes_tt']

            types_chat = {'private': 'пользователе', 'group': 'группе', 'supergroup': 'супергруппе',
                          'channel': 'канале'}
            text = f'<b>Информация о {types_chat[user_info.type]}</b>\n'

            birthdate = user_info.birthdate
            if birthdate:
                birthdate = f'{birthdate.day} {months[birthdate.month - 1]["dec"]}' + (
                    f' {birthdate.year} года' if birthdate.year else '')
            channel = user_info.personal_chat
            if channel:
                channel = f'<a href="https://t.me/{channel.username}">{channel.title}</a>'
            fields = {
                'ID': f'<code>{user_info.id}</code>' if user_info.has_private_forwards or user_info.type != 'private' else f'<a href="tg://user?id={user_info.id}">{user_info.id}</a>',
                'Название': user_info.title, 'Ник': '@' + user_info.username if user_info.username else None,
                'Имя': user_info.first_name, 'Фамилия': user_info.last_name,
                'День рождения': birthdate, 'Личный канал': channel,
                'О себе': user_info.bio, 'Описание': user_info.description,
                'Пригласительная ссылка': user_info.invite_link,
                '\nАдминистратор': admin, 'Подписка на рассылку новостей': send_news,
                'Подписка на рассылку изменений в расписании': send_changes_tt
            }

            for key, value in fields.items():
                if not value is None:
                    if type(value) is bool:
                        value = ['Нет', 'Да'][value]
                    text += f'\n{key}: {value}'

            edit_level(m, 'menu', session)
    else:
        if 'user_id' in kwargs:
            if m.text.strip() == '/user':
                text = Phrase.ID_SHOULD_BE_WRITTEN
            else:
                text = Phrase.NOT_ID_CHAT_CMD
        else:
            text = Phrase.NOT_ID_CHAT

    list_inline_btn = []
    if is_found_id:
        if user_info.type == 'private' and (count := bot.get_user_profile_photos(user_id).total_count):
            if count == 1:
                list_inline_btn = [('Фотография пользователя', 'userphoto$new')]
            else:
                list_inline_btn = [('Фотографии пользователя', 'userphoto$new')]

    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

    if not 'user_id' in kwargs:
        if is_found_id:
            list_inline_btn = [('← Назад', 'aboutuser'), ('🏠 В меню', 'menu')]
        else:
            list_inline_btn = [('← Назад', 'users'), ('🏠 В меню', 'menu')]
        inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
        inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb, parse_mode='HTML', disable_web_page_preview=True)


def user_id_for_about(m, user, bot, session, *args, **kwargs):
    text = Phrase.GET_CHAT_ID_FOR_ABOUT

    list_inline_btn = [('← Назад', 'users'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    edit_level(m, 'aboutuser', session)


def call(m, user, bot, session, *args, **kwargs):
    text = Phrase.SECTION_USERS
    list_inline_btn = [
        ('👤 О пользователе', 'aboutuser'), ('🧮 Количество пользователей', 'cntusers'),
        ('📊 Статистика', 'stat'), ('🏠 В меню', 'menu')
    ]
    if m.is_superadmin:
        list_inline_btn = [('✍ Написать пользователю', 'wuser'), ('📢 Рассылка', 'wusers')] + list_inline_btn
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    send_text(bot, m, text, inline_kb)

    if user['level'] != 'menu':
        edit_level(m, 'menu', session)


def count_users(m, user, bot, session, *args, **kwargs):
    result = session.transaction().execute(
        f'SELECT COUNT(*) AS count FROM {get_users_table(get_messenger_from_kwargs(kwargs))}',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    count = result[0].rows[0]['count']
    text = Phrase.COUNT_USERS.format(c_usrs=count)

    list_inline_btn = [('← Назад', 'users'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

    send_text(bot, m, text, inline_kb)
