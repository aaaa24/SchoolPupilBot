import os
import time
from re import search

import requests
import telebot
import ydb
from telebot import types

from messenger_context import get_users_table
from messengers import Messenger


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


code = '''var all_walls = API.wall.get({"domain": "public_school335", "count": 24}).items;
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


def send_newsletter():
    driver = ydb.Driver(endpoint=os.getenv('YDB_ENDPOINT'), database=os.getenv('YDB_DATABASE'),
                        credentials=ydb.iam.MetadataUrlCredentials())
    driver.wait(fail_fast=True, timeout=5)

    session = driver.table_client.session().create()

    result = session.transaction().execute(
        f'SELECT * FROM app WHERE key = "last_news_id";',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    if result[0].rows:
        last_id = result[0].rows[0]['value']
    else:
        last_id = 0

    access_token = os.getenv('VK_ACCESS_TOKEN')
    r = requests.post('https://api.vk.com/method/execute',
                      params={'access_token': access_token, 'lang': 'ru', 'code': code % last_id, 'v': 5.131})

    print(r.json())
    r = r.json()['response']

    if not r:
        print('Новых новостей нет')
        return

    bot = telebot.TeleBot(os.getenv('TELEGRAM_BOT_TOKEN'))

    result = session.transaction().execute(
        f'SELECT * FROM {get_users_table(Messenger.TELEGRAM)} WHERE send_news = true;',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    users = [u['id'] for u in result[0].rows]

    r.sort(key=lambda w: w['date'])
    if last_id == 0:
        r = r[-1:]

    if users:
        bot.send_message(int(os.getenv('TELEGRAM_SUPERADMIN')),
                         'Начало рассылки новостей',
                         disable_notification=True)

    for writing in r:
        date = time.strftime('%H:%M %d.%m.%Y', time.gmtime(writing['date'] + 10800))

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
        url_videos = []
        attachments = writing['attachments'].copy()

        if 'copy_history' in writing:
            for copied in writing['copy_history']:
                date = time.strftime('%H:%M %d.%m.%Y', time.gmtime(copied['date'] + 10800))

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
                continue
                access_key = attachment['video']['access_key']
                owner_id = attachment['video']['owner_id']
                id_video = attachment['video']['id']
                title = attachment['video']['title']
                # url_videos.append((title, f'https://vk.com/video{owner_id}_{id_video}?list={access_key}'))
        if url_videos:
            if len(url_videos) == 1:
                text += f'\n\nК новости прикреплена видеозапись: <a href="{url_videos[0][1]}">{url_videos[0][0]}</a>'
                text_pervye = f'Видеозапись: <a href="{url_videos[0][1]}">{url_videos[0][0]}</a>\n\n{text_pervye}'
            else:
                text += '\n\nК новости прикреплены видеозаписи: '
                text_videos = ', '.join([f'<a href="{video[1]}">{video[0]}</a>' for video in url_videos])
                text += text_videos
                text_pervye = f'Видеозаписи: {text_videos}\n\n{text_pervye}'
            text = text.replace('\n' * 4, '\n' * 2)

        print(text)

        if writing is r[-1]:
            print('Последняя новость')
            inline_kb = types.InlineKeyboardMarkup()
            inline_kb.row(types.InlineKeyboardButton('🏠 В меню', callback_data='menu$new'))
        else:
            inline_kb = None

        if not photos:
            for user in users:
                except_429(
                    "k['bot'].send_message(k['user'], k['text'], reply_markup = k['inline_kb'], parse_mode = 'HTML', disable_web_page_preview = True)",
                    bot=bot, user=user, text=text, inline_kb=inline_kb
                )
        elif len(photos) == 1:
            for user in users:
                if len(text) > 1023:
                    except_429(
                        "k['bot'].send_photo(k['user'], photo = k['photo'], parse_mode = 'HTML')",
                        bot=bot, user=user, photo=photos[0]
                    )
                    except_429(
                        "k['bot'].send_message(k['user'], k['text'], reply_markup = k['inline_kb'], parse_mode = 'HTML', disable_web_page_preview = True)",
                        bot=bot, user=user, text=text, inline_kb=inline_kb
                    )
                else:
                    except_429(
                        "k['bot'].send_photo(k['user'], caption = k['text'], photo = k['photo'], reply_markup = k['inline_kb'], parse_mode = 'HTML')",
                        bot=bot, user=user, text=text, photo=photos[0], inline_kb=inline_kb
                    )
        else:
            if len(text) <= 1023 and not writing is r[-1]:
                media = [telebot.types.InputMediaPhoto(photos[0], caption=text, parse_mode='HTML')]
                media.extend([telebot.types.InputMediaPhoto(ph) for ph in photos[1:]])
            else:
                media = [telebot.types.InputMediaPhoto(ph) for ph in photos]

            for user in users:
                except_429(
                    "k['bot'].send_media_group(k['user'], k['media'])",
                    bot=bot, user=user, media=media
                )
                if len(text) > 1023 or writing is r[-1]:
                    except_429(
                        "k['bot'].send_message(k['user'], k['text'], reply_markup = k['inline_kb'], parse_mode = 'HTML', disable_web_page_preview = True)",
                        bot=bot, user=user, text=text, inline_kb=inline_kb
                    )

        hashtags = ['ДвижениеПервых', 'ДвижениеПервыхСПб', 'ПервыеПушкин', 'ПервичкаПервых', 'ДвижениеПервыхСПб',
                    'ПервыеПомогают']
        if search(f'#({"|".join(hashtags)})'.lower(), text_pervye.lower()):
            send_pervye(bot, text_pervye, photos)

    request = session.transaction().execute(
        f'UPSERT INTO app (key, value) VALUES ("last_news_id", "{r[-1]["id"]}");',
        commit_tx=True,
        settings=ydb.BaseRequestSettings().with_timeout(3).with_operation_timeout(2)
    )

    if users:
        bot.send_message(int(os.getenv('TELEGRAM_SUPERADMIN')),
                         f'Новости успешно отправлены. Количество новостей: {len(r)}. Количество подписчиков: {len(users)}',
                         disable_notification=True)
    print('OK')

    return True
