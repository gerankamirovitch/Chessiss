# Chessiss

Шахматы для Windows с тренером, который после каждого хода объясняет, как он изменил оценку позиции, какой ход был лучше и почему. Объяснения собираются из анализа Stockfish по шаблонам, без нейросетей и без интернета.

![Объяснение хода](docs/game-explanation.png)

## Что есть

- Игра против Stockfish, уровни 1-20, с разбором каждого хода. Перед ходом можно запросить подсказку: до трёх вариантов с причиной.
- Игра вдвоём за одним компьютером.
- Контроль времени: Bullet, Blitz, Rapid, Classical, своя настройка (минуты и инкремент) или тренировка без таймера. Просрочка времени даёт поражение, а если у соперника нет материала для мата, ничью.
- 600 тактических пазлов: вилка, связка, мат в 1, 2 и 3 хода, выигрыш материала.
- Разбор партии с пометками ходов (отличный, хороший, неточность, ошибка, зевок) и графиком оценки. Партию можно загрузить из PGN.
- История партий с фильтрами, импорт и экспорт PGN.
- Прерванную партию можно продолжить после перезапуска.
- Светлая и тёмная темы.

![Разбор партии](docs/analysis.png)

![Пазл](docs/puzzle.png)

## Скачать

Готовая portable-сборка лежит в [релизе v1.0.0](https://github.com/gerankamirovitch/Chessiss/releases/tag/v1.0.0). Распакуйте архив и запустите `Chessiss\Chessiss.exe`. Установка не нужна, Stockfish внутри. Файл не подписан, поэтому при первом запуске Windows может показать предупреждение.

Партии, пазлы и настройки хранятся в `%LOCALAPPDATA%\Chessiss`. Папку с программой можно заменять, данные останутся.

## Запуск из исходников

Нужны Python 3 и Windows x64.

```powershell
git clone https://github.com/gerankamirovitch/Chessiss.git
cd Chessiss
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\fetch_stockfish.py
.\.venv\Scripts\python.exe main.py
```

`scripts/fetch_stockfish.py` скачивает Stockfish 19 в `~/Downloads`, сверяет SHA-256 и кладёт его в `engines/stockfish/`. Бинарника в репозитории нет. Путь к другому Stockfish можно указать в настройках приложения.

## Тесты

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
```

Тесты, которым нужен движок, пропускаются, если в `engines/stockfish/` нет Stockfish. Полный прогон занимает около пяти минут.

## Сборка

```powershell
.\.venv\Scripts\python.exe scripts\build.py
```

Результат: папка `dist\Chessiss` (PyInstaller, onedir) со Stockfish внутри. Перед сборкой должен быть выполнен `scripts/fetch_stockfish.py`.

## Структура

```text
core/      правила, часы, обёртка над Stockfish, генератор объяснений, PGN
storage/   SQLite: партии, ходы, пазлы, настройки
ui/        окна PySide6, шахматной логики в них нет
net/       пусто, место под сетевой режим
scripts/   загрузка Stockfish, сборка пазлов, сборка exe
data/      puzzles.json
tests/     pytest
```

## Ограничения

- Проверено только на Windows 11 x64. На Windows 10 приложение не запускалось.
- Интерфейс только на русском.
- Если отменить ходы, сделанные до восстановления прерванной партии, потраченное на них время не вернётся.

## Лицензии

Код Chessiss распространяется под GPLv3, текст в файле [LICENSE](LICENSE).

- [Stockfish](https://stockfishchess.org/) 19, GPLv3. Запускается как отдельный процесс по протоколу UCI.
- [python-chess](https://github.com/niklasf/python-chess), GPLv3.
- [PySide6](https://doc.qt.io/qtforpython-6/), LGPLv3.
- Пазлы взяты из [базы Lichess](https://database.lichess.org/#puzzles), CC0.
