package main

import (
	"fmt"
	"generate-code/handlers"
	"log"
	"os"

	"github.com/gofiber/fiber/v2"
	"github.com/gofiber/template/html/v2"
)

func main() {
	// Initialize template engine
	engine := html.New("./views", ".html")

	// Initialize Fiber app
	app := fiber.New(fiber.Config{
		Views:     engine,
		BodyLimit: 10 * 1024 * 1024, // 10MB to allow handler to catch >5MB files
	})

	// Static files
	app.Static("/uploads", "./uploads")
	app.Static("/qr_output", "./qr_output")

	// Routes
	app.Get("/", handlers.Index)
	app.Post("/", handlers.Upload)
	app.Get("/download/:filename", handlers.Download)

	// Start server
	port := os.Getenv("PORT")
	if port == "" {
		port = "5001"
	}
	log.Fatal(app.Listen(fmt.Sprintf(":%s", port)))
}
