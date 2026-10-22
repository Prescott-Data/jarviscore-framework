ARG PY=3.12
FROM python:${PY}-slim

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends bubblewrap git \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m tester
USER tester
WORKDIR /home/tester/app
ENV VIRTUAL_ENV=/home/tester/venv PATH=/home/tester/venv/bin:$PATH
RUN python -m venv /home/tester/venv && pip install -q --upgrade pip setuptools wheel

# Dependencies only, cached until pyproject.toml changes; source is streamed in at run time.
COPY --chown=tester pyproject.toml README.md ./
RUN mkdir jarviscore && touch jarviscore/__init__.py \
    && pip install -q ".[dev]" \
    && pip uninstall -y -q jarviscore-framework \
    && rm -rf jarviscore build *.egg-info
