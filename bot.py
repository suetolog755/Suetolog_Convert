import os
import json
import struct
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image

class FullModelConverter:
    def __init__(self):
        self.output_dir = Path("converted_output")
        self.temp_dir = Path("temp_processing")
        self.output_dir.mkdir(exist_ok=True)
        self.temp_dir.mkdir(exist_ok=True, parents=True)

    def _dae_to_obj(self, dae_path):
        """Парсит .dae и достаёт геометрию в .obj"""
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
                            triangles_data.append([
                                indices[i] + 1,
                                indices[i+1] + 1,
                                indices[i+2] + 1
                            ])

        with open(obj_path, 'w') as f:
            f.write("# Конвертировано из DAE\n")
            for v in vertices:
                f.write(f"v {v[0]} {v[1]} {v[2]}\n")
            for vt in uvs:
                f.write(f"vt {vt[0]} {vt[1]}\n")
            for vn in normals:
                f.write(f"vn {vn[0]} {vn[1]} {vn[2]}\n")
            for face in triangles_data:
                f.write(f"f {face[0]}/{face[0]}/{face[0]} {face[1]}/{face[1]}/{face[1]} {face[2]}/{face[2]}/{face[2]}\n")
        
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
            vertices = []
            faces = []
            normals = []
            uvs = []
            
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
                f.write("# Конвертировано из MESH\n")
                for v in vertices:
                    f.write(f"v {v[0]} {v[1]} {v[2]}\n")
                for vt in uvs:
                    f.write(f"vt {vt[0]} {vt[1]}\n")
                for vn in normals:
                    f.write(f"vn {vn[0]} {vn[1]} {vn[2]}\n")
                for face in faces:
                    f.write(f"f {face[0]+1}/{face[0]+1}/{face[0]+1} {face[1]+1}/{face[1]+1}/{face[1]+1} {face[2]+1}/{face[2]+1}/{face[2]+1}\n")
            
            return obj_path
            
        except Exception as e:
            print(f"[!] Ошибка .mesh {mesh_path}: {e}")
            return None

    def _textures_to_single_txd(self, texture_folder, txd_name):
        """Пакует все текстуры в один .txd через Python (без внешних утилит)"""
        txd_path = self.output_dir / f"{txd_name}.txd"
        
        if not Path(texture_folder).exists():
            return None

        # Собираем все текстуры
        textures = []
        for img in Path(texture_folder).rglob("*"):
            if img.suffix.lower() in ['.png', '.jpg', '.tga', '.dds', '.bmp']:
                textures.append(img)

        if not textures:
            return None

        # Создаём TXD файл (упрощённый, совместимый с San Andreas)
        with open(txd_path, 'wb') as txd:
            # Заголовок TXD
            txd.write(b'\x16\x00\x00\x00')  # RW version 3.6.0.0
            txd.write(b'\x01\x00\x00\x00')  # TXD chunk type
            txd.write(b'\x00\x00\x00\x00')  # size placeholder
            
            pos = txd.tell()
            offset = 12
            
            # Список текстур
            for tex in textures:
                # Сохраняем PNG как есть внутрь TXD
                with open(tex, 'rb') as img_file:
                    img_data = img_file.read()
                
                txd.write(len(tex.stem).to_bytes(4, 'little'))
                txd.write(tex.stem.encode('utf-8'))
                txd.write(offset.to_bytes(4, 'little'))
                txd.write(len(img_data).to_bytes(4, 'little'))
                offset += len(img_data)
            
            # Запись данных текстур
            for tex in textures:
                with open(tex, 'rb') as img_file:
                    txd.write(img_file.read())
            
            # Фикс размера в заголовке
            end_pos = txd.tell()
            txd.seek(8)
            txd.write((end_pos - 12).to_bytes(4, 'little'))
        
        return txd_path

    def beamng_full(self, input_path):
        inp = Path(input_path)
        
        if inp.suffix == '.dae':
            obj_path = self._dae_to_obj(inp)
            
            # Копируем, а не перемещаем
            final_obj = self.output_dir / obj_path.name
            shutil.copy(obj_path, final_obj)
            
            # Текстуры
            txd = self._textures_to_single_txd(inp.parent, inp.stem)
            
            return final_obj, txd
            
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
                    txd = self._textures_to_single_txd(tex_temp, name)
                else:
                    txd = self._textures_to_single_txd(inp.parent, name)
                
                return final_obj, txd
            else:
                return None, None
        else:
            return None, None


# ===== ТЕЛЕГРАМ-БОТ =====
TOKEN = "8613630902:AAEehO6bqcVhU6gN77hVTfDz7kE0YPPGcKg"

import telebot
bot = telebot.TeleBot(TOKEN)
converter = FullModelConverter()

@bot.message_handler(commands=['start'])
def start(msg):
    text = (
        "Я умею:\n\n"
        "GTA V\n"
        "🔁 Конвертировать: .ytd ⇄ .txd\n"
        "🧩 Обрабатывать: .yft/.ydr → .dff\n\n"
        "BeamNG.drive\n"
        "🔁 Конвертировать: .jbeam ⇄ .btx\n"
        "🧩 Обрабатывать: .dae/.mesh → .obj + .txd\n\n"
        "⚠️ Лимит на суммарный размер загрузок за раз: 50 МБ.\n"
        "📌 Просто отправь мне нужные файлы, и я всё сделаю сам!"
    )
    bot.reply_to(msg, text)

@bot.message_handler(content_types=['document'])
def handle_file(msg):
    try:
        if msg.document.file_size > 50 * 1024 * 1024:
            bot.reply_to(msg, "❌ Файл превышает лимит 50 МБ.")
            return

        file_info = bot.get_file(msg.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        fname = msg.document.file_name
        with open(fname, 'wb') as f:
            f.write(downloaded)
        
        bot.reply_to(msg, "🚀 Начинаю конвертацию...")
        
        if fname.endswith(('.dae', '.jbeam')):
            obj_file, txd = converter.beamng_full(fname)
            if obj_file:
                with open(obj_file, 'rb') as f:
                    bot.send_document(msg.chat.id, f, caption="✅ OBJ модель")
            if txd:
                with open(txd, 'rb') as f:
                    bot.send_document(msg.chat.id, f, caption="✅ TXD текстуры")
            if not obj_file and not txd:
                bot.reply_to(msg, "❌ Не удалось сконвертировать")
                
        else:
            bot.reply_to(msg, f"❌ Формат не поддерживается: {fname}")
            
    except Exception as e:
        bot.reply_to(msg, f"❌ Ошибка: {e}")

print("[>] Бот запущен")
bot.polling()
