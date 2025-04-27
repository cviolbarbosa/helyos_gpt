FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
# RUN  pip3 install --extra-index-url https://alpine-wheels.github.io/index numpy
RUN pip install -r requirements.txt
COPY src src
COPY llm_directives llm_directives
EXPOSE 9333
HEALTHCHECK --interval=30s --timeout=30s --start-period=30s --retries=3 CMD curl -f http://localhost:9333/health || exit 1
ENTRYPOINT ["python", "src/main.py"]


