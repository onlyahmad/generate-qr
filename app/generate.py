# generate.py (enterprise-hardened)
import qrcode
import pandas as pd
import os
import re
import io
import time
import json
import shutil
import zipfile
import hashlib
import hmac
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
import logging
import html

# ===== CONFIG (dapat di-set via environment) =====
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "6"))
MAX_FILE_SIZE_BYTES = int(os.environ.get("MAX_FILE_SIZE_BYTES", str(50 * 1024 * 1024)))  # 50 MB
REQUIRE_SIGNATURE = os.environ.get("REQUIRE_SIGNATURE", "0") == "1"
SIGNATURE_SECRET = os.environ.get("SIGNATURE_SECRET", "")
RATE_LIMIT_DELAY_SECONDS = float(os.environ.get("RATE_LIMIT_DELAY_SECONDS", "0.01"))  # small per-task delay
AUDIT_LOG_PATH = os.environ.get("AUDIT_LOG_PATH", "/tmp/generate_audit.jsonl")
APP_LOG_PATH = os.environ.get("APP_LOG_PATH", "/tmp/generate.log")
MAX_QR_CONTENT_LENGTH = int(os.environ.get("MAX_QR_CONTENT_LENGTH", "500"))
# ==================================================

# ===== LOGGING =====
logging.basicConfig(
    filename=APP_LOG_PATH,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
# ===================

# ===== Helper security utilities =====
def sanitize_filename(name: str) -> str:
    name = re.sub(r'[^a-zA-Z0-9._-]', '_', name)
    return name.strip("_") or "file"

def sanitize_folder(name: str) -> str:
    name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    return name.strip("_") or "folder"

def clean_number(value: str) -> str:
    return re.sub(r'\D', '', value)

def valid_number(value: str, length: int) -> bool:
    return value.isdigit() and len(value) == length

def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()

def hmac_verify_filepath(file_path: str, signature: str, secret: str) -> bool:
    # compute HMAC-SHA256 over file bytes
    h = hmac.new(secret.encode('utf-8'), digestmod=hashlib.sha256)
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    computed = h.hexdigest()
    return hmac.compare_digest(computed, signature)

def audit_write(entry: dict):
    try:
        with open(AUDIT_LOG_PATH, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logging.error(f"Failed to write audit log: {e}")

# ===== QR generation (thread-safe & rate-limited per task) =====
def generate_qr(row_idx: int, row, base_folder: str):
    """
    Process a single row and return tuple (status, message).
    Also write a JSON audit line per-row (without leaking raw NIK/KK).
    """
    # very small rate-limit per worker to avoid spikes to filesystem
    if RATE_LIMIT_DELAY_SECONDS > 0:
        time.sleep(RATE_LIMIT_DELAY_SECONDS)

    try:
        nik_raw = str(row["NO IDENTITAS"])
        kk_raw = str(row["NOMOR KK"])
        nik = clean_number(nik_raw)
        no_kk = clean_number(kk_raw)
        nama = sanitize_filename(str(row["NAMA LENGKAP"]).replace(" ", "_"))
        qr_value = html.escape(str(row["KODE QR"]).strip())

        # audit skeleton (non-sensitive)
        audit = {
            "ts": time.time(),
            "row_idx": row_idx,
            "nik_hash": sha256_hex(nik) if nik else None,
            "kk_hash": sha256_hex(no_kk) if no_kk else None,
            "action": None,
            "message": None
        }

        if not valid_number(nik, 16):
            audit["action"] = "invalid"
            audit["message"] = "invalid_nik"
            audit_write(audit)
            return ("invalid", f"Invalid NIK: {nik}")

        if not valid_number(no_kk, 16):
            audit["action"] = "invalid"
            audit["message"] = "invalid_kk"
            audit_write(audit)
            return ("invalid", f"Invalid KK: {no_kk}")

        kec = sanitize_folder(str(row.get("KECAMATAN", "Kecamatan")))
        kel = sanitize_folder(str(row.get("KELURAHAN", "Kelurahan")))

        folder = os.path.join(base_folder, kec, kel)
        # hard check: output must remain inside base_folder
        if not os.path.abspath(folder).startswith(os.path.abspath(base_folder)):
            audit["action"] = "blocked"
            audit["message"] = "directory_traversal_detected"
            audit_write(audit)
            logging.error(f"Blocked directory traversal attempt: {folder}")
            return ("error", "Illegal folder path detected")

        os.makedirs(folder, exist_ok=True)

        filename = sanitize_filename(f"{nik}-{no_kk}-{nama}.png")
        filepath = os.path.join(folder, filename)

        if not os.path.abspath(filepath).startswith(os.path.abspath(base_folder)):
            audit["action"] = "blocked"
            audit["message"] = "file_escape_detected"
            audit_write(audit)
            logging.error(f"Blocked file escape attempt: {filepath}")
            return ("error", "Illegal file path detected")

        if os.path.exists(filepath):
            audit["action"] = "skip"
            audit["message"] = "exists"
            audit_write(audit)
            logging.info(f"SKIP: {filename} sudah ada.")
            return ("skip", filename)

        if len(qr_value) > MAX_QR_CONTENT_LENGTH:
            audit["action"] = "invalid"
            audit["message"] = "qr_content_too_long"
            audit_write(audit)
            return ("invalid", "QR content too long")

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

        # write image safely (atomic write pattern)
        tmp_fp = filepath + ".tmp"
        img.save(tmp_fp, format="PNG", quality=100)
        os.replace(tmp_fp, filepath)

        audit["action"] = "ok"
        audit["message"] = filename
        audit_write(audit)
        logging.info(f"OK: {filename} berhasil dibuat.")
        return ("ok", filename)

    except Exception as e:
        logging.error(f"ERROR saat membuat QR (row {row_idx}): {e}")
        audit = {
            "ts": time.time(),
            "row_idx": row_idx,
            "action": "error",
            "message": str(e)
        }
        audit_write(audit)
        return ("error", str(e))


# ===== File validation helpers =====
def validate_input_file(file_path: str):
    # existence & size
    if not os.path.exists(file_path):
        raise Exception("File input tidak ditemukan")
    size = os.path.getsize(file_path)
    if size == 0:
        raise Exception("File kosong")
    if size > MAX_FILE_SIZE_BYTES:
        raise Exception("File terlalu besar")

    # extension-based checks
    lower = file_path.lower()
    if lower.endswith(".xlsx") or lower.endswith(".xls"):
        # xlsx is a zip archive of xml files; quick check with zipfile
        if not zipfile.is_zipfile(file_path):
            raise Exception("File Excel tidak valid")
    elif lower.endswith(".csv"):
        # try to open as text with a small sample to ensure it's textual
        try:
            with open(file_path, "r", encoding="utf-8", errors="strict") as fh:
                fh.read(2048)
        except Exception:
            # try latin-1 as fallback
            try:
                with open(file_path, "r", encoding="latin-1", errors="strict") as fh:
                    fh.read(2048)
            except Exception:
                raise Exception("CSV tidak tampak sebagai text yang valid")
    else:
        raise Exception("Format file tidak didukung atau berbahaya")


# ===== Public API function =====
def run_generate(file_path: str, output_folder: str, signature: str = None):
    """
    Main runner.
    - file_path: path to input file on host (will be sandboxed)
    - output_folder: directory where PNGs will be written
    - signature: optional HMAC-SHA256 hex string to verify file integrity (only required if REQUIRE_SIGNATURE=1)
    """
    # basic sanitasi path
    if ".." in file_path or ".." in output_folder:
        raise Exception("Path tidak valid")

    # file size / type checks
    validate_input_file(file_path)

    # signature verification if required
    if REQUIRE_SIGNATURE:
        if not signature:
            raise Exception("Signature required but tidak diberikan")
        if not SIGNATURE_SECRET:
            raise Exception("Server tidak dikonfigurasi dengan SIGNATURE_SECRET")
        if not hmac_verify_filepath(file_path, signature, SIGNATURE_SECRET):
            raise Exception("Signature file tidak valid")

    # sandboxed processing dir
    with tempfile.TemporaryDirectory(prefix="generate_sandbox_") as tmpdir:
        # copy input file to sandbox for safe processing
        sandbox_file = os.path.join(tmpdir, "input" + os.path.splitext(file_path)[1])
        shutil.copyfile(file_path, sandbox_file)

        # read dataframe from sandbox file
        lower = sandbox_file.lower()
        if lower.endswith(".xlsx") or lower.endswith(".xls"):
            df = pd.read_excel(sandbox_file)
        elif lower.endswith(".csv"):
            # read as text with fallback encoding detection (utf-8 then latin-1)
            try:
                df = pd.read_csv(sandbox_file, encoding="utf-8")
            except Exception:
                df = pd.read_csv(sandbox_file, encoding="latin-1")
        else:
            raise Exception("Format file tidak didukung")

        required = {"NO IDENTITAS", "NOMOR KK", "NAMA LENGKAP", "KODE QR"}
        missing = required - set(df.columns)
        if missing:
            raise Exception(f"Kolom wajib hilang: {missing}")

        # ensure output dir exists and is absolute
        os.makedirs(output_folder, exist_ok=True)
        output_folder = os.path.abspath(output_folder)

        rows = list(df.itertuples(index=False, name=None))
        # convert rows to dict-like for backward compatibility with old code
        # but we need column names
        cols = list(df.columns)

        result = {"generated": 0, "skipped": 0, "invalid": 0, "errors": []}

        # worker submission: keep index for audit mapping
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = []
            for idx, row_tuple in enumerate(rows):
                row_dict = {cols[i]: row_tuple[i] for i in range(len(cols))}
                futures.append(executor.submit(generate_qr, idx, row_dict, output_folder))

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

        # Create ZIP hasil (name sanitized)
        # safe_zip_base = sanitize_filename(os.path.basename(output_folder))
        # Use output_folder as base to ensure it is created in the parent dir (OUTPUT_BASE)
        zip_path = shutil.make_archive(output_folder, 'zip', output_folder)
        result["zip_filename"] = os.path.basename(zip_path)

        logging.info(f"SELESAI. Hasil: {result}")
        audit_write({"ts": time.time(), "action": "finished", "result": result})
        return result
