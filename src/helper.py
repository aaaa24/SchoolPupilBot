from telebot import types

from utils import send_text, edit_level
from constants import Phrase


def get_help(m, user, bot, session, *args, **kwargs):
    inline_kb = types.InlineKeyboardMarkup()
    inline_kb.row(types.InlineKeyboardButton(text='Инструкция',
                                             url='https://telegra.ph/Instrukciya-po-polzovaniyu-botom-SHkolnyj-pomoshchnik-02-06'))
    inline_kb.row(types.InlineKeyboardButton(text='Форма обратной связи',
                                             url='https://forms.yandex.ru/u/65ca60aa02848fc53123c61f'))

    list_inline_btn = [('← Назад', 'inf'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb.row(*inline_buttons)

    send_text(bot, m, Phrase.HELP, inline_kb)
    if user['level'] != 'menu':
        edit_level(m, 'menu', session)
