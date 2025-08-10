#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ConversationHandler,
    CallbackContext
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
import re
from typing import Optional, Dict, Any

# 🔧 Налаштування
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN", "7627926805:AAFCYdWl9Bg8BdV38RpZyL_fkJQt8JNBf7s")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "700139501"))
SPREADSHEET_ID = "1i7BKTUHO4QW9OoUW_0xdE1uKqGCcY3MO_6BjHaVzyFk"
WORKSHEET_ID = 1024616098  # ID вкладки з URL

# 🎯 Додаткові налаштування
MAX_MESSAGE_LENGTH = 4000  # Максимальна довжина повідомлення
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@admin")  # Username адміністратора для контактів

# 🔌 Підключення до Google Sheets
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

def setup_google_sheets():
    """Налаштування підключення до Google Sheets з обробкою помилок"""
    try:
        creds_json_str = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if creds_json_str:
            try:
                creds_info = json.loads(creds_json_str)
                creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
                logging.info("Google Sheet credentials завантажено зі змінної оточення.")
            except json.JSONDecodeError as e:
                logging.error(f"Помилка декодування GOOGLE_CREDENTIALS_JSON: {e}")
                creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
                logging.warning("Використовується файл credentials.json через помилку JSON.")
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
            logging.info("Google Sheet credentials завантажено з файлу credentials.json.")
        
        gc = gspread.authorize(creds)
        
        # Відкриваємо таблицю по ID
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        
        # Отримуємо потрібну вкладку по ID
        try:
            worksheet = spreadsheet.get_worksheet_by_id(WORKSHEET_ID)
        except gspread.WorksheetNotFound:
            # Якщо не знайдена по ID, пробуємо по імені
            worksheet = spreadsheet.worksheet("Ответы на форму")
        
        # Отримуємо заголовки
        headers = worksheet.row_values(1) if worksheet.row_count > 0 else []
        
        logging.info(f"Підключена Google Таблиця. Заголовки: {headers}")
        return worksheet, headers
    
    except Exception as e:
        logging.error(f"Критична помилка підключення до Google Sheets: {e}")
        return None, []

# Глобальні змінні
WORKSHEET, HEADERS = setup_google_sheets()

# 🧩 Етапи розмови
DOCTOR, PHONE, CLINIC, DATETIME, PATIENT, IMPLANT_SYSTEM, ZONE, MAIN_MENU, CHAT_MODE = range(9)

# 📊 Відповідність полів бота і таблиці
FIELD_MAPPING = {
    "timestamp": "Временная метка",
    "doctor": "ПІБ лікаря", 
    "phone": "Контактний телефон",
    "clinic": "Назва клініки",
    "date": "дата здачі",
    "patient": "ПІБ пацієнта",
    "implant_system": "Система імплантатів",
    "zone": "Передбачувана зона встановлення імплантатів Вкажіть в форматі \"номер зуба - диаметер/довжина імплантата\"",
    "status": "Статус"
}

# 🔍 Функції валідації
def validate_phone(phone: str) -> bool:
    """Валідація номера телефону (український формат)"""
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)
    pattern = r'^(\+38)?[0-9]{10}$'
    return bool(re.match(pattern, cleaned))

def validate_date(date_str: str) -> bool:
    """Валідація дати у форматі DD.MM.YYYY"""
    pattern = r'^\d{2}\.\d{2}\.\d{4}$'
    if not re.match(pattern, date_str):
        return False
    
    try:
        datetime.strptime(date_str, '%d.%m.%Y')
        return True
    except ValueError:
        return False

def validate_zone(zone: str) -> bool:
    """Валідація зони імплантації"""
    if not zone.strip():
        return False
    # Більш гнучка валідація - приймаємо будь-який непорожній текст
    return len(zone.strip()) >= 2

# 🏠 Головне меню
def get_main_menu_keyboard():
    """Створює клавіатуру головного меню"""
    keyboard = [
        [InlineKeyboardButton("📝 Нове замовлення", callback_data="new_order")],
        [InlineKeyboardButton("💬 Чат з підтримкою", callback_data="chat_support")],
        [InlineKeyboardButton("ℹ️ Довідка", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def show_main_menu(update: Update, context: CallbackContext):
    """Показує головне меню"""
    menu_text = (
        "🏥 **Система замовлень імплантатів**\n\n"
        "Оберіть дію:"
    )
    
    keyboard = get_main_menu_keyboard()
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            menu_text, 
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            menu_text,
            parse_mode='Markdown', 
            reply_markup=keyboard
        )
    
    return MAIN_MENU

# 📝 Обробники команд
async def start(update: Update, context: CallbackContext) -> int:
    """Початкова команда"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Невідомо"
    first_name = update.effective_user.first_name or ""
    
    logging.info(f"Команда /start від користувача {user_id} (@{username})")
    
    welcome_text = (
        f"👋 Вітаємо, {first_name}!\n\n"
        "🏥 **Система замовлень імплантатів**\n\n"
        "Я допоможу вам:\n"
        "• Оформити нове замовлення\n"
        "• Зв'язатися з підтримкою\n"
        "• Отримати довідкову інформацію\n\n"
        "Оберіть потрібну дію:"
    )
    
    keyboard = get_main_menu_keyboard()
    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown',
        reply_markup=keyboard
    )
    
    return MAIN_MENU

async def menu_callback(update: Update, context: CallbackContext) -> int:
    """Обробник натискань кнопок головного меню"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "new_order":
        await query.edit_message_text(
            "👨‍⚕️ **Починаємо оформлення замовлення**\n\n"
            "Введіть **прізвище лікаря**:",
            parse_mode='Markdown'
        )
        return DOCTOR
        
    elif query.data == "chat_support":
        await query.edit_message_text(
            "💬 **Режим чату з підтримкою**\n\n"
            "Тепер ви можете писати повідомлення, і вони будуть передані в службу підтримки.\n"
            "Для повернення в головне меню використовуйте /menu\n\n"
            "Напишіть ваше повідомлення:",
            parse_mode='Markdown'
        )
        return CHAT_MODE
        
    elif query.data == "help":
        help_text = (
            "🆘 **Довідка по боту**\n\n"
            "**Команди:**\n"
            "• `/start` - Головне меню\n"
            "• `/menu` - Повернутися в меню\n"
            "• `/cancel` - Скасувати операцію\n\n"
            "**Процес замовлення:**\n"
            "1️⃣ Прізвище лікаря\n"
            "2️⃣ Контактний телефон\n"
            "3️⃣ Назва клініки\n"
            "4️⃣ Дата замовлення\n"
            "5️⃣ ПІБ пацієнта\n" 
            "6️⃣ Система імплантатів\n"
            "7️⃣ Зона імплантації\n\n"
            f"**Підтримка:** {ADMIN_USERNAME}"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]]
        await query.edit_message_text(
            help_text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return MAIN_MENU
        
    elif query.data == "back_to_menu":
        return await show_main_menu(update, context)

# 💬 Чат з підтримкою
async def chat_handler(update: Update, context: CallbackContext) -> int:
    """Обробник повідомлень у режимі чату"""
    user_message = update.message.text
    user_id = update.effective_user.id
    username = update.effective_user.username or "Невідомо"
    first_name = update.effective_user.first_name or ""
    
    # Відправляємо повідомлення адміністратору
    admin_msg = (
        "💬 **ПОВІДОМЛЕННЯ ВІД КОРИСТУВАЧА**\n\n"
        f"👤 **Користувач:** {first_name} (@{username})\n"
        f"🆔 **ID:** `{user_id}`\n"
        f"⏰ **Час:** {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
        f"📝 **Повідомлення:**\n{user_message}"
    )
    
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_msg,
            parse_mode='Markdown'
        )
        
        await update.message.reply_text(
            "✅ Ваше повідомлення відправлено в службу підтримки!\n"
            "Ми зв'яжемося з вами найближчим часом.\n\n"
            "Ви можете продовжити писати або повернутися в /menu"
        )
        
    except Exception as e:
        logging.error(f"Помилка відправлення повідомлення адміну: {e}")
        await update.message.reply_text(
            "❌ Виникла помилка при відправленні повідомлення.\n"
            "Будь ласка, спробуйте пізніше або використайте /menu"
        )
    
    return CHAT_MODE

# 📝 Обробники замовлення
async def doctor_handler(update: Update, context: CallbackContext) -> int:
    """Обробник введення даних лікаря"""
    doctor_name = update.message.text.strip()
    
    if len(doctor_name) < 2:
        await update.message.reply_text(
            "❌ Прізвище лікаря занадто коротке.\n"
            "Будь ласка, введіть коректне прізвище:"
        )
        return DOCTOR
    
    context.user_data["doctor"] = doctor_name
    logging.info(f"Отримано ім'я лікаря: {doctor_name}")
    
    await update.message.reply_text(
        "📞 Введіть **контактний номер телефону**:\n"
        "_(наприклад: +380501234567 або 0501234567)_",
        parse_mode='Markdown'
    )
    return PHONE

async def phone_handler(update: Update, context: CallbackContext) -> int:
    """Обробник введення номера телефону"""
    phone = update.message.text.strip()
    
    if not validate_phone(phone):
        await update.message.reply_text(
            "❌ Некоректний формат номера телефону.\n"
            "Будь ласка, введіть номер у форматі:\n"
            "• +380501234567\n"
            "• 0501234567"
        )
        return PHONE
    
    context.user_data["phone"] = phone
    logging.info(f"Отримано телефон: {phone}")
    
    await update.message.reply_text(
        "🏥 Введіть **назву клініки**:",
        parse_mode='Markdown'
    )
    return CLINIC

async def clinic_handler(update: Update, context: CallbackContext) -> int:
    """Обробник введення назви клініки"""
    clinic_name = update.message.text.strip()
    
    if len(clinic_name) < 3:
        await update.message.reply_text(
            "❌ Назва клініки занадто коротка.\n"
            "Будь ласка, введіть повну назву:"
        )
        return CLINIC
    
    context.user_data["clinic"] = clinic_name
    logging.info(f"Отримано назву клініки: {clinic_name}")
    
    await update.message.reply_text(
        "📅 Введіть **дату замовлення** у форматі ДД.ММ.РРРР:\n"
        "_(наприклад: 24.12.2024)_",
        parse_mode='Markdown'
    )
    return DATETIME

async def datetime_handler(update: Update, context: CallbackContext) -> int:
    """Обробник введення дати"""
    date_str = update.message.text.strip()
    
    if not validate_date(date_str):
        await update.message.reply_text(
            "❌ Некоректний формат дати.\n"
            "Будь ласка, введіть дату у форматі **ДД.ММ.РРРР**\n"
            "Наприклад: 24.12.2024",
            parse_mode='Markdown'
        )
        return DATETIME
    
    context.user_data["date"] = date_str
    logging.info(f"Отримано дату: {date_str}")
    
    await update.message.reply_text(
        "👤 Введіть **ПІБ пацієнта**:",
        parse_mode='Markdown'
    )
    return PATIENT

async def patient_handler(update: Update, context: CallbackContext) -> int:
    """Обробник введення даних пацієнта"""
    patient_name = update.message.text.strip()
    
    if len(patient_name) < 5:
        await update.message.reply_text(
            "❌ ПІБ пацієнта занадто коротке.\n"
            "Будь ласка, введіть повне ПІБ:"
        )
        return PATIENT
    
    context.user_data["patient"] = patient_name
    logging.info(f"Отримано ПІБ пацієнта: {patient_name}")
    
    await update.message.reply_text(
        "🔩 Введіть **систему імплантатів**:",
        parse_mode='Markdown'
    )
    return IMPLANT_SYSTEM

async def implant_handler(update: Update, context: CallbackContext) -> int:
    """Обробник введення системи імплантатів"""
    implant_system = update.message.text.strip()
    
    if len(implant_system) < 3:
        await update.message.reply_text(
            "❌ Назва системи занадто коротка.\n"
            "Будь ласка, введіть повну назву:"
        )
        return IMPLANT_SYSTEM
    
    context.user_data["implant_system"] = implant_system
    logging.info(f"Отримано систему імплантатів: {implant_system}")
    
    await update.message.reply_text(
        "🦷 Введіть **зону імплантації**:\n"
        "_(наприклад: 1.1 або 2.4 - 4.2x10 або будь-який опис)_",
        parse_mode='Markdown'
    )
    return ZONE

async def zone_handler(update: Update, context: CallbackContext) -> int:
    """Обробник введення зони імплантації"""
    zone = update.message.text.strip()
    
    if not validate_zone(zone):
        await update.message.reply_text(
            "❌ Будь ласка, введіть зону імплантації:"
        )
        return ZONE
    
    # Зберігаємо user_id для сповіщень
    context.user_data["user_id"] = update.effective_user.id
    context.user_data["zone"] = zone
    context.user_data["status"] = "Новий"
    context.user_data["timestamp"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    
    logging.info(f"Отримано зону: {zone}")
    logging.info("Всі дані зібрано. Збереження...")
    
    # Показуємо дані користувачу для підтвердження
    await show_order_summary(update, context)
    
    # Збереження в Google Sheets
    success = await save_to_sheet_async(context.user_data)
    
    if success:
        # Сповіщення адміністратора
        await notify_admin_async(context)
        
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]]
        await update.message.reply_text(
            "✅ **Замовлення успішно прийнято і збережено!**\n\n"
            "Адміністратор отримав сповіщення і зв'яжеться з вами.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]]
        await update.message.reply_text(
            "⚠️ **Замовлення прийнято, але виникла проблема зі збереженням.**\n"
            "Адміністратор був сповіщений.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    return MAIN_MENU

async def show_order_summary(update: Update, context: CallbackContext):
    """Показує зведення замовлення"""
    data = context.user_data
    summary = (
        "📋 **Зведення вашого замовлення:**\n\n"
        f"👨‍⚕️ **Лікар:** {data.get('doctor', 'N/A')}\n"
        f"📞 **Телефон:** {data.get('phone', 'N/A')}\n"
        f"🏥 **Клініка:** {data.get('clinic', 'N/A')}\n"
        f"📅 **Дата:** {data.get('date', 'N/A')}\n"
        f"👤 **Пацієнт:** {data.get('patient', 'N/A')}\n"
        f"🔩 **Система:** {data.get('implant_system', 'N/A')}\n"
        f"🦷 **Зона:** {data.get('zone', 'N/A')}\n"
        f"⏰ **Час створення:** {data.get('timestamp', 'N/A')}"
    )
    
    await update.message.reply_text(summary, parse_mode='Markdown')

# 💾 Робота з Google Sheets
async def save_to_sheet_async(data: Dict[str, Any]) -> bool:
    """Асинхронне збереження в Google Sheets"""
    if not WORKSHEET or not HEADERS:
        logging.error("Google Sheet не підключений")
        return False
    
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, save_to_sheet_sync, data)
        return True
    except Exception as e:
        logging.error(f"Помилка збереження в Google Sheet: {e}")
        return False

def save_to_sheet_sync(data: Dict[str, Any]):
    """Синхронне збереження в Google Sheets"""
    try:
        # Створюємо рядок даних відповідно до заголовків таблиці
        row = []
        
        for header in HEADERS:
            value = ""
            # Шукаємо відповідність між заголовком таблиці і полями бота
            for field_key, header_key in FIELD_MAPPING.items():
                if header.strip() == header_key.strip():
                    value = data.get(field_key, "")
                    break
            
            # Якщо не знайдено прямої відповідності, пробуємо знайти часткову
            if not value and header:
                for field_key, field_value in data.items():
                    if field_key.lower() in header.lower() or header.lower() in field_key.lower():
                        value = field_value
                        break
            
            row.append(str(value))
        
        # Додаємо рядок в таблицю
        WORKSHEET.append_row(row)
        logging.info(f"Рядок додано в Google Sheet: {row}")
        
    except Exception as e:
        logging.error(f"Помилка при записі в Google Sheet: {e}")
        raise

# 📧 Сповіщення
async def notify_admin_async(context: CallbackContext):
    """Сповіщення адміністратора про нове замовлення"""
    try:
        data = context.user_data
        # Отримуємо user_id з ефективного користувача
        user_id = data.get('user_id', 'N/A')
        
        msg = (
            "🆕 **НОВЕ ЗАМОВЛЕННЯ ІМПЛАНТАТА**\n\n"
            f"👨‍⚕️ **Лікар:** {data.get('doctor', 'N/A')}\n"
            f"📞 **Телефон:** {data.get('phone', 'N/A')}\n"
            f"🏥 **Клініка:** {data.get('clinic', 'N/A')}\n"
            f"📅 **Дата замовлення:** {data.get('date', 'N/A')}\n"
            f"👤 **Пацієнт:** {data.get('patient', 'N/A')}\n"
            f"🔩 **Система:** {data.get('implant_system', 'N/A')}\n"
            f"🦷 **Зона:** {data.get('zone', 'N/A')}\n"
            f"📌 **Статус:** {data.get('status', 'N/A')}\n"
            f"⏰ **Час:** {data.get('timestamp', 'N/A')}\n"
            f"🆔 **User ID:** `{user_id}`"
        )
        
        # Кнопки для адміна
        admin_keyboard = [
            [InlineKeyboardButton("✅ Прийняти", callback_data=f"accept_{user_id}")],
            [InlineKeyboardButton("❌ Відхилити", callback_data=f"reject_{user_id}")],
            [InlineKeyboardButton("💬 Відповісти", callback_data=f"reply_{user_id}")],
        ]
        
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=msg,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(admin_keyboard)
        )
        
        logging.info("Сповіщення адміністратору відправлено")
        
    except Exception as e:
        logging.error(f"Помилка відправлення сповіщення адміністратору: {e}")

# 👥 Функції для адміністратора
async def admin_callback_handler(update: Update, context: CallbackContext):
    """Обробник дій адміністратора"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_CHAT_ID:
        await query.answer("❌ Недостатньо прав", show_alert=True)
        return
    
    action, user_id = query.data.split("_", 1)
    
    if action == "accept":
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ ПРИЙНЯТО", callback_data="accepted")
            ]])
        )
        
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text="✅ **Ваше замовлення прийнято!**\n\nМи розпочали обробку вашого замовлення.",
                parse_mode='Markdown'
            )
        except:
            logging.error(f"Не вдалося відправити сповіщення користувачу {user_id}")
    
    elif action == "reject":
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ ВІДХИЛЕНО", callback_data="rejected")
            ]])
        )
        
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text="❌ **Ваше замовлення відхилено**\n\nЗв'яжіться з нами для уточнення деталей.",
                parse_mode='Markdown'
            )
        except:
            logging.error(f"Не вдалося відправити сповіщення користувачу {user_id}")
    
    elif action == "reply":
        # Встановлюємо режим відповіді адміністратора
        context.chat_data['admin_reply_to'] = user_id
        await query.message.reply_text(
            f"💬 Введіть повідомлення для користувача {user_id}:"
        )

async def admin_message_handler(update: Update, context: CallbackContext):
    """Обробник повідомлень адміністратора"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    
    # Перевіряємо, чи відповідає адмін користувачу
    reply_to = context.chat_data.get('admin_reply_to')
    if reply_to:
        try:
            admin_message = update.message.text
            await context.bot.send_message(
                chat_id=int(reply_to),
                text=f"📩 **Повідомлення від адміністратора:**\n\n{admin_message}",
                parse_mode='Markdown'
            )
            
            await update.message.reply_text(
                f"✅ Повідомлення відправлено користувачу {reply_to}"
            )
            
            # Скидаємо режим відповіді
            context.chat_data.pop('admin_reply_to', None)
            
        except Exception as e:
            await update.message.reply_text(
                f"❌ Помилка відправлення повідомлення: {e}"
            )
            context.chat_data.pop('admin_reply_to', None)

# 🔄 Службові команди
async def menu_command(update: Update, context: CallbackContext) -> int:
    """Команда повернення в головне меню"""
    return await show_main_menu(update, context)

async def cancel_handler(update: Update, context: CallbackContext) -> int:
    """Обробник скасування"""
    keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]]
    
    await update.message.reply_text(
        "❌ **Операцію скасовано**",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return MAIN_MENU

async def error_handler(update: object, context: CallbackContext):
    """Глобальний обробник помилок"""
    logging.error(f"Exception: {context.error}")
    
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ Виникла помилка. Використайте /start для перезапуску."
        )

def main():
    """Основна функція"""
    # Налаштування логування
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO,
        handlers=[
            logging.FileHandler('bot.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    if not WORKSHEET:
        logging.error("Не вдалося підключитися до Google Sheets!")
        return
    
    logging.info("Запуск бота...")
    
    # Створення програми
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # ConversationHandler для замовлень
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(menu_callback, pattern="^(new_order|chat_support|help|back_to_menu)$")
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(menu_callback, pattern="^(new_order|chat_support|help|back_to_menu)$")
            ],
            DOCTOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, doctor_handler)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_handler)],
            CLINIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, clinic_handler)],
            DATETIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, datetime_handler)],
            PATIENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, patient_handler)],
            IMPLANT_SYSTEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, implant_handler)],
            ZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, zone_handler)],
            CHAT_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_handler),
            CommandHandler("menu", menu_command),
            CommandHandler("start", start),
        ],
        per_message=False,
    )
    
    # Додавання обробників
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(accept_|reject_|reply_)"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_message_handler))
    application.add_error_handler(error_handler)
    
    logging.info("Бот запущено. Починаю polling...")
    
    # Запуск
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        logging.info("Отримано сигнал зупинки")
    except Exception as e:
        logging.error(f"Критична помилка: {e}")
    finally:
        logging.info("Бот зупинено")

if __name__ == '__main__':
    main()
