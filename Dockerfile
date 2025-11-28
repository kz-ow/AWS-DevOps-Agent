# SmartDeployAgent のイメージの作成

# ── Stage 1: Builder (依存ライブラリのビルド) ──
FROM python:3.12-slim AS builder
WORKDIR /app

# pip のパフォーマンスとキャッシュ設定
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# ビルドに必要な最小限のツール (gccなど) をインストール
# ※ pythonライブラリによってはコンパイルが必要なため
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
 && rm -rf /var/lib/apt/lists/*

# requirements.txt をコピーして wheel (バイナリパッケージ) を作成
COPY ./requirements.txt .
RUN pip install --upgrade pip \
 && pip wheel --wheel-dir /wheels -r requirements.txt


# ── Stage 2: Runner (実行用軽量イメージ) ──
FROM python:3.12-slim AS runner
WORKDIR /app

# 1. Docker CLI のインストール
# Agentがホスト側のDockerを操作(docker buildなど)するために必須
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    lsb-release \
    ca-certificates \
 && mkdir -p /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
 && echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
    $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
 && apt-get update \
 && apt-get install -y docker-ce-cli \
 && rm -rf /var/lib/apt/lists/*

# 2. Builderで作った wheel をコピーしてインストール
COPY --from=builder /wheels /wheels
COPY ./requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
 && rm -rf /wheels

# 3. アプリケーションコードを配置
# srcディレクトリごとコピーします
COPY src /app/src

# 【重要: ユーザー権限について】
# このAgentはホスト側のDockerソケット(/var/run/docker.sock)を操作する必要があります．
# 非rootユーザーに切り替えると権限エラー(Permission denied)で動かないケースが多いため，
# 開発用ツールとして確実性を取るために root ユーザーのまま実行します．

# 環境変数設定
# PYTHONUNBUFFERED=1 は MCP通信のために必須
ENV PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# 実行コマンド
# docker run 時に引数なしで実行された場合のデフォルト
ENTRYPOINT ["python", "src/server.py"]