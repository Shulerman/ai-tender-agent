# AI Tender Agent — Architecture

## 1. Application entry point

Основной файл: `app/main.py`.

Приложение создаётся через FastAPI:

- title: AI Tender Agent;
- description: Tender monitoring and analysis system;
- version: 0.1.0.

Зависимость базы данных передаётся через `get_db()`, который открывает `SessionLocal` и закрывает сессию после выполнения запроса.

## 2. API

### Служебные маршруты
- `GET /` — информация о приложении.
- `GET /health` — проверка состояния приложения.

### Документы
- `POST /documents/upload` — загрузка документа и извлечение текста.

В `main.py` используются отдельные обработчики:
- `app/documents/pdf_reader.py`;
- `app/documents/docx_reader.py`;
- `app/documents/doc_reader.py`;
- `app/documents/html_reader.py`.

Хранение файлов организовано через `app/documents/storage.py`.

### Анализ
- `POST /analysis/technical`;
- `POST /analysis/legal`;
- `POST /analysis/full`.

Используемые сервисы:
- `app/ai/technical_analyst.py`;
- `app/ai/legal_analyst.py`;
- `app/ai/full_analyst.py`.

### Тендеры
- `POST /tenders` — создание тендера;
- `GET /tenders` — список тендеров;
- `PATCH /tenders/{tender_id}` — обновление тендера.

Модели и сервисы:
- `app/tenders/models.py`;
- `app/tenders/service.py`.

### Коммерческий модуль
- `POST /commercial/imports/excel/preview` — предварительный анализ Excel-прайса;
- `POST /commercial/imports/excel` — импорт прайса поставщика;
- `GET /commercial/products/search` — поиск товаров;
- `GET /commercial/imports/{import_id}/unmatched` — строки импорта, требующие сопоставления;
- `POST /commercial/imports/{import_id}/rows/{row_id}/match` — ручное сопоставление с товаром каталога.

## 3. Application modules

### `app/ai`
- `gemini.py` — интеграция с Gemini;
- `technical_analyst.py` — технический анализ;
- `legal_analyst.py` — юридический анализ;
- `full_analyst.py` — объединённый анализ;
- `technical_models.py` — модели технического анализа;
- `legal_models.py` — модели юридического анализа;
- `evidence_validator.py` — проверка доказательств;
- `evidence_relevance_validator.py` — проверка релевантности доказательств.

### `app/documents`
- `storage.py`;
- `pdf_reader.py`;
- `docx_reader.py`;
- `doc_reader.py`;
- `html_reader.py`.

### `app/legal_knowledge`
- `models.py`;
- `article_parser.py`;
- `service.py`;
- `version_checker.py`.

### `app/commercial`
- `models.py`;
- `calculator.py`;
- `service.py`;
- `excel_importer.py`;
- `import_service.py`;
- `unit_normalizer.py` — нормализация единиц измерения и преобразование по правилам товара;
- `quantity_parser.py` — разбор количества из строк прайс-листа.

### `app/tenders`
- `models.py`;
- `service.py`.

## 4. Database

Основной модуль: `app/database.py`.

Используются:
- SQLAlchemy ORM;
- `create_engine`;
- `sessionmaker`;
- `declarative_base`;
- Pydantic Settings.

Обязательные параметры:
- `DATABASE_URL`;
- `POSTGRES_PASSWORD`.

Настройки загружаются также из `.env`.

В `database.py` определены модели тендеров и правовых знаний. Коммерческие ORM-модели находятся отдельно в `app/commercial/models.py`.

## 5. Excel import flow

Предварительный просмотр:
1. API принимает файл.
2. Проверяет расширение XLSX/XLSM.
3. Временно сохраняет содержимое.
4. Вызывает `inspect_price_list`.
5. Возвращает структуру книги и предлагаемое сопоставление.
6. Удаляет временный файл.

Импорт:
1. Проверяет существование поставщика.
2. Проверяет имя и расширение файла.
3. Читает JSON-сопоставление столбцов.
4. Вычисляет SHA-256 исходного файла.
5. Сохраняет файл в `data/commercial/price_lists/` в отдельном каталоге.
6. Вызывает `import_price_list`.
7. При ошибке удаляет каталог неуспешного импорта.

Ручное сопоставление:
1. Проверяется импорт.
2. Проверяется принадлежность строки этому импорту.
3. Проверяется статус строки.
4. Проверяется существование товара каталога.
5. Проверяется наличие цены.
6. Вызывается `match_import_row`.

## 6. Testing

Тесты находятся в `tests/`.

Полный запуск:
`.\run_tests.ps1`

Скрипт:
- временно задаёт тестовые переменные окружения;
- использует SQLite `ci_test.db`;
- запускает подготовку тестовой БД;
- выполняет `compileall`;
- запускает pytest;
- восстанавливает прежние значения окружения.

Не удалять `ci_test.db` без отдельного согласования.

## 7. Architecture rules

- API-слой не должен содержать всю бизнес-логику.
- Сложную логику размещать в профильных сервисах.
- Не смешивать коммерческий модуль, анализ тендеров и правовые знания без необходимости.
- Сохранять происхождение импортированных данных.
- Изменения моделей БД сопровождать тестами.
- Не менять публичные API-контракты без проверки влияния на существующие тесты и потребителей.
