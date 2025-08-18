import os, time

LOG_FOLDER = "logs"
MAX_AGE_DAYS = 7
MAX_SIZE_MB = 5

def cleanup_logs():
    now = time.time()
    for filename in os.listdir(LOG_FOLDER):
        path = os.path.join(LOG_FOLDER, filename)
        if not os.path.isfile(path): continue
        age = now - os.path.getmtime(path)
        size_mb = os.path.getsize(path) / (1024 * 1024)
        if age > MAX_AGE_DAYS * 86400 or size_mb > MAX_SIZE_MB:
            print(f"🧹 Deleting: {filename}")
            os.remove(path)

if __name__ == "__main__":
    cleanup_logs()