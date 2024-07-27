import os
import requests
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

# Функция для скачивания файла с повторами
def download_file(url, file_path, timeout=60):
    while True:
        start_time = time.time()
        downloaded_size = 0
        try:
            response = requests.get(url, stream=True, timeout=timeout)
            response.raise_for_status()  # Проверка на ошибки HTTP
            total_size = int(response.headers.get('content-length', 0))

            with open(file_path, 'wb') as file:
                for data in response.iter_content(chunk_size=1024):
                    if time.time() - start_time > timeout:
                        raise Exception("Загрузка прервана, слишком долго")
                    file.write(data)
                    downloaded_size += len(data)
                    done = int(50 * downloaded_size / total_size)
                    percent_done = (downloaded_size / total_size) * 100
                    elapsed_time = time.time() - start_time
                    speed = downloaded_size / elapsed_time if elapsed_time > 0 else 0

                    # Форматирование строки
                    print(f"\rЗагрузка {file_path}: {downloaded_size / (1024 * 1024):.2f} MB из {total_size / (1024 * 1024):.2f} MB): [{'#' * done}{'.' * (50 - done)}] {percent_done:.2f}%", end='')

                print()  # Завершение строки после завершения загрузки
            return True  # Успешная загрузка
        except (requests.RequestException, Exception) as e:
            print(f"\nОшибка при скачивании {file_path}: {e}")
            if os.path.exists(file_path):
                os.remove(file_path)
            time.sleep(5)  # Подождем перед повторной попыткой

# Функция для конвертации файлов сегментов в mp4
def convert_segments_to_mp4(segment_files, mp4_file):
    try:
        # Создание файла filelist.txt
        with open('filelist.txt', 'w') as filelist:
            for segment_file in segment_files:
                filelist.write(f"file '{segment_file}'\n")

        # Вывод содержимого filelist.txt для отладки
        print("Содержимое filelist.txt:")
        with open('filelist.txt', 'r') as filelist:
            print(filelist.read())

        # Выполнение команды ffmpeg
        command = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'filelist.txt', '-c', 'copy', mp4_file]
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode != 0:
            print(f"Ошибка при конвертации: {result.stderr}")
        else:
            print(f"Конвертация завершена: {mp4_file}")
    except subprocess.CalledProcessError as e:
        print(f"Ошибка при конвертации сегментов в {mp4_file}: {e}")
    except Exception as e:
        print(f"Неизвестная ошибка при конвертации сегментов в {mp4_file}: {e}")
    finally:
        os.remove('filelist.txt')  # Удаление временного файла

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

# Функция для многопоточного скачивания сегментов
def download_segments(segments, base_url, output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for i, segment in enumerate(segments):
            segment_url = f"{base_url}/{segment}".replace(' ', '%20')
            segment_path = os.path.join(output_dir, segment)
            futures.append(executor.submit(download_file, segment_url, segment_path))

        for future in futures:
            future.result()  # Дожидаемся завершения всех потоков

# Основной блок для обработки ссылок
if __name__ == "__main__":
    # Создание директорий для сохранения файлов
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
        segment_files = []
        mp4_file_path = f'film/{series_number}.mp4'

        # Скачивание m3u8 файла
        print(f'Скачивание m3u8 файла для серии {series_number}...')
        download_file(url, m3u8_file_path)

        # Чтение ссылок на сегменты из m3u8 файла
        segments = parse_m3u8(m3u8_file_path)
        base_url = os.path.dirname(url)  # Извлечение базового URL
        for i, segment in enumerate(segments):
            segment_url = f"{base_url}/{segment}".replace(' ', '%20')
            segment_file_path = f'ts/{series_number}_{i}.ts'
            segment_files.append(segment_file_path)

        # Скачивание сегментов многопоточно
        print(f'Скачивание сегментов для серии {series_number}...')
        download_segments(segments, base_url, 'ts')

        # Конвертация сегментов в mp4
        print(f'Конвертация серии {series_number}...')
        convert_segments_to_mp4(segment_files, mp4_file_path)

        # Удаление временного m3u8 файла и сегментов
        os.remove(m3u8_file_path)
        for segment_file in segment_files:
            os.remove(segment_file)

        # Вывод информации о завершенной загрузке
        remaining_files = len(lines) - index
        print(f'Завершена загрузка: {mp4_file_path}. Осталось {remaining_files} файлов.')
