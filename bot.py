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

TOKEN = "8613630902:AAEehO6bqcVhU6gN77hVTfDz7kE0YPPGcKg"
CHANNEL_ID = "@brmodels095"
CHANNEL_URL = "https://t.me/brmodels095"

bot = telebot.TeleBot(TOKEN)
user_files = {}

class FullModelConverter:
    def __init__(self):
        self.output_dir = Path("converted_output")
        self.temp_dir = Path("temp_processing")
        self.output_dir.mkdir(exist_ok=True)
        self.temp_dir.mkdir(exist_ok=True, parents=True)

    def _dae_to_obj(self, dae_path):
        tree = ET.parse(dae_path)
        root = tree.getroot()
        ns = 'http://www.collada.org/2005/11/COLLADASchema'
        obj_path = self.temp_dir / f"{Path(dae_path).stem}.obj"
        vertices, normals, uvs, triangles_data = [], [], [], []
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
                            triangles_data.append([indices[i]+1, indices[i+1]+1, indices[i+2]+1])
        with open(obj_path, 'w') as f:
            for v in vertices: f.write(f"v {v[0]} {v[1]} {v[2]}\n")
            for vt in uvs: f.write(f"vt {vt[0]} {vt[1]}\n")
            for vn in normals: f.write(f"vn {vn[0]} {vn[1]} {vn[2]}\n")
            for face in triangles_data: f.write(f"f {face[0]} {face[1]} {face[2]}\n")
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
            vertices, faces, normals, uvs = [], [], [], []
            with open(mesh_path, 'rb') as f:
                f.read(8)
                vertex_count = struct.unpack('i', f.read(4))[0]
                for _ in range(vertex_count):
                    x, y, z = struct.unpack('fff', f.read(12))
                    vertices.append([x, y, z])
                    nx, ny, nz = struct.unpack('fff', f.read(12))
                    normals.append([nx, ny, nz])
                    u, v = struct.unpack('ff', f.read(8))
                    uvs.append([u, v])
                triangle_count = struct.unpack('i', f.read(4))[0]
                for _ in range(triangle_count):
                    faces.append(list(struct.unpack('iii', f.read(12))))
            obj_path = self.temp_dir / f"{mesh_name}.obj"
            with open(obj_path, 'w') as f:
                for v in vertices: f.write(f"v {v[0]} {v[1]} {v[2]}\n")
                for vt in uvs: f.write(f"vt {vt[0]} {vt[1]}\n")
                for vn in normals: f.write(f"vn {vn[0]} {vn[1]} {vn[2]}\n")
                for face in faces: f.write(f"f {face[0]+1} {face[1]+1} {face[2]+1}\n")
            return obj_path
        except:
            return None

    def _obj_to_dff(self, obj_path, output_name=None):
        obj_file = Path(obj_path)
        if output_name is None:
            output_name = obj_file.stem
        dff_path = self.output_dir / f"{output_name}.dff"
        vertices, faces = [], []
        with open(obj_file, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if line.startswith('v '):
                    vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
                elif line.startswith('f '):
                    face = []
                    for p in parts[1:]:
                        idx = int(p.split('/')[0]) - 1
                        face.append(idx)
                    if len(face) == 3:
                        faces.append(face)
        with open(dff_path, 'wb') as f:
            f.write(b'\x16\x00\x00\x00')
            f.write(b'\x01\x00\x00\x00')
            f.write(len(vertices).to_bytes(4, 'little'))
            f.write(len(faces).to_bytes(4, 'little'))
            for v in vertices:
                f.write(struct.pack('fff', v[0], v[1], v[2]))
            for fc in faces:
                f.write(struct.pack('HHH', fc[0], fc[1], fc[2]))
        return dff_path

    def _png_to_btx(self, png_path, output_name=None):
        png_file = Path(png_path)
        if output_name is None:
            output_name = png_file.stem
        btx_path = self.output_dir / f"{output_name}.btx"
        
        img = Image.open(png_file).convert("RGB")
        
        # Ограничение размера до 512x512
        max_size = 512
        if img.width > max_size or img.height > max_size:
            img.thumbnail((max_size, max_size), Image.LANCZOS)
        
        # Сжатие через JPEG для уменьшения размера
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
        inp = Path(input_path)
        if inp.suffix == '.dae':
            obj_path = self._dae_to_obj(inp)
            final_obj = self.output_dir / obj_path.name
            shutil.copy(obj_path, final_obj)
            png_files = self._extract_textures_to_png(inp.parent)
            zip_path = self._pack_to_zip(png_files, inp.stem) if png_files else None
            return final_obj, zip_path
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
                png_files = self._extract_textures_to_png(inp.parent)
                zip_path = self._pack_to_zip(png_files, name) if png_files else None
                return final_obj, zip_path
        return None, None

    def obj_to_dff_only(self, input_path):
        inp = Path(input_path)
        if inp.suffix.lower() == '.obj':
            return self._obj_to_dff(inp)
        return None


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


@bot.message_handler(commands=['start'])
def start(msg):
    if not check_subscription(msg.from_user.id):
        send_subscription_message(msg.chat.id)
        return
    bot.reply_to(msg, (
        "Возможности:\n\n"
        "🎨 PNG → BTX (сжатый, макс 512x512)\n"
        "🧩 OBJ → DFF\n"
        "📦 .dae / .jbeam → .obj + текстуры в ZIP\n\n"
        "Канал: @brmodels095"
    ))


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
    if not check_subscription(msg.from_user.id):
        send_subscription_message(msg.chat.id)
        return
    if msg.document.file_size > 50 * 1024 * 1024:
        bot.reply_to(msg, "❌ Файл > 50 МБ")
        return
    file_info = bot.get_file(msg.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    fname = msg.document.file_name
    with open(fname, 'wb') as f:
        f.write(downloaded)
    user_files[msg.from_user.id] = fname
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Конвертировать", callback_data="convert"),
        types.InlineKeyboardButton("❌ Отменить", callback_data="cancel")
    )
    bot.reply_to(msg, f"📁 {fname}", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "convert")
def convert_callback(call):
    uid = call.from_user.id
    if uid not in user_files:
        bot.answer_callback_query(call.id, "Файл не найден", show_alert=True)
        return
    fname = user_files[uid]
    bot.answer_callback_query(call.id, "🚀 Конвертирую...")
    bot.edit_message_text(f"🚀 {fname}...", call.message.chat.id, call.message.message_id)
    try:
        if fname.lower().endswith('.png'):
            btx = converter._png_to_btx(fname)
            with open(btx, 'rb') as f:
                bot.send_document(call.message.chat.id, f, caption="✅ BTX")
        elif fname.lower().endswith('.obj'):
            dff = converter.obj_to_dff_only(fname)
            if dff:
                with open(dff, 'rb') as f:
                    bot.send_document(call.message.chat.id, f, caption="✅ DFF")
        elif fname.endswith(('.dae', '.jbeam')):
            obj_file, zip_file = converter.beamng_full(fname)
            if obj_file:
                with open(obj_file, 'rb') as f:
                    bot.send_document(call.message.chat.id, f, caption="✅ OBJ")
            if zip_file:
                with open(zip_file, 'rb') as f:
                    bot.send_document(call.message.chat.id, f, caption="✅ Текстуры ZIP")
        else:
            bot.send_message(call.message.chat.id, f"❌ Формат: {fname}")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")
    if uid in user_files:
        del user_files[uid]


@bot.callback_query_handler(func=lambda call: call.data == "cancel")
def cancel_callback(call):
    if call.from_user.id in user_files:
        del user_files[call.from_user.id]
    bot.answer_callback_query(call.id, "❌ Отменено")
    bot.edit_message_text("❌ Отменено.", call.message.chat.id, call.message.message_id)


@bot.message_handler(func=lambda msg: True)
def any_msg(msg):
    if not check_subscription(msg.from_user.id):
        send_subscription_message(msg.chat.id)
        return
    bot.reply_to(msg, "Отправьте файл или /start")


print("[>] Бот запущен")
bot.polling()
