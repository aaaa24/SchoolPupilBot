def home(txt):
    txt = txt.lower()
    if any(string in txt for string in ('в меню', 'главн', 'домой', 'старт')):
        return 100
    else:
        return 0


def edit_tt(txt):
    txt = txt.lower()
    if ('измен' in txt or 'помен' in txt) and ('расписани' in txt or 'урок' in txt):
        return 100
    else:
        return 0


def tt(txt):
    txt = txt.lower()
    if 'расписани' in txt and not ('измен' in txt or 'помен' in txt):
        return 100
    else:
        return 0


def send_news(txt):
    txt = txt.lower()
    if 'новост' in txt or 'рассылк' in txt:
        return 100
    else:
        return 0


def send_news_true(txt):
    txt = txt.lower()
    if ('новост' in txt or 'рассылк' in txt) and ('подпис' in txt or 'вкл' in txt):
        return 100
    else:
        return 0


def send_news_false(txt):
    txt = txt.lower()
    if ('новост' in txt or 'рассылк' in txt) and ('отпис' in txt or 'выкл' in txt):
        return 100
    else:
        return 0


def classes(txt):
    txt = txt.lower()
    if any(string in txt for string in ('класс', 'параллел')):
        return 100
    else:
        return 0


def teachers(txt):
    txt = txt.lower()
    if any(string in txt for string in ('учител', 'училк')):
        return 100
    else:
        return 0


def hlp(txt):
    txt = txt.lower()
    if any(string in txt for string in ('вопрос', 'помощ')):
        return 100
    else:
        return 0


def fback(txt):
    txt = txt.lower()
    if any(string in txt for string in ('отзыв', 'ошибк', 'иде', 'вопрос', 'помощ', 'связь')):
        return 100
    else:
        return 0


def info(txt):
    txt = txt.lower()
    if any(string in txt for string in ('информаци', 'инструкци')):
        return 100
    else:
        return 0
