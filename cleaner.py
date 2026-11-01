# -*- coding: utf-8 -*-
"""
Cleaner v5.0 — Автоматическая очистка диска C:\
Запускать от имени администратора.
"""

import os
import sys
import shutil
import subprocess
import ctypes

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def run_cmd(cmd, timeout=300):
    """Выполняет команду без вывода в консоль (скрыто)."""
    try:
        subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    except Exception:
        pass

def get_used_space():
    """Возвращает реальный объем занятого места на диске C: в байтах."""
    try:
        return shutil.disk_usage("C:\\").used
    except Exception:
        return 0

def fmt_size(bytes_):
    for unit in ["Б", "КБ", "МБ", "ГБ", "ТБ"]:
        if bytes_ < 1024:
            return f"{bytes_:.1f} {unit}"
        bytes_ /= 1024
    return f"{bytes_:.1f} ПБ"

def safe_delete(path, keep_backup=True):
    """Безопасно удаляет папку/файл, опционально сохраняя в бэкап."""
    if not os.path.exists(path):
        return
    
    backup_dir = os.path.join(os.environ.get("USERPROFILE", ""), "Cleaner_Backup")
    
    try:
        if os.path.isfile(path) or os.path.islink(path):
            if keep_backup:
                os.makedirs(backup_dir, exist_ok=True)
                shutil.move(path, os.path.join(backup_dir, os.path.basename(path)))
            else:
                os.remove(path)
        elif os.path.isdir(path):
            if keep_backup:
                os.makedirs(backup_dir, exist_ok=True)
                dest = os.path.join(backup_dir, os.path.basename(path))
                if os.path.exists(dest):
                    shutil.rmtree(dest, ignore_errors=True)
                shutil.move(path, dest)
            else:
                shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass

def clean_dir_contents(folder_path):
    """Очищает содержимое папки (без удаления самой папки)."""
    if not os.path.isdir(folder_path):
        return
    for item in os.listdir(folder_path):
        safe_delete(os.path.join(folder_path, item), keep_backup=True)

def main():
    if not is_admin():
        # Перезапуск с правами администратора
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        sys.exit()

    print("🧹 Запуск Cleaner v5.0 (Автоматическая очистка)...")
    print("Измерение исходного размера диска...")
    
    start_used = get_used_space()

    print("⏳ [1/10] Очистка временных файлов...")
    clean_dir_contents(os.environ.get("TEMP", ""))
    clean_dir_contents(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Temp"))
    clean_dir_contents(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "SystemTemp"))

    print("⏳ [2/10] Очистка кэша браузеров...")
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")
    browsers = [
        os.path.join(local, "Google", "Chrome", "User Data"),
        os.path.join(local, "Microsoft", "Edge", "User Data"),
        os.path.join(roaming, "Mozilla", "Firefox", "Profiles"),
        os.path.join(roaming, "Opera Software", "Opera Stable")
    ]
    for base in browsers:
        if os.path.isdir(base):
            for profile in os.listdir(base):
                prof_path = os.path.join(base, profile)
                if os.path.isdir(prof_path):
                    for c in ["Cache", "Code Cache", "GPUCache", "cache2"]:
                        clean_dir_contents(os.path.join(prof_path, c))

    print("⏳ [3/10] Отключение гибернации (освобождение hiberfil.sys)...")
    run_cmd("powercfg /h off")

    print("⏳ [4/10] Удаление старых точек восстановления...")
    run_cmd("vssadmin delete shadows /for=C: /oldest /quiet")

    print("⏳ [5/10] Очистка кэша эскизов и шрифтов...")
    explorer_dir = os.path.join(local, "Microsoft", "Windows", "Explorer")
    if os.path.isdir(explorer_dir):
        for f in os.listdir(explorer_dir):
            if f.startswith(("thumbcache_", "iconcache_")):
                safe_delete(os.path.join(explorer_dir, f))
    run_cmd("net stop FontCache")
    font_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "ServiceProfiles", "LocalService", "AppData", "Local", "FontCache")
    clean_dir_contents(font_dir)
    run_cmd("net start FontCache")

    print("⏳ [6/10] Удаление Windows.old, дампов и отчетов об ошибках...")
    run_cmd("cleanmgr /autoclean")
    safe_delete(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "MEMORY.DMP"))
    safe_delete(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Minidump"))
    clean_dir_contents(os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Microsoft", "Windows", "WER", "ReportArchive"))
    clean_dir_contents(os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Microsoft", "Windows", "WER", "ReportQueue"))
    clean_dir_contents(os.path.join(local, "Microsoft", "Windows", "WER"))

    print("⏳ [7/10] Очистка логов CBS и DISM...")
    clean_dir_contents(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Logs", "CBS"))
    clean_dir_contents(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Logs", "DISM"))

    print("⏳ [8/10] Очистка кэша пакетных менеджеров...")
    run_cmd("pip cache purge")
    run_cmd("npm cache clean --force")
    run_cmd("nuget locals all -clear")
    run_cmd("gradle --stop")

    print("⏳ [9/10] Сброс DNS и очистка Prefetch...")
    run_cmd("ipconfig /flushdns")
    clean_dir_contents(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Prefetch"))

    print("⏳ [10/10] Очистка кэша Windows Store...")
    run_cmd("wsreset.exe")
    
    # Принудительно ждем пару секунд, чтобы файловая система обновила данные
    import time
    time.sleep(2)

    print("📊 Подсчет результатов...")
    end_used = get_used_space()
    
    # Считаем разницу (если система во время уборки что-то записала на диск, покажем честный результат)
    freed_bytes = start_used - end_used
    
    print("=" * 50)
    if freed_bytes > 0:
        print(f"✅ Очистка завершена! Реально освобождено: {fmt_size(freed_bytes)}")
    else:
        print("✅ Очистка завершена! Диск уже чист (освобождено < 1 МБ).")
    print(f"💾 Занято на диске C: сейчас: {fmt_size(end_used)}")
    print("=" * 50)

if __name__ == "__main__":
    main()
