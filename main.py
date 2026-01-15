import logging
import asyncio
import csv
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage

from pyrogram import Client
from pyrogram.errors import (
    FloodWait, UserPrivacyRestricted, PeerFlood,
    UserNotMutualContact, UserChannelsTooMuch, UserBannedInChannel
)

BOT_TOKEN = 'your_bot_token_here'
API_ID = 12345678
API_HASH = 'your_api_hash_here'

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
    
    for idx, user in enumerate(users, 1):
        if not is_running.get(chat_id):
            break
            
        log.info(f"[{idx}/{total}] {user}")
        result = await add_user(chat_id, user)
        stats[result] = stats.get(result, 0) + 1
        
        if result == 'peer_flood':
            await msg.answer("🚫 PeerFlood! Остановка. Повторите через 24 часа.")
            break
        
        if idx % BATCH_SIZE == 0:
            await asyncio.sleep(DELAY_BATCH)
        else:
            await asyncio.sleep(DELAY_BETWEEN)
    
    report = f"""📊 Отчёт

✅ Успешно: {stats['success']}
⏳ FloodWait: {stats['flood']}
🔒 Приватность: {stats['privacy']}
👤 Не в контактах: {stats['not_contact']}
📊 Много групп: {stats['too_many_groups']}
🚫 Забанены: {stats['banned']}
❌ Ошибки: {stats['error']}

Обработано: {idx}/{total}"""
    
    await msg.answer(report)
    log.info(report)
    is_running[chat_id] = False

@dp.message(Command('start'))
async def start(msg: Message):
    await msg.answer(
        "👋 Бот для добавления пользователей\n\n"
        "1. Добавьте бота в группу (админ)\n"
        "2. Отправьте users.txt или users.csv\n"
        "3. Напишите /add_users\n\n"
        "Команды: /add_users /stop"
    )

@dp.message(F.document)
async def handle_file(msg: Message):
    doc = msg.document
    
    if not (doc.file_name.endswith('.txt') or doc.file_name.endswith('.csv')):
        await msg.answer("❌ Только .txt или .csv")
        return
    
    Path('downloads').mkdir(exist_ok=True)
    file_path = f"downloads/{doc.file_name}"
    await bot.download(doc, destination=file_path)
    
    uploaded_files[msg.chat.id] = file_path
    users = parse_file(file_path)
    
    await msg.answer(f"✅ Файл: {doc.file_name}\n👥 Пользователей: {len(users)}\n\nНапишите /add_users")
    log.info(f"Загружен {doc.file_name} в чат {msg.chat.id}")

@dp.message(Command('add_users'))
async def add_users(msg: Message):
    chat_id = msg.chat.id
    
    if is_running.get(chat_id):
        await msg.answer("⏳ Уже идёт...")
        return
    
    if chat_id not in uploaded_files:
        await msg.answer("❌ Загрузите файл")
        return
    
    if msg.chat.type not in ['group', 'supergroup']:
        await msg.answer("❌ Только в группах")
        return
    
    users = parse_file(uploaded_files[chat_id])
    
    if not users:
        await msg.answer("❌ Файл пустой")
        return
    
    is_running[chat_id] = True
    await msg.answer(
        f"🚀 Начинаю добавление {len(users)} пользователей\n"
        f"⏱ {DELAY_BETWEEN}с между добавлениями\n"
        f"📦 {DELAY_BATCH}с каждые {BATCH_SIZE} человек\n\n"
        f"/stop для остановки"
    )
    
    log.info(f"Запуск в чате {chat_id}, пользователей: {len(users)}")
    asyncio.create_task(process(chat_id, users, msg))

@dp.message(Command('stop'))
async def stop(msg: Message):
    chat_id = msg.chat.id
    
    if is_running.get(chat_id):
        is_running[chat_id] = False
        await msg.answer("🛑 Остановка...")
        log.info(f"Остановка в чате {chat_id}")
    else:
        await msg.answer("ℹ️ Не запущен")

async def main():
    log.info("Запуск...")
    await app.start()
    log.info("✅ Готов")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
