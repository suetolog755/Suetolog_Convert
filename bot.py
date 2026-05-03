import os
import json
import struct
import random
import shutil
import io
from pathlib import Path
from PIL import Image
import telebot
from telebot import types

TOKEN = "8613630902:AAG40R1_fFUUvS1a8VFFf1WaWSCc9mFf1lQ"
CHANNEL_ID = "@brmodels095"
CHANNEL_URL = "https://t.me/brmodels095"

bot = telebot.TeleBot(TOKEN)
user_files = {}

def analyze_file(file_path):
    try:
        ext = Path(file_path).suffix.lower()
        size_kb = os.path.getsize(file_path) // 1024
        verts, faces = 0, 0
        
        if ext == '.obj':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if line.startswith('v '): verts += 1
                    elif line.startswith('f '): faces += 1
        elif ext == '.dff':
            try:
                with open(file_path, 'rb') as f:
                    data = f.read()
                idx = 0
                while idx < len(data) - 4:
                    if data[idx] == 0x0F and data[idx+1] == 0x00:
                        verts = struct.unpack_from('<I', data, idx+4)[0]
                        faces = struct.unpack_from('<I', data, idx+8)[0]
                        break
                    idx += 1
            except: pass

        if verts > 65535: verdict = "Очень много вершин"
        elif verts > 40000: verdict = "Тяжелая модель"
        else: verdict = "Хорошая модель"
        
        return {'ext': ext, 'verts': verts, 'faces': faces, 'verdict': verdict}
    except: return None


class FullModelConverter:
    def __init__(self):
        self.output_dir = Path("converted_output")
        self.output_dir.mkdir(exist_ok=True, parents=True)

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

    def damage_obj(self, obj_path, intensity=0.05):
        """Создаёт локальные вмятины на детали (дверь, крыло и т.д.)"""
        lines = []
        with open(obj_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        verts = []
        for i, line in enumerate(lines):
            if line.startswith('v '):
                parts = line.strip().split()
                verts.append({'idx': i, 'x': float(parts[1]), 'y': float(parts[2]), 'z': float(parts[3])})
        
        if not verts:
            return None
        
        xs = [v['x'] for v in verts]
        ys = [v['y'] for v in verts]
        zs = [v['z'] for v in verts]
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
        depth = max(zs) - min(zs)
        
        num_dents = random.randint(2, 6)
        
        for _ in range(num_dents):
            cx = random.uniform(min(xs), max(xs))
            cy = random.uniform(min(ys), max(ys))
            cz = random.uniform(min(zs), max(zs))
            radius = random.uniform(0.15, 0.3) * max(width, height)
            
            for v in verts:
                dist = ((v['x']-cx)**2 + (v['y']-cy)**2 + (v['z']-cz)**2)**0.5
                if dist < radius:
                    force = (1 - dist/radius) * intensity * random.uniform(0.5, 1.5)
                    if width >= height and width >= depth:
                        lines[v['idx']] = f"v {v['x'] - force if v['x'] > 0 else v['x'] + force:.6f} {v['y']:.6f} {v['z']:.6f}\n"
                    elif height >= depth:
                        lines[v['idx']] = f"v {v['x']:.6f} {v['y'] - force:.6f} {v['z']:.6f}\n"
                    else:
                        lines[v['idx']] = f"v {v['x']:.6f} {v['y']:.6f} {v['z'] - force:.6f}\n"
        
        out_path = self.output_dir / f"{Path(obj_path).stem}_damaged.obj"
        with open(out_path, 'w') as f:
            f.writelines(lines)
        return out_path

    def generate_xml(self, car_name, obj_name, texture_names):
        xml = '<?xml version="1.0" encoding="utf-8"?>\n'
        xml += f'<Car name="{car_name}">\n  <Case>\n    <Render object="{obj_name}">\n'
        for tex in texture_names:
            xml += f'      <Texture name="{tex}"/>\n'
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
        types.KeyboardButton("📋 Список"),
        types.KeyboardButton("🗑 Очистить"),
        types.KeyboardButton("🔍 Анализ")
    )
    return markup

@bot.message_handler(commands=['start'])
def start(msg):
    if not check_subscription(msg.from_user.id): send_subscription_message(msg.chat.id); return
    user_files[msg.from_user.id] = []
    bot.reply_to(msg, (
        "🔧 *Бот для модов BR*\n\n"
        "🎨 PNG → BTX\n"
        "🚗 Повредить деталь (.obj)\n"
        "📄 Создать XML\n\n"
        "💬 Напиши «помни» после отправки .obj файла детали\n\n"
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
    if info: a = f"\n\n{info['verts']} вершин | {info['faces']} полигонов"
    bot.reply_to(msg, f"📁 {fname}{a}", reply_markup=get_menu_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "🔍 Анализ")
def analyze_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]: bot.reply_to(msg, "Нет файлов."); return
    for fp in user_files[uid]:
        info = analyze_file(fp)
        if info: bot.reply_to(msg, f"📊 {os.path.basename(fp)}\nВершин: {info['verts']}\nПолигонов: {info['faces']}")

@bot.message_handler(func=lambda msg: msg.text == "✅ Конвертировать")
def convert_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]: bot.reply_to(msg, "Нет файлов."); return
    for fp in user_files[uid].copy():
        try:
            ext = Path(fp).suffix.lower()
            if ext == '.png':
                btx = converter._png_to_btx(fp)
                if btx: 
                    with open(btx, 'rb') as f: bot.send_document(uid, f, caption="BTX")
            elif ext in ['.obj', '.dff']:
                with open(fp, 'rb') as f: bot.send_document(uid, f, caption=ext.upper())
        except Exception as e: bot.send_message(uid, f"Ошибка: {e}")
    bot.send_message(uid, "✅ Готово!", reply_markup=get_menu_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "🚗 Повредить")
def damage_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]: 
        bot.reply_to(msg, "Нет файлов. Отправьте .obj файл детали."); return
    
    for fp in user_files[uid].copy():
        ext = Path(fp).suffix.lower()
        if ext != '.obj': continue
        try:
            damaged = converter.damage_obj(fp)
            if damaged:
                with open(damaged, 'rb') as f:
                    bot.send_document(uid, f, caption="🚗 Повреждено")
        except Exception as e: 
            bot.send_message(uid, f"Ошибка: {e}")
    bot.send_message(uid, "✅ Готово!", reply_markup=get_menu_keyboard())

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
    bot.send_message(uid, "✅ Готово!", reply_markup=get_menu_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "📋 Список")
def list_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]: bot.reply_to(msg, "Пусто."); return
    text = "\n".join([f"• {os.path.basename(f)}" for f in user_files[uid] if os.path.exists(f)])
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
            bot.reply_to(msg, "Сначала отправьте .obj файл детали."); return
        
        for fp in user_files[uid].copy():
            ext = Path(fp).suffix.lower()
            if ext != '.obj': continue
            try:
                damaged = converter.damage_obj(fp)
                if damaged:
                    with open(damaged, 'rb') as f:
                        bot.send_document(uid, f, caption="🚗 Повреждённая деталь")
            except Exception as e:
                bot.send_message(uid, f"Ошибка: {e}")
        return
    
    bot.reply_to(msg, "💬 Отправьте .obj файл детали и напишите «помни»\nИли используйте меню.", reply_markup=get_menu_keyboard())

print("[>] Бот запущен")
bot.polling()
