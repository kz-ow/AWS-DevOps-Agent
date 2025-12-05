from pathlib import Path
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # AWSリージョン（default us-west-1）
    AWS_REGION: str = "us-west-1"
    
    # AWSクレデンシャル (任意: Lambdaデプロイ用)
    # ~/.aws/credentials がある場合に自動的に使用
    HAS_AWS_CREDS: bool = (
        os.path.exists(os.path.expanduser("~/.aws/credentials")) or 
        "AWS_ACCESS_KEY_ID" in os.environ or 
        "AWS_CONTAINER_CREDENTIALS" in os.environ
    )

    LLM_MODEL: str = ""  # LLMモデル名

    GITHUB_TOKEN: str | None = None # GitHub Personal Access Token (任意)

    # ディレクトリ設定
    BASE_DIR: Path = Path(__file__).parent.parent
    WORK_DIR: Path = BASE_DIR / "__output__" / "work_dir"
    RULES_DIR: Path = BASE_DIR / "_rules_"
    
    # 制御設定
    MAX_RETRIES: int = 3

settings = Settings()