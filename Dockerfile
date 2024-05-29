FROM python:3.12-slim-bullseye

WORKDIR /code

RUN pip install uv --no-cache-dir
 
COPY ./requirements.txt /code/requirements.txt

RUN uv pip install --no-cache --system -r /code/requirements.txt

COPY ./app /code/app

EXPOSE 8080

CMD ["python3", "-OO", "-m", "fastapi_cli", "run", "app/main.py", "--port", "8080"]