package handlers

import (
	"fmt"
	"generate-code/service"
	"os"
	"path/filepath"
	"strings"

	"github.com/gofiber/fiber/v2"
)

func Index(c *fiber.Ctx) error {
	return c.Render("index", fiber.Map{})
}

func Upload(c *fiber.Ctx) error {
	file, err := c.FormFile("file")
	if err != nil {
		return c.Render("index", fiber.Map{
			"Error": "Tidak ada file diupload.",
		})
	}

	// Validate file size (max 5MB)
	if file.Size > 5*1024*1024 {
		return c.Render("index", fiber.Map{
			"Error": "Ukuran file melebihi batas 5MB.",
		})
	}

	// Validate file extension
	ext := strings.ToLower(filepath.Ext(file.Filename))
	if ext != ".xlsx" && ext != ".xls" && ext != ".csv" {
		return c.Render("index", fiber.Map{
			"Error": "Format file tidak didukung. Harap upload file Excel (.xlsx, .xls) atau CSV (.csv).",
		})
	}

	uploadFolder := os.Getenv("UPLOAD_FOLDER")
	if uploadFolder == "" {
		uploadFolder = "./uploads"
	}
	outputBase := os.Getenv("OUTPUT_BASE")
	if outputBase == "" {
		outputBase = "./qr_output"
	}

	if err := os.MkdirAll(uploadFolder, 0755); err != nil {
		return c.Render("index", fiber.Map{
			"error": fmt.Sprintf("Failed to create upload dir: %v", err),
		})
	}

	filename := service.SanitizeFilename(file.Filename)
	filepathStr := filepath.Join(uploadFolder, filename)

	if err := c.SaveFile(file, filepathStr); err != nil {
		return c.Render("index", fiber.Map{
			"error": fmt.Sprintf("Failed to save file: %v", err),
		})
	}

	importName := strings.TrimSuffix(filename, filepath.Ext(filename))
	outputFolder := filepath.Join(outputBase, importName)

	result, err := service.RunGenerate(filepathStr, outputFolder)
	if err != nil {
		return c.Render("index", fiber.Map{
			"error": err.Error(),
		})
	}

	return c.Render("index", fiber.Map{
		"Result":       result,
		"OutputFolder": outputFolder,
		"ZipFilename":  result.ZipFilename,
	})
}

func Download(c *fiber.Ctx) error {
	filename := c.Params("filename")
	outputBase := os.Getenv("OUTPUT_BASE")
	if outputBase == "" {
		outputBase = "./qr_output"
	}
	filepath := filepath.Join(outputBase, filename)
	return c.Download(filepath)
}
