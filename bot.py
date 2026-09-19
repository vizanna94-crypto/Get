"""
Telegram-бот для приёма заявок на разбор по глазам/ладони.

ЧТО ДЕЛАЕТ БОТ:
1. Клиент пишет /start — видит услуги и цены, выбирает пакет.
2. Бот просит прислать фото (глаза или ладонь) и главный вопрос.
3. Бот присылает клиенту реквизиты для оплаты (номер телефона/имя).
4. Бот пересылает заявку (фото + вопрос + пакет + username клиента) тебе (админу).
5. Ты делаешь разбор сама и отправляешь его клиенту:
   - либо просто написав ему в личку в Telegram (если у него есть @username),
   - либо через саму бота командой:  /reply <chat_id> текст ответа
     (chat_id бот сам присылает тебе вместе с заявкой).

НИЧЕГО не анализирует и не генерирует автоматически — это инструмент
для приёма заказов и оплаты, сам разбор всегда делаешь ты вручную.
"""

import logging
import os

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# НАСТРОЙКИ — впиши свои значения сюда или (лучше) задай через переменные
# окружения BOT_TOKEN и ADMIN_CHAT_ID на хостинге.
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВСТАВЬ_СЮДА_ТОКЕН_ОТ_BOTFATHER").strip()
ADMIN_CHAT_ID_RAW = os.environ.get("ADMIN_CHAT_ID", "0").strip()
ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_RAW) if ADMIN_CHAT_ID_RAW else 0

# Файл с карточкой оплаты (номер телефона + имя), лежит рядом с bot.py
PAYMENT_CARD_PATH = os.path.join(
    os.path.dirname(__file__), "payment_card.png"
)

PACKAGES = {
    "eyes": {"title": "Разбор по глазам", "price": "90 ₽"},
    "palm": {"title": "Разбор по ладони", "price": "90 ₽"},
    "full": {"title": "Полный комплекс (глаза + ладонь)", "price": "140 ₽"},
}

# Состояния диалога
CHOOSING, WAITING_PHOTO, WAITING_QUESTION = range(3)


# ---------------------------------------------------------------------------
# /start — приветствие и выбор пакета
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()

    text = (
        "🔮 Персональный разбор по фотографии — глаза или ладонь.\n\n"
        "👁 Разбор по глазам — 90 ₽\n"
        "✋ Разбор по ладони — 90 ₽\n"
        "✨ Полный комплекс (глаза + ладонь) — 140 ₽\n\n"
        "К любому разбору — бонус: разбор 1 личного вопроса, который тебя "
        "волнует.\n\n"
        "Выбери, что тебя интересует:\n\n"
        "(команда /help — условия и политика возврата)"
    )

    keyboard = [
        [InlineKeyboardButton("👁 Глаза — 90 ₽", callback_data="eyes")],
        [InlineKeyboardButton("✋ Ладонь — 90 ₽", callback_data="palm")],
        [InlineKeyboardButton("✨ Комплекс — 140 ₽", callback_data="full")],
    ]

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING


async def package_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    package_key = query.data
    package = PACKAGES[package_key]
    context.user_data["package"] = package_key
    context.user_data["photos"] = []

    if package_key == "full":
        photo_request = "Пришли, пожалуйста, ДВА фото: глаза крупным планом и ладонь при дневном свете."
        context.user_data["photos_needed"] = 2
    elif package_key == "eyes":
        photo_request = "Пришли, пожалуйста, фото глаз крупным планом (без фильтров и очков)."
        context.user_data["photos_needed"] = 1
    else:
        photo_request = "Пришли, пожалуйста, фото ладони при дневном свете — линии должны быть хорошо видны."
        context.user_data["photos_needed"] = 1

    await query.edit_message_text(
        f"Выбрано: {package['title']} — {package['price']}\n\n{photo_request}"
    )
    return WAITING_PHOTO


# ---------------------------------------------------------------------------
# Приём фото
# ---------------------------------------------------------------------------

async def photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    file_id = update.message.photo[-1].file_id
    context.user_data.setdefault("photos", []).append(file_id)

    needed = context.user_data.get("photos_needed", 1)
    have = len(context.user_data["photos"])

    if have < needed:
        await update.message.reply_text(
            f"Фото {have}/{needed} получено. Пришли, пожалуйста, ещё одно."
        )
        return WAITING_PHOTO

    await update.message.reply_text(
        "Фото получено ✅\n\nТеперь напиши свой главный вопрос — что тебя "
        "(отношения, работа, деньги или важный выбор) — он входит в стоимость."
    )
    return WAITING_QUESTION


async def photo_missing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Похоже, это не фото. Пришли, пожалуйста, именно изображение (как фото, не файлом)."
    )
    return WAITING_PHOTO


# ---------------------------------------------------------------------------
# Приём вопроса → отправка реквизитов клиенту + пересылка заявки админу
# ---------------------------------------------------------------------------

async def question_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    question = update.message.text
    package_key = context.user_data.get("package")
    package = PACKAGES[package_key]
    photos = context.user_data.get("photos", [])
    user = update.effective_user

    # 1) Клиенту — подтверждение, реквизиты и все условия текстом
    confirm_text = (
        f"Спасибо! Заявка принята:\n\n"
        f"📦 {package['title']} — {package['price']}\n"
        f"❓ Вопрос: {question}\n\n"
        f"Для оплаты переведи {package['price']} на карту:\n\n"
        f"4276 2800 1233 2471\n"
        f"Анна Викторовна В.\n\n"
        f"После оплаты разбор будет готов в течение дня.\n"
        f"🔐 Конфиденциальность гарантирована — фото и переписка никому не передаются.\n\n"
        f"💬 Есть ещё один вопрос? Просто напиши его следующим сообщением — "
        f"это +40 ₽ к стоимости."
    )
    await update.message.reply_text(confirm_text, reply_markup=ReplyKeyboardRemove())

    # 2) Админу (тебе) — пересылка всей заявки
    if ADMIN_CHAT_ID:
        username = f"@{user.username}" if user.username else "(без username)"
        admin_caption = (
            f"🆕 Новая заявка\n\n"
            f"Клиент: {user.full_name} {username}\n"
            f"chat_id: {user.id}\n"
            f"Пакет: {package['title']} — {package['price']}\n"
            f"Вопрос: {question}\n\n"
            f"Чтобы ответить через бота:\n/reply {user.id} текст ответа"
        )
        for i, file_id in enumerate(photos, start=1):
            await context.bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=file_id,
                caption=admin_caption if i == len(photos) else None,
            )
    else:
        logger.warning("ADMIN_CHAT_ID не задан — заявки некому пересылать.")

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Заявка отменена. Если захочешь начать заново — напиши /start.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /help — политика и условия, доступно в любой момент
# ---------------------------------------------------------------------------

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "ℹ️ Условия и политика\n\n"
        "🔮 Формат: разбор — это личная интерпретация по фото, "
        "развлекательно-консультационный формат. Он не заменяет "
        "профессиональную психологическую, медицинскую, юридическую "
        "или финансовую консультацию.\n\n"
        "🔐 Конфиденциальность: присланные фото и переписка не передаются "
        "третьим лицам и используются только для разбора.\n\n"
        "💳 Оплата: после отправки фото и вопроса тебе придут реквизиты "
        "для перевода. Разбор готовится в течение дня после оплаты.\n\n"
        "↩️ Если разбор не понравился: возврат средств за уже "
        "выполненную работу не производится, но если что-то показалось "
        "неполным или непонятным — просто напиши об этом, и я уточню "
        "или разберу тот же вопрос ещё раз бесплатно.\n\n"
        "Чтобы сделать новую заявку — напиши /start."
    )
    await update.message.reply_text(text)


# ---------------------------------------------------------------------------
# Сообщения вне активной заявки (например, отзыв или жалоба после разбора) —
# пересылаем админу, чтобы ничего не терялось.
# ---------------------------------------------------------------------------

async def forward_followup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    # Сообщения от самого админа в этом же чате не пересылаем самому себе
    if ADMIN_CHAT_ID and user.id == ADMIN_CHAT_ID:
        return

    text = update.message.text
    if ADMIN_CHAT_ID:
        username = f"@{user.username}" if user.username else "(без username)"
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"💬 Сообщение от клиента (вне заявки)\n\n"
                f"От: {user.full_name} {username}\n"
                f"chat_id: {user.id}\n\n"
                f"Текст: {text}\n\n"
                f"Ответить: /reply {user.id} текст ответа"
            ),
        )
    await update.message.reply_text(
        "Спасибо, я передала твоё сообщение — отвечу как можно скорее 💬"
    )


# ---------------------------------------------------------------------------
# Команда для админа: /reply <chat_id> <текст> — отправить ответ клиенту
# ---------------------------------------------------------------------------

async def reply_to_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_CHAT_ID:
        return  # игнорируем команду от кого угодно, кроме админа

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Использование: /reply <chat_id> <текст ответа>"
        )
        return

    try:
        target_chat_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("chat_id должен быть числом.")
        return

    message_text = " ".join(context.args[1:])

    try:
        await context.bot.send_message(chat_id=target_chat_id, text=message_text)
        await update.message.reply_text("Отправлено ✅")
    except Exception as e:
        await update.message.reply_text(f"Не удалось отправить: {e}")


# ---------------------------------------------------------------------------
# Запуск бота
# ---------------------------------------------------------------------------

def main() -> None:
    if BOT_TOKEN == "ВСТАВЬ_СЮДА_ТОКЕН_ОТ_BOTFATHER":
        raise SystemExit(
            "Не задан BOT_TOKEN. Впиши токен в код или задай переменную окружения BOT_TOKEN."
        )

    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING: [CallbackQueryHandler(package_chosen)],
            WAITING_PHOTO: [
                MessageHandler(filters.PHOTO, photo_received),
                MessageHandler(~filters.PHOTO & ~filters.COMMAND, photo_missing),
            ],
            WAITING_QUESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, question_received)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("reply", reply_to_client))
    application.add_handler(CommandHandler("help", help_command))
    # Обязательно последним: ловит любые сообщения вне активной заявки
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, forward_followup)
    )

    logger.info("Бот запущен...")
    application.run_polling()


if __name__ == "__main__":
    main()
