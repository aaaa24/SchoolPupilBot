import ydb
from telebot import types

from utils import send_text, edit_level
from constants import Phrase


def call(m, user, bot, session, *args, **kwargs):
    if user['send_news']:
        text = Phrase.STATUS_SUBSCR.format(onoff='✅', subscr='подписаны на рассылку', endstatus='')
        list_inline_btn = [('❌ Отписаться от новостей', 'news_off')]
    else:
        text = Phrase.STATUS_SUBSCR.format(onoff='❌', subscr='не подписаны на рассылку',
                                           endstatus='.\n\nВы можете подписаться на новости. В таком случае бот будет каждый час проверять наличие новых записей на страницы школы во ВКонтакте и, если они есть, будет присылать их Вам')
        list_inline_btn = [('✅ Подписаться на новости', 'news_on')]

    list_inline_btn.append(('🏠 В меню', 'menu'))
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    send_text(bot, m, text, inline_kb)
    if user['level'] != 'menu':
        edit_level(m, 'menu', session)


def on(m, user, bot, session, *args, **kwargs):
    if user['send_news']:
        text = Phrase.STATUS_SUBSCR.format(onoff='✅', subscr='уже подписаны на рассылку', endstatus='')
    else:
        request = session.transaction().execute(
            f'UPSERT INTO users (id, send_news) VALUES ({m.json["from"]["id"]}, True);',
            commit_tx=True,
            settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
        )
        text = Phrase.STATUS_SUBSCR.format(onoff='✅', subscr='успешно подписались на рассылку', endstatus='')

    list_inline_btn = [('❌ Отписаться от новостей', 'news_off'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    send_text(bot, m, text, inline_kb)


def off(m, user, bot, session, *args, **kwargs):
    if not user['send_news']:
        text = Phrase.STATUS_SUBSCR.format(onoff='❌', subscr='уже отписаны от рассылки', endstatus='')
    else:
        request = session.transaction().execute(
            f'UPSERT INTO users (id, send_news) VALUES ({m.json["from"]["id"]}, False);',
            commit_tx=True,
            settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
        )
        text = Phrase.STATUS_SUBSCR.format(onoff='❌', subscr='успешно отписались от рассылки', endstatus='')

    list_inline_btn = [('✅ Подписаться на новости', 'news_on'), ('🏠 В меню', 'menu')]
    inline_buttons = [types.InlineKeyboardButton(t[0], callback_data=t[1]) for t in list_inline_btn]
    inline_kb = types.InlineKeyboardMarkup(row_width=1).add(*inline_buttons)

    send_text(bot, m, text, inline_kb)
