import os
import time
from concurrent.futures import ThreadPoolExecutor
from re import search, sub

import requests
import telebot
import ydb
from telebot import types

from messenger_context import get_users_table
from messengers import TELEGRAM_CAPTION_LIMIT, MediaItem, Messenger
from utils import msk_time


def except_429(f, n=1, **k):
    print(429, n)
    if n == 5:
        try:
            eval(f)
        except:
            pass
        return
    try:
        eval(f)
    except telebot.apihelper.ApiTelegramException as e:
        print(e)
        if 'Error code: 429' in str(e):
            time.sleep(4)
            except_429(f, n + 1, **k)
        else:
            print(e)
    print('End 429', n)


code = '''var all_walls = API.wall.get({"domain": "%s", "count": 24}).items;
var walls = [];
var i = 0;
while (i < all_walls.length) {
	if (all_walls[i].id > "%s") {
		var arr = all_walls[i];
		if (parseInt(all_walls[i].signer_id) != 0) {
			arr.push(API.users.get({"user_ids": all_walls[i].signer_id, "name_case": "gen"})[0]);}
		walls.push(arr);
		}
	i = i + 1;}
return walls;'''

hashtags = ['ДвижениеПервых', 'ДвижениеПервыхСПб', 'ПервыеПушкин', 'ПервичкаПервых', 'ДвижениеПервыхСПб',
            'ПервыеПомогают']


def send_pervye(bot, text, photos):
    print('Отправка новости в канал Первых')
    if not photos:
        except_429(
            "k['bot'].send_message(k['chat'], k['text'], parse_mode = 'HTML', disable_web_page_preview = True)",
            bot=bot, chat=os.getenv('CHANNEL_PERVYE'), text=text
        )
    elif len(photos) == 1:
        if len(text) > 1023:
            except_429(
                "k['bot'].send_photo(k['chat'], photo = k['photo'])",
                bot=bot, chat=os.getenv('CHANNEL_PERVYE'), photo=photos[0]
            )
            except_429(
                "k['bot'].send_message(k['chat'], k['text'], parse_mode = 'HTML', disable_web_page_preview = True)",
                bot=bot, chat=os.getenv('CHANNEL_PERVYE'), text=text
            )
        else:
            except_429(
                "k['bot'].send_photo(k['chat'], caption = k['text'], photo = k['photo'], parse_mode = 'HTML')",
                bot=bot, chat=os.getenv('CHANNEL_PERVYE'), text=text, photo=photos[0]
            )
    else:
        if len(text) <= 1023:
            media = [telebot.types.InputMediaPhoto(photos[0], caption=text, parse_mode='HTML')]
            media.extend([telebot.types.InputMediaPhoto(ph) for ph in photos[1:]])
        else:
            media = [telebot.types.InputMediaPhoto(ph) for ph in photos]

        except_429(
            "k['bot'].send_media_group(k['chat'], k['media'])",
            bot=bot, chat=os.getenv('CHANNEL_PERVYE'), media=media
        )
        if len(text) > 1023:
            except_429(
                "k['bot'].send_message(k['chat'], k['text'], parse_mode = 'HTML', disable_web_page_preview = True)",
                bot=bot, chat=os.getenv('CHANNEL_PERVYE'), text=text
            )
    print('Отправка новости в канал Первых успешно выполнена')


def _execute(session, query):
    return session.transaction().execute(
        query,
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )


def _last_news_key(messenger):
    return f'last_news_id_{Messenger(messenger).value}'


def _get_last_news_id(messenger, session):
    result = _execute(session, f'SELECT value FROM app WHERE key = "{_last_news_key(messenger)}";')
    return int(result[0].rows[0]['value']) if result[0].rows else 0


def _save_last_news_id(messenger, last_news_id, session):
    _execute(session, f'UPSERT INTO app (key, value) VALUES ("{_last_news_key(messenger)}", "{last_news_id}");')


def _get_subscribers(messenger, session):
    result = _execute(session, f'SELECT id FROM {get_users_table(messenger)} WHERE send_news = true;')
    return [row['id'] for row in result[0].rows]


def _get_news(last_news_id, logger):
    response = requests.post(
        'https://api.vk.com/method/execute',
        params={'access_token': os.getenv('VK_ACCESS_TOKEN'), 'lang': 'ru',
                'code': code % (os.getenv('VK_DOMAIN'), last_news_id), 'v': 5.131}
    )
    payload = response.json()
    logger.debug('Получен ответ ВКонтакте', extra={'count': len(payload['response'])})

    news = payload['response']
    news.sort(key=lambda writing: writing['date'])
    return news


def _link_mentions(text):
    def link(match):
        target = match.group(1)
        url = target if target.startswith('http') else f'https://vk.ru/{target}'
        return f'<a href="{url}">{match.group(2)}</a>'

    return sub(r'\[(https?://[^\s|\]]+|[A-Za-z][A-Za-z0-9_.]*)\|([^\]]+)\]', link, text)


def _build_news(writing):
    date = time.strftime('%H:%M %d.%m.%Y', msk_time(writing['date']))

    if '0' in writing:
        signer = f' от {writing["0"]["first_name"]} {writing["0"]["last_name"]}'
    else:
        signer = ''

    url = f'https://vk.com/wall{writing["owner_id"]}_{writing["id"]}'
    text = f'<a href="{url}">Новость{signer}</a> ({date})\n\n'
    text += writing['text'].rstrip()
    text_pervye = writing['text'].rstrip()
    text_pervye += f'\n\n<a href="{url}">Прочитать во ВКонтакте</a>'

    photos = []
    videos = 0
    attachments = writing['attachments'].copy()

    if 'copy_history' in writing:
        for copied in writing['copy_history']:
            date = time.strftime('%H:%M %d.%m.%Y', msk_time(copied['date']))

            url = f'https://vk.com/wall{copied["owner_id"]}_{copied["id"]}'
            text += f'\n\n<a href="{url}">Пересланная новость</a> ({date})\n\n'
            text = text.replace('\n' * 4, '\n' * 2)
            text += copied['text'].rstrip()
            text_pervye += '\n\n'
            text_pervye += copied['text'].rstrip()

            if 'attachments' in copied:
                attachments.extend(copied['attachments'])

    for attachment in attachments:
        if attachment['type'] == 'photo':
            photos.append(max(attachment['photo']['sizes'], key=lambda s: s['height'])['url'])
        if attachment['type'] == 'video':
            videos += 1

    if videos:
        note = f'\n\n<i>К новости прикреплен{"а видеозапись" if videos == 1 else "ы видеозаписи"}</i>'
        text += note
        text_pervye += note

    return _link_mentions(text), _link_mentions(text_pervye), photos


def _download_photo(url, logger):
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
    except Exception:
        logger.exception('Не удалось скачать фотографию новости', extra={'url': url})
        return None

    return (url.split('?')[0].rsplit('/', 1)[-1], response.content, response.headers.get('Content-Type'))


def _download_photos(urls, logger):
    if not urls:
        return []

    with ThreadPoolExecutor(max_workers=min(len(urls), 8)) as executor:
        photos = list(executor.map(lambda url: _download_photo(url, logger), urls))
    return [photo for photo in photos if photo]


def _is_url_download_error(error):
    text = str(error)
    return 'HTTP URL' in text or 'WEBPAGE_CURL_FAILED' in text or 'wrong file identifier' in text


def _photos_media(urls, photos, logger):
    if urls and not photos:
        photos.extend(_download_photos(urls, logger))
    return [MediaItem(data=data, filename=filename, content_type=content_type)
            for filename, data, content_type in photos]


def _split_text(text, limit):
    if len(text) <= limit:
        return [text]

    parts = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind('\n', 0, limit + 1)
        if cut == -1:
            cut = rest.rfind(' ', 0, limit + 1)
        if cut == -1:
            cut = limit
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()

    if rest:
        parts.append(rest)
    return parts


def _menu_keyboard():
    inline_kb = types.InlineKeyboardMarkup()
    inline_kb.row(types.InlineKeyboardButton('🏠 В меню', callback_data='menu$new'))
    return inline_kb


def _send_to_user(bot, user_id, text, media, inline_kb):
    if bot.platform == Messenger.MAX:
        parts = _split_text(text, Messenger.MAX.text_limit)
        for number, part in enumerate(parts):
            bot.send_message_to_user(user_id, part,
                                     media=media if number == 0 else None,
                                     reply_markup=inline_kb if number == len(parts) - 1 else None,
                                     parse_mode='HTML')
        return

    if media and len(text) <= TELEGRAM_CAPTION_LIMIT:
        bot.send_message_to_user(user_id, text, media=media, reply_markup=inline_kb, parse_mode='HTML')
        return

    if media:
        bot.send_message_to_user(user_id, '', media=media)

    parts = _split_text(text, Messenger.TELEGRAM.text_limit)
    for number, part in enumerate(parts):
        bot.send_message_to_user(user_id, part,
                                 reply_markup=inline_kb if number == len(parts) - 1 else None,
                                 parse_mode='HTML', disable_web_page_preview=True)


def _notify_superadmin(bot, messenger, text, logger):
    superadmin_id = Messenger(messenger).superadmin_id
    if not superadmin_id:
        return

    try:
        bot.send_message_to_user(superadmin_id, text, disable_notification=True)
    except Exception:
        logger.exception('Не удалось отправить уведомление суперадминистратору')


def _prepare_mailings(clients, news, session, logger):
    from main import set_log_messenger

    mailings = {}
    for messenger, bot in clients.items():
        set_log_messenger(messenger)
        last_news_id = _get_last_news_id(messenger, session)
        messenger_news = [writing for writing in news if int(writing['id']) > last_news_id]
        if last_news_id == 0:
            messenger_news = messenger_news[-1:]

        if not messenger_news:
            logger.debug('Новых новостей нет')
            continue

        users = _get_subscribers(messenger, session)
        mailings[messenger] = {
            'bot': bot,
            'users': users,
            'news_ids': {int(writing['id']) for writing in messenger_news},
            'last_news_id': int(messenger_news[-1]['id']),
            'count_news': len(messenger_news),
            'count_sent': 0
        }

        if users:
            _notify_superadmin(bot, messenger, 'Начало рассылки новостей', logger)

    set_log_messenger(None)
    return mailings


def send_newsletter(clients, session, logger, *args, **kwargs):
    from main import bot as telegram_bot, set_log_messenger

    start_time = time.time()
    logger.debug('Запущена функция send_newsletter')
    log_info = {}

    news = _get_news(min(_get_last_news_id(messenger, session) for messenger in clients), logger)
    if not news:
        logger.debug('Новых новостей нет')
        return True

    mailings = _prepare_mailings(clients, news, session, logger)

    for writing in news:
        text, text_pervye, urls = _build_news(writing)
        photos = []

        for messenger, mailing in mailings.items():
            if int(writing['id']) not in mailing['news_ids']:
                continue

            set_log_messenger(messenger)
            bot = mailing['bot']

            # Telegram скачивает фотографию по ссылке сам, а в ответе отдаёт file_id для следующих отправок
            by_url = bot.platform == Messenger.TELEGRAM and bool(urls)
            media = [MediaItem(id=url) for url in urls] if by_url else _photos_media(urls, photos, logger)
            inline_kb = _menu_keyboard() if int(writing['id']) == mailing['last_news_id'] else None

            for user_id in mailing['users']:
                log_extra = {'user_id': user_id, 'news_id': writing['id']}
                try:
                    _send_to_user(bot, user_id, text, media, inline_kb)
                except Exception as error:
                    if not by_url or not _is_url_download_error(error):
                        logger.exception('Не удалось отправить новость', extra=log_extra)
                        continue

                    # ВКонтакте отдаёт фотографии не всякому клиенту, поэтому пробуем отправить байтами
                    logger.warning('Telegram не скачал фотографии по ссылке', extra=log_extra)
                    by_url = False
                    media = _photos_media(urls, photos, logger)
                    try:
                        _send_to_user(bot, user_id, text, media, inline_kb)
                    except Exception:
                        logger.exception('Не удалось отправить новость', extra=log_extra)
                        continue
                mailing['count_sent'] += 1

            if messenger == Messenger.TELEGRAM and search(f'#({"|".join(hashtags)})'.lower(), text_pervye.lower()):
                send_pervye(telegram_bot, text_pervye, urls)

    for messenger, mailing in mailings.items():
        set_log_messenger(messenger)
        _save_last_news_id(messenger, mailing['last_news_id'], session)
        if mailing['users']:
            _notify_superadmin(
                bot=mailing['bot'], messenger=messenger, logger=logger,
                text=f'Новости успешно отправлены. Количество новостей: {mailing["count_news"]}. '
                     f'Количество подписчиков: {len(mailing["users"])}'
            )
        log_info[Messenger(messenger).value] = {
            'count_news': mailing['count_news'],
            'count_users': len(mailing['users']),
            'count_sent': mailing['count_sent'],
            'last_news_id': mailing['last_news_id']
        }

    set_log_messenger(None)
    logger.debug('Завершена функция send_newsletter',
                 extra={'duration': time.time() - start_time, 'info': log_info})

    return True
