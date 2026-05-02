import telebot

TOKEN = "8613630902:AAEehO6bqcVhU6gN77hVTfDz7kE0YPPGcKg"

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start(msg):
    bot.reply_to(msg, "Привет! Я работаю!")

@bot.message_handler(content_types=['document'])
def handle_file(msg):
    bot.reply_to(msg, "Файл получил!")

print("[>] Бот запущен")
bot.polling()
