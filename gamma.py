import ctypes
import json
import os
import time
from ctypes import wintypes
import platform
from pathlib import Path

# --- Проверка ОС ---
if platform.system() != "Windows":
    raise RuntimeError("Этот способ работает только в Windows.")

# --- Конфигурация ---
CONFIG_PATH = Path.home() / "Desktop" / "gamma_config.json"
DEFAULT_CONFIG = {
    "gamma": 2.0,
    "color_mode": "all",  # "all", "blue"
    "hotkeys": {
        "toggle": "F2",
        "increase": "F3",
        "decrease": "F4",
        "cycle_color": "F5"
    }
}

# --- WinAPI ---
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

DISPLAY_DEVICE_ACTIVE = 0x00000001

class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]

EnumDisplayDevicesW = user32.EnumDisplayDevicesW
CreateDCW = gdi32.CreateDCW
DeleteDC = gdi32.DeleteDC
SetDeviceGammaRamp = gdi32.SetDeviceGammaRamp

# Тип гамма-таблицы
RampArray = (ctypes.c_ushort * 256) * 3

class GammaController:
    def __init__(self):
        self.config = self.load_config()
        self.running = True
        self.current_gamma = self.config["gamma"]
        self.enabled = False  # Всегда выключено при запуске
        self.color_mode = self.config["color_mode"]
        self.last_status = ""
        
    def load_config(self):
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        # Сохраняем только гамму и цветовой режим
        self.config.update({
            "gamma": self.current_gamma,
            "color_mode": self.color_mode
        })
        with open(CONFIG_PATH, 'w') as f:
            json.dump(self.config, f, indent=4)

    def _build_gamma_ramp(self, gamma: float) -> RampArray:
        ramp = RampArray()
        inv = 1.0 / gamma
        
        for i in range(256):
            x = i / 255.0
            y = pow(x, inv)
            v = int(y * 65535 + 0.5)
            v = max(0, min(65535, v))
            
            if self.color_mode == "blue":
                # Только синий канал
                ramp[0][i] = i * 257  # R линейный
                ramp[1][i] = i * 257  # G линейный
                ramp[2][i] = v        # B с гаммой
            else:  # all
                # Все каналы одинаковые
                ramp[0][i] = v
                ramp[1][i] = v
                ramp[2][i] = v
        return ramp

    def _set_ramp_on_all_active_displays(self, ramp: RampArray) -> None:
        i = 0
        any_applied = False
        
        while True:
            dd = DISPLAY_DEVICEW()
            dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
            if not EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
                break
                
            if dd.StateFlags & DISPLAY_DEVICE_ACTIVE:
                hdc = CreateDCW("DISPLAY", dd.DeviceName, None, None)
                if hdc:
                    try:
                        SetDeviceGammaRamp(hdc, ctypes.byref(ramp))
                        any_applied = True
                    finally:
                        DeleteDC(hdc)
            i += 1

        if not any_applied:
            # Фолбэк на основной дисплей
            hdc = user32.GetDC(None)
            if hdc:
                SetDeviceGammaRamp(hdc, ctypes.byref(ramp))
                user32.ReleaseDC(None, hdc)

    def apply_gamma(self):
        if self.enabled:
            ramp = self._build_gamma_ramp(self.current_gamma)
        else:
            ramp = self._build_gamma_ramp(1.0)  # Сброс
        self._set_ramp_on_all_active_displays(ramp)

    def toggle(self):
        self.enabled = not self.enabled
        self.apply_gamma()
        # Не сохраняем состояние вкл/выкл в конфиг
        self.update_display()

    def change_gamma(self, delta: float):
        self.current_gamma = max(0.1, min(4.4, self.current_gamma + delta))  # Макс 4.4
        if self.enabled:
            self.apply_gamma()
        self.save_config()  # Сохраняем только гамму
        self.update_display()

    def cycle_color_mode(self):
        modes = ["all", "blue"]
        current_idx = modes.index(self.color_mode)
        self.color_mode = modes[(current_idx + 1) % len(modes)]
        if self.enabled:
            self.apply_gamma()
        self.save_config()  # Сохраняем только цветовой режим
        self.update_display()

    def get_status_text(self):
        status_color = "🟢 ВКЛ" if self.enabled else "🔴 ВЫКЛ"
        color_mode_text = "Все цвета" if self.color_mode == "all" else "Синий"
        
        return (
            f"Gamma Controller - Работает\n\n"
            f"Текущие настройки:\n"
            f"  Статус: {status_color}\n"
            f"  Гамма: {self.current_gamma:.1f}\n"
            f"  Цвет гаммы: {color_mode_text}\n\n"
            f"Горячие клавиши:\n"
            f"  F2 - Вкл/Выкл\n"
            f"  F3 - Гамма +\n"
            f"  F4 - Гамма -\n"
            f"  F5 - Сменить цвет\n\n"
            f"Для выхода закройте окно"
        )

    def update_display(self):
        new_status = self.get_status_text()
        if new_status != self.last_status:
            os.system('cls' if os.name == 'nt' else 'clear')
            print(new_status)
            self.last_status = new_status

    def reset_gamma(self):
        self.enabled = False
        self.apply_gamma()

def main():
    controller = GammaController()
    
    try:
        # При запуске гамма выключена
        controller.reset_gamma()
        controller.update_display()
        
        # Состояния клавиш для предотвращения повторного срабатывания
        key_states = {
            0x71: False,  # F2
            0x72: False,  # F3  
            0x73: False,  # F4
            0x74: False   # F5
        }
        
        while controller.running:
            # Проверяем горячие клавиши с обработкой нажатия
            for key_code, key_name in [(0x71, "F2"), (0x72, "F3"), (0x73, "F4"), (0x74, "F5")]:
                current_state = user32.GetAsyncKeyState(key_code) & 0x8000
                
                if current_state and not key_states[key_code]:
                    # Клавиша только что нажата
                    if key_code == 0x71:  # F2
                        controller.toggle()
                    elif key_code == 0x72:  # F3
                        controller.change_gamma(0.1)
                    elif key_code == 0x73:  # F4
                        controller.change_gamma(-0.1)
                    elif key_code == 0x74:  # F5
                        controller.cycle_color_mode()
                
                key_states[key_code] = current_state
                
            time.sleep(0.05)  # Небольшая задержка для снижения нагрузки на CPU
            
    except KeyboardInterrupt:
        print("\nЗавершение работы...")
    finally:
        # Восстанавливаем стандартную гамму при выходе
        controller.reset_gamma()
        print("Гамма восстановлена. Выход.")

if __name__ == "__main__":
    main()