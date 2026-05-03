import os
import json
import struct
import shutil
import zipfile
import io
import xml.etree.ElementTree as ET
import requests
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
        verts, faces, uvs = 0, 0, 0
        
        if ext == '.obj':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if line.startswith('v '): verts += 1
                    elif line.startswith('vt '): uvs += 1
                    elif line.startswith('f '): faces += 1
        
        elif ext == '.dae':
            try:
                tree = ET.parse(file_path)
                root = tree.getroot()
                ns = 'http://www.collada.org/2005/11/COLLADASchema'
                for mesh in root.iter(f'{{{ns}}}mesh'):
                    for source in mesh.findall(f'{{{ns}}}source'):
                        if 'positions' in source.get('id', ''):
                            fa = source.find(f'{{{ns}}}float_array')
                            if fa is not None and fa.text:
                                verts += len(fa.text.strip().split()) // 3
                    for tag_name in ['triangles', 'polylist', 'polygons']:
                        for elem in mesh.findall(f'{{{ns}}}{tag_name}'):
                            p_elems = elem.findall(f'{{{ns}}}p')
                            if p_elems and p_elems[0].text:
                                faces += len(p_elems[0].text.strip().split()) // 3
            except: pass
        
        issues, warnings = [], []
        import_support = "Поддерживается"
        needs_fix = False
        
        if ext == '.dae':
            import_support = "Не поддерживается"
            needs_fix = True
        
        if verts > 65535:
            issues.append(f"Вершин: {verts} (>65535) — краш ZModeler")
            needs_fix = True
        elif verts > 40000:
            warnings.append(f"Вершин: {verts} — возможны лаги")
        
        if faces > 50000:
            issues.append(f"Полигонов: {faces} (>50000) — краш ZModeler")
            needs_fix = True
        
        if size_kb > 10000:
            warnings.append(f"Размер: {size_kb} КБ")
        
        if issues: verdict = "Требуется конвертация"
        elif needs_fix: verdict = "Рекомендуется конвертация"
        elif warnings: verdict = "Может работать с ограничениями"
        else: verdict = "Не нуждается в конвертации"
        
        return {'ext': ext, 'verts': verts, 'faces': faces, 'uvs': uvs,
                'size_kb': size_kb, 'issues': issues, 'warnings': warnings,
                'verdict': verdict, 'import_support': import_support, 'needs_fix': needs_fix}
    except: return None


class FullModelConverter:
    def __init__(self):
        self.output_dir = Path("converted_output")
        self.temp_dir = Path("temp_processing")
        self.output_dir.mkdir(exist_ok=True, parents=True)
        self.temp_dir.mkdir(exist_ok=True, parents=True)

    def _clean_temp(self):
        if self.temp_dir.exists(): shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir.mkdir(exist_ok=True, parents=True)

    def _simplify_model(self, vertices, uvs, faces, max_verts=60000):
        if len(vertices) <= max_verts: return vertices, uvs, faces
        step = len(vertices) / max_verts
        old_to_new, new_vertices, new_uvs = {}, [], []
        i = 0.0
        while i < len(vertices):
            idx = int(i)
            old_to_new[idx] = len(new_vertices)
            new_vertices.append(vertices[idx])
            if idx < len(uvs): new_uvs.append(uvs[idx])
            i += step
        new_faces = [ [old_to_new[v] for v in face] for face in faces if all(v in old_to_new for v in face) ]
        return new_vertices, new_uvs, new_faces

    def _obj_simplify(self, obj_path):
        vertices, uvs, faces = [], [], []
        with open(obj_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if line.startswith('v '):
                    parts = line.strip().split()
                    vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
                elif line.startswith('vt '):
                    parts = line.strip().split()
                    uvs.append([float(parts[1]), float(parts[2])])
                elif line.startswith('f '):
                    parts = line.strip().split()
                    face = [int(p.split('/')[0]) - 1 for p in parts[1:]]
                    if len(face) == 3: faces.append(face)
        if not vertices: return None
        
        if len(faces) > 50000:
            ratio = 50000 / len(faces)
            target = max(3000, int(len(vertices) * ratio))
            vertices, uvs, faces = self._simplify_model(vertices, uvs, faces, target)
        elif len(vertices) > 60000:
            vertices, uvs, faces = self._simplify_model(vertices, uvs, faces, 60000)
        else: return None
        
        while len(uvs) < len(vertices): uvs.append([0.0, 0.0])
        out = self.output_dir / Path(obj_path).name
        with open(out, 'w') as f:
            for v in vertices: f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            for vt in uvs: f.write(f"vt {vt[0]:.6f} {vt[1]:.6f}\n")
            for fc in faces: f.write(f"f {fc[0]+1} {fc[1]+1} {fc[2]+1}\n")
        return out

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

    def obj_to_dff_cloud(self, obj_path):
        try:
            api_url = "https://api.sketchfab.com/v3/conversions"
            files = {'file': open(obj_path, 'rb')}
            data = {'outputFormat': 'dff'}
            response = requests.post(api_url, files=files, data=data, timeout=60)
            if response.status_code == 200:
                dff_url = response.json().get('url')
                if dff_url:
                    dff_data = requests.get(dff_url).content
                    dff_path = self.output_dir / f"{Path(obj_path).stem}.dff"
                    with open(dff_path, 'wb') as f: f.write(dff_data)
                    return dff_path
            return None
        except: return None

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
    bot.send_message(chat_id, "🔒 Подпишитесь чтобы пользоваться ботом\n\n" + CHANNEL_URL, reply_markup=markup)

def get_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("✅ Конвертировать в OBJ"),
        types.KeyboardButton("✅ Конвертировать в DFF"),
        types.KeyboardButton("❌ Отменить"),
        types.KeyboardButton("📋 Список файлов"),
        types.KeyboardButton("🗑 Очистить"),
        types.KeyboardButton("🔍 Анализ файла")
    )
    return markup

@bot.message_handler(commands=['start'])
def start(msg):
    if not check_subscription(msg.from_user.id): send_subscription_message(msg.chat.id); return
    user_files[msg.from_user.id] = []
    bot.reply_to(msg, (
        "Возможности:\n\n"
        "🎨 PNG → BTX\n"
        "📦 .dae → .obj (через trimesh)\n"
        "🧩 .obj → .obj (упрощённый)\n"
        "🚀 .obj → .dff (облачный конвертер)\n"
        "🔍 AI-анализ\n\n"
        "📂 Отправьте файл → выберите действие\n\n"
        "Канал: @brmodels095"
    ), reply_markup=get_menu_keyboard())

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def check_sub_callback(call):
    if check_subscription(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ Доступ открыт!")
        bot.edit_message_text("✅ Готово! Отправьте файл или /start", call.message.chat.id, call.message.message_id)
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
    analysis_text = ""
    if info:
        analysis_text = f"\n\nAI-анализ ({info['ext']}):\n• Вершин: {info['verts']}\n• Полигонов: {info['faces']}\n• Вердикт: {info['verdict']}"
    bot.reply_to(msg, f"Файл {fname} добавлен\nВсего: {len(user_files[uid])}{analysis_text}\n\nИспользуйте меню:", reply_markup=get_menu_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "🔍 Анализ файла")
def analyze_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]: bot.reply_to(msg, "Нет файлов.", reply_markup=get_menu_keyboard()); return
    for fpath in user_files[uid]:
        if not os.path.exists(fpath): continue
        info = analyze_file(fpath)
        if info:
            text = f"Анализ: {os.path.basename(fpath)}\n\n"
            if info['verts'] > 0: text += f"Вершин: {info['verts']}\nПолигонов: {info['faces']}\n"
            text += f"Вердикт: {info['verdict']}\n"
            text += "\nРекомендация: Нажми Конвертировать в OBJ или DFF."
            bot.reply_to(msg, text)

@bot.message_handler(func=lambda msg: msg.text == "✅ Конвертировать в OBJ")
def convert_obj_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]: bot.reply_to(msg, "Нет файлов.", reply_markup=get_menu_keyboard()); return
    files = list(user_files[uid])
    user_files[uid] = []
    for fpath in files:
        try:
            if not os.path.exists(fpath): continue
            fname = os.path.basename(fpath)
            info = analyze_file(fpath)
            ext = Path(fpath).suffix.lower()
            
            if ext == '.png':
                btx = converter._png_to_btx(fpath)
                if btx:
                    with open(btx, 'rb') as f: bot.send_document(uid, f, caption="BTX")
            
            elif ext == '.dae':
                bot.send_message(uid, "⏳ DAE → OBJ...")
                try:
                    import trimesh
                    import numpy as np
                    
                    mesh = trimesh.load(fpath, force='mesh')
                    if isinstance(mesh, trimesh.Scene):
                        combined = trimesh.util.concatenate(list(mesh.geometry.values()))
                        obj_path = converter.output_dir / f"{Path(fpath).stem}.obj"
                        combined.export(str(obj_path))
                    else:
                        obj_path = converter.output_dir / f"{Path(fpath).stem}.obj"
                        mesh.export(str(obj_path))
                    
                    with open(obj_path, 'rb') as f:
                        bot.send_document(uid, f, caption="OBJ (из DAE)")
                except Exception as e:
                    bot.send_message(uid, f"❌ Ошибка: {str(e)[:150]}")
            
            elif ext == '.obj':
                if info and info['needs_fix']:
                    simplified = converter._obj_simplify(fpath)
                    if simplified:
                        with open(simplified, 'rb') as f: bot.send_document(uid, f, caption="OBJ (упрощён)")
                    else: bot.send_message(uid, "✅ OBJ в порядке.")
                else:
                    with open(fpath, 'rb') as f: bot.send_document(uid, f, caption="OBJ")
        except Exception as e: bot.send_message(uid, f"Ошибка: {str(e)[:100]}")
    bot.send_message(uid, "Готово!", reply_markup=get_menu_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "✅ Конвертировать в DFF")
def convert_dff_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]: bot.reply_to(msg, "Нет файлов.", reply_markup=get_menu_keyboard()); return
    files = list(user_files[uid])
    user_files[uid] = []
    for fpath in files:
        try:
            if not os.path.exists(fpath): continue
            fname = os.path.basename(fpath)
            ext = Path(fpath).suffix.lower()
            
            if ext == '.obj':
                bot.send_message(uid, "⏳ OBJ → DFF через облачный конвертер...")
                dff_path = converter.obj_to_dff_cloud(fpath)
                if dff_path:
                    with open(dff_path, 'rb') as f: bot.send_document(uid, f, caption="DFF (готово)")
                else:
                    bot.send_message(uid, "❌ Не удалось. Попробуйте упростить модель сначала (Конвертировать в OBJ).")
            else:
                bot.send_message(uid, "❌ DFF можно сделать только из .obj файла.")
        except Exception as e: bot.send_message(uid, f"Ошибка: {str(e)[:100]}")
    bot.send_message(uid, "Готово!", reply_markup=get_menu_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "❌ Отменить")
def cancel_cmd(msg):
    uid = msg.from_user.id
    if uid in user_files:
        for f in user_files[uid]:
            if os.path.exists(f): os.remove(f)
        user_files[uid] = []
    bot.reply_to(msg, "Удалено.", reply_markup=get_menu_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "📋 Список файлов")
def list_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]: bot.reply_to(msg, "Пусто."); return
    text = "Файлы:\n"
    for f in user_files[uid]:
        if os.path.exists(f): text += f"• {os.path.basename(f)}\n"
    bot.reply_to(msg, text)

@bot.message_handler(func=lambda msg: msg.text == "🗑 Очистить")
def clear_cmd(msg):
    uid = msg.from_user.id
    if uid in user_files:
        for f in user_files[uid]:
            if os.path.exists(f): os.remove(f)
        user_files[uid] = []
    bot.reply_to(msg, "Очищено.")

@bot.message_handler(func=lambda msg: True)
def any_msg(msg):
    if not check_subscription(msg.from_user.id): send_subscription_message(msg.chat.id); return
    bot.reply_to(msg, "Используйте меню.", reply_markup=get_menu_keyboard())

print("[>] Бот запущен")
bot.polling()
