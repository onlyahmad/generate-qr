package service

import (
	"archive/zip"
	"encoding/csv"
	"fmt"
	"image"
	"image/color"
	"image/draw"
	"image/png"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"

	"github.com/skip2/go-qrcode"
	"github.com/xuri/excelize/v2"
)

type Result struct {
	Generated   int      `json:"generated"`
	Skipped     int      `json:"skipped"`
	Invalid     int      `json:"invalid"`
	Errors      []string `json:"errors"`
	ZipFilename string   `json:"zip_filename"`
}

func SanitizeFilename(name string) string {
	reg := regexp.MustCompile(`[^a-zA-Z0-9._-]`)
	name = reg.ReplaceAllString(name, "_")
	return strings.Trim(name, "_")
}

func SanitizeFolder(name string) string {
	reg := regexp.MustCompile(`[^a-zA-Z0-9_-]`)
	name = reg.ReplaceAllString(name, "_")
	return strings.Trim(name, "_")
}

func CleanNumber(value string) string {
	reg := regexp.MustCompile(`\D`)
	return reg.ReplaceAllString(value, "")
}

func GenerateQR(row map[string]string, baseFolder string) (string, string) {
    nikRaw := row["NO IDENTITAS"]
    kkRaw := row["NOMOR KK"]
    nik := CleanNumber(nikRaw)
    noKK := CleanNumber(kkRaw)
    nama := SanitizeFilename(strings.ReplaceAll(row["NAMA LENGKAP"], " ", "_"))
    qrValue := strings.TrimSpace(row["KODE QR"])

    if len(nik) != 16 {
        return "invalid", fmt.Sprintf("Invalid NIK: %s", nik)
    }
    if len(noKK) != 16 {
        return "invalid", fmt.Sprintf("Invalid KK: %s", noKK)
    }

    kec := SanitizeFolder(row["KECAMATAN"])
    if kec == "" {
        kec = "Kecamatan"
    }
    kel := SanitizeFolder(row["KELURAHAN"])
    if kel == "" {
        kel = "Kelurahan"
    }

    folder := filepath.Join(baseFolder, kec, kel)
    if err := os.MkdirAll(folder, 0755); err != nil {
        return "error", fmt.Sprintf("Failed to create dir: %v", err)
    }

    filename := SanitizeFilename(fmt.Sprintf("%s-%s-%s.png", nik, noKK, nama))
    outPath := filepath.Join(folder, filename)

    if _, err := os.Stat(outPath); err == nil {
        return "skip", filename
    }

    if len(qrValue) > 500 {
        return "invalid", "QR content too long"
    }

    // Create QR matrix
    qr, err := qrcode.New(qrValue, qrcode.Highest)
    if err != nil {
        return "error", fmt.Sprintf("Failed to create QR: %v", err)
    }
    qr.DisableBorder = true // kita handle quiet zone secara manual

    matrix := qr.Bitmap()
    modules := len(matrix)

    // === QR STYLE EXACT MATCH LIKE EXAMPLE ===
    border := 4                // QR quiet zone per ISO
    scale := 64                // pixel per module (high resolution)
    finalSize := (modules + border*2) * scale

    img := image.NewRGBA(image.Rect(0, 0, finalSize, finalSize))

    // pure white background
    draw.Draw(img, img.Bounds(), &image.Uniform{color.White}, image.Point{}, draw.Src)

    // draw QR blocks
    for y := 0; y < modules; y++ {
        for x := 0; x < modules; x++ {
            if matrix[y][x] {
                px := (x + border) * scale
                py := (y + border) * scale
                rect := image.Rect(px, py, px+scale, py+scale)
                draw.Draw(img, rect, &image.Uniform{color.Black}, image.Point{}, draw.Src)
            }
        }
    }

    // Save PNG (lossless)
    outFile, err := os.Create(outPath)
    if err != nil {
        return "error", fmt.Sprintf("Failed to save: %v", err)
    }
    defer outFile.Close()

    encoder := png.Encoder{
        CompressionLevel: png.BestCompression,
    }
    if err := encoder.Encode(outFile, img); err != nil {
        return "error", fmt.Sprintf("PNG encode error: %v", err)
    }

    return "ok", filename
}



func RunGenerate(filePath string, outputFolder string) (*Result, error) {
	var rows []map[string]string
	var err error

	ext := strings.ToLower(filepath.Ext(filePath))
	if ext == ".xlsx" || ext == ".xls" {
		rows, err = readExcel(filePath)
	} else if ext == ".csv" {
		rows, err = readCSV(filePath)
	} else {
		return nil, fmt.Errorf("unsupported file format: %s", ext)
	}

	if err != nil {
		return nil, err
	}

	if err := os.MkdirAll(outputFolder, 0755); err != nil {
		return nil, err
	}

	result := &Result{Errors: []string{}}
	var wg sync.WaitGroup
	var mu sync.Mutex
	sem := make(chan struct{}, 6) // Max workers

	for _, row := range rows {
		wg.Add(1)
		sem <- struct{}{}
		go func(r map[string]string) {
			defer wg.Done()
			defer func() { <-sem }()

			status, msg := GenerateQR(r, outputFolder)
			mu.Lock()
			switch status {
			case "ok":
				result.Generated++
			case "skip":
				result.Skipped++
			case "invalid":
				result.Invalid++
			case "error":
				result.Errors = append(result.Errors, msg)
			}
			mu.Unlock()
		}(row)
	}
	wg.Wait()

	// Zip the output
	zipFilename := filepath.Base(outputFolder) + ".zip"
	// Ensure zip is created in the parent directory of outputFolder
	zipPath := filepath.Join(filepath.Dir(outputFolder), zipFilename)
	
	if err := zipFolder(outputFolder, zipPath); err != nil {
		return nil, fmt.Errorf("failed to zip: %v", err)
	}
	result.ZipFilename = zipFilename

	return result, nil
}

func readExcel(filePath string) ([]map[string]string, error) {
	f, err := excelize.OpenFile(filePath)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	sheet := f.GetSheetName(0)
	rows, err := f.GetRows(sheet)
	if err != nil {
		return nil, err
	}

	if len(rows) < 2 {
		return nil, fmt.Errorf("empty excel file")
	}

	headers := rows[0]
	var result []map[string]string
	for _, row := range rows[1:] {
		data := make(map[string]string)
		for i, cell := range row {
			if i < len(headers) {
				data[headers[i]] = cell
			}
		}
		result = append(result, data)
	}
	return result, nil
}

func readCSV(filePath string) ([]map[string]string, error) {
	f, err := os.Open(filePath)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	r := csv.NewReader(f)
	headers, err := r.Read()
	if err != nil {
		return nil, err
	}

	var result []map[string]string
	for {
		record, err := r.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			continue
		}
		data := make(map[string]string)
		for i, cell := range record {
			if i < len(headers) {
				data[headers[i]] = cell
			}
		}
		result = append(result, data)
	}
	return result, nil
}

func zipFolder(source, target string) error {
	zipfile, err := os.Create(target)
	if err != nil {
		return err
	}
	defer zipfile.Close()

	archive := zip.NewWriter(zipfile)
	defer archive.Close()

	return filepath.Walk(source, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}

		header, err := zip.FileInfoHeader(info)
		if err != nil {
			return err
		}

		header.Name, err = filepath.Rel(filepath.Dir(source), path)
		if err != nil {
			return err
		}

		if info.IsDir() {
			header.Name += "/"
		} else {
			header.Method = zip.Deflate
		}

		writer, err := archive.CreateHeader(header)
		if err != nil {
			return err
		}

		if info.IsDir() {
			return nil
		}

		file, err := os.Open(path)
		if err != nil {
			return err
		}
		defer file.Close()
		_, err = io.Copy(writer, file)
		return err
	})
}
