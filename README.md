# Запуск контейнера:
Сборка и запуск:\
***docker build -t questionnaire-app . && docker run --rm -p 8000:8000 questionnaire-app***\
Только запуск:\
 ***docker run --rm -p 8000:8000 questionnaire-app***\
 \
После запуска опросник будет доступен по адресу http://localhost:8000

# Запуск проекта локально без контейнера: 
***python3 app.py***\
После старта в браузере открыть http://localhost:8000/