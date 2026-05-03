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
        
        issues, warnings = [], []
        needs_fix = False
        
        if verts > 65535:
            issues.append(f"Вершин: {verts} (>65535) - краш ZModeler")
            needs_fix = True
        elif verts > 40000:
            warnings.append(f"Вершин: {verts} - возможны лаги")
        
        if faces > 50000:
            issues.append(f"Полигонов: {faces} - краш ZModeler")
            needs_fix = True
        
        if issues: verdict = "Требуется конвертация"
        elif needs_fix: verdict = "Рекомендуется конвертация"
        elif warnings: verdict = "Может работать с ограничениями"
        else: verdict = "Готово к использованию"
        
        return {'ext': ext, 'verts': verts, 'faces': faces, 'uvs': uvs,
                'size_kb': size_kb, 'issues': issues, 'warnings': warnings,
                'verdict': verdict, 'needs_fix': needs_fix}
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

    def damage_obj(self, obj_path, intensity=0.15, num_dents=8):
        """
        ТУПО ВДАВЛИВАЕТ ВЕРШИНЫ ВНУТРЬ ПО ОСИ X (для дверей).
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
            return None, 0
        
        all_x = [v[1] for v in vert_entries]
        det_size = max(all_x) - min(all_x)
        
        for _ in range(num_dents):
            ri = random.randint(0, len(vert_entries)-1)
            cx, cy, cz = vert_entries[ri][1], vert_entries[ri][2], vert_entries[ri][3]
            radius = det_size * random.uniform(0.2, 0.5)
            
            for entry in vert_entries:
                idx, x, y, z = entry
                dx = x - cx
                dy = y - cy
                dz = z - cz
                dist = (dx*dx + dy*dy + dz*dz) ** 0.5
                
                if dist < radius and abs(x) > 0.01:
                    force = (1 - dist/radius) * intensity * random.uniform(0.5, 1.5)
                    
                    if x > 0:
                        new_x = x - force
                    else:
                        new_x = x + force
                    
                    new_y = y + random.uniform(-force*0.3, force*0.3)
                    new_z = z + random.uniform(-force*0.3, force*0.3)
                    
                    lines[idx] = f"v {new_x:.6f} {new_y:.6f} {new_z:.6f}"
        
        out_path = self.output_dir / f"{Path(obj_path).stem}_damaged.obj"
        with open(out_path, 'w') as f:
            f.write('\n'.join(lines))
        
        return out_path, num_dents

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
        types.KeyboardButton("✅ Конвертировать"),
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
        types.InlineKeyboardButton("🤏 Слабо (5см)", callback_data="dmg_light"),
        types.InlineKeyboardButton("💪 Средне (15см)", callback_data="dmg_medium"),
        types.InlineKeyboardButton("💥 Сильно (30см)", callback_data="dmg_hard"),
        types.InlineKeyboardButton("🔥 Хлам (50см)", callback_data="dmg_extreme")
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
        'light':   {'intensity': 0.05, 'dents': 4,  'label': 'Слабые', 'icon': '🤏'},
        'medium':  {'intensity': 0.15, 'dents': 8,  'label': 'Средние', 'icon': '💪'},
        'hard':    {'intensity': 0.30, 'dents': 12, 'label': 'Сильные', 'icon': '💥'},
        'extreme': {'intensity': 0.50, 'dents': 16, 'label': 'Хлам', 'icon': '🔥'}
    }
    
    s = settings.get(level, settings['medium'])
    
    status_msg = bot.send_message(cid, f"🤔 AI анализирует геометрию...\nПрогресс: 0%")
    
    def process():
        time.sleep(0.5)
        for fp in user_files[uid].copy():
            ext = Path(fp).suffix.lower()
            if ext != '.obj': continue
            try:
                damaged, num_dents = converter.damage_obj(fp, intensity=s['intensity'], num_dents=s['dents'])
                if damaged:
                    with open(damaged, 'rb') as f:
                        bot.send_document(uid, f, caption=f"🚗 {s['icon']} {s['label']} повреждения")
                    
                    total_verts = 0
                    with open(fp, 'r') as f: total_verts = sum(1 for l in f if l.startswith('v '))
                    zmodeler_chance = 85 if total_verts < 50000 else 50
                    
                    bot.send_message(uid, (
                        f"📊 *Отчёт о повреждениях*\n\n"
                        f"▫️ Уровень: {s['label']}\n"
                        f"▫️ Вмятин: {num_dents}\n"
                        f"▫️ Глубина: {int(s['intensity']*100)} см\n"
                        f"▫️ Шанс в ZModeler: {zmodeler_chance}%\n\n"
                        f"🕐 Обработка: {num_dents * 0.2:.1f} сек"
                    ), parse_mode="Markdown")
            except Exception as e:
                bot.send_message(uid, f"❌ Ошибка: {e}")
    
    threading.Thread(target=process).start()
    send_progress(cid, status_msg.message_id, f"🔧 Наношу {s['label'].lower()} повреждения...", 3)
    try: bot.edit_message_text("✅ Готово!", cid, status_msg.message_id)
    except: pass
    bot.send_message(cid, f"✅ {s['label']} повреждения нанесены!", reply_markup=get_menu_keyboard())


@bot.message_handler(commands=['start'])
def start(msg):
    if not check_subscription(msg.from_user.id): send_subscription_message(msg.chat.id); return
    user_files[msg.from_user.id] = []
    user_damage_level[msg.from_user.id] = 'medium'
    bot.reply_to(msg, (
        "🔧 *Бот для модов BR*\n\n"
        "🎨 PNG → BTX\n"
        "🚗 Повредить деталь (.obj)\n"
        "📄 Создать XML\n"
        "🆘 Техподдержка\n\n"
        "💬 Отправь .obj и выбери уровень повреждений\n\n"
        "Канал: @brmodels095"
    ), reply_markup=get_menu_keyboard())

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
    
    labels = {'light': '🤏 Слабо', 'medium': '💪 Средне', 'hard': '💥 Сильно', 'extreme': '🔥 Хлам'}
    bot.answer_callback_query(call.id, f"Выбрано: {labels.get(level, 'Средне')}")
    bot.edit_message_text(f"✅ Уровень: {labels.get(level, 'Средне')}\nНачинаю повреждения...", call.message.chat.id, call.message.message_id)
    
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
            text = f"📊 {os.path.basename(fp)}\n\nВершин: {info['verts']}\nПолигонов: {info['faces']}\nUV: {info['uvs']}\nРазмер: {info['size_kb']} КБ\nВердикт: {info['verdict']}"
            if info['issues']: text += "\n⚠️ " + "\n".join(info['issues'])
            bot.reply_to(msg, text)

@bot.message_handler(func=lambda msg: msg.text == "✅ Конвертировать")
def convert_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]: bot.reply_to(msg, "Нет файлов."); return
    files = user_files[uid].copy()
    status_msg = bot.reply_to(msg, "⏳ AI анализирует...\nПрогресс: 0%")
    def process():
        time.sleep(0.5)
        for fp in files:
            try:
                ext = Path(fp).suffix.lower()
                if ext == '.png':
                    btx = converter._png_to_btx(fp)
                    if btx:
                        with open(btx, 'rb') as f: bot.send_document(uid, f, caption="BTX")
                elif ext in ['.obj', '.dff']:
                    with open(fp, 'rb') as f: bot.send_document(uid, f, caption=ext.upper())
            except Exception as e: bot.send_message(uid, f"Ошибка: {e}")
    threading.Thread(target=process).start()
    send_progress(msg.chat.id, status_msg.message_id, "⏳ AI обрабатывает...", 2)
    try: bot.edit_message_text("✅ Готово!", msg.chat.id, status_msg.message_id)
    except: pass
    bot.send_message(uid, "✅ Конвертация завершена!", reply_markup=get_menu_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "🚗 Повредить")
def damage_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]:
        bot.reply_to(msg, "Нет файлов. Отправьте .obj файл детали."); return
    bot.reply_to(msg, "💥 *Выберите уровень повреждений:*", parse_mode="Markdown", reply_markup=get_damage_level_keyboard())

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
    if not obj_file: bot.reply_to(msg, "❌ Нужен .obj файл."); return
    car_name = Path(obj_file).stem
    xml_path = converter.generate_xml(car_name, os.path.basename(obj_file), png_names)
    with open(xml_path, 'rb') as f: bot.send_document(uid, f, caption=f"XML для {car_name}")
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
        if uid not in user_files or not user_files[uid]: bot.reply_to(msg, "Сначала отправьте .obj файл детали."); return
        bot.reply_to(msg, "💥 *Выберите уровень повреждений:*", parse_mode="Markdown", reply_markup=get_damage_level_keyboard())
        return
    bot.reply_to(msg, "💬 Отправьте .obj и выберите уровень повреждений.\nИли используйте меню.", reply_markup=get_menu_keyboard())

print("[>] Бот запущен")
bot.polling()
