FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg

WORKDIR /opt/ypendulum
COPY pyproject.toml README.md LICENSE CHANGELOG.md ./
COPY src ./src
COPY configs ./configs
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

ENTRYPOINT ["ypendulum"]
CMD ["--help"]
