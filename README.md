# AT89C51RD2 ISP Flasher

Простой Python-инструмент для прошивки микроконтроллеров **AT89C51RD2 / ED2** через UART (встроенный ISP bootloader).

Работает на Linux,(с доработкой на  macOS и Windows). Не требует Java, Wine и устаревших утилит Atmel/Microchip.

## Возможности

- ✅ Чтение сигнатуры и конфигурации (BSB, SBV, Security Level, HW byte)
- ✅ Full Chip Erase
- ✅ Постраничная запись Flash (128 байт) с проверкой эха
- ✅ Верификация после записи
- ✅ Установка/сброс BLJB (Boot Loader Jump Bit)
- ✅ Установка Security Level 2
- ✅ Прогресс-бар и подробный вывод

## Установка

```bash
git clone https://github.com/Vilckins/at89c51rd2-isp.git
cd at89c51rd2-isp

python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

pip install pyserial
```

## Использование

```bash
# Только чтение сигнатуры и конфигурации
./isp.py

# Прошить с верификацией
./isp.py firmware.hex --verify

# Прошить без предварительного стирания
./isp.py firmware.hex --no-erase

# Установить BLJB=0 (загрузчик при старте, удобно для отладки)
./isp.py firmware.hex --bootloader-at-start

# Установить Security Level 2 (НЕОБРАТИМО через ISP!)
./isp.py firmware.hex --security2

# Указать другой порт и скорость
./isp.py firmware.hex -p /dev/ttyUSB1 -b 9600
```

### Параметры командной строки

| Опция | Описание |
|---|---|
| `hexfile` | Путь к Intel HEX файлу прошивки |
| `-p, --port` | Последовательный порт (по умолчанию `/dev/ttyUSB0`) |
| `-b, --baud` | Скорость UART (по умолчанию `115200`) |
| `--no-erase` | Не стирать чип перед записью |
| `--no-sync` | Пропустить синхронизацию |
| `--verify` | Верифицировать после записи |
| `--bootloader-at-start` | BLJB=0: загрузчик при старте |
| `--security2` | Установить Security Level 2 |

## Аппаратное подключение

```
CP2102 / CH340          AT89C51RD2
──────────────          ──────────
TX      ──────────►     P3.0 (RXD)
RX      ◄──────────     P3.1 (TXD)
GND     ──────────      GND
                        VCC = +5V
```

Для входа в режим ISP при сбросе:

- **EA** = HIGH (+5V)
- **PSEN** = LOW через резистор **1 кОм** (не напрямую!)
- **P2.6** = HIGH через резистор **10 кОм**
- **P2.7** = HIGH через резистор **10 кОм**

> ⚠️ **Важно:** UART работает с **2 стоп-битами** (см. даташит AT89C51RD2, стр. 104–105). Скрипт уже настроен соответствующим образом.

## Формат протокола

Инструмент использует встроенный ISP bootloader AT89C51RD2 и общается с ним через **Intel HEX** записи поверх UART:

```
:LL AAAA TT DD...DD CC
```

- `LL` — длина данных
- `AAAA` — адрес
- `TT` — тип записи (`00` = данные, `03` = управление, `05` = чтение)
- `DD...` — данные
- `CC` — контрольная сумма (дополнение до двух)

Скорость автоопределяется загрузчиком по первому символу `U` (0x55). Надёжный диапазон — от 2400 до 115200 бод.

## Требования

- Python 3.8+
- [pyserial](https://pypi.org/project/pyserial/) >= 3.5
- USB-UART адаптер (CP2102, CH340, FT232 и т.п.)

## Известные ограничения

- **Security Level 2** можно сбросить только полным стиранием Full Chip Erase через ISP.
- **Full Chip Erase не может повредить заводской загрузчик** так как он зашит в ROM чипа.
- **Резисторы обязательны.** Прямое подключение PSEN к GND может повредить порт.

## Лицензия

MIT — см. файл [LICENSE](LICENSE).

## Благодарности

Протокол ISP описан в официальном даташите AT89C51RD2/ED2 от Atmel (Microchip).
