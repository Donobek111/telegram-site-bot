import os
import io
import json
import datetime
import logging
import base64
import tempfile
import requests
import asyncio
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InputFile, Message
from aiogram.filters import Command

# ---------------------------
# CONFIG (вставь свои токены)
# ---------------------------
BOT_TOKEN = "7816366790:AAGFyFNOTm08JIn3abYz3LJHuNCyEIz9CjY"
OPENROUTER_API_KEY = "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"
if BOT_TOKEN.startswith("ВАШ_") or OPENROUTER_API_KEY.startswith("ВАШ_"):
    raise RuntimeError("Вставь BOT_TOKEN и OPENROUTER_API_KEY в код перед запуском.")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
bot = Bot(token="7816366790:AAGFyFNOTm08JIn3abYz3LJHuNCyEIz9CjY")
dp = Dispatcher()
router = Router()

DATA_FILE = "users.json"  # сохраняем базовые данные пользователей
CHAT_MEM_FILE = "chat_mem.json"  # сохраняем историю чата по пользователям

# ---------------------------
# HELPERS: load/save JSON
# ---------------------------

def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


users = load_json(DATA_FILE)  # структура: users[user_id] = {fields...}
chat_mem = load_json(CHAT_MEM_FILE)  # structure: chat_mem[user_id] = [ {role, content}, ... ]

# ---------------------------
# MENU
# ---------------------------

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💬 Чат с ИИ"), KeyboardButton(text="🌐 Создать сайт")],
            [KeyboardButton(text="🚀 Лимит"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="🤝 Пригласить друга"), KeyboardButton(text="ℹ️ Помощь")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие 👇"
    )

# ---------------------------
# INIT USER
# ---------------------------

def ensure_user(user_id: str):
    today = str(datetime.date.today())
    if user_id not in users:
        users[user_id] = {
            "daily_limit_base": 3,
            "used_today": 0,
            "total_sites": 0,
            "referrals": 0,
            "joined": today,
            "last_reset": today
        }
        save_json(DATA_FILE, users)
    # safety: ensure keys exist
    u = users[user_id]
    if "daily_limit_base" not in u:
        u["daily_limit_base"] = 3
    if "used_today" not in u:
        u["used_today"] = 0
    if "total_sites" not in u:
        u["total_sites"] = 0
    if "referrals" not in u:
        u["referrals"] = 0
    if "joined" not in u:
        u["joined"] = str(datetime.date.today())
    if "last_reset" not in u:
        u["last_reset"] = str(datetime.date.today())
    save_json(DATA_FILE, users)


def reset_if_new_day(user_id: str):
    today = str(datetime.date.today())
    if users[user_id]["last_reset"] != today:
        users[user_id]["used_today"] = 0
        users[user_id]["last_reset"] = today
        save_json(DATA_FILE, users)

# ---------------------------
# USER MODES
# ---------------------------
# mode_map[user_id] = "menu" | "chat" | "site_step_N" ...
mode_map = {}


def set_mode(user_id: str, mode: str):
    mode_map[user_id] = mode


def get_mode(user_id: str):
    return mode_map.get(user_id, "menu")

# ---------------------------
# OPENROUTER INTERFACE
# ---------------------------

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def ask_openrouter_messages(messages):
    """
    messages: list of dicts like [{"role":"user","content": "text"}, ...]
    returns assistant content string or raises
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": messages
    }
    r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    resp = r.json()
    return resp["choices"][0]["message"]["content"]


def ask_openrouter_with_image(user_text, image_path):
    """ Sends a message with an embedded image as base64 to OpenRouter. Returns assistant text. """
    with open(image_path, "rb") as f:
        b = f.read()
    img_b64 = base64.b64encode(b).decode("utf-8")
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    content = [
        {"type": "text", "text": user_text},
        {"type": "image_url", "image_url": f"data:image/jpeg;base64,{img_b64}"}
    ]
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": content}]
    }
    r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    resp = r.json()
    return resp["choices"][0]["message"]["content"]

# ---------------------------
# HANDLERS
# ---------------------------

@router.message(Command(commands=["start"]))
async def cmd_start(message: Message):
    args = message.text.split()
    user_id = str(message.from_user.id)
    ensure_user(user_id)
    # referral
    if len(args) > 1:
        ref = args[1]
        if ref != user_id and ref in users:
            users[ref]["referrals"] = users[ref].get("referrals", 0) + 1
            save_json(DATA_FILE, users)
            try:
                await bot.send_message(int(ref), "🎉 По вашей ссылке зарегистрировался новый пользователь — +1 к лимиту сегодня!")
            except Exception:
                pass
    set_mode(user_id, "menu")
    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        "Меню:\n"
        "• 💬 Чат с ИИ — общайся как ChatGPT (помню 50 сообщений)\n • 🌐 Создать сайт — бот задаёт вопросы и отдаёт HTML\n"
        "• 🚀 Лимит — сколько сайтов осталось сегодня\n"
        "• 📊 Статистика — твоя активность\n"
        "• 🤝 Пригласить друга — получи бонусы\n"
        "• ℹ️ Помощь — инструкция",
        reply_markup=main_menu()
    )

# Buttons (text exact match)
@router.message(F.text == "💬 Чат с ИИ")
async def btn_chat(message: Message):
    user_id = str(message.from_user.id)
    ensure_user(user_id)
    set_mode(user_id, "chat")
    chat_mem.setdefault(user_id, [])
    save_json(CHAT_MEM_FILE, chat_mem)
    await message.answer("💬 Режим чата включён. Отправь текст или фото. Чтобы выйти — /exit")

@router.message(F.text == "🌐 Создать сайт")
async def btn_create(message: Message):
    user_id = str(message.from_user.id)
    ensure_user(user_id)
    reset_if_new_day(user_id)
    limit_total = users[user_id]["daily_limit_base"] + users[user_id].get("referrals", 0)
    if users[user_id]["used_today"] >= limit_total:
        await message.answer("🚫 Лимит сайтов на сегодня исчерпан. Пригласи друга, чтобы получить +1.")
        return
    set_mode(user_id, "site_step_type")
    await message.answer(
        "📝 Давай создадим сайт. Сначала — выбери тип (напиши цифру):\n"
        "1 — Визитка\n2 — Блог\n3 — Лендинг\n4 — Магазин\n5 — Портфолио\n6 — Резюме\n7 — Новости\n8 — Обучение\n"
    )

@router.message(F.text == "🚀 Лимит")
async def btn_limit(message: Message):
    user_id = str(message.from_user.id)
    ensure_user(user_id)
    reset_if_new_day(user_id)
    total = users[user_id]["daily_limit_base"] + users[user_id].get("referrals", 0)
    left = max(0, total - users[user_id]["used_today"])
    await message.answer(f"🚀 Сегодня ты можешь создать ещё {left} сайтов (всего {total}).")

@router.message(F.text == "📊 Статистика")
async def btn_stats(message: Message):
    user_id = str(message.from_user.id)
    ensure_user(user_id)
    reset_if_new_day(user_id)
    u = users[user_id]
    await message.answer(
        f"📊 Статистика:\n"
        f"• Всего создано сайтов: {u.get('total_sites',0)}\n"
        f"• Создано сегодня: {u.get('used_today',0)}\n"
        f"• Рефералов: {u.get('referrals',0)}\n"
        f"• Дата регистрации: {u.get('joined')}"
    )

@router.message(F.text == "🤝 Пригласить друга")
async def btn_invite(message: Message):
    user_id = str(message.from_user.id)
    ensure_user(user_id)
    try:
        me = await bot.get_me()
        bot_username = me.username if hasattr(me, "username") else None
    except Exception:
        bot_username = None
    if not bot_username:
        link = f"https://t.me/YourBot?start={user_id}"
    else:
        link = f"https://t.me/{bot_username}?start={user_id}"
    await message.answer(f"🤝 Поделись ссылкой:\n{link}\n\nЗа каждого нового — +1 к лимиту на день.")

@router.message(F.text == "ℹ️ Помощь")
async def btn_help(message: Message):
    await message.answer("ℹ️ Помощь и контакты:\nПиши в поддержку: @xxsint\n\nКак опубликовать HTML: открой Netlify / Vercel / GitHub Pages и загрузите файл index.html")

@router.message(Command(commands=["exit"]))
async def cmd_exit(message: Message):
    user_id = str(message.from_user.id)
    set_mode(user_id, "menu")
    await message.answer("🏠 Вернулся в меню.", reply_markup=main_menu())

# Photo handler (only used in chat mode)
@router.message(F.photo)
async def handle_photo(message: Message):
    user_id = str(message.from_user.id)
    mode = get_mode(user_id)
    if mode != "chat":
        await message.answer("📸 Фото можно отправлять в режиме 'Чат с ИИ' (кнопка «💬 Чат с ИИ»).")
        return
    # download highest-res photo to temp file
    photo = message.photo[-1]  # PhotoSize
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmpf:
            tmp_path = tmpf.name
            # Try multiple download methods (compatibility between aiogram versions)
            try:
                # Method A: get file info and download by file_path
                f_info = await bot.get_file(photo.file_id)
                # aiogram 3: bot.download_file may not exist in some builds; try file.download()
                try:
                    # If File object supports download
                    await f_info.download(destination=tmp_path)
                except Exception:
                    # Fallback: try bot.download_file (older/newer builds)
                    try:
                        await bot.download_file(f_info.file_path, tmp_path)
                    except Exception:
                        # Last fallback: PhotoSize.download (if available)
                        await photo.download(destination=tmp_path)
            except Exception:
                # If anything failed, try PhotoSize.download directly
                try:
                    await photo.download(destination=tmp_path)
                except Exception as e:
                    raise RuntimeError(f"Не удалось скачать файл фото: {e}")
        caption = message.caption or "Опиши, что на изображении"
        await message.answer("🧠 Обрабатываю изображение...")
        try:
            reply = ask_openrouter_with_image(caption, tmp_path)
        except Exception as e:
            reply = f"⚠️ Ошибка при обращении к OpenRouter: {e}"
        # save memory: user message + assistant reply
        chat_mem[user_id] = chat_mem.get(user_id, []) + [{"role":"user","content":caption}, {"role":"assistant","content":reply}]
        if len(chat_mem[user_id]) > 100:
            chat_mem[user_id] = chat_mem[user_id][-100:]
        save_json(CHAT_MEM_FILE, chat_mem)
        await message.answer(reply)
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

# General text handler: catches all text messages (buttons handled above first)
@router.message(F.text & ~F.via_bot)
async def all_text_handler(message: Message):
    user_id = str(message.from_user.id)
    ensure_user(user_id)
    mode = get_mode(user_id)
    text = message.text.strip()
    # ------------- CHAT MODE -------------
    if mode == "chat":
        chat_mem.setdefault(user_id, [])
        chat_mem[user_id].append({"role":"user","content": text})
        if len(chat_mem[user_id]) > 100:
            chat_mem[user_id] = chat_mem[user_id][-100:]
        save_json(CHAT_MEM_FILE, chat_mem)
        await message.answer("🧠 Думаю...")
        msgs = []
        for item in chat_mem[user_id]:
            role = item.get("role", "user")
            content = item.get("content", "")
            msgs.append({"role": role, "content": content})
        try:
            reply = ask_openrouter_messages(msgs)
        except Exception as e:
            reply = f"⚠️ Ошибка OpenRouter: {e}"
        chat_mem[user_id].append({"role":"assistant","content":reply})
        if len(chat_mem[user_id]) > 100:
            chat_mem[user_id] = chat_mem[user_id][-100:]
        save_json(CHAT_MEM_FILE, chat_mem)
        await message.answer(reply)
        return
    # ------------- SITE CREATION FLOW -------------
    # modes: site_step_type -> site_step_topic -> site_step_audience -> site_step_style -> generate
    if mode and mode.startswith("site_step"):
        temp_key = f"site_draft_{user_id}"
        temp = users.get(temp_key, {})
    # ---------------- САЙТ ----------------
    if mode.startswith("site_step"):
        temp_key = f"site_draft_{user_id}"
        temp = users.get(temp_key, {})
    # Шаг 1 — тип сайта
    if mode == "site_step_type":
        site_types = {
            "1": "Визитка",
            "2": "Блог",
            "3": "Лендинг",
            "4": "Магазин",
            "5": "Портфолио",
            "6": "Резюме",
            "7": "Новости",
            "8": "Обучение"
        }
        temp["type"] = site_types.get(text, text)
        users[temp_key] = temp
        set_mode(user_id, "site_step_topic")
        await message.answer("📌 Как будет называться сайт? (например: Мой блог, Портфолио дизайнера)")
        return
    # Шаг 2 — тема сайта
    elif mode == "site_step_topic":
        temp["topic"] = text
        users[temp_key] = temp
        set_mode(user_id, "site_step_audience")
        await message.answer("🎯 Какая будет аудитория сайта? (например: дизайнеры, покупатели, студенты)")
        return
    # Шаг 3 — аудитория сайта
    elif mode == "site_step_audience":
        temp["audience"] = text
        users[temp_key] = temp
        set_mode(user_id, "site_step_style")
        await message.answer("🎨 В каком стиле должен быть сайт? (например: минимализм, футуризм, бизнес)")
        return
    # Шаг 4 — стиль сайта и создание HTML
    elif mode == "site_step_style":
        temp["style"] = text
        users[temp_key] = temp
        set_mode(user_id, "menu")
        topic = temp.get("topic", "Мой сайт")
        site_type = temp.get("type", "Сайт")
        audience = temp.get("audience", "")
        style = temp.get("style", "")
        html = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{topic}</title>
<style>
:root {{ --bg:#fff; --fg:#111; --accent:#4f46e5; }}
body{{font-family:Arial,Helvetica,sans-serif;margin:0;padding:24px;background:linear-gradient(135deg,#f3f4f6,#fff);color:var(--fg)}}
.header{{max-width:900px;margin:0 auto;text-align:center;padding:40px 20px}} h1{{color:var(--accent);margin-bottom:8px}} .lead{{color:#374151}} .section{{max-width:900px;margin:24px auto;padding:20px;background:#ffffff;border-radius:10px;box-shadow:0 6px 18px rgba(15,23,42,0.06)}} .row{{display:flex;flex-wrap:wrap;gap:16px}} .card{{flex:1;min-width:220px;padding:16px;border-radius:8px;background:#fafafa}} footer{{text-align:center;padding:28px;color:#6b7280}} @media(max-width:640px){{.row{{flex-direction:column}}}}
</style>
</head>
<body>
<div class="header">
<h1>{topic}</h1>
<div class="lead">{site_type} — для {audience}. Стиль: {style}.</div>
</div>
<div class="section">
<h2>О проекте</h2>
<p>Короткое описание: сайт типа {site_type}. Наполни текстами и добавь изображения.</p>
<div class="row">
<div class="card"><h3>Услуги</h3><p>Опиши услуги или проекты.</p></div>
<div class="card"><h3>Портфолио</h3><p>Здесь будут примеры работ.</p></div>
<div class="card"><h3>Контакты</h3><p>Укажи e-mail и ссылки на соцсети.</p></div>
</div>
</div>
<footer>Сгенерировано ботом 🤖 — Подключи свои тексты и опубликуй на Netlify / Vercel / GitHub Pages</footer>
</body>
</html>"""
        # Сохранение статистики
        reset_if_new_day(user_id)
        users[user_id]["used_today"] = users[user_id].get("used_today", 0) + 1
        users[user_id]["total_sites"] = users[user_id].get("total_sites", 0) + 1
        users.pop(temp_key, None)
        save_json(DATA_FILE, users)
        # Отправка файла
        file = io.BytesIO(html.encode("utf-8"))
        input_file = InputFile(file, filename="site.html")
        await message.answer_document(
            input_file,
            caption=(
                "✅ Сайт готов!\n\n"
                "📌 Инструкция по публикации:\n"
                "1️⃣ Netlify — перетащи site.html\n"
                "2️⃣ GitHub Pages — переименуй в index.html и загрузи\n"
                "3️⃣ Vercel — просто добавь файл в проект\n\n"
                "🏠 Вернуться в меню — /start"
            ),
            reply_markup=main_menu()
        )
        return
    # ------------- MENU (default) -------------
    await message.answer("Я не понял — выбери пункт в меню или напиши /start, чтобы вернуться.", reply_markup=main_menu())

# ---------------------------
# Register router & run
# ---------------------------

dp.include_router(router)

async def main():
    logger.info("✅ Бот запущен (aiogram 3.x)!")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

    if __name__ == "__main__":
        import asyncio
        asyncio.run(main())