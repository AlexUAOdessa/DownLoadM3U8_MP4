import os
import requests
import subprocess
import time
from io import BytesIO

# Функция для скачивания сегмента и возвращения его данных


def download_segment(url, timeout=60, current_segment=1, total_segments=1, series_number=""):
    while True:
        start_time = time.time()
        try:
            response = requests.get(url, stream=True, timeout=timeout)
            response.raise_for_status()  # Проверка на ошибки HTTP
            segment_data = BytesIO(response.content)
            elapsed_time = time.time() - start_time

            # Выводим информацию о загрузке сегмента
            print(f"Серия {series_number}, сегмент {
                  current_segment}/{total_segments} из {url} загружен за {elapsed_time:.2f} секунд")
            return segment_data

        except (requests.RequestException, Exception) as e:
            print(f"\nОшибка при скачивании {url}: {e}")
            time.sleep(5)  # Подождем перед повторной попыткой

# Функция для скачивания m3u8 файла


def download_m3u8(m3u8_url, output_path):
    try:
        response = requests.get(m3u8_url)
        response.raise_for_status()  # Проверка на ошибки HTTP
        with open(output_path, 'w') as f:
            f.write(response.text)
    except requests.RequestException as e:
        print(f"Ошибка при скачивании m3u8 файла: {e}")

# Функция для парсинга m3u8 файла


def parse_m3u8(m3u8_file):
    segments = []
    with open(m3u8_file, 'r') as f:
        lines = f.readlines()
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            segments.append(line)
    return segments


# Основной блок для обработки ссылок
if __name__ == "__main__":
    # Создание директории для сохранения итоговых MP4 файлов
    if not os.path.exists('film'):
        os.makedirs('film')
    if not os.path.exists('ts'):
        os.makedirs('ts')

    # Чтение ссылок из файла
    with open('downloads.txt', 'r') as file:
        lines = file.readlines()

    # Обработка каждой ссылки
    for index, line in enumerate(lines, start=1):
        url, series_number = line.strip().split()
        m3u8_file_path = f'film/{series_number}.m3u8'
        mp4_file_path = f'film/{series_number}.mp4'

        # Скачивание m3u8 файла
        print(f'Скачивание m3u8 файла для серии {series_number}...')
        download_m3u8(url, m3u8_file_path)

        # Чтение ссылок на сегменты из m3u8 файла
        segments = parse_m3u8(m3u8_file_path)
        base_url = os.path.dirname(url)  # Извлечение базового URL
        total_segments = len(segments)

        start_series_time = time.time()

        # Создание файла filelist.txt
        with open('filelist.txt', 'w') as filelist:
            segment_files = []
            for i, segment in enumerate(segments):
                segment_url = f"{base_url}/{segment}".replace(' ', '%20')
                segment_data = download_segment(
                    segment_url, current_segment=i+1, total_segments=total_segments, series_number=series_number)

                segment_file_path = f'ts/{series_number}_{segment}.ts'
                # Записываем данные сегмента в файл и в список файлов
                with open(segment_file_path, 'wb') as segment_file:
                    segment_file.write(segment_data.getbuffer())
                    filelist.write(f"file '{segment_file_path}'\n")
                    segment_files.append(segment_file_path)

        # Выполнение команды ffmpeg
        command = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'filelist.txt', '-c', 'copy', mp4_file_path
        ]
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode != 0:
            print(f"Ошибка при конвертации: {result.stderr}")
        else:
            print(f"Конвертация завершена: {mp4_file_path}")

        # Удаление временного m3u8 файла и сегментов
        os.remove(m3u8_file_path)
        for segment_file in segment_files:
            os.remove(segment_file)

        os.remove('filelist.txt')  # Удаление временного файла filelist.txt

        # Вывод информации о завершенной загрузке
        elapsed_series_time = time.time() - start_series_time
        remaining_files = len(lines) - index
        print(f'Завершена загрузка: {mp4_file_path}. Осталось {
              remaining_files} файлов. Общее время: {elapsed_series_time:.2f} секунд.')
