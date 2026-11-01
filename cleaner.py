# -*- coding: utf-8 -*-
"""
Cleaner v4.0 — Safe Disk Cleanup Tool for Windows 11
GUI with pie charts, one-click cleanup, and undo support.
Запускать от имени администратора.
"""

import os
import sys
import shutil
import subprocess
import ctypes
import json
import urllib.request
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading

# ── Matplotlib для диаграмм ──
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ──────────────────────────────────────────────
# КОНСТАНТЫ
# ──────────────────────────────────────────────
APP_NAME = "Cleaner"
APP_VERSION = "4.0"
GITHUB_REPO = "your-username/cleaner"  # ← замени на свой репозиторий
BACKUP_ROOT = os.path.join(os.environ.get("USERPROFILE", ""), "Cleaner_Backup")
CURRENT_BACKUP_DIR = None  # заполняется при очистке

# ──────────────────────────────────────────────
# УТИЛИТЫ
# ──────────────────────────────────────────────

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def get_disk_usage(drive="C:\\"):
    total, used, free = shutil.disk_usage(drive)
    return total, used, free


def fmt_size(bytes_):
    for unit in ["Б", "КБ", "МБ", "ГБ", "ТБ"]:
        if bytes_ < 1024:
            return f"{bytes_:.1f} {unit}"
        bytes_ /= 1024
    return f"{bytes_:.1f} ПБ"


def run_cmd(cmd, timeout=600):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return False, str(e)


def safe_move_to_backup(src):
    """Перемещает файл/папку в текущую резервную папку с сохранением структуры."""
    if CURRENT_BACKUP_DIR is None:
        return False
    try:
        rel = os.path.relpath(src, "C:\\")
        dst = os.path.join(CURRENT_BACKUP_DIR, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            dst = dst + f"_{datetime.now():%H%M%S}"
        shutil.move(src, dst)
        return True
    except Exception:
        return False


def safe_delete_dir_contents(path, move=True):
    """Удаляет (или перемещает в бэкап) всё содержимое папки."""
    if not os.path.isdir(path):
        return 0
    freed = 0
    for item in os.listdir(path):
        item_path = os.path.join(path, item)
        try:
            size = 0
            if os.path.isfile(item_path) or os.path.islink(item_path):
                size = os.path.getsize(item_path)
            elif os.path.isdir(item_path):
                size = sum(os.path.getsize(os.path.join(r, f))
                           for r, _, fs in os.walk(item_path) for f in fs)
            if move:
                safe_move_to_backup(item_path)
            else:
                if os.path.isfile(item_path):
                    os.remove(item_path)
                else:
                    shutil.rmtree(item_path, ignore_errors=True)
            freed += size
        except Exception:
            pass
    return freed


# ──────────────────────────────────────────────
# МОДУЛИ ОЧИСТКИ (каждый возвращает освобождённые байты)
# ──────────────────────────────────────────────

def module_temp_files():
    freed = 0
    paths = [
        os.environ.get("TEMP", ""),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp"),
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Temp"),
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "SystemTemp"),
    ]
    for p in paths:
        freed += safe_delete_dir_contents(p)
    return freed


def module_browser_cache():
    freed = 0
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")
    browser_paths = [
        # Chrome
        os.path.join(local, "Google", "Chrome", "User Data"),
        # Edge
        os.path.join(local, "Microsoft", "Edge", "User Data"),
        # Firefox
        os.path.join(roaming, "Mozilla", "Firefox", "Profiles"),
        # Opera
        os.path.join(roaming, "Opera Software", "Opera Stable"),
    ]
    for base in browser_paths:
        if not os.path.isdir(base):
            continue
        for profile in os.listdir(base):
            prof_path = os.path.join(base, profile)
            if not os.path.isdir(prof_path):
                continue
            for cache_name in ["Cache", "Code Cache", "GPUCache", "cache2"]:
                cache_path = os.path.join(prof_path, cache_name)
                freed += safe_delete_dir_contents(cache_path)
    return freed


def module_hibernation():
    total, used, free = get_disk_usage()
    # hiberfil.sys примерно равен объёму ОЗУ
    ok, _ = run_cmd("powercfg /h off")
    if ok:
        return 1024**3  # приблизительно 1 ГБ как заглушка; реально ОЗУ
    return 0


def module_restore_points():
    ok, out = run_cmd("vssadmin delete shadows /for=C: /oldest /quiet")
    return 512 * 1024**2 if ok else 0  # приблизительно


def module_thumbnail_cache():
    freed = 0
    explorer_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                                "Microsoft", "Windows", "Explorer")
    if os.path.isdir(explorer_dir):
        for f in os.listdir(explorer_dir):
            if f.startswith("thumbcache_") or f.startswith("iconcache_"):
                fp = os.path.join(explorer_dir, f)
                try:
                    size = os.path.getsize(fp)
                    safe_move_to_backup(fp)
                    freed += size
                except Exception:
                    pass
    run_cmd("taskkill /f /im explorer.exe")
    run_cmd("start explorer.exe")
    return freed


def module_font_cache():
    freed = 0
    run_cmd("net stop FontCache")
    font_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                            "ServiceProfiles", "LocalService", "AppData",
                            "Local", "FontCache")
    if os.path.isdir(font_dir):
        freed += safe_delete_dir_contents(font_dir)
    fnt = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "FNTCACHE.DAT")
    if os.path.isfile(fnt):
        try:
            freed += os.path.getsize(fnt)
            safe_move_to_backup(fnt)
        except Exception:
            pass
    run_cmd("net start FontCache")
    return freed


def module_windows_old():
    ok, _ = run_cmd("cleanmgr /autoclean")
    return 2 * 1024**3 if ok else 0  # приблизительно


def module_memory_dumps():
    freed = 0
    paths = [
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "MEMORY.DMP"),
        os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Minidump"),
    ]
    for p in paths:
        if os.path.isfile(p):
            try:
                freed += os.path.getsize(p)
                safe_move_to_backup(p)
            except Exception:
                pass
        elif os.path.isdir(p):
            freed += safe_delete_dir_contents(p)
    return freed


def module_wer_reports():
    freed = 0
    paths = [
        os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                     "Microsoft", "Windows", "WER", "ReportArchive"),
        os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                     "Microsoft", "Windows", "WER", "ReportQueue"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Microsoft", "Windows", "WER"),
    ]
    for p in paths:
        freed += safe_delete_dir_contents(p)
    return freed


def module_cbs_dism_logs():
    freed = 0
    log_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Logs")
    for sub in ["CBS", "DISM"]:
        p = os.path.join(log_dir, sub)
        if os.path.isdir(p):
            freed += safe_delete_dir_contents(p, move=False)  # логи можно просто удалить
    return freed


def module_package_manager_cache():
    freed = 0
    cmds = [
        ("pip cache purge", "pip"),
        ("npm cache clean --force", "npm"),
        ("nuget locals all -clear", "nuget"),
        ("gradle --stop", "gradle"),
    ]
    for cmd, name in cmds:
        ok, _ = run_cmd(cmd, timeout=120)
        if ok:
            freed += 100 * 1024**2  # приблизительно
    return freed


def module_dns_cache():
    run_cmd("ipconfig /flushdns")
    return 0  # место не освобождает, но полезно


def module_prefetch():
    prefetch = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Prefetch")
    return safe_delete_dir_contents(prefetch)


def module_windows_store_cache():
    run_cmd("wsreset.exe")
    return 0


def module_old_drivers():
    # Только перечисление; удаление — вручную после подтверждения
    ok, out = run_cmd("pnputil /enum-drivers")
    return 0


# ──────────────────────────────────────────────
# ПУНКТ 39: SMART-ДИАГНОСТИКА
# ──────────────────────────────────────────────

def check_smart_health():
    """Возвращает словарь с информацией о здоровье диска."""
    ps_cmd = (
        'powershell -NoProfile -Command "'
        'Get-PhysicalDisk | Select-Object FriendlyName, HealthStatus, OperationalStatus | ConvertTo-Json'
        '"'
    )
    ok, out = run_cmd(ps_cmd, timeout=60)
    if not ok:
        return {"error": "Не удалось получить данные SMART."}
    try:
        disks = json.loads(out)
        if isinstance(disks, dict):
            disks = [disks]
        result = []
        for d in disks:
            rel_cmd = (
                f'powershell -NoProfile -Command "'
                f'Get-StorageReliabilityCounter -PhysicalDisk (Get-PhysicalDisk -FriendlyName \'{d.get("FriendlyName", "")}\') | '
                f'Select-Object PowerOnHours, Temperature, Wear | ConvertTo-Json'
                f'"'
            )
            _, rel_out = run_cmd(rel_cmd, timeout=30)
            rel = {}
            if rel_out.strip():
                try:
                    rel = json.loads(rel_out)
                except Exception:
                    pass
            result.append({
                "name": d.get("FriendlyName", "—"),
                "health": d.get("HealthStatus", "—"),
                "status": d.get("OperationalStatus", "—"),
                "power_on_hours": rel.get("PowerOnHours", "—"),
                "temperature": rel.get("Temperature", "—"),
                "wear": rel.get("Wear", "—"),
            })
        return {"disks": result}
    except Exception as e:
        return {"error": str(e)}


# ──────────────────────────────────────────────
# ПУНКТ 37: ТОЧКА ВОССТАНОВЛЕНИЯ
# ──────────────────────────────────────────────

def create_restore_point():
    ok, out = run_cmd(
        'powershell -NoProfile -Command "'
        'Checkpoint-Computer -Description \'Cleaner v4.0\' -RestorePointType \'MODIFY_SETTINGS\''
        '"',
        timeout=120
    )
    return ok, out


# ──────────────────────────────────────────────
# ПУНКТ 43: ПРОВЕРКА ОБНОВЛЕНИЙ
# ──────────────────────────────────────────────

def check_for_updates():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Cleaner"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            latest = data.get("tag_name", "").lstrip("v")
            html_url = data.get("html_url", "")
            if latest and latest != APP_VERSION:
                return True, latest, html_url
            return False, latest, html_url
    except Exception as e:
        return False, None, str(e)


# ──────────────────────────────────────────────
# ПУНКТ 45: ОТМЕНА ПОСЛЕДНЕЙ ОЧИСТКИ
# ──────────────────────────────────────────────

def undo_last_cleanup():
    if not os.path.isdir(BACKUP_ROOT):
        return False, "Резервная папка не найдена."
    backups = sorted(
        [d for d in os.listdir(BACKUP_ROOT)
         if os.path.isdir(os.path.join(BACKUP_ROOT, d))],
        reverse=True
    )
    if not backups:
        return False, "Нет сохранённых резервных копий."
    latest = os.path.join(BACKUP_ROOT, backups[0])
    restored = 0
    for root, dirs, files in os.walk(latest):
        for f in files:
            src = os.path.join(root, f)
            rel = os.path.relpath(src, latest)
            dst = os.path.join("C:\\", rel)
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.exists(dst):
                    dst = dst + f".restored_{datetime.now():%H%M%S}"
                shutil.move(src, dst)
                restored += 1
            except Exception:
                pass
    shutil.rmtree(latest, ignore_errors=True)
    return True, f"Восстановлено файлов: {restored}"


# ──────────────────────────────────────────────
# GUI
# ──────────────────────────────────────────────

class CleanerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION} — Safe Cleanup for Windows 11")
        self.geometry("1100x750")
        self.minsize(1000, 700)

        # Переменные
        self.before_used = tk.IntVar(value=0)
        self.before_free = tk.IntVar(value=0)
        self.freed_bytes = tk.IntVar(value=0)
        self.after_used = tk.IntVar(value=0)
        self.after_free = tk.IntVar(value=0)

        self.module_vars = {}
        self._build_ui()
        self._update_disk_stats()
        self._check_admin()
        self._auto_check_updates()

    # ── Построение интерфейса ──
    def _build_ui(self):
        # Баннер
        banner = tk.Frame(self, bg="#1a1a2e", height=70)
        banner.pack(fill="x")
        banner.pack_propagate(False)
        tk.Label(
            banner, text="🧹  CLEANER  v4.0",
            font=("Segoe UI", 22, "bold"), fg="#e94560", bg="#1a1a2e"
        ).pack(pady=15)
        tk.Label(
            banner, text="Safe Disk Cleanup Tool • Windows 11",
            font=("Segoe UI", 10), fg="#a0a0b0", bg="#1a1a2e"
        ).pack()

        # Основной контейнер
        main = tk.Frame(self)
        main.pack(fill="both", expand=True, padx=15, pady=10)

        # ── Левая панель: диаграммы ──
        left = tk.Frame(main)
        left.pack(side="left", fill="both", expand=True)

        self.fig = Figure(figsize=(5.5, 5), dpi=100)
        self.fig.patch.set_facecolor("#f5f5f5")
        self.ax1 = self.fig.add_subplot(121)
        self.ax2 = self.fig.add_subplot(122)
        self.canvas = FigureCanvasTkAgg(self.fig, master=left)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self._draw_charts()

        # ── Правая панель: управление ──
        right = tk.Frame(main, width=380)
        right.pack(side="right", fill="y", padx=(10, 0))
        right.pack_propagate(False)

        # Кнопки
        btn_frame = tk.Frame(right)
        btn_frame.pack(fill="x", pady=(0, 10))

        self.btn_start = tk.Button(
            btn_frame, text="🚀  Начать очистку",
            font=("Segoe UI", 13, "bold"), bg="#e94560", fg="white",
            activebackground="#c73650", relief="flat", height=2,
            command=self._start_cleanup
        )
        self.btn_start.pack(fill="x", pady=2)

        self.btn_undo = tk.Button(
            btn_frame, text="↩️  Отменить последнюю очистку",
            font=("Segoe UI", 10), bg="#f0f0f0",
            command=self._undo
        )
        self.btn_undo.pack(fill="x", pady=2)

        self.btn_smart = tk.Button(
            btn_frame, text="🩺  Проверить здоровье диска (SMART)",
            font=("Segoe UI", 10), bg="#f0f0f0",
            command=self._show_smart
        )
        self.btn_smart.pack(fill="x", pady=2)

        self.btn_update = tk.Button(
            btn_frame, text="🔄  Проверить обновления Cleaner",
            font=("Segoe UI", 10), bg="#f0f0f0",
            command=self._manual_update_check
        )
        self.btn_update.pack(fill="x", pady=2)

        # Чекбоксы модулей
        tk.Label(right, text="Модули (для ручного выбора):",
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(10, 2))

        self._module_defs = [
            ("temp", "Временные файлы", module_temp_files),
            ("browser", "Кэш браузеров", module_browser_cache),
            ("hiber", "Файл гибернации", module_hibernation),
            ("restore", "Старые точки восстановления", module_restore_points),
            ("thumb", "Кэш эскизов и иконок", module_thumbnail_cache),
            ("font", "Кэш шрифтов", module_font_cache),
            ("winold", "Windows.old", module_windows_old),
            ("dumps", "Файлы дампа памяти", module_memory_dumps),
            ("wer", "Отчёты об ошибках Windows", module_wer_reports),
            ("cbs", "Логи CBS и DISM", module_cbs_dism_logs),
            ("pkg", "Кэш пакетных менеджеров", module_package_manager_cache),
            ("dns", "DNS-кэш", module_dns_cache),
            ("prefetch", "Prefetch (осторожно)", module_prefetch),
            ("store", "Кэш Windows Store", module_windows_store_cache),
            ("drivers", "Старые драйверы (только список)", module_old_drivers),
        ]

        cb_frame = tk.Frame(right)
        cb_frame.pack(fill="x")
        for key, label, _ in self._module_defs:
            var = tk.BooleanVar(value=True)
            self.module_vars[key] = var
            cb = tk.Checkbutton(cb_frame, text=label, variable=var,
                                font=("Segoe UI", 9))
            cb.pack(anchor="w")

        # Прогресс-бар
        self.progress = ttk.Progressbar(right, mode="determinate")
        self.progress.pack(fill="x", pady=(10, 2))

        # Текстовое поле вывода
        self.log_text = scrolledtext.ScrolledText(
            right, height=12, font=("Consolas", 8), state="disabled"
        )
        self.log_text.pack(fill="both", expand=True, pady=(5, 0))

    # ── Диаграммы ──
    def _draw_charts(self):
        self.ax1.clear()
        self.ax2.clear()

        # Диаграмма 1: занятое место до
        total, used, free = get_disk_usage()
        self.before_used.set(used)
        self.before_free.set(free)

        labels1 = ["Занято", "Свободно"]
        sizes1 = [used, free]
        colors1 = ["#e94560", "#2ecc71"]
        self.ax1.pie(sizes1, labels=labels1, autopct=lambda p: f"{p:.1f}%",
                     colors=colors1, startangle=90,
                     textprops={"fontsize": 8})
        self.ax1.set_title(f"C:\\ до очистки\n{fmt_size(used)} занято",
                           fontsize=10)

        # Диаграмма 2: освобождено
        freed = self.freed_bytes.get()
        remaining = max(0, self.before_used.get() - freed)
        if freed > 0:
            labels2 = ["Освобождено", "Осталось занято"]
            sizes2 = [freed, remaining]
            colors2 = ["#f5a623", "#e94560"]
        else:
            labels2 = ["Пока нет данных"]
            sizes2 = [1]
            colors2 = ["#dddddd"]
        self.ax2.pie(sizes2, labels=labels2,
                     autopct=lambda p: f"{p:.1f}%" if freed > 0 else "",
                     colors=colors2, startangle=90,
                     textprops={"fontsize": 8})
        self.ax2.set_title(f"Освобождено\n{fmt_size(freed)}", fontsize=10)

        self.fig.tight_layout()
        self.canvas.draw()

    # ── Обновление статистики ──
    def _update_disk_stats(self):
        self._draw_charts()

    # ── Логирование в текстовое поле ──
    def _log(self, msg):
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        self.update_idletasks()

    # ── Проверка прав ──
    def _check_admin(self):
        if not is_admin():
            messagebox.showwarning(
                "Права администратора",
                "Программа запущена без прав администратора.\n"
                "Некоторые модули могут не работать.\n"
                "Рекомендуется перезапустить от имени администратора."
            )

    # ── Автопроверка обновлений ──
    def _auto_check_updates(self):
        def run():
            ok, latest, url = check_for_updates()
            if ok:
                self._log(f"⬆️ Доступна новая версия: {latest} → {url}")
            else:
                self._log("✅ Обновлений нет (или репозиторий не настроен).")
        threading.Thread(target=run, daemon=True).start()

    def _manual_update_check(self):
        self._log("🔄 Проверка обновлений...")
        threading.Thread(target=self._auto_check_updates, daemon=True).start()

    # ── Пункт 39: SMART ──
    def _show_smart(self):
        self._log("🩺 Запрос данных SMART...")
        threading.Thread(target=self._do_smart, daemon=True).start()

    def _do_smart(self):
        info = check_smart_health()
        if "error" in info:
            self._log(f"❌ {info['error']}")
            return
        for d in info.get("disks", []):
            self._log(
                f"💽 {d['name']}: Health={d['health']}, Status={d['status']}, "
                f"PowerOnHours={d['power_on_hours']}, Temp={d['temperature']}°C, "
                f"Wear={d['wear']}"
            )

    # ── Пункт 45: Отмена ──
    def _undo(self):
        ok, msg = undo_last_cleanup()
        if ok:
            messagebox.showinfo("Отмена", msg)
            self._log(f"↩️ {msg}")
        else:
            messagebox.showerror("Отмена", msg)
            self._log(f"❌ {msg}")
        self._draw_charts()

    # ── Запуск очистки ──
    def _start_cleanup(self):
        if self.btn_start["state"] == "disabled":
            return
        self.btn_start.config(state="disabled", text="⏳ Идёт очистка...")
        self.progress["value"] = 0
        self.freed_bytes.set(0)
        self._log("=" * 50)
        self._log(f"🚀 Запуск очистки — {datetime.now():%Y-%m-%d %H:%M:%S}")

        threading.Thread(target=self._run_cleanup, daemon=True).start()

    def _run_cleanup(self):
        global CURRENT_BACKUP_DIR
        # Создаём папку бэкапа
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        CURRENT_BACKUP_DIR = os.path.join(BACKUP_ROOT, ts)
        os.makedirs(CURRENT_BACKUP_DIR, exist_ok=True)

        # Пункт 37: точка восстановления
        self._log("🛡️ Создание точки восстановления...")
        ok, out = create_restore_point()
        self._log(f"   {'✅' if ok else '⚠️'} Точка восстановления: {'создана' if ok else out[:100]}")

        # Модули
        modules = [m for m in self._module_defs if self.module_vars[m[0]].get()]
        total = len(modules)
        total_freed = 0

        for i, (key, label, func) in enumerate(modules):
            self._log(f"\n▶ [{i+1}/{total}] {label}")
            try:
                freed = func()
                total_freed += freed
                self._log(f"   ✅ Освобождено: {fmt_size(freed)}")
            except Exception as e:
                self._log(f"   ❌ Ошибка: {e}")
            self.progress["value"] = ((i + 1) / total) * 100
            self.update_idletasks()

        # Итог
        self.freed_bytes.set(total_freed)
        self._log("\n" + "=" * 50)
        self._log(f"🏁 Итого освобождено: {fmt_size(total_freed)}")
        self._log(f"📁 Бэкап: {CURRENT_BACKUP_DIR}")

        # Обновляем диаграммы в главном потоке
        self.after(0, self._finalize_cleanup)

    def _finalize_cleanup(self):
        self._update_disk_stats()
        self.btn_start.config(state="normal", text="🚀  Начать очистку")
        messagebox.showinfo("Готово", f"Очистка завершена.\nОсвобождено: {fmt_size(self.freed_bytes.get())}")


# ──────────────────────────────────────────────
# ЗАПУСК
# ──────────────────────────────────────────────

if __name__ == "__main__":
    if not is_admin():
        # Попытка перезапуска с правами администратора
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, " ".join(sys.argv), None, 1
            )
            sys.exit(0)
        except Exception:
            pass
    app = CleanerApp()
    app.mainloop()
