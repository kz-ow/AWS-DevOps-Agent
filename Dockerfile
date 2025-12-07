# ── Stage 1: Builder ──
FROM python:3.12-slim AS builder

# 作業ディレクトリ
WORKDIR /app
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1

# ビルドツール
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*

# 依存関係のホイールを事前構築
COPY ./requirements.txt .
RUN pip install --upgrade pip && pip wheel --wheel-dir /wheels -r requirements.txt

# ── Stage 2: Runner ──
FROM python:3.12-slim AS runner
WORKDIR /app

# 基本ツール & Docker CLI & セキュリティツール(RUNをできるだけまとめてイメージ層を減らす)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg lsb-release ca-certificates git wget \
 && mkdir -p /etc/apt/keyrings \
 # Docker CLI
 && curl -fsSL --retry 5 https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
 && apt-get update && apt-get install -y docker-ce-cli \
 # Hadolint
 && wget --tries=5 -O /bin/hadolint https://github.com/hadolint/hadolint/releases/download/v2.12.0/hadolint-Linux-x86_64 && chmod +x /bin/hadolint \
 # Trivy
 && curl -sfL --retry 5 https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin \
 && rm -rf /var/lib/apt/lists/*


# AWS SAM 静的パッケージのインストール（以降テストのためRUNを分離）
RUN curl -L "https://github.com/aws/aws-sam-cli/releases/latest/download/aws-sam-cli-linux-x86_64.zip" -o "aws-sam-cli.zip" \
 && unzip aws-sam-cli.zip -d sam-installation \
 && ./sam-installation/install \
 && rm -rf aws-sam-cli.zip sam-installation \
 && rm -rf /var/lib/apt/lists/*

# IaC静的解析ツールのインストール
RUN pip install cfn-lint checkov

# Pythonパッケージ
COPY --from=builder /wheels /wheels
COPY ./requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt && rm -rf /wheels


# アプリコード
COPY src /app/src
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "src/server.py"]