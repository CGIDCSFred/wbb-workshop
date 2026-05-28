FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir --trusted-host pypi.org --trusted-host files.pythonhosted.org psycopg2-binary==2.9.9
COPY common.py extract.py load.py run_etl.sh ./
RUN chmod +x run_etl.sh
CMD ["./run_etl.sh"]
