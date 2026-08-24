import time

from telebot import types, apihelper

from messenger_context import get_messenger_from_m, get_users_table
from messengers import ScreenState, force_new_screen


def get_inline_button(button):
    if len(button) == 3 and button[2] == 'url':
        return types.InlineKeyboardButton(button[0], url=button[1])
    else:
        return types.InlineKeyboardButton(button[0], callback_data=button[1])


def create_inline_kb(list_inline_btn, row_width=3):
    inline_kb = types.InlineKeyboardMarkup(row_width=row_width)
    for row in list_inline_btn:
        if type(row) is list:
            inline_kb.row(*[get_inline_button(button) for button in row])
        elif type(row) is tuple:
            inline_kb.row(get_inline_button(row))
    return inline_kb


def except_429(f, n=1, **k):
    if n == 5:
        try:
            eval(f)
        except:
            print('Всё плохо')
            return False
        else:
            return True
    try:
        eval(f)
    except apihelper.ApiTelegramException as e:
        print(n, e)
        if 'Error code: 429' in str(e):
            time.sleep(4)
            except_429(f, n + 1, **k)


def find_callback_data(message, text):
    data = None
    keyboard = message.reply_markup.keyboard
    for row in keyboard:
        for btn in row:
            if text in btn.text:
                data = btn.callback_data
                break
        else:
            continue
        break
    return data


def send_text(bot, m, text, inline_kb, new_message=False, **kwargs):
    if hasattr(m, 'message'):
        suffixes(bot, m, text, inline_kb, **kwargs)
        force_new = force_new_screen(m.data) or new_message
        if m.message.content_type == 'text' and not force_new:
            return bot.edit_message_text(text, m.message.chat.id, m.message.id, reply_markup=inline_kb, **kwargs)
        if not kwargs and hasattr(bot, 'render_screen'):
            state = ScreenState(chat_id=m.message.chat.id, message_id=m.message.id, content_type=m.message.content_type)
            return bot.render_screen(state, text, [], reply_markup=inline_kb, force_new=force_new)
        m = m.message

    return bot.send_message(m.chat.id, text, reply_markup=inline_kb, **kwargs)


def edit_level(m, level, session):
    import ydb
    messenger = get_messenger_from_m(m)
    if hasattr(m, 'from_user'):
        user_id = m.from_user.id
    else:
        if m.json['from']['is_bot']:
            user_id = m.json['chat']['id']
        else:
            user_id = m.json['from']['id']
    if user_id < 0:
        return False
    users_table = get_users_table(messenger)
    request = session.transaction().execute(
        f'UPSERT INTO {users_table} (id, level) VALUES ({user_id}, "{level}");',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )
    return True


def suffixes(bot, m, text, inline_kb, **kwargs):
    if '$del' in m.data:
        message_ids = m.data[m.data.index('$del') + 4:].split('$')[0].split(',')
        for message_id in message_ids:
            bot.delete_message(m.message.chat.id, message_id)
    if '$sdel' in m.data:
        bot.delete_message(m.message.chat.id, m.message.message_id)
