import asyncio
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
(
    SELECTING_ACTION,
    KICKOFF_PRESENTATION,
    CHANGE_REQUEST_DESC,
    CHANGE_REQUEST_PRIORITY,
    FEEDBACK_COLLECTION,
    MEETING_NOTES,
    TASK_CREATION,
    TASK_DESCRIPTION,
    TASK_PRIORITY,
    METRICS_REQUEST,
    DEVIL_ADVOCATE_COMMENT
) = range(11)

# Конфигурация
TOKEN = "8747965944:AAHF7n-R7-CXx88YkMxwJXNiTEE9-LxJ_U8"  # Замените на ваш токен

# Типы встреч по фреймворку
class MeetingType(Enum):
    STATUS_BUSINESS = "status_business"  # Встреча с бизнесом (2 раза в неделю)
    STATUS_INTERNAL = "status_internal"  # Внутренний статус (за 2 часа до встречи с бизнесом)
    KICKOFF = "kickoff"  # Стратсессия / Kick-off
    URGENT = "urgent"  # Срочный канал

# Типы напоминаний
class ReminderType(Enum):
    MEETING = "meeting"
    CHANGE_REVIEW = "change_review"
    FEEDBACK_COLLECTION = "feedback_collection"
    METRICS_CHECK = "metrics_check"

# Класс для работы с базой данных
class Database:
    def __init__(self, db_name="bp_framework.db"):
        self.db_name = db_name
        self.init_db()
    
    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Пользователи
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
            
            # Встречи по фреймворку
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
            
            # Запросы на изменения (письменный след)
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
            
            # Сбор обратной связи
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
            
            # Срочные оповещения (канал срочных оповещений)
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
            
            # Задачи в трекере
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
            
            # Проверка метрик (правило 5 минут)
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
            
            # Роль "Адвоката дьявола"
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
            
            conn.commit()
    
    def add_user(self, user_id, username, first_name, last_name, role='team_member', team=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR IGNORE INTO users 
                   (user_id, username, first_name, last_name, role, team) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, username, first_name, last_name, role, team)
            )
            conn.commit()
    
    def update_user_role(self, user_id, role, team=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET role = ?, team = ? WHERE user_id = ?",
                (role, team, user_id)
            )
            conn.commit()
    
    def create_meeting(self, meeting_type, title, meeting_date, meeting_time, 
                      duration, participants, agenda, created_by):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO meetings 
                   (meeting_type, title, meeting_date, meeting_time, duration_minutes, 
                    participants, agenda, created_by) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (meeting_type, title, meeting_date, meeting_time, duration,
                 json.dumps(participants), agenda, created_by)
            )
            conn.commit()
            return cursor.lastrowid
    
    def get_upcoming_meetings(self, meeting_type=None, days_ahead=7):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            today = datetime.now().date()
            end_date = today + timedelta(days=days_ahead)
            
            query = """SELECT m.*, u.username as creator_name 
                       FROM meetings m
                       JOIN users u ON m.created_by = u.user_id
                       WHERE m.meeting_date BETWEEN ? AND ?"""
            params = [today, end_date]
            
            if meeting_type:
                query += " AND m.meeting_type = ?"
                params.append(meeting_type)
            
            query += " ORDER BY m.meeting_date, m.meeting_time"
            
            cursor.execute(query, params)
            return cursor.fetchall()
    
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
            conn.commit()
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
            conn.commit()
    
    def create_urgent_alert(self, user_id, alert_type, description):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO urgent_alerts (user_id, alert_type, description) VALUES (?, ?, ?)",
                (user_id, alert_type, description)
            )
            conn.commit()
            return cursor.lastrowid
    
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
    
    def resolve_urgent_alert(self, alert_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE urgent_alerts SET is_resolved = 1, resolved_at = ? WHERE id = ?",
                (datetime.now(), alert_id)
            )
            conn.commit()
    
    def create_task(self, title, description, priority, change_request_id, assigned_to, due_date):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO tasks 
                   (title, description, priority, change_request_id, assigned_to, due_date) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (title, description, priority, change_request_id, assigned_to, due_date)
            )
            conn.commit()
            return cursor.lastrowid
    
    def add_devil_advocate_review(self, request_id, reviewer_id, review_comments, 
                                 is_legitimate, risk_assessment):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO devil_advocate_reviews 
                   (request_id, reviewer_id, review_comments, is_legitimate, risk_assessment) 
                   VALUES (?, ?, ?, ?, ?)""",
                (request_id, reviewer_id, review_comments, is_legitimate, risk_assessment)
            )
            conn.commit()
    
    def add_metrics_check(self, request_id, checked_by, original_urgency, 
                         analysis_result, is_valid_urgency, recommendation):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO metrics_checks 
                   (request_id, checked_by, original_urgency, analysis_result, 
                    is_valid_urgency, recommendation) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (request_id, checked_by, original_urgency, analysis_result, 
                 is_valid_urgency, recommendation)
            )
            conn.commit()

# Инициализация базы данных
db = Database()

# Обработчики команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start - презентация фреймворка"""
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
        "/feedback - собрать обратную связь\n"
        "/tasks - управление задачами\n"
        "/metrics_check - проверить метрики (правило 5 минут)\n"
        "/devil_advocate - роль адвоката дьявола\n"
        "/my_requests - мои запросы\n"
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
        "• Канал срочных оповещений (СберЧат / ТГ)\n"
        "  Правило: Только для оперативной ОС и критических блокировок\n"
        "• Пул обратной связи: раз в неделю структурированный сбор\n\n"
        
        "**3. Принцип работы с изменениями**\n"
        "• Правило «Письменного следа»: изменение не существует без фиксации\n"
        "• Инструменты: комментарий в документе, задача в трекере\n"
        "• Фраза-триггер: «Зафиксируйте комментарием в документе»\n\n"
        
        "**4. Защита от манипуляций**\n"
        "• Правило «Пяти минут»: пауза на анализ срочности\n"
        "• Контекст vs. Цифры: запрос метрик и обоснований\n"
        "• Роль «Адвоката дьявола» на внутренних статусах\n\n"
        
        "🔷 **Итоговая схема работы:**\n"
        "Kick-off → Будни (работа с запросами) → Внутренний статус → "
        "Статус-встреча с бизнесом"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 Провести Kick-off", callback_data="start_kickoff")],
        [InlineKeyboardButton("📅 Ближайшие встречи", callback_data="upcoming_meetings")],
        [InlineKeyboardButton("📝 Создать запрос на изменение", callback_data="new_change_request")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(framework_text, parse_mode='Markdown', reply_markup=reply_markup)

async def kickoff_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало Kick-off встречи"""
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
        user_id = update.effective_user.id
    else:
        message = update.message
        user_id = update.effective_user.id
    
    kickoff_text = (
        "🚀 **Kick-off встреча**\n\n"
        "Давайте договоримся о правилах игры:\n\n"
        
        "**Правило 1: Регулярные встречи**\n"
        "• Статус-встречи с бизнесом: [выберите дни и время]\n"
        "• Внутренние статусы: за 2 часа до встречи с бизнесом\n\n"
        
        "**Правило 2: Каналы связи**\n"
        "• Создаем отдельный чат для срочных оповещений\n"
        "• В этом чате: только критические блокировки и срочные проблемы\n"
        "• Новые гипотезы и идеи - на встречах или в трекере\n\n"
        
        "**Правило 3: Письменный след**\n"
        "• Любое изменение фиксируем в документе/трекере\n"
        "• Без письменной фиксации изменения не существует\n\n"
        
        "**Правило 4: Защита от манипуляций**\n"
        "• Правило 5 минут - пауза перед реакцией на срочные запросы\n"
        "• Запрос метрик и обоснований\n"
        "• Роль адвоката дьявола на внутренних статусах\n\n"
        
        "Готовы зафиксировать эти правила?"
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ Принимаю правила", callback_data="accept_rules")],
        [InlineKeyboardButton("📅 Настроить расписание встреч", callback_data="setup_meetings")],
        [InlineKeyboardButton("👥 Создать чат оповещений", callback_data="create_urgent_chat")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.reply_text(kickoff_text, parse_mode='Markdown', reply_markup=reply_markup)
    return KICKOFF_PRESENTATION

async def accept_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принятие правил фреймворка"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    # Создаем первую встречу - kick-off
    meeting_id = db.create_meeting(
        meeting_type=MeetingType.KICKOFF.value,
        title="Kick-off встреча по фреймворку БП",
        meeting_date=datetime.now().date(),
        meeting_time=datetime.now().time().strftime("%H:%M"),
        duration=60,
        participants=[user_id],
        agenda="Презентация фреймворка, принятие правил, настройка процесса",
        created_by=user_id
    )
    
    await query.edit_message_text(
        text="✅ **Правила приняты!**\n\n"
             "Фреймворк внедрен. Теперь:\n"
             "• Все изменения проходят через письменную фиксацию\n"
             "• Срочные вопросы - только в отдельном чате\n"
             "• Регулярные встречи синхронизированы\n\n"
             "Используйте /meetings для управления расписанием\n"
             "Или /change_request для создания первого запроса",
        parse_mode='Markdown'
    )

async def setup_meetings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройка регулярных встреч"""
    query = update.callback_query
    await query.answer()
    
    setup_text = (
        "📅 **Настройка регулярных встреч**\n\n"
        "Согласно фреймворку, нам нужно настроить:\n\n"
        
        "**1. Статус-встречи с бизнесом**\n"
        "• Частота: 2 раза в неделю\n"
        "• Длительность: 30 минут\n"
        "• Формат: Что сделано / Что планируем / Эскалации\n\n"
        
        "**2. Внутренние статусы**\n"
        "• За 2 часа до каждой встречи с бизнесом\n"
        "• Цель: причесать статус, выявить риски\n\n"
        
        "Выберите дни для статус-встреч:"
    )
    
    # Здесь можно добавить инлайн-календарь для выбора дат
    keyboard = [
        [InlineKeyboardButton("ПН и ЧТ 11:00", callback_data="meeting_mon_thu_11")],
        [InlineKeyboardButton("ВТ и ПТ 10:30", callback_data="meeting_tue_fri_1030")],
        [InlineKeyboardButton("СР и ПН 14:00", callback_data="meeting_wed_mon_14")],
        [InlineKeyboardButton("Настроить вручную", callback_data="meeting_custom")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(setup_text, parse_mode='Markdown', reply_markup=reply_markup)

async def create_urgent_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание чата для срочных оповещений"""
    query = update.callback_query
    await query.answer()
    
    chat_text = (
        "⚠️ **Канал срочных оповещений**\n\n"
        "Правила чата:\n"
        "• Только для ОПЕРАТИВНОЙ ОС и критических блокировок\n"
        "• Если упал сервер или сорвался дедлайн - пиши сюда\n"
        "• Новые гипотезы и идеи - на встречи или в трекер\n\n"
        "**Как создать чат:**\n"
        "1. Создайте отдельный чат в Telegram\n"
        "2. Добавьте всех участников команды и бизнеса\n"
        "3. Отправьте команду /set_chat_rules в этом чате\n"
        "4. Бот автоматически закрепит правила\n\n"
        "Или используйте кнопку ниже для создания шаблона"
    )
    
    keyboard = [
        [InlineKeyboardButton("📝 Создать шаблон правил", callback_data="generate_rules_template")],
        [InlineKeyboardButton("✅ Готово, чат создан", callback_data="urgent_chat_created")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(chat_text, parse_mode='Markdown', reply_markup=reply_markup)

async def change_request_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание запроса на изменение (письменный след)"""
    request_text = (
        "📝 **Создание запроса на изменение**\n\n"
        "Помните правило: изменение не существует без письменной фиксации.\n\n"
        "Опишите запрос на изменение:"
    )
    
    await update.message.reply_text(request_text, parse_mode='Markdown')
    return CHANGE_REQUEST_DESC

async def change_request_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение описания запроса"""
    context.user_data['change_desc'] = update.message.text
    
    await update.message.reply_text(
        "Выберите приоритет запроса:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 Высокий", callback_data="priority_high")],
            [InlineKeyboardButton("🟡 Средний", callback_data="priority_medium")],
            [InlineKeyboardButton("🟢 Низкий", callback_data="priority_low")]
        ])
    )
    return CHANGE_REQUEST_PRIORITY

async def change_request_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка приоритета запроса"""
    query = update.callback_query
    await query.answer()
    
    priority = query.data.split('_')[1]
    user_id = update.effective_user.id
    description = context.user_data.get('change_desc', '')
    
    # Создаем запрос на изменение
    request_id = db.create_change_request(
        requester_id=user_id,
        description=description,
        priority=priority
    )
    
    # Автоматически запускаем проверку по правилу 5 минут
    context.user_data['current_request_id'] = request_id
    
    response_text = (
        f"✅ **Запрос на изменение создан!**\n"
        f"ID запроса: #{request_id}\n"
        f"Приоритет: {priority}\n\n"
        
        "**Что дальше?**\n"
        "1️⃣ Запущена автоматическая проверка по правилу 5 минут\n"
        "2️⃣ На внутреннем статусе запрос будет рассмотрен\n"
        "3️⃣ Вы получите уведомление о решении\n\n"
        
        "Хотите добавить ссылку на документ или обоснование?"
    )
    
    keyboard = [
        [InlineKeyboardButton("📎 Добавить ссылку на документ", 
                              callback_data=f"add_doc_{request_id}")],
        [InlineKeyboardButton("📊 Добавить метрики/обоснование", 
                              callback_data=f"add_metrics_{request_id}")],
        [InlineKeyboardButton("✅ Завершить", callback_data="finish_change_request")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(response_text, parse_mode='Markdown', reply_markup=reply_markup)
    
    # Автоматически запускаем правило 5 минут
    await metrics_check_auto(update, context, request_id, description, priority)
    
    return ConversationHandler.END

async def metrics_check_auto(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                            request_id: int, description: str, priority: str):
    """Автоматическая проверка по правилу 5 минут"""
    user_id = update.effective_user.id
    
    # Анализ срочности (простая эвристика)
    urgent_keywords = ['срочно', 'критично', 'падение', 'ошибка', 'дедлайн', 'авария']
    is_urgent = any(keyword in description.lower() for keyword in urgent_keywords)
    
    analysis = (
        f"**Правило 5 минут - анализ запроса #{request_id}**\n\n"
        f"Исходная срочность: {priority}\n"
        f"Ключевые слова срочности: {'обнаружены' if is_urgent else 'не обнаружены'}\n\n"
        
        "**Результат анализа:**\n"
    )
    
    if priority == 'high' and not is_urgent:
        analysis += (
            "⚠️ Запрос помечен как высокий приоритет, "
            "но не содержит явных признаков срочности.\n"
            "Рекомендуется запросить дополнительное обоснование."
        )
        is_valid = False
        recommendation = "Запросить обоснование срочности"
    elif priority == 'low' and is_urgent:
        analysis += (
            "⚠️ Запрос содержит признаки срочности, "
            "но помечен как низкий приоритет.\n"
            "Рекомендуется пересмотреть приоритет."
        )
        is_valid = False
        recommendation = "Пересмотреть приоритет"
    else:
        analysis += (
            "✅ Приоритет соответствует контексту запроса.\n"
            "Можно рассматривать на ближайшей статус-встрече."
        )
        is_valid = True
        recommendation = "Включить в повестку статус-встречи"
    
    # Сохраняем проверку
    db.add_metrics_check(
        request_id=request_id,
        checked_by=user_id,
        original_urgency=priority,
        analysis_result=analysis,
        is_valid_urgency=is_valid,
        recommendation=recommendation
    )
    
    # Отправляем результат
    keyboard = [
        [InlineKeyboardButton("🔍 Запустить адвоката дьявола", 
                              callback_data=f"devil_review_{request_id}")],
        [InlineKeyboardButton("📅 Добавить в повестку статус-встречи", 
                              callback_data=f"add_to_agenda_{request_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=user_id,
        text=analysis,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def urgent_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание срочного оповещения"""
    await update.message.reply_text(
        "⚠️ **Срочное оповещение**\n\n"
        "Опишите критическую проблему или блокировку:"
    )
    return 1  # состояние для получения описания

async def urgent_alert_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка срочного оповещения"""
    description = update.message.text
    user_id = update.effective_user.id
    
    alert_id = db.create_urgent_alert(
        user_id=user_id,
        alert_type='critical',
        description=description
    )
    
    # Уведомляем всех админов (в реальном боте нужно получать список админов)
    admins = [user_id]  # временно
    
    for admin_id in admins:
        await context.bot.send_message(
            chat_id=admin_id,
            text=f"🚨 **СРОЧНОЕ ОПОВЕЩЕНИЕ** 🚨\n\n"
                 f"От: {update.effective_user.first_name}\n"
                 f"Проблема: {description}\n\n"
                 f"ID оповещения: #{alert_id}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Взять в работу", callback_data=f"take_alert_{alert_id}")],
                [InlineKeyboardButton("🔍 Уточнить детали", callback_data=f"ask_alert_{alert_id}")]
            ])
        )
    
    await update.message.reply_text(
        f"✅ Срочное оповещение #{alert_id} отправлено. Команда уже уведомлена."
    )
    return ConversationHandler.END

async def devil_advocate_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запуск роли адвоката дьявола"""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        
        data = query.data
        if data.startswith("devil_review_"):
            request_id = int(data.split('_')[2])
            context.user_data['review_request_id'] = request_id
            
            request = None
            # Получаем данные запроса
            requests = db.get_pending_change_requests()
            for req in requests:
                if req['id'] == request_id:
                    request = req
                    break
            
            if request:
                review_text = (
                    f"👿 **Роль Адвоката дьявола**\n\n"
                    f"Запрос #{request_id}\n"
                    f"Описание: {request['description']}\n"
                    f"Приоритет: {request['priority']}\n"
                    f"Автор: {request['requester_name']}\n\n"
                    
                    "**Проверьте запрос на честность:**\n"
                    "1. Действительно ли это срочно?\n"
                    "2. Чья это работа? Не пытаются ли делегировать чужую ответственность?\n"
                    "3. Есть ли метрики и обоснования?\n"
                    "4. Как это влияет на результат БП?\n\n"
                    
                    "Ваш вердикт:"
                )
                
                keyboard = [
                    [InlineKeyboardButton("✅ Легитимный запрос", 
                                          callback_data=f"devil_legit_{request_id}")],
                    [InlineKeyboardButton("⚠️ Требует уточнений", 
                                          callback_data=f"devil_question_{request_id}")],
                    [InlineKeyboardButton("❌ Отклонить (манипуляция)", 
                                          callback_data=f"devil_reject_{request_id}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(review_text, parse_mode='Markdown', 
                                            reply_markup=reply_markup)
                return DEVIL_ADVOCATE_COMMENT
    
    else:
        await update.message.reply_text(
            "Выберите запрос для проверки:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Посмотреть ожидающие запросы", 
                                    callback_data="view_pending_requests")]
            ])
        )
        return DEVIL_ADVOCATE_COMMENT

async def devil_advocate_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка решения адвоката дьявола"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    parts = data.split('_')
    decision = parts[1]
    request_id = int(parts[2])
    
    user_id = update.effective_user.id
    
    if decision == 'legit':
        result = "✅ Запрос признан легитимным"
        is_legitimate = True
        risk = "Низкий"
    elif decision == 'question':
        result = "⚠️ Запрос требует уточнений"
        is_legitimate = None
        risk = "Средний"
    else:  # reject
        result = "❌ Запрос отклонен как манипулятивный"
        is_legitimate = False
        risk = "Высокий"
    
    # Сохраняем ревью
    db.add_devil_advocate_review(
        request_id=request_id,
        reviewer_id=user_id,
        review_comments=result,
        is_legitimate=is_legitimate,
        risk_assessment=f"Риск: {risk}"
    )
    
    # Обновляем статус запроса
    if decision == 'reject':
        db.update_change_request_status(request_id, 'rejected')
    
    await query.edit_message_text(
        text=f"👿 **Вердикт адвоката дьявола:**\n\n{result}\n\n"
             f"Запрос #{request_id} будет рассмотрен на внутреннем статусе.",
        parse_mode='Markdown'
    )
    
    return ConversationHandler.END

async def upcoming_meetings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр ближайших встреч"""
    meetings = db.get_upcoming_meetings()
    
    if not meetings:
        text = "📅 Нет запланированных встреч"
    else:
        text = "📅 **Ближайшие встречи:**\n\n"
        for meeting in meetings:
            meeting_type_display = {
                'status_business': '🤝 С бизнесом',
                'status_internal': '👥 Внутренний статус',
                'kickoff': '🚀 Kick-off',
                'urgent': '⚠️ Срочная'
            }.get(meeting['meeting_type'], meeting['meeting_type'])
            
            text += (
                f"**{meeting_type_display}**\n"
                f"📌 {meeting['title']}\n"
                f"📅 {meeting['meeting_date']} в {meeting['meeting_time']}\n"
                f"⏱ {meeting['duration_minutes']} мин\n"
                f"📋 {meeting['agenda'][:100]}...\n\n"
            )
    
    keyboard = [
        [InlineKeyboardButton("➕ Создать встречу", callback_data="create_meeting")],
        [InlineKeyboardButton("📋 Сформировать повестку", callback_data="create_agenda")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode='Markdown', 
                                                    reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)

async def internal_status_prep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подготовка к внутреннему статусу (за 2 часа до встречи с бизнесом)"""
    # Получаем запросы для рассмотрения
    pending_requests = db.get_pending_change_requests()
    
    text = (
        "👥 **Подготовка к внутреннему статусу**\n"
        "(за 2 часа до встречи с бизнесом)\n\n"
        
        "**Цели встречи:**\n"
        "• Причесать статус\n"
        "• Выявить риски\n"
        "• Выработать единую позицию\n"
        "• Проверить запросы на надувательство\n\n"
    )
    
    if pending_requests:
        text += "**Запросы на рассмотрение:**\n"
        for req in pending_requests:
            text += f"• #{req['id']} {req['description'][:50]}... ({req['priority']})\n"
    
    keyboard = [
        [InlineKeyboardButton("🔍 Запустить адвоката дьявола", callback_data="devil_advocate")],
        [InlineKeyboardButton("📊 Проверить метрики", callback_data="check_metrics")],
        [InlineKeyboardButton("📝 Сформировать повестку бизнесу", callback_data="business_agenda")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)

async def business_status_prep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подготовка к статус-встрече с бизнесом"""
    # Получаем одобренные запросы
    approved_requests = db.get_pending_change_requests('high')  # временно
    
    text = (
        "🤝 **Подготовка к статус-встрече с бизнесом**\n\n"
        
        "**Формат встречи (30 мин):**\n"
        "• ✅ Что сделано\n"
        "• 📋 Что планируем\n"
        "• 🆘 Где нужна помощь бизнеса (эскалация)\n\n"
        
        "**Важно:** На встрече фиксируем прогресс, не рождаем новые идеи\n\n"
    )
    
    if approved_requests:
        text += "**Изменения для согласования:**\n"
        for req in approved_requests:
            text += f"• #{req['id']} {req['description'][:50]}...\n"
    
    keyboard = [
        [InlineKeyboardButton("📊 Подготовить отчет", callback_data="prepare_report")],
        [InlineKeyboardButton("⚠️ Выявить риски", callback_data="identify_risks")],
        [InlineKeyboardButton("🎯 Определить эскалации", callback_data="escalations")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка всех callback запросов"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "start_kickoff":
        await kickoff_start(update, context)
    elif data == "accept_rules":
        await accept_rules(update, context)
    elif data == "setup_meetings":
        await setup_meetings(update, context)
    elif data == "create_urgent_chat":
        await create_urgent_chat(update, context)
    elif data == "upcoming_meetings":
        await upcoming_meetings(update, context)
    elif data.startswith("priority_"):
        await change_request_priority(update, context)
    elif data.startswith("devil_review_"):
        await devil_advocate_start(update, context)
    elif data.startswith("devil_"):
        await devil_advocate_decision(update, context)
    elif data == "view_pending_requests":
        requests = db.get_pending_change_requests()
        text = "**Ожидающие запросы:**\n\n"
        for req in requests:
            text += f"• #{req['id']} {req['description'][:100]}... ({req['priority']})\n"
        await query.edit_message_text(text, parse_mode='Markdown')
    else:
        await query.edit_message_text(f"Обработка: {data}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия"""
    await update.message.reply_text(
        "❌ Действие отменено.\n"
        "Используйте /start для просмотра доступных команд."
    )
    return ConversationHandler.END

async def send_meeting_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Отправка напоминаний о встречах"""
    try:
        # Получаем встречи на завтра
        tomorrow = datetime.now().date() + timedelta(days=1)
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT m.*, u.user_id as creator_id 
                   FROM meetings m
                   JOIN users u ON m.created_by = u.user_id
                   WHERE m.meeting_date = ?""",
                (tomorrow,)
            )
            meetings = cursor.fetchall()
        
        for meeting in meetings:
            meeting_type_display = {
                'status_business': '🤝 Статус-встреча с бизнесом',
                'status_internal': '👥 Внутренний статус',
                'kickoff': '🚀 Kick-off'
            }.get(meeting['meeting_type'], meeting['meeting_type'])
            
            text = (
                f"🔔 **Напоминание о встрече!**\n\n"
                f"**{meeting_type_display}**\n"
                f"📌 {meeting['title']}\n"
                f"📅 Завтра в {meeting['meeting_time']}\n"
                f"⏱ Длительность: {meeting['duration_minutes']} мин\n\n"
                f"**Повестка:**\n{meeting['agenda']}\n\n"
            )
            
            # Отправляем всем участникам
            participants = json.loads(meeting['participants'])
            for participant_id in participants:
                try:
                    await context.bot.send_message(
                        chat_id=participant_id,
                        text=text,
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Error sending reminder to {participant_id}: {e}")
        
        # Напоминание о внутреннем статусе (за 2 часа до встречи с бизнесом)
        # В реальном боте нужно получать время встречи с бизнесом
        logger.info("Meeting reminders sent")
        
    except Exception as e:
        logger.error(f"Error in send_meeting_reminders: {e}")

async def send_feedback_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Напоминание о сборе обратной связи"""
    text = (
        "📊 **Время сбора обратной связи!**\n\n"
        "Согласно фреймворку, нужно собрать структурированную ОС от бизнеса.\n\n"
        "Используйте /feedback для запуска сбора."
    )
    
    # В реальном боте нужно получать список лидов
    leads = []  # временно
    
    for lead_id in leads:
        try:
            await context.bot.send_message(
                chat_id=lead_id,
                text=text,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error sending feedback reminder: {e}")

def main():
    """Главная функция"""
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # ConversationHandler для запросов на изменение
    change_request_conv = ConversationHandler(
        entry_points=[CommandHandler('change_request', change_request_start)],
        states={
            CHANGE_REQUEST_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, 
                                                change_request_description)],
            CHANGE_REQUEST_PRIORITY: [CallbackQueryHandler(change_request_priority)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # ConversationHandler для срочных оповещений
    urgent_conv = ConversationHandler(
        entry_points=[CommandHandler('urgent', urgent_alert)],
        states={
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, urgent_alert_description)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # ConversationHandler для адвоката дьявола
    devil_conv = ConversationHandler(
        entry_points=[
            CommandHandler('devil_advocate', devil_advocate_start),
            CallbackQueryHandler(devil_advocate_start, pattern='^devil_review_')
        ],
        states={
            DEVIL_ADVOCATE_COMMENT: [CallbackQueryHandler(devil_advocate_decision, pattern='^devil_')]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('framework', framework_overview))
    application.add_handler(CommandHandler('kickoff', kickoff_start))
    application.add_handler(CommandHandler('meetings', upcoming_meetings))
    application.add_handler(CommandHandler('internal_status', internal_status_prep))
    application.add_handler(CommandHandler('business_status', business_status_prep))
    application.add_handler(CommandHandler('my_requests', lambda u,c: u.message.reply_text("В разработке")))
    application.add_handler(CommandHandler('help', lambda u,c: u.message.reply_text(
        "Справка по командам:\n"
        "/framework - обзор фреймворка\n"
        "/kickoff - провести Kick-off\n"
        "/meetings - управление встречами\n"
        "/change_request - создать запрос на изменение\n"
        "/urgent - срочное оповещение\n"
        "/feedback - собрать обратную связь\n"
        "/tasks - управление задачами\n"
        "/metrics_check - проверить метрики\n"
        "/devil_advocate - роль адвоката дьявола\n"
        "/internal_status - подготовка к внутреннему статусу\n"
        "/business_status - подготовка к встрече с бизнесом"
    )))
    
    # Добавляем ConversationHandler'ы
    application.add_handler(change_request_conv)
    application.add_handler(urgent_conv)
    application.add_handler(devil_conv)
    
    # Обработчик callback запросов (должен быть после всех конкретных)
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Планировщик для отправки напоминаний
    job_queue = application.job_queue
    if job_queue:
        # Ежедневно в 9:00 проверяем встречи на завтра
        job_queue.run_daily(send_meeting_reminders, time=time(9, 0))
        # Еженедельно в пятницу в 16:00 напоминаем о сборе ОС
        job_queue.run_daily(send_feedback_reminder, days=(4,), time=time(16, 0))  # пятница = 4
        logger.info("Scheduler started")
    
    # Запускаем бота
    print("🚀 Бот фреймворка БП запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()