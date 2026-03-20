import os
import logging
from datetime import datetime, time, timedelta
from typing import Dict, Optional, List
import sqlite3
from contextlib import contextmanager
import json
from enum import Enum

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
CHANGE_REQUEST_DESC, CHANGE_REQUEST_PRIORITY, URGENT_ALERT_DESC = range(3)

# Конфигурация - берем токен из переменных окружения
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    logger.error("BOT_TOKEN not set! Please add it to Railway environment variables.")
    exit(1)

# Путь к базе данных - на Railway используем /data/
DB_PATH = os.environ.get('DB_PATH', '/data/bp_framework.db')

# Класс для работы с базой данных
class Database:
    def __init__(self, db_name=DB_PATH):
        self.db_name = db_name
        # Убедимся, что директория /data существует
        db_dir = os.path.dirname(self.db_name)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        self.init_db()
    
    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    role TEXT DEFAULT 'team_member',
                    team TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS meetings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_type TEXT,
                    title TEXT,
                    meeting_date DATE,
                    meeting_time TIME,
                    duration_minutes INTEGER,
                    participants TEXT,
                    agenda TEXT,
                    created_by INTEGER,
                    is_recurring BOOLEAN DEFAULT 0,
                    recurring_pattern TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (created_by) REFERENCES users(user_id)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS change_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    requester_id INTEGER,
                    description TEXT,
                    priority TEXT CHECK(priority IN ('high', 'medium', 'low')),
                    status TEXT DEFAULT 'new',
                    document_link TEXT,
                    task_tracker_link TEXT,
                    assigned_to INTEGER,
                    business_impact TEXT,
                    metrics_required BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TIMESTAMP,
                    FOREIGN KEY (requester_id) REFERENCES users(user_id),
                    FOREIGN KEY (assigned_to) REFERENCES users(user_id)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    feedback_type TEXT,
                    content TEXT,
                    meeting_id INTEGER,
                    rating INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS urgent_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    alert_type TEXT,
                    description TEXT,
                    is_resolved BOOLEAN DEFAULT 0,
                    resolved_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    description TEXT,
                    priority TEXT,
                    status TEXT DEFAULT 'new',
                    change_request_id INTEGER,
                    assigned_to INTEGER,
                    due_date DATE,
                    estimated_hours FLOAT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (change_request_id) REFERENCES change_requests(id),
                    FOREIGN KEY (assigned_to) REFERENCES users(user_id)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metrics_checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id INTEGER,
                    checked_by INTEGER,
                    original_urgency TEXT,
                    analysis_result TEXT,
                    is_valid_urgency BOOLEAN,
                    recommendation TEXT,
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (request_id) REFERENCES change_requests(id),
                    FOREIGN KEY (checked_by) REFERENCES users(user_id)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS devil_advocate_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id INTEGER,
                    reviewer_id INTEGER,
                    review_comments TEXT,
                    is_legitimate BOOLEAN,
                    risk_assessment TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (request_id) REFERENCES change_requests(id),
                    FOREIGN KEY (reviewer_id) REFERENCES users(user_id)
                )
            """)
            
            logger.info("Database initialized successfully at %s", self.db_name)
    
    def add_user(self, user_id, username, first_name, last_name, role='team_member', team=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR IGNORE INTO users 
                   (user_id, username, first_name, last_name, role, team) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, username, first_name, last_name, role, team)
            )
    
    def create_change_request(self, requester_id, description, priority, 
                            document_link=None, business_impact=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO change_requests 
                   (requester_id, description, priority, document_link, business_impact) 
                   VALUES (?, ?, ?, ?, ?)""",
                (requester_id, description, priority, document_link, business_impact)
            )
            return cursor.lastrowid
    
    def create_urgent_alert(self, user_id, alert_type, description):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO urgent_alerts (user_id, alert_type, description) VALUES (?, ?, ?)",
                (user_id, alert_type, description)
            )
            return cursor.lastrowid
    
    def get_pending_change_requests(self, priority=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = """SELECT cr.*, u.username as requester_name 
                       FROM change_requests cr
                       JOIN users u ON cr.requester_id = u.user_id
                       WHERE cr.status = 'new'"""
            params = []
            
            if priority:
                query += " AND cr.priority = ?"
                params.append(priority)
            
            query += " ORDER BY cr.created_at DESC"
            
            cursor.execute(query, params)
            return cursor.fetchall()
    
    def update_change_request_status(self, request_id, status, reviewed_at=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if reviewed_at:
                cursor.execute(
                    "UPDATE change_requests SET status = ?, reviewed_at = ? WHERE id = ?",
                    (status, reviewed_at, request_id)
                )
            else:
                cursor.execute(
                    "UPDATE change_requests SET status = ? WHERE id = ?",
                    (status, request_id)
                )
    
    def get_active_urgent_alerts(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT ua.*, u.username, u.first_name 
                   FROM urgent_alerts ua
                   JOIN users u ON ua.user_id = u.user_id
                   WHERE ua.is_resolved = 0
                   ORDER BY ua.created_at DESC"""
            )
            return cursor.fetchall()

# Инициализация базы данных
db = Database()

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    db.add_user(user.id, user.username, user.first_name, user.last_name)
    
    welcome_text = (
        f"👋 Привет, {user.first_name}!\n\n"
        "🔷 **Фреймворк управления БП** 🔷\n\n"
        "**Цель:** Снизить хаос, обеспечить прозрачность, защитить ресурсы команды\n\n"
        "**Ключевые принципы:**\n"
        "1️⃣ Регулярные ревью (Ритм встреч)\n"
        "2️⃣ Каналы связи и сбор ОС\n"
        "3️⃣ Принцип работы с изменениями (письменный след)\n"
        "4️⃣ Защита от манипуляций\n\n"
        "**Доступные команды:**\n"
        "/framework - обзор фреймворка\n"
        "/kickoff - провести Kick-off встречу\n"
        "/meetings - управление встречами\n"
        "/change_request - создать запрос на изменение\n"
        "/urgent - срочное оповещение\n"
        "/pending - посмотреть ожидающие запросы\n"
        "/help - помощь"
    )
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def framework_overview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальный обзор фреймворка"""
    framework_text = (
        "📋 **Детальный обзор фреймворка**\n\n"
        
        "**1. Регулярные ревью (Ритм встреч)**\n"
        "• Статус-встречи с бизнесом: 2 раза в неделю по 30 мин\n"
        "  Формат: «Что сделано / Что планируем / Где нужна помощь»\n"
        "• Внутренние статусы: за 2 часа до встречи с бизнесом\n"
        "• Стратсессии / Kick-off: точка входа в процесс\n\n"
        
        "**2. Каналы связи и сбор ОС**\n"
        "• Канал срочных оповещений\n"
        "  Правило: Только для оперативной ОС и критических блокировок\n"
        "• Пул обратной связи: раз в неделю структурированный сбор\n\n"
        
        "**3. Принцип работы с изменениями**\n"
        "• Правило «Письменного следа»: изменение не существует без фиксации\n"
        "• Инструменты: комментарий в документе, задача в трекере\n"
        "• Фраза-триггер: «Зафиксируйте комментарием в документе»\n\n"
        
        "**4. Защита от манипуляций**\n"
        "• Правило «Пяти минут»: пауза на анализ срочности\n"
        "• Контекст vs. Цифры: запрос метрик и обоснований\n"
        "• Роль «Адвоката дьявола» на внутренних статусах"
    )
    
    await update.message.reply_text(framework_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда помощи"""
    help_text = (
        "📚 **Справка по командам**\n\n"
        "/start - Начать работу с ботом\n"
        "/framework - Обзор фреймворка\n"
        "/kickoff - Провести Kick-off встречу\n"
        "/meetings - Управление встречами\n"
        "/change_request - Создать запрос на изменение\n"
        "/urgent - Создать срочное оповещение\n"
        "/pending - Посмотреть ожидающие запросы\n"
        "/help - Показать эту справку\n\n"
        
        "💡 **Совет:** Все изменения должны иметь письменный след!\n"
        "Используйте /change_request для создания запросов."
    )
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def kickoff_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kick-off встреча"""
    kickoff_text = (
        "🚀 **Kick-off встреча**\n\n"
        "**Правила фреймворка:**\n\n"
        "1. **Регулярные встречи**\n"
        "   - Статус-встречи с бизнесом: 2 раза в неделю\n"
        "   - Внутренние статусы: за 2 часа до встречи с бизнесом\n\n"
        "2. **Письменный след**\n"
        "   - Любое изменение фиксируется в /change_request\n"
        "   - Без письменной фиксации изменения не существуют\n\n"
        "3. **Каналы связи**\n"
        "   - Срочные проблемы: /urgent\n"
        "   - Обычные вопросы: на статус-встречах\n\n"
        "4. **Защита от манипуляций**\n"
        "   - Правило 5 минут на анализ срочности\n"
        "   - Все запросы проходят проверку\n\n"
        "✅ **Готовы начать?** Используйте /change_request для первого запроса."
    )
    
    await update.message.reply_text(kickoff_text, parse_mode='Markdown')

async def meetings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать ближайшие встречи"""
    await update.message.reply_text(
        "📅 **Управление встречами**\n\n"
        "**Рекомендуемое расписание:**\n"
        "• Статус-встреча с бизнесом: вторник и пятница, 11:00\n"
        "• Внутренний статус: за 2 часа до встречи с бизнесом\n\n"
        "Скоро здесь появится возможность создавать встречи и получать напоминания.",
        parse_mode='Markdown'
    )

async def pending_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать ожидающие запросы"""
    requests = db.get_pending_change_requests()
    
    if not requests:
        await update.message.reply_text(
            "📭 Нет ожидающих запросов на изменение.\n\n"
            "Создайте запрос с помощью /change_request"
        )
        return
    
    text = "📋 **Ожидающие запросы на изменение:**\n\n"
    for req in requests:
        priority_emoji = "🔴" if req['priority'] == 'high' else "🟡" if req['priority'] == 'medium' else "🟢"
        text += f"{priority_emoji} **#{req['id']}** - {req['description'][:80]}\n"
        text += f"   От: {req['requester_name']} | Приоритет: {req['priority']}\n\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def change_request_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание запроса на изменение"""
    request_text = (
        "📝 **Создание запроса на изменение**\n\n"
        "Помните правило: изменение не существует без письменной фиксации.\n\n"
        "Опишите запрос на изменение (что нужно изменить и почему):\n\n"
        "_(отправьте /cancel для отмены)_"
    )
    
    await update.message.reply_text(request_text, parse_mode='Markdown')
    return CHANGE_REQUEST_DESC

async def change_request_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение описания запроса"""
    context.user_data['change_desc'] = update.message.text
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Высокий", callback_data="priority_high")],
        [InlineKeyboardButton("🟡 Средний", callback_data="priority_medium")],
        [InlineKeyboardButton("🟢 Низкий", callback_data="priority_low")]
    ])
    
    await update.message.reply_text(
        "Выберите приоритет запроса:",
        reply_markup=keyboard
    )
    return CHANGE_REQUEST_PRIORITY

async def change_request_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка приоритета запроса"""
    query = update.callback_query
    await query.answer()
    
    priority = query.data.split('_')[1]
    user_id = update.effective_user.id
    description = context.user_data.get('change_desc', '')
    
    request_id = db.create_change_request(
        requester_id=user_id,
        description=description,
        priority=priority
    )
    
    response_text = (
        f"✅ **Запрос на изменение создан!**\n"
        f"ID запроса: #{request_id}\n"
        f"Приоритет: {priority}\n\n"
        f"**Что дальше?**\n"
        f"1. Запрос будет рассмотрен на внутреннем статусе\n"
        f"2. Вы получите уведомление о решении\n"
        f"3. При необходимости запросим дополнительные метрики\n\n"
        f"Используйте /pending для просмотра всех запросов."
    )
    
    await query.edit_message_text(response_text, parse_mode='Markdown')
    return ConversationHandler.END

async def urgent_alert_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало создания срочного оповещения"""
    await update.message.reply_text(
        "⚠️ **Срочное оповещение**\n\n"
        "Опишите критическую проблему или блокировку:\n\n"
        "_(нажмите /cancel для отмены)_"
    )
    return URGENT_ALERT_DESC

async def urgent_alert_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание срочного оповещения"""
    description = update.message.text
    user_id = update.effective_user.id
    
    alert_id = db.create_urgent_alert(
        user_id=user_id,
        alert_type='critical',
        description=description
    )
    
    await update.message.reply_text(
        f"✅ **Срочное оповещение #{alert_id} создано!**\n\n"
        f"Оповещение будет рассмотрено в ближайшее время.\n"
        f"Команда уведомлена о проблеме."
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена действия"""
    await update.message.reply_text(
        "❌ Действие отменено.\n"
        "Используйте /start для просмотра доступных команд."
    )
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Exception while handling an update: {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Произошла ошибка. Пожалуйста, попробуйте позже.\n"
            "Если ошибка повторяется, обратитесь к администратору."
        )

async def post_init(application: Application):
    """Функция, запускаемая после инициализации бота"""
    logger.info("Bot started successfully! Ready to receive messages.")
    logger.info(f"Database path: {DB_PATH}")

def main():
    """Главная функция"""
    try:
        # Создаем приложение
        application = Application.builder().token(TOKEN).post_init(post_init).build()
        
        # Создаем ConversationHandler для запросов на изменение
        change_request_conv = ConversationHandler(
            entry_points=[CommandHandler('change_request', change_request_start)],
            states={
                CHANGE_REQUEST_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_request_description)],
                CHANGE_REQUEST_PRIORITY: [CallbackQueryHandler(change_request_priority, pattern='^priority_')],
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        
        # Создаем ConversationHandler для срочных оповещений
        urgent_conv = ConversationHandler(
            entry_points=[CommandHandler('urgent', urgent_alert_start)],
            states={
                URGENT_ALERT_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, urgent_alert_description)],
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        
        # Добавляем обработчики команд
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('framework', framework_overview))
        application.add_handler(CommandHandler('help', help_command))
        application.add_handler(CommandHandler('kickoff', kickoff_command))
        application.add_handler(CommandHandler('meetings', meetings_command))
        application.add_handler(CommandHandler('pending', pending_requests))
        application.add_handler(change_request_conv)
        application.add_handler(urgent_conv)
        
        # Обработчик ошибок
        application.add_error_handler(error_handler)
        
        # Запускаем бота
        logger.info("Starting bot...")
        logger.info(f"Using database at: {DB_PATH}")
        
        # Для Railway используем polling (без вебхука)
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise

if __name__ == '__main__':
    main()