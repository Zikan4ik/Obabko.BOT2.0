#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Updater,
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
creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
gc = gspread.authorize(creds)
sheet = gc.open_by_key("1i7BKTUHO4QW9OoUW_0xdE1uKqGCcY3MO_6BjHaVzyFk").worksheet("Ответы на форму")
headers = sheet.row_values(1)  # Назви колонок

# 🧩 Етапи збору даних
DOCTOR, PHONE, CLINIC, DATETIME, PATIENT, IMPLANT_SYSTEM, ZONE = range(7)

def start(update: Update, context: CallbackContext) -> int:
    update.message.reply_text("👨‍⚕️ Введіть прізвище лікаря:")
    return DOCTOR

def doctor(update: Update, context: CallbackContext) -> int:
    context.user_data["ПІБ лікаря"] = update.message.text
    update.message.reply_text("📞 Введіть номер телефону:")
    return PHONE

def phone(update: Update, context: CallbackContext) -> int:
    context.user_data["Контактний телефон"] = update.message.text
    update.message.reply_text("🏥 Введіть назву клініки:")
    return CLINIC

def clinic(update: Update, context: CallbackContext) -> int:
    context.user_data["Назва клініки"] = update.message.text
    update.message.reply_text("📅 Введіть дату замовлення (напр. 24.07.2025):")
    return DATETIME

def datetime_step(update: Update, context: CallbackContext) -> int:
    context.user_data["дата здачі"] = update.message.text
    update.message.reply_text("👤 Введіть ПІБ пацієнта:")
    return PATIENT

def patient(update: Update, context: CallbackContext) -> int:
    context.user_data["ПІБ лікаря"] = update.message.text
    update.message.reply_text("🔩 Введіть імплантаційну систему:")
    return IMPLANT_SYSTEM

def implant(update: Update, context: CallbackContext) -> int:
    context.user_data["Система імплантатів"] = update.message.text
    update.message.reply_text("🦷 Введіть зону (наприклад 1.1 або 2.4):")
    return ZONE

def zone(update: Update, context: CallbackContext) -> int:
    context.user_data["Передбачувана зона встановлення імплантатів Вкажіть в форматі номер зуба - диаметер/довжина імплантата"] = update.message.text
    context.user_data["Статус"] = "Новий"
    save_to_sheet(context.user_data)
    notify_admin(context)
    update.message.reply_text("✅ Замовлення прийняте. Дякуємо!")
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
    """
    data = context.user_data
    msg = (
        "🆕 НОВЕ ЗАМОВЛЕННЯ\n\n"
        f"📅 Дата: {data.get('Дата')}\n"
        f"🏥 Клініка: {data.get('Клініка')}\n"
        f"👤 Пацієнт: {data.get('ПІБ пацієнта')}\n"
        f"🔩 Система: {data.get('Система')}\n"
        f"🦷 Зона: {data.get('Зона')}\n"
        f"📞 Телефон: {data.get('Телефон')}\n"
        f"📌 Статус: {data.get('Статус')}"
    )
    context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg)

def cancel(update: Update, context: CallbackContext) -> int:
    update.message.reply_text("❌ Операцію скасовано.")
    return ConversationHandler.END

def main():
    # Логування (за потреби можна налаштувати)
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

    # Ініціалізація черги оновлень
    update_queue = Queue()
    updater = Updater(TELEGRAM_BOT_TOKEN, update_queue=update_queue)
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            DOCTOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, doctor)], # Переконайтеся, що тут filters (з маленької)
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone)],
            CLINIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, clinic)],
            DATETIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, datetime_step)],
            PATIENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, patient)],
            IMPLANT_SYSTEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, implant)],
            ZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, zone)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    dp.add_handler(conv_handler)

    # Запускаємо бота
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
