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

# 🔧 Налаштування
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN", "7627926805:AAFCYdWl9Bg8BdV38RpZyL_fkJQt8JNBf7s")
ADMIN_CHAT_ID = 700139501  # ID, куди надсилаються повідомлення

# 🔌 Підключення до Google Sheets
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
# Переконайтеся, що credentials.json знаходиться у тій же директорії, що і telegram_bot.py
creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
gc = gspread.authorize(creds)
# Переконайтеся, що назва аркуша "Ответы на форму" точно співпадає з вашою вкладкою в Google Sheets
sheet = gc.open_by_key("1i7BKTUHO4QW9OoUW_0xdE1uKqGCcY3MO_6BjHaVzyFk").worksheet("Ответы на форму")
headers = sheet.row_values(1)  # Назви колонок з першого рядка таблиці

# 🧩 Етапи збору даних
DOCTOR, PHONE, CLINIC, DATETIME, PATIENT, IMPLANT_SYSTEM, ZONE = range(7)

async def start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("👨‍⚕️ Введіть прізвище лікаря:")
    return DOCTOR

async def doctor(update: Update, context: CallbackContext) -> int:
    context.user_data["ПІБ лікаря"] = update.message.text
    await update.message.reply_text("📞 Введіть номер телефону:")
    return PHONE

async def phone(update: Update, context: CallbackContext) -> int:
    context.user_data["Контактний телефон"] = update.message.text
    await update.message.reply_text("🏥 Введіть назву клініки:")
    return CLINIC

async def clinic(update: Update, context: CallbackContext) -> int:
    context.user_data["Назва клініки"] = update.message.text
    await update.message.reply_text("📅 Введіть дату замовлення (напр. 24.07.2025):")
    return DATETIME

async def datetime_step(update: Update, context: CallbackContext) -> int:
    context.user_data["дата здачі"] = update.message.text # Ключ для збереження дати
    await update.message.reply_text("👤 Введіть ПІБ пацієнта:")
    return PATIENT

async def patient(update: Update, context: CallbackContext) -> int:
    context.user_data["ПІБ пацієнта"] = update.message.text # Виправлено: було "ПІБ лікаря"
    await update.message.reply_text("🔩 Введіть імплантаційну систему:")
    return IMPLANT_SYSTEM

async def implant(update: Update, context: CallbackContext) -> int:
    context.user_data["Система імплантатів"] = update.message.text # Ключ для збереження системи
    await update.message.reply_text("🦷 Введіть зону (наприклад 1.1 або 2.4):")
    return ZONE

async def zone(update: Update, context: CallbackContext) -> int:
    # Виправлення SyntaxError:
    context.user_data['Передбачувана зона встановлення імплантатів Вкажіть в форматі "номер зуба - диаметер/довжина імплантата"'] = update.message.text
    context.user_data["Статус"] = "Новий"
    save_to_sheet(context.user_data) # Може бути async, але залишимо так для простоти
    notify_admin(context) # Може бути async, але залишимо так для простоти
    await update.message.reply_text("✅ Замовлення прийняте. Дякуємо!")
    return ConversationHandler.END

def save_to_sheet(data: dict):
    """
    Формуємо рядок відповідно до заголовків першого рядка та додаємо новий рядок у таблицю.
    """
    row = [data.get(col, "") for col in headers]
    sheet.append_row(row)

def notify_admin(context: CallbackContext):
    """
    Надсилаємо адміну повідомлення про нове замовлення.
    Ключі тут мають ТОЧНО співпадати з ключами в context.user_data
    """
    data = context.user_data
    msg = (
        "🆕 НОВЕ ЗАМОВЛЕННЯ\n\n"
        f"📅 Дата: {data.get('дата здачі', 'N/A')}\n" # Виправлено: 'Дата' на 'дата здачі'
        f"🏥 Клініка: {data.get('Назва клініки', 'N/A')}\n" # Виправлено: 'Клініка' на 'Назва клініки'
        f"👤 Пацієнт: {data.get('ПІБ пацієнта', 'N/A')}\n"
        f"🔩 Система: {data.get('Система імплантатів', 'N/A')}\n" # Виправлено: 'Система' на 'Система імплантатів'
        f"🦷 Зона: {data.get('Передбачувана зона встановлення імплантатів Вкажіть в форматі \"номер зуба - диаметер/довжина імплантата\"', 'N/A')}\n" # Виправлено ключ
        f"📞 Телефон: {data.get('Контактний телефон', 'N/A')}\n" # Виправлено: 'Телефон' на 'Контактний телефон'
        f"📌 Статус: {data.get('Статус', 'N/A')}"
    )
    context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg)

async def cancel(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("❌ Операцію скасовано.")
    return ConversationHandler.END

def main():
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

    # Ініціалізація Application (Application замінює Updater та Dispatcher)
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

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

    # Додаємо обробник до application
    application.add_handler(conv_handler)

    # Запускаємо бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
