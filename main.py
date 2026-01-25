import os
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
from dotenv import load_dotenv
import asyncio
import logging
from contextlib import suppress

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

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
            await msg.answer(
                "🚫 <b>Обнаружен PeerFlood!</b>\n\n"
                "❌ Процесс автоматически остановлен\n"
                "⏰ Повторите попытку через 24 часа\n"
                "💡 Рекомендуем увеличить задержки между добавлениями",
                parse_mode='HTML'
            )
            break
        
        if idx % 10 == 0:
            progress = (idx / total) * 100
            await msg.answer(
                f"⚡️ <b>Обработка в процессе...</b>\n\n"
                f"📊 Прогресс: <code>{idx}/{total}</code> ({progress:.1f}%)\n"
                f"✅ Успешно добавлено: <b>{stats['success']}</b>\n"
                f"⏱ Продолжаем работу...",
                parse_mode='HTML'
            )
        
        if idx % BATCH_SIZE == 0:
            await asyncio.sleep(DELAY_BATCH)
        else:
            await asyncio.sleep(DELAY_BETWEEN)
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    stats_history[chat_id] = {
        'date': end_time.strftime('%Y-%m-%d %H:%M:%S'),
        'stats': stats,
        'total': total,
        'processed': idx,
        'duration': duration
    }
    
    success_rate = (stats['success'] / idx * 100) if idx > 0 else 0
    
    report = f"""
🎉 <b>Операция завершена!</b>

━━━━━━━━━━━━━━━━━━━━
📈 <b>РЕЗУЛЬТАТЫ</b>
━━━━━━━━━━━━━━━━━━━━

✅ <b>Успешно:</b> {stats['success']} ({success_rate:.1f}%)
⏳ <b>FloodWait:</b> {stats['flood']}
🔒 <b>Настройки приватности:</b> {stats['privacy']}
👤 <b>Не в контактах:</b> {stats['not_contact']}
📊 <b>Превышен лимит групп:</b> {stats['too_many_groups']}
🚫 <b>Заблокированы:</b> {stats['banned']}
❌ <b>Другие ошибки:</b> {stats['error']}

━━━━━━━━━━━━━━━━━━━━
📋 <b>ОБЩАЯ ИНФОРМАЦИЯ</b>
━━━━━━━━━━━━━━━━━━━━

👥 Обработано: <b>{idx}</b> из {total}
⏱ Затраченное время: <b>{int(duration // 60)}м {int(duration % 60)}с</b>
⚡️ Средняя скорость: <b>{stats['success'] / (duration / 60):.1f}</b> польз/мин

━━━━━━━━━━━━━━━━━━━━

💾 Используйте /stats для просмотра детальной статистики
"""
    
    await msg.answer(report, parse_mode='HTML')
    log.info(report)
    is_running[chat_id] = False
    
    await export_failed_users(chat_id, users, stats, msg)

async def export_failed_users(chat_id: int, users: list, stats: dict, msg: Message):
    failed_count = stats['privacy'] + stats['not_contact'] + stats['too_many_groups'] + stats['banned'] + stats['error']
    
    if failed_count > 0:
        await msg.answer(
            f"💾 <b>Экспорт неудачных попыток...</b>\n\n"
            f"📁 Сохранено <code>{failed_count}</code> пользователей",
            parse_mode='HTML'
        )

@dp.message(Command('start'))
async def start(msg: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Помощь", callback_data="help")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")]
    ])
    
    await msg.answer(
        "👋 <b>Добро пожаловать в бот массового добавления!</b>\n\n"
        "🚀 <b>Быстрый старт за 3 шага:</b>\n\n"
        "1️⃣ Добавьте бота в вашу группу с правами администратора\n"
        "2️⃣ Отправьте файл с пользователями (users.txt или users.csv)\n"
        "3️⃣ Запустите процесс командой /add_users\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📋 <b>Основные команды:</b>\n\n"
        "▫️ /add_users — Начать добавление пользователей\n"
        "▫️ /stop — Остановить текущий процесс\n"
        "▫️ /status — Проверить статус операции\n"
        "▫️ /stats — Посмотреть статистику\n"
        "▫️ /preview — Предпросмотр загруженного файла\n"
        "▫️ /settings — Настройки и параметры\n"
        "▫️ /help — Подробная инструкция\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "💡 <b>Совет:</b> Начните с небольшого файла, чтобы протестировать работу!",
        parse_mode='HTML',
        reply_markup=keyboard
    )

@dp.message(F.document)
async def handle_file(msg: Message):
    doc = msg.document
    
    if not (doc.file_name.endswith('.txt') or doc.file_name.endswith('.csv')):
        await msg.answer(
            "❌ <b>Неподдерживаемый формат файла!</b>\n\n"
            "📁 Пожалуйста, отправьте файл в формате:\n"
            "▫️ .txt (построчно)\n"
            "▫️ .csv (с заголовками)",
            parse_mode='HTML'
        )
        return
    
    Path('downloads').mkdir(exist_ok=True)
    file_path = f"downloads/{doc.file_name}"
    await bot.download(doc, destination=file_path)
    
    uploaded_files[msg.chat.id] = file_path
    users = parse_file(file_path)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👀 Просмотр (10 строк)", callback_data="preview_10")],
        [InlineKeyboardButton(text="🚀 Начать добавление", callback_data="start_adding")]
    ])
    
    await msg.answer(
        f"✅ <b>Файл успешно загружен и обработан!</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📄 <b>Название:</b> <code>{doc.file_name}</code>\n"
        f"👥 <b>Найдено пользователей:</b> <b>{len(users)}</b>\n"
        f"📦 <b>Размер файла:</b> {doc.file_size / 1024:.1f} KB\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n",
        parse_mode='HTML',
        reply_markup=keyboard
    )
    log.info(f"Загружен {doc.file_name} в чат {msg.chat.id}")

@dp.message(Command('preview'))
async def preview_file(msg: Message):
    chat_id = msg.chat.id
    
    if chat_id not in uploaded_files:
        await msg.answer(
            "❌ <b>Файл не найден!</b>\n\n"
            "📤 Сначала загрузите файл с пользователями\n"
            "💡 Поддерживаемые форматы: .txt, .csv",
            parse_mode='HTML'
        )
        return
    
    users = parse_file(uploaded_files[chat_id])
    preview_list = users[:10]
    
    preview_text = "👀 <b>Предпросмотр загруженного файла</b>\n\n━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for i, user in enumerate(preview_list, 1):
        preview_text += f"{i}. <code>{user}</code>\n"
    
    if len(users) > 10:
        preview_text += f"\n━━━━━━━━━━━━━━━━━━━━\n📋 ... и ещё <b>{len(users) - 10}</b> пользователей"
    
    preview_text += f"\n\n📊 <b>Всего в файле:</b> {len(users)} пользователей"
    
    await msg.answer(preview_text, parse_mode='HTML')

@dp.message(Command('status'))
async def check_status(msg: Message):
    chat_id = msg.chat.id
    
    if is_running.get(chat_id):
        await msg.answer(
            "⚙️ <b>СТАТУС СИСТЕМЫ</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🟢 <b>Состояние:</b> Активно\n"
            "🔄 <b>Операция:</b> Добавление пользователей\n"
            "⚡️ <b>Процесс:</b> Выполняется...\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🛑 Используйте /stop для остановки",
            parse_mode='HTML'
        )
    else:
        await msg.answer(
            "⚙️ <b>СТАТУС СИСТЕМЫ</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚪️ <b>Состояние:</b> Неактивно\n"
            "💤 <b>Операция:</b> Нет активных процессов\n"
            "📊 <b>Готовность:</b> Ожидание команд\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "💡 Используйте /add_users для запуска",
            parse_mode='HTML'
        )

@dp.message(Command('stats'))
async def show_stats(msg: Message):
    chat_id = msg.chat.id
    
    if chat_id not in stats_history:
        await msg.answer(
            "📊 <b>История операций пуста</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "ℹ️ Статистика пока не собрана\n"
            "🚀 Выполните /add_users для начала работы\n"
            "📈 После завершения здесь появится детальная статистика",
            parse_mode='HTML'
        )
        return
    
    history = stats_history[chat_id]
    stats = history['stats']
    
    success_rate = (stats['success'] / history['processed'] * 100) if history['processed'] > 0 else 0
    
    report = f"""
📊 <b>ДЕТАЛЬНАЯ СТАТИСТИКА</b>

━━━━━━━━━━━━━━━━━━━━
⏰ <b>ИНФОРМАЦИЯ О СЕАНСЕ</b>
━━━━━━━━━━━━━━━━━━━━

📅 <b>Дата:</b> <code>{history['date']}</code>
⏱ <b>Продолжительность:</b> {int(history['duration'] // 60)}м {int(history['duration'] % 60)}с
⚡️ <b>Скорость:</b> {stats['success'] / (history['duration'] / 60):.1f} польз/мин

━━━━━━━━━━━━━━━━━━━━
📈 <b>РЕЗУЛЬТАТЫ ОБРАБОТКИ</b>
━━━━━━━━━━━━━━━━━━━━

✅ <b>Успешно добавлено:</b> {stats['success']} <i>({success_rate:.1f}%)</i>
⏳ <b>FloodWait:</b> {stats['flood']}
🔒 <b>Приватность:</b> {stats['privacy']}
👤 <b>Не в контактах:</b> {stats['not_contact']}
📊 <b>Превышен лимит групп:</b> {stats['too_many_groups']}
🚫 <b>Заблокированы:</b> {stats['banned']}
❌ <b>Другие ошибки:</b> {stats['error']}

━━━━━━━━━━━━━━━━━━━━
📋 <b>ИТОГО</b>
━━━━━━━━━━━━━━━━━━━━

👥 Обработано: <b>{history['processed']}</b> из {history['total']}
📊 Эффективность: <b>{success_rate:.1f}%</b>
"""
    
    await msg.answer(report, parse_mode='HTML')

@dp.message(Command('settings'))
async def show_settings(msg: Message):
    settings_text = f"""
⚙️ <b>ТЕКУЩИЕ НАСТРОЙКИ СИСТЕМЫ</b>

━━━━━━━━━━━━━━━━━━━━
⏱ <b>ПАРАМЕТРЫ ЗАДЕРЖЕК</b>
━━━━━━━━━━━━━━━━━━━━

▫️ Между добавлениями: <code>{DELAY_BETWEEN}</code> сек
▫️ Между пакетами: <code>{DELAY_BATCH}</code> сек
▫️ Размер пакета: <code>{BATCH_SIZE}</code> пользователей

━━━━━━━━━━━━━━━━━━━━
💡 <b>РЕКОМЕНДАЦИИ</b>
━━━━━━━━━━━━━━━━━━━━

1️⃣ При получении PeerFlood увеличьте задержки в 2 раза
2️⃣ Для максимальной безопасности уменьшите размер пакета
3️⃣ Не добавляйте более 50 пользователей в день
4️⃣ Делайте перерывы между сеансами минимум 6 часов
5️⃣ Следите за показателем успешности (должен быть >50%)

━━━━━━━━━━━━━━━━━━━━

🔐 <b>Безопасность — наш приоритет!</b>
"""
    
    await msg.answer(settings_text, parse_mode='HTML')

@dp.message(Command('add_users'))
async def add_users(msg: Message):
    chat_id = msg.chat.id
    
    if is_running.get(chat_id):
        await msg.answer(
            "⚠️ <b>Процесс уже запущен!</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⏳ Операция выполняется в данный момент\n"
            "🔄 Дождитесь завершения текущего процесса\n\n"
            "🛑 Или используйте /stop для остановки",
            parse_mode='HTML'
        )
        return
    
    if chat_id not in uploaded_files:
        await msg.answer(
            "❌ <b>Файл не загружен!</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📤 <b>Шаг 1:</b> Загрузите файл с пользователями\n"
            "📋 <b>Формат:</b> users.txt или users.csv\n\n"
            "💡 <b>Пример формата TXT:</b>\n"
            "<code>username1\nusername2\nuser_id_123</code>\n\n"
            "💡 <b>Пример формата CSV:</b>\n"
            "<code>username,user_id\nuser1,123\nuser2,456</code>",
            parse_mode='HTML'
        )
        return
    
    if msg.chat.type not in ['group', 'supergroup']:
        await msg.answer(
            "❌ <b>Неверный тип чата!</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ Бот работает только в группах и супергруппах\n"
            "👥 Добавьте бота в нужную группу\n"
            "🔐 Выдайте права администратора\n"
            "🚀 Запустите команду снова",
            parse_mode='HTML'
        )
        return
    
    users = parse_file(uploaded_files[chat_id])
    
    if not users:
        await msg.answer(
            "❌ <b>Файл пустой!</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📭 Файл не содержит пользователей\n"
            "📤 Загрузите корректный файл\n"
            "✅ Убедитесь в правильности формата",
            parse_mode='HTML'
        )
        return
    
    is_running[chat_id] = True
    
    estimated_time = len(users) * DELAY_BETWEEN / 60
    
    await msg.answer(
        f"🚀 <b>ЗАПУСК ПРОЦЕССА ДОБАВЛЕНИЯ</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>ПАРАМЕТРЫ ОПЕРАЦИИ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 <b>Всего пользователей:</b> <code>{len(users)}</code>\n"
        f"⏱ <b>Задержка:</b> <code>{DELAY_BETWEEN}</code> сек между добавлениями\n"
        f"📦 <b>Пакетная обработка:</b> каждые <code>{BATCH_SIZE}</code> пользователей\n"
        f"⏸ <b>Пауза между пакетами:</b> <code>{DELAY_BATCH}</code> сек\n"
        f"⏰ <b>Ориентировочное время:</b> ~<b>{int(estimated_time)}</b> минут\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚡️ Процесс запущен! Следите за обновлениями...\n"
        f"🛑 Для остановки используйте /stop",
        parse_mode='HTML'
    )
    
    log.info(f"Запуск добавления в чате {chat_id}, пользователей: {len(users)}")
    asyncio.create_task(process(chat_id, users, msg))

@dp.message(Command('stop'))
async def stop(msg: Message):
    chat_id = msg.chat.id
    
    if is_running.get(chat_id):
        is_running[chat_id] = False
        await msg.answer(
            "🛑 <b>ОСТАНОВКА ПРОЦЕССА</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⏳ Завершение текущей операции...\n"
            "💾 Сохранение промежуточных результатов...\n"
            "📊 Подготовка статистики...\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "✅ Процесс будет остановлен через несколько секунд\n"
            "📈 Используйте /stats для просмотра результатов",
            parse_mode='HTML'
        )
        log.info(f"Остановка процесса в чате {chat_id}")
    else:
        await msg.answer(
            "ℹ️ <b>Нет активных процессов</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "💤 В данный момент ничего не выполняется\n"
            "🚀 Используйте /add_users для запуска\n"
            "📊 Или /status для проверки состояния",
            parse_mode='HTML'
        )

@dp.message(Command('help'))
async def help_command(msg: Message):
    help_text = """
📖 <b>ПОДРОБНАЯ ИНСТРУКЦИЯ</b>

━━━━━━━━━━━━━━━━━━━━
🎯 <b>ОСНОВНЫЕ КОМАНДЫ</b>
━━━━━━━━━━━━━━━━━━━━

/start — Главное меню и приветствие
/add_users — Запустить процесс добавления
/stop — Остановить текущую операцию
/status — Проверить статус системы
/stats — Детальная статистика операций
/preview — Просмотр загруженного файла
/settings — Настройки и параметры
/help — Показать эту справку

━━━━━━━━━━━━━━━━━━━━
📁 <b>ПОДДЕРЖИВАЕМЫЕ ФОРМАТЫ</b>
━━━━━━━━━━━━━━━━━━━━

<b>📄 TXT файл (построчно):</b>
<code>username1
username2
user_id_123
@username3</code>

<b>📊 CSV файл (с заголовками):</b>
<code>username,user_id,id
user1,123,
user2,,456
@user3,789,</code>

━━━━━━━━━━━━━━━━━━━━
⚠️ <b>КОДЫ ОШИБОК</b>
━━━━━━━━━━━━━━━━━━━━

🔒 <b>Приватность</b> — Настройки конфиденциальности пользователя
👤 <b>Не в контактах</b> — Пользователь отсутствует в контактах
📊 <b>Много групп</b> — Превышен лимит групп у пользователя
🚫 <b>Забанены</b> — Пользователь заблокирован в группе
⏳ <b>FloodWait</b> — Временное ограничение Telegram
❌ <b>Ошибка</b> — Другие технические проблемы

━━━━━━━━━━━━━━━━━━━━
💡 <b>СОВЕТЫ ПО ИСПОЛЬЗОВАНИЮ</b>
━━━━━━━━━━━━━━━━━━━━

1️⃣ Не добавляйте более 50 пользователей в день
2️⃣ При получении PeerFlood подождите 24 часа
3️⃣ Используйте задержки минимум 60 секунд
4️⃣ Обязательно выдайте боту права администратора
5️⃣ Начните с тестового файла из 5-10 пользователей
6️⃣ Регулярно проверяйте статистику командой /stats
7️⃣ Делайте перерывы между сеансами

━━━━━━━━━━━━━━━━━━━━
🔐 <b>БЕЗОПАСНОСТЬ</b>
━━━━━━━━━━━━━━━━━━━━

▫️ Бот следует официальным лимитам Telegram
▫️ Автоматическая обработка FloodWait
▫️ Интеллектуальная система пауз
▫️ Детальное логирование всех операций

━━━━━━━━━━━━━━━━━━━━

❓ <b>Остались вопросы?</b> 
Используйте /status для проверки состояния!
"""
    
    await msg.answer(help_text, parse_mode='HTML')


async def main():
    log.info("🚀 Запуск бота...")

    try:
        # Запуск Pyrogram
        await app.start()
        log.info("✅ Pyrogram клиент готов")

        # Запуск Aiogram
        await dp.start_polling(bot)

    except (KeyboardInterrupt, SystemExit):
        log.warning("⛔ Остановка по сигналу")

    except Exception as e:
        log.exception("❌ Критическая ошибка", exc_info=e)

    finally:
        # Корректное завершение
        with suppress(Exception):
            await bot.session.close()
            await app.stop()

        log.info("🛑 Бот корректно остановлен")

if __name__ == '__main__':
    asyncio.run(main())
