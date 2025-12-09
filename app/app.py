from flask import Flask, render_template, request, send_from_directory
import os
from generate import run_generate  # kita buat function run_generate dari kode kamu
from werkzeug.utils import secure_filename

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
OUTPUT_BASE = "qr_output"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_BASE, exist_ok=True)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        file = request.files.get("file")
        if not file:
            return render_template("index.html", error="Tidak ada file diupload.")

        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        # nama folder output mengikuti nama file
        import_name = os.path.splitext(filename)[0]
        output_folder = os.path.join(OUTPUT_BASE, import_name)

        # jalankan generator
        try:
            result = run_generate(filepath, output_folder)
            return render_template("index.html", result=result, output_folder=output_folder, zip_filename=result.get("zip_filename"))
        except Exception as e:
            return render_template("index.html", error=str(e))

    return render_template("index.html")

@app.route("/download/<filename>")
def download_file(filename):
    return send_from_directory(OUTPUT_BASE, filename, as_attachment=True)
    
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
