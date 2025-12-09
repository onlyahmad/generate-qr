import qrcode
import pandas as pd
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
import logging

MAX_WORKERS = 8

logging.basicConfig(
    filename='generate.log',
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)

def clean_number(value):
    return re.sub(r'\D', '', value)

def valid_number(value, length):
    return value.isdigit() and len(value) == length

def generate_qr(row, base_folder):
    nik = clean_number(str(row["NO IDENTITAS"]))
    no_kk = clean_number(str(row["NOMOR KK"]))
    nama = str(row["NAMA LENGKAP"]).replace(" ", "_")
    qr_value = str(row["KODE QR"])

    if not valid_number(nik, 16):
        return ("invalid", f"Invalid NIK: {nik}")

    if not valid_number(no_kk, 16):
        return ("invalid", f"Invalid KK: {no_kk}")

    kec = str(row.get("KECAMATAN", "Kecamatan")).replace(" ", "_")
    kel = str(row.get("KELURAHAN", "Kelurahan")).replace(" ", "_")

    folder = os.path.join(base_folder, kec, kel)
    os.makedirs(folder, exist_ok=True)

    filename = f"{nik}-{no_kk}-{nama}.png"
    filepath = os.path.join(folder, filename)

    if os.path.exists(filepath):
        return ("skip", filename)

    qr = qrcode.QRCode(
        version=3,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_value)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    width, height = img.size
    img = img.resize((width * 6, height * 6), Image.LANCZOS)
    img.save(filepath, quality=100)

    return ("ok", filename)

def run_generate(file_path, output_folder):
    if file_path.endswith(".xlsx") or file_path.endswith(".xls"):
        df = pd.read_excel(file_path)
    elif file_path.endswith(".csv"):
        df = pd.read_csv(file_path)
    else:
        raise Exception("Format file tidak didukung")

    required = {"NO IDENTITAS", "NOMOR KK", "NAMA LENGKAP", "KODE QR"}
    missing = required - set(df.columns)
    if missing:
        raise Exception(f"Kolom wajib hilang: {missing}")

    rows = [row for _, row in df.iterrows()]
    os.makedirs(output_folder, exist_ok=True)

    result = {"generated": 0, "skipped": 0, "invalid": 0, "errors": []}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(generate_qr, row, output_folder) for row in rows]
        for fut in as_completed(futures):
            status, msg = fut.result()
            if status == "ok":
                result["generated"] += 1
            elif status == "skip":
                result["skipped"] += 1
            elif status == "invalid":
                result["invalid"] += 1
            else:
                result["errors"].append(msg)

    # Create ZIP file
    import shutil
    shutil.make_archive(output_folder, 'zip', output_folder)
    result["zip_filename"] = f"{os.path.basename(output_folder)}.zip"

    return result
