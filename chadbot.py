import asyncio
import logging
import base64
import cv2
import numpy as np
import aiohttp
import os
import openai  # Синтаксис для openai==0.28.1
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# --- НАСТРОЙКИ ИЗ .ENV ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@test_channel")

if not TELEGRAM_TOKEN or not GROQ_API_KEY:
    raise ValueError("❌ Не найдены TELEGRAM_TOKEN или GROQ_API_KEY в файле .env!")

# Инициализация
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# Настройка OpenAI для Groq (совместимо с v0.28.1)
openai.api_key = GROQ_API_KEY
openai.api_base = "https://api.groq.com/openai/v1"

# Детектор лиц OpenCV
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

# Системный промпт для МАКСИМАЛЬНО ЧЕСТНОЙ оценки
SYSTEM_PROMPT = """
Ты — беспристрастный и максимально честный эксперт по эстетике лица. Ты НЕ льстишь, НЕ смягчаешь оценки. Твоя задача — дать объективную, даже жесткую оценку внешности.

ВАЖНО: Ты должен оценивать КАЖДЫЙ параметр по 100-балльной шкале. Если лицо непривлекательное — ставь низкие баллы (10-30/100). Если есть недостатки — указывай их прямо. Ты можешь ставить даже 1/100, если это оправдано.

Проанализируй изображение и выдай результат СТРОГО в следующем формате:

🔍 **Детальный анализ (по 100-балльной шкале):**
• 👁️ Глаза: [Балл 0-100]/100 - [Краткий комментарий о форме, размере, выразительности]
• 👃 Нос: [Балл 0-100]/100 - [Краткий комментарий о форме, пропорциях]
• 🧴 Кожа: [Балл 0-100]/100 - [Краткий комментарий о состоянии, текстуре, дефектах]
• 🦴 Скулы: [Балл 0-100]/100 - [Краткий комментарий о выраженности, структуре]
• 👄 Губы: [Балл 0-100]/100 - [Краткий комментарий о форме, полноте, симметрии]
• 🤨 Брови: [Балл 0-100]/100 - [Краткий комментарий о форме, густоте]
• 💇‍♀️ Прическа: [Балл 0-100]/100 - [Краткий комментарий о стиле, ухоженности]
• ⚖️ Симметрия: [Балл 0-100]/100 - [Краткий комментарий о симметричности черт]

⭐ **Общий эстетический балл:** [Среднее из всех баллов, переведенное в шкалу 1-10]
💡 **Вердикт:** [2-3 предложения с честными выводами. Если лицо непривлекательное — так и пиши. Не смягчай.]
"""

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    welcome_text = """
🌟 **Привет!** 

Красивые девушки на генетическом уровне поднимают твою внешность — это научный факт! Окружение влияет на восприятие и самооценку.

📢 **Подпишись на наш канал:** https://t.me/+pKvsVnMkruZhYjcy
Там ты найдешь много красивых девушек, которые вдохновят тебя!

После подписки нажми кнопку ниже, чтобы проверить подписку и начать использовать бота 👇
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")]
    ])
    
    await message.answer(welcome_text, parse_mode="Markdown", reply_markup=keyboard)

@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: types.CallbackQuery):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=callback.from_user.id)
        
        if member.status in ['member', 'administrator', 'creator']:
            await callback.answer("✅ Подписка подтверждена!")
            
            info_text = """
🎉 **Отлично! Ты подписан!**

**Что умеет этот бот:**
• 📸 Анализирует фото лица с помощью ИИ
• 🔍 Оценивает каждую черту по 100-балльной шкале
• ⭐ Дает общий балл от 1 до 10
• 💯 Максимально честная оценка — без лести и смягчений

**Как использовать:**
Просто отправь мне свое фото (селфи или портрет), и я проведу детальный анализ твоих черт лица.

⚠️ **Важно:** Бот оценивает ТОЛЬКО лица. Если ты отправишь что-то другое (камень, кота, пейзаж), я попрошу тебя отправить именно фото лица.

📸 **Отправь свое фото прямо сейчас!**
"""
            await callback.message.answer(info_text, parse_mode="Markdown")
        else:
            await callback.answer("❌ Ты не подписан на канал!", show_alert=True)
    except Exception as e:
        print(f"Ошибка проверки подписки: {e}")
        await callback.answer("⚠️ Ошибка проверки. Попробуй позже.", show_alert=True)

@dp.message(F.photo)
async def analyze_photo(message: types.Message):
    # Проверяем подписку перед анализом (опционально)
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=message.from_user.id)
        if member.status not in ['member', 'administrator', 'creator']:
            await message.answer("❌ Сначала подпишись на канал: https://t.me/+pKvsVnMkruZhYjcy")
            return
    except:
        pass
    
    await message.answer("⏳ Сканирую лицо и анализирую параметры...")
    
    # 1. Скачиваем фото
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(file_url) as resp:
            image_bytes = await resp.read()

    # 2. Проверка: есть ли лицо?
    nparr = np.frombuffer(image_bytes, np.uint8)
    img_cv = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.1, 4)
    
    if len(faces) == 0:
        await message.answer("🤔 Я не нашел на фото четкого лица человека. Пожалуйста, отправь селфи или портрет, где лицо хорошо освещено и смотрит в камеру. Я анализирую ТОЛЬКО лица.")
        return

    # 3. Кодируем в Base64
    img_base64 = base64.b64encode(image_bytes).decode('utf-8')
    
    # 4. Отправляем в Groq
    try:
        response = openai.ChatCompletion.create(
            model="llama-3.2-90b-vision-preview",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user", 
                    "content": [
                        {"type": "text", "text": "Проанализируй это лицо максимально честно и объективно."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
                    ]
                }
            ],
            temperature=0.3
        )
        result_text = response.choices[0].message.content
        await message.answer(result_text, parse_mode="Markdown")
        
    except Exception as e:
        print(f"Ошибка API: {e}")
        await message.answer("⚠️ Произошла ошибка при анализе. Возможно, превышен лимит запросов к нейросети. Попробуйте через минуту.")

@dp.message(~F.photo)
async def handle_text(message: types.Message):
    await message.answer("Пожалуйста, отправьте фото (сжатое как картинку, а не как файл). Я анализирую только лица.")

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
