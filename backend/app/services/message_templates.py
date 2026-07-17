"""F25 — Urdu/English SMS templates.

SMS is the fallback-of-last-resort channel (in-app -> email -> SMS), so it
gets the bilingual treatment the higher-priority channels don't need: a
patient who never opens the app or reads English email still gets the
appointment fact in a language they read. Titles used across the app
(booking_service, reminders, admin_service, waitlist_service, ...) are
looked up against a fixed phrase table; anything not in the table still
sends — English body only, never blocked on a missing translation.
"""

_TITLE_UR: dict[str, str] = {
    "Appointment reminder": "اپائنٹمنٹ یاد دہانی",
    "Booking confirmed": "بکنگ کی تصدیق ہو گئی",
    "Booking pending doctor acceptance": "بکنگ ڈاکٹر کی منظوری کے منتظر ہے",
    "Booking rejected": "بکنگ مسترد کر دی گئی",
    "Booking cancelled": "بکنگ منسوخ کر دی گئی",
    "Appointment cancelled by doctor": "ڈاکٹر نے اپائنٹمنٹ منسوخ کر دی",
    "Booking expired": "بکنگ کی معیاد ختم ہو گئی",
    "Waitlist slot available": "ویٹنگ لسٹ میں جگہ دستیاب ہے",
    "Follow-up suggested": "دوبارہ چیک اپ تجویز کردہ",
    "Verification approved": "تصدیق منظور ہو گئی",
    "Verification rejected": "تصدیق مسترد ہو گئی",
}


def render_sms(*, title: str, body: str) -> str:
    """English body first (SMS gateways are commonly GSM-7/Latin-charset
    billed, so leading with English keeps single-segment messages single-
    segment); Urdu title appended in parentheses when a translation exists."""
    ur_title = _TITLE_UR.get(title)
    if ur_title:
        return f"{body} ({ur_title})"
    return body
