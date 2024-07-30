package main

import (
	"bufio"
	"bytes"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const maxConcurrentDownloads = 6 // Константа для количества потоков

// Функция для скачивания сегмента и возвращения его данных
func downloadSegment(url string, timeout time.Duration, currentSegment, totalSegments int, seriesNumber string) ([]byte, error) {
	for {
		startTime := time.Now()
		client := http.Client{
			Timeout: timeout,
		}

		resp, err := client.Get(url)
		if err != nil {
			fmt.Printf("\nОшибка при скачивании %s: %v\n", url, err)
			time.Sleep(5 * time.Second)
			continue
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			fmt.Printf("\nОшибка при скачивании %s: статус %s\n", url, resp.Status)
			time.Sleep(5 * time.Second)
			continue
		}

		segmentData, err := io.ReadAll(resp.Body)
		if err != nil {
			fmt.Printf("\nОшибка при чтении данных %s: %v\n", url, err)
			time.Sleep(5 * time.Second)
			continue
		}

		elapsedTime := time.Since(startTime).Seconds()
		fmt.Printf("Серия %s, сегмент %d/%d из %s загружен за %.2f секунд\n", seriesNumber, currentSegment, totalSegments, url, elapsedTime)
		return segmentData, nil
	}
}

// Функция для скачивания m3u8 файла
func downloadM3u8(m3u8URL, outputPath string) error {
	resp, err := http.Get(m3u8URL)
	if err != nil {
		return fmt.Errorf("ошибка при скачивании m3u8 файла: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("ошибка при скачивании m3u8 файла: статус %s", resp.Status)
	}

	file, err := os.Create(outputPath)
	if err != nil {
		return fmt.Errorf("ошибка при создании файла %s: %v", outputPath, err)
	}
	defer file.Close()

	_, err = io.Copy(file, resp.Body)
	if err != nil {
		return fmt.Errorf("ошибка при сохранении m3u8 файла: %v", err)
	}

	return nil
}

// Функция для парсинга m3u8 файла
func parseM3u8(m3u8File string) ([]string, error) {
	file, err := os.Open(m3u8File)
	if err != nil {
		return nil, fmt.Errorf("ошибка при открытии файла %s: %v", m3u8File, err)
	}
	defer file.Close()

	var segments []string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		segments = append(segments, line)
	}

	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("ошибка при чтении файла %s: %v", m3u8File, err)
	}

	return segments, nil
}

// Функция для многопоточного скачивания сегментов
func downloadSegmentsConcurrently(baseURL string, segments []string, seriesNumber string, wg *sync.WaitGroup, semaphore chan struct{}) {
	defer wg.Done()

	for i, segment := range segments {
		semaphore <- struct{}{}
		go func(i int, segment string) {
			defer func() { <-semaphore }()

			segmentURL := fmt.Sprintf("%s%s", baseURL, segment)
			segmentData, err := downloadSegment(segmentURL, 60*time.Second, i+1, len(segments), seriesNumber)
			if err != nil {
				fmt.Println(err)
				return
			}

			segmentFilePath := filepath.Join("ts", fmt.Sprintf("%s_%s.ts", seriesNumber, filepath.Base(segment)))
			err = os.WriteFile(segmentFilePath, segmentData, 0644)
			if err != nil {
				fmt.Printf("Ошибка при записи сегмента %s: %v\n", segmentFilePath, err)
				return
			}
			fmt.Printf("Сегмент %s успешно скачан и сохранен как %s\n", segment, segmentFilePath)
		}(i, segment)
	}
}

func main() {
	// Создание директории для сохранения итоговых MP4 файлов
	if _, err := os.Stat("film"); os.IsNotExist(err) {
		os.Mkdir("film", os.ModePerm)
	}
	if _, err := os.Stat("ts"); os.IsNotExist(err) {
		os.Mkdir("ts", os.ModePerm)
	}

	// Чтение ссылок из файла
	file, err := os.Open("downloads.txt")
	if err != nil {
		fmt.Printf("Ошибка при открытии файла downloads.txt: %v\n", err)
		return
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	var lines []string
	for scanner.Scan() {
		lines = append(lines, scanner.Text())
	}
	if err := scanner.Err(); err != nil {
		fmt.Printf("Ошибка при чтении файла downloads.txt: %v\n", err)
		return
	}

	// Обработка каждой ссылки
	for index, line := range lines {
		parts := strings.Split(line, " ")
		url := parts[0]
		seriesNumber := parts[1]

		// Замена обратных слэшей на прямые
		url = strings.ReplaceAll(url, "\\", "/")

		m3u8FilePath := filepath.Join("film", seriesNumber+".m3u8")
		mp4FilePath := filepath.Join("film", seriesNumber+".mp4")

		// Скачивание m3u8 файла
		fmt.Printf("Скачивание m3u8 файла для серии %s...\n", seriesNumber)
		err := downloadM3u8(url, m3u8FilePath)
		if err != nil {
			fmt.Println(err)
			continue
		}

		// Чтение ссылок на сегменты из m3u8 файла
		segments, err := parseM3u8(m3u8FilePath)
		if err != nil {
			fmt.Println(err)
			continue
		}

		baseURL := strings.TrimRight(url, filepath.Base(url)) // Получаем базовый URL

		startSeriesTime := time.Now()

		// Создание файла filelist.txt
		filelist, err := os.Create("filelist.txt")
		if err != nil {
			fmt.Printf("Ошибка при создании файла filelist.txt: %v\n", err)
			continue
		}
		defer filelist.Close()

		var wg sync.WaitGroup
		semaphore := make(chan struct{}, maxConcurrentDownloads)

		// Многопоточное скачивание сегментов
		wg.Add(1)
		go downloadSegmentsConcurrently(baseURL, segments, seriesNumber, &wg, semaphore)

		wg.Wait()

		// Выполнение команды ffmpeg
		cmd := exec.Command("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "filelist.txt", "-c", "copy", mp4FilePath)
		var out bytes.Buffer
		cmd.Stdout = &out
		cmd.Stderr = &out
		err = cmd.Run()
		if err != nil {
			fmt.Printf("Ошибка при конвертации: %v\n", out.String())
		} else {
			fmt.Printf("Конвертация завершена: %s\n", mp4FilePath)
		}

		// Удаление временного m3u8 файла и сегментов
		os.Remove(m3u8FilePath)
		for _, segment := range segments {
			segmentFilePath := filepath.Join("ts", fmt.Sprintf("%s_%s.ts", seriesNumber, filepath.Base(segment)))
			os.Remove(segmentFilePath)
		}
		os.Remove("filelist.txt") // Удаление временного файла filelist.txt

		// Вывод информации о завершенной загрузке
		elapsedSeriesTime := time.Since(startSeriesTime).Seconds()
		remainingFiles := len(lines) - index - 1
		fmt.Printf("Завершена загрузка: %s. Осталось %d файлов. Общее время: %.2f секунд.\n", mp4FilePath, remainingFiles, elapsedSeriesTime)
	}
}
