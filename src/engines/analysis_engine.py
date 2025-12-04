import shutil
from pathlib import Path
from git import Repo
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings as LlamaSettings
from llama_index.llms.bedrock import Bedrock
from llama_index.embeddings.bedrock import BedrockEmbedding
from config import settings

class AnalysisEngine:
    def __init__(self):
        self._initialize_llm()
        self.rules_index = self._load_rules_index()

    def _initialize_llm(self):
        """Claude 3.5 Sonnet (API) + Local Embedding"""
        print(f"🧠 Initializing AI Brain: [ Claude 3.5 Sonnet ]")
        
        if not settings.ANTHROPIC_API_KEY:
            print("⚠️ ANTHROPIC_API_KEY not found. Please set it in env vars.")
            return

        try:
            # LLM: Claude 3.5 Sonnet
            LlamaSettings.llm = Bedrock(
                model=settings.LLM_MODEL,
                api_key=settings.ANTHROPIC_API_KEY
            )
            # ベクトル埋め込み: AWS Bedrock Embedding
            LlamaSettings.embed_model = BedrockEmbedding(
                model_name="amazon.titan-embed-text-v2:0"
            )
        except Exception as e:
            print(f"❌ AI Init Failed: {e}")

    def _load_rules_index(self):
        if not settings.RULES_DIR.exists(): return None
        documents = SimpleDirectoryReader(str(settings.RULES_DIR), recursive=True).load_data()
        return VectorStoreIndex.from_documents(documents) if documents else None

    def clone_repository(self, repo_url: str) -> Path:
        if settings.WORK_DIR.exists(): shutil.rmtree(settings.WORK_DIR)
        settings.WORK_DIR.mkdir(parents=True, exist_ok=True)
        print(f"📥 Cloning {repo_url}...")
        Repo.clone_from(repo_url, settings.WORK_DIR)
        return settings.WORK_DIR

    def analyze_context(self, project_path: Path) -> dict:
        print("🧠 Analyzing source code...")
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
        print(f"🧐 Detected Stack: {stack_info}")

        # ルール検索
        security_context = "Standard best practices."
        if self.rules_index:
            nodes = self.rules_index.as_retriever(similarity_top_k=3).retrieve(f"security requirements for {stack_info}")
            security_context = "\n".join([n.get_content() for n in nodes])

        return {"stack_summary": stack_info, "security_context": security_context}