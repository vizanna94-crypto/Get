import os
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# Настройка логов
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Переменные из Railway
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Ваши реквизиты прямо в тексте:
PAYMENT_DETAILS = "+79083288684 (Сбербанк, Анна Викторовна В.)"

# Этапы диалога
WAITING_PACKAGE, WAITING_PHOTO, WAITING_QUESTION = range(3)

# Тарифы
PACKAGES = {
    "1": {"title": "Разбор по глазам", "price": "90 ₽"},
    "2": {"title": "Разбор по ладони", "price": "150 ₽"},
    "3": {"title": "Полный разбор (глаза + ладонь)", "price": "200 ₽"},
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [
        ["1️⃣ Разбор по глазам — 90 ₽"],
        ["2️⃣ Разбор по ладони — 150 ₽"],
        ["3️⃣ Полный разбор — 200 ₽"],
    ]
    await update.message.reply_text(
        "Привет! Выбери нужный вариант разбора:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
    )
    return WAITING_PACKAGE

async def package_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "1" in text:
        key = "1"
    elif "2" in text:
        key = "2"
    elif "3" in text:
        key = "3"
    else:
        await update.message.reply_text("Пожалуйста, выбери вариант из меню.")
        return WAITING_PACKAGE

    context.user_data["package"] = key
    context.user_data["photos"] = []
    
    await update.message.reply_text(
        f"Отлично! Выбран: {PACKAGES[key]['title']}.\n\n"
        "Теперь пришли мне от 1 до 3 четких фото (глаз или ладони в зависимости от услуги).\n"
        "Когда закончишь отправку фото, напиши слово 'Готово'.",
        reply_markup=ReplyKeyboardRemove()
    )
    return WAITING_PHOTO

async def photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file = update.message.photo[-1].file_id
    context.user_data["photos"].append(photo_file)
    await update.message.reply_text("Фото получено! Пришли ещё или напиши 'Готово'.")
    return WAITING_PHOTO

async def photo_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("photos"):
        await update.message.reply_text("Пожалуйста, пришли хотя бы одно фото!")
        return WAITING_PHOTO
    
    await update.message.reply_text("Теперь напиши свой главный вопрос (сферу жизни/ситуацию):")
    return WAITING_QUESTION

async def question_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = update.message.text
    package_key = context.user_data.get("package")
    package = PACKAGES[package_key]
    photos = context.user_data.get("photos", [])
    user = update.effective_user

    # 1) Сообщение клиенту с реквизитами
    confirm_text = (
        f"Спасибо! Заявка принята:\n\n"
        f"📦 {package['title']} — {package['price']}\n"
        f"❓ Вопрос: {question}\n\n"
        f"💳 Реквизиты для оплаты:\n"
        f"Переведи {package['price']} по номеру:\n"
        f"{PAYMENT_DETAILS}\n\n"
        f"После оплаты разбор будет готов в течение дня 🔐"
    )

    # Простая текстовая отправка безо всяких картинок
    await update.message.reply_text(confirm_text, reply_markup=ReplyKeyboardRemove())

    # 2) Уведомление администратору
    admin_text = (
        f"🆕 Новая заявка!\n\n"
        f"Клиент: {user.full_name} (@{user.username})\n"
        f"chat_id: {user.id}\n"
        f"Пакет: {package['title']} ({package['price']})\n"
        f"Вопрос: {question}"
    )
    
    if ADMIN_CHAT_ID:
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_text)
            for p in photos:
                await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=p)
        except Exception as e:
            logger.error(f"Ошибка отправки админу: {e}")

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Диалог отменён. Напиши /start для начала.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_PACKAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, package_selected)],
            WAITING_PHOTO: [
                MessageHandler(filters.PHOTO, photo_received),
                MessageHandler(filters.Regex("(?i)^готово$"), photo_done),
            ],
            WAITING_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, question_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    logger.info("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
