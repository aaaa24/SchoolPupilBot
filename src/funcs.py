import time

from telebot import types, apihelper

import cmd_recognition
import var
from var import Phrase


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


def find_callback_text(message, data):
    text = None
    keyboard = message.reply_markup.keyboard
    for row in keyboard:
        for btn in row:
            if data == btn.callback_data:
                text = btn.text
                break
        else:
            continue
        break
    return text


def cancel(m, user, bot, session, *args, **kwargs):
    bot.delete_message(m.message.chat.id, m.message.message_id)

    if '$del' in m.data:
        message_ids = m.data[m.data.index('$del') + 4:].split('$')[0].split(',')
        for message_id in message_ids:
            bot.delete_message(m.message.chat.id, message_id)

    if user['level'] != 'menu':
        from funcs import edit_level
        edit_level(m, 'menu', session)


def suffixes(bot, m, text, inline_kb, **kwargs):
    if '$del' in m.data:
        message_ids = m.data[m.data.index('$del') + 4:].split('$')[0].split(',')
        for message_id in message_ids:
            bot.delete_message(m.message.chat.id, message_id)
    if '$sdel' in m.data:
        bot.delete_message(m.message.chat.id, m.message.message_id)


def send_photo(bot, m, text, photo_id, inline_kb, new_message=False, **kwargs):
    if hasattr(m, 'message'):
        suffixes(bot, m, text, inline_kb, **kwargs)
        if m.message.content_type == 'photo':
            if not ('$new' in m.data or '$sdel' in m.data or new_message):
                photo = types.InputMediaPhoto(photo_id, caption=text, **kwargs)
                return bot.edit_message_media(photo, m.message.chat.id, m.message.id, reply_markup=inline_kb)
        m = m.message

    return bot.send_photo(m.chat.id, caption=text, photo=photo_id, reply_markup=inline_kb, **kwargs)


def send_text(bot, m, text, inline_kb, new_message=False, **kwargs):
    if hasattr(m, 'message'):
        suffixes(bot, m, text, inline_kb, **kwargs)
        if m.message.content_type == 'text':
            if not ('$new' in m.data or '$sdel' in m.data or new_message):
                return bot.edit_message_text(text, m.message.chat.id, m.message.id, reply_markup=inline_kb, **kwargs)
        m = m.message

    return bot.send_message(m.chat.id, text, reply_markup=inline_kb, **kwargs)


def info(m, user, bot, session, *args, **kwargs):
    text = Phrase.BOT_INFO

    inline_kb = types.InlineKeyboardMarkup()
    inline_kb.row(types.InlineKeyboardButton('💬 Обратная связь', callback_data='fback'))
    inline_kb.row(
        types.InlineKeyboardButton('🎓 Бот «Школьный тренер»', url='https://t.me/SchoolCoachBot?start=fromSchoolPupil'))
    inline_kb.row(types.InlineKeyboardButton('🏠 В меню', callback_data='menu'))

    send_text(bot, m, text, inline_kb)
    if user['level'] != 'menu':
        edit_level(m, 'menu', session)


def edit_level(m, level, session):
    import ydb
    if hasattr(m, 'from_user'):
        user_id = m.from_user.id
    else:
        if m.json['from']['is_bot']:
            user_id = m.json['chat']['id']
        else:
            user_id = m.json['from']['id']
    if user_id < 0:
        return False
    request = session.transaction().execute(
        f'UPSERT INTO users (id, level) VALUES ({user_id}, "{level}");',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )
    return True


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

    send_text(bot, m, Phrase.START, inline_kb)
    edit_level(m, 'menu', session)


def _check_short_cmd(txt):
    list_of_cmds = []
    for k in short_cmds:
        if short_cmds[k](txt):
            list_of_cmds.append(k)
    return list_of_cmds


def is_send_news(m, user, bot, session, *args, **kwargs):
    import ydb

    request = session.transaction().execute(
        f'UPSERT INTO users (id, send_news) VALUES ({m.json["from"]["id"]}, {not user["send_news"]});',
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


def text_handling(m, user, bot, session, *args, **kwargs):
    logger = kwargs['logger']
    log_info = {
        'user_id': m.from_user.id, 'level': user['level'],
        'type_level': user['level'].split('_')[0],
        'content_type': m.content_type, 'text': m.text,
        'command': None, 'result': None, 'photo': None
    }
    if m.photo:
        log_info['photo'] = m.photo[-1].file_id

    flag = check_answer(m, user, bot, session, *args, **kwargs)
    if flag:
        log_info['result'] = flag
        logger.info('Ответ пользователю отправлен', extra={'type_event': 'message', 'info': log_info})
        return

    if not m.is_edit_text:
        list_of_short_cmds = _check_short_cmd(m.text)
    else:
        list_of_short_cmds = []

    if list_of_short_cmds:
        command = list_of_short_cmds[0]
        modules(list_func[commands[command]], m, user, bot, session)
        log_info['result'] = 'short_cmd'
    else:
        if user['level'].isdigit():
            modules(list_func[int(user['level'])], m, user, bot, session)
            log_info['result'] = 'digit_level'
        else:
            modules(list_func[commands[user['level']]], m, user, bot, session)
            log_info['result'] = 'command_level'

    logger.info('Ответ пользователю отправлен', extra={'type_event': 'message', 'info': log_info})


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


def check_answer(m, user, bot, session, *args, **kwargs):
    from re import match
    if m.reply_to_message and not m.reply_to_message.text is None and m.reply_to_message.from_user.id == bot.get_me().id:
        txt = m.reply_to_message.text
        for t in phrases_answer.items():
            data = match(t[0].replace('(', '\\(').replace(')', '\\)').format(**var.dict_re), txt)
            if data:
                modules(t[1], m, user, bot, session, *data.groups(), *args, **kwargs)
                return 'reply_to_message'

    txt = user['level']
    for t in level_answer.items():
        data = match(t[0].format(**var.dict_re), txt)
        if data:
            modules(t[1], m, user, bot, session, *data.groups(), *args, **kwargs)
            return 'level'
    return False


def callback_handling(callback_query, user, bot, session, *args, **kwargs):
    type_query = callback_query.data.split('$')[0].split('_')[0]
    list_funcs_callback[type_query](callback_query, user, bot, session, *args, **kwargs)

    logger = kwargs['logger']
    callback_text = find_callback_text(callback_query.message, callback_query.data)
    quert_without_suff = callback_query.data.split('$')[0]

    log_info = {
        'user_id': callback_query.from_user.id, 'level': user['level'],
        'callback_data': callback_query.data, 'callback_text': callback_text,
        'type_query': type_query, 'quert_without_suff': quert_without_suff,
    }

    logger.info('Ответ пользователю отправлен', extra={'type_event': 'callback_query', 'info': log_info})


def tt_callback(callback_query, user, bot, session, *args, **kwargs):
    import timetable

    query = callback_query.data
    quert_without = query.split('$')[0]
    quert_split = quert_without.split('_')
    function = None

    if quert_without == 'tt':
        function = timetable.call
    elif quert_split[0] == 'tt':
        if len(quert_split) == 2:
            function = timetable.parall
        elif len(quert_split) == 3:
            function = timetable.classes
        elif len(quert_split) in (4, 5):
            function = timetable.weekday
    elif quert_split[0] == 'att':
        function = timetable.add_weekday
    elif quert_split[0] == 'ett':
        if quert_split[-1].isalpha() and quert_split[-1] in [day['abb_name'] for day in var.weekdays]:
            function = timetable.edit
    elif quert_without == 'hol':
        function = timetable.holidays
    elif quert_without == 'callsch':
        function = timetable.call_schedule

    kwargs['logger'].debug('Определена функция для обработки нажатия', extra={'function': function})
    if function:
        function(callback_query, user, bot, session, *args, **kwargs)


def cl_callback(callback_query, user, bot, session, *args, **kwargs):
    import classes

    query = callback_query.data
    quert_without = query.split('$')[0]
    quert_split = quert_without.split('_')
    function = None

    if quert_without == 'cl':
        function = classes.call
    elif quert_split[0] == 'cl':
        if quert_split[-1].isdigit() and 1 <= int(quert_split[-1]) <= 11:
            function = classes.parall
        elif quert_split[-1].isalpha() and quert_split[-1] in ('А', 'Б', 'В', 'Г'):
            function = classes.info
    elif quert_split[0] == 'ecl':
        if quert_split[-1].isdigit() and 1 <= int(quert_split[-1]) <= 11:
            function = classes.add
        elif quert_split[-1].isalpha() and quert_split[-1] in ('А', 'Б', 'В', 'Г'):
            function = classes.add_end
    elif quert_split[0] == 'ncl':
        function = classes.call_edit_cabinet
    elif quert_split[0] == 'ccl':
        function = classes.call_edit_count
    elif quert_split[0] == 'tcl':
        function = classes.call_edit_class_teacher
    elif quert_split[0] == 'listcltea':
        function = classes.class_teachers

    kwargs['logger'].debug('Определена функция для обработки нажатия', extra={'function': function})
    if function:
        function(callback_query, user, bot, session, *args, **kwargs)


def tea_callback(callback_query, user, bot, session, *args, **kwargs):
    import teachers

    query = callback_query.data
    quert_without = query.split('$')[0]
    quert_split = quert_without.split('_')
    function = None

    if quert_without == 'tea':
        function = teachers.call
    elif quert_without == 'atea':
        function = teachers.add
    elif quert_split[0] == 'listtea':
        function = teachers.info_list_teachers
    elif quert_split[0] == 'itea':
        function = teachers.info_teacher
    elif quert_split[0] == 'acltea':
        function = teachers.add_class_teacher
    elif quert_split[0] == 'atttea':
        function = teachers.invitation_to_add_subjects_and_classes
    elif quert_split[0] == 'scltea':
        function = teachers.show_subjects_and_classes
    elif quert_split[0] == 'dtttea':
        function = teachers.invitation_to_del_subjects_and_classes
    elif quert_split[0] == 'fitttea':
        function = teachers.choose_weekday
    elif quert_split[0] == 'tttea':
        if len(quert_split) == 2:
            function = teachers.choose_weekday
        if len(quert_split) in (3, 4):
            function = teachers.show_timetable
    elif quert_split[0] == 'listtttea':
        function = teachers.tt_list_teachers
    elif quert_without == 'ftttea':
        function = teachers.foto_timetable
    elif quert_without == 'infofindtea':
        function = teachers.ask_teacher_name_info
    elif quert_without == 'ttfindtea':
        function = teachers.ask_teacher_name_tt

    kwargs['logger'].debug('Определена функция для обработки нажатия', extra={'function': function})
    if function:
        function(callback_query, user, bot, session, *args, **kwargs)


def chtt_callback(callback_query, user, bot, session, *args, **kwargs):
    import changes_tt

    query = callback_query.data
    quert_without = query.split('$')[0]
    quert_split = quert_without.split('_')
    function = None

    if quert_without == 'chtt':
        function = changes_tt.call
    elif quert_without == 'dchtt':
        function = changes_tt.get_date
    elif quert_split[0] == 'chtt' and quert_split[1].count('.') == 2 and quert_split[1].replace('.', '').isdigit():
        function = changes_tt.specific_date
    elif quert_without == 'achtt':
        function = changes_tt.get_photo
    elif quert_split[0] == 'achtt' and quert_split[1].count('.') == 2 and quert_split[1].replace('.', '').isdigit():
        function = changes_tt.specific_edit_date
    elif quert_without == 'subchtt':
        function = changes_tt.subscribe
    elif quert_split[0] == 'subchtt':
        if quert_split[1] == 'on':
            function = changes_tt.on_subscribe
        elif quert_split[1] == 'off':
            function = changes_tt.off_subscribe
    elif quert_split[0] == 'delchtt':
        if len(quert_split) == 2:
            function = changes_tt.confirmation_del_changes_tt
        elif len(quert_split) == 3:
            function = changes_tt.del_changes_tt
    elif quert_split[0] == 'echtt':
        function = changes_tt.edit_changes_tt

    kwargs['logger'].debug('Определена функция для обработки нажатия', extra={'function': function})
    if function:
        function(callback_query, user, bot, session, *args, **kwargs)


def news_callback(callback_query, user, bot, session, *args, **kwargs):
    import subscribe

    query = callback_query.data
    quert_without = query.split('$')[0]
    quert_split = quert_without.split('_')
    function = None

    if quert_without == 'news':
        function = subscribe.call
    elif quert_split[0] == 'news' and quert_split[1] == 'on':
        function = subscribe.on
    elif quert_split[0] == 'news' and quert_split[1] == 'off':
        function = subscribe.off

    kwargs['logger'].debug('Определена функция для обработки нажатия', extra={'function': function})
    if function:
        function(callback_query, user, bot, session, *args, **kwargs)


def help_callback(callback_query, user, bot, session, *args, **kwargs):
    import helper

    query = callback_query.data
    quert_without = query.split('$')[0]
    quert_split = quert_without.split('_')
    function = None

    if quert_without == 'hlp':
        function = helper.get_help

    kwargs['logger'].debug('Определена функция для обработки нажатия', extra={'function': function})
    if function:
        function(callback_query, user, bot, session, *args, **kwargs)


def comm_callback(callback_query, user, bot, session, *args, **kwargs):
    import communication

    query = callback_query.data
    quert_without = query.split('$')[0]
    quert_split = quert_without.split('_')
    function = None

    if quert_without == 'fback':
        function = communication.ask_feedback
    elif quert_split[0] == 'afback' and len(quert_split) in (3, 4):
        function = communication.get_answer_to_feedback
    elif quert_split[0] == 'ans':
        function = communication.get_answer_to_afback
    elif quert_without == 'wuser':
        function = communication.ask_id_to_write
    elif quert_split[0] == 'swuser' and len(quert_split) == 2:
        function = communication.write_to_user
    elif quert_split[0] == 'wuser' and len(quert_split) == 2:
        function = communication.another_message_to_user
    elif quert_split[0] == 'wuser' and len(quert_split) == 3:
        function = communication.confirmation_message
    elif quert_split[0] == 'safback' and len(quert_split) == 3:
        function = communication.answer_to_feedback
    elif quert_without == 'wusers':
        function = communication.ask_text_to_users
    elif quert_split[0] == 'wusers' and quert_split[1].isdigit():
        function = communication.confirmation_message_to_users
    elif quert_split[0] == 'chbtn':
        function = communication.choose_btn
    elif quert_split[0] == 'rwusers':
        function = communication.reask_btns_to_users
    elif quert_split[0] == 'rwuser':
        function = communication.reask_btns_to_user
    elif quert_split[0] == 'swadms':
        function = communication.send_message_to_admins
    elif quert_split[0] == 'swusers':
        function = communication.send_message_to_users

    kwargs['logger'].debug('Определена функция для обработки нажатия', extra={'function': function})
    if function:
        function(callback_query, user, bot, session, *args, **kwargs)


def users_callback(callback_query, user, bot, session, *args, **kwargs):
    import statistics
    import users

    query = callback_query.data
    quert_without = query.split('$')[0]
    quert_split = quert_without.split('_')
    function = None

    if quert_without == 'users':
        function = users.call
    elif quert_without == 'cntusers':
        function = users.count_users
    elif quert_without == 'aboutuser':
        function = users.user_id_for_about
    elif quert_without == 'userphoto':
        function = users.get_user_photos
    elif quert_without == 'stat':
        function = statistics.call

    kwargs['logger'].debug('Определена функция для обработки нажатия', extra={'function': function})
    if function:
        function(callback_query, user, bot, session, *args, **kwargs)


def pay_callback(callback_query, user, bot, session, *args, **kwargs):
    import pay

    query = callback_query.data
    quert_without = query.split('$')[0]
    quert_split = quert_without.split('_')
    function = None

    if quert_without == 'pay':
        function = pay.call
    elif quert_split[0] == 'pay':
        function = pay.create_order

    kwargs['logger'].debug('Определена функция для обработки нажатия', extra={'function': function})
    if function:
        function(callback_query, user, bot, session, *args, **kwargs)


def modules(function, m, user, bot, session, *args, **kwargs):
    if '.' in function:
        module = '.'.join(function.split('.')[:-1])
        exec(f'import {module}')
    eval(f'{function}(m, user, bot, session, *args, **kwargs)')


# !!! Нет коротких команд для изменений в расписании, и отключены для вкл/выкл подписки и для помощи
short_cmds = {
    'home': cmd_recognition.home, 'timetable_edit': cmd_recognition.edit_tt,
    'timetable': cmd_recognition.tt, 'news': cmd_recognition.send_news,
    #    'send_news_true': cmd_recognition.send_news_true, 'send_news_false': cmd_recognition.send_news_false,
    'classes': cmd_recognition.classes, 'teachers': cmd_recognition.teachers,  # 'help': cmd_recognition.hlp,
    'feedback': cmd_recognition.fback, 'info': cmd_recognition.info
}

admin_commands = ['timetable_edit', 'stat', 'user', 'users']

list_func = {
    0: 'auth_user', 1: 'to_menu', 2: 'timetable.call', 3: 'timetable.call', 4: 'changes_tt.call',
    5: 'subscribe.call', 6: 'list_of_cmds', 7: 'classes.call', 8: 'teachers.call', 9: 'helper.get_help',
    10: 'communication.ask_feedback', 11: 'info', 12: 'statistics.call', 13: 'users.about_user_cmd',
    14: 'users.call', 15: 'teachers.tt_list_teachers', 16: 'pay.call'
}

commands = {
    'start': 0, 'home': 1, 'main': 1, 'menu': 1, 'timetable_edit': 2, 'timetable': 3, 'changes_tt': 4,
    'news': 5, 'commands': 6, 'list': 6, 'classes': 7, 'teachers': 8, 'help': 9, 'feedback': 10, 'info': 11,
    'stat': 12, 'user': 13, 'users': 14, 'teachers_schedule': 15, 'donate': 16
}

list_funcs_callback = {
    'menu': to_menu, 'cncl': cancel, 'inf': info, '123': help_callback,
    'tt': tt_callback, 'ett': tt_callback, 'att': tt_callback, 'hol': tt_callback, 'callsch': tt_callback,
    'cl': cl_callback, 'ecl': cl_callback, 'tcl': cl_callback, 'ncl': cl_callback,
    'dcl': cl_callback, 'ccl': cl_callback, 'listcltea': cl_callback,
    'listtea': tea_callback, 'etea': tea_callback, 'atea': tea_callback, 'tea': tea_callback, 'itea': tea_callback,
    'acltea': tea_callback,
    'atttea': tea_callback, 'scltea': tea_callback, 'dtttea': tea_callback, 'fitttea': tea_callback,
    'tttea': tea_callback, 'listtttea': tea_callback, 'ftttea': tea_callback, 'infofindtea': tea_callback,
    'ttfindtea': tea_callback,
    'chtt': chtt_callback, 'dchtt': chtt_callback, 'achtt': chtt_callback, 'subchtt': chtt_callback,
    'delchtt': chtt_callback, 'echtt': chtt_callback,
    'news': news_callback,
    'hlp': help_callback,
    'fback': comm_callback, 'afback': comm_callback, 'ans': comm_callback, 'safback': comm_callback,
    'wuser': comm_callback, 'swuser': comm_callback, 'wusers': comm_callback, 'rwuser': comm_callback,
    'chbtn': comm_callback, 'rwusers': comm_callback, 'swadms': comm_callback, 'swusers': comm_callback,
    'users': users_callback, 'cntusers': users_callback, 'aboutuser': users_callback, 'userphoto': users_callback,
    'stat': users_callback,
    'pay': pay_callback
}

phrases_answer = {
    Phrase.EDIT_TT: 'timetable.writing', Phrase.ADD_TEA: 'teachers.writing_new',
    Phrase.INPUT_DATE: 'changes_tt.send_date', Phrase.IT_IS_SUNDAY: 'changes_tt.send_date',
    Phrase.ERROR_DATE: 'changes_tt.send_date',
    Phrase.EDIT_CHANGES_NOT_DATE: 'changes_tt.add_changes_tt',
    Phrase.NEED_CAPTION: 'changes_tt.add_changes_tt',
    Phrase.EDIT_IT_IS_SUNDAY: 'changes_tt.add_changes_tt',
    Phrase.ENTER_CLASS_CABINET: 'classes.edit_cabinet',
    Phrase.NOT_EDIT_CLASS_CABINET: 'classes.edit_cabinet',
    Phrase.ENTER_COUNT_PUPILS: 'classes.edit_count', Phrase.NOT_EDIT_COUNT_PUPILS: 'classes.edit_count',
    Phrase.ENTER_CLASS_TEACHER: 'classes.edit_class_teacher',
    Phrase.NOT_EDIT_CLASS_TEACHER: 'classes.edit_class_teacher',
    Phrase.ASK_FEEDBACK: 'communication.accept_feedback',
    Phrase.ACCEPT_FEEDBACK: 'communication.accept_feedback',
    Phrase.ASK_ID_TO_WRITE: 'communication.ask_text_to_write',
    Phrase.CONFIRMATION_MESSAGE_TO_USERS: 'communication.last_user',
    Phrase.ANSWER_RECEIVED: 'communication.reply_to_answer',
    Phrase.MESSAGE_FROM_USER: 'communication.reply_to_feedback',
    Phrase.ANSWER_FROM_USER: 'communication.reply_to_feedback',
    Phrase.ASK_BTNS: 'communication.add_button',
    Phrase.GET_CHAT_ID_FOR_ABOUT: 'users.about_user', Phrase.CHAT_NOT_FOUND: 'users.about_user',
    Phrase.NOT_ID_CHAT: 'users.about_user', Phrase.NOT_ID_USER: 'communication.ask_text_to_write',
    Phrase.USER_NOT_FOUND: 'communication.ask_text_to_write'
}

level_answer = {
    'ett_{p}_{ch}_{abb}': 'timetable.writing', 'atea': 'teachers.writing_new',
    'dchtt': 'changes_tt.send_date', 'achtt_{date}': 'changes_tt.add_changes_tt',
    'ncl_{p}_{ch}': 'classes.edit_cabinet', 'ccl_{p}_{ch}': 'classes.edit_count',
    'tcl_{p}_{ch}': 'classes.edit_class_teacher',
    'afback_{u_id}_{m_id}_{m_id}': 'communication.confirmation_answer_to_user',
    'fback': 'communication.accept_feedback',
    'ans_{u_id}_{m_id}_{m_id}': 'communication.answer_to_afback', 'wusers': 'communication.ask_btns_to_users',
    'wuser_{u_id}': 'communication.ask_btns_to_user', 'wuser': 'communication.ask_text_to_write',
    'aboutuser': 'users.about_user', 'atttea_{text}': 'teachers.add_subjects_and_classes',
    'dtttea_{text}': 'teachers.del_subjects_and_classes', 'infofindtea_{text}': 'teachers.find_teachers_info',
    'ttfindtea_{text}': 'teachers.find_teachers_tt'
}
