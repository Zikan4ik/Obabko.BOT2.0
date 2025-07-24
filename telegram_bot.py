#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackContext
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json # Додано для обробки JSON з змінної оточення

# 🔧 Налаштування
# Токен бота можна передати через змінну оточення BOT_TOKEN
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN", "7627926805:AAFCYdWl9Bg8BdV38RpZyL_fkJQt8JNBf7s")
# ID чату адміністратора, куди будуть надходити повідомлення про нові замовлення
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "700139501")) # Переконайтеся, що це ваш ID, перетворений на int

# 🔌 Підключення до Google Sheets
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

# Спроба отримати облікові дані з змінної оточення (рекомендовано для Railway)
creds_json_str = os.getenv("GOOGLE_CREDENTIALS_JSON")
if creds_json_str:
    try:
        creds_info = json.loads(creds_json_str)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        logging.info("Google Sheet credentials loaded from environment variable.")
    except json.JSONDecodeError as e:
        logging.error(f"Failed to decode GOOGLE_CREDENTIALS_JSON: {e}")
        # Запасний варіант, якщо змінна оточення некоректна
        creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
        logging.warning("Falling back to credentials.json file due to JSON decode error.")
    except Exception as e:
        logging.error(f"Error loading credentials from environment variable: {e}")
        creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
        logging.warning("Falling back to credentials.json file due to general error.")
else:
    # Якщо змінна оточення не встановлена, спробуйте завантажити з файлу
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    logging.info("Google Sheet credentials loaded from credentials.json file.")

gc = gspread.authorize(creds)
# Переконайтеся, що назва аркуша "Ответы на форму" точно співпадає з вашою вкладкою в Google Sheets
sheet = gc.open_by_key("1i7BKTUHO4QW9OoUW_0xdE1uKqGCcY3MO_6BjHaVzyFk").worksheet("Ответы на форму")
headers = sheet.row_values(1)  # Назви колонок з першого рядка таблиці
logging.info(f"Google Sheet headers: {headers}")

# 🧩 Етапи збору даних
DOCTOR, PHONE, CLINIC, DATETIME, PATIENT, IMPLANT_SYSTEM, ZONE = range(7)

async def start(update: Update, context: CallbackContext) -> int:
    logging.info(f"Отримано команду /start від користувача {update.effective_user.id}")
    await update.message.reply_text("👨‍⚕️ Введіть прізвище лікаря:")
    return DOCTOR

async def doctor(update: Update, context: CallbackContext) -> int:
    logging.info(f"Отримано відповідь лікаря: {update.message.text}")
    context.user_data["ПІБ лікаря"] = update.message.text
    await update.message.reply_text("📞 Введіть номер телефону:")
    return PHONE

async def phone(update: Update, context: CallbackContext) -> int:
    logging.info(f"Отримано відповідь телефону: {update.message.text}")
    context.user_data["Контактний телефон"] = update.message.text
    await update.message.reply_text("🏥 Введіть назву клініки:")
    return CLINIC

async def clinic(update: Update, context: CallbackContext) -> int:
    logging.info(f"Отримано відповідь клініки: {update.message.text}")
    context.user_data["Назва клініки"] = update.message.text
    await update.message.reply_text("📅 Введіть дату замовлення (напр. 24.07.2025):")
    return DATETIME

async def datetime_step(update: Update, context: CallbackContext) -> int:
    logging.info(f"Отримано відповідь дати: {update.message.text}")
    context.user_data["дата здачі"] = update.message.text
    await update.message.reply_text("👤 Введіть ПІБ пацієнта:")
    return PATIENT

async def patient(update: Update, context: CallbackContext) -> int:
    logging.info(f"Отримано відповідь ПІБ пацієнта: {update.message.text}")
    context.user_data["ПІБ пацієнта"] = update.message.text
    await update.message.reply_text("🔩 Введіть імплантаційну систему:")
    return IMPLANT_SYSTEM

async def implant(update: Update, context: CallbackContext) -> int:
    logging.info(f"Отримано відповідь імплантаційної системи: {update.message.text}")
    context.user_data["Система імплантатів"] = update.message.text
    await update.message.reply_text("🦷 Введіть зону (наприклад 1.1 або 2.4):")
    return ZONE

async def zone(update: Update, context: CallbackContext) -> int:
    logging.info(f"Отримано відповідь зони: {update.message.text}")
    # Виправлення SyntaxError та використання довгого ключа
    context.user_data['Передбачувана зона встановлення імплантатів Вкажіть в форматі "номер зуба - диаметер/довжина імплантата"'] = update.message.text
    context.user_data["Статус"] = "Новий"
    
    logging.info("Дані збережено в context.user_data. Спроба зберегти в Google Sheet.")
    save_to_sheet(context.user_data) # Ця функція не async
    
    logging.info("Спроба надіслати повідомлення адміну.")
    notify_admin(context) # Ця функція не async
    
    await update.message.reply_text("✅ Замовлення прийняте. Дякуємо!")
    logging.info("Замовлення прийнято, ConversationHandler.END")
    return ConversationHandler.END

def save_to_sheet(data: dict):
    """
    Формуємо рядок відповідно до заголовків першого рядка та додаємо новий рядок у таблицю.
    """
    row = [data.get(col, "") for col in headers]
    try:
        sheet.append_row(row)
        logging.info(f"Рядок успішно додано до Google Sheet: {row}")
    except Exception as e:
        logging.error(f"Помилка при додаванні рядка до Google Sheet: {e}")
        # Додатково: можна відправити повідомлення адміну про помилку збереження
        # context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"Помилка збереження в Google Sheet: {e}")

def notify_admin(context: CallbackContext):
    """
    Надсилаємо адміну повідомлення про нове замовлення.
    Ключі тут мають ТОЧНО співпадати з ключами в context.user_data
    """
    data = context.user_data
    msg = (
        "🆕 НОВЕ ЗАМОВЛЕННЯ\n\n"
        f"👨‍⚕️ ПІБ лікаря: {data.get('ПІБ лікаря', 'N/A')}\n"
        f"📞 Телефон: {data.get('Контактний телефон', 'N/A')}\n"
        f"🏥 Клініка: {data.get('Назва клініки', 'N/A')}\n"
        f"📅 Дата замовлення: {data.get('дата здачі', 'N/A')}\n"
        f"👤 ПІБ пацієнта: {data.get('ПІБ пацієнта', 'N/A')}\n"
        f"🔩 Система імплантатів: {data.get('Система імплантатів', 'N/A')}\n"
        f"🦷 Зона: {data.get('Передбачувана зона встановлення імплантатів Вкажіть в форматі \"номер зуба - диаметер/довжина імплантата\"', 'N/A')}\n"
        f"📌 Статус: {data.get('Статус', 'N/A')}"
    )
    try:
        context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg)
        logging.info("Повідомлення адміну успішно надіслано.")
    except Exception as e:
        logging.error(f"Помилка при надсиланні повідомлення адміну: {e}")

async def cancel(update: Update, context: CallbackContext) -> int:
    logging.info(f"Користувач {update.effective_user.id} скасував операцію.")
    await update.message.reply_text("❌ Операцію скасовано.")
    return ConversationHandler.END

def main():
    # Налаштування логування на DEBUG для детальнішого виводу
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)

    logging.info("Бот запускається...")
    
    # Ініціалізація Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    logging.info("Application ініціалізовано.")

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            DOCTOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, doctor)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone)],
            CLINIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, clinic)],
            DATETIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, datetime_step)],
            PATIENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, patient)],
            IMPLANT_SYSTEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, implant)],
            ZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, zone)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    logging.info("ConversationHandler додано до Application.")

    logging.info("Починаємо опитування оновлень...")
    # allowed_updates=Update.ALL_TYPES забезпечує, що бот отримує всі типи оновлень.
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    logging.info("Опитування оновлень завершено. Бот зупинено.")

if __name__ == '__main__':
    main()
