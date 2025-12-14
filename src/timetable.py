import ydb
from telebot import types
import var
from re import match, search, sub
from var import Phrase, months
from funcs import send_text, edit_level, create_inline_kb
import time
from datetime import datetime, timedelta


def call_schedule(m, user, bot, session, *args, **kwargs):
    text_request = 'SELECT * FROM call_schedule'
    request = session.transaction().execute(
        text_request,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    text_list_call_schedule = []
    for lesson in request[0].rows:
        text_list_call_schedule.append(
            f'<i>{lesson["id"]} урок:</i> {lesson["start_time"]} — {lesson["end_time"]}'
        )
    text_call_schedule = '\n'.join(text_list_call_schedule)

    if text_call_schedule:
        text = Phrase.CALL_SCHEDULE.format(text=text_call_schedule)
    else:
        text = Phrase.NOT_CALL_SCHEDULE

    inline_kb = create_inline_kb(
        [
            [('← Назад', 'tt'), ('🏠 В меню', 'menu')]
        ]
    )
    send_text(bot, m, text, inline_kb, parse_mode='HTML')


def get_text_date_range(date1, date2):
    if date1.day == 2:
        text = 'со '
    else:
        text = 'с '
    text += f'{date1.day} {months[date1.month - 1]["dec"]} '
    if date1.year != date2.year:
        text += f'{date1.year} года '
    text += f'по {date2.day} {months[date2.month - 1]["dec"]} {date2.year} года'
    return text


def get_holiday_date(number_day):
    delta = timedelta(days=number_day)
    epoch = datetime(1970, 1, 1)
    date = epoch + delta
    return date


def holidays(m, user, bot, session, *args, **kwargs):
    current_time = time.localtime()
    current_date = (current_time.tm_year, current_time.tm_mon, current_time.tm_mday)
    if current_date[1:] >= (9, 1):
        start_year = current_date[0]
    else:
        start_year = current_date[0] - 1

    text_request = f'SELECT * FROM holidays WHERE start BETWEEN Date("{start_year}-09-01") AND Date("{start_year + 1}-05-31")'
    request = session.transaction().execute(
        text_request,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    list_holidays = []
    for row in request[0].rows:
        name = row['name']
        start = get_holiday_date(row['start'])
        end = get_holiday_date(row['end'])
        list_holidays.append([name, start, end])
    list_holidays.sort(key=lambda t: t[1:])

    list_text_holidays = []
    for holidays in list_holidays:
        list_text_holidays.append(
            f'{holidays[0]}: {get_text_date_range(*holidays[1:])}'
        )
    text_holidays = '\n'.join(list_text_holidays)

    if text_holidays:
        text = Phrase.HOLIDAYS_TIMETABLE.format(text=text_holidays)
    else:
        text = Phrase.NOT_HOLIDAYS_TIMETABLE

    inline_kb = create_inline_kb(
        [
            [('← Назад', 'tt'), ('🏠 В меню', 'menu')]
        ]
    )
    send_text(bot, m, text, inline_kb)


def get_weekday_names(weekday):
    if type(weekday) is str and weekday.isdigit():
        weekday = int(weekday)
    for w in var.weekdays:
        if weekday in w.values():
            return w


def get_next_wday_btn(weekday, weekdays, data):
    next_weekday = weekdays.replace(str(weekday), '')
    sorted_weekdays = sorted(weekdays)
    if len(sorted_weekdays) in (0, 1):
        return []
    if len(sorted_weekdays) == 2:
        str_next_weekday = get_weekday_names(next_weekday)
        callback_data = f'{data}_{str_next_weekday["abb_name"]}_{weekdays}'
        if int(next_weekday) > weekday:
            btn_txt = f'{str_next_weekday["abb_name"]} →'
        else:
            btn_txt = f'← {str_next_weekday["abb_name"]}'
        return [(btn_txt, callback_data)]
    index_w = sorted_weekdays.index(str(weekday))
    previous_w = get_weekday_names(sorted_weekdays[index_w - 1])
    next_w = get_weekday_names(sorted_weekdays[(index_w + 1) % len(sorted_weekdays)])
    return [
        (f'← {previous_w["abb_name"]}', f'{data}_{previous_w["abb_name"]}_{weekdays}'),
        (f'{next_w["abb_name"]} →', f'{data}_{next_w["abb_name"]}_{weekdays}')
    ]


def _exst_info(old_line, num_line):
    # Добывает информацию об уроке
    seq_number = match(r'(\d{1})[\. \)]+', old_line)
    if not seq_number is None:
        old_line = old_line[seq_number.span()[1]:]
        seq_number = int(seq_number.group(1))
    else:
        seq_number = num_line

    if old_line.strip() in '–--0':
        lesson = {'is_null': True, 'seq_number': seq_number}
        return lesson

    if '\\' in old_line:
        lines = old_line.split('\\', maxsplit=1)
    elif '/' in old_line:
        lines = old_line.split('/', maxsplit=1)
    else:
        lines = [old_line]

    lessons = []
    for line in lines:
        lesson = {}
        num_cabinet_search = search(r'\(?(\d+)\)?', line)
        if num_cabinet_search:
            num_cabinet = int(num_cabinet_search.group(1))
            name_subj = line[:num_cabinet_search.span()[0]].strip()
        else:
            num_cabinet = 0
            name_subj = line.strip()

        if name_subj:
            foo = lambda s: sub(r'[\.\-" 0-9\(\)\\/\:]+', '', s.lower())
            for s in var.subjects:
                if foo(name_subj) == foo(s['name']) or foo(name_subj) in s['var_names']:
                    name_subj = s['name']
                    break
            else:
                name_subj = ''
        lesson['subject'] = name_subj.replace('"', '\\"')
        lesson['number'] = num_cabinet
        lessons.append(lesson)

    lesson = {'seq_number': seq_number, 'is_null': False}
    if len(lessons) == 1:
        lesson['two_stream'] = False
        if lessons[0]['subject']:
            lesson['subject'] = lessons[0]['subject']
            lesson['subject2'] = ''
        else:
            return 2
        lesson['number_cabinet'] = lessons[0]['number']
        lesson['number_cabinet2'] = 0
    else:
        if lessons[0]['subject'] and not lessons[1]['subject']:
            lesson['subject'] = lesson['subject2'] = lessons[0]['subject']
            if not lessons[1]['number']:
                lesson['two_stream'] = False
            else:
                lesson['two_stream'] = True
        elif lessons[1]['subject'] and not lessons[0]['subject']:
            lesson['subject'] = lesson['subject2'] = lessons[1]['subject']
            if not lessons[0]['number']:
                lesson['two_stream'] = False
            else:
                lesson['two_stream'] = True
        elif lessons[0]['subject'] and lessons[1]['subject']:
            lesson['subject'] = lessons[0]['subject']
            lesson['subject2'] = lessons[1]['subject']
            lesson['two_stream'] = True
        else:
            return 2

        lesson['number_cabinet'] = lessons[0]['number']
        lesson['number_cabinet2'] = lessons[1]['number']
        if not lesson['two_stream']:
            if lesson['number_cabinet'] == 0 and lesson['number_cabinet2'] != 0:
                lesson['number_cabinet'], lesson['number_cabinet2'] = lesson['number_cabinet2'], lesson[
                    'number_cabinet']
            lesson['number_cabinet2'] = 0
    return lesson


def writing(m, user, bot, session, *args, **kwargs):
    parallel, char, weekday = args

    for w in var.weekdays:
        if weekday in w.values():
            weekday = w['abb_name']
            full_weekday = w['name']
            weekday_num = w['num']
            accusative = w['accusative']
            break

    lines = [line.strip() for line in m.text.split('\n')]
    lessons = []
    null_lessons = []
    count = 1
    error = False
    text = ''
    for line in lines:
        if not line:
            continue
        line = line.strip()
        lesson = _exst_info(line, count)
        if lesson == 1:
            text += f'Неправильный номер кабинета у урока "{line}".\n'
            error = True
        elif lesson == 2:
            text += f'Не удалось распознать название урока "{line}".\n'
            error = True
        elif lesson['is_null']:
            null_lessons.append(lesson['seq_number'])
            continue

        lessons.append(lesson)
        count += 1

    inline_kb = types.InlineKeyboardMarkup()
    if not error:
        inline_kb.row(types.InlineKeyboardButton('Добавить день недели', callback_data=f'att_{parallel}_{char}'))

    list_inline_btn = [('← Назад', f'tt_{parallel}_{char}_{weekday}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    if not error:
        request_text = ''
        idd = f'{parallel}{"АБВГ".index(char) + 1}{weekday_num}'
        if lessons:
            values_text = ', '.join([
                f'({idd}{lesson["seq_number"]}, {parallel}, "{char}", {weekday_num}, {lesson["seq_number"]}, "{lesson["subject"]}", {lesson["number_cabinet"]}, {lesson["two_stream"]}, "{lesson["subject2"]}", {lesson["number_cabinet2"]})'
                for lesson in lessons])
            request_text += f'UPSERT INTO lessons (id, number_class, char_class, weekday, seq_number, subject, number_cabinet, two_stream, subject2, number_cabinet2) VALUES ' + values_text + ';'
        if null_lessons:
            null_lessons = ', '.join([idd + str(null) for null in null_lessons])
            request_text += f'DELETE FROM lessons WHERE id in ({null_lessons});'
        print(request_text)
        request = session.transaction().execute(
            request_text,
            commit_tx=True,
            settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
        )

        text = f'Расписание для {parallel}{char} класса на {accusative} успешно записано'
    else:
        text += f'Введите заново расписание для {parallel}{char} класса на {accusative}'

    send_text(bot, m, text.strip(), inline_kb)
    if not error:
        edit_level(m, 'menu', session)


def call(m, user, bot, session, *args, **kwargs):
    list_inline_btn = [(str(i), 'tt_' + str(i)) for i in range(1, 12)]
    inline_kb = create_inline_kb([
        list_inline_btn[:6],
        list_inline_btn[6:],
        ('🔔 Расписание звонков', 'callsch'),
        ('🏖 Расписание каникул', 'hol'),
        ('🏠 В меню', 'menu')
    ])

    if user['admin']:
        text = 'Чтобы узнать или редактировать расписание классов, выберите параллель'
    else:
        text = 'Чтобы узнать расписание классов, выберите параллель'

    send_text(bot, m, text, inline_kb)
    if user['level'] != 'menu':
        edit_level(m, 'menu', session)


def parall(m, user, bot, session, *args, **kwargs):
    parallel = m.data.split('$')[0].split('_')[1]

    id_class = int(f'{parallel}0')
    result = session.transaction().execute(
        f'SELECT * FROM classes WHERE id BETWEEN {id_class} AND {id_class + 10};',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    chars = [cl['char'] for cl in result[0].rows]
    list_inline_btn = [(f'{parallel}{c}', f'tt_{parallel}_{c}') for c in chars]

    if result[0].rows == []:
        text = f'В {parallel} параллели не добавлены классы'
    else:
        if user['admin']:
            text = 'Выберите класс, у которого хотите узнать или отредактировать расписание'
        else:
            text = 'Выберите класс, у которого хотите узнать расписание'

    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=4).add(*inline_buttons)

    list_inline_btn = [('← Назад', f'tt'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)


def classes(m, user, bot, session, *args, **kwargs):
    parallel, char = m.data.split('$')[0].split('_')[1:3]

    id_class = int(f'{parallel}{"АБВГ".index(char) + 1}00')
    result = session.transaction().execute(
        f'SELECT DISTINCT weekday FROM lessons WHERE id BETWEEN {id_class} AND {id_class + 100};',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    weekdays = [var.weekdays[w['weekday'] - 1]['abb_name'] for w in result[0].rows]
    str_weekdays = ''.join([str(w['weekday']) for w in result[0].rows])
    list_inline_btn = [(w, f'tt_{parallel}_{char}_{w}_{str_weekdays}') for w in weekdays]

    if result[0].rows == []:
        text = f'Для {parallel}{char} класса не добавлено расписание'
    else:
        if user['admin']:
            text = f'Чтобы узнать или отредактировать расписание для {parallel}{char} класса, выберите день недели'
        else:
            text = f'Чтобы узнать расписание для {parallel}{char} класса, выберите день недели'
            if len(weekdays) <= 4:
                text += '. Показаны дни, для которых добавлено расписание'

    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=6).add(*inline_buttons)

    if len(weekdays) <= 5 and user['admin']:
        inline_kb.row(types.InlineKeyboardButton('Добавить день недели', callback_data=f'att_{parallel}_{char}'))

    if match('1?[0-9]{1}[А-Г]{1} класс\n', m.message.text):
        back = f'cl_{parallel}_{char}'
    # elif match('Выберите класс, у которого хотите узнать (или отредактировать |)расписание', m.message.text):
    else:
        back = f'tt_{parallel}'

    list_inline_btn = [('← Назад', back), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    if user['level'] != 'menu':
        edit_level(m, 'menu', session)


def weekday(m, user, bot, session, *args, **kwargs):
    print(m.data)

    data = m.data.split('$')[0].split('_')
    parallel = int(data[1])
    char = data[2]
    weekday = data[3]
    if len(data) == 5:
        all_weekdays = data[4]
    else:
        all_weekdays = ''

    for w in var.weekdays:
        if weekday in w.values():
            full_weekday = w['name']
            n_weekday = w['num']
            accusative = w['accusative']
            break

    id_class = int(f'{parallel}{"АБВГ".index(char) + 1}{n_weekday}0')
    result = session.transaction().execute(
        f'SELECT * FROM lessons WHERE id BETWEEN {id_class} AND {id_class + 10};',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    if result[0].rows == []:
        text = f'Расписание для {parallel}{char} класса на {accusative} не добавлено'
    else:
        subjects = result[0].rows
        text = f'{parallel}{char} класс, {full_weekday}:\n'
        for i in range(len(subjects)):
            if subjects[i]['two_stream']:
                if subjects[i]['subject'] == subjects[i]['subject2']:
                    text += f'\n{subjects[i]["seq_number"]}. {subjects[i]["subject"]}'
                    if subjects[i]["number_cabinet"] != 0 and subjects[i]["number_cabinet2"]:
                        text += f' ({subjects[i]["number_cabinet"]} / {subjects[i]["number_cabinet2"]})'
                    elif subjects[i]["number_cabinet"] != 0:
                        text += f' ({subjects[i]["number_cabinet"]})'
                    elif subjects[i]["number_cabinet2"] != 0:
                        text += f' ({subjects[i]["number_cabinet2"]})'
                else:
                    text += f'\n{subjects[i]["seq_number"]}. {subjects[i]["subject"]}'
                    if subjects[i]["number_cabinet"] != 0:
                        text += f' ({subjects[i]["number_cabinet"]})'
                    text += f' / {subjects[i]["subject2"]}'
                    if subjects[i]["number_cabinet2"] != 0:
                        text += f' ({subjects[i]["number_cabinet2"]})'
            else:
                text += f'\n{subjects[i]["seq_number"]}. {subjects[i]["subject"]}'
                if subjects[i]["number_cabinet"] != 0:
                    text += f' ({subjects[i]["number_cabinet"]})'

    inline_kb = types.InlineKeyboardMarkup()
    if user['admin']:
        inline_kb.row(
            types.InlineKeyboardButton('Редактировать расписание', callback_data=f'ett_{parallel}_{char}_{weekday}'))

    list_inline_btn = get_next_wday_btn(n_weekday, all_weekdays, f'tt_{parallel}_{char}')
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)
    list_inline_btn = [('← Назад', f'tt_{parallel}_{char}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    if user['level'] != 'menu':
        edit_level(m, 'menu', session)


def add_weekday(m, user, bot, session, *args, **kwargs):
    parallel, char = m.data.split('$')[0].split('_')[1:3]

    id_class = int(f'{parallel}{"АБВГ".index(char) + 1}00')
    result = session.transaction().execute(
        f'SELECT DISTINCT weekday FROM lessons WHERE id BETWEEN {id_class} AND {id_class + 100};',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    weekdays = sorted({w['num'] for w in var.weekdays[:6]} - set([w['weekday'] for w in result[0].rows]))
    weekdays = [var.weekdays[w - 1]['abb_name'] for w in weekdays]

    if len(weekdays) == 0:
        text = f'Для {parallel}{char} класса расписание добавлено на все дни недели. Выберите день недели, для которого хотите отредактировать расписание'
        weekdays = [w['abb_name'] for w in var.weekdays[:6]]
    else:
        text = f'Выберите день недели, для которого хотите добавить расписание для {parallel}{char} класса'
    list_inline_btn = [(w, f'ett_{parallel}_{char}_{w}') for w in weekdays]

    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=6).add(*inline_buttons)

    list_inline_btn = [('← Назад', f'tt_{parallel}_{char}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)


def edit(m, user, bot, session, *args, **kwargs):
    data = m.data.split('$')[0].split('_')
    parallel = int(data[1])
    char = data[2]
    weekday = data[3]

    for w in var.weekdays:
        if weekday in w.values():
            full_weekday = w['name']
            n_weekday = w['num']
            accusative = w['accusative']
            break

    if match('{p}{ch} класс, {weekd}:'.format(**var.dict_re), m.message.text):
        back = f'tt_{parallel}_{char}_{weekday}'
    else:
        back = f'tt_{parallel}_{char}'

    list_inline_btn = [('← Назад', back), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

    send_text(bot, m, Phrase.EDIT_TT.format(p=parallel, ch=char, acc=accusative), inline_kb)
    edit_level(m, f'ett_{parallel}_{char}_{weekday}', session)
