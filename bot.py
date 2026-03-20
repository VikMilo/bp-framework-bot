import os
import logging
from datetime import datetime
import sqlite3
from contextlib import contextmanager

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

# Конфигурация
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    logger.error("BOT_TOKEN not set!")
    exit(1)

DB_PATH = os.environ.get('DB_PATH', '/data/bp_framework.db')

# Класс для работы с базой данных
class Database:
    def __init__(self, db_name=DB_PATH):
        self.db_name = db_name
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
        except Exception as e:
            conn.rollback()
            raise e
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
                CREATE TABLE IF NOT EXISTS change_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    requester_id INTEGER,
                    description TEXT,
                    priority TEXT CHECK(priority IN ('high', 'medium', 'low')),
                    status TEXT DEFAULT 'new',
                    document_link TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (requester_id) REFERENCES users(user_id)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS urgent_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    alert_type TEXT,
                    description TEXT,
                    is_resolved BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            
            logger.info("Database initialized at %s", self.db_name)
    
    def add_user(self, user_id, username, first_name, last_name, role='team_member', team=None):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, role, team) 
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (user_id, username, first_name, last_name, role, team))
                logger.info(f"User {user_id} ({username}) added/updated")
        except Exception as e:
            logger.error(f"Error adding user: {e}")
    
    def create_change_request(self, requester_id, description, priority):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO change_requests (requester_id, description, priority) 
                    VALUES (?, ?, ?)
                """, (requester_id, description, priority))
                request_id = cursor.lastrowid
                logger.info(f"Change request {request_id} created by user {requester_id}")
                return request_id
        except Exception as e:
            logger.error(f"Error creating change request: {e}")
            return None
    
    def create_urgent_alert(self, user_id, alert_type, description):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO urgent_alerts (user_id, alert_type, description) 
                    VALUES (?, ?, ?)
                """, (user_id, alert_type, description))
                alert_id = cursor.lastrowid
                logger.info(f"Urgent alert {alert_id} created by user {user_id}")
                return alert_id
        except Exception as e:
            logger.error(f"Error creating urgent alert: {e}")
            return None
    
    def get_pending_change_requests(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT cr.*, u.username, u.first_name 
                    FROM change_requests cr
                    LEFT JOIN users u ON cr.requester_id = u.user_id
                    WHERE cr.status = 'new'
                    ORDER BY cr.created_at DESC
                """)
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting pending requests: {e}")
            return []

# Инициализация базы данных
db = Database()

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    try:
        user = update.effective_user
        logger.info(f"User {user.id} ({user.username}) started the bot")
        
        db.add_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
        
        # Используем HTML вместо Markdown для безопасности
        welcome_text = (
            f"👋 Привет, {user.first_name}!\n\n"
            "🔷 ФРЕЙМВОРК УПРАВЛЕНИЯ БП 🔷\n\n"
            "Цель: Снизить хаос, обеспечить прозрачность, защитить ресурсы команды\n\n"
            "Ключевые принципы:\n"
            "1️⃣ Регулярные ревью (Ритм встреч)\n"
            "2️⃣ Каналы связи и сбор ОС\n"
            "3️⃣ Принцип работы с изменениями (письменный след)\n"
            "4️⃣ Защита от манипуляций\n\n"
            "Доступные команды:\n"
            "/framework - обзор фреймворка\n"
            "/kickoff - провести Kick-off встречу\n"
            "/change_request - создать запрос на изменение\n"
            "/urgent - срочное оповещение\n"
            "/pending - посмотреть ожидающие запросы\n"
            "/help - помощь"
        )
        
        await update.message.reply_text(welcome_text)
        logger.info(f"Start message sent to user {user.id}")
        
    except Exception as e:
        logger.error(f"Error in start command: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка. Пожалуйста, попробуйте позже."
        )

async def framework_overview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальный обзор фреймворка"""
    try:
        framework_text = (
            "📋 ДЕТАЛЬНЫЙ ОБЗОР ФРЕЙМВОРКА\n\n"
            "1. Регулярные ревью (Ритм встреч)\n"
            "   • Статус-встречи с бизнесом: 2 раза в неделю по 30 мин\n"
            "     Формат: Что сделано / Что планируем / Где нужна помощь\n"
            "   • Внутренние статусы: за 2 часа до встречи с бизнесом\n"
            "   • Стратсессии / Kick-off: точка входа в процесс\n\n"
            "2. Каналы связи и сбор ОС\n"
            "   • Канал срочных оповещений\n"
            "     Правило: Только для оперативной ОС и критических блокировок\n"
            "   • Пул обратной связи: раз в неделю структурированный сбор\n\n"
            "3. Принцип работы с изменениями\n"
            "   • Правило Письменного следа: изменение не существует без фиксации\n"
            "   • Инструменты: комментарий в документе, задача в трекере\n"
            "   • Фраза-триггер: Зафиксируйте комментарием в документе\n\n"
            "4. Защита от манипуляций\n"
            "   • Правило Пяти минут: пауза на анализ срочности\n"
            "   • Контекст vs Цифры: запрос метрик и обоснований\n"
            "   • Роль Адвоката дьявола на внутренних статусах"
        )
        
        await update.message.reply_text(framework_text)
        
    except Exception as e:
        logger.error(f"Error in framework command: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def kickoff_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kick-off встреча"""
    try:
        kickoff_text = (
            "🚀 KICK-OFF ВСТРЕЧА\n\n"
            "Правила фреймворка:\n\n"
            "1. Регулярные встречи\n"
            "   - Статус-встречи с бизнесом: 2 раза в неделю\n"
            "   - Внутренние статусы: за 2 часа до встречи с бизнесом\n\n"
            "2. Письменный след\n"
            "   - Любое изменение фиксируется в /change_request\n"
            "   - Без письменной фиксации изменения не существуют\n\n"
            "3. Каналы связи\n"
            "   - Срочные проблемы: /urgent\n"
            "   - Обычные вопросы: на статус-встречах\n\n"
            "4. Защита от манипуляций\n"
            "   - Правило 5 минут на анализ срочности\n"
            "   - Все запросы проходят проверку\n\n"
            "✅ Готовы начать? Используйте /change_request для первого запроса."
        )
        
        await update.message.reply_text(kickoff_text)
        
    except Exception as e:
        logger.error(f"Error in kickoff command: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def pending_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать ожидающие запросы"""
    try:
        requests = db.get_pending_change_requests()
        
        if not requests:
            await update.message.reply_text(
                "📭 Нет ожидающих запросов на изменение.\n\n"
                "Создайте запрос с помощью /change_request"
            )
            return
        
        text = "📋 Ожидающие запросы на изменение:\n\n"
        for req in requests:
            priority_emoji = "🔴" if req['priority'] == 'high' else "🟡" if req['priority'] == 'medium' else "🟢"
            text += f"{priority_emoji} #{req['id']} - {req['description'][:80]}\n"
            text += f"   От: {req['first_name'] or req['username']} | Приоритет: {req['priority']}\n"
            text += f"   Статус: {req['status']}\n\n"
        
        await update.message.reply_text(text)
        
    except Exception as e:
        logger.error(f"Error in pending requests: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def change_request_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание запроса на изменение"""
    try:
        request_text = (
            "📝 СОЗДАНИЕ ЗАПРОСА НА ИЗМЕНЕНИЕ\n\n"
            "Помните правило: изменение не существует без письменной фиксации.\n\n"
            "Опишите запрос на изменение (что нужно изменить и почему):\n\n"
            "(отправьте /cancel для отмены)"
        )
        
        await update.message.reply_text(request_text)
        return CHANGE_REQUEST_DESC
        
    except Exception as e:
        logger.error(f"Error in change_request_start: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")
        return ConversationHandler.END

async def change_request_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение описания запроса"""
    try:
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
        
    except Exception as e:
        logger.error(f"Error in change_request_description: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")
        return ConversationHandler.END

async def change_request_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка приоритета запроса"""
    try:
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
        
        if request_id:
            response_text = (
                f"✅ ЗАПРОС СОЗДАН!\n\n"
                f"ID запроса: #{request_id}\n"
                f"Приоритет: {priority}\n\n"
                f"Что дальше?\n"
                f"1. Запрос будет рассмотрен на внутреннем статусе\n"
                f"2. Вы получите уведомление о решении\n\n"
                f"Используйте /pending для просмотра всех запросов."
            )
        else:
            response_text = "❌ Не удалось создать запрос. Попробуйте позже."
        
        await query.edit_message_text(response_text)
        
    except Exception as e:
        logger.error(f"Error in change_request_priority: {e}")
        await query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")
    
    return ConversationHandler.END

async def urgent_alert_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало создания срочного оповещения"""
    try:
        await update.message.reply_text(
            "⚠️ СРОЧНОЕ ОПОВЕЩЕНИЕ\n\n"
            "Опишите критическую проблему или блокировку:\n\n"
            "(нажмите /cancel для отмены)"
        )
        return URGENT_ALERT_DESC
        
    except Exception as e:
        logger.error(f"Error in urgent_alert_start: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")
        return ConversationHandler.END

async def urgent_alert_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание срочного оповещения"""
    try:
        description = update.message.text
        user_id = update.effective_user.id
        
        alert_id = db.create_urgent_alert(
            user_id=user_id,
            alert_type='critical',
            description=description
        )
        
        if alert_id:
            response_text = (
                f"✅ СРОЧНОЕ ОПОВЕЩЕНИЕ #{alert_id} СОЗДАНО!\n\n"
                f"Оповещение будет рассмотрено в ближайшее время.\n"
                f"Команда уведомлена о проблеме."
            )
        else:
            response_text = "❌ Не удалось создать оповещение. Попробуйте позже."
        
        await update.message.reply_text(response_text)
        
    except Exception as e:
        logger.error(f"Error in urgent_alert_description: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")
    
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда помощи"""
    try:
        help_text = (
            "📚 СПРАВКА ПО КОМАНДАМ\n\n"
            "/start - Начать работу с ботом\n"
            "/framework - Обзор фреймворка\n"
            "/kickoff - Провести Kick-off встречу\n"
            "/change_request - Создать запрос на изменение\n"
            "/urgent - Создать срочное оповещение\n"
            "/pending - Посмотреть ожидающие запросы\n"
            "/help - Показать эту справку\n\n"
            "Совет: Все изменения должны иметь письменный след!\n"
            "Используйте /change_request для создания запросов."
        )
        
        await update.message.reply_text(help_text)
        
    except Exception as e:
        logger.error(f"Error in help command: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def meetings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Встречи (в разработке)"""
    await update.message.reply_text(
        "📅 УПРАВЛЕНИЕ ВСТРЕЧАМИ\n\n"
        "Рекомендуемое расписание:\n"
        "• Статус-встреча с бизнесом: вторник и пятница, 11:00\n"
        "• Внутренний статус: за 2 часа до встречи с бизнесом\n\n"
        "Функция в разработке. Скоро здесь появится возможность создавать встречи."
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена действия"""
    await update.message.reply_text(
        "❌ Действие отменено.\n"
        "Используйте /start для просмотра доступных команд."
    )
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=True)
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Произошла ошибка. Пожалуйста, попробуйте позже."
        )

async def post_init(application: Application):
    """Функция после инициализации"""
    logger.info("=" * 50)
    logger.info("✅ Bot started successfully!")
    logger.info(f"📁 Database path: {DB_PATH}")
    logger.info(f"🤖 Bot username: @{application.bot.username}")
    logger.info("=" * 50)

async def app_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открыть Mini App"""
    try:
        # Замените URL на ваш реальный адрес GitHub Pages
        miniapp_url = "https://ВАШ_АККАУНТ.github.io/bp-framework-miniapp/"
        
        keyboard = [[InlineKeyboardButton(
            "📱 Открыть панель управления", 
            web_app={"url": miniapp_url}
        )]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "📊 **BP Framework Mini App**\n\n"
            "Нажмите кнопку ниже, чтобы открыть панель управления:\n"
            "• Создавайте запросы на изменения\n"
            "• Отслеживайте статусы\n"
            "• Отправляйте срочные оповещения",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in app command: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

def main():
    """Главная функция"""
    try:
        # Создаем приложение
        application = Application.builder().token(TOKEN).post_init(post_init).build()
        
        # ConversationHandler для запросов на изменение
        change_request_conv = ConversationHandler(
            entry_points=[CommandHandler('change_request', change_request_start)],
            states={
                CHANGE_REQUEST_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, change_request_description)],
                CHANGE_REQUEST_PRIORITY: [CallbackQueryHandler(change_request_priority, pattern='^priority_')],
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        
        # ConversationHandler для срочных оповещений
        urgent_conv = ConversationHandler(
            entry_points=[CommandHandler('urgent', urgent_alert_start)],
            states={
                URGENT_ALERT_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, urgent_alert_description)],
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        
        # Добавляем обработчики
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('framework', framework_overview))
        application.add_handler(CommandHandler('help', help_command))
        application.add_handler(CommandHandler('kickoff', kickoff_command))
        application.add_handler(CommandHandler('meetings', meetings_command))
        application.add_handler(CommandHandler('pending', pending_requests))
        application.add_handler(change_request_conv)
        application.add_handler(urgent_conv)
        
 application.add_handler(CommandHandler('app', app_command))

        # Обработчик ошибок
        application.add_error_handler(error_handler)
        
        # Запускаем бота
        logger.info("Starting bot polling...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise

if __name__ == '__main__':
    main()