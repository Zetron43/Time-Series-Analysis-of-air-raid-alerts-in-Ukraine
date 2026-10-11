FROM python:3.13-slim

# Встановлюємо системні шрифти для коректного рендерингу зображень Pillow на Linux
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копіюємо та встановлюємо залежності
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо код проєкту
COPY . .

# Запуск бота
CMD ["python", "bot.py"]
