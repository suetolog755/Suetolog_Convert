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

def analyze_obj(file_path):
    """AI-анализ OBJ файла для ZModeler"""
    try:
        verts = 0
        faces = 0
        uvs = 0
        size_kb = os.path.getsize(file_path) // 1024
        
        with open(file_path, 'r') as f:
            for line in f:
                if line.startswith('v '): verts += 1
                elif line.startswith('vt '): uvs += 1
                elif line.startswith('f '): faces += 1
        
        # Анализ совместимости
        issues = []
        warnings = []
        
        if verts > 65535:
            issues.append("⚠️ Более 65535 вершин — ZModeler может крашнуться")
        elif verts > 20000:
            warnings.append("⚡ Модель тяжёлая (>20K вершин) — возможны лаги")
        
        if uvs == 0:
            warnings.append("🖌 Нет UV-развёртки — текстуры не наложатся")
        
        if faces > 50000:
            issues.append("⚠️ Слишком много полигонов — высокий шанс краша")
        
        if size_kb > 10000:
            warnings.append("📦 Файл большой (>10 МБ) — может долго грузиться")
        
        # Итоговая оценка
        if issues:
            verdict = "❌ Скорее всего не откроется в ZModeler"
        elif warnings:
            verdict = "⚠️ Может работать с ограничениями"
        else:
            verdict = "✅ Должен открыться без проблем"
        
        return {
            'verts': verts,
            'faces': faces,
            'uvs': uvs,
            'size_kb': size_kb,
            'issues': issues,
            'warnings': warnings,
            'verdict': verdict
        }
    except:
        return None

def analyze_dae(file_path):
    """Анализ DAE файла"""
    try:
        size_kb = os.path.getsize(file_path) // 1024
        return {
            'size_kb': size_kb,
            'verdict': '📦 DAE файл — будет конвертирован в OBJ'
        }
    except:
        return None

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

    def _dae_to_obj(self, dae_path):
        tree = ET.parse(dae_path)
        root = tree.getroot()
        ns = 'http://www.collada.org/2005/11/COLLADASchema'
        obj_path = self.temp_dir / f"{Path(dae_path).stem}.obj"
        vertices, normals, uvs, faces = [], [], [], []
        
        for mesh in root.iter(f'{{{ns}}}mesh'):
            positions = normals_data = uvs_data = None
            for source in mesh.findall(f'{{{ns}}}source'):
                sid = source.get('id', '')
                float_array = source.find(f'{{{ns}}}float_array')
                if float_array is not None:
                    data = list(map(float, float_array.text.strip().split()))
                    if 'positions' in sid:
                        positions = [[data[i], data[i+1], data[i+2]] for i in range(0, len(data), 3)]
                    elif 'normals' in sid:
                        normals_data = [[data[i], data[i+1], data[i+2]] for i in range(0, len(data), 3)]
                    elif 'map' in sid.lower() or 'uv' in sid.lower():
                        uvs_data = [[data[i], data[i+1]] for i in range(0, len(data), 2)]
            if positions: vertices.extend(positions)
            if normals_data: normals.extend(normals_data)
            if uvs_data: uvs.extend(uvs_data)
            
            for triangles in mesh.findall(f'{{{ns}}}triangles'):
                p_elems = triangles.findall(f'{{{ns}}}p')
                if p_elems:
                    indices = list(map(int, p_elems[0].text.strip().split()))
                    for i in range(0, len(indices), 3):
                        if i + 2 < len(indices):
                            faces.append([indices[i]+1, indices[i+1]+1, indices[i+2]+1])

        with open(obj_path, 'w') as f:
            for v in vertices:
                f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            for vt in uvs:
                f.write(f"vt {vt[0]:.6f} {vt[1]:.6f}\n")
            for face in faces:
                f.write(f"f {face[0]} {face[1]} {face[2]}\n")
        return obj_path

    def _parse_jbeam(self, jbeam_path):
        with open(jbeam_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        mesh_files, texture_paths = [], []
        for key, value in data.items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        if item.endswith('.mesh'): mesh_files.append(item)
                        elif any(item.lower().endswith(ext) for ext in ['.png', '.dds', '.jpg', '.tga']): texture_paths.append(item)
            elif isinstance(value, str):
                if value.endswith('.mesh'): mesh_files.append(value)
                elif any(value.lower().endswith(ext) for ext in ['.png', '.dds', '.jpg', '.tga']): texture_paths.append(value)
        return Path(jbeam_path).stem, mesh_files, texture_paths

    def _mesh_to_obj(self, mesh_path):
        mesh_name = Path(mesh_path).stem
        try:
            vertices, faces, uvs = [], [], []
            with open(mesh_path, 'rb') as f:
                f.read(8)
                vertex_count = struct.unpack('i', f.read(4))[0]
                for _ in range(vertex_count):
                    x, y, z = struct.unpack('fff', f.read(12))
                    vertices.append([x, y, z])
                    f.read(12)
                    u, v = struct.unpack('ff', f.read(8))
                    uvs.append([u, v])
                triangle_count = struct.unpack('i', f.read(4))[0]
                for _ in range(triangle_count):
                    faces.append(list(struct.unpack('iii', f.read(12))))
                    
            obj_path = self.temp_dir / f"{mesh_name}.obj"
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

    def beamng_full(self, input_path):
        self._clean_temp()
        inp = Path(input_path)
        if inp.suffix == '.dae':
            obj_path = self._dae_to_obj(inp)
            final_obj = self.output_dir / obj_path.name
            shutil.copy(obj_path, final_obj)
            if self._has_textures(inp.parent):
                png_files = self._extract_textures_to_png(inp.parent)
                if png_files:
                    zip_path = self._pack_to_zip(png_files, inp.stem)
                    return final_obj, zip_path
            return final_obj, None
        elif inp.suffix == '.jbeam':
            name, mesh_files, textures = self._parse_jbeam(inp)
            obj_paths = []
            for m in mesh_files:
                mesh_full_path = inp.parent / m
                if mesh_full_path.exists():
                    p = self._mesh_to_obj(mesh_full_path)
                    if p: obj_paths.append(p)
            if obj_paths:
                final_obj = self.output_dir / f"{name}.obj"
                with open(final_obj, 'w') as out:
                    for p in obj_paths:
                        with open(p, 'r') as inp_f:
                            out.write(inp_f.read())
                if textures or self._has_textures(inp.parent):
                    png_files = self._extract_textures_to_png(inp.parent)
                    if png_files:
                        zip_path = self._pack_to_zip(png_files, name)
                        return final_obj, zip_path
                return final_obj, None
        return None, None


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
        "🎨 PNG → BTX (сжатый, макс 512x512)\n"
        "📦 .dae / .jbeam → .obj + текстуры в ZIP\n"
        "🧩 OBJ → остаётся OBJ (в ZModeler сам экспортируй в DFF)\n"
        "🔍 AI-анализ — проверь откроется ли файл в ZModeler\n\n"
        "📂 Отправляйте файлы (можно много)\n"
        "Затем нажмите ✅ Конвертировать или 🔍 Анализ в меню\n\n"
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

    total_size = msg.document.file_size
    if uid in user_files:
        for fname in user_files[uid]:
            if os.path.exists(fname):
                total_size += os.path.getsize(fname)

    if total_size > 50 * 1024 * 1024:
        bot.reply_to(msg, "❌ Общий размер файлов > 50 МБ")
        return

    file_info = bot.get_file(msg.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    fname = msg.document.file_name

    base, ext = os.path.splitext(fname)
    counter = 1
    while fname in (user_files.get(uid, [])):
        fname = f"{base}_{counter}{ext}"
        counter += 1

    with open(fname, 'wb') as f:
        f.write(downloaded)

    if uid not in user_files:
        user_files[uid] = []
    user_files[uid].append(fname)

    # Авто-анализ при добавлении файла
    analysis_text = ""
    if fname.lower().endswith('.obj'):
        info = analyze_obj(fname)
        if info:
            analysis_text = (
                f"\n\n🔍 *AI-анализ:*\n"
                f"• Вершин: {info['verts']}\n"
                f"• Полигонов: {info['faces']}\n"
                f"• UV-координат: {info['uvs']}\n"
                f"• Размер: {info['size_kb']} КБ\n"
                f"• Вердикт: {info['verdict']}"
            )
    elif fname.lower().endswith('.dae'):
        info = analyze_dae(fname)
        if info:
            analysis_text = (
                f"\n\n🔍 *AI-анализ:*\n"
                f"• Размер: {info['size_kb']} КБ\n"
                f"• Вердикт: {info['verdict']}"
            )

    bot.reply_to(msg, 
        f"📁 {fname} добавлен\nВсего файлов: {len(user_files[uid])}{analysis_text}\n\nИспользуйте меню для действий:", 
        reply_markup=get_menu_keyboard(),
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda msg: msg.text == "🔍 Анализ файла")
def analyze_cmd(msg):
    uid = msg.from_user.id

    if uid not in user_files or not user_files[uid]:
        bot.reply_to(msg, "❌ Нет файлов для анализа. Отправьте файлы сначала.", reply_markup=get_menu_keyboard())
        return

    files = user_files[uid]
    for fname in files:
        if fname.lower().endswith('.obj'):
            info = analyze_obj(fname)
            if info:
                text = (
                    f"🔍 *AI-анализ: {fname}*\n\n"
                    f"📊 *Статистика:*\n"
                    f"• Вершин: {info['verts']}\n"
                    f"• Полигонов: {info['faces']}\n"
                    f"• UV-координат: {info['uvs']}\n"
                    f"• Размер: {info['size_kb']} КБ\n\n"
                    f"📋 *Вердикт ZModeler:*\n{info['verdict']}\n"
                )
                if info['issues']:
                    text += f"\n⚠️ *Проблемы:*\n" + "\n".join(info['issues'])
                if info['warnings']:
                    text += f"\n💡 *Замечания:*\n" + "\n".join(info['warnings'])
                text += "\n\n📌 *Рекомендация:*\n"
                if info['verts'] > 65535:
                    text += "• Упрости модель (уменьши количество вершин)\n"
                if info['uvs'] == 0:
                    text += "• Добавь UV-развёртку перед конвертацией\n"
                if not info['issues']:
                    text += "• Можно смело импортировать в ZModeler\n"
                    text += "• File → Import → выбери этот .obj\n"
                    text += "• File → Export → DFF (GTA SA)\n"
                
                bot.reply_to(msg, text, parse_mode="Markdown")
            else:
                bot.reply_to(msg, f"❌ Не удалось проанализировать {fname}")
        else:
            bot.reply_to(msg, f"🔍 {fname} — анализ доступен только для .obj файлов")


@bot.message_handler(func=lambda msg: msg.text == "✅ Конвертировать")
def convert_cmd(msg):
    uid = msg.from_user.id

    if not check_subscription(uid):
        send_subscription_message(msg.chat.id)
        return

    if uid not in user_files or not user_files[uid]:
        bot.reply_to(msg, "❌ Нет файлов. Отправьте файлы сначала.", reply_markup=get_menu_keyboard())
        return

    files = user_files[uid]
    bot.reply_to(msg, f"🚀 Конвертирую {len(files)} файлов...")

    for fname in files:
        try:
            if fname.lower().endswith('.png'):
                btx = converter._png_to_btx(fname)
                with open(btx, 'rb') as f:
                    bot.send_document(uid, f, caption=f"✅ {Path(btx).name}")

            elif fname.lower().endswith('.obj'):
                with open(fname, 'rb') as f:
                    bot.send_document(uid, f, caption="✅ OBJ модель")
                bot.send_message(uid, (
                    "📌 Что делать с OBJ:\n"
                    "1. Открой ZModeler\n"
                    "2. File → Import — выбери этот .obj\n"
                    "3. File → Export — выбери DFF (GTA SA)\n"
                    "4. Сохрани — готово!"
                ))

            elif fname.endswith(('.dae', '.jbeam')):
                obj_file, zip_file = converter.beamng_full(fname)
                if obj_file:
                    with open(obj_file, 'rb') as f:
                        bot.send_document(uid, f, caption="✅ OBJ модель")
                if zip_file:
                    with open(zip_file, 'rb') as f:
                        bot.send_document(uid, f, caption="✅ Текстуры ZIP")
                if not obj_file and not zip_file:
                    bot.send_message(uid, f"❌ Не удалось: {fname}")
        except Exception as e:
            bot.send_message(uid, f"❌ Ошибка в {fname}: {e}")

    user_files[uid] = []
    bot.send_message(uid, "✅ Готово! Отправьте новые файлы.", reply_markup=get_menu_keyboard())


@bot.message_handler(func=lambda msg: msg.text == "❌ Отменить")
def cancel_cmd(msg):
    uid = msg.from_user.id
    if uid in user_files:
        for fname in user_files[uid]:
            if os.path.exists(fname):
                os.remove(fname)
        user_files[uid] = []
    bot.reply_to(msg, "❌ Все файлы удалены. Отправьте новые.", reply_markup=get_menu_keyboard())


@bot.message_handler(func=lambda msg: msg.text == "📋 Список файлов")
def list_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]:
        bot.reply_to(msg, "📋 Нет загруженных файлов.", reply_markup=get_menu_keyboard())
        return

    text = "📋 Загруженные файлы:\n"
    total = 0
    for fname in user_files[uid]:
        if os.path.exists(fname):
            size = os.path.getsize(fname)
            total += size
            text += f"• {fname} ({size // 1024} КБ)\n"
    text += f"\nВсего: {len(user_files[uid])} файлов, {total // 1024} КБ"
    bot.reply_to(msg, text, reply_markup=get_menu_keyboard())


@bot.message_handler(func=lambda msg: msg.text == "🗑 Очистить")
def clear_cmd(msg):
    uid = msg.from_user.id
    if uid in user_files:
        for fname in user_files[uid]:
            if os.path.exists(fname):
                os.remove(fname)
        user_files[uid] = []
    bot.reply_to(msg, "🗑 Очищено. Отправьте новые файлы.", reply_markup=get_menu_keyboard())


@bot.message_handler(func=lambda msg: True)
def any_msg(msg):
    if not check_subscription(msg.from_user.id):
        send_subscription_message(msg.chat.id)
        return
    bot.reply_to(msg, "Используйте меню или отправьте файлы.", reply_markup=get_menu_keyboard())


print("[>] Бот запущен")
bot.polling()
