# One image for the whole project: the Rust measurement tool `itb` and the Python analysis.
# Build:  docker compose build        Run: see docker-compose.yml

FROM rust:1-slim-bookworm AS build
WORKDIR /src
COPY itb/Cargo.toml itb/Cargo.lock ./
# cache the dependency build
RUN mkdir src && echo "fn main() {}" > src/main.rs && cargo build --release --locked && rm -rf src
COPY itb/src ./src
RUN touch src/main.rs && cargo build --release --locked && cargo test --release --locked

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /work
COPY analysis/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY --from=build /src/target/release/itb /usr/local/bin/itb
COPY analysis ./analysis
COPY scripts ./scripts
# data/, figures/, docs/ and keys/ are mounted at run time (docker-compose.yml)
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
CMD ["itb", "--help"]
