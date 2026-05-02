```python
import os
import json
import struct
import shutil
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image
import trimesh

class FullModelConverter:
    def __init__(self):
        self.output_dir = Path("converted_output")
        self.temp_dir = Path("temp_processing")
        self.output_dir.mkdir(exist_ok=True)
        self.temp_dir.mkdir(exist_ok=True, parents=True)

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
                        elif any(item.lower().endswith(ext) for ext in ['.png', '.dds', '.jpg']):
                            texture_paths.append(item)
            elif isinstance(value, str):
                if value.endswith('.mesh'):
                    mesh_files.append(value)
                    
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

            mesh = trimesh.Trimesh(
                vertices=np.array(vertices),
                faces=np.array(faces),
                vertex_normals=np.array(normals),
                visual=trimesh.visual.TextureVisuals(uv=np.array(uvs))
            )
            
            obj_path = self.temp_dir / f"{mesh_name}.obj"
            mesh.export(obj_path, file_type='obj')
            return obj_path
            
        except Exception as e:
            print(f"[!] Ошибка .mesh: {e}")
            return None

    def _blender_to_dff(self, input_path, output_name):
        output_path = self.output_dir / f"{output_name}.dff"
        
        script = f"""
import bpy
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
bpy.ops.import_scene.obj(filepath='{input_path}')
for obj in bpy.context.scene.objects:
    if obj.type == 'MESH':
        obj.select_set(True)
bpy.ops.export_dff.dff_export(
    filepath='{output_path}',
    export_version='3.4.0.0',
    export_collision=False
)
        """
        
        script_path = self.temp_dir / "convert.py"
        script_path.write_text(script)
        subprocess.run(["blender", "--background", "--python", str(script_path)], check=True)
        script_path.unlink(missing_ok=True)
        return output_path

    def _textures_to_txd(self, texture_folder, txd_name):
        txd_path = self.output_dir / f"{txd_name}.txd"
        dds_folder = self.temp_dir / "dds_temp"
        dds_folder.mkdir(exist_ok=True)

        for img in Path(texture_folder).rglob("*"):
            if img.suffix.lower() in ['.png', '.jpg', '.tga', '.dds']:
                shutil.copy(img, dds_folder / img.name)

        subprocess.run([
            "magic-txd-cli", "create",
            "--input", str(dds_folder),
            "--output", str(txd_path),
            "--game", "sa"
        ], check=True)

        shutil.rmtree(dds_folder, ignore_errors=True)
        return txd_path

    def beamng_full(self, input_path):
        """Конверт BeamNG: .dae или .jbeam"""
        inp = Path(input_path)
        
        if inp.suffix == '.dae':
            obj_path = self.temp_dir / f"{inp.stem}.obj"
            mesh = trimesh.load(inp, force='mesh')
            mesh.export(obj_path, file_type='obj')
            dff = self._blender_to_dff(obj_path, inp.stem)
            print(f"[+] DFF готов: {dff}")
            return dff
            
        elif inp.suffix == '.jbeam':
            name, mesh_files, textures = self._parse_jbeam(inp)
            obj_paths = []
            for m in mesh_files:
                p = self._mesh_to_obj(m)
                if p:
                    obj_paths.append(p)
            
            if obj_paths:
                merged = trimesh.util.concatenate([trimesh.load(p) for p in obj_paths])
                merged_path = self.temp_dir / f"{name}_merged.obj"
                merged.export(merged_path)
                dff = self._blender_to_dff(merged_path, name)
                print(f"[+] DFF готов: {dff}")
                return dff
        else:
            print(f"[!] Формат не поддерживается: {inp.suffix}")

    def gta5_full(self, model_path, texture_path=None):
        """Конверт GTA V: .yft/.ydr + .ytd"""
        model = Path(model_path)
        
        # Распаковка модели
        extract_dir = self.temp_dir / f"ext_{model.stem}"
        extract_dir.mkdir(exist_ok=True)
        
        subprocess.run([
            "Codewalker.CLI", "extract",
            "-i", str(model),
            "-o", str(extract_dir),
            "-f", "obj"
        ], check=True)
        
        obj_files = list(extract_dir.glob("*.obj"))
        if not obj_files:
            raise FileNotFoundError("OBJ не извлечён")
        
        dff = self._blender_to_dff(obj_files[0], model.stem)
        print(f"[+] DFF: {dff}")
        
        # Текстуры
        if texture_path:
            tex_dir = self.temp_dir / f"tex_{Path(texture_path).stem}"
            tex_dir.mkdir(exist_ok=True)
            
            subprocess.run([
                "RageLibConsole", "extract",
                "-i", str(texture_path),
                "-o", str(tex_dir),
                "-f", "png"
            ], check=True)
            
            txd = self._textures_to_txd(tex_dir, model.stem)
            print(f"[+] TXD: {txd}")
            return dff, txd
        
        return dff


# ===== ТОЧКА ВХОДА ДЛЯ ТЕЛЕГРАМ-БОТА =====
# 8613630902:AAEHjhOWk9VDJKer1dYbEIdnvaLwLSavdy0

TOKEN = "8613630902:AAEHjhOWk9VDJKer1dYbEIdnvaLwLSavdy0"

try:
    import telebot
    bot = telebot.TeleBot(TOKEN)
    converter = FullModelConverter()

    @bot.message_handler(commands=['start'])
    def start(msg):
        bot.reply_to(msg, "Кидай .dae / .jbeam (BeamNG) или .yft / .ydr + .ytd (GTA V) — сконвертирую в .dff и .txd")

    @bot.message_handler(content_types=['document'])
    def handle_file(msg):
        file_info = bot.get_file(msg.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        fname = msg.document.file_name
        with open(fname, 'wb') as f:
            f.write(downloaded)
        
        bot.reply_to(msg, "Конвертирую...")
        
        try:
            if fname.endswith(('.dae', '.jbeam')):
                dff = converter.beamng_full(fname)
                with open(dff, 'rb') as f:
                    bot.send_document(msg.chat.id, f)
                    
            elif fname.endswith(('.yft', '.ydr')):
                dff = converter.gta5_full(fname)
                with open(dff, 'rb') as f:
                    bot.send_document(msg.chat.id, f)
        except Exception as e:
            bot.reply_to(msg, f"Ошибка: {e}")

    print("[>] Бот запущен")
    bot.polling()

except ImportError:
    print("Telebot не установлен. Работаю как CLI-скрипт.")
    print("python bot.py <файл>")
```
