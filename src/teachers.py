import re

import ydb
from telebot import types

import constants
from constants import Phrase
from utils import send_text, edit_level

clear_symbols = lambda s: re.sub(r'[\.\-" 0-9\(\)\\/\:]+', '', s.lower())
limit_teachers = 15


def get_back_button(keyboard, default_callback_data):
    buttons = [(b.text, b.callback_data) for l in keyboard for b in l]
    for button in buttons:
        if button[0] == '←':
            callback_data = button[1].split('_')[0]
            offset = int(button[1].split('_')[1])
            back = f'{callback_data}_{offset + limit_teachers}'
            break
        elif button[0] == '→':
            callback_data = button[1].split('_')[0]
            offset = int(button[1].split('_')[1])
            back = f'{callback_data}_{offset - limit_teachers}'
            break
    else:
        back = f'{default_callback_data}_0'
    return back


def find_teachers_info(m, user, bot, session, *args, **kwargs):
    find_teachers(m, user, bot, session, *args, t='info', **kwargs)


def find_teachers_tt(m, user, bot, session, *args, **kwargs):
    find_teachers(m, user, bot, session, *args, t='tt', **kwargs)


def find_teachers(m, user, bot, session, *args, **kwargs):
    back = args[0]
    teachers = get_found_teachers(m.text, session)
    if teachers is None:
        text = Phrase.NOT_FOUND_TEACHER_FROM_LIST
        inline_kb = types.InlineKeyboardMarkup()
    elif len(teachers) == 1:
        teacher = teachers[0]
        if kwargs['t'] == 'info':
            info_teacher(m, user, bot, session, *args, teacher_id=teacher['id'], teacher=teacher, back=back, **kwargs)
        else:
            choose_weekday(m, user, bot, session, *args, teacher_id=teacher['id'], teacher=teacher, back=back, **kwargs)
        return
    else:
        text_teachers = []
        for i in range(len(teachers)):
            text_teachers.append(
                f'{i + 1}. {teachers[i]["last_name"]} {teachers[i]["first_name"]} {teachers[i]["patronymic"]}')
        str_teachers = '\n'.join(text_teachers)
        if kwargs['t'] == 'info':
            text = Phrase.FOUND_SOME_TEACHERS_INFO.format(text=str_teachers)
            teacher_data = 'itea'
        else:
            text = Phrase.FOUND_SOME_TEACHERS_TT.format(text=str_teachers)
            teacher_data = 'tttea'

        list_inline_btn = []
        for i in range(len(teachers)):
            teacher_id = teachers[i]['id']
            button_info = f'{teacher_data}_{teacher_id}'
            list_inline_btn.append((f'{i + 1}', button_info))
        inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
        inline_kb = types.InlineKeyboardMarkup(row_width=5).add(*inline_buttons)

    list_inline_btn = [('← Назад', back), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    if teachers:
        edit_level(m, 'menu', session)


def ask_teacher_name_info(m, user, bot, session, *args, **kwargs):
    ask_teacher_name(m, user, bot, session, *args, t='info', **kwargs)


def ask_teacher_name_tt(m, user, bot, session, *args, **kwargs):
    ask_teacher_name(m, user, bot, session, *args, t='tt', **kwargs)


def ask_teacher_name(m, user, bot, session, *args, **kwargs):
    if kwargs['t'] == 'info':
        text = Phrase.ASK_TEACHER_NAME_TO_FIND_INFO
        callback_data = 'listtea'
        level = 'infofindtea'
    else:
        text = Phrase.ASK_TEACHER_NAME_TO_FIND_TT
        callback_data = 'listtttea'
        level = 'ttfindtea'

    buttons = [(b.text, b.callback_data) for l in m.message.reply_markup.keyboard for b in l]
    back = get_back_button(m.message.reply_markup.keyboard, callback_data)

    list_inline_btn = [('← Назад', back), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    level += f'_{back}'
    edit_level(m, level, session)


def create_variants(names, m=[]):
    if len(names) == 1:
        return ['("' + '", "'.join(m + [names[0]]) + '")']
    variants = []
    for i in range(len(names)):
        variants.extend(create_variants(names[:i] + names[i + 1:], m + [names[i]]))
    return variants


def get_found_teachers(text, session, columns=None):
    fio = _clean_text(text, hyphen=True).title().split()
    names = fio[:3]
    tuples = f', '.join(create_variants(names))
    if len(names) == 3:
        where = f'(last_name, first_name, patronymic) IN ({tuples})'
    elif len(names) == 2:
        where = f'(last_name, first_name) IN ({tuples}) OR ' \
                f'(first_name, patronymic) IN ({tuples}) OR ' \
                f'(last_name, patronymic) IN ({tuples})'
    elif len(names) == 1:
        where = f'{tuples} IN (last_name, first_name, patronymic)'
    else:
        return None

    where += ' AND quit = false'

    text_request = f'SELECT {", ".join(columns) if columns else "*"} FROM teachers WHERE {where}'
    request = session.transaction().execute(
        text_request,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    teachers = request[0].rows
    if not teachers:
        return None
    return teachers


def show_timetable(m, user, bot, session, *args, **kwargs):
    from timetable import get_next_wday_btn
    if len(m.data.split('$')[0].split('_')) == 4:
        teacher_id, weekday, all_weekdays = m.data.split('$')[0].split('_')[1:4]
    else:
        teacher_id, weekday = m.data.split('$')[0].split('_')[1:3]
        all_weekdays = ''
    for w in constants.weekdays:
        if weekday in w.values():
            full_weekday = w['name']
            n_weekday = w['num']
            accusative = w['accusative']
            break

    text_request = 'SELECT les.*, tl.group AS group FROM lessons AS les ' \
                   'JOIN teachers_lessons AS tl ' \
                   'ON les.number_class = tl.number_class AND les.char_class = tl.char_class ' \
                   f'WHERE weekday = {n_weekday} AND id_teacher = {teacher_id} ' \
                   'AND (tl.group IN (0, 1, 3) AND tl.subject = les.subject ' \
                   'OR tl.group IN (0, 2, 4) AND tl.subject = les.subject2 ' \
                   'OR tl.subject = les.subject AND les.subject2 = ""); ' \
                   'SELECT last_name, first_name, patronymic FROM teachers ' \
                   f'WHERE id = {teacher_id}'

    request = session.transaction().execute(
        text_request,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    t = request[1].rows[0]
    teacher = f'{t["last_name"]} {t["first_name"]} {t["patronymic"]}'
    if request[0].rows == []:
        text = f'{teacher}\n\nРасписание на {accusative} не добавлено'
    else:
        lessons = request[0].rows
        filtered_lessons = []
        for lesson in lessons:
            filtered_lesson = {
                'number_class': lesson['number_class'],
                'char_class': lesson['char_class'],
                'seq_number': lesson['seq_number'],
                'group': lesson['group']
            }
            if lesson['group'] in (0, 1, 3) or not lesson['two_stream']:
                filtered_lesson['subject'] = lesson['subject']
                filtered_lesson['number_cabinet'] = lesson['number_cabinet']
            elif lesson['group'] in (2, 4):
                filtered_lesson['subject'] = lesson['subject2']
                filtered_lesson['number_cabinet'] = lesson['number_cabinet2']
            filtered_lesson['subject'] = filtered_lesson['subject'][0].lower() + filtered_lesson['subject'][1:]
            filtered_lessons.append(filtered_lesson)
        filtered_lessons.sort(key=lambda les: les['seq_number'])
        is_one_subject = len({item['subject'] for item in filtered_lessons}) == 1
        is_one_cabinet = len({item['number_cabinet'] for item in filtered_lessons}) == 1 \
                         and filtered_lessons[0]['number_cabinet'] != 0

        text = f'{teacher}, {full_weekday}'
        if is_one_subject and is_one_cabinet:
            text += f' ({filtered_lessons[0]["subject"]}, {filtered_lessons[0]["number_cabinet"]} каб.)'
        elif is_one_subject:
            text += f' ({filtered_lessons[0]["subject"]})'
        elif is_one_cabinet:
            text += f' ({filtered_lessons[0]["number_cabinet"]} каб.)'
        text += ':\n'
        for lesson in filtered_lessons:
            text += f'\n{lesson["seq_number"]}. {lesson["number_class"]}{lesson["char_class"]}'
            if lesson['group'] in (1, 2):
                text += f' ({lesson["group"]} гр.)'
            elif lesson['group'] == 3:
                text += ' (м)'
            elif lesson['group'] == 4:
                text += ' (д)'
            if not is_one_cabinet and lesson['number_cabinet'] != 0:
                text += f', {lesson["number_cabinet"]} каб.'
            if not is_one_subject:
                text += f' ({lesson["subject"]})'

    list_inline_btn = get_next_wday_btn(n_weekday, all_weekdays, f'tttea_{teacher_id}')
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().row(*inline_buttons)
    list_inline_btn = [('← Назад', f'tttea_{teacher_id}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)


def choose_weekday(m, user, bot, session, *args, **kwargs):
    if 'teacher_id' in kwargs:
        teacher_id = kwargs['teacher_id']
        back = kwargs['back']
        teacher = kwargs['teacher']
        teacher = f'{teacher["last_name"]} {teacher["first_name"]} {teacher["patronymic"]}'
    else:
        teacher_id = m.data.split('$')[0].split('_')[1]
        back = None
        teacher = None
    text_request = 'SELECT DISTINCT weekday FROM lessons AS les ' \
                   'JOIN teachers_lessons AS tl ' \
                   'ON les.number_class = tl.number_class AND les.char_class = tl.char_class ' \
                   f'WHERE id_teacher = {teacher_id} ' \
                   'AND (tl.group IN (0, 1, 3) AND tl.subject = les.subject ' \
                   'OR tl.group IN (2, 4) AND tl.subject = les.subject2);'
    if teacher is None and m.data.split('$')[0].split('_')[0] == 'tttea':
        text_request += 'SELECT last_name, first_name, patronymic FROM teachers ' \
                        f'WHERE id = {teacher_id}'

    request = session.transaction().execute(
        text_request,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    if teacher is None:
        if m.data.split('$')[0].split('_')[0] == 'tttea':
            t = request[1].rows[0]
            teacher = f'{t["last_name"]} {t["first_name"]} {t["patronymic"]}'
        else:
            teacher = m.message.text.split('\n')[0]

    sorted_weekdays = sorted(request[0].rows, key=lambda x: x['weekday'])
    weekdays = [constants.weekdays[w['weekday'] - 1]['abb_name'] for w in sorted_weekdays]
    str_weekdays = ''.join([str(w['weekday']) for w in sorted_weekdays])
    list_inline_btn = [(w, f'tttea_{teacher_id}_{w}_{str_weekdays}') for w in weekdays]

    text = teacher
    if request[0].rows == []:
        text += '\n\nРасписание не добавлено'
    else:
        text += '\n\nЧтобы узнать расписание, выберите день недели'

    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=6).add(*inline_buttons)

    if back is None:
        if m.message.reply_markup.keyboard[-1][0].callback_data.startswith('itea'):
            back = f'scltea_{teacher_id}'
        elif m.message.text.startswith('Список учителей, у которых добавлено расписание'):
            buttons = [(b.text, b.callback_data) for l in m.message.reply_markup.keyboard for b in l]
            back = get_back_button(m.message.reply_markup.keyboard, 'listtttea')
        else:
            back = f'itea_{teacher_id}'
    list_inline_btn = [('← Назад', back), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    if user['level'] != 'menu':
        edit_level(m, 'menu', session)


def del_subjects_and_classes(m, user, bot, session, *args, **kwargs):
    teacher_id = args[0]

    request = find_subjects_and_classes(m.text)
    subjects_and_classes = request['subjects_and_classes']
    set_of_subjects = request['set_of_subjects']
    set_of_only_subjects = request['set_of_only_subjects']

    if set_of_subjects:

        request = session.transaction().execute(
            f'SELECT subjects FROM teachers WHERE id = {teacher_id}',
            commit_tx=True,
            settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
        )

        if request[0].rows[0]['subjects']:
            original_subjects_of_teacher = set(request[0].rows[0]['subjects'].split(';'))
        else:
            original_subjects_of_teacher = set()

        unique_subjects = (set_of_subjects - {item[0] for item in subjects_and_classes}) | set_of_only_subjects
        subjects_of_teacher = original_subjects_of_teacher - unique_subjects
        subjects_of_teacher_str = ';'.join(subjects_of_teacher)
        if unique_subjects:
            subjects_and_classes = [item for item in subjects_and_classes if not item[0] in unique_subjects]

        values = []
        for subject, number, char, group in subjects_and_classes:
            if group is None:
                group = 0
            values.append(f'("{subject}", {number}, "{char}", {group})')

        text_request = ''
        if original_subjects_of_teacher != subjects_of_teacher:
            text_request = 'UPSERT INTO teachers (id, subjects)' \
                           f'VALUES ({teacher_id}, '
            if subjects_of_teacher_str:
                text_request += f'"{subjects_of_teacher_str}");'
            else:
                text_request += f'null);'

        text_request += f'DELETE FROM teachers_lessons WHERE id_teacher = {teacher_id} AND '
        conds = []
        if unique_subjects:
            unique_subjects_str = [f'"{item}"' for item in unique_subjects]
            conds.append(f'subject IN ({", ".join(unique_subjects_str)},)')
        if values:
            conds.append(f'(subject, number_class, char_class, group) IN ({", ".join(values)},)')
        text_request += f'({" OR ".join(conds)})'

        request = session.transaction().execute(
            text_request,
            commit_tx=True,
            settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
        )

        info_about_subjects = create_info_about_teachers_subjects(subjects_and_classes, set_of_subjects)
        text = Phrase.YES_DEL_TEACHERS_SUBJECTS.format(text=info_about_subjects)
        edit_level(m, 'menu', session)
    else:
        text = Phrase.NOT_FOUND_SUBJECT

    list_inline_btn = [('← Назад', f'scltea_{teacher_id}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

    send_text(bot, m, text, inline_kb)


def invitation_to_del_subjects_and_classes(m, user, bot, session, *args, **kwargs):
    teacher_id = m.data.split('$')[0].split('_')[1]
    teacher = m.message.text.split('\n')[0]
    text = Phrase.INVITATION_TO_DEL_SUBJECTS_AND_CLASSES.format(text=teacher)

    list_inline_btn = [('← Назад', f'scltea_{teacher_id}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    edit_level(m, f'dtttea_{teacher_id}', session)


def show_subjects_and_classes(m, user, bot, session, *args, **kwargs):
    teacher_id = m.data.split('$')[0].split('_')[1]

    request = session.transaction().execute(
        f'SELECT last_name, first_name, patronymic, subjects FROM teachers WHERE id = {teacher_id};' \
        f'SELECT * FROM teachers_lessons WHERE id_teacher = {teacher_id}',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    t = request[0].rows[0]
    text = f'{t["last_name"]} {t["first_name"]} {t["patronymic"]}'

    if request[0].rows[0]['subjects'] or request[1].rows:

        subjects_and_classes = []
        for row in request[1].rows:
            subjects_and_classes.append((row['subject'], row['number_class'], row['char_class'], row['group']))
        set_of_subjects = {item[0] for item in subjects_and_classes}
        if request[0].rows[0]['subjects']:
            set_of_subjects = set_of_subjects.union(request[0].rows[0]['subjects'].split(';'))
        set_of_classes = {item[1:] for item in subjects_and_classes}
        info_about_subjects = create_info_about_teachers_subjects(subjects_and_classes, set_of_subjects)

        if len(set_of_subjects) > 1:
            if len(set_of_classes) > 1:
                text += '\n\nПредметы и классы, в которых преподаёт:\n'
            elif len(set_of_classes) == 1:
                text += '\n\nПредметы и класс, в котором преподаёт:\n'
            else:
                text += '\n\nПредметы:\n'
        else:
            if len(set_of_classes) > 1:
                text += '\n\nПредмет и классы, в которых преподаёт:\n'
            elif len(set_of_classes) == 1:
                text += '\n\nПредмет и класс, в котором преподаёт:\n'
            else:
                text += '\n\nПредмет:\n'

        text += info_about_subjects

        inline_kb = types.InlineKeyboardMarkup().row(
            types.InlineKeyboardButton('🗓 Расписание', callback_data=f'tttea_{teacher_id}'))

    else:
        text += '\n\nОтсутствует информация о предметах и о классах, в которых преподаёт'
        inline_kb = types.InlineKeyboardMarkup()

    if user['admin']:
        inline_kb.row(types.InlineKeyboardButton('Добавить', callback_data=f'atttea_{teacher_id}'))
        if request[0].rows[0]['subjects'] or request[1].rows:
            inline_kb.row(types.InlineKeyboardButton('Удалить', callback_data=f'dtttea_{teacher_id}'))

    list_inline_btn = [('← Назад', f'itea_{teacher_id}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    if user['level'] != 'menu':
        edit_level(m, 'menu', session)


def create_info_about_teachers_subjects(subjects_and_classes, set_of_subjects):
    distribution_by_subject = {}
    for subject, number, char, group in sorted(subjects_and_classes, key=lambda x: (int(x[1]), x[2], int(x[3]))):
        if not subject in distribution_by_subject:
            distribution_by_subject[subject] = []
        str_class = f'{number}{char}'
        if group:
            if int(group) in (1, 2):
                str_class += f' ({group} гр.)'
            elif int(group) == 3:
                str_class += f' (м)'
            elif int(group) == 4:
                str_class += f' (д)'
        distribution_by_subject[subject].append(str_class)

    lines = [f'{subject}' for subject in set_of_subjects - set(distribution_by_subject.keys())]
    text = ''
    for subject, classes in distribution_by_subject.items():
        lines.append(f'{subject}: {", ".join(classes)}')
    lines.sort()

    text = '\n'.join(lines)
    if len(set_of_subjects) != 1:
        text = '– ' + text.replace('\n', '\n– ')
    return text


def find_subjects_and_classes_in_line(line, pattern_subj, pattern_cl):
    found_subjects = re.findall(pattern_subj, line)
    result_subjects = set()
    for found_subject in found_subjects:
        for subject in constants.subjects:
            if found_subject.lower() == clear_symbols(subject['name']) or found_subject.lower() in subject['var_names']:
                result_subjects.add(subject['name'])

    found_classes = re.finditer(pattern_cl, line)
    result_classes = set()
    for cl in found_classes:
        m = list(filter(lambda g: not g is None, cl.groups()))
        if len(m) == 2:
            result_classes.add((m[0], m[1].upper(), 0))
        else:
            group = m[2]
            if group.lower() in 'мюд':
                group = {'м': '3', 'ю': '3', 'д': '4'}[group.lower()]
            result_classes.add((m[0], m[1].upper(), group))

    return result_subjects, result_classes


def find_subjects_and_classes(text):
    list_subjects = []
    for subj in constants.subjects:
        list_subjects.append(clear_symbols(subj['name']))
        list_subjects.extend(subj['var_names'])
    str_subjects = '|'.join([re.escape(subj) for subj in list_subjects])
    pattern_subj = re.compile(str_subjects, flags=re.IGNORECASE)

    pattern_cl = re.compile(
        r'(?<!\d)([1-9]{1}|1[01]) *([а-г])(?!\w) *(?:\(([1-4мюд]) *(?:гр\.?|группа)?\)|\(?(?:(м)ал|(ю)нош|(д)ев)\)?|([1-4мюд]) *(?:гр(?:\.|(?!\w))|группа(?!\w)))?',
        flags=re.IGNORECASE)

    subjects_and_classes, set_of_subjects, set_of_only_subjects = set(), set(), set()

    for line in text.split('\n'):
        subjects, classes = find_subjects_and_classes_in_line(line, pattern_subj, pattern_cl)
        for subject in subjects:
            set_of_subjects.add(subject)
            if not classes:
                set_of_only_subjects.add(subject)
            for number, char, group in classes:
                subjects_and_classes.add((subject, number, char, group))

    result = {
        'subjects_and_classes': subjects_and_classes,
        'set_of_subjects': set_of_subjects,
        'set_of_only_subjects': set_of_only_subjects
    }
    return result


def add_subjects_and_classes(m, user, bot, session, *args, **kwargs):
    teacher_id = args[0]

    result = find_subjects_and_classes(m.text)
    subjects_and_classes, set_of_subjects = result['subjects_and_classes'], result['set_of_subjects']

    if set_of_subjects:

        request = session.transaction().execute(
            f'SELECT subjects FROM teachers WHERE id = {teacher_id}',
            commit_tx=True,
            settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
        )

        if request[0].rows[0]['subjects']:
            original_subjects_of_teacher = set(request[0].rows[0]['subjects'].split(';'))
        else:
            original_subjects_of_teacher = set()
        subjects_of_teacher = original_subjects_of_teacher | set_of_subjects
        subjects_of_teacher_str = ';'.join(subjects_of_teacher)

        values = []
        for subject, number, char, group in subjects_and_classes:
            values.append(f'({teacher_id}, "{subject}", {number}, "{char}", {group})')

        text_request = ''
        if original_subjects_of_teacher != subjects_of_teacher:
            text_request = 'UPSERT INTO teachers (id, subjects)' \
                           f'VALUES ({teacher_id}, "{subjects_of_teacher_str}");'
        if values:
            text_request += 'UPSERT INTO teachers_lessons (id_teacher, subject, number_class, char_class, group)' \
                            f'VALUES {", ".join(values)}'
        if text_request:
            request = session.transaction().execute(
                text_request,
                commit_tx=True,
                settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
            )

        info_about_subjects = create_info_about_teachers_subjects(subjects_and_classes, set_of_subjects)
        text = Phrase.YES_ADD_TEACHERS_SUBJECTS.format(text=info_about_subjects)
        edit_level(m, 'menu', session)
    else:
        text = Phrase.NOT_FOUND_SUBJECT

    list_inline_btn = [('← Назад', f'scltea_{teacher_id}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

    send_text(bot, m, text, inline_kb)


def invitation_to_add_subjects_and_classes(m, user, bot, session, *args, **kwargs):
    teacher_id = m.data.split('$')[0].split('_')[1]
    teacher = m.message.text.split('\n')[0]
    text = Phrase.INVITATION_TO_ADD_SUBJECTS_AND_CLASSES.format(text=teacher)

    list_inline_btn = [('← Назад', f'scltea_{teacher_id}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    edit_level(m, f'atttea_{teacher_id}', session)


def foto_timetable(m, user, bot, session, *args, **kwargs):
    request = session.transaction().execute(
        'SELECT file_id, seq_number FROM foto_timetable WHERE is_active = true ORDER BY seq_number',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )
    file_ids = [t['file_id'] for t in request[0].rows]

    text = 'Расписание учителей'

    media = [types.InputMediaPhoto(ph) for ph in file_ids]

    back = get_back_button(m.message.reply_markup.keyboard, 'listtttea')
    back += '$new'

    list_inline_btn = [('← Назад', back), ('🏠 В меню', 'menu$new')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=2).add(*inline_buttons)

    if hasattr(m, 'message'):
        m = m.message
    bot.send_media_group(m.chat.id, media)
    bot.send_message(m.chat.id, text, reply_markup=inline_kb)


def add_class_teacher(m, user, bot, session, *args, **kwargs):
    flag, parallel, char = m.data.split('$')[0].split('_')[1:4]
    if flag == 'да':
        from re import search
        teacher = search(Phrase.CLASS_TEACHER_NOT_IN_DB.format(**constants.dict_re), m.message.text)
        teacher = teacher.group(1)

        request = session.transaction().execute(
            'SELECT value FROM app WHERE key = "max_teacher_id"',
            commit_tx=True,
            settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
        )
        teacher_id = int(request[0].rows[0]["value"]) + 1

        last_name, first_name, patronymic = _clean_text(teacher, hyphen=True).split()
        text_request = f'UPSERT INTO teachers (id, last_name, first_name, patronymic, quit, number_class, char_class) ' \
                       f'VALUES ({teacher_id}, "{last_name}", "{first_name}", "{patronymic}", false, "{parallel}", "char");' \
                       f'UPSERT INTO classes (id, teacher, id_teacher) ' \
                       f'VALUES ({parallel}{"АБВГ".index(char) + 1}, "{teacher}", {teacher_id});' \
                       'UPSERT INTO app (key, value)' \
                       f'VALUES ("max_teacher_id", "{teacher_id}")'
        request = session.transaction().execute(
            text_request,
            commit_tx=True,
            settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
        )
        text = Phrase.ADD_CLASS_TEACHER.format(cl_teach=teacher, p=parallel, ch=char)
    else:
        text = Phrase.NOT_ADD_CLASS_TEACHER.format(p=parallel, ch=char)

    list_inline_btn = [
        ('Изменить номер кабинета', f'ncl_{parallel}_{char}'),
        ('Изменить классного руководителя', f'tcl_{parallel}_{char}'),
        ('Изменить количество учащихся', f'ccl_{parallel}_{char}')
    ]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    list_inline_btn = [('← Назад', f'cl_{parallel}_{char}'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)


def info_teacher(m, user, bot, session, *args, **kwargs):
    if 'teacher_id' in kwargs:
        teacher_id = kwargs['teacher_id']
        back = kwargs['back']
    else:
        teacher_id = m.data.split('$')[0].split('_')[1]
        back = None

    text_request = f'SELECT * FROM classes VIEW id_teacher_index WHERE id_teacher = {teacher_id};' \
                   f'SELECT EXISTS (SELECT * FROM teachers_lessons WHERE id_teacher = {teacher_id}) AS res;'

    if 'teacher' in kwargs:
        teacher = kwargs['teacher']
    else:
        text_request += f'SELECT * FROM teachers WHERE id = {teacher_id};'
        teacher = None

    request = session.transaction().execute(
        text_request,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    if teacher or request[2].rows:
        if teacher is None:
            teacher = request[2].rows[0]
        text = f'{teacher["last_name"]} {teacher["first_name"]} {teacher["patronymic"]}'
        if request[0].rows:
            classes = [f'{cl["number"]}{cl["char"]}' for cl in request[0].rows]
            post_class = 'Классный руководитель '
            if len(classes) == 1:
                post_class += f'{classes[0]} класса'
            else:
                post_class += f'{", ".join(classes[:-1])} и {classes[-1]} классов'
            post_class = [post_class]
        else:
            post_class = []

        if teacher['posts']:
            posts = teacher['posts'].split(';')
        else:
            posts = []
        posts = sorted(post_class + posts)
        if posts:
            text += '\n'
            if len(posts) == 1:
                text += f'\n{posts[0]}'
            else:
                for post in posts: text += f'\n– {post}'

        if teacher['subjects'] and not 'Учитель начальных классов' in posts:
            subjs = sorted(teacher['subjects'].split(';'))
            text += f'\n\nПредмет{"ы" if len(subjs) > 1 else ""}:'
            if len(subjs) == 1:
                text += f'\n{subjs[0]}'
            else:
                for subj in subjs: text += f'\n– {subj}'

        if teacher['number_cabinet']:
            text += f'\n\nКабинет: {teacher["number_cabinet"]}'

        if teacher['birthday']:
            from time import strptime
            birthday = strptime(teacher['birthday'], '%d.%m.%Y')
            month_birthday = constants.months[birthday.tm_mon - 1]['dec']
            text += f'\n\nДень рождения: {birthday.tm_mday} {month_birthday}'
    else:
        text = Phrase.NOT_TEACHER_IN_DB

    inline_kb = types.InlineKeyboardMarkup(row_width=2)
    if teacher or request[2].rows:
        if request[1].rows[0]['res']:
            callback_data = f'fitttea_{teacher_id}'
            inline_kb.row(types.InlineKeyboardButton('🗓 Расписание', callback_data=callback_data))
        if request[0].rows:
            list_inline_btn = [(f'{cl["number"]}{cl["char"]} класс', f'cl_{cl["number"]}_{cl["char"]}') for cl in
                               request[0].rows]
            inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
            inline_kb.add(*inline_buttons)
        if request[1].rows[0]['res'] and not 'Учитель начальных классов' in posts or user['admin']:
            callback_data = f'scltea_{teacher_id}'
            inline_kb.row(types.InlineKeyboardButton('Предметы и классы', callback_data=callback_data))

    if back is None:
        is_list_class_teachers = re.match(Phrase.LIST_CLASS_TEACHERS.format(**constants.dict_re), m.message.text)
        if m.message.text.startswith('Список учителей:\n'):
            buttons = [(b.text, b.callback_data) for l in m.message.reply_markup.keyboard for b in l]
            back = get_back_button(m.message.reply_markup.keyboard, 'listtea')
        elif is_list_class_teachers:
            parallel, char = is_list_class_teachers.groups()[:2]
            back = f'listcltea_{parallel}_{char}'
        else:
            back = 'listtea_0'

    list_inline_btn = [('← Назад', back), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    if user['level'] != 'menu':
        edit_level(m, 'menu', session)


def create_list_teachers(teachers_list, offset, teacher_data, next_data):
    ts = sorted(teachers_list[:limit_teachers], key=lambda t: (t['last_name'], t['first_name'], t['patronymic']))
    text = [f'{i + offset + 1}. {ts[i]["last_name"]} {ts[i]["first_name"]} {ts[i]["patronymic"]}' for i in
            range(len(ts))]
    text = '\n'.join(text)

    list_inline_btn = []
    for i in range(len(ts)):
        teacher_id = ts[i]['id']
        button_info = f'{teacher_data}_{teacher_id}'
        list_inline_btn.append((f'{i + offset + 1}', button_info))
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=5).add(*inline_buttons)

    l = offset - limit_teachers
    if l < 0 and offset > 0:
        l = 0
    elif l < 0 and offset == 0:
        l = -1

    if len(teachers_list) < limit_teachers + 1:
        r = -1
    else:
        r = offset + limit_teachers

    list_inline_btn = []
    if l != -1: list_inline_btn.append(('←', f'{next_data}_{l}'))
    if r != -1: list_inline_btn.append(('→', f'{next_data}_{r}'))
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    return text, inline_kb


def tt_list_teachers(m, user, bot, session, *args, **kwargs):
    list_teachers(m, user, bot, session, *args, t='tt', **kwargs)


def info_list_teachers(m, user, bot, session, *args, **kwargs):
    list_teachers(m, user, bot, session, *args, t='info', **kwargs)


def list_teachers(m, user, bot, session, *args, **kwargs):
    if hasattr(m, 'message'):
        offset = int(m.data.split('$')[0].split('_')[1])
    else:
        offset = 0
    if kwargs['t'] == 'info':
        text_request = 'SELECT id, last_name, first_name, patronymic FROM teachers ' \
                       'WHERE quit = false ORDER BY last_name, first_name, patronymic ' \
                       f'LIMIT {limit_teachers + 1} OFFSET {offset};'
    else:
        text_request = 'SELECT id, last_name, first_name, patronymic FROM teachers AS t ' \
                       'LEFT SEMI JOIN teachers_lessons AS tl ' \
                       'ON tl.id_teacher = t.id ' \
                       'WHERE t.quit = false ' \
                       'ORDER BY last_name, first_name, patronymic ' \
                       f'LIMIT {limit_teachers + 1} OFFSET {offset};'
    request = session.transaction().execute(
        text_request,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    if request[0].rows:
        if kwargs['t'] == 'info':
            text, inline_kb = create_list_teachers(request[0].rows, offset, 'itea', 'listtea')
            text = 'Список учителей:\n' + text
        else:
            text, inline_kb = create_list_teachers(request[0].rows, offset, 'tttea', 'listtttea')
            text = 'Список учителей, у которых добавлено расписание:\n' + text
    else:
        if kwargs['t'] == 'info':
            text = 'Учителя ещё не добавлены'
        else:
            text = 'Ни у одного учителя не добавлено расписание'
        inline_kb = types.InlineKeyboardMarkup()

    if kwargs['t'] == 'info':
        inline_kb.row(types.InlineKeyboardButton('🔎 Найти учителя', callback_data='infofindtea'))
        if user['admin']:
            inline_kb.row(types.InlineKeyboardButton('Добавить учителя', callback_data='atea'))
    if kwargs['t'] == 'tt':
        inline_kb.row(types.InlineKeyboardButton('🔎 Найти учителя', callback_data='ttfindtea'))
        inline_kb.row(types.InlineKeyboardButton('🖼 Расписание в виде фотографий', callback_data='ftttea'))

    list_inline_btn = [('← Назад', 'tea'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)

    if user['level'] != 'menu':
        edit_level(m, 'menu', session)


def call(m, user, bot, session, *args, **kwargs):
    list_inline_btn = [('📋 Список учителей', 'listtea_0'), ('🗓 Расписание учителей', 'listtttea_0')]

    if user['admin']:
        text = 'Выберите, что желаете узнать, или добавьте учителя'
        list_inline_btn.append(('Добавить учителя', 'atea'))
    else:
        text = 'Выберите, что желаете узнать'

    list_inline_btn.append(('🏠 В меню', 'menu'))

    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    send_text(bot, m, text, inline_kb)

    if user['level'] != 'menu':
        edit_level(m, 'menu', session)


def add(m, user, bot, session, *args, **kwargs):
    if m.message.text.startswith('Список учителей'):
        back = get_back_button(m.message.reply_markup.keyboard, 'listtea')
    else:
        back = 'tea'
    list_inline_btn = [('← Назад', back), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup().add(*inline_buttons)

    send_text(bot, m, Phrase.ADD_TEA, inline_kb)

    edit_level(m, 'atea', session)


def _clean_text(t, hyphen=False):
    t = t.replace('\n', ' ')
    if hyphen:
        s = ' ёЁ-'
    else:
        s = ' ёЁ'
    text = ''.join(filter((lambda ch: ch in s or 1040 <= ord(ch) <= 1103 or ch.isdigit()), t.strip()))
    return text


def _find_subjs(text):
    from re import match
    subjs = []
    posts = []
    classes = []
    number_class = 'null'
    lines = text.split(';')
    for line in lines:
        if not line:
            continue
        number = match(r'(\d{3})', line)
        if number:
            number_class = int(number.group(1))
            continue
        clean_line = clear_symbols(line).split()
        for sub in constants.subjects:
            if clear_symbols(sub['name']) in clean_line or any(
                    [clear_symbols(var) in clean_line for var in sub['var_names']]):
                subjs.append(sub['name'])
                break
        else:
            cl = match(r'(1?[0-9]{1}) *([А-Г]{1})', line.upper())
            if cl:
                parallel = cl.group(1)
                char = cl.group(2)
                classes.append((parallel, char))
            else:
                post = line.strip()
                post = post[0].upper() + post[1:]
                if 'началк' in post.lower():
                    post = 'Учитель начальных классов'
                elif any([p in post.lower() for p in ('одод', 'дополнительное образование', 'допобр', 'доп')]):
                    post = 'Педагог дополнительного образования'
                elif 'организатор' in post.lower():
                    post = 'Педагог-организатор'
                posts.append(post)
    subjs = list(set(subjs))
    posts = list(set(posts))
    classes = list(set(classes))
    return subjs, posts, number_class, classes


def writing_new(m, user, bot, session, *args, **kwargs):
    lines = m.text.split('\n')
    error = False
    text = ''

    fio = _clean_text(lines[0], hyphen=True).split()
    if len(fio) < 3:
        error = True
        text += 'ФИО учителя должно состоять из фамилии, имени и отчества.\n'
    else:
        last_name, first_name, patronymic = fio[:3]
        last_name, first_name, patronymic = last_name.title(), first_name.title(), patronymic.title()
        fio = f'{last_name} {first_name} {patronymic}'

    if len(lines) > 1:
        subjs, posts, number_cabinet, classes = _find_subjs(';'.join(lines[1:]))
        if not (subjs or posts or classes) and number_cabinet == 'null':
            error = True
            text += 'Не удалось распознать предметы или должности, которые ведёт или занимает учитель, или номер его кабинета, или классное руководство\n.'
    else:
        subjs, posts, number_cabinet, classes = [], [], 'null', []

    list_inline_btn = []

    if not error:
        request = session.transaction().execute(
            'SELECT value FROM app WHERE key = "max_teacher_id"',
            commit_tx=True,
            settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
        )
        teacher_id = int(request[0].rows[0]["value"]) + 1

        subjs = ';'.join(subjs)
        posts = ';'.join(posts)
        parallels = ';'.join([c[0] for c in classes])
        chars = ';'.join([c[1] for c in classes])
        values = f'({teacher_id}, "{last_name}", "{first_name}", "{patronymic}", false, {number_cabinet}' + \
                 (f', "{subjs}"' if subjs else '') + (f', "{posts}"' if posts else '') + \
                 (f', "{parallels}"' if parallels else '') + (f', "{chars}"' if chars else '') + ')'

        text_requests = f'UPSERT INTO teachers (id, last_name, first_name, patronymic, quit, number_cabinet' + \
                        (', subjects' if subjs else '') + (', posts' if posts else '') + \
                        (', number_class' if parallels else '') + (
                            ', char_class' if chars else '') + f') VALUES {values};'

        if classes:
            values = ', '.join(
                f'({parallel}{"АБВГ".index(char) + 1}, "{fio}", {teacher_id})' for parallel, char in classes)
            text_requests += f'UPSERT INTO classes (id, teacher, id_teacher) VALUES {values};'

        text_requests += 'UPSERT INTO app (key, value)' \
                         f'VALUES ("max_teacher_id", "{teacher_id}")'
        request = session.transaction().execute(
            text_requests,
            commit_tx=True,
            settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
        )

        subjs = subjs.replace(';', '; ')
        posts = posts.replace(';', '; ')
        classes = '; '.join(c[0] + c[1] for c in classes)
        text = f'Добавлен учитель:\n{last_name} {first_name} {patronymic}'
        if subjs: text += f'\nПредмет{"ы" if len(subjs.split(";")) > 1 else ""}: {subjs}'
        if posts: text += f'\nДолжност{"и" if len(posts.split(";")) > 1 else "ь"}: {posts}'
        if number_cabinet != 'null': text += f'\nКабинет: {number_cabinet}'
        if classes: text += f'\nКласс{"ы" if len(classes.split(";")) > 1 else ""}: {classes}'
        button_edit = f'etea_{teacher_id}'
        list_inline_btn += [
            ('Информация об учителе', f'itea_{teacher_id}'),
            ('Редактировать', button_edit),
            ('Добавить учителя', 'atea')
        ]
    else:
        text += 'Введите всю информацию заново'

    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    list_inline_btn = [('← Назад', 'tea'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    if not error:
        edit_level(m, 'menu', session)
