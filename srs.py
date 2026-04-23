from datetime import date, timedelta


def sm2(ease_factor: float, interval: int, repetitions: int, quality: int):
    """
    SM-2 spaced repetition algorithm.
    quality: 0 = don't know, 3 = hard, 5 = know it
    returns: (ease_factor, interval, repetitions, next_review_date_str)
    """
    if quality < 3:
        repetitions = 0
        interval = 1
    else:
        if repetitions == 0:
            interval = 1
        elif repetitions == 1:
            interval = 6
        else:
            interval = round(interval * ease_factor)
        repetitions += 1

    ease_factor = ease_factor + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
    ease_factor = max(1.3, ease_factor)

    next_review = (date.today() + timedelta(days=interval)).isoformat()
    return ease_factor, interval, repetitions, next_review
