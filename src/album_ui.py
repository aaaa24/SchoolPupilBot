import time

import constants
from constants import Phrase
from messenger_context import get_messenger_from_kwargs
from messengers import Messenger, ScreenState, force_new_screen, get_client
from photo_album import ChangesAlbum, TimetablePhotoAlbum, photos_to_add
from utils import create_inline_kb, edit_level, suffixes, try_delete_message

NO_SCOPE = '-'


class AlbumSection:
    code = None

    def album(self, session, scope):
        raise NotImplementedError

    def title(self, scope):
        raise NotImplementedError

    def empty_title(self, scope):
        raise NotImplementedError

    def back(self, scope):
        raise NotImplementedError


class ChangesSection(AlbumSection):
    # scope — дата в формате ДД.ММ.ГГГГ, как в callback_data
    code = 'chtt'

    def album(self, session, scope):
        return ChangesAlbum(session, '-'.join(scope.split('.')[::-1]))

    def _date_args(self, scope):
        time_date = time.strptime(scope, '%d.%m.%Y')
        return {
            'acc': constants.weekdays[time_date.tm_wday]['accusative'],
            'day': time_date.tm_mday,
            'dec': constants.months[time_date.tm_mon - 1]['dec'],
            'year': time_date.tm_year,
        }

    def title(self, scope):
        return Phrase.CHANGES_TT_WEEKDAY.format(**self._date_args(scope))

    def empty_title(self, scope):
        return Phrase.NOT_CHANGES_TT_WEEKDAY.format(**self._date_args(scope))

    def back(self, scope):
        return f'chtt_{scope}'


class TimetablePhotoSection(AlbumSection):
    code = 'fttea'

    def album(self, session, scope):
        return TimetablePhotoAlbum(session)

    def title(self, scope):
        return Phrase.TIMETABLE_PHOTO

    def empty_title(self, scope):
        return Phrase.NOT_TIMETABLE_PHOTO

    def back(self, scope):
        return 'listtttea_0'


sections = {section.code: section for section in (ChangesSection(), TimetablePhotoSection())}


def callback_data(section, scope, op, arg=None):
    parts = ['alb', section.code, scope, op]
    if arg is not None:
        parts.append(str(arg))
    return '_'.join(parts)


def _screen_state(mm):
    if hasattr(mm, 'message'):
        return ScreenState(chat_id=mm.message.chat.id, message_id=mm.message.id,
                           content_type=mm.message.content_type)
    return ScreenState(chat_id=mm.chat.id)


def _exit_suffix(messenger):
    # Telegram не превращает фотографию в текст, поэтому экран карусели при выходе удаляется
    return '$sdel' if Messenger(messenger) is Messenger.TELEGRAM else ''


def _force_new(mm):
    return hasattr(mm, 'data') and force_new_screen(mm.data)


def render(bot, mm, text, media, inline_kb):
    if hasattr(mm, 'data'):
        suffixes(bot, mm, text, inline_kb)

    client = get_client(bot)
    state = _screen_state(mm)

    # Telegram не умеет превращать сообщение с фотографией в текстовое, поэтому старый экран убирается
    if not media and state.message_id is not None and state.content_type == 'photo' \
            and client.platform is Messenger.TELEGRAM:
        try_delete_message(bot, state.chat_id, state.message_id)
        state = ScreenState(chat_id=state.chat_id)

    return client.render_screen(state, text, media, reply_markup=inline_kb, force_new=_force_new(mm))


def send_album(bot, mm, chat_id, album, text, inline_kb, messenger, logger):
    # Все фотографии альбома одним экраном: mm is None — личное сообщение рассылки
    media = album.media(messenger, logger)
    items = [item for _, item in media]

    if mm is None:
        result = get_client(bot).send_message_to_user(chat_id, text, media=items, reply_markup=inline_kb)
    else:
        result = render(bot, mm, text, items, inline_kb)

    album.save_media(messenger, media)
    return result


def _screen_with_photo(bot, mm, album, text, list_inline_btn, messenger, logger, position, items):
    media = album.media(messenger, logger, rows=[items[position - 1]])
    render(bot, mm, text, [item for _, item in media], create_inline_kb(list_inline_btn))
    album.save_media(messenger, media)


def edit_screen(m, user, bot, session, *args, **kwargs):
    section, scope, position = args[0], args[1], args[2]
    logger = kwargs['logger']
    messenger = get_messenger_from_kwargs(kwargs)

    album = section.album(session, scope)
    items = album.items()
    count = len(items)

    if user['level'] != 'menu':
        edit_level(m, 'menu', session)

    if not count:
        list_inline_btn = [
            ('➕ Добавить фотографии', callback_data(section, scope, 'add')),
            [('← Назад', section.back(scope)), ('🏠 В меню', 'menu')],
        ]
        render(bot, m, section.empty_title(scope), [], create_inline_kb(list_inline_btn))
        return

    position = min(max(position, 1), count)
    text = f'{section.title(scope)}\n{Phrase.ALBUM_POSITION.format(number=position, count=count)}'
    exit_suffix = _exit_suffix(messenger)

    list_inline_btn = []
    if count > 1:
        list_inline_btn.append([('←', callback_data(section, scope, 'ed', position - 1 or count)),
                                ('→', callback_data(section, scope, 'ed', position + 1 if position < count else 1))])
        list_inline_btn.append([('↑ Выше', callback_data(section, scope, 'up', position)),
                                ('↓ Ниже', callback_data(section, scope, 'dn', position))])
    list_inline_btn.append(('🗑 Удалить эту', callback_data(section, scope, 'd1', position)))
    list_inline_btn.append([('➕ Добавить', callback_data(section, scope, 'add')),
                            ('🗑 Удалить все', callback_data(section, scope, 'dal'))])
    list_inline_btn.append([('← Назад', section.back(scope) + exit_suffix), ('🏠 В меню', 'menu' + exit_suffix)])

    _screen_with_photo(bot, m, album, text, list_inline_btn, messenger, logger, position, items)


def move_photo(m, user, bot, session, *args, **kwargs):
    section, scope, position, delta = args[0], args[1], args[2], args[3]
    album = section.album(session, scope)
    edit_screen(m, user, bot, session, section, scope, album.move(position, delta), **kwargs)


def confirm_delete_one(m, user, bot, session, *args, **kwargs):
    section, scope, position = args[0], args[1], args[2]
    logger = kwargs['logger']
    messenger = get_messenger_from_kwargs(kwargs)

    album = section.album(session, scope)
    items = album.items()
    count = len(items)
    if not count:
        edit_screen(m, user, bot, session, section, scope, 1, **kwargs)
        return

    position = min(max(position, 1), count)
    text = f'{section.title(scope)}\n{Phrase.ALBUM_CONFIRM_DELETE_ONE.format(number=position, count=count)}'
    list_inline_btn = [
        [('Да', callback_data(section, scope, 'dd1', position)),
         ('Нет', callback_data(section, scope, 'ed', position))],
        [('🏠 В меню', 'menu' + _exit_suffix(messenger))],
    ]

    _screen_with_photo(bot, m, album, text, list_inline_btn, messenger, logger, position, items)


def delete_one(m, user, bot, session, *args, **kwargs):
    section, scope, position = args[0], args[1], args[2]
    album = section.album(session, scope)
    album.delete(position)
    edit_screen(m, user, bot, session, section, scope, position, **kwargs)


def confirm_delete_all(m, user, bot, session, *args, **kwargs):
    section, scope = args[0], args[1]
    logger = kwargs['logger']
    messenger = get_messenger_from_kwargs(kwargs)

    album = section.album(session, scope)
    items = album.items()
    count = len(items)
    if not count:
        edit_screen(m, user, bot, session, section, scope, 1, **kwargs)
        return

    text = f'{section.title(scope)}\n{Phrase.ALBUM_CONFIRM_DELETE_ALL.format(count=count)}'
    list_inline_btn = [
        [('Да', callback_data(section, scope, 'ddal')),
         ('Нет', callback_data(section, scope, 'ed', 1))],
        [('🏠 В меню', 'menu' + _exit_suffix(messenger))],
    ]

    _screen_with_photo(bot, m, album, text, list_inline_btn, messenger, logger, 1, items)


def delete_all(m, user, bot, session, *args, **kwargs):
    section, scope = args[0], args[1]
    section.album(session, scope).delete_all()
    edit_screen(m, user, bot, session, section, scope, 1, **kwargs)


def ask_photos(m, user, bot, session, *args, **kwargs):
    section, scope = args[0], args[1]
    messenger = get_messenger_from_kwargs(kwargs)

    text = Phrase.ALBUM_ASK_PHOTO_MAX if messenger is Messenger.MAX else Phrase.ALBUM_ASK_PHOTO
    list_inline_btn = [[('← Назад', callback_data(section, scope, 'ed', 1)), ('🏠 В меню', 'menu')]]

    render(bot, m, text, [], create_inline_kb(list_inline_btn))
    edit_level(m, callback_data(section, scope, 'add'), session)


def accept_photos(m, user, bot, session, *args, **kwargs):
    # Обработка уровня alb_<раздел>_<область>_add: пришли фотографии для альбома
    code, scope = args[0].split('_')[:2]
    section = sections[code]
    messenger = get_messenger_from_kwargs(kwargs)

    photos = photos_to_add(m, messenger)
    if not photos:
        list_inline_btn = [[('← Назад', callback_data(section, scope, 'ed', 1)), ('🏠 В меню', 'menu')]]
        bot.send_message(m.chat.id, Phrase.ALBUM_NEED_PHOTO, reply_markup=create_inline_kb(list_inline_btn))
        return

    album = section.album(session, scope)
    added = album.add(bot, photos)
    text = Phrase.ALBUM_PHOTO_ADDED.format(added=added, count=album.count())

    # В MAX все фотографии приходят одним сообщением, поэтому режим добавления сразу закрывается,
    # а в Telegram он держится, пока администратор не нажмёт «Готово»
    if messenger is Messenger.MAX:
        edit_level(m, 'menu', session)
        next_button = ('🖼 К фотографиям', callback_data(section, scope, 'ed', 1))
    else:
        next_button = ('✅ Готово', callback_data(section, scope, 'ed', 1))

    list_inline_btn = [next_button, [('🏠 В меню', 'menu')]]
    bot.send_message(m.chat.id, text, reply_markup=create_inline_kb(list_inline_btn))
