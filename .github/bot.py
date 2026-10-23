"""Sends today's PERG school lunch to Telegram.

Env vars: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
Optional: FORCE=1 (send now, ignore the 11:00 check)
"""
import io
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

PAGE = "https://perg.ee/toitlustus/"
TZ = ZoneInfo("Europe/Tallinn")

MONTHS = ["jaanuar", "veebruar", "märts", "aprill", "mai", "juuni", "juuli",
          "august", "september", "oktoober", "november", "detsember"]

# Side items that are the same every day; hidden to keep the message short.
SKIP = ("kastmevalik", "seemnesegu", "maitsevesi", "piim", "leivatoodete",
        "rosinad")

HEADER = re.compile(
    r"^(esmaspäev|teisipäev|kolmapäev|neljapäev|reede),\s*(\d{1,2})\.\s*(\w+)")
ROW = re.compile(
    r"^(.*?)\s+(\d+)\s+\d+\s+[\d.]+\s+[\d.]+\s+[\d.]+(?:\s+[\d;]+)?$")


def find_pdf_url() -> str:
    html = requests.get(PAGE, timeout=30).text
    links = re.findall(r'href="([^"]+\.pdf)"', html, flags=re.I)
    menu = [l for l in links if "menuu" in l.lower() or "menu" in l.lower()]
    if not (menu or links):
        raise RuntimeError("No PDF link found on page")
    return (menu or links)[0]


def pdf_text(url: str) -> str:
    from pypdf import PdfReader
    data = requests.get(url, timeout=60).content
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(p.extract_text() or "" for p in reader.pages)


def parse_day(text: str, day: int, month: str):
    """Return (header, main_dishes, alternatives) or None."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    start = None
    for i, l in enumerate(lines):
        m = HEADER.match(l)
        if m and int(m.group(2)) == day and m.group(3).lower() == month:
            start = i
            break
    if start is None:
        return None

    header = re.split(r"\s+Kogus", lines[start])[0]
    main, alt, after_total = [], [], False
    for l in lines[start + 1:]:
        if HEADER.match(l) or l.startswith(("Nädala keskmine", "Joogivesi")):
            break
        if l.startswith("Kokku"):
            after_total = True
            continue
        m = ROW.match(l)
        if not m:
            continue
        name, qty = m.group(1).strip(), int(m.group(2))
        if qty == 0 or name.lower().startswith(SKIP):
            continue
        (alt if after_total else main).append(name)
    return header, main, alt


def build_message() -> str:
    now = datetime.now(TZ)
    url = find_pdf_url()
    result = parse_day(pdf_text(url), now.day, MONTHS[now.month - 1])
    if result is None:
        return f"Today's menu wasn't found in the PDF.\n{url}"
    header, main, alt = result
    msg = f"🍽 {header.capitalize()}\n\n" + "\n".join(f"• {d}" for d in main)
    if alt:
        msg += "\n\n🌱 Alternative:\n" + "\n".join(f"• {d}" for d in alt)
    return msg


def send(text: str) -> None:
    r = requests.post(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage",
        json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text},
        timeout=30,
    )
    r.raise_for_status()


if __name__ == "__main__":
    now = datetime.now(TZ)
    if not os.environ.get("FORCE") and (now.hour != 11 or now.weekday() > 4):
        sys.exit(0)  # not 11:00 in Tallinn / weekend
    send(build_message())
