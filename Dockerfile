# SmartDeployAgent の完全版イメージ

# ── Stage 1: Builder (依存ライブラリのビルド) ──
FROM python:3.12-slim AS builder
WORKDIR /app

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# ビルドツールインストール
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
 && rm -rf /var/lib/apt/lists/*

# 依存パッケージのホイール作成
COPY ./requirements.txt .
RUN pip install --upgrade pip \
 && pip wheel --wheel-dir /wheels -r requirements.txt


# ── Stage 2: Runner (実行用軽量イメージ) ──
FROM python:3.12-slim AS runner
WORKDIR /app

# 1. 必須ツールとセキュリティ監査ツールのインストール
# - docker-ce-cli: ホストのDockerデーモン操作用
# - git: リポジトリのClone用
# - hadolint: Dockerfileのベストプラクティス監査用
# - trivy: 脆弱性と秘密情報スキャン用
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    lsb-release \
    ca-certificates \
    git \
    wget \
 && mkdir -p /etc/apt/keyrings \
 # Docker公式GPG鍵とリポジトリの追加
 && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
 && echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
    $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
 && apt-get update \
 && apt-get install -y docker-ce-cli \
 # --- Hadolint (Linter) のインストール ---
 && wget -O /bin/hadolint https://github.com/hadolint/hadolint/releases/download/v2.12.0/hadolint-Linux-x86_64 \
 && chmod +x /bin/hadolint \
 # --- Trivy (Scanner) のインストール ---
 && curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin \
 # --------------------------------------
 && rm -rf /var/lib/apt/lists/*

# 2. Pythonライブラリのインストール
COPY --from=builder /wheels /wheels
COPY ./requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
 && rm -rf /wheels

# 3. アプリケーションコードの配置
COPY src /app/src

# 環境変数
ENV PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONPATH=/app/src

# 実行コマンド
ENTRYPOINT ["python", "src/server.py"]