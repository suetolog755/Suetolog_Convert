import os
import json
import struct
import shutil
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
        vertices = []
        normals = []
        uvs = []
        triangles_data = []
        for mesh in root.iter(f'{{{ns}}}mesh'):
            positions = None
            normals_data = None
            uvs_data = None
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
            if positions:
                vertices.extend(positions)
            if normals_data:
                normals.extend(normals_data)
            if uvs_data:
                uvs.extend(uvs_data)
            for triangles in mesh.findall(f'{{{ns}}}triangles'):
                p_elems = triangles.findall(f'{{{ns}}}p')
                if p_elems:
                    indices = list(map(int, p_elems[0].text.strip().split()))
                    for i in range(0, len(indices), 3):
                        if i + 2 < len(indices):
                            triangles_data.append([indices[i]+1, indices[i+1]+1, indices[i+2]+1])
        with open(obj_path, 'w') as f:
            f.write("# DAE -> OBJ\n")
            for v in vertices:
                f.write(f"v {v[0]} {v[1]} {v[2]}\n")
            for vt in uvs:
                f.write(f"vt {vt[0]} {vt[1]}\n")
            for vn in normals:
                f.write(f"vn {vn[0]} {vn[1]} {vn[2]}\n")
            for face in triangles_data:
                f.write(f"f {face[0]} {face[1]} {face[2]}\n")
        return obj_path

    def _parse_jbeam(self, jbeam_path):
        with open(jbeam_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        mesh_files = []
        texture_paths = []
        for key, value in data.items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        if item.endswith('.mesh'):
                            mesh_files.append(item)
                        elif any(item.lower().endswith(ext) for ext in ['.png', '.dds', '.jpg', '.tga']):
                            texture_paths.append(item)
            elif isinstance(value, str):
                if value.endswith('.mesh'):
                    mesh_files.append(value)
                elif any(value.lower().endswith(ext) for ext in ['.png', '.dds', '.jpg', '.tga']):
                    texture_paths.append(value)
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
                f.write("# MESH -> OBJ\n")
                for v in vertices:
                    f.write(f"v {v[0]} {v[1]} {v[2]}\n")
                for vt in uvs:
                    f.write(f"vt {vt[0]} {vt[1]}\n")
                for vn in normals:
                    f.write(f"vn {vn[0]} {vn[1]} {vn[2]}\n")
                for face in faces:
                    f.write(f"f {face[0]+1} {face[1]+1} {face[2]+1}\n")
            return obj_path
        except Exception as e:
            print(f"[!] Ошибка .mesh: {e}")
            return None

    def _png_to_btx(self, png_path, output_name=None):
        png_file = Path(png_path)
        if output_name is None:
            output_name = png_file.stem
        btx_path = self.output_dir / f"{output_name}.btx"
        img = Image.open(png_file).convert("RGBA")
        with open(btx_path, 'wb') as f:
            f.write(b'BTX\x00')
            f.write(img.width.to_bytes(2, 'little'))
            f.write(img.height.to_bytes(2, 'little'))
            f.write(b'\x01')
            f.write(b'\x04')
            f.write(img.tobytes())
        return btx_path

    def _convert_all_textures(self, texture_folder):
        texture_path = Path(texture_folder)
        btx_files = []
        if not texture_path.exists():
            return btx_files
        for img in texture_path.rglob("*"):
            if img.suffix.lower() == '.png':
                btx = self._png_to_btx(img, img.stem)
                btx_files.append(btx)
        return btx_files

    def beamng_full(self, input_path):
        inp = Path(input_path)
        btx_files = []
        if inp.suffix == '.dae':
            obj_path = self._dae_to_obj(inp)
            final_obj = self.output_dir / obj_path.name
            shutil.copy(obj_path, final_obj)
            btx_files = self._convert_all_textures(inp.parent)
            return final_obj, btx_files
        elif inp.suffix == '.jbeam':
            name, mesh_files, textures = self._parse_jbeam(inp)
            obj_paths = []
            for m in mesh_files:
                mesh_full_path = inp.parent / m
                if mesh_full_path.exists():
                    p = self._mesh_to_obj(mesh_full_path)
                    if p:
                        obj_paths.append(p)
            if obj_paths:
                final_obj = self.output_dir / f"{name}.obj"
                with open(final_obj, 'w') as out:
                    for p in obj_paths:
                        with open(p, 'r') as inp_f:
                            out.write(inp_f.read())
                if textures:
                    tex_temp = self.temp_dir / f"tex_{name}"
                    tex_temp.mkdir(exist_ok=True)
                    for tex in textures:
                        tex_full = inp.parent / tex
                        if tex_full.exists():
                            shutil.copy(tex_full, tex_temp / tex_full.name)
                    btx_files = self._convert_all_textures(tex_temp)
                else:
                    btx_files = self._convert_all_textures(inp.parent)
                return final_obj, btx_files
        return None, []

    def textures_only(self, input_path):
        inp = Path(input_path)
        if inp.suffix.lower() == '.png':
            btx = self._png_to_btx(inp)
            return [btx]
        return []


converter = FullModelConverter()


def check_subscription(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False


def send_subscription_message(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_subscribe = types.InlineKeyboardButton("📢 Подписаться", url=CHANNEL_URL)
    btn_check = types.InlineKeyboardButton("✅ Проверить подписку", callback_data="check_sub")
    markup.add(btn_subscribe, btn_check)
    text = "🔒 Подпишитесь чтобы пользоваться ботом\n\nДля доступа необходимо подписаться на канал автора:\n" + CHANNEL_URL
    bot.send_message(chat_id, text, reply_markup=markup)


@bot.message_handler(commands=['start'])
def start(msg):
    user_id = msg.from_user.id
    if not check_subscription(user_id):
        send_subscription_message(msg.chat.id)
        return
    text = (
        "Выберите действие:\n\n"
        "Конвертировать:\n"
        "- PNG -> BTX (1 PNG = 1 BTX)\n"
        "- Несколько PNG = несколько BTX\n\n"
        "Обрабатывать:\n"
        "- .dae -> .obj\n"
        "- .jbeam + .mesh -> .obj\n"
        "- Все PNG текстуры рядом -> BTX\n\n"
        "Лимит: до 50 МБ за раз\n\n"
        "Канал автора: @brmodels095\n\n"
        "Просто отправь мне файлы и нажми Конвертировать!"
    )
    bot.reply_to(msg, text)


@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def check_sub_callback(call):
    user_id = call.from_user.id
    if check_subscription(user_id):
        bot.answer_callback_query(call.id, "Вы подписаны! Доступ открыт.")
        bot.edit_message_text("Подписка подтверждена! Отправьте файл или напишите /start", call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "Вы не подписаны!", show_alert=True)
        send_subscription_message(call.message.chat.id)


@bot.message_handler(content_types=['document'])
def handle_file(msg):
    user_id = msg.from_user.id
    if not check_subscription(user_id):
        send_subscription_message(msg.chat.id)
        return
    if msg.document.file_size > 50 * 1024 * 1024:
        bot.reply_to(msg, "Файл превышает лимит 50 МБ.")
        return
    file_info = bot.get_file(msg.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    fname = msg.document.file_name
    with open(fname, 'wb') as f:
        f.write(downloaded)
    user_files[user_id] = fname
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_convert = types.InlineKeyboardButton("✅ Конвертировать", callback_data="convert")
    btn_cancel = types.InlineKeyboardButton("❌ Отменить", callback_data="cancel")
    markup.add(btn_convert, btn_cancel)
    bot.reply_to(msg, f"Файл: {fname}\n\nВыберите действие:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "convert")
def convert_callback(call):
    user_id = call.from_user.id
    if user_id not in user_files:
        bot.answer_callback_query(call.id, "Файл не найден. Отправьте заново.", show_alert=True)
        return
    fname = user_files[user_id]
    bot.answer_callback_query(call.id, "Начинаю конвертацию...")
    bot.edit_message_text(f"Конвертирую {fname}...", call.message.chat.id, call.message.message_id)
    try:
        if fname.lower().endswith('.png'):
            btx_files = converter.textures_only(fname)
            for btx in btx_files:
                with open(btx, 'rb') as f:
                    bot.send_document(call.message.chat.id, f, caption=f"Готово: {Path(btx).name}")
            if not btx_files:
                bot.send_message(call.message.chat.id, "Не удалось конвертировать")
        elif fname.endswith(('.dae', '.jbeam')):
            obj_file, btx_files = converter.beamng_full(fname)
            if obj_file:
                with open(obj_file, 'rb') as f:
                    bot.send_document(call.message.chat.id, f, caption="OBJ модель")
            for btx in btx_files:
                with open(btx, 'rb') as f:
                    bot.send_document(call.message.chat.id, f, caption=f"Готово: {Path(btx).name}")
            if not obj_file and not btx_files:
                bot.send_message(call.message.chat.id, "Не удалось сконвертировать")
        else:
            bot.send_message(call.message.chat.id, f"Формат не поддерживается: {fname}")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"Ошибка: {e}")
    if user_id in user_files:
        del user_files[user_id]


@bot.callback_query_handler(func=lambda call: call.data == "cancel")
def cancel_callback(call):
    user_id = call.from_user.id
    if user_id in user_files:
        del user_files[user_id]
    bot.answer_callback_query(call.id, "Отменено")
    bot.edit_message_text("Конвертация отменена.", call.message.chat.id, call.message.message_id)


@bot.message_handler(func=lambda msg: True)
def check_all_messages(msg):
    user_id = msg.from_user.id
    if not check_subscription(user_id):
        send_subscription_message(msg.chat.id)
        return
    bot.reply_to(msg, "Отправьте файл для конвертации или напишите /start")


print("[>] Бот запущен")
bot.polling()
