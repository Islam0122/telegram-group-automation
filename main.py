import logging
import asyncio
import csv
import json
from pathlib import Path
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage

from pyrogram import Client
from pyrogram.errors import (
    FloodWait, UserPrivacyRestricted, PeerFlood,
    UserNotMutualContact, UserChannelsTooMuch, UserBannedInChannel
)

BOT_TOKEN = ''
API_ID = 0
API_HASH = ''

DELAY_BETWEEN = 65
DELAY_BATCH = 300
BATCH_SIZE = 10

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler('bot.log', encoding='utf-8'), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

uploaded_files = {}
is_running = {}
stats_history = {}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
app = Client('session', api_id=API_ID, api_hash=API_HASH)

def parse_file(path: str) -> list:
    users = []
    p = Path(path)
    
    if p.suffix == '.txt':
        with open(path, 'r', encoding='utf-8') as f:
            users = [line.strip() for line in f if line.strip()]
    elif p.suffix == '.csv':
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                user = row.get('username') or row.get('user_id') or row.get('id')
                if user:
                    users.append(user.strip())
    
    log.info(f"Найдено {len(users)} пользователей")
    return users

async def add_user(chat_id: int, user: str):
    try:
        await app.add_chat_members(chat_id, [user])
        log.info(f"✅ {user}")
        return 'success'
    except FloodWait as e:
        log.warning(f"⏳ FloodWait {e.value}с")
        await asyncio.sleep(e.value)
        return 'flood'
    except UserPrivacyRestricted:
        log.warning(f"🔒 {user}")
        return 'privacy'
    except PeerFlood:
        log.error(f"🚫 PeerFlood!")
        return 'peer_flood'
    except UserNotMutualContact:
        log.warning(f"👤 {user}")
        return 'not_contact'
    except UserChannelsTooMuch:
        log.warning(f"📊 {user}")
        return 'too_many_groups'
    except UserBannedInChannel:
        log.warning(f"🚫 {user}")
        return 'banned'
    except Exception as e:
        log.error(f"❌ {user}: {e}")
        return 'error'

async def process(chat_id: int, users: list, msg: Message):
    stats = {'success': 0, 'flood': 0, 'privacy': 0, 'peer_flood': 0, 
             'not_contact': 0, 'too_many_groups': 0, 'banned': 0, 'error': 0}
    
    total = len(users)
    start_time = datetime.now()
    
    for idx, user in enumerate(users, 1):
        if not is_running.get(chat_id):
            break
            
        log.info(f"[{idx}/{total}] {user}")
        result = await add_user(chat_id, user)
        stats[result] = stats.get(result, 0) + 1
        
        if result == 'peer_flood':
            await msg.answer("🚫 PeerFlood! Остановка. Повторите через 24 часа.")
            break
        
        # Progress update every 10 users
        if idx % 10 == 0:
            progress = (idx / total) * 100
            await msg.answer(f"⏳ Прогресс: {idx}/{total} ({progress:.1f}%)\n✅ Добавлено: {stats['success']}")
        
        if idx % BATCH_SIZE == 0:
            await asyncio.sleep(DELAY_BATCH)
        else:
            await asyncio.sleep(DELAY_BETWEEN)
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    # Save to history
    stats_history[chat_id] = {
        'date': end_time.strftime('%Y-%m-%d %H:%M:%S'),
        'stats': stats,
        'total': total,
        'processed': idx,
        'duration': duration
    }
    
    report = f"""📊 Отчёт завершён

✅ Успешно: {stats['success']}
⏳ FloodWait: {stats['flood']}
🔒 Приватность: {stats['privacy']}
👤 Не в контактах: {stats['not_contact']}
📊 Много групп: {stats['too_many_groups']}
🚫 Забанены: {stats['banned']}
❌ Ошибки: {stats['error']}

Обработано: {idx}/{total}
⏱ Время: {int(duration // 60)}м {int(duration % 60)}с
📈 Скорость: {stats['success'] / (duration / 60):.1f} польз/мин"""
    
    await msg.answer(report)
    log.info(report)
    is_running[chat_id] = False
    
    # Export failed users
    await export_failed_users(chat_id, users, stats, msg)

async def export_failed_users(chat_id: int, users: list, stats: dict, msg: Message):
    """Export list of users who weren't added successfully"""
    failed_count = stats['privacy'] + stats['not_contact'] + stats['too_many_groups'] + stats['banned'] + stats['error']
    
    if failed_count > 0:
        await msg.answer(f"💾 Экспорт неудачных попыток... ({failed_count} польз.)")

@dp.message(Command('start'))
async def start(msg: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Помощь", callback_data="help")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")]
    ])
    
    await msg.answer(
        "👋 *Бот для добавления пользователей в группы*\n\n"
        "🚀 *Быстрый старт:*\n"
        "1. Добавьте бота в группу как администратора\n"
        "2. Отправьте файл users.txt или users.csv\n"
        "3. Используйте /add\\_users для начала\n\n"
        "📋 *Команды:*\n"
        "/add\\_users - Начать добавление\n"
        "/stop - Остановить процесс\n"
        "/status - Текущий статус\n"
        "/stats - История операций\n"
        "/preview - Просмотр файла\n"
        "/settings - Настройки",
        parse_mode='Markdown',
        reply_markup=keyboard
    )

@dp.message(F.document)
async def handle_file(msg: Message):
    doc = msg.document
    
    if not (doc.file_name.endswith('.txt') or doc.file_name.endswith('.csv')):
        await msg.answer("❌ Поддерживаются только форматы .txt или .csv")
        return
    
    Path('downloads').mkdir(exist_ok=True)
    file_path = f"downloads/{doc.file_name}"
    await bot.download(doc, destination=file_path)
    
    uploaded_files[msg.chat.id] = file_path
    users = parse_file(file_path)
    
    # Show file info with inline buttons
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👀 Просмотр (10 строк)", callback_data="preview_10")],
        [InlineKeyboardButton(text="🚀 Начать добавление", callback_data="start_adding")]
    ])
    
    await msg.answer(
        f"✅ *Файл загружен:* `{doc.file_name}`\n"
        f"👥 *Пользователей найдено:* {len(users)}\n"
        f"📏 *Размер файла:* {doc.file_size / 1024:.1f} KB\n\n"
        f"Используйте /add\\_users для начала",
        parse_mode='Markdown',
        reply_markup=keyboard
    )
    log.info(f"Загружен {doc.file_name} в чат {msg.chat.id}")

@dp.message(Command('preview'))
async def preview_file(msg: Message):
    """Preview first 10 users from uploaded file"""
    chat_id = msg.chat.id
    
    if chat_id not in uploaded_files:
        await msg.answer("❌ Сначала загрузите файл с пользователями")
        return
    
    users = parse_file(uploaded_files[chat_id])
    preview_list = users[:10]
    
    preview_text = "👀 *Предпросмотр файла (первые 10):*\n\n"
    for i, user in enumerate(preview_list, 1):
        preview_text += f"{i}. `{user}`\n"
    
    if len(users) > 10:
        preview_text += f"\n... и ещё {len(users) - 10} пользователей"
    
    await msg.answer(preview_text, parse_mode='Markdown')

@dp.message(Command('status'))
async def check_status(msg: Message):
    """Check current operation status"""
    chat_id = msg.chat.id
    
    if is_running.get(chat_id):
        await msg.answer(
            "⚙️ *Статус:* Выполняется\n"
            "🔄 Добавление пользователей в процессе...\n\n"
            "Используйте /stop для остановки",
            parse_mode='Markdown'
        )
    else:
        await msg.answer(
            "💤 *Статус:* Не активен\n"
            "Нет активных операций",
            parse_mode='Markdown'
        )

@dp.message(Command('stats'))
async def show_stats(msg: Message):
    """Show statistics from last operation"""
    chat_id = msg.chat.id
    
    if chat_id not in stats_history:
        await msg.answer("📊 История операций пуста\n\nВыполните /add_users для начала")
        return
    
    history = stats_history[chat_id]
    stats = history['stats']
    
    success_rate = (stats['success'] / history['processed'] * 100) if history['processed'] > 0 else 0
    
    report = f"""📊 *Последняя операция*

📅 Дата: `{history['date']}`
⏱ Длительность: {int(history['duration'] // 60)}м {int(history['duration'] % 60)}с

✅ Успешно: {stats['success']} ({success_rate:.1f}%)
⏳ FloodWait: {stats['flood']}
🔒 Приватность: {stats['privacy']}
👤 Не в контактах: {stats['not_contact']}
📊 Много групп: {stats['too_many_groups']}
🚫 Забанены: {stats['banned']}
❌ Ошибки: {stats['error']}

📈 Всего обработано: {history['processed']}/{history['total']}"""
    
    await msg.answer(report, parse_mode='Markdown')

@dp.message(Command('settings'))
async def show_settings(msg: Message):
    """Show current bot settings"""
    settings_text = f"""⚙️ *Текущие настройки*

⏱ Задержка между добавлениями: `{DELAY_BETWEEN}` сек
📦 Размер пакета: `{BATCH_SIZE}` пользователей
⏳ Задержка между пакетами: `{DELAY_BATCH}` сек

💡 *Рекомендации:*
• Увеличьте задержки при PeerFlood
• Уменьшайте размер пакета для безопасности
• Не добавляйте больше 50 пользователей в день"""
    
    await msg.answer(settings_text, parse_mode='Markdown')

@dp.message(Command('add_users'))
async def add_users(msg: Message):
    chat_id = msg.chat.id
    
    if is_running.get(chat_id):
        await msg.answer("⏳ Процесс уже запущен...\n\nИспользуйте /stop для остановки")
        return
    
    if chat_id not in uploaded_files:
        await msg.answer("❌ Сначала загрузите файл с пользователями (users.txt или users.csv)")
        return
    
    if msg.chat.type not in ['group', 'supergroup']:
        await msg.answer("❌ Бот работает только в группах и супергруппах")
        return
    
    users = parse_file(uploaded_files[chat_id])
    
    if not users:
        await msg.answer("❌ Файл пустой или не содержит пользователей")
        return
    
    is_running[chat_id] = True
    
    estimated_time = len(users) * DELAY_BETWEEN / 60
    
    await msg.answer(
        f"🚀 *Начинаю добавление пользователей*\n\n"
        f"👥 Всего пользователей: `{len(users)}`\n"
        f"⏱ Задержка: `{DELAY_BETWEEN}` сек между добавлениями\n"
        f"📦 Пакетная обработка: каждые `{BATCH_SIZE}` = `{DELAY_BATCH}` сек паузы\n"
        f"⏰ Примерное время: ~{int(estimated_time)} минут\n\n"
        f"Используйте /stop для остановки",
        parse_mode='Markdown'
    )
    
    log.info(f"Запуск добавления в чате {chat_id}, пользователей: {len(users)}")
    asyncio.create_task(process(chat_id, users, msg))

@dp.message(Command('stop'))
async def stop(msg: Message):
    chat_id = msg.chat.id
    
    if is_running.get(chat_id):
        is_running[chat_id] = False
        await msg.answer(
            "🛑 *Остановка процесса...*\n\n"
            "Текущая операция будет завершена, затем процесс остановится.\n"
            "Используйте /stats для просмотра результатов.",
            parse_mode='Markdown'
        )
        log.info(f"Остановка процесса в чате {chat_id}")
    else:
        await msg.answer("ℹ️ Нет активных процессов для остановки")

@dp.message(Command('help'))
async def help_command(msg: Message):
    """Detailed help information"""
    help_text = """📖 *Подробная справка*

*Основные команды:*
/start - Главное меню
/add\\_users - Запустить добавление
/stop - Остановить процесс
/status - Текущий статус
/stats - Статистика операций
/preview - Просмотр загруженного файла
/settings - Настройки бота
/help - Эта справка

*Форматы файлов:*

*TXT файл:*
```
username1
username2
user_id_123
```

*CSV файл:*
```
username,user_id,id
user1,123,
user2,,456
```

*Коды ошибок:*
🔒 Приватность - Настройки приватности
👤 Не в контактах - Нет в контактах
📊 Много групп - Лимит групп
🚫 Забанены - Пользователь забанен
⏳ FloodWait - Ограничение Telegram

*Советы:*
• Добавляйте не более 50 пользователей в день
• При PeerFlood подождите 24 часа
• Используйте задержки 60+ секунд
• Добавьте бота администратором группы"""
    
    await msg.answer(help_text, parse_mode='Markdown')

async def main():
    log.info("🚀 Запуск бота...")
    await app.start()
    log.info("✅ Pyrogram клиент готов")
    log.info("✅ Бот готов к работе")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
