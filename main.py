import asyncio
import os
from datetime import datetime
from PIL import Image
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncioScheduler

# Данные вашего бота и канала
BOT_TOKEN = "8736161280:AAHGgiJacTKNo37SHuXmPGqdg-lY37VI8Ls"
CHANNEL_ID = "@Dnipro_meridian"
WATERMARK_PATH = "watermark.png"

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncioScheduler()

class PostStates(StatesGroup):
    text = State()
    photo = State()
    premium_reactions = State()
    schedule_time = State()

def apply_watermark(input_image_path, output_image_path, watermark_path):
    try:
        base_image = Image.open(input_image_path).convert("RGBA")
        watermark = Image.open(watermark_path).convert("RGBA")
        w_width = int(base_image.width * 0.20)
        w_height = int(watermark.height * (w_width / watermark.width))
        watermark = watermark.resize((w_width, w_height))
        position = (base_image.width - w_width - 20, base_image.height - w_height - 20)
        transparent = Image.new("RGBA", base_image.size, (0, 0, 0, 0))
        transparent.paste(base_image, (0, 0))
        transparent.paste(watermark, position, mask=watermark)
        finished_image = transparent.convert("RGB")
        finished_image.save(output_image_path, "JPEG")
        return True
    except Exception as e:
        print(f"Ошибка ватермарки: {e}")
        return False

async def send_scheduled_post(chat_id, text, photo_path=None, reactions=None):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    if reactions:
        buttons = []
        for emoji in reactions:
            buttons.append(InlineKeyboardButton(text=f"{emoji} 0", callback_data=f"react_{emoji}"))
        keyboard.inline_keyboard.append(buttons)
    try:
        if photo_path and os.path.exists(photo_path):
            photo = types.FSInputFile(photo_path)
            await bot.send_photo(CHANNEL_ID, photo=photo, caption=text, reply_markup=keyboard, parse_mode="Markdown")
            os.remove(photo_path)
        else:
            await bot.send_message(CHANNEL_ID, text=text, reply_markup=keyboard, parse_mode="Markdown")
        await bot.send_message(chat_id, "✅ Пост опубликован в канале!")
    except Exception as e:
        await bot.send_message(chat_id, f"❌ Ошибка публикации: {e}")

@dp.message(Command("start", "newpost"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("📝 Отправьте текст для вашего поста (поддерживается Markdown):")
    await state.set_state(PostStates.text)

@dp.message(PostStates.text)
async def process_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    markup = types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="⏭ Пропустить фото")]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer("📸 Отправьте фотографию или нажмите 'Пропустить фото':", reply_markup=markup)
    await state.set_state(PostStates.photo)

@dp.message(PostStates.photo)
async def process_photo(message: types.Message, state: FSMContext):
    if message.photo:
        photo_id = message.photo[-1].file_id
        file = await bot.get_file(photo_id)
        temp_input = f"temp_in_{message.chat.id}.jpg"
        temp_output = f"temp_out_{message.chat.id}.jpg"
        await bot.download_file(file.file_path, temp_input)
        if os.path.exists(WATERMARK_PATH):
            if apply_watermark(temp_input, temp_output, WATERMARK_PATH):
                await state.update_data(photo_path=temp_output)
                await message.answer("🔒 Ватермарка успешно наложена.")
            else:
                await state.update_data(photo_path=temp_input)
        else:
            await state.update_data(photo_path=temp_input)
        if os.path.exists(temp_input) and temp_input != temp_output:
            os.remove(temp_input)
    elif message.text == "⏭ Пропустить фото":
        await state.update_data(photo_path=None)

    await message.answer("⚡ Отправьте эмодзи для реакций через пробел (или напишите `нет`):")
    await state.set_state(PostStates.premium_reactions)

@dp.message(PostStates.premium_reactions)
async def process_reactions(message: types.Message, state: FSMContext):
    reactions = message.text.split() if message.text.lower() != 'нет' else None
    await state.update_data(reactions=reactions)
    await message.answer("⏰ Укажите время в формате `ДД.ММ.ГГГГ ЧЧ:ММ` (или напишите `сейчас`):")
    await state.set_state(PostStates.schedule_time)

@dp.message(PostStates.schedule_time)
async def process_schedule(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if message.text.lower() == 'сейчас':
        await send_scheduled_post(message.chat.id, data['text'], data.get('photo_path'), data.get('reactions'))
        await state.clear()
    else:
        try:
            run_time = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
            scheduler.add_job(send_scheduled_post, 'date', run_date=run_time, args=[message.chat.id, data['text'], data.get('photo_path'), data.get('reactions')])
            await message.answer(f"📅 Пост успешно запланирован на {message.text}!")
            await state.clear()
        except ValueError:
            await message.answer("❌ Неверный формат. Попробуйте еще раз (например: `25.10.2026 18:00`):")

@dp.callback_query(F.data.startswith("react_"))
async def handle_reaction_click(callback: types.CallbackQuery):
    emoji = callback.data.split("_")[1]
    reply_markup = callback.message.reply_markup
    for row in reply_markup.inline_keyboard:
        for button in row:
            if button.callback_data == callback.data:
                count = int(button.text.split()[1]) + 1
                button.text = f"{emoji} {count}"
    await callback.message.edit_reply_markup(reply_markup=reply_markup)
    await callback.answer()

async def main():
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
