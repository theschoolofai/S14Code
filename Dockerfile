FROM python:3.11-slim

RUN pip install uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

EXPOSE 8113

CMD ["uv", "run", "s14code", "serve", "--host", "0.0.0.0"]