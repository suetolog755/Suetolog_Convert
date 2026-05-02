import os
import json
import struct
import shutil
import zipfile
import io
import xml.etree.ElementTree as ET
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
    """AI-анализ для ZModeler Android"""
    try:
        ext = Path(file_path).suffix.lower()
        size_kb = os.path.getsize(file_path) // 1024
        
        verts = 0
        faces = 0
        uvs = 0
        
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
                    for triangles in mesh.findall(f'{{{ns}}}triangles'):
                        p_elems = triangles.findall(f'{{{ns}}}p')
                        if p_elems and p_elems[0].text:
                            faces += len(p_elems[0].text.strip().split()) // 3
            except:
                pass
        
        issues = []
        warnings = []
        import_support = "Поддерживается"
        needs_fix = False
        
        if ext == '.dae':
            import_support = "Не поддерживается"
            needs_fix = True
        
        if verts > 0:
            if verts > 65535:
                issues.append(f"Вершин: {verts} (больше 65535) - краш ZModeler")
                needs_fix = True
            elif verts > 40000:
                warnings.append(f"Вершин: {verts} - возможны лаги")
        
        if faces > 50000:
            issues.append(f"Полигонов: {faces} - краш ZModeler")
            needs_fix = True
        
        if size_kb > 10000:
            warnings.append(f"Размер: {size_kb} КБ - может долго грузиться")
        
        if issues:
            verdict = "Требуется конвертация"
        elif needs_fix:
            verdict = "Рекомендуется конвертация"
        elif warnings:
            verdict = "Может работать с ограничениями"
        elif ext in ['.dff', '.3ds']:
            verdict = "Не нуждается в конвертации"
        elif verts > 0:
            verdict = "Не нуждается в конвертации"
        else:
            verdict = "Проанализирован"
        
        return {
            'ext': ext, 'verts': verts, 'faces': faces, 'uvs': uvs,
            'size_kb': size_kb, 'issues': issues, 'warnings': warnings,
            'verdict': verdict, 'import_support': import_support,
            'needs_fix': needs_fix
        }
    except:
        return None


def get_advisor_tips(info):
    tips = []
    ext = info['ext']
    verts = info['verts']
    
    if ext == '.dae':
        tips.append("ZModeler не открывает .dae. Нажми Конвертировать.")
    elif ext == '.dff':
        tips.append("DFF открывается в ZModeler.")
    elif ext == '.3ds':
        tips.append("3DS открывается. После импорта проверь текстуры.")
    elif ext == '.obj' and verts <= 65535:
        tips.append("Файл готов к импорту в ZModeler.")
    
    if verts > 65535:
        tips.append("Лимит 65K вершин. Нажми Конвертировать.")
    
    return tips


class FullModelConverter:
    def __init__(self):
        self.output_dir = Path("converted_output")
        self.temp_dir = Path("temp_processing")
        self.output_dir.mkdir(exist_ok=True)
        self.temp_dir.mkdir(exist_ok=True, parents=True)

    def _clean_temp(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir.mkdir(exist_ok=True, parents=True)

    def _simplify_model(self, vertices, uvs, faces, max_verts=60000):
        if len(vertices) <= max_verts:
            return vertices, uvs, faces
        
        step = len(vertices) / max_verts
        old_to_new = {}
        new_vertices = []
        new_uvs = []
        
        i = 0.0
        while i < len(vertices):
            idx = int(i)
            old_to_new[idx] = len(new_vertices)
            new_vertices.append(vertices[idx])
            if idx < len(uvs):
                new_uvs.append(uvs[idx])
            i += step
        
        new_faces = []
        for face in faces:
            if all(v in old_to_new for v in face):
                new_faces.append([old_to_new[v] for v in face])
        
        return new_vertices, new_uvs, new_faces

    def _dae_to_obj(self, dae_path):
        try:
            tree = ET.parse(dae_path)
            root = tree.getroot()
            ns = 'http://www.collada.org/2005/11/COLLADASchema'
            obj_path = self.temp_dir / f"{Path(dae_path).stem}.obj"
            vertices, uvs, faces = [], [], []
            
            for mesh in root.iter(f'{{{ns}}}mesh'):
                positions = None
                uvs_data = None
                
                for source in mesh.findall(f'{{{ns}}}source'):
                    sid = source.get('id', '')
                    float_array = source.find(f'{{{ns}}}float_array')
                    if float_array is not None and float_array.text:
                        data = list(map(float, float_array.text.strip().split()))
                        if 'positions' in sid:
                            positions = [[data[i], data[i+1], data[i+2]] for i in range(0, len(data), 3)]
                        elif 'map' in sid.lower() or 'uv' in sid.lower():
                            uvs_data = [[data[i], data[i+1]] for i in range(0, len(data), 2)]
                
                if positions:
                    start_idx = len(vertices)
                    vertices.extend(positions)
                    if uvs_data:
                        uvs.extend(uvs_data)
                    
                    for triangles in mesh.findall(f'{{{ns}}}triangles'):
                        p_elems = triangles.findall(f'{{{ns}}}p')
                        if p_elems and p_elems[0].text:
                            indices = list(map(int, p_elems[0].text.strip().split()))
                            for i in range(0, len(indices), 3):
                                if i + 2 < len(indices):
                                    faces.append([indices[i]+start_idx, indices[i+1]+start_idx, indices[i+2]+start_idx])

            if not vertices or not faces:
                return None

            vertices, uvs, faces = self._simplify_model(vertices, uvs, faces)
            
            while len(uvs) < len(vertices):
                uvs.append([0.0, 0.0])

            with open(obj_path, 'w') as f:
                for v in vertices:
                    f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
                for vt in uvs:
                    f.write(f"vt {vt[0]:.6f} {vt[1]:.6f}\n")
                for face in faces:
                    f.write(f"f {face[0]+1} {face[1]+1} {face[2]+1}\n")
            return obj_path
        except:
            return None

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
                    face = []
                    for p in parts[1:]:
                        idx = int(p.split('/')[0]) - 1
                        face.append(idx)
                    if len(face) == 3:
                        faces.append(face)
        
        if not vertices:
            return None
        
        vertices, uvs, faces = self._simplify_model(vertices, uvs, faces, 60000)
        
        while len(uvs) < len(vertices):
            uvs.append([0.0, 0.0])
        
        out_path = self.output_dir / Path(obj_path).name
        with open(out_path, 'w') as f:
            for v in vertices:
                f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            for vt in uvs:
                f.write(f"vt {vt[0]:.6f} {vt[1]:.6f}\n")
            for face in faces:
                f.write(f"f {face[0]+1} {face[1]+1} {face[2]+1}\n")
        return out_path

    def _png_to_btx(self, png_path, output_name=None):
        png_file = Path(png_path)
        if output_name is None:
            output_name = png_file.stem
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
            f.write(b'\x01')
            f.write(b'\x03')
            f.write(compressed.tobytes())
        return btx_path

    def _has_textures(self, folder):
        for img in Path(folder).rglob("*"):
            if img.suffix.lower() in ['.png', '.jpg', '.jpeg', '.tga', '.bmp', '.dds']:
                return True
        return False

    def _extract_textures_to_png(self, source_folder):
        tex_folder = self.temp_dir / "extracted_textures"
        tex_folder.mkdir(exist_ok=True)
        png_files = []
        for img in Path(source_folder).rglob("*"):
            if img.suffix.lower() in ['.png', '.jpg', '.jpeg', '.tga', '.bmp', '.dds']:
                try:
                    im = Image.open(img).convert("RGB")
                    png_path = tex_folder / f"{img.stem}.png"
                    im.save(png_path, "PNG")
                    png_files.append(png_path)
                except:
                    pass
        return png_files

    def _pack_to_zip(self, files, zip_name=None):
        if zip_name is None:
            zip_name = "textures"
        zip_path = self.output_dir / f"{zip_name}.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                zf.write(f, Path(f).name)
        return zip_path

    def dae_to_obj(self, dae_path):
        self._clean_temp()
        inp = Path(dae_path)
        obj_path = self._dae_to_obj(inp)
        if obj_path is None:
            return None, None
        final_obj = self.output_dir / obj_path.name
        shutil.copy(obj_path, final_obj)
        if self._has_textures(inp.parent):
            png_files = self._extract_textures_to_png(inp.parent)
            if png_files:
                zip_path = self._pack_to_zip(png_files, inp.stem)
                return final_obj, zip_path
        return final_obj, None


converter = FullModelConverter()


def check_subscription(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False


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
        types.KeyboardButton("✅ Конвертировать"),
        types.KeyboardButton("❌ Отменить"),
        types.KeyboardButton("📋 Список файлов"),
        types.KeyboardButton("🗑 Очистить"),
        types.KeyboardButton("🔍 Анализ файла")
    )
    return markup


@bot.message_handler(commands=['start'])
def start(msg):
    if not check_subscription(msg.from_user.id):
        send_subscription_message(msg.chat.id)
        return
    user_files[msg.from_user.id] = []
    bot.reply_to(msg, (
        "Возможности:\n\n"
        "🎨 PNG → BTX (сжатый, 512x512)\n"
        "📦 .dae → .obj (авто-упрощение)\n"
        "🧩 .obj → .obj (авто-упрощение)\n"
        "🔧 .dff → .obj (если нужна конвертация)\n"
        "🔧 .3ds → .obj (если нужна конвертация)\n"
        "🔍 AI-анализ + советы\n\n"
        "📂 Отправьте файл → ✅ Конвертировать\n\n"
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
    if not check_subscription(uid):
        send_subscription_message(msg.chat.id)
        return

    file_info = bot.get_file(msg.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    fname = msg.document.file_name

    save_path = os.path.join(os.getcwd(), fname)
    with open(save_path, 'wb') as f:
        f.write(downloaded)

    if uid not in user_files:
        user_files[uid] = []
    user_files[uid].append(save_path)

    info = analyze_file(save_path)
    analysis_text = ""
    if info:
        analysis_text = (
            f"\n\nAI-анализ ({info['ext']}):\n"
            f"• Вершин: {info['verts']}\n"
            f"• Полигонов: {info['faces']}\n"
            f"• Размер: {info['size_kb']} КБ\n"
            f"• Вердикт: {info['verdict']}"
        )

    bot.reply_to(msg,
        f"Файл {fname} добавлен\nВсего: {len(user_files[uid])}{analysis_text}\n\nИспользуйте меню:",
        reply_markup=get_menu_keyboard()
    )


@bot.message_handler(func=lambda msg: msg.text == "🔍 Анализ файла")
def analyze_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]:
        bot.reply_to(msg, "Нет файлов.", reply_markup=get_menu_keyboard())
        return

    for fpath in user_files[uid]:
        if not os.path.exists(fpath):
            continue
        info = analyze_file(fpath)
        if info:
            fname = os.path.basename(fpath)
            text = f"Анализ: {fname}\n\n"
            if info['verts'] > 0:
                text += f"Статистика:\n• Вершин: {info['verts']}\n• Полигонов: {info['faces']}\n"
            text += f"• Размер: {info['size_kb']} КБ\n"
            text += f"• Формат: {info['ext']}\n\n"
            text += f"Импорт в ZModeler: {info['import_support']}\n"
            text += f"Вердикт: {info['verdict']}\n"
            
            tips = get_advisor_tips(info)
            if tips:
                text += "\nСоветник:\n" + "\n".join(tips)
            if info['issues']:
                text += "\nПроблемы:\n" + "\n".join(info['issues'])
            
            text += "\n\nРекомендация:\n"
            if info['verdict'] == "Не нуждается в конвертации":
                text += "• Этот файл уже готов для ZModeler. Конвертация не требуется."
            elif info['needs_fix']:
                text += "• Нажми Конвертировать — бот исправит файл."
            
            bot.reply_to(msg, text)


@bot.message_handler(func=lambda msg: msg.text == "✅ Конвертировать")
def convert_cmd(msg):
    uid = msg.from_user.id
    
    if uid not in user_files or len(user_files[uid]) == 0:
        bot.reply_to(msg, "Нет файлов. Отправьте файлы сначала.", reply_markup=get_menu_keyboard())
        return

    files = list(user_files[uid])
    user_files[uid] = []
    
    bot.reply_to(msg, f"Конвертирую {len(files)} файлов...")

    for fpath in files:
        try:
            if not os.path.exists(fpath):
                bot.send_message(uid, "Файл не найден")
                continue
            
            fname = os.path.basename(fpath)
            info = analyze_file(fpath)
            ext = Path(fpath).suffix.lower()
            
            if info and info['verdict'] == "Не нуждается в конвертации":
                bot.send_message(uid, f"✅ {fname} — не нуждается в конвертации. Готово для ZModeler.")
                continue
                
            if ext == '.png':
                btx = converter._png_to_btx(fpath)
                if btx:
                    with open(btx, 'rb') as f:
                        bot.send_document(uid, f, caption=f"BTX: {Path(btx).name}")

            elif ext == '.dae':
                bot.send_message(uid, f"Конвертирую DAE в OBJ...")
                obj_file, zip_file = converter.dae_to_obj(fpath)
                if obj_file:
                    with open(obj_file, 'rb') as f:
                        bot.send_document(uid, f, caption="OBJ (из DAE)")
                    new_info = analyze_file(str(obj_file))
                    if new_info:
                        bot.send_message(uid, f"После конвертации: {new_info['verts']} вершин\nВердикт: {new_info['verdict']}")
                if zip_file:
                    with open(zip_file, 'rb') as f:
                        bot.send_document(uid, f, caption="Текстуры ZIP")
                if not obj_file:
                    bot.send_message(uid, f"Не удалось конвертировать: {fname}")

            elif ext == '.dff':
                bot.send_message(uid, f"✅ {fname} — DFF файл. ZModeler его открывает. Конвертация не требуется.")

            elif ext == '.3ds':
                bot.send_message(uid, f"✅ {fname} — 3DS файл. ZModeler его открывает. Конвертация не требуется.")

            elif ext == '.obj':
                if info and info['verts'] > 60000:
                    bot.send_message(uid, f"Упрощаю OBJ ({info['verts']} вершин)...")
                    simplified = converter._obj_simplify(fpath)
                    if simplified:
                        with open(simplified, 'rb') as f:
                            bot.send_document(uid, f, caption="OBJ (упрощён)")
                        new_info = analyze_file(str(simplified))
                        if new_info:
                            bot.send_message(uid, f"До: {info['verts']} вершин\nПосле: {new_info['verts']} вершин")
                else:
                    bot.send_message(uid, f"✅ {fname} — OBJ в порядке, конвертация не требуется.")

            else:
                bot.send_message(uid, f"Формат не поддерживается: {fname}")
                
        except Exception as e:
            bot.send_message(uid, f"Ошибка: {str(e)[:100]}")

    bot.send_message(uid, "Готово!", reply_markup=get_menu_keyboard())


@bot.message_handler(func=lambda msg: msg.text == "❌ Отменить")
def cancel_cmd(msg):
    uid = msg.from_user.id
    if uid in user_files:
        for fpath in user_files[uid]:
            if os.path.exists(fpath):
                os.remove(fpath)
        user_files[uid] = []
    bot.reply_to(msg, "Удалено.", reply_markup=get_menu_keyboard())


@bot.message_handler(func=lambda msg: msg.text == "📋 Список файлов")
def list_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]:
        bot.reply_to(msg, "Пусто.", reply_markup=get_menu_keyboard())
        return
    text = "Файлы:\n"
    for fpath in user_files[uid]:
        if os.path.exists(fpath):
            fname = os.path.basename(fpath)
            s = os.path.getsize(fpath)
            text += f"• {fname} ({s//1024} КБ)\n"
    bot.reply_to(msg, text, reply_markup=get_menu_keyboard())


@bot.message_handler(func=lambda msg: msg.text == "🗑 Очистить")
def clear_cmd(msg):
    uid = msg.from_user.id
    if uid in user_files:
        for fpath in user_files[uid]:
            if os.path.exists(fpath):
                os.remove(fpath)
        user_files[uid] = []
    bot.reply_to(msg, "Очищено.", reply_markup=get_menu_keyboard())


@bot.message_handler(func=lambda msg: True)
def any_msg(msg):
    if not check_subscription(msg.from_user.id):
        send_subscription_message(msg.chat.id)
        return
    bot.reply_to(msg, "Используйте меню или отправьте файлы.", reply_markup=get_menu_keyboard())


print("[>] Бот запущен")
bot.polling()
