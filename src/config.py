from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # AWS設定 (自動読み込みされるが明示も可)
    AWS_REGION: str = "us-east-1"
    
    # Bedrockモデル設定
    LLM_MODEL_ID: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"
    EMBED_MODEL_ID: str = "amazon.titan-embed-text-v2:0"

    # パス設定
    WORK_DIR: Path = Path("/app/__output__/work_dir")
    RULES_DIR: Path = Path("/app/src/security_rules")
    
    # FinOps設定
    MAX_MONTHLY_BUDGET: float = 20.0
    
    # 制御設定
    MAX_RETRIES: int = 3

settings = Settings()