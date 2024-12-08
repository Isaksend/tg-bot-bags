import cv2
from pyzbar.pyzbar import decode
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import requests
import sqlite3
import os
import shlex
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
import logging
from telegram.error import NetworkError
# Токен бота
BOT_TOKEN = '7867222443:AAHKAhhOF2FvCAhd_ejVg4lDZjW5qolQeoE'


async def safe_polling(app):
    try:
        app.run_polling()
    except NetworkError as e:
        logging.error(f"Сетевая ошибка: {e}")
        print("Ошибка сети. Проверьте подключение или перезапустите бота.")



def create_user_table():
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('seller', 'client')),
        is_logged_in INTEGER DEFAULT 0
    )
    """)

    conn.commit()
    conn.close()

create_user_table()

async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Ошибка! Укажите логин, пароль и (опционально) роль.\nПример: /register <логин> <пароль> <роль>")
        return

    # Сохраняем логин и пароль в user_data для последующей обработки
    context.user_data["register_args"] = context.args

    # Создаём кнопки для выбора роли
    keyboard = [
        [
            InlineKeyboardButton("Продавец", callback_data="register_seller"),
            InlineKeyboardButton("Клиент", callback_data="register_client"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправляем сообщение с кнопками
    await update.message.reply_text(
        "Выберите вашу роль для регистрации:",
        reply_markup=reply_markup
    )

def get_user_role(username):
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    return user[0] if user else None
    
def is_user_logged_in(username):
    print(f"Проверка авторизации для пользователя: {username}")
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("SELECT is_logged_in FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    print(f"Результат запроса для {username}: {user}")
    conn.close()
    return user and user[0] == 1


# Глобальное хранилище ожидающих штрихкодов
pending_barcodes = {}

# Создание базы данных
def create_database():
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        barcode TEXT UNIQUE,
        name TEXT,
        brand TEXT,
        description TEXT,
        quantity TEXT,
        country TEXT,
        material TEXT,
        image_path TEXT
    )
    """)

    conn.commit()
    conn.close()

create_database()

# Добавление продукта в базу данных
def add_product(barcode, name, brand, description, quantity, country, material, image_path):
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()

    cursor.execute("""
    INSERT OR REPLACE INTO products (barcode, name, brand, description, quantity, country, material, image_path)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (barcode, name, brand, description, quantity, country, material, image_path))

    conn.commit()
    conn.close()


# Получение информации о продукте из базы данных
def get_product_info_with_image(barcode):
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()

    cursor.execute("""
    SELECT name, brand, description, quantity, country, material, image_path
    FROM products WHERE barcode = ?
    """, (barcode,))
    product = cursor.fetchone()
    conn.close()

    if product:
        name, brand, description, quantity, country, material, image_path = product
        text_info = (
            f"Штрихкод: {barcode}\n"
            f"Название продукта: {name}\n"
            f"Бренд: {brand}\n"
            f"Описание: {description}\n"
            f"Количество: {quantity}\n"
            f"Страна: {country}\n"
            f"Материал: {material}\n"
        )
        return text_info, image_path
    else:
        return "Продукт с таким штрихкодом отсутствует в базе данных.", None

# Преобразование изображения для распознавания штрихкода
def preprocess_image(image_path):
    img = cv2.imread(image_path)

    # Проверка загрузки изображения
    if img is None:
        print(f"Ошибка загрузки изображения: {image_path}")
        return None

    # Преобразование в оттенки серого
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Увеличение контраста (CLAHE - адаптивное выравнивание гистограммы)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # Удаление шумов
    blurred = cv2.GaussianBlur(enhanced, (3, 3), 0)

    # Пороговая обработка
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Увеличение изображения
    scaled = cv2.resize(binary, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

    return scaled


def debug_save_image(image, filename):
    cv2.imwrite(filename, image)
    print(f"Изображение сохранено для отладки: {filename}")

# Считывание штрихкода
def BarcodeReader(image_path):
    img = preprocess_image(image_path)
    if img is None:
        return None
    processed = preprocess_image(image_path)
    if processed is not None:
        debug_save_image(processed, "processed_image.jpg")
    # Основная попытка распознавания
    detectedBarcodes = decode(img)

    # Попытки с поворотом изображения
    if not detectedBarcodes:
        for angle in [90, 180, 270]:
            rotated = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE if angle == 90 else
                                        cv2.ROTATE_180 if angle == 180 else
                                        cv2.ROTATE_90_COUNTERCLOCKWISE)
            detectedBarcodes = decode(rotated)
            if detectedBarcodes:
                break

    # Итоговый результат
    if not detectedBarcodes:
        print("Штрихкод не распознан после всех попыток.")
        return None

    for barcode in detectedBarcodes:
        barcode_data = barcode.data.decode('utf-8')
        print(f"Штрихкод успешно распознан: {barcode_data}")
        return barcode_data


# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Привет! Войдите в систему и отправьте фото штрихкода для поиска информации о продукте.")


async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Ошибка! Укажите логин и пароль.\nПример: /register <логин> <пароль>")
        return

    # Сохраняем логин и пароль во временные данные
    context.user_data["register_args"] = context.args

    # Отправляем кнопки для выбора роли
    keyboard = [
        [
            InlineKeyboardButton("Продавец", callback_data="register_seller"),
            InlineKeyboardButton("Клиент", callback_data="register_client"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Выберите вашу роль для регистрации:",
        reply_markup=reply_markup
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()  # Обязательно подтверждаем нажатие

    # Получаем роль из callback_data
    role = query.data.split("_")[-1]  # "seller" или "client"

    if "register_args" not in context.user_data:
        await query.edit_message_text("Ошибка! Сначала используйте команду /register <логин> <пароль>.")
        return

    username, password = context.user_data["register_args"]

    # Регистрируем пользователя с выбранной ролью
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, password, role))
        conn.commit()
        await query.edit_message_text(f"Регистрация завершена! Логин: {username}, Роль: {role.capitalize()}.")
    except sqlite3.IntegrityError:
        await query.edit_message_text(f"Ошибка! Пользователь {username} уже существует.")
    finally:
        conn.close()


async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Ошибка! Укажите логин и пароль.\nПример: /login <логин> <пароль>")
        return

    username = context.args[0]
    password = context.args[1]

    # Проверяем данные пользователя
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = ? AND password = ?", (username, password))
    user = cursor.fetchone()

    if user:
        cursor.execute("UPDATE users SET is_logged_in = 1 WHERE id = ?", (user[0],))
        conn.commit()
        await update.message.reply_text(f"Добро пожаловать, {username}! Вы успешно вошли в систему.")
    else:
        await update.message.reply_text("Ошибка! Неверный логин или пароль.")
    conn.close()

async def logout_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Получаем логин пользователя
    username = context.args[0] if len(context.args) > 0 else None
    if not username:
        await update.message.reply_text("Ошибка! Укажите ваш логин для выхода из системы.\nПример: /logout <логин>")
        return

    # Обновляем статус в базе данных
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_logged_in = 0 WHERE username = ?", (username,))
    conn.commit()

    if cursor.rowcount > 0:  # Если была изменена хотя бы одна строка
        await update.message.reply_text(f"Пользователь {username} успешно вышел из системы.")
    else:
        await update.message.reply_text(f"Пользователь {username} не найден или уже вышел из системы.")

    conn.close()




# Команда для добавления продукта
async def add_product_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Разбираем текст команды, включая кавычки
    try:
        args = shlex.split(update.message.text)
    except ValueError:
        await update.message.reply_text("Ошибка! Проверьте правильность команды.")
        return

    # Убираем саму команду (/add_product)
    if len(context.args) < 7:
        await update.message.reply_text(
            "Ошибка! Укажите все параметры:\n"
            "/add_product <штрихкод> <название> <бренд> <описание> <количество> <страна> <материал>"
        )
        return

    # Получаем username пользователя
    username = update.message.from_user.username

    # Проверяем, вошёл ли пользователь в систему
    if not is_user_logged_in(username):
        await update.message.reply_text("Ошибка! Сначала войдите в систему с помощью /login.")
        return
    
    # Проверяем роль
    role = get_user_role(username)
    if not role or role != "seller":
        await update.message.reply_text("Ошибка! Только продавцы могут добавлять товары.")
        return

    # Если роль продавец, продолжаем обработку
    args = context.args

    # Извлекаем параметры
    barcode = args[0]
    name = args[1]
    brand = args[2]
    description = args[3]
    quantity = args[4]
    country = args[5]
    material = args[6]

    # Сохраняем продукт в базу данных
    add_product(barcode, name, brand, description, quantity, country, material, None)
    await update.message.reply_text(f"Продукт \"{name}\" добавлен в базу данных.")


async def update_product_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Получаем username пользователя
    username = update.message.from_user.username

    # Проверяем, вошёл ли пользователь в систему
    if not is_user_logged_in(username):
        await update.message.reply_text("Ошибка! Сначала войдите в систему с помощью /login.")
        return
    
    # Проверяем авторизацию
    if not is_user_logged_in(username):
        await update.message.reply_text("Ошибка! Сначала войдите в систему с помощью /login.")
        return
    
    role = get_user_role(username)
    if not role or role != "seller":
        await update.message.reply_text("Ошибка! Только продавцы могут обновлять товары.")
        return
    
    # Разбираем текст команды с учётом кавычек
    try:
        args = shlex.split(update.message.text)
    except ValueError:
        await update.message.reply_text("Ошибка! Проверьте правильность команды.")
        return

    # Убираем саму команду (/update_product)
    args = args[1:]

    # Проверяем, что указаны все параметры
    if len(args) < 7:
        await update.message.reply_text(
            "Ошибка! Укажите все параметры для обновления:\n"
            "/update_product <штрихкод> <название> <бренд> <описание> <количество> <страна> <материал>"
        )
        return

    # Извлекаем параметры
    barcode = args[0]
    name = args[1]
    brand = args[2]
    description = args[3]
    quantity = args[4]
    country = args[5]
    material = args[6]

    # Проверяем наличие продукта
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM products WHERE barcode = ?", (barcode,))
    product = cursor.fetchone()

    if not product:
        conn.close()
        await update.message.reply_text(f"Продукт с штрихкодом {barcode} не найден в базе данных.")
        return

    # Обновляем данные в базе
    cursor.execute("""
    UPDATE products
    SET name = ?, brand = ?, description = ?, quantity = ?, country = ?, material = ?
    WHERE barcode = ?
    """, (name, brand, description, quantity, country, material, barcode))

    conn.commit()
    conn.close()

    await update.message.reply_text(f"Данные для продукта с штрихкодом {barcode} успешно обновлены.")


async def delete_product_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Получаем username пользователя
    username = update.message.from_user.username

    # Проверяем, вошёл ли пользователь в систему
    if not is_user_logged_in(username):
        await update.message.reply_text("Ошибка! Сначала войдите в систему с помощью /login.")
        return
    role = get_user_role(username)

    if not role or role != "seller":
        await update.message.reply_text("Ошибка! Только продавцы могут удалять товары.")
        return
    
    if len(context.args) < 1:
        await update.message.reply_text("Ошибка! Укажите штрихкод продукта для удаления:\n"
                                        "/delete_product <штрихкод>")
        return

    # Извлекаем штрихкод
    barcode = context.args[0]

    # Удаляем продукт из базы
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()

    # Проверяем наличие продукта
    cursor.execute("SELECT image_path FROM products WHERE barcode = ?", (barcode,))
    product = cursor.fetchone()

    if not product:
        conn.close()
        await update.message.reply_text(f"Продукт с штрихкодом {barcode} не найден в базе данных.")
        return

    # Удаляем фото, если оно есть
    image_path = product[0]
    if image_path and os.path.exists(image_path):
        os.remove(image_path)

    # Удаляем продукт из базы
    cursor.execute("DELETE FROM products WHERE barcode = ?", (barcode,))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"Продукт с штрихкодом {barcode} успешно удалён.")


# Команда для загрузки фото продукта
async def upload_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Ошибка! Укажите штрихкод продукта.\nПример: /upload_image 1234567890128")
        return

    barcode = context.args[0]
    conn = sqlite3.connect("products.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM products WHERE barcode = ?", (barcode,))
    product = cursor.fetchone()
    conn.close()

    if not product:
        await update.message.reply_text(f"Продукт с штрихкодом {barcode} не найден в базе данных. Добавьте его с помощью команды /add_product.")
        return

    user_id = update.message.from_user.id
    pending_barcodes[user_id] = barcode
    await update.message.reply_text(f"Теперь отправьте фотографию для продукта с штрихкодом {barcode}.")

# Обработка фотографий
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    photo_file = await update.message.photo[-1].get_file()
    file_path = f"photo_{user_id}.jpg"
    await photo_file.download_to_drive(file_path)

    if user_id in pending_barcodes:
        # Фото продукта
        barcode = pending_barcodes.pop(user_id)
        os.makedirs("images", exist_ok=True)
        image_path = f"images/{barcode}.jpg"
        os.rename(file_path, image_path)

        conn = sqlite3.connect("products.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE products SET image_path = ? WHERE barcode = ?", (image_path, barcode))
        conn.commit()
        conn.close()

        await update.message.reply_text(f"Фото для продукта с штрихкодом {barcode} успешно загружено.")
    else:
        # Фото штрихкода
        barcode = BarcodeReader(file_path)
        if barcode:
            product_info, image_path = get_product_info_with_image(barcode)
            if image_path and os.path.exists(image_path):
                # Отправляем текст и изображение
                await update.message.reply_text(product_info)
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=open(image_path, 'rb'))
            else:
                # Отправляем только текст
                await update.message.reply_text(product_info)
        else:
            await update.message.reply_text("Штрихкод не обнаружен или изображение повреждено.")


# Основная функция
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register_command))
    app.add_handler(CommandHandler("login", login_command))
    app.add_handler(CommandHandler("logout", logout_command))
    app.add_handler(CommandHandler("add_product", add_product_command))
    app.add_handler(CommandHandler("update_product", update_product_command))  # Обновление продукта
    app.add_handler(CommandHandler("delete_product", delete_product_command))
    app.add_handler(CommandHandler("upload_image", upload_image))
    
    
    # Обработчик кнопок
    app.add_handler(CallbackQueryHandler(button_handler)) 
    
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    app.run_polling()

if __name__ == "__main__":
    main()
