import os
import json
import struct
import shutil
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image

class FullModelConverter:
    def __init__(self):
        self.output_dir = Path("converted_output")
        self.temp_dir = Path("temp_processing")
        self.output_dir.mkdir(exist_ok=True)
        self.temp_dir.mkdir(exist_ok=True, parents=True)

    def _dae_to_obj(self, dae_path):
        """Конвертирует .dae в .obj через асс импортёр"""
        dae_file = Path(dae_path)
        obj_path = self.temp_dir / f"{dae_file.stem}.obj"
        
        script = f"""
import bpy
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
bpy.ops.wm.collada_import(filepath='{dae_file}')
for obj in bpy.context.scene.objects:
    if obj.type == 'MESH':
        obj.select_set(True)
bpy.ops.export_scene.obj(filepath='{obj_path}')
"""
        script_path = self.temp_dir / "dae_to_obj.py"
        script_path.write_text(script)
        subprocess.run(["blender", "--background", "--python", str(script_path)], check=True)
        script_path.unlink(missing_ok=True)
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

            # Запись OBJ вручную
            obj_path = self.temp_dir / f"{mesh_name}.obj"
            with open(obj_path, 'w') as f:
                for v in vertices:
                    f.write(f"v {v[0]} {v[1]} {v[2]}\n")
                for vt in uvs:
                    f.write(f"vt {vt[0]} {vt[1]}\n")
                for vn in normals:
                    f.write(f"vn {vn[0]} {vn[1]} {vn[2]}\n")
                for face in faces:
                    i1, i2, i3 = face[0]+1, face[1]+1, face[2]+1
                    f.write(f"f {i1}/{i1}/{i1} {i2}/{i2}/{i2} {i3}/{i3}/{i3}\n")
            
            return obj_path
            
        except Exception as e:
            print(f"[!] Ошибка .mesh {mesh_path}: {e}")
            return None

    def _obj_to_dff(self, obj_path, output_name):
        output_path = self.output_dir / f"{output_name}.dff"
        
        script = f"""
import bpy
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
bpy.ops.import_scene.obj(filepath='{obj_path}')
for obj in bpy.context.scene.objects:
    if obj.type == 'MESH':
        obj.select_set(True)
bpy.ops.export_dff.dff_export(
    filepath='{output_path}',
    export_version='3.4.0.0',
    export_collision=False
)
"""
        script_path = self.temp_dir / "obj_to_dff.py"
        script_path.write_text(script)
        subprocess.run(["blender", "--background", "--python", str(script_path)], check=True)
        script_path.unlink(missing_ok=True)
        return output_path

    def _textures_to_single_txd(self, texture_folder, txd_name):
        txd_path = self.output_dir / f"{txd_name}.txd"
        
        if not Path(texture_folder).exists():
            return None

        dds_folder = self.temp_dir / f"txd_{txd_name}"
        dds_folder.mkdir(exist_ok=True)

        texture_count = 0
        for img in Path(texture_folder).rglob("*"):
            if img.suffix.lower() in ['.png', '.jpg', '.tga', '.dds', '.bmp']:
                shutil.copy(img, dds_folder / img.name)
                texture_count += 1

        if texture_count == 0:
            shutil.rmtree(dds_folder, ignore_errors=True)
            return None

        subprocess.run([
            "magic-txd-cli", "create",
            "--input", str(dds_folder),
            "--output", str(txd_path),
            "--game", "sa"
        ], check=True)

        shutil.rmtree(dds_folder, ignore_errors=True)
        return txd_path

    def beamng_full(self, input_path):
        inp = Path(input_path)
        
        if inp.suffix == '.dae':
            obj_path = self._dae_to_obj(inp)
            dff = self._obj_to_dff(obj_path, inp.stem)
            txd = self._textures_to_single_txd(inp.parent, inp.stem)
            return dff, txd
            
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
                # Просто берём первый меш
                dff = self._obj_to_dff(obj_paths[0], name)
                
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
                
                return dff, txd
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
        "🔁 Конвертировать: .ytd ⇄ .btx\n"
        "🧩 Обрабатывать: .yft/.ydr → .dff\n\n"
        "BeamNG.drive\n"
        "🔁 Конвертировать: .jbeam ⇄ .btx\n"
        "🧩 Обрабатывать: .dae/.mesh → .dff\n\n"
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
            dff, txd = converter.beamng_full(fname)
            if dff:
                with open(dff, 'rb') as f:
                    bot.send_document(msg.chat.id, f, caption="✅ DFF модель")
            if txd:
                with open(txd, 'rb') as f:
                    bot.send_document(msg.chat.id, f, caption="✅ TXD текстуры")
            if not dff and not txd:
                bot.reply_to(msg, "❌ Не удалось сконвертировать")
                
        elif fname.endswith(('.yft', '.ydr')):
            bot.reply_to(msg, "⏳ GTA V конвертация пока недоступна")
                    
        else:
            bot.reply_to(msg, f"❌ Формат не поддерживается: {fname}")
            
    except Exception as e:
        bot.reply_to(msg, f"❌ Ошибка: {e}")

print("[>] Бот запущен")
bot.polling()
