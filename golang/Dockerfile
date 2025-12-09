# Build stage
FROM docker.io/library/golang:1.24-alpine AS builder

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN go build -o main .

# Final stage
FROM alpine:latest

WORKDIR /app

COPY --from=builder /app/main .
COPY --from=builder /app/views ./views

# Create directories
RUN mkdir -p uploads qr_output && chmod 777 uploads qr_output

EXPOSE 5001

CMD ["./main"]
