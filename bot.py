import os
import random
import shutil
import io
import time
import threading
from pathlib import Path

from PIL import Image
import telebot
from telebot import types

# =========================
# CONFIG
# =========================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise Exception("BOT_TOKEN не найден!")

CHANNEL_ID = "@brmodels095"
CHANNEL_URL = "https://t.me/brmodels095"
SUPPORT_USERNAME = "@brmodels013"

bot = telebot.TeleBot(TOKEN, parse_mode="Markdown")

user_files = {}
user_agreed = {}

# =========================
# HELPERS
# =========================

def safe_remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except:
        pass


def analyze_file(file_path):
    try:
        ext = Path(file_path).suffix.lower()
        verts = 0
        faces = 0

        if ext == ".obj":
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("v "):
                        verts += 1
                    elif line.startswith("f "):
                        faces += 1

        if verts > 65535:
            verdict = "Тяжёлая модель"
        elif verts > 40000:
            verdict = "Средняя модель"
        else:
            verdict = "Лёгкая модель"

        return {
            "ext": ext,
            "verts": verts,
            "faces": faces,
            "verdict": verdict
        }

    except Exception as e:
        print("ANALYZE ERROR:", e)
        return None


# =========================
# CONVERTER
# =========================

class FullModelConverter:

    def __init__(self):
        self.output_dir = Path("converted_output")
        self.temp_dir = Path("temp_processing")

        self.output_dir.mkdir(exist_ok=True, parents=True)
        self.temp_dir.mkdir(exist_ok=True, parents=True)

    # =========================
    # PNG -> BTX
    # =========================

    def png_to_btx(self, png_path, output_name=None):

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

        with open(btx_path, "wb") as f:

            f.write(b"BTX\x00")

            f.write(compressed.width.to_bytes(2, "little"))
            f.write(compressed.height.to_bytes(2, "little"))

            f.write(b"\x01")
            f.write(b"\x03")

            f.write(compressed.tobytes())

        return btx_path

    # =========================
    # DAMAGE OBJ
    # =========================

    def damage_obj(
        self,
        obj_path,
        mtl_path=None,
        intensity=0.20,
        num_dents=8
    ):

        with open(obj_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.read().splitlines()

        # удаляем старые normal / mtllib
        lines = [
            l for l in lines
            if not l.startswith("mtllib ")
            and not l.startswith("vn ")
        ]

        vert_entries = []

        for i, line in enumerate(lines):

            if line.startswith("v ") and not line.startswith("vt "):

                parts = line.strip().split()

                if len(parts) >= 4:
                    try:
                        vert_entries.append([
                            i,
                            float(parts[1]),
                            float(parts[2]),
                            float(parts[3])
                        ])
                    except:
                        pass

        if len(vert_entries) < 10:
            raise Exception("Слишком мало вершин")

        if len(vert_entries) > 120000:
            raise Exception("Слишком тяжёлая модель")

        all_x = [v[1] for v in vert_entries]
        all_y = [v[2] for v in vert_entries]
        all_z = [v[3] for v in vert_entries]

        min_x = min(all_x)
        max_x = max(all_x)

        min_y = min(all_y)
        max_y = max(all_y)

        min_z = min(all_z)
        max_z = max(all_z)

        mid_x = (min_x + max_x) / 2
        mid_y = (min_y + max_y) / 2
        mid_z = (min_z + max_z) / 2

        size_x = max_x - min_x
        size_y = max_y - min_y
        size_z = max_z - min_z

        # axis

        if size_x >= size_y and size_x >= size_z:
            push_axis = "x"

        elif size_y >= size_z:
            push_axis = "y"

        else:
            push_axis = "z"

        edge = 0.25

        def is_edge(x, y, z):

            return (
                abs(x - min_x) < size_x * edge
                or abs(x - max_x) < size_x * edge
                or abs(y - min_y) < size_y * edge
                or abs(y - max_y) < size_y * edge
                or abs(z - min_z) < size_z * edge
                or abs(z - max_z) < size_z * edge
            )

        main_radius = max(size_x, size_y, size_z) * random.uniform(0.3, 0.5)

        main_damaged = 0

        max_push = 0.5

        # main dent

        for entry in vert_entries:

            idx, x, y, z = entry

            dx = x - mid_x
            dy = y - mid_y
            dz = z - mid_z

            dist = (dx * dx + dy * dy + dz * dz) ** 0.5

            if dist < main_radius and not is_edge(x, y, z):

                force = min(
                    (
                        (1 - dist / main_radius)
                        * intensity
                        * random.uniform(0.8, 1.3)
                    ),
                    max_push
                )

                self.push_vertex(
                    lines,
                    idx,
                    x,
                    y,
                    z,
                    force,
                    push_axis
                )

                main_damaged += 1

        # extra dents

        for _ in range(num_dents):

            cx = random.uniform(
                min_x + size_x * edge,
                max_x - size_x * edge
            )

            cy = random.uniform(
                min_y + size_y * edge,
                max_y - size_y * edge
            )

            cz = random.uniform(
                min_z + size_z * edge,
                max_z - size_z * edge
            )

            small_radius = max(size_x, size_y, size_z) * random.uniform(0.08, 0.18)

            for entry in vert_entries:

                idx, x, y, z = entry

                dx = x - cx
                dy = y - cy
                dz = z - cz

                dist = (dx * dx + dy * dy + dz * dz) ** 0.5

                if dist < small_radius and not is_edge(x, y, z):

                    force = min(
                        (
                            (1 - dist / small_radius)
                            * intensity
                            * 0.5
                            * random.uniform(0.5, 1.5)
                        ),
                        max_push
                    )

                    self.push_vertex(
                        lines,
                        idx,
                        x,
                        y,
                        z,
                        force,
                        push_axis
                    )

        # collect verts

        final_verts = []

        for line in lines:

            if line.startswith("v ") and not line.startswith("vt "):

                parts = line.strip().split()

                if len(parts) >= 4:
                    try:
                        final_verts.append([
                            float(parts[1]),
                            float(parts[2]),
                            float(parts[3])
                        ])
                    except:
                        pass

        # faces

        final_faces = []

        for line in lines:

            if line.startswith("f "):

                parts = line.strip().split()

                face = []

                for p in parts[1:]:

                    try:

                        raw_idx = int(p.split("/")[0])

                        if raw_idx < 0:
                            idx = len(final_verts) + raw_idx
                        else:
                            idx = raw_idx - 1

                        if 0 <= idx < len(final_verts):
                            face.append(idx)

                    except:
                        pass

                if len(face) >= 3:
                    final_faces.append(face[:3])

        # normals

        vertex_normals = [
            [0.0, 0.0, 0.0]
            for _ in final_verts
        ]

        for face in final_faces:

            try:

                v0 = final_verts[face[0]]
                v1 = final_verts[face[1]]
                v2 = final_verts[face[2]]

                e1 = [
                    v1[0] - v0[0],
                    v1[1] - v0[1],
                    v1[2] - v0[2]
                ]

                e2 = [
                    v2[0] - v0[0],
                    v2[1] - v0[1],
                    v2[2] - v0[2]
                ]

                nx = e1[1] * e2[2] - e1[2] * e2[1]
                ny = e1[2] * e2[0] - e1[0] * e2[2]
                nz = e1[0] * e2[1] - e1[1] * e2[0]

                length = (nx * nx + ny * ny + nz * nz) ** 0.5

                if length > 0.000001:
                    nx /= length
                    ny /= length
                    nz /= length
                else:
                    nx, ny, nz = 0.0, 1.0, 0.0

                for fi in face:

                    vertex_normals[fi][0] += nx
                    vertex_normals[fi][1] += ny
                    vertex_normals[fi][2] += nz

            except:
                pass

        # normalize

        for i in range(len(vertex_normals)):

            n = vertex_normals[i]

            length = (
                n[0] ** 2 +
                n[1] ** 2 +
                n[2] ** 2
            ) ** 0.5

            if length > 0.000001:
                n[0] /= length
                n[1] /= length
                n[2] /= length
            else:
                n[0], n[1], n[2] = 0.0, 1.0, 0.0

        # append vn

        for n in vertex_normals:
            lines.append(
                f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}"
            )

        # rewrite faces

        max_vert = len(final_verts)

        for i, line in enumerate(lines):

            if line.startswith("f "):

                parts = line.strip().split()

                new_face = ["f"]

                valid = True

                for p in parts[1:]:

                    try:

                        raw_idx = int(p.split("/")[0])

                        if raw_idx < 0:
                            v_idx = max_vert + raw_idx + 1
                        else:
                            v_idx = raw_idx

                        if v_idx < 1 or v_idx > max_vert:
                            valid = False
                            break

                        new_face.append(f"{v_idx}//{v_idx}")

                    except:
                        valid = False
                        break

                if valid:
                    lines[i] = " ".join(new_face)
                else:
                    lines[i] = ""

        # clean — убираем всё что может сломать ZModeler
        cleaned = []
        for l in lines:
            l = l.strip()
            if not l:
                continue
            if l[0] not in ('v', 'f', 'm', 'u', '#'):
                continue
            cleaned.append(l)
        lines = cleaned

        damaged_name = f"{Path(obj_path).stem}_damaged"

        out_path = self.output_dir / f"{damaged_name}.obj"

        # mtl

        if mtl_path and os.path.exists(mtl_path):

            new_mtl_name = f"{damaged_name}.mtl"

            new_mtl_path = self.output_dir / new_mtl_name

            shutil.copy(mtl_path, new_mtl_path)

            lines.insert(0, f"mtllib {new_mtl_name}")

        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return out_path, 1 + num_dents, main_damaged

    # =========================
    # PUSH VERTEX
    # =========================

    def push_vertex(self, lines, idx, x, y, z, force, axis):

        if axis == "x":

            new_x = x - force if x > 0 else x + force

            new_y = y + random.uniform(-force * 0.2, force * 0.2)

            new_z = z + random.uniform(-force * 0.2, force * 0.2)

        elif axis == "y":

            new_y = y - force

            new_x = x + random.uniform(-force * 0.2, force * 0.2)

            new_z = z + random.uniform(-force * 0.2, force * 0.2)

        else:

            new_z = z - force

            new_x = x + random.uniform(-force * 0.2, force * 0.2)

            new_y = y + random.uniform(-force * 0.2, force * 0.2)

        lines[idx] = (
            f"v {new_x:.6f} {new_y:.6f} {new_z:.6f}"
        )

    # =========================
    # XML
    # =========================

    def generate_xml(
        self,
        car_name,
        obj_name,
        texture_names
    ):

        xml = '<?xml version="1.0" encoding="utf-8"?>\n'

        xml += f'<Car name="{car_name}">\n'
        xml += '  <Case>\n'
        xml += f'    <Render object="{obj_name}">\n'

        for tex in texture_names:
            xml += f'      <Texture name="{tex}"/>\n'

        xml += '    </Render>\n'
        xml += '  </Case>\n'
        xml += '</Car>'

        xml_path = self.output_dir / f"{car_name}.xml"

        xml_path.write_text(xml, encoding="utf-8")

        return xml_path


converter = FullModelConverter()

# =========================
# SUB
# =========================

def check_subscription(user_id):

    try:

        member = bot.get_chat_member(CHANNEL_ID, user_id)

        return member.status in [
            "member",
            "administrator",
            "creator"
        ]

    except Exception as e:
        print("SUB ERROR:", e)
        return False


def send_subscription_message(chat_id):

    markup = types.InlineKeyboardMarkup(row_width=1)

    markup.add(
        types.InlineKeyboardButton(
            "📢 Подписаться",
            url=CHANNEL_URL
        ),
        types.InlineKeyboardButton(
            "✅ Проверить подписку",
            callback_data="check_sub"
        )
    )

    bot.send_message(
        chat_id,
        f"🔒 Подпишитесь:\n{CHANNEL_URL}",
        reply_markup=markup
    )


# =========================
# AGREEMENT
# =========================

def send_agreement(chat_id):

    markup = types.InlineKeyboardMarkup(row_width=1)

    markup.add(
        types.InlineKeyboardButton(
            "✅ Принимаю",
            callback_data="agree_yes"
        ),
        types.InlineKeyboardButton(
            "❌ Отказываюсь",
            callback_data="agree_no"
        )
    )

    bot.send_message(
        chat_id,
        (
            "📋 *Пользовательское соглашение*\n\n"
            "✅ *Можно:* GTA SA, GTA V, LibertyCity, BeamNG, CRMP\n"
            "⚠️ *Black Russia:* запрещено, риск бана\n"
            "🛡 Ответственность на пользователе.\n\n"
            "1. Вы имеете право изменять файлы\n"
            "2. Не нарушаете авторские права\n"
            "3. Используете бот на свой риск\n"
        ),
        reply_markup=markup
    )


# =========================
# KEYBOARDS
# =========================

def get_menu_keyboard():

    markup = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )

    markup.add(
        types.KeyboardButton("🎨 Конвертировать"),
        types.KeyboardButton("🚗 Повредить"),
        types.KeyboardButton("📄 Создать XML"),
        types.KeyboardButton("📋 Инструкция"),
        types.KeyboardButton("🆘 Техподдержка"),
        types.KeyboardButton("🗑 Очистить"),
        types.KeyboardButton("🔍 Анализ")
    )

    return markup


def get_damage_level_keyboard():

    markup = types.InlineKeyboardMarkup(row_width=1)

    markup.add(
        types.InlineKeyboardButton(
            "🤏 Мелкие",
            callback_data="dmg_light"
        ),
        types.InlineKeyboardButton(
            "💪 Средние",
            callback_data="dmg_medium"
        ),
        types.InlineKeyboardButton(
            "💥 Авария",
            callback_data="dmg_hard"
        ),
        types.InlineKeyboardButton(
            "🔥 Хлам",
            callback_data="dmg_extreme"
        )
    )

    return markup


# =========================
# DAMAGE PROCESS
# =========================

def process_damage(uid, cid, level="medium"):

    if uid not in user_files or not user_files[uid]:
        bot.send_message(cid, "❌ Нет файлов")
        return

    settings = {
        "light": {
            "intensity": 0.08,
            "dents": 5,
            "label": "Мелкие",
            "icon": "🤏"
        },

        "medium": {
            "intensity": 0.20,
            "dents": 8,
            "label": "Средние",
            "icon": "💪"
        },

        "hard": {
            "intensity": 0.40,
            "dents": 12,
            "label": "Авария",
            "icon": "💥"
        },

        "extreme": {
            "intensity": 0.60,
            "dents": 16,
            "label": "Хлам",
            "icon": "🔥"
        }
    }

    s = settings.get(level, settings["medium"])

    status_msg = bot.send_message(
        cid,
        "🔧 Обработка..."
    )

    def worker():

        obj_file = None
        mtl_file = None

        for fp in user_files[uid]:

            ext = Path(fp).suffix.lower()

            if ext == ".obj":
                obj_file = fp

            elif ext == ".mtl":
                mtl_file = fp

        if not obj_file:
            bot.send_message(uid, "❌ Нужен OBJ")
            return

        try:

            damaged, total_dents, main_verts = converter.damage_obj(
                obj_file,
                mtl_file,
                intensity=s["intensity"],
                num_dents=s["dents"]
            )

            with open(damaged, "rb") as f:
                bot.send_document(
                    uid,
                    f,
                    caption=f"{s['icon']} {s['label']}"
                )

            mtl_out = (
                converter.output_dir /
                f"{Path(obj_file).stem}_damaged.mtl"
            )

            if mtl_out.exists():

                with open(mtl_out, "rb") as f:
                    bot.send_document(
                        uid,
                        f,
                        caption="📄 MTL"
                    )

            bot.send_message(
                uid,
                (
                    f"✅ Готово\n\n"
                    f"Вмятин: {total_dents}\n"
                    f"Вершин: ~{main_verts}"
                )
            )

        except Exception as e:

            print("DAMAGE ERROR:", e)

            bot.send_message(
                uid,
                f"❌ Ошибка:\n{e}"
            )

    threading.Thread(target=worker).start()

    try:
        bot.edit_message_text(
            "✅ Запущено",
            cid,
            status_msg.message_id
        )
    except:
        pass


# =========================
# START
# =========================

@bot.message_handler(commands=["start"])
def start(msg):

    uid = msg.from_user.id

    if not check_subscription(uid):
        send_subscription_message(msg.chat.id)
        return

    if uid not in user_agreed:
        send_agreement(msg.chat.id)
        return

    user_files[uid] = []

    bot.reply_to(
        msg,
        (
            "🔧 *Бот для модов*\n\n"
            "🎨 PNG → BTX\n"
            "🚗 Повреждение OBJ\n"
            "📄 XML генератор"
        ),
        reply_markup=get_menu_keyboard()
    )


# =========================
# AGREEMENT CALLBACK
# =========================

@bot.callback_query_handler(func=lambda c: c.data.startswith("agree_"))
def agreement_callback(call):

    uid = call.from_user.id

    if call.data == "agree_yes":

        user_agreed[uid] = True
        user_files[uid] = []

        bot.answer_callback_query(
            call.id,
            "✅ Принято"
        )

        bot.edit_message_text(
            "✅ Доступ открыт",
            call.message.chat.id,
            call.message.message_id
        )

    else:

        bot.answer_callback_query(
            call.id,
            "❌ Доступ запрещён",
            show_alert=True
        )


# =========================
# CHECK SUB
# =========================

@bot.callback_query_handler(func=lambda c: c.data == "check_sub")
def check_sub_callback(call):

    if check_subscription(call.from_user.id):

        bot.answer_callback_query(
            call.id,
            "✅ Подписка есть"
        )

        try:
            bot.edit_message_text(
                "✅ Проверено",
                call.message.chat.id,
                call.message.message_id
            )
        except:
            pass

    else:

        bot.answer_callback_query(
            call.id,
            "❌ Нет подписки",
            show_alert=True
        )


# =========================
# DAMAGE CALLBACK
# =========================

@bot.callback_query_handler(func=lambda c: c.data.startswith("dmg_"))
def damage_level_callback(call):

    uid = call.from_user.id

    level = call.data.replace("dmg_", "")

    bot.answer_callback_query(
        call.id,
        "✅ Начинаю"
    )

    process_damage(uid, call.message.chat.id, level)


# =========================
# FILES
# =========================

@bot.message_handler(content_types=["document"])
def handle_file(msg):

    uid = msg.from_user.id

    if not check_subscription(uid):
        send_subscription_message(msg.chat.id)
        return

    if uid not in user_agreed:
        send_agreement(msg.chat.id)
        return

    file_info = bot.get_file(msg.document.file_id)

    downloaded = bot.download_file(file_info.file_path)

    fname = msg.document.file_name

    user_dir = Path("user_files") / str(uid)
    user_dir.mkdir(parents=True, exist_ok=True)

    save_path = user_dir / fname

    with open(save_path, "wb") as f:
        f.write(downloaded)

    if uid not in user_files:
        user_files[uid] = []

    user_files[uid].append(str(save_path))

    info = analyze_file(str(save_path))

    txt = f"📁 {fname}"

    if info:
        txt += (
            f"\n\n"
            f"Вершин: {info['verts']}\n"
            f"Полигонов: {info['faces']}\n"
            f"{info['verdict']}"
        )

    bot.reply_to(
        msg,
        txt,
        reply_markup=get_menu_keyboard()
    )


# =========================
# BUTTONS
# =========================

@bot.message_handler(func=lambda m: m.text == "🚗 Повредить")
def damage_cmd(msg):

    uid = msg.from_user.id

    if uid not in user_files or not user_files[uid]:

        bot.reply_to(
            msg,
            "❌ Сначала отправьте OBJ + MTL"
        )

        return

    bot.reply_to(
        msg,
        "💥 Выберите уровень:",
        reply_markup=get_damage_level_keyboard()
    )


@bot.message_handler(func=lambda m: m.text == "🎨 Конвертировать")
def convert_cmd(msg):

    uid = msg.from_user.id

    if uid not in user_files:
        return

    found = False

    for fp in user_files[uid]:

        try:

            if Path(fp).suffix.lower() == ".png":

                found = True

                btx = converter.png_to_btx(fp)

                with open(btx, "rb") as f:
                    bot.send_document(
                        uid,
                        f,
                        caption="✅ BTX"
                    )

        except Exception as e:

            bot.send_message(
                uid,
                f"❌ Ошибка:\n{e}"
            )

    if not found:
        bot.send_message(uid, "❌ PNG не найден")


@bot.message_handler(func=lambda m: m.text == "📄 Создать XML")
def xml_cmd(msg):

    uid = msg.from_user.id

    if uid not in user_files:
        return

    obj_file = None
    png_names = []

    for fp in user_files[uid]:

        ext = Path(fp).suffix.lower()

        if ext == ".obj":
            obj_file = fp

        elif ext == ".png":
            png_names.append(Path(fp).stem)

    if not obj_file:
        bot.reply_to(msg, "❌ Нужен OBJ")
        return

    xml_path = converter.generate_xml(
        Path(obj_file).stem,
        os.path.basename(obj_file),
        png_names
    )

    with open(xml_path, "rb") as f:

        bot.send_document(
            uid,
            f,
            caption="✅ XML"
        )


@bot.message_handler(func=lambda m: m.text == "🔍 Анализ")
def analyze_cmd(msg):

    uid = msg.from_user.id

    if uid not in user_files:
        return

    for fp in user_files[uid]:

        if not os.path.exists(fp):
            continue

        info = analyze_file(fp)

        if info:

            bot.reply_to(
                msg,
                (
                    f"📊 {os.path.basename(fp)}\n\n"
                    f"Вершин: {info['verts']}\n"
                    f"Полигонов: {info['faces']}\n"
                    f"{info['verdict']}"
                )
            )


@bot.message_handler(func=lambda m: m.text == "📋 Инструкция")
def instruction_cmd(msg):

    bot.reply_to(
        msg,
        (
            "📋 *Инструкция*\n\n"
            "1. Экспортируй OBJ из ZModeler 2.5\n"
            "2. Отправь OBJ + MTL в бота\n"
            "3. Нажми 🚗 Повредить\n"
            "4. Выбери уровень\n"
            "5. Скачай результат\n"
            "6. Открой в ZModeler → Export DFF"
        ),
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.text == "🗑 Очистить")
def clear_cmd(msg):

    uid = msg.from_user.id

    if uid in user_files:

        for f in user_files[uid]:
            safe_remove(f)

        user_files[uid] = []

    bot.reply_to(msg, "🗑 Очищено")


@bot.message_handler(func=lambda m: m.text == "🆘 Техподдержка")
def support_cmd(msg):

    markup = types.InlineKeyboardMarkup()

    markup.add(
        types.InlineKeyboardButton(
            "📩 Написать",
            url=f"https://t.me/{SUPPORT_USERNAME.replace('@', '')}"
        )
    )

    bot.reply_to(
        msg,
        f"Техподдержка: {SUPPORT_USERNAME}",
        reply_markup=markup
    )


# =========================
# DEFAULT
# =========================

@bot.message_handler(func=lambda m: True)
def any_msg(msg):

    bot.reply_to(
        msg,
        "💬 Используйте меню",
        reply_markup=get_menu_keyboard()
    )


# =========================
# START BOT
# =========================

print("[>] Бот запущен")

while True:

    try:

        bot.infinity_polling(
            timeout=60,
            long_polling_timeout=60
        )

    except Exception as e:

        print("POLLING ERROR:", e)

        time.sleep(5)
