from telebot import types
from var import Phrase
from funcs import send_text, edit_level


def last_user(m, user, bot, session, *args, **kwargs):
    import re
    user_id = re.match(r'(id)?(\d+)', m.text, re.IGNORECASE)
    if user_id:
        user_id = user_id.group(2)
        text = Phrase.YES_ID_LAST_USER.format(u_id=f'<code>{user_id}</code>')

        inline_buttons = [b[0] for b in m.reply_to_message.reply_markup.keyboard[:-5]]
        inline_buttons.append(types.InlineKeyboardButton(m.reply_to_message.reply_markup.keyboard[-5][0].text,
                                                         callback_data=f'swusers_{user_id}$sdel'))
        inline_buttons.append(types.InlineKeyboardButton(m.reply_to_message.reply_markup.keyboard[-4][0].text,
                                                         callback_data=f'swadms_{user_id}$sdel'))
        inline_buttons += [b[0] for b in m.reply_to_message.reply_markup.keyboard[-3:]]
        inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

        bot.edit_message_reply_markup(chat_id=m.reply_to_message.chat.id, message_id=m.reply_to_message.message_id,
                                      reply_markup=inline_kb)
    else:
        text = Phrase.NOT_ID_LAST_USER

    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(
        types.InlineKeyboardButton('❌ Скрыть сообщение', callback_data=f'cncl$del{m.message_id}'))
    send_text(bot, m, text, inline_kb, reply_to_message_id=m.message_id, parse_mode='HTML')


def mailing(m, user, bot, session, *args, **kwargs):
    users = kwargs['users']
    btns = [b[0] for b in m.message.reply_markup.keyboard[:-6]]
    count = 0

    list_inline_btn = [('Новое сообщение', 'wusers$new'), ('Поддержать', '123'), ('🏠 В меню', 'menu$new')]
    inline_buttons_admin = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb_admin = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons_admin)

    print('Рассылка начата. Количество получателей:', len(users))
    text = Phrase.START_MAILING.format(text=f'0/{len(users)}')
    info_mailing = send_text(bot, m, text, inline_kb_admin, reply_to_message_id=m.message.reply_to_message.message_id)

    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*btns)

    if m.message.reply_to_message.content_type == 'text':
        text_users = m.message.reply_to_message.text
    elif m.message.reply_to_message.content_type == 'photo':
        caption = m.message.reply_to_message.caption
        photo = m.message.reply_to_message.photo[-1].file_id

    for user_id in users:
        try:
            if m.message.reply_to_message.content_type == 'text':
                bot.send_message(user_id, text_users, reply_markup=inline_kb)
            elif m.message.reply_to_message.content_type == 'photo':
                bot.send_photo(user_id, caption=caption, photo=photo, reply_markup=inline_kb)
        except:
            import traceback
            traceback.print_exc()
        else:
            count += 1
            text = Phrase.START_MAILING.format(
                text=f'{count}/{len(users)}. Последний пользователь с ID <code>{user_id}</code>')
            bot.edit_message_text(text, info_mailing.chat.id, info_mailing.message_id,
                                  reply_markup=inline_kb_admin, parse_mode='HTML')

    list_inline_btn = [('Новое сообщение', 'wusers$new'), ('🏠 В меню', 'menu$new')]
    inline_buttons_admin = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb_admin = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons_admin)

    print(f'Рассылка завершена. Количество пользователей, получивших сообщение: {count}/{len(users)}')
    text = Phrase.END_MAILING.format(text=f'{count}/{len(users)}')
    bot.edit_message_text(text, info_mailing.chat.id, info_mailing.message_id, reply_markup=inline_kb_admin)


def get_users(m, user, bot, session, *args, **kwargs):
    import ydb
    request = kwargs['request']
    result = session.transaction().execute(
        request,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )
    users = [u['id'] for u in result[0].rows]

    return users


def send_message_to_admins(m, user, bot, session, *args, **kwargs):
    user_id = m.data.split('$')[0].split('_')[1]
    batch_size = 500
    i = 0
    users = []
    while True:
        request = f'SELECT id FROM users WHERE admin = true AND id > {user_id} LIMIT {batch_size} OFFSET {i};'
        new_users = get_users(m, user, bot, session, *args, request=request, **kwargs)
        if not new_users:
            break
        users.extend(new_users)
        i += batch_size
    mailing(m, user, bot, session, *args, users=users, **kwargs)


def send_message_to_users(m, user, bot, session, *args, **kwargs):
    user_id = m.data.split('$')[0].split('_')[1]
    batch_size = 500
    i = 0
    users = []
    while True:
        request = f'SELECT id FROM users WHERE id > {user_id} LIMIT {batch_size} OFFSET {i};'
        new_users = get_users(m, user, bot, session, *args, request=request, **kwargs)
        if not new_users:
            break
        users.extend(new_users)
        i += batch_size
    mailing(m, user, bot, session, *args, users=users, **kwargs)


def reask_btns_to_users(m, user, bot, session, *args, **kwargs):
    message_id = m.data.split('$')[0].split('_')[1]
    callback_data = f'wusers_{message_id}$sdel'
    back = 'wusers'
    ask_btns(m, user, bot, session, *args, callback_data=callback_data, back=back, **kwargs)


def get_attachable_buttons(message):
    from var import attachable_buttons

    btns = []
    result_btns = []
    keyboard = message.reply_markup.keyboard
    for row in keyboard:
        for btn in row:
            if 'chbtn' in btn.callback_data and btn.callback_data.split('_')[1] != '0':
                btns.append((btn.text, btn.callback_data))

    btns.sort(key=lambda b: int(b[1].split('_')[1]))

    for btn in btns:
        text_btn = btn[0][btn[0].index(' ') + 1:]
        callback_data = '_'.join(btn[1].split('_')[2:]) + '$new'
        for attachable_button in attachable_buttons:
            if text_btn in attachable_button[0]:
                text_btn = attachable_button[0]
                break
        result_btns.append((text_btn, callback_data))
    return result_btns


def confirmation_message_to_users(m, user, bot, session, *args, **kwargs):
    # Подтверждение отправки рассылки пользователям
    message_id = m.data.split('$')[0].split('_')[1]

    btns = get_attachable_buttons(m.message)

    text = Phrase.CONFIRMATION_MESSAGE_TO_USERS.format(text='')

    list_inline_btn = btns
    if btns:
        if len(btns) == 1:
            list_inline_btn += [('☝️ К сообщению будет прикреплена кнопка', '123')]
        else:
            list_inline_btn += [('☝️ К сообщению будут прикреплены кнопки', '123')]
    list_inline_btn += [
        ('Отправить всем пользователям', f'swusers_0$sdel'),
        ('Отправить только администраторам', f'swadms_0$sdel'),
        ('Изменить сообщение', 'wusers$sdel'), ('Изменить кнопки', f'rwusers_{message_id}$sdel'),
        ('🏠 В меню', 'menu$sdel')
    ]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    send_text(bot, m, text, inline_kb, reply_to_message_id=message_id, parse_mode='HTML')


def add_button(m, user, bot, session, *args, **kwargs):
    from funcs import list_funcs_callback

    split_text = m.text.split('\n')
    if len(split_text) < 2 or not split_text[1].split('_')[0] in list_funcs_callback:
        text = Phrase.NO_ADD_BTN
    else:
        text_btn = m.text.split('\n')[0]
        callback_data = m.text.split('\n')[1]

        inline_buttons = [b[0] for b in m.reply_to_message.reply_markup.keyboard[:-2]]
        inline_buttons.append(types.InlineKeyboardButton('❌ ' + text_btn, callback_data='chbtn_0_' + callback_data))
        inline_buttons.append(m.reply_to_message.reply_markup.keyboard[-2][0])
        inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)
        inline_buttons = m.reply_to_message.reply_markup.keyboard[-1]
        inline_kb.row(*inline_buttons)

        bot.edit_message_reply_markup(chat_id=m.reply_to_message.chat.id, message_id=m.reply_to_message.message_id,
                                      reply_markup=inline_kb)

        text = Phrase.YES_ADD_BTN.format(text=f'<i>«{text_btn}»</i> с командой <i>{callback_data}</i>')

    list_inline_btn = [(text_btn, callback_data + '$new'), ('❌ Скрыть сообщение', f'cncl$del{m.message_id}')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    send_text(bot, m, text, inline_kb, reply_to_message_id=m.message_id, parse_mode='HTML')


def choose_btn(m, user, bot, session, *args, **kwargs):
    def make_number(number):
        digits = ('0️⃣', '1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣')
        for i in range(10):
            number = number.replace(str(i), digits[i])
        return number

    split_data = m.data.split('_')
    btns = [[b[0].text, b[0].callback_data.split('_')] for b in m.message.reply_markup.keyboard[:-2]]
    text_btn = [b[0] for b in btns if b[1] == split_data][0]
    number_data = btns.index([text_btn, split_data])
    if split_data[1] == '0':
        max_btn = max(btns, key=lambda b: int(b[1][1]))
        number = str(int(max_btn[1][1]) + 1)
        btns[number_data][0] = f'{make_number(number)} {text_btn[2:]}'
        btns[number_data][1][1] = number
    else:
        for btn in btns:
            if int(btn[1][1]) > int(split_data[1]):
                number = str(int(btn[1][1]) - 1)
                btn[0] = make_number(number) + btn[0][btn[0].index(' '):]
                btn[1][1] = number
        btns[number_data][0] = '❌' + text_btn[text_btn.index(' '):]
        btns[number_data][1][1] = '0'

    btns = [(b[0], '_'.join(b[1])) for b in btns]

    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in btns]
    inline_buttons.append(m.message.reply_markup.keyboard[-2][0])
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    inline_buttons = m.message.reply_markup.keyboard[-1]
    inline_kb.row(*inline_buttons)

    bot.edit_message_reply_markup(chat_id=m.message.chat.id, message_id=m.message.message_id, reply_markup=inline_kb)


def ask_btns(m, user, bot, session, *args, **kwargs):
    from var import attachable_buttons

    callback_data, back = kwargs['callback_data'], kwargs['back']
    text = Phrase.ASK_BTNS

    chars = 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ1234567890 '

    list_inline_btn = [('❌ ' + (''.join(filter((lambda c: c.upper() in chars), b[0]))).strip(), 'chbtn_0_' + b[1]) for b
                       in attachable_buttons]
    list_inline_btn.append(('✅ Готово', callback_data))
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    list_inline_btn = [('← Назад', back), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    edit_level(m, 'menu', session)


def ask_btns_to_users(m, user, bot, session, *args, **kwargs):
    callback_data = f'wusers_{m.message_id}$sdel'
    back = 'wusers'
    ask_btns(m, user, bot, session, *args, callback_data=callback_data, back=back, **kwargs)


def ask_text_to_users(m, user, bot, session, *args, **kwargs):
    # Просьба ввести сообщение для пользователей

    text = Phrase.ASK_MESSAGE_TO_USERS
    list_inline_btn = [('← Назад', 'users'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    edit_level(m, 'wusers', session)


def reply_to_answer(m, user, bot, session, *args, **kwargs):
    # Обработка ответа на ответ админа
    user_id, message_id, reply_id = get_info_for_reply_to_message(m)
    if args:
        kwargs['text'] = args[0]
    answer_to_afback(m, user, bot, session, user_id, message_id, reply_id, **kwargs)


def reply_to_feedback(m, user, bot, session, *args, **kwargs):
    # Обработка ответа на отзыв пользователя
    user_id, message_id, reply_id = get_info_for_reply_to_message(m)
    if args:
        kwargs['id'] = args[0]
    confirmation_answer_to_user(m, user, bot, session, user_id, message_id, reply_id, **kwargs)


def get_info_for_reply_to_message(m):
    # Добыча информации из кнопки «Ответить»
    from funcs import find_callback_data
    data = find_callback_data(m.reply_to_message, 'Ответить')
    split_data = data.split('$')[0].split('_')
    if len(split_data) > 3:
        user_id, message_id, reply_id = split_data[1:4]
    else:
        user_id, message_id = split_data[1:3]
        reply_id = m.reply_to_message.message_id

    return user_id, message_id, reply_id


def another_message_to_user(m, user, bot, session, *args, **kwargs):
    # Изменения сообщения для пользователя с заданным id
    user_id = m.data.split('$')[0].split('_')[1]
    kwargs['user_id'] = user_id
    ask_text_to_write(m, user, bot, session, *args, **kwargs)


def write_to_user(m, user, bot, session, *args, **kwargs):
    # Отправка пользователю сообщения
    from var import dict_re
    from re import match

    btns = [b[0] for b in m.message.reply_markup.keyboard[:-6]]
    user_id = m.data.split('$')[0].split('_')[1]

    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*btns)

    try:
        if m.message.reply_to_message.content_type == 'text':
            bot.send_message(user_id, m.message.reply_to_message.text, reply_markup=inline_kb)
        elif m.message.reply_to_message.content_type == 'photo':
            bot.send_photo(user_id, caption=m.message.reply_to_message.caption,
                           photo=m.message.reply_to_message.photo[-1].file_id, reply_markup=inline_kb)
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        print(trace)
        if 'chat not found' in trace:
            text = Phrase.USER_NOT_FOUND.format(u_id=f'<code>{user_id}</code>')
        elif 'bot was blocked by the user' in trace:
            text = Phrase.BOT_WAS_BLOCKED.format(u_id=f'<code>{user_id}</code>')
        else:
            text = Phrase.ERROR
        list_inline_btn = [('Начать заново', 'wuser$new')]
    else:
        text = Phrase.YES_SEND_MESSAGE_TO_USER
        list_inline_btn = [('Другое сообщение', f'wuser_{user_id}$new'), ('Начать заново', 'wuser$new')]

    list_inline_btn.append(('🏠 В меню', 'menu$new'))
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    send_text(bot, m, text, inline_kb, parse_mode='HTML', reply_to_message_id=m.message.reply_to_message.message_id)


def confirmation_message(m, user, bot, session, *args, **kwargs):
    # Подтверждение отправки пользователю сообщения
    user_id, message_id = m.data.split('$')[0].split('_')[1:3]

    btns = get_attachable_buttons(m.message)
    text = Phrase.CONFIRMATION_OF_SEND_MESSAGE_TO_USER.format(u_id=f'<code>{user_id}</code>')
    list_inline_btn = btns

    if btns:
        if len(btns) == 1:
            list_inline_btn += [('☝️ К сообщению будет прикреплена кнопка', '123')]
        else:
            list_inline_btn += [('☝️ К сообщению будут прикреплены кнопки', '123')]
    list_inline_btn += [
        ('Отправить', f'swuser_{user_id}$sdel'),
        ('Изменить сообщение', f'wuser_{user_id}$sdel'),
        ('Изменить кнопки', f'rwuser_{user_id}_{message_id}$sdel'),
        ('Начать заново', 'wuser$sdel'),
        ('🏠 В меню', 'menu$sdel')
    ]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    send_text(bot, m, text, inline_kb, reply_to_message_id=message_id, parse_mode='HTML')


def reask_btns_to_user(m, user, bot, session, *args, **kwargs):
    user_id, message_id = m.data.split('$')[0].split('_')[1:3]
    callback_data = f'wuser_{user_id}_{message_id}$sdel'
    back = f'wuser_{user_id}'
    ask_btns(m, user, bot, session, *args, callback_data=callback_data, back=back, **kwargs)


def ask_btns_to_user(m, user, bot, session, *args, **kwargs):
    user_id = args[0]
    callback_data = f'wuser_{user_id}_{m.message_id}$sdel'
    back = f'wuser_{user_id}'
    ask_btns(m, user, bot, session, *args, callback_data=callback_data, back=back, **kwargs)


def ask_text_to_write(m, user, bot, session, *args, **kwargs):
    # Обработка введённого id и просьба ввести сообщение для пользователя
    from re import match, IGNORECASE

    is_found_id = True

    if 'user_id' in kwargs:
        user_id = kwargs['user_id']
    else:
        user_id = match(r'(id)?(\d+)', m.text, IGNORECASE)
        if user_id:
            user_id = user_id.group(2)
        else:
            is_found_id = False

    if is_found_id:
        try:
            bot.get_chat(user_id)
        except:
            text = Phrase.USER_NOT_FOUND.format(u_id=f'<code>{user_id}</code>')
            list_inline_btn = [('← Назад', 'users'), ('🏠 В меню', 'menu')]
        else:
            text = Phrase.TEXT_TO_WRITE.format(u_id=f'<code>{user_id}</code>')
            list_inline_btn = [('← Назад', 'wuser'), ('🏠 В меню', 'menu')]
            edit_level(m, f'wuser_{user_id}', session)
    else:
        text = Phrase.NOT_ID_USER
        list_inline_btn = [('← Назад', 'users'), ('🏠 В меню', 'menu')]

    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

    send_text(bot, m, text, inline_kb, parse_mode='HTML')


def ask_id_to_write(m, user, bot, session, *args, **kwargs):
    # Просьба админу ввести id пользователя, чтобы отправить тому сообщение

    text = Phrase.ASK_ID_TO_WRITE

    list_inline_btn = [('← Назад', 'users'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    edit_level(m, 'wuser', session)


def answer_to_afback(m, user, bot, session, *args, **kwargs):
    # Обработка ответа пользователя на ответ админа

    user_id, message_id, reply_id = args[:3]
    text_admin = Phrase.ANSWER_FROM_USER.format(u_id=f'<code>{m.json["from"]["id"]}</code>')
    inline_kb_admin = types.InlineKeyboardMarkup().row(
        types.InlineKeyboardButton('✍ Ответить', callback_data=f'afback_{m.chat.id}_{m.message_id}$new'))
    bot.forward_message(user_id, m.chat.id, m.message_id)
    bot.send_message(user_id, text_admin, reply_markup=inline_kb_admin, parse_mode='HTML',
                     reply_to_message_id=message_id)

    text_user = Phrase.ACCEPT_FEEDBACK
    list_inline_btn = [('✍ Ответить ещё', f'ans_{user_id}_{message_id}_{reply_id}'), ('🔄 Новое сообщение', 'fback'),
                       ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb_user = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)
    send_text(bot, m, text_user, inline_kb_user)

    edit_level(m, 'menu', session)


def get_answer_to_afback(m, user, bot, session, *args, **kwargs):
    # Предложение пользователю ответить на ответ админа

    split_data = m.data.split('$')[0].split('_')
    if len(split_data) > 3:
        user_id, message_id, reply_id = split_data[1:4]
    else:
        user_id, message_id = split_data[1:3]
        reply_id = m.message.message_id
    text = Phrase.ASK_ANSWER_TO_AFBACK
    list_inline_btn = [('← Назад', 'inf$new'), ('🏠 В меню', 'menu$new')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

    edit_level(m, f'ans_{user_id}_{message_id}_{reply_id}', session)
    if hasattr(m, 'message'):
        m = m.message
    bot.send_message(m.chat.id, text, reply_to_message_id=reply_id, reply_markup=inline_kb)


def answer_to_feedback(m, user, bot, session, *args, **kwargs):
    # Обработка ответа админа на сообщение пользователя

    user_id, message_id = m.data.split('$')[0].split('_')[1:3]
    text = m.message.reply_to_message.text
    chat = m.message.chat.id
    reply_id = m.message.reply_to_message.message_id

    text_user = Phrase.ANSWER_RECEIVED.format(text=f'<blockquote>{text}</blockquote>')

    list_inline_btn = [('✍ Ответить', f'ans_{chat}_{reply_id}'), ('🔄 Новое сообщение', 'fback$new'),
                       ('🏠 В меню', 'menu$new')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb_user = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)
    bot.send_message(user_id, text_user, reply_to_message_id=message_id, reply_markup=inline_kb_user, parse_mode='HTML')

    text_admin = Phrase.ACCEPT_ANSWER_TO_FEEDBACK
    send_text(bot, m, text_admin, None)


def confirmation_answer_to_user(m, user, bot, session, *args, **kwargs):
    # Подтверждение отправки ответа на сообщение пользователя
    user_id, message_id, reply_id = args[:3]

    text = Phrase.CONFIRMATION_OF_SEND_ANSWER_TO_USER.format(u_id=f'<code>{user_id}</code>')

    list_inline_btn = [('Отправить', f'safback_{user_id}_{message_id}$sdel'),
                       ('Изменить текст', f'afback_{user_id}_{message_id}_{reply_id}$sdel'), ('❌ Отменить', 'cncl')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    send_text(bot, m, text, inline_kb, reply_to_message_id=m.message_id, parse_mode='HTML')
    edit_level(m, 'menu', session)


def get_answer_to_feedback(m, user, bot, session, *args, **kwargs):
    # Предложение админу написать ответ на сообщение пользователя

    split_data = m.data.split('$')[0].split('_')
    if len(split_data) > 3:
        user_id, message_id, reply_id = split_data[1:4]
    else:
        user_id, message_id = split_data[1:3]
        reply_id = m.message.message_id

    text = Phrase.ASK_ANSWER_TO_FEEDBACK
    inline_kb = types.InlineKeyboardMarkup().row(types.InlineKeyboardButton('❌ Отменить', callback_data='cncl'))

    send_text(bot, m, text, inline_kb, reply_to_message_id=reply_id, parse_mode='HTML')
    edit_level(m, f'afback_{user_id}_{message_id}_{reply_id}', session)


def accept_feedback(m, user, bot, session, *args, **kwargs):
    # Обработка первого сообщения от пользователя
    import os

    text_admin = Phrase.MESSAGE_FROM_USER.format(
        text=f'ID: <code>{m.json["from"]["id"]}</code>\nИмя: {m.json["from"]["first_name"]}' + \
             (f'\nФамилия: {m.json["from"]["last_name"]}' if 'last_name' in m.json['from'] else '') + \
             (f'\nНик: {"@" if m.json["from"]["username"] else ""}{m.json["from"]["username"]}' if 'username' in m.json[
                 'from'] else '')
    )
    inline_kb_admin = types.InlineKeyboardMarkup().row(
        types.InlineKeyboardButton('✍ Ответить', callback_data=f'afback_{m.chat.id}_{m.message_id}$new'))
    bot.forward_message(os.getenv('TECHNO_INFO'), m.chat.id, m.message_id)
    bot.send_message(os.getenv('TECHNO_INFO'), text_admin, reply_markup=inline_kb_admin, parse_mode='HTML')

    text_user = Phrase.ACCEPT_FEEDBACK
    inline_kb_user = types.InlineKeyboardMarkup().row(
        types.InlineKeyboardButton('✍ Написать ещё', callback_data='fback'))
    list_inline_btn = [('← Назад', 'inf'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb_user.row(*inline_buttons)
    send_text(bot, m, text_user, inline_kb_user)

    edit_level(m, 'menu', session)


def ask_feedback(m, user, bot, session, *args, **kwargs):
    # Предложение пользователю написать отзыв

    text = Phrase.ASK_FEEDBACK
    list_inline_btn = [('← Назад', 'inf'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    edit_level(m, 'fback', session)
