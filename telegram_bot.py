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
MAX_MESSAGE_LENGTH = 4000
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@vlasenko_b")
WEBSITE_URL = "https://www.obabkolab.com.ua/"

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
        spreadsheet = gc.open_by_key(SPREADSHEET_ID)
        
        try:
            worksheet = spreadsheet.get_worksheet_by_id(WORKSHEET_ID)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.worksheet("Ответы на форму")

        headers = worksheet.row_values(1) if worksheet.row_count > 0 else []
        
        logging.info(f"Підключена Google Таблиця. Заголовки: {headers}")
        return worksheet, headers
    
    except Exception as e:
        logging.error(f"Критична помилка підключення до Google Sheets: {e}")
        return None, []

# Глобальні змінні
WORKSHEET, HEADERS = setup_google_sheets()

# 🧩 Етапи розмови
DOCTOR, PHONE, CLINIC, DATETIME, PATIENT, IMPLANT_SYSTEM, ZONE, MAIN_MENU, CHAT_MODE, FILES_MODE = range(10)

# 📊 Оновлене відповідність полів бота і таблиці за колонками
COLUMN_MAPPING = {
    "doctor": "J",       # Лікар
    "phone": "K",        # Телефон
    "clinic": "L",       # Клініка
    "date": "O",         # Дата здачі
    "patient": "R",      # Пацієнт
    "implant_system": "S",  # Система
    "zone": "T",         # Зона
    "status": "Z",       # Статус
}

# 🔍 Функції валідації
def validate_phone(phone: str) -> bool:
    """Валідація номера телефону (український формат)"""
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)
    pattern = r'^(?:\+380|0)\d{9}$'
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
    return len(zone.strip()) >= 2

# 🏠 Головне меню
def get_main_menu_keyboard():
    """Створює клавіатуру головного меню з оновленими пунктами"""
    keyboard = [
        [InlineKeyboardButton("📝 Нове замовлення", callback_data="new_order")],
        [InlineKeyboardButton("💬 Чат з підтримкою", callback_data="chat_support"),
         InlineKeyboardButton("💰 Прайс", callback_data="price")],
        [InlineKeyboardButton("🌐 Сайт", callback_data="website"),
         InlineKeyboardButton("📁 Надіслати файл", callback_data="send_files")],
        [InlineKeyboardButton("ℹ️ Довідка", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def show_main_menu(update: Update, context: CallbackContext):
    """Показує головне меню з красивим оформленням"""
    menu_text = (
        "🏥 <b>Система замовлень імплантатів</b>\n\n"
        "🔹 <b>Нове замовлення</b> - оформити замовлення на імплантати\n"
        "🔹 <b>Чат з підтримкою</b> - зв'язатися з нашими спеціалістами\n" 
        "🔹 <b>Прайс</b> - переглянути актуальні ціни\n"
        "🔹 <b>Сайт</b> - відвідати наш офіційний сайт\n"
        "🔹 <b>Надіслати файл</b> - відправити документи чи фото\n"
        "🔹 <b>Довідка</b> - допомога по роботі з ботом\n\n"
        "👆 <i>Оберіть потрібну дію:</i>"
    )
    
    keyboard = get_main_menu_keyboard()
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            menu_text, 
            parse_mode='HTML',
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            menu_text,
            parse_mode='HTML', 
            reply_markup=keyboard
        )
    
    return MAIN_MENU

# 📝 Обробники команд
async def start(update: Update, context: CallbackContext) -> int:
    """Початкова команда"""
    user = update.effective_user
    first_name = user.first_name or ""
    
    welcome_text = (
        f"👋 <b>Вітаємо, {first_name}!</b>\n\n"
        "🏥 <b>Система замовлень Хірургічних шаблонів</b>\n\n"
        "🎯 За допомогою цього бота ви можете:\n"
        "• Оформити замовлення на імплантати\n"
        "• Зв'язатися з нашою підтримкою\n"
        "• Переглянути прайс-лист\n"
        "• Надіслати необхідні файли\n\n"
        "👆 <i>Оберіть потрібну дію:</i>"
    )
    
    keyboard = get_main_menu_keyboard()
    await update.message.reply_text(
        welcome_text,
        parse_mode='HTML',
        reply_markup=keyboard
    )
    
    return MAIN_MENU

async def menu_callback(update: Update, context: CallbackContext) -> int:
    """Обробник натискань кнопок головного меню"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "new_order":
        await query.edit_message_text(
            "👨‍⚕️ <b>Починаємо оформлення замовлення</b>\n\n"
            "📝 Введіть <b>ПІБ лікаря</b>:",
            parse_mode='HTML'
        )
        return DOCTOR
        
    elif query.data == "chat_support":
        support_text = (
            "💬 <b>Чат з підтримкою</b>\n\n"
            "✉️ Напишіть ваше повідомлення, і ми передамо його спеціалісту.\n"
            "📞 Ви отримаєте відповідь найближчим часом.\n\n"
            "💡 <i>Для повернення в головне меню використовуйте /menu</i>"
        )
        await query.edit_message_text(
            support_text,
            parse_mode='HTML'
        )
        return CHAT_MODE
        
    elif query.data == "send_files":
        files_text = (
            "📁 <b>Надсилання файлів</b>\n\n"
            "📤 Надішліть файли (фото, документи, скани) одним або декількома повідомленнями.\n"
            "🔄 Ми автоматично передамо їх спеціалісту для обробки.\n\n"
            "💡 <i>Щоб повернутися в меню, використайте /menu</i>"
        )
        await query.edit_message_text(
            files_text,
            parse_mode='HTML'
        )
        return FILES_MODE

    elif query.data == "price":
        # Надсилаємо прайс-листи як фото
        await query.message.reply_photo(
            photo="AgACAgIAAxkBAAICNmda6Mxv8bPEaK95ZqD25N4nrlwqAAJ07jEbDy-pSvGEoq_uPfNZAQADAgADeQADNgQ",
            caption="💰 <b>Прайс-лист: Хірургічні шаблони</b>\n\nАктуальні ціни на хірургічні шаблони з опорою на зуби:",
            parse_mode='HTML'
        )
        
        await query.message.reply_photo(
            photo="AgACAgIAAxkBAAICOWda6MxrGCKN68l8WuUhYf5W5NBEAAJB7jEbDy-pShaH1LgtPXHxAQADAgADeQADNgQ",
            caption="💰 <b>Прайс-лист: Різні послуги</b>\n\nПовний перелік наших послуг та їх вартість:",
            parse_mode='HTML'
        )
        
        await query.message.reply_photo(
            photo="AgACAgIAAxkBAAICOGda6MxsEaG_cjWUBplttTXUQiPFAAJA7jEbDy-pStCB5_hRy0YkAQADAgADeQADNgQ",
            caption="💰 <b>Прайс-лист: Основні послуги</b>\n\nДетальна інформація про наші основні послуги:",
            parse_mode='HTML'
        )
        
        keyboard = [[InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]]
        await query.message.reply_text(
            "📋 <b>Прайс-листи надіслано!</b>\n\n"
            "📞 Для уточнення деталей або індивідуальних розрахунків зв'яжіться з нашою підтримкою.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return MAIN_MENU

    elif query.data == "website":
        website_text = (
            f"🌐 <b>Наш офіційний сайт</b>\n\n"
            f"🔗 <a href='{WEBSITE_URL}'>ObaBko Lab - Цифрова стоматологія</a>\n\n"
            "💡 На сайті ви знайдете:\n"
            "• Повну інформацію про наші послуги\n"
            "• Портфоліо робіт\n"
            "• Контактні дані\n"
            "• Форму для замовлення\n\n"
            "📱 Перейдіть за посиланням, щоб відвідати наш сайт!"
        )
        
        keyboard = [
            [InlineKeyboardButton("🌐 Відкрити сайт", url=WEBSITE_URL)],
            [InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]
        ]
        await query.edit_message_text(
            website_text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=False
        )
        return MAIN_MENU

    elif query.data == "help":
        help_text = (
            "🆘 <b>Довідка по боту</b>\n\n"
            "<b>📋 Доступні команди:</b>\n"
            "• <code>/start</code> - Головне меню\n"
            "• <code>/menu</code> - Повернутися в меню\n"
            "• <code>/cancel</code> - Скасувати операцію\n\n"
            "<b>📞 Технічна підтримка:</b>\n"
            f"• Telegram: {ADMIN_USERNAME}\n\n"
            "<b>💡 Як користуватися ботом:</b>\n"
            "1. Оберіть потрібну дію в головному меню\n"
            "2. Слідуйте інструкціям бота\n"
            "3. При виникненні питань звертайтеся в підтримку"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]]
        await query.edit_message_text(
            help_text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return MAIN_MENU
        
    elif query.data == "back_to_menu":
        return await show_main_menu(update, context)

# 💬 Чат з підтримкою
async def chat_handler(update: Update, context: CallbackContext) -> int:
    """Обробник повідомлень у режимі чату - пересилає повідомлення адміністратору"""
    user_message = update.message.text
    user = update.effective_user
    username = user.username or "Невідомо"
    first_name = user.first_name or ""
    
    admin_msg = (
        "💬 <b>ПОВІДОМЛЕННЯ ВІД КОРИСТУВАЧА</b>\n\n"
        f"👤 <b>Користувач:</b> {first_name} (@{username})\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
        f"📝 <b>Повідомлення:</b>\n{user_message}"
    )
    
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_msg,
            parse_mode='HTML'
        )
        
        await update.message.reply_text(
            "✅ <b>Ваше повідомлення відправлено!</b>\n\n"
            "📞 Спеціаліст зв'яжеться з вами найближчим часом.\n\n"
            "💡 <i>Ви можете продовжити писати або повернутися в</i> /menu",
            parse_mode='HTML'
        )
        
    except Exception as e:
        logging.error(f"Помилка надсилання повідомлення адміну: {e}")
        await update.message.reply_text(
            "❌ Виникла помилка при відправленні повідомлення.\n"
            "Будь ласка, спробуйте пізніше або використайте /menu"
        )
    
    return CHAT_MODE

# 📁 Надсилання файлів
async def files_handler(update: Update, context: CallbackContext):
    """Обробник надсилання файлів - пересилає файли адміністратору"""
    user = update.effective_user
    username = user.username or "Невідомо"
    first_name = user.first_name or ""

    message_type = update.message.effective_attachment
    
    if message_type:
        caption = (
            f"📁 <b>Файл від користувача</b>\n\n"
            f"👤 <b>Користувач:</b> {first_name} (@{username})\n"
            f"🆔 <b>ID:</b> <code>{user.id}</code>"
        )
        
        try:
            # Пересилаємо файл адміністратору
            await context.bot.forward_message(
                chat_id=ADMIN_CHAT_ID,
                from_chat_id=update.message.chat_id,
                message_id=update.message.message_id
            )
            # Відправляємо інформацію про користувача
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=caption,
                parse_mode='HTML'
            )
            
            await update.message.reply_text(
                "✅ <b>Файл успішно відправлено!</b>\n\n"
                "📞 Спеціаліст опрацює ваш файл найближчим часом.\n\n"
                "💡 <i>Ви можете надіслати ще файли або повернутися в</i> /menu",
                parse_mode='HTML'
            )

        except Exception as e:
            logging.error(f"Помилка пересилання файлу: {e}")
            await update.message.reply_text(
                "❌ Виникла помилка при відправленні файлу.\n"
                "Будь ласка, спробуйте пізніше або використайте /menu"
            )
    else:
        await update.message.reply_text(
            "📁 Будь ласка, надішліть файл (фото, документ, скан).\n\n"
            "💡 Щоб повернутися в головне меню, використайте /menu"
        )

    return FILES_MODE

# 📝 Обробники замовлення
async def doctor_handler(update: Update, context: CallbackContext) -> int:
    doctor_name = update.message.text.strip()
    if len(doctor_name) < 2:
        await update.message.reply_text("❌ ПІБ лікаря занадто коротке. Будь ласка, введіть коректне ПІБ:")
        return DOCTOR
    context.user_data["doctor"] = doctor_name
    await update.message.reply_text("📞 Введіть <b>контактний номер телефону</b>:\n<i>(наприклад: +380501234567)</i>", parse_mode='HTML')
    return PHONE

async def phone_handler(update: Update, context: CallbackContext) -> int:
    phone = update.message.text.strip()
    if not validate_phone(phone):
        await update.message.reply_text("❌ Некоректний формат номера телефону. Будь ласка, введіть номер у форматі: +380501234567")
        return PHONE
    context.user_data["phone"] = phone
    await update.message.reply_text("🏥 Введіть <b>назву клініки</b>:", parse_mode='HTML')
    return CLINIC

async def clinic_handler(update: Update, context: CallbackContext) -> int:
    clinic_name = update.message.text.strip()
    if len(clinic_name) < 3:
        await update.message.reply_text("❌ Назва клініки занадто коротка. Будь ласка, введіть повну назву:")
        return CLINIC
    context.user_data["clinic"] = clinic_name
    await update.message.reply_text("📅 Введіть <b>дату здачі</b> у форматі ДД.ММ.РРРР:", parse_mode='HTML')
    return DATETIME

async def datetime_handler(update: Update, context: CallbackContext) -> int:
    date_str = update.message.text.strip()
    if not validate_date(date_str):
        await update.message.reply_text("❌ Некоректний формат дати. Будь ласка, введіть дату у форматі <b>ДД.ММ.РРРР</b>", parse_mode='HTML')
        return DATETIME
    context.user_data["date"] = date_str
    await update.message.reply_text("👤 Введіть <b>ПІБ пацієнта</b>:", parse_mode='HTML')
    return PATIENT

async def patient_handler(update: Update, context: CallbackContext) -> int:
    patient_name = update.message.text.strip()
    if len(patient_name) < 5:
        await update.message.reply_text("❌ ПІБ пацієнта занадто коротке. Будь ласка, введіть повне ПІБ:")
        return PATIENT
    context.user_data["patient"] = patient_name
    await update.message.reply_text("🔩 Введіть <b>систему імплантатів</b>:", parse_mode='HTML')
    return IMPLANT_SYSTEM

async def implant_handler(update: Update, context: CallbackContext) -> int:
    implant_system = update.message.text.strip()
    if len(implant_system) < 3:
        await update.message.reply_text("❌ Назва системи занадто коротка. Будь ласка, введіть повну назву:")
        return IMPLANT_SYSTEM
    context.user_data["implant_system"] = implant_system
    await update.message.reply_text("🦷 Введіть <b>передбачувану зону встановлення імплантатів</b>:\n<i>Вкажіть у форматі \"номер зуба - діаметр/довжина імплантата\"</i>", parse_mode='HTML')
    return ZONE

async def zone_handler(update: Update, context: CallbackContext) -> int:
    zone = update.message.text.strip()
    if not validate_zone(zone):
        await update.message.reply_text("❌ Будь ласка, введіть зону імплантації:")
        return ZONE
    
    context.user_data["user_id"] = update.effective_user.id
    context.user_data["zone"] = zone
    context.user_data["status"] = "Новий"
    context.user_data["timestamp"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    
    await show_order_summary(update, context)
    
    success = await save_to_sheet_async(context.user_data)
    
    if success:
        await notify_admin_async(context)
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]]
        await update.message.reply_text(
            "✅ <b>Замовлення успішно прийнято і збережено!</b>\n\n"
            f"📞 Спеціаліст {ADMIN_USERNAME} зв'яжеться з вами найближчим часом.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]]
        await update.message.reply_text(
            "⚠️ <b>Замовлення прийнято, але виникла проблема зі збереженням.</b>\n"
            f"📞 {ADMIN_USERNAME} був сповіщений.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    return MAIN_MENU

async def show_order_summary(update: Update, context: CallbackContext):
    data = context.user_data
    summary = (
        "📋 <b>Зведення вашого замовлення:</b>\n\n"
        f"👨‍⚕️ <b>Лікар:</b> {data.get('doctor', 'N/A')}\n"
        f"📞 <b>Телефон:</b> {data.get('phone', 'N/A')}\n"
        f"🏥 <b>Клініка:</b> {data.get('clinic', 'N/A')}\n"
        f"📅 <b>Дата здачі:</b> {data.get('date', 'N/A')}\n"
        f"👤 <b>Пацієнт:</b> {data.get('patient', 'N/A')}\n"
        f"🔩 <b>Система:</b> {data.get('implant_system', 'N/A')}\n"
        f"🦷 <b>Зона:</b> {data.get('zone', 'N/A')}\n"
        f"⏰ <b>Час створення:</b> {data.get('timestamp', 'N/A')}"
    )
    await update.message.reply_text(summary, parse_mode='HTML')

# Оновлена функція збереження в Google Sheets за колонками
async def save_to_sheet_async(data: Dict[str, Any]) -> bool:
    if not WORKSHEET:
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
    try:
        # Знаходимо останній рядок з даними
        last_row = len(WORKSHEET.get_all_values()) + 1
        
        # Записуємо дані у відповідні колонки
        for field, column in COLUMN_MAPPING.items():
            value = str(data.get(field, ""))
            if value:  # Записуємо тільки якщо є значення
                cell = f"{column}{last_row}"
                WORKSHEET.update(cell, value)
                logging.info(f"Записано в {cell}: {value}")
        
        logging.info(f"Дані замовлення збережено у рядок {last_row}")
        
    except Exception as e:
        logging.error(f"Помилка при записі в Google Sheet: {e}")
        raise

async def notify_admin_async(context: CallbackContext):
    try:
        data = context.user_data
        user_id = data.get('user_id', 'N/A')
        
        msg = (
            "🆕 <b>НОВЕ ЗАМОВЛЕННЯ ІМПЛАНТАТА</b>\n\n"
            f"👨‍⚕️ <b>Лікар:</b> {data.get('doctor', 'N/A')}\n"
            f"📞 <b>Телефон:</b> {data.get('phone', 'N/A')}\n"
            f"🏥 <b>Клініка:</b> {data.get('clinic', 'N/A')}\n"
            f"📅 <b>Дата здачі:</b> {data.get('date', 'N/A')}\n"
            f"👤 <b>Пацієнт:</b> {data.get('patient', 'N/A')}\n"
            f"🔩 <b>Система:</b> {data.get('implant_system', 'N/A')}\n"
            f"🦷 <b>Зона:</b> {data.get('zone', 'N/A')}\n"
            f"📌 <b>Статус:</b> {data.get('status', 'N/A')}\n"
            f"⏰ <b>Час:</b> {data.get('timestamp', 'N/A')}\n"
            f"🆔 <b>User ID:</b> <code>{user_id}</code>"
        )
        
        admin_keyboard = [
            [InlineKeyboardButton("✅ Прийняти", callback_data=f"accept_{user_id}")],
            [InlineKeyboardButton("❌ Відхилити", callback_data=f"reject_{user_id}")],
            [InlineKeyboardButton("💬 Відповісти", callback_data=f"reply_{user_id}")],
        ]
        
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=msg,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(admin_keyboard)
        )
        
        logging.info("Сповіщення адміністратору відправлено")
        
    except Exception as e:
        logging.error(f"Помилка надсилання повідомлення адміну: {e}")

async def admin_callback_handler(update: Update, context: CallbackContext):
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
                text="✅ <b>Ваше замовлення прийнято!</b>\n\n"
                     f"📞 Наш спеціаліст {ADMIN_USERNAME} зв'яжеться з вами найближчим часом.",
                parse_mode='HTML'
            )
        except Exception as e:
            logging.error(f"Не вдалося відправити сповіщення користувачу {user_id}: {e}")
    
    elif action == "reject":
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ ВІДХИЛЕНО", callback_data="rejected")
            ]])
        )
        
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text="❌ <b>Ваше замовлення відхилено</b>\n\n"
                     f"📞 Зв'яжіться з {ADMIN_USERNAME} для уточнення деталей.",
                parse_mode='HTML'
            )
        except Exception as e:
            logging.error(f"Не вдалося відправити сповіщення користувачу {user_id}: {e}")
    
    elif action == "reply":
        context.chat_data['admin_reply_to'] = user_id
        await query.message.reply_text(
            f"💬 Введіть повідомлення для користувача {user_id}:"
        )

async def admin_message_handler(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    
    reply_to = context.chat_data.get('admin_reply_to')
    if reply_to:
        try:
            admin_message = update.message.text
            await context.bot.send_message(
                chat_id=int(reply_to),
                text=f"📩 <b>Повідомлення від адміністратора:</b>\n\n{admin_message}",
                parse_mode='HTML'
            )
            
            await update.message.reply_text(
                f"✅ Повідомлення відправлено користувачу {reply_to}"
            )
            
            context.chat_data.pop('admin_reply_to', None)
            
        except Exception as e:
            await update.message.reply_text(
                f"❌ Помилка відправлення повідомлення: {e}"
            )
            context.chat_data.pop('admin_reply_to', None)

async def menu_command(update: Update, context: CallbackContext) -> int:
    return await show_main_menu(update, context)

async def cancel_handler(update: Update, context: CallbackContext) -> int:
    keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]]
    await update.message.reply_text(
        "❌ <b>Операцію скасовано</b>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return MAIN_MENU

async def error_handler(update: object, context: CallbackContext):
    logging.error(f"Exception: {context.error}")
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ Виникла помилка. Використайте /start для перезапуску."
        )

def main():
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
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(menu_callback, pattern="^(new_order|chat_support|send_files|help|back_to_menu|price|website)$")
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(menu_callback, pattern="^(new_order|chat_support|send_files|help|back_to_menu|price|website)$")
            ],
            DOCTOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, doctor_handler)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_handler)],
            CLINIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, clinic_handler)],
            DATETIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, datetime_handler)],
            PATIENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, patient_handler)],
            IMPLANT_SYSTEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, implant_handler)],
            ZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, zone_handler)],
            CHAT_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler)],
            FILES_MODE: [MessageHandler(filters.ATTACHMENT | (filters.TEXT & ~filters.COMMAND), files_handler)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_handler),
            CommandHandler("menu", menu_command),
            CommandHandler("start", start),
        ],
        per_message=False,
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(accept_|reject_|reply_)"))
    application.add_handler(MessageHandler(filters.TEXT & filters.Chat(chat_id=ADMIN_CHAT_ID) & ~filters.COMMAND, admin_message_handler))
    application.add_error_handler(error_handler)
    
    logging.info("Бот запущено. Починаю polling...")
    
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
