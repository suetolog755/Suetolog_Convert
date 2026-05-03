import os
import json
import struct
import random
import shutil
import io
import time
import threading
from pathlib import Path
from PIL import Image
import telebot
from telebot import types

TOKEN = "8613630902:AAG40R1_fFUUvS1a8VFFf1WaWSCc9mFf1lQ"
CHANNEL_ID = "@brmodels095"
CHANNEL_URL = "https://t.me/brmodels095"
SUPPORT_USERNAME = "@brmodels013"

bot = telebot.TeleBot(TOKEN)
user_files = {}

def analyze_file(file_path):
    try:
        ext = Path(file_path).suffix.lower()
        size_kb = os.path.getsize(file_path) // 1024
        verts, faces, uvs = 0, 0, 0
        
        if ext == '.obj':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if line.startswith('v '): verts += 1
                    elif line.startswith('vt '): uvs += 1
                    elif line.startswith('f '): faces += 1
        
        if verts > 65535: verdict = "Тяжёлая модель"
        elif verts > 40000: verdict = "Средняя модель"
        else: verdict = "Лёгкая модель"
        
        return {'ext': ext, 'verts': verts, 'faces': faces, 'uvs': uvs,
                'size_kb': size_kb, 'verdict': verdict}
    except: return None


class FullModelConverter:
    def __init__(self):
        self.output_dir = Path("converted_output")
        self.temp_dir = Path("temp_processing")
        self.output_dir.mkdir(exist_ok=True, parents=True)
        self.temp_dir.mkdir(exist_ok=True, parents=True)

    def _png_to_btx(self, png_path, output_name=None):
        png_file = Path(png_path)
        if output_name is None: output_name = png_file.stem
        btx_path = self.output_dir / f"{output_name}.btx"
        img = Image.open(png_file).convert("RGB")
        max_size = 512
        if img.width > max_size or img.height > max_size:
            img.thumbnail((max_size, max_size), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        buf.seek(0)
        compressed = Image.open(buf).convert("RGB")
        with open(btx_path, 'wb') as f:
            f.write(b'BTX\x00')
            f.write(compressed.width.to_bytes(2, 'little'))
            f.write(compressed.height.to_bytes(2, 'little'))
            f.write(b'\x01'); f.write(b'\x03')
            f.write(compressed.tobytes())
        return btx_path

    def damage_obj(self, obj_path):
        """
        Создаёт 3 варианта повреждений: царапины, авария, хлам.
        Все варианты НЕ задевают края (отступ 25%).
        """
        with open(obj_path, 'r', encoding='utf-8', errors='ignore') as f:
            original_lines = f.read().split('\n')
        
        # Собираем вершины
        vert_entries = []
        for i, line in enumerate(original_lines):
            if line.startswith('v ') and not line.startswith('vt ') and not line.startswith('vn '):
                parts = line.strip().split()
                if len(parts) >= 4:
                    try:
                        vert_entries.append([i, float(parts[1]), float(parts[2]), float(parts[3])])
                    except: pass
        
        if len(vert_entries) < 10:
            return []
        
        all_x = [v[1] for v in vert_entries]
        all_y = [v[2] for v in vert_entries]
        all_z = [v[3] for v in vert_entries]
        
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        min_z, max_z = min(all_z), max(all_z)
        
        mid_x = (min_x + max_x) / 2
        mid_y = (min_y + max_y) / 2
        mid_z = (min_z + max_z) / 2
        
        size_x = max_x - min_x
        size_y = max_y - min_y
        size_z = max_z - min_z
        
        # Определяем ось вдавливания
        if size_x >= size_y and size_x >= size_z: push_axis = 'x'
        elif size_y >= size_z: push_axis = 'y'
        else: push_axis = 'z'
        
        # Большой отступ от краёв (25%)
        edge = 0.25
        
        def is_edge(x, y, z):
            return (
                abs(x - min_x) < size_x * edge or abs(x - max_x) < size_x * edge or
                abs(y - min_y) < size_y * edge or abs(y - max_y) < size_y * edge or
                abs(z - min_z) < size_z * edge or abs(z - max_z) < size_z * edge
            )
        
        def push(lines, idx, x, y, z, force):
            if push_axis == 'x':
                new_x = x - force if x > 0 else x + force
                lines[idx] = f"v {new_x:.6f} {y:.6f} {z:.6f}"
            elif push_axis == 'y':
                lines[idx] = f"v {x:.6f} {y - force:.6f} {z:.6f}"
            else:
                lines[idx] = f"v {x:.6f} {y:.6f} {z - force:.6f}"
        
        def make_variant(intensity, dents_count, radius_mult, small_radius_mult):
            lines = original_lines.copy()
            # Одна большая вмятина в центре
            main_radius = max(size_x, size_y, size_z) * radius_mult
            for entry in vert_entries:
                idx, x, y, z = entry
                dx, dy, dz = x - mid_x, y - mid_y, z - mid_z
                dist = (dx*dx + dy*dy + dz*dz) ** 0.5
                if dist < main_radius and not is_edge(x, y, z):
                    force = (1 - dist/main_radius) * intensity
                    push(lines, idx, x, y, z, force)
            
            # Мелкие вмятины
            for _ in range(dents_count):
                cx = random.uniform(min_x + size_x*edge, max_x - size_x*edge)
                cy = random.uniform(min_y + size_y*edge, max_y - size_y*edge)
                cz = random.uniform(min_z + size_z*edge, max_z - size_z*edge)
                sr = max(size_x, size_y, size_z) * small_radius_mult
                for entry in vert_entries:
                    idx, x, y, z = entry
                    dx, dy, dz = x - cx, y - cy, z - cz
                    dist = (dx*dx + dy*dy + dz*dz) ** 0.5
                    if dist < sr and not is_edge(x, y, z):
                        force = (1 - dist/sr) * intensity * 0.5 * random.uniform(0.6, 1.4)
                        push(lines, idx, x, y, z, force)
            return lines
        
        results = []
        
        # Вариант 1: Царапины (лёгкие)
        lines1 = make_variant(intensity=0.02, dents_count=10, radius_mult=0.2, small_radius_mult=0.04)
        out1 = self.output_dir / f"{Path(obj_path).stem}_scratches.obj"
        with open(out1, 'w') as f: f.write('\n'.join(lines1))
        results.append((out1, "🤏 Царапины", "scratches"))
        
        # Вариант 2: Авария (средние)
        lines2 = make_variant(intensity=0.15, dents_count=8, radius_mult=0.35, small_radius_mult=0.08)
        out2 = self.output_dir / f"{Path(obj_path).stem}_crash.obj"
        with open(out2, 'w') as f: f.write('\n'.join(lines2))
        results.append((out2, "💪 Авария", "crash"))
        
        # Вариант 3: Хлам (сильные)
        lines3 = make_variant(intensity=0.40, dents_count=12, radius_mult=0.50, small_radius_mult=0.12)
        out3 = self.output_dir / f"{Path(obj_path).stem}_junk.obj"
        with open(out3, 'w') as f: f.write('\n'.join(lines3))
        results.append((out3, "🔥 Хлам", "junk"))
        
        return results

    def generate_xml(self, car_name, obj_name, texture_names):
        xml = '<?xml version="1.0" encoding="utf-8"?>\n'
        xml += f'<Car name="{car_name}">\n  <Case>\n    <Render object="{obj_name}">\n'
        for tex in texture_names: xml += f'      <Texture name="{tex}"/>\n'
        xml += '    </Render>\n  </Case>\n</Car>'
        xml_path = self.output_dir / f"{car_name}.xml"
        xml_path.write_text(xml, encoding='utf-8')
        return xml_path

converter = FullModelConverter()


def check_subscription(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except: return False

def send_subscription_message(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📢 Подписаться", url=CHANNEL_URL),
        types.InlineKeyboardButton("✅ Проверить подписку", callback_data="check_sub")
    )
    bot.send_message(chat_id, "🔒 Подпишитесь\n" + CHANNEL_URL, reply_markup=markup)

def get_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("🚗 Повредить"),
        types.KeyboardButton("📄 Создать XML"),
        types.KeyboardButton("🆘 Техподдержка"),
        types.KeyboardButton("📋 Список"),
        types.KeyboardButton("🗑 Очистить"),
        types.KeyboardButton("🔍 Анализ")
    )
    return markup

def send_progress(chat_id, message_id, text, duration=3):
    steps = [10, 25, 40, 55, 70, 85, 95, 100]
    for p in steps:
        try: bot.edit_message_text(f"{text}\nПрогресс: {p}%", chat_id, message_id)
        except: pass
        time.sleep(duration / len(steps))

def process_damage(uid, cid):
    if uid not in user_files or not user_files[uid]:
        bot.send_message(cid, "❌ Нет файлов."); return
    
    status_msg = bot.send_message(cid, "🤔 Анализирую геометрию детали...\nПрогресс: 0%")
    
    def process():
        time.sleep(0.5)
        for fp in user_files[uid].copy():
            ext = Path(fp).suffix.lower()
            if ext != '.obj': continue
            try:
                results = converter.damage_obj(fp)
                if results:
                    bot.send_message(uid, (
                        "📦 *Создано 3 варианта повреждений:*\n\n"
                        "1️⃣ `*_scratches.obj` — 🤏 Царапины (лёгкие)\n"
                        "2️⃣ `*_crash.obj` — 💪 Авария (средние)\n"
                        "3️⃣ `*_junk.obj` — 🔥 Хлам (сильные)\n\n"
                        "✅ Края детали НЕ задеты.\n"
                        "📂 Импортируйте нужный вариант в ZModeler."
                    ), parse_mode="Markdown")
                    
                    for path, label, vid in results:
                        with open(path, 'rb') as f:
                            bot.send_document(uid, f, caption=f"{label}")
            except Exception as e:
                bot.send_message(uid, f"❌ Ошибка: {e}")
    
    threading.Thread(target=process).start()
    send_progress(cid, status_msg.message_id, "🔧 Создаю 3 варианта...", 4)
    try: bot.edit_message_text("✅ Готово!", cid, status_msg.message_id)
    except: pass
    bot.send_message(cid, "✅ Готово! Выберите подходящий вариант.", reply_markup=get_menu_keyboard())

INSTRUCTION = (
    "📋 *Как сделать повреждения:*\n\n"
    "1️⃣ Скачайте ZModeler 2.5 (не 2.8!)\n"
    "2️⃣ Откройте машину в ZModeler\n"
    "3️⃣ Export → OBJ → нужная деталь → Accept\n"
    "4️⃣ Отправьте .obj файл в бота\n"
    "5️⃣ Нажмите 🚗 Повредить\n"
    "6️⃣ Бот пришлёт 3 файла:\n"
    "     • Царапины (лёгкие)\n"
    "     • Авария (средние)\n"
    "     • Хлам (сильные)\n"
    "7️⃣ Import в ZModeler → Export .dff\n"
    "8️⃣ Готово! Края не задеты."
)

@bot.message_handler(commands=['start'])
def start(msg):
    if not check_subscription(msg.from_user.id): send_subscription_message(msg.chat.id); return
    user_files[msg.from_user.id] = []
    bot.reply_to(msg, INSTRUCTION, parse_mode="Markdown", reply_markup=get_menu_keyboard())

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def check_sub_callback(call):
    if check_subscription(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ Открыт!")
        bot.edit_message_text("✅ Готово!", call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "❌ Не подписаны!", show_alert=True)
        send_subscription_message(call.message.chat.id)

@bot.message_handler(content_types=['document'])
def handle_file(msg):
    uid = msg.from_user.id
    if not check_subscription(uid): send_subscription_message(msg.chat.id); return
    file_info = bot.get_file(msg.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    fname = msg.document.file_name
    save_path = os.path.join(os.getcwd(), fname)
    with open(save_path, 'wb') as f: f.write(downloaded)
    if uid not in user_files: user_files[uid] = []
    user_files[uid].append(save_path)
    info = analyze_file(save_path)
    a = ""
    if info: a = f"\n\n📊 {info['verts']} вершин | {info['faces']} полигонов | {info['verdict']}"
    bot.reply_to(msg, f"📁 {fname}{a}", reply_markup=get_menu_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "🔍 Анализ")
def analyze_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]: bot.reply_to(msg, "Нет файлов."); return
    for fp in user_files[uid]:
        if not os.path.exists(fp): continue
        info = analyze_file(fp)
        if info:
            text = f"📊 {os.path.basename(fp)}\n\nВершин: {info['verts']}\nПолигонов: {info['faces']}\nUV: {info['uvs']}\nРазмер: {info['size_kb']} КБ"
            bot.reply_to(msg, text)

@bot.message_handler(func=lambda msg: msg.text == "🚗 Повредить")
def damage_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]:
        bot.reply_to(msg, INSTRUCTION, parse_mode="Markdown"); return
    process_damage(uid, msg.chat.id)

@bot.message_handler(func=lambda msg: msg.text == "📄 Создать XML")
def xml_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]: bot.reply_to(msg, "Нет файлов."); return
    obj_file = None
    png_names = []
    for fp in user_files[uid]:
        ext = Path(fp).suffix.lower()
        if ext == '.obj': obj_file = fp
        elif ext == '.png': png_names.append(Path(fp).stem)
    if not obj_file: bot.reply_to(msg, "❌ Нужен .obj"); return
    xml_path = converter.generate_xml(Path(obj_file).stem, os.path.basename(obj_file), png_names)
    with open(xml_path, 'rb') as f: bot.send_document(uid, f, caption="XML")
    user_files[uid] = []
    bot.send_message(uid, "✅ XML создан!", reply_markup=get_menu_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "🆘 Техподдержка")
def support_cmd(msg):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📩 Написать в ЛС", url=f"https://t.me/{SUPPORT_USERNAME.replace('@', '')}"))
    bot.reply_to(msg, f"По вопросам: {SUPPORT_USERNAME}", reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text == "📋 Список")
def list_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]: bot.reply_to(msg, "Пусто."); return
    text = "📁 Файлы:\n"
    for f in user_files[uid]:
        if os.path.exists(f): text += f"• {os.path.basename(f)}\n"
    bot.reply_to(msg, text or "Пусто.")

@bot.message_handler(func=lambda msg: msg.text == "🗑 Очистить")
def clear_cmd(msg):
    uid = msg.from_user.id
    if uid in user_files:
        for f in user_files[uid]:
            if os.path.exists(f): os.remove(f)
        user_files[uid] = []
    bot.reply_to(msg, "🗑 Очищено.")

@bot.message_handler(func=lambda msg: True)
def any_msg(msg):
    uid = msg.from_user.id
    if not check_subscription(uid): send_subscription_message(msg.chat.id); return
    text = msg.text.lower()
    if any(w in text for w in ['помни', 'повреди', 'вмятина', 'дверь', 'двери']):
        if uid not in user_files or not user_files[uid]:
            bot.reply_to(msg, INSTRUCTION, parse_mode="Markdown"); return
        process_damage(uid, msg.chat.id)
        return
    bot.reply_to(msg, "💬 Используйте меню.", reply_markup=get_menu_keyboard())

print("[>] Бот запущен")
bot.polling()
