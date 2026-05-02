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
    """AI-анализ 3D-файла на совместимость с ZModeler Android"""
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
                            if fa is not None:
                                verts += len(fa.text.strip().split()) // 3
                    for triangles in mesh.findall(f'{{{ns}}}triangles'):
                        p_elems = triangles.findall(f'{{{ns}}}p')
                        if p_elems:
                            faces += len(p_elems[0].text.strip().split()) // 3
            except:
                pass
        
        elif ext in ['.dff', '.3ds']:
            # Бинарные форматы — только размер и тип
            pass
        
        # Формируем вердикт
        issues = []
        warnings = []
        
        if ext in ['.obj', '.dae'] and verts > 0:
            if verts > 65535:
                issues.append(f"⚠️ {verts} вершин > 65535 — ZModeler крашнется")
            elif verts > 40000:
                warnings.append(f"⚡ {verts} вершин — возможны лаги")
            
            if faces > 50000:
                issues.append(f"⚠️ {faces} полигонов — высокий шанс краша")
            
            if uvs == 0 and ext == '.obj':
                warnings.append("🖌 Нет UV-развёртки")
        
        if size_kb > 10000:
            warnings.append(f"📦 Файл {size_kb} КБ — может долго грузиться")
        
        # Вердикт
        if ext == '.dff':
            verdict = "⚠️ DFF — импорт НЕ поддерживается. Конвертируй в OBJ через бота."
        elif ext == '.3ds':
            verdict = "⚠️ 3DS — может открыться, но лучше конвертировать в OBJ."
        elif issues:
            verdict = "❌ Скорее всего не откроется"
        elif warnings:
            verdict = "⚠️ Может работать с ограничениями"
        elif verts > 0:
            verdict = "✅ Должен открыться без проблем"
        else:
            verdict = "📦 Файл проанализирован. Размер: {} КБ".format(size_kb)
        
        return {
            'ext': ext,
            'verts': verts,
            'faces': faces,
            'uvs': uvs,
            'size_kb': size_kb,
            'issues': issues,
            'warnings': warnings,
            'verdict': verdict
        }
    except Exception as e:
        return {'ext': Path(file_path).suffix, 'verts': 0, 'faces': 0, 'uvs': 0, 'size_kb': 0, 'issues': [], 'warnings': [], 'verdict': f'❌ Ошибка анализа: {e}'}


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

        max_verts = 60000
        if len(vertices) > max_verts:
            keep_ratio = max_verts / len(vertices)
            step = max(1, int(1.0 / keep_ratio))
            new_vertices, new_uvs, new_faces, old_to_new = [], [], [], {}
            for i in range(0, len(vertices), step):
                old_to_new[i] = len(new_vertices)
                new_vertices.append(vertices[i])
                if i < len(uvs):
                    new_uvs.append(uvs[i])
            for face in faces:
                if all(v in old_to_new for v in face):
                    new_faces.append([old_to_new[v] for v in face])
            vertices, uvs, faces = new_vertices, new_uvs, new_faces

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
        "🎨 PNG → BTX (сжатый, 512x512)\n"
        "📦 .dae / .jbeam → .obj + ZIP текстур\n"
        "🔍 AI-анализ: .obj, .dae, .dff, .3ds\n\n"
        "📂 Отправляйте файлы (можно много)\n"
        "Затем ✅ Конвертировать или 🔍 Анализ\n\n"
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
        bot.reply_to(msg, "❌ Общий размер > 50 МБ")
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

    # Авто-анализ для всех форматов
    info = analyze_file(fname)
    analysis_text = ""
    if info:
        analysis_text = f"\n\n🔍 *AI-анализ ({info['ext']}):*\n"
        if info['verts'] > 0:
            analysis_text += f"• Вершин: {info['verts']}\n• Полигонов: {info['faces']}\n• UV: {info['uvs']}\n"
        analysis_text += f"• Размер: {info['size_kb']} КБ\n• Вердикт: {info['verdict']}"

    bot.reply_to(msg,
        f"📁 {fname} добавлен\nВсего: {len(user_files[uid])}{analysis_text}\n\nИспользуйте меню:",
        reply_markup=get_menu_keyboard(),
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda msg: msg.text == "🔍 Анализ файла")
def analyze_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]:
        bot.reply_to(msg, "❌ Нет файлов.", reply_markup=get_menu_keyboard())
        return

    for fname in user_files[uid]:
        info = analyze_file(fname)
        if info:
            text = f"🔍 *Анализ: {fname}*\n\n"
            if info['verts'] > 0:
                text += f"📊 *Статистика:*\n• Вершин: {info['verts']}\n• Полигонов: {info['faces']}\n• UV: {info['uvs']}\n"
            text += f"• Размер: {info['size_kb']} КБ\n• Формат: {info['ext']}\n\n📋 *Вердикт:*\n{info['verdict']}\n"
            if info['issues']:
                text += f"\n⚠️ *Проблемы:*\n" + "\n".join(info['issues'])
            if info['warnings']:
                text += f"\n💡 *Замечания:*\n" + "\n".join(info['warnings'])
            if info['ext'] == '.dff':
                text += "\n\n📌 *DFF не импортируется в ZModeler.*\nОтправь .obj или .dae для конвертации."
            elif info['ext'] == '.3ds':
                text += "\n\n📌 *3DS лучше конвертировать в OBJ.*\nОтправь файл боту для конвертации."
            elif info['verts'] > 65535:
                text += "\n\n📌 *Слишком много вершин.*\nКонвертируй через бота — авто-упрощение до 60K."
            bot.reply_to(msg, text, parse_mode="Markdown")


@bot.message_handler(func=lambda msg: msg.text == "✅ Конвертировать")
def convert_cmd(msg):
    uid = msg.from_user.id
    if not check_subscription(uid):
        send_subscription_message(msg.chat.id)
        return
    if uid not in user_files or not user_files[uid]:
        bot.reply_to(msg, "❌ Нет файлов.", reply_markup=get_menu_keyboard())
        return

    files = user_files[uid]
    bot.reply_to(msg, f"🚀 Конвертирую {len(files)}...")

    for fname in files:
        try:
            if fname.lower().endswith('.png'):
                btx = converter._png_to_btx(fname)
                with open(btx, 'rb') as f:
                    bot.send_document(uid, f, caption=f"✅ {Path(btx).name}")

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

            elif fname.lower().endswith('.obj'):
                with open(fname, 'rb') as f:
                    bot.send_document(uid, f, caption="✅ OBJ модель")
                bot.send_message(uid, "📌 File → Import (ZModeler) → Export DFF")

            else:
                bot.send_message(uid, f"❌ Формат не поддерживается: {fname}")
        except Exception as e:
            bot.send_message(uid, f"❌ Ошибка в {fname}: {e}")

    user_files[uid] = []
    bot.send_message(uid, "✅ Готово!", reply_markup=get_menu_keyboard())


@bot.message_handler(func=lambda msg: msg.text == "❌ Отменить")
def cancel_cmd(msg):
    uid = msg.from_user.id
    if uid in user_files:
        for f in user_files[uid]:
            if os.path.exists(f): os.remove(f)
        user_files[uid] = []
    bot.reply_to(msg, "❌ Удалено.", reply_markup=get_menu_keyboard())


@bot.message_handler(func=lambda msg: msg.text == "📋 Список файлов")
def list_cmd(msg):
    uid = msg.from_user.id
    if uid not in user_files or not user_files[uid]:
        bot.reply_to(msg, "📋 Пусто.", reply_markup=get_menu_keyboard())
        return
    text = "📋 *Файлы:*\n"
    total = 0
    for f in user_files[uid]:
        if os.path.exists(f):
            s = os.path.getsize(f); total += s
            text += f"• {f} ({s//1024} КБ)\n"
    text += f"\n{len(user_files[uid])} шт, {total//1024} КБ"
    bot.reply_to(msg, text, parse_mode="Markdown", reply_markup=get_menu_keyboard())


@bot.message_handler(func=lambda msg: msg.text == "🗑 Очистить")
def clear_cmd(msg):
    uid = msg.from_user.id
    if uid in user_files:
        for f in user_files[uid]:
            if os.path.exists(f): os.remove(f)
        user_files[uid] = []
    bot.reply_to(msg, "🗑 Очищено.", reply_markup=get_menu_keyboard())


@bot.message_handler(func=lambda msg: True)
def any_msg(msg):
    if not check_subscription(msg.from_user.id):
        send_subscription_message(msg.chat.id)
        return
    bot.reply_to(msg, "Используйте меню или отправьте файлы.", reply_markup=get_menu_keyboard())


print("[>] Бот запущен")
bot.polling()
