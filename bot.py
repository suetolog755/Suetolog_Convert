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
user_damage_level = {}

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

    def damage_obj(self, obj_path, intensity=0.15, num_dents=6):
        """
        Вмятины. Одна большая + несколько мелких.
        Края НЕ задеваются (отступ 25%).
        Глубина средних: 15 см.
        """
        with open(obj_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.read().split('\n')
        
        vert_entries = []
        for i, line in enumerate(lines):
            if line.startswith('v ') and not line.startswith('vt ') and not line.startswith('vn '):
                parts = line.strip().split()
                if len(parts) >= 4:
                    try:
                        vert_entries.append([i, float(parts[1]), float(parts[2]), float(parts[3])])
                    except: pass
        
        if len(vert_entries) < 10:
            return None, 0, 0
        
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
        
        if size_x >= size_y and size_x >= size_z: push_axis = 'x'
        elif size_y >= size_z: push_axis = 'y'
        else: push_axis = 'z'
        
        edge = 0.25
        
        def is_edge(x, y, z):
            return (
                abs(x - min_x) < size_x * edge or abs(x - max_x) < size_x * edge or
                abs(y - min_y) < size_y * edge or abs(y - max_y) < size_y * edge or
                abs(z - min_z) < size_z * edge or abs(z - max_z) < size_z * edge
            )
        
        main_radius = max(size_x, size_y, size_z) * random.uniform(0.5, 0.7)
        main_damaged = 0
        
        for entry in vert_entries:
            idx, x, y, z = entry
            dx = x - mid_x; dy = y - mid_y; dz = z - mid_z
            dist = (dx*dx + dy*dy + dz*dz) ** 0.5
            
            if dist < main_radius and not is_edge(x, y, z):
                force = (1 - dist/main_radius) * intensity * random.uniform(0.8, 1.3)
                self._push_vertex(lines, idx, x, y, z, force, push_axis)
                main_damaged += 1
        
        for _ in range(num_dents):
            cx = random.uniform(min_x + size_x*edge, max_x - size_x*edge)
            cy = random.uniform(min_y + size_y*edge, max_y - size_y*edge)
            cz = random.uniform(min_z + size_z*edge, max_z - size_z*edge)
            small_radius = max(size_x, size_y, size_z) * random.uniform(0.08, 0.18)
            
            for entry in vert_entries:
                idx, x, y, z = entry
                dx = x - cx; dy = y - cy; dz = z - cz
                dist = (dx*dx + dy*dy + dz*dz) ** 0.5
                
                if dist < small_radius and not is_edge(x, y, z):
                    force = (1 - dist/small_radius) * intensity * 0.5 * random.uniform(0.5, 1.5)
                    self._push_vertex(lines, idx, x, y, z, force, push_axis)
        
        out_path = self.output_dir / f"{Path(obj_path).stem}_damaged.obj"
        with open(out_path, 'w') as f:
            f.write('\n'.join(lines))
        
        return out_path, 1 + num_dents, main_damaged
    
    def _push_vertex(self, lines, idx, x, y, z, force, axis):
        new_x, new_y, new_z = x, y, z
        if axis == 'x':
            new_x = x - force if x > 0 else x + force
            new_y = y + random.uniform(-force*0.4, force*0.4)
            new_z = z + random.uniform(-force*0.4, force*0.4)
        elif axis == 'y':
            new_y = y - force
            new_x = x + random.uniform(-force*0.4, force*0.4)
            new_z = z + random.uniform(-force*0.4, force*0.4)
        else:
            new_z = z - force
            new_x = x + random.uniform(-force*0.4, force*0.4)
            new_y = y + random.uniform(-force*0.4, force*0.4)
        lines[idx] = f"v {new_x:.6f} {new_y:.6f} {new_z:.6f}"

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
        types.KeyboardButton("🎨 Конвертировать"),
        types.KeyboardButton("🚗 Повредить"),
        types.KeyboardButton("📄 Создать XML"),
        types.KeyboardButton("🆘 Техподдержка"),
        types.KeyboardButton("📋 Список"),
        types.KeyboardButton("🗑 Очистить"),
        types.KeyboardButton("🔍 Анализ")
    )
    return markup

def get_damage_level_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🤏 Мелкие царапины (5см)", callback_data="dmg_light"),
        types.InlineKeyboardButton("💪 Средние вмятины (15см)", callback_data="dmg_medium"),
        types.InlineKeyboardButton("💥 Сильная авария (30см)", callback_data="dmg_hard"),
        types.InlineKeyboardButton("🔥 Полный хлам (50см)", callback_data="dmg_extreme")
    )
    return markup

def send_progress(chat_id, message_id, text, duration=3):
    steps = [10, 25, 40, 55, 70, 85, 95, 100]
    for p in steps:
        try: bot.edit_message_text(f"{text}\nПрогресс: {p}%", chat_id, message_id)
        except: pass
        time.sleep(duration / len(steps))

def process_damage(uid, cid, level='medium'):
    if uid not in user_files or not user_files[uid]:
        bot.send_message(cid, "❌ Нет файлов."); return
    
    settings = {
        'light':   {'intensity': 0.05, 'dents': 4,  'label': 'Мелкие царапины (5см)', 'icon': '🤏'},
        'medium':  {'intensity': 0.15, 'dents': 6,  'label': 'Средние вмятины (15см)', 'icon': '💪'},
        'hard':    {'intensity': 0.30, 'dents': 10, 'label': 'Сильная авария (30см)', 'icon': '💥'},
        'extreme': {'intensity': 0.50, 'dents': 14, 'label': 'Полный хлам (50см)', 'icon': '🔥'}
    }
    
    s = settings.get(level, settings['medium'])
    
    status_msg = bot.send_message(cid, f"🤔 Анализирую геометрию...\nПрогресс: 0%")
    
    def process():
        time.sleep(0.5)
        for fp in user_files[uid].copy():
            ext = Path(fp).suffix.lower()
            if ext != '.obj': continue
            try:
                damaged, total_dents, main_verts = converter.damage_obj(fp, intensity=s['intensity'], num_dents=s['dents'])
                if damaged:
                    with open(damaged, 'rb') as f:
                        bot.send_document(uid, f, caption=f"🚗 {s['icon']} {s['label']}")
                    
                    bot.send_message(uid, (
                        f"📊 *Отчёт о повреждениях*\n\n"
                        f"▫️ Уровень: {s['label']}\n"
                        f"▫️ Основная вмятина: 1 (центр)\n"
                        f"▫️ Мелких вмятин: {s['dents']}\n"
                        f"▫️ Задето вершин: ~{main_verts}\n"
                        f"▫️ Края: НЕ задеты\n\n"
                        f"📁 *Файл:* `{Path(damaged).name}`\n\n"
                        f"💡 ZModeler → Export .dff → готово"
                    ), parse_mode="Markdown")
            except Exception as e:
                bot.send_message(uid, f"❌ Ошибка: {e}")
    
    threading.Thread(target=process).start()
    send_progress(cid, status_msg.message_id, f"🔧 Наношу {s['label'].lower()}...", 3)
    try: bot.edit_message_text("✅ Готово!", cid, status_msg.message_id)
    except: pass
    bot.send_message(cid, f"✅ Готово!", reply_markup=get_menu_keyboard())

INSTRUCTION = (
    "🔧 *Бот для модов Black Russia*\n\n"
    "🎨 *Конвертировать:*\n"
    "• PNG → BTX (сжатый, 512x512)\n\n"
    "🚗 *Повредить:*\n"
    "• Отправьте .obj детали\n"
    "• Выберите уровень:\n"
    "   🤏 Мелкие царапины (5см)\n"
    "   💪 Средние вмятины (15см)\n"
    "   💥 Сильная авария (30см)\n"
    "   🔥 Полный хлам (50см)\n"
    "• Края НЕ задеваются\n\n"
    "📄 *Создать XML:*\n"
    "• Для упаковки мода в BR\n\n"
    "🆘 *Техподдержка:* @brmodels013\n\n"
    "📂 Отправьте файл и выберите действие"
)

@bot.message_handler(commands=['start'])
def start(msg):
    if not check_subscription(msg.from_user.id): send_subscription_message(msg.chat.id); return
    user_files[msg.from_user.id] = []
    user_damage_level[msg.from_user.id] = 'medium'
    bot.reply_to(msg, INSTRUCTION, parse_mode="Markdown", reply_markup=get_menu_keyboard())

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def check_sub_callback(call):
    if check_subscription(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ Открыт!")
        bot.edit_message_text("✅ Готово!", call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "❌ Не подписаны!", show_alert=True)
        send_subscription_message(call.message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("dmg_"))
def damage_level_callback(call):
    uid = call.from_user.id
    level = call.data.replace("dmg_", "")
    user_damage_level[uid] = level
    
    labels = {'light': '🤏 Мелкие (5см)', 'medium': '💪 Средние (15см)', 'hard': '💥 Авария (30см)', 'extreme': '🔥 Хлам (50см)'}
    bot.answer_callback_query(call.id, f"Выбрано: {labels.get(level, 'Средние')}")
    bot.edit_message_text(f"✅ {labels.get(level, 'Средние')}\nНачинаю...", call.message.chat.id, call.message.message_id)
    
    process_damage(uid, call.message.chat.id, level)

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
            text = f"📊 {os.path.basename(fp)}\n\nВершин: {info['verts']}\nПолигонов: {info['faces']}\nUV: {info['uvs']}\nРазмер: {info['size_kb']} КБ\n{info['verdict']}"
            bot.reply_to(msg, text)

@bot.message_handler(func=lambda msg: msg.text == "🎨 Конвертировать")
def convert_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]: 
        bot.reply_to(msg, "Нет файлов. Отправьте PNG."); return
    for fp in user_files[uid].copy():
        try:
            ext = Path(fp).suffix.lower()
            if ext == '.png':
                btx = converter._png_to_btx(fp)
                if btx:
                    with open(btx, 'rb') as f: 
                        bot.send_document(uid, f, caption="BTX")
        except Exception as e: 
            bot.send_message(uid, f"Ошибка: {e}")
    bot.send_message(uid, "✅ Готово!", reply_markup=get_menu_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "🚗 Повредить")
def damage_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]:
        bot.reply_to(msg, INSTRUCTION, parse_mode="Markdown"); return
    bot.reply_to(msg, "💥 *Выберите уровень:*", parse_mode="Markdown", reply_markup=get_damage_level_keyboard())

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
        bot.reply_to(msg, "💥 *Выберите уровень:*", parse_mode="Markdown", reply_markup=get_damage_level_keyboard())
        return
    bot.reply_to(msg, "💬 Используйте меню.", reply_markup=get_menu_keyboard())

print("[>] Бот запущен")
bot.polling()
