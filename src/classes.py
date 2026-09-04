import ydb
from telebot import types

import constants
from constants import Phrase
from utils import send_text, edit_level


def class_teachers(m, user, bot, session, *args, **kwargs):
    parallel, char = m.data.split('$')[0].split('_')[1:3]

    text_request = 'SELECT t.id, t.last_name, t.first_name, t.patronymic, les.group, les.subject ' \
                   'FROM teachers t JOIN teachers_lessons les ON t.id = les.id_teacher ' \
                   f'WHERE les.number_class = {parallel} AND les.char_class = "{char}"'
    request = session.transaction().execute(
        text_request,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    if not request[0].rows:
        text = Phrase.NO_TEACHERS_HAVE_BEEN_ADDED_TO_THE_CLASS.format(p=parallel, ch=char)
        inline_kb = types.InlineKeyboardMarkup()
    else:
        list_teachers = []
        for teacher_id in set(t['t.id'] for t in request[0].rows):
            subjs = [t for t in request[0].rows if t['t.id'] == teacher_id]
            line = f'{subjs[0]["t.last_name"]} {subjs[0]["t.first_name"]} {subjs[0]["t.patronymic"]} – '
            text_subjs = []
            for subj in subjs:
                text_subjs.append(subj['les.subject'][0].lower() + subj['les.subject'][1:])
                abb_name = constants.get_division_abb(subj['les.group'])
                if abb_name:
                    text_subjs[-1] += f' ({abb_name})'
            line += ', '.join(sorted(text_subjs))
            list_teachers.append(line)
        list_teachers.sort()
        text_list_teachers = '\n'.join([f'{i + 1}. {t}' for i, t in enumerate(list_teachers)])
        text = Phrase.LIST_CLASS_TEACHERS.format(p=parallel, ch=char, text=text_list_teachers)

        list_inline_btn = []
        for i, t in enumerate(
                sorted(set(
                    (t['t.last_name'], t['t.first_name'], t['t.patronymic'], t['t.id']) for t in request[0].rows
                ))
        ):
            teacher_id = t[-1]
            button_info = f'itea_{teacher_id}'
            list_inline_btn.append((f'{i + 1}', button_info))
        inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
        inline_kb = types.InlineKeyboardMarkup(row_width=5).add(*inline_buttons)

    list_inline_btn = [('← Назад', f'cl_{parallel}_{char}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)


def edit_class_teacher(m, user, bot, session, *args, **kwargs):
    from teachers import _clean_text, get_found_teachers
    parallel, char = args

    text = ''
    fio = _clean_text(m.text, hyphen=True).title().split()
    teacher = get_found_teachers(m.text, session,
                                 ['id', 'last_name', 'first_name', 'patronymic', 'number_class', 'char_class'])
    if teacher is None:
        text = Phrase.NOT_EDIT_CLASS_TEACHER.format(p=parallel, ch=char)
        list_inline_btn = []
    elif len(teacher) > 1:
        teachers = []
        for i in range(len(teacher)):
            teachers.append(
                f'{i + 1}. <code>{teacher[i]["last_name"]} {teacher[i]["first_name"]} {teacher[i]["patronymic"]}</code>')
        teachers = '\n'.join(teachers)
        text = Phrase.FOUND_SOME_CLASS_TEACHERS.format(text=teachers)
        list_inline_btn = []
    else:
        teacher = teacher[0]
        last_name, first_name, patronymic = teacher['last_name'], teacher['first_name'], teacher['patronymic']
        fio = ' '.join((last_name, first_name, patronymic))

        num_class = teacher['number_class']
        ch_class = teacher['char_class']
        classes = list(zip(
            num_class.split(';') if num_class else (),
            ch_class.split(';') if ch_class else (),
        ))

        if not (parallel, char) in classes:
            classes += [(parallel, char)]
            classes.sort()
            number_class = ';'.join([cl[0] for cl in classes])
            char_class = ';'.join([cl[1] for cl in classes])
            r_text = f'UPSERT INTO teachers (id, number_class, char_class) VALUES ({teacher["id"]}, "{number_class}", "{char_class}");'
        else:
            r_text = ''

        r_text += f'UPSERT INTO classes (id, teacher, id_teacher) ' \
                  f'VALUES ({parallel}{"АБВГ".index(char) + 1}, "{fio}", {teacher["id"]});'

        print(r_text)

        result = session.transaction().execute(
            r_text,
            commit_tx=True,
            settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
        )

        text = Phrase.EDIT_CLASS_TEACHER.format(p=parallel, ch=char, cl_teach=fio)
        list_inline_btn = [
            ('Изменить номер кабинета', f'ncl_{parallel}_{char}'),
            ('Изменить классного руководителя', f'tcl_{parallel}_{char}'),
            ('Изменить количество учащихся', f'ccl_{parallel}_{char}')
        ]
        edit_level(m, 'menu', session)

    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    list_inline_btn = [('← Назад', f'cl_{parallel}_{char}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb, parse_mode='HTML')


def call_edit_class_teacher(m, user, bot, session, *args, **kwargs):
    parallel, char = m.data.split('$')[0].split('_')[1:3]

    list_inline_btn = [('← Назад', f'cl_{parallel}_{char}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().row(*inline_buttons)

    send_text(bot, m, Phrase.ENTER_CLASS_TEACHER.format(p=parallel, ch=char), inline_kb)
    edit_level(m, f'tcl_{parallel}_{char}', session)


def edit_count(m, user, bot, session, *args, **kwargs):
    from re import search
    parallel, char = args

    count = search(r'\d{2}', m.text)
    if count:
        count = count.group()
        request = session.transaction().execute(
            f'UPSERT INTO classes (id, 	count_pupils) VALUES ({parallel}{"АБВГ".index(char) + 1}, {count});',
            commit_tx=True,
            settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
        )
        text = Phrase.EDIT_COUNT_PUPILS.format(p=parallel, ch=char, count_p=count)
        list_inline_btn = [
            ('Изменить номер кабинета', f'ncl_{parallel}_{char}'),
            ('Изменить классного руководителя', f'tcl_{parallel}_{char}'),
            ('Изменить количество учащихся', f'ccl_{parallel}_{char}')
        ]
        edit_level(m, 'menu', session)
    else:
        text = Phrase.NOT_EDIT_COUNT_PUPILS.format(p=parallel, ch=char)
        list_inline_btn = []

    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    list_inline_btn = [('← Назад', f'cl_{parallel}_{char}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)


def call_edit_count(m, user, bot, session, *args, **kwargs):
    parallel, char = m.data.split('$')[0].split('_')[1:3]

    list_inline_btn = [('← Назад', f'cl_{parallel}_{char}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().row(*inline_buttons)

    send_text(bot, m, Phrase.ENTER_COUNT_PUPILS.format(p=parallel, ch=char), inline_kb)
    edit_level(m, f'ccl_{parallel}_{char}', session)


def edit_cabinet(m, user, bot, session, *args, **kwargs):
    from re import search
    parallel, char = args

    number_cabinet = search(r'\d{3}', m.text)
    if number_cabinet:
        number_cabinet = number_cabinet.group()
        request = session.transaction().execute(
            f'UPSERT INTO classes (id, number_cabinet) VALUES ({parallel}{"АБВГ".index(char) + 1}, {number_cabinet});',
            commit_tx=True,
            settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
        )
        text = Phrase.EDIT_CLASS_CABINET.format(p=parallel, ch=char, cab=number_cabinet)
        list_inline_btn = [
            ('Изменить номер кабинета', f'ncl_{parallel}_{char}'),
            ('Изменить классного руководителя', f'tcl_{parallel}_{char}'),
            ('Изменить количество учащихся', f'ccl_{parallel}_{char}')
        ]
        edit_level(m, 'menu', session)
    else:
        text = Phrase.NOT_EDIT_CLASS_CABINET.format(p=parallel, ch=char)
        list_inline_btn = []

    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    list_inline_btn = [('← Назад', f'cl_{parallel}_{char}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)


def call_edit_cabinet(m, user, bot, session, *args, **kwargs):
    parallel, char = m.data.split('$')[0].split('_')[1:3]

    list_inline_btn = [('← Назад', f'cl_{parallel}_{char}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().row(*inline_buttons)

    send_text(bot, m, Phrase.ENTER_CLASS_CABINET.format(p=parallel, ch=char), inline_kb)
    edit_level(m, f'ncl_{parallel}_{char}', session)


def call(m, user, bot, session, *args, **kwargs):
    list_inline_btn = [(str(i), 'cl_' + str(i)) for i in range(1, 12)]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=6).add(*inline_buttons)
    inline_kb.row(types.InlineKeyboardButton('🏠 В меню', callback_data='menu'))

    send_text(bot, m, 'Для просмотра информации о классе выберите параллель', inline_kb)
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

    if result[0].rows == []:
        text = f'В {parallel} параллели не добавлены классы'
    else:
        text = 'Выберите класс, информацию о котором хотите узнать'
        if user['admin'] and len(result[0].rows) < 4:
            text += ', или добавьте отсутствующий'

    chars = [cl['char'] for cl in result[0].rows]
    list_inline_btn = [(f'{parallel}{c}', f'cl_{parallel}_{c}') for c in chars]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=4).add(*inline_buttons)

    if user['admin'] and len(result[0].rows) < 4:
        inline_kb.row(types.InlineKeyboardButton('Добавить класс', callback_data=f'ecl_{parallel}'))

    list_inline_btn = [('← Назад', 'cl'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)


def info(m, user, bot, session, *args, **kwargs):
    from re import search
    parallel, char = m.data.split('$')[0].split('_')[1:3]

    id_class = int(f'{parallel}{"АБВГ".index(char) + 1}')
    result = session.transaction().execute(
        f'SELECT * FROM classes WHERE id = {id_class};',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    class_info = result[0].rows[0]

    text = f'{parallel}{char} класс\n\n'
    if not class_info['number_cabinet'] is None:
        text += f'Номер классного кабинета: {class_info["number_cabinet"]}\n'
        txt_cab = 'Изменить'
    else:
        txt_cab = 'Указать'
    if not class_info['teacher'] is None:
        text += f'Классный руководитель: {class_info["teacher"]}\n'
        txt_teach = 'Изменить'
    else:
        txt_teach = 'Указать'
    if not class_info['count_pupils'] is None:
        text += f'Количество учащихся: {class_info["count_pupils"]}'
        txt_count = 'Изменить'
    else:
        txt_count = 'Указать'

    list_inline_btn = [
        ('🗓 Расписание', f'tt_{parallel}_{char}'),
        ('👨‍🏫👩‍🏫 Учителя', f'listcltea_{parallel}_{char}')]
    if not class_info['id_teacher'] is None:
        list_inline_btn += [
            ('👨‍🏫 Классный руководитель', f'itea_{class_info["id_teacher"]}'.encode('utf-8')[:63].decode('utf-8'))]

    if user['admin']:
        list_inline_btn += [(
            f'{txt_cab} номер кабинета', f'ncl_{parallel}_{char}'),
            (f'{txt_teach} классного руководителя', f'tcl_{parallel}_{char}'),
            (f'{txt_count} количество учащихся', f'ccl_{parallel}_{char}')
        ]

    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    if search(f'Классный руководитель.+{parallel}{char}.+(класса|классов)', m.message.text):
        back = f'itea_{class_info["id_teacher"]}'.encode('utf-8')[:63].decode('utf-8')
    else:
        back = f'cl_{parallel}'
    list_inline_btn = [('← Назад', back), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    if user['level'] != 'menu':
        edit_level(m, 'menu', session)


def add(m, user, bot, session, *args, **kwargs):
    parallel = m.data.split('$')[0].split('_')[1]

    id_class = int(f'{parallel}0')
    result = session.transaction().execute(
        f'SELECT * FROM classes WHERE id BETWEEN {id_class} AND {id_class + 10};',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    chars = sorted(list({'А', 'Б', 'В', 'Г'} - {cl['char'] for cl in result[0].rows}))

    inline_kb = types.InlineKeyboardMarkup(row_width=4)
    if chars:
        list_inline_btn = [(f'{parallel}{c}', f'ecl_{parallel}_{c}') for c in chars]
        inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
        inline_kb.add(*inline_buttons)
        text = Phrase.SELECT_ADD_CLASS
    else:
        list_inline_btn = [(f'{parallel}{c}', f'cl_{parallel}_{c}') for c in ('А', 'Б', 'В', 'Г')]
        inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
        inline_kb.add(*inline_buttons)
        text = Phrase.FULL_PARALLEL.format(p=parallel)

    list_inline_btn = [('← Назад', f'cl_{parallel}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)


def add_end(m, user, bot, session, *args, **kwargs):
    parallel, char = m.data.split('$')[0].split('_')[1:3]

    request = session.transaction().execute(
        f'UPSERT INTO classes (id, number, char) VALUES ({parallel}{("А", "Б", "В", "Г").index(char) + 1}, {parallel}, "{char}");',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    list_inline_btn = [
        ('🗓 Добавить расписание', f'att_{parallel}_{char}'),
        ('Указать номер кабинета', f'ncl_{parallel}_{char}'),
        ('Указать классного руководителя', f'tcl_{parallel}_{char}'),
        ('Указать количество учащихся', f'ccl_{parallel}_{char}'),
    ]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    list_inline_btn = [('← Назад', f'ecl_{parallel}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, f'{parallel}{char} класс успешно добавлен', inline_kb)
