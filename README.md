# Запуск в контейнере:
Сборка и запуск:\
***docker build -t questionnaire-app . && docker run --rm -p 8000:8000 questionnaire-app***\
Только запуск:\
 ***docker run --rm -p 8000:8000 questionnaire-app***\
 \
После запуска опросник будет доступен по адресу http://localhost:8000

# Запуск проекта локально без контейнера: 
***python3 app.py***\
После запуска опросник будет доступен по адресу http://localhost:8000

# Curl
1. GET / — страница опросника (HTML):\
***curl http://localhost:8000/***
2. GET /questions — список вопросов (JSON):\
***curl http://localhost:8000/questions***
3. POST /answers — отправка ответов:\
***curl -X POST http://localhost:8000/answers \
  -H "Content-Type: application/json" \
  -d '{"answers": [{"question_id": 1, "answer": "Python"}, {"question_id": 2, "answer": "5 лет"}]}'***\
Формат тела запроса: объект с полем answers — непустой список объектов вида {"question_id": <число>, "answer": "<строка>"}.
4. Пример ошибки (пустой список ответов вернёт 400):\
***curl -X POST http://localhost:8000/answers \
  -H "Content-Type: application/json" \
  -d '{"answers": []}'***\
Сервер отвечает JSON-ошибкой: {"error": "Поле 'answers' должно быть непустым списком"}
5. Несуществующий путь (вернёт 404):\
***curl -i http://localhost:8000/unknown***