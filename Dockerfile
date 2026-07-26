FROM python:3.9-slim

WORKDIR /data

COPY . /data/

EXPOSE 9290 9291

CMD ["sh", "-c", "python3 /data/grocyscan_app.py"]
