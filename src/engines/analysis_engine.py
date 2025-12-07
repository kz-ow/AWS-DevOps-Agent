import shutil
import sys
from pathlib import Path
from git import Repo
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings as LlamaSettings
from llama_index.llms.bedrock_converse import BedrockConverse
from llama_index.embeddings.bedrock import BedrockEmbedding
from config import settings

class AnalysisEngine:
    def __init__(self):
        self._initialize_llm()
        self.rules_index = self._load_rules_index()

    def _initialize_llm(self):
        """AWS Bedrock (API) + Local Embedding"""
        print(f"🧠 Initializing AI Brain: [ {settings.LLM_MODEL} ]", file=sys.stderr)

        try:
            # LLMモデル: AWS Bedrock 
            LlamaSettings.llm = BedrockConverse(
                model=settings.LLM_MODEL,
                region_name=settings.AWS_REGION
            )
            # ベクトル埋め込み: AWS Bedrock Embedding
            LlamaSettings.embed_model = BedrockEmbedding(
                model_name="amazon.titan-embed-text-v2:0",
                region_name=settings.AWS_REGION
            )
        except Exception as e:
            print(f"❌ AI Init Failed: {e}", file=sys.stderr)

    def _load_rules_index(self):
        if not settings.RULES_DIR.exists(): return None
        documents = SimpleDirectoryReader(str(settings.RULES_DIR), recursive=True).load_data()
        return VectorStoreIndex.from_documents(documents) if documents else None

    def clone_repository(self, repo_url: str) -> Path:
        if settings.WORK_DIR.exists(): shutil.rmtree(settings.WORK_DIR)
        settings.WORK_DIR.mkdir(parents=True, exist_ok=True)

        final_url = repo_url
        if settings.GITHUB_TOKEN:
            # トークンがある場合（プライベートリポジトリの場合），URLに埋め込む
            # https://github.com/... -> https://<TOKEN>@github.com/...
            if repo_url.startswith("https://"):
                final_url = repo_url.replace("https://", f"https://{settings.GITHUB_TOKEN}@")
                print(f"🔐 Authenticated clone enabled for private repo.", file=sys.stderr)
            else:
                print("⚠️ Warning: GITHUB_TOKEN provided but URL is not HTTPS. Token ignored.", file=sys.stderr)
        
        print(f"📥 Cloning {repo_url}...", file=sys.stderr)
        # ログには生のTokenが出ないように注意しつつ、final_urlでクローン
        try:
            # 実際のクローン処理
            Repo.clone_from(final_url, settings.WORK_DIR)        
        except Exception as e:
            # エラーが発生した場合、メッセージの中にトークンが含まれていないかチェックして隠す
            error_msg = str(e)
            if settings.GITHUB_TOKEN:
                # トークン部分を '***' に置換して隠す
                error_msg = error_msg.replace(settings.GITHUB_TOKEN, "***")
            
            print(f"❌ Clone Failed: {error_msg}", file=sys.stderr)
            raise Exception("Repository clone failed (details in log)") # 詳細を隠して再送出
    
        return settings.WORK_DIR
    
    def analyze_context(self, project_path: Path) -> dict:
        print("🧠 Analyzing source code...", file=sys.stderr)
        # ノイズになるファイルを除外
        documents = SimpleDirectoryReader(
            input_dir=str(project_path), recursive=True, 
            exclude=["*.git*", "*.lock", "node_modules", "__pycache__", "*.png", "*.jpg", ".DS_Store"]
        ).load_data()
        
        index = VectorStoreIndex.from_documents(documents)
        
        # 技術スタックの特定
        stack_info = str(index.as_query_engine().query(
            "Identify the programming language, framework, and entry point file. List key dependencies."
        ))
        print(f"🧐 Detected Stack: {stack_info}", file=sys.stderr)

        # ルール検索
        security_context = "Standard best practices."
        if self.rules_index:
            nodes = self.rules_index.as_retriever(similarity_top_k=3).retrieve(f"security requirements for {stack_info}")
            security_context = "\n".join([n.get_content() for n in nodes])

        return {"stack_summary": stack_info, "security_context": security_context}